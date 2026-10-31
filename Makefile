.PHONY: init sync status dev dev-build dev-detached stop down ps logs check check-compose check-staging staging-preflight check-local-staging local-staging-home local-staging-init local-staging-build local-staging-releases local-staging-preflight local-staging-migrate local-staging-start local-staging-stop local-staging-down local-staging-status local-staging-smoke local-staging-backup local-staging-restore local-staging-rollback check-backend check-frontend test test-backend test-backend-fresh test-frontend test-e2e test-e2e-submission-media test-e2e-public-media provision-test-users migrate codegen

LOCAL_STAGING = python3 scripts/local-staging.py --home "$(LOCAL_STAGING_HOME)"

E2E_COMPOSE = docker compose -f docker-compose.yaml -f e2e/docker-compose.e2e.yaml --project-name smokemap-e2e
E2E_SUBMISSION_COMPOSE = docker compose -f docker-compose.yaml -f e2e/docker-compose.e2e.yaml --project-name smokemap-e2e-submission-media
E2E_PUBLIC_MEDIA_COMPOSE = docker compose -f docker-compose.yaml -f e2e/docker-compose.e2e.yaml --project-name smokemap-e2e-public-media

init:
	git submodule update --init --recursive

sync:
	git submodule sync --recursive
	git submodule update --init --recursive

status:
	git status --short --branch
	git submodule status --recursive

dev:
	docker compose up --build

dev-build:
	docker compose build

dev-detached:
	docker compose up --build --detach --wait

stop:
	docker compose stop

down:
	docker compose down --remove-orphans

ps:
	docker compose ps

logs:
	docker compose logs --follow backend media-cleanup frontend

check: check-compose check-backend check-frontend

check-compose:
	./scripts/validate-compose.sh

check-staging:
	python3 scripts/validate-staging.py --template
	python3 -m unittest discover -s tests -p 'test_validate_staging.py' -v

.PHONY: test-staging-postgis test-staging-cleanup
test-staging-postgis:
	python3 -m unittest discover -s tests -p 'test_staging_postgis.py' -v

test-staging-cleanup:
	python3 -m unittest discover -s tests -p 'test_staging_cleanup.py' -v

staging-preflight:
	@test -n "$(STAGING_ENV_FILE)" || { \
		echo "Set STAGING_ENV_FILE to the absolute path of the staging environment file." >&2; \
		exit 64; \
	}
	python3 scripts/validate-staging.py --env-file "$(STAGING_ENV_FILE)"

check-local-staging:
	python3 scripts/validate-local-staging.py --template
	python3 -m unittest discover -s tests -p 'test_local_staging.py' -v

local-staging-home:
	@test -n "$(LOCAL_STAGING_HOME)" || { \
		echo "Set LOCAL_STAGING_HOME to an absolute directory outside every Git working tree." >&2; \
		exit 64; \
	}

local-staging-init: local-staging-home
	$(LOCAL_STAGING) init --https-port "$(or $(HTTPS_PORT),8443)" $(if $(SECRET_GID),--secret-gid "$(SECRET_GID)")

local-staging-build local-staging-releases local-staging-start local-staging-stop local-staging-down local-staging-status local-staging-smoke: local-staging-home
	$(LOCAL_STAGING) $(patsubst local-staging-%,%,$@)

local-staging-preflight: local-staging-home
	$(LOCAL_STAGING) preflight $(if $(RELEASE),--release "$(RELEASE)")

local-staging-migrate local-staging-rollback: local-staging-home
	$(LOCAL_STAGING) $(patsubst local-staging-%,%,$@) --release "$(RELEASE)"

local-staging-backup: local-staging-home
	$(LOCAL_STAGING) backup $(if $(LABEL),--label "$(LABEL)")

local-staging-restore: local-staging-home
	$(LOCAL_STAGING) restore --backup "$(BACKUP)" --confirm "$(CONFIRM)"

check-backend:
	docker compose exec -T backend python manage.py check

check-frontend:
	docker compose exec -T frontend yarn run check

test: test-dev-cleanup test-dev-cleanup-alert test-backend test-frontend

test-backend:
	docker compose exec -T -e POSTGRES_OPTIONS="-c search_path=public" backend python manage.py test --keepdb

test-backend-fresh:
	docker compose exec -T -e POSTGRES_OPTIONS="-c search_path=public" backend python manage.py test --noinput

test-frontend:
	docker compose exec -T frontend yarn test:ci

test-e2e:
	@set -eu; \
	cleanup() { \
		$(E2E_COMPOSE) exec -T \
			-e SMOKEMAP_E2E_FIXTURE_ACTION=cleanup \
			backend python manage.py shell < e2e/viewport-fixtures.py || true; \
		$(E2E_COMPOSE) down --remove-orphans; \
	}; \
	trap cleanup EXIT HUP INT TERM; \
	$(E2E_COMPOSE) up --build --detach --wait \
		db storage storage-init backend frontend; \
	$(E2E_COMPOSE) exec -T \
		-e SMOKEMAP_E2E_FIXTURE_ACTION=seed \
		backend python manage.py shell < e2e/viewport-fixtures.py; \
	$(E2E_COMPOSE) run --rm --no-deps e2e; \
	$(E2E_COMPOSE) exec -T \
		-e SMOKEMAP_E2E_FIXTURE_ACTION=cleanup \
		backend python manage.py shell < e2e/viewport-fixtures.py; \
	$(E2E_COMPOSE) down --remove-orphans; \
	trap - EXIT HUP INT TERM

