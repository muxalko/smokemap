# M3 submission and media contract

Status: Adopted when this document is merged into `development`

Decision date: 2026-08-30

Tracking issue: root `#59`

## 1. Scope and authority

This contract resolves the product, lifecycle, validation, upload, visibility,
retry, and cleanup decisions required to begin **M3 — Submission and media
vertical slice**. It applies to every submission and media entry point,
regardless of whether that entry point is REST, GraphQL, or a frontend server
action.

The [M1 security and authorization contract](M1_SECURITY_POLICY.md) remains in
force and takes precedence. In particular:

- only active authenticated users may create submissions or upload media;
- the Django backend assigns and enforces the owner from the authenticated
  request; guests, inactive accounts, IP addresses, forwarded addresses,
  cookies, browser IDs, and client-supplied actor fields never establish
  ownership;
- normal users see only their own submissions, while moderators and
  administrators receive the M1 review visibility;
- moderators cannot approve their own submissions, and ordinary moderation
  never gains an administrator bypass;
- frontend checks are fail-closed UX only; the backend remains the
  authorization boundary;
- credentials, presigned fields, object keys that grant capability, and
  secret-bearing request data are never logged or exposed through the browser
  session; and
- exceptional hard deletion remains administrator-only and must write durable
  audit evidence before deleting its target.

The legacy public-URL image model, general presign query, and arbitrary image
creation mutation are not approved M3 interfaces. They remain disabled until
the complete owner-bound path defined here is implemented and tested. M3 does
not change repository or deployment ownership: application work stays in the
independently deployed backend and frontend repositories.

## 2. Submission aggregate and states

A submission is a durable proposal, not an approved `Place`. It owns a
snapshot of the proposed name, point, address label, category, tags,
description, website, owner, ordered media attachments, timestamps, and
lifecycle events. Creating or editing a proposal must not create or mutate an
authoritative `Place`, `Address`, `Location`, public tag relation, or public
media record. Approval later materializes the accepted snapshot through the
moderation transaction.

The complete state set is:

| State | Meaning | Mutable content |
| --- | --- | --- |
| `draft` | Owner is preparing validated content and zero or more media attachments; it is not in the review queue. | In M3, the owner may edit proposed fields, add/remove/reorder media, or finalize. Withdrawal is reserved for M4. |
| `pending` | Owner finalized one immutable review snapshot. | No content edits or new media. Withdrawal, approval, and rejection are reserved for M4. |
| `withdrawn` | In M4, the owner deliberately ended a draft or pending proposal. | Terminal; it may be cloned into a new draft but never reopened in place. Distinctly modeled but unreachable throughout M3. |
| `expired` | The system ended a draft after 30 days without owner or media activity. | Terminal; it may be cloned into a new draft but never reopened in place. |
| `approved` | In M4, a moderator accepted the exact pending snapshot and linked it to the resulting public place. | Terminal; later place maintenance does not rewrite submission history. |
| `rejected` | In M4, a moderator rejected the exact pending snapshot with a non-empty reason. | Terminal; it may be cloned into a new draft but never reopened in place. |

Only these transitions are valid:

```text
M3-enabled:
create -> draft
draft  -> pending     owner finalizes
draft  -> expired     30-day inactivity cleanup runs as the system actor

M4-reserved; disabled throughout M3:
draft   -> withdrawn  owner withdraws
pending -> withdrawn  owner withdraws before moderation commits
pending -> approved   moderator other than owner approves
pending -> rejected   moderator other than owner rejects with a reason
```

Every M3-enabled lifecycle transition after creation—finalization and system
expiry—runs in its own `transaction.atomic()` service. The M4-reserved owner
withdrawal, approval, and rejection transitions must use the same boundary
when M4 enables them; throughout M3 every such attempt fails closed before any
state or event write. The service locks the submission row with
`select_for_update()` before it rechecks current state, current backend account
authorization, and all transition preconditions. The state change and its
immutable event commit together. The event contains the backend-owned actor
(or named system actor), action, source state, destination state, target,
timestamp, and outcome. Creation atomically writes the initial `draft` and its
creation event because there is no prior row to lock.

Competing transitions on one submission serialize on that row. The first
committed valid transition wins; every stale contender rechecks the new state
under the lock and returns a stable invalid-transition or prior-idempotent
result without writing another state or event. Moderators do not edit proposed
content. Withdrawal, rejection, and expiry are distinct lifecycle actions;
withdrawal and rejection remain M4 operations. Exceptional M1 audited hard
deletion is not any of those actions. An administrator self-review override
remains outside the ordinary path and is not enabled by M3 or M4.

