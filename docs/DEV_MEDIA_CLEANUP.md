# Development cleanup supervision

Root issue #130 (linked backend #55) replaces only the canonical development
shell loop with `scripts/dev-media-cleanup.py`. It uses the existing backend
`manage.py check`, then `manage.py process_media_cleanup --batch-size N`.
There is no application, schema, expiry or deletion-policy change. Backend
and frontend source revisions, web health endpoints, external staging, local
staging and Quick runners retain their existing contracts. This change is
source/control work; it does not update frozen live release checkouts or
constitute deployment/recovery evidence for DEVELOPMENT.

The development service retains the backend build, environment and `/app`
source mount, waits for backend readiness, publishes no ports, and uses
`restart: unless-stopped`. Only this service mounts the runner read-only at
`/opt/smokemap-dev-media-cleanup.py`. No monitor service or credentials are
required. Docker's cleanup healthcheck explicitly replaces any inherited web
probe; it verifies batch progress rather than PID 1 liveness.

## Configuration and timing

Safe overrides are listed in `.env.example`:

| Knob | Default | Meaning |
| --- | --- | --- |
| `MEDIA_CLEANUP_BATCH_SIZE` | `100` | Integer `1..1000`, passed to the existing management command |
| `MEDIA_CLEANUP_INTERVAL_SECONDS` | `300` | Positive integer delay after each attempt, including failure |
| `MEDIA_CLEANUP_TIMEOUT_SECONDS` | `120` | Positive integer deadline for each Django check or cleanup command |
| `MEDIA_CLEANUP_HEALTH_START_PERIOD` | `250s` | Compose duration for initial health grace |

The numeric runner settings accept ASCII decimal integers up to `2147483647`
seconds (batch size remains capped at 1000); signs, whitespace, fractions,
zero and non-finite values fail startup. Invalid configuration never runs
Django. Django system checks must succeed before any batch is processed.
Startup checks and cleanup commands each have their own timeout. Increase
`MEDIA_CLEANUP_HEALTH_START_PERIOD` to at least **2 × timeout + 10 seconds**
when increasing the timeout. The default allows two 120-second budgets and
10 seconds for scheduling. The first batch runs immediately after checks;
startup grace does not need to include the retry interval. An initial failure
can exceed this grace while waiting for a retry, correctly exposing unhealthy
status. `--wait` operators can set a finite `--wait-timeout` appropriate to
these budgets; a restart loop may otherwise wait indefinitely.

The health probe runs every 5 seconds with a 3-second probe timeout and one
failure required to become unhealthy after startup grace. Grace suppresses
Docker's initial failure accounting; the probe itself always fails until a
real successful cleanup batch has completed, including a valid zero-work
batch. Startup/check success is never batch success.

After success, waiting health lasts the interval plus a fixed 15-second
scheduling allowance. A subsequent running batch may retain health only if
that success was still fresh when it began and only until the batch's own
bounded deadline. Health rejects future timestamps, stale success, exceeded
deadlines and inconsistent timestamp ordering **in the elapsed clock domain**.
Health freshness uses Linux `CLOCK_BOOTTIME`, a monotonic boot-relative clock
shared by the runner and separate probe processes that also counts suspended
time. Both waiting freshness and running deadlines use this clock, and the
runner clears an expired success before publishing a new running deadline.
For example, an unchanged success with a 315-second waiting budget remains
unhealthy after 600 elapsed seconds even if the wall clock rewinds 400 seconds.
Wall-clock adjustments in either direction do not affect freshness; wall
timestamps are diagnostic only, so their order can change across writes.
Command timeouts and retry sleeps continue to use `time.monotonic()`.
A failed batch clears the success markers immediately. Its next running retry
remains unhealthy until it actually succeeds. Expired success likewise cannot
restore health without a new successful batch.

## Status and failure handling

Status lives only in `/tmp/smokemap-dev-cleanup/status.json`, on the worker's
16 MiB `/tmp` tmpfs. It is never written into application source, a release,
a database or a persistent volume. The runner creates a private UID-owned
`0700` directory and writes UID-owned `0600` regular files through exclusive,
random staging files and atomic replacement. A wrong owner/mode, symlink,
unreadable file, oversized file, duplicate key or non-allowlisted schema is
unhealthy. A staging file is never trusted or reused. Failed status writes
stop the runner with a generic event and best-effort invalidation, rather
than continuing cleanup without reporting. Private status contains only the
exact version-2 keys `version`, `pid`, `process_start` (Linux start ticks),
`started_at`, `updated_at`, `last_success_at`, `phase`, `deadline`,
`started_elapsed`, `updated_elapsed`, `last_success_elapsed`, and
`deadline_elapsed`. The `*_at` fields and `deadline` are finite epoch seconds;
the elapsed fields are finite boot-relative seconds. Both last-success fields
are null until success, after failure, and when expired success is invalidated
before a new batch. Starting, failed and stopped phases are unhealthy.
The probe rejects the old wall-only schema; a runner restart discards old
ephemeral status and requires a new successful batch.
The probe independently binds status to the currently existing Linux process
and its start ticks. Every start invalidates previous status before checking
configuration or running Django, so an old success cannot bless a fresh run.

