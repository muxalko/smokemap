#!/bin/sh

set -eu

docker compose config --quiet

umask 077
default_compose_config_file=$(mktemp "${TMPDIR:-/tmp}/smokemap-compose-defaults.XXXXXX")
compose_config_file=$(mktemp "${TMPDIR:-/tmp}/smokemap-compose-config.XXXXXX")
trap 'rm -f "$default_compose_config_file" "$compose_config_file"' EXIT HUP INT TERM

POSTGRES_PASSWORD=validation-password \
MINIO_ROOT_USER=validation-user \
MINIO_ROOT_PASSWORD=validation-password \
MINIO_BUCKET= \
MINIO_PRIVATE_MEDIA_BUCKET= \
MINIO_API_PORT= \
DJANGO_SECRET_KEY=validation-django-secret \
NEXTAUTH_SECRET=validation-nextauth-secret \
MEDIA_CLEANUP_BATCH_SIZE= \
MEDIA_CLEANUP_INTERVAL_SECONDS= \
MEDIA_CLEANUP_TIMEOUT_SECONDS= \
MEDIA_CLEANUP_HEALTH_START_PERIOD= \
  docker compose config --format json >"$default_compose_config_file"

POSTGRES_PASSWORD=validation-password \
MINIO_ROOT_USER=validation-user \
MINIO_ROOT_PASSWORD=validation-password \
MINIO_BUCKET=smokemap-legacy-validation \
MINIO_PRIVATE_MEDIA_BUCKET=smokemap-private-validation \
MINIO_API_PORT=19090 \
DJANGO_SECRET_KEY=validation-django-secret \
NEXTAUTH_SECRET=validation-nextauth-secret \
MEDIA_CLEANUP_BATCH_SIZE=17 \
MEDIA_CLEANUP_INTERVAL_SECONDS=29 \
MEDIA_CLEANUP_TIMEOUT_SECONDS=37 \
MEDIA_CLEANUP_HEALTH_START_PERIOD=84s \
  docker compose config --format json >"$compose_config_file"

require_literal() {
  if ! grep -F -- "$1" "$compose_config_file" >/dev/null; then
    echo "Compose validation failed: $2" >&2
    exit 1
  fi
}

reject_literal() {
  if grep -F -- "$1" "$compose_config_file" >/dev/null; then
    echo "Compose validation failed: $2" >&2
    exit 1
  fi
}

require_count() {
  actual_count=$(grep -F -c -- "$1" "$compose_config_file" || true)
  if [ "$actual_count" -ne "$2" ]; then
    echo "Compose validation failed: $3" >&2
    exit 1
  fi
}

require_default_literal() {
  if ! grep -F -- "$1" "$default_compose_config_file" >/dev/null; then
    echo "Compose validation failed: $2" >&2
    exit 1
  fi
}

require_default_literal '"MINIO_BUCKET": "smokemap-images"' \
  "legacy bucket default changed"
require_default_literal '"MINIO_PRIVATE_MEDIA_BUCKET": "smokemap-media-private"' \
  "private bucket default changed"
require_default_literal '"MEDIA_CLEANUP_BATCH_SIZE": "100"' \
  "cleanup batch default changed"
require_default_literal '"MEDIA_CLEANUP_INTERVAL_SECONDS": "300"' \
  "cleanup interval default changed"
require_default_literal '"MEDIA_STORAGE_BUCKET_NAME": "smokemap-media-private"' \
  "default private bucket is not wired to the backend"
require_default_literal '"MEDIA_UPLOAD_ENDPOINT_URL": "http://localhost:9000"' \
  "default browser upload endpoint changed"

extract_service_source() {
  awk -v wanted="$1" '
    $0 == "  " wanted ":" { found = 1; print; next }
    found && /^  [[:alnum:]_-]+:$/ { exit }
    found { print }
  ' docker-compose.yaml
}

