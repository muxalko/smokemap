# Smokemap pre-milestone audit

Audit date: 2026-08-19

Status: Completed evidence review and canonical action plan

## 1. Scope and method

This audit reconciles current source, Git history, GitHub repository settings,
issues, milestones, pull requests, branch state, Docker Compose checks, tests,
and redacted secret scans across:

- the `smokemap` workspace;
- `smokemap-webapp`;
- `smokemap-django-backend`.

No production credentials, tokens, session values, authorization headers, or
private-key material were printed or inspected.

## 2. Executive finding

Credential incident response and repository governance cleanup are complete.
Application security containment is not complete. Smokemap is ready to begin
the canonical M1 security and authorization milestone, but it is not ready to
start M2 through M5 or to enable untrusted production writes.

## 3. Verified completed work

### Credential and history response

- The known leaked token was revoked.
- Supported root and frontend histories were cleaned as planned.
- Backend history was preserved.
- Production-named credential files and application logs are not tracked.
- Redacted Gitleaks full-history scans returned clean for all three
  repositories on 2026-08-19.
- Only the safe root `.env.example` matched the tracked configuration pattern.

### Repository governance

All three repositories are public and use `development` as the default branch.
They allow only squash merges, delete merged branches, and protect
`development` with:

- one required approval;
- resolved review conversations;
- linear history;
- force pushes disabled;
- branch deletion disabled.

Frontend `development`, `staging`, and `main` remain intentionally independent
clean-root trees. Backend history and deployment branches remain intact.

### Local engineering baseline

On 2026-08-19:

- `docker compose config --quiet` passed;
- Django system checks passed;
- eight backend tests passed;
- frontend TypeScript and ESLint passed with documented existing warnings;
- three frontend Jest tests passed;
- the complete Compose stack remained the canonical development environment.

The frontend now has focused coverage for basemap style normalization and
missing-image handling. This is useful coverage, not yet the complete critical
workflow foundation required by M1.

## 4. Unfinished security blockers

### Public backend writes

`PlaceViewSet` is still a full Django REST Framework `ModelViewSet` with
`AllowAny`. An anonymous client can therefore reach create, update, and delete
operations. M1 must make public place access read-only and test every method.

### Moderation authorization

Pending-request reads, approval, and deletion check only
`user.is_authenticated`. A normal authenticated account is not distinguished
from a moderator or administrator at the backend boundary. Approval also uses
a client-supplied `approved_by` string.

### Upload and image authorization

Presigned-upload generation and image-record creation remain public. They are
not bound to an authenticated owner, exact upload intent, verified object, or
submission capability.

### Browser-visible backend credentials

The NextAuth session callback still copies backend access and refresh tokens to
the browser-readable session. Refresh behavior is not fully defined for
rotation, reuse, concurrent requests, revocation, logout, and terminal failure.

### Frontend destructive-action guards

Approval and deletion server actions call the backend without their own
moderator/administrator session check. Frontend checks are needed for
fail-closed UX, while backend authorization remains authoritative.

### Regression and CI enforcement

There is no complete role/action matrix suite, authentication-lifecycle suite,
or CI workflow enforcing secret scanning, checks, and tests. Manual Gitleaks
and local tests are currently clean but are not a durable gate.

## 5. Current milestone inventory

GitHub milestones are canonical:

| Repository | M1 open work |
| --- | --- |
| Backend | `#13` permission matrix; `#48` JWT lifecycle |
| Frontend | `#4` same-origin verification; `#12` token handling; `#13` destructive guards; `#14` critical tests |

Later milestones already contain viewport, submission, media, moderation,
search, dependency, CI, and production-readiness issues. They should remain
ordered but inactive until their entry criteria pass.

## 6. Planning and governance drift found

The audit found these documentation mismatches:

- the root roadmap used historical M0–M9 numbering while GitHub uses M1–M5;
- the architecture assessment was still presented as current even where
  cleanup and local-development findings had been superseded;
- the local checkpoint could be mistaken for the current integration baseline;
- the development guide said zero approvals while repository protection and
  the agreed workflow require one;
- the guide recorded seven backend tests and zero frontend tests instead of
  eight and three;
- the workflow required a GitHub Project even though no Project V2 exists;
- feature branches were assumed to receive previews, but Vercel tracks only
  deployment branches;
- the production branch was sometimes called `master`, while the remote branch
  is `main`.

The accompanying planning-sync change resolves these mismatches by making the
M1–M5 roadmap canonical, marking historical evidence explicitly, requiring one
approval, making Project assignment conditional on a project existing, and
documenting promotion behavior.

## 7. Recommended M1 order

1. Verify and close the existing same-origin boundary work.
2. Deny anonymous place writes and restrict moderation conservatively.
3. Approve and enforce the role matrix in REST and GraphQL.
4. Define and test JWT login, expiry, refresh, revocation, and logout.
5. Remove backend credentials from browser-visible sessions.
6. Add frontend moderator/administrator guards.
7. Complete backend and frontend security regression suites.
8. Add reliable CI gates, including redacted secret scanning.
9. Demonstrate every M1 exit criterion before beginning M2.

## 8. Decisions intentionally deferred until this plan merges

The next planning activity will approve or explicitly defer:

- guest submission policy and ownership;
- the guest/user/moderator/administrator permission matrix;
- moderator versus administrator powers;
- token transport, rotation, reuse, revocation, and lifetime;
- logout and terminal refresh-failure semantics;
- minimum audit and privacy requirements.

No implementation should silently decide these product policies. Conservative
denial may still be used to close an unsafe public boundary.

## 9. Non-blocking backlog hygiene

After the planning-sync pull request is approved and merged:

- close six stale backend Dependabot PRs and regenerate dependency updates in
  M5 against the current manifests and history;
- inspect obsolete branches before deletion and preserve every branch with
  unique history;
- keep frontend clean-root deployment trees intact;
- preserve backend history and define deployment-branch promotion before
  reconciling it.

This hygiene is administrative cleanup, not an M1 prerequisite.

## 10. Readiness decision

After the planning-sync change and pointer baseline are merged, no further
credential/history cleanup blocks development. Begin M1 with the policy
contract and conservative backend containment. Do not begin M2, M3, M4, or M5
product work until M1 exit evidence is recorded.
