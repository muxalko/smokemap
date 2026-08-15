# Smokemap Execution Roadmap

Status: Active planning document

Last updated: 2026-08-10

Evidence base: [Joint Architecture and Engineering Assessment](ARCHITECTURE_ASSESSMENT.md)

## 1. How to use this roadmap

This document orders the work required to move Smokemap from the current prototype to a safe, testable product.

Working rules:

1. Keep one milestone in active development at a time.
2. Do not start a dependent milestone before its entry criteria are satisfied.
3. Keep changes small enough to verify and release independently.
4. Add tests at the boundary being changed, not as a later cleanup phase.
5. Preserve legacy behavior only when it is intentional and documented.
6. Record product and architecture decisions before implementation depends on them.
7. Update this roadmap when evidence changes; do not maintain a separate hidden backlog.

Status values:

- **Current:** the only milestone receiving feature-development effort.
- **Next:** ready after the current milestone exits.
- **Blocked:** waiting for a named decision or external action.
- **Later:** ordered but not ready to begin.
- **Done:** exit criteria have been demonstrated.

## 2. Ordered roadmap

| Order | Milestone | Status | Depends on | Primary outcome |
|---:|---|---|---|---|
| 0 | Contain active security risks | **Current** | None | Unsafe production boundaries are closed |
| 1 | Agree on product and architecture decisions | Next | Immediate containment actions | Stable requirements and permission model |
| 2 | Establish the engineering baseline | Later | Milestone 1 | Reproducible local development and CI |
| 3 | Build the viewport-to-GeoJSON vertical slice | Later | Milestone 2 | Correct, bounded map browsing |
| 4 | Consolidate authentication and roles | Later | Milestones 1–2 | Server-side credentials and backend authorization |
| 5 | Introduce the submission domain | Later | Milestones 1, 2, and 4 | Durable submission lifecycle |
| 6 | Rebuild media upload | Later | Milestone 5 | Verified, recoverable uploads |
| 7 | Implement transactional moderation | Later | Milestones 4–6 | Atomic approval and auditable rejection |
| 8 | Rebuild search and place details | Later | Milestones 2–3 | Bounded, indexed discovery |
| 9 | Migrate data and retire legacy paths | Later | Milestones 3–8 | One supported architecture |

## 3. Current focus — Milestone 0: contain active security risks

### Objective

Make the current deployment safe enough to remain online while the staged migration is developed.

This milestone is containment, not the target architecture. Conservative denial is acceptable where the final role model has not yet been approved.

### Ordered work

#### 0.1 Credential incident response

- Identify the credentials referenced by the tracked production-named environment files without copying their values into issues, chat, or logs.
- Rotate or revoke every affected database, Django, storage, OAuth, and deployment credential.
- Remove credential files and rotated application logs from Git tracking.
- Purge sensitive historical blobs from repository history using an agreed, coordinated procedure.
- Add secret scanning to local checks and CI.

Verification:

- Old credentials no longer authenticate.
- Secret scanning passes on the current tree and full history.
- A fresh clone contains no production credential files or application logs.

Operational note: credential rotation and history rewriting affect external systems and collaborators. They require explicit operational coordination before execution.

#### 0.2 Close public write endpoints

- Convert the public place endpoint from `ModelViewSet` to read-only list/retrieve behavior.
- Deny anonymous access to moderation operations.
- Temporarily restrict approval and deletion to the existing trusted administrator group until the final permission matrix is approved.
- Decide whether anonymous submissions remain enabled during containment.
- If anonymous submissions remain enabled, rate-limit them and keep all secondary mutations bound to the created submission.
- Disable image-record creation and presigning if they cannot yet be safely bound to a submission.

Verification:

- Anonymous clients cannot create, update, or delete places.
- A normal authenticated account cannot read, approve, or delete pending submissions.
- Only the temporary trusted administrator role can use moderation operations.
- Direct backend requests and Next.js server actions produce the same authorization result.

#### 0.3 Remove authentication data from logs and sessions

- Remove logging of tokens, sessions, credentials-provider requests, login responses, cookies, and middleware token objects.
- Add central redaction for authorization headers, cookies, tokens, passwords, and presigned form fields.
- Stop copying backend access and refresh tokens into the browser-visible NextAuth session.
- Keep refresh credentials server-side.
- Define the behavior for refresh failure and force sign-out when recovery is unsafe.
- Revoke the backend refresh credential on sign-out where supported.

Verification:

- `/api/auth/session` contains user profile and role data but no backend credentials.
- Access and refresh flows still work through the protected server path.
- Automated log-capture tests contain no token or password material.
- Refresh failure results in a clear, deterministic session state.

#### 0.4 Add containment regression tests

- Add backend tests for anonymous, authenticated non-admin, and administrator access to every write and moderation operation.
- Add frontend tests for session shaping and protected server actions.
- Add a minimal test proving that public place reads still work.

Verification:

- The security matrix runs in one documented command per repository.
- Tests fail if public writes, non-admin moderation, or browser-visible refresh tokens return.