cleanup_source=$(extract_service_source media-cleanup)
backend_source=$(extract_service_source backend)
frontend_source=$(extract_service_source frontend)

require_cleanup_source() {
  if ! printf '%s\n' "$cleanup_source" | grep -F -- "$1" >/dev/null; then
    echo "Compose validation failed: $2" >&2
    exit 1
  fi
}

reject_service_source() {
  service_source=$1
  if printf '%s\n' "$service_source" | grep -F -- "$2" >/dev/null; then
    echo "Compose validation failed: $3" >&2
    exit 1
  fi
}

require_cleanup_source 'build: *backend-build' \
  "cleanup does not use the backend build"
require_cleanup_source '<<: *backend-environment' \
  "cleanup does not inherit the backend runtime environment"
require_cleanup_source '- ./smokemap-django-backend:/app' \
  "cleanup does not use the backend source mount"
require_cleanup_source '- ./scripts/dev-media-cleanup.py:/opt/smokemap-dev-media-cleanup.py:ro' \
  "cleanup runner is not mounted read-only"
require_cleanup_source 'command: ["python", "/opt/smokemap-dev-media-cleanup.py", "run"]' \
  "canonical development cleanup runner changed"
require_cleanup_source 'test: ["CMD", "python", "/opt/smokemap-dev-media-cleanup.py", "health"]' \
  "cleanup does not override inherited probes with progress health"
require_cleanup_source '/tmp:rw,noexec,nosuid,size=16m,mode=1777' \
  "cleanup status is not ephemeral"
require_cleanup_source 'stop_grace_period: 10s' \
  "cleanup shutdown grace changed"
require_cleanup_source 'condition: service_healthy' \
  "cleanup does not wait for backend health"
require_cleanup_source 'restart: unless-stopped' \
  "cleanup restart policy changed"
reject_service_source "$cleanup_source" 'ports:' \
  "cleanup publishes a host port"
reject_service_source "$backend_source" 'media-cleanup' \
  "backend depends on cleanup"
reject_service_source "$frontend_source" 'media-cleanup' \
  "frontend depends on cleanup"

require_literal '"MINIO_BUCKET": "smokemap-legacy-validation"' \
  "legacy bucket override was not rendered"
require_literal '"MINIO_PRIVATE_MEDIA_BUCKET": "smokemap-private-validation"' \
  "private bucket override was not rendered"
require_literal 'if [ \"$${MINIO_BUCKET}\" = \"$${MINIO_PRIVATE_MEDIA_BUCKET}\" ]' \
  "storage-init does not reject identical bucket names"
require_literal 'mc anonymous set download \"local/$${MINIO_BUCKET}\"' \
  "legacy bucket is not configured for anonymous download"
require_literal 'mc anonymous set private \"local/$${MINIO_PRIVATE_MEDIA_BUCKET}\"' \
  "private media bucket is not configured as anonymous-private"
reject_literal 'mc anonymous set download \"local/$${MINIO_PRIVATE_MEDIA_BUCKET}\"' \
  "private media bucket is configured for anonymous download"
reject_literal 'mc anonymous set upload \"local/$${MINIO_PRIVATE_MEDIA_BUCKET}\"' \
  "private media bucket is configured for anonymous upload"
reject_literal 'mc anonymous set public \"local/$${MINIO_PRIVATE_MEDIA_BUCKET}\"' \
  "private media bucket is configured for anonymous public access"

# The backend and cleanup service must each receive these exact legacy/private
# bindings. Counts of two catch missing wiring and accidental extra consumers.
require_count '"AWS_STORAGE_BUCKET_NAME": "smokemap-legacy-validation"' 2 \
  "legacy bucket is not wired only to backend runtimes"
require_count '"AWS_S3_ENDPOINT_URL": "http://localhost:19090"' 2 \
  "legacy endpoint is not preserved on backend runtimes"
require_count '"AWS_S3_ADDRESSING_STYLE": "path"' 2 \
  "path-style S3 addressing is not set on backend runtimes"
