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

See [AGENTS.md](AGENTS.md) for the complete development, security and verification rules.
