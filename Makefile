.PHONY: init sync status dev dev-build dev-detached stop down ps logs check check-backend check-frontend test test-backend test-backend-fresh test-frontend provision-test-users migrate codegen

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
	docker compose logs --follow backend frontend

check: check-backend check-frontend

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

provision-test-users:
	@docker compose exec -T -e SMOKEMAP_LOCAL_TEST_PASSWORD backend python manage.py provision_local_test_users

migrate:
	docker compose exec -T backend python manage.py migrate

codegen:
	docker compose exec -T frontend yarn codegen
