"""Pure stdlib tests: disposable fake manage.py, never Django/DB/storage/Docker."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts/dev-media-cleanup.py'
SPEC = importlib.util.spec_from_file_location('dev_cleanup', SCRIPT)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)
SUMMARY = worker.PREFIX + ' '.join(f'{name}=0' for name in worker.COUNTS)
SECRET = 'UNTRUSTED-CHILD-DIAGNOSTIC-must-never-be-emitted'

FAKE = '''import json, os, signal, subprocess, sys, time
from pathlib import Path
with open('calls', 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
print({secret!r}, flush=True)
print({secret!r}, file=sys.stderr, flush=True)
mode = Path('mode').read_text()
if sys.argv[1] == 'check':
    if mode == 'check_failure': sys.exit(9)
    if mode == 'check_timeout': time.sleep(60)
    sys.exit(0)
if mode in ('hang', 'descendant'):
    if mode == 'descendant':
        child = subprocess.Popen([sys.executable, '-c',
            'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])
        Path('descendant').write_text(str(child.pid))
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)
if mode == 'exit':
    print({summary!r}, flush=True)
    sys.exit(8)
if mode == 'flood':
    print({secret!r} * 10000, flush=True)
    time.sleep(60)
if mode == 'missing': sys.exit(0)
if mode == 'duplicate': print({summary!r}, flush=True)
if mode == 'malformed': print({summary!r} + ' failed=2', flush=True)
elif mode == 'failed': print({summary!r}.replace('failed=0', 'failed=1'), flush=True)
else: print({summary!r}, flush=True)
'''


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='smokemap-cleanup-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state_dir = self.root / 'state'
        self.store = worker.Store(self.state_dir)
        (self.root / 'manage.py').write_text(FAKE.format(secret=SECRET, summary=SUMMARY))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('MEDIA_CLEANUP_')}
        self.env.update(MEDIA_CLEANUP_BATCH_SIZE='17', MEDIA_CLEANUP_INTERVAL_SECONDS='1',
                        MEDIA_CLEANUP_TIMEOUT_SECONDS='1', PYTHONDONTWRITEBYTECODE='1')
        config_patch = patch.dict(os.environ, {key: self.env[key] for key in (
            'MEDIA_CLEANUP_BATCH_SIZE', 'MEDIA_CLEANUP_INTERVAL_SECONDS',
            'MEDIA_CLEANUP_TIMEOUT_SECONDS')})
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.proc = None

    def start(self, mode='ok', **overrides):
        (self.root / 'mode').write_text(mode)
        self.log = self.root / 'events'
        self.stream = self.log.open('w')
        self.addCleanup(self.stream.close)
        # Test harness supplies a disposable store through the Python API; the
        # product CLI has no alternate command, success or test-state switches.
        harness = ("import importlib.util,sys; from pathlib import Path; "
                   "s=importlib.util.spec_from_file_location('worker',sys.argv[1]); "
                   "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                   "sys.exit(m.run(Path(sys.argv[2])))")
        self.proc = subprocess.Popen([sys.executable, '-c', harness, str(SCRIPT),
                                      str(self.state_dir)], cwd=self.root,
                                     env={**self.env, **overrides}, stdout=self.stream,
                                     stderr=subprocess.STDOUT)
        self.addCleanup(self.finish)
        return self.proc

    def finish(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def until(self, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except FileNotFoundError:
                pass  # Fresh-start invalidation intentionally removes the old file.
            time.sleep(.02)
        self.fail('Timed out waiting for disposable cleanup fixture')

    def reason(self, reason):
        return any(e['reason'] == reason for e in self.events())

    def test_real_batch_and_command_order_and_private_state(self):
        self.start()
        self.until(lambda: worker.healthy(self.store))
        calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        self.assertEqual(calls[:2], [['check'], ['process_media_cleanup', '--batch-size', '17']])
        self.assertEqual(self.store.read()['phase'], 'waiting')
        self.assertEqual(self.state_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.state_dir / 'status.json').stat().st_mode & 0o777, 0o600)
        self.assertFalse(any(self.state_dir.glob('.status-*')))
        self.finish()
        self.assertEqual(self.proc.returncode, 0)
        self.assertFalse(worker.healthy(self.store))
        self.assertNotIn(SECRET, self.log.read_text())

    def test_failed_count_exit_zero_and_recovery_only_after_real_success(self):
        self.start('failed')
        self.until(lambda: self.reason('failed_count'))
        self.assertFalse(worker.healthy(self.store))
        self.assertIsNone(self.store.read()['last_success_at'])
        (self.root / 'mode').write_text('hang')
        self.until(lambda: self.store.read()['phase'] == 'running')
        self.assertFalse(worker.healthy(self.store))
        self.assertFalse(any(e['outcome'] == 'recovered' for e in self.events()))
        self.until(lambda: self.reason('timeout'))
        (self.root / 'mode').write_text('ok')
        self.until(lambda: worker.healthy(self.store))
        self.assertTrue(any(e['outcome'] == 'recovered' for e in self.events()))
        self.finish()
        for item in self.events():
            self.assertLessEqual(set(item), {'event', 'outcome', 'reason', 'timestamp', 'counts'})
            if 'counts' in item:
                self.assertEqual(set(item['counts']), set(worker.COUNTS))
        self.assertNotIn(SECRET, self.log.read_text())

    def test_running_after_success_is_healthy_only_until_bounded_deadline(self):
        self.start()
        self.until(lambda: worker.healthy(self.store))
        (self.root / 'mode').write_text('hang')
        self.until(lambda: self.store.read()['phase'] == 'running')
        state = self.store.read()
        self.assertIsNotNone(state['last_success_at'])
        self.assertTrue(worker.healthy(self.store))
        self.assertFalse(worker.healthy(self.store, now=state['deadline'] + .01))
        self.until(lambda: self.reason('timeout'))
        self.assertFalse(worker.healthy(self.store))
        self.assertIsNone(self.store.read()['last_success_at'])

    def test_nonzero_exit_missing_duplicate_malformed_and_output_limit(self):
        for mode, reason in (('exit', 'command_exit'), ('missing', 'output_invalid'),
                             ('duplicate', 'output_invalid'), ('malformed', 'output_invalid'),
                             ('flood', 'output_limit')):
            with self.subTest(mode=mode):
                self.start(mode)
                self.until(lambda: self.reason(reason))
                self.assertFalse(worker.healthy(self.store))
                self.assertIsNone(self.proc.poll(), 'ordinary failure must retry')
                self.finish()
                self.assertNotIn(SECRET, self.log.read_text())
                self.assertFalse(any(e['outcome'] == 'recovered' for e in self.events()))

    def test_startup_check_failure_and_timeout(self):
        for mode, reason in (('check_failure', 'command_exit'), ('check_timeout', 'timeout')):
            with self.subTest(mode=mode):
                self.start(mode)
                self.proc.wait(timeout=5)
                self.assertEqual(self.proc.returncode, 1)
                self.assertTrue(self.reason(reason))
                self.assertFalse(worker.healthy(self.store))
                self.assertEqual(len((self.root / 'calls').read_text().splitlines()), 1)
                (self.root / 'calls').unlink()
                self.assertNotIn(SECRET, self.log.read_text())

    def test_timeout_kills_descendant_and_retries(self):
        self.start('descendant')
        self.until(lambda: (self.root / 'descendant').exists())
        descendant = int((self.root / 'descendant').read_text())
        self.until(lambda: self.reason('timeout'))
        self.assertFalse(worker.healthy(self.store))
        self.assert_process_stopped(descendant)
        (self.root / 'mode').write_text('ok')
        self.until(lambda: worker.healthy(self.store))
        self.assertTrue(any(e['outcome'] == 'recovered' for e in self.events()))

    def assert_process_stopped(self, pid):
        def stopped():
            try:
                worker.process_start(pid)
            except (OSError, ValueError):
                return True
            return False
        self.until(stopped)

    def test_sigterm_kills_group_during_batch_and_during_startup(self):
        for mode in ('descendant', 'check_timeout'):
            with self.subTest(mode=mode):
                self.start(mode, MEDIA_CLEANUP_TIMEOUT_SECONDS='60')
                if mode == 'descendant':
                    self.until(lambda: (self.root / 'descendant').exists())
                    descendant = int((self.root / 'descendant').read_text())
                else:
                    self.until(lambda: (self.root / 'calls').exists())
                before = time.monotonic()
                self.finish()
                self.assertLess(time.monotonic() - before, 4)
                self.assertEqual(self.proc.returncode, 0)
                self.assertFalse(worker.healthy(self.store))
                if mode == 'descendant':
                    self.assert_process_stopped(descendant)
                (self.root / 'calls').unlink()
                self.assertNotIn(SECRET, self.log.read_text())

    def test_invalid_config_never_runs_django(self):
        self.start(MEDIA_CLEANUP_BATCH_SIZE='1001')
        self.proc.wait(timeout=5)
        self.assertEqual(self.proc.returncode, 64)
        self.assertTrue(self.reason('config_invalid'))
        self.assertFalse((self.root / 'calls').exists())
        self.assertFalse(worker.healthy(self.store))

    def seed_success(self):
        self.store.prepare()
        now = time.time()
        value = {'version': 1, 'pid': os.getpid(),
                 'process_start': worker.process_start(os.getpid()),
                 'started_at': now - 1, 'updated_at': now,
                 'last_success_at': now, 'phase': 'waiting',
                 'deadline': now + worker.config()[1] + worker.SCHEDULING_GRACE}
        self.store.write(value)
        return value

    def test_fresh_start_invalidates_old_success(self):
        self.seed_success()
        self.assertTrue(worker.healthy(self.store))
        self.start('hang')
        self.until(lambda: self.store.read()['pid'] == self.proc.pid and
                   self.store.read()['phase'] == 'running')
        self.assertIsNone(self.store.read()['last_success_at'])
        self.assertFalse(worker.healthy(self.store))

    def test_store_failure_exits_generically_before_work(self):
        self.state_dir.mkdir(mode=0o755)
        self.start()
        self.proc.wait(timeout=5)
        self.assertEqual(self.proc.returncode, 74)
        self.assertTrue(self.reason('state_error'))
        self.assertFalse((self.root / 'calls').exists())
        self.assertFalse(worker.healthy(self.store))

    def test_state_write_failure_after_success_invalidates_status(self):
        self.start()
        self.until(lambda: worker.healthy(self.store))
        # An untrusted/stale staging path is never opened or reused. A failed
        # atomic replace must stop work and remove the previous success file.
        (self.state_dir / 'status.json').unlink()
        (self.state_dir / 'status.json').mkdir()
        self.proc.wait(timeout=5)
        self.assertEqual(self.proc.returncode, 74)
        self.assertTrue(self.reason('state_error'))
        self.assertFalse(worker.healthy(self.store))

    def test_staging_collision_is_never_reused_or_unlinked(self):
        value = self.seed_success()
        stage = self.state_dir / '.status-collision'
        stage.write_text(SECRET)
        stage.chmod(0o644)
        identity = type('Identity', (), {'hex': 'collision'})()
        with patch.object(worker.uuid, 'uuid4', return_value=identity):
            self.assertRaises(FileExistsError, self.store.write, value)
        self.assertEqual(stage.read_text(), SECRET)
        self.assertEqual(self.store.read(), value)

    def test_health_strict_schema_time_and_process_identity(self):
        baseline = self.seed_success()
        mutations = [dict(version=True), dict(version=2), dict(extra='unknown'),
                     dict(pid=True), dict(pid=2147483647), dict(process_start=1),
                     dict(last_success_at=None), dict(phase='starting'), dict(phase='failed'),
                     dict(updated_at=float('nan')), dict(updated_at='123'),
                     dict(started_at=baseline['updated_at'] + 1),
                     dict(updated_at=baseline['updated_at'] + 100),
                     dict(deadline=baseline['deadline'] + 100)]
        for change in mutations:
            with self.subTest(change=change):
                # JSON with NaN deliberately bypasses the safe writer.
                (self.state_dir / 'status.json').write_text(json.dumps({**baseline, **change}))
                self.assertFalse(worker.healthy(self.store))
        self.store.write(baseline)
        self.assertFalse(worker.healthy(self.store, now=baseline['deadline'] + .01))
        running = {**baseline, 'phase': 'running', 'deadline': baseline['updated_at'] + worker.config()[2]}
        self.store.write(running)
        self.assertTrue(worker.healthy(self.store))
        self.assertFalse(worker.healthy(self.store, now=running['deadline'] + .01))
        running['last_success_at'] -= 400
        self.store.write(running)
        self.assertFalse(worker.healthy(self.store))

    def test_missing_wrong_unreadable_oversized_duplicate_symlink_state(self):
        self.assertFalse(worker.healthy(self.store))
        self.seed_success()
        path = self.state_dir / 'status.json'
        for raw in ('[]', '{}', '{', '{"version":1,"version":1}', 'x' * 4097):
            path.write_text(raw)
            self.assertFalse(worker.healthy(self.store))
        self.seed_success()
        path.chmod(0o644)
        self.assertFalse(worker.healthy(self.store))
        path.chmod(0)
        self.assertFalse(worker.healthy(self.store))
        path.chmod(0o600)
        os.link(path, self.state_dir / 'hardlink')
        self.assertFalse(worker.healthy(self.store))
        path.unlink()
        path.symlink_to(self.root / 'manage.py')
        self.assertFalse(worker.healthy(self.store))
        self.state_dir.chmod(0o755)
        self.assertFalse(worker.healthy(self.store))
        self.state_dir.chmod(0o700)
        with patch.object(worker.os, 'geteuid', return_value=os.geteuid() + 1):
            self.assertFalse(worker.healthy(self.store))


class ProtocolTests(unittest.TestCase):
    def test_defaults_and_config_validation(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(worker.config(), (100, 300, 120))
            for key in ('BATCH_SIZE', 'INTERVAL_SECONDS', 'TIMEOUT_SECONDS'):
                for value in ('', '0', '-1', '1.5', 'inf', 'NaN', ' 1', '1 ', '١', '9' * 100):
                    with self.subTest(key=key, value=value):
                        with patch.dict(os.environ, {'MEDIA_CLEANUP_' + key: value}):
                            self.assertRaises(ValueError, worker.config)
            for value in ('1', '1000'):
                with patch.dict(os.environ, {'MEDIA_CLEANUP_BATCH_SIZE': value}):
                    self.assertEqual(worker.config()[0], int(value))

    def test_exact_summary_allowlist_with_untrusted_preamble(self):
        output = f'{SECRET}\nGDAL_LIBRARY_PATH: /usr/lib/libgdal.so\n{SUMMARY}\n'
        self.assertEqual(worker.parse_counts(output.encode()), dict.fromkeys(worker.COUNTS, 0))
        for value in ('', SUMMARY + '\n' + SUMMARY, SUMMARY + ' unknown=1',
                      SUMMARY.replace('expired=0', 'expired=-1', 1),
                      SUMMARY.replace('failed=0', 'failed=NaN'),
                      SUMMARY.replace('failed=0', 'failed=1.2'),
                      SUMMARY.replace('skipped=0', 'failed=0'),
                      SUMMARY.replace('skipped=0 ', ''),
                      'prefix ' + SUMMARY, SUMMARY + SECRET):
            with self.subTest(value=value):
                self.assertRaises(worker.InvalidOutput, worker.parse_counts, value.encode())

    def test_source_contract_is_dev_only_and_wait_target_uses_health(self):
        compose = (ROOT / 'docker-compose.yaml').read_text()
        cleanup = compose.split('  media-cleanup:\n')[1].split('\n  frontend:')[0]
        self.assertIn('command: ["python", "/opt/smokemap-dev-media-cleanup.py", "run"]', cleanup)
        self.assertIn('test: ["CMD", "python", "/opt/smokemap-dev-media-cleanup.py", "health"]', cleanup)
        self.assertIn('./smokemap-django-backend:/app', cleanup)
        self.assertIn('./scripts/dev-media-cleanup.py:/opt/smokemap-dev-media-cleanup.py:ro', cleanup)
        self.assertIn('restart: unless-stopped', cleanup)
        self.assertNotIn('ports:', cleanup)
        self.assertEqual(compose.count('./scripts/dev-media-cleanup.py:'), 1)
        self.assertIn('docker compose up --build --detach --wait', (ROOT / 'Makefile').read_text())
        self.assertIn('make test-dev-cleanup', (ROOT / '.github/workflows/test.yml').read_text())
        for path in (ROOT / 'deploy/staging').rglob('*.py'):
            self.assertNotIn('dev-media-cleanup', path.read_text())


if __name__ == '__main__':
    unittest.main()
