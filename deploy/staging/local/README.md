# Local staging on the Jenkins host

Local staging runs the reviewed staging topology from `../compose.yaml` on this
host, without Cloudflare, `cloudflared`, DNS, or an image registry. It is the
first rehearsal stage of the M5 promotion path. The external, Cloudflare-routed
contract in `../README.md` is unchanged and still applies later.

The overlay in this directory makes these changes to the base contract:

| Concern | Local staging |
| --- | --- |
| Ingress | The `cloudflared` service and its token are never selected. A non-root nginx `edge` terminates TLS on **one** published port, `127.0.0.1:${LOCAL_STAGING_HTTPS_PORT}` (default 8443). |
| Origins | Two separate origins on reserved private-use names: `https://app.local-staging.smokemap.internal:<port>` and `https://media.local-staging.smokemap.internal:<port>`. No public DNS or tunnel can serve them, and the external preflight rejects them. |
| Images | Content-addressed local image IDs (`sha256:…`) recorded by `build`, with `pull_policy: never`. Nothing is pulled or published at startup. |
| Privilege | `frontend`, `backend`, `media-cleanup`, and `migrate` run as `10001:10001`, and `edge` runs as `101:101`. All five drop every capability and forbid privilege escalation. |
| Isolation | The project is always `smokemap-local-staging`. Its volumes and networks are project-scoped and can never be the development `smokemap_*` resources. |

Everything else is inherited and enforced unchanged:

- PostgreSQL, the backend, and the MinIO API publish no ports, and the MinIO console is off.
- The database, application, media, and ingress networks are internal.
- `verify-full` database TLS, file-backed secrets, fixed private aliases, the backend and frontend production contracts, and the one-shot migration ordering all still apply.

```
browser ── https://app…:8443 ──┐                      ┌── frontend:3000 ── api…internal:8000 (backend)
           https://media…:8443 ┴─ 127.0.0.1:8443 edge ┤                     │            │
                                  (edge network)      └── storage:9000 ─────┘ postgis…internal:5432
```

The edge selects each origin by TLS name and rejects any other name during
the handshake. It preserves the exact `Host`, including the port, because MinIO
verifies signed requests against it and the frontend checks server-action
origins with it. It replaces client forwarding headers, sends
`X-Forwarded-Proto: https`, and never logs query strings. Its error log is
limited to `crit` and above, because nginx quotes the full request line in
request errors, including the ordinary `error`-level upstream failures. The
access log still records every `502` and `504`, without the query. Signed
preview URLs and presigned form fields therefore stay out of logs.

## Operator home

Every command takes an absolute `LOCAL_STAGING_HOME` outside any Git working
tree. A non-root operator should use a path under their own writable `$HOME`:

```sh
export LOCAL_STAGING_HOME="$HOME/.local/state/smokemap-local-staging"
mkdir -p "$(dirname "$LOCAL_STAGING_HOME")"
```

`init` requires the parent to exist and creates the home itself. A system path
such as `/var/lib/smokemap-local-staging` works only when the operator can
write to its parent. The home contains:

| Path | Contents | Mode |
| --- | --- | --- |
| `settings.env` | Operator settings copied from `settings.env.example`; never secret values | `0600` |
| `secrets/` | Independent staging-only secrets plus database and edge TLS material | `0750` / `0640`, secret group |
| `authority/` | Staging-only CA keys; never mounted into a container | `0700` / `0600` |
| `edge-ca.crt` | Edge trust anchor for browsers and `smoke` | `0644` |
| `releases/<id>/` | `manifest.json` and `release.env` for each build | `0700` / `0600` |
| `release.env` | The selected release | `0600` |
| `backups/<id>/` | Paired `database.dump` and `media.tar` with `backup.json` | `0700` / `0600` |
| `state.json` | Migration records and action history | `0600` |

The secret group defaults to the operator's primary group (`--secret-gid`, or
`SECRET_GID=` with make, overrides it). Containers receive it through
`group_add`, so the non-root images can read the `0640` files without making
them world-readable. `init` refuses to touch an existing non-empty home and
never prints a secret.

Resolve both names to loopback wherever the browser runs. On the Jenkins host
itself, run:

```sh
echo '127.0.0.1 app.local-staging.smokemap.internal media.local-staging.smokemap.internal' | sudo tee -a /etc/hosts
```

From a workstation, forward the port without exposing it on the LAN:

```sh
ssh -N -L 8443:127.0.0.1:8443 <jenkins-host>
```

Add the same hosts line on the workstation, and trust `edge-ca.crt` only in a
dedicated browser profile.

## Release flow

Run the commands from a **clean** checkout of merged root `development` with
initialized submodules (`make sync`):

```sh
export LOCAL_STAGING_HOME="$HOME/.local/state/smokemap-local-staging"
mkdir -p "$(dirname "$LOCAL_STAGING_HOME")"
make local-staging-init LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME"
make local-staging-build LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME"
make local-staging-releases LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME"
make local-staging-preflight LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME" RELEASE=<id>
make local-staging-migrate LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME" RELEASE=<id>
make local-staging-start LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME"
make local-staging-smoke LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME"
```

`build`:

- requires a clean root tree and submodules;
- reads the root `smokemap-webapp` and `smokemap-django-backend` gitlinks, and requires each one to be on its application remote's `development` branch;
- exports each exact commit with `git archive`, so the working tree is never the build context, and builds the `production` targets;
- builds the frontend with exactly these public inputs: `VCS_REF` = `NEXT_PUBLIC_VERSION` = the frontend commit, `staging`, the fixed `/api/smokemap` paths, the local application origin, `NEXT_PUBLIC_MAP_STYLE`, and `LOG_LEVEL`;
- builds MinIO server and client from the root `docker/minio` tree at the pinned source tags;
- resolves PostGIS `17-3.5` and `nginx-unprivileged` `1.30.6-alpine` by pinned index digest;
- tags every image under `smokemap-local-staging/` so pruning dangling images cannot remove a release that rollback may need.