require_count '"MEDIA_STORAGE_BUCKET_NAME": "smokemap-private-validation"' 2 \
  "private bucket is not wired to backend and cleanup"
require_count '"MEDIA_STORAGE_IDENTIFIER": "smokemap-local-private-media-v1"' 2 \
  "stable local media identifier is not wired to backend and cleanup"
require_count '"MEDIA_STORAGE_INTERNAL_ENDPOINT_URL": "http://storage:9000"' 2 \
  "internal media endpoint is not wired to backend and cleanup"
require_count '"MEDIA_UPLOAD_ENDPOINT_URL": "http://localhost:19090"' 2 \
  "browser media endpoint is not wired to backend and cleanup"

require_literal '"MEDIA_CLEANUP_BATCH_SIZE": "17"' \
  "cleanup batch override was not rendered"
require_literal '"MEDIA_CLEANUP_INTERVAL_SECONDS": "29"' \
  "cleanup interval override was not rendered"
require_default_literal '"MEDIA_CLEANUP_TIMEOUT_SECONDS": "120"' \
  "cleanup timeout default changed"
require_default_literal '"start_period": "4m10s"' \
  "cleanup startup grace default changed"
require_literal '"MEDIA_CLEANUP_TIMEOUT_SECONDS": "37"' \
  "cleanup timeout override was not rendered"
require_literal '"start_period": "1m24s"' \
  "cleanup startup grace override was not rendered"
require_literal '"media-cleanup": {' "media-cleanup service is missing"

python3 -I - "$compose_config_file" "$default_compose_config_file" <<'PYTHON'
import json
import sys

def validate(path, start_period, expected_config):
    with open(path) as stream:
        services = json.load(stream)["services"]
    worker = services["media-cleanup"]
    for key, expected in zip(("MEDIA_CLEANUP_BATCH_SIZE", "MEDIA_CLEANUP_INTERVAL_SECONDS",
                              "MEDIA_CLEANUP_TIMEOUT_SECONDS"), expected_config):
        assert worker["environment"][key] == expected
        assert key not in services["backend"]["environment"]
    assert worker["command"] == ["python", "/opt/smokemap-dev-media-cleanup.py", "run"]
    assert worker["healthcheck"] == {
        "test": ["CMD", "python", "/opt/smokemap-dev-media-cleanup.py", "health"],
        "interval": "5s", "timeout": "3s", "retries": 1, "start_period": start_period,
    }
    assert worker["restart"] == "unless-stopped" and not worker.get("ports")
    assert worker["depends_on"]["backend"]["condition"] == "service_healthy"
    mounts = {v["target"]: v for v in worker["volumes"]}
    assert set(mounts) == {"/app", "/opt/smokemap-dev-media-cleanup.py"}
    assert mounts["/app"]["source"] == next(
        v["source"] for v in services["backend"]["volumes"] if v["target"] == "/app")
    runner = mounts["/opt/smokemap-dev-media-cleanup.py"]
    assert runner["type"] == "bind" and runner["read_only"] is True
    assert runner["source"].endswith("/scripts/dev-media-cleanup.py")
    assert worker["tmpfs"] == ["/tmp:rw,noexec,nosuid,size=16m,mode=1777"]
    for name in ("backend", "frontend"):
        assert not any(v["target"] == "/opt/smokemap-dev-media-cleanup.py"
                       for v in services[name]["volumes"])
        assert "media-cleanup" not in services[name].get("depends_on", {})
    assert worker["stop_grace_period"] == "10s"

try:
    validate(sys.argv[1], "1m24s", ("17", "29", "37"))
    validate(sys.argv[2], "4m10s", ("100", "300", "120"))
except (AssertionError, KeyError, TypeError, ValueError, StopIteration):
    sys.exit("Compose validation failed: development cleanup contract")
PYTHON

echo "Compose media storage and cleanup wiring is valid."
