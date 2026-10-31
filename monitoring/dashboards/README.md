# Smokemap / HCP native Grafana suite

Source for Grafana **11.3.1**, using built-in panels only. No dashboard has been
published or visually validated by this source change. The primary operator owns
live PromQL validation, browser QA, folder assignment and publication. No global
preferences, collectors, rules, routes or notification settings change here.

| Source | Stable UID | Purpose |
| --- | --- | --- |
| `overview.json` | `smokemap-monitoring` | Six headline signals, CPU/memory, core services, disk/inodes and alert context |
| `smokemap.json` | `smokemap-health` | Five development services, restart history, source failures and recovery evidence |
| `hcp.json` | `hcp-operations` | API/runtime, queue age/count, leases, rolling failures and informational blocked waits |

`../grafana-dashboard.json` is an exact copy of Overview, preserving the old
bookmark and import entrypoint. Edit both copies together. Navigation preserves
time and variables. Default is last six hours, browser timezone, 30s refresh;
the 24-column desktop layout uses a shallow header and spacious trend rows.
Grafana stacks panels on smaller screens; compact readability still needs QA.

## Signal semantics

Custom operational queries require the `smokemap-monitoring` exporter to be up,
collector age between 0 and 180 seconds, and a readable textfile. Joins use
`job,instance`, preserving each source. Queue and backup age additionally require
a successful source read. Docker state requires a configured healthcheck and
combines running with health. Unsupported/missing health is **UNKNOWN**; failed
health is red. Stat queries are instant and use the last value, avoiding a
previous non-null healthy sample. Timelines expose 0/1 and preserve null gaps;
90s gap insertion allows for 30s scrape cadence without bridging long outages.

Aggregate availability requires both named probes; the service count requires
all five service observations. Missing data cannot reduce the denominator.
Host metrics use the existing `linux` job and fixed `host="jenkins"`; custom
metrics use the same static host. No private instance addresses are embedded.

Backup readiness currently reads **OPEN** and verified age **NO EVIDENCE / OPEN**.
There is no verified pipeline. Readiness reports evidence presence separately
from its age: evidence older than 86400s is amber. Never create synthetic backup
evidence. Collector age warns at 180s, queue age at 1800s, expired leases above
zero, disk space below 15% free and inodes below 10% free. Root and data mounts
are shown individually. CPU uses counter rate, restart history uses a 10m
counter increase, and one-hour failures remain a rolling gauge.

Blocked / approval waits include blocked tasks and are blue informational values,
not a count exclusively of human approvals. No active worker, capacity, completed
throughput, HTTP rate, p95 latency or submission-throughput metrics are implied.

Alert tables show only `monitoring_scope="smokemap_hcp"`, firing state, alert
name, source and severity; other host/job alerts remain in existing dashboards.
The Smokemap and HCP tables include alerts without a source for shared monitoring
failures. A legitimate zero alert count is anchored to a live Prometheus self
scrape; operational metrics never get zero fallbacks. Empty alert tables do not
prove health or notification delivery. Descriptions document coverage, not private
diagnostics, paths, task content or secrets.

## Offline checks

No dependencies, Docker, host services or network are needed:

```sh
make test-monitoring
# Dashboard-only checks:
python3 -m unittest discover -s tests -p test_monitoring_dashboards.py -v
# Export every actual target as normalized Prometheus recording-rule expressions:
python3 tests/test_monitoring_dashboards.py --promql > /tmp/dashboard-queries.json
# When an existing promtool is available (also run in CI):
promtool check rules /tmp/dashboard-queries.json
```

The export replaces `$__rate_interval` with `5m`. The output is a **parse-only
validation artifact**, not a rule file to install. Offline tests enforce JSON
identity, navigation, native panel types, grid bounds/overlap, known metric
coverage, gates, missing-state handling, units, counters and informational waits.
CI uses the Prometheus parser on all exported queries. Static tests do not prove
live label cardinality, data freshness, rendering or operational behavior.

## Primary operator handoff (not executed)

1. Review the exact PR head independently and wait for required CI before merge.
   Keep corrections on the same issue/branch/PR. This source author stops before
   merge or publication.
2. Validate every target against live Prometheus as its actual instant or range
   query. Use `5m` for `$__rate_interval` in normalized samples; verify host/source
   labels and unique per-instance joins. Check healthy, failed, missing, stale,
   future collector timestamp, exporter-down and unsupported Docker-health cases.
   Confirm zero alerts with live Prometheus and unknown with self scrape down.
3. Publish through the existing Grafana API in the dedicated folder supplied by
   the primary, retaining all three UIDs. Set the existing Prometheus UID as the
   `DS_PROMETHEUS` datasource variable's current selection; retain the datasource
   reference `${DS_PROMETHEUS}`. Import Overview only once (legacy file is a copy).
4. Inspect desktop and compact browser layouts: status text, legends, crosslinks
   with time/datasource selection, service gaps, trend units, concise alert rows
   and visible OPEN backup gap. Confirm actual health is teal/green, information
   blue, readiness amber, failures red, and unknown never green. Record real QA
   evidence separately; source tests cannot establish it.

Preserve the existing Telegram primary and optional email behavior. Delivery and
recovery proof for both original and scoped firing/recovery pairs remain primary
operator acceptance; this suite does not test or alter alert delivery.
