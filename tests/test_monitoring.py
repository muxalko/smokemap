import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('collector', Path(__file__).resolve().parents[1] / 'monitoring/collector.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class MonitoringTests(unittest.TestCase):
    def test_escaping(self):
        self.assertEqual(c.sample('test', 1, source='a"\\\nb'), 'smokemap_test{source="a\\"\\\\\\nb"} 1\n')
        with self.assertRaises(ValueError):
            c.sample('test', float('nan'))

    def test_partial_failure_and_redaction(self):
        config = {'sources': [{'name':'bad','kind':'http','url':'http://127.0.0.1/secret'},
                              {'name':'good','kind':'runtime','path':'/secret'}]}
        with patch.object(c, 'probe', side_effect=RuntimeError('PROMPT TOKEN SECRET URL')), patch.object(c, 'runtime', return_value={}):
            result = c.collect(config, 100)
        self.assertIn('source_success{source="bad"} 0', result)
        self.assertIn('source_timestamp_seconds{source="bad"} 0', result)
        self.assertIn('source_success{source="good"} 1', result)
        for secret in ['PROMPT','TOKEN','SECRET','URL','/secret']:
            self.assertNotIn(secret, result)

    def test_timeouts_do_not_leak(self):
        with patch.object(c.subprocess, 'run', side_effect=subprocess.TimeoutExpired('SECRET', 2)) as run:
            result = c.collect({'timeout_seconds':2, 'sources':[{'name':'runtime','kind':'runtime','path':'/private'}]}, 100)
        self.assertIn('source_success{source="runtime"} 0', result)
        self.assertEqual(run.call_args.kwargs['timeout'], 2)
        self.assertEqual(run.call_args.kwargs['stdout'], subprocess.DEVNULL)
        self.assertNotIn('SECRET', result)

    def test_probe_is_shallow_bounded_no_proxy_or_redirect(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        with patch.object(c, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            c.probe('http://127.0.0.1:8000/health/ready/', 3)
            self.assertEqual(opener.call_args.args[0].proxies, {})
            self.assertIsInstance(opener.call_args.args[1], c.NoRedirect)
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'], 3)
            response.read.assert_not_called()
        with self.assertRaises(ValueError):
            c.NoRedirect().redirect_request(None, None, None, None, None, None)
        for url in ['http://example.com/', 'http://192.168.1.1/', 'https://127.0.0.1/', 'http://user:pass@127.0.0.1/', 'http://127.0.0.1/?token=x']:
            with self.assertRaises(ValueError):
                c.probe(url, 1)

    def test_docker_allowlist_and_minimal_format(self):
        with patch.object(c.subprocess, 'run', return_value=Mock(stdout=b'true healthy 4\n')) as run:
            metrics = c.container('development-db-1', 2)
        self.assertEqual(metrics['container_restarts_total'], 4)
        command = run.call_args.args[0]
        self.assertIn('docker', command)
        self.assertNotIn('.Config', ' '.join(command))
        self.assertEqual(command[-1], 'development-db-1')
        for bad in ['--all','a b','a\nSECRET']:
            with self.assertRaises(ValueError):
                c.container(bad, 2)

    def test_queue_aggregate_readonly_expected_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'control.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE tasks(status,created_at,updated_at,lease_expires_at,spec_json,result_json,error,token)')
                for row in [('queued',10,20,None),('running',0,20,800),('running',0,20,950),('failed',0,990,None),('blocked',0,0,0),('waiting_approval',0,0,0)]:
                    db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)', (*row,'SECRET','PROMPT','ERROR','TOKEN'))
            before = path.read_bytes()
            original = c.sqlite3.connect
            statements = []
            def connect(database_uri, **kwargs):
                self.assertTrue(database_uri.endswith('?mode=ro'))
                connection = original(database_uri, **kwargs)
                connection.set_trace_callback(statements.append)
                return connection
            with patch.object(c.sqlite3, 'connect', side_effect=connect):
                metrics = c.queue(path, 1, 1000)
            self.assertEqual(metrics['hcp_queue_oldest_age_seconds'], 990)
            self.assertEqual(metrics['hcp_expired_leases'], 1)
            self.assertEqual(metrics['hcp_failures_last_hour'], 1)
            self.assertEqual(metrics['hcp_approval_waits'], 2)
            self.assertEqual(metrics['hcp_unknown_status_count'], 0)
            self.assertEqual(before, path.read_bytes())
            self.assertTrue(all(s.lstrip().startswith('WITH normalized AS (SELECT') for s in statements))
            for forbidden in ['spec_json','result_json','error,','token']:
                self.assertNotIn(forbidden, ' '.join(statements))
            with original(path.as_uri()+'?mode=ro', uri=True) as readonly:
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.execute('DELETE FROM tasks')
            missing = Path(tmp) / 'missing.db'
            with self.assertRaises(sqlite3.OperationalError):
                c.queue(missing, 1, 1000)
            self.assertFalse(missing.exists())

    def test_queue_iso_dates_invalid_dates_and_query_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queue.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE tasks(status,created_at,updated_at,lease_expires_at)')
                db.execute("INSERT INTO tasks VALUES ('queued','1970-01-01T00:00:10Z',NULL,NULL)")
            self.assertAlmostEqual(c.queue(path, 1, 1000)['hcp_queue_oldest_age_seconds'], 990, places=3)
            with sqlite3.connect(path) as db:
                db.execute("UPDATE tasks SET created_at='invalid'")
            with self.assertRaises(ValueError):
                c.queue(path, 1, 1000)
            with sqlite3.connect(path) as db:
                db.execute('DELETE FROM tasks')
                db.executemany('INSERT INTO tasks VALUES (?,?,?,?)', [('queued', 10, 10, None)] * 2000)
            # Expired progress budget interrupts aggregate scanning.
            with self.assertRaises(sqlite3.OperationalError):
                c.queue(path, 0.000000001, 1000)

    def test_backup_requires_actual_evidence_not_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'evidence.json'
            for data in [{}, {'version':1,'verified_at':50,'backup_succeeded':True,'restore_verified':False}, {'version':1,'verified_at':101,'backup_succeeded':True,'restore_verified':True}, {'version':1,'verified_at':True,'backup_succeeded':True,'restore_verified':True}]:
                path.write_text(json.dumps(data))
                os.utime(path, (100,100))
                with self.assertRaises((ValueError, KeyError)):
                    c.backup(path, 100)
            path.write_text(json.dumps({'version':1,'verified_at':50,'backup_succeeded':True,'restore_verified':True}))
            self.assertEqual(c.backup(path,100), {'backup_verified_timestamp_seconds':50})
            path.unlink()
            result = c.collect({'sources':[{'name':'backup','kind':'backup','path':str(path)}]},100)
            self.assertIn('source_success{source="backup"} 0', result)
            self.assertNotIn('smokemap_backup_verified_timestamp_seconds', result)

    def test_atomic_private_replacement_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'smokemap.prom'
            c.atomic_write(path, 'old\n')
            with patch.object(c.os, 'replace', side_effect=OSError('SECRET')):
                with self.assertRaises(OSError):
                    c.atomic_write(path, 'new\n')
            self.assertEqual(path.read_text(), 'old\n')
            self.assertEqual(list(Path(tmp).iterdir()), [path])
            c.atomic_write(path, 'new\n')
            self.assertEqual(path.read_text(), 'new\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_config_bounds_fixed_labels(self):
        for config in [{'sources':[]}, {'timeout_seconds':11,'sources':[{'name':'x','kind':'http'}]}, {'sources':[{'name':'SECRET\nURL','kind':'http'}]}, {'sources':[{'name':'x','kind':'http'}]*2}]:
            with self.assertRaises(ValueError):
                c.collect(config)

    def test_cli_diagnostic_redacted_preserves_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)/'config.json'
            output = Path(tmp)/'smokemap.prom'
            config.write_text('SECRET INVALID JSON')
            output.write_text('old')
            result = subprocess.run(['python3',str(Path(c.__file__)), '--config',str(config),'--output',str(output)],capture_output=True,text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, 'monitoring_collection_failed\n')
            self.assertEqual(result.stderr, '')
            self.assertEqual(output.read_text(), 'old')


if __name__ == '__main__':
    unittest.main()
