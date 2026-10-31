# Deployment monitoring — source and operator runbook

Additive source for issue #144; not installed or live-validated by the author.
Root owns required CI waiting, independent exact-SHA review, installation,
notification routing and browser/live QA. Keep all corrections on issue #144 and
its single branch/PR. Never install or merge as a source worker.

## Boundaries and inventory

The existing eleven-source collector, 29 alert rules, three dashboards, 9708
private exporter, 9100/linux target, original Telegram/HCP/Smokemap routing and
optional cleanup email monitor remain intact. No app sources, containers,
volumes, schemas, providers, tunnels or credentials are changed. No listener,
privileged container, cAdvisor or dependency install is needed. Python stdlib,
existing Docker/curl, and existing in-container Python/Node are used.

| Application | Environment / deployment | Compose project | Expected services |
| --- | --- | --- | --- |
| Smokemap | development / development | smokemap | frontend, backend, db, storage, media-cleanup (5) |
| Smokemap | staging / quick | smokemap-quick-staging | frontend, backend, db, storage, media-cleanup, quick-app, quick-media (7) |
| Smokemap | staging / local | smokemap-local-staging | edge, frontend, backend, db, storage, media-cleanup (6) |
| Web checker | production / production | web-checker-production | checker, maintenance (2) |

Quick connectors are long-running expected ingress, even when exited. Excluded:
storage-init, old PR67/testDB, web-checker development/mock-site, Jupyter and all
other host services. Fixed aliases are code-owned; private config supplies only
Quick recorded state and local public CA paths. No auto-discovery into alerts.

## Collection and privacy

`collector.py` is a separate user oneshot/timer, every 30s, with an output-file
lock preventing overlapping manual/timer runs. It writes only `deployments.prom`.
A 25s process alarm and pre-publication elapsed check bound the pass; systemd
TimeoutStartSec is 28s. Four independent operations at most; commands <=4s,
HTTP/curl <=3s, SQLite busy <=1s/query <=2s. Docker-exec Python/Node helpers have
internal 3s deadlines because killing Docker CLI does not stop an exec. Overlong
passes leave the old file stale. Malformed configuration also leaves it stale.
Only fixed `deployment_collection_failed` is printed on handled failure. A hard
deadline exits 1 without printing input or diagnostic details.

`docker_metadata.py` lists bounded internal IDs then makes **one metadata
snapshot** through a restricted inspect template: name/ID, exact Compose
project/service labels, running, health status, restarts, image digest, safe OCI
revision, created and started timestamps. No full inspect, environment, command,
health logs, arbitrary label maps or image inspect. IDs/names are internal only.
Missing after valid snapshot is present=0/running=0/state=0. Duplicate matching
services or malformed data are UNKNOWN; snapshot failure makes all UNKNOWN.

`resources.py` consumes one bounded `docker stats --no-stream --no-trunc`
snapshot for selected running IDs only. Strict finite percentages, SI/IEC memory
units and PIDs; CPU may exceed 100%. Memory is Docker-reported usage/limit, not
RSS. Missing running stats means resource_success=0, with values omitted. Stopped
services have no resource values (resource_success=1 means known not applicable).
Resource failure never changes service health or availability.

All labels are fixed application/environment/deployment/service or fixed
probe/signal aliases; container_info additionally has validated image SHA256 and
40-hex OCI revision or `unknown`. Prometheus supplies job/instance/host. Never
export job IDs/text, provider names/URLs, exception text, paths, container
names/IDs, credentials, presigned fields or raw command output. Every external
command discards stderr, bounds stdout at 64KiB and kills its process group.
Backups/config/logs have additional input limits. Files are replaced via 0600
temporary file, fsync, atomic rename and directory fsync, in owned 0700 metrics
directory. `common.py` reuses the unchanged original bounded-command/atomic-write
implementation from a separate package copy.

## Metric and state semantics

