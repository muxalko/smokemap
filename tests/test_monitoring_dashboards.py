"""Offline source contracts. --promql emits normalized rules for promtool parsing."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = {'overview': 'smokemap-monitoring', 'smokemap': 'smokemap-health', 'hcp': 'hcp-operations'}
DASHBOARDS = {name: json.loads((ROOT / 'monitoring/dashboards' / f'{name}.json').read_text()) for name in FILES}
CUSTOM = {
    'smokemap_collector_timestamp_seconds', 'smokemap_source_success',
    'smokemap_source_timestamp_seconds', 'smokemap_source_expected',
    'smokemap_container_running', 'smokemap_container_health',
    'smokemap_container_health_configured', 'smokemap_container_restarts_total',
    'smokemap_hcp_queue_count', 'smokemap_hcp_queue_oldest_age_seconds',
    'smokemap_hcp_expired_leases', 'smokemap_hcp_failures_last_hour',
    'smokemap_hcp_approval_waits', 'smokemap_hcp_unknown_status_count',
    'smokemap_backup_verified_timestamp_seconds',
}
HOST = {'node_cpu_seconds_total', 'node_memory_MemAvailable_bytes', 'node_memory_MemTotal_bytes',
        'node_filesystem_avail_bytes', 'node_filesystem_size_bytes',
        'node_filesystem_files_free', 'node_filesystem_files', 'node_boot_time_seconds',
        'node_textfile_scrape_error'}

def targets():
    for name, dashboard in DASHBOARDS.items():
        for panel in dashboard['panels']:
            for target in panel.get('targets', []):
                yield name, panel, target


def normalized_rules():
    """Every actual target, including instant and range targets; no mock queries."""
    return {'groups': [{'name': 'dashboard-query-parse-only', 'rules': [
        {'record': f'dashboard_query_{i}', 'expr': t['expr'].replace('$__rate_interval', '5m')}
        for i, (_, _, t) in enumerate(targets())]}]}


def backup_semantics():
    """Promtool evaluates the actual cards, including vector joins and missing series."""
    labels = 'job="smokemap-monitoring",host="jenkins",instance="fixture"'
    source_labels = labels + ',source="backup"'
    cases = [
        ('fresh', 1, 89999, 1, 90000, 0, 1),
        ('exactly_24h', 1, 3600, 1, 90000, 0, 1),
        ('older_than_24h', 1, 3599, 1, 90000, 0, 0),
        ('operator_regression_25h', 1, 1, 1, 90000, 0, 0),
        ('future_evidence', 1, 90001, 1, 90000, 0, 0),
        ('failed_source', 0, None, 1, 90000, 0, 0),
        ('claimed_success_without_timestamp', 1, None, 1, 90000, 0, None),
        ('missing_source', None, 89999, 1, 90000, 0, None),
        ('exporter_down', 1, 89999, 0, 90000, 0, None),
        ('stale_collector', 1, 89999, 1, 89819, 0, None),
        ('future_collector', 1, 89999, 1, 90001, 0, None),
        ('textfile_error', 1, 89999, 1, 90000, 1, None),
    ]
    tests = []
    for name, success, verified, up, collector, error, expected in cases:
        # Arithmetic on(job,instance,source) drops host in the success branch.
        # The failed-source scalar branch retains all source labels.
        result_labels = source_labels if success == 0 else 'job="smokemap-monitoring",instance="fixture",source="backup"'
        metrics = [
            (f'up{{{labels}}}', up),
            (f'smokemap_collector_timestamp_seconds{{{labels}}}', collector),
            (f'node_textfile_scrape_error{{{labels}}}', error),
            (f'smokemap_source_success{{{source_labels}}}', success),
            (f'smokemap_backup_verified_timestamp_seconds{{{source_labels}}}', verified),
        ]
        tests.append({
            'name': name, 'interval': '25h',
            'input_series': [{'series': metric, 'values': f'{value} {value}'}
                             for metric, value in metrics if value is not None],
            'promql_expr_test': [
                {'expr': next(p for p in DASHBOARDS[d]['panels']
                              if p['title'] == 'Backup readiness')['targets'][0]['expr'],
                 'eval_time': '25h',
                 'exp_samples': [] if expected is None else [
                     {'labels': '{' + result_labels + '}', 'value': expected}]}
                for d in ('overview', 'smokemap')],
        })
    return {'rule_files': [], 'evaluation_interval': '25h', 'tests': tests}


def observation_semantics():
    """Evaluate every actual source-age target against valid and invalid reads."""
    labels = 'job="smokemap-monitoring",host="jenkins",instance="fixture"'
    tests = []
    cases = [('valid', 1, 89940, 60), ('zero_age', 1, 90000, 0),
             ('zero_timestamp', 1, 0, None), ('negative_timestamp', 1, -1, None),
             ('future_timestamp', 1, 90001, None), ('failed_read', 0, 89940, None),
             ('missing_success', None, 89940, None), ('missing_timestamp', 1, None, None)]
    for dashboard, panel, target in targets():
        if panel['title'] not in ('Source observation age', 'Signal freshness'):
            continue
        source = re.search(r'source="([^"}]+)"', target['expr']).group(1)
        source_labels = labels + f',source="{source}"'
        for name, success, timestamp, expected in cases:
            metrics = [(f'up{{{labels}}}', 1),
                       (f'smokemap_collector_timestamp_seconds{{{labels}}}', 90000),
                       (f'node_textfile_scrape_error{{{labels}}}', 0),
                       (f'smokemap_source_success{{{source_labels}}}', success),
                       (f'smokemap_source_timestamp_seconds{{{source_labels}}}', timestamp)]
            tests.append({'name': f'{dashboard}_{source}_{name}', 'interval': '25h',
                          'input_series': [{'series': metric, 'values': f'{value} {value}'}
                                           for metric, value in metrics if value is not None],
                          'promql_expr_test': [{'expr': target['expr'], 'eval_time': '25h',
                                               'exp_samples': [] if expected is None else [
                                                   {'labels': '{' + source_labels + '}', 'value': expected}]}]})
    return tests


class DashboardContracts(unittest.TestCase):
    def test_identity_navigation_and_native_panels(self):
        self.assertEqual(len(set(d['uid'] for d in DASHBOARDS.values())), 3)
        for name, d in DASHBOARDS.items():
            with self.subTest(dashboard=name):
                self.assertEqual(d['uid'], FILES[name])
                self.assertEqual(d['refresh'], '30s')
                self.assertEqual(d['time'], {'from': 'now-6h', 'to': 'now'})
                self.assertEqual(d['timezone'], 'browser')
                self.assertEqual(d['templating']['list'][0]['name'], 'DS_PROMETHEUS')
                self.assertEqual(d['templating']['list'][0]['type'], 'datasource')
                self.assertEqual(d['templating']['list'][0]['query'], 'prometheus')
                self.assertEqual(d['templating']['list'][0]['hide'], 2)
                self.assertEqual({link['url'] for link in d['links']}, {f'/d/{uid}' for uid in FILES.values()})
                self.assertTrue(all(link['keepTime'] and link['includeVars'] for link in d['links']))
                self.assertTrue(13 <= len(d['panels']) <= 18)
                self.assertEqual(len({p['id'] for p in d['panels']}), len(d['panels']))
                self.assertTrue(all(p['type'] in {'text', 'stat', 'timeseries', 'state-timeline', 'table'} for p in d['panels']))
        self.assertEqual((ROOT / 'monitoring/grafana-dashboard.json').read_bytes(),
                         (ROOT / 'monitoring/dashboards/overview.json').read_bytes())

    def test_grid_bounds_and_no_overlaps(self):
        for name, d in DASHBOARDS.items():
            occupied = set()
            for p in d['panels']:
                with self.subTest(dashboard=name, panel=p['title']):
                    g = p['gridPos']
                    self.assertGreaterEqual(g['x'], 0)
                    self.assertGreaterEqual(g['y'], 0)
                    self.assertGreater(g['w'], 0)
                    self.assertGreater(g['h'], 0)
                    self.assertLessEqual(g['x'] + g['w'], 24)
                    cells = {(x, y) for x in range(g['x'], g['x'] + g['w']) for y in range(g['y'], g['y'] + g['h'])}
                    self.assertFalse(occupied & cells)
                    occupied |= cells

    def test_only_known_metrics_and_safe_labels(self):
        seen = set()
        for _, p, t in targets():
            q = t['expr']
            metrics = set(re.findall(r'\b([a-zA-Z_:][a-zA-Z0-9_:]*)\s*\{', q))
            self.assertLessEqual(metrics, CUSTOM | HOST | {'up', 'ALERTS'})
            seen |= metrics
            self.assertNotIn('vector(0)', q)
            self.assertNotIn('or vector', q)
            self.assertNotIn('http', q)
            self.assertNotIn('instance=', q)
            self.assertNotIn('dev_', t['legendFormat'])
            self.assertEqual(p['datasource'], {'type': 'prometheus', 'uid': '${DS_PROMETHEUS}'})
            for selector in re.findall(r'\{([^}]+)\}', q):
                if 'job="smokemap-monitoring"' in selector or 'job="linux"' in selector:
                    self.assertIn('host="jenkins"', selector)
        # Inventory has no useful changing signal; do not require a padding panel.
        self.assertLessEqual((CUSTOM - {'smokemap_source_expected'}) | HOST | {'ALERTS', 'up'}, seen)

    def test_freshness_and_missing_data_contract(self):
        for _, p, t in targets():
            q = t['expr']
            custom = set(re.findall(r'\b(smokemap_\w+)\{', q))
            if custom - {'smokemap_collector_timestamp_seconds'}:
                for fragment in ['up{job="smokemap-monitoring",host="jenkins"} == 1',
                                 'and on(job,instance)', '>= 0', '<= 180',
                                 'node_textfile_scrape_error', 'smokemap_collector_timestamp_seconds']:
                    self.assertIn(fragment, q)
            if 'smokemap_container_health{' in q:
                self.assertIn('smokemap_container_health_configured', q)
                self.assertIn('smokemap_container_running', q)
                self.assertIn('== 1', q)
            if 'smokemap_hcp_' in q or 'smokemap_backup_verified_timestamp_seconds' in q:
                self.assertIn('smokemap_source_success', q)
                self.assertIn('== 1', q)
            if p['type'] in ('timeseries', 'state-timeline'):
                self.assertIs(p['fieldConfig']['defaults']['custom']['spanNulls'], False)
                self.assertIs(p['fieldConfig']['defaults']['custom']['insertNulls'], False)
            if p['type'] == 'stat':
                self.assertTrue(t['instant'])
                self.assertFalse(t['range'])
                self.assertEqual(p['options']['reduceOptions']['calcs'], ['last'])
                special = [m for m in p['fieldConfig']['defaults']['mappings'] if m['type'] == 'special']
                self.assertTrue(special)
                self.assertIn(special[0]['options']['result']['color'], ('gray', 'orange'))

    def test_counters_gauges_units_and_alert_scope(self):
        for _, p, t in targets():
            q = t['expr']
            if 'node_cpu_seconds_total' in q:
                self.assertIn('rate(', q)
                self.assertIn('[$__rate_interval]', q)
                self.assertEqual(p['fieldConfig']['defaults']['unit'], 'percent')
            if 'smokemap_container_restarts_total' in q:
                self.assertIn('increase(', q)
                self.assertIn('[1h]' if p['title'] == 'Restarts · 1h' else '[10m]', q)
            if 'smokemap_hcp_failures_last_hour' in q:
                self.assertNotIn('increase(', q)
                self.assertNotIn('rate(', q)
            if 'ALERTS{' in q:
                self.assertIn('monitoring_scope="smokemap_hcp"', q)
                self.assertIn('alertstate="firing"', q)
            if ' or ' in q and 'ALERTS{' in q:
                self.assertIn('up{job="prometheus"}', q)
                self.assertIn('== 1', q)
            if 'smokemap_hcp_approval_waits' in q:
                self.assertIn('INFORMATIONAL', p['description'])
                self.assertEqual(p['fieldConfig']['defaults']['thresholds']['steps'], [{'color': 'blue', 'value': None}])
        payload = json.dumps(DASHBOARDS)
        for forbidden in ('histogram_quantile', 'http_requests_total', 'completed_tasks_total', 'active_workers', 'capacity_total', 'latency_seconds'):
            self.assertNotIn(forbidden, payload)

    def test_backup_gap_and_thresholds_are_visible(self):
        for name in ('overview', 'smokemap'):
            readiness = next(p for p in DASHBOARDS[name]['panels'] if p['title'] == 'Backup readiness')
            self.assertEqual(readiness['fieldConfig']['defaults']['mappings'][0]['options']['0'], {'text': 'OPEN', 'color': 'orange'})
            q = readiness['targets'][0]['expr']
            for fragment in ('smokemap_backup_verified_timestamp_seconds', '<= bool 86400',
                             '>= bool 0', 'on(job,instance,source)', '== 0', '== 1'):
                self.assertIn(fragment, q)
            self.assertEqual(readiness['fieldConfig']['defaults']['mappings'][0]['options']['1'],
                             {'text': 'READY', 'color': 'green'})
        age = next(p for p in DASHBOARDS['smokemap']['panels'] if p['title'] == 'Verified backup age')
        self.assertEqual(age['fieldConfig']['defaults']['noValue'], 'NO EVIDENCE / OPEN')
        self.assertIn({'color': 'orange', 'value': 86400}, age['fieldConfig']['defaults']['thresholds']['steps'])
        for name, title, threshold in [('overview', 'Disk space free', 15), ('overview', 'Inodes free', 10), ('hcp', 'Oldest queued', 1800)]:
            p = next(p for p in DASHBOARDS[name]['panels'] if p['title'] == title)
            self.assertIn(threshold, [s['value'] for s in p['fieldConfig']['defaults']['thresholds']['steps']])

    def test_review_regressions(self):
        p = next(p for p in DASHBOARDS['overview']['panels'] if p['title'] == 'Services / 5')
        self.assertEqual(p['fieldConfig']['defaults']['thresholds']['steps'],
                         [{'color': 'red', 'value': None}, {'color': 'green', 'value': 5}])
        p = next(p for p in DASHBOARDS['smokemap']['panels'] if p['title'] == 'Restarts · 1h')
        self.assertIn('== 5', p['targets'][0]['expr'])
        p = next(p for p in DASHBOARDS['smokemap']['panels'] if p['title'] == 'Host data volume · free space')
        self.assertEqual(p['fieldConfig']['defaults']['unit'], 'bytes')
        self.assertIn('mountpoint="/data"', p['targets'][0]['expr'])
        stats = [p['description'] for p in DASHBOARDS['hcp']['panels'] if p['type'] == 'stat']
        self.assertEqual(len(stats), len(set(stats)))
        payload = json.dumps(DASHBOARDS)
        for obsolete in ('Backup evidence remains OPEN', 'No verified backup pipeline is currently available'):
            self.assertNotIn(obsolete, payload)

    def test_semantic_fixtures_cover_both_actual_cards(self):
        tests = backup_semantics()['tests']
        self.assertEqual(len(tests), 12)
        self.assertTrue(all(len(t['promql_expr_test']) == 2 for t in tests))
        stale = next(t for t in tests if t['name'] == 'operator_regression_25h')
        self.assertTrue(all(t['exp_samples'][0]['value'] == 0 for t in stale['promql_expr_test']))

    def test_inspection_failures_describe_reads_not_health(self):
        panel = next(p for p in DASHBOARDS['smokemap']['panels'] if p['id'] == 10)
        self.assertEqual(panel['title'], 'Docker inspection failures')
        for phrase in ('1 = Docker state could not be read', '0 = successful inspection',
                       'Five-service state', 'Gaps are unknown'):
            self.assertIn(phrase, panel['description'])
        self.assertEqual(len(panel['targets']), 5)
        for target in panel['targets']:
            self.assertIn('(1 - smokemap_source_success{', target['expr'])

    def test_hcp_alert_filter_excludes_shared_and_other_sources(self):
        panel = next(p for p in DASHBOARDS['hcp']['panels'] if p['type'] == 'table')
        query = panel['targets'][0]['expr']
        matcher = re.search(r'source=~"([^"}]+)"', query).group(1)
        self.assertEqual(matcher, 'hcp_.*')
        for source in ('hcp_api', 'hcp_runtime', 'hcp_queue'):
            self.assertIsNotNone(re.fullmatch(matcher, source))
        for source in ('', 'backup', 'dev_frontend', 'frontend', 'linux'):
            self.assertIsNone(re.fullmatch(matcher, source))

    def test_observation_age_filters_invalid_and_failed_reads(self):
        observations = [(p, t) for _, p, t in targets()
                        if p['title'] in ('Source observation age', 'Signal freshness')]
        self.assertEqual(len(observations), 8)
        for panel, target in observations:
            q = target['expr']
            timestamp = re.search(r'smokemap_source_timestamp_seconds\{[^}]+\}', q).group()
            success = timestamp.replace('smokemap_source_timestamp_seconds', 'smokemap_source_success')
            self.assertTrue(q.startswith(f'((time() - ({timestamp} > 0)) >= 0)'))
            self.assertIn(f'and on(job,instance,source) ({success} == 1)', q)
            self.assertNotIn('bool', q)
            self.assertNotIn(' or ', q)
            self.assertIn('gaps', panel['description'])
        fixtures = observation_semantics()
        self.assertEqual(len(fixtures), 64)
        for fixture in fixtures:
            sample = fixture['promql_expr_test'][0]['exp_samples']
            if fixture['name'].endswith(('_valid', '_zero_age')):
                self.assertEqual(len(sample), 1)
                self.assertIn(sample[0]['value'], (0, 60))
            else:
                self.assertEqual(sample, [])

    def test_alert_tables_have_truthful_empty_cells_and_friendly_sources(self):
        aliases = {'frontend': 'Web', 'backend': 'API', 'dev_frontend': 'Web',
                   'dev_backend': 'API', 'dev_db': 'Database', 'dev_storage': 'Storage',
                   'dev_media_cleanup': 'Cleanup', 'hcp_api': 'HCP API',
                   'hcp_runtime': 'HCP runtime', 'hcp_queue': 'HCP queue', 'backup': 'Backup'}
        for dashboard in DASHBOARDS.values():
            panel = next(p for p in dashboard['panels'] if p['type'] == 'table')
            defaults = panel['fieldConfig']['defaults']
            self.assertEqual(defaults['noValue'], '—')
            self.assertEqual(defaults['mappings'][0]['options']['result']['text'], '—')
            self.assertIn('No rows means no matching firing alerts', panel['description'])
            self.assertIn('Check monitoring health', panel['description'])
            override = next(o for o in panel['fieldConfig']['overrides']
                            if o['matcher'] == {'id': 'byName', 'options': 'Source'})
            mapping = next(p['value'][0]['options'] for p in override['properties'] if p['id'] == 'mappings')
            self.assertEqual(mapping, {key: {'text': value} for key, value in aliases.items()})
            self.assertEqual(panel['transformations'][0]['options']['renameByName']['source'], 'Source')
            self.assertNotIn(' or ', panel['targets'][0]['expr'])

    def test_normalized_validation_export_covers_every_target(self):
        rules = normalized_rules()['groups'][0]['rules']
        self.assertEqual(len(rules), len(list(targets())))
        self.assertTrue(all('$' not in r['expr'] for r in rules))
        self.assertEqual(len({r['record'] for r in rules}), len(rules))


if __name__ == '__main__':
    if sys.argv[1:] == ['--promql']:
        print(json.dumps(normalized_rules(), indent=2))
    elif sys.argv[1:] == ['--promql-tests']:
        suite = backup_semantics()
        suite['tests'].extend(observation_semantics())
        print(json.dumps(suite, indent=2))
    else:
        unittest.main()
