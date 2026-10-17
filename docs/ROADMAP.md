# Smokemap execution roadmap

Status: Active planning document

Last updated: 2026-10-17

Evidence base:

- [Joint architecture and engineering assessment](ARCHITECTURE_ASSESSMENT.md)
- [Pre-milestone audit](PRE_MILESTONE_AUDIT.md)
- [M1 security and authorization contract](M1_SECURITY_POLICY.md)
- [M1 exit evidence](M1_EXIT_EVIDENCE.md)
- [M2 exit evidence](M2_EXIT_EVIDENCE.md)
- [M3 submission and media contract](M3_SUBMISSION_MEDIA_POLICY.md)
- [M3 exit evidence](M3_EXIT_EVIDENCE.md)
- [M4 exit evidence](M4_EXIT_EVIDENCE.md)

## 1. Planning model

GitHub milestones M1 through M5 are the canonical execution sequence. The
earlier M0 through M9 plan was useful for identifying dependencies, but its
numbering no longer matches the repository milestones. The detailed concerns
from that plan are retained below under the five canonical milestones.

Working rules:

1. Keep one milestone in active product development at a time.
2. Do not start a dependent milestone until its entry criteria are satisfied.
3. Use issue → branch → focused commit → pull request → required
   CI/secrets/E2E as applicable → independent agent review → resolve review
   conversations → GitHub App squash merge. Keep `development` PR-only and
   its required checks strict and up to date, with administrator enforcement,
   linear history, conversation resolution, force-push and deletion bans, and
   an approving review count of `0`; human review is optional only for
   unresolved product or policy decisions, destructive or production changes,
   ambiguous scope, or an explicit user request, and `@muxalko` is not a
   routine dependency.
4. Add tests at the authorization, API, or UI boundary being changed.
5. Record product and architecture decisions before implementation depends on
   them.
6. Keep frontend, backend, and workspace histories and deployments separate.
7. Update this roadmap and the audit evidence when milestone status changes.

Status values:

- **Current:** the only milestone receiving product-development effort.
- **Next:** ready after the current milestone exits.
- **Blocked:** waiting for a named decision or prerequisite.
- **Later:** ordered but not ready to begin.
- **Done:** exit criteria have been demonstrated.

## 2. Ordered milestones

| Order | Canonical GitHub milestone | Status | Primary outcome |
| ---: | --- | --- | --- |
| 1 | M1 — Security and authorization foundation | **Done** | Unsafe public boundaries are closed; credentials remain server-side; the role matrix is enforced and tested |
| 2 | M2 — Viewport map vertical slice | **Done** | Every settled viewport loads bounded, indexed GeoJSON with deterministic UI states |
| 3 | M3 — Submission and media vertical slice | **Done** | Validated submissions and zero-or-more verified uploads work end to end |
| 4 | M4 — Moderation and search | **Done** | Moderation is atomic and auditable; search is bounded and relevant |
| 5 | M5 — Production readiness | **Current** | Supported dependencies, CI, deployment controls, observability, migration, and recovery form a releasable baseline |

## 3. Completed pre-milestone foundation

The following work was complete before M1 and was not part of its exit gate:

- exposed credentials were revoked or rotated;
- supported repository histories were cleaned and re-rooted where required;
- redacted Gitleaks full-history scans pass in all three repositories;
- repositories are public and `development` is protected;
- at that pre-milestone checkpoint, only squash merges were enabled and one
  approval was required; this is historical evidence, not the active working
  rule;
- Docker Compose starts the complete frontend, backend, PostGIS, and MinIO
  stack;
- health endpoints, same-origin browser proxies, a safe schema baseline,
  provisional categories, and deterministic local mock places exist;
- the pre-M1 checks passed with eight backend tests and three frontend tests;
- map empty-state, interaction flicker, and incomplete basemap-style warnings
  have focused fixes.

A healthy local stack does not satisfy the security, permission, submission,
upload, moderation, or viewport milestone criteria by itself.

## 4. Completed milestone — M1 security and authorization foundation

### Objective

