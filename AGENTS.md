# Smokemap development guide

This repository is the Smokemap workspace superproject. It contains shared local-development orchestration and pins two independently deployed Git repositories as submodules. Read this file before changing either application. Then initialize the submodules and read the repository documentation and the architecture/roadmap documents in `docs/`.

## Repositories and ownership

- `smokemap-webapp/`: independently deployed frontend submodule using Next.js 13, TypeScript, Apollo/GraphQL, NextAuth, MapLibre, Tailwind and the moderation UI.
- `smokemap-django-backend/`: independently deployed backend submodule using Django 4.2, Django REST Framework, Graphene GraphQL, PostGIS, JWT authentication and S3-compatible upload orchestration.
- Workspace root: the superproject containing Docker Compose, safe example configuration, common commands, cross-repository documentation and the exact tested application revisions. It is not an application deployment unit.

The application repositories deploy independently. Preserve that boundary unless a deliberate architecture decision changes it. A submodule pointer records an integration baseline; it does not combine application histories or deployments. The backend is the authoritative authorization boundary; frontend checks improve UX but never replace backend permission checks. S3-compatible object storage holds submitted images, while Django owns image metadata.

## Product-critical workflows

- Browse and retrieve places by current map viewport.
- Search for places and open place details.
- Authenticate and refresh JWTs without exposing tokens.
- Submit a place with tags and zero or more images.
- Obtain presigned upload data, upload image bytes and create image records.
- Review, approve and delete submissions.
- Enforce guest, user, moderator and administrator permissions on the backend.

See `docs/ARCHITECTURE_ASSESSMENT.md` for evidence and `docs/ROADMAP.md` for the ordered remediation plan. A healthy local stack does not mean the known product, authorization, token-handling, upload or viewport defects are resolved.

## Verified local architecture

Docker Compose is the canonical development environment. Host Node and Python installations are not required.

| Service | Container address | Host address | Notes |
| --- | --- | --- | --- |
| Frontend | `http://frontend:3000` | `http://localhost:3000` | Next.js development server and hot reload |
| Backend | `http://backend:8000` | `http://localhost:8000` | Django development server; runs migrations before startup |
| GraphQL | `http://backend:8000/graphql/` | `http://localhost:8000/graphql/` | Schema/codegen uses the container address |
| GeoJSON REST | `http://backend:8000/locations/` | `http://localhost:8000/locations/` | Supports `in_bbox=minx,miny,maxx,maxy` |
| PostgreSQL/PostGIS | `db:5432` | `localhost:5432` | Persistent named volume; application schema is `smokemap` |
| MinIO API | `http://storage:9000` | `http://localhost:9000` | Local S3-compatible storage |
| MinIO console | n/a | `http://localhost:9001` | Local inspection UI |

Health endpoints:

- Liveness: `http://localhost:8000/health/live/`
- Readiness, including database access: `http://localhost:8000/health/ready/`

Compose waits for PostGIS and MinIO health, creates the image bucket, runs migrations, waits for backend readiness, and only then starts the frontend. Ports bind to `127.0.0.1` and are not exposed on the LAN.

The stack was verified with Docker Engine 28.1.1, Compose v2.35.1, Python 3.12 and Node 22. These container runtimes make development reproducible; they do not make the legacy Django 4.2 or Next.js 13 application dependencies a supported long-term baseline. Framework selection and upgrades remain an explicit roadmap milestone.

The host Docker daemon currently uses `/data/docker-data` with `overlay2`; confirm with:

```sh
docker info --format 'Root={{.DockerRootDir}} Driver={{.Driver}}'
```

Do not delete the previous `/var/lib/docker` backup until the Docker data-root migration has been independently verified and intentionally retired.

## Configuration and secrets

`docker-compose.yaml` contains safe development fallbacks. `.env.example` documents every supported local override. Existing `.env` files may contain private values: never print, copy into logs, commit or replace them casually.

For a new machine, only create a local `.env` when overrides are needed:

```sh
cp .env.example .env
```

