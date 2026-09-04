.PHONY: init sync status dev dev-build dev-detached stop down ps logs check check-compose check-backend check-frontend test test-backend test-backend-fresh test-frontend test-e2e test-e2e-submission-media provision-test-users migrate codegen

E2E_COMPOSE = docker compose -f docker-compose.yaml -f e2e/docker-compose.e2e.yaml --project-name smokemap-e2e
E2E_SUBMISSION_COMPOSE = docker compose -f docker-compose.yaml -f e2e/docker-compose.e2e.yaml --project-name smokemap-e2e-submission-media

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

check-backend:
	docker compose exec -T backend python manage.py check

check-frontend:
	docker compose exec -T frontend yarn run check

test: test-backend test-frontend

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

provision-test-users:
	@docker compose exec -T -e SMOKEMAP_LOCAL_TEST_PASSWORD backend python manage.py provision_local_test_users

migrate:
	docker compose exec -T backend python manage.py migrate

codegen:
	docker compose exec -T frontend yarn codegen
