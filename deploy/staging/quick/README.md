# Temporary staging with two Quick Tunnels

This is an explicit temporary public rehearsal, owned and launched by the
primary operator. It uses `smokemap-quick-staging`, separate volumes/networks,
new file-backed credentials and a new database CA outside Git. It does not
use a chosen domain, Cloudflare account/API, named tunnel or tunnel token.
Never read, copy or mount an existing `.cloudflare/smokemap-stg.token`.
The existing local project/home/data and development/production environments
are independent. Do not operate another cloudflared process or host PID.

The frontend/backend remain pinned to `21b93f47ddb9614509f636c83478b8a10b8dac47`
and `05098a798961e6e1b968d78f3211a17df63d036f`. This path builds the existing
production targets; it does not change either application. Local-staging's
reserved origins and external staging's registry/digest contract are unchanged.
Quick mode uses recorded local image IDs with `pull_policy: never`, without
publishing application images to a registry. Building/pulling reviewed public
base images still needs network access on the build host.

## Prepare and launch (primary operator only)

Use a new clean checkout/worktree of merged `origin/development`, initialize
its pinned submodules, and run commands from that root. `build` records the
root commit, submodule commits, source/archive checksums, all public build
inputs and their hash, local image IDs/revision labels, upstream digests, exact
public origins and connector process ownership. Migration refuses a root
commit that has not merged into remote development. PR validation does not
require merging or starting public tunnels.

Requirements: Linux Docker Engine, Compose 2.35.1+, Buildx, Git, Python 3 and
OpenSSL. Host Node/Python application dependencies are not required. Choose a
NEW outside-Git absolute home with an existing parent and a positive group ID
that belongs to the operator. Do not reuse a local-staging home or copy its
credentials, TLS, release files or data.

```sh
# Static validation only: safe for workers/CI; no daemon or public tunnel.
make check-quick-staging

# The following commands allocate public URLs / start containers: primary only.
export QUICK_STAGING_HOME=/absolute/new/private/smokemap-quick-staging
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" init
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" connectors
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" build
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" releases
```

`connectors` starts ONLY `quick-app` and `quick-media` with `--no-deps`, while
apps are unavailable. Each connector is the official immutable
`cloudflare/cloudflared:2026.10.0` image, nonroot, read-only, with all capabilities
dropped and no privilege escalation. It has no credential/config mount,
restart policy, host port or app dependency. Each reaches only its required
internal ingress network and the egress `edge` network. Apps/storage/DB never
join `edge`. Targets are fixed `http://frontend:3000` and
`http://storage:9000`; backend, DB and MinIO console have no public listener.

Discovery reads the private port 2000 `/quicktunnel` endpoint through a
short-lived nonroot, read-only, capability-free PostGIS-image bash helper on
ONE internal ingress network. It has no mounts/secrets/egress and does not
read Docker logs. The URLs, container IDs, PIDs, start times and restart counts
are persisted in mode-0600 state/settings, never taken from user input.
Both origins must be distinct exact lowercase `https://<one-label>.trycloudflare.com`
values with no port/path/query/credentials/wildcard.

`build` compiles the frontend for that actual app URL. Use the release ID
printed by `build` in the next commands:

```sh
export QUICK_RELEASE=YYYYMMDDTHHMMSSZ-rootcommit12
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" preflight --release "$QUICK_RELEASE"
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" migrate --release "$QUICK_RELEASE"
# Foreground, long-running supervisor. Keep this terminal/process alive.
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" start
```

Migration requires stopped app writers, checks deployment settings, runs one
`run --rm migrate` job, and records success for the exact backend image before
selecting the release. `start` checks that record before starting apps. It
never recreates connectors. In another terminal:

```sh
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" status
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" smoke
# Close BOTH public ingresses first, then stop this project, keeping all data.
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" stop
```

Ctrl-C/SIGTERM to `start` also closes ingress before stopping app writers.
`stop` works before any build/release exists. It never removes volumes,
networks, images or other projects, and never signals a host PID. No `down`,
prune, reset or implicit data deletion is provided.

## HTTPS, logging and changes of URL

Cloudflare terminates public TLS. cloudflared preserves the public Host and
Cloudflare supplies HTTPS forwarding metadata to the fixed private HTTP
origin; no `http-host-header`, insecure TLS or insecure-origin bypass is used.
NextAuth's canonical URL and public browser bundle both use the exact app
origin. Backend CORS/CSRF and MinIO CORS use only that app origin. Both signing
URLs use the exact media origin. The existing frontend production proxy and
server clients replace forwarding headers with `X-Forwarded-Proto: https` and
use the private backend alias; Django trusts only that configured hop and
requires database `verify-full` TLS. MinIO receives the original signed Host.
The primary must verify those behaviors through actual public HTTPS.