Close unsafe production boundaries and establish one explicit, backend-owned
permission and authentication model. Conservative denial is acceptable until
the final product decisions are approved.

### Entry decisions

The [M1 security and authorization contract](M1_SECURITY_POLICY.md) resolves:

1. the guest, user, moderator, and administrator permission matrix;
2. authenticated-only submission ownership and denial of guest submissions;
3. the difference between moderator and administrator powers;
4. five-minute access and seven-day refresh lifetimes, rotation, revocation,
   reuse, and transport;
5. logout and terminal refresh-failure behavior;
6. the server-handled, browser-hidden credential boundary;
7. minimum audit and privacy requirements for user and moderator identity.

Merge of the contract adopted these decisions. Application enforcement was
tracked in the six canonical M1 issues below.

### Exit outcome

All M1 security blockers are resolved at the merged application revisions
pinned by the workspace. The complete criterion-to-test mapping, smoke results,
CI evidence, and deliberately deferred production-build debt are recorded in
[M1 exit evidence](M1_EXIT_EVIDENCE.md).

### Tracked M1 issues

Backend:

- `smokemap-django-backend#13` — enforce the permission matrix;
- `smokemap-django-backend#48` — define and test JWT login and refresh.

Frontend:

- `smokemap-webapp#12` — replace token handling and remove secret logging;
- `smokemap-webapp#13` — guard destructive frontend actions;
- `smokemap-webapp#14` — complete the critical test foundation;
- `smokemap-webapp#4` — verify and close the mostly implemented same-origin
  browser boundary.

CI and exit follow-up:

- `smokemap-django-backend#74` — enforce backend tests and secret scanning;
- `smokemap-webapp#46` — enforce frontend secret scanning;
- `smokemap-webapp#48` — restore runtime compilation and add a startup gate;
- `smokemap#35` — enforce workspace integration and secret checks;
- `smokemap#37` — record this exit evidence and advance the roadmap.

### Completed M1 course of action

1. Verify and close the same-origin boundary issue if its smoke criteria pass.
2. Close anonymous place writes and restrict moderation conservatively on the
   backend.
3. Enforce the adopted permission matrix consistently in REST and GraphQL.
4. Implement and test the adopted login, expiry, refresh rotation/reuse,
   revocation, logout, and failure semantics.
5. Keep refresh credentials server-side and remove backend tokens from the
   browser-visible session.
6. Add frontend role checks for destructive actions while continuing to treat
   backend authorization as authoritative.
7. Add parameterized backend role tests and frontend authentication,
   moderation-guard, and failure-state tests.
8. Add CI checks for secret scanning, type/lint checks, and deterministic test
   commands once the suites are reliable.
9. Re-run direct backend and frontend-path authorization tests and record M1
   exit evidence.

### M1 exit criteria

M1 is done only when:

- anonymous users cannot create, update, or delete places;
- non-moderators cannot read or mutate pending submissions;
- presigning and image creation are denied or safely owner-bound;
- browser JavaScript cannot read backend access or refresh credentials;
- login, refresh, logout, revocation, and terminal failure are deterministic;
- REST and GraphQL enforce the approved role matrix;
- routine logs and CI artifacts contain no authentication secrets;
- automated tests fail when any protected boundary regresses.

## 5. Completed milestone — M2 viewport map vertical slice

### Exit outcome

Every M2 ordered item and exit criterion is demonstrated at merged root
`74383bc`, backend `48d1a8a`, and frontend `ad334dd`. The complete functional,
real-browser, natural-query-plan, performance, CI, and host-measurement record
is in [M2 exit evidence](M2_EXIT_EVIDENCE.md).

### Entry criteria

- M1 is complete.
- The map read API may remain public under an explicit read-only policy.

### Ordered work

1. Define `GET /api/v1/places?bbox=&zoom=&categories=` and its GeoJSON
   response.