Metrics use `deployment_`; see `inventory.py` for exact labels. Global collector
completion evidence uses a conservative start timestamp and duration. Every
expected service emits expected=1 and observation_success=1/0. Valid observations
provide present/running, health_configured/health, restarts_total and applicable
created/started timestamps. State: **0 missing/stopped, 1 unhealthy/starting,
2 running without healthcheck (blue), 3 healthy (green)**. Missing observation
omits state. In particular, maintenance's absent Docker healthcheck is blue,
never healthy. `container_info` describes the **CONTAINER IMAGE**; development
bind-mounted application code is not established by image revision.

Resource metrics: cpu_percent, memory_usage_bytes, memory_limit_bytes,
memory_percent, pids and resource_success. Probe metrics: expected,
observation_success, success and timestamp_seconds with probe aliases.
Network/non-200/timeout/TLS failures are valid availability observations with
success=0; bad config, execution or malformed result is UNKNOWN. No bodies are
read or redirects followed. Development uses host loopback; both staging groups
use built-in Node HTTP/Python stdlib HTTP through read-only Docker exec. Local
public probes use fixed hosts, port 8443, `curl --resolve` to 127.0.0.1 with the
operator's **public CA**, no TLS bypass or environment proxy. Quick probes reload
recorded state, strictly validate HTTPS trycloudflare origins without port,
credentials, query, fragment or redirects, and verify standard certificates.
Supervisor probe matches `/proc/PID/stat` start ticks, not PID existence alone.
A missing recorded supervisor or reused/dead PID is observed failed.

Web-checker signals are worker_status, backup and maintenance_log, each with
expected/observation_success/success/timestamp. Success means a valid read;
availability/evidence comes from aggregate values, not success alone.

`webchecker_helper.py` imports only `web_checker.config.load_config` from app
code. It reads a bounded immutable config snapshot, keeps enabled scheduled jobs,
opens SQLite `mode=ro`, query_only, supported user_version=3, with lock/progress
and process deadlines. It never instantiates the store or runs status, worker,
check, check-all, dispatch, migration, backup or maintenance commands. SELECTs
use only approved status/timing/count columns; IDs only match internally.
It exports scheduled_jobs, missing_status_jobs, overdue_jobs,
oldest_terminal_attempt_age_seconds, repeated_failure_jobs,
notification_pending, notification_failed_pending, oldest_pending_age_seconds,
operational_pending and database_bytes. Oldest terminal attempt uses
max(last_success_at,last_failure_at) for each active job, so provider failure is
not mistaken for scheduler stall. Overdue is age > max(3*interval,600)+300 or
missing terminal status. No attempts means absent age, never invented zero age.
Repeated failures are consecutive_failures>=3. Current baseline is seven active
jobs at 300/3600s, but count is observed, not hard-coded to seven. Zero scheduled
jobs warns. Queues count undelivered rows; failed_pending means attempts>0;
combined oldest pending age is zero only when observed queues are both empty.
Database bytes means main SQLite file size, not logical content/WAL total.

Backup helper reads bounded `/backups/last-backup.json`: aware positive nonfuture
completion, safe web-checker-YYYYMMDDTHHMMSSZ.db basename, positive bytes, regular
non-symlink in-directory file with matching size. Manifest missing/invalid is
observed present/valid=0; timestamps/size omitted when invalid. Under the source
app contract this is an **on-host online backup + integrity_check signal**. It
is not off-host backup, restore verification or proof of recovered product. It
does not close the Smokemap backup/restore gate. Manifest is written before
prune; it does not prove whole maintenance completion.

Maintenance separately parses only anchored `maintenance event=completed/failed`
from bounded Docker logs (`--timestamps --since 48h --tail 200`). Only Docker
timestamps and failures strictly after latest completion are exported. Missing
completion produces present=0 and no age. Docker log window/rotation limitations
are explicit: no event in this window means NO EVIDENCE, not proof it never ran.
No raw lines or error detail leave the collector. Backup age and actual
maintenance completion age warn independently after 36h (24h configured cycle).

## Prometheus and dashboards

