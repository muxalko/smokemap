# Isolated staging preparation

This directory defines a fail-closed staging topology and release-input
preflight. It is preparation only: neither validation command pulls images,
creates containers, runs migrations, changes Cloudflare, or starts services.

## Boundaries

- Every runtime is an externally published image selected by immutable
  `sha256` digest. The root workspace never builds application release images.
- The independently deployed frontend and backend repositories own their
  images. A release must record each owning commit and CI result; a root
  gitlink remains only the tested integration baseline.
- Database, application, media, and the two tunnel-ingress networks are
  internal. A separate edge network gives only `cloudflared` outbound
  connectivity, while the tunnel can reach only the frontend and storage
  services. No service publishes a host port, including PostgreSQL, the
  backend, or MinIO API. The MinIO browser console is disabled and has no
  listener for the tunnel to reach.
- The remotely managed tunnel token is file-backed and scoped to one tunnel.
  Cloudflare must route only the application hostname to `frontend:3000` and
  the distinct upload hostname to `storage:9000`. No route may target the
  backend, database, MinIO console, or host SSH. Neither route may override the
  HTTP `Host` header or rewrite the path or query: signed storage requests are
  bound to the public upload host.
- `migrate` is a separate `staging-migration` profile. It is never a backend
  startup side effect and must be run once under a controlled release step.
- Runtime services are behind the explicit `staging-runtime` profile, so the
  checked-in definition has no default startup path.

## Local-staging mode

`local/` holds a separate, root-owned mode for rehearsing this topology on the
Jenkins host before Cloudflare exists. Its overlay:

- swaps `cloudflared` for a non-root TLS edge that publishes only on `127.0.0.1`;
- serves reserved `.internal` application and media origins;
- runs locally built images by content-addressed ID.

It never changes this file's external contract. The external preflight rejects
a local configuration, and the local preflight rejects this file's environment.
`local/README.md` is its runbook.

Cloudflare recommends a remotely managed tunnel for new deployments, and its
[current run-parameter documentation][cloudflare-run-parameters] records
`--token-file` support in `cloudflared` 2025.4.0 or later. The connector in
this contract therefore reads `/run/secrets/cloudflared_token` rather than
placing the token in command arguments or environment variables. The tunnel
and its public hostname routes are external prerequisites, not resources
created by this repository.

[cloudflare-run-parameters]: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/#token-file

## Application production contracts

The Compose file targets the backend production contract merged in
smokemap-django-backend PR #116 (`05098a798961e6e1b968d78f3211a17df63d036f`)
and the frontend production image merged in smokemap-webapp PR #69
(`21b93f47ddb9614509f636c83478b8a10b8dac47`). The preflight pins these values
exactly:

| Concern | Root contract |
| --- | --- |
| Backend host validation | `DJANGO_ALLOWED_HOSTS=api.smokemap-staging.internal`, the only `Host` the frontend proxy and readiness probe send |
| Development names | Backend staging rejects `backend`, `db`, `storage`, and similar names, so backend-facing connections use the fixed private aliases `api.`, `postgis.`, and `objects.smokemap-staging.internal` |
| Trusted HTTPS proxy | `DJANGO_TRUST_X_FORWARDED_PROTO=true`. Only `frontend` and `migrate` share the backend's application network, and the frontend proxy replaces any client forwarding header with `X-Forwarded-Proto: https` |
| Readiness | `GET http://127.0.0.1:8000/health/ready/` with the allowed `Host` and `X-Forwarded-Proto: https`, because staging redirects plain HTTP and rejects unknown hosts |
| Database TLS | `POSTGRES_SSLMODE=verify-full` with `PGSSLROOTCERT=/run/secrets/postgres_tls_ca` for `backend`, `migrate`, and `media-cleanup` |
| Storage endpoints | Private I/O uses `http://objects.smokemap-staging.internal:9000` on the internal media network; browser-signed operations and the legacy binding use `STAGING_MEDIA_URL` |
| Web server | Gunicorn flags match the backend image `CMD` |
| Frontend backend origin | `BACKEND_INTERNAL_URL=http://api.smokemap-staging.internal:8000` and `GRAPHQL_INTERNAL_ENDPOINT=http://api.smokemap-staging.internal:8000/graphql/` |
| Frontend public values | `staging`, the fixed `/api/smokemap` paths, `STAGING_APP_URL`, `NEXT_PUBLIC_MAP_STYLE`, `LOG_LEVEL`, and `RELEASE_VERSION` |

The frontend replaces `NEXT_PUBLIC_*` values at build time, and its startup
fails if a runtime value differs from `production-build.json`. The frontend
image for a release must therefore be built with exactly the staging
environment file's `STAGING_APP_URL`, `NEXT_PUBLIC_MAP_STYLE`, and `LOG_LEVEL`,
and with `NEXT_PUBLIC_VERSION` and `VCS_REF` equal to `RELEASE_VERSION`: the
full lowercase frontend source commit. The preflight enforces each value's
format and the equality between frontend and backend origins. It cannot read
the manifest inside an unpulled image, so the release manifest below must
record that equality.