### Milestone 0 exit criteria

Milestone 0 is done only when:

- All affected credentials have been rotated or revoked.
- No unauthenticated place write is possible.
- Non-admin users cannot moderate.
- Refresh tokens are absent from browser-visible sessions.
- Routine logs contain no authentication secrets.
- Regression tests enforce all of the above.

## 4. Milestone 1: agree on product and architecture decisions

### Objective

Remove product ambiguity before it becomes schema, authorization, and workflow code.

### Ordered decisions

1. Approve the guest, user, moderator, and administrator permission matrix.
2. Decide whether guests may submit and how guest ownership or capability is represented.
3. Decide whether images are required and when they become publicly readable.
4. Define submission states and permitted transitions.
5. Define rejection, deletion, retention, and recovery behavior.
6. Decide whether corrections to existing places use the same submission workflow.
7. Decide place uniqueness rules; do not assume names are globally unique.
8. Decide whether location comes from selected coordinates, geocoding, or both.
9. Define audit and privacy requirements for users, IP addresses, moderators, and media.
10. Confirm expected scale for places, viewport results, search, and upload volume.
11. Confirm that REST/OpenAPI plus GeoJSON is the target API and GraphQL is a migration adapter.
12. Confirm that repositories remain separate during stabilization.

Deliverables:

- Permission matrix.
- Submission state diagram.
- Media visibility and retention policy.
- API-style architecture decision record.
- Authentication architecture decision record.
- Repository strategy decision record.

Exit criteria:

- Every decision above is accepted, assigned an owner, or explicitly deferred without blocking Milestone 2.

## 5. Milestone 2: establish the engineering baseline

### Objective

Make development, verification, and deployment reproducible before replacing product workflows.

### Ordered work

1. Select supported Node.js, Next.js, Python, Django, PostgreSQL, and PostGIS versions.
2. Consolidate each repository onto one dependency manifest and lock strategy.
3. Repair production password-hasher and server dependencies.
4. Document environment variables without values and validate them at startup.
5. Provide one complete local-stack command including frontend, backend, PostGIS, and a local S3-compatible service.
6. Define deterministic `format`, `lint`, `typecheck`, `test`, and `build` commands.
7. Add CI to both repositories.
8. Add `/health/live` and `/health/ready` to the backend.
9. Publish a versioned API contract artifact for frontend validation and generation.
10. Add structured logging with redaction and request correlation IDs.

Exit criteria:

- A new developer can start the complete stack from documented steps.
- Clean checkouts pass all CI checks.
- Deployment does not run `makemigrations`.
- Schema migration is a controlled release step.
- Frontend contract checks do not require a manually running localhost backend.

## 6. Milestone 3: build the viewport-to-GeoJSON vertical slice

### Objective

Deliver the first clean end-to-end feature on the target architecture.

### Ordered work

1. Define `GET /api/v1/places?bbox=&zoom=&categories=` and its GeoJSON response.
2. Choose the authoritative geometry model and query it directly.
3. Validate coordinate count, order, latitude/longitude ranges, and maximum viewport area.
4. Define result caps and behavior when a viewport exceeds them.
5. Confirm and test the PostGIS spatial index and query plan.
6. Add backend integration tests against PostGIS.
7. Create a focused frontend map-data module.
8. Refetch on viewport changes with debounce, cancellation, and stale-response protection.
9. Render explicit initial-loading, refreshing, empty, error, and success states.
10. Add an end-to-end pan test across two disjoint regions.

Exit criteria:

- Panning loads only places from the current viewport.
- An older response cannot replace a newer response.
- Empty areas remain interactive and do not appear to load forever.
- Oversized or invalid bounds are rejected predictably.
- The query remains within the agreed performance budget.

## 7. Milestone 4: consolidate authentication and roles

### Objective

Make the backend authoritative for permissions while keeping credentials out of browser JavaScript.

### Ordered work

1. Implement the approved roles through Django groups and permissions or equivalent explicit policies.
2. Choose one protected-request path, preferably the Next.js backend-for-frontend for the current separate-origin deployment.
3. Keep refresh credentials in a server-only, encrypted, HTTP-only session.
4. Remove manual browser/backend cookie combinations and unused authentication clients.
5. Add refresh rotation or reuse rules, revocation, expiry handling, and sign-out behavior.
6. Add login and protected-operation throttling.
7. Add the complete role-matrix integration suite.
8. Restore discoverable sign-in, profile, and role-appropriate navigation.

Exit criteria:

- Browser JavaScript cannot read backend tokens.
- Backend permissions decide every protected operation.
- Guest, user, moderator, and administrator tests match the approved matrix.
- Sign-out revokes or invalidates the complete session chain.

## 8. Milestone 5: introduce the submission domain

### Objective

Represent community proposals as durable, validated state rather than partially duplicated rows.

### Ordered work

