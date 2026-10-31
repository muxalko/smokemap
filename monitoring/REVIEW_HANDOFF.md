# Independent exact-head review handoff — issue 138

Branch: `issue-138-monitoring-contract`, based on explicitly fetched
`origin/development` at `215bd7a5c3b000d605600ed33710a0285f619c40`.
Issue: https://github.com/muxalko/smokemap/issues/138.
PR and exact final commit are recorded in the final report and issue/PR evidence.
Verify `git rev-parse HEAD` equals the PR `headRefOid` before independent review.
The existing PR135 branch and dirty workspace are untouched. No worker subagents
or orchestration were used; independent review is pending caller handoff.

Artifacts:

- `monitoring/collector.py`: bounded stdlib one-shot; atomic 0600 textfile;
  ISO-8601 read-only aggregate queue reads; JSON runtime compatibility check.
- `monitoring/config.example.json`: all eleven required names/kinds; private
  operator input replaces paths/container placeholders.
- `monitoring/prometheus/rules.yml`: 29 alerts including static absence gates,
  Jenkins inode exhaustion and missing inode metrics; actionable source summaries.
- `monitoring/prometheus/rules.test.yml`: rule delay/firing/recovery/absence,
  complete healthy set, individual source omissions and expected approval waits.
- `monitoring/prometheus/scrape.example.yml`: additive private 9708 scrape job.
- `monitoring/grafana-dashboard.json`: dashboard including existing 9100 inodes.
- `monitoring/systemd/`: collector/timer and separate same-user textfile exporter.
- `monitoring/README.md`: privacy/metrics/backup semantics, bounded install,
  Telegram primary, optional secondary email, acceptance gates and rollback.
- `tests/test_monitoring.py`, Makefile target, integration CI monitoring gates.

Local verification: 18 monitoring tests, 43 cleanup-email tests and 21 existing
cleanup-supervisor tests pass; Python compilation, dashboard ID/JSON validation
and whitespace checks pass. Local promtool is unavailable; CI runs the actual
29-rule/46-scenario Prometheus evaluation.

Tests use synthetic SQLite data, mocked external readers and
short-lived Python fixture processes only. No Docker daemon, HCP runtime/API,
SMTP, Telegram or host service was contacted. Existing cleanup email code and
units are unchanged. Required workflow jobs run in GitHub CI; consult exact-head
results rather than assuming inherited green status.

Known earlier CI failure: draft PR137 head `7c6ba3e`, run `41187779191`, job
`124498101651` failed at existing `make test-dev-cleanup`, after its monitoring
unit/promtool gates passed. Job metadata was confirmed via the App API. Full log
download redirects to a sandbox-blocked Azure blob domain; the existing 21-test
cleanup suite passes offline, so the old failure's cause is not established.
Do not call it resolved without new CI evidence or an actual failure diagnostic.

Limits: no merge, deployment, host config changes, app changes/upgrades,
migrations, service disruption or live notification tests. Runtime installation,
private 9708 access, real HCP JSON/schema compatibility, dashboard import and
Telegram firing/recovery remain primary-operator gates. Missing backup pipeline
or verified backup/restore evidence remains OPEN. No backup or delivery claim.
Keep existing 9100 exporter, Telegram route/credentials/targets and original
cleanup mail monitor running. Do not copy SMTP passwords or weaken 0600 output
for the root exporter. This source review cannot prove host delivery or health.
