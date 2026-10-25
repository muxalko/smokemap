#!/usr/bin/env python3
"""Operate a dedicated, supervised two-Quick-Tunnel temporary rehearsal."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import signal
import ssl
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quick = load("quick_contract", "validate-quick-staging.py")
api = load("quick_operator_helpers", "local-staging.py")
# This private module instance adapts existing build/backup/recovery operations.
# No shared module or default local/external contract is mutated.
api.local = quick
api.staging = quick.staging
api.ValidationError, api.fail = quick.ValidationError, quick.fail
api.PROJECT_NAME = api.IMAGE_TAG_PREFIX = quick.PROJECT_NAME
api.MODE = "quick-staging"
api.UPSTREAM_IMAGES = {"db": api.UPSTREAM_IMAGES["db"]}
api.WRITERS = ("frontend", "media-cleanup", "backend")
staging = quick.staging
fail, ValidationError = quick.fail, quick.ValidationError
Home = api.Home
ALL_PROFILES = quick.PROFILES
APP_SERVICES = ("frontend", "media-cleanup", "backend")
CONNECTORS = quick.CONNECTORS
BASE_VALIDATE_HOME = api.validate_home
BASE_LOAD_MANIFEST = api.load_manifest


def validate_home(home: Home) -> None:
    BASE_VALIDATE_HOME(home)
    if api.load_state(home).get("mode") != "quick-staging":
        fail("this home does not belong to quick-staging; never reuse a local/production home")
    staging.validate_environment_file(home.settings, variable="quick settings", label="quick settings")
    settings = quick.read_env_file(home.settings)
    quick.validate_settings(settings, empty=True)
    if Path(settings["STAGING_SECRETS_DIR"]) != home.secrets:
        fail("quick secrets must belong to this independent home")


def load_manifest(home: Home, release_id: str) -> dict:
    manifest = BASE_LOAD_MANIFEST(home, release_id)
    if manifest.get("mode") != "quick-staging" or manifest.get("registry") is not None:
        fail("release is not a recorded quick-staging local build")
    if {name: manifest["sources"][name]["commit"] for name in quick.PINS} != quick.PINS:
        fail("quick source pins have changed")
    return manifest


def write_settings(home: Home, settings: dict) -> None:
    api.write_private(home.settings, "".join(f"{k}={v}\n" for k, v in settings.items()))


def compose(home: Home, *arguments, release_file=None, profiles=quick.RUNTIME_PROFILES, **options):
    # Connectors-only phase still needs syntactically complete base variables.
    # Use a private resolved settings file, with inert origins while unallocated.
    settings = quick.read_env_file(home.settings)
    for key, sample in (("STAGING_APP_URL", "https://unallocated-app.trycloudflare.com"),
                        ("STAGING_MEDIA_URL", "https://unallocated-media.trycloudflare.com")):
        if not settings[key]:
            settings[key] = sample
    import tempfile
    with tempfile.TemporaryDirectory(prefix="compose-", dir=home.work) as directory:
        resolved = Path(directory) / "settings.env"
        api.write_private(resolved, "".join(f"{k}={v}\n" for k, v in settings.items()))
        return api.run([*quick.compose_arguments(resolved, release_file or
                       (home.release if home.release.exists() else quick.RELEASE_TEMPLATE), profiles=profiles),
                        *arguments], docker=True, **options)


def runtime_inventory(home: Home) -> dict:
    """Inspect only the dedicated project; validate ownership before any stop."""
    result = {}
    for container in api.project_containers():
        config, host = container.get("Config") or {}, container.get("HostConfig") or {}
        labels = config.get("Labels") or {}
        name = labels.get("com.docker.compose.service")
        if labels.get("com.docker.compose.project") != quick.PROJECT_NAME or name not in quick.EXPECTED_SERVICES:
            fail("unexpected container in the quick project")
        # Compose run --rm jobs are transient; never use them as service identity.
        if labels.get("com.docker.compose.oneoff", "False").lower() == "true":
            continue
        if name in result or api.published_bindings(container):
            fail("quick project has duplicate services or published ports")
        expected_networks = {f"{quick.PROJECT_NAME}_{n}" for n in quick.REACHABILITY[name]}
        if set((container.get("NetworkSettings") or {}).get("Networks") or {}) != expected_networks:
            fail("quick container network ownership differs from reviewed isolation")
        if name in CONNECTORS:
            if (config.get("Image") != quick.CLOUDFLARED_IMAGE or
                config.get("Cmd") != quick.connector_command(name) or
                config.get("Entrypoint") != ["cloudflared", "--no-autoupdate"] or
                config.get("User") != "65532:65532" or container.get("Mounts") or
                host.get("RestartPolicy", {}).get("Name") != "no" or
                host.get("LogConfig", {}).get("Type") != "none" or
                not host.get("ReadonlyRootfs") or host.get("Privileged") or
                host.get("CapDrop") != ["ALL"] or host.get("CapAdd") or
                not any(x in host.get("SecurityOpt", []) for x in ("no-new-privileges", "no-new-privileges:true"))):
                fail("live quick connector differs from reviewed argv/security contract")
        result[name] = container
    return result


def connector_snapshot(home: Home, reader_image: str) -> dict:
    inventory = runtime_inventory(home)
    result = {}
    for service in CONNECTORS:
        container = inventory.get(service)
        if not container or not container["State"].get("Running"):
            fail("both original quick connector processes must be running")
        network = "ingress" if service == "quick-app" else "media-ingress"
        # The upstream distroless cloudflared image has no shell/curl. Use the
        # already digest-verified PostGIS bash on ONE internal ingress network.
        # This helper has no secrets, mounts, host ports, or internet route.
        command = ["docker", "run", "--rm", "--pull", "never", "--network", f"{quick.PROJECT_NAME}_{network}",
                   "--read-only", "--user", "65532:65532", "--cap-drop", "ALL",
                   "--security-opt", "no-new-privileges:true", "--entrypoint", "timeout", reader_image, "5", "bash", "-ec",
                   f"exec 3<>/dev/tcp/{service}/2000; "
                   "printf 'GET /quicktunnel HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n' >&3; cat <&3"]
        probe = api.run(command, capture=True, docker=True, check=False)
        if probe.returncode:
            fail("private quicktunnel metrics probe failed; no logs were read")
        try:
            head, body = probe.stdout.split("\r\n\r\n" if "\r\n" in probe.stdout else "\n\n", 1)
            if head.splitlines()[0].split()[1] != "200":
                raise ValueError()
            hostname = json.loads(body)["hostname"]
            origin = hostname if hostname.startswith("https://") else "https://" + hostname
            quick.require_origin(origin)
        except (KeyError, ValueError, IndexError):
            fail("private quicktunnel endpoint returned no exact quick origin")
        result[service] = {"id": container["Id"], "pid": container["State"]["Pid"],
                           "started_at": container["State"]["StartedAt"],
                           "restart_count": container["RestartCount"], "origin": origin}
    if result[CONNECTORS[0]]["origin"] == result[CONNECTORS[1]]["origin"]:
        fail("quick connector origins must differ")
    return result


def check_connectors(home: Home) -> dict:
    state = api.load_state(home)
    expected = state.get("connectors")
    if not expected or state.get("invalidated"):
        fail("no connector generation is recorded; run connectors before build")
    try:
        actual = connector_snapshot(home, state["reader_image"])
        settings = quick.read_env_file(home.settings)
        if actual != expected or any(settings[key] != actual[service]["origin"] for service, key in
                                     zip(CONNECTORS, ("STAGING_APP_URL", "STAGING_MEDIA_URL"))):
            fail("quick connector process/URL changed")
    except (ValidationError, OSError, ValueError):
        state["invalidated"] = True
        api.save_state(home, state)
        close_ingress(home)
        fail("quick connector process/URL unavailable or changed; stop, allocate connectors, and rebuild frontend")
    return actual


def close_ingress(home: Home) -> None:
    # Project-scoped Compose stop is intentionally usable with stale URLs.
    compose(home, "stop", *CONNECTORS, profiles=ALL_PROFILES)


def preflight(home: Home, release_file: Path, **unused):
    validate_home(home)
    settings = quick.read_env_file(home.settings)
    quick.validate_settings(settings)
    release = quick.read_env_file(release_file)
    quick.validate_release_selection(release, allow_placeholders=False)
    if release_file not in (home.release, home.release_file(release["RELEASE_ID"])):
        fail("quick release must live in its recorded home")
    manifest = load_manifest(home, release["RELEASE_ID"])
    if manifest.get("connector_image") != quick.CLOUDFLARED_IMAGE:
        fail("quick connector image differs from the manifest")
    if release != manifest["release_env"]:
        fail("quick release differs from recorded manifest")
    public = manifest["frontend_public_build_inputs"]
    if (public != public_inputs(settings) or
        hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest() != manifest["frontend_public_build_inputs_sha256"]):
        fail("quick public build inputs changed; rebuild frontend")
    if manifest["connectors"] != check_connectors(home):
        fail("quick connector generation changed; rebuild frontend")
    if manifest["public_origins"] != {k: settings[k] for k in ("STAGING_APP_URL", "STAGING_MEDIA_URL")}:
        fail("quick public origins changed; rebuild frontend")
    config = quick.render(home.settings, release_file)
    quick.validate_structure(config, allow_placeholders=False)
    for path in (release_file, home.settings):
        quick.require_outside_repositories(path, "quick configuration")
        staging.validate_environment_file(path, variable="quick configuration", label="quick configuration")
    staging.validate_secret_files(config)
    quick.validate_local_images(release, api.manifest_revisions(manifest))
    for key, service in quick.IMAGE_VARIABLES.items():
        if manifest["images"][service]["id"] != release[key]:
            fail("quick image IDs differ from recorded manifest")
    api.validate_resource_ownership(config)
    runtime_inventory(home)
    return settings, release, manifest, config


def public_inputs(settings: dict) -> dict:
    return {"VCS_REF": quick.PINS["frontend"], "NEXT_PUBLIC_ENVIRONMENT": "staging",
            "NEXT_PUBLIC_VERSION": quick.PINS["frontend"], "NEXT_PUBLIC_BASE_URL": settings["STAGING_APP_URL"],
            **{k: v for k, v in staging.FRONTEND_CONTRACT.items() if k.startswith("NEXT_PUBLIC_") and k != "NEXT_PUBLIC_ENVIRONMENT"},
            "NEXT_PUBLIC_MAP_STYLE": settings["NEXT_PUBLIC_MAP_STYLE"], "NEXT_PUBLIC_LOG_LEVEL": settings["LOG_LEVEL"]}


def command_init(home: Home, gid: int | None) -> None:
    if home.path.exists() and (not home.path.is_dir() or any(home.path.iterdir())):
        fail("refusing to initialize a non-empty quick home")
    gid = os.getegid() if gid is None else gid
    if gid <= 0 or (gid != os.getegid() and gid not in os.getgroups()):
        fail("quick secret group must be a positive group belonging to the operator")
    if not home.path.parent.is_dir():
        fail("quick home parent must already exist")
    if not home.path.exists():
        api.make_directory(home.path, 0o700)
    os.chmod(home.path, 0o700)
    for directory in (home.authority, home.releases, home.backups, home.work):
        api.make_directory(directory, 0o700)
    api.make_directory(home.secrets, 0o750, gid=gid)
    settings = quick.read_env_file(quick.SETTINGS_TEMPLATE)
    settings.update(STAGING_SECRETS_DIR=str(home.secrets), STAGING_SECRET_GID=str(gid))
    write_settings(home, settings)
    for name, generator in api.SECRET_GENERATORS.items():
        api.write_private(home.secrets / name, generator() + "\n", mode=0o640, gid=gid)
    authority = api.generate_authority(home.authority, "database-ca", "Smokemap quick-staging database CA")
    key, certificate = api.issue_certificate(authority, home.authority, "postgres-server", (staging.DATABASE_ALIAS,))
    for name, path in (("postgres_tls_private_key", key), ("postgres_tls_certificate", certificate), ("postgres_tls_ca", authority[1])):
        api.write_private(home.secrets / name, path.read_text(), mode=0o640, gid=gid)
    key.unlink()
    certificate.unlink()
    state = api.load_state(home)
    state["mode"] = "quick-staging"
    api.save_state(home, state)
    validate_home(home)
    config = quick.render(home.settings, quick.RELEASE_TEMPLATE)
    quick.validate_structure(config, allow_placeholders=True)
    staging.validate_secret_files(config)
    print(f"Initialized independent quick home {home.path}. Next: connectors")


def command_connectors(home: Home) -> None:
    validate_home(home)
    config = quick.render(home.settings, quick.RELEASE_TEMPLATE)
    quick.validate_structure(config, allow_placeholders=True)
    api.validate_resource_ownership(config)
    inventory = runtime_inventory(home)
    if any(c["State"].get("Running") for c in inventory.values()):
        fail("stop the quick project before allocating a new connector generation")
    # Fetch only reviewed public upstream artifacts; no application registry.
    reader_image, _ = api.ensure_upstream("db")
    if quick.inspect_image(quick.CLOUDFLARED_IMAGE) is None:
        api.run(["docker", "pull", quick.CLOUDFLARED_IMAGE], docker=True)
    state = api.load_state(home)
    state.pop("connectors", None)
    state.pop("invalidated", None)
    state["reader_image"] = reader_image
    state["current_release"] = None
    api.save_state(home, state)
    home.release.unlink(missing_ok=True)
    compose(home, "up", "--detach", "--no-deps", "--force-recreate", *CONNECTORS, profiles=ALL_PROFILES)
    try:
        for attempt in range(30):
            try:
                snapshot = connector_snapshot(home, reader_image)
                break
            except ValidationError:
                if attempt == 29:
                    raise
                time.sleep(2)
        state["connectors"] = snapshot
        settings = quick.read_env_file(home.settings)
        for service, key in zip(CONNECTORS, ("STAGING_APP_URL", "STAGING_MEDIA_URL")):
            settings[key] = snapshot[service]["origin"]
        quick.validate_settings(settings)
        write_settings(home, settings)
        api.record(home, state, "connectors", connectors=snapshot)
    except BaseException:
        close_ingress(home)
        raise
    print("Allocated two connectors; applications remain unavailable:")
    for service in CONNECTORS:
        print(f"  {service}: {snapshot[service]['origin']}")
    print("Next: build. Do not restart/recreate either connector.")


def command_build(home: Home) -> None:
    validate_home(home)
    snapshot = check_connectors(home)
    api.require_clean_root()
    if {name: api.gitlink(source["path"]) for name, source in api.SOURCES.items()} != quick.PINS:
        fail("quick application gitlinks must remain at the reviewed pins")
    api.command_build(home)
    if check_connectors(home) != snapshot:
        fail("connectors changed during build; rebuild frontend")
    state = api.load_state(home)
    release_id = state["history"][-1]["release"]
    path = home.release_file(release_id).with_name("manifest.json")
    manifest = load_manifest(home, release_id)
    settings = quick.read_env_file(home.settings)
    manifest.update(connectors=snapshot,
                    public_origins={k: settings[k] for k in ("STAGING_APP_URL", "STAGING_MEDIA_URL")},
                    connector_image=quick.CLOUDFLARED_IMAGE)
    api.write_private(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def supervisor_alive(supervisor: dict | None) -> bool:
    if not supervisor:
        return False
    stat = Path(f"/proc/{supervisor['pid']}/stat")
    return stat.exists() and stat.read_text().split()[21] == supervisor["proc_start"]


def require_supervisor(home: Home) -> None:
    if not supervisor_alive(api.load_state(home).get("supervisor")):
        close_ingress(home)
        fail("quick smoke/recovery requires the live foreground supervisor; ingress closed")


def command_migrate(home: Home, release_id: str) -> None:
    if any(c["State"].get("Running") for name, c in runtime_inventory(home).items() if name in APP_SERVICES):
        fail("quick app writers must be stopped before the one-shot migration")
    api.command_migrate(home, release_id)
    check_connectors(home)


def command_start(home: Home, lock=None) -> None:
    preflight(home, home.release)
    api.require_migrated(api.load_state(home), quick.read_env_file(home.release))
    state = api.load_state(home)
    supervisor = state.get("supervisor")
    if supervisor:
        if supervisor_alive(supervisor):
            fail("a quick supervisor already owns this rehearsal")
        close_ingress(home)
        fail("previous quick supervisor disappeared; stop, allocate connectors, and rebuild")
    state["supervisor"] = {"pid": os.getpid(), "started_at": api.timestamp(),
                           "proc_start": Path(f"/proc/{os.getpid()}/stat").read_text().split()[21]}
    api.save_state(home, state)
    print("Starting apps under foreground supervision. Keep this terminal alive; Ctrl-C closes ingress.", flush=True)
    try:
        compose(home, "up", "--detach", "--wait", "db", "storage", "storage-init", *APP_SERVICES)
        if lock is not None:
            fcntl.flock(lock, fcntl.LOCK_UN)
        while True:
            check_connectors(home)
            time.sleep(2)
    finally:
        close_ingress(home)
        compose(home, "stop", *APP_SERVICES)
        state = api.load_state(home)
        state.pop("supervisor", None)
        api.record(home, state, "supervisor-stop")


def command_stop(home: Home) -> None:
    validate_home(home)
    close_ingress(home)
    compose(home, "stop", profiles=ALL_PROFILES)
    api.record(home, api.load_state(home), "stop")


def command_status(home: Home) -> None:
    validate_home(home)
    state = api.load_state(home)
    print(f"Project: {quick.PROJECT_NAME}; release: {state.get('current_release')}")
    try:
        check_connectors(home)
    except (ValidationError, OSError):
        close_ingress(home)
        fail("quick connector generation is unavailable/changed; ingress closed; rebuild required")
    for service in CONNECTORS:
        print(f"{service}: {state['connectors'][service]['origin']}")
    alive = supervisor_alive(state.get("supervisor"))
    if not alive and any(c["State"].get("Running") for n, c in runtime_inventory(home).items() if n in APP_SERVICES):
        close_ingress(home)
        fail("quick apps lost their supervisor; ingress closed; stop and rebuild")
    print(f"Supervisor: {state.get('supervisor') if alive else 'not running (apps stopped)'}")
    compose(home, "ps", "--all", profiles=ALL_PROFILES)


def public_request(origin: str, method: str, path: str, **options):
    quick.require_origin(origin)
    connection = http.client.HTTPSConnection(urlsplit(origin).hostname, timeout=20, context=ssl.create_default_context())
    try:
        connection.request(method, path, **options)
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


def command_smoke(home: Home) -> None:
    settings, release, _, _ = preflight(home, home.release)
    api.require_migrated(api.load_state(home), release)
    require_supervisor(home)
    app, media = settings["STAGING_APP_URL"], settings["STAGING_MEDIA_URL"]
    checks = []
    def check(name, origin, method, path, predicate, **options):
        status, headers, body = public_request(origin, method, path, **options)
        checks.append((name, predicate(status, headers, body)))
    check("application", app, "GET", "/", lambda s, h, b: s == 200 and not api.from_minio(h))
    check("GraphQL", app, "POST", "/api/smokemap/graphql",
          lambda s, h, b: s == 200 and json.loads(b).get("data", {}).get("__typename") == "Query",
          headers={"Content-Type": "application/json"}, body=b'{"query":"{ __typename }"}')
    check("viewport", app, "GET", f"/api/smokemap/locations?bbox={api.SMOKE_BBOX}&zoom=12",
          lambda s, h, b: s == 200 and json.loads(b).get("type") == "FeatureCollection")
    check("auth callback origin", app, "GET", "/api/auth/providers",
          lambda s, h, b: s == 200 and bool(json.loads(b)) and
          all(p["callbackUrl"].startswith(app + "/api/auth/callback/") for p in json.loads(b).values()))
    check("media health", media, "GET", "/minio/health/live", lambda s, h, b: s == 200)
    for path in ("/graphql/", "/health/ready/", "/api/auth/providers"):
        check("media backend separation", media, "GET", path, lambda s, h, b: s >= 400 and api.from_minio(h))
    for bucket in (settings["MINIO_BUCKET"], settings["MINIO_PRIVATE_MEDIA_BUCKET"]):
        check("anonymous listing", media, "GET", f"/{bucket}?list-type=2", lambda s, h, b: s == 403)
        check("unsigned write", media, "PUT", f"/{bucket}/quick-smoke-probe", lambda s, h, b: s == 403, body=b"x")
    check("private read", media, "GET", f"/{settings['MINIO_PRIVATE_MEDIA_BUCKET']}/quick-smoke-probe", lambda s, h, b: s == 403)
    check("CORS", media, "OPTIONS", f"/{settings['MINIO_PRIVATE_MEDIA_BUCKET']}/quick-smoke-probe",
          lambda s, h, b: s == 200 and h.get("access-control-allow-origin") == app,
          headers={"Origin": app, "Access-Control-Request-Method": "POST"})
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    if not all(passed for _, passed in checks):
        fail("quick public smoke failed; no response bodies or signed URLs were printed")


# Explicitly adapt only the reusable operations of this private module instance.
api.compose = compose
api.validate_home = validate_home
api.load_manifest = load_manifest
api.preflight = preflight


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--secret-gid", type=int)
    for name in ("connectors", "build", "start", "stop", "status", "smoke", "backup", "releases"):
        commands.add_parser(name)
    for name in ("preflight", "migrate", "rollback"):
        commands.add_parser(name).add_argument("--release", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--confirm", required=True)
    args = parser.parse_args(argv)
    try:
        home = api.resolve_home(args.home)
        # Resolve symlinks before any access; never initialize through an alias.
        if home.path.resolve() != home.path:
            fail("quick home must be its canonical path without symlinks")
        if args.command == "init":
            command_init(home, args.secret_gid)
            return 0
        validate_home(home)
        # Serialize mutations. Foreground supervision releases the lock after
        # setup so smoke/backup/status/stop can be used in a second terminal.
        with (home.path / "operator.lock").open("a") as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "start":
                command_start(home, lock)
            elif args.command in ("connectors", "build", "stop", "status", "smoke"):
                globals()[f"command_{args.command}"](home)
            elif args.command == "preflight":
                api.command_preflight(home, args.release)
            elif args.command == "migrate":
                command_migrate(home, args.release)
            elif args.command == "releases":
                api.command_releases(home)
            elif args.command == "backup":
                require_supervisor(home)
                api.command_backup(home)
            elif args.command == "restore":
                require_supervisor(home)
                api.command_restore(home, args.backup, args.confirm, True)
            elif args.command == "rollback":
                require_supervisor(home)
                api.command_rollback(home, args.release)
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException, ValidationError) as error:
        # Do not stringify network/JSON exceptions: they can contain URLs/body.
        print(f"Quick staging failed: {error if isinstance(error, ValidationError) else type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    def terminate(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, terminate)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
