# Local development checkpoint

The working local-development baseline was recorded on 2026-08-10 after the complete stack, map, provisional categories and same-origin API proxy were verified.

## Application revisions

| Repository | Branch at checkpoint | Commit | Tag |
| --- | --- | --- | --- |
| `smokemap-webapp` | `staging` | `421cfc6` | `local-dev-baseline-2026-08-10` |
| `smokemap-django-backend` | `development` | `b99aefc` | `local-dev-baseline-2026-08-10` |
| Workspace orchestration | `main` | See the tag | `local-dev-baseline-2026-08-10` |

The tags are local recovery points. They are not an off-machine backup until the corresponding commits and tags are pushed to an intentional remote.

## Development-branch reconciliation

After the original checkpoint, both remote repositories were fetched and the verified baseline was reconciled onto their `development` branches:

| Repository | Development commit | Remote relationship | Tag |
| --- | --- | --- | --- |
| `smokemap-webapp` | `8c66f99` | Based on `origin/development`; 12 local commits ahead | `development-baseline-2026-08-10` |
| `smokemap-django-backend` | `974d29e` | Based on `origin/development`; 2 local commits ahead | `development-baseline-2026-08-10` |
| Workspace orchestration | See the tag | Local repository with no remote | `development-baseline-2026-08-10` |

The backend's former divergent history is preserved as `development-pre-sync-2026-08-10`, by the original baseline tag, and in the Git bundle. Neither application branch was pushed during reconciliation; publishing the ahead commits remains an explicit remote operation.

## Verified state

- Docker Compose reports the database, storage, backend and frontend healthy.
- The interactive map renders successfully.
- Browser GraphQL and viewport GeoJSON requests work through the same-origin Next.js proxy.
- A fresh schema provisions eight provisional categories.
- An empty place database returns a valid empty GeoJSON feature collection.
- Django system checks and three backend tests pass.
- Frontend TypeScript and ESLint checks pass with documented warnings.
- The frontend Jest command passes with no test files; this is not test coverage.

## Resume from the checkpoint

Start new working branches without moving the existing branches:

```sh
git switch -c work/next-milestone local-dev-baseline-2026-08-10
git -C smokemap-webapp switch -c work/next-milestone local-dev-baseline-2026-08-10
git -C smokemap-django-backend switch -c work/next-milestone local-dev-baseline-2026-08-10
docker compose up --detach --wait
make check
make test
```

Use different branch names if any of those names already exist. Never discard later work merely to return to this point; create a branch from the tag and compare or migrate changes deliberately.

For work after branch reconciliation, use `development-baseline-2026-08-10` in place of the original tag.
