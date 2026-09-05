# M3 exit evidence

Status: **Demonstrated**

Recorded: 2026-09-04

Final audit: `586885c1c8844109b041d94d0befdc8b` — verdict `READY_TO_CLOSE_M3`

This record closes **M3 — Submission and media vertical slice** against the
[M3 submission and media contract](M3_SUBMISSION_MEDIA_POLICY.md) and the exit
criteria in [ROADMAP.md](ROADMAP.md). Evidence comes from the exact revisions
pinned by this workspace: root `c2e5224264a0df4a5a5ae02872c7b9ac9f6f4b28`,
backend `4fe254aa94eb90f67dbfbf3b0f93b3e5bbccf058`, and frontend
`586e56d3e1f5f2e5c44a77050da3564f6337b5bf`.

## Ordered-work evidence

| ROADMAP M3 work item | Decision | Merged implementation and verification evidence |
| --- | --- | --- |
| 1. Introduce M3-reachable `draft`/`pending`/`expired` states; reserve `withdrawn`/`approved`/`rejected`; add constraints and immutable lifecycle events | **Complete** | Backend `11e105f` ("Create atomic M3 submission drafts") evolves `Request` into the single M3 submission aggregate with explicit lifecycle state, migrations, and immutable lifecycle events; the complete fresh backend suite passed 92/92 with an independent Claude review approval. |
| 2. Carry the M1 authenticated owner relation through every state; guest submission stays disabled | **Complete** | `11e105f` keeps `createSubmissionV3` owner-bound from the authenticated request and preserves the M1 guest-denial boundary; owner binding is re-enforced under lock in every later transition (`4d15a80` finalize, `9851806` expiry, `fa4aed0` media remove/reorder). |
| 3. Separate proposed content from approved places | **Complete** | `11e105f` models the submission as a durable proposal distinct from `Place`; approval-time materialization is explicitly out of scope and remains M4-reserved per the contract. |
| 4. Move geocoding out of model `save()` into an explicit service or job | **Complete** | `11e105f` removes `Address.save()` geocoding and the legacy global address/place-name uniqueness constraint. |
| 5. Validate coordinates, category slugs, tags, websites, descriptions, and privacy-scoped duplicates; perform no DNS/network/fetch during website validation; remove global place-name uniqueness | **Complete** | `11e105f` adds normalized-field, coordinate, category-slug, tag, and deterministic syntactic-only HTTPS website validation with dedicated test coverage; `4d15a80` layers the privacy-scoped `ST_DWithin(..., 25.0)` duplicate check that revalidates the complete stored proposal under lock at finalization. |
| 6. Serialize lifecycle transitions with row locking, retry-safe writes, lifecycle history, and a transaction-scoped lock keyed by the full canonical name before duplicate checks | **Complete** | `4d15a80` ("Implement M3 draft editing and finalization") adds owner-only `editSubmissionV3`/`finalizeSubmissionV3`, serializes duplicate checks with a transaction-scoped advisory lock derived from the full canonical name independent of whether a matching row exists, and applies ownership inside the row-lock predicate so a foreign submission ID neither discloses nor blocks on another owner's row; the complete backend suite passed 195/195 (1 intentional skip) with an independent Codex review approval. |
| 7. Add upload intents with exact storage object identifier, owner, submission, MIME, size, server-verified SHA-256, state, and transactionally locked three-slot accounting | **Complete** | `9915360` ("Harden owner-bound media uploads") introduces owner-bound private media upload intents with three-slot locking and server-side byte verification; a real MinIO overwrite-after-verify attack was exercised and defeated (mutable upload key overwritten, sealed attachment unchanged); 43/43 focused media tests and 135/135 full backend tests passed. |
| 8. Issue one constrained presigned request per file | **Complete** | `9915360` issues exact presigned POST policies constrained to the exact key, one content type, and a bounded content-length range; `261f5ab` ("Split private media storage endpoints") separates the browser-facing presign endpoint configuration from private server I/O, with 138/138 full backend tests passing. |
| 9. Await, verify, attach, and clean up each upload independently, with deterministic failure handoff and the unified 24-hour `cleanup_pending` SLA | **Complete** | `9915360` adds durable autonomous expiry/cleanup with retry leases and exact-key deletion; `9851806` ("Expire inactive M3 drafts") hands off draft expiry to the same `cleanup_pending` path under the 24-hour SLA with parent-first locking (212/212 full suite); `fa4aed0` adds idempotent draft-media removal with exact-object `cleanup_pending` handoff and atomic reorder (248/248 full suite); `4fe254a` ("Add authorized private media previews") adds short-lived, exact-object private preview authorization for owners and moderators (269/269 full suite, independent HCP review approval). |
| 10. Rebuild the frontend form around deterministic zero-or-more image behavior | **Complete** | Frontend `80167b0` implements the authenticated zero-image `createSubmissionV3` → `finalizeSubmissionV3` path; `fd031ae` adds live-session 0–3 media uploads with issue/renew/verify/attach and partial-failure handling (19 suites / 120 tests); `1148123` ("Resume and manage M3 draft media") restores draft/pending state from backend truth after refresh, exposes authorized private attachment previews, and supports idempotent remove/reorder/retry (20 suites / 194 tests); backend `b95c39a` exposes each attachment's real `mediaIntentId` in `submissionMediaStateV3` so resume/reorder/remove target the intended attachment. |
| 11. Keep every legacy submission/media write fail-closed; keep both withdrawal transitions plus approval/rejection disabled for all roles until M4 | **Complete** | `11e105f` and `4d15a80` keep legacy submission/moderation/media/import/admin write paths fail-closed while preserving audited administrator hard deletion; `4d15a80`'s migration explicitly leaves no M4 transition reachable. Root `AGENTS.md` and CI (below) enforce the same boundary at the workspace level. |

