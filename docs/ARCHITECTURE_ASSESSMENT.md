# Smokemap Joint Architecture and Engineering Assessment

Status: Completed assessment

Assessment date: 2026-08-10

Scope: `smokemap-webapp` and `smokemap-django-backend`

Method: Read-only source, configuration, repository, and static-analysis review

Execution plan: [Smokemap Execution Roadmap](ROADMAP.md)

## 1. Executive conclusion

Recommendation: **perform a partial rewrite with staged migration**.

Keep the viable foundations—Django, PostGIS, Next.js, MapLibre, the existing visual components, domain vocabulary, and production data—but replace the critical workflows behind versioned boundaries. The current system should not accept production writes until the highest-priority authorization and credential issues are contained.

A clean-slate implementation would discard useful product knowledge. Incremental patching alone is insufficient because authorization, moderation, uploads, authentication, and the domain lifecycle share unsafe assumptions.

Evidence labels used in this document:

- **Direct evidence:** visible in the current source or repository state.
- **Inference:** derived from source behavior but not exercised against live infrastructure.

The backend repository is named `smokemap-django-backend` in this workspace. Neither repository contains an additional `AGENTS.md`; the workspace-level instructions apply to both.

## 2. Product intent

Smokemap is a community-maintained geographic directory of places. Its important workflows are:

1. Browse places on an interactive map.
2. Retrieve places within the visible viewport.
3. Search for places and view their details.
4. Submit a place with category, description, tags, location, and images.
5. Authenticate users and refresh sessions.
6. Review, approve, reject, or delete submissions.
7. Apply guest, user, moderator, and administrator permissions.

## 3. Current system architecture

```text
Browser
  |
  +-- Direct REST GET /locations/?in_bbox=...
  |     `-- Django REST Framework -> Location -> PostGIS
  |
  +-- Direct public GraphQL
  |     +-- categories
  |     +-- place search and details
  |     +-- createRequest
  |     `-- createImage
  |
  +-- Next.js server and server actions
  |     +-- NextAuth login and refresh
  |     +-- moderation queries and mutations
  |     +-- place-name suggestion filtering
  |     `-- presigned-upload request
  |
  `-- Direct presigned POST to S3-compatible storage

Django
  +-- Graphene/JWT endpoint
  +-- DRF/GeoJSON endpoints
  +-- PostgreSQL/PostGIS
  `-- boto3 presign generation
