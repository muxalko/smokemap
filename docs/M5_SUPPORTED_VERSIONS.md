# M5 supported-version baseline

Status: Adopted target for M5 implementation

Decision date: 2026-10-08

Source review date: 2026-10-08

Scope: Node.js, Next.js, Python, Django, PostgreSQL, and PostGIS only. This
document selects targets and an upgrade order; it does not perform an upgrade
or change a manifest, lockfile, image, workflow, deployment, or database.

## Decision

Smokemap will converge on these production-supported version lines:

| Component | Selected target | Patch policy | Why this target |
| --- | --- | --- | --- |
| Node.js | 24 LTS | Use the latest supported 24.x patch and pin the production image by immutable digest | It is the current production-ready LTS line, is supported by Next.js 16, and has a longer runway than Node.js 22. |
| Next.js | 16.x | Use the latest supported 16.x release and regenerate the lockfile in the frontend repository | It is Active LTS; 15.x is already in Maintenance LTS and 13.x is unsupported. |
| Python | 3.14 | Use the latest 3.14 micro release and pin the production image by immutable digest | It is in bugfix support, is supported by Django 5.2 from 5.2.8 onward, and aligns the runtime horizon beyond Django 5.2's support window. |
| Django | 5.2 LTS | Use the latest 5.2.x patch, never the initial 5.2.0 release | It is the supported LTS destination with extended support through April 2028 and is a smaller, longer-supported step than a non-LTS feature release. |
| PostgreSQL | 17 | Stay on major 17, apply the current 17.x minor promptly, and pin the production image by immutable digest | Major 17 remains supported through November 2029. Retaining the major avoids an unrelated data-format migration while M5 establishes controlled migration and recovery. |
| PostGIS | 3.6 | Use the latest 3.6.x patch paired with PostgreSQL 17 and pin the production image by immutable digest | 3.6 is the current stable line and the official compatibility matrix marks the PostgreSQL 17 pairing as supported. |

These are version-line decisions, not permission to use floating production
artifacts. Implementation issues must record exact patches and image digests,
and must update them within the selected line without waiting for another
architecture decision. A new major or minor-line decision requires a fresh
compatibility and lifecycle review.

## Observed baseline at the M5 entry revision

The observations below come from root `0750a15e70999d6ea5d3cb8b7e8d3f65ef96e943`
with backend `d9ddb016fd0fd6cff893f1d70dcb067574bedafc` and frontend
`d46626891ca8ec780a554b4fadd7b2515a8c7e5a`. They describe committed file
evidence, not versions inferred from a developer's host or an unrelated
running container.

| Component | Observed declaration | File evidence | Precision and authority |
| --- | --- | --- | --- |
| Node.js | `node:22-bookworm-slim` | `smokemap-webapp/Dockerfile` | The canonical Compose frontend builds this Dockerfile. The tag selects major 22 but does not make the resolved patch or image digest immutable. |
| Next.js | `13.5.4` | `smokemap-webapp/package.json`; exact `next@13.5.4` entry in `smokemap-webapp/yarn.lock` | Exact direct dependency and lock resolution. |
| Python | `python:3.12-slim-bookworm` | `smokemap-django-backend/Dockerfile` | The canonical Compose backend builds this Dockerfile. The tag selects minor 3.12 but does not make the resolved micro release or image digest immutable. |
| Django | `django==4.2.22` | `smokemap-django-backend/requirements.txt` | This is the production dependency input copied and installed by the Dockerfile. `requirements-dev.txt` agrees on 4.2.22, while the stale `Pipfile.lock` records 4.2.10. |
| PostgreSQL | `postgis/postgis:17-3.5` | root `docker-compose.yaml` | The image tag selects PostgreSQL 17 but not an immutable 17.x patch or digest. |
| PostGIS | `postgis/postgis:17-3.5` | root `docker-compose.yaml` | The image tag selects PostGIS 3.5 but not an immutable 3.5.x patch or digest. |

The backend also retains non-canonical Python 3.9 declarations in `Pipfile`
and `vercel.json`. They do not define the verified Compose runtime, but they
are manifest divergence that must be removed or reconciled before a production
deployment contract can be claimed.

## Lifecycle evidence and current-target gaps

All lifecycle statements were checked against official upstream sources on
2026-10-08. Dates are upstream dates; where an upstream policy is intentionally
approximate, this document does not invent an exact deadline.