M3 accepts new-place proposals only. A submission cannot target or amend an
existing place. A future correction workflow requires its own contract and
must retain the original submission and place history.

## 3. Retention and deletion

- `pending` submissions do not expire automatically.
- `approved`, `rejected`, `withdrawn`, and `expired` submission records and
  their lifecycle events are not routinely hard-deleted. They remain durable
  until the M5 operational/privacy policy adopts a broader retention or
  account erasure schedule.
- A `draft` with no owner or media activity for 30 days is transitioned to
  `expired` by an idempotent cleanup job. The transition is audited; the row
  is not silently deleted.
- Exceptional administrator hard deletion follows M1: durable evidence is
  written before deletion, and related media is first made non-public and
  transitioned to `cleanup_pending` for exact-key cleanup.
- Removing media from a draft or expiring a draft in M3 makes the media
  unavailable and transitions each affected object to `cleanup_pending` in
  the same database transaction. M4 withdrawal and rejection do the same once
  enabled. The cleanup job must attempt exact-key deletion within 24 hours
  after that transition commits, while a non-secret metadata tombstone and
  lifecycle evidence remain.
- Media belonging to an approved place remains available with that place.
  Exceptional removal makes it unavailable and enters `cleanup_pending` in
  the same transaction; the same 24-hour deletion-attempt SLA applies without
  erasing the submission or audit history.

These are product-domain retention rules. They do not alter M1's deferral of
security-log retention and account data-export/deletion periods to M5.

## 4. Canonical field validation

The backend applies the same rules on create, every draft edit, finalization,
and, once enabled in M4, approval. Frontend validation mirrors them for
feedback but is never authoritative. User-authored human-readable strings are
Unicode NFKC-normalized, trimmed, and have internal runs of whitespace
collapsed before length and duplicate checks. User text is treated as plain
text, not trusted HTML. Stable category slugs are identifiers and use the
exact-match rules below rather than human-text normalization.

### Name and location

- `name` is required and contains 2 through 100 Unicode characters after
  normalization.
- Every submission has exactly one explicit WGS84/SRID 4326 point. Longitude
  and latitude are separate finite numeric values; longitude is in
  `[-180, 180]` and latitude is in `[-90, 90]`. A coordinate pair embedded in
  an address string is not an API representation.
- The proposed point is authoritative. `address` is an optional human-readable
  label of 1 through 255 characters when present; empty input becomes `null`.
  Address labels are not unique, and multiple places may share a building or
  label.
- Address lookup or geocoding is an explicit service or job outside model
  `save()`. The user must confirm the resulting point before submission
  creation. A geocoder failure creates no submission or address row, and a
  later geocoder response cannot silently replace a user-confirmed point.

### Category, tags, description, and website

- `category_slug` is required. The API accepts only an exact, case-sensitive
  match to a backend-issued stable slug; it does not trim, case-fold, derive a
  slug from a display label, or accept a numeric database ID. The initial
  mappings are exactly `indoors` → “Indoors”, `outdoors` → “Outdoors”,
  `rooftop` → “Rooftop”, `underground` → “Underground”, `on-the-water` → “On
  the water”, `underwater` → “Underwater”, `in-the-air` → “In the air”, and
  `other` → “Other”. Slugs are unique and immutable once issued; display names
  and descriptions may change without changing the slug. A later migration
  may add a category but must not repurpose a published slug. A submission
  cannot create a category, use a sentinel such as `-1`, or retain a missing
  category, and category rows remain protected while referenced.
- Tags are optional. A submission contains at most 10 distinct tags. Each tag
  contains 3 through 50 characters after normalization. Tags are compared by
  Unicode case-folded canonical value, duplicate canonical values are
  rejected, and their owner-selected display order is retained. Empty tags,
  null elements, and category creation through a tag are rejected.
- `description` is optional plain text with a maximum of 255 characters after
  normalization; empty input becomes `null`.
- `website` is optional and has a maximum normalized length of 255 characters.
  Empty input becomes `null`. Validation is deterministic and syntactic only:
  the value must parse as an absolute `https` URL, and its hostname must either
  already be ASCII or convert deterministically under the implementation's
  pinned IDNA rules to a valid ASCII/Punycode, multi-label DNS name. The
  backend rejects every IPv4 or IPv6 address representation, `localhost`, all
  other single-label hosts, and every exact name or suffix in a versioned,
  code-owned reserved/special-use hostname list applied to the canonical ASCII
  hostname. It also rejects embedded username or password, a non-default
  port, a fragment, control characters, malformed percent escapes, another
  scheme, and a relative URL. Paths and query strings are allowed. Validation
  performs absolutely no DNS lookup, network connection, HTTP request, or
  other fetch.

