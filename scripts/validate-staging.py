#!/usr/bin/env python3
"""Render and validate the staging contract without starting any services."""

from __future__ import annotations

import argparse
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
    "storage_access_key",
    "storage_secret_key",
}
IMMUTABLE_IMAGE = re.compile(r"^[^\s:@]+(?:/[^\s:@]+)+@sha256:[0-9a-f]{64}$")
PLACEHOLDER_DIGEST = "0" * 64


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def render(env_file: Path) -> dict:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(COMPOSE_FILE),
            "--profile",
            "staging-runtime",
            "--profile",
            "staging-migration",
            "config",
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


def require_https_origin(value: str, label: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        fail(f"{label} must be an HTTPS origin without credentials, path, query, or non-default port")
    return parsed.hostname


def command_text(service: dict) -> str:
    entrypoint = service.get("entrypoint") or []
    command = service.get("command") or []
    if isinstance(entrypoint, str):
        entrypoint = [entrypoint]
    if isinstance(command, str):
        command = [command]
    return " ".join([*entrypoint, *command])


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
        for mount in service.get("volumes", []):
            if mount.get("type") == "bind":
                fail(f"{name} contains an unexpected host bind mount")
        for key, value in service.get("environment", {}).items():
            if any(marker in key for marker in ("PASSWORD", "SECRET", "TOKEN", "ACCESS_KEY")):
                if not key.endswith("_FILE") or not str(value).startswith("/run/secrets/"):
                    fail(f"{name} places sensitive input {key} in its environment")
        lowered = command_text(service).lower()
        for forbidden in ("runserver", "yarn dev", "next dev", "makemigrations"):
            if forbidden in lowered:
                fail(f"{name} contains forbidden development command: {forbidden}")

    if services["migrate"].get("profiles") != ["staging-migration"]:
        fail("migration must remain an explicitly selected one-shot profile")
    for name in EXPECTED_SERVICES - {"migrate"}:
        if services[name].get("profiles") != ["staging-runtime"]:
            fail(f"{name} must remain behind the explicit staging-runtime profile")

    networks = config.get("networks", {})
    for name in ("application", "database", "media"):
        if not networks.get(name, {}).get("internal"):
            fail(f"{name} network must remain internal")
    if networks.get("edge", {}).get("internal"):
        fail("edge network must permit the tunnel's outbound connection")

    expected_networks = {
        "db": {"database"},
        "storage": {"media"},
        "storage-init": {"media"},
        "migrate": {"application", "database", "media"},
        "backend": {"application", "database", "media"},
        "media-cleanup": {"database", "media"},
        "frontend": {"application", "edge"},
        "cloudflared": {"edge", "media"},
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

    backend_env = services["backend"].get("environment", {})
    app_host = require_https_origin(backend_env.get("CORS_ALLOWED_ORIGINS", ""), "STAGING_APP_URL")
    media_host = require_https_origin(backend_env.get("MEDIA_UPLOAD_ENDPOINT_URL", ""), "STAGING_MEDIA_URL")
    if app_host == media_host:
        fail("application and upload origins must use distinct hostnames")
    if backend_env.get("AWS_STORAGE_BUCKET_NAME") == backend_env.get("MEDIA_STORAGE_BUCKET_NAME"):
        fail("public and private media buckets must be distinct")

    if "gunicorn" not in command_text(services["backend"]):
        fail("backend must use the production WSGI server contract")
    if "yarn start" not in command_text(services["frontend"]):
        fail("frontend must use the production server contract")


def validate_permissions(path: Path, expected_mode: int, label: str) -> None:
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


def validate_release_inputs(config: dict, env_file: Path) -> None:
    if not env_file.is_absolute():
        fail("STAGING_ENV_FILE must be an absolute path")
    if ROOT in env_file.parents:
        fail("the staging environment file must remain outside the repository")
    validate_permissions(env_file, 0o600, "staging environment file")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, _ = line.strip().partition("=")
        if (
            separator
            and key != "STAGING_SECRETS_DIR"
            and any(
                marker in key.upper()
                for marker in ("PASSWORD", "SECRET", "TOKEN", "ACCESS_KEY")
            )
        ):
            fail("the staging environment file must contain secret paths, never secret values")

    secret_paths = []
    for name, secret in config["secrets"].items():
        source = Path(secret.get("file", ""))
        if not source.is_absolute():
            fail(f"{name} secret source must be an absolute path")
        secret_paths.append(source)
        validate_permissions(source, 0o600, f"{name} secret")
        if source.stat().st_size == 0:
            fail(f"{name} secret must not be empty")

    secret_directories = {path.parent for path in secret_paths}
    if len(secret_directories) != 1:
        fail("all staging secret files must come from one isolated directory")
    validate_permissions(secret_directories.pop(), 0o700, "staging secret directory")


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
    env_file = TEMPLATE_FILE if args.template else args.env_file.resolve()
    try:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
