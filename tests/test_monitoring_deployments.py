"""Offline fixtures only. No Docker daemon, host network, production config or DB."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, call, MagicMock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'monitoring/deployments'
sys.path.insert(0, str(SOURCE))
import common
import docker_metadata as dm
import inventory
import probes
import resources
import webchecker
import webchecker_helper as helper
spec = importlib.util.spec_from_file_location('deployments_collector', SOURCE / 'collector.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
NOW = 1800000000
DATE = '2026-01-01T00:00:00Z'
CONFIG = dict(version=1, quick_state_path='/private/state.json', local_ca_path='/public/ca.crt')


def row(project='smokemap', service='backend', identity='a'*64, health='healthy', running=True):
    return [identity, '/private-container', project, service, running, health, 2,
            'sha256:'+'b'*64, 'c'*40, DATE, DATE if running else '0001-01-01T00:00:00Z']


def offline(rows=None, stats=None, calls=None):
    with ExitStack() as stack:
        stack.enter_context(patch.object(c, 'snapshot', return_value=rows or []))
        for name in ('host_probe', 'exec_probe', 'local_probe', 'supervisor_probe'):
            mock = stack.enter_context(patch.object(c, name, return_value=1))
            if calls is not None: calls[name] = mock
        stack.enter_context(patch.object(c, 'quick_state', return_value={'connectors':{
            'quick-app':{'origin':'https://fake-app.trycloudflare.com'},
            'quick-media':{'origin':'https://fake-media.trycloudflare.com'}}}))
        stack.enter_context(patch.object(c, 'aggregate', return_value={'scheduled_jobs':7}))
        stack.enter_context(patch.object(c, 'maintenance', return_value={'maintenance_completion_present':0}))
        stack.enter_context(patch.object(c, 'command', return_value=stats or b''))
        return c.collect(CONFIG)


class MetadataTests(unittest.TestCase):
    def test_inventory_exact(self):
        self.assertEqual(len(inventory.SERVICES),20)
        self.assertEqual([len(g[-1]) for g in inventory.GROUPS],[5,7,6,2])
        self.assertIn('quick-media', inventory.GROUPS[1][-1])

    def test_state_matrix(self):
        for running, health, expected in [(False,'healthy',0),(True,'starting',1),
                (True,'unhealthy',1),(True,'none',2),(True,'healthy',3)]:
            with self.subTest(running=running,health=health):
                _, values = dm.observe([row(health=health,running=running)],'smokemap','backend',NOW)
                self.assertEqual(values['state'],expected)
                self.assertEqual(values['health_configured'],int(health!='none'))

    def test_missing_vs_duplicate(self):
        self.assertEqual(dm.observe([],'smokemap','backend',NOW)[1],dict(present=0,running=0,state=0))
        with self.assertRaises(ValueError):
            dm.observe([row(),row()],'smokemap','backend',NOW)

    def test_bad_metadata(self):
        for index,value in [(4,'true'),(5,'invalid'),(6,-1),(7,'tag:latest'),(9,'future'),(10,None)]:
            item=row();item[index]=value
            with self.subTest(index=index),self.assertRaises((ValueError,TypeError,AttributeError)):
                dm.observe([item],'smokemap','backend',NOW)

    def test_image_revision_safe(self):
        item=row();item[8]='private/token'
        self.assertEqual(dm.observe([item],'smokemap','backend',NOW)[1]['container_info']['image_revision'],'unknown')

    def test_snapshot_fake_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            docker=Path(temp)/'docker'
            docker.write_text('#!/usr/bin/env python3\nimport sys\n'
                'if sys.argv[1]=="ps": print('+repr('a'*64)+')\n'
                'elif sys.argv[1]=="inspect": print('+repr(json.dumps(row()))+')\n'
                'else: sys.exit(1)\n')
            docker.chmod(0o700)
            with patch.dict(os.environ,PATH=temp+os.pathsep+os.environ['PATH']):
                self.assertEqual(dm.snapshot(),[row()])
        self.assertNotIn('.Config.Env',dm.FORMAT)
        self.assertNotIn('.State.Health.Log',dm.FORMAT)
        self.assertNotIn('{{json .Config.Labels}}',dm.FORMAT)

    def test_snapshot_rejects_bad_ids(self):
        with patch.object(dm,'command',return_value=b'not-an-id'):
            with self.assertRaises(ValueError):dm.snapshot()


class ResourceTests(unittest.TestCase):
    def test_units(self):
        for text,value in [('1 B',1),('1.5KiB',1536),('2 MB',2000000),('2GiB',2147483648),('3kB',3000)]:
            self.assertEqual(resources.memory(text),value)
        for text in ('1GBsecret','nanB','-1B','1XB','inf%'):
            with self.assertRaises(ValueError):resources.memory(text)

    def test_multicore_and_errors(self):
        raw=json.dumps(['a'*64,'201.25%','1MiB / 2MiB','50.00%','12']).encode()
        self.assertEqual(resources.parse_stats(raw)['a'*64]['cpu_percent'],201.25)
        self.assertEqual(resources.parse_stats(raw)['a'*64]['memory_usage_bytes'],1048576)
        for cpu,mem,percentage,pids in [('NaN%','1B / 2B','50%','1'),('1%','3B / 2B','50%','1'),
                 ('1%','1B / 2B','101%','1'),('1%','1B / 2B','50%','-1')]:
            with self.assertRaises(ValueError):
                resources.parse_stats(json.dumps(['a'*64,cpu,mem,percentage,pids]).encode())
        with self.assertRaises(ValueError):resources.parse_stats(raw+b'\n'+raw)


class ProbeTests(unittest.TestCase):
    def test_https_allowlist(self):
        self.assertEqual(probes.quick_origin('https://fake-host.trycloudflare.com'),'fake-host.trycloudflare.com')
        for value in ['http://x.trycloudflare.com','https://x.trycloudflare.com:443','https://x.trycloudflare.com/',
                      'https://x.trycloudflare.com?secret=x','https://x.trycloudflare.com.evil','https://u:p@x.trycloudflare.com']:
            with self.assertRaises(ValueError):probes.quick_origin(value)

    def test_supervisor_pid_reuse_and_spaces(self):
        state={'supervisor':{'pid':42,'proc_start':'123'}}
        with tempfile.TemporaryDirectory() as temp:
            proc=Path(temp);(proc/'42').mkdir()
            path=proc/'42/stat'
            path.write_text('42 (name with (spaces)) '+' '.join(['S']+['0']*18+['123']))
            self.assertEqual(probes.supervisor_probe(state,proc),1)
            state['supervisor']['proc_start']='124'
            self.assertEqual(probes.supervisor_probe(state,proc),0)
            path.unlink()
            self.assertEqual(probes.supervisor_probe(state,proc),0)
        self.assertEqual(probes.supervisor_probe({}),0)

    def test_http_network_vs_execution(self):
        with patch('http.client.HTTPConnection',side_effect=ConnectionRefusedError):
            self.assertEqual(probes.http_probe('127.0.0.1',3000,'/'),0)
        with patch.object(probes,'command',return_value=b'secret response'):
            with self.assertRaises(ValueError):probes.exec_probe('a'*64,False)
        self.assertIn('signal.alarm(3)',probes.PYTHON)
        self.assertIn('3000',probes.NODE)

    def test_staging_backend_fixed_headers_and_status(self):
        # Execute the exact embedded probe without network or Docker. Redirects
        # and bad hosts fail; the only accepted response is 200, without a read.
        for status,want in ((200,'1'),(301,'0'),(400,'0'),(503,'0')):
            connection=MagicMock()
            connection.getresponse.return_value.status=status
            with patch('http.client.HTTPConnection',return_value=connection) as factory, \
                    patch('signal.signal'),patch('signal.alarm'),patch('builtins.print') as output:
                exec(probes.PYTHON,{})
            factory.assert_called_once_with('127.0.0.1',8000,timeout=2.5)
            connection.request.assert_called_once_with('GET','/health/ready/',
                headers={'Host':'api.smokemap-staging.internal','X-Forwarded-Proto':'https'})
            connection.getresponse.return_value.read.assert_not_called()
            connection.close.assert_called_once()
            self.assertEqual(str(output.call_args.args[0]),want)

    def test_development_host_and_staging_exec_routing(self):
        calls={}
        offline(rows=[row(project='smokemap-quick-staging',identity='a'*64),
                      row(project='smokemap-local-staging',identity='b'*64)],calls=calls)
        calls['host_probe'].assert_has_calls([call('127.0.0.1',3000,'/'),
            call('127.0.0.1',8000,'/health/ready/')],any_order=True)
        self.assertCountEqual(calls['exec_probe'].call_args_list,[call('a'*64,False),call('b'*64,False)])

    def test_curl_policy(self):
        code=(SOURCE/'curl_probe.py').read_text()
        for required in ('--resolve','--cacert','--max-time','--output','--noproxy','--disable'):
            self.assertIn(required,code)
        self.assertNotIn('--insecure',code)


class AggregateTests(unittest.TestCase):
    def database(self,path):
        with sqlite3.connect(path) as db:
            db.executescript('''PRAGMA user_version=3;
                CREATE TABLE job_status(job_id TEXT PRIMARY KEY,last_success_at TEXT,last_failure_at TEXT,consecutive_failures INTEGER);
                CREATE TABLE notification_outbox(delivered_at TEXT,attempts INTEGER,checked_at TEXT);
                CREATE TABLE operational_alert_outbox(delivered_at TEXT,attempts INTEGER,created_at TEXT);''')
            db.executemany('INSERT INTO job_status VALUES(?,?,?,?)',[
                ('hourly',DATE,'2026-01-01T00:10:00Z',6),('fast',DATE,None,0),('disabled',DATE,None,30)])

    def test_schedule_terminal_failure_and_queues_readonly(self):
        now=helper.stamp('2026-01-01T00:20:00Z',NOW)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.db';self.database(path)
            before=path.read_bytes()
            result=helper.worker(path,{'hourly':3600,'fast':300,'missing':300},now)
            self.assertEqual(result['scheduled_jobs'],3)
            self.assertEqual(result['missing_status_jobs'],1)
            self.assertEqual(result['overdue_jobs'],1) # fast age1200 equals threshold: not overdue
            self.assertEqual(result['repeated_failure_jobs'],1)
            self.assertEqual(result['oldest_terminal_attempt_age_seconds'],1200)
            self.assertEqual(result['oldest_pending_age_seconds'],0)
            self.assertEqual(path.read_bytes(),before)
            with sqlite3.connect(path) as db:
                db.execute('INSERT INTO notification_outbox VALUES(NULL,2,?)',(DATE,))
                db.execute('INSERT INTO operational_alert_outbox VALUES(NULL,0,?)',(DATE,))
            result=helper.worker(path,{'hourly':3600},now)
            self.assertEqual(result['notification_pending'],1)
            self.assertEqual(result['notification_failed_pending'],1)
            self.assertEqual(result['operational_pending'],1)
            self.assertEqual(result['oldest_pending_age_seconds'],1200)

    def test_empty_active_set_missing_schema_and_future(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.db';self.database(path)
            result=helper.worker(path,{},NOW)
            self.assertEqual(result['scheduled_jobs'],0)
            self.assertNotIn('oldest_terminal_attempt_age_seconds',result)
            with self.assertRaises(ValueError):helper.worker(path,{'hourly':3600},100)
            with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=2')
            with self.assertRaises(ValueError):helper.worker(path,{},NOW)
            missing=Path(temp)/'absent.db'
            with self.assertRaises(sqlite3.OperationalError):helper.worker(missing,{},NOW)
            self.assertFalse(missing.exists())

    def test_read_lock_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.db';self.database(path)
            with sqlite3.connect(path) as db:
                db.execute('BEGIN EXCLUSIVE')
                start=time.monotonic()
                with self.assertRaises(sqlite3.OperationalError):helper.worker(path,{},NOW)
                self.assertLess(time.monotonic()-start,2.5)

    def test_query_progress_deadline(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.db';self.database(path)
            with sqlite3.connect(path) as db:
                db.executemany('INSERT INTO notification_outbox VALUES(NULL,0,?)',[(DATE,)]*1000)
            calls=iter([0]+[10]*100)
            with patch.object(helper.time,'monotonic',side_effect=lambda:next(calls)):
                with self.assertRaises(sqlite3.OperationalError):helper.worker(path,{},NOW)

    def test_bad_timestamps_and_queue_attempts(self):
        for date in ('2026-01-01T00:00:00','2099-01-01T00:00:00Z','bad'):
            with self.assertRaises(ValueError):helper.stamp(date,NOW)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.db';self.database(path)
            with sqlite3.connect(path) as db:db.execute('INSERT INTO notification_outbox VALUES(NULL,-1,?)',(DATE,))
            with self.assertRaises(ValueError):helper.worker(path,{},NOW)

    def test_schedule_config_filter_and_bounded_snapshot(self):
        from types import SimpleNamespace as NS, ModuleType
        loader=ModuleType('web_checker.config')
        seen=[]
        def load(path):
            seen.append(Path(path).read_bytes())
            return NS(jobs=(NS(id='enabled',enabled=True,schedule=NS(interval_seconds=300)),
                            NS(id='disabled',enabled=False,schedule=NS(interval_seconds=300)),
                            NS(id='manual',enabled=True,schedule=None)))
        loader.load_config=load
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.yaml';path.write_bytes(b'synthetic snapshot')
            with patch.dict(sys.modules,{'web_checker.config':loader}):
                self.assertEqual(helper.schedules(path),{'enabled':300})
                self.assertEqual(seen,[b'synthetic snapshot'])
                path.write_bytes(b'x'*(helper.LIMIT+1))
                with self.assertRaises(ValueError):helper.schedules(path)

    def test_missing_status_has_no_fabricated_age(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.db';self.database(path)
            result=helper.worker(path,{'absent':300},NOW)
            self.assertEqual(result['missing_status_jobs'],1)
            self.assertEqual(result['overdue_jobs'],1)
            self.assertNotIn('oldest_terminal_attempt_age_seconds',result)

    def test_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            self.assertEqual(helper.backup(directory,NOW),dict(backup_manifest_present=0,backup_manifest_valid=0))
            name='web-checker-20260101T000000Z.db';(directory/name).write_bytes(b'1234')
            manifest=dict(completed_at=DATE,path=name,bytes=4)
            path=directory/'last-backup.json'
            for overrides,valid in [({},1),({'path':'../'+name},0),({'path':'/outside/'+name},0),
                    ({'bytes':3},0),({'bytes':0},0),({'completed_at':'2099-01-01T00:00:00Z'},0),
                    ({'path':'arbitrary.db'},0)]:
                path.write_text(json.dumps(dict(manifest,**overrides)))
                result=helper.backup(directory,NOW)
                self.assertEqual(result['backup_manifest_valid'],valid)
                if not valid:self.assertNotIn('backup_completed_timestamp_seconds',result)
            path.write_text(json.dumps(manifest));(directory/name).unlink();(directory/name).symlink_to(path)
            self.assertEqual(helper.backup(directory,NOW)['backup_manifest_valid'],0)

    def test_logs_anchored_and_failure_order(self):
        raw=b'2026-01-01T00:00:00Z maintenance event=failed error=PRIVATE\n2026-01-01T00:01:00Z maintenance event=completed backup=PRIVATE\n2026-01-01T00:02:00Z maintenance event=failed error=PRIVATE\n2026-01-01T00:03:00Z other maintenance event=completed\n'
        result=webchecker.maintenance_logs(raw,NOW)
        self.assertEqual(result['maintenance_failures_after_success'],1)
        self.assertNotIn('PRIVATE',str(result))
        self.assertEqual(webchecker.maintenance_logs(b'2026-01-01T00:00:00Z maintenance event=failed error=x',NOW),{'maintenance_completion_present':0})
        with self.assertRaises(ValueError):webchecker.maintenance_logs(b'2099-01-01T00:00:00Z maintenance event=completed',NOW)

    def test_host_rejects_nonaggregate_payload(self):
        with patch.object(webchecker,'command',return_value=b'{"provider_url":"PRIVATE"}'):
            with self.assertRaises(ValueError) as error:webchecker.aggregate('a'*64,'worker')
            self.assertNotIn('PRIVATE',str(error.exception))

    def test_helper_boundaries(self):
        source=(SOURCE/'webchecker_helper.py').read_text()
        self.assertIn('mode=ro',source)
        self.assertIn('query_only = ON',source)
        self.assertIn('signal.alarm(3)',source)
        self.assertIn('set_progress_handler',source)
        self.assertNotIn('SQLiteObservationStore',source)
        self.assertNotIn('import web_checker.storage',source)
        self.assertNotIn('last_error',source)


class CollectorTests(unittest.TestCase):
    def test_valid_missing_and_no_health(self):
        rendered=offline([row('web-checker-production','maintenance',health='none')])
        self.assertEqual(sum(line.startswith('deployment_expected{') for line in rendered.splitlines()),20)
        self.assertIn('deployment_state{application="web_checker",deployment="production",environment="production",service="maintenance"} 2',rendered)
        self.assertIn('deployment_resource_success{application="web_checker",deployment="production",environment="production",service="maintenance"} 0',rendered)
        self.assertNotIn('private-container',rendered)
        self.assertNotIn('a'*64,rendered)

    def test_complete_inventory_resources_and_concurrency(self):
        import threading
        rows=[row(project,labels['service'],identity=f'{i:064x}') for i,(labels,project) in enumerate(inventory.SERVICES)]
        raw='\n'.join(json.dumps([item[0],'250%','1MiB / 2MiB','50%','12']) for item in rows).encode()
        active=0;maximum=0;guard=threading.Lock()
        def bounded_task(*args):
            nonlocal active,maximum
            with guard:active+=1;maximum=max(maximum,active)
            time.sleep(0.005)
            with guard:active-=1
            return 1
        with ExitStack() as stack:
            stack.enter_context(patch.object(c,'snapshot',return_value=rows))
            stack.enter_context(patch.object(c,'command',return_value=raw))
            for name in ('host_probe','exec_probe','local_probe','supervisor_probe'):
                stack.enter_context(patch.object(c,name,side_effect=bounded_task))
            stack.enter_context(patch.object(c,'quick_state',return_value={'connectors':{
                'quick-app':{'origin':'https://fake-app.trycloudflare.com'},
                'quick-media':{'origin':'https://fake-media.trycloudflare.com'}}}))
            stack.enter_context(patch.object(c,'aggregate',return_value={'scheduled_jobs':7}))
            stack.enter_context(patch.object(c,'maintenance',return_value={'maintenance_completion_present':0}))
            result=c.collect(CONFIG)
        self.assertGreater(maximum,1);self.assertLessEqual(maximum,4)
        self.assertEqual(sum(line.startswith('deployment_cpu_percent{') for line in result.splitlines()),20)
        self.assertEqual(sum(line.startswith('deployment_observation_success{') and line.endswith(' 1') for line in result.splitlines()),20)

    def test_stopped_quick_connector_is_expected_down(self):
        rendered=offline([row('smokemap-quick-staging','quick-app',running=False)])
        labels='application="smokemap",deployment="quick",environment="staging",service="quick-app"'
        self.assertIn('deployment_expected{'+labels+'} 1',rendered)
        self.assertIn('deployment_state{'+labels+'} 0',rendered)
        self.assertIn('deployment_observation_success{'+labels+'} 1',rendered)
        self.assertNotIn('deployment_cpu_percent{'+labels,rendered)

    def test_duplicate_is_unknown(self):
        rendered=offline([row(),row()])
        labels='application="smokemap",deployment="development",environment="development",service="backend"'
        self.assertIn('deployment_observation_success{'+labels+'} 0',rendered)
        self.assertNotIn('deployment_state{'+labels,rendered)

    def test_failed_snapshot_does_not_invent_down(self):
        with patch.object(c,'snapshot',side_effect=ValueError('PRIVATE')):
            # Patch the snapshot within offline would replace it: run separate
            # empty collection then directly exercise the failure path here.
            with patch.object(c,'host_probe',return_value=0),patch.object(c,'quick_state',side_effect=ValueError),patch.object(c,'local_probe',side_effect=ValueError):
                result=c.collect(CONFIG)
        self.assertNotIn('deployment_state{',result)
        self.assertNotIn('PRIVATE',result)
        self.assertEqual(sum(l.endswith(' 0') and l.startswith('deployment_observation_success') for l in result.splitlines()),20)

    def test_config_and_atomic_permissions(self):
        with self.assertRaises(ValueError):c.collect(dict(CONFIG,extra='secret'))
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);directory.chmod(0o700);path=directory/'deployments.prom'
            common.atomic_write(path,'original')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            bad=directory/'bad.json';bad.write_text('{}')
            proc=subprocess.run([sys.executable,str(SOURCE/'collector.py'),'--config',str(bad),'--output',str(path)],capture_output=True)
            self.assertEqual(proc.returncode,1)
            self.assertEqual(proc.stdout,b'deployment_collection_failed\n')
            self.assertEqual(proc.stderr,b'')
            self.assertEqual(path.read_text(),'original')
            directory.chmod(0o755)
            with self.assertRaises(ValueError):common.atomic_write(path,'bad')

    def test_lock_overlap_and_owned_output(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);directory.chmod(0o700)
            config=directory/'config.json';config.write_text(json.dumps(CONFIG))
            path=directory/'deployments.prom';path.write_text('original')
            lock=directory/'.deployments.lock';lock.touch(mode=0o600)
            with lock.open('w') as stream:
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                result=subprocess.run([sys.executable,str(SOURCE/'collector.py'),'--config',str(config),'--output',str(path)],capture_output=True)
                self.assertEqual(result.returncode,1)
                self.assertEqual(path.read_text(),'original')
            original=directory/'smokemap.prom';original.write_text('preserve')
            result=subprocess.run([sys.executable,str(SOURCE/'collector.py'),'--config',str(config),'--output',str(original)],capture_output=True)
            self.assertEqual(result.returncode,1)
            self.assertEqual(original.read_text(),'preserve')

    def test_bounded_command_redacts_timeout_and_overflow(self):
        for script in ['import time;time.sleep(2)', 'print("PRIVATE"*20000)']:
            with self.assertRaises(ValueError) as caught:
                common.command([sys.executable,'-c',script],0.2)
            self.assertNotIn('PRIVATE',str(caught.exception))


if __name__=='__main__':unittest.main()
