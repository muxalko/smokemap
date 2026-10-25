#!/usr/bin/env python3
"""Strict, opt-in Quick Tunnel contract; local/external contracts stay unchanged."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("quick_local_contract", ROOT / "scripts/validate-local-staging.py")
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)
staging = local.staging
ValidationError, fail = local.ValidationError, local.fail
DIRECTORY = ROOT / "deploy/staging/quick"
SETTINGS_TEMPLATE = DIRECTORY / "settings.env.example"
RELEASE_TEMPLATE = DIRECTORY / "release.env.example"
PROJECT_NAME = "smokemap-quick-staging"
CONNECTORS = ("quick-app", "quick-media")
CONNECTOR_PROFILE = "quick-connectors"
RUNTIME_PROFILES = local.RUNTIME_PROFILES
PROFILES = (*local.PROFILES, CONNECTOR_PROFILE)
CLOUDFLARED_IMAGE = "cloudflare/cloudflared:2026.10.0@sha256:9b49eed8f62806d5d45ddf59ecefb5710429598ea6d3fcccd2af938f621b2b07"
ORIGIN = re.compile(r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com")
PINS = {"backend": "05098a798961e6e1b968d78f3211a17df63d036f", "frontend": "21b93f47ddb9614509f636c83478b8a10b8dac47"}
IMAGE_VARIABLES = {k: v for k, v in local.IMAGE_VARIABLES.items() if k != "EDGE_PROXY_IMAGE"}
RELEASE_KEYS = {"RELEASE_ID", "RELEASE_VERSION", *IMAGE_VARIABLES}
SETTINGS_KEYS = local.SETTINGS_KEYS - {"LOCAL_STAGING_HTTPS_PORT"}
RELEASE_ID = local.RELEASE_ID
APP_SERVICES = local.APP_SERVICES
HARDENED_USERS = {name: local.APP_USER for name in APP_SERVICES}
read_env_file = local.read_env_file
docker_environment = local.docker_environment
require_outside_repositories = local.require_outside_repositories
inspect_image = local.inspect_image
EXPECTED_SERVICES = (staging.EXPECTED_SERVICES - {"cloudflared"}) | set(CONNECTORS)
EXPECTED_SECRETS = staging.EXPECTED_SECRETS - {"cloudflared_token"}
REACHABILITY = {k: v for k, v in local.EXPECTED_REACHABILITY.items() if k != "edge"}
REACHABILITY.update({"quick-app": {"edge", "ingress"}, "quick-media": {"edge", "media-ingress"}})


def require_origin(value: str) -> None:
    if not ORIGIN.fullmatch(value):
        fail("quick origins must be exact HTTPS single-label trycloudflare.com origins")


def validate_settings(settings: dict, *, empty: bool = False) -> None:
    if set(settings) != SETTINGS_KEYS:
        fail("quick settings differ from the reviewed variable set")
    if settings["COMPOSE_PROJECT_NAME"] != PROJECT_NAME:
        fail(f"quick project must be {PROJECT_NAME}")
    origins = [settings[k] for k in ("STAGING_APP_URL", "STAGING_MEDIA_URL")]
    if not (empty and origins == ["", ""]):
        for origin in origins:
            require_origin(origin)
        if origins[0] == origins[1]:
            fail("quick app and media origins must differ")
    if settings["CLOUDFLARED_IMAGE"] != CLOUDFLARED_IMAGE:
        fail("quick cloudflared must use the reviewed official immutable image")
    for key in ("POSTGRES_DB", "POSTGRES_USER"):
        if settings[key] != "smokemap_quick_staging":
            fail(f"{key} must remain dedicated to quick staging")
    for key, suffix in (("MINIO_BUCKET", "public"), ("MINIO_PRIVATE_MEDIA_BUCKET", "private")):
        if settings[key] != f"{PROJECT_NAME}-{suffix}":
            fail(f"{key} must remain dedicated to quick staging")
    if not Path(settings["STAGING_SECRETS_DIR"]).is_absolute():
        fail("quick secrets must have an absolute outside-Git path")


def validate_release_selection(release: dict, *, allow_placeholders: bool) -> None:
    if set(release) != RELEASE_KEYS:
        fail("quick release differs from the reviewed variable set")
    # Reuse the existing strict ID/revision parser without changing its defaults.
    local.validate_release_selection({**release, "EDGE_PROXY_IMAGE": release["POSTGIS_IMAGE"]}, allow_placeholders=allow_placeholders)
    if not allow_placeholders and release["RELEASE_VERSION"] != PINS["frontend"]:
        fail("quick frontend must remain at its reviewed source pin")


def compose_arguments(settings_file: Path, release_file: Path, *, profiles=PROFILES) -> list[str]:
    return ["docker", "compose", "--project-name", PROJECT_NAME,
            "--project-directory", str(staging.COMPOSE_FILE.parent),
            "--env-file", str(settings_file), "--env-file", str(release_file),
            "-f", str(staging.COMPOSE_FILE), "-f", str(DIRECTORY / "compose.yaml"),
            *[a for profile in profiles for a in ("--profile", profile)]]


def render(settings_file: Path, release_file: Path) -> dict:
    # Empty connectors-first origins cannot satisfy the base interpolation.
    # Rendering uses inert, valid sample origins only; no runtime/build accepts them.
    settings = read_env_file(settings_file)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="quick-render-") as directory:
        resolved = Path(directory) / "settings.env"
        for key, sample in (("STAGING_APP_URL", "https://unallocated-app.trycloudflare.com"),
                            ("STAGING_MEDIA_URL", "https://unallocated-media.trycloudflare.com")):
            if not settings[key]:
                settings[key] = sample
        resolved.write_text("".join(f"{k}={v}\n" for k, v in settings.items()))
        resolved.chmod(0o600)
        configs = []
        for options in (("--no-interpolate", "--no-normalize", "--no-env-resolution"), ()):
            result = subprocess.run([*compose_arguments(resolved, release_file), "config", *options, "--format", "json"],
                                    cwd=ROOT, env=docker_environment(), text=True, capture_output=True)
            if result.returncode:
                fail("Compose could not render the quick contract")
            configs.append(json.loads(result.stdout))
        if any(s.get("env_file") for s in configs[0]["services"].values()):
            fail("quick services must not load environment files")
        return configs[1]


def connector_command(service: str) -> list[str]:
    target = "http://frontend:3000" if service == "quick-app" else "http://storage:9000"
    return ["tunnel", "--loglevel", "fatal", "--metrics", "0.0.0.0:2000", "--url", target]


def validate_structure(config: dict, *, allow_placeholders: bool) -> None:
    if config.get("name") != PROJECT_NAME or set(config.get("services", {})) != EXPECTED_SERVICES:
        fail("quick project/services differ from reviewed topology")
    services = config["services"]
    if set(config.get("secrets", {})) != EXPECTED_SECRETS:
        fail("quick secrets must exclude every tunnel token and edge key")
    for secret in config["secrets"].values():
        if set(secret) - {"name", "file"} or not secret.get("file"):
            fail("quick secrets must be file backed")
    configs = config.get("configs", {})
    if (set(configs) != {"postgres_init"} or
        Path(configs["postgres_init"].get("file", "")) != local.POSTGRES_INIT_FILE or
        set(configs["postgres_init"]) - {"name", "file"}):
        fail("quick mode must use the reviewed PostgreSQL initializer")
    for kind, expected in (("networks", staging.EXPECTED_NETWORKS), ("volumes", staging.EXPECTED_VOLUMES)):
        if set(config.get(kind, {})) != expected:
            fail(f"quick {kind} differ from reviewed set")
        for name, resource in config[kind].items():
            if resource.get("name") != f"{PROJECT_NAME}_{name}" or resource.get("external") or resource.get("driver_opts") or resource.get("driver") not in (None, "local", "bridge"):
                fail("quick resources must be project scoped with default drivers")
            if kind == "networks" and bool(resource.get("internal")) != (name != "edge"):
                fail("only the connector edge network may have internet egress")
    for name, service in services.items():
        staging.validate_service_isolation(name, service)
        if service.get("ports") or service.get("expose"):
            fail("quick services must not publish or expose any host port")
        for key in ("build", "container_name", "network_mode", "ipc", "userns_mode", "volumes_from"):
            if service.get(key):
                fail(f"quick {name} must not set {key}")
        for mount in service.get("volumes", []):
            if mount.get("type") != "volume" or mount.get("source") not in staging.EXPECTED_VOLUMES:
                fail("quick mounts must use project-scoped volumes")
        if set(service.get("networks", {})) != REACHABILITY[name]:
            fail(f"quick {name} network reachability changed")
        if service.get("pull_policy") != "never":
            fail("quick services must use pull never")
        if name in CONNECTORS:
            if (service.get("image") != CLOUDFLARED_IMAGE or
                service.get("entrypoint") != ["cloudflared", "--no-autoupdate"] or
                service.get("command") != connector_command(name) or
                service.get("secrets") or service.get("configs") or service.get("volumes") or
                service.get("environment") or service.get("group_add") or service.get("depends_on") or
                service.get("profiles") != [CONNECTOR_PROFILE] or
                service.get("restart") != "no" or not service.get("read_only") or
                service.get("logging") != {"driver": "none"}):
                fail("quick connector argv/image/logging/mount/order contract changed")
        else:
            image = service.get("image", "")
            if not local.LOCAL_IMAGE.fullmatch(image) or (not allow_placeholders and image == local.PLACEHOLDER_IMAGE):
                fail("quick runtime images must be recorded local content-addressed IDs")
            if service.get("profiles") != [staging.MIGRATION_PROFILE if name == "migrate" else staging.RUNTIME_PROFILE]:
                fail("quick runtime/migration profiles changed")
        user = "65532:65532" if name in CONNECTORS else HARDENED_USERS.get(name)
        if user and (service.get("user") != user or service.get("cap_drop") != ["ALL"] or
                     "no-new-privileges:true" not in service.get("security_opt", [])):
            fail("quick applications/connectors must remain hardened nonroot services")
    staging.secret_group_id(services)
    staging.validate_aliases(services)
    backend = staging.validate_backend_contract(services)
    staging.validate_database_tls(services)
    staging.validate_frontend_contract(services, backend, allow_placeholders=allow_placeholders)
    app = services["frontend"]["environment"]["NEXTAUTH_URL"]
    media = backend.get("MEDIA_UPLOAD_ENDPOINT_URL", "")
    for origin in (app, media):
        require_origin(origin)
    if app == media or backend.get("AWS_S3_ENDPOINT_URL") != media:
        fail("quick media signing must use the distinct exact media origin")
    staging.validate_migration(services)
    staging.validate_runtime_contract(services, backend)
    if backend.get("AWS_STORAGE_BUCKET_NAME") == backend.get("MEDIA_STORAGE_BUCKET_NAME"):
        fail("quick buckets must differ")


def validate_local_images(release: dict, expected_revisions: dict, *, inspect=inspect_image) -> dict:
    images = {}
    for key, service in IMAGE_VARIABLES.items():
        metadata = inspect(release[key])
        if metadata is None or metadata.get("Id") != release[key]:
            fail(f"{key} must exist under its recorded local ID")
        config = metadata.get("Config") or {}
        if service in expected_revisions and (config.get("Labels") or {}).get("org.opencontainers.image.revision") != expected_revisions[service]:
            fail(f"{key} revision differs from recorded source")
        if service in HARDENED_USERS and local.is_root_user(config.get("User", "")):
            fail(f"{key} must declare a nonroot user")
        images[service] = metadata
    if expected_revisions.get("frontend") != release["RELEASE_VERSION"]:
        fail("quick frontend version must equal its source commit")
    return images


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", action="store_true", required=True)
    parser.parse_args()
    try:
        validate_settings(read_env_file(SETTINGS_TEMPLATE), empty=True)
        validate_release_selection(read_env_file(RELEASE_TEMPLATE), allow_placeholders=True)
        validate_structure(render(SETTINGS_TEMPLATE, RELEASE_TEMPLATE), allow_placeholders=True)
    except (OSError, ValueError, ValidationError) as error:
        print(f"Quick contract validation failed: {error}", file=sys.stderr)
        return 1
    print("Quick contract validated; no connectors or applications started.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
