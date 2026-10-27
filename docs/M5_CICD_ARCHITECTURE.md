# M5 planned hybrid CI/CD architecture

Status: approved future design, not deployed. Recorded 2026-10-27 under
[root issue #128](https://github.com/muxalko/smokemap/issues/128).
This document specifies implementation and acceptance work; it neither changes
infrastructure nor demonstrates M5 completion. The older PoC proposal in
issue #108 / PR #109 remains separate and unchanged. Its illustrative sizing
and networking are not the production target specified here.

## Ownership and trust boundaries

The frontend and backend remain independently deployed repositories. Each owns
its build, tests, image publication and API compatibility. Root gitlinks name
an integration baseline, not a combined application history or deployment.
The root release manifest binds the independently published artifacts to one
tested combination and records which services actually need replacement.

The approved hybrid separates these responsibilities:

| Boundary | Planned responsibility | Authority excluded |
| --- | --- | --- |
| Hosted disposable CI | Execute untrusted PR code, lint, tests, production build and isolated cross-app E2E | Local network, Jenkins, deployment SSH, runtime secrets and production data |
| Hosted protected publisher | Publish reviewed source images, SBOMs, signatures and provenance to the registry using scoped short-lived identity | Deployment access or permission to approve its own promotion |
| HCP independent review | Review the exact candidate source/configuration head, report findings and resolution evidence | Deployment credentials or implicit production approval |
| Trusted upgraded local Jenkins | Verify releases, serialize deployments, run gates and retain audit evidence | Running arbitrary public PR jobs or rebuilding application images locally |
| Environment runtime | Pull verified digests and run the selected release with environment-specific credentials | Registry write, CI administration or access to another environment's secrets |

There will be no public-repository self-hosted runners on the Jenkins host,
production VM or trusted LAN. Jenkins is a deployment controller, not an
untrusted CI executor. Before enabling it, upgrade Jenkins core, plugins and
its supported runtime; inventory compatibility, remove unused plugins, patch
the host, back up configuration, rehearse restore and apply least-privilege
access. Select and verify supported exact versions in that implementation
issue; this plan does not claim the existing installation is ready.

Jenkins jobs and deployment scripts come from reviewed, protected controller
configuration. Application checkouts, Jenkinsfiles, PR metadata and artifact
contents cannot supply commands to execute on the controller. Use fixed jobs,
a strict manifest schema and fixed deployment actions; never evaluate a
manifest as shell code. Keep execution outside the controller process with
narrow environment access. Docker socket/root-equivalent access, where
unavoidable for deployment, is restricted to the trusted deployment identity.

## Release flow and promotion policy

1. A feature PR runs on hosted CI with read-only repository permissions,
   isolated fixtures and no privileged credentials. Required application
   checks are `test` and `secrets`; root checks are `integration`,
   `viewport-pan`, `submission-media`, `public-after-approval` and `secrets`.
   HCP independently reviews the exact head; changes invalidate prior review
   and applicable checks. Resolve all review conversations before merge.
2. Application commits merge in their owning repositories first. A separate
   root PR updates only published application commits and checks the combined
   baseline. Preserve target-tree promotion practices, including frontend
   histories that cannot be directly merged across deployment branches.
3. Protected hosted publication builds the eligible merged source and
   environment variants, signs artifacts, emits provenance and publishes
   immutable registry digests. The root release manifest records the exact
   root SHA and both gitlink SHAs; it binds them to owning source revisions,
   build identities, configuration identities and image digests. Publication
   alone does not authorize deployment.
4. A push to the protected **root `development` branch** automatically queues
   DEVELOPMENT deployment only after validation of that exact merged SHA,
   required successful CI, HCP/merge evidence and all artifact checks. An
   application push, PR event or mutable tag alone cannot trigger it.
   Jenkins polls GitHub using outbound authenticated requests; any later
   notification mechanism is only a hint and must requery authoritative state.
   No inbound public Jenkins webhook is required.
5. Jenkins obtains the deployment lock, rechecks freshness, creates a recovery
   point, deploys only affected services and runs the post-deployment
   [DEVELOPMENT verification gate](DEVELOPMENT_VERIFICATION.md). This includes
   actual feature/authentication browser behavior and regressions, beyond
   container health. Persist a signed gate record binding source, manifest,
   selected/running digests, configuration and results. A failure blocks the
   next task and promotion; recover and repeat the gate.
6. **STAGING requires a merged promotion PR**, based on the target deployment
   tree, with required checks and independent review. The PR references a
   passing DEVELOPMENT gate for the identical source combination. Jenkins
   verifies that record before deployment and runs staging-specific checks.
   A queued PR, PR label or DEVELOPMENT success alone cannot deploy staging.
7. **PRODUCTION requires explicit manual promotion** of a staging-validated
   release. The authorized operator selects the immutable manifest and target,
   acknowledges migration/recovery impact and records identity, time and
   reason. No automatic `main` push, staging merge, timer or retry can substitute
   for this action. Any required `main` target-tree PR and its review/checks
   must also pass. Authorization is bound to that release and expires on
   changed inputs; production permission is never inherited from a docs PR.

The automatic DEVELOPMENT path is future automation of the existing per-task
verification discipline, not permission to alter today's live checkout. Each
environment has its own serialized queue/lock. Coalesce superseded work before
side effects; recheck branch head and gate identities immediately before
execution. Once migrations/deployment begin, complete or recover that
transaction before another release runs. Duplicate events are idempotent by
release/environment ID; partial and interrupted runs require reconciliation.

## Immutable artifacts and frontend configuration

The immutable, signed release manifest must contain at least:

- release ID, schema version, root and application SHAs, exact target
  environment, promotion ancestry and previous release ID;
- registry/repository and image digest for each application and infrastructure
  service, including migration and cleanup images; platform/architecture;
- build workflow identity and immutable workflow revision, CI run/check links,
  HCP review identity/head/result, SBOM and provenance/signature references;
- non-secret build/runtime configuration hashes, frontend public build inputs,
  API/schema compatibility and ordered migration plan;
- DEVELOPMENT/STAGING gate references, recovery-point reference, and explicit
  production authorization where applicable.

Jenkins verifies signatures and provenance on both the manifest and every
image before pull/deploy. Verification policy allowlists issuer, repository,
protected ref, workflow identity/revision, source SHA, builder, environment
and digest; cryptographic validity alone is insufficient. Reject unsigned,
revoked, expired-policy, mismatched or missing evidence, untrusted builders,
mutable tag-only inputs and replayed promotions. Never silently rebuild or
resolve a replacement digest. Retain evidence and previous verified images
under an explicit retention policy so rollback survives registry cleanup.

`NEXT_PUBLIC_*` values are compiled into the frontend browser bundle. The
[current staging contract](../deploy/staging/README.md) also requires runtime
public values to match the image's `production-build.json`. Environment name,
public base URL, map style, public logging and release identity can therefore
require **different frontend image digests for DEVELOPMENT, STAGING and
PRODUCTION**, built from the same reviewed frontend source SHA. Secrets must
never enter these public inputs or build layers.

The manifest maps each environment to its prebuilt variant and records exact
public inputs and provenance. Validate each variant in hosted CI, then test
the actual selected variant in its target environment before accepting that
gate. Production promotion includes a candidate validation of the exact
production variant with safe isolated dependencies before manual approval.
DEVELOPMENT/STAGING evidence establishes source compatibility, not proof that
an untested production bundle works. Backend images may be reused by exact
digest when configuration and schema contracts permit. Do not claim universal
exact-image promotion across environments. A future runtime public-config
redesign could enable that, but requires separate application work and tests.

## Public-repository threats and safeguards

| Threat | Required safeguard and negative acceptance test |
| --- | --- |
| Fork PR executes malicious code or steals tokens | Hosted disposable execution, read-only token, no deployment secrets/network. A fork can neither publish an eligible release nor reach Jenkins/VMs. |
| Privileged event checks out PR code (`pull_request_target`, unsafe `workflow_run`) | Never execute untrusted source in a privileged context. Requery protected source and exact checks before publication; demonstrate a spoofed event is rejected. |
| Poisoned artifact/cache/dependency/action | Separate untrusted and protected caches, immutable action/base-image pins, declared dependency authority, clean builds, SBOM/security checks and verified source-bound provenance. Reject a substituted digest. |
| Forged tag, status, review or promotion replay | Query expected GitHub App/workflow identities, protected branch membership, exact SHAs and fresh gate records. Demonstrate wrong-head and previously consumed production authorizations fail. |
| Malicious manifest or deployment script | Strict schema/allowlists, fixed trusted commands, bounded input sizes, no command interpolation or arbitrary path/mount selection. Reject shell payloads and unauthorized service/volume changes. |
| Compromised registry or publisher | Independent deployment policy, scoped publisher identity, signature/provenance verification and revocation response. Registry read access cannot grant promotion authority. |
| Public ingress or lateral movement | No public controller/admin/DB/storage-console listeners; restricted Tailscale/host-only paths and separated networks/credentials. Verify reachability denial from untrusted CI and the public internet. |
| Secret leakage and resource exhaustion | Redacted logs/artifacts, secret scanning, retention/access controls, CI quotas/timeouts and deployment locks. Test redaction with synthetic values and concurrent/duplicate events. |

Signing proves origin and integrity, not application safety. Required tests,
review, dependency/security policy and controlled promotion remain separate
gates. On suspected credential compromise, freeze deployment, revoke/rotate
the affected identity, quarantine artifacts, review audit records and rebuild
from an independently verified source and builder before resuming.

Credentials are independent across DEVELOPMENT, STAGING and PRODUCTION and
across registry publication, read-only deployment pulls, GitHub metadata,
Jenkins administration, deployment transport, database, object storage,
backups and tunnel ingress. Use scoped short-lived credentials where feasible;
otherwise store secrets outside Git with restrictive file/service access,
rotation and revocation procedures. The GitHub mutation identity remains the
App through `scripts/github-app-gh`; its private key is never a CI artifact.
HCP review receives only the access needed for review. No runtime gets the
publisher token, controller credentials or another environment's secrets.

## Planned production host and exposure

The production target is a separate **VirtualBox VM running Ubuntu Server
24.04**, provisioned with **4 vCPU, 12 GiB RAM, a 50 GB OS disk and a separate
150 GB data disk**. This is the approved initial allocation, not measured
capacity or a high-availability guarantee. Monitor free space, memory, CPU,
backup growth and media growth; define alerts and retention before rollout.
Keep persistent database/media state on the data disk with documented mounts,
ownership and backup/restore mappings. Do not put secrets or state in images.

Use **NAT plus host-only networking and Tailscale**. NAT provides outbound
updates, registry pulls and tunnel connectivity; host-only networking supplies
a restricted Jenkins-to-VM deployment path, and Tailscale supplies authenticated
operator access under explicit ACLs/device policy. Restrict SSH to authorized
controller/admin identities, pin host keys and firewall the host-only interface;
being on that interface is not authorization. Disable VirtualBox/router port
forwarding and bridged public exposure. There are **no inbound public ports**.
Jenkins and HCP control access must not be exposed by application ingress.

Future public application HTTPS uses outbound Cloudflare Tunnel connectors;
only approved frontend and restricted media hostnames are routed. A separate
browser-reachable media origin must preserve signed upload Host/path/query and
explicit CORS without making private source objects anonymously readable.
Expose no direct backend, PostgreSQL, MinIO console, Docker socket or SSH.
Retain backend authorization and private/public media lifecycle boundaries.
Production services are a production-built frontend, Gunicorn/Django,
PostGIS, private source-media storage, periodic media cleanup and controlled
edge ingress. Migrations are a separate one-time job, not startup behavior.
Existing local-staging/Quick Tunnel rehearsals remain separate resources and
do not provision this production VM or establish production readiness.

The physical host, power, disks and local controller remain shared failure
risks even with separate VMs. Off-host backups and a restore rehearsal are
mandatory; VM snapshots alone are neither consistent backups nor redundancy.
Costs and availability require capacity/operational evidence before launch.

## Operations, recovery and audit

Before each deployment, verify configuration, resource isolation, image trust,
compatibility, capacity, prior release availability and a consistent paired
database/media recovery point. Coordinate writes and cleanup for consistency.
Backups must be encrypted, access-controlled, retained off-host with independent
credentials and tested by restoring into an isolated target. Record measured
recovery time and recoverable data window against approved RTO/RPO targets;
choose those numeric targets before production acceptance.

Run migrations once under the environment lock using the verified backend
image and an explicit reviewed plan. Prefer expand/contract changes compatible
with old and new code. Test fresh install and upgrade from restored data,
including PostGIS extensions and spatial behavior. Record migration IDs,
start/end/result and schema compatibility; a failed migration stops rollout.
Never fake migration state or assume restarting containers reverses a schema
change. Destructive or irreversible changes require their own explicit approval,
backup and maintenance plan; normal deployment authorization does not cover
deleting volumes or production data.

After deployment, compare running digests/configuration with the manifest,
check frontend/live/readiness/GraphQL/bounded viewport, and exercise real
authentication/logout, submission with zero/multiple images, upload/CORS,
moderation, private-before-approval and public-after-approval behavior. Keep
synthetic fixtures isolated and ensure cleanup cannot target user data. Alert
on failed gates, cleanup failures, backup failures and resource exhaustion.

Rollback selects the retained previous signed manifest and environment variant
by digest, changes only affected services, and repeats health/product checks.
Preserve useful data and unrelated volumes. Roll back application code only
when schema/data compatibility permits. Otherwise stop writes and follow the
reviewed forward-fix or explicitly authorized paired database/media restore
procedure. Rehearse both application rollback and data restoration; record
actual outcomes and keep failed gates visible.

Retain a redacted append-only audit trail outside the deployment host: trigger,
actor/authorization, PR/review/check identities, root/application SHAs,
manifest/signature/provenance identities, selected and running digests,
non-secret config hashes, environment, lock/job IDs, timestamps, migration
results, recovery point, feature/regression evidence and rollback/restore
outcome. Never include tokens, sessions, authorization headers, presigned
URLs/form fields or secret-bearing environment dumps. Separate audit write and
delete authority and define retention and incident access policy.

## Staged implementation and acceptance plan

Every stage needs a focused issue/branch/PR in its owning repository, exact-head
CI, independent HCP review and resolved findings. Application changes land
before separate root pointer integration. This table is future work, not a
record of passing acceptance results.

| Stage | Implementation scope | Objective acceptance evidence |
| --- | --- | --- |
| 1. Freeze policy and inventory | Record trust identities, supported Jenkins/runtime/plugin upgrades, environment resource map, RTO/RPO, secret ownership and promotion policy | Reviewed inventory; no public self-hosted runners; isolated upgrade/restore succeeds before controller enablement |
| 2. Hosted supply chain | Protected publishers, immutable image/manifest schema, environment frontend variants, SBOM/signatures/provenance and verifier | Clean builds; exact-source traceability; wrong SHA, issuer, builder, digest, public config and missing signature all rejected; fork publication denied |
| 3. Harden local controller | Fixed trusted deployment jobs, scoped identities, outbound polling, locks, idempotency and external audit | No untrusted checkout execution; duplicate/stale/spoofed events rejected; concurrent deploys serialize; secret redaction and revocation drills pass |
| 4. Automate DEVELOPMENT | Exact merged root push eligibility, frozen releases, recovery points and affected-service deployment | Validated push deploys automatically; application-only/unvalidated pushes do not; real feature/auth gate passes; failed gate blocks next task and promotion |
| 5. Rehearse STAGING | Target-tree promotion PR linked to passed DEVELOPMENT record, target frontend variant and controlled migrations | Unmerged/wrong-source/missing-gate PR rejected; merged valid PR deploys; complete product suite, migration failure, rollback and isolated paired restore demonstrated |
| 6. Prepare production VM | Approved Ubuntu/VirtualBox allocation, NAT/host-only/Tailscale restrictions, persistent disks, ingress and monitoring | Verify 4 vCPU/12 GiB/50 GB OS/150 GB data, reboot persistence, restricted administration, no inbound public ports, private media and off-host recovery within approved RTO/RPO |
| 7. Enable manual production promotion | Release-bound manual authorization after staging, tested production frontend variant, maintenance/recovery runbooks | Staging merge/main push alone cannot deploy; authorized exact manifest deploys; running digests match; probes/product workflows pass; rollback and restore/audit evidence retained |

Do not enable the next automation stage before its negative tests and recovery
checks pass. M5 also retains the supported-version, dependency, contract,
legacy-data and retirement work in the roadmap. Adopting this architecture or
opening its PR completes none of those implementation or deployment gates.
