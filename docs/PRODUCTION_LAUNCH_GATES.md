# Minimum safe production launch and remaining M5 work

Decision: 2026-10-30 (America/Los_Angeles); synchronized 2026-10-31 under
[root #134](https://github.com/muxalko/smokemap/issues/134). Authority: the
approved production-launch decision, supplied to the implementer at
`/home/michael/.local/state/smokemap-production-launch-decision-20261030.md`.
This page preserves its substantive requirements in the repository. It does
not authorize deployment or declare readiness. M5 remains Current.

The [bounded security assessment](M5_SECURITY_ASSESSMENT_20261031.md) is the
first assessment, with incomplete dependency and container scans. No launch
gate below is demonstrated complete by that assessment or this document.

## Mandatory before launch

| Gate | Evidence required for the exact release candidate |
| --- | --- |
| Supported, patched stack | Supported application frameworks and compatible runtimes; exact versions, authoritative locks and immutable image digests; production dependency and container scans. Resolve critical/high findings unless a documented applicability assessment proves they cannot affect the release. Review lower severities for authorization, disclosure, data loss and availability impact. An incomplete scan is an open gate. |
| Production operations | Stable hosting/domain/HTTPS, production builds and application servers, independent secrets/data, restricted database/storage access, verified cookies/CORS/CSRF/proxy settings, automatic startup and reboot rehearsal. Quick Tunnels remain staging tools. |
| Recovery | Automated off-host database and media backups with retention and failure alerts; restore into an isolated environment and verify data/media consistency; agree recovery time and acceptable data loss. |
| Release control | Reproducible releases, controlled migrations, exact-candidate staging rehearsal and tested application rollback with explicit schema compatibility. Application rollback does not reverse data migrations. |
| Detection and response | External availability monitoring surviving VM loss, plus API/frontend/cleanup health, disk and backup-failure alerts; verify delivery and assign a responder. Add an external heartbeat where needed to complement public endpoint checks. |
| Product acceptance | Production-like exact-candidate authentication/token/logout, map/search, photo/no-photo submission, pending-media privacy, moderation and approved-image rendering. Verify the actual basemap/provider integration as well as deterministic fixtures. Run modest representative load checks against agreed budgets. |
| Launch data and ownership | Decide the launch dataset; reconcile every included record/media object and exclude test accounts/fixtures. Assign moderation, abuse-report and support ownership. Provide a usable launch account-access path and document relevant privacy/retention behavior. |
| Explicit decision | Final launch review records evidence and unresolved risks and makes an explicit production deployment decision. Development success alone is insufficient. |

## Conditional post-launch M5 work

Deferral is tracked work. Create a focused owning-repository issue when each
item is scheduled and record the evidence satisfying its condition at final
launch review. No blanket exception follows from this table.

| Work retained in M5 | Condition for deferral |
| --- | --- |
| Node/Python modernization beyond supported bridge versions | Launch runtimes remain supported, patched and compatible. Unsupported Next.js or Django is a launch blocker. |
| PostGIS minor upgrade | Current pairing remains supported/patched and spatial/recovery checks pass. |
| Full legacy migration | Excluded records are safely preserved; every served record/media object is reconciled. |
| GraphQL retirement and duplicate-path removal | Existing endpoints cannot bypass authorization or the supported write workflow. Fix or disable unsafe endpoints before launch. |
| Broad API consolidation | Launch frontend contract is documented/tested, with no unsupported external-client promise. |
| Tailwind cleanup and refactoring | No launch-impacting defect or production-build blocker depends on them. |
| Advanced tracing, dashboards and optimization | Actionable basic monitoring and acceptable launch performance already exist. |
| High availability and automatic failover | Single-VM downtime is explicitly accepted; external detection and tested recovery exist. |

The [roadmap](ROADMAP.md) retains the full M5 completion criteria, including
one supported implementation/contract per workflow and full production-data
reconciliation. A minimum safe launch does not satisfy them automatically.
The [supported-version targets](M5_SUPPORTED_VERSIONS.md) remain the broader
modernization destination; bridge acceptance requires fresh support, patch,
compatibility and security evidence on the actual launch date.

## Sequential execution gates

1. Finish assessment and prioritize supported-framework/security work using
   the [assessment acceptance plan](M5_SECURITY_ASSESSMENT_20261031.md).
   Missing scans and unknown runtime identities remain explicit open evidence.
2. Implement one focused issue in its owning repository; exact-head checks,
   required CI/secrets/E2E, independent agent review and resolved conversations
   precede any merge. Application merges precede a separately reviewed root
   pointer integration. This assessment task stops at an unmerged PR; its
   author does not supply its independent review.
3. After review/merge and separate operational authorization, deploy only the
   reviewed release to DEVELOPMENT using frozen sources and independent
   dependency/cache volumes. Pass feature/authentication and applicable
   cross-application regressions and record the result before advancing to
   the next implementation task. Follow [Development verification](DEVELOPMENT_VERIFICATION.md).
4. Rehearse the exact production candidate in independent staging, including
   controlled migrations, recovery and schema-compatible rollback. Re-run
   scans and acceptance on the final artifacts, not earlier development images.
5. Complete every mandatory launch gate, record conditional deferrals with
   owners/tracking and evidence, then obtain an explicit production decision.
   There is no automatic production promotion.

Application upgrades, operations preparation and launch/data preparation may
have independent planning lanes. They do not authorize concurrent service
changes; the one-task-at-a-time implementation and DEVELOPMENT gate remain.
Preserve existing dirty source, useful uploads/data, staging projects,
credentials and release/recovery evidence throughout. Keep private operational
scan evidence in the established Jenkins evidence store; publish only
sanitized summaries. This leaf assessment neither orchestrates Jenkins nor
changes a running environment.