| Component | Current lifecycle | Target lifecycle | Gap and decision |
| --- | --- | --- | --- |
| Node.js | 22 is in Maintenance LTS and reaches EOL on 2027-04-30. | 24 is in Active LTS until its scheduled Maintenance transition on 2026-10-20 and reaches EOL on 2028-04-30. | Upgrade 22 to 24 after the Next.js migration passes on Node.js 22. Do not target the non-LTS Node.js 26 Current line. |
| Next.js | 13.x is explicitly unsupported. | 16.x is Active LTS. Under the published policy it becomes Maintenance LTS when the next major ships and remains in maintenance for two years after its 2025-10-21 initial release, through 2027-10-21. | This is the urgent frontend support gap. Cross each intervening major and its documented breaking changes rather than treating 13 to 16 as a blind lockfile update. |
| Python | 3.12 is in security-only support and reaches EOL in 2028-10. | 3.14 is in bugfix support and reaches EOL in 2030-10. | Python 3.12 remains a supported bridge for the Django upgrade. Move to 3.14 only after binary and GeoDjango dependencies are proven on the new Django line. Python 3.15 was still prerelease on the review date and is not a production target. |
| Django | 4.2 LTS ended extended support on 2026-04-07; pinned 4.2.22 is also behind the final 4.2.30 patch. | 5.2 LTS ended mainstream support on 2025-12-03 and receives extended security/data-loss support through April 2028. | This is the urgent backend support gap. 5.2 has a longer published support window than current non-LTS feature releases and supports Python 3.14 from 5.2.8. Reassess Django 6.2 LTS only after its planned April 2027 stable release. |
| PostgreSQL | Major 17 is supported; upstream lists 17.11 as current on the review date and final support on 2029-11-08. The floating image tag does not prove which minor is deployed. | Major 17 at the current minor, with the exact image digest recorded. | No major-version gap. Patch freshness and artifact immutability are gaps. PostgreSQL recommends always running the current minor. |
| PostGIS | 3.5 is still shown as a stable line and works with PostgreSQL 17. It was released on 2024-09-26; the project strives to support a minor for 2-4 years, so its non-binding window is approximately September 2026 through September 2028. | 3.6 is the current stable line, works with PostgreSQL 17, and was released on 2025-09-02; applying the same policy gives an approximate, non-binding window of September 2027 through September 2029. | Move one PostGIS minor without changing the PostgreSQL major. Exact EOL is not promised by upstream, so recheck the compatibility and EOL pages before implementation and every quarter. |

Official sources:

