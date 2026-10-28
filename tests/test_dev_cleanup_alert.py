"""Pure stdlib tests: fake Docker CLI and fake SMTP; never network, mail or Docker."""
import ast
import configparser
from contextlib import redirect_stdout
import email
import email.policy
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import smtplib
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts/dev-cleanup-alert.py'
TEMPLATES = ROOT / 'deploy/development/cleanup-alert'
SPEC = importlib.util.spec_from_file_location('dev_cleanup_alert', SCRIPT)
alert = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alert)
SECRET = 'UNTRUSTED-DIAGNOSTIC-must-never-be-emitted'
PASSWORD = 'smtp-PASSWORD-must-never-be-emitted'
NOW = 1800000000.0
CONTAINER = 'a' * 64

FAKE_DOCKER = '''#!{python}
import json, os, sys, time
from pathlib import Path
root = Path(__file__).resolve().parent
leaked = sorted(k for k in os.environ
                if k.startswith('CLEANUP_ALERT_') or k == 'CREDENTIALS_DIRECTORY')
with open(root / 'calls', 'a') as stream:
    stream.write(json.dumps({{'argv': sys.argv[1:], 'leaked': leaked}}) + '\\n')
print({secret!r}, file=sys.stderr, flush=True)
mode = (root / 'mode').read_text()
if mode == 'timeout':
    time.sleep(30)
if mode == 'ps_fail':
    sys.exit(1)
if sys.argv[1] == 'ps':
    if mode == 'missing':
        sys.exit(0)
    if mode == 'ambiguous':
        print('a' * 64)
        print('b' * 64)
    elif mode == 'bad_id':
        print({secret!r})
    else:
        print('a' * 64)
    sys.exit(0)
if mode == 'inspect_fail':
    sys.exit(1)
if mode == 'garbage':
    print({secret!r} + '{{')
elif mode == 'oversize':
    print('x' * 5000)
elif mode == 'non_ascii':
    sys.stdout.buffer.write('{{"status":"runningé"}}'.encode())
elif mode == 'extra':
    print(json.dumps({{'status': 'running', 'health': 'healthy', 'restarts': 0,
                      'env': {secret!r}}}))
elif mode == 'duplicate':
    print('{{"status":"running","status":"running","health":"healthy","restarts":0}}')
elif mode == 'nan':
    print('{{"status":"running","health":"healthy","restarts":NaN}}')
else:
    status, health, restarts = mode.split('/')
    print(json.dumps({{'status': status, 'health': None if health == 'null' else health,
                      'restarts': json.loads(restarts)}}))
'''


def refuse_network(*_args, **_kwargs):
    raise AssertionError('network access attempted by an offline test')


def setUpModule():
    # Any accidental socket, DNS or real SMTP use fails the suite.
    for target, name in ((socket.socket, 'connect'), (socket, 'create_connection'),
                         (socket, 'getaddrinfo'), (smtplib, 'SMTP'), (smtplib, 'SMTP_SSL')):
        patch.object(target, name, refuse_network).start()


def tearDownModule():
    patch.stopall()


class FakeSMTP:
    """Records the SMTP conversation; `fail` names the step that raises."""
    instances = []
    fail = None
    refused = {}
    quit_fails = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls = []
        self.messages = []
        FakeSMTP.instances.append(self)
        if FakeSMTP.fail == 'connect':
            raise ConnectionRefusedError(SECRET)

    def ehlo(self):
        self.calls.append('ehlo')

    def starttls(self, context=None):
        self.calls.append('starttls')
        self.starttls_context = context
        if FakeSMTP.fail == 'starttls':
            raise smtplib.SMTPNotSupportedError(SECRET)

    def login(self, username, password):
        self.calls.append('login')
        self.credentials = (username, password)
        if FakeSMTP.fail == 'login':
            raise smtplib.SMTPAuthenticationError(535, SECRET.encode())

    def send_message(self, message, sender, recipients):
        self.calls.append('send')
        self.messages.append((message, sender, recipients))
        if FakeSMTP.fail == 'send':
            raise smtplib.SMTPRecipientsRefused({recipients[0]: (550, SECRET.encode())})
        return dict(FakeSMTP.refused)

    def quit(self):
        self.calls.append('quit')
        if FakeSMTP.quit_fails:
            raise smtplib.SMTPServerDisconnected(SECRET)

    def close(self):
        self.calls.append('close')


class FakeSMTPSSL(FakeSMTP):
    pass