## Exit-criterion decision

| M3 exit criterion | Decision | Evidence |
| --- | --- | --- |
| Only create → `draft`, owner draft edit/media, `draft` → `pending`, and system `draft` → `expired` succeed; both withdrawal transitions, approval, and rejection remain fail-closed for every role | **Demonstrated** | Backend transition tests in `11e105f`, `4d15a80`, and `9851806` cover every M3-enabled and denied transition per role; the M3 policy (section 11) and `AGENTS.md` record `withdrawn`/`approved`/`rejected` as reachable-but-disabled throughout M3. |
| Every M3 lifecycle and media/cleanup race has one deterministic winner and no extra state, event, attachment, slot, or cleanup target | **Demonstrated** | `11e105f` covers concurrent create idempotency; `4d15a80` and `9851806` force finalize/expire races under `select_for_update()`; `9915360` and `fa4aed0` force intent/attachment/remove/reorder/finalize/expiry races at the three-slot boundary; each commit's verification records a passing complete backend suite (92 → 269 tests across the sequence) with no extra state written. |
| Validation failures leave no partial rows | **Demonstrated** | `11e105f`'s atomic `createSubmissionV3` and `4d15a80`'s atomic `editSubmissionV3`/`finalizeSubmissionV3` validate before mutation inside `transaction.atomic()`; their test suites include rollback coverage. |
| Duplicate checks use the exact 25-metre geography predicate without leaking another owner's private proposal or imposing global name uniqueness | **Demonstrated** | `4d15a80` applies `ST_DWithin(..., 25.0)` against public places plus only the owner's own draft/pending rows, with ownership enforced in the row-lock SQL predicate so a foreign submission ID neither discloses nor blocks on another owner's proposal; `11e105f` removes the legacy global place-name uniqueness constraint. |
| Zero, one, and multiple uploads handle retry and partial failure correctly | **Demonstrated** | Frontend `fd031ae` and `1148123` add deterministic zero/one/three-image, retry, partial-failure, renewal, and duplicate-submit coverage; the root E2E (below) exercises a real zero-image and a real two-image submission end to end. |
| Concurrent intent and attachment operations cannot allocate a fourth slot, and stored SHA-256 values are computed from object bytes by the backend | **Demonstrated** | `9915360` locks intent creation/verification/attachment at the three-slot boundary and computes SHA-256 by streaming bytes back from the managed object store during verification, never trusting a browser-supplied digest; `fa4aed0` extends the same locking to remove/reorder. |
| A client cannot attach another submission's object | **Demonstrated** | `9915360`'s attachment path requires a verified intent owned by the same user and bound to the same draft; the root E2E independently confirms each attached image's sealed object exists only at its own recorded key. |
| Abandoned objects and intents have a tested exact-key cleanup path whose deletion attempt begins within 24 hours of `cleanup_pending` | **Demonstrated** | `9915360` adds durable autonomous expiry/cleanup with retry leases and exact-key deletion; `9851806` and `fa4aed0` hand off draft-expiry and removed-media objects to the same `cleanup_pending` path under the unified 24-hour SLA. |