Consent UI is not an ownership field and cannot substitute for authentication.
Persisting acceptance of versioned legal terms requires an approved terms
version and is outside this contract.

### Duplicate policy

Different places may share the same display name. The implementation must
remove the legacy global `Place.name` uniqueness rule and must not replace it
with a global uniqueness constraint on either display name or canonical name.
A duplicate requires both an equal Unicode NFKC-normalized, whitespace-
collapsed, case-folded canonical name and this PostGIS predicate on SRID 4326
points:

```sql
ST_DWithin(candidate.point::geography, existing.point::geography, 25.0)
```

The 25 metres are inclusive. Category, website, and address spelling do not
bypass the rule. The same canonical name farther than 25 metres away and a
different canonical name at the same point are allowed.

Owner-facing checks are privacy-scoped. Finalization checks public approved
places and the authenticated owner's other `draft` or `pending` submissions;
it never queries or signals the existence of another owner's private
submission. `withdrawn`, `expired`, and `rejected` submissions do not block a
proposal. M4 approval repeats the check against approved places while holding
the submission lock. Another owner's pending proposal does not itself block
finalization or disclose a conflict; once one proposal is approved, a later
nearby matching approval receives the ordinary non-sensitive duplicate error.

Finalization and M4 approval also acquire a transaction-scoped database lock
keyed by the full canonical name before running the spatial query—for example,
a PostgreSQL transaction-level advisory lock derived from that complete
canonical value. Lock acquisition is independent of whether any row with that
canonical name already exists; an absent matching row cannot bypass
serialization. The lock is a serialization mechanism, not a uniqueness
constraint: after acquiring it, the service still evaluates `ST_DWithin` and
permits far-apart matches. A duplicate returns a stable conflict without
partial writes. An idempotent retry of the same operation returns that
operation's prior result rather than being treated as a duplicate.

## 5. Media policy and limits

Images are optional. A finalized submission may contain zero, one, two, or
three ordered images. Zero images is a complete successful path and does not
create an upload intent, wait for storage, or display a placeholder as if it
were submitted media.

Each source image must satisfy all of the following:

- non-empty and no larger than exactly 5,000,000 bytes;
- MIME type `image/jpeg`, `image/png`, or `image/webp`;
- content signature and successful safe image decoding agree with the claimed
  MIME type; file extension and browser-supplied metadata are not evidence;
- width and height are each at most 10,000 pixels and decoded area is at most
  25,000,000 pixels; and
- its server-verified object-byte SHA-256 digest is distinct from every other
  attachment on the submission.

The backend stores the verified byte size, detected MIME type, dimensions,
lowercase hexadecimal SHA-256 digest, owner, submission, exact object key,
ordering position, and media state. The backend computes that digest by
streaming the bytes back from the managed object store during verification;
it does not trust a browser digest, object metadata, ETag, presigned-form
field, or checksum header as proof of the stored bytes. Type detection and
safe decoding examine those same object bytes. A client-supplied URL, bucket,
object key, owner, submission owner, verification flag, or public status is
rejected or ignored. Original file names are non-authoritative, are not used
in keys, and are not exposed publicly.

## 6. Upload intent and attachment protocol

An active authenticated owner may request an intent only for their own
`draft`. Attached media and slot-reserving intents in `created`, `issued`, or
`verified` together cannot exceed three. `failed`, `expired`,
`cleanup_pending`, and `deleted` intents do not reserve a slot. Each file uses
a separate intent and a cryptographically unguessable exact object key under
the managed submission-media namespace.

An intent records owner, submission, expected MIME type, exact byte size, a
required separately labelled client-declared SHA-256 expectation, the server-
verified SHA-256 once available, exact storage object identifier,
creation/expiry timestamps, attempt information, stable failure outcome, and
state. The declaration must be exactly 64 lowercase hexadecimal characters,
but is only an expectation, not verification evidence. Its lifecycle is:

```text
created -> issued -> verified -> attached
created/issued -> expired
created/issued -> failed
created/issued/failed/expired/verified/attached -> cleanup_pending -> deleted
```

The browser's report that an upload completed is not a trusted state. `issued`
therefore remains the state until backend verification succeeds.

