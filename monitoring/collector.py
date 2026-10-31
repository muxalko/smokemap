#!/usr/bin/env python3
"""One-shot, stdlib-only, private textfile collector. Never print source diagnostics."""
import argparse
from contextlib import closing
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import sqlite3
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler


REQUIRED_SOURCES = {
    'hcp_api': 'http', 'frontend': 'http', 'backend': 'http',
    'hcp_runtime': 'runtime', 'hcp_queue': 'sqlite',
    'dev_frontend': 'docker', 'dev_backend': 'docker', 'dev_db': 'docker',
    'dev_storage': 'docker', 'dev_media_cleanup': 'docker', 'backup': 'backup',
}
OUTPUT_LIMIT = 65536


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('redirect forbidden')


def label(value):
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


def sample(name, value, **labels):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('nonfinite')
    suffix = '{' + ','.join(f'{k}="{label(v)}"' for k, v in sorted(labels.items())) + '}' if labels else ''
    return f'smokemap_{name}{suffix} {value:.17g}\n'


def number(value):
    if isinstance(value, bool):
        raise ValueError('boolean timestamp')
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('invalid number')
    return value


def probe(url, timeout):
    parsed = urlsplit(url)
    if (parsed.scheme != 'http' or not ipaddress.ip_address(parsed.hostname).is_loopback
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('loopback HTTP only')
    # Never follow redirects or environment proxies; no response bodies are read.
    with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError('probe failed')
    return {}


def bounded_command(arguments, timeout):
    """Bound memory and wall time; discard stderr and never expose diagnostics."""
    child = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map() or child.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('command timeout')
                for key, _ in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fd, 8192)
                    if not data:
                        selector.unregister(key.fd)
                    elif len(output) + len(data) > OUTPUT_LIMIT:
                        raise ValueError('command output limit')
                    else:
                        output.extend(data)
        if child.returncode != 0:
            raise ValueError('command failure')
        return bytes(output)
    finally:
        # Kill any surviving descendants, including a child holding stdout open.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        child.stdout.close()


def runtime(path, timeout):
    status = json.loads(bounded_command([path, 'herdr-check'], timeout))
    if (status.get('server', {}).get('status') != 'running'
            or status.get('endpoint_compatible') is not True
            or status.get('private_protocol_compatible') is not True):
        raise ValueError('runtime unavailable')
    return {}


def container(name, timeout):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name):
        raise ValueError('invalid container')
    # Format excludes env, logs, names, IDs, health logs and secrets.
    output = bounded_command(['docker', 'inspect', '--format',
                             '{{json .State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.RestartCount}}', name],
                            timeout)
    running, health, restarts = output.decode('ascii').strip().split()
    if (running not in ('true', 'false') or health not in ('healthy', 'unhealthy', 'starting', 'none')
            or not re.fullmatch(r'[0-9]{1,16}', restarts)):
        raise ValueError('invalid Docker state')
    return {'container_running': int(running == 'true'),
            'container_health': int(health == 'healthy'),
            'container_health_configured': int(health != 'none'),
            'container_restarts_total': number(restarts)}


