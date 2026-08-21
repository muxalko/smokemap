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
validate the Docker Compose configuration, and scan the full workspace history
with Gitleaks. Secret-scan findings are redacted from CI output.

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