One presigned request is issued per intent and exact key. It expires after at
most 10 minutes and constrains the exact key, one allowed content type, and a
content-length range whose upper bound is the intent's declared size and never
exceeds 5,000,000 bytes. Presigning never grants list, read, delete, overwrite
of another key, or attachment capability. Renewing an active intent issues a
new short-lived signature for the same exact key; it does not allocate another
media slot.

After direct upload, the backend reads the object at the expected bucket and
key and verifies its exact size, detected type, server-computed object-byte
SHA-256 and equality to the declared expectation, safe image decoding, and
dimension limits. Verification is idempotent. A mismatch does not attach the
object. In one database transaction it records a stable per-file failure
outcome, performs the `failed` transition, then enters `cleanup_pending` with
durable exact-key cleanup work; the failure outcome remains available after
the state changes. Only a verified intent owned by the same user and bound to
the same draft may be attached. Attachment is a backend transition, not an
image-record mutation accepting a request ID and URL.

Every operation that can allocate, retain, release, or consume one of the
three media slots—including intent creation, verification completion,
attachment, removal, intent discard/expiry, and finalization—locks the parent
submission row and relevant intent/attachment rows in a consistent order
inside `transaction.atomic()`. It rechecks ownership, `draft` state, slot
count, attachment position uniqueness, digest uniqueness, and intent state
under those locks before mutation. External object transfer and byte
inspection occur outside the transaction; the verifier then reacquires the
locks and revalidates before committing its result. Two concurrent intent
requests therefore cannot allocate a fourth slot, and attachment cannot race
removal, expiry, cleanup, or finalization into an invalid aggregate.

The owner may remove or reorder attached media while the submission is a
draft. Finalization succeeds only when every retained media slot is verified
and attached and no non-terminal intent remains. Once pending, media and order
are immutable. Approval links the same retained media metadata to the public
place without losing its submission relation or provenance.

## 7. Visibility and delivery

- Source objects, intents, checksums, storage metadata, and media attached to
  `draft`, `pending`, `withdrawn`, `expired`, or `rejected` submissions are
  private. Possessing or guessing an object key is not read authorization.
- The owner may retrieve their own private preview through a short-lived,
  backend-authorized read capability. Moderators may retrieve pending media
  under the M1 review permission. Neither capability is a permanent public
  URL.
- Media becomes public only after the submission is approved. Public responses
  expose an application-controlled media URL or identifier, never a presigned
  upload form, private source key, owner, intent, or submission audit data.
- Before public delivery, the implementation must produce or validate a safe
  display rendition that strips embedded metadata. The private source object
  is never made anonymously readable merely by changing its submission state.
- Rejection, withdrawal, expiry, removal, or exceptional place/media deletion
  revokes preview or public delivery before asynchronous object deletion
  begins.

The local S3-compatible environment must exercise the same private-before-
approval and public-after-approval semantics; a globally anonymous upload
prefix is not acceptable evidence for this workflow.

## 8. Transactions, retries, and partial failure

Submission creation, draft edit, finalization, every media state/attachment
operation, and system expiry each validate before mutation and commit their own
database change atomically. The M4-reserved owner withdrawal, rejection, and
approval operations must do the same once enabled; they fail closed throughout
M3. Every operation on an existing submission first locks that submission row;
media operations use the additional consistent lock order in section 6.
Transition preconditions and authorization are always rechecked under the
lock. Validation or storage failure leaves no orphan `Address`, `Place`, tag,
attachment, or public-media row. External geocoding, object transfer, and
object decoding do not run as model-save side effects or hold a database
transaction open.

Every state-changing client operation carries an opaque idempotency key scoped
to the authenticated actor and operation. The backend retains the key and a
canonical request hash with the target lifecycle record. Repeating the same
key and same canonical payload returns the original resource and outcome;
reusing it with a different payload returns an idempotency conflict and changes
nothing. Draft edit, finalize, verify, attach, remove, and reorder are safe to
repeat after a lost response in M3. When M4 enables them, withdrawal, approval,
and rejection must have the same idempotent behavior. System expiry and
cleanup use deterministic job identities and the same prior-result behavior.

Files progress independently. If one of several uploads fails, successful
verified attachments remain on the draft, the failed file retains a stable
per-file failure code while its object proceeds through `cleanup_pending`, and
the submission remains `draft`. The owner may retry the same active intent
after a transport failure, discard it, or replace an intent with a recorded
failed/expired outcome after the locked slot count confirms capacity. Retrying
submission creation never creates a second draft, and retrying an upload never
attaches an object twice.

