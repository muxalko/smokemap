# HCP / Smokemap monitoring source package

Source only. No host installation, notification delivery, backup validation or
runtime health is claimed. The collector requires Python 3 stdlib. The operator
owns deployment and independent exact-head review. Existing apps, the 9100
exporter, linux scrape job, Telegram receiver and cleanup email monitor stay
running. Host changes below are operator instructions, not executed by this PR.

## Privacy and metrics contract

`collector.py` performs one bounded pass, replacing only `smokemap.prom` via a
0600 temporary file, fsync and atomic rename in a private 0700 directory. It
emits no source diagnostics. A top-level failure returns 1 and prints only
`monitoring_collection_failed`; the old file remains and freshness alerts fire.
Per-source failures emit success=0 and timestamp=0 and omit that source's result
metrics. Other sources still run. A 30s timer plus 150s service timeout bounds
an entire pass (at most 20 sources, each timeout <=10s; an overlong pass is
terminated without replacing the previous file). Default 11 sources take at
most about 55 seconds when all fail. Operator must retain the 150s service cap.

Every metric has prefix `smokemap_`. Only configured, validated `source` aliases
become labels. No task IDs, prompts, error text, tokens, paths, URLs, discovered
container names or response data enter metrics/logs. Prometheus adds fixed job
and instance labels. Config is trusted, private operator input; do not put secrets
in it. The example contains deliberately unusable Docker container placeholders.

* `collector_timestamp_seconds`: pass completion snapshot timestamp (set at pass
  start, conservatively including collection duration in its age).
* `source_expected`, `source_success`, `source_timestamp_seconds`: inventory,
  source read/health success and freshness. HTTP success requires exactly 200.
  HTTP probes use numeric loopback HTTP, no credentials/query, environment proxy,
  redirects or body reads. HCP API is `/health`; runtime is the configured
  executable with exactly `herdr-check`, exit status only, stdout/stderr discarded.
* `container_running`, `container_health`, `container_health_configured`,
  `container_restarts_total`: Docker inspect of explicit allowlist entries only,
  restricted formatting of running/health/restart fields. A missing healthcheck
  is reported with configured=0; running is still monitored. No compose changes.
* `hcp_queue_count`, `hcp_queue_oldest_age_seconds`: queued/pending only;
  `hcp_expired_leases`: running lease expiry older than 120s;
  `hcp_failures_last_hour`: failed/error updated in the last hour;
  `hcp_approval_waits`: blocked/waiting_approval/awaiting_approval (informational,
  no page); `hcp_unknown_status_count`: unrecognized states warn about schema drift.
  done/completed/succeeded/cancelled are terminal. The operator must verify these
  status meanings against its installed HCP revision before enabling alerts.
  The DB connection uses `mode=ro`, finite lock/query timeouts, aggregate SELECT
  only on status/created_at/updated_at/lease_expires_at. Epoch seconds and ISO
  dates are supported; relevant invalid/missing timestamps fail the source.
  No spec_json/result_json/error/token column is read. Database/WAL handling
  remains SQLite's normal read-only behavior; do not use immutable=1 on a live DB.
* `backup_verified_timestamp_seconds`: last explicitly verified restore evidence.
  Required JSON <=4096 bytes: `{"version":1,"backup_succeeded":true,
  "restore_verified":true,"verified_at":<Unix seconds>}`. Only a backup pipeline
  that completed a backup AND a restore verification may atomically publish this
  private evidence. Timestamp must be positive and no later than now. File mtime,
  directory existence and a successful copy are never evidence. A missing pipeline
  or record is **OPEN**, represented by backup success=0, absent verified metric,
  and `BackupEvidenceMissing` after 15m. This package does not implement a backup
  pipeline. Do not create dummy evidence to silence the alert.

Rules warn after 3m for probe/container failures; source/collector freshness
threshold is 180s with 3m persistence; queue age >1800s; lease grace 120s; backup
age >86400s with 3m persistence; absent backup evidence 15m. Restart warning is
>2 increments in 10m sustained 3m; any failure in the rolling last hour warns.
Approval waits have no alert. Absent exporter, collector, per-source success and
timestamps, fixed inventory and required aggregates alert visibly. Inventory
rules reflect the example aliases; update these rules and their tests together
if changing aliases or removing sources. Missing metrics never become zero.
All alerts carry severity=warning; preserve the existing primary route's matching
semantics when integrating. Do not silently route them to a null receiver.

## Operator installation (bounded, user-owned)

1. Record reviewed Git SHA, existing `/opt/monitoring` config checksums, service
   states, and existing receiver/route/target identities in private operator
   evidence. Do not put credential-bearing config in PR artifacts. Keep 9100,
   the `linux` target `192.168.56.5:9100`, cleanup Gmail monitor, containers and
   their volumes unchanged. No sudo or root-owned exporter changes are required.