class Harness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='smokemap-alert-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state_dir = self.root / 'state'
        self.docker = self.root / 'docker'
        self.docker.write_text(FAKE_DOCKER.format(python=sys.executable, secret=SECRET))
        self.docker.chmod(0o700)
        self.mode('running/healthy/0')
        FakeSMTP.instances = []
        FakeSMTP.fail = None
        FakeSMTP.refused = {}
        FakeSMTP.quit_fails = False
        for name, fake in (('SMTP', FakeSMTP), ('SMTP_SSL', FakeSMTPSSL)):
            smtp_patch = patch.object(alert.smtplib, name, fake)
            smtp_patch.start()
            self.addCleanup(smtp_patch.stop)

    def env(self, **overrides):
        values = {'COMPOSE_PROJECT': 'smokemap-dev-r1', 'DOCKER': str(self.docker),
                  'DOCKER_TIMEOUT_SECONDS': '5', 'SMTP_HOST': 'smtp.example.test',
                  'FROM': 'monitor@example.test', 'TO': 'ops@example.test',
                  'STATE_DIRECTORY': str(self.state_dir)}
        values.update(overrides)
        return {alert.PREFIX + key: value for key, value in values.items() if value is not None}

    def config(self, **overrides):
        return alert.load_config(self.env(**overrides))

    def mode(self, value):
        (self.root / 'mode').write_text(value)

    def calls(self):
        path = self.root / 'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def capture(self, function, *args, **kwargs):
        output = io.StringIO()
        with redirect_stdout(output):
            code = function(*args, **kwargs)
        text = output.getvalue()
        for secret in (SECRET, PASSWORD):
            self.assertNotIn(secret, text)
        return code, text

    def events(self, text):
        return [json.loads(line) for line in text.splitlines() if line.startswith('{')]

    def check(self, config, now, password=None):
        code, text = self.capture(alert.check, config, password, now=now)
        return code, self.events(text)

    def sent(self):
        return [message for client in FakeSMTP.instances for message, _, _ in client.messages]

    def secret_file(self, content=PASSWORD + '\n', mode=0o600):
        path = self.root / 'password'
        path.write_text(content)
        path.chmod(mode)
        return path


class ConfigTests(Harness):
    def test_defaults_and_systemd_state_directory(self):
        env = self.env(DOCKER=None, DOCKER_TIMEOUT_SECONDS=None, STATE_DIRECTORY=None)
        config = alert.load_config({**env, 'STATE_DIRECTORY': str(self.state_dir)})
        self.assertEqual(
            (config.docker, config.docker_timeout, config.port, config.security, config.timeout,
             config.threshold, config.repeat, config.recipients, config.username,
             config.password_file, config.state_directory),
            ('/usr/bin/docker', 15, 587, 'starttls', 20, 2, 21600, ('ops@example.test',), '',
             '', str(self.state_dir)))

    def assertRejected(self, key, **overrides):
        with self.assertRaises(alert.ConfigError) as caught:
            self.config(**overrides)
        self.assertEqual(caught.exception.key, key)

    def test_required_values_and_placeholders(self):
        for key in ('COMPOSE_PROJECT', 'SMTP_HOST', 'FROM', 'TO', 'STATE_DIRECTORY'):
            with self.subTest(key=key):
                self.assertRejected(key, **{key: None})
                self.assertRejected(key, **{key: 'REPLACE_ME'})
        for key in ('SMTP_PORT', 'SMTP_SECURITY', 'DOCKER', 'SMTP_USERNAME'):
            with self.subTest(key=key):
                self.assertRejected(key, **{key: 'x-REPLACE_ME'})

    def test_header_and_value_injection_rejected(self):
        for key, value in (('FROM', 'monitor@example.test\r\nBcc: x@example.test'),
                           ('FROM', 'Monitor <monitor@example.test>'),
                           ('TO', 'ops@example.test\nBcc: x@example.test'),
                           ('TO', 'ops@example.test;x@example.test'),
                           ('TO', 'ops@example.test,'), ('FROM', 'no-at.example.test'),
                           ('COMPOSE_PROJECT', 'Smokemap'), ('COMPOSE_PROJECT', 'dev project'),
                           ('COMPOSE_PROJECT', '-dev'), ('SMTP_HOST', 'smtp.example.test/x'),
                           ('SMTP_HOST', 'smtp example'), ('SMTP_USERNAME', 'user name'),
                           ('DOCKER', 'docker'), ('SMTP_SECURITY', 'ssl'),
                           ('SMTP_HOST', 'smtp.example.test\x00')):
            with self.subTest(key=key, value=value):
                self.assertRejected(key, **{key: value})

    def test_integer_bounds_are_ascii_and_strict(self):
        for key, value in (('SMTP_PORT', '0'), ('SMTP_PORT', '65536'), ('SMTP_PORT', '+587'),
                           ('SMTP_PORT', ' 587'), ('SMTP_PORT', '５８７'),
                           ('SMTP_PORT', '1e3'), ('FAILURE_THRESHOLD', '0'),
                           ('FAILURE_THRESHOLD', '101'), ('REPEAT_SECONDS', '59'),
                           ('REPEAT_SECONDS', '2592001'), ('SMTP_TIMEOUT_SECONDS', '0'),
                           ('SMTP_TIMEOUT_SECONDS', '301'), ('DOCKER_TIMEOUT_SECONDS', '301'),
                           ('REPEAT_SECONDS', '-1')):
            with self.subTest(key=key, value=value):
                self.assertRejected(key, **{key: value})
        config = self.config(REPEAT_SECONDS='0', FAILURE_THRESHOLD='100', SMTP_PORT='465',
                             SMTP_SECURITY='tls')
        self.assertEqual((config.repeat, config.threshold, config.port), (0, 100, 465))

    def test_recipient_list_bounds(self):
        config = self.config(TO='a@example.test, b@example.test')
        self.assertEqual(config.recipients, ('a@example.test', 'b@example.test'))
        self.assertRejected('TO', TO='a@example.test,a@example.test')
        self.assertRejected('TO', TO=','.join(f'o{n}@example.test' for n in range(11)))

    def test_plaintext_only_for_loopback_without_credentials(self):
        self.assertRejected('SMTP_SECURITY', SMTP_SECURITY='none')
        for host in ('localhost', '127.0.0.1', '::1'):
            self.assertEqual(self.config(SMTP_SECURITY='none', SMTP_HOST=host).security, 'none')
        password = self.secret_file()
        self.assertRejected('SMTP_SECURITY', SMTP_SECURITY='none', SMTP_HOST='localhost',
                            SMTP_USERNAME='user', SMTP_PASSWORD_FILE=str(password))

    def test_credential_paths(self):
        self.assertRejected('SMTP_PASSWORD_FILE', SMTP_USERNAME='user')
        self.assertRejected('SMTP_PASSWORD_FILE', SMTP_PASSWORD_FILE='/run/password')
        self.assertRejected('SMTP_PASSWORD_FILE', SMTP_USERNAME='user',
                            SMTP_PASSWORD_FILE='relative/password')
        config = alert.load_config({**self.env(SMTP_USERNAME='user'),
                                    'CREDENTIALS_DIRECTORY': '/run/credentials/unit'})
        self.assertEqual(config.password_file, '/run/credentials/unit/smtp-password')
        explicit = alert.load_config({**self.env(SMTP_USERNAME='user',
                                                 SMTP_PASSWORD_FILE='/private/password'),
                                      'CREDENTIALS_DIRECTORY': '/run/credentials/unit'})
        self.assertEqual(explicit.password_file, '/private/password')

    def test_state_directory_shape(self):
        self.assertRejected('STATE_DIRECTORY', STATE_DIRECTORY='relative/state')
        with self.assertRaises(alert.ConfigError):
            alert.load_config({**self.env(STATE_DIRECTORY=None),
                               'STATE_DIRECTORY': '/a/state:/b/state'})