2. Choose and query the authoritative geometry model directly.
3. Validate coordinate count/order, ranges, and maximum viewport area.
4. Define result caps and oversized-viewport behavior.
5. Confirm the PostGIS spatial index and query plan.
6. Add representative backend integration tests.
7. Create a focused frontend map-data module.
8. Refetch on settled viewport changes with cancellation and stale-response
   protection.
9. Render explicit initial, refreshing, empty, error, and success states.
10. Add an end-to-end pan test across disjoint regions.
11. Decompose the large map component only along responsibilities required by
    this slice.

### Exit criteria

- panning loads only current-viewport places;
- stale responses cannot replace newer responses;
- empty and error states remain interactive;
- invalid or oversized bounds fail predictably;
- the query meets an agreed performance budget.

## 6. Completed milestone — M3 submission and media vertical slice

### Exit outcome

Every M3 ordered-work item and exit criterion is demonstrated at merged root
`c2e5224`, backend `4fe254a`, and frontend `586e56d`. The complete
criterion-to-implementation mapping, race and validation evidence, the real
cross-application submission-and-media browser path, and CI/audit evidence
are recorded in [M3 exit evidence](M3_EXIT_EVIDENCE.md).

### Entry decision

The [M3 submission and media contract](M3_SUBMISSION_MEDIA_POLICY.md) resolves
the full state/transition and retention model, including a distinct expired
draft state and M4-reserved withdrawal and moderation transitions;
coordinate/address, stable category slug, tag, deterministic syntactic-only
HTTPS website, description, privacy-scoped spatial duplicate, and a
transaction-scoped lock keyed by the full canonical name; zero-or-more media
semantics and limits; retry and partial-failure behavior; private-before-
approval object visibility;
transactional three-slot owner-bound media; server-verified object-byte
SHA-256; and the unified 24-hour `cleanup_pending` SLA. It preserves the M1
authenticated-owner, guest-denial, authorization, audit, and fail-closed
legacy-write boundaries. Adoption of that contract satisfied the remaining
entry decision; it does not activate M4 withdrawal, approval, or rejection.

### Entry criteria

- M1 is complete.
- Submission ownership, state, coordinate, category, tag, and media policies
  are approved in the
  [M3 submission and media contract](M3_SUBMISSION_MEDIA_POLICY.md).

### Ordered work

1. Introduce M3-reachable `draft`, `pending`, and distinct `expired` states;
   distinctly model but reserve `withdrawn`, `approved`, and `rejected` for M4;
   and add database constraints and immutable lifecycle events.
2. Carry the M1 authenticated owner relation through every submission state;
   guest submission remains disabled.
3. Separate proposed content from approved places.
4. Move geocoding out of model `save()` into an explicit service or job.
5. Validate coordinates, exact stable category slugs, tags, optional HTTPS
   websites by deterministic syntax only with ASCII/Punycode multi-label hosts
   and a code-owned reserved/special-use rejection list, descriptions, and
   privacy-scoped duplicates with geography `ST_DWithin(..., 25.0)`; perform no
   DNS/network/fetch during website validation; remove global place-name
   uniqueness.
6. Serialize every M3 lifecycle transition with submission row locking, make
   writes retry-safe, preserve lifecycle history, and acquire a transaction-
   scoped lock keyed by the full canonical name before duplicate checks,
   independent of whether any matching row exists.
7. Add upload intents with exact storage object identifier, owner, submission,
   MIME, size, server-verified object-byte SHA-256, state, and transactionally
   locked three-slot accounting.
8. Issue one constrained presigned request per file.
9. Await, verify, attach, and clean up each upload independently, with
   deterministic failure handoff and the unified 24-hour `cleanup_pending`
   deletion-attempt SLA.
10. Rebuild the frontend form around deterministic zero-or-more image behavior.
11. Keep every legacy submission/media write fail-closed and both withdrawal
    transitions plus every approval or rejection transition disabled for all
    roles until M4.

### Exit criteria

- only create → `draft`, owner draft edit/media, `draft` → `pending`, and system
  `draft` → `expired` succeed; both withdrawal transitions, approval, and
  rejection remain fail-closed for every role;
