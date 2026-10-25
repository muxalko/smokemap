#!/usr/bin/env python3
"""Render and validate the staging contract without starting any services."""

from __future__ import annotations

import argparse
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "deploy" / "staging" / "compose.yaml"
TEMPLATE_FILE = ROOT / "deploy" / "staging" / ".env.example"
README_FILE = ROOT / "deploy" / "staging" / "README.md"
RUNTIME_PROFILE = "staging-runtime"
MIGRATION_PROFILE = "staging-migration"
COMPOSE_PREFIX = (
    'docker compose --env-file "$STAGING_ENV_FILE" -f deploy/staging/compose.yaml'
)
MIGRATION_COMMAND = (
    f"{COMPOSE_PREFIX} --profile {RUNTIME_PROFILE} --profile {MIGRATION_PROFILE}"
    " run --rm migrate"
)
RUNTIME_COMMAND = f"{COMPOSE_PREFIX} --profile {RUNTIME_PROFILE} up --detach --wait"
EXPECTED_SERVICES = {
    "backend",
    "cloudflared",
    "db",
    "frontend",
    "media-cleanup",
    "migrate",
    "storage",
    "storage-init",
}
EXPECTED_SECRETS = {
    "cloudflared_token",
    "django_secret_key",
    "minio_root_password",
    "minio_root_user",
    "nextauth_secret",
    "postgres_password",
    "postgres_tls_ca",
    "postgres_tls_certificate",
    "postgres_tls_private_key",
    "storage_access_key",
    "storage_secret_key",
}
# Secrets exported through "$(cat ...)", which strips only trailing newlines;
# the applications reject any other surrounding whitespace.
EXPORTED_SECRETS = {
    "django_secret_key",
    "minio_root_password",
    "minio_root_user",
    "nextauth_secret",
    "postgres_password",
    "storage_access_key",
    "storage_secret_key",
}
SECRET_MINIMUM_LENGTHS = {"django_secret_key": 50, "nextauth_secret": 32}
EXPECTED_VOLUMES = {"minio-data", "postgres-data"}
EXPECTED_NETWORKS = {
    "application",
    "database",
    "edge",
    "ingress",
    "media",
    "media-ingress",
}
IMMUTABLE_IMAGE = re.compile(r"^[^\s:@]+(?:/[^\s:@]+)+@sha256:[0-9a-f]{64}$")
PLACEHOLDER_DIGEST = "0" * 64
SOURCE_REVISION = re.compile(r"[0-9a-f]{40}")
PLACEHOLDER_REVISION = "0" * 40

# Backend staging settings reject development service names, so each
# backend-facing service is reached through one fixed private alias.
DATABASE_ALIAS = "postgis.smokemap-staging.internal"
STORAGE_ALIAS = "objects.smokemap-staging.internal"
BACKEND_ALIAS = "api.smokemap-staging.internal"
EXPECTED_ALIASES = {
    ("db", "database"): [DATABASE_ALIAS],
    ("storage", "media"): [STORAGE_ALIAS],
    ("backend", "application"): [BACKEND_ALIAS],
}
# Mirrors the backend's rejected development hosts for regression tests.
BACKEND_DEVELOPMENT_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
    "backend",
    "db",
    "minio",
    "postgres",
    "storage",
}
BACKEND_SERVICES = ("backend", "media-cleanup", "migrate")
BACKEND_CONTRACT = {
    "SETTINGS_MODE": "staging",
    "DJANGO_ALLOWED_HOSTS": BACKEND_ALIAS,
    "DJANGO_TRUST_X_FORWARDED_PROTO": "true",
    "POSTGRES_HOST": DATABASE_ALIAS,
    "POSTGRES_PORT": "5432",
    "POSTGRES_OPTIONS": "-c search_path=smokemap,public",
    "POSTGRES_SSLMODE": "verify-full",
    "PGSSLROOTCERT": "/run/secrets/postgres_tls_ca",
    "AWS_S3_ADDRESSING_STYLE": "path",
    "MEDIA_STORAGE_INTERNAL_ENDPOINT_URL": f"http://{STORAGE_ALIAS}:9000",
}
BACKEND_READINESS_PROBE = (
    "'http://127.0.0.1:8000/health/ready/'",
    f"'Host': '{BACKEND_ALIAS}'",
    "'X-Forwarded-Proto': 'https'",
)
# Pin the whole mapping so disabled, inherited HTTP, and self-PID probes fail
# closed in both external and local staging. This says nothing about batches.
CLEANUP_HEALTHCHECK = {
    "test": ["CMD", "python", "-c", "import os; os.kill(1, 0)"],
    "interval": "10s",
    "timeout": "5s",
    "retries": 3,
    "start_period": "5s",
}
FRONTEND_CONTRACT = {
    "NODE_ENV": "production",
    "NEXT_PUBLIC_ENVIRONMENT": "staging",
    "NEXT_PUBLIC_BACKEND": "/api/smokemap",
    "NEXT_PUBLIC_GRAPHQL_ENDPOINT": "/api/smokemap/graphql",
    "NEXT_PUBLIC_FEATURESERV_ENDPOINT": "/api/smokemap/locations",
    "BACKEND_INTERNAL_URL": f"http://{BACKEND_ALIAS}:8000",
    "GRAPHQL_INTERNAL_ENDPOINT": f"http://{BACKEND_ALIAS}:8000/graphql/",
}
FRONTEND_LOG_LEVELS = {"trace", "debug", "info", "warn", "error", "fatal"}
DATABASE_TLS_DIRECTORY = "/run/postgresql-tls"
DATABASE_TLS_ARGUMENTS = (
    "postgres -c ssl=on",
    f"-c ssl_cert_file={DATABASE_TLS_DIRECTORY}/server.crt",
    f"-c ssl_key_file={DATABASE_TLS_DIRECTORY}/server.key",
)


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def compose_config(
    env_file: Path,
    compose_file: Path,
    *,
    extra_args: tuple[str, ...] = (),
    profiles: tuple[str, ...] = (RUNTIME_PROFILE, MIGRATION_PROFILE),
) -> dict:
    profile_args = [
        argument for profile in profiles for argument in ("--profile", profile)
    ]
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(compose_file),
            *profile_args,
            "config",
            *extra_args,
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        fail(f"Docker Compose could not render the staging contract: {detail}")
    return json.loads(result.stdout)