class SecretTests(Harness):
    def test_reads_private_file_and_strips_one_newline(self):
        self.assertEqual(alert.read_secret(str(self.secret_file())), PASSWORD)
        self.assertEqual(alert.read_secret(str(self.secret_file(PASSWORD, 0o400))), PASSWORD)

    def test_rejects_unsafe_or_malformed_files(self):
        cases = {'group': (PASSWORD, 0o640), 'other': (PASSWORD, 0o604), 'empty': ('', 0o600),
                 'newline': ('a\nb', 0o600), 'oversize': ('x' * 4097, 0o600)}
        for name, (content, mode) in cases.items():
            with self.subTest(name=name), self.assertRaises(alert.SecretError):
                alert.read_secret(str(self.secret_file(content, mode)))
        target = self.secret_file()
        link = self.root / 'link'
        link.symlink_to(target)
        fifo = self.root / 'fifo'
        os.mkfifo(fifo, 0o600)
        for path in (link, fifo, self.root, self.root / 'absent'):
            with self.subTest(path=path.name), self.assertRaises(alert.SecretError):
                alert.read_secret(str(path))


class ProbeTests(Harness):
    def observe(self, mode, **overrides):
        self.mode(mode)
        return alert.observe(self.config(**overrides))

    def test_docker_states_map_to_fixed_reasons(self):
        for mode, expected in (('running/healthy/0', ('healthy', 0)),
                               ('running/unhealthy/2', ('unhealthy', 2)),
                               ('running/starting/0', ('starting', 0)),
                               ('running/null/0', ('no_healthcheck', 0)),
                               ('restarting/unhealthy/7', ('restarting', 7)),
                               ('exited/unhealthy/1', ('not_running', 1)),
                               ('paused/healthy/0', ('not_running', 0)),
                               ('missing', ('missing', None)),
                               ('ambiguous', ('ambiguous', None)),
                               ('ps_fail', ('probe_failed', None)),
                               ('inspect_fail', ('probe_failed', None)),
                               ('bad_id', ('probe_invalid', None)),
                               ('garbage', ('probe_invalid', None)),
                               ('oversize', ('probe_invalid', None)),
                               ('non_ascii', ('probe_invalid', None)),
                               ('extra', ('probe_invalid', None)),
                               ('duplicate', ('probe_invalid', None)),
                               ('nan', ('probe_invalid', None)),
                               ('running/bogus/0', ('probe_invalid', None)),
                               ('bogus/healthy/0', ('probe_invalid', None)),
                               ('running/healthy/-1', ('probe_invalid', None)),
                               ('running/healthy/true', ('probe_invalid', None)),
                               ('running/healthy/1.5', ('probe_invalid', None))):
            with self.subTest(mode=mode):
                self.assertEqual(self.observe(mode), expected)

    def test_timeout_and_missing_binary(self):
        self.assertEqual(self.observe('timeout', DOCKER_TIMEOUT_SECONDS='1'),
                         ('probe_timeout', None))
        self.assertEqual(self.observe('running/healthy/0', DOCKER=str(self.root / 'absent')),
                         ('probe_failed', None))

    def test_only_read_only_queries_with_fixed_filters_and_template(self):
        with patch.dict(os.environ, {'CLEANUP_ALERT_SMTP_USERNAME': 'leak',
                                     'CREDENTIALS_DIRECTORY': '/run/credentials/x'}):
            self.observe('running/healthy/0')
        calls = self.calls()
        self.assertEqual([call['argv'] for call in calls], [
            ['ps', '--all', '--no-trunc', '--quiet',
             '--filter', 'label=com.docker.compose.project=smokemap-dev-r1',
             '--filter', 'label=com.docker.compose.service=media-cleanup',
             '--filter', 'label=com.docker.compose.oneoff=False'],
            ['inspect', '--type', 'container', '--format', alert.INSPECT_FORMAT, CONTAINER]])
        self.assertEqual([call['leaked'] for call in calls], [[], []])
        # Only status, health status and restart count leave Docker.
        self.assertEqual(set(re.findall(r'\.[A-Z][A-Za-z.]*', alert.INSPECT_FORMAT)),
                         {'.State.Status', '.State.Health', '.State.Health.Status',
                          '.RestartCount'})


