# M1 security and authorization contract

Status: Adopted when this document is merged into `development`

Decision date: 2026-08-19

Tracking issue: root `#15`

## 1. Scope and authority

This contract resolves the product and security decisions required to implement
M1. It applies to REST, GraphQL, frontend server actions, authentication
callbacks, and moderation UI.

The Django backend is the authoritative authorization boundary. The frontend
must also fail closed so unavailable controls and unauthorized server actions
produce safe behavior, but a frontend role check never replaces a backend
permission check. Backend permissions are derived from the current database
user on every protected request; client input and browser session claims are
not authoritative.

An inactive account is denied every authenticated action. It retains only the
same public read access as a guest.

## 2. Roles

M1 uses the existing Django account state with this precedence:

1. **Administrator:** active user with `is_superuser=True`. Administrators must
   also have `is_staff=True`.
2. **Moderator:** active user with `is_staff=True` and
   `is_superuser=False`.
3. **User:** active authenticated user with neither staff nor superuser status.
4. **Guest:** unauthenticated visitor. Inactive accounts are treated as guests
   for public reads and denied otherwise.

The backend may return a normalized `user`, `moderator`, or `administrator`
role to support frontend UX. That value is an informational snapshot only.
Authorization continues to use the authenticated backend user.

## 3. Permission matrix

`Own` means the backend-assigned owner, never a client-supplied identifier.
`All` means any submission within the endpoint's bounded query contract.

| Action | Guest | User | Moderator | Administrator |
| --- | --- | --- | --- | --- |
| Read approved places, categories, tags, and public map/search data | Yes | Yes | Yes | Yes |
| Create a pending submission | No | Own | Own | Own |
| Read a pending submission | No | Own | All | All |
| List pending submissions | No | Own only | All | All |
| Update or withdraw a pending submission | No | Denied in M1 | Denied in M1 | Denied in M1 |
| Approve a pending submission | No | No | Yes | Yes |
| Reject a pending submission | No | No | Deferred to M3/M4 | Deferred to M3/M4 |
| Hard-delete a pending submission | No | No | No | Yes, with durable audit evidence |
| Directly create, update, or delete an approved place | No | No | No | Yes |
| Request an upload or create an image record | No | Denied in M1 | Denied in M1 | Denied in M1 |
| Manage accounts, roles, or permissions | No | No | No | Yes |

Additional rules:

- REST approved-place list and retrieve operations remain public. REST write
  methods require an administrator.
- A moderator may create a personal submission as a user. That does not make
  the moderator the submission's reviewer.
- A reviewer must not approve their own submission. An administrator may
  override this only through an explicit, audited administrative path; the
  ordinary moderation mutation must reject it.
- The current destructive delete operation is administrator-only. A durable
  rejection/withdrawal lifecycle belongs to M3/M4 and must replace deletion as
  the routine moderation outcome.
- Upload presigning and image-record creation remain disabled during M1. M3
  may enable them only through an authenticated, owner-bound, constrained
  upload intent with object verification.

## 4. Guest submission and ownership decision

Guests cannot submit places or upload images. No IP address, forwarded address,
cookie, or browser-generated identifier is accepted as submission ownership.
A future guest-capability design requires a separate decision and threat model.

Authenticated submission creation is enabled only after `Request` has a
backend-assigned foreign-key owner. Until that ownership change is merged, the
creation mutation must fail closed for every caller. New submissions must not
use the legacy `requested_by` IP string as identity.

Pending-submission queries must filter normal users to their own rows. They
must not expose another submitter's identity or moderation data. The backend
sets owner, creator, and reviewer fields from the authenticated request and
rejects or ignores equivalent client-supplied fields.

## 5. Moderator and administrator powers

Moderators review the pending queue and may approve submissions. They may use a
durable reject action after the M3/M4 lifecycle exists. They cannot manage
accounts or roles, hard-delete pending records, or directly mutate approved
places.

Administrators inherit moderator powers and may additionally manage accounts
and roles, perform direct approved-place maintenance, and execute exceptional
audited hard deletion. Superuser status does not bypass the normal API audit
requirements.

The client-supplied `approved_by` string is retired. Approval records the
authenticated reviewer through a backend-owned relation or immutable actor
identifier.

## 6. Authentication and token lifecycle

### Canonical path and lifetime

- The M1 frontend uses the GraphQL login, refresh, verify, and revoke lifecycle.
  It must not mix GraphQL login with the legacy DRF refresh path.
- The access token issued by that lifecycle is the single bearer credential
  for protected application REST and GraphQL requests. Both paths must resolve
  the same active backend user and apply the same role contract.
- Access tokens live for five minutes.
- Refresh tokens live for seven days. The frontend session cannot outlive the
  refresh token.
