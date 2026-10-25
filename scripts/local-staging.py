#!/usr/bin/env python3
"""Operate the loopback-only local-staging mode.

Every command works on an operator home directory outside any Git working tree:

  settings.env      operator settings, mode 0600, never secret values
  release.env       the selected release, copied from releases/<id>
  secrets/          file-backed Compose secrets, modes 0750/0640
  authority/        staging-only certificate authority keys; never mounted
  edge-ca.crt       local edge trust anchor for browsers and smoke checks
  releases/<id>/    manifest.json and release.env recorded by each build
  backups/<id>/     paired database.dump and media.tar with checksums
  state.json        migration records and the action history

No command prints a secret value, publishes a non-loopback port, or removes a
volume. deploy/staging/local/README.md is the runbook.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets as token_source
import socket
import ssl
import string
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "validate_local_staging", ROOT / "scripts" / "validate-local-staging.py"
)
assert _SPEC is not None and _SPEC.loader is not None
local = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(local)
staging = local.staging

ValidationError = local.ValidationError
fail = local.fail
PROJECT_NAME = local.PROJECT_NAME

SOURCES = {
    "backend": {
        "path": "smokemap-django-backend",
        "url": "https://github.com/muxalko/smokemap-django-backend.git",
        "files": ("Dockerfile", "requirements.txt"),
    },
    "frontend": {
        "path": "smokemap-webapp",
        "url": "https://github.com/muxalko/smokemap-webapp.git",
        "files": ("Dockerfile", "package.json", "yarn.lock", "src/lib/production-config.js"),
    },
}
DEVELOPMENT_BRANCH = "refs/heads/development"
# Must equal the build arguments in docker-compose.yaml; a test pins them.
MINIO_SERVER_RELEASE = "RELEASE.2025-07-23T15-54-02Z"
MINIO_SERVER_COMMIT = "7ced9663e6a791fef9dc6be798ff24cda9c730ac"
MINIO_CLIENT_RELEASE = "RELEASE.2025-08-13T08-35-41Z"
MINIO_CLIENT_COMMIT = "7394ce0dd2a80935aded936b09fa12cbb3cb8096"
# Reviewed upstream releases pinned by index digest.
UPSTREAM_IMAGES = {
    "db": "postgis/postgis:17-3.5@sha256:45f2a608397fa67d236b012c14a9e3ea31e9fe813edbeb5c1c0d1acbf0d48ea9",
    local.EDGE_SERVICE: "nginxinc/nginx-unprivileged:1.30.6-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03",
}
IMAGE_TAG_PREFIX = PROJECT_NAME
WRITERS = (local.EDGE_SERVICE, "frontend", "media-cleanup", "backend")
SECRET_ALPHABET = string.ascii_letters + string.digits
LOWER_ALPHABET = string.ascii_lowercase + string.digits
SMOKE_OBJECT = "local-staging-smoke-probe"
SMOKE_BBOX = "-0.5,51.3,0.3,51.7"
TLS_DAYS = {"authority": 825, "server": 365}
BACKUP_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z")


class Home:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.settings = path / "settings.env"
        self.release = path / "release.env"
        self.secrets = path / "secrets"
        self.authority = path / "authority"
        self.edge_ca = path / "edge-ca.crt"
        self.releases = path / "releases"
        self.backups = path / "backups"
        self.state = path / "state.json"
        self.work = path / "work"

    def release_file(self, release_id: str) -> Path:
        if not local.RELEASE_ID.fullmatch(release_id):
            fail("a release identifier looks like 20260101T000000Z-0123456789ab")
        return self.releases / release_id / "release.env"


def now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp() -> str:
    return now().strftime("%Y-%m-%dT%H:%M:%SZ")


def run(
    arguments: list[str],
    *,
    cwd: Path = ROOT,
    capture: bool = False,
    check: bool = True,
    stdin=None,
    stdout=None,
    docker: bool = False,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=local.docker_environment() if docker else None,
        check=False,
        text=capture,
        stdin=stdin,
        stdout=subprocess.PIPE if capture else stdout,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode:
        detail = (result.stderr or "").strip() if capture else ""
        fail(f"{' '.join(arguments[:3])} failed with exit status {result.returncode}"
             + (f": {detail}" if detail else ""))
    return result


def git(*arguments: str, cwd: Path = ROOT) -> str:
    return run(["git", *arguments], cwd=cwd, capture=True).stdout.strip()


def compose(
    home: Home,
    *arguments: str,
    release_file: Path | None = None,
    profiles: tuple[str, ...] = local.RUNTIME_PROFILES,
    **options,
) -> subprocess.CompletedProcess:
    return run(
        [
            *local.compose_arguments(
                home.settings, release_file or home.release, profiles=profiles
            ),
            *arguments,
        ],
        docker=True,
        **options,
    )


def private_opener(path: str, flags: int) -> int:
    return os.open(path, flags, 0o600)


def write_private(path: Path, text: str, *, mode: int = 0o600, gid: int | None = None) -> None:
    """Write atomically with the final mode set before the name appears."""

    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        if gid is not None:
            os.chown(temporary, -1, gid)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def make_directory(path: Path, mode: int, *, gid: int | None = None) -> None:
    path.mkdir(mode=mode)
    os.chmod(path, mode)
    if gid is not None:
        os.chown(path, -1, gid)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_home(value: str) -> Home:
    path = Path(value)
    if not path.is_absolute():
        fail("--home must be an absolute path")
    path = Path(os.path.abspath(path))
    local.require_outside_repositories(path, "the local-staging home")
    return Home(path)


def validate_home(home: Home) -> None:
    if not home.path.is_dir():
        fail(f"the local-staging home does not exist; run init first: {home.path}")
    staging.validate_permissions(home.path, 0o700, "local-staging home")
    for directory in (home.authority, home.releases, home.backups, home.work):
        staging.validate_permissions(directory, 0o700, f"local-staging {directory.name} directory")


# State --------------------------------------------------------------------


def load_state(home: Home) -> dict:
    if not home.state.exists():
        return {"schema": 1, "current_release": None, "migrations": {}, "history": []}
    staging.validate_permissions(home.state, 0o600, "local-staging state file")
    state = json.loads(home.state.read_text(encoding="utf-8"))
    if state.get("schema") != 1:
        fail("the local-staging state file has an unsupported schema")
    return state


def save_state(home: Home, state: dict) -> None:
    write_private(home.state, json.dumps(state, indent=2, sort_keys=True) + "\n")


def record(home: Home, state: dict, action: str, **details) -> None:
    state["history"].append({"at": timestamp(), "action": action, **details})
    save_state(home, state)


def load_manifest(home: Home, release_id: str) -> dict:
    path = home.release_file(release_id).with_name("manifest.json")
    if not path.is_file():
        fail(f"release {release_id} has no recorded manifest")
    staging.validate_permissions(path, 0o600, "release manifest")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("release_id") != release_id:
        fail(f"release {release_id} manifest is not a supported local-staging manifest")
    return manifest


def manifest_revisions(manifest: dict) -> dict[str, str]:
    return {
        "backend": manifest["sources"]["backend"]["commit"],
        "frontend": manifest["sources"]["frontend"]["commit"],
        "storage": MINIO_SERVER_COMMIT,
        "storage-init": MINIO_CLIENT_COMMIT,
    }


def require_migrated(state: dict, release: dict[str, str]) -> None:
    migration = state["migrations"].get(release["RELEASE_ID"])
    if not migration or migration.get("backend_image") != release["BACKEND_IMAGE"]:
        fail(
            f"release {release['RELEASE_ID']} has no successful migration record; "
            "run migrate --release first"
        )


def select_release(home: Home, release_file: Path) -> None:
    write_private(home.release, release_file.read_text(encoding="utf-8"))


# Preflight -----------------------------------------------------------------


def validate_resource_ownership(config: dict) -> None:
    """A same-named volume or network must already belong to this project."""

    for kind, command in (("volumes", "volume"), ("networks", "network")):
        for resource in config[kind].values():
            result = run(
                ["docker", command, "inspect", resource["name"]],
                capture=True,
                check=False,
                docker=True,
            )
            if result.returncode:
                continue
            labels = json.loads(result.stdout)[0].get("Labels") or {}
            if labels.get("com.docker.compose.project") != PROJECT_NAME:
                fail(f"{resource['name']} exists but does not belong to the {PROJECT_NAME} project")


def project_containers() -> list[dict]:
    identifiers = run(
        ["docker", "ps", "--all", "--quiet", "--filter", f"label=com.docker.compose.project={PROJECT_NAME}"],
        capture=True,
        docker=True,
    ).stdout.split()
    if not identifiers:
        return []
    return json.loads(run(["docker", "inspect", *identifiers], capture=True, docker=True).stdout)


def published_bindings(container: dict) -> list[dict]:
    ports = (container.get("NetworkSettings") or {}).get("Ports") or {}
    configured = (container.get("HostConfig") or {}).get("PortBindings") or {}
    return [
        binding
        for source in (ports, configured)
        for bindings in source.values()
        for binding in bindings or []
    ]


def edge_holds_port(port: int, containers: list[dict]) -> bool:
    for container in containers:
        labels = (container.get("Config") or {}).get("Labels") or {}
        if labels.get("com.docker.compose.service") != local.EDGE_SERVICE:
            continue
        for binding in published_bindings(container):
            if binding.get("HostPort") == str(port):
                return True
    return False


def validate_port_available(port: int) -> None:
    if edge_holds_port(port, project_containers()):
        return
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((local.LOOPBACK, port))
    except OSError:
        fail(f"{local.LOOPBACK}:{port} is already in use by another process")
    finally:
        probe.close()


def preflight(home: Home, release_file: Path, *, check_port: bool = True):
    validate_home(home)
    settings = local.read_env_file(home.settings)
    port = local.validate_settings(settings)
    release = local.read_env_file(release_file)
    local.validate_release_selection(release, allow_placeholders=False)
    if release_file != home.release and release_file != home.release_file(release["RELEASE_ID"]):
        fail("a release file must live in its own recorded release directory")
    manifest = load_manifest(home, release["RELEASE_ID"])
    recorded = {key: manifest["release_env"][key] for key in local.RELEASE_KEYS}
    if recorded != release:
        fail("the release selection differs from its recorded manifest")
    inputs = manifest["frontend_public_build_inputs"]
    if (
        inputs["NEXT_PUBLIC_BASE_URL"] != settings["STAGING_APP_URL"]
        or inputs["NEXT_PUBLIC_MAP_STYLE"] != settings["NEXT_PUBLIC_MAP_STYLE"]
        or inputs["NEXT_PUBLIC_LOG_LEVEL"] != settings["LOG_LEVEL"]
    ):
        fail("the frontend image was built for different public inputs; rebuild the release")
    config = local.render(home.settings, release_file)
    local.validate_structure(config, port, allow_placeholders=False)
    local.validate_release_inputs(config, home.settings, release_file, home.edge_ca)
    local.validate_local_images(release, manifest_revisions(manifest))
    validate_resource_ownership(config)
    if check_port:
        validate_port_available(port)
    return settings, release, manifest, config


def light_selection(home: Home) -> tuple[dict, dict]:
    """Enough validation to address the project without starting anything."""

    validate_home(home)
    settings = local.read_env_file(home.settings)
    local.validate_settings(settings)
    if not home.release.is_file():
        fail("no release is selected yet; build and migrate one first")
    release = local.read_env_file(home.release)
    local.validate_release_selection(release, allow_placeholders=False)
    return settings, release


# init ----------------------------------------------------------------------


def random_text(length: int, alphabet: str = SECRET_ALPHABET) -> str:
    return "".join(token_source.choice(alphabet) for _ in range(length))


SECRET_GENERATORS = {
    "django_secret_key": lambda: random_text(64),
    "nextauth_secret": lambda: random_text(48),
    "postgres_password": lambda: random_text(40),
    "minio_root_user": lambda: "localroot" + random_text(10, LOWER_ALPHABET),
    "minio_root_password": lambda: random_text(32),
    "storage_access_key": lambda: "localapp" + random_text(12, LOWER_ALPHABET),
    "storage_secret_key": lambda: random_text(32),
}


def openssl(*arguments: str, cwd: Path) -> None:
    result = subprocess.run(
        ["openssl", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode:
        fail(f"openssl {arguments[0]} failed while generating staging-only TLS material")


def generate_authority(directory: Path, name: str, common_name: str) -> tuple[Path, Path]:
    key, certificate = directory / f"{name}.key", directory / f"{name}.crt"
    openssl(
        "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
        "-nodes", "-keyout", str(key), "-out", str(certificate),
        "-subj", f"/CN={common_name}", "-days", str(TLS_DAYS["authority"]),
        "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        cwd=directory,
    )
    os.chmod(key, 0o600)
    os.chmod(certificate, 0o600)
    return key, certificate


def issue_certificate(
    authority: tuple[Path, Path], directory: Path, name: str, hostnames: tuple[str, ...]
) -> tuple[Path, Path]:
    key, certificate = directory / f"{name}.key", directory / f"{name}.crt"
    request, extensions = directory / f"{name}.csr", directory / f"{name}.ext"
    openssl(
        "req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
        "-keyout", str(key), "-out", str(request), "-subj", f"/CN={hostnames[0]}",
        cwd=directory,
    )
    os.chmod(key, 0o600)
    extensions.write_text(
        "subjectAltName=" + ",".join(f"DNS:{host}" for host in hostnames) + "\n"
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature\n"
        "extendedKeyUsage=serverAuth\n",
        encoding="utf-8",
    )
    openssl(
        "x509", "-req", "-in", str(request), "-CA", str(authority[1]),
        "-CAkey", str(authority[0]), "-set_serial", "0x" + token_source.token_hex(16),
        "-days", str(TLS_DAYS["server"]), "-extfile", str(extensions), "-out", str(certificate),
        cwd=directory,
    )
    request.unlink()
    extensions.unlink()
    return key, certificate


def command_init(home: Home, https_port: int, secret_gid: int | None) -> None:
    if home.path.exists() and (not home.path.is_dir() or any(home.path.iterdir())):
        fail("refusing to initialize an existing non-empty home; nothing was changed")
    if not home.path.parent.is_dir():
        fail(f"the parent of the local-staging home must exist: {home.path.parent}")
    gid = os.getegid() if secret_gid is None else secret_gid
    if gid <= 0:
        fail("the staging secret group must be a positive numeric GID")
    if gid != os.getegid() and gid not in os.getgroups():
        fail("the operator must belong to the staging secret group")
    port = local.https_port({"LOCAL_STAGING_HTTPS_PORT": str(https_port)})

    if not home.path.exists():
        make_directory(home.path, 0o700)
    os.chmod(home.path, 0o700)
    for directory in (home.authority, home.releases, home.backups, home.work):
        make_directory(directory, 0o700)
    make_directory(home.secrets, 0o750, gid=gid)

    replacements = {
        "STAGING_SECRETS_DIR": str(home.secrets),
        "STAGING_SECRET_GID": str(gid),
        "LOCAL_STAGING_HTTPS_PORT": str(port),
        "STAGING_APP_URL": local.app_origin(port),
        "STAGING_MEDIA_URL": local.media_origin(port),
    }
    lines = []
    for line in local.SETTINGS_TEMPLATE.read_text(encoding="utf-8").splitlines():
        key = line.partition("=")[0]
        lines.append(f"{key}={replacements[key]}" if key in replacements else line)
    write_private(home.settings, "\n".join(lines) + "\n")

    for name, generator in SECRET_GENERATORS.items():
        write_private(home.secrets / name, generator() + "\n", mode=0o640, gid=gid)

    database_authority = generate_authority(
        home.authority, "database-ca", "Smokemap local-staging database CA"
    )
    edge_authority = generate_authority(
        home.authority, "edge-ca", "Smokemap local-staging edge CA"
    )
    issued = {
        "postgres_tls": issue_certificate(
            database_authority, home.authority, "postgres-server", (staging.DATABASE_ALIAS,)
        ),
        "edge_tls": issue_certificate(
            edge_authority, home.authority, "edge-server", (local.APP_HOST, local.MEDIA_HOST)
        ),
    }
    for prefix, (key, certificate) in issued.items():
        write_private(home.secrets / f"{prefix}_certificate", certificate.read_text(), mode=0o640, gid=gid)
        write_private(home.secrets / f"{prefix}_private_key", key.read_text(), mode=0o640, gid=gid)
        key.unlink()
        certificate.unlink()
    write_private(
        home.secrets / "postgres_tls_ca", database_authority[1].read_text(), mode=0o640, gid=gid
    )
    write_private(home.edge_ca, edge_authority[1].read_text(), mode=0o644)
    save_state(home, load_state(home))

    # Prove that the generated inputs already satisfy the release preflight.
    config = local.render(home.settings, local.RELEASE_TEMPLATE)
    staging.validate_environment_file(
        home.settings, variable="local-staging settings file", label="local-staging settings file"
    )
    staging.validate_secret_files(config)
    local.validate_edge_certificate(config["secrets"], home.edge_ca)

    print(f"Initialized local staging in {home.path}; no secret values were printed.")
    print(f"  Application origin: {local.app_origin(port)}")
    print(f"  Media origin:       {local.media_origin(port)}")
    print(f"  Edge trust anchor:  {home.edge_ca}")
    print(f"  Resolve both names to {local.LOOPBACK} where the browser runs, for example:")
    print(f"    {local.LOOPBACK} {local.APP_HOST} {local.MEDIA_HOST}")
    print("Next: build a release from a clean checkout of merged root development.")


# build ---------------------------------------------------------------------


def require_clean_root() -> None:
    if git("status", "--porcelain", "--untracked-files=no", "--ignore-submodules=none"):
        fail("the root checkout and its submodules must be clean; run make sync")


def fetch_development(path: Path, remote: str) -> str:
    git("fetch", "--quiet", "--no-tags", remote, DEVELOPMENT_BRANCH, cwd=path)
    return git("rev-parse", "FETCH_HEAD", cwd=path)


def is_ancestor(path: Path, commit: str, head: str) -> bool:
    return run(
        ["git", "merge-base", "--is-ancestor", commit, head], cwd=path, check=False
    ).returncode == 0


def gitlink(path: str) -> str:
    entry = git("ls-tree", "HEAD", path).split()
    if len(entry) != 4 or entry[0] != "160000" or entry[1] != "commit":
        fail(f"{path} is not a recorded submodule gitlink")
    return entry[2]


def verify_sources() -> tuple[dict, dict]:
    require_clean_root()
    root_commit = git("rev-parse", "HEAD")
    root_head = fetch_development(ROOT, "origin")
    root = {
        "commit": root_commit,
        "clean": True,
        "remote": git("remote", "get-url", "origin"),
        "remote_development": root_head,
        "on_remote_development": is_ancestor(ROOT, root_commit, root_head),
    }
    sources = {}
    for name, source in SOURCES.items():
        path = ROOT / source["path"]
        url = git("config", "--file", ".gitmodules", f"submodule.{source['path']}.url")
        if url != source["url"]:
            fail(f"{source['path']} must come from {source['url']}")
        if not (path / ".git").exists():
            fail(f"{source['path']} is not initialized; run make init")
        commit = gitlink(source["path"])
        head = fetch_development(path, source["url"])
        if not is_ancestor(path, commit, head):
            fail(f"{name} gitlink {commit} is not on the remote development branch")
        sources[name] = {
            "repository": source["url"],
            "commit": commit,
            "remote_development": head,
            "on_remote_development": True,
            "files": {
                file: hashlib.sha256(
                    run(["git", "show", f"{commit}:{file}"], cwd=path, capture=False,
                        stdout=subprocess.PIPE).stdout
                ).hexdigest()
                for file in source["files"]
            },
        }
    return root, sources


def build_image(
    archive: Path, tag: str, target: str, arguments: dict[str, str], work: Path
) -> tuple[str, dict]:
    identifier_file, metadata_file = work / f"{target}.iid", work / f"{target}.json"
    identifier_file.unlink(missing_ok=True)
    command = ["docker", "build", "--target", target, "--tag", tag,
               "--iidfile", str(identifier_file), "--metadata-file", str(metadata_file)]
    for key, value in arguments.items():
        command += ["--build-arg", f"{key}={value}"]
    with archive.open("rb") as context:
        run([*command, "-"], stdin=context, docker=True)
    metadata = json.loads(metadata_file.read_text(encoding="utf-8")) if metadata_file.exists() else {}
    return identifier_file.read_text(encoding="utf-8").strip(), {
        key: metadata[key]
        for key in ("buildx.build.ref", "containerimage.config.digest", "containerimage.digest")
        if key in metadata
    }


def archive_tree(path: Path, tree: str, archive: Path) -> str:
    run(["git", "archive", "--format=tar", f"--output={archive}", tree], cwd=path)
    return sha256_file(archive)


def ensure_upstream(service: str) -> tuple[str, str]:
    reference = UPSTREAM_IMAGES[service]
    if local.inspect_image(reference) is None:
        run(["docker", "pull", reference], docker=True)
    metadata = local.inspect_image(reference)
    if metadata is None:
        fail(f"{reference} could not be resolved locally")
    name, _, digest = reference.partition("@sha256:")
    tag = f"{IMAGE_TAG_PREFIX}/{service}:{name.rsplit(':', 1)[1]}-{digest[:12]}"
    run(["docker", "tag", metadata["Id"], tag], docker=True)
    return metadata["Id"], tag


def describe_image(image_id: str, tag: str, **details) -> dict:
    metadata = local.inspect_image(image_id)
    if metadata is None:
        fail(f"{tag} disappeared before it could be recorded")
    config = metadata.get("Config") or {}
    labels = config.get("Labels") or {}
    return {
        "id": metadata["Id"],
        "tag": tag,
        "repo_digests": metadata.get("RepoDigests") or [],
        "created": metadata.get("Created"),
        "platform": f"{metadata.get('Os')}/{metadata.get('Architecture')}",
        "user": config.get("User", ""),
        "revision_label": labels.get("org.opencontainers.image.revision"),
        "source_label": labels.get("org.opencontainers.image.source"),
        **details,
    }


def command_build(home: Home) -> None:
    validate_home(home)
    settings = local.read_env_file(home.settings)
    local.validate_settings(settings)
    root, sources = verify_sources()
    public_inputs = {
        "VCS_REF": sources["frontend"]["commit"],
        "NEXT_PUBLIC_ENVIRONMENT": "staging",
        "NEXT_PUBLIC_VERSION": sources["frontend"]["commit"],
        "NEXT_PUBLIC_BASE_URL": settings["STAGING_APP_URL"],
        "NEXT_PUBLIC_BACKEND": staging.FRONTEND_CONTRACT["NEXT_PUBLIC_BACKEND"],
        "NEXT_PUBLIC_GRAPHQL_ENDPOINT": staging.FRONTEND_CONTRACT["NEXT_PUBLIC_GRAPHQL_ENDPOINT"],
        "NEXT_PUBLIC_FEATURESERV_ENDPOINT": staging.FRONTEND_CONTRACT["NEXT_PUBLIC_FEATURESERV_ENDPOINT"],
        "NEXT_PUBLIC_MAP_STYLE": settings["NEXT_PUBLIC_MAP_STYLE"],
        "NEXT_PUBLIC_LOG_LEVEL": settings["LOG_LEVEL"],
    }
    inputs_digest = hashlib.sha256(
        json.dumps(public_inputs, sort_keys=True).encode("utf-8")
    ).hexdigest()
    images = {}
    started = timestamp()
    with tempfile.TemporaryDirectory(prefix="build-", dir=home.work) as directory:
        work = Path(directory)
        for name, target, arguments, tag in (
            ("backend", "production", {"VCS_REF": sources["backend"]["commit"]},
             f"{IMAGE_TAG_PREFIX}/backend:{sources['backend']['commit']}"),
            ("frontend", "production", public_inputs,
             f"{IMAGE_TAG_PREFIX}/frontend:{sources['frontend']['commit']}-{inputs_digest[:12]}"),
        ):
            archive = work / f"{name}.tar"
            sources[name]["archive_sha256"] = archive_tree(
                ROOT / SOURCES[name]["path"], sources[name]["commit"], archive
            )
            print(f"Building {name} production image from {sources[name]['commit']}")
            image_id, build = build_image(archive, tag, target, arguments, work)
            images[name] = describe_image(image_id, tag, build=build, build_arguments=sorted(arguments))

        minio_archive = work / "minio.tar"
        minio = {
            "root_tree": git("rev-parse", "HEAD:docker/minio"),
            "archive_sha256": archive_tree(ROOT, "HEAD:docker/minio", minio_archive),
            "server_release": MINIO_SERVER_RELEASE,
            "server_commit": MINIO_SERVER_COMMIT,
            "client_release": MINIO_CLIENT_RELEASE,
            "client_commit": MINIO_CLIENT_COMMIT,
        }
        for service, target, arguments, tag in (
            ("storage", "server",
             {"SERVER_RELEASE": MINIO_SERVER_RELEASE, "SERVER_COMMIT": MINIO_SERVER_COMMIT},
             f"{IMAGE_TAG_PREFIX}/minio:{MINIO_SERVER_RELEASE}"),
            ("storage-init", "client",
             {"CLIENT_RELEASE": MINIO_CLIENT_RELEASE, "CLIENT_COMMIT": MINIO_CLIENT_COMMIT},
             f"{IMAGE_TAG_PREFIX}/mc:{MINIO_CLIENT_RELEASE}"),
        ):
            print(f"Building {service} from the root-pinned MinIO source tag")
            image_id, build = build_image(minio_archive, tag, target, arguments, work)
            images[service] = describe_image(image_id, tag, build=build)

    for service in UPSTREAM_IMAGES:
        image_id, tag = ensure_upstream(service)
        images[service] = describe_image(image_id, tag, upstream_reference=UPSTREAM_IMAGES[service])

    release_id = f"{now():%Y%m%dT%H%M%SZ}-{root['commit'][:12]}"
    release = {
        "RELEASE_ID": release_id,
        "RELEASE_VERSION": sources["frontend"]["commit"],
        **{key: images[service]["id"] for key, service in local.IMAGE_VARIABLES.items()},
    }
    local.validate_release_selection(release, allow_placeholders=False)
    local.validate_local_images(
        release,
        {"backend": sources["backend"]["commit"], "frontend": sources["frontend"]["commit"],
         "storage": MINIO_SERVER_COMMIT, "storage-init": MINIO_CLIENT_COMMIT},
    )
    docker_version = json.loads(
        run(["docker", "version", "--format", "{{json .}}"], capture=True, docker=True).stdout
    )
    state = load_state(home)
    manifest = {
        "schema": 1,
        "mode": "local-staging",
        "release_id": release_id,
        "build_started_at": started,
        "build_finished_at": timestamp(),
        "builder": {
            "host": socket.gethostname(),
            "docker_client": (docker_version.get("Client") or {}).get("Version"),
            "docker_server": (docker_version.get("Server") or {}).get("Version"),
            "buildx": run(["docker", "buildx", "version"], capture=True, docker=True).stdout.strip(),
        },
        "root": root,
        "sources": {**sources, "minio": minio},
        "frontend_public_build_inputs": public_inputs,
        "frontend_public_build_inputs_sha256": inputs_digest,
        "images": images,
        "release_env": release,
        "previous_release": state.get("current_release"),
        "registry": None,
        "attestations": "none: the local docker image store keeps no provenance or SBOM",
    }
    directory = home.releases / release_id
    make_directory(directory, 0o700)
    write_private(directory / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    write_private(
        directory / "release.env",
        "".join(f"{key}={release[key]}\n" for key in sorted(release)),
    )
    record(home, state, "build", release=release_id, root_commit=root["commit"])
    print(f"Recorded release {release_id} in {directory}")
    for key, service in local.IMAGE_VARIABLES.items():
        print(f"  {key}={images[service]['id']}  ({images[service]['tag']})")
    if not root["on_remote_development"]:
        print("This root commit is not on origin/development; migrate refuses this release.")
    print(f"Next: migrate --release {release_id}")


# Lifecycle -----------------------------------------------------------------


def require_root_merged(manifest: dict) -> None:
    head = fetch_development(ROOT, "origin")
    if not is_ancestor(ROOT, manifest["root"]["commit"], head):
        fail("the release root commit is not on origin/development; rebuild from merged development")


def command_preflight(home: Home, release_id: str | None) -> None:
    release_file = home.release_file(release_id) if release_id else home.release
    _, release, manifest, _ = preflight(home, release_file)
    print(f"Release {release['RELEASE_ID']} passed local-staging preflight; nothing was started.")
    print(f"  root {manifest['root']['commit']}")
    for name in SOURCES:
        print(f"  {name} {manifest['sources'][name]['commit']}")


def command_migrate(home: Home, release_id: str) -> None:
    release_file = home.release_file(release_id)
    _, release, manifest, _ = preflight(home, release_file)
    require_root_merged(manifest)
    print(f"Running the single-writer migration job for release {release_id}")
    compose(home, "run", "--rm", "migrate", release_file=release_file, profiles=local.PROFILES)
    state = load_state(home)
    state["migrations"][release_id] = {
        "completed_at": timestamp(),
        "backend_image": release["BACKEND_IMAGE"],
        "previous_release": state.get("current_release"),
    }
    select_release(home, release_file)
    state["current_release"] = release_id
    record(home, state, "migrate", release=release_id)
    print(f"Release {release_id} is migrated and selected. Next: start")


def command_start(home: Home) -> None:
    _, release, _, _ = preflight(home, home.release)
    state = load_state(home)
    require_migrated(state, release)
    compose(home, "up", "--detach", "--wait")
    record(home, state, "start", release=release["RELEASE_ID"])
    print(f"Release {release['RELEASE_ID']} is running. Next: smoke")


def command_stop(home: Home) -> None:
    light_selection(home)
    compose(home, "stop")
    record(home, load_state(home), "stop")


def command_down(home: Home) -> None:
    # Removes containers and networks only; named volumes are always kept.
    light_selection(home)
    compose(home, "down", "--remove-orphans", profiles=local.PROFILES)
    record(home, load_state(home), "down")


def command_status(home: Home) -> None:
    settings, release = light_selection(home)
    state = load_state(home)
    port = local.https_port(settings)
    migrated = release["RELEASE_ID"] in state["migrations"]
    print(f"Release:   {release['RELEASE_ID']} ({'migrated' if migrated else 'NOT migrated'})")
    print(f"App:       {local.app_origin(port)}")
    print(f"Media:     {local.media_origin(port)}")
    compose(home, "ps", "--all", profiles=local.PROFILES)
    for container in project_containers():
        name = container["Name"].lstrip("/")
        for binding in published_bindings(container)[:1]:
            print(f"Published: {name} {binding.get('HostIp')}:{binding.get('HostPort')}")


def command_releases(home: Home) -> None:
    validate_home(home)
    state = load_state(home)
    for directory in sorted(home.releases.iterdir()):
        manifest = load_manifest(home, directory.name)
        marker = "*" if directory.name == state.get("current_release") else " "
        migrated = "migrated" if directory.name in state["migrations"] else "built"
        print(
            f"{marker} {directory.name}  {migrated:8}  root {manifest['root']['commit'][:12]}"
            f"  backend {manifest['sources']['backend']['commit'][:12]}"
            f"  frontend {manifest['sources']['frontend']['commit'][:12]}"
        )


def command_rollback(home: Home, release_id: str) -> None:
    release_file = home.release_file(release_id)
    state = load_state(home)
    current = state.get("current_release")
    if release_id == current:
        fail(f"release {release_id} is already selected")
    migration = state["migrations"].get(release_id)
    if not migration:
        fail("rollback selects only a release that was previously migrated and deployed")
    _, release, _, _ = preflight(home, release_file)
    require_migrated(state, release)
    select_release(home, release_file)
    state["current_release"] = release_id
    record(home, state, "rollback", release=release_id, previous_release=current)
    compose(home, "up", "--detach", "--wait")
    print(f"Rolled back from {current} to {release_id} by recorded image ID.")
    print("The database schema was not reversed. If the newer release applied a")
    print("migration this release cannot run against, restore the paired backup")
    print("taken before that upgrade.")


# Smoke ---------------------------------------------------------------------


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to loopback while presenting and verifying the origin's name."""

    def connect(self) -> None:
        connection = socket.create_connection((local.LOOPBACK, self.port), self.timeout)
        self.sock = self._context.wrap_socket(connection, server_hostname=self.host)