class EvaluateTests(Harness):
    def step(self, state, reason, now, **overrides):
        return alert.evaluate(state, reason, now, self.config(**overrides))

    def test_threshold_alert_reminder_and_recovery(self):
        state = alert.fresh(NOW)
        state, kind = self.step(state, 'unhealthy', NOW)
        self.assertEqual((kind, state['streak'], state['since']), (None, 1, NOW))
        state, kind = self.step(state, 'starting', NOW + 300)
        self.assertEqual((kind, state['streak'], state['reason'], state['since']),
                         ('alert', 2, 'starting', NOW))
        state['alerted_at'] = NOW + 300
        state, kind = self.step(state, 'unhealthy', NOW + 600)
        self.assertIsNone(kind)
        state, kind = self.step(state, 'unhealthy', NOW + 300 + 21600)
        self.assertEqual(kind, 'reminder')
        state, kind = self.step(state, 'healthy', NOW + 22000)
        self.assertEqual((kind, state['recovery_pending'], state['streak'], state['reason']),
                         ('recovery', True, 0, 'unhealthy'))
        self.assertTrue(alert.valid_state(state))

    def test_threshold_one_disabled_reminders_and_silent_reset(self):
        state, kind = self.step(alert.fresh(NOW), 'missing', NOW, FAILURE_THRESHOLD='1',
                                REPEAT_SECONDS='0')
        self.assertEqual(kind, 'alert')
        state['alerted_at'] = NOW
        state, kind = self.step(state, 'missing', NOW + 10 ** 7, FAILURE_THRESHOLD='1',
                                REPEAT_SECONDS='0')
        self.assertIsNone(kind)
        unalerted, _ = self.step(alert.fresh(NOW), 'unhealthy', NOW)
        state, kind = self.step(unalerted, 'healthy', NOW + 300)
        self.assertEqual((kind, state), (None, alert.fresh(NOW + 300)))

    def test_recurrence_before_recovery_delivery_continues_incident(self):
        state = {**alert.fresh(NOW), 'streak': 0, 'reason': 'unhealthy', 'since': NOW,
                 'alerted_at': NOW + 300, 'recovery_pending': True}
        state, kind = self.step(state, 'not_running', NOW + 600)
        self.assertEqual((kind, state['recovery_pending'], state['since'], state['streak'],
                          state['alerted_at']), (None, False, NOW, 1, NOW + 300))

    def test_wall_clock_rewind_prefers_a_reminder(self):
        state = {**alert.fresh(NOW), 'streak': 3, 'reason': 'unhealthy', 'since': NOW,
                 'alerted_at': NOW}
        self.assertEqual(self.step(state, 'unhealthy', NOW - 60)[1], 'reminder')

    def test_streak_is_capped(self):
        state = {**alert.fresh(NOW), 'streak': alert.STREAK_LIMIT, 'reason': 'unhealthy',
                 'since': NOW, 'alerted_at': NOW}
        self.assertEqual(self.step(state, 'unhealthy', NOW + 1)[0]['streak'], alert.STREAK_LIMIT)