- Authentication tokens contain the minimum claims needed for validation and
  subject identity. Email, image URLs, and other profile data are excluded
  unless a demonstrated backend requirement needs them.

### Transport and browser boundary

- Credentials and backend tokens are handled only by trusted frontend server
  code and the backend over TLS in deployed environments.
- Access and refresh tokens may be retained inside the encrypted, HTTP-only
  NextAuth session cookie used by server callbacks. They must never be copied
  into the browser-visible session object, response JSON, client storage, URL,
  error message, or log.
- Production session cookies are host-only, `Secure`, `HttpOnly`, and
  `SameSite=Lax`. Development may disable `Secure` only for local HTTP.
- The browser-visible session contains only safe identity/UX data: user ID,
  display name, image URL, normalized role, session expiry, and a non-sensitive
  terminal-authentication error code.
- Protected frontend server actions obtain the server session, check the
  required role, and attach the access token only to the server-to-backend
  request. State-changing same-origin boundaries retain CSRF and origin
  protection.

### Rotation, concurrency, revocation, and failure

- Every successful refresh rotates the refresh token and revokes the token it
  replaces. Rotation is atomic at the backend.
- Reuse of a rotated token revokes its token family and terminates the session.
- Concurrent frontend requests use one refresh operation per session. Waiting
  requests reuse the resulting credentials; they do not independently rotate
  the same refresh token.
- Logout revokes the active refresh token family before clearing the frontend
  session. Local session clearing still occurs if the backend is unavailable.
- Missing, malformed, expired, revoked, or reused refresh tokens are terminal.
  Invalid refresh responses and repeated provider/network failure after one
  controlled retry are also terminal.
- Terminal failure erases held backend credentials, clears authenticated
  state, returns a stable non-secret error, and requires a new login. It never
  enters a refresh loop.
- Authentication error responses are generic enough to avoid account
  enumeration. No token payload, cookie, password, authorization header, CSRF
  value, session object, or secret-bearing environment value is logged.

## 7. Audit and privacy minimums

M1 requires the following minimum evidence:

- moderation and administrative mutations record actor, action, target,
  timestamp, and outcome from backend-owned identity;
- hard deletion records durable evidence before the target is removed;
- authentication and authorization logs record outcome, correlation ID, and a
  stable internal actor ID when available, without credentials or profile
  data;
- public place responses do not expose submission owner, reviewer identity,
  authentication state, IP address, or internal audit fields;
- IP addresses are not domain ownership and are not persisted in `Request`;
- routine application and CI output uses structured redaction for cookies,
  tokens, authorization headers, passwords, presigned fields, and secret-bearing
  objects.

Exact security-log retention and account data-export/deletion periods are
deferred to the M5 operational/privacy policy. Until that policy is adopted,
the applications must minimize collection and must not introduce new persistent
IP or credential-derived fields.

## 8. Error contract and tests

REST uses `401` for missing or invalid authentication, `403` for an
authenticated role without permission, and `404` when object-level filtering
must avoid confirming another user's protected object exists. GraphQL returns
the equivalent typed/stable authentication or permission error without
embedding sensitive context.

Parameterized backend tests must cover every matrix row for guest, inactive,
user, moderator, and administrator accounts across both REST and GraphQL.
Frontend tests must cover hidden controls, direct server-action invocation,
backend denial, login, refresh, concurrent refresh, rotation reuse, logout, and
terminal failure.

## 9. Mapping to M1 issues

| Repository issue | Contract implemented |
| --- | --- |
| Backend `#13` | Sections 1–5, 7, and authorization/error tests in section 8 |
| Backend `#48` | Section 6 and authentication tests in section 8 |
| Frontend `#4` | Same-origin transport portion of section 6 |
| Frontend `#12` | Browser boundary and lifecycle portions of section 6 |
| Frontend `#13` | Role-sensitive server-action and UI requirements in sections 1–3 |
| Frontend `#14` | Frontend regression requirements in section 8 |

Application changes remain in their owning repositories. Cross-repository work
uses linked issues and pull requests, and the root updates submodule pointers
only after application commits are merged and available remotely.

## 10. Implementation order after adoption

1. Verify and close frontend same-origin issue `#4`.
2. Implement conservative backend containment and the role matrix under
   backend `#13`.
3. Implement the backend token lifecycle under backend `#48`.
4. Remove browser-visible credentials under frontend `#12`.
5. Add frontend destructive-action guards under frontend `#13`.
6. Complete the security regression foundation under frontend `#14`.
7. Add reliable CI gates and record M1 exit evidence.

M2 does not begin until every M1 exit criterion in the roadmap is demonstrated.