The release manifest records:

- the root commit and whether it is on `origin/development`;
- each application commit, its remote `development` head, the `git archive` SHA-256, and the SHA-256 of the `Dockerfile`, `requirements.txt`, `package.json`, `yarn.lock`, and `src/lib/production-config.js` inputs;
- the frontend public build inputs and their digest;
- the MinIO tags, commits and source-tree hash;
- each image's ID, tag, repository digests, OCI revision and source labels, user, platform, creation time and BuildKit reference;
- the Docker and Buildx versions, the builder host, and the previous release.

The local Docker store keeps no registry digest, provenance attestation, or SBOM,
and the manifest says so. Registry publication and attestations remain
prerequisites for the external contract.

`preflight` renders the base contract plus this overlay with a scrubbed
environment, so shell `COMPOSE_*` or staging variables cannot override the
reviewed files. It then validates:

- the full structure above and the base backend/frontend contracts;
- env-file and secret ownership, modes and values;
- database TLS (`verify-full` chain and hostname) and edge TLS (both origin names and key match), without printing key material;
- that every image exists locally under its recorded ID with the recorded OCI revision label and a non-root user;
- that any existing same-named volume or network belongs to this project;
- that the loopback port is free or held by this project's edge.

`preflight` starts nothing.

`migrate` repeats preflight and requires the root commit to be on
`origin/development`. It then runs the single-writer job
(`check --deploy`, then `migrate --noinput`) with both profiles, exactly as
the external contract does. Only after it succeeds does it record the
migration and select the release. `start` refuses any release without a
migration record for its backend image ID, and never selects the migration
profile.

## Operations

```sh
make local-staging-status LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME"
make local-staging-stop LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME"     # keep containers and data
make local-staging-down LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME"     # remove containers/networks, keep volumes
make local-staging-backup LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME" LABEL=before-upgrade
make local-staging-restore LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME" BACKUP=<id> CONFIRM=smokemap-local-staging
make local-staging-rollback LOCAL_STAGING_HOME="$LOCAL_STAGING_HOME" RELEASE=<previous-id>
```

`smoke` probes the edge as a browser would, pinning loopback and the edge
trust anchor. It checks:

- the application page, same-origin GraphQL, and bounded viewport GeoJSON;
- that the application origin never answers as MinIO, and the media origin never answers as the backend;
- anonymous listing of the root and both buckets, unsigned writes to both buckets, unsigned private reads, and the unsigned admin API, all `403`;
- upload CORS for the exact application origin only;
- rejection of unknown TLS names;
- that only the edge publishes a port, and only on `127.0.0.1`.

The signed POST upload and signed GET preview flows in `../README.md` need an
authenticated session and remain manual launch tests.

`backup` takes a **paired** snapshot under the selected release:

1. Stops `edge`, `frontend`, `media-cleanup`, and `backend`.
2. Dumps PostgreSQL with `pg_dump --format=custom` and verifies it with `pg_restore --list`.
3. Stops MinIO and archives the project's `minio-data` volume from a one-off container. The container has no network, a read-only root, no capabilities, and only that volume mounted, read-only.
4. Records SHA-256 checksums.
5. Returns services to their previous state.

`restore`:

- requires `CONFIRM=smokemap-local-staging`;
- verifies both checksums;
- refuses a backup taken under a different backend image (roll back to that release first, then migrate forward);
- takes a safety backup first, unless `--skip-safety-backup` is passed directly to the script;
- replaces only this project's database and media volume, then starts the release.

No command removes a volume, prunes, or passes `--volumes`.

`rollback` reselects a previously migrated release by its recorded image IDs
and starts it without migrating. It never reverses a schema. If the newer
release applied a migration the older code cannot run against, restore the
paired backup taken before that upgrade. Always take
`make local-staging-backup … LABEL=before-<release>` before migrating a new
release.

## Static checks

```sh
make check-local-staging
```

The checks render the checked-in templates, which only render and cannot
start. They fail on:

- public, wildcard or extra binds, or a published development port;
- an exposed database, backend, or storage service;
- `cloudflared`, a registry or mutable image, or a startup pull;
- root application users or retained capabilities;
- development project, volume or network names, and external resources;
- edge routing to the backend, the console, or anything but the frontend and MinIO API, edge logging of query strings or credentials, and an edge error log below `crit`;
- public or mismatched origins;
- drift from the backend and frontend production contracts.

They also prove that the external preflight still rejects a local configuration.

## Launch gates and known limits

Before treating local staging as a rehearsed environment, record evidence for
every step:

1. Clean merged root `development` with both production gitlinks.
2. `make check-local-staging`, `make check-staging`, and exact-head CI.
3. `init`, `build`, `preflight`, `migrate`, `start`, and `smoke`.
4. Manual signed upload and preview tests from `../README.md` against the local media origin.
5. A paired backup, a rebuilt-or-second release migration, a digest rollback, and a restore rehearsal with post-restore `smoke`.

Known limits:

- Django 4.2 is past its end of extended support.
- The backend requirements are exact pins, not a hash lock.
- The backend Python base tag is mutable, so the manifest records the built image rather than a promised bit-for-bit rebuild.
- MinIO and PostgreSQL still run their entrypoints as root inside their containers.
- Server-side `hostssl` enforcement remains a follow-up.
- Local staging has no observability sink.
- Cloudflare routing, Access policy, and registry publication are later steps through the external contract.