`rules.yml` is separate from existing rules. It adds freshness/state recordings
and scoped alerts; labels `monitoring_scope=deployments`, `host=jenkins` retain
application/environment/deployment for routing. Collector absence/stale/future
alerts are suppressed while the shared exporter is down or textfile parsing
fails, since original rules cover those conditions. Operational history requires
exporter up, textfile error=0, collector timestamp in [now-180,now], and successful
per-service/per-signal observation. Signal timestamp gates also apply. Expected
inventory vs observed state prevents disappeared telemetry from becoming green.
Read failures warn separately from service downtime; no healthcheck is not
unhealthy. Most alerts persist 3m, memory >90% persists 10m. Production stopped,
unhealthy/unavailable and overdue jobs are critical; dev/staging failures,
repeated provider failures and backup/maintenance gaps are warnings. Counter
increase is used only for Docker restarts, never rolling gauges.

Two Grafana 11.3.1 built-in-only dashboards in the root-supplied **Deployments**
folder: `deployments.json` UID `jenkins-deployments` and `web-checker.json` UID
`web-checker-production`. Preserve all existing dashboards/UIDs. Hidden portable
DS_PROMETHEUS binds existing `PBFA97CFB590B2093`; browser timezone, 6h default,
30s refresh, 24 columns, <=18 panels, no overlaps, null gaps unbridged. Navigation
keeps time/variables. Overview selectors use fixed known values. Counts are
inventory-anchored; zero fallbacks for counts use observed expected inventory,
not blanket vector(0). UNKNOWN count and resource telemetry are separate from
DOWN. Alert count includes only selected app/deployment alerts, so collector-wide
alerts still need the original overview/Prometheus alerts view. Image identity
is explicitly not code provenance. Web-checker cards explain schedule-aware
progress, repeated failures, delivery backlog and independent backup/maintenance
evidence. Missing ages show UNKNOWN, not an epoch-sized spike.

Offline gates (no live source access):

```sh
make test-monitoring
# Existing promtool required; do not install host dependencies as a source worker.
make check-deployment-promql
```

Existing `make test-monitoring`/integration CI discover the new tests without
removing old tests. CI parses actual dashboard targets and rules with promtool,
evaluates actual rules/recordings across missing/down/no-check/unknown/stale/
future, queues/provider failures/backup/maintenance cases, and evaluates actual
dashboard expressions against freshness failures. Unit fixtures use fake Docker,
network mocks and synthetic SQLite/files only. Source checks do not prove live
label uniqueness, rendering, service health or notification delivery.

## Root-only installation plan (not performed)

1. Save private preservation evidence: exact reviewed source SHA; existing
   collector/rules/dashboard hashes, units, scrape target/relabel/routing and
   credential-file references. Do not print config/credentials or runtime env.
   Wait all required CI, obtain independent review, resolve conversations, and
   keep corrections on the same PR before merge. Source author returns after
   focused checks/push; no CI waiting or merge here.
2. As existing Jenkins user michael (uid 1000), prepare **new** private config
   and code, keeping old `~/.config/smokemap-monitoring/` unchanged:

   ```sh
   install -d -m 700 ~/.config/deployment-monitoring ~/.local/lib/deployment-monitoring/deployments
   install -m 600 <reviewed-source>/monitoring/collector.py ~/.local/lib/deployment-monitoring/collector.py
   install -m 600 <reviewed-source>/monitoring/deployments/*.py ~/.local/lib/deployment-monitoring/deployments/
   install -m 600 <reviewed-source>/monitoring/deployments/config.example.json ~/.config/deployment-monitoring/config.json
   install -m 600 <reviewed-source>/monitoring/deployments/systemd/* ~/.config/systemd/user/
   ```

   Root supplies actual recorded Quick state path and public local CA path in
   the **new** private config. Reuse existing owned0700 metrics directory; refuse
   wrong ownership/mode, never loosen it or change exporter user/bind/firewall.
   Verify user unit syntax with systemd-analyze before enabling. First run the
   new oneshot and inspect numeric private output for 20 expectations and truthful
   Quick failure/provider warnings. Never start or repair application services.