- every M3 lifecycle and media/cleanup race has one deterministic winner and
  no extra state, event, attachment, slot, or cleanup target;
- validation failures leave no partial rows;
- duplicate checks use the exact 25-metre geography predicate without leaking
  another owner's private proposal or imposing global name uniqueness;
- zero, one, and multiple uploads handle retry and partial failure correctly;
- concurrent intent and attachment operations cannot allocate a fourth slot,
  and stored SHA-256 values are computed from object bytes by the backend;
- a client cannot attach another submission's object;
- abandoned objects and intents have a tested exact-key cleanup path whose
  deletion attempt begins within 24 hours of `cleanup_pending`.

## 7. Completed milestone — M4 moderation and search

### Exit outcome

Every M4 ordered-work item and exit criterion is demonstrated at merged root
`ac86d7a`, backend `d9ddb01`, and frontend `d466268`. The complete lifecycle,
authorization, audit, race, rollback, bounded-search, stale-response,
public-media, real-browser, CI, and final-audit record is in
[M4 exit evidence](M4_EXIT_EVIDENCE.md).

### Activation boundary

The M3 contract distinctly models `draft` → `withdrawn`, `pending` →
`withdrawn`, `pending` → `approved`, and `pending` → `rejected`, but all four
transitions and every legacy equivalent remain disabled throughout M3. M4 must
implement owner withdrawal and moderator rejection as distinct lifecycle
actions and may enable them, together with approval, only with the serialized
services and M4 race, rollback, authorization, audit, privacy-scoped duplicate,
cleanup, and public-delivery tests required by that contract. Withdrawal and
rejection are each separate from system draft expiry and from exceptional
administrator hard deletion, which remains the separate M1 audited operation.

### Entry criteria

- M1 and M3 are complete.
- M2 is complete for map/search integration.

### Ordered work

1. Implement both owner withdrawal transitions, moderator approval, and
   moderator rejection as explicit lifecycle services that lock the submission
   inside `transaction.atomic()` and recheck every precondition; approval also
   acquires a transaction-scoped lock keyed by the full canonical name,
   independent of existing rows, before duplicate revalidation.
2. Record the backend-owned authenticated owner or moderator, as applicable,
   and immutable lifecycle/audit events.
3. Keep owner withdrawal and moderator rejection distinct from each other,
   from system expiry, and from the M1 exceptional audited hard-deletion path.
4. Add rollback, injected-failure, simultaneous-withdrawal, simultaneous-
   approval, simultaneous-rejection, finalize/withdrawal, withdrawal/expiry,
   approval/rejection, approval/withdrawal, rejection/withdrawal, duplicate-
   approval, and media-cleanup race tests before enabling any M4 transition.
5. Define a bounded search contract with geographic/category context.
6. Add indexes, ranking, result caps, debounce, cancellation, and stale-response
   protection.
7. Refresh affected UI state after submission and moderation.

### Search scope

The M4 search criteria cover the search and autocomplete surfaces: the bounded
backend search API and the legacy GraphQL name-autocomplete and name-lookup
fields. They do not cover the legacy public listings, GraphQL `places` and REST
`/places/`. Those listings are a separate contract. They are unbounded but
return only approved places, never submission requests. Backend issue
`smokemap-django-backend#105` tracks deprecating GraphQL `places` and pinning
that behavior with tests. The listings may be bounded or removed only after the
frontend search migration, `smokemap-webapp#10`, has shipped and no supported
client depends on them.

### Exit criteria

- partial or concurrent moderation cannot corrupt state;
- every withdrawal, approval, and rejection action is authorized, auditable,
  and distinct from exceptional M1 audited hard deletion;
- search and autocomplete never retrieve the full place-name collection, as
  scoped above;
- results are capped, relevant, and protected from response reordering.

## 8. Current milestone — M5 production readiness

### Entry criteria

- M1 through M4 have demonstrated their exit criteria.

### Ordered work

1. Select supported Node, Next.js, Python, Django, PostgreSQL, and PostGIS
   versions.
2. Consolidate dependency manifests and lock strategies.
3. Close obsolete dependency PRs and regenerate upgrades against current
   development history.