2. Install from the reviewed checkout, under the Jenkins user (replace `<source>`):

   ```sh
   install -d -m 700 ~/.local/lib/smokemap-monitoring ~/.config/smokemap-monitoring ~/.local/state/smokemap-monitoring/metrics ~/.config/systemd/user
   install -m 600 <source>/monitoring/collector.py ~/.local/lib/smokemap-monitoring/collector.py
   install -m 600 <source>/monitoring/config.example.json ~/.config/smokemap-monitoring/config.json
   install -m 600 <source>/monitoring/systemd/* ~/.config/systemd/user/
   ```

   Edit only the private copy of config: resolve the five exact development
   container names and verify HCP path/status/timestamp compatibility without
   reading task content. Keep probes on loopback. Configure exporter.env (0600)
   with `MONITORING_LISTEN=192.168.56.5:9708`, replacing the address with the
   Jenkins private VM interface if different. Never use 0.0.0.0 or public access.
   Restrict port 9708 to the monitoring host using existing network controls.
   The existing `/usr/bin/prometheus-node-exporter` binary must support the
   textfile flags; the second user process disables default collectors. Both
   processes coexist; do not edit the root service ARGS or port 9100.
3. Run the offline gates below. Then run the installed one-shot manually with
   `--config` and `--output` exactly as in the service; inspect only its private
   numeric metrics. Run `systemd-analyze --user verify` on the three unit files,
   then `systemctl --user daemon-reload` and enable/start
   `smokemap-textfile-exporter.service` and `smokemap-monitoring.timer`.
   The user manager must survive logout; if lingering isn't already enabled,
   record that deployment prerequisite rather than changing root policy here.
4. On the monitoring device, back up config privately and append the scrape job
   in `prometheus/scrape.example.yml`; append `rules.yml` to rule_files. Keep 30s
   scrape/evaluation. Run `promtool check config` on the assembled config and
   `promtool check rules`, then reload using existing lifecycle support. Do not
   replace `/opt/monitoring`, receiver definitions, routes, credentials or targets.
   Import `grafana-dashboard.json`, select the existing Prometheus datasource.
   NO DATA for backup means OPEN. Confirm the 9708 target and 9100 target coexist.
5. Existing Telegram with send_resolved=true is PRIMARY. Inspect existing routing
   privately and ensure these alert labels reach it. No receiver/secret material
   is supplied here. Email is optional secondary: operator may add a child route
   with `continue: true` and an existing authorized email receiver using private
   external configuration; validate with `amtool check-config` and routing tests.
   Never replace Telegram or copy Gmail cleanup credentials. This PR does not
   enable SMTP or send notifications. Leave original cleanup mail monitor enabled.

## Offline gates and operator acceptance

```sh
make test-monitoring
promtool check rules monitoring/prometheus/rules.yml
promtool test rules monitoring/prometheus/rules.test.yml
```

Unit tests mock subprocess/network; the temporary SQLite DB contains synthetic
content. They never call Docker, HCP, host systemd, SMTP or Telegram. CI runs the
same tests plus actual promtool rule evaluation. Rules/tests use JSON, a YAML
subset, to avoid adding Python packages. Official semantics:
[Prometheus rule testing](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/),
[node exporter textfile collector](https://github.com/prometheus/node_exporter#textfile-collector).

Primary operator must record reviewed SHA and deployment paths; fresh successful
metrics, absent/stale source alerts; exporter stop/restart and recovery; healthy
real runtime/probes/Docker sources; expected approval waits without a page;
read-only HCP compatibility; real backup+restore pipeline evidence or explicit
OPEN gap; and controlled failure/recovery through the existing Telegram route
with send_resolved. Prefer a temporary synthetic Prometheus alert to stopping
apps; never stop applications or delete data for notification tests. Record
actual received/resolved times privately. User accepts shared infrastructure
failure risk: this cannot notify if Prometheus/Alertmanager/Telegram or the
monitoring device itself is unavailable. No runtime/delivery claims until those
operator checks pass.

## Rollback

Disable/stop only `smokemap-monitoring.timer`, `smokemap-monitoring.service` and
`smokemap-textfile-exporter.service` as user units. Remove only their installed
unit files, reload the user manager, remove the dedicated 9708 scrape job and
monitoring rule file from the monitoring device's config, validate and reload.
Restore the private pre-change configuration if necessary, preserving subsequent
unrelated changes. Remove only the dedicated dashboard by UID
`smokemap-monitoring`. Archive numeric evidence before removing only this
package's private metrics/state/config directories. Do not disable the existing
9100 service, cleanup monitor, Telegram routing or any application. Never prune
Docker resources, volumes, other worktrees or root-owned monitoring files.