The frontend's `docs/PRODUCTION_IMAGE.md` still names `http://backend:8000`.
Its validator accepts the `.internal` alias above, so no frontend change is
required.

## Database TLS

PostGIS serves TLS from three file-backed secrets: `postgres_tls_ca`, the
trust anchor mounted only by backend jobs; `postgres_tls_certificate`; and
`postgres_tls_private_key`, which only `db` mounts. PostgreSQL refuses a key
that its own user or root does not own, and the image entrypoint drops the
supplemental secret group. The `db` command therefore copies the pair into
the memory-backed `/run/postgresql-tls` with owner-only modes, then starts the
standard entrypoint with `ssl=on`.

The certificate must name `postgis.smokemap-staging.internal` in its subject
alternative names and chain to `postgres_tls_ca`. The private key must be
unencrypted. Release preflight verifies all of this with local `openssl`,
including current validity and certificate-key agreement, without printing key
material. Provision these from a staging-only authority; never reuse local, CI,
or production certificates.

The backend enforces TLS on the client side, which covers every current
database client. The server still accepts plaintext TCP from the internal
database network. A reviewed `pg_hba.conf` that accepts only `hostssl`
connections is a recorded follow-up; it is not part of this contract.

## Upload hostname contract

The upload hostname (`STAGING_MEDIA_URL`) is the browser-facing MinIO API. It
carries two backend-signed flows from the approved M3/M4 media contract, both
issued against `MEDIA_UPLOAD_ENDPOINT_URL`:

- **Presigned POST upload:** short-lived and bound to one exact private key,
  one content type, and a bounded length range.
- **Signed GET preview:** a short-lived, backend-authorized read of one
  private source object, as `docs/M3_SUBMISSION_MEDIA_POLICY.md` section 7
  requires. It is not a public URL.

The legacy bucket named by `MINIO_BUCKET` keeps its existing
anonymous object reads through the same API listener. Storage initialization
replaces the canned `download` policy with an explicit `s3:GetObject` grant
on public-bucket objects only. Anonymous bucket listing and writes are denied;
the authenticated application identity has a separate policy. The private
bucket stays anonymous-private, and the application storage identity cannot
delete or overwrite the legacy bucket.

Any Cloudflare Access policy chosen for the upload hostname must still let
these browser flows through, including the POST's CORS preflight. Run the
following tests through the real tunnel with that policy applied before the
launch is accepted:

1. `OPTIONS` with `Origin: STAGING_APP_URL` and
   `Access-Control-Request-Method: POST` returns
   `Access-Control-Allow-Origin` equal to that exact origin. The same request
   from any other origin receives no allow-origin header.
2. A backend-issued presigned POST succeeds from the application origin.
   Each of the following is rejected with an S3 error response and writes no
   object: a changed key, a changed content type, a body outside the signed
   length range, or a submission after expiry.
3. An unsigned `PUT` or `POST` to the private bucket, and an anonymous
   `PUT` to the legacy bucket, both return `403`.
4. A backend-issued signed GET preview returns the object before expiry. An
   expired URL, a URL with a modified signature, query, or key, and an
   unsigned `GET` of the same private key each return `403`.
5. An anonymous `GET /` (bucket listing), an anonymous list of either bucket,
   and an unsigned MinIO admin API request each return `403`. No console page
   is served.
6. An anonymous `GET` of an existing legacy-bucket object still returns `200`,
   confirming the unchanged legacy semantics.
7. Backend paths such as `/graphql/` and `/health/ready/` on the upload
   hostname return a MinIO error, never a backend response. The application
   hostname never returns a MinIO response.

## Prepare release inputs without launching

1. Copy `.env.example` to an absolute path outside the clone. Keep it mode
   `0600`, replace all `example.invalid` image references with immutable
   digest references from the approved release manifest, set
   `RELEASE_VERSION` to the frontend image's source commit, and use the exact
   public staging origins without trailing slashes.
2. Create a dedicated host group for staging secret readers and set its
   numeric GID as `STAGING_SECRET_GID`. Create the absolute
   `STAGING_SECRETS_DIR` owned by the deployment identity and that group with
   mode `0750`. Create each named secret file from the Compose `secrets`
   section with the same ownership and mode `0640`. Compose bind-mounts
   file-backed secrets without remapping ownership; `group_add` therefore
   gives non-root image users read access without making the host files
   world-readable. Values must be independent of local, CI, and production
   credentials. `django_secret_key` needs at least 50 characters and
   `nextauth_secret` at least 32. Exported secrets may end with a newline but
   must have no other surrounding whitespace.
3. Configure a remotely managed Cloudflare Tunnel and exact hostname routes
   separately. Apply the intended Cloudflare Access policy before any runtime
   launch, then run the upload hostname tests above.
4. Run the non-mutating checks:

   ```sh
   make check-staging
   make staging-preflight STAGING_ENV_FILE=/absolute/path/to/staging.env
   ```