```

The system effectively has three APIs:

1. Public DRF/GeoJSON endpoints.
2. Public and authenticated GraphQL operations.
3. Next.js server actions acting as an inconsistent backend-for-frontend.

Protected GraphQL calls pass access and refresh tokens from NextAuth to Django as manually constructed cookies (`smokemap-webapp/src/lib/client.js:38-58`). Browser Apollo calls do not attach NextAuth credentials (`smokemap-webapp/src/lib/apollo-wrapper.tsx:31-59`), so corresponding backend operations work only when public.

## 4. End-to-end workflow traces

### 4.1 Authentication and token refresh

Actual flow:

1. Credentials are posted to NextAuth.
2. `authorize()` calls the backend GraphQL `tokenAuth` mutation (`smokemap-webapp/src/app/api/auth/[...nextauth]/config.ts:141-175`).
3. Django returns an access token, refresh token, expirations, and user information (`smokemap-django-backend/backend/schema.py:592-604`).
4. NextAuth merges the returned user and token fields into its JWT (`config.ts:320-343`).
5. The session callback copies access and refresh tokens into the browser-readable session (`config.ts:345-352`).
6. After access-token expiry, the JWT callback calls GraphQL `refreshToken`, sending the refresh token as a backend cookie (`config.ts:74-112`).
7. Backend revoke support exists, but no frontend operation calls it. NextAuth sign-out therefore does not revoke the backend refresh credential.

Identity and role handling is split:

- Django groups produce only `admin` or `guest` (`smokemap-django-backend/backend/schema.py:24-45`).
- `is_staff` and `is_superuser` govern Django administration rather than API moderation.
- User and moderator roles do not exist as backend API concepts.
- The main template does not render its imported navigation component, leaving no discoverable sign-in route in normal navigation (`smokemap-webapp/src/components/template/template.tsx:33-48`).

Security evidence:

- Tokens and authentication structures are logged in `config.ts:22`, `config.ts:77`, `config.ts:177`, `config.ts:206`, and `config.ts:320-342`.
- Server Apollo logs the complete NextAuth session (`smokemap-webapp/src/lib/client.js:22-39`).
- Middleware logs `request.nextauth`, which contains the augmented token (`smokemap-webapp/src/middleware.ts:9-14`).
- Access and refresh fields are explicitly part of the browser session type (`smokemap-webapp/src/types/nextt-auth.d.ts:9-21`).

### 4.2 Viewport-based place retrieval

Actual flow:

1. The map initializes around Washington, DC and constructs a four-degree bounding box (`smokemap-webapp/src/components/map/map-component.tsx:95-103`).
2. On initial mount, the browser fetches `NEXT_PUBLIC_FEATURESERV_ENDPOINT?in_bbox=...` (`map-component.tsx:317-359`). All supplied frontend environments target `/locations/`.
3. `LocationViewSet` declares `InBBoxFilter` but does not define `bbox_filter_field` (`smokemap-django-backend/backend/views.py:8-23`).
4. **Direct evidence:** the installed filter returns the queryset unchanged when that field is absent (`venv3.9/lib/python3.9/site-packages/rest_framework_gis/filters.py:69-83`). The `/locations/` endpoint therefore ignores `in_bbox`.
5. Moving the map updates viewport, bounds, crosshair state, and a cookie (`map-component.tsx:580-591`, `map-component.tsx:726-780`) but never refetches features.
6. When the feature collection is empty, the UI displays “Loading” and does not mount the map (`map-component.tsx:947-953`).

`Address.location` and `Location.geom` are SRID 4326 point fields (`smokemap-django-backend/backend/models.py:71-74`, `models.py:176-184`). GeoDjango enables spatial indexes by default, but no deployed schema or query plan was inspected. The immediate failure is that the current viewport endpoint does not apply its spatial predicate.

No viewport-size cap, result limit, pagination, zoom-dependent behavior, or server-side clustering is implemented.

### 4.3 Search and place details

Two search paths coexist:

- Every keystroke triggers a server action (`smokemap-webapp/src/components/places/Search.tsx:18-31`). The action retrieves every place name and filters the collection in memory (`smokemap-webapp/src/app/actions.ts:60-79`).
- Pressing Enter performs a second GraphQL request, `placesStartwithName` (`smokemap-webapp/src/components/places/PlaceList.tsx:20-28`).

The backend performs an unbounded, case-sensitive `startswith` query (`smokemap-django-backend/backend/schema.py:252-254`). Results include nested address, category, and images without explicit query optimization or a limit.

Selecting a map feature renders `PlaceCard`, which calls public `placeById` and displays related images (`smokemap-webapp/src/components/places/PlaceCard.tsx:51-62`, `PlaceCard.tsx:83-121`).

### 4.4 Place submission

Actual flow:

1. The client validates the form and submits `createRequest` (`smokemap-webapp/src/app/requests/request-react-form.tsx:455-483`).
2. The backend mutation has no authentication check (`smokemap-django-backend/backend/schema.py:302-410`).
3. An address is reused, synchronously geocoded with Nominatim, or created from client-supplied coordinates.
4. A `Request` is created with a proxy/IP-derived `requested_by` string rather than a user relation (`schema.py:388-401`).
5. Image upload begins asynchronously after the request mutation completes.

Backend correctness concerns:

- Address creation happens before category validation, allowing invalid submissions to leave orphan addresses.
- `Address.save()` performs network I/O and rejects normal updates because it finds the existing row (`smokemap-django-backend/backend/models.py:75-106`).
- Duplicate-place validation calls `len()` on a single `Place`; the resulting exception is swallowed (`smokemap-django-backend/backend/schema.py:352-362`).
- Several GraphQL inputs are optional while corresponding database fields are non-null, permitting database errors from clients that bypass the frontend.
- Coordinate strings are parsed without explicit coordinate-count or range validation (`schema.py:317-330`).

### 4.5 Presigned image upload and image-record creation

Actual flow:

1. A Next.js server action requests `s3PresignedUrl`.
2. The public resolver creates a 60-second presigned POST (`smokemap-django-backend/backend/schema.py:256-292`).
3. The browser uploads directly to object storage.
4. The browser calls public `createImage` with a request ID and constructed object URL.

Confirmed defects and risks:

- `Image.set_id` is required and has no default (`smokemap-django-backend/backend/models.py:162-168`), but `CreateImage` never assigns it (`smokemap-django-backend/backend/schema.py:573-589`). Image-record insertion should fail.
- One mutable `FormData` and one presigned response are reused for concurrent uploads (`smokemap-webapp/src/app/requests/request-react-form.tsx:342-409`).
- Upload promises started through `forEach` are not collectively awaited.
- HTTP success is not checked before `createImage` is called.
- Completion is counted before image mutations finish, and the form may clear while operations are failing.
- Client Zod refinements inspect only the first file (`request-react-form.tsx:122-134`).
- The backend accepts arbitrary request IDs and URLs without confirming object key, ownership, size, type, or upload completion.
- No object cleanup, lifecycle state, quarantine, or storage deletion operation exists.

### 4.6 Moderation approval and deletion

Actual flow:

1. NextAuth middleware restricts `/requests` to a frontend token with role `admin` (`smokemap-webapp/src/middleware.ts:9-25`).
2. The server-rendered page retrieves pending submissions through authenticated server Apollo.
3. Server actions call approval or deletion without independently checking the session role (`smokemap-webapp/src/app/actions.ts:16-58`).
4. Django requires only `is_authenticated` for pending-submission reads, approval, and deletion (`smokemap-django-backend/backend/schema.py:214-228`, `schema.py:413-426`, `schema.py:434-447`).

Approval sequentially creates a `Place`, tags, image associations, a denormalized `Location`, and then updates the request (`schema.py:477-565`). There is no `transaction.atomic`, row lock, or concurrency control.

Further defects:

- `approved_by` comes from a client-supplied string and is hardcoded to `Admin` by the frontend (`smokemap-webapp/src/app/actions.ts:41-53`).
- Concurrent approvals can partially write or collide on unique place names.
- Deletion is a hard delete with no audit record.
- Image foreign keys use `on_delete=DO_NOTHING`; deleting a request with images is expected to fail under the database foreign-key constraint (`smokemap-django-backend/backend/models.py:162-168`).
- In the current uncommitted frontend working tree, clicking Approve invokes the action twice (`smokemap-webapp/src/app/requests/columns.tsx:153-168`).

## 5. Actual authorization enforcement

| Capability | Guest | Any authenticated user | Admin group | Actual backend boundary |
|---|---:|---:|---:|---|
| View places and locations | Yes | Yes | Yes | `AllowAny` |
| Create, update, or delete `Place` through DRF | **Yes** | Yes | Yes | Full `ModelViewSet` with `AllowAny` |
| Submit request | Yes | Yes | Yes | No check |
| Request presigned upload | Yes | Yes | Yes | No check |
| Create image record | Yes | Yes | Yes | No check |
| Read pending submissions | No | **Yes** | Yes | `is_authenticated` |
| Approve or delete submission | No | **Yes** | Yes | `is_authenticated` |
| Use Django admin | No | No | Local staff only | Admin disabled outside local mode |

The most severe boundary is `PlaceViewSet`: it is a full public `ModelViewSet` (`smokemap-django-backend/backend/views.py:42-60`). Frontend middleware is not an authorization boundary.

The intended guest/user/moderator/administrator model is not implemented. The backend recognizes an `admins` group for the role displayed to the frontend but does not use it to authorize mutations.

## 6. Django and storage assessment

### 6.1 Domain model

`Request`, `Place`, and `Location` repeat name, category, address/location, tags, and description (`smokemap-django-backend/backend/models.py:115-159`, `models.py:176-190`). Approval manually synchronizes them; later changes through public DRF writes do not synchronize `Location`.

The submission lifecycle is represented by `approved: bool` plus hard deletion. It cannot accurately represent pending, rejected, withdrawn, superseded, or failed moderation and cannot retain an immutable audit trail.

`requested_by` and `approved_by` are strings rather than user foreign keys. `Place.name` is globally unique, which may incorrectly reject identically named places at different locations.

### 6.2 GraphQL schema and resolvers

The schema mixes types, public queries, authentication, storage integration, submission logic, and moderation in one 611-line module.

Plain-list fields such as places, names, addresses, images, and pending requests are unbounded (`smokemap-django-backend/backend/schema.py:134-175`). `RELAY_CONNECTION_MAX_LIMIT` does not constrain these ordinary `graphene.List` fields.

Nested place and request fields lack `select_related` and `prefetch_related`, creating probable N+1 behavior. DRF also has a confirmed N+1 pattern because `PlaceSerializer.get_location()` performs an address query per object (`smokemap-django-backend/backend/serializers.py:42-44`).

### 6.3 Transactions and validation

Approval crosses `Place`, `Tag`, `Image`, `Location`, and `Request` without an atomic transaction. Submission creates or geocodes an address before all input has been validated. Database exceptions can therefore leave partial state.

Validation is distributed between Zod, resolver code, model overrides, and database constraints. The backend cannot rely on frontend validation because GraphQL and DRF are independently reachable.

### 6.4 Geospatial design

PostGIS is appropriate for the product. The two spatial models are not.

`Location` is a manually synchronized read model whose viewport filter is currently ineffective. Unless measured scale requires a materialized projection, the API should query an authoritative `Place.location` or related authoritative point directly.

A viewport API should validate coordinate order and ranges, reject excessive/world-sized bounds, cap results, accept useful category and zoom parameters, and define whether the client or server owns clustering.

### 6.5 Storage design

The backend stores client-supplied public URLs rather than authoritative object keys. Media records do not establish uploader ownership, expected size/type, checksum, upload state, verification state, or cleanup state.

The target design should issue one upload intent and one exact object key per file, constrain content length and MIME type in the presign policy, verify the uploaded object before attachment, and clean up abandoned objects.

## 7. Should GraphQL remain?

For the current product, **GraphQL is not providing enough benefit to remain the primary API**.

Direct evidence:

- The map already needs a specialized REST/GeoJSON endpoint.
- Frontend operations are fixed, screen-specific queries and mutations.
- Search and lists remain unbounded despite GraphQL.
- Generated types add release coupling without eliminating weak runtime handling.
- Browser and server GraphQL clients have different authentication behavior.
- Resolvers do not use Relay pagination, DataLoader, or meaningful graph composition.

Recommended target:

- Versioned REST endpoints with OpenAPI for write and authentication-facing workflows.
- A bounded GeoJSON viewport endpoint.
- A bounded search endpoint.
- The existing GraphQL endpoint retained temporarily as a compatibility adapter.
- GraphQL reconsidered only if multiple independent clients later require materially different graph projections.

## 8. Findings by category

### 8.1 Confirmed defects

| Severity | Finding |
|---|---|
| Critical | Public unauthenticated `Place` CRUD through DRF. |
| High | `/locations/` ignores its bbox; map movement never refetches. |
| High | `CreateImage` omits required `set_id`, breaking image-record creation. |
| High | Moderation is non-transactional and vulnerable to partial state. |
| High | Requests with images cannot be safely hard-deleted because image FKs use `DO_NOTHING`. |
| High | Address updates reject themselves and geocoding occurs inside `save()`. |
| High | The configured primary Argon2 password hasher (`smokemap-django-backend/smokemap/settings.py:28-32`) has no declared `argon2-cffi` dependency in production requirements. A clean install is expected to fail when creating Argon2 hashes. |
| Medium | Empty map results render indefinitely as loading and prevent map interaction. |
| Medium | Multi-image upload can report success before uploads and records complete. |
| Medium | Current frontend working tree invokes approval twice. |
| Medium | Duplicate-place validation swallows its own `TypeError`. |
| Medium | Search retrieves all names per keystroke and has no response-order protection. |

### 8.2 Security risks

| Severity | Finding |
|---|---|
| Critical | Three production-named environment files are tracked: `.postgres.production.env`, `.smokemap.production.env`, and `.smokemap_admin.production.env`. Values were not inspected. Treat referenced credentials as exposed, rotate them, and purge them from Git history. |
| Critical | Public DRF writes permit unauthorized modification or deletion of public map data. |
| High | Any authenticated account can read, approve, or delete pending submissions. |
| High | Access tokens, refresh tokens, sessions, login results, and middleware tokens are logged. |
| High | Refresh tokens are exposed through the browser-readable NextAuth session. |
| High | Presigning and image creation are anonymous and not bound to an owner or upload intent. |
| High | Authorization audit fields are spoofable strings rather than authenticated identities. |
| Medium | GraphQL is explicitly CSRF-exempt (`smokemap-django-backend/backend/urls.py:16-18`) while production JWT cookie security is disabled (`smokemap-django-backend/smokemap/settings.py:385-397`). |
| Medium | No login throttling, mutation throttling, or GraphQL complexity/depth control was found. |
| Medium | Public `images` returns all image records, including request associations (`smokemap-django-backend/backend/schema.py:200-202`). |
| Medium | A tracked rotated backend log contains token-related text. Its contents were not displayed. |

### 8.3 Architectural concerns

- Duplicated `Request`, `Place`, and `Location` sources of truth.
- No durable submission state machine or moderation audit trail.
- Authorization split across Django groups, staff flags, NextAuth roles, middleware, and actions.
- External geocoding as a model persistence side effect.
- Unbounded API queries and probable N+1 behavior.
- Storage coupled to public URLs rather than managed object identities.
- Build-time schema generation and database migration (`smokemap-django-backend/build_files.sh:55-58`).
- Multiple Apollo clients with different authentication semantics.

### 8.4 Maintainability issues

- The map and submission components each exceed 1,000 lines.
- Authentication, GraphQL, storage, submission, and moderation logic are concentrated in large modules.
- Backend settings duplicate staging and production branches and call `quit()` for unrecognized environments (`smokemap-django-backend/smokemap/settings.py:456-458`).
- Next.js is 13.5.4 while `eslint-config-next` is 14.x (`smokemap-webapp/package.json:52`, `package.json:90`).
- React Strict Mode is disabled (`smokemap-webapp/next.config.js:41`).
- GraphQL code generation hardcodes localhost (`smokemap-webapp/codegen.ts:3-6`).
- Production requirements, development requirements, and Pipfile disagree.
- Backend documentation remains primarily a Vercel starter template.
- The frontend has no tests; backend tests cover only `CustomUserManager`.
- No CI workflows, dependency automation, production metrics, tracing, or error aggregation were found.
- The frontend working tree was dirty during assessment. The backend branch was 25 commits ahead and 43 behind its remote tracking branch.

### 8.5 Product decisions requiring clarification

1. May guests submit, or must submissions belong to an account?
2. Are images mandatory?
3. What exact permissions distinguish user, moderator, and administrator?
4. May moderators edit a submission before approval?
5. Is rejection reversible, and how long must rejected submissions be retained?
6. Can different places share the same name?
7. Are corrections to existing places represented as submissions?
8. Should users select coordinates, enter addresses, or use both?
9. What viewport size, feature count, language coverage, and search relevance are expected?
10. Are images public immediately or only after approval?
11. What audit and privacy policy applies to user identity, IP addresses, moderators, and deleted content?
12. Are external clients relying on GraphQL, or is the webapp the only consumer?

## 9. Local development, testing, deployment, and operations

### 9.1 Verification performed

- Frontend TypeScript passed `tsc --noEmit --incremental false`.
- Inspected Python files parsed successfully as Python syntax.
- No migrations, database tests, live requests, builds, or external audits were run.
- No assessment-time files were changed before this report was requested.

### 9.2 Local development

The root Compose file runs PostGIS and a database client only. The backend service is commented out and the frontend is absent (`docker-compose.yaml:3-58`). There is no documented complete-stack command or storage emulator.

The frontend README contains only minimal startup guidance. The backend README remains largely the original Vercel Django example.

### 9.3 Testing and CI

- No frontend tests were found.
- Backend tests cover only user-manager creation (`smokemap-django-backend/backend/tests.py:4-40`).
- No permission, viewport, spatial, submission, upload, moderation, rollback, concurrency, or end-to-end tests were found.
- No CI workflow exists.
- The frontend `test` command uses watch mode, which is unsuitable as the only CI test command (`smokemap-webapp/package.json:5-12`).

### 9.4 Deployment

- The frontend Dockerfile has no startup command (`smokemap-webapp/Dockerfile:1-13`).
- The backend Dockerfile points `PATH` at a nonexistent `/env`, does not install production Gunicorn, and starts `smokemap.wsgi:application` even though the module exports `app` (`smokemap-django-backend/Dockerfile:11-26`, `smokemap-django-backend/smokemap/wsgi.py:14-16`).
- Backend deployment is pinned to Python 3.9 (`smokemap-django-backend/vercel.json:1-8`).
- Running `makemigrations` and `migrate` in a deployment build is non-repeatable and unsafe under concurrent releases.
- Separate deployments currently rely on manually synchronized GraphQL operations and committed generated types.

### 9.5 Observability

Observability consists mainly of debug logging and an elapsed-time response header (`smokemap-django-backend/backend/stats.py:14-32`). No correlation IDs, structured audit events, metrics, tracing, alerting, or production error aggregation were found.

Current logging is actively unsafe because authentication structures are recorded. Operational logging should be redacted by default and separated from immutable security and moderation audit events.

### 9.6 Dependency health

Exact current vulnerability status was not checked because the assessment prohibited external service access. No automated dependency audit or update workflow exists.

Visible concerns include:

- Next.js and its ESLint configuration are on different major versions.
- Apollo Next.js support packages are experimental or release-candidate versions.
- Python 3.9 and Django 4.2-era deployment configuration require an explicit supported-version decision.
- Backend dependency manifests disagree, and Gunicorn appears only in `requirements-dev.txt`.
- Argon2 is configured as the primary password hasher without a declared production dependency.
- The npm `crypto` compatibility package and Node `path`/`crypto` imports appear inside a client component, creating a probable build portability issue that was not tested with a production build.

## 10. Recommended target architecture

### 10.1 Backend boundaries

```text
accounts/
  users, roles, sessions, permission policies