1. Add the approved submission states and database constraints.
2. Link authenticated submissions to users; implement the approved guest-ownership mechanism if guests may submit.
3. Separate proposed content from the approved `Place` record.
4. Link an approved submission to the place it created or changed.
5. Move geocoding out of model `save()` into an explicit service or job.
6. Validate coordinates, category, tags, website, description, and uniqueness at the API boundary.
7. Make submission creation idempotent where clients may retry.
8. Preserve rejected, withdrawn, and approved history.
9. Migrate the frontend form into a focused submission feature.

Exit criteria:

- Only documented state transitions succeed.
- Failed validation leaves no address, submission, or place residue.
- Submission ownership and history are queryable and test-covered.

## 9. Milestone 6: rebuild media upload

### Objective

Make multi-image uploads verifiable, retryable, and recoverable.

### Ordered work

1. Add a media/upload-intent model with object key, owner, submission, expected MIME type, expected size, and state.
2. Issue one presigned request per exact object key.
3. Constrain content length and MIME type in the storage policy.
4. Upload each file with independent request data.
5. Await every upload and completion call.
6. Verify object existence, size, and type before attachment.
7. Make completion idempotent.
8. Add cleanup for expired or abandoned intents and storage objects.
9. Define deletion behavior for rejected submissions and deleted places.

Exit criteria:

- Tests cover zero files, multiple files, partial failure, retry, abandonment, invalid MIME, excessive size, and cleanup.
- The UI cannot report full success while any required upload or media record is incomplete.
- A client cannot attach another submission's object.

## 10. Milestone 7: implement transactional moderation

### Objective

Make approval and rejection authorized, atomic, auditable, and concurrency-safe.

### Ordered work

1. Implement moderation through a dedicated application service.
2. Lock the submission row during transitions.
3. Run approval in `transaction.atomic()`.
4. Create or update the authoritative place without a manually synchronized `Location` row.
5. Attach only verified media.
6. Record the authenticated moderator and immutable audit event.
7. Implement rejection separately from deletion.
8. Add confirmation and deterministic error recovery in the frontend.
9. Add injected-failure and simultaneous-approval tests.

Exit criteria:

- Failure at any approval step rolls back the entire database transition.
- Two simultaneous approvals produce one place transition and one successful audit event.
- Every moderation action identifies the authenticated moderator.

## 11. Milestone 8: rebuild search and place details

### Objective

Provide bounded, relevant discovery without full-table reads or per-keystroke server-action churn.

### Ordered work

1. Define a bounded search contract with result limit and geographic/category context.
2. Decide and document case, language, normalization, and spelling behavior.
3. Add the required PostgreSQL indexes and ranking strategy.
4. Return only fields needed for suggestions and results.
5. Add frontend debounce, cancellation, and stale-response protection.
6. Consolidate suggestions, result selection, fly-to behavior, and place details.
7. Add relevance, empty, error, and performance tests.

Exit criteria:

- Search never retrieves the complete place-name collection.
- Results are capped and meet the agreed relevance behavior.
- Out-of-order responses cannot overwrite current results.

## 12. Milestone 9: migrate data and retire legacy paths

### Objective

Finish the migration with one supported source of truth and one documented API architecture.

### Ordered work

1. Inventory and clean existing requests, places, locations, images, tags, and users.
2. Write rehearsable, reversible data migrations.
3. Compare legacy and target read behavior on representative data.
4. Move frontend workflows to `/api/v1` behind independently releasable changes.
5. Stop writes through legacy GraphQL mutations.
6. Remove the denormalized `Location` model after parity is proven.
7. Remove obsolete authentication clients and dead code.
8. Decide whether any read-only GraphQL endpoint remains justified.
9. Remove the compatibility adapter after an announced deprecation window.
10. Update architecture documentation and operating procedures.

Exit criteria:

- Contract and end-to-end tests pass with legacy paths disabled.
- Production data has been migrated and reconciled.
- Rollback and recovery procedures have been rehearsed.
- Only one supported implementation exists for each workflow.

## 13. Milestone dependency map

```text
M0 Security containment
 |
 v
M1 Product and architecture decisions
 |
 v
M2 Engineering baseline
 |\
 | +--------------------+
 v                      v
M3 Viewport slice       M4 Authentication and roles
                         |
                         v
                       M5 Submission domain
                         |
                         v
                       M6 Media upload
                         |
                         v
                       M7 Moderation

M3 + M2 ----------------> M8 Search and details

M3 through M8 ----------> M9 Legacy retirement
```

## 14. Deliberately deferred work

The following should not distract from the current milestone unless new evidence makes them blocking:

- Monorepo migration.
- Native mobile applications.
- Server-side map clustering before a measured need exists.
- General-purpose background-job infrastructure before geocoding or cleanup requirements justify it.
- Advanced social login providers.
- Large visual redesigns unrelated to workflow correctness.
- New community features beyond the agreed core workflows.

## 15. Progress log

Update this table only when exit criteria have been demonstrated.

| Date | Milestone | Status change | Evidence |
|---|---|---|---|
| 2026-08-10 | Joint assessment | Completed | `docs/ARCHITECTURE_ASSESSMENT.md` |
| 2026-08-10 | Milestone 0 | Set to Current | Ordered execution roadmap created |
