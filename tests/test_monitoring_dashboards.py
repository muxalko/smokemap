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
        self.assertLessEqual(CUSTOM | HOST | {'ALERTS', 'up'}, seen)

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
                self.assertEqual(p['fieldConfig']['defaults']['custom']['insertNulls'], 90000)
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
                self.assertIn('[10m]', q)
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
        age = next(p for p in DASHBOARDS['smokemap']['panels'] if p['title'] == 'Verified backup age')
        self.assertEqual(age['fieldConfig']['defaults']['noValue'], 'NO EVIDENCE / OPEN')
        self.assertIn({'color': 'orange', 'value': 86400}, age['fieldConfig']['defaults']['thresholds']['steps'])
        for name, title, threshold in [('overview', 'Disk space free', 15), ('overview', 'Inodes free', 10), ('hcp', 'Oldest queued task', 1800)]:
            p = next(p for p in DASHBOARDS[name]['panels'] if p['title'] == title)
            self.assertIn(threshold, [s['value'] for s in p['fieldConfig']['defaults']['thresholds']['steps']])

    def test_normalized_validation_export_covers_every_target(self):
        rules = normalized_rules()['groups'][0]['rules']
        self.assertEqual(len(rules), len(list(targets())))
        self.assertTrue(all('$' not in r['expr'] for r in rules))
        self.assertEqual(len({r['record'] for r in rules}), len(rules))


if __name__ == '__main__':
    if sys.argv[1:] == ['--promql']:
        print(json.dumps(normalized_rules(), indent=2))
    else:
        unittest.main()