class MessageTests(Harness):
    def test_alert_message_is_fixed_text_and_actionable(self):
        state = {**alert.fresh(NOW), 'streak': 2, 'reason': 'unhealthy', 'since': NOW - 300}
        message = alert.compose_message(self.config(TO='a@example.test,b@example.test'),
                                        'alert', state, 4, NOW)
        self.assertEqual(message['Subject'],
                         '[Smokemap DEVELOPMENT] media-cleanup ALERT: unhealthy')
        self.assertEqual((message['From'], message['To']),
                         ('monitor@example.test', 'a@example.test, b@example.test'))
        self.assertTrue(message['Message-ID'].endswith('@example.test>'))
        self.assertEqual(sorted(message.keys()), sorted(
            ['Subject', 'From', 'To', 'Date', 'Message-ID', 'Content-Type',
             'Content-Transfer-Encoding', 'MIME-Version']))
        body = message.get_content()
        for expected in ('Environment: DEVELOPMENT', alert.DESCRIPTIONS['unhealthy'],
                         'Non-healthy checks in a row: 2', 'First observed: 2027-01-15T07:55:00Z',
                         'Container restarts: 4', 'Reminders repeat every 21600 seconds',
                         'docker compose --project-name smokemap-dev-r1 logs --tail 50 '
                         'media-cleanup'):
            self.assertIn(expected, body)

    def test_recovery_and_test_messages(self):
        state = {**alert.fresh(NOW), 'reason': 'missing', 'since': NOW - 600,
                 'alerted_at': NOW - 300, 'recovery_pending': True}
        recovery = alert.compose_message(self.config(), 'recovery', state, None, NOW)
        self.assertIn('RECOVERED: healthy', recovery['Subject'])
        body = recovery.get_content()
        self.assertIn('Previous condition: missing', body)
        self.assertIn('Container restarts: unknown', body)
        self.assertNotIn('Reminders', body)
        test = alert.compose_message(self.config(), 'test', alert.fresh(NOW), None, NOW)
        self.assertEqual(test['Subject'], '[Smokemap DEVELOPMENT] media-cleanup TEST')
        self.assertIn('does not query', test.get_content())

    def test_every_subject_and_body_line_stays_unfolded(self):
        config = self.config(COMPOSE_PROJECT='p' * 63)
        for kind in ('alert', 'reminder', 'recovery'):
            for reason in alert.PROBLEMS:
                state = {**alert.fresh(NOW), 'streak': 1, 'reason': reason, 'since': NOW,
                         'alerted_at': NOW}
                if kind == 'recovery':
                    state.update(streak=0, recovery_pending=True)
                text = alert.compose_message(config, kind, state, 10 ** 9, NOW).as_string()
                subject = next(line for line in text.splitlines()
                               if line.startswith('Subject: '))
                with self.subTest(kind=kind, reason=reason):
                    self.assertLessEqual(len(subject), 78)
                    self.assertIn(alert.LABELS[kind], subject)
                    self.assertNotIn('Content-Transfer-Encoding: quoted-printable', text)


class SmtpTests(Harness):
    def message(self, config):
        return alert.compose_message(config, 'test', alert.fresh(NOW), None, NOW)

    def assertVerified(self, context):
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_starttls_precedes_authentication(self):
        config = self.config(SMTP_USERNAME='user', SMTP_PASSWORD_FILE='/unused',
                             TO='a@example.test,b@example.test', SMTP_TIMEOUT_SECONDS='7')
        self.assertEqual(alert.send(config, PASSWORD, self.message(config)), 'sent')
        [client] = FakeSMTP.instances
        self.assertIs(type(client), FakeSMTP)
        self.assertEqual((client.host, client.port, client.timeout),
                         ('smtp.example.test', 587, 7))
        self.assertEqual(client.calls,
                         ['ehlo', 'starttls', 'ehlo', 'login', 'send', 'quit', 'close'])
        self.assertVerified(client.starttls_context)
        self.assertEqual(client.credentials, ('user', PASSWORD))
        self.assertEqual(client.messages[0][1:],
                         ('monitor@example.test', ['a@example.test', 'b@example.test']))

    def test_implicit_tls_and_unauthenticated_relays(self):
        config = self.config(SMTP_SECURITY='tls', SMTP_PORT='465')
        self.assertEqual(alert.send(config, None, self.message(config)), 'sent')
        [client] = FakeSMTP.instances
        self.assertIs(type(client), FakeSMTPSSL)
        self.assertVerified(client.context)
        self.assertEqual(client.calls, ['send', 'quit', 'close'])
        FakeSMTP.instances = []
        config = self.config(SMTP_SECURITY='none', SMTP_HOST='127.0.0.1', SMTP_PORT='25')
        self.assertEqual(alert.send(config, None, self.message(config)), 'sent')
        self.assertEqual(FakeSMTP.instances[0].calls, ['send', 'quit', 'close'])

    def test_failures_map_to_fixed_reasons(self):
        config = self.config(SMTP_USERNAME='user', SMTP_PASSWORD_FILE='/unused')
        for fail, reason in (('connect', 'smtp_connect'), ('starttls', 'smtp_tls'),
                             ('login', 'smtp_auth'), ('send', 'smtp_send')):
            with self.subTest(fail=fail):
                FakeSMTP.fail = fail
                self.assertEqual(alert.send(config, PASSWORD, self.message(config)), reason)
        self.assertNotIn('send', FakeSMTP.instances[-2].calls)
        FakeSMTP.fail = None
        FakeSMTP.quit_fails = True
        self.assertEqual(alert.send(config, PASSWORD, self.message(config)), 'sent')
        FakeSMTP.quit_fails = False
        FakeSMTP.refused = {'ops@example.test': (550, b'x')}
        self.assertEqual(alert.send(config, PASSWORD, self.message(config)), 'smtp_partial')