Browser API reads use same-origin paths (`/api/smokemap/graphql` and `/api/smokemap/locations`) which Next.js proxies to `BACKEND_INTERNAL_URL`. This works whether the browser reaches the frontend directly, through a tunnel or through a development proxy. Next.js server code uses Compose service names via `BACKEND_INTERNAL_URL` and `GRAPHQL_INTERNAL_ENDPOINT`; never use browser `localhost` URLs from inside a container. The backend signs local MinIO uploads with the browser-reachable endpoint.

The backend accepts both `http://localhost:<frontend-port>` and `http://127.0.0.1:<frontend-port>` as local CORS/CSRF origins. Compose derives these origins from `FRONTEND_PORT`; keep the Django origin configuration aligned if another browser hostname is introduced.

All example credentials and secrets are local-only. Production must use independent secret management, TLS and non-default credentials. Never log access tokens, refresh tokens, sessions, authorization headers, presigned form fields or secret-bearing environment objects.

## Schema and provisional reference data

This is a pre-production schema baseline. The former five backend prototype migrations were collapsed into `backend/migrations/0001_initial.py`. A database carrying the former backend migration history is incompatible with this baseline and must be deliberately migrated or rebuilt; never fake migration state on a database containing useful data.

A fresh database provisions these provisional physical-setting categories in the initial migration:

- Indoors
- Outdoors
- Rooftop
- Underground
- On the water
- Underwater
- In the air
- Other

Category names are unique, and `Place` and `Request` must reference a real category instead of falling back to an invalid `-1` ID. The taxonomy is intentionally provisional. Once this baseline is shared, do not edit the applied initial migration to rename or replace categories; create a new schema/data migration so environments converge predictably.

The initial product state contains categories but no places. The map must still render and display `No places in this area yet.` An empty feature collection is a successful API result, not a loading condition.

## Daily commands

Run commands from this workspace root.

```sh
# Initialize a fresh clone at the exact revisions pinned by this superproject
make init

# Reapply .gitmodules URLs and restore the pinned application revisions
make sync

# Inspect the superproject and pinned submodule revisions
make status

# Build, start in the background and wait for health checks
make dev-detached

# Or run attached and follow all service output
make dev

# Inspect status or application logs
make ps
make logs

# Stop while preserving containers and data
make stop

# Remove containers/network while preserving named volumes
make down
```

Source directories are bind-mounted for hot reload. Rebuild images after changing `Dockerfile`, `requirements.txt`, `package.json` or `yarn.lock`:

```sh
make dev-build
docker compose up --detach --wait
```

Named volumes preserve PostgreSQL, MinIO data, frontend dependencies and the Next.js cache. Removing volumes is destructive and requires explicit confirmation of the exact target; never add `--volumes` reflexively.

## Quality gates

The stack must be running before these commands:

```sh
# Django system check, TypeScript and ESLint
make check

# Backend tests plus the frontend CI test command
make test

# Recreate the isolated backend test database from zero
make test-backend-fresh

# Apply pending development migrations
make migrate

# Regenerate GraphQL client types from the running backend
make codegen
```

Backend tests deliberately override `POSTGRES_OPTIONS` to use the isolated test database's `public` schema. Normal development continues to use the `smokemap` schema. Tests use `--keepdb` for fast repeat runs and apply new migrations automatically.

Current verified baseline:

- Django system check passes.
- Seven backend tests pass, including initial category provisioning and local workflow coverage.
- Frontend TypeScript checking passes.
- ESLint passes with known warnings documented in the architecture assessment.
- The frontend test command passes but reports no tests; adding meaningful tests is roadmap work, not evidence of coverage today.

Code generation is explicit, not a `dev` precondition. This lets the frontend start reliably while still making schema drift a deliberate, reviewable change. Generated output must be inspected before committing.

## Smoke-test checklist

After infrastructure or dependency changes, verify all of the following:

1. `docker compose config --quiet` succeeds.
2. `make dev-detached` exits successfully.
3. `make ps` shows `db`, `storage`, `backend` and `frontend` healthy; `storage-init` must exit `0`.
4. Frontend `/`, backend live/readiness, GraphQL `{ __typename }` and a bounded `/locations/?in_bbox=...` request return HTTP 200.
5. Django reports the `smokemap` schema and a PostGIS version.
6. `make check` and `make test` pass.
7. After migration changes, `make test-backend-fresh` proves the schema from an empty test database.

When a sandbox cannot access host-published ports, test from inside the relevant container rather than interpreting host networking isolation as an application failure.

