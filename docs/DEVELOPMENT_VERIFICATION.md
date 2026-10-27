# Per-task DEVELOPMENT verification

Client decision date: 2026-10-26. Root integration:
[#126](https://github.com/muxalko/smokemap/issues/126).

M5 proceeds one task at a time: implement → exact-head checks and independent
review → merge and root integration review → deploy the reviewed release to
DEVELOPMENT → verify feature/authentication behavior and regressions → record
the result → advance to the next task only after the gate passes. This gate
adds operational evidence to the existing [M5 roadmap](ROADMAP.md); it neither
completes M5 nor replaces any production-readiness requirement.

This prepared standalone control/source clone is not the live DEVELOPMENT
checkout. This change only records source integration and the verification
procedure. It does not deploy, migrate, restart, delete, or change existing
runtime resources or data. The primary operator owns the later DEVELOPMENT
deployment and records its outcome separately.

## Evidence boundaries

| Phase | Required evidence | What it establishes |
| --- | --- | --- |
| Isolated pre-merge preview | Exact candidate SHA, image provenance, isolated project/resources, feature checks and applicable CI/E2E results | Candidate behavior before merge; no deployed-DEVELOPMENT claim |
| Post-deployment DEVELOPMENT gate | Reviewed merged root and application SHAs, selected/running image identities, recovery point, readiness, real feature/auth checks, regressions and rollback outcome if needed | Only the identified DEVELOPMENT release and tested workflows |
| Later staging/production promotion | Separate target-tree issue/branch/PR, required checks and independent review, controlled migrations, promotion/rollback/backup/recovery rehearsal evidence | Only the explicitly promoted environment and release |

An isolated preview must use its own source checkout, project, ports, network,
database/media and dependency/cache volumes. Never point preview or E2E
fixtures at live DEVELOPMENT data. A green CI run, a preview URL, a healthy
container, or a merged pointer alone does not pass the DEVELOPMENT gate.

## Release and data safety

Serve DEVELOPMENT from a frozen per-release checkout pinned to the reviewed
merged root SHA and both exact submodule SHAs. Prepare the next release in a
separate checkout; never edit, switch branches, check out revisions, run
`make sync`, or install dependencies beneath running development services
before review. Preserve unrelated dirty source as it stands; do not reset,
stash, clean, or repurpose it for deployment.

Each release must use separate versioned dependency and build/cache volumes
(including frontend `node_modules` and `.next`). Record their exact names and
image/lockfile association. Never share writable dependency/cache volumes
between a candidate, the active release, and the rollback release. Keep the
prior release checkout, images and volumes available for rollback. Existing
Compose defaults do not by themselves enforce this release discipline; the
operator must verify the resolved bind mounts, project, ports and volume
mapping before starting a release. Do not hot-update the current checkout.

Preserve useful PostgreSQL and MinIO data and all unrelated runtime resources.
Take a consistent paired database/media recovery point before deployment,
record its identity and restore procedure, and retain the prior release.
Coordinate writes and cleanup while obtaining that point so the database and
objects agree. Do not equate isolated test fixtures with a recovery backup.
Never delete volumes, prune caches/images, reset databases, or overwrite data
as routine verification. Any destructive recovery requires separate explicit
authorization for the exact target and recovery point.

Do not expose tokens, sessions, authorization headers, presigned fields/URLs,
passwords or secret-bearing environment objects in evidence. Do not install
host application dependencies, use production secrets, contact production
storage, or run production migrations for this development gate. Anonymous
submission remains disabled; this procedure changes no authorization or
public/private bucket policy.

## Operator sequence for each task

1. Finish the task and its tests in the owning repository. Capture the actual
   immutable PR head, all applicable CI/security results, independent review
   and resolved conversations before merge. Application repositories deploy
   independently. Integrate only published merged application commits through
   a separately reviewed root PR; record the root and both application SHAs.
2. Prepare a frozen release checkout and versioned dependency/cache volumes
   without altering the active release. Record source SHAs, image IDs/digests
   and revision labels, build inputs/lockfile identity, non-secret configuration
   identity, release ID, environment/project, mounts, volumes and endpoints.
   Check the running release's identity rather than inferring it from a
   mutable image tag or the control clone's HEAD.
3. Record the prior release and consistent database/media recovery point.
   Verify that the prior images, checkout, volumes and recovery instructions
   are usable. Identify exactly which services need replacing and any schema
   compatibility constraints. A schema change needs its own reviewed migration
   plan; this frontend logout integration needs no backend migration.
4. Deploy only the affected services after review and merge. For logout this
   is the frontend; preserve the backend, database, storage, cleanup service
   and their data. Avoid a blanket `make dev-detached`: it builds/starts the
   stack, and backend startup runs migrations. Verify the resolved deployment
   plan does not recreate dependencies or reuse the active dependency/cache
   volumes. Record actual selected and running image identities and mounts.
5. Wait for affected-service health and verify the real DEVELOPMENT endpoints:
   frontend `/`, backend `/health/live/` and `/health/ready/`, GraphQL
   `{ __typename }`, and bounded viewport retrieval. Confirm unchanged
   dependencies remain healthy. Readiness is a prerequisite for product tests.
6. Run the task's real browser feature and authentication checks against the
   deployed DEVELOPMENT origin, including relevant roles, error/retry states
   and responsive layouts. For logout: sign in, find the accessible account
   control on desktop/mobile, sign out, return to signed-out home, verify
   protected views/actions require authentication, and verify a new sign-in.
   Check terminal expiry, duplicate logout prevention and safe failure/retry
   with the appropriate automated or controlled test evidence. Do not put
   tokens or session material in the record.
7. Run `make check` and `make test` against the explicitly selected DEVELOPMENT
   project/release. The Makefile uses plain `docker compose exec`, so verify
   its project/configuration targets the intended containers before running.
   `make check` includes Compose validation, Django system checks and frontend
   checks; `make test` runs backend tests with the isolated `public` test-schema
   override and frontend `yarn test:ci`. Use the canonical targets rather than
   a raw backend test command. Record container/source identity and results.
8. Run applicable cross-application regressions from the frozen source in
   dedicated isolated E2E projects: `make test-e2e` (viewport pan),
   `make test-e2e-submission-media` (authenticated zero/multiple-image
   submission), and `make test-e2e-public-media` (public-after-approval lifecycle).
   These targets start/build services, create and clean fixtures, and tear down
   their test containers; inspect resource mappings first and preserve useful
   data. They do not run against the deployed DEVELOPMENT origin and cannot
   replace step 6. Record them as separate regression evidence, with the same
   source baseline and their actual image identities. Logout additionally
   requires the focused frontend authentication/session tests.
9. Record pass/fail, exact revisions/images, checks and timestamps, redacted
   evidence locations, prior release/recovery point, and remaining limitations.
   On any failed gate stop advancement, restore the previous affected-service
   release with its original dependency/cache volumes, and repeat readiness
   and regression checks. If data recovery is necessary, stop writes and
   follow the separately authorized paired recovery procedure; do not assume
   application rollback reverses migrations or data changes. Record rollback
   evidence and keep the task gate failed until corrected and reverified.

## Initial logout source integration

Feature [frontend #71](https://github.com/muxalko/smokemap-webapp/issues/71)
was merged through [PR #72](https://github.com/muxalko/smokemap-webapp/pull/72).
The published frontend commit pinned here is
`a07af381b870e16229c36cee491a6cb8c0859d38`; the backend pin remains
`05098a798961e6e1b968d78f3211a17df63d036f`.

Upstream source evidence: Reviewed PR: #72 (frontend); Reviewed head:
`1eda407a62f576bbcdb286b106236c333708b389`.
[CI run 40462513012](https://github.com/muxalko/smokemap-webapp/actions/runs/40462513012)
passed. The supplied independent HCP review
`5a8e078096074fb09cdaa14d8dd39cf7` reported APPROVE, HIGH=0, MEDIUM=0 for that
source head. This is upstream review evidence, not independent approval of
root #126 or proof of DEVELOPMENT deployment. The published squash commit
and reviewed PR head are different identities and must both remain explicit.
The primary operator must still record the post-deployment gate above.

## Later promotion

Keep public and private staging resources and contracts independent of
DEVELOPMENT. Follow the existing [local staging](../deploy/staging/local/README.md),
[external staging](../deploy/staging/README.md) and explicit temporary
[Quick Tunnel rehearsal](../deploy/staging/quick/README.md) procedures when
separately authorized. Preserve existing staging homes, secrets, origins,
containers, networks and data; this gate does not launch or replace them.

Promotion remains deliberate `development → staging → main` work, with a
branch based on the target deployment tree and a reviewed PR. Do not assume
a direct merge across the frontend's independent histories. A passed
DEVELOPMENT gate authorizes neither production changes nor an M5 completion
claim; all existing migration, observability, supported-version, staging,
rollback, backup and recovery requirements remain in force.