4. Add CI, builds, startup validation, structured redacted logging, correlation
   IDs, and deployment checks.
5. Publish a versioned API contract artifact.
6. Document and rehearse `development → staging → main` promotion, rollback,
   backup, and recovery.
7. Inventory and migrate legacy places, requests, locations, media, tags, and
   users through reversible migrations.
8. Retire duplicate write paths, obsolete clients, and the denormalized
   `Location` model only after parity is proven.
9. Decide whether a read-only GraphQL compatibility adapter remains justified.

### Future PoC demo deployment design

Status: planning only; agreed 2026-10-17. This design does not deploy a demo,
complete an M5 ordered-work item, or demonstrate an M5 exit criterion. The
supported-version baseline remains separate work in open root issue `#106` and
PR `#107`; this plan neither supersedes nor closes them. Implementation must be
split into focused owning-repository and root integration issues in the M5
order above.

#### Host and network boundary

- Keep the existing Jenkins/HCP development VM and create a separate
  VirtualBox demo VM on the same physical host. The demo VM is not another
  role for the development VM and receives no development bind mounts or
  credentials.
- Attach an internal-only NIC to both VMs on an isolated subnet, with
  `172.29.50.0/24` as the example range. Allow deployment SSH to the demo VM
  only from the Jenkins/HCP VM over that NIC and only through a limited
  deployment identity. Do not route this subnet to the LAN or Internet.
- Give the demo VM a separate NAT interface for outbound image pulls, GitHub
  access, updates, Tailscale, and Cloudflare Tunnel. Configure no hypervisor,
  router, or host inbound port forwards.
- Use Tailscale with restricted identities and ACLs for exceptional
  administration. It is not a public application ingress or an unrestricted
  deployment path.
- Run `cloudflared` inside the demo stack and establish outbound-only
  Cloudflare Tunnel connections. Publish HTTPS for the frontend and a
  distinct, restricted media hostname needed for browser uploads. No other
  hostname or direct socket is public.

#### Demo Compose boundary

The future demo-specific Compose definition runs these services on private
container networks:

- a Next.js frontend produced by a production build and started in production
  mode;
- Django served by Gunicorn, with backend authorization remaining
  authoritative;
- PostgreSQL with PostGIS;
- MinIO for media objects;
- the periodic media-cleanup worker; and
- `cloudflared` as the only public ingress path.

Only the frontend HTTPS hostname and the restricted media hostname are
publicly routable through the Tunnel. The backend, database, MinIO console,
SSH, and container or host management endpoints have no public route. The
media hostname exposes only the MinIO API surface required for application-
issued, signed presigned POST uploads; it is not an anonymous bucket or
console endpoint. MinIO CORS permits the exact demo frontend origin and only
the required upload methods and headers. Presigned POST policy conditions
continue to constrain bucket, exact object key, content type, size, expiry,
and authenticated owner/submission workflow, and Django verifies the stored
object before attachment under the M3/M4 media contract.

#### Build, release, migration, and recovery

- Preserve the independently deployed frontend and backend repositories.
  Their GitHub CI gates build and test each application commit before it is
  eligible for a demo release. Merge application changes in their owning
  repositories first, then update the root repository's pinned gitlinks in a
  separate tested integration PR.
- Build release images from those exact commits, identify every image by an
  immutable digest, and record a release manifest mapping the root commit,
  both gitlinks, configuration version, schema state, and image digests. The
  demo VM pulls digests; it never builds an unreviewed checkout or deploys a
  floating tag.
- Require the root GitHub CI integration, browser-workflow, and secret checks
  at the pinned release commit before deployment. Jenkins uses the restricted
  internal NIC and a least-privilege deployment identity that can pull the
  approved release and operate only the demo deployment; it receives neither
  general administrator access nor application/database secrets outside the
  minimum deployment interface.
- Serialize deployments. After a pre-deploy database and media backup, run
  reviewed Django migrations exactly once as a controlled release step, record
  their result, start the digest-pinned services, and run smoke tests before
  declaring the release available. Routine application container startup must
  not race or independently repeat the migration step.