class CheckTests(Harness):
    def state(self):
        return json.loads((self.state_dir / 'state.json').read_text())

    def test_incident_lifecycle_and_private_state(self):
        config = self.config(REPEAT_SECONDS='3600')
        expected = (('running/healthy/0', 0, None, 'healthy'),
                    ('running/unhealthy/0', 0, None, 'unhealthy'),
                    ('running/unhealthy/0', 600, 'ALERT: unhealthy', 'unhealthy'),
                    ('restarting/null/1', 900, None, 'restarting'),
                    ('restarting/null/2', 4200, 'STILL FAILING: restarting', 'restarting'),
                    ('running/healthy/2', 4500, 'RECOVERED: healthy', 'healthy'),
                    ('running/healthy/2', 4800, None, 'healthy'))
        for mode, offset, subject, reason in expected:
            with self.subTest(mode=mode, offset=offset):
                self.mode(mode)
                before = len(self.sent())
                code, events = self.check(config, NOW + offset)
                self.assertEqual(code, 0)
                self.assertEqual(events[0]['reason'], reason)
                sent = self.sent()[before:]
                self.assertEqual([subject] if subject else [],
                                 [m['Subject'].split('media-cleanup ')[1].split(' (')[0]
                                  for m in sent])
        self.assertEqual(self.state(), alert.fresh(NOW + 4800))
        self.assertEqual(stat.S_IMODE(self.state_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.state_dir / 'state.json').stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.state_dir.iterdir()), ['lock', 'state.json'])

    def test_failed_alert_and_recovery_delivery_retry(self):
        config = self.config(FAILURE_THRESHOLD='1')
        self.mode('missing')
        FakeSMTP.fail = 'send'
        code, events = self.check(config, NOW)
        self.assertEqual(code, 75)
        self.assertEqual(events[-1], {**events[-1], 'event': 'notify', 'outcome': 'failure',
                                      'reason': 'smtp_send', 'kind': 'alert'})
        self.assertIsNone(self.state()['alerted_at'])
        FakeSMTP.fail = None
        self.assertEqual(self.check(config, NOW + 300)[0], 0)
        self.assertEqual(self.state()['alerted_at'], NOW + 300)
        self.mode('running/healthy/0')
        FakeSMTP.fail = 'connect'
        code, events = self.check(config, NOW + 600)
        self.assertEqual((code, events[-1]['reason']), (75, 'smtp_connect'))
        self.assertTrue(self.state()['recovery_pending'])
        FakeSMTP.fail = None
        code, events = self.check(config, NOW + 900)
        self.assertEqual((code, events[-1]['outcome'], events[-1]['reason']),
                         (0, 'sent', 'recovery'))
        self.assertEqual(self.state(), alert.fresh(NOW + 900))

    def test_partial_delivery_retries_alert_and_recovery_until_all_accepted(self):
        config = self.config(FAILURE_THRESHOLD='1')
        self.mode('missing')
        FakeSMTP.refused = {'ops@example.test': (550, SECRET.encode())}
        code, events = self.check(config, NOW)
        self.assertEqual(code, 75)
        self.assertEqual(events[-1]['reason'], 'smtp_partial')
        self.assertIsNone(self.state()['alerted_at'])
        FakeSMTP.refused = {}
        self.assertEqual(self.check(config, NOW + 300)[0], 0)
        self.assertEqual(len(self.sent()), 2)
        self.assertEqual(self.state()['alerted_at'], NOW + 300)
        self.assertEqual(self.check(config, NOW + 400)[0], 0)
        self.assertEqual(len(self.sent()), 2, 'fully accepted alerts are suppressed')
        self.mode('running/healthy/0')
        FakeSMTP.refused = {'ops@example.test': (550, SECRET.encode())}
        self.assertEqual(self.check(config, NOW + 600)[0], 75)
        self.assertTrue(self.state()['recovery_pending'])
        FakeSMTP.refused = {}
        self.assertEqual(self.check(config, NOW + 900)[0], 0)
        self.assertEqual(self.state(), alert.fresh(NOW + 900))
        self.assertEqual(len(self.sent()), 4)
        self.assertEqual(self.check(config, NOW + 1200)[0], 0)
        self.assertEqual(len(self.sent()), 4, 'accepted recovery is suppressed')

    def test_password_is_used_but_never_emitted(self):
        config = self.config(FAILURE_THRESHOLD='1', SMTP_USERNAME='user',
                             SMTP_PASSWORD_FILE=str(self.secret_file()))
        self.mode('running/unhealthy/0')
        FakeSMTP.fail = 'login'
        self.check(config, NOW, password=PASSWORD)
        self.assertEqual(FakeSMTP.instances[0].credentials, ('user', PASSWORD))
        self.assertNotIn(PASSWORD, (self.state_dir / 'state.json').read_text())

    def test_concurrent_run_is_skipped_without_querying_docker(self):
        self.state_dir.mkdir(mode=0o700)
        lock = os.open(self.state_dir / 'lock', os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, lock)
        fcntl.flock(lock, fcntl.LOCK_EX)
        code, events = self.check(self.config(), NOW)
        self.assertEqual((code, events[0]['reason']), (75, 'busy'))
        self.assertEqual(self.calls(), [])

    def test_malformed_state_is_reset(self):
        for content in ('{', '[]', '{"version":1}', '{"a":1,"a":1}', 'x' * 5000,
                        json.dumps({**alert.fresh(NOW), 'checked_at': None}),
                        json.dumps({**alert.fresh(NOW), 'version': 2}),
                        json.dumps({**alert.fresh(NOW), 'streak': True}),
                        json.dumps({**alert.fresh(NOW), 'streak': 1}),
                        json.dumps({**alert.fresh(NOW), 'reason': 'healthy'}),
                        json.dumps({**alert.fresh(NOW), 'recovery_pending': True}),
                        json.dumps(alert.fresh(NOW)).replace(str(NOW), 'NaN')):
            with self.subTest(content=content[:40]):
                self.state_dir.mkdir(mode=0o700, exist_ok=True)
                path = self.state_dir / 'state.json'
                path.write_text(content)
                path.chmod(0o600)
                code, events = self.check(self.config(), NOW)
                self.assertEqual(code, 0)
                self.assertEqual(events[0], {**events[0], 'event': 'state', 'outcome': 'reset',
                                             'reason': 'state_invalid'})
                self.assertEqual(self.state(), alert.fresh(NOW))

    def test_unsafe_state_fails_closed_before_docker(self):
        def symlink_state():
            (self.root / 'elsewhere').write_text('{}')
            (self.state_dir / 'state.json').symlink_to(self.root / 'elsewhere')
        def public_state():
            path = self.state_dir / 'state.json'
            path.write_text(json.dumps(alert.fresh(NOW)))
            path.chmod(0o644)
        def public_directory():
            self.state_dir.chmod(0o755)
        def hardlinked_state():
            public_state()
            (self.state_dir / 'state.json').chmod(0o600)
            os.link(self.state_dir / 'state.json', self.root / 'second-link')
        for name, damage in (('symlink', symlink_state), ('mode', public_state),
                             ('directory', public_directory), ('hardlink', hardlinked_state)):
            with self.subTest(name=name):
                self.state_dir.mkdir(mode=0o700)
                damage()
                code, events = self.check(self.config(), NOW)
                self.assertEqual((code, events[-1]['reason']), (74, 'state_error'))
                self.assertEqual(self.calls(), [])
                self.state_dir.chmod(0o700)
                for path in (self.state_dir / 'state.json', self.state_dir / 'lock',
                             self.root / 'second-link'):
                    path.unlink(missing_ok=True)
                self.state_dir.rmdir()

    def test_missing_parent_directory_is_a_state_error(self):
        config = self.config(STATE_DIRECTORY=str(self.root / 'absent' / 'state'))
        self.assertEqual(self.check(config, NOW)[0], 74)


