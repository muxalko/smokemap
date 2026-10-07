# M4 exit evidence

Status: **Demonstrated**

Recorded: 2026-10-07

Final audit: `302a3f86d1864c0e941133e24b918e23` — verdict
`READY_TO_CLOSE_M4`

This record closes **M4 — Moderation and search** against the ordered work and
exit criteria in [ROADMAP.md](ROADMAP.md). Evidence comes from the exact merged
revisions pinned by this workspace: root
`ac86d7ac48568d2544a7c48aa96928dbc973ed8e`, backend
`d9ddb016fd0fd6cff893f1d70dcb067574bedafc`, and frontend
`d46626891ca8ec780a554b4fadd7b2515a8c7e5a`.

## Ordered-work evidence

| ROADMAP M4 work item | Decision | Merged implementation and verification evidence |
| --- | --- | --- |
| 1. Implement serialized owner withdrawal and moderator approval/rejection, including canonical-name approval locking and duplicate revalidation | **Complete** | Backend `54b91d4` (PR #99) adds explicit row-locked withdrawal, approval, and rejection services inside atomic transactions, including full-canonical-name advisory locking and approval-time duplicate revalidation. Backend `1f83faf` (PR #103) completes atomic moderation safety and legacy map compatibility without reopening legacy write paths. |
| 2. Record backend-owned authenticated actors and immutable lifecycle/audit events | **Complete** | Backend `54b91d4` records the authenticated owner or reviewer in immutable lifecycle events; `1f83faf` adds normalized reviewer comments, replay-safe idempotency, protected audit evidence, and explicit administrator-only audited hard deletion. The client never supplies the authoritative actor. |
| 3. Keep withdrawal, rejection, expiry, and exceptional hard deletion distinct | **Complete** | Backend `54b91d4` implements withdrawal and rejection as distinct terminal lifecycle transitions rather than deletion or expiry. Backend `1f83faf` preserves exceptional hard deletion as a separate administrator-only audited service and protects approved results, image metadata, owner-bound objects, and audit rows from accidental cascade deletion. |
| 4. Prove rollback and the complete moderation race matrix before enabling transitions | **Complete** | Backend `54b91d4` adds forced rollback, idempotency, simultaneous transition, finalize/withdrawal, withdrawal/expiry, approval/rejection, approval/withdrawal, rejection/withdrawal, duplicate-approval, and duplicate-revalidation coverage. Backend `1f83faf` adds deletion and materialization safety. Tests-only backend `f54944a` (PR #108) forces approval and rejection against exact-key media cleanup in both parent-lock orderings and asserts one winner, exact lifecycle/place/cleanup cardinality, and bounded synchronization. |
| 5. Define a bounded search contract with geographic/category context | **Complete** | Backend `29a1c96` (PR #104) adds public `GET /api/v1/places/search/`, searching only approved places with an autocomplete-safe projection containing the point, category, and address context. It validates normalized 2–100-character queries, defaults to 10 results, and hard-caps results at 20. Backend `3870140` (PR #106) deprecates the unbounded GraphQL `places` listing and characterizes the roadmap's explicit distinction between bounded search/autocomplete and approved-only legacy listings. |
| 6. Add indexes, ranking, caps, debounce, cancellation, and stale-response protection | **Complete** | Backend `29a1c96` adds deterministic prefix-before-trigram ranking, B-tree and GIN indexes, SQL limiting, capped legacy autocomplete, and a 20,000-row natural-plan gate with `enable_seqscan=on`. Frontend `699264b` (PR #63) removes the full-list client filter, uses the bounded same-origin endpoint, debounces by 300 ms, aborts superseded requests, rejects late stale responses even when abort is ignored, clamps limits, and provides explicit idle/loading/empty/error/success states. |
| 7. Refresh affected UI state after submission and moderation | **Complete** | Frontend `7cd48b5` (PR #62) builds the permission-aware bounded moderation queue and deterministic post-action first-page refresh. Frontend `5ffae82` (PR #64) makes backend truth authoritative after success or conflict, preserves usable state if refresh fails, and provides deterministic retry. Public map/search reads remain uncached backend reads, while new submissions remain pending and therefore non-public. |

All M4 lifecycle actions also satisfy the M3 contract's public-delivery gate.
Backend `5e17dcb` (PR #110) creates separately keyed, metadata-stripped public
renditions while retaining verified originals privately, publishes opaque media
records atomically with approval, and adds audited revocation and exact-key
cleanup. Backend `d9ddb01` (PR #112) makes public media URLs application-origin
relative and immune to forwarded-host influence. Frontend `d466268` (PR #66)
renders only the ordered approved-rendition contract and handles zero, one,
multiple, revoked, and unavailable media states. Root `e5a2bc2` (PR #101) proves
the complete approval, rejection, withdrawal, public search/map visibility,
anonymous rendition delivery, private-source non-disclosure, and idempotent
cleanup path in a real browser against the pinned applications.

## Exit-criterion decision

| M4 exit criterion | Decision | Evidence |
| --- | --- | --- |
| Partial or concurrent moderation cannot corrupt state | **Demonstrated** | The backend serializes every transition on the submission row, rechecks preconditions inside the transaction, uses canonical-name locking for approval, and tests rollback plus every required transition race. `f54944a` additionally forces approval/rejection against cleanup in both lock orderings with exact terminal-state and side-effect cardinality assertions. |
| Every withdrawal, approval, and rejection action is authorized, auditable, and distinct from exceptional M1 audited hard deletion | **Demonstrated** | `54b91d4` enforces owner-only withdrawal and moderator/administrator approval or rejection while recording authenticated immutable lifecycle events. `1f83faf` keeps hard deletion administrator-only, separately audited, idempotent, and protective of published and retained evidence. `7cd48b5` supplies matching fail-closed frontend role checks without replacing backend authorization. |
| Search and autocomplete never retrieve the full place-name collection, as scoped in the roadmap | **Demonstrated** | `29a1c96` caps the REST search and legacy autocomplete surfaces in SQL and returns only approved places. `699264b` removes the frontend's full-list GraphQL download. `3870140` deprecates and characterizes the separate approved-only legacy listing so it is not misrepresented as an autocomplete surface. |
| Results are capped, relevant, and protected from response reordering | **Demonstrated** | `29a1c96` validates and caps results at 20, ranks prefix before trigram similarity with deterministic ties, and proves natural index use on 20,000 rows. `699264b` clamps the requested limit, debounces input, cancels superseded work, keys results to the normalized query, and rejects late responses. |

All ordered work and every exit criterion are demonstrated at the exact merged
and pinned revisions. M4 is therefore **Done**.

## Cross-application approval and public-media path

The root `make test-e2e-public-media` target runs a deterministic two-phase
real-browser path rather than a mock:

```text
Pinned Puppeteer Chromium
  -> real NextAuth sign-in and product submission form
  -> real presigned uploads to private MinIO storage
  -> backend checkpoint proving pending media is anonymous-private
  -> real moderation UI approval plus supported rejection/withdrawal actions
  -> public map and bounded-search discovery of only the approved place
  -> anonymous application-relative sanitized-rendition delivery
  -> backend/storage non-disclosure, lifecycle, and cleanup verification
```

The browser creates three distinct valid-image submissions. Approval is
performed through the real moderation UI; rejection and withdrawal use their
supported authenticated lifecycle interfaces. The verifier compares public
API, DOM, and captured network evidence against private database and storage
identifiers, proves rejected and withdrawn submissions never become public,
and cleans its owned places, submissions, immutable fixtures, and objects
idempotently. The isolated Compose project has no published host ports and
blocks external browser traffic.

## Final combined verification record

At root `ac86d7a`, backend `d9ddb01`, and frontend `d466268`:

- all eight backend M4 milestone issues and all five frontend M4 milestone
  issues are closed, with zero open issues in either application M4 milestone;
- the backend required `test` and `secrets` checks passed at every merged M4
  implementation head and at the pinned backend head;
- the frontend required `test` and `secrets` checks passed at every merged M4
  implementation head and at the pinned frontend head;
- root required checks `integration`, `viewport-pan`, `submission-media`,
  `public-after-approval`, and `secrets` all passed at the exact pinned root;
- `public-after-approval` exercises approval, rejection, withdrawal, pending
  privacy, public search/map visibility, safe rendition delivery,
  non-disclosure, and cleanup against the exact final application pair;
- live `development` protection requires those five root checks strictly and
  preserves administrator enforcement, pull-request-only changes, linear
  history, review-conversation resolution, zero mandatory human approvals,
  and force-push and branch-deletion bans;
- a fresh root `make check-compose` passed, and a redacted Gitleaks
  full-history scan of the pinned root reported no leaks.

The 2026-10-07 final exit audit
`302a3f86d1864c0e941133e24b918e23` returned `READY_TO_CLOSE_M4`. Fresh root,
GitHub, milestone, branch-protection, required-check, roadmap, and gitlink
readback on 2026-10-07 found no invalidating change.

## M5 gate

M5 is now **Current**. This status opens production-readiness work; it does not
assert that Smokemap is production-ready. Dependency support, deployment and
promotion controls, observability, recovery, production configuration,
security hardening, migration rehearsal, and release evidence remain M5 work.
