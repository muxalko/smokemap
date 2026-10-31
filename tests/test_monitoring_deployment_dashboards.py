"""Native dashboard/grid/query contracts and exports for the actual PromQL parser."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]/'monitoring/deployments'
BOARDS={name:json.loads((ROOT/name).read_text()) for name in ('deployments.json','web-checker.json')}


def normalize(expr):
    for variable in ('application','environment','deployment'):
        expr=expr.replace('$'+variable,'.*')
    return expr.replace('$__rate_interval','5m')


def queries():
    return [normalize(t['expr']) for b in BOARDS.values() for p in b['panels'] for t in p.get('targets',[])]


def export():
    return {'groups':[{'name':'deployment-dashboard-query-parse-only','rules':[
        {'record':f'deployment_dashboard_query_{i}','expr':q} for i,q in enumerate(queries())]}]}


def semantics():
    # Evaluate the actual worker cards/history under all freshness boundaries.
    rules=ROOT/'rules.yml'
    j='job="smokemap-monitoring",host="jenkins",instance="fixture"'
    g=j+',application="web_checker",environment="production",deployment="production"'
    targets=[normalize(t['expr']) for p in BOARDS['web-checker.json']['panels'] for t in p.get('targets',[]) if 'deployment_repeated_failure_jobs' in t['expr']]
    tests=[]
    for name,collector,up,error,observation,signalstamp,want in [('fresh',600,1,0,1,600,1),('stale',1,1,0,1,600,None),('future',601,1,0,1,600,None),('down',600,0,0,1,600,None),('textfile',600,1,1,1,600,None),('failed read',600,1,0,0,600,None),('future signal',600,1,0,1,601,None),('missing signal',600,1,0,1,None,None)]:
        series={f'up{{{j}}}':up,f'node_textfile_scrape_error{{{j}}}':error,f'deployment_collector_timestamp_seconds{{{j}}}':collector,
            f'deployment_signal_observation_success{{{g},signal="worker_status"}}':observation,
            f'deployment_repeated_failure_jobs{{{g}}}':6}
        if signalstamp is not None:series[f'deployment_signal_timestamp_seconds{{{g},signal="worker_status"}}']=signalstamp
        tests.append(dict(name=name,interval='30s',input_series=[dict(series=k,values=f'{v}x20') for k,v in series.items()],promql_expr_test=[dict(expr=f'count({q})',eval_time='10m',exp_samples=[] if want is None else [{'labels':'{}','value':want}]) for q in targets]))
    # Source test path is absolute for CLI artifacts created in RUNNER_TEMP.
    return dict(rule_files=[str(rules)],evaluation_interval='30s',tests=tests)


class DashboardTests(unittest.TestCase):
    def test_native_grid_and_identity(self):
        for name,b in BOARDS.items():
            self.assertEqual(b['uid'],{'deployments.json':'jenkins-deployments','web-checker.json':'web-checker-production'}[name])
            self.assertLessEqual(len(b['panels']),18)
            self.assertEqual(b['timezone'],'browser');self.assertEqual(b['refresh'],'30s')
            self.assertEqual(b['time'],{'from':'now-6h','to':'now'})
            self.assertEqual(b['templating']['list'][0]['name'],'DS_PROMETHEUS')
            self.assertEqual(b['templating']['list'][0]['hide'],2)
            for i,p in enumerate(b['panels']):
                self.assertIn(p['type'],('text','stat','table','state-timeline','timeseries'))
                pos=p['gridPos'];self.assertLessEqual(pos['x']+pos['w'],24)
                self.assertLessEqual(len(p.get('title','')),80)
                for other in b['panels'][:i]:
                    q=other['gridPos']
                    overlap=pos['x']<q['x']+q['w'] and q['x']<pos['x']+pos['w'] and pos['y']<q['y']+q['h'] and q['y']<pos['y']+pos['h']
                    self.assertFalse(overlap,(name,p['title'],other['title']))
                for t in p.get('targets',[]):
                    self.assertEqual(t['instant'],p['type'] in ('stat','table'))
                    self.assertTrue('deployment_collector_fresh' in t['expr'] or 'deployment_service_state' in t['expr'])
                    self.assertNotIn('vector(0)',t['expr'])
                    self.assertNotRegex(t['expr'],r'(increase|rate)\(deployment_(overdue|repeated_failure|notification)')
                if p['type'] in ('state-timeline','timeseries'):
                    default=p['fieldConfig']['defaults']
                    self.assertIs(default['custom']['spanNulls'],False)
                    self.assertIs(default['custom']['insertNulls'],False)
                    self.assertNotIn('thresholdsStyle',default['custom'])
                if p['type']=='state-timeline':self.assertEqual(p['fieldConfig']['defaults']['color']['mode'],'palette-classic')
                if p.get('fieldConfig',{}).get('defaults',{}).get('unit')=='bytes':self.assertGreaterEqual(p['fieldConfig']['defaults']['decimals'],2)
            self.assertTrue(all(link['keepTime'] and link['includeVars'] for link in b['links']))

    def test_queries_and_privacy(self):
        source=json.dumps(BOARDS)
        for forbidden in ('192.168.','localhost','trycloudflare.com','job_id','provider_url'):
            self.assertNotIn(forbidden,source)
        self.assertIn('on-host',source.lower())
        self.assertIn('bind-mounted',source)
        self.assertIn('max(3',source)
        self.assertEqual(len(export()['groups'][0]['rules']),32)

    def test_rules_cover_contract(self):
        rules=json.loads((ROOT/'rules.yml').read_text())['groups'][0]['rules']
        alerts=[r for r in rules if 'alert' in r]
        for rule in alerts:
            self.assertEqual(rule['labels']['monitoring_scope'],'deployments')
            self.assertEqual(rule['labels']['host'],'jenkins')
            self.assertIn(rule['for'],('3m','10m'))
        self.assertGreater(len(json.loads((ROOT/'rules.test.yml').read_text())['tests']),30)
        source=json.dumps(rules)
        self.assertNotIn('vector(0)',source)
        self.assertNotIn('increase(deployment_overdue',source)
        self.assertIn('WebCheckerRepeatedFailures',source)


if __name__=='__main__':
    if '--promql' in sys.argv:print(json.dumps(export(),indent=2))
    elif '--promql-tests' in sys.argv:print(json.dumps(semantics(),indent=2))
    else:unittest.main()