## Engineering workflow

Use a lightweight issue → branch → commit → pull request → squash-merge workflow in the superproject and each application repository. Superproject changes are limited to orchestration, shared documentation and tested submodule pointers; application code remains in its owning repository.

1. Read this file, both repository statuses, relevant documentation and nearby code before editing.
2. Select or create one small GitHub issue with an observable acceptance criterion. Add it to the Smokemap project, assign the appropriate milestone and priority, and move it to In Progress when work starts.
3. Start from a clean, current `development` branch. Fetch before reconciling remote history, and never discard or force-push divergent work; the pre-reconciliation backend history is preserved as `development-pre-sync-2026-08-10`.
4. Create a branch named `issue-<number>-<short-slug>`, for example `issue-49-viewport-query-contract`.
5. Preserve unrelated working-tree changes and make the smallest change that satisfies the issue. Cross-repository work uses a linked issue, branch and PR in each repository because the applications deploy independently.
6. Add or update tests at the authorization/API boundary and the relevant UI behavior. Run proportional quality gates and smoke tests before requesting merge.
7. Make focused, imperative commits. Include the issue number when it improves traceability, for example `Validate viewport bounds (#49)`.
8. Push the feature branch and open a PR targeting `development`. The PR must include `Closes #<number>`, a concise behavior summary, verification evidence and any known follow-up work.
9. Resolve every review conversation, then squash-merge the PR. GitHub deletes the remote feature branch automatically. An issue is Done only after its acceptance criteria pass and its PR is merged.
10. Update architecture, roadmap and operating documentation when behavior or decisions change.

After an application PR is merged, update its submodule pointer in a separate superproject issue, branch and PR only after the merged commit is available from the application remote. Never record a submodule commit that exists only locally. Verify pointer-only changes with `git submodule status`, `git diff --submodule=log`, `docker compose config --quiet` and proportional workspace checks.

Both application repositories protect `development`: changes require a PR, administrators follow the same rule, force pushes and branch deletion are blocked, and review conversations must be resolved. Zero approvals are required for this lightweight single-maintainer phase. Only squash merges are enabled. Required CI checks should be added when the test/CI foundation tracked in the roadmap is reliable; until then, record local command evidence in every PR.

Typical command sequence inside one application repository:

```sh
git switch development
git pull --ff-only
git switch -c issue-<number>-<short-slug>
# Make the change and run proportional checks.
git add <paths>
git commit -m "Concise imperative change (#<number>)"
git push -u origin issue-<number>-<short-slug>
gh pr create --base development --title "Concise outcome" --body "Closes #<number>"
gh pr merge --squash --delete-branch
```

Do not install host dependencies, run production migrations, contact external storage/services or use production secrets for ordinary development. Prefer the local Compose services.

## Troubleshooting

- Codex app GitHub authentication: inside the Codex sandbox, `gh auth status` can report an `invalid` token even after successful authentication because the sandbox cannot access the host keychain or injected token environment (see [openai/codex#10695](https://github.com/openai/codex/issues/10695)). Treat this as a sandbox false negative only when an authenticated GitHub connector request succeeds and the repository's normal Git remote operation also authenticates. In that case, do not repeatedly ask the user to log in and never print or copy tokens; use local Git for branch/commit/push and the connected GitHub tools for issues and pull requests. If both the connector and Git remote authentication fail, stop and request reauthentication.
- `ENOSPC` during Docker builds: check both `df -h / /data` and `docker system df`. Do not prune unrelated images, volumes or caches without approval.
- Backend waits indefinitely: inspect `docker compose logs backend db` and call `/health/ready/` from the backend container.
- Frontend waits indefinitely: inspect `docker compose logs frontend`; the first request may trigger a development compilation.
- MinIO initialization fails: inspect `docker compose logs storage storage-init`; success means the bucket exists and anonymous download access is configured for local image display.
- Test database schema errors: use `make test`; do not run the raw backend test command without its `POSTGRES_OPTIONS` override.
- Port conflict: override only the host-side port in `.env` using `FRONTEND_PORT`, `BACKEND_PORT`, `POSTGRES_PORT`, `MINIO_API_PORT` or `MINIO_CONSOLE_PORT`.
