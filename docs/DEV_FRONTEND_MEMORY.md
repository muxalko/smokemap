# Development frontend memory guardrails

Source proposal for [workspace #154](https://github.com/muxalko/smokemap/issues/154).
No deployment, restart, migration, data change or leak fix is claimed. Follow
[DEVELOPMENT verification](DEVELOPMENT_VERIFICATION.md) before a later rollout;
keep frozen release sources, prior images, dependency/cache volumes and paired
database/media recovery points intact.

## Bounded diagnosis, 2026-11-04 UTC

The requested frontend revision is
`a07af381b870e16229c36cee491a6cb8c0859d38` (Next.js 15.5.28).
The runtime source checkout reports root
`0e3e98c371708b2c0356f977f5b2c539fe3d9728` and that frontend revision.
The newest inspected frozen checkout, `task7-1bc657271d3f`, reports root
`1bc657271d3f8b7335a163680970b83413f87f85` and the same frontend revision.
These are filesystem observations, **not verified running image/mount identity**.

This worker's Docker socket access was denied (`operation not permitted`).
The host-published backend readiness request also failed to connect from the
sandbox. Neither is evidence that the application is unhealthy. Running image
IDs, mounts, process RSS/heap, restart counts, configured health probes and
bounded health history remain unavailable. No full inspect, environment dump,
raw application log, heap snapshot or secret-bearing configuration was read.

Three read-only cgroup-v2 samples, ten seconds apart, were available for Docker
scope `43f7c6a6337e656485334fb3d590dcd70e47695ef8d8acdf3596807b3a720fd1`.
**Its service/release association could not be verified.** Values below are
bytes; `memory.current` includes anonymous, file and kernel memory, not just
JavaScript heap or process RSS.

| UTC | memory.current | anon | file | kernel | pids.current |
| --- | ---: | ---: | ---: | ---: | ---: |
| 22:30:22 | 5,259,968,512 | 4,803,338,240 | 314,728,448 | 141,332,480 | 50 |
| 22:30:32 | 5,249,138,688 | 4,794,159,104 | 314,748,928 | 140,230,656 | 39 |
| 22:30:42 | 5,251,018,752 | 4,795,994,112 | 314,748,928 | 140,279,808 | 39 |

Across these samples `memory.max=max`, swap usage was zero, and every
`memory.events` counter (including `oom` and `oom_kill`) was zero. The peak
rose from 5,274,755,072 to 5,280,141,312 bytes while current usage fell overall.
This short uncontrolled window establishes neither a leak nor a growth slope.
The raw numeric sample is retained at `/tmp/smokemap-memory-cgroup-evidence.json`
in the worker environment; this table is the durable sanitized record.

Verified source-level exposure: canonical Compose starts `next dev`, has no
frontend memory limit or explicit Node heap cap, and runs a rendered-homepage
GET every five seconds with only Docker's outer timeout. The exact frontend
has a tracked public favicon, outside its authentication middleware matcher.
Dev compiler/cache retention and repeated rendered-page work are plausible
memory/CPU contributors. They are hypotheses, not an attributed cause of the
unidentified cgroup's usage. Retained objects, native memory, caches and
transient requests cannot be distinguished by these samples. A verified leak
requires longer controlled repeat/idle observations and allocation evidence.

## Proposed source defaults

| Setting | Default | Scope |
| --- | --- | --- |
| `FRONTEND_MEMORY_LIMIT` | `6g` | RAM ceiling for the whole frontend container |
| `FRONTEND_NODE_MAX_OLD_SPACE_SIZE_MB` | `4096` | MiB of old-space per Node process via `NODE_OPTIONS` |
| Health request | `HEAD /favicon.ico` | Exactly HTTP 200, no redirect following, 3-second abort |
| Docker health timing | 30s / 5s / 4 / 60s | interval / timeout / retries / startup grace |

The 2 GiB nominal gap allows native allocations, other Node processes and file
cache; it is **not a measured capacity guarantee**. Old-space is not total RSS,
and multiple processes each inherit the Node setting. The container cap is the
aggregate backstop. Node may exit on heap exhaustion; the container may be
OOM-killed at its RAM cap. These are containment, not leak repair. Swap policy
is unchanged. Use a positive integer heap override and a valid Compose byte
value with sufficient aggregate headroom; invalid values fail Node/Compose
startup. Do not apply these settings to an active release to diagnose it.

The static probe confirms that the HTTP server can serve a public asset; it
does not establish map compilation, backend readiness, authentication, GraphQL
or submission/media correctness. The existing homepage, auth and browser E2E
gates retain those responsibilities. A missing favicon fails health closed.
Docker unhealthy status alone does not restart a running service. The inherited
isolated E2E projects use the same guardrails; staging overlays have independent
contracts. The static request avoids repeatedly warming the map merely to
measure liveness.

## E2E startup readiness repair

Original candidate `d06abcdfab38a07019595040a5b67e1d43d6f5be`, CI run
`41926302715`, passed integration, secrets and submission-media but failed
viewport-pan (30-second Puppeteer timeout) and public-after-approval
(`waitForVisibleText` in `fillSubmission`, lines 150/190, five-second timeout).
The existing HCP report `8055827cdee24b738fa150a2bc36b702` records these
unresolved failures; it supplies no independent review or live verification.

Source inspection confirms that replacing the homepage health GET with static
liveness removed the only pre-browser homepage compilation. The viewport
test starts its first response/navigation clocks before that cold compilation;
the public-media test previously treated a visible server-rendered submission
button as interactive readiness. These are startup synchronization gaps,
consistent with the supplied failed-job evidence. Docker and redirected full
CI logs remain inaccessible in this sandbox; no compiler-duration measurement
or verified live memory cause is inferred from the failures.

The isolated E2E entrypoint now requests the homepage once, requires HTTP 200
without redirects, and consumes the complete streamed body before importing
the browser suite. Cold development compilation has a separate bounded
two-minute startup deadline; request, body, status and deadline failures abort
the suite. There are no retry loops or periodic rendered-page probes. The
public-media creation phase also waits for the real successful initial bbox
response from the mounted map before interacting with the submission button.
Existing navigation, response and interaction budgets and all product/storage
assertions remain intact. The canonical static liveness probe is unchanged.

`node --test tests/e2e-frontend-readiness.test.mjs` covers streamed-body
completion, non-200 responses, request/body failures and a hung body deadline
without application dependencies or network access. All three real browser
suites still run in CI; their results must be attached to the repaired head.

References: [Compose memory limits and healthcheck](https://docs.docker.com/reference/compose-file/services/),
[Node old-space limit](https://nodejs.org/docs/latest-v22.x/api/cli.html#--max-old-space-sizesize-in-mib).

## Verification and remaining gates

`make check-compose` validates default and overridden limits without a daemon.
`python3 -m unittest discover -s tests -p 'test_dev_frontend_memory.py' -v`
also validates isolated E2E inheritance and executes the actual rendered probe
against disposable loopback HTTP servers: 200, 204, redirect, 503, hung response
and connection refusal. No live app, database or storage is used. CI pins Node
to the frontend's `.nvmrc`; local offline configuration checks used Compose
2.35.1 and Python 3.12. Local HTTP tests were blocked by the sandbox's private
network policy; they must pass in CI. CI/E2E results belong to the exact PR
candidate and do not establish live recovery or calibrated memory capacity.

Before diagnosis can close, an authorized operator must map the exact running
frontend container to image ID, frozen `/app` mount and frontend SHA; read only
selected memory limits, restart/OOM state and five health entries (exit codes
and timings, no raw output); then collect at most twelve ten-second samples of
that container's cgroup memory/current/stat/events and per-process RSS. Record
the request workload and distinguish file cache from anonymous memory. Do not
send traffic, trigger GC, attach an inspector or restart it as part of this
read-only pass. A longer controlled reproduction belongs in a separate isolated
candidate with its own database/media/cache volumes. Retest homepage, login,
logout, viewport and submission/media behavior there before any later rollout.
Independent review is still required; this stage uses no subagents and cannot
supply its own independent review. No merge or live rollout is authorized.

Active GDAL task `b76eeccd98a54da499a622498fd819e9` owns backend
[PR #124](https://github.com/muxalko/smokemap-django-backend/pull/124), branch
`gdal-installer-hardening`, inspected head
`6ae7c7f891c4d682dc0e74bb59a459589475c8a6`. This change does not edit that
worktree, backend source/installers, dependency files or either application
gitlink. Reconcile through a later root integration only after that task's
reviewed commit is merged and published. The shared Smokemap Project lookup
returned no accessible projects; no project status was changed.