The cloudflared log level is `fatal`; Docker log storage is `none` even for
fatal failures. Discovery never needs logs. No command dumps settings,
secrets, sessions, response bodies, presigned form fields or signed URL queries.
The smoke command prints only check names and pass/fail results.

Every preflight checks exact process ownership AND the live private hostname
against the recorded generation and build manifest. The foreground supervisor
repeats the check every two seconds (plus probe time). A missing/restarted/
replaced connector, changed URL or unavailable metrics invalidates the
generation and stops BOTH connectors. Reconnecting an existing transport is
allowed if its process and assigned hostname remain identical. A new process
is never adopted automatically, even if it reports the old hostname.

To resume after stop/restart/URL change, run `stop`, `connectors`, `build`,
`preflight`, `migrate`, `start` again. Rebuild the frontend even if only the
media URL or connector process changed. Old generation manifests are rejected.
Do not manually run `docker restart`, Compose `up` or attach ingress networks.

Supervision is an operator control, not an atomic per-request network lease.
There is a bounded detection interval after an out-of-band Docker restart.
SIGKILL of the supervisor, host death or an unavailable Docker daemon cannot
run its cleanup; `status` detects a missing supervisor with live apps and
closes ingress. Keep the supervisor alive and use `stop` before maintenance.
This temporary rehearsal is not unattended hosting or a production deployment.

## Backup and recovery rehearsal

Use only disposable quick-project accounts/data. The primary owns authenticated
login, refresh/logout, submission with zero/multiple images, presign/upload/
preview, moderation and post-approval checks through the two public URLs.
Unauthenticated `smoke` covers public home/GraphQL/viewport, canonical auth
callback URLs, media health/CORS, denied anonymous listings/writes/private
reads, and app/media routing. It does not prove authenticated product behavior.
The existing 18 local smoke checks stay unchanged.

Paired backup and recovery reuse the validated local operator primitives,
scoped to this quick project. Keep the foreground supervisor running in one
terminal, then use the second terminal:

```sh
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" backup
# After adding/changing disposable quick data, restore the printed backup ID:
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" restore \
  --backup YYYYMMDDTHHMMSSZ --confirm smokemap-quick-staging
python3 scripts/quick-staging.py --home "$QUICK_STAGING_HOME" smoke
```

Backup pauses app writers, dumps PostgreSQL, stops MinIO and archives its
project volume using a network-less helper. It stores the paired files and
checksums in the private home, then resumes runtime. Restore verifies project,
checksums and paired backend image, takes a safety backup, stops writers,
replaces ONLY the quick DB/media, and resumes. It is explicitly destructive to
that disposable quick data, hence the exact project confirmation. It never
reads another project's volumes. Verify the pre-backup submission/media state
is restored and subsequent authenticated writes work.

Backup, restore and rollback require the live foreground supervisor, because
the reused helpers resume runtime after pausing writers. They cannot start an
unsupervised public application from a stopped rehearsal.

Within one unchanged connector generation, `rollback --release ID` selects a
previously migrated compatible release by recorded image IDs. It does not
reverse DB migrations. After connector loss, create a NEW generation/rebuild
first, then migrate/select and `start` that release before restore; the backend image must
still match the backup. Never reuse an old frontend with new public URLs.
Keep the private home, credentials, local images and both volumes until the
primary has completed recovery evidence. No cleanup of another local rehearsal
is part of this procedure.

## Evidence and upstream verification

`make check-quick-staging` runs rendered-contract and mocked lifecycle tests
without a Docker daemon. CI also pulls the exact official connector digest,
runs its version/help with `--network none`, and runs the unchanged local,
external and cross-app CI suites. It never opens a Quick Tunnel.

The upstream [2026.10.0 metrics implementation](https://github.com/cloudflare/cloudflared/blob/2026.10.0/metrics/metrics.go)
returns `{"hostname":"..."}` from `/quicktunnel`; the
[Quick Tunnel implementation](https://github.com/cloudflare/cloudflared/blob/2026.10.0/cmd/cloudflared/tunnel/quick_tunnel.go)
provisions the hostname before starting the tunnel server. The
[official image Dockerfile](https://github.com/cloudflare/cloudflared/blob/2026.10.0/Dockerfile)
sets UID/GID 65532. The digest is recorded in
[the official image listing](https://hub.docker.com/layers/cloudflare/cloudflared/2026.10.0/images/sha256-1a50cc8893b3f0dd283805d2efcd3336210aced60a83d967fb2bbc8ab69b5f35).
Upstream request-error logging can carry URL context, so fatal-only plus
Docker logging `none` is deliberate.

[Quick Tunnel limits](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
include no uptime guarantee, at most 200 concurrent in-flight requests and no
SSE. This is a temporary public rehearsal. Static/mock/offline evidence does
not prove actual URL assignment, Docker routing/egress, forwarding headers,
public HTTPS, upload signatures or recovery; those are primary operator gates.