def queue(path, timeout, now):
    # Only aggregate SELECTs on the four approved columns. No task text is fetched.
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=timeout)) as db:
        deadline = time.monotonic() + timeout
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        row = db.execute('''WITH normalized AS (SELECT status,
          CASE WHEN typeof(created_at) IN ('integer','real') THEN created_at
            ELSE (julianday(created_at)-2440587.5)*86400 END AS created_at,
          CASE WHEN typeof(updated_at) IN ('integer','real') THEN updated_at
            ELSE (julianday(updated_at)-2440587.5)*86400 END AS updated_at,
          CASE WHEN typeof(lease_expires_at) IN ('integer','real') THEN lease_expires_at
            ELSE (julianday(lease_expires_at)-2440587.5)*86400 END AS lease_expires_at,
          CASE WHEN lease_expires_at IS NOT NULL AND
            (CASE WHEN typeof(lease_expires_at) IN ('integer','real') THEN lease_expires_at
              ELSE julianday(lease_expires_at) END) IS NULL THEN 1 ELSE 0 END AS bad_lease
          FROM tasks) SELECT
          SUM(CASE WHEN status IN ('queued','pending') THEN 1 ELSE 0 END),
          MIN(CASE WHEN status IN ('queued','pending') THEN created_at END),
          SUM(CASE WHEN status = 'running' AND lease_expires_at < ? THEN 1 ELSE 0 END),
          SUM(CASE WHEN status IN ('failed','error') AND updated_at >= ? THEN 1 ELSE 0 END),
          SUM(CASE WHEN status IN ('blocked','waiting_approval','awaiting_approval') THEN 1 ELSE 0 END),
          SUM(CASE WHEN status NOT IN ('queued','pending','running','failed','error',
            'blocked','waiting_approval','awaiting_approval','completed','done','cancelled','succeeded')
            OR status IS NULL THEN 1 ELSE 0 END),
          SUM(CASE WHEN (status IN ('queued','pending') AND created_at IS NULL)
            OR (status IN ('failed','error') AND updated_at IS NULL)
            OR (status = 'running' AND bad_lease = 1) THEN 1 ELSE 0 END)
          FROM normalized''', (now - 120, now - 3600)).fetchone()
    count, oldest, expired, failed, waits, unknown, invalid = row
    if invalid:
        raise ValueError("invalid queue timestamps")
    age = max(0, now - number(oldest)) if oldest is not None else 0
    return dict(zip(('hcp_queue_count', 'hcp_queue_oldest_age_seconds', 'hcp_expired_leases',
                     'hcp_failures_last_hour', 'hcp_approval_waits', 'hcp_unknown_status_count'),
                    (count or 0, age, expired or 0, failed or 0, waits or 0, unknown or 0)))


def backup(path, now):
    # Evidence must be authored by a backup+restore-verification pipeline, never mtime.
    with open(path, encoding='utf-8') as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError('oversize evidence')
    evidence = json.loads(raw)
    stamp = number(evidence['verified_at'])
    if (type(evidence.get('version')) is not int or evidence.get('version') != 1
            or evidence.get('backup_succeeded') is not True
            or evidence.get('restore_verified') is not True or not 0 < stamp <= now):
        raise ValueError('unverified backup')
    return {'backup_verified_timestamp_seconds': stamp}


def collect(config, now=None):
    now = time.time() if now is None else now
    timeout = number(config.get('timeout_seconds', 5))
    if not 0 < timeout <= 10:
        raise ValueError('timeout outside bound')
    sources = config['sources']
    if not 1 <= len(sources) <= 20:
        raise ValueError('source count outside bound')
    names = [s['name'] for s in sources]
    if len(set(names)) != len(names) or any(not re.fullmatch('[a-z][a-z0-9_]{0,47}', n) for n in names):
        raise ValueError('invalid fixed source label')
    kinds = {s['name']: s['kind'] for s in sources}
    if any(kinds.get(name) != kind for name, kind in REQUIRED_SOURCES.items()):
        raise ValueError('required source missing or wrong kind')
    output = sample('collector_timestamp_seconds', now)
    for source in sources:
        name, kind = source['name'], source['kind']
        output += sample('source_expected', 1, source=name)
        values = {}
        try:
            if kind == 'http':
                values = probe(source['url'], timeout)
            elif kind == 'docker':
                values = container(source['container'], timeout)
            elif kind == 'runtime':
                values = runtime(source['path'], timeout)
            elif kind == 'sqlite':
                values = queue(source['path'], timeout, now)
            elif kind == 'backup':
                values = backup(source['path'], now)
            else:
                raise ValueError('unknown source kind')
            rendered = ''.join(sample(metric, value, source=name) for metric, value in values.items())
            success = 1
        except Exception:
            # No exception text, URLs, command output, DB contents or paths escape.
            rendered, success = '', 0
        output += sample('source_success', success, source=name)
        output += sample('source_timestamp_seconds', now if success else 0, source=name)
        output += rendered
    return output


def atomic_write(path, contents):
    path = Path(path)
    info = path.parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('private same-user metrics directory required')
    descriptor, temporary = tempfile.mkstemp(prefix='.collector-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        with open(args.config, encoding='utf-8') as stream:
            raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError('config limit')
            config = json.loads(raw)
        atomic_write(args.output, collect(config))
    except Exception:
        print('monitoring_collection_failed')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