- Retain the prior release manifest and image digests. Roll back application
  services to those digests when the schema remains backward-compatible. If a
  migration is not backward-compatible, stop and follow its rehearsed reverse
  migration or restore procedure rather than pretending an image rollback
  also rolls back data.
- Back up PostgreSQL and MinIO media together at a documented consistency
  point, protect and retain the backups outside the demo VM, and rehearse a
  restore into an isolated target. Recovery evidence must reconcile database
  image metadata with restored object keys.

An illustrative starting allocation for the demo VM is 4 vCPU, 8 GB RAM, and
60 GB disk, subject to measured build/runtime headroom and backup growth. The
incremental subscription estimate is `$0` only while the existing physical
host, VirtualBox, Jenkins/HCP VM, Tailscale plan, Cloudflare plan, DNS, and
storage capacity remain available within their current allowances. Usage,
egress, domain, backup, or capacity changes can introduce cost. Both VMs still
share one physical host, so host, disk, power, or uplink failure is a known
single point of failure; this PoC is not a high-availability production design.

#### Future implementation checklist

1. Open focused frontend, backend, and root issues; define the demo hostnames,
   DNS ownership, secret owners, retention targets, and operator runbook.
2. Provision the isolated demo VM, internal NIC and example subnet, separate
   NAT, host firewall, restricted deployment SSH identity, and restricted
   Tailscale administration; prove there are no port forwards.
3. Add production frontend and Gunicorn backend images in their owning
   repositories, pin their base and release images by digest, and pass each
   repository's GitHub CI and secret gates.
4. Add the demo Compose and `cloudflared` configuration in the root repository
   without collapsing application ownership; expose only the two approved
   Tunnel hostnames and keep database, console, backend, SSH, and management
   sockets private.
5. Configure private MinIO buckets, exact-origin CORS, short-lived signed
   presigned POST policies, cleanup, and end-to-end upload verification.
6. Implement the release manifest, deployment lock, least-privilege deploy
   command, one-time migration job, health checks, and post-deploy smoke suite.
7. Automate coordinated database/media backup and rehearse restore, compatible
   digest rollback, and the incompatible-schema recovery path.
8. Measure CPU, memory, disk, backup, and tunnel behavior; revise the example
   allocation and conditional cost statement before calling the PoC ready.

#### Acceptance gates for a future implementation

- **Isolation:** From an external network, scans and direct connection tests
  reach only Cloudflare HTTPS; from the LAN and NAT side, SSH, PostgreSQL,
  MinIO API/console, backend, and management ports are unreachable. Deployment
  SSH succeeds only from the Jenkins/HCP VM on the internal subnet, and an
  authorized Tailscale administrator can use only the documented admin path.
- **Artifact provenance:** A release record maps an immutable root commit and
  its exact frontend/backend gitlinks to CI-passing image digests. The running
  containers match those digests and use no floating image tags.
- **Controlled deployment:** The limited deployment identity completes a
  serialized deployment without broad host, GitHub, database, or secret-store
  authority. Migrations run once, are recorded, and fail closed before traffic
  promotion.
- **Application and media:** Frontend, liveness/readiness, GraphQL, bounded
  viewport, search, authentication, submission, moderation, approved media,
  and cleanup smoke tests pass. A real browser presigned POST succeeds only
  from the exact allowed origin and within its signed key/type/size/expiry
  conditions; altered or expired requests and disallowed CORS origins fail.
- **Exposure:** The frontend and restricted media hostname are the only public
  routes. The media route cannot reach the MinIO console, list buckets, or
  perform unsigned writes; backend and storage administration remain private.
- **Recovery:** A rehearsal restores the paired database/media backup into an
  isolated target and reconciles metadata/object keys. A compatible release
  rolls back to the recorded prior image digests, and an incompatible schema
  follows the rehearsed reverse-or-restore path within documented recovery
  targets.
