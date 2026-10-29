#!/usr/bin/env python3
"""Opt-in DEVELOPMENT host monitor: email on media-cleanup health transitions.

Python stdlib only. Docker is queried through two read-only commands with a
fixed output template; the monitor never starts, stops or recreates anything.
Mail contains fixed text, allowlisted reason codes, validated configuration and
numbers only. Docker diagnostics, probe logs, SMTP errors and credentials never
reach events or mail.
"""
from __future__ import annotations

import collections
import contextlib
import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import smtplib
import socket
import ssl
import stat
import subprocess
import sys
import time
import uuid

PREFIX = 'CLEANUP_ALERT_'
KEYS = ('COMPOSE_PROJECT', 'DOCKER', 'DOCKER_TIMEOUT_SECONDS', 'SMTP_HOST', 'SMTP_PORT',
        'SMTP_SECURITY', 'SMTP_TIMEOUT_SECONDS', 'SMTP_USERNAME', 'SMTP_PASSWORD_FILE',
        'FROM', 'TO', 'FAILURE_THRESHOLD', 'REPEAT_SECONDS', 'STATE_DIRECTORY')
PLACEHOLDER = 'REPLACE_ME'
SERVICE = 'media-cleanup'
OUTPUT_LIMIT = 4096
SECRET_LIMIT = 4096
STATE_LIMIT = 4096
STREAK_LIMIT = 1000000000
MAX_RECIPIENTS = 10
LOOPBACK = {'localhost', '127.0.0.1', '::1'}
ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})+")
HOST = re.compile(r'[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|::1')
DOCKER_STATUSES = {'created', 'running', 'paused', 'restarting', 'removing', 'exited', 'dead'}
HEALTH_STATUSES = {'starting', 'healthy', 'unhealthy'}
# Only these fields leave Docker; .State.Health.Log and Config are never read.
INSPECT_FORMAT = ('{"status":{{json .State.Status}},"health":{{if .State.Health}}'
                  '{{json .State.Health.Status}}{{else}}null{{end}},'
                  '"restarts":{{json .RestartCount}}}')
DESCRIPTIONS = {
    'healthy': 'Docker reports the cleanup progress healthcheck as healthy.',
    'starting': 'Docker still reports the healthcheck as starting; no successful batch yet.',
    'unhealthy': 'Docker reports the cleanup progress healthcheck as unhealthy.',
    'restarting': 'The container is restarting because the runner exited.',
    'not_running': 'The container exists but is not running.',
    'no_healthcheck': 'The running container has no Docker healthcheck.',
    'missing': 'No media-cleanup container exists for the configured Compose project.',
    'ambiguous': 'More than one media-cleanup container matches the configured Compose project.',
    'probe_failed': 'The read-only Docker query failed.',
    'probe_timeout': 'The read-only Docker query timed out.',
    'probe_invalid': 'The read-only Docker query returned unexpected output.',
}
PROBLEMS = set(DESCRIPTIONS) - {'healthy'}
STATE_KEYS = {'version', 'streak', 'reason', 'since', 'alerted_at', 'recovery_pending',
              'checked_at'}
LABELS = {'alert': 'ALERT', 'reminder': 'STILL FAILING', 'recovery': 'RECOVERED',
          'test': 'TEST'}


class ConfigError(Exception):
    def __init__(self, key):
        super().__init__(key)
        self.key = key


class SecretError(Exception):
    pass


class StateError(Exception):
    pass


class Malformed(Exception):
    pass


class Busy(Exception):
    pass


class ScopeChanged(Exception):
    pass


class ProbeError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


Config = collections.namedtuple('Config', (
    'project', 'docker', 'docker_timeout', 'host', 'port', 'security', 'timeout', 'username',
    'password_file', 'sender', 'recipients', 'threshold', 'repeat', 'state_directory'))


