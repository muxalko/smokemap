"""Primary/CI-only Docker regression: isolated UUID project, fake manage.py.

Run with Compose 2.35.1; no application, live database, storage or host ports.
The staging regression remains separate and its PID 1 contract is unchanged.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ('media cleanup processed: expired=0 claimed=0 deleted=0 upload_claimed=0 '
           'upload_deleted=0 redacted=0 failed=0 skipped=0 draft_expired=0')


class DevelopmentCleanupComposeTests(unittest.TestCase):
    def test_wait_overrides_inherited_probe_and_requires_progress_then_recovers(self):
        compose = ([os.environ['COMPOSE_235_BINARY']] if os.environ.get('COMPOSE_235_BINARY')
                   else ['docker', 'compose'])
        version = subprocess.run([*compose, 'version', '--short'], check=True,
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(version.stdout.strip().removeprefix('v'), '2.35.1')
        # Explicit empty env file: never read local .env or staging secrets.
        rendered = json.loads(subprocess.run(
            [*compose, '--env-file', '/dev/null', '--file', str(ROOT / 'docker-compose.yaml'),
             'config', '--format', 'json'], check=True, capture_output=True, text=True,
            timeout=15).stdout)['services']['media-cleanup']
        self.assertEqual(rendered['command'], ['python', '/opt/smokemap-dev-media-cleanup.py', 'run'])
        self.assertEqual(rendered['healthcheck']['test'],
                         ['CMD', 'python', '/opt/smokemap-dev-media-cleanup.py', 'health'])
        project = 'smokemap-dev-cleanup-regression-' + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix=project, dir='/tmp') as directory:
            root = Path(directory)
            inherited_probe = ['python', '-c', "import urllib.request; "
                               "urllib.request.urlopen('http://127.0.0.1:8000/health/live/', timeout=2)"]
            (root / 'Dockerfile').write_text(
                'FROM python:3.12-slim-bookworm\n'
                'WORKDIR /app\nCOPY manage.py /app/manage.py\n'
                'USER 10001:10001\n'
                f'HEALTHCHECK CMD {json.dumps(inherited_probe)}\n')
            (root / 'manage.py').write_text(
                'import sys\nfrom pathlib import Path\n'
                'print("UNTRUSTED-CHILD-DIAGNOSTIC", flush=True)\n'
                'if sys.argv[1] == "check": sys.exit(0)\n'
                f'summary = {SUMMARY!r}\n'
                'if not Path("/tmp/recovered").exists():\n'
                '    summary = summary.replace("failed=0", "failed=1")\n'
                'print(summary, flush=True)\n')
            image = project + ':test'
            subprocess.run(['docker', 'build', '--tag', image, str(root)], check=True, timeout=180)
            self.addCleanup(subprocess.run, ['docker', 'image', 'rm', image], check=True, timeout=30)
            # World-readable source but no writable host mounts; state belongs
            # to the image's non-root UID and lives only in its temporary /tmp.
            config = {'services': {'media-cleanup': {
                'image': image, 'pull_policy': 'never', 'network_mode': 'none',
                'init': True, 'cap_drop': ['ALL'],
                'security_opt': ['no-new-privileges:true'],
                'command': rendered['command'], 'restart': 'no',
                'environment': {'MEDIA_CLEANUP_BATCH_SIZE': '100',
                                'MEDIA_CLEANUP_INTERVAL_SECONDS': '1',
                                'MEDIA_CLEANUP_TIMEOUT_SECONDS': '2'},
                'volumes': [{'type': 'bind', 'source': str(ROOT / 'scripts/dev-media-cleanup.py'),
                             'target': '/opt/smokemap-dev-media-cleanup.py', 'read_only': True}],
                'tmpfs': rendered['tmpfs'],
                'healthcheck': {**rendered['healthcheck'], 'interval': '1s',
                                'start_period': '1s'},
            }}}
            config_file = root / 'compose.json'
            config_file.write_text(json.dumps(config))
            prefix = [*compose, '--project-name', project, '--file', str(config_file)]
            def state():
                container = subprocess.run([*prefix, 'ps', '--quiet', 'media-cleanup'],
                                           check=True, capture_output=True, text=True,
                                           timeout=10).stdout.strip()
                return json.loads(subprocess.run(['docker', 'inspect', container], check=True,
                                  capture_output=True, text=True, timeout=10).stdout)[0]
            try:
                failed = subprocess.run([*prefix, 'up', '--detach', '--wait', '--wait-timeout', '15'],
                                        capture_output=True, text=True, timeout=25)
                self.assertNotEqual(failed.returncode, 0)
                inspected = state()
                self.assertEqual(inspected['State']['Health']['Status'], 'unhealthy')
                self.assertEqual(inspected['Config']['Healthcheck']['Test'],
                                 rendered['healthcheck']['test'])
                self.assertEqual(inspected['Config']['User'], '10001:10001')
                subprocess.run([*prefix, 'exec', '-T', 'media-cleanup', 'python', '-c',
                                'from pathlib import Path; Path("/tmp/recovered").touch()'],
                               check=True, timeout=10)
                deadline = time.monotonic() + 15
                while state()['State']['Health']['Status'] != 'healthy':
                    self.assertLess(time.monotonic(), deadline, 'Recovery health deadline exceeded')
                    time.sleep(.25)
                passed = subprocess.run([*prefix, 'up', '--detach', '--wait', '--wait-timeout', '15'],
                                        capture_output=True, text=True, timeout=25)
                self.assertEqual(passed.returncode, 0, 'Compose --wait must accept real batch recovery')
                logs = subprocess.run([*prefix, 'logs', '--no-color', '--no-log-prefix'],
                                      check=True, capture_output=True, text=True, timeout=10).stdout
                self.assertNotIn('UNTRUSTED-CHILD-DIAGNOSTIC', logs)
                events = [json.loads(line) for line in logs.splitlines() if line.strip()]
                self.assertTrue(any(e['reason'] == 'failed_count' for e in events))
                self.assertTrue(any(e['outcome'] == 'recovered' for e in events))
            finally:
                # This UUID project only; no shared services, volumes or ports.
                subprocess.run([*prefix, 'down', '--timeout', '5'], check=True, timeout=30)


if __name__ == '__main__':
    unittest.main()