def render(env_file: Path, *, compose_file: Path = COMPOSE_FILE) -> dict:
    source_config = compose_config(
        env_file,
        compose_file,
        extra_args=("--no-interpolate", "--no-normalize", "--no-env-resolution"),
    )
    for name, service in source_config.get("services", {}).items():
        if service.get("env_file"):
            fail(f"{name} must not load an unreviewed environment file")
    return compose_config(env_file, compose_file)


def is_public_hostname(hostname: str) -> bool:
    try:
        ip_address(hostname)
    except ValueError:
        return "." in hostname and not hostname.endswith(
            (".local", ".localhost", ".internal")
        )
    return False


def require_https_url(value: str, label: str, *, origin_only: bool) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        fail(f"{label} must be a valid HTTPS URL")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not is_public_hostname(parsed.hostname)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (origin_only and (port not in (None, 443) or parsed.path))
    ):
        if origin_only:
            fail(
                f"{label} must be an exact public HTTPS origin without credentials, "
                "path, trailing slash, query, or non-default port"
            )
        fail(f"{label} must be a public HTTPS URL without credentials, query, or fragment")
    return parsed.hostname


def require_https_origin(value: str, label: str) -> str:
    return require_https_url(value, label, origin_only=True)


def command_text(service: dict) -> str:
    entrypoint = service.get("entrypoint") or []
    command = service.get("command") or []
    if isinstance(entrypoint, str):
        entrypoint = [entrypoint]
    if isinstance(command, str):
        command = [command]
    return " ".join([*entrypoint, *command])


def secret_group_id(services: dict) -> int:
    groups = {
        tuple(str(group) for group in service.get("group_add", []))
        for service in services.values()
        if service.get("secrets")
    }
    if len(groups) != 1:
        fail("secret-consuming services must share one explicit supplemental group")
    group = next(iter(groups))
    if len(group) != 1 or not group[0].isdigit() or int(group[0]) == 0:
        fail("staging secret access must use one positive numeric supplemental group")
    return int(group[0])


def service_secrets(service: dict) -> set[str]:
    return {
        secret["source"] if isinstance(secret, dict) else secret
        for secret in service.get("secrets", [])
    }


def validate_aliases(services: dict) -> None:
    for service_name, service in services.items():
        for network_name, network in (service.get("networks") or {}).items():
            aliases = (network or {}).get("aliases") or []
            if aliases != EXPECTED_ALIASES.get((service_name, network_name), []):
                fail(f"{service_name} private alias on {network_name} changed")