The preflight renders Compose and validates image immutability, explicit
profiles, service/network isolation, fixed private aliases, the backend and
frontend production contracts, database TLS material, group-readable secret
ownership and modes, secret length and whitespace rules, distinct buckets and
HTTPS origins, exact MinIO API CORS, a disabled MinIO console, production
commands, migration ordering, and the absence of published ports or privilege
and bind-mount escape paths. It intentionally does not verify that registry
images exist, pull them, or read their labels.

## Release manifest

Record one approved manifest per release, outside this repository, before
the controlled commands run. Each image entry needs:

- the registry repository and `sha256` index digest used in the environment
  file, plus each platform manifest digest;
- the owning repository and full source commit, with a clean-tree assertion;
- the successful CI run URL for that exact commit, including image build,
  startup, tests, and full-history Gitleaks;
- the verified `org.opencontainers.image.revision` label and BuildKit
  provenance and SBOM attestations, builder identity, and build timestamp.

The manifest also records:

- frontend public build inputs equal to the environment file values above;
- for the backend, the Python base digest resolved from provenance and the
  migration result;
- for the root-built MinIO server and client images, the upstream tags and
  commits that `docker/minio/Dockerfile` verifies;
- for PostGIS and `cloudflared`, the reviewed upstream release and digest;
- the previous verified digests that rollback would select.

Rollback selects previously verified digests; it never reverses a schema
migration implicitly.

## Controlled migration and runtime order

All backend jobs use exactly `POSTGRES_OPTIONS=-c search_path=smokemap,public`.
The pinned PostGIS image initializes its extension in `public`; including that
schema exposes `geometry` and spatial functions during fresh migrations.
Keeping `smokemap` first makes it the target for application tables and indexes.
Local staging inherits this same setting. The preflights reject either omitting
`public` or putting it first.

`make test-staging-postgis` checks both rendered contracts against the pinned
local-staging PostGIS image in a fresh disposable container. It proves the old
path fails GIS DDL, then exercises geometry columns, spatial indexes, and a
spatial insert/query with the configured options. It uses an in-memory database,
no network or published ports, and no existing database, volume, or credentials.
CI runs this regression as part of `integration`. This is a database DDL test,
not a full Django migration or a staging deployment rehearsal.

After the manifest is approved and the preflight passes, a release runs
exactly two commands from the workspace root, in this order:

```sh
docker compose --env-file "$STAGING_ENV_FILE" -f deploy/staging/compose.yaml --profile staging-runtime --profile staging-migration run --rm migrate
docker compose --env-file "$STAGING_ENV_FILE" -f deploy/staging/compose.yaml --profile staging-runtime up --detach --wait
```

The migration command must select both profiles: `migrate` depends on the
runtime-profile `db`, `storage`, and `storage-init` services, and Compose
rejects the migration profile on its own. It starts only those dependencies,
runs `python manage.py check --deploy`, then a single-writer
`python manage.py migrate --noinput`, and exits. The runtime command never
selects `staging-migration`, so web replicas do not migrate. If both profiles
are ever selected for `up`, the backend still waits for the migration job to
finish before it starts. A failed migration stops the release: do not run the
runtime command.

## Launch blockers

Do not launch this topology yet. A passing preflight is necessary preparation,
not authorization to deploy or evidence that staging is healthy.

- The root gitlinks must pin the merged production contracts: backend
  `05098a798961e6e1b968d78f3211a17df63d036f` and frontend
  `21b93f47ddb9614509f636c83478b8a10b8dac47`. Root issue #112 / PR #113 moves
  them from the earlier `d9ddb01…` and `d466268…` baselines.
- No registry, signing policy, or publication workflow exists. No backend,
  frontend, MinIO, PostGIS, or `cloudflared` release digest has been produced,
  approved, or recorded in a manifest.
- The backend remains on Django 4.2, past its end of extended support, and its
  requirements are exact pins, not a hash-verified lock, as recorded in its
  `docs/PRODUCTION_IMAGE.md`.
- No staging PostgreSQL certificate authority or certificate has been
  provisioned. The TLS entrypoint wrapper and the readiness probe have not run
  against real images, because this change launches nothing. Server-side
  `hostssl` enforcement is a follow-up.
- The tunnel, DNS routes, Access policy, and upload hostname tests have not
  been created or proven. The local-staging mode supplies operator commands
  for backup/restore, migration, smoke, and digest rollback, but no
  rehearsal has run yet. Observability remains open.

Resolve those items through focused issues and PRs in the owning repositories,
then update root gitlinks in separate integration PRs.

## Cleanup worker status

`media-cleanup` runs the periodic command loop without an HTTP server. Its
Compose healthcheck explicitly disables the production backend image's HTTP
probe. `up --wait` therefore checks that the worker process is running; it
does not prove that cleanup batches succeed or that the worker is making
progress. The worker still waits for backend readiness before starting and
restarts unless stopped. Inspect its command logs and durable cleanup backlog
to monitor successful work; individual batch failures are retried by the loop.
This status contract applies to both external and local staging.