- **Operations and confidentiality:** Resource measurements fit the approved
  capacity with documented headroom; health, deployment, backup, and Tunnel
  failures are observable; logs and CI artifacts contain no tokens, sessions,
  credentials, presigned fields, authorization headers, or secret-bearing
  environment values.

### Exit criteria

- clean checkouts pass required CI;
- supported deployments use controlled schema migrations;
- staging promotion, rollback, backup, and recovery are rehearsed;
- production data is reconciled;
- each workflow has one supported implementation and contract.

## 9. Non-blocking backlog hygiene

Completed on 2026-08-19 under root issue `#13`:

1. Stale backend Dependabot PRs `#30`, `#38`, `#40`, `#41`, `#46`, and `#47`
   were closed without merging and with an M5 regeneration explanation.
2. Backend branch `13-secure-django-endpoints` was re-verified at 116 commits
   behind `development` with zero unique commits and was deleted.
3. Backend `muxalko-patch-1` was preserved because it has one unique commit;
   backend `development`, `main`, and `staging` were also preserved.
4. The intentionally independent frontend `development`, `staging`, and
   `main` clean-root trees were preserved.
5. Backend deployment-branch reconciliation remains deferred to the deliberate
   M5 promotion plan.

No remaining item in this hygiene list delays the M1 security blockers.

## 10. Progress log

| Date | Milestone or checkpoint | Status change | Evidence |
| --- | --- | --- | --- |
| 2026-08-10 | Joint assessment | Completed | `ARCHITECTURE_ASSESSMENT.md` |
| 2026-08-10 | Local engineering baseline | Established | `LOCAL_CHECKPOINT.md` |
| 2026-08-16 | Credential/history cleanup | Completed | Clean supported histories, revoked credentials, redacted scans |
| 2026-08-19 | Pre-milestone audit | Completed | `PRE_MILESTONE_AUDIT.md` |
| 2026-08-19 | Non-blocking backlog hygiene | Completed | Root issue `#13`; six stale backend dependency PRs closed; zero-unique-commit branch retired |
| 2026-08-19 | M1 security and authorization contract | Adopted | `M1_SECURITY_POLICY.md`; root issue `#15` |
| 2026-08-19 | M1 | Set to Current | Canonical M1–M5 plan synchronized with GitHub |
| 2026-08-21 | M1 | Done | All exit criteria demonstrated in `M1_EXIT_EVIDENCE.md`; root issue `#37` |
| 2026-08-21 | M2 | Set to Current | M1 exit gate demonstrated; viewport vertical slice may begin |
| 2026-08-30 | M2 | Done | All ordered work and exit criteria demonstrated in `M2_EXIT_EVIDENCE.md` at root `74383bc`, backend `48d1a8a`, and frontend `ad334dd` |
| 2026-08-30 | M3 | Set to Current | `M3_SUBMISSION_MEDIA_POLICY.md` adopted under root issue `#59`; complete entry policy approved |
| 2026-09-04 | M3 | Done | All ordered work and exit criteria demonstrated in `M3_EXIT_EVIDENCE.md` at root `c2e5224`, backend `4fe254a`, and frontend `586e56d`; final audit `586885c1c8844109b041d94d0befdc8b` returned `READY_TO_CLOSE_M3` |
| 2026-09-04 | M4 | Set to Current | M3 exit gate demonstrated; moderation and search vertical slice may begin |
| 2026-10-07 | M4 | Done | All ordered work and exit criteria demonstrated in `M4_EXIT_EVIDENCE.md` at root `ac86d7a`, backend `d9ddb01`, and frontend `d466268`; final audit `302a3f86d1864c0e941133e24b918e23` returned `READY_TO_CLOSE_M4` |
| 2026-10-07 | M5 | Set to Current | M4 exit gate demonstrated; production-readiness work may begin |
| 2026-10-17 | M5 PoC demo deployment | Future design documented | Root issue `#108`; planning only for an isolated VirtualBox demo VM, restricted outbound-Tunnel exposure, digest-pinned release controls, and rehearsed recovery; no M5 item or exit criterion is complete |