def validate_backend_contract(services: dict) -> dict:
    environments = [services[name].get("environment", {}) for name in BACKEND_SERVICES]
    shared = {
        key: value
        for key, value in environments[0].items()
        if not key.startswith("MEDIA_CLEANUP_")
    }
    for name, environment in zip(BACKEND_SERVICES, environments):
        own = {
            key: value
            for key, value in environment.items()
            if not key.startswith("MEDIA_CLEANUP_")
        }
        if own != shared:
            fail(f"{name} must receive the same backend staging environment")
        if "postgres_tls_ca" not in service_secrets(services[name]):
            fail(f"{name} must mount the PostgreSQL TLS trust anchor")

    for key, expected in BACKEND_CONTRACT.items():
        if shared.get(key) != expected:
            fail(f"backend {key} must be {expected!r} for the production contract")
    if "ALLOWED_HOSTS" in shared:
        fail("backend must use DJANGO_ALLOWED_HOSTS, not the ignored ALLOWED_HOSTS")
    return shared


def validate_database_tls(services: dict) -> None:
    database = services["db"]
    if DATABASE_TLS_DIRECTORY not in database.get("tmpfs", []):
        fail("PostgreSQL TLS material must be copied to a memory-backed directory")
    database_command = command_text(database)
    if any(argument not in database_command for argument in DATABASE_TLS_ARGUMENTS):
        fail("PostgreSQL must serve TLS from its certificate and private key")
    if not {"postgres_tls_certificate", "postgres_tls_private_key"} <= service_secrets(
        database
    ):
        fail("PostgreSQL must mount its TLS certificate and private key")
    for name, service in services.items():
        if name != "db" and "postgres_tls_private_key" in service_secrets(service):
            fail(f"{name} must not mount the PostgreSQL TLS private key")


def validate_frontend_contract(
    services: dict, backend_env: dict, *, allow_placeholders: bool
) -> None:
    frontend_env = services["frontend"].get("environment", {})
    for key, expected in FRONTEND_CONTRACT.items():
        if frontend_env.get(key) != expected:
            fail(f"frontend {key} must be {expected!r} for the production contract")

    app_url = frontend_env.get("NEXT_PUBLIC_BASE_URL", "")
    require_https_origin(app_url, "STAGING_APP_URL")
    if frontend_env.get("NEXTAUTH_URL") != app_url:
        fail("frontend NEXTAUTH_URL must equal NEXT_PUBLIC_BASE_URL exactly")
    for key in ("CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS"):
        if backend_env.get(key) != app_url:
            fail(f"backend {key} must equal the frontend public origin exactly")

    version = str(frontend_env.get("NEXT_PUBLIC_VERSION", ""))
    if not SOURCE_REVISION.fullmatch(version):
        fail("RELEASE_VERSION must be the full lowercase 40-hex frontend source commit")
    if not allow_placeholders and version == PLACEHOLDER_REVISION:
        fail("RELEASE_VERSION still uses the placeholder commit")

    require_https_url(
        frontend_env.get("NEXT_PUBLIC_MAP_STYLE", ""),
        "NEXT_PUBLIC_MAP_STYLE",
        origin_only=False,
    )
    if frontend_env.get("NEXT_PUBLIC_LOG_LEVEL") not in FRONTEND_LOG_LEVELS:
        fail("LOG_LEVEL must be a frontend production log level")


def validate_migration(services: dict) -> None:
    migration = command_text(services["migrate"])
    check_index = migration.find("python manage.py check --deploy")
    migrate_index = migration.find("python manage.py migrate --noinput")
    if check_index < 0 or migrate_index < check_index:
        fail("migration must run the deployment check before migrate --noinput")
    dependencies = services["migrate"].get("depends_on", {})
    if (
        dependencies.get("db", {}).get("condition") != "service_healthy"
        or dependencies.get("storage-init", {}).get("condition")
        != "service_completed_successfully"
    ):
        fail("migration must wait for PostgreSQL and storage initialization")
    ordering = services["backend"].get("depends_on", {}).get("migrate", {})
    if (
        ordering.get("condition") != "service_completed_successfully"
        or ordering.get("required") is not False
    ):
        fail("backend must start only after a selected migration job completes")