class CliTests(Harness):
    def run_cli(self, *arguments, env=None):
        environment = {'PATH': os.environ.get('PATH', ''), 'PYTHONDONTWRITEBYTECODE': '1',
                       **(env or {})}
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), *arguments], env=environment,
                                capture_output=True, text=True, timeout=30, check=False)
        for secret in (SECRET, PASSWORD):
            self.assertNotIn(secret, result.stdout + result.stderr)
        return result

    def local_env(self, **overrides):
        # Even an accidental send would target a closed loopback port, never the network.
        return self.env(SMTP_HOST='localhost', SMTP_SECURITY='none', SMTP_PORT='9', **overrides)

    def test_usage(self):
        for arguments in ((), ('run',), ('check', 'extra'), ('--help',)):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments, env=self.local_env())
                self.assertEqual((result.returncode, result.stdout), (64, ''))

    def test_validate(self):
        result = self.run_cli('validate', env=self.local_env())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['outcome'], 'valid')
        result = self.run_cli('validate', env=self.local_env(TO='x@example.test\r\nBcc: y'))
        self.assertEqual(result.returncode, 64)
        self.assertEqual(json.loads(result.stdout)['key'], 'CLEANUP_ALERT_TO')
        result = self.run_cli('validate', env=self.env(
            SMTP_USERNAME='user', SMTP_PASSWORD_FILE=str(self.secret_file(mode=0o644))))
        self.assertEqual((result.returncode, json.loads(result.stdout)['reason']),
                         (64, 'credential_unavailable'))
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.state_dir.exists())

    def test_preview_never_writes_or_sends(self):
        self.mode('running/unhealthy/3')
        result = self.run_cli('preview', env=self.local_env(FAILURE_THRESHOLD='1'))
        self.assertEqual(result.returncode, 0, result.stderr)
        first, rest = result.stdout.split('\n', 1)
        decision = json.loads(first)
        self.assertEqual((decision['outcome'], decision['reason']), ('alert', 'unhealthy'))
        message = email.message_from_string(rest, policy=email.policy.default)
        self.assertEqual(message['Subject'],
                         '[Smokemap DEVELOPMENT] media-cleanup ALERT: unhealthy')
        self.assertEqual(message['Content-Transfer-Encoding'], '7bit')
        self.assertIn('Container restarts: 3', message.get_content())
        self.assertFalse(self.state_dir.exists())

    def test_example_settings_are_complete_and_refused_until_replaced(self):
        lines = [line for line in (TEMPLATES / 'dev-cleanup-alert.env.example')
                 .read_text().splitlines() if line and not line.startswith('#')]
        example = dict(line.split('=', 1) for line in lines)
        self.assertEqual(set(example), {alert.PREFIX + key for key in alert.KEYS
                                        if key != 'STATE_DIRECTORY'})
        self.assertFalse(any('PASSWORD=' in line for line in lines))
        result = self.run_cli('validate', env={**example, 'STATE_DIRECTORY': str(self.root)})
        self.assertEqual((result.returncode, json.loads(result.stdout)['reason']),
                         (64, 'config_invalid'))
        replacements = {'CLEANUP_ALERT_COMPOSE_PROJECT': 'smokemap-dev-r1',
                        'CLEANUP_ALERT_SMTP_HOST': 'smtp.example.test',
                        'CLEANUP_ALERT_FROM': 'monitor@example.test',
                        'CLEANUP_ALERT_TO': 'ops@example.test'}
        self.assertEqual({key for key, value in example.items() if 'REPLACE_ME' in value},
                         set(replacements))
        config = alert.load_config({**example, **replacements,
                                    'STATE_DIRECTORY': str(self.root)})
        self.assertEqual((config.security, config.threshold), ('starttls', 2))


