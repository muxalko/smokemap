# Bounded launch dependency and container assessment

Assessment date: 2026-10-31 UTC. Tracking:
[root #134](https://github.com/muxalko/smokemap/issues/134).
Outcome: **launch security gate remains open**. No upgrades, dependency
installs, image pulls/builds, service changes, migrations or production access
were performed. This is documentation and read-only assessment evidence.

## Source identity and scope

Assessed current `development` root:
`215bd7a5c3b000d605600ed33710a0285f619c40`.
Committed backend gitlink: `05098a798961e6e1b968d78f3211a17df63d036f`.
Committed frontend gitlink: `a07af381b870e16229c36cee491a6cb8c0859d38`.
Both initialized submodules were clean and matched their gitlinks; no
initialization/reset was necessary. Inputs were read with `git show HEAD:<path>`
in each owning repository, not inferred from installed host dependencies.

The isolated checkout initially had clean root HEAD
`73bb73112293c5542a3697790107094ac4fce669` on the prior task branch.
After fetching, its file tree matched `origin/development`; the local
`development` branch was fast-forwarded to the assessed root before creating
`issue-134-launch-security-assessment`. Original branch/history were preserved.
No other checkout or dirty evidence was altered. Host tooling is not evidence
of application runtime versions.

| Committed component | Exact declaration and authority | Limits |
| --- | --- | --- |
| Frontend framework/auth/UI | `next` and `eslint-config-next` 15.5.28, `next-auth` 4.24.15, React/React DOM 18.3.1 in `package.json`/`yarn.lock` | Yarn v1 lock has 1,431 version entries including dev/optional entries; production standalone closure was not inspected. |
| Frontend runtime | `.nvmrc`/Dockerfile Node 22.23.4; `packageManager` Yarn 1.22.22 | Dockerfile pins `node:22.23.4-bookworm-slim@sha256:de170b39439eb0e5a3444ad7d60b015614a381e10fecae2e30ec9e735122f38d`; this is a base reference, not a built/running application image digest. |
| Backend runtime/framework | `python:3.12-slim-bookworm`; Django 4.2.22, Gunicorn 23.0.0 in `requirements.txt` | Python base floats; 34 exact runtime pins do not lock undeclared transitives or artifact hashes. |
| Backend libraries | Pillow 10.4.0, DRF 3.15.2, SimpleJWT 5.3.1, PyJWT 2.8.0, urllib3 1.26.19, psycopg2-binary 2.9.9 | Explicit versions only; no complete resolved Python production graph or native-library inventory. |
| Backend dev additions | `requirements-dev.txt` includes runtime input plus Fiona 1.9.5 and pandas 2.2.1 | Pipenv files have already been retired; see backend `DEPENDENCIES.md`. Do not resurrect the historical lock. |
| Database/spatial | Root Compose `postgis/postgis:17-3.5` | Floating patches; no deployed server/extension version or immutable digest established. |
| Storage server | Compose source release `RELEASE.2025-07-23T15-54-02Z`, commit `7ced9663e6a791fef9dc6be798ff24cda9c730ac` | Custom MinIO build; source/checksum verification establishes provenance checks, not security maintenance or vulnerability clearance. |
| Storage client/init | `RELEASE.2025-08-13T08-35-41Z`, commit `7394ce0dd2a80935aded936b09fa12cbb3cb8096` | Client/init must be assessed even though it is not a long-running application service. |
| Root dependency inputs | No root Node/Python application lock or manifest. Root owns Compose, MinIO Dockerfile, E2E and CI inputs. | OS packages, Go modules/toolchains and CI dependencies require separate coverage. |

`docker/minio/Dockerfile` pins Go 1.24.5/1.24.6 builder images and UBI 9.6
server/client bases by digest, verifies source commits and runs `go mod verify`.
Their exact digest references remain in that immutable root file; the SHA-256
below fingerprints it. It also installs build packages from mutable package
repositories. E2E uses `ghcr.io/puppeteer/puppeteer:24.16.0`; CI references
`actions/checkout@v4`. Neither is a production artifact clearance. Staging
contracts require operator-supplied application/database/storage/tunnel digests;
placeholder requirements do not establish selected or running images.

Public committed-input SHA-256 fingerprints:

| Input | SHA-256 |
| --- | --- |
| Root `docker-compose.yaml` | `bcc96c6c7f7ceedf19c21966e812405a1b80300aa0f46d5a1c8b7afa83e37835` |
| Root `docker/minio/Dockerfile` | `98fbfa08e7df2d343d14011969fb216c0c2b05c5654b0b5e0f8e2b6420bcd5bf` |
| Frontend `package.json` | `491ccbf90ae8fbeb36149cda05008f9e4bcacbbf0de716a3b4a85af2cc53097d` |
| Frontend `yarn.lock` | `ed82c9705fea2bd546f597c06a095b5d8bcd0389ffce16ac6667ad893973fdf5` |
| Backend `requirements.txt` | `96c2e77cd5ba7b1deca39764bec0ce21ae1d55595af07ff5872eeb2a705b92d4` |
| Backend `requirements-dev.txt` | `fad9132e924a023266af909345c53332ffd4acad10870a387e08bdd89d3ebddd` |

## Actual runtime and image evidence: unavailable

`docker ps --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}}'` failed with
Docker socket permission denied (`operation not permitted`) in this sandbox.
No container was exec'd, copied, exported, started, stopped or inspected.
Actual running source paths/SHAs/dirty state, bind mounts, dependency/cache
volumes, installed package versions, architecture, image IDs/RepoDigests and
revision labels are **unknown**, across development and staging. No production
inventory was attempted. Do not substitute the table above for runtime facts.

A later authorized operator must read only allowlisted identity fields, map
all running services (including cleanup, init, database, storage and proxies)
to their actual sources/mounts and immutable images, and compare installed
packages to the candidate locks/SBOMs. Avoid full environment/inspect/log dumps.
Keep private host paths/configuration in Jenkins evidence; publish a sanitized
identity comparison. This leaf task did not use orchestration or access private
Jenkins scan artifacts, so no existing operational result is claimed here.

## Advisory attempts and coverage

Bounded attempts used public package/version inputs only, in scratch files
under `/tmp`; no application packages or scanner were installed. The query
method was [GitHub's global advisory API](https://docs.github.com/en/rest/security-advisories/global-advisories),
not a reachability scanner. Evidence timestamp: approximately 06:40 UTC.

| Attempt | Result | Meaning |
| --- | --- | --- |
| `command -v trivy grype syft osv-scanner pip-audit` | None available | No container/OS/SBOM scanner executed. |
| OSV `POST /v1/querybatch` | First 100-package batch failed (`URLError`); sandbox denied `api.osv.dev` | Zero completed advisory queries. Public-input parser enumerated 1,467 distinct ecosystem/name/version tuples (1,431 Yarn entries plus 36 Python pins); no complete graph scan. |
| `timeout 45s yarn --cwd <scratch> --ignore-scripts --non-interactive audit --groups dependencies --json` | Sandbox denied `registry.yarnpkg.com`; no audit summary produced | Incomplete; no zero-finding claim. Scratch manifest/lock were copied from committed frontend input. |
| App-helper `GET /advisories?ecosystem=pip&affects=django@4.2.22&per_page=100` | Completed: 11 reviewed advisory records | One critical, two high, three medium, five low; version-range matches, no exploitability proof. |
| Same API, `ecosystem=npm&affects=next@15.5.28` | Completed: empty array | Only this direct framework lookup; no transitive, unreviewed, malware or image coverage. |
| Batched GitHub queries against enumerated tuples | Tool interrupted on sandbox network denial; no completed result artifact | Entire broader attempt recorded incomplete; no aggregate counts or graph clearance inferred. |
| Actual images / native libraries / embedded Go modules | Not scanned | Docker access and approved scanner execution/evidence still required. |

Successful direct queries used `scripts/github-app-gh api --method GET
/advisories -f ecosystem=<pip or npm> -f affects=<name@version> -f per_page=100`.
Responses fit within one page (11 and 0 records). API defaults cover reviewed
non-malware advisories. Counts are dated database observations; future scans
must record database freshness, tool versions, exit codes and pagination.

### Django findings requiring disposition

| Severity | Reviewed advisory IDs | Initial disposition |
| --- | --- | --- |
| Critical | [GHSA-frmv-pr5f-9mcr](https://github.com/advisories/GHSA-frmv-pr5f-9mcr) (`CVE-2025-64459`) | `_connector` SQL injection; affected 4.2 range is below 4.2.26. Supported-framework upgrade and fresh full scan required. Reachability not established; no exception granted. |
| High | [GHSA-hpr9-3m2g-3j9p](https://github.com/advisories/GHSA-hpr9-3m2g-3j9p) (`CVE-2025-59681`) | Column-alias SQL injection; 4.2 range below 4.2.25. Backend uses annotations; limited text inspection does not prove user control or non-applicability. |
| High | [GHSA-qw25-v68c-qjf3](https://github.com/advisories/GHSA-qw25-v68c-qjf3) (`CVE-2025-64458`) | Windows redirect DoS. Linux Dockerfiles suggest a platform mismatch, but actual release platform is unverified. Candidate-specific applicability evidence remains necessary. |
| Medium | `GHSA-q238-5cxm-5c9h`, `GHSA-crhf-3pfg-w68w`, `GHSA-8qcx-xf44-272x` | GeoDjango geometry DoS, GDALRaster memory over-read, domain-validator newline handling. Review untrusted geometry/raster/URL entry points for availability/disclosure impact. |
| Low | `GHSA-3h9f-r86x-qvjx`, `GHSA-h7pc-vwp9-298g`, `GHSA-8cjm-8mp7-r2xf`, `GHSA-923m-gv2p-w5qp`, `GHSA-q95w-c7qg-hrff` | Cache privacy, signed-cookie namespace and archive traversal findings require configuration/code-path review for authorization/disclosure/data-loss impact. Severity alone does not justify deferral. |

Patch numbers in individual advisories are historical first fixes, not current
upgrade targets. No vulnerability was fixed or accepted as inapplicable by
this assessment. The initial list covers Django only; the follow-up below adds five direct-package queries. All other packages remain unassessed.

## Support review and prioritized acceptance plan

Official sources checked 2026-10-31:
[Django](https://www.djangoproject.com/download/) lists 4.2 unsupported since
2026-04-07 and 5.2 LTS supported through April 2028;
[Next.js](https://nextjs.org/support-policy) currently lists 15 Maintenance LTS
with security releases extended through 2027-01-31 and 16 Active LTS;
[Node](https://nodejs.org/en/about/previous-releases) lists 22 as LTS;
[Python](https://devguide.python.org/versions/) retains 3.12 in security support.
A supported line does not prove a particular patch is safe or current.
[PostgreSQL policy](https://www.postgresql.org/support/versioning/) requires
minor-release maintenance; [PostGIS support guidance](https://postgis.net/development/versions_eol/)
is approximate. Actual database/storage patch status remains unknown.

Implement these as focused issues in the owning repositories; each must pass
the sequential gates in [Launch gates](PRODUCTION_LAUNCH_GATES.md) before the
next implementation advances. Planning can proceed across lanes.

1. **Backend: mandatory supported-framework/security work.** Move to latest
   supported Django 5.2 patch on compatible patched Python 3.12 first; review
   intervening breaking changes and dependency compatibility. Temporary 4.2/
   5.0/5.1 steps are migration bridges, never launch destinations. Acceptance:
   reproducible production graph, full advisory dispositions, backend checks,
   auth/JWT/role/lifecycle/media/race/spatial tests and required cross-app gates.
2. **Candidate dependency/image evidence: mandatory before launch.** Complete
   frontend production closure and backend transitive/native resolution; scan
   immutable production images including OS and embedded Go dependencies,
   storage/init and selected edge/tunnel images. Record source, architecture,
   digests, locks/SBOM hashes, scanner/database versions/time, exit status and
   coverage. Resolve critical/high or prove release-specific non-applicability;
   review lower findings for material impact. Fresh patched bases and a
   maintained storage strategy may require separate remediation issues.
3. **Frontend bridge validation: mandatory; broader target conditional.**
   Validate Next 15.5.28 and Node 22.23.4 against fresh security/patch evidence,
   production build/startup/auth/proxy and viewport/submission/moderation tests.
   If launch or maintenance extends beyond Next 15 support, move to supported
   Next 16 before that date. Next 16/Node 24 remain M5 targets; no automatic
   deferral of security fixes follows from a presently supported bridge.
4. **Database/storage operations: mandatory patch/provenance and recovery.**
   Identify actual PostgreSQL 17/PostGIS 3.5 patches and storage provenance,
   complete scans and paired restore/spatial checks; pin accepted artifacts.
   Rehearse any patch/extension change against restored isolated data first.
   PostGIS 3.6 may follow launch only under the documented support/patch and
   spatial/recovery conditions. No database change is authorized here.
5. **Remaining modernization: conditional post-launch M5.** Python 3.14,
   Node 24, broader API/GraphQL consolidation and other retained work follow
   the explicit conditions in Launch gates. Unsupported frameworks, unsafe
   endpoints, missing basic monitoring or unreconciled served data cannot defer.

## Follow-up evidence captured at 06:54 UTC

The continuation started at root `15b57e5eb2a74c1676d14adb3ee708c62f0afc4c`
on the existing clean assessment branch, preserving its commits. A fresh fetch
confirmed remote root `development` remained
`215bd7a5c3b000d605600ed33710a0285f619c40`; `git ls-remote` confirmed both
application `development` heads still matched the full gitlinks above. This
records remote source identity, not the sources used by any running service.
The original operational checkout was not inspected or modified.

Six completed direct-package GitHub advisory queries ran from
2026-10-31T06:54:39Z to 06:54:51Z, each exit 0 and each returning fewer than
100 records (one page). The command is the same API method documented above.
Tooling: GitHub CLI 2.98.0 (2026-08-20), Python 3.12.3, Git 2.50.1;
Docker client 28.1.1 and Compose v2.35.1. Host Node v24.19.0 and Yarn 1.22.22
were inventoried only; they are not the application runtime. GitHub's live
advisory service has no exposed database snapshot/version identifier here;
per-record publication/update/withdrawal timestamps are retained. Coverage is
reviewed non-malware version matches only, without exploitability analysis.

| Direct declared package | Critical | High | Medium | Low | Records |
| --- | --- | --- | --- | --- | --- |
| Django 4.2.22 | 1 | 2 | 3 | 5 | 11 |
| Next.js 15.5.28 | 0 | 0 | 0 | 0 | 0 |
| Pillow 10.4.0 | 3 | 19 | 9 | 0 | 31 |
| urllib3 1.26.19 | 0 | 6 | 1 | 0 | 7 |
| PyJWT 2.8.0 | 1 | 2 | 4 | 0 | 7 |
| Gunicorn 23.0.0 | 0 | 0 | 0 | 0 | 0 |

These 56 package/advisory records are a partial declared-input assessment,
not findings against a resolved production graph or installed runtime. Zero
records in a direct query do not clear that package or its dependencies.
[Sanitized advisory results](M5_ADVISORY_RESULTS_20261031.json) retain every
returned public ID, severity, summary, affected range and first-fix version,
including records not individually discussed here. SHA-256:
`b4ec6a29904a45573a416c15c966064815f992c8e2a85468dd8bb90523545b29`.
First fixes are historical advisory data, not recommended upgrade targets.

Priority applicability observations, without granting exceptions:

- Pillow's [JPEG decoder overflow](https://github.com/advisories/GHSA-8g5g-8vmr-9782)
  is critical and potentially relevant: `backend/media.py` opens, verifies,
  reopens and decodes submitted image bytes. Signature, dimension and area
  checks do not establish immunity to a decoder memory defect. Review all
  accepted JPEG/PNG/WebP decoding and rendition paths against the full list.
- Critical Pillow [TIFF encoder overflow](https://github.com/advisories/GHSA-332p-7hrc-92wf)
  and [Ghostscript argument injection](https://github.com/advisories/GHSA-w889-685w-c8fh)
  depend on different formats/helpers. Current accepted signatures and
  rendition formats narrow exposure, but do not prove absence of all other
  call sites or plugins in the actual release. No platform/format exception
  is accepted here; assess native libraries and the deployed image too.
- Critical PyJWT [asymmetric-key confusion](https://github.com/advisories/GHSA-ffc3-869f-jxw9)
  needs release-configuration review. `backend/tokens.py` passes a configured
  key and an explicit singleton algorithm list; its default is HS256.
  That is useful context, not proof of safe production key/algorithm handling.
  Review third-party JWT consumers, JWK/redirect paths, parsing DoS and the
  raw-token revocation finding. Never collect the key itself as scan evidence.
- urllib3's six high findings concern response/decompression bounds,
  redirects, sensitive headers and proxy TLS. Review boto/storage clients and
  outbound request usage/configuration; availability or disclosure impact
  cannot be dismissed solely because browsers do not call this library.

Supported-framework migration and these direct-library dispositions belong
in the first bounded backend remediation lane, with media/JWT/authorization
and cross-app regression acceptance. Full transitive/native/image assessment
remains a separate mandatory evidence gate. Recheck supported patches when
implementing; none of these queries changes dependencies.

Private raw stdout/stderr and a timestamped command/exit/hash index were
captured outside Git in a mode-0700 temporary evidence directory, with
mode-0600 files. Index SHA-256:
`6411ce2392ed1e41e37dfe8f732279d35df3f00d648d04386fd7457ecdadd567`.
The evidence location is supplied privately in the implementation handoff.
This sandbox cannot publish it to the established Jenkins evidence store
without the prohibited orchestration path. Durable Jenkins archival remains
**incomplete**; temporary evidence must be retained by the operator before
cleanup. No private paths, environments, credentials or raw operational dumps
are included in the committed results.

A repeated allowlisted Docker inventory at 06:54:39Z exited 1 with socket
access denied. Scanner discovery found no Trivy, Grype, Syft, OSV Scanner or
pip-audit. No image/OS/native/Go scan ran, and no image was pulled or built.
Complete graph scanning, actual runtime identity and immutable image evidence
therefore remain open. Official Django, Next.js, Python and Node support
pages linked above were rechecked during this continuation; the support
conclusions are unchanged.

## Proportional verification

Docs-only changes preserve gitlinks, application manifests/locks and runtime
configuration. `make check-compose`, `make check-staging` and
`make check-local-staging` passed without service startup. `git diff --check`
and documentation-link validation are recorded in the PR. Follow-up reruns
passed Compose validation and 52 local-staging tests. The first staging rerun
failed (six failures/two errors) because private evidence capture inherited
umask 077, creating fixture directories as 0700 instead of the expected 0750.
With test-process umask 022, all 43 staging tests passed; no repository or
operational permissions were changed. Both attempts are retained in evidence. Application tests,
E2E, production acceptance and container scans were not run in this assessment;
required PR CI and independent exact-head review remain separate gates. No
merge or deployment is authorized by these checks.
