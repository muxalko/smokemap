#!/usr/bin/env python3
"""Render and validate the local-staging overlay without starting services.

Local staging reuses the reviewed staging topology in deploy/staging/compose.yaml
and its validators, then applies stricter local rules: a single loopback-only
edge port, reserved non-public hostnames, local content-addressed images that
are never pulled, non-root application users, and project-scoped resources
that cannot collide with the development stack.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "validate_staging", ROOT / "scripts" / "validate-staging.py"
)
assert _SPEC is not None and _SPEC.loader is not None
staging = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(staging)

ValidationError = staging.ValidationError
fail = staging.fail

LOCAL_DIRECTORY = ROOT / "deploy" / "staging" / "local"
BASE_COMPOSE_FILE = staging.COMPOSE_FILE
OVERLAY_FILE = LOCAL_DIRECTORY / "compose.yaml"
EDGE_CONFIG_FILE = LOCAL_DIRECTORY / "nginx.conf"
SETTINGS_TEMPLATE = LOCAL_DIRECTORY / "settings.env.example"
RELEASE_TEMPLATE = LOCAL_DIRECTORY / "release.env.example"
README_FILE = LOCAL_DIRECTORY / "README.md"
POSTGRES_INIT_FILE = ROOT / "docker" / "postgres" / "init" / "00-create-smokemap-schema.sql"

PROJECT_NAME = "smokemap-local-staging"
PROFILES = (staging.RUNTIME_PROFILE, staging.MIGRATION_PROFILE)
RUNTIME_PROFILES = (staging.RUNTIME_PROFILE,)

# Reserved private-use names. Both the backend and frontend production
# validators accept them, the external preflight rejects them, and no public
# DNS or Cloudflare route can ever serve them.
APP_HOST = "app.local-staging.smokemap.internal"
MEDIA_HOST = "media.local-staging.smokemap.internal"
EDGE_SERVICE = "edge"
EDGE_CONTAINER_PORT = 8443
EDGE_HEALTH_LISTENER = "127.0.0.1:8081"
EDGE_CONFIG_TARGET = "/etc/nginx/smokemap-local-staging.conf"
EDGE_UPSTREAMS = {"http://frontend:3000", "http://storage:9000"}
# nginx logs upstream failures at "error"; only levels above it are allowed.
EDGE_ERROR_LOG_LEVELS = {"crit", "alert", "emerg"}
LOOPBACK = "127.0.0.1"
# Host ports the development stack in docker-compose.yaml publishes by default.
DEVELOPMENT_PORTS = {3000, 5432, 8000, 9000, 9001}

APP_USER = "10001:10001"
EDGE_USER = "101:101"
APP_SERVICES = ("backend", "frontend", "media-cleanup", "migrate")
HARDENED_USERS = {**{name: APP_USER for name in APP_SERVICES}, EDGE_SERVICE: EDGE_USER}

EXPECTED_SERVICES = (staging.EXPECTED_SERVICES - {"cloudflared"}) | {EDGE_SERVICE}
EDGE_SECRETS = {"edge_tls_certificate", "edge_tls_private_key"}
EXPECTED_SECRETS = (staging.EXPECTED_SECRETS - {"cloudflared_token"}) | EDGE_SECRETS
EXPECTED_CONFIGS = {"edge_nginx": EDGE_CONFIG_FILE, "postgres_init": POSTGRES_INIT_FILE}
EXPECTED_REACHABILITY = {
    "db": {"database"},
    "storage": {"media", "media-ingress"},
    "storage-init": {"media"},
    "migrate": {"application", "database", "media"},
    "backend": {"application", "database", "media"},
    "media-cleanup": {"database", "media"},
    "frontend": {"application", "ingress"},
    EDGE_SERVICE: {"edge", "ingress", "media-ingress"},
}

LOCAL_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
PLACEHOLDER_IMAGE = "sha256:" + "0" * 64
INERT_CLOUDFLARED_IMAGE = (
    "local-staging.invalid/cloudflared-disabled@sha256:" + "0" * 64
)
RELEASE_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
PLACEHOLDER_RELEASE_ID = "00000000T000000Z-000000000000"
DATABASE_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}")
# Image variable -> service and the expected OCI revision source.
IMAGE_VARIABLES = {
    "POSTGIS_IMAGE": "db",
    "MINIO_IMAGE": "storage",
    "MINIO_CLIENT_IMAGE": "storage-init",
    "BACKEND_IMAGE": "backend",
    "FRONTEND_IMAGE": "frontend",
    "EDGE_PROXY_IMAGE": EDGE_SERVICE,
}
SETTINGS_KEYS = {
    "COMPOSE_PROJECT_NAME",
    "STAGING_SECRETS_DIR",
    "STAGING_SECRET_GID",
    "LOCAL_STAGING_HTTPS_PORT",
    "STAGING_APP_URL",
    "STAGING_MEDIA_URL",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "MINIO_BUCKET",
    "MINIO_PRIVATE_MEDIA_BUCKET",
    "AWS_REGION",
    "MEDIA_CLEANUP_BATCH_SIZE",
    "MEDIA_CLEANUP_INTERVAL_SECONDS",
    "LOG_LEVEL",
    "NEXT_PUBLIC_MAP_STYLE",
    "CLOUDFLARED_IMAGE",
}
RELEASE_KEYS = {"RELEASE_ID", "RELEASE_VERSION", *IMAGE_VARIABLES}
# Only these variables reach Docker; COMPOSE_* and every staging value in the
# caller's shell would otherwise override the reviewed files.
PASSTHROUGH_ENVIRONMENT = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "XDG_RUNTIME_DIR",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
)


def app_origin(port: int) -> str:
    return f"https://{APP_HOST}:{port}"


def media_origin(port: int) -> str:
    return f"https://{MEDIA_HOST}:{port}"


def docker_environment() -> dict[str, str]:
    return {key: os.environ[key] for key in PASSTHROUGH_ENVIRONMENT if key in os.environ}


def compose_arguments(
    settings_file: Path,
    release_file: Path,
    *,
    profiles: tuple[str, ...] = PROFILES,
) -> list[str]:
    profile_args = [argument for profile in profiles for argument in ("--profile", profile)]
    return [
        "docker",
        "compose",
        "--project-name",
        PROJECT_NAME,
        "--project-directory",
        str(BASE_COMPOSE_FILE.parent),
        "--env-file",
        str(settings_file),
        "--env-file",
        str(release_file),
        "-f",
        str(BASE_COMPOSE_FILE),
        "-f",
        str(OVERLAY_FILE),
        *profile_args,
    ]


def compose_config(
    settings_file: Path,
    release_file: Path,
    *,
    profiles: tuple[str, ...] = PROFILES,
    extra_args: tuple[str, ...] = (),
) -> dict:
    result = subprocess.run(
        [
            *compose_arguments(settings_file, release_file, profiles=profiles),
            "config",
            *extra_args,
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=docker_environment(),
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        fail(f"Docker Compose could not render the local-staging overlay: {detail}")
    return json.loads(result.stdout)


def render(settings_file: Path, release_file: Path) -> dict:
    source_config = compose_config(
        settings_file,
        release_file,
        extra_args=("--no-interpolate", "--no-normalize", "--no-env-resolution"),
    )
    for name, service in source_config.get("services", {}).items():
        if service.get("env_file"):
            fail(f"{name} must not load an unreviewed environment file")
    return compose_config(settings_file, release_file)


def read_env_file(path: Path) -> dict[str, str]:
    """Parse the plain KEY=VALUE subset these files use, rejecting the rest."""

    values: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            fail(f"{path.name} line {number} must be a plain KEY=VALUE assignment")
        if value != value.strip() or value[:1] in {"'", '"'} or "$" in value:
            fail(f"{path.name} {key} must be an unquoted value without interpolation")
        if key in values:
            fail(f"{path.name} assigns {key} more than once")
        values[key] = value
    return values


def https_port(settings: dict[str, str]) -> int:
    value = settings.get("LOCAL_STAGING_HTTPS_PORT", "")
    if not value.isdigit() or not 1024 <= int(value) <= 65535:
        fail("LOCAL_STAGING_HTTPS_PORT must be an unprivileged TCP port")
    port = int(value)
    if port in DEVELOPMENT_PORTS:
        fail("LOCAL_STAGING_HTTPS_PORT must not reuse a development stack port")
    return port


def validate_settings(settings: dict[str, str]) -> int:
    if set(settings) != SETTINGS_KEYS:
        fail("local-staging settings differ from the reviewed variable set")
    if settings["COMPOSE_PROJECT_NAME"] != PROJECT_NAME:
        fail(f"COMPOSE_PROJECT_NAME must remain {PROJECT_NAME}")
    port = https_port(settings)
    if settings["STAGING_APP_URL"] != app_origin(port):
        fail(f"STAGING_APP_URL must be exactly {app_origin(port)}")
    if settings["STAGING_MEDIA_URL"] != media_origin(port):
        fail(f"STAGING_MEDIA_URL must be exactly {media_origin(port)}")
    for key in ("POSTGRES_DB", "POSTGRES_USER"):
        if not DATABASE_IDENTIFIER.fullmatch(settings[key]):
            fail(f"{key} must be a lowercase PostgreSQL identifier")
    if not Path(settings["STAGING_SECRETS_DIR"]).is_absolute():
        fail("STAGING_SECRETS_DIR must be an absolute path")
    if settings["CLOUDFLARED_IMAGE"] != INERT_CLOUDFLARED_IMAGE:
        fail("CLOUDFLARED_IMAGE must remain the inert local placeholder")
    return port


def validate_release_selection(
    release: dict[str, str], *, allow_placeholders: bool
) -> None:
    if set(release) != RELEASE_KEYS:
        fail("the release selection differs from the reviewed variable set")
    if not RELEASE_ID.fullmatch(release["RELEASE_ID"]) or (
        not allow_placeholders and release["RELEASE_ID"] == PLACEHOLDER_RELEASE_ID
    ):
        fail("RELEASE_ID must be a recorded local release identifier")
    if not staging.SOURCE_REVISION.fullmatch(release["RELEASE_VERSION"]):
        fail("RELEASE_VERSION must be the full lowercase 40-hex frontend source commit")
    for key in IMAGE_VARIABLES:
        if not LOCAL_IMAGE.fullmatch(release[key]):
            fail(f"{key} must be a content-addressed local image ID")
        if not allow_placeholders and release[key] == PLACEHOLDER_IMAGE:
            fail(f"{key} still uses the placeholder image ID")
    if not allow_placeholders and release["RELEASE_VERSION"] == staging.PLACEHOLDER_REVISION:
        fail("RELEASE_VERSION still uses the placeholder commit")


def validate_published_port(services: dict, port: int) -> None:
    for name, service in services.items():
        if service.get("expose"):
            fail(f"{name} must not expose a port")
        if name != EDGE_SERVICE and service.get("ports"):
            fail(f"{name} must not publish a port; only the local edge may")
    ports = services[EDGE_SERVICE].get("ports") or []
    if len(ports) != 1:
        fail("the local edge must publish exactly one HTTPS port")
    binding = ports[0]
    if binding.get("host_ip") != LOOPBACK:
        fail(f"the local edge must bind only to {LOOPBACK}")
    if (
        binding.get("target") != EDGE_CONTAINER_PORT
        or binding.get("protocol", "tcp") != "tcp"
        or binding.get("mode", "ingress") != "ingress"
    ):
        fail("the local edge must publish only its TCP HTTPS listener")
    if str(binding.get("published")) != str(port):
        fail("the local edge must publish exactly LOCAL_STAGING_HTTPS_PORT")


def validate_project_resources(config: dict) -> None:
    for kind, expected in (
        ("volumes", staging.EXPECTED_VOLUMES),
        ("networks", staging.EXPECTED_NETWORKS),
    ):
        resources = config.get(kind, {})
        if set(resources) != expected:
            fail(f"local-staging {kind} differ from the reviewed set")
        for key, resource in resources.items():
            if resource.get("external"):
                fail(f"{key} must not reuse an external resource")
            if resource.get("name") != f"{PROJECT_NAME}_{key}":
                fail(f"{key} must remain scoped to the {PROJECT_NAME} project")
            if resource.get("driver_opts") or resource.get("driver") not in (None, "local", "bridge"):
                fail(f"{key} must use the default local driver without options")
    for name in ("application", "database", "ingress", "media", "media-ingress"):
        if not config["networks"][name].get("internal"):
            fail(f"{name} network must remain internal")
    if config["networks"]["edge"].get("internal"):
        fail("edge network must allow the loopback port publication")


def validate_hardening(services: dict) -> None:
    for name, user in HARDENED_USERS.items():
        service = services[name]
        if service.get("user") != user:
            fail(f"{name} must run as the non-root user {user}")
        if service.get("cap_drop") != ["ALL"]:
            fail(f"{name} must drop every Linux capability")
        if "no-new-privileges:true" not in (service.get("security_opt") or []):
            fail(f"{name} must forbid privilege escalation")
    edge = services[EDGE_SERVICE]
    if not edge.get("read_only"):
        fail("the local edge must use a read-only root filesystem")
    if staging.command_text(edge) != f"nginx -c {EDGE_CONFIG_TARGET} -g daemon off;":
        fail("the local edge must run nginx with only the reviewed configuration")
    if edge.get("configs") != [{"source": "edge_nginx", "target": EDGE_CONFIG_TARGET}]:
        fail("the local edge must mount only the reviewed nginx configuration")
    if staging.service_secrets(edge) != EDGE_SECRETS:
        fail("the local edge must mount only its own TLS certificate and key")
    for name, service in services.items():
        if name != EDGE_SERVICE and staging.service_secrets(service) & EDGE_SECRETS:
            fail(f"{name} must not mount the local edge TLS material")


def strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def validate_edge_config(text: str) -> None:
    """Pin the reviewed nginx routing: two origins, two upstreams, no leaks."""

    config = strip_comments(text)
    names = set(re.findall(r"^\s*server_name\s+([^;]+);", config, re.MULTILINE))
    if names != {APP_HOST, MEDIA_HOST}:
        fail("the local edge must serve exactly the application and media hostnames")
    listens = re.findall(r"^\s*listen\s+([^;]+);", config, re.MULTILINE)
    if set(listens) != {f"{EDGE_CONTAINER_PORT} ssl default_server", f"{EDGE_CONTAINER_PORT} ssl", EDGE_HEALTH_LISTENER}:
        fail("the local edge must listen only for TLS and its container-local health check")
    if "ssl_reject_handshake on;" not in config:
        fail("the local edge must reject TLS names it does not serve")
    upstreams = set(re.findall(r"^\s*set\s+\$\w+\s+([^;]+);", config, re.MULTILINE))
    if upstreams != EDGE_UPSTREAMS or re.findall(r"proxy_pass\s+(?!\$)", config):
        fail("the local edge may proxy only to the frontend and MinIO API")
    for header in (
        "proxy_set_header Host $http_host;",
        "proxy_set_header X-Forwarded-Proto https;",
        'proxy_set_header Forwarded "";',
    ):
        if header not in config:
            fail(f"the local edge must set {header}")
    if re.search(r"proxy_set_header\s+\S+\s+\$proxy_add_x_forwarded_for", config):
        fail("the local edge must replace, never append, client forwarding headers")
    formats = " ".join(re.findall(r"log_format[^;]+;", config, re.DOTALL))
    if not formats or re.search(
        r"\$(?:request(?![_a-z])|request_uri|args|query_string|arg_\w+|http_authorization|http_cookie)",
        formats,
    ):
        fail("the local edge access log must omit query strings and credentials")
    # Error messages quote the whole request line, so ordinary upstream
    # failures ("error") must never be logged.
    error_logs = re.findall(r"(?<![\w$])error_log\s+([^;]*);", config)
    if not error_logs or any(
        len(arguments.split()) != 2 or arguments.split()[1] not in EDGE_ERROR_LOG_LEVELS
        for arguments in error_logs
    ):
        fail("the local edge error log must set an explicit crit, alert or emerg level")


def validate_frontend_contract(
    services: dict, backend_env: dict, port: int, *, allow_placeholders: bool
) -> None:
    frontend_env = services["frontend"].get("environment", {})
    for key, expected in staging.FRONTEND_CONTRACT.items():
        if frontend_env.get(key) != expected:
            fail(f"frontend {key} must be {expected!r} for the production contract")
    expected_origins = {
        "NEXT_PUBLIC_BASE_URL": (frontend_env, app_origin(port)),
        "NEXTAUTH_URL": (frontend_env, app_origin(port)),
        "CORS_ALLOWED_ORIGINS": (backend_env, app_origin(port)),
        "CSRF_TRUSTED_ORIGINS": (backend_env, app_origin(port)),
        "AWS_S3_ENDPOINT_URL": (backend_env, media_origin(port)),
        "MEDIA_UPLOAD_ENDPOINT_URL": (backend_env, media_origin(port)),
    }
    for key, (environment, expected) in expected_origins.items():
        if environment.get(key) != expected:
            fail(f"{key} must be exactly {expected}")
    version = str(frontend_env.get("NEXT_PUBLIC_VERSION", ""))
    if not staging.SOURCE_REVISION.fullmatch(version):
        fail("RELEASE_VERSION must be the full lowercase 40-hex frontend source commit")
    if not allow_placeholders and version == staging.PLACEHOLDER_REVISION:
        fail("RELEASE_VERSION still uses the placeholder commit")
    staging.require_https_url(
        frontend_env.get("NEXT_PUBLIC_MAP_STYLE", ""),
        "NEXT_PUBLIC_MAP_STYLE",
        origin_only=False,
    )
    if frontend_env.get("NEXT_PUBLIC_LOG_LEVEL") not in staging.FRONTEND_LOG_LEVELS:
        fail("LOG_LEVEL must be a frontend production log level")


def validate_structure(config: dict, port: int, *, allow_placeholders: bool) -> None:
    if config.get("name") != PROJECT_NAME:
        fail(f"the local-staging project name must remain {PROJECT_NAME}")

    services = config.get("services", {})
    if set(services) != EXPECTED_SERVICES:
        fail("local-staging services differ from the reviewed topology")

    secrets = config.get("secrets", {})
    if set(secrets) != EXPECTED_SECRETS:
        fail("local-staging secrets differ from the reviewed file-backed set")
    for name, secret in secrets.items():
        if "file" not in secret or not set(secret) <= {"file", "name"}:
            fail(f"{name} must remain a local file-backed Compose secret")

    configs = config.get("configs", {})
    if set(configs) != set(EXPECTED_CONFIGS):
        fail("local-staging configs differ from the reviewed file-backed set")
    for name, path in EXPECTED_CONFIGS.items():
        if not set(configs[name]) <= {"file", "name"} or Path(
            configs[name].get("file", "")
        ) != path:
            fail(f"{name} must remain the reviewed repository file")

    for name, service in services.items():
        if "build" in service:
            fail(f"{name} must run a recorded local image, not build at startup")
        image = service.get("image", "")
        if not LOCAL_IMAGE.fullmatch(image):
            fail(f"{name} image is not a content-addressed local image ID")
        if not allow_placeholders and image == PLACEHOLDER_IMAGE:
            fail(f"{name} still uses the placeholder image ID")
        if service.get("pull_policy") != "never":
            fail(f"{name} must never pull an image at startup")
        for key in ("container_name", "network_mode", "ipc", "userns_mode", "volumes_from"):
            if service.get(key):
                fail(f"{name} must not set {key}")
        for mount in service.get("volumes", []):
            if mount.get("type") == "volume" and mount.get("source") not in staging.EXPECTED_VOLUMES:
                fail(f"{name} must mount only project-scoped named volumes")
        staging.validate_service_isolation(name, service)

    validate_published_port(services, port)
    validate_hardening(services)
    staging.secret_group_id(services)

    if services["migrate"].get("profiles") != [staging.MIGRATION_PROFILE]:
        fail("migration must remain an explicitly selected one-shot profile")
    for name in EXPECTED_SERVICES - {"migrate"}:
        if services[name].get("profiles") != [staging.RUNTIME_PROFILE]:
            fail(f"{name} must remain behind the explicit staging-runtime profile")

    validate_project_resources(config)
    for name, wanted in EXPECTED_REACHABILITY.items():
        if set(services[name].get("networks", {})) != wanted:
            fail(f"{name} network reachability changed")

    staging.validate_aliases(services)
    backend_env = staging.validate_backend_contract(services)
    staging.validate_database_tls(services)
    validate_frontend_contract(
        services, backend_env, port, allow_placeholders=allow_placeholders
    )
    staging.validate_migration(services)
    if backend_env.get("AWS_STORAGE_BUCKET_NAME") == backend_env.get("MEDIA_STORAGE_BUCKET_NAME"):
        fail("public and private media buckets must be distinct")
    staging.validate_runtime_contract(services, backend_env)
    validate_edge_config(Path(configs["edge_nginx"]["file"]).read_text(encoding="utf-8"))


def inside_git_work_tree(path: Path) -> bool:
    directory = path if path.is_dir() else path.parent
    result = subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "--is-inside-work-tree"],
        check=False,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def require_outside_repositories(path: Path, label: str) -> None:
    if ROOT == path or ROOT in path.parents:
        fail(f"{label} must remain outside the repository")
    if inside_git_work_tree(path):
        fail(f"{label} must not be inside any Git working tree")


def validate_edge_certificate(secrets: dict, trust_anchor: Path) -> None:
    """Prove both origins chain to the local edge authority; never echo keys."""

    certificate = secrets["edge_tls_certificate"]["file"]
    private_key = secrets["edge_tls_private_key"]["file"]
    if not trust_anchor.is_file():
        fail(f"missing local edge trust anchor: {trust_anchor}")
    for hostname in (APP_HOST, MEDIA_HOST):
        verification = staging.openssl(
            "verify",
            "-CAfile",
            str(trust_anchor),
            "-purpose",
            "sslserver",
            "-verify_hostname",
            hostname,
            certificate,
        )
        if verification.returncode:
            fail(
                "the local edge TLS certificate must be currently valid, chain to "
                f"the local edge authority, and name {hostname}"
            )
    certificate_key = staging.openssl("x509", "-in", certificate, "-noout", "-pubkey")
    server_key = staging.openssl("pkey", "-in", private_key, "-pubout", "-passin", "pass:")
    if (
        certificate_key.returncode
        or server_key.returncode
        or certificate_key.stdout != server_key.stdout
    ):
        fail("the local edge TLS private key must be unencrypted and match its certificate")


def validate_release_inputs(
    config: dict, settings_file: Path, release_file: Path, edge_trust_anchor: Path
) -> None:
    for path, label in (
        (settings_file, "local-staging settings file"),
        (release_file, "local-staging release file"),
    ):
        staging.validate_environment_file(path, variable=label, label=label)
        require_outside_repositories(path, label)
    secret_directory = {Path(secret["file"]).parent for secret in config["secrets"].values()}
    for directory in secret_directory:
        require_outside_repositories(directory, "the local-staging secret directory")
    staging.validate_secret_files(config)
    validate_edge_certificate(config["secrets"], edge_trust_anchor)


def inspect_image(image: str) -> dict | None:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        env=docker_environment(),
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        return None
    return json.loads(result.stdout)[0]


def is_root_user(user: str) -> bool:
    return user.split(":", 1)[0] in {"", "0", "root"}


def validate_local_images(
    release: dict[str, str], expected_revisions: dict[str, str], *, inspect=inspect_image
) -> dict[str, dict]:
    """Every selected image must exist locally under its exact recorded ID."""

    images = {}
    for key, service in IMAGE_VARIABLES.items():
        metadata = inspect(release[key])
        if metadata is None or metadata.get("Id") != release[key]:
            fail(f"{key} is not present locally under its recorded image ID")
        labels = (metadata.get("Config") or {}).get("Labels") or {}
        revision = expected_revisions.get(service)
        if revision is not None and labels.get("org.opencontainers.image.revision") != revision:
            fail(f"{key} revision label differs from the recorded source commit")
        if service in HARDENED_USERS and is_root_user((metadata.get("Config") or {}).get("User", "")):
            fail(f"{key} image must declare a non-root user")
        images[service] = metadata
    if expected_revisions.get("frontend") != release["RELEASE_VERSION"]:
        fail("RELEASE_VERSION must equal the frontend image source commit")
    return images


def validate_template() -> None:
    settings = read_env_file(SETTINGS_TEMPLATE)
    port = validate_settings(settings)
    validate_release_selection(read_env_file(RELEASE_TEMPLATE), allow_placeholders=True)
    validate_structure(render(SETTINGS_TEMPLATE, RELEASE_TEMPLATE), port, allow_placeholders=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="validate the local-staging overlay without starting runtime"
    )
    parser.add_argument(
        "--template",
        action="store_true",
        required=True,
        help="validate the checked-in safe templates; use local-staging.py preflight for a release",
    )
    parser.parse_args()
    try:
        validate_template()
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"Local-staging validation failed: {error}", file=sys.stderr)
        return 1
    print("Local-staging overlay structure is valid; no runtime actions were performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