class TemplateTests(unittest.TestCase):
    def unit(self, name):
        parser = configparser.ConfigParser(strict=False, interpolation=None, delimiters=('=',))
        parser.optionxform = str
        parser.read_string((TEMPLATES / name).read_text())
        return parser

    def test_service_is_bounded_private_and_read_only_toward_docker(self):
        service = self.unit('smokemap-dev-cleanup-alert.service')['Service']
        self.assertEqual(
            {key: service[key] for key in ('Type', 'StateDirectory', 'StateDirectoryMode',
                                           'UMask', 'NoNewPrivileges', 'EnvironmentFile')},
            {'Type': 'oneshot', 'StateDirectory': 'smokemap-dev-cleanup-alert',
             'StateDirectoryMode': '0700', 'UMask': '0077', 'NoNewPrivileges': 'yes',
             'EnvironmentFile': '%h/.config/smokemap/dev-cleanup-alert.env'})
        self.assertEqual(service['ExecStart'], '/usr/bin/python3 -I '
                         '%h/.local/libexec/smokemap/dev-cleanup-alert.py check')
        # Two Docker queries plus one SMTP exchange fit the unit deadline at defaults.
        self.assertGreaterEqual(int(service['TimeoutStartSec']), 2 * 15 + 5 * 20)
        self.assertFalse({'Environment', 'ExecStartPre', 'ExecStartPost', 'Restart',
                          'LoadCredential', 'User'} & set(service))

    def test_timer_schedule_covers_cleanup_start_grace(self):
        timer = self.unit('smokemap-dev-cleanup-alert.timer')
        self.assertEqual(timer['Timer']['Unit'], 'smokemap-dev-cleanup-alert.service')
        self.assertEqual(timer['Timer']['OnUnitActiveSec'], '5min')
        self.assertEqual(timer['Install']['WantedBy'], 'timers.target')
        compose = (ROOT / 'docker-compose.yaml').read_text()
        grace = int(re.search(r'MEDIA_CLEANUP_HEALTH_START_PERIOD:-([0-9]+)s', compose)[1])
        # The default second consecutive check cannot alert inside start grace.
        self.assertLess(grace, (2 - 1) * 5 * 60)

    def test_monitor_is_stdlib_only(self):
        tree = ast.parse(SCRIPT.read_text())
        modules = {alias.name.split('.')[0] for node in ast.walk(tree)
                   if isinstance(node, ast.Import) for alias in node.names}
        modules |= {node.module.split('.')[0] for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.level == 0}
        self.assertLessEqual(modules - {'__future__'}, set(sys.stdlib_module_names))

    def test_make_and_ci_run_the_offline_suite(self):
        makefile = (ROOT / 'Makefile').read_text()
        self.assertRegex(makefile, r'(?m)^test: .*\btest-dev-cleanup-alert\b')
        self.assertIn("-p 'test_dev_cleanup_alert.py'", makefile)
        workflow = (ROOT / '.github/workflows/test.yml').read_text()
        self.assertIn('- run: make test-dev-cleanup-alert', workflow)


if __name__ == '__main__':
    unittest.main()