places/
  authoritative public places, spatial query service, search

submissions/
  proposed content, validation, lifecycle state

moderation/
  atomic transitions, row locking, audit events

media/
  upload intents, object verification, attachment, cleanup

api/v1/
  REST/OpenAPI and bounded GeoJSON contracts
```

Recommended domain behavior:

- `Place` is the approved public entity with an authoritative point geometry.
- `Submission` is a durable proposal linked to its submitter and eventual place.
- States include pending, approved, rejected, and withdrawn.
- Moderator and submitter are user foreign keys where accounts are required.
- Approval runs in one `transaction.atomic()` service with `select_for_update()`.
- Moderation events are immutable.
- Geocoding is an explicit service or job, never model `save()` behavior.
- Media records store object keys, ownership, expected type/size, and verification state.

### 10.2 Frontend boundaries

```text
src/
  app/
  features/
    auth/
    map/
    places/
    submissions/
    moderation/
    media/
  shared/
    api/
    components/
    configuration/
    logging/
```

Protected requests should use one path. Given the current separate-origin deployment, a Next.js backend-for-frontend is a reasonable option: keep refresh credentials in a server-only encrypted session and send protected backend requests from the server. Browser sessions must contain profile and role information only, never backend tokens.

Public map reads may remain direct if their API is intentionally public, bounded, and separately rate-limited.

## 11. Repository strategy

Keep the repositories separate during stabilization and staged migration.

A monorepo would not fix authorization, transaction boundaries, upload ownership, or observability. Immediate contract problems can be addressed through:

- A versioned API schema artifact.
- Consumer-contract checks in both repositories.
- Root workspace orchestration for local development.
- Cross-repository integration CI.
- Explicit compatibility and deployment sequencing rules.

A monorepo becomes worthwhile if the same team routinely changes both applications together and needs atomic contract changes, one integration pipeline, and shared release tooling. Independent deployment can still be preserved through path-filtered pipelines, but repository migration should not precede security and domain work.

## 12. Prioritized roadmap

### P0 — Contain active risks

- Rotate every credential referenced by tracked production environment files.
- Remove those files and tracked logs from the current tree and Git history.
- Convert public `PlaceViewSet` to read-only.
- Disable or protect moderation, presigning, and image mutations until permission tests exist.
- Redact tokens, credentials, sessions, and authorization headers from all logs.
- Stop returning refresh tokens in the NextAuth session.

Verification:

- Anonymous API tests prove all writes are denied.
- Repository secret scanning is clean.
- Routine logs contain no token material.

### P1 — Establish an engineering baseline

- Document one supported local startup path.
- Add deterministic frontend and backend lint, type, test, and build commands.
- Add CI for both repositories.
- Align supported runtimes and dependency manifests.
- Validate required environment variables at startup.
- Add `/health/live` and `/health/ready`.
- Define and approve the permission matrix and submission lifecycle.

Verification:

- A fresh environment starts without undocumented steps.
- CI is green from clean checkouts.

### P2 — Build the read-only map vertical slice

- Add `/api/v1/places?bbox=&zoom=&categories=`.
- Validate coordinate order, ranges, viewport size, and result caps.
- Query authoritative place geometry through PostGIS.
- Add PostGIS integration and query-count tests.
- Refetch on map movement with debounce, cancellation, and stale-response protection.
- Distinguish loading, empty, error, and success states.

Verification:

- An automated test pans between disjoint regions and proves only the newest region is rendered.

### P3 — Rebuild authentication and roles

- Keep refresh credentials server-side only.
- Use one protected-request path.
- Derive permissions exclusively from backend users, groups, and permissions.
- Implement guest, user, moderator, and administrator tests.
- Revoke refresh credentials on sign-out and security events.
- Add login and mutation throttling.

Verification:

- A permission-matrix integration suite exercises every role against every protected operation.

### P4 — Introduce the submission domain

- Add explicit submission states and user attribution.
- Separate proposed data from approved places.
- Add API and database validation.
- Move geocoding out of model persistence.
- Preserve rejected and approved history.

Verification:

- Only documented state transitions succeed, and invalid transitions leave data unchanged.

### P5 — Rebuild media upload

- Create one upload-intent record per file.
- Issue one presigned request per exact object key.
- Constrain MIME type and content length.
- Verify object existence, size, and type before attachment.
- Await all upload and record operations.
- Add idempotency, retries, and orphan cleanup.

Verification:

- Tests cover zero files, multiple files, upload failure, retry, abandonment, invalid MIME, excessive size, and cleanup.

### P6 — Implement transactional moderation

- Run approval in one atomic application service.
- Lock the submission during transition.
- Record the authenticated moderator and immutable event.
- Make rejection distinct from deletion.
- Define concurrency and recovery behavior.

Verification:

- Injected failures at every step roll back all changes.
- Simultaneous approvals produce one result and one audit event.

### P7 — Improve search and retire legacy paths

- Add bounded, indexed search with explicit case and language behavior.
- Add debounce and cancellation in the frontend.
- Migrate details, submissions, media, and moderation to `/api/v1`.
- Remove the denormalized `Location` model after parity is proven.
- Retire legacy GraphQL mutations and reassess whether any read-only GraphQL surface remains justified.

Verification:

- Contract and end-to-end tests pass with legacy endpoints disabled.

## 13. Assessment limitations

- No live services, databases, storage buckets, or external providers were contacted.
- Secret values were not displayed or intentionally inspected.
- No dependencies were installed.
- No migrations were generated or run.
- No production build was run because it would create build artifacts.
- Static evidence was used to infer database and runtime behavior where noted.
- Exact third-party vulnerability and support status was not externally verified.

This report describes the current checkout, including uncommitted frontend changes. It should be updated as each roadmap milestone changes the evidence or closes a finding.