def validate_service_isolation(name: str, service: dict) -> None:
    """Privilege, mount, and secret rules shared by every staging mode."""

    if service.get("privileged"):
        fail(f"{name} must not run privileged")
    if service.get("cap_add"):
        fail(f"{name} must not add Linux capabilities")
    if service.get("pid"):
        fail(f"{name} must not join another PID namespace")
    if service.get("env_file"):
        fail(f"{name} must not load an unreviewed environment file")
    for mount in service.get("volumes", []):
        if mount.get("type") == "bind":
            fail(f"{name} contains an unexpected host bind mount")
    for secret in service.get("secrets", []):
        if isinstance(secret, dict) and secret.get("target") not in (
            None,
            f"/run/secrets/{secret['source']}",
        ):
            fail(f"{name} must mount each secret at its default path")
    for key, value in service.get("environment", {}).items():
        if any(marker in key for marker in ("PASSWORD", "SECRET", "TOKEN", "ACCESS_KEY")):
            if not key.endswith("_FILE") or not str(value).startswith("/run/secrets/"):
                fail(f"{name} places sensitive input {key} in its environment")
    lowered = command_text(service).lower()
    for forbidden in ("runserver", "yarn dev", "next dev", "makemigrations"):
        if forbidden in lowered:
            fail(f"{name} contains forbidden development command: {forbidden}")