def edge_request(
    context: ssl.SSLContext, host: str, port: int, method: str, path: str,
    *, headers: dict | None = None, body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = PinnedHTTPSConnection(host, port, context=context, timeout=20)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


def from_minio(headers: dict[str, str]) -> bool:
    return headers.get("server", "").lower().startswith("minio") or "x-amz-request-id" in headers


def smoke_checks(settings: dict, context: ssl.SSLContext):
    port = local.https_port(settings)
    app, media, origin = local.APP_HOST, local.MEDIA_HOST, local.app_origin(port)
    public, private = settings["MINIO_BUCKET"], settings["MINIO_PRIVATE_MEDIA_BUCKET"]

    def call(host, method, path, **options):
        return edge_request(context, host, port, method, path, **options)

    def check_json(status, body, predicate):
        try:
            data = json.loads(body)
            return status == 200 and isinstance(data, dict) and predicate(data)
        except ValueError:
            return False

    status, headers, _ = call(app, "GET", "/")
    yield "application home page", status == 200 and not from_minio(headers), status
    status, _, body = call(
        app, "POST", "/api/smokemap/graphql",
        headers={"Content-Type": "application/json"}, body=b'{"query":"{ __typename }"}',
    )
    yield "GraphQL through the same-origin proxy", check_json(
        status, body, lambda data: data.get("data", {}).get("__typename") == "Query"
    ), status
    status, _, body = call(app, "GET", f"/api/smokemap/locations?bbox={SMOKE_BBOX}&zoom=12")
    yield "bounded viewport GeoJSON", check_json(
        status, body, lambda data: data.get("type") == "FeatureCollection"
        and isinstance(data.get("features"), list)
    ), status
    status, headers, _ = call(app, "GET", "/minio/health/live")
    yield "application origin never serves MinIO", not from_minio(headers), status
    status, _, _ = call(media, "GET", "/minio/health/live")
    yield "media origin reaches the MinIO API", status == 200, status
    for path in ("/graphql/", "/health/ready/"):
        status, headers, _ = call(media, "GET", path)
        yield f"media origin never serves backend {path}", from_minio(headers) and status >= 400, status
    for path in ("/", f"/{private}?list-type=2", f"/{public}?list-type=2"):
        status, _, _ = call(media, "GET", path)
        yield f"anonymous listing {path} is denied", status == 403, status
    for bucket in (private, public):
        status, _, _ = call(media, "PUT", f"/{bucket}/{SMOKE_OBJECT}", body=b"x")
        yield f"unsigned write to {bucket} is denied", status == 403, status
    status, _, _ = call(media, "GET", f"/{private}/{SMOKE_OBJECT}")
    yield "unsigned private read is denied", status == 403, status
    status, _, _ = call(media, "GET", "/minio/admin/v3/info")
    yield "unsigned admin API is denied", status == 403, status
    for request_origin, allowed in ((origin, True), ("https://untrusted.invalid", False)):
        status, headers, _ = call(
            media, "OPTIONS", f"/{private}/",
            headers={"Origin": request_origin, "Access-Control-Request-Method": "POST"},
        )
        granted = headers.get("access-control-allow-origin")
        passed = granted == origin if allowed else granted in (None, "")
        yield f"upload CORS {'allows' if allowed else 'refuses'} {request_origin}", passed, status
    try:
        edge_request(context, f"unknown.{app.split('.', 1)[1]}", port, "GET", "/")
        rejected = False
    except (ssl.SSLError, ConnectionResetError):
        # An unrecognized-name alert, a certificate mismatch (an SSLError
        # subclass), or a reset mean no session; a refused connection does not.
        rejected = True
    yield "unknown TLS names are rejected", rejected, "handshake"
    exposed = [
        f"{container['Name'].lstrip('/')} {binding.get('HostIp')}:{binding.get('HostPort')}"
        for container in project_containers()
        for binding in published_bindings(container)
        if ((container.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.service")
        != local.EDGE_SERVICE
        or binding.get("HostIp") != local.LOOPBACK
        or binding.get("HostPort") != str(port)
    ]
    yield "only the edge publishes, and only on loopback", not exposed, ", ".join(exposed) or "edge"


def command_smoke(home: Home) -> None:
    settings, release = light_selection(home)
    require_migrated(load_state(home), release)
    context = ssl.create_default_context(cafile=str(home.edge_ca))
    failures = 0
    for name, passed, detail in smoke_checks(settings, context):
        failures += not passed
        print(f"{'PASS' if passed else 'FAIL'}  {name} ({detail})")
    if failures:
        fail(f"{failures} local-staging smoke check(s) failed")
    print(f"All local-staging smoke checks passed for release {release['RELEASE_ID']}.")


# Backup and restore --------------------------------------------------------


def running_services(home: Home) -> set[str]:
    return set(
        compose(home, "ps", "--services", "--status", "running", capture=True).stdout.split()
    )


def project_volume(config: dict, key: str) -> str:
    name = config["volumes"][key]["name"]
    result = run(["docker", "volume", "inspect", name], capture=True, check=False, docker=True)
    if result.returncode:
        fail(f"{name} does not exist yet; start local staging before backing it up")
    labels = json.loads(result.stdout)[0].get("Labels") or {}
    if labels.get("com.docker.compose.project") != PROJECT_NAME:
        fail(f"{name} does not belong to the {PROJECT_NAME} project")
    return name


def volume_helper(image: str, volume: str, *, writable: bool) -> list[str]:
    """A network-less one-off container that sees only one project volume."""

    command = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--security-opt", "no-new-privileges:true", "--cap-drop", "ALL",
        "--label", f"io.smokemap.local-staging.helper={'restore' if writable else 'backup'}",
        "--volume", f"{volume}:/data{'' if writable else ':ro'}",
    ]
    if writable:
        command += ["--interactive", "--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE",
                    "--cap-add", "FOWNER"]
    return [*command, "--entrypoint", "sh", image, "-ec"]


def database_command(settings: dict, *arguments: str) -> list[str]:
    return ["exec", "-T", "--user", "postgres", "db", *arguments,
            "--username", settings["POSTGRES_USER"]]


def command_backup(home: Home, label: str | None = None) -> str:
    settings, release, _, config = preflight(home, home.release)
    state = load_state(home)
    require_migrated(state, release)
    media_volume = project_volume(config, "minio-data")
    project_volume(config, "postgres-data")
    backup_id = f"{now():%Y%m%dT%H%M%SZ}"
    directory = home.backups / backup_id
    make_directory(directory, 0o700)
    dump, media = directory / "database.dump", directory / "media.tar"
    was_running = running_services(home)
    print(f"Backing up release {release['RELEASE_ID']} as {backup_id}; writers pause meanwhile.")
    try:
        writers = [service for service in WRITERS if service in was_running]
        if writers:
            compose(home, "stop", *writers)
        compose(home, "up", "--detach", "--wait", "db")
        with open(dump, "wb", opener=private_opener) as output:
            compose(home, *database_command(settings, "pg_dump", "--format=custom",
                                            "--dbname", settings["POSTGRES_DB"]), stdout=output)
        with dump.open("rb") as archive:
            compose(home, *database_command(settings, "pg_restore", "--list"),
                    stdin=archive, stdout=subprocess.DEVNULL)
        compose(home, "stop", "storage")
        with open(media, "wb", opener=private_opener) as output:
            run([*volume_helper(release["POSTGIS_IMAGE"], media_volume, writable=False),
                 "exec tar -C /data --numeric-owner -cf - ."], stdout=output, docker=True)
        with tarfile.open(media) as archive:
            members = sum(1 for _ in archive)
    finally:
        if was_running:
            compose(home, "up", "--detach", "--wait")
        else:
            compose(home, "stop")
    metadata = {
        "schema": 1,
        "backup_id": backup_id,
        "created_at": timestamp(),
        "label": label,
        "project": PROJECT_NAME,
        "release_id": release["RELEASE_ID"],
        "images": {"backend": release["BACKEND_IMAGE"], "postgis": release["POSTGIS_IMAGE"],
                   "minio": release["MINIO_IMAGE"]},
        "database": {"name": settings["POSTGRES_DB"], "format": "pg_dump custom"},
        "buckets": [settings["MINIO_BUCKET"], settings["MINIO_PRIVATE_MEDIA_BUCKET"]],
        "consistency": "writers stopped; database dumped, then MinIO stopped and archived",
        "files": {
            path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in (dump, media)
        },
        "media_entries": members,
    }
    write_private(directory / "backup.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    record(home, state, "backup", backup=backup_id, release=release["RELEASE_ID"], label=label)
    print(f"Recorded paired backup {backup_id} in {directory}")
    return backup_id


def load_backup(home: Home, backup_id: str) -> tuple[Path, dict]:
    if not BACKUP_ID.fullmatch(backup_id):
        fail("a backup identifier looks like 20260101T000000Z")
    directory = home.backups / backup_id
    path = directory / "backup.json"
    if not path.is_file():
        fail(f"backup {backup_id} is not recorded")
    staging.validate_permissions(path, 0o600, "backup metadata")
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if metadata.get("schema") != 1 or metadata.get("project") != PROJECT_NAME:
        fail(f"backup {backup_id} does not belong to {PROJECT_NAME}")
    for name, expected in metadata["files"].items():
        staging.validate_permissions(directory / name, 0o600, f"backup {name}")
        if sha256_file(directory / name) != expected["sha256"]:
            fail(f"backup {backup_id} {name} does not match its recorded checksum")
    return directory, metadata


def command_restore(home: Home, backup_id: str, confirm: str, safety_backup: bool) -> None:
    if confirm != PROJECT_NAME:
        fail(f"restore replaces local-staging data; pass --confirm {PROJECT_NAME}")
    directory, metadata = load_backup(home, backup_id)
    settings, release, _, config = preflight(home, home.release)
    require_migrated(load_state(home), release)
    if metadata["images"]["backend"] != release["BACKEND_IMAGE"]:
        fail(
            f"backup {backup_id} pairs with release {metadata['release_id']}; roll back to it "
            "before restoring, then migrate forward"
        )
    media_volume = project_volume(config, "minio-data")
    project_volume(config, "postgres-data")
    safety = command_backup(home, label=f"before-restore-{backup_id}") if safety_backup else None
    database = settings["POSTGRES_DB"]
    print(f"Restoring backup {backup_id}; the safety backup is {safety or 'skipped'}.")
    try:
        compose(home, "stop", *WRITERS, "storage")
        compose(home, "up", "--detach", "--wait", "db")
        for statement in (
            f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)',
            f'CREATE DATABASE "{database}" OWNER "{settings["POSTGRES_USER"]}" TEMPLATE template0',
        ):
            compose(home, *database_command(settings, "psql", "--no-psqlrc", "--set",
                                            "ON_ERROR_STOP=1", "--dbname", "postgres",
                                            "--command", statement))
        with (directory / "database.dump").open("rb") as archive:
            compose(home, *database_command(settings, "pg_restore", "--exit-on-error",
                                            "--single-transaction", "--no-owner",
                                            "--dbname", database), stdin=archive)
        with (directory / "media.tar").open("rb") as archive:
            run([*volume_helper(release["POSTGIS_IMAGE"], media_volume, writable=True),
                 'cd /data; for entry in * .[!.]* ..?*; do '
                 'if [ -e "$entry" ] || [ -L "$entry" ]; then rm -rf -- "$entry"; fi; done; '
                 "exec tar -C /data --numeric-owner -xpf -"], stdin=archive, docker=True)
    except BaseException:
        print(f"Restore stopped before completion; services stay stopped. Safety backup: {safety}",
              file=sys.stderr)
        raise
    compose(home, "up", "--detach", "--wait")
    state = load_state(home)
    record(home, state, "restore", backup=backup_id, safety_backup=safety)
    print(f"Restored backup {backup_id} under release {release['RELEASE_ID']}. Next: smoke")


# CLI -----------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--home", required=True, help="absolute local-staging home outside the repository")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create settings, secrets, and staging-only TLS material")
    init.add_argument("--https-port", type=int, default=8443)
    init.add_argument("--secret-gid", type=int)
    commands.add_parser("build", help="build and record a release from the root gitlinks")
    commands.add_parser("releases", help="list recorded releases")
    preflight_command = commands.add_parser("preflight", help="validate a release without starting it")
    preflight_command.add_argument("--release")
    migrate = commands.add_parser("migrate", help="run the one-shot migration and select the release")
    migrate.add_argument("--release", required=True)
    commands.add_parser("start", help="start the selected, migrated release")
    commands.add_parser("stop", help="stop containers, keeping them and all data")
    commands.add_parser("down", help="remove containers and networks, keeping all volumes")
    commands.add_parser("status", help="show the selected release and containers")
    commands.add_parser("smoke", help="probe the running edge, origins, and exposure")
    backup = commands.add_parser("backup", help="take a paired database and media backup")
    backup.add_argument("--label")
    restore = commands.add_parser("restore", help="replace local-staging data from a paired backup")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--confirm", required=True)
    restore.add_argument("--skip-safety-backup", action="store_true")
    rollback = commands.add_parser("rollback", help="reselect a previously migrated release by image ID")
    rollback.add_argument("--release", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        home = resolve_home(args.home)
        if args.command == "init":
            command_init(home, args.https_port, args.secret_gid)
        elif args.command == "build":
            command_build(home)
        elif args.command == "releases":
            command_releases(home)
        elif args.command == "preflight":
            command_preflight(home, args.release)
        elif args.command == "migrate":
            command_migrate(home, args.release)
        elif args.command == "start":
            command_start(home)
        elif args.command == "stop":
            command_stop(home)
        elif args.command == "down":
            command_down(home)
        elif args.command == "status":
            command_status(home)
        elif args.command == "smoke":
            command_smoke(home)
        elif args.command == "backup":
            command_backup(home, args.label)
        elif args.command == "restore":
            command_restore(home, args.backup, args.confirm, not args.skip_safety_backup)
        elif args.command == "rollback":
            command_rollback(home, args.release)
    except (OSError, json.JSONDecodeError, KeyError, ValidationError) as error:
        print(f"Local staging {args.command} failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