def load_config(env):
    def value(key, default=None):
        item = env.get(PREFIX + key, '')
        if item == '':
            if default is None:
                raise ConfigError(key)
            item = default
        # Placeholders and control characters (including CR/LF) never reach mail.
        if PLACEHOLDER in item or not item.isprintable() or len(item) > 1024:
            raise ConfigError(key)
        return item

    def integer(key, default, low, high):
        item = value(key, default)
        if not re.fullmatch(r'[0-9]{1,10}', item) or not low <= int(item) <= high:
            raise ConfigError(key)
        return int(item)

    project = value('COMPOSE_PROJECT')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', project):
        raise ConfigError('COMPOSE_PROJECT')
    docker = value('DOCKER', '/usr/bin/docker')
    if not os.path.isabs(docker):
        raise ConfigError('DOCKER')
    host = value('SMTP_HOST')
    if not HOST.fullmatch(host):
        raise ConfigError('SMTP_HOST')
    security = value('SMTP_SECURITY', 'starttls')
    if security not in ('starttls', 'tls', 'none'):
        raise ConfigError('SMTP_SECURITY')
    username = value('SMTP_USERNAME', '')
    if username and not re.fullmatch(r'[\x21-\x7e]{1,256}', username):
        raise ConfigError('SMTP_USERNAME')
    # Plaintext SMTP is limited to a host-local relay and never carries credentials.
    if security == 'none' and (host not in LOOPBACK or username):
        raise ConfigError('SMTP_SECURITY')
    password_file = value('SMTP_PASSWORD_FILE', '')
    if username and not password_file and env.get('CREDENTIALS_DIRECTORY'):
        password_file = os.path.join(env['CREDENTIALS_DIRECTORY'], 'smtp-password')
    if bool(username) != bool(password_file) or (password_file
                                                  and not os.path.isabs(password_file)):
        raise ConfigError('SMTP_PASSWORD_FILE')
    sender = value('FROM')
    if len(sender) > 254 or not ADDRESS.fullmatch(sender):
        raise ConfigError('FROM')
    recipients = tuple(item.strip() for item in value('TO').split(','))
    if (not 1 <= len(recipients) <= MAX_RECIPIENTS or len(set(recipients)) != len(recipients)
            or any(len(item) > 254 or not ADDRESS.fullmatch(item) for item in recipients)):
        raise ConfigError('TO')
    repeat = integer('REPEAT_SECONDS', '21600', 0, 2592000)
    if 0 < repeat < 60:
        raise ConfigError('REPEAT_SECONDS')
    state_directory = env.get(PREFIX + 'STATE_DIRECTORY') or env.get('STATE_DIRECTORY', '')
    # systemd joins several StateDirectory= entries with ':'; exactly one is supported.
    if (not os.path.isabs(state_directory) or ':' in state_directory
            or PLACEHOLDER in state_directory or not state_directory.isprintable()):
        raise ConfigError('STATE_DIRECTORY')
    return Config(project=project, docker=docker,
                  docker_timeout=integer('DOCKER_TIMEOUT_SECONDS', '15', 1, 300),
                  host=host, port=integer('SMTP_PORT', '587', 1, 65535), security=security,
                  timeout=integer('SMTP_TIMEOUT_SECONDS', '20', 1, 300), username=username,
                  password_file=password_file, sender=sender, recipients=recipients,
                  threshold=integer('FAILURE_THRESHOLD', '2', 1, 100), repeat=repeat,
                  state_directory=state_directory)


def read_secret(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise SecretError from None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise SecretError
        raw = os.read(fd, SECRET_LIMIT + 1)
    except OSError:
        raise SecretError from None
    finally:
        os.close(fd)
    if len(raw) > SECRET_LIMIT:
        raise SecretError
    try:
        password = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise SecretError from None
    password = password.removesuffix('\n').removesuffix('\r')
    if not password or any(character in password for character in '\r\n\0'):
        raise SecretError
    return password


def event(name, outcome, reason, **fields):
    value = {'event': name, 'outcome': outcome, 'reason': reason, 'timestamp': time.time(),
             **fields}
    print(json.dumps(value, separators=(',', ':'), allow_nan=False), flush=True)


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def reject_constant(_name):
    raise ValueError


def loads(raw):
    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)


def fresh(now):
    return {'version': 1, 'streak': 0, 'reason': None, 'since': None, 'alerted_at': None,
            'recovery_pending': False, 'checked_at': now}


