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
time and variables. The portable datasource variable is hidden by default for the
one-datasource installation; the operator binds its current UID at publication.
Default is last six hours, browser timezone, 30s refresh;
the 24-column desktop layout uses a shallow header and spacious trend rows.
Grafana stacks panels on smaller screens; compact readability still needs QA.

## Signal semantics

Custom operational queries require the `smokemap-monitoring` exporter to be up,
collector age between 0 and 180 seconds, and a readable textfile. Joins use
`job,instance`, preserving each source. Queue and backup age additionally require
a successful source read. Docker state requires a configured healthcheck and
combines running with health. Unsupported/missing health is **UNKNOWN**; failed
health is red. Stat queries are instant and use the last value, avoiding a
previous non-null healthy sample. Timelines expose 0/1 and preserve null gaps.
No fixed disconnect threshold is used, so valid 2m/5m query steps at longer
ranges stay connected while actual nulls remain unbridged. Source-age trends
require successful reads and positive, non-future timestamps; invalid observations
are gaps instead of epoch-sized spikes. Docker inspection failures reports only
unreadable Docker state, not unhealthy containers; Five-service state shows health.

Aggregate availability requires both named probes; the service count requires
all five service observations. Missing data cannot reduce the denominator.
Host metrics use the existing `linux` job and fixed `host="jenkins"`; custom
metrics use the same static host. The live installation must supply the static
`host="jenkins"` scrape label on both jobs and `monitoring_scope="smokemap_hcp"`
on scoped alert rules. These labels are required query inputs; the source example
scrape/rules do not supply them. Preserve the installed labels when publishing;
this change does not modify collectors, scrape configuration or rules. No private
instance addresses are embedded.

Backup readiness is **READY** only when a successful evidence read has a verified
backup and restore timestamp aged 0–86400s. Failed reads, older evidence and future
evidence show **OPEN**; claimed success without a timestamp remains **UNKNOWN**.
Missing verified age reads **NO EVIDENCE / OPEN**, never a zero-age backup.
Never create synthetic backup evidence. Collector age warns at 180s, queue age at
1800s, expired leases above zero, disk space below 15% free and inodes below 10%
free. Root and data mounts are shown individually. CPU uses counter rate;
restart history uses per-service 10m counter increases, while the headline shows
an aggregate 1h increase requiring all five services. The data-volume bytes trend
shows shared host storage. One-hour failures remain a rolling gauge.

Blocked / approval waits include blocked tasks and are blue informational values,
not a count exclusively of human approvals. No active worker, capacity, completed
throughput, HTTP rate, p95 latency or submission-throughput metrics are implied.

Alert tables show only `monitoring_scope="smokemap_hcp"`, firing state, alert
name, source and severity; other host/job alerts remain in existing dashboards.
The HCP table includes only sources matching `hcp_.*`. Shared alerts without a
source, backup alerts and host alerts are available in Overview; Smokemap also
includes shared monitoring failures. Source cells map known aliases to friendly
names without changing query labels. Missing cells use an em dash; no rows means
no matching firing alerts. A legitimate zero alert count is anchored to a live
Prometheus self scrape; operational metrics never get zero fallbacks. Empty alert tables do not
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
python3 tests/test_monitoring_dashboards.py --promql-tests > /tmp/dashboard-semantics.json
promtool test rules /tmp/dashboard-semantics.json
```

The export replaces `$__rate_interval` with `5m`. The output is a **parse-only
validation artifact**, not a rule file to install. Offline tests enforce JSON
identity, navigation, native panel types, grid bounds/overlap, known metric
coverage, gates, missing-state handling, units, counters and informational waits.
CI uses the Prometheus parser on all exported queries and evaluates synthetic
backup-readiness cases against both actual dashboard expressions (fresh, 24h
boundary, old, future, absent evidence, failed source, exporter down, stale/future
collector and textfile errors), plus every source-age target with valid, zero,
negative, future, missing and failed-read observations. Fixtures contain no live
metrics. Static tests do not prove live label cardinality, data freshness, rendering or operational behavior.

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