All ordered work and every exit criterion are demonstrated at the exact merged
and pinned revisions. M3 is therefore **Done**.

## Cross-application submission and media path

The root `make test-e2e-submission-media` target (added at `2168e04`, wired
into CI as the `submission-media` job) exercises the real path rather than a
mock:

```text
Pinned Puppeteer Chromium
  → real NextAuth credentials sign-in UI
  → frontend M3 submission form
  → GraphQL createSubmissionV3 / editSubmissionV3 / finalizeSubmissionV3
  → owner-bound media intents (issue → direct MinIO POST → verify → attach)
  → on-page status banner confirming a finalized `pending` submission
  → backend/storage truth check (owner, state, attachment count, distinct
    SHA-256 digests, no non-terminal intents, sealed private object at its
    exact key, anonymous-access denial, cleaned-up unsealed upload object)
```

It runs two submissions against the pinned applications and real MinIO: one
with zero images and one with two real local image files, hashed in-browser
and uploaded through a real presigned POST issued by the backend. The isolated
`smokemap-e2e-submission-media` Compose project has no published host ports;
uploads are signed against the internal `storage:9000` service address rather
than a host-published port. The target seeds no fixtures ahead of time —
same-named submissions, media, and MinIO objects from a prior run are removed
before and after every run — and fails closed at any step (sign-in, upload,
verification, finalization, or the backend/storage checks); nothing downstream
is skipped or treated as a soft warning. `586e56d` ("Reset submission category
after success") was itself a fix for a repeated-submission category leak that
this real E2E exposed, and added sequential zero-image and media-attached
regression coverage confirming the fix.

## Final combined verification record

At the exact merged and pinned root `c2e5224`, backend `4fe254a`, and frontend
`586e56d`:

- backend: full suite 269/269 tests passed (`4fe254a`), `manage.py check`
  passed, `makemigrations --check --dry-run` reported no drift, `compileall`
  passed, `git diff --check` passed, and independent HCP review returned
  APPROVE with no defects;
- frontend: `yarn test:ci` 21 suites / 196 tests passed (`586e56d`), with
  `yarn typecheck`, `yarn lint` (only pre-existing unrelated `PlaceList.tsx`
  warnings), `yarn build`, and `git diff --check` all passing, and independent
  HCP review completed;
- workspace: `make check-compose` (root `scripts/validate-compose.sh`, added
  at `3cdc435` when the private M3 media stack was wired) validates the
  private-media bucket anonymous-private policy, the legacy bucket's
  anonymous-download policy, exact backend/cleanup environment wiring, and the
  `media-cleanup` Compose service topology;
- workspace CI (`.github/workflows/test.yml`) runs four required jobs on every
  pull request into `development`: `integration` (`make check-compose`),
  `viewport-pan` (the M2 real-browser pan), `submission-media` (the M3 E2E
  above), and `secrets` (redacted Gitleaks full-history scan); `AGENTS.md`
  lists all four as required workspace checks alongside backend and frontend
  `test`/`secrets`.

The M2 viewport-pan CI job and its M2 exit evidence are unaffected by M3 work
and continue to pass at this baseline; this record does not re-verify M2.

Each intermediate backend and frontend baseline in the sequence above was
independently pinned into the root workspace by its own PR (root `#59`–`#80`)
and re-verified by the workspace `integration` and E2E CI jobs at that pin, so
the final combined record reflects the cumulative, continuously-verified
history rather than a single unverified last step.

The 2026-09-04 final exit audit (`586885c1c8844109b041d94d0befdc8b`) reviewed
the merged evidence above against every ROADMAP M3 ordered-work item and exit
criterion and returned `READY_TO_CLOSE_M3`.

## M4 gate

M4's owner-withdrawal, moderator-approval, and moderator-rejection
transitions remain disabled. The M3 submission and media contract already
models `draft` → `withdrawn`, `pending` → `withdrawn`, `pending` →
`approved`, and `pending` → `rejected`, but every M3-pinned entry point
continues to return a stable fail-closed response for those four transitions
and their legacy equivalents, for every role. M4 must implement owner
withdrawal, moderator approval, and moderator rejection as explicit,
lock-serialized services with the complete race, rollback, authorization,
audit, privacy-scoped duplicate, cleanup, and public-delivery test gate
required by
[M3_SUBMISSION_MEDIA_POLICY.md](M3_SUBMISSION_MEDIA_POLICY.md) sections 2 and
10 before enabling any of those transitions. This record does not enable, and
does not evaluate readiness to enable, any M4 transition.