def valid_state(value):
    if not isinstance(value, dict) or set(value) != STATE_KEYS:
        return False
    if type(value['version']) is not int or value['version'] != 1:
        return False
    if type(value['streak']) is not int or not 0 <= value['streak'] <= STREAK_LIMIT:
        return False
    if type(value['recovery_pending']) is not bool:
        return False
    reason = value['reason']
    if reason is not None and (type(reason) is not str or reason not in PROBLEMS):
        return False
    for key in ('since', 'alerted_at', 'checked_at'):
        item = value[key]
        if item is not None and (type(item) not in (int, float) or not math.isfinite(item)
                                 or item <= 0):
            return False
    if value['checked_at'] is None:
        return False
    if value['streak'] and (reason is None or value['since'] is None):
        return False
    if value['recovery_pending']:
        return (value['alerted_at'] is not None and not value['streak'] and reason is not None
                and value['since'] is not None)
    if not value['streak']:
        return reason is None and value['since'] is None and value['alerted_at'] is None
    return True


def state_scope(config):
    # Bind delivery suppression to its target and destinations. Credentials are
    # intentionally excluded so rotation cannot reset a correctly tracked incident.
    value = [config.project, config.host, config.port, config.security,
             config.sender, sorted(config.recipients)]
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


class Store:
    def __init__(self, directory, scope):
        self.directory = Path(directory)
        self.scope = scope

    def directory_fd(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            os.close(fd)
            raise StateError
        return fd

    def prepare(self):
        try:
            self.directory.mkdir(mode=0o700)
        except FileExistsError:
            pass

    @contextlib.contextmanager
    def locked(self):
        fd = self.directory_fd()
        try:
            lock = os.open('lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        finally:
            os.close(fd)
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Busy from None
            yield
        finally:
            os.close(lock)

    def load(self):
        fd = self.directory_fd()
        try:
            try:
                source = os.open('state.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=fd)
            except FileNotFoundError:
                return None
        finally:
            os.close(fd)
        with os.fdopen(source, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise StateError
            raw = stream.read(STATE_LIMIT + 1)
        if len(raw) > STATE_LIMIT:
            raise Malformed
        try:
            value = loads(raw)
        except ValueError:
            raise Malformed from None
        if (not isinstance(value, dict) or set(value) != {'version', 'scope', 'incident'}
                or type(value['version']) is not int or value['version'] != 2
                or not isinstance(value['scope'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', value['scope'])
                or not valid_state(value['incident'])):
            raise Malformed
        if value['scope'] != self.scope:
            raise ScopeChanged
        return value['incident']

    def write(self, value):
        fd = self.directory_fd()
        stage = '.state-' + uuid.uuid4().hex
        created = False
        try:
            out = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=fd)
            created = True
            with os.fdopen(out, 'w') as stream:
                json.dump({'version': 2, 'scope': self.scope, 'incident': value}, stream,
                          separators=(',', ':'), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(stage, 'state.json', src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                if created:
                    os.unlink(stage, dir_fd=fd)
            except FileNotFoundError:
                pass
            finally:
                os.close(fd)


def docker(config, arguments):
    environment = {key: item for key, item in os.environ.items()
                   if not key.startswith(PREFIX) and key != 'CREDENTIALS_DIRECTORY'}
    try:
        child = subprocess.run([config.docker, *arguments], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=environment, timeout=config.docker_timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ProbeError('probe_timeout') from None
    except OSError:
        raise ProbeError('probe_failed') from None
    if child.returncode != 0:
        raise ProbeError('probe_failed')
    if len(child.stdout) > OUTPUT_LIMIT:
        raise ProbeError('probe_invalid')
    try:
        return child.stdout.decode('ascii')
    except UnicodeDecodeError:
        raise ProbeError('probe_invalid') from None


def observe(config):
    """Return (reason, restart count or None) from read-only Docker queries."""
    try:
        ids = docker(config, [
            'ps', '--all', '--no-trunc', '--quiet',
            '--filter', f'label=com.docker.compose.project={config.project}',
            '--filter', f'label=com.docker.compose.service={SERVICE}',
            '--filter', 'label=com.docker.compose.oneoff=False']).split()
        if not all(re.fullmatch(r'[0-9a-f]{64}', item) for item in ids):
            return 'probe_invalid', None
        if not ids:
            return 'missing', None
        if len(ids) > 1:
            return 'ambiguous', None
        value = loads(docker(config, ['inspect', '--type', 'container', '--format',
                                      INSPECT_FORMAT, ids[0]]))
    except ProbeError as error:
        return error.reason, None
    except ValueError:
        return 'probe_invalid', None
    if not isinstance(value, dict) or set(value) != {'status', 'health', 'restarts'}:
        return 'probe_invalid', None
    status, health, restarts = value['status'], value['health'], value['restarts']
    if (type(status) is not str or status not in DOCKER_STATUSES
            or (health is not None and (type(health) is not str
                                        or health not in HEALTH_STATUSES))
            or type(restarts) is not int or not 0 <= restarts <= STREAK_LIMIT):
        return 'probe_invalid', None
    if status == 'restarting':
        return 'restarting', restarts
    if status != 'running':
        return 'not_running', restarts
    if health is None:
        return 'no_healthcheck', restarts
    return health, restarts


def evaluate(state, reason, now, config):
    """Return the next state (before delivery) and the notification due, if any."""
    state = {**state, 'checked_at': now}
    if reason == 'healthy':
        if state['alerted_at'] is not None:
            return {**state, 'streak': 0, 'recovery_pending': True}, 'recovery'
        return fresh(now), None
    # A recurrence before recovery was delivered continues the announced incident.
    state['recovery_pending'] = False
    if state['since'] is None:
        state['since'] = now
    state['streak'] = min(state['streak'] + 1, STREAK_LIMIT)
    state['reason'] = reason
    if state['alerted_at'] is None:
        return state, 'alert' if state['streak'] >= config.threshold else None
    elapsed = now - state['alerted_at']
    # A wall-clock rewind makes elapsed negative; prefer a reminder over silence.
    if config.repeat and (elapsed >= config.repeat or elapsed < 0):
        return state, 'reminder'
    return state, None


def utc(value):
    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).strftime(
        '%Y-%m-%dT%H:%M:%SZ')


def hostname():
    return re.sub(r'[^A-Za-z0-9.-]', '?', socket.gethostname())[:64] or 'unknown'


def compose_message(config, kind, state, restarts, now):
    reason = 'healthy' if kind == 'recovery' else state['reason']
    message = EmailMessage()
    # Fixed parts keep every subject below the 78-character folding limit.
    subject = f'[Smokemap DEVELOPMENT] {SERVICE} {LABELS[kind]}'
    message['Subject'] = subject if kind == 'test' else f'{subject}: {reason}'
    message['From'] = config.sender
    message['To'] = ', '.join(config.recipients)
    message['Date'] = formatdate(now, usegmt=True)
    message['Message-ID'] = make_msgid(domain=config.sender.rsplit('@', 1)[1])
    lines = ['Environment: DEVELOPMENT', f'Host: {hostname()}',
             f'Compose project: {config.project}', f'Service: {SERVICE}',
             f'Event: {LABELS[kind]}', f'Checked: {utc(now)}']
    if kind == 'test':
        lines += ['', 'This is an operator-requested delivery test. It does not query',
                  'Docker and says nothing about media-cleanup health.']
    else:
        lines.insert(5, f'Condition: {reason} - {DESCRIPTIONS[reason]}')
        if kind == 'recovery':
            lines += [f'Previous condition: {state["reason"]} - {DESCRIPTIONS[state["reason"]]}',
                      f'Incident first observed: {utc(state["since"])}']
        else:
            lines += [f'Non-healthy checks in a row: {state["streak"]}',
                      f'First observed: {utc(state["since"])}']
        lines.append('Container restarts: '
                     + ('unknown' if restarts is None else str(restarts)))
        compose = f'docker compose --project-name {config.project}'
        lines += ['', 'Operator checks on the DEVELOPMENT host, from the active release checkout:',
                  f'  {compose} ps {SERVICE}',
                  f'  {compose} logs --tail 50 {SERVICE}',
                  f'  {compose} exec -T {SERVICE} python /opt/smokemap-dev-media-cleanup.py health',
                  '', 'Diagnose with the fixed reason codes in docs/DEV_MEDIA_CLEANUP.md.',
                  'Docker unhealthy status does not restart a running worker.']
        if kind != 'recovery':
            lines += [f'Reminders repeat every {config.repeat} seconds while the condition persists.'
                      if config.repeat else 'Reminders are disabled; only recovery is reported.']
    lines += ['', 'This message contains no logs, environment values or credentials.']
    message.set_content('\n'.join(lines) + '\n', cte='7bit')
    return message


def send(config, password, message):
    """Deliver once; return 'sent' only when every recipient is accepted."""
    context = ssl.create_default_context()
    try:
        if config.security == 'tls':
            client = smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout,
                                      context=context)
        else:
            client = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
    except (OSError, smtplib.SMTPException):
        return 'smtp_connect'
    stage = 'smtp_tls'
    try:
        if config.security == 'starttls':
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        stage = 'smtp_auth'
        if config.username:
            client.login(config.username, password)
        stage = 'smtp_send'
        refused = client.send_message(message, config.sender, list(config.recipients))
    except (OSError, smtplib.SMTPException, ValueError):
        return stage
    finally:
        with contextlib.suppress(OSError, smtplib.SMTPException):
            client.quit()
        with contextlib.suppress(OSError):
            client.close()
    return 'smtp_partial' if refused else 'sent'


def load_state(store, now):
    try:
        state = store.load()
    except ScopeChanged:
        event('state', 'reset', 'scope_changed')
        return fresh(now)
    except Malformed:
        event('state', 'reset', 'state_invalid')
        return fresh(now)
    return fresh(now) if state is None else state


def check(config, password, now=None):
    store = Store(config.state_directory, state_scope(config))
    try:
        store.prepare()
        with store.locked():
            now = time.time() if now is None else now
            state = load_state(store, now)
            reason, restarts = observe(config)
            state, kind = evaluate(state, reason, now, config)
            event('check', 'healthy' if reason == 'healthy' else 'problem', reason,
                  streak=state['streak'])
            code = 0
            if kind:
                result = send(config, password, compose_message(config, kind, state,
                                                                restarts, now))
                if result == 'sent':
                    state = fresh(now) if kind == 'recovery' else {**state, 'alerted_at': now}
                    event('notify', result, kind)
                    code = 0
                else:
                    event('notify', 'failure', result, kind=kind)
                    code = 75
            store.write(state)
            return code
    except Busy:
        event('check', 'skipped', 'busy')
        return 75
    except (OSError, StateError):
        event('state', 'failure', 'state_error')
        return 74


def preview(config, now=None):
    """Show the next decision and message; never locks, writes or sends."""
    now = time.time() if now is None else now
    try:
        state = load_state(Store(config.state_directory, state_scope(config)), now)
    except FileNotFoundError:
        state = fresh(now)
    except (OSError, StateError):
        event('state', 'failure', 'state_error')
        return 74
    reason, restarts = observe(config)
    state, kind = evaluate(state, reason, now, config)
    event('preview', kind or 'none', reason, streak=state['streak'])
    if kind:
        print(compose_message(config, kind, state, restarts, now).as_string(), flush=True)
    return 0


def main(argv=None, env=None):
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    if len(argv) != 1 or argv[0] not in ('check', 'preview', 'validate', 'send-test'):
        print('usage: dev-cleanup-alert.py check|preview|validate|send-test', file=sys.stderr)
        return 64
    try:
        config = load_config(env)
    except ConfigError as error:
        event('config', 'failure', 'config_invalid', key=PREFIX + error.key)
        return 64
    try:
        password = read_secret(config.password_file) if config.username else None
    except SecretError:
        event('config', 'failure', 'credential_unavailable')
        return 64
    if argv[0] == 'validate':
        event('config', 'valid', 'ok')
        return 0
    if argv[0] == 'preview':
        return preview(config)
    if argv[0] == 'send-test':
        now = time.time()
        result = send(config, password, compose_message(config, 'test', fresh(now), None, now))
        if result == 'sent':
            event('notify', result, 'test')
            return 0
        event('notify', 'failure', result, kind='test')
        return 75
    return check(config, password)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        # Never let a traceback expose configuration, credentials or Docker data.
        event('monitor', 'failure', 'internal_error')
        sys.exit(70)
