# M1 exit evidence

Status: Demonstrated

Recorded: 2026-08-21

This record closes **M1 — Security and authorization foundation** against the
contract in [M1_SECURITY_POLICY.md](M1_SECURITY_POLICY.md) and the exit criteria
in [ROADMAP.md](ROADMAP.md). Evidence was collected from the workspace baseline
that pins backend `83c4be8` and frontend `8ce02be`.

## Exit-criterion evidence

| M1 exit criterion | Implementation and regression evidence |
| --- | --- |
| Anonymous users cannot create, update, or delete places | Backend `AuthorizationMatrixTests.test_submission_creation_requires_active_user_and_assigns_owner` denies guest and inactive GraphQL submissions; `test_approved_place_rest_writes_are_administrator_only` denies unauthenticated REST writes and permits only administrators. |
| Non-moderators cannot read or mutate pending submissions | `test_pending_queries_hide_other_users_rows`, `test_only_moderators_approve_and_self_review_is_denied`, and `test_only_administrator_can_hard_delete_with_durable_audit` cover guest, inactive, user, moderator, and administrator behavior, ownership filtering, self-review denial, and durable audit records. |
| Presigning and image creation are denied or safely owner-bound | `test_upload_entry_points_fail_closed` denies both GraphQL entry points for every M1 role. Upload implementation remains deferred to M3. |
| Browser JavaScript cannot read backend access or refresh credentials | Frontend `config.test.ts` proves that the public NextAuth session contains only safe identity, role, expiry, and terminal-error fields and excludes both backend credentials. Same-origin proxying remains the browser boundary. |
| Login, refresh, logout, revocation, and terminal failure are deterministic | Backend `TokenLifecycleTests` and `ConcurrentRefreshTests` cover five-minute access credentials, seven-day refresh families, hashing, rotation, concurrent refresh, reuse compromise, expiry, verification, bearer authentication, and revocation. Frontend `backend-auth-client.test.ts`, `token-lifecycle.test.ts`, and `config.test.ts` cover one controlled retry, refresh deduplication, credential erasure, terminal failure, and best-effort backend revocation during logout. |
| REST and GraphQL enforce the approved role matrix | Backend authorization-matrix tests exercise GraphQL submission/moderation and REST place writes. Frontend `permissions.test.ts`, `actions.test.ts`, and `columns.test.tsx` cover UI capability mapping and direct server-action invocation; backend checks remain authoritative. |
| Routine logs and CI artifacts contain no authentication secrets | Backend issues `#62` and `#64` removed header and SQL-parameter diagnostics; frontend issues `#12` and `#24` removed browser/session exposure and secret-bearing diagnostics. Pinned, redacted Gitleaks full-history jobs pass in the backend, frontend, and workspace repositories. |
| Automated tests fail when a protected boundary regresses | Backend CI runs the Django system check and all 25 tests against PostGIS. Frontend CI runs type checking, lint, all 33 tests, a Next.js compile-and-serve probe, and secret scanning. Workspace CI verifies the pinned submodules, Compose configuration, and root-history secret scan. |

## Verification run

The 2026-08-21 exit run demonstrated:

- `docker info --format 'Root={{.DockerRootDir}} Driver={{.Driver}}'` reported
  `/data/docker-data` and `overlay2`;
- `docker compose config --quiet` passed;
- `docker compose up --build --detach --wait` rebuilt the merged application
  revisions, and all long-running services reached healthy;
- frontend `/`, backend liveness/readiness, GraphQL `{ __typename }`, and a
  bounded GeoJSON request returned HTTP 200;
- Django reported application `search_path` `smokemap` and PostGIS 3.5;
- `make check` passed with the known lint warnings;
- `make test-backend-fresh` recreated the isolated database and passed 25
  tests;
- `make test` passed 25 backend tests and 33 frontend tests;
- the latest `development` workflow completed successfully at backend
  `83c4be8`, frontend `8ce02be`, and workspace `f9736f0`.

## Deliberately deferred work

The Next.js production build still exposes legacy prerender failures across
unrelated pages, recorded under frontend M5 issue `#17`. M1 added a framework
compile-and-serve gate for the canonical
development runtime, which catches invalid `"use server"` exports and protects
the verified local stack. A clean production build, supported framework
versions, dependency remediation, and deployment gates remain M5 production-
readiness work and do not weaken the demonstrated M1 authorization boundaries.
