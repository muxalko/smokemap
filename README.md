# Smokemap workspace

This repository is the reproducible local-development and integration root for Smokemap. The frontend and backend remain independently deployed repositories and are pinned here as Git submodules at a pair of revisions verified to work together.

## Clone and initialize

```sh
git clone --recurse-submodules https://github.com/muxalko/smokemap.git
cd smokemap
make init
make dev-detached
```

For an existing clone, use `make sync` to restore the revisions recorded by the superproject. A normal submodule checkout may use a detached `HEAD`; switch the relevant submodule to `development` before starting application work.

## Repository boundaries

- `smokemap-webapp/` owns the Next.js frontend and deploys independently.
- `smokemap-django-backend/` owns the Django API and deploys independently.
- This root owns Docker Compose, safe local configuration examples, shared commands, architecture documentation and the tested application revision pair.

Application changes follow their own issue, branch and pull-request workflow. After an application PR is merged and verified, update the corresponding submodule pointer in a separate root pull request.

Pull requests and pushes to `development` initialize the pinned submodules,
validate the Docker Compose configuration and media wiring, and scan the full
workspace history with Gitleaks. Secret-scan findings are redacted from CI
output.

## Local submission media

MinIO keeps the legacy `${MINIO_BUCKET:-smokemap-images}` bucket anonymously
downloadable for existing public image paths. M3 source media uses the distinct
`${MINIO_PRIVATE_MEDIA_BUCKET:-smokemap-media-private}` bucket, whose anonymous
policy is reset to private whenever `storage-init` runs. The backend uses
`http://storage:9000` for private object operations and signs browser uploads
against `http://localhost:${MINIO_API_PORT:-9000}`.

The `media-cleanup` service waits for a healthy backend and periodically runs
the backend's durable cleanup command. `MEDIA_CLEANUP_BATCH_SIZE` (default
`100`) controls each batch and `MEDIA_CLEANUP_INTERVAL_SECONDS` (default `300`)
controls the delay between attempts. An individual command failure is logged
and retried after the interval; invalid loop configuration fails at startup.
No cleanup port is published, and the API/frontend do not depend on this
service. Use `make check-compose` to validate the bucket policies, split
endpoints, and cleanup wiring without starting the stack.

## Cross-application viewport test

Run the M2 browser pan test from the workspace root:

```sh
make test-e2e
```

The target starts an isolated `smokemap-e2e` Compose project on an internal-only
network, seeds two namespaced PostGIS fixtures, and runs the Chromium version
bundled with the pinned Puppeteer container. Chromium opens the first real
MapLibre marker, drags the map into a disjoint viewport, verifies the live
frontend-proxied GeoJSON contains only the second fixture, and opens its marker.
A root-owned blank basemap and local Next font response remove network
variability. The internal Compose network and browser request guard reject
external traffic. The target removes the fixtures and test containers whether
the browser passes or fails; the isolated named volumes are preserved for
faster subsequent runs.

## Cross-application submission and media test

Run the M3 browser submission and media test from the workspace root:

```sh
make test-e2e-submission-media
```

The target starts its own isolated `smokemap-e2e-submission-media` Compose
project on an internal-only network, provisions the same repeatable
`user-one@smokemap.local` local test account used by `make
provision-test-users`, and drives the pinned Puppeteer Chromium through the
real NextAuth credentials sign-in UI. Chromium then submits two places
through the real M3 form: one with zero images and one with two real local
image files, waiting in both cases for the on-page status banner to report a
finalized `pending` submission rather than assuming success once the dialog
closes. The second submission's images are hashed in-browser, uploaded
directly to the private MinIO bucket with a real presigned POST issued by the
backend, verified, and attached — end to end through the same GraphQL
mutations the production form uses, with no mocked GraphQL, media or storage
path. Because this internal network has no published host ports, the E2E
Compose overlay signs uploads against the `storage:9000` Compose service
address instead of the host-published MinIO port, and points `NEXTAUTH_URL`
at the `frontend:3000` service address instead of `localhost`; both still
exercise the same backend code paths a browser on the host would.

After the browser run, the target execs into the backend container to verify
backend and storage truth directly: both submissions belong to the signed-in
owner and are `pending`; the zero-image submission has no attachments or
leftover media intents; the multi-image submission has exactly two ordered,
`attached` managed images with distinct server-verified SHA-256 digests, no
non-terminal media intents, and no idempotency-row duplication; each attached
image's sealed object exists in the private managed-media bucket at its exact
recorded key and returns an anonymous-access error rather than its bytes; and
each image's original (unsealed) upload object was already cleaned up by
verification. The target seeds no fixtures ahead of time — it removes any
prior run's same-named submissions, media, and MinIO objects before and after
every run (regardless of outcome), so reruns never accumulate data. A failure
at any step — sign-in, upload, verification, finalization, or the backend/
storage checks — fails the target closed; nothing downstream is skipped or
treated as a soft warning.

## Local test accounts

With the stack running, provision the repeatable login and moderation cohort:

```sh
make provision-test-users
```

This creates or updates one administrator (`admin@smokemap.local`) and two
regular users (`user-one@smokemap.local` and `user-two@smokemap.local`). They
use the documented local-only fallback password
`Smokemap-local-test-only-2026!`. To replace it without adding the value to the
command line or its output, set `SMOKEMAP_LOCAL_TEST_PASSWORD` in your shell
before running the Make target.

Sign in at `http://localhost:3000/api/auth/signin`. Submit a zero-image request
as either regular user, then sign in as the administrator and review it at
`http://localhost:3000/requests`. The command is idempotent, never prints the
password, and refuses to run outside Django debug mode.

Planning and evidence:

- [Pre-milestone audit](docs/PRE_MILESTONE_AUDIT.md)
- [Execution roadmap](docs/ROADMAP.md)
- [M1 security and authorization contract](docs/M1_SECURITY_POLICY.md)
- [M1 exit evidence](docs/M1_EXIT_EVIDENCE.md)
- [Historical architecture assessment](docs/ARCHITECTURE_ASSESSMENT.md)

See [AGENTS.md](AGENTS.md) for the complete development, security and
verification rules.
