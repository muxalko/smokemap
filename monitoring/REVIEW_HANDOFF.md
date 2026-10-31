# Independent review handoff — issue 136

Branch: `issue-136-monitoring-source`, based on fetched `origin/development`
`215bd7a` (not PR135). Issue: https://github.com/muxalko/smokemap/issues/136.
Resolve the exact candidate with `git rev-parse HEAD` and verify the PR head
matches before reviewing. The final caller report records the full commit SHA.
No independent reviewer was spawned: the caller forbids worker subagents.

Artifacts:

- `monitoring/collector.py`: stdlib one-shot collector.
- `monitoring/config.example.json`: private-config template with explicit aliases.
- `monitoring/prometheus/rules.yml`: alerts and absence gates.
- `monitoring/prometheus/rules.test.yml`: firing/delay/absence/healthy/wait tests.
- `monitoring/prometheus/scrape.example.yml`: additive private 9708 scrape job.
- `monitoring/grafana-dashboard.json`: dashboard with existing datasource selector.
- `monitoring/systemd/`: three user units; 9100 untouched.
- `monitoring/README.md`: metrics/privacy/backup contract, installation,
  Telegram-primary/email-optional integration, failure/recovery gates and rollback.
- `tests/test_monitoring.py`, Makefile `test-monitoring`, integration CI steps.

Local evidence: 11 monitoring tests, 43 existing cleanup-mail tests and 21
existing cleanup-supervisor tests pass. Python compilation and diff whitespace
checks pass. Local promtool is unavailable; downloads from GitHub release assets
and Ubuntu archives were blocked by sandbox network policy. CI performs real
promtool checks and all existing required jobs; use its exact-head results.

Limitations: no deployment, service changes, Docker/API/runtime access, production
secrets, live email/Telegram sends, migration or merge. HCP live schema/status
compatibility, user exporter/private interface/lingering, backup pipeline and
restore evidence, Grafana import and Telegram failure/recovery delivery remain
primary operator gates. Missing backup evidence remains OPEN. Systemd units are
source templates, not host-verified services. An independent exact-head reviewer
must assess the complete diff before any later merge/deployment decision.
