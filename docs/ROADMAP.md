# Smokemap execution roadmap

Status: Active planning document

Last updated: 2026-08-19

Evidence base:

- [Joint architecture and engineering assessment](ARCHITECTURE_ASSESSMENT.md)
- [Pre-milestone audit](PRE_MILESTONE_AUDIT.md)

## 1. Planning model

GitHub milestones M1 through M5 are the canonical execution sequence. The
earlier M0 through M9 plan was useful for identifying dependencies, but its
numbering no longer matches the repository milestones. The detailed concerns
from that plan are retained below under the five canonical milestones.

Working rules:

1. Keep one milestone in active product development at a time.
2. Do not start a dependent milestone until its entry criteria are satisfied.
3. Use issue → branch → focused commit → pull request → approval → squash merge.
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
| 1 | M1 — Security and authorization foundation | **Current** | Unsafe public boundaries are closed; credentials remain server-side; the role matrix is enforced and tested |
| 2 | M2 — Viewport map vertical slice | Next | Every settled viewport loads bounded, indexed GeoJSON with deterministic UI states |
| 3 | M3 — Submission and media vertical slice | Later | Validated submissions and zero-or-more verified uploads work end to end |
| 4 | M4 — Moderation and search | Later | Moderation is atomic and auditable; search is bounded and relevant |
| 5 | M5 — Production readiness | Later | Supported dependencies, CI, deployment controls, observability, migration, and recovery form a releasable baseline |

## 3. Completed pre-milestone foundation

The following work is complete and is not part of the remaining M1 exit gate:

- exposed credentials were revoked or rotated;
- supported repository histories were cleaned and re-rooted where required;
- redacted Gitleaks full-history scans pass in all three repositories;
- repositories are public and `development` is protected;
- only squash merges are enabled and one approval is required;
- Docker Compose starts the complete frontend, backend, PostGIS, and MinIO
  stack;
- health endpoints, same-origin browser proxies, a safe schema baseline,
  provisional categories, and deterministic local mock places exist;
- current checks pass with eight backend tests and three frontend tests;
- map empty-state, interaction flicker, and incomplete basemap-style warnings
  have focused fixes.

A healthy local stack does not satisfy the security, permission, submission,
upload, moderation, or viewport milestone criteria by itself.

## 4. Current milestone — M1 security and authorization foundation

### Objective

Close unsafe production boundaries and establish one explicit, backend-owned
permission and authentication model. Conservative denial is acceptable until
the final product decisions are approved.

### Entry decisions

Before role implementation depends on them, approve or explicitly defer:

1. the guest, user, moderator, and administrator permission matrix;
2. whether guests may submit and how guest ownership is represented;
3. the difference between moderator and administrator powers;
4. access/refresh lifetimes, rotation, revocation, reuse, and transport;
5. logout and terminal refresh-failure behavior;
6. the server-only session boundary used for protected backend requests;
7. minimum audit and privacy requirements for user and moderator identity.

These decisions are the next planned activity after the planning-sync change is
merged. They do not postpone conservative containment of anonymous writes.

### Unfinished security blockers

Current source evidence shows that:

- `PlaceViewSet` remains a full public `ModelViewSet` with `AllowAny`;
- pending-request reads, approval, and deletion require only authentication,
  not moderator or administrator authority;
- presigning and image-record creation remain publicly callable and are not
  bound to an owner or upload intent;
- NextAuth copies backend access and refresh tokens into the browser-visible
  session;
- destructive frontend server actions do not independently check the role;
- the role matrix and complete token lifecycle lack regression coverage;
- secret scanning and application tests are not yet enforced in CI.

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

### Ordered M1 course of action

1. Verify and close the same-origin boundary issue if its smoke criteria pass.
2. Close anonymous place writes and restrict moderation conservatively on the
   backend.
3. Record the final permission matrix and enforce it consistently in REST and
   GraphQL.
4. Define and test login, expiry, refresh rotation/reuse, revocation, logout,
   and failure semantics.
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

## 5. M2 — Viewport map vertical slice

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

## 6. M3 — Submission and media vertical slice

### Entry criteria

- M1 is complete.
- Submission ownership, state, coordinate, category, tag, and media policies
  are approved.

### Ordered work

1. Introduce explicit submission states and database constraints.
2. Link submissions to authenticated users or the approved guest capability.
3. Separate proposed content from approved places.
4. Move geocoding out of model `save()` into an explicit service or job.
5. Validate coordinates, category, tags, website, description, and uniqueness
   at the API boundary.
6. Make submission creation retry-safe and preserve lifecycle history.
7. Add upload intents with exact object key, owner, submission, MIME, size, and
   state.
8. Issue one constrained presigned request per file.
9. Await, verify, complete, and clean up each upload independently.
10. Rebuild the frontend form around deterministic zero-or-more image behavior.

### Exit criteria

- only documented submission transitions succeed;
- validation failures leave no partial rows;
- zero, one, and multiple uploads handle retry and partial failure correctly;
- a client cannot attach another submission's object;
- abandoned objects and intents have a tested cleanup path.

## 7. M4 — Moderation and search

### Entry criteria

- M1 and M3 are complete.
- M2 is complete for map/search integration.

### Ordered work

1. Implement moderation through a dedicated service with row locking and
   `transaction.atomic()`.
2. Record the authenticated moderator and immutable audit events.
3. Separate rejection, withdrawal, and deletion.
4. Add rollback, injected-failure, and simultaneous-approval tests.
5. Define a bounded search contract with geographic/category context.
6. Add indexes, ranking, result caps, debounce, cancellation, and stale-response
   protection.
7. Refresh affected UI state after submission and moderation.

### Exit criteria

- partial or concurrent moderation cannot corrupt state;
- every moderation action is authorized and auditable;
- search never retrieves the full place-name collection;
- results are capped, relevant, and protected from response reordering.

## 8. M5 — Production readiness

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

### Exit criteria

- clean checkouts pass required CI;
- supported deployments use controlled schema migrations;
- staging promotion, rollback, backup, and recovery are rehearsed;
- production data is reconciled;
- each workflow has one supported implementation and contract.

## 9. Non-blocking backlog hygiene

Perform after this planning synchronization is approved and merged:

1. Close stale backend Dependabot PRs `#30`, `#38`, `#40`, `#41`, `#46`, and
   `#47` with an explanation that dependency work will be regenerated against
   the current M5 baseline.
2. Verify obsolete remote branches before deletion. The backend
   `13-secure-django-endpoints` branch currently has no commits unique from
   `development`; do not delete branches with unique history.
3. Preserve the intentionally independent frontend `development`, `staging`,
   and `main` clean-root trees.
4. Preserve backend history and reconcile deployment branches only through a
   deliberate promotion plan.

This hygiene must not delay the M1 security blockers.

## 10. Progress log

| Date | Milestone or checkpoint | Status change | Evidence |
| --- | --- | --- | --- |
| 2026-08-10 | Joint assessment | Completed | `ARCHITECTURE_ASSESSMENT.md` |
| 2026-08-10 | Local engineering baseline | Established | `LOCAL_CHECKPOINT.md` |
| 2026-08-16 | Credential/history cleanup | Completed | Clean supported histories, revoked credentials, redacted scans |
| 2026-08-19 | Pre-milestone audit | Completed | `PRE_MILESTONE_AUDIT.md` |
| 2026-08-19 | M1 | Set to Current | Canonical M1–M5 plan synchronized with GitHub |