def validate_anonymous_storage_policy(service: dict) -> None:
    """Pin the object-only public policy separately from authenticated app IAM."""

    command = command_text(service)
    match = re.search(
        r'cat >"\$\$\{policy_file\}" <<PUBLIC_READ_POLICY\n(.*?)\nPUBLIC_READ_POLICY\n',
        command,
        re.DOTALL,
    )
    try:
        policy = json.loads(match.group(1)) if match else None
    except ValueError:
        policy = None
    expected = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::$${MINIO_BUCKET}/*"],
        }],
    }
    anonymous_commands = [
        line.strip() for line in command.splitlines() if "mc anonymous" in line
    ]
    if policy != expected or anonymous_commands != [
        'mc anonymous set-json "$${policy_file}" "local/$${MINIO_BUCKET}"',
        'mc anonymous set private "local/$${MINIO_PRIVATE_MEDIA_BUCKET}"',
    ]:
        fail(
            "storage-init must install only anonymous GetObject on public objects "
            "and keep private media private"
        )


def validate_runtime_contract(services: dict, backend_env: dict) -> None:
    """MinIO exposure, readiness, and production-server rules for every mode."""

    validate_anonymous_storage_policy(services["storage-init"])
    if services["media-cleanup"].get("healthcheck") != CLEANUP_HEALTHCHECK:
        fail("media-cleanup must use the exact PID 1 process-only healthcheck")

    storage = services["storage"]
    storage_env = storage.get("environment", {})
    if storage_env.get("MINIO_API_CORS_ALLOW_ORIGIN") != backend_env.get(
        "CORS_ALLOWED_ORIGINS"
    ):
        fail("MinIO API CORS must match the exact staging application origin")
    if storage_env.get("MINIO_BROWSER") != "off" or "--console-address" in command_text(storage):
        fail("the MinIO browser console must remain disabled")
    if "mc cors" in command_text(services["storage-init"]).lower():
        fail("storage initialization must not call the unsupported mc cors command")

    backend_healthcheck = " ".join(
        services["backend"].get("healthcheck", {}).get("test", [])
    )
    if any(marker not in backend_healthcheck for marker in BACKEND_READINESS_PROBE):
        fail(
            "backend readiness must send the allowed Host and trusted "
            "X-Forwarded-Proto headers"
        )

    if "gunicorn" not in command_text(services["backend"]):
        fail("backend must use the production WSGI server contract")
    if "yarn start" not in command_text(services["frontend"]):
        fail("frontend must use the production server contract")


def validate_structure(config: dict, *, allow_placeholders: bool) -> None:
    if config.get("name") != "smokemap-staging":
        fail("the reviewed staging project name must remain smokemap-staging")

    services = config.get("services", {})
    if set(services) != EXPECTED_SERVICES:
        fail("staging services differ from the reviewed topology")

    secrets = config.get("secrets", {})
    if set(secrets) != EXPECTED_SECRETS:
        fail("staging secrets differ from the reviewed file-backed set")
    for name, secret in secrets.items():
        if "file" not in secret or not set(secret) <= {"file", "name"}:
            fail(f"{name} must remain a local file-backed Compose secret")

    configs = config.get("configs", {})
    if (
        set(configs) != {"postgres_init"}
        or "file" not in configs["postgres_init"]
        or not set(configs["postgres_init"]) <= {"file", "name"}
    ):
        fail("PostgreSQL schema initialization must remain a single file-backed Compose config")

    for name, service in services.items():
        if "build" in service:
            fail(f"{name} must use a published image, not a local build")
        image = service.get("image", "")
        if not IMMUTABLE_IMAGE.fullmatch(image):
            fail(f"{name} image is not an immutable sha256 reference")
        if not allow_placeholders and (
            image.startswith("example.invalid/") or image.endswith(PLACEHOLDER_DIGEST)
        ):
            fail(f"{name} still uses a placeholder image")
        if service.get("ports") or service.get("expose"):
            fail(f"{name} must not publish or expose a port")
        validate_service_isolation(name, service)

    secret_group_id(services)

    if services["migrate"].get("profiles") != ["staging-migration"]:
        fail("migration must remain an explicitly selected one-shot profile")
    for name in EXPECTED_SERVICES - {"migrate"}:
        if services[name].get("profiles") != ["staging-runtime"]:
            fail(f"{name} must remain behind the explicit staging-runtime profile")

    networks = config.get("networks", {})
    if set(networks) != EXPECTED_NETWORKS:
        fail("staging networks differ from the reviewed topology")
    for name in ("application", "database", "ingress", "media", "media-ingress"):
        if not networks.get(name, {}).get("internal"):
            fail(f"{name} network must remain internal")
    if networks.get("edge", {}).get("internal"):
        fail("edge network must permit the tunnel's outbound connection")

    volumes = config.get("volumes", {})
    if set(volumes) != EXPECTED_VOLUMES:
        fail("staging volumes differ from the reviewed named-volume set")
    for name, volume in volumes.items():
        if volume.get("driver_opts"):
            fail(f"{name} must not use driver options that can create a host bind mount")

    expected_networks = {
        "db": {"database"},
        "storage": {"media", "media-ingress"},
        "storage-init": {"media"},
        "migrate": {"application", "database", "media"},
        "backend": {"application", "database", "media"},
        "media-cleanup": {"database", "media"},
        "frontend": {"application", "ingress"},
        "cloudflared": {"edge", "ingress", "media-ingress"},
    }
    for service_name, wanted in expected_networks.items():
        if set(services[service_name].get("networks", {})) != wanted:
            fail(f"{service_name} network reachability changed")

    tunnel = services["cloudflared"]
    tunnel_command = command_text(tunnel)
    if "--token-file /run/secrets/cloudflared_token" not in tunnel_command:
        fail("cloudflared must read its remotely managed tunnel token from a secret file")
    if any("TOKEN" in key for key in tunnel.get("environment", {})):
        fail("cloudflared token must not be placed in the environment")

    validate_aliases(services)
    backend_env = validate_backend_contract(services)
    validate_database_tls(services)
    validate_frontend_contract(
        services, backend_env, allow_placeholders=allow_placeholders
    )
    validate_migration(services)

    app_host = require_https_origin(backend_env.get("CORS_ALLOWED_ORIGINS", ""), "STAGING_APP_URL")
    media_host = require_https_origin(backend_env.get("MEDIA_UPLOAD_ENDPOINT_URL", ""), "STAGING_MEDIA_URL")
    if app_host == media_host:
        fail("application and upload origins must use distinct hostnames")
    if backend_env.get("AWS_STORAGE_BUCKET_NAME") == backend_env.get("MEDIA_STORAGE_BUCKET_NAME"):
        fail("public and private media buckets must be distinct")

    validate_runtime_contract(services, backend_env)


def validate_permissions(
    path: Path, expected_mode: int, label: str, *, expected_gid: int | None = None
) -> None:
    if path.is_symlink():
        fail(f"{label} must not be a symbolic link: {path}")
    try:
        metadata = path.stat()
    except FileNotFoundError:
        fail(f"missing {label}: {path}")
    actual_mode = stat.S_IMODE(metadata.st_mode)
    if actual_mode != expected_mode:
        fail(f"{label} must have mode {expected_mode:04o}, found {actual_mode:04o}: {path}")
    if metadata.st_uid != os.geteuid():
        fail(f"{label} must be owned by the deployment identity: {path}")
    if expected_gid is not None and metadata.st_gid != expected_gid:
        fail(f"{label} must be group-owned by GID {expected_gid}: {path}")


def validate_release_inputs(config: dict, env_file: Path) -> None:
    validate_environment_file(env_file)
    validate_secret_files(config)


def validate_environment_file(
    env_file: Path,
    *,
    variable: str = "STAGING_ENV_FILE",
    label: str = "staging environment file",
) -> None:
    if not env_file.is_absolute():
        fail(f"{variable} must be an absolute path")
    if ROOT in env_file.parents:
        fail(f"the {label} must remain outside the repository")
    if not env_file.is_file():
        fail(f"{label} must be a regular file: {env_file}")
    validate_permissions(env_file, 0o600, label)
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, _ = line.strip().partition("=")
        if (
            separator
            and key not in {"STAGING_SECRETS_DIR", "STAGING_SECRET_GID"}
            and any(
                marker in key.upper()
                for marker in ("PASSWORD", "SECRET", "TOKEN", "ACCESS_KEY")
            )
        ):
            fail(f"the {label} must contain secret paths, never secret values")


def validate_secret_files(config: dict) -> None:
    expected_gid = secret_group_id(config["services"])
    secret_paths = []
    for name, secret in config["secrets"].items():
        source = Path(secret.get("file", ""))
        if not source.is_absolute():
            fail(f"{name} secret source must be an absolute path")
        secret_paths.append(source)
        if not source.is_file():
            fail(f"{name} secret must be a regular file: {source}")
        validate_permissions(
            source, 0o640, f"{name} secret", expected_gid=expected_gid
        )
        if source.stat().st_size == 0:
            fail(f"{name} secret must not be empty")

    secret_directories = {path.parent for path in secret_paths}
    if len(secret_directories) != 1:
        fail("all staging secret files must come from one isolated directory")
    secret_directory = secret_directories.pop()
    if not secret_directory.is_dir():
        fail(f"staging secret directory must be a directory: {secret_directory}")
    validate_permissions(
        secret_directory,
        0o750,
        "staging secret directory",
        expected_gid=expected_gid,
    )
    validate_secret_values(config["secrets"])
    validate_database_certificate(config["secrets"])


def validate_secret_values(secrets: dict) -> None:
    """Mirror application secret rules; errors name a secret, never its value."""

    for name in sorted(EXPORTED_SECRETS):
        try:
            value = Path(secrets[name]["file"]).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            fail(f"{name} secret must be UTF-8 text")
        value = value.rstrip("\n")
        if not value or value != value.strip():
            fail(f"{name} secret must not be blank or have surrounding whitespace")
        minimum = SECRET_MINIMUM_LENGTHS.get(name)
        if minimum is not None and len(value) < minimum:
            fail(f"{name} secret must contain at least {minimum} characters")


def openssl(*arguments: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["openssl", *arguments],
            check=False,
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        fail("openssl is required to verify the PostgreSQL TLS certificate")


def validate_database_certificate(secrets: dict) -> None:
    """Prove the verify-full contract offline; never echo key material."""

    trust_anchor = secrets["postgres_tls_ca"]["file"]
    certificate = secrets["postgres_tls_certificate"]["file"]
    private_key = secrets["postgres_tls_private_key"]["file"]
    verification = openssl(
        "verify",
        "-CAfile",
        trust_anchor,
        "-untrusted",
        certificate,
        "-purpose",
        "sslserver",
        "-verify_hostname",
        DATABASE_ALIAS,
        certificate,
    )
    if verification.returncode:
        fail(
            "the PostgreSQL TLS certificate must be currently valid, chain to "
            f"postgres_tls_ca, and name {DATABASE_ALIAS}"
        )
    certificate_key = openssl("x509", "-in", certificate, "-noout", "-pubkey")
    server_key = openssl("pkey", "-in", private_key, "-pubout", "-passin", "pass:")
    if (
        certificate_key.returncode
        or server_key.returncode
        or certificate_key.stdout != server_key.stdout
    ):
        fail("the PostgreSQL TLS private key must be unencrypted and match its certificate")


def resolve_release_env_file(env_file: Path) -> Path:
    if not env_file.is_absolute():
        fail("STAGING_ENV_FILE must be an absolute path")
    return env_file.resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="validate the staging Compose contract without starting runtime"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--template", action="store_true", help="validate the checked-in safe template")
    source.add_argument("--env-file", type=Path, help="preflight an external staging environment file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        env_file = (
            TEMPLATE_FILE
            if args.template
            else resolve_release_env_file(args.env_file)
        )
        config = render(env_file)
        validate_structure(config, allow_placeholders=args.template)
        if not args.template:
            validate_release_inputs(config, env_file)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"Staging validation failed: {error}", file=sys.stderr)
        return 1

    if args.template:
        print("Staging Compose structure is valid; no runtime actions were performed.")
    else:
        print("Staging release inputs passed preflight; no runtime actions were performed.")
        print("Controlled release order, after the release manifest is approved:")
        print(f"  1. {MIGRATION_COMMAND}")
        print(f"  2. {RUNTIME_COMMAND}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