- Node.js [Release Working Group schedule](https://github.com/nodejs/release#release-schedule)
  and [release-status guidance](https://nodejs.org/en/about/previous-releases),
  reviewed 2026-10-08.
- Next.js [support policy and supported-version table](https://nextjs.org/support-policy),
  reviewed 2026-10-08; its 16.x table is dated by the 2025-10-21 release.
- Python [supported-version status table](https://devguide.python.org/versions/),
  reviewed 2026-10-08; the table records first-release and EOL months for each
  branch.
- Django [supported-version and release-roadmap table](https://www.djangoproject.com/download/)
  and [Django 5.2 release notes](https://docs.djangoproject.com/en/5.2/releases/5.2/),
  reviewed 2026-10-08; the release notes are dated 2025-04-02.
- PostgreSQL [versioning policy and supported-release table](https://www.postgresql.org/support/versioning/),
  reviewed 2026-10-08; the table records first and final release dates.
- PostGIS [versioning and EOL policy](https://postgis.net/development/versions_eol/),
  [compatibility and support matrix](https://postgis.net/development/compatibility/),
  and the dated [3.5.0](https://postgis.net/2024/09/PostGIS-3.5.0/) and
  [3.6.0](https://postgis.net/2025/09/PostGIS-3.6.0/) release records, reviewed
  2026-10-08. The compatibility data identifies itself as generated on
  2026-09-26.

## Compatibility risks to retire

### Frontend

- Next.js 13 to 16 spans three major upgrade guides. Next.js 16 requires
  Node.js 20.9 or newer, React 19.2-era compatibility, asynchronous request
  APIs, and migration away from the removed `next lint` command. Its default
  Turbopack build can expose assumptions hidden by the existing webpack path.
- The current `eslint-config-next` 14.x already disagrees with Next.js 13.5.4.
  Framework, React, types, ESLint integration, and Apollo/NextAuth adapters
  must be upgraded as one tested frontend dependency graph, not independently.
- The historical assessment found Node `crypto` and `path` use reachable from
  client code. Next.js 16 explicitly expects native Node modules to stay out of
  browser bundles; this must be resolved rather than masked with a bundler
  fallback.
- The Yarn classic lock strategy and package-manager provisioning are not
  declared independently of the Node image. M5 manifest consolidation must
  make the package manager and lockfile authority explicit before changing the
  runtime image.

### Backend

- Django 4.2 to 5.2 crosses the 5.0, 5.1, and 5.2 deprecation and
  backwards-compatibility boundaries. Django recommends reading and testing
  every intervening final release and resolving deprecation warnings before
  each step.
- Graphene, GraphQL JWT, DRF/GIS, CORS, storage, Pillow, psycopg, and
  authentication packages must each prove Django 5.2 and Python 3.14 support.
  The present production, development, and Pipenv dependency sets disagree.
- Python 3.14 can expose unavailable wheels or C-extension build failures in
  Pillow, psycopg2, GDAL/GEOS/PROJ integration, and transitive cryptography
  packages. Keep Python 3.12 while establishing Django 5.2 compatibility, then
  move the runtime in a separate backend issue.
- Django 5.2 supports PostgreSQL 14 and newer, but its documentation recommends
  current psycopg and notes that psycopg2 is likely to be deprecated later.
  Driver migration must be explicit and tested; it is not implied by this
  target selection.

### Database and spatial extension

- The current database tag floats both PostgreSQL and PostGIS patches. A
  deployment can therefore change without a source commit. Production and
  recovery evidence must name immutable image digests and the database's
  reported `server_version` and `postgis_full_version()`.
- PostGIS 3.5 to 3.6 requires a controlled extension upgrade and spatial
  regression checks. Exercise viewport predicates, distance-based duplicate
  checks, search plans, indexes, dumps, restores, and rollback before adopting
  the image.
- PostgreSQL remains on major 17. A later move to 18 is a separate data upgrade
  requiring `pg_upgrade` or dump/restore evidence; it is not bundled into a
  framework-support task.
- The M5 backup/recovery rehearsal must prove that a PostgreSQL 17 backup with
  the selected PostGIS extension can be restored into the exact target
  artifacts before any production declaration.

## Upgrade sequence and acceptance boundaries

Each numbered step is independently reviewable and must land in its owning
repository. Application changes merge there first; root gitlinks update only
after the merged commit is available from the application remote.

1. **Make dependency authority explicit.** Reconcile the backend production,
   development, and Pipenv declarations; declare the frontend package manager
   and lockfile policy; record exact current image digests and runtime patch
   versions. Preserve the working Compose baseline while doing so.
2. **Upgrade Next.js incrementally on Node.js 22.** Use the latest patch in
   each intervening major, moving 13 to 14, 14 to 15, and 15 to 16. At every
   step align React, types, ESLint, NextAuth, Apollo integration, middleware,
   request APIs, browser/server module boundaries, compilation, startup,
   frontend tests, and root browser workflows. Node.js 22 remains a supported
   bridge until 2027-04-30.
3. **Move the frontend runtime to Node.js 24.** After Next.js 16 is green on
   Node.js 22, change the runtime and package-manager provisioning, regenerate
   only the authoritative lockfile if required, and repeat clean build,
   startup, tests, and root E2E checks.
4. **Upgrade Django incrementally on Python 3.12.** First use the final 4.2
   patch as a migration bridge, eliminate project deprecation warnings, then
   test the latest patches of 5.0, 5.1, and finally 5.2. Run schema checks,
   authorization, lifecycle, storage, race, spatial, and root integration
   gates at each compatibility boundary. Do not mix schema redesign into these
   dependency changes.
5. **Move the backend runtime to Python 3.14.** Upgrade or replace unsupported
   dependencies, prove wheels/native libraries in clean container builds, and
   repeat backend plus cross-application checks. The accepted Django version
   must be 5.2.8 or newer because that is where official Python 3.14 support
   begins.
6. **Patch PostgreSQL 17 and upgrade PostGIS to 3.6.** Capture a restorable
   backup, pin exact target artifacts, rehearse the extension upgrade against
   restored data, verify reported versions and natural spatial query plans,
   and prove rollback. Keep the PostgreSQL major unchanged.
7. **Re-run the release baseline.** From clean checkouts, prove all repository
   required checks, root integration and browser workflows, secret scanning,
   controlled migrations, backup/restore, staging promotion, and rollback.
   Record immutable application commits, image digests, and schema/extension
   versions in M5 exit evidence.

No selected target is accepted merely because its container starts. The
product-critical workflows, backend authorization boundary, private/public
media contract, spatial plans, and recovery path must remain demonstrated.

## Maintenance policy

- Review these six upstream lifecycle sources at least quarterly and whenever
  an upstream announces a security release, support-policy change, or new LTS.
- Open replacement-target work no later than 12 months before a selected
  line's EOL, and complete it no later than 90 days before EOL.
- Apply supported patch releases promptly through focused repository issues
  and clean lock/image regeneration; never retain a vulnerable patch merely
  because its major or minor line remains supported.
- Reassess Django 6.2 LTS after its stable release, Next.js when 16 leaves
  Active LTS, Node.js 24 before 2027-04-30, PostgreSQL 17 before 2028-11-08,
  and PostGIS 3.6 quarterly because its EOL window is guidance rather than a
  fixed promise.
- Treat a missing exact patch, digest, database-reported version, or recovery
  result as unknown evidence, not as a pass.
