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
    targets=[normalize(t['expr']) for p in BOARDS['web-checker.json']['panels'] for t in p.get('targets',[]) if 'deployment_repeated_failure_jobs' in t['expr'] or p['id'] in (7,18)]
    tests=[]
    for name,collector,up,error,observation,signalstamp,want in [('fresh',600,1,0,1,600,1),('stale',1,1,0,1,600,None),('future',601,1,0,1,600,None),('down',600,0,0,1,600,None),('textfile',600,1,1,1,600,None),('failed read',600,1,0,0,600,None),('future signal',600,1,0,1,601,None),('missing signal',600,1,0,1,None,None)]:
        series={f'up{{{j}}}':up,f'node_textfile_scrape_error{{{j}}}':error,f'deployment_collector_timestamp_seconds{{{j}}}':collector,
            f'deployment_signal_observation_success{{{g},signal="worker_status"}}':observation,
            f'deployment_repeated_failure_jobs{{{g}}}':6,
            f'deployment_overdue_jobs{{{g}}}':0,
            f'deployment_notification_failed_pending{{{g}}}':2,
            f'deployment_oldest_terminal_attempt_age_seconds{{{g}}}':1224}
        if signalstamp is not None:series[f'deployment_signal_timestamp_seconds{{{g},signal="worker_status"}}']=signalstamp
        tests.append(dict(name=name,interval='30s',input_series=[dict(series=k,values=f'{v}x20') for k,v in series.items()],promql_expr_test=[dict(expr=f'count({q})',eval_time='10m',exp_samples=[] if want is None else [{'labels':'{}','value':want}]) for q in targets]))
    history=next(p for p in BOARDS['web-checker.json']['panels'] if p['id']==18)
    for test in tests:
        visible=test['name']=='fresh'
        for target,metric,value in zip(history['targets'],('overdue_jobs','repeated_failure_jobs','notification_failed_pending'),(0,6,2)):
            test['promql_expr_test'].append(dict(expr=normalize(target['expr']),eval_time='10m',
                exp_samples=[dict(labels='deployment_'+metric+'{'+g+'}',value=value)] if visible else []))
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
        self.assertEqual(len(export()['groups'][0]['rules']),34)

    def test_simultaneous_history_targets(self):
        panel=next(p for p in BOARDS['web-checker.json']['panels'] if p['id']==18)
        self.assertEqual([t['refId'] for t in panel['targets']],list('ABC'))
        for target,metric,legend in zip(panel['targets'],('overdue_jobs','repeated_failure_jobs','notification_failed_pending'),
                ('Overdue jobs','Repeated failure jobs','Failed pending deliveries')):
            self.assertTrue(target['expr'].startswith('deployment_'+metric+'{'))
            self.assertNotIn(' or ',target['expr'])
            self.assertEqual(target['legendFormat'],legend)
        fresh=semantics()['tests'][0]
        for metric in ('overdue_jobs','repeated_failure_jobs','notification_failed_pending'):
            self.assertTrue(any(x['series'].startswith('deployment_'+metric+'{') for x in fresh['input_series']))
        self.assertEqual(len(fresh['promql_expr_test'][-3:]),3)

    def test_information_cards_are_blue(self):
        for board,ids in [('deployments.json',(2,3,6)),('web-checker.json',(7,))]:
            for panel in [p for p in BOARDS[board]['panels'] if p['id'] in ids]:
                self.assertEqual(panel['fieldConfig']['defaults']['color'],{'mode':'fixed','fixedColor':'blue'})

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