Race outcomes are deterministic. Tests must force competing lifecycle
transitions to pass their initial read before either commits and prove that
exactly one valid transition/event wins. The M3 submission race matrix includes
concurrent idempotent creation, same-transition duplicates, and
finalize/expire. M4 owns every race involving a reserved withdrawal, approval,
or rejection: finalize/withdraw, withdraw/expire, withdraw/approve,
withdraw/reject, approve/reject, simultaneous withdrawals, simultaneous
approvals, and simultaneous rejections. Tests must do the same for concurrent
intent creation at the three-slot boundary, duplicate attachment, attach
versus remove/finalize/expiry, and verification versus cleanup; M4 adds
approval and withdrawal versus cleanup. Losing operations return a stable
conflict or idempotent prior result and create no extra event, attachment,
slot, place, or cleanup target.

The frontend shows submission and per-file states from backend truth, awaits
every selected file, and reports success only after finalization returns the
`pending` submission. It must not clear the form or claim completion because
the proposal row exists while requested media is still issued, failed, or
unverified. A refresh or reconnect can reload the draft and resume from its
recorded state.

## 9. Abandoned intent and object cleanup

- An unverified intent expires 24 hours after creation if verification has not
  succeeded. Renewing its presigned request does not extend that absolute
  deadline. Its presigned request may expire earlier as required above. The
  serialized expiry transaction records `expired` as the failure outcome and
  immediately enters `cleanup_pending` when an object may exist.
- Every object made unavailable in M3 by intent expiry, verification failure,
  draft-media removal, draft expiry, or exceptional deletion enters
  `cleanup_pending` in the same database transaction as that decision. M4
  withdrawal and rejection use this same handoff once enabled. One unified SLA
  applies: an idempotent job must attempt deletion by the recorded exact bucket
  and key no later than 24 hours after `cleanup_pending` commits. No seven-day
  cleanup window applies to any of these cases.
- A deletion failure retains the intent/object metadata, records a redacted
  failure outcome, and retries with bounded backoff. Metadata is marked
  `deleted` only after storage confirms the object is absent.
- Draft inactivity cleanup uses the 30-day `draft` → `expired` transition in
  section 3 and moves every retained object to `cleanup_pending` in that same
  transaction.
- Cleanup locks the media record and parent submission, claims the exact key
  with a conditional lease, and rechecks that the object is unavailable and
  is not attached to a live draft, pending submission, or approved place
  before deletion. Verification, attachment, removal, and cleanup honor the
  same lock order and lease in M3; approval and withdrawal join that order in
  M4. A cleanup race must fail closed rather than delete live media; a key
  claimed for cleanup cannot become verified or attached.
- Cleanup work is recoverable from durable `cleanup_pending` rows. Dispatch may
  use an outbox or post-commit wake-up, but correctness cannot depend only on an
  in-memory task or `on_commit` callback that can be lost after commit.
- Reconciliation is restricted to the managed media namespace and known
  intent keys. It must not perform an unbounded bucket deletion or infer
  ownership from a filename or prefix alone.

Cleanup emits counts and non-sensitive identifiers suitable for operations,
but never presigned fields, credentials, user profile data, or object contents.
Tests use controlled time and a fake/local S3-compatible service to prove the
24-hour SLA, expiry, deterministic failure-to-cleanup handoff, deletion retry,
lease recovery, forced verification/attachment cleanup races, and absence of
cross-submission deletion. M4 adds forced withdrawal, rejection, and approval
cleanup races before enabling those transitions.

## 10. Errors, authorization, and verification requirements

M1's REST `401`/`403`/object-hiding `404` semantics and equivalent stable
GraphQL errors continue to apply. M3 additionally defines stable,
non-sensitive errors for invalid fields, duplicate submissions, invalid state
transitions, idempotency conflicts, media limits, invalid media, expired
intents, verification failure, and media not ready for finalization. Field and
per-file errors may identify the invalid field or client-visible media slot;
they must not reveal another owner, submission, intent, bucket, or object key.

M3 backend tests must cover:

- guest, inactive, owner, other user, moderator, and administrator access to
  every M3 submission, intent, preview, attachment, and transition boundary;
- every M3-enabled and denied submission transition, forced finalize/expiry
  races, exactly one winning state/event, and fail-closed `draft` →
  `withdrawn`, `pending` → `withdrawn`, `pending` → `approved`, and `pending`
  → `rejected` attempts for every role;