3. Extend existing private exporter metric-relabel keep from
   `smokemap_.*|node_textfile_scrape_error` to
   `smokemap_.*|deployment_.*|node_textfile_scrape_error`. Preserve job/instance and
   host=jenkins. Add only this rules file. Use installed promtool 2.55.1 to check
   assembled config/rules/fixtures. Validate before reload. No new exporter or
   network exposure. Enable/start only deployment-monitoring.timer after tests.
4. Add an Alertmanager child route matching `monitoring_scope=deployments`, group
   by `[application,environment,deployment]`, to a new deployments receiver using
   the **existing Telegram channel and credential-file references**. Preserve
   original infra/Smokemap/HCP routes and receivers, Telegram primary, optional
   email unchanged. Receiver header `[Deployments]`; template each alert with its
   own FIRING/RESOLVED status and HTML-escape all interpolated labels/annotations
   (`html` template function) before Telegram HTML parsing. Set send_resolved.
   Never paste tokens/channel secrets into source or output. Root must use
   amtool check-config/routes test against assembled private config, then prove
   synthetic firing/recovery delivery without stopping apps or calling providers.
5. Load both JSONs into root-supplied Deployments folder, preserve UIDs and bind
   existing datasource. Validate every actual instant/range target against live
   Prometheus; confirm expected20/unknown/blue maintenance/Quick failures and
   repeated-provider warning without repairing them. Browser QA desktop and 390px,
   legends, labels, gaps, time navigation, bytes precision and no zero-epoch spikes.
   Check real schema/config paths and schedule-aware ages read-only. Record
   source/live evidence separately; on-host backup is not restored-product proof.

## Root-only rollback

Run as the monitoring owner (uid 1000). In a RemoteCommander shell, set the
user-bus environment before any user-systemd commands:

```sh
export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
```

1. Remove only the deployments rules file reference from the assembled
   Prometheus configuration (or the owned file from its rules glob). Validate
   with `promtool check config`, reload, and confirm the deployments rule group
   is unloaded. Do this before removing metrics so rollback does not trigger
   collector-missing alerts. Preserve every original rule.
2. Disable and stop the timer, then explicitly stop the service; stopping the
   timer alone leaves an in-flight oneshot able to recreate the metrics file:

   ```sh
   systemctl --user disable --now deployment-monitoring.timer
   systemctl --user stop deployment-monitoring.service
   ```

   The service is a static oneshot with no enablement target. If it was enabled
   through a separately added link, disable that owned link too.
3. Wait for the stop to finish. Prove both units are inactive, the service has
   `MainPID=0` and an empty control group (no collector or helper process), and
   no manual collector remains. Inspect only process identity, never argv or
   environment. Check the private writer lock is free:

   ```sh
   systemctl --user show deployment-monitoring.timer deployment-monitoring.service \
     --property=ActiveState --property=SubState --property=MainPID --property=ControlGroup
   flock --exclusive --nonblock "$HOME/.local/state/smokemap-monitoring/metrics/.deployments.lock" true
   ```

   Continue only when neither unit is active/activating/deactivating, no metrics
   writer exists and the lock check succeeds. A failed check means wait or
   investigate; do not remove the lock to bypass an active writer.
4. Only then remove the owned metric and lock files:

   ```sh
   rm -- "$HOME/.local/state/smokemap-monitoring/metrics/deployments.prom" \
     "$HOME/.local/state/smokemap-monitoring/metrics/.deployments.lock"
   ```

   Remove only the new deployment unit files and reload the user manager.
5. Optionally remove only the deployments child route/receiver and the two new
   dashboard UIDs; validate assembled configs before reload. Remove the new
   `deployment_.*` keep-prefix last, after publication has stopped.

Keep `smokemap.prom`, the original collector/timer/exporter, 9708 bind/firewall,
9100, original metrics/rules/routes/dashboards and application runtime untouched.
Preserve private evidence and subsequent unrelated edits; no Docker pruning, DB
writes or service repair. Disabling this collector cannot clear the existing
Smokemap backup gate.