Child stdout and stderr are combined and captured in memory only, capped at
64 KiB per command. They are never forwarded or persisted. GDAL/debug preamble
is ignored; exactly one `media cleanup processed: ...` summary must provide
exactly these nonnegative ASCII integer fields once each: `expired`, `claimed`,
`deleted`, `upload_claimed`, `upload_deleted`, `redacted`, `failed`, `skipped`,
`draft_expired`. Unknown, missing, duplicate or malformed summaries/counts fail
closed. Each count is limited to ten digits. Exit zero with `failed > 0` is a
failed batch. Nonzero exit, missing summary, timeout and output overflow are
also failures. None can claim recovery. Successful checks do not require a
cleanup summary.

The loop retries normal batch failures after the configured interval. Startup
check/configuration failures exit; the existing restart policy retries the
runner. Timeout and SIGTERM/SIGINT terminate the entire command process group,
allow up to two seconds for graceful exit, then kill remaining group members
and reap the command. This includes descendants that keep pipes open or
ignore SIGTERM. The container's 10-second stop grace accommodates this bound.
Shutdown during waiting is observed within 100 milliseconds. The final stopped status is
unhealthy. Existing durable backend cleanup leases/rows provide retry
recovery; killing a command is not evidence of a completed batch.

## Redacted events and operator checks

Each event is one small JSON object on stdout with `event`, `outcome`,
`reason`, `timestamp`, and optional `counts` containing only the nine numeric
fields above. No child text, exception text, environment, tokens, presigned
payloads, keys or record IDs are logged. Events are:

| Event | Outcome | Reason |
| --- | --- | --- |
| `startup` | `success` | `system_check` (only checks passed) |
| `startup` | `failure` | `config_invalid`, `command_exit`, `timeout`, `output_limit`, `spawn_failed`, `shutdown` |
| `batch` | `success` | `ok` |
| `batch` | `failure` | `command_exit`, `timeout`, `output_limit`, `spawn_failed`, `output_invalid`, `failed_count` |
| `batch` | `recovered` | `ok`, only after a prior failed batch and a new successful real batch |
| `shutdown` | `stopped` | `shutdown` |
| `runner` | `failure` | `state_error`, or `internal_error` for an unexpected internal failure |

For the canonical development project, after the primary has started it:

```sh
docker compose ps media-cleanup
docker compose logs --tail 50 media-cleanup
docker compose exec -T media-cleanup python /opt/smokemap-dev-media-cleanup.py health
```

The last command prints nothing and exits `0` for healthy, `1` for unhealthy.
Use the fixed reason codes, backend readiness and local storage availability
to diagnose failures; do not enable raw child-output logging. After fixing
an invalid knob or statestore problem, recreate the development worker with
its corrected configuration. Normal batch failures retry automatically and
report `recovered` only after genuine batch success. Docker unhealthy status
exposes the failure but **does not restart a still-running process**. Root
#132 adds opt-in, host-side [cleanup health email alerts](DEV_CLEANUP_ALERTS.md)
that read this Docker health status; nothing installs or enables them by
default, and they change neither this worker nor its healthcheck.

## Verification

`make test-dev-cleanup` runs Python-stdlib tests with fake `manage.py` children
and disposable private temp directories: successful work, failure/recovery,
startup, stale/future/malformed health, unchanged stale snapshots across wall
rewinds, forward/backward wall adjustments, elapsed waiting/running/retry
boundaries, stale-success invalidation and genuine-batch recovery,
configuration, output parsing and bounds, failed counts despite exit zero,
timeouts, descendant shutdown,
private atomic state, statestore failure and secret redaction. It is part of
`make test` and required root `integration` CI. No DB, storage or host packages
are needed.

The primary runs `make check-compose` for rendered defaults/overrides, canonical
command/mount, shared backend source, progress probe and isolation. Required
root CI also runs `make test-dev-cleanup-compose` using verified Compose
2.35.1 through `COMPOSE_235_BINARY`. That disposable UUID project uses a
non-root Python image with an inherited web probe, the real development
runner/probe and a fake management command. It proves `up --wait` fails on
exit-zero failed counts, then succeeds after a real recovery batch, with no
web listener, application, DB, storage, host port or writable source mount.
It remains separate from `tests/test_staging_cleanup.py`, which preserves the
staging PID 1 liveness contract.