test-e2e-submission-media:
	@set -eu; \
	cleanup() { \
		$(E2E_SUBMISSION_COMPOSE) exec -T \
			-e SMOKEMAP_E2E_FIXTURE_ACTION=cleanup \
			backend python manage.py shell < e2e/submission-media-fixtures.py || true; \
		$(E2E_SUBMISSION_COMPOSE) down --remove-orphans; \
	}; \
	trap cleanup EXIT HUP INT TERM; \
	$(E2E_SUBMISSION_COMPOSE) up --build --detach --wait \
		db storage storage-init backend frontend; \
	$(E2E_SUBMISSION_COMPOSE) exec -T \
		-e SMOKEMAP_E2E_FIXTURE_ACTION=cleanup \
		backend python manage.py shell < e2e/submission-media-fixtures.py; \
	$(E2E_SUBMISSION_COMPOSE) exec -T -e SMOKEMAP_LOCAL_TEST_PASSWORD \
		backend python manage.py provision_local_test_users; \
	$(E2E_SUBMISSION_COMPOSE) run --rm --no-deps -e SMOKEMAP_LOCAL_TEST_PASSWORD \
		e2e e2e/submission-media.mjs; \
	$(E2E_SUBMISSION_COMPOSE) exec -T \
		-e SMOKEMAP_E2E_FIXTURE_ACTION=verify \
		backend python manage.py shell < e2e/submission-media-fixtures.py; \
	$(E2E_SUBMISSION_COMPOSE) exec -T \
		-e SMOKEMAP_E2E_FIXTURE_ACTION=cleanup \
		backend python manage.py shell < e2e/submission-media-fixtures.py; \
	$(E2E_SUBMISSION_COMPOSE) down --remove-orphans; \
	trap - EXIT HUP INT TERM

test-e2e-public-media:
	@set -eu; \
	cleanup() { \
		$(E2E_PUBLIC_MEDIA_COMPOSE) exec -T \
			-e SMOKEMAP_E2E_FIXTURE_ACTION=cleanup \
			backend python manage.py shell < e2e/public-media-fixtures.py || true; \
		$(E2E_PUBLIC_MEDIA_COMPOSE) down --remove-orphans; \
	}; \
	trap cleanup EXIT HUP INT TERM; \
	$(E2E_PUBLIC_MEDIA_COMPOSE) up --build --detach --wait \
		db storage storage-init backend frontend; \
	$(E2E_PUBLIC_MEDIA_COMPOSE) exec -T \
		backend chmod 1777 /workspace-e2e-state; \
	$(E2E_PUBLIC_MEDIA_COMPOSE) exec -T \
		-e SMOKEMAP_E2E_FIXTURE_ACTION=cleanup \
		backend python manage.py shell < e2e/public-media-fixtures.py; \
	$(E2E_PUBLIC_MEDIA_COMPOSE) exec -T -e SMOKEMAP_LOCAL_TEST_PASSWORD \
		backend python manage.py provision_local_test_users; \
	$(E2E_PUBLIC_MEDIA_COMPOSE) run --rm --no-deps \
		-e SMOKEMAP_LOCAL_TEST_PASSWORD \
		-e SMOKEMAP_E2E_PHASE=create \
		e2e e2e/public-after-approval.mjs; \
	$(E2E_PUBLIC_MEDIA_COMPOSE) exec -T \
		-e SMOKEMAP_E2E_FIXTURE_ACTION=verify_pending \
		backend python manage.py shell < e2e/public-media-fixtures.py; \
	$(E2E_PUBLIC_MEDIA_COMPOSE) run --rm --no-deps \
		-e SMOKEMAP_LOCAL_TEST_PASSWORD \
		-e SMOKEMAP_E2E_PHASE=lifecycle \
		e2e e2e/public-after-approval.mjs; \
	$(E2E_PUBLIC_MEDIA_COMPOSE) exec -T \
		-e SMOKEMAP_E2E_FIXTURE_ACTION=verify_final \
		backend python manage.py shell < e2e/public-media-fixtures.py; \
	$(E2E_PUBLIC_MEDIA_COMPOSE) exec -T \
		-e SMOKEMAP_E2E_FIXTURE_ACTION=cleanup \
		backend python manage.py shell < e2e/public-media-fixtures.py; \
	$(E2E_PUBLIC_MEDIA_COMPOSE) down --remove-orphans; \
	trap - EXIT HUP INT TERM

provision-test-users:
	@docker compose exec -T -e SMOKEMAP_LOCAL_TEST_PASSWORD backend python manage.py provision_local_test_users

migrate:
	docker compose exec -T backend python manage.py migrate

codegen:
	docker compose exec -T frontend yarn codegen

# Pure rendering/unit evidence; never starts a Quick Tunnel.
.PHONY: check-quick-staging
check-quick-staging:
	python3 scripts/validate-quick-staging.py --template
	python3 -m unittest discover -s tests -p 'test_quick_staging.py' -v

# Python stdlib only; no Docker, database or storage.
.PHONY: test-dev-cleanup test-dev-cleanup-compose
test-dev-cleanup:
	python3 -m unittest discover -s tests -p 'test_dev_cleanup.py' -v

test-dev-cleanup-compose:
	python3 -m unittest discover -s tests -p 'test_dev_cleanup_compose.py' -v

# Python stdlib only; fake Docker CLI and SMTP, never network, mail or Docker.
.PHONY: test-dev-cleanup-alert
test-dev-cleanup-alert:
	python3 -m unittest discover -s tests -p 'test_dev_cleanup_alert.py' -v

# Source-only monitoring tests: mock network/commands; synthetic read-only DB.
.PHONY: test-monitoring
test-monitoring:
	python3 -m unittest discover -s tests -p 'test_monitoring.py' -v