- all field boundaries, coordinate ranges, the exact stable category slug set,
  deterministic syntactic-only HTTPS website parsing, ASCII and Punycode
  multi-label hosts, rejection of IP/single-label/reserved/special-use hosts
  from the code-owned list, proof that validation performs no DNS, network, or
  fetch, and canonical tag rules;
- the exact geography `ST_DWithin(..., 25.0)` boundary, same names beyond it,
  different names at one point, absence of global name uniqueness,
  transaction-scoped full-canonical-name serialization even when no matching
  row exists, owner-scoped non-terminal checks, and no cross-owner private-
  submission conflict or disclosure;
- zero, one, and three images; a fourth image; every allowed and rejected
  media type; byte, dimension, signature, decode, and server-computed object-
  byte SHA-256 failures; untrusted client hash/metadata disagreement; and
  verified-digest uniqueness per submission;
- exact owner/submission/key binding and attempts to attach another owner's or
  another submission's object;
- concurrent intent creation at the three-slot boundary, attach/remove/
  finalize/expiry races, duplicate attachment and position races, and proof
  that failure creates one durable cleanup target without consuming a slot;
- same-key retries, different-payload conflicts, lost-response retries,
  independent multi-file failure/retry, and no premature success;
- private M3 visibility with no public delivery path; and
- intent expiry, distinct draft `expired` state, the unified 24-hour
  `cleanup_pending` SLA, deterministic failure handoff, deletion retry/lease
  recovery, forced cleanup races, and exact-key isolation.

Before M4 enables lifecycle or moderation writes, its backend tests must
additionally cover every allowed and denied owner withdrawal, approval, and
rejection transition, including self-review denial; approval-time validation
and privacy-safe duplicate revalidation under the submission row lock and a
transaction-scoped lock keyed by the full canonical name, independent of
whether a matching row exists;
simultaneous withdrawal, simultaneous approval, simultaneous rejection,
finalize/withdrawal, withdrawal/expiry, approval/rejection,
approval/withdrawal, and rejection/withdrawal races; withdrawal and rejection
as distinct lifecycle actions, each distinct from exceptional M1 audited hard
deletion; injected rollback at every materialization step; withdrawal and
rejection cleanup under the unified 24-hour SLA; and private-to-public delivery
without exposing storage or identity metadata. These M4 tests are contract
requirements, not M3 exit work.

M3 frontend tests must cover mirrored validation, authenticated-only entry,
zero-image completion, per-file progress and error states, retry after partial
failure, refresh/resume, and success only after backend finalization. A local
cross-application test must exercise submission with zero images and with
multiple images through the real backend, object storage, and frontend path;
it ends at private `pending`, not approval. M4 owns moderation UI tests and the
public-after-approval cross-application path.

## 11. M3 implementation boundary

M3 implementation may begin after this contract is adopted. Work proceeds in
the owning repositories through linked issues and pull requests. Until a new
path demonstrates this complete contract, all legacy submission/media write
entry points—including the general presign query, public-URL image mutation,
and any path accepting a client URL, actor, owner, verification flag, or
arbitrary object key—stay fail-closed. They may be removed, but cannot act as a
compatibility shim around the new aggregate.

M3 enables only creation into `draft`, owner draft editing and media work,
owner finalization from `draft` to `pending`, and system expiry from `draft`.
It may expose the M1-authorized private pending review read, but it does not
enable owner withdrawal or moderation writes. Every legacy or new entry point
capable of `draft` → `withdrawn`, `pending` → `withdrawn`, `pending` →
`approved`, or `pending` → `rejected` must return a stable fail-closed response
for users, moderators, and administrators throughout M3. `withdrawn` remains a
distinctly modeled reserved state but is unreachable until M4. Exceptional
administrator hard deletion remains the separate M1 audited operation and
must never be represented as withdrawal or rejection. M4 alone may enable both
owner withdrawal transitions, approval, and rejection after its transactional
services and complete M4 test gate above are merged.

The implementation order remains the roadmap order: introduce the submission
aggregate and constraints; add canonical validation and idempotent draft/
finalize operations; add exact owner-bound intents, verification, attachment,
visibility, and cleanup; then rebuild the frontend around the backend state.
M3 exits only when every M3 roadmap criterion and M3 test above is demonstrated
at merged application revisions pinned by the workspace. The reserved M4
withdrawal, approval, and rejection transitions and their enabling tests do not
become M3 exit criteria and remain disabled when M3 exits.
