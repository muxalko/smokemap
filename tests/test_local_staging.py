from __future__ import annotations

import ast
import contextlib
import copy
import importlib.util
import io
import itertools
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "local_staging", ROOT / "scripts" / "local-staging.py"
)
assert SPEC is not None and SPEC.loader is not None
local_staging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local_staging)
local = local_staging.local
staging = local_staging.staging

PORT = 8443
FAKE_IMAGES = {key: "sha256:" + f"{index:x}" * 64 for index, key in enumerate(local.IMAGE_VARIABLES, 1)}
FAKE_RELEASE_ID = "20261025T120000Z-0123456789ab"
FRONTEND_COMMIT = "a" * 40
BACKEND_COMMIT = "b" * 40


def setUpModule() -> None:
    global HOME_DIRECTORY, HOME, INIT_OUTPUT
    HOME_DIRECTORY = tempfile.TemporaryDirectory(prefix="smokemap-local-staging-", dir="/tmp")
    HOME = local_staging.Home(Path(HOME_DIRECTORY.name) / "home")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        local_staging.command_init(HOME, PORT, None)
    INIT_OUTPUT = output.getvalue()
    write_fake_release(HOME)


def tearDownModule() -> None:
    HOME_DIRECTORY.cleanup()


def write_fake_release(home) -> Path:
    release = {"RELEASE_ID": FAKE_RELEASE_ID, "RELEASE_VERSION": FRONTEND_COMMIT, **FAKE_IMAGES}
    directory = home.releases / FAKE_RELEASE_ID
    directory.mkdir(mode=0o700, exist_ok=True)
    local_staging.write_private(
        directory / "release.env", "".join(f"{key}={value}\n" for key, value in release.items())
    )
    settings = local.read_env_file(home.settings)
    manifest = {
        "schema": 1,
        "release_id": FAKE_RELEASE_ID,
        "root": {"commit": "c" * 40},
        "sources": {
            "backend": {"commit": BACKEND_COMMIT},
            "frontend": {"commit": FRONTEND_COMMIT},
        },
        "frontend_public_build_inputs": {
            "NEXT_PUBLIC_BASE_URL": settings["STAGING_APP_URL"],
            "NEXT_PUBLIC_MAP_STYLE": settings["NEXT_PUBLIC_MAP_STYLE"],
            "NEXT_PUBLIC_LOG_LEVEL": settings["LOG_LEVEL"],
        },
        "release_env": release,
    }
    local_staging.write_private(directory / "manifest.json", json.dumps(manifest))
    return directory / "release.env"


def fake_inspect(overrides: dict | None = None):
    revisions = {
        "BACKEND_IMAGE": BACKEND_COMMIT,
        "FRONTEND_IMAGE": FRONTEND_COMMIT,
        "MINIO_IMAGE": local_staging.MINIO_SERVER_COMMIT,
        "MINIO_CLIENT_IMAGE": local_staging.MINIO_CLIENT_COMMIT,
    }
    by_id = {}
    for key, image in FAKE_IMAGES.items():
        user = {"BACKEND_IMAGE": "smokemap", "FRONTEND_IMAGE": "10001:10001", "EDGE_PROXY_IMAGE": "101"}.get(key, "")
        by_id[image] = {
            "Id": image,
            "Config": {"User": user, "Labels": {"org.opencontainers.image.revision": revisions.get(key, "")}},
        }
    for key, change in (overrides or {}).items():
        if change is None:
            by_id.pop(FAKE_IMAGES[key])
        else:
            by_id[FAKE_IMAGES[key]] = change(copy.deepcopy(by_id[FAKE_IMAGES[key]]))
    return lambda image: by_id.get(image)


EXPECTED_REVISIONS = {
    "backend": BACKEND_COMMIT,
    "frontend": FRONTEND_COMMIT,
    "storage": local_staging.MINIO_SERVER_COMMIT,
    "storage-init": local_staging.MINIO_CLIENT_COMMIT,
}


class SmokeViewportTests(unittest.TestCase):
    def viewport_result(self, status=200, body=b'{"type":"FeatureCollection","features":[]}'):
        # Consume only the application probes: no sockets, Docker, or live data.
        responses = [(200, {}, b"home"), (200, {}, b'{"data":{"__typename":"Query"}}'),
                     (status, {}, body)]
        with mock.patch.object(local_staging, "edge_request", side_effect=responses) as request:
            checks = list(itertools.islice(
                local_staging.smoke_checks(local.read_env_file(HOME.settings), None), 3
            ))
        return checks[-1], request.call_args_list[-1].args[4]

    def test_smoke_query_satisfies_the_pinned_backend_viewport_parser(self) -> None:
        result, path = self.viewport_result()
        self.assertTrue(result[1])  # An empty viewport is a successful result.
        parsed = urlsplit(path)
        self.assertEqual(parsed.path, "/api/smokemap/locations")
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        self.assertEqual(set(query), {"bbox", "zoom"})
        # Execute the actual pure parser from the pinned backend, without Django
        # dependencies. This catches contract drift (including required zoom).
        source = ast.parse((ROOT / "smokemap-django-backend/backend/views.py").read_text())
        names = {"ViewportQueryError", "parse_viewport_query"}
        constants = {"VIEWPORT_MAX_SPAN_DEGREES", "VIEWPORT_MAX_CATEGORIES"}
        nodes = [node for node in source.body
                 if getattr(node, "name", None) in names
                 or (isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id in constants
                             for target in node.targets))]
        namespace = {"math": math}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "pinned_viewport_parser", "exec"), namespace)
        bbox, zoom, categories = namespace["parse_viewport_query"](query)
        self.assertEqual(bbox, (-0.5, 51.3, 0.3, 51.7))
        self.assertEqual(zoom, 12)
        self.assertEqual(categories, ())
        for invalid in ({"in_bbox": query["bbox"]}, {"bbox": query["bbox"]}):
            with self.subTest(query=invalid):
                with self.assertRaises(namespace["ViewportQueryError"]):
                    namespace["parse_viewport_query"](invalid)

    def test_smoke_rejects_failed_or_malformed_geojson(self) -> None:
        for status, body in (
            (400, b'{"code":"invalid_viewport","detail":"bbox is required"}'),
            (400, b'{"type":"FeatureCollection","features":[]}'),
            (200, b'not json'), (200, b'[]'),
            (200, b'{"type":"FeatureCollection"}'),
            (200, b'{"type":"FeatureCollection","features":{}}'),
            (200, b'{"type":"Feature","features":[]}'),
        ):
            with self.subTest(status=status, body=body):
                self.assertFalse(self.viewport_result(status, body)[0][1])


class LocalStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = local.render(local.SETTINGS_TEMPLATE, local.RELEASE_TEMPLATE)

    def assert_rejected(self, config: dict, message: str) -> None:
        with self.assertRaisesRegex(local.ValidationError, message):
            local.validate_structure(config, PORT, allow_placeholders=True)

    def test_checked_in_templates_are_structurally_valid(self) -> None:
        local.validate_template()

    def test_cleanup_must_disable_the_inherited_web_probe(self) -> None:
        self.assertEqual(self.config["services"]["media-cleanup"]["healthcheck"], {"disable": True})
        for healthcheck in (None, {}, {"disable": False},
                            self.config["services"]["backend"]["healthcheck"]):
            config = copy.deepcopy(self.config)
            config["services"]["media-cleanup"]["healthcheck"] = healthcheck
            self.assert_rejected(config, "media-cleanup must explicitly disable")

    def test_local_overlay_rejects_anonymous_policy_drift(self) -> None:
        for old, new in (
            ('"s3:GetObject"', '"s3:GetObject","s3:ListBucket"'),
            ('"s3:GetObject"', '"s3:PutObject"'),
            ('arn:aws:s3:::$${MINIO_BUCKET}/*', 'arn:aws:s3:::$${MINIO_PRIVATE_MEDIA_BUCKET}/*'),
            ('mc anonymous set-json "$${policy_file}"', 'mc anonymous set download'),
            ('mc anonymous set private', 'mc anonymous set download'),
        ):
            with self.subTest(replacement=new):
                config = copy.deepcopy(self.config)
                command = config["services"]["storage-init"]["command"]
                command[0] = command[0].replace(old, new, 1)
                self.assert_rejected(config, "storage-init must install only anonymous GetObject")

    def test_tunnel_is_absent_and_edge_is_the_only_publisher(self) -> None:
        services = self.config["services"]
        self.assertNotIn("cloudflared", services)
        self.assertNotIn("cloudflared_token", self.config["secrets"])
        publishers = {name for name, service in services.items() if service.get("ports")}
        self.assertEqual(publishers, {local.EDGE_SERVICE})
        self.assertEqual(
            services[local.EDGE_SERVICE]["ports"],
            [{"name": "https", "mode": "ingress", "host_ip": "127.0.0.1",
              "target": 8443, "published": str(PORT), "protocol": "tcp"}],
        )

    def test_public_or_wildcard_bind_is_rejected(self) -> None:
        for host_ip in ("0.0.0.0", "::", "", None, "192.168.1.10"):
            with self.subTest(host_ip=host_ip):
                config = copy.deepcopy(self.config)
                binding = config["services"][local.EDGE_SERVICE]["ports"][0]
                if host_ip is None:
                    binding.pop("host_ip")
                else:
                    binding["host_ip"] = host_ip
                self.assert_rejected(config, "must bind only to 127.0.0.1")

    def test_any_other_published_or_exposed_port_is_rejected(self) -> None:
        for service in ("db", "backend", "storage", "frontend"):
            with self.subTest(service=service):
                config = copy.deepcopy(self.config)
                config["services"][service]["ports"] = [
                    {"host_ip": "127.0.0.1", "target": 5432, "published": "5432"}
                ]
                self.assert_rejected(config, f"{service} must not publish a port")
        config = copy.deepcopy(self.config)
        config["services"]["storage"]["expose"] = ["9001"]
        self.assert_rejected(config, "storage must not expose a port")
        config = copy.deepcopy(self.config)
        config["services"][local.EDGE_SERVICE]["ports"].append(
            {"host_ip": "127.0.0.1", "target": 8081, "published": "8081"}
        )
        self.assert_rejected(config, "exactly one HTTPS port")

    def test_published_port_must_match_the_origins(self) -> None:
        config = copy.deepcopy(self.config)
        config["services"][local.EDGE_SERVICE]["ports"][0]["published"] = "9443"
        self.assert_rejected(config, "exactly LOCAL_STAGING_HTTPS_PORT")
        config = copy.deepcopy(self.config)
        config["services"][local.EDGE_SERVICE]["ports"][0]["target"] = 8081
        self.assert_rejected(config, "only its TCP HTTPS listener")

    def test_development_and_privileged_ports_are_rejected(self) -> None:
        for value in ("3000", "5432", "8000", "9000", "9001"):
            with self.subTest(port=value):
                with self.assertRaisesRegex(local.ValidationError, "development stack port"):
                    local.https_port({"LOCAL_STAGING_HTTPS_PORT": value})
        for value in ("443", "80", "0", "70000", "8443-8444", ""):
            with self.subTest(port=value):
                with self.assertRaisesRegex(local.ValidationError, "unprivileged TCP port"):
                    local.https_port({"LOCAL_STAGING_HTTPS_PORT": value})

    def test_development_project_and_resources_are_never_shared(self) -> None:
        config = copy.deepcopy(self.config)
        config["name"] = "smokemap"
        self.assert_rejected(config, "project name must remain smokemap-local-staging")
        for kind, key, change, message in (
            ("volumes", "postgres-data", {"name": "smokemap_postgres-data"}, "scoped to the"),
            ("volumes", "minio-data", {"external": True}, "external resource"),
            ("volumes", "postgres-data", {"driver_opts": {"o": "bind"}}, "default local driver"),
            ("networks", "database", {"name": "smokemap_default"}, "scoped to the"),
            ("networks", "media", {"external": True}, "external resource"),
            ("networks", "database", {"internal": False}, "database network must remain internal"),
        ):
            with self.subTest(kind=kind, key=key, change=change):
                config = copy.deepcopy(self.config)
                config[kind][key].update(change)
                self.assert_rejected(config, message)
        for key, value in (
            ("container_name", "smokemap-db-1"),
            ("network_mode", "host"),
            ("volumes_from", ["smokemap-db-1"]),
        ):
            with self.subTest(key=key):
                config = copy.deepcopy(self.config)
                config["services"]["db"][key] = value
                self.assert_rejected(config, f"db must not set {key}")
        config = copy.deepcopy(self.config)
        config["services"]["db"]["volumes"][0]["source"] = "smokemap_postgres-data"
        self.assert_rejected(config, "only project-scoped named volumes")

    def test_mutable_registry_and_placeholder_images_are_rejected(self) -> None:
        for image in (
            "postgis/postgis:17-3.5",
            "registry.test/smokemap/backend@sha256:" + "1" * 64,
            "sha256:" + "A" * 64,
        ):
            with self.subTest(image=image):
                config = copy.deepcopy(self.config)
                config["services"]["backend"]["image"] = image
                self.assert_rejected(config, "content-addressed local image ID")
        with self.assertRaisesRegex(local.ValidationError, "placeholder image ID"):
            local.validate_structure(self.config, PORT, allow_placeholders=False)

    def test_startup_pulls_are_rejected(self) -> None:
        for policy in (None, "always", "missing"):
            with self.subTest(policy=policy):
                config = copy.deepcopy(self.config)
                config["services"]["storage"]["pull_policy"] = policy
                self.assert_rejected(config, "storage must never pull")

    def test_applications_and_edge_must_run_without_root_or_privileges(self) -> None:
        for service in (*local.APP_SERVICES, local.EDGE_SERVICE):
            for key, value, message in (
                ("user", "0:0", "non-root user"),
                ("cap_drop", [], "drop every Linux capability"),
                ("security_opt", [], "forbid privilege escalation"),
            ):
                with self.subTest(service=service, key=key):
                    config = copy.deepcopy(self.config)
                    config["services"][service][key] = value
                    self.assert_rejected(config, message)
        config = copy.deepcopy(self.config)
        config["services"]["frontend"]["cap_add"] = ["NET_ADMIN"]
        self.assert_rejected(config, "frontend must not add Linux capabilities")

    def test_edge_mounts_and_reaches_only_its_reviewed_inputs(self) -> None:
        cases = (
            ("read_only", False, "read-only root filesystem"),
            ("entrypoint", ["nginx", "-g", "daemon off;"], "only the reviewed configuration"),
            ("configs", [{"source": "postgres_init", "target": local.EDGE_CONFIG_TARGET}],
             "only the reviewed nginx configuration"),
        )
        for key, value, message in cases:
            with self.subTest(key=key):
                config = copy.deepcopy(self.config)
                config["services"][local.EDGE_SERVICE][key] = value
                self.assert_rejected(config, message)
        config = copy.deepcopy(self.config)
        config["services"][local.EDGE_SERVICE]["secrets"].append(
            {"source": "postgres_tls_private_key", "target": "/run/secrets/postgres_tls_private_key"}
        )
        self.assert_rejected(config, "edge must mount only its own TLS")
        config = copy.deepcopy(self.config)
        config["services"]["frontend"]["secrets"].append(
            {"source": "edge_tls_private_key", "target": "/run/secrets/edge_tls_private_key"}
        )
        self.assert_rejected(config, "frontend must not mount the local edge TLS")
        for network in ("application", "database", "media"):
            with self.subTest(network=network):
                config = copy.deepcopy(self.config)
                config["services"][local.EDGE_SERVICE]["networks"][network] = None
                self.assert_rejected(config, "edge network reachability changed")

    def test_backend_and_frontend_production_contracts_are_reused(self) -> None:
        config = copy.deepcopy(self.config)
        for name in staging.BACKEND_SERVICES:
            config["services"][name]["environment"]["POSTGRES_SSLMODE"] = "require"
        self.assert_rejected(config, "backend POSTGRES_SSLMODE must be")
        config = copy.deepcopy(self.config)
        config["services"]["frontend"]["environment"]["BACKEND_INTERNAL_URL"] = "http://backend:8000"
        self.assert_rejected(config, "frontend BACKEND_INTERNAL_URL")
        config = copy.deepcopy(self.config)
        config["services"]["storage"]["environment"]["MINIO_BROWSER"] = "on"
        self.assert_rejected(config, "MinIO browser console must remain disabled")

    def test_search_path_preserves_application_schema_and_public_postgis(self) -> None:
        for name in staging.BACKEND_SERVICES:
            self.assertEqual(
                self.config["services"][name]["environment"]["POSTGRES_OPTIONS"],
                "-c search_path=smokemap,public",
            )
        for value in (
            "-c search_path=smokemap",
            "-c search_path=public,smokemap",
            "-c search_path=public",
        ):
            with self.subTest(options=value):
                config = copy.deepcopy(self.config)
                for name in staging.BACKEND_SERVICES:
                    config["services"][name]["environment"]["POSTGRES_OPTIONS"] = value
                self.assert_rejected(config, "backend POSTGRES_OPTIONS must be")

    def test_origins_are_pinned_to_reserved_local_names(self) -> None:
        for key, value in (
            ("CORS_ALLOWED_ORIGINS", "https://staging.example.com"),
            ("MEDIA_UPLOAD_ENDPOINT_URL", local.app_origin(PORT)),
            ("AWS_S3_ENDPOINT_URL", "https://uploads.staging.example.com"),
        ):
            with self.subTest(key=key):
                config = copy.deepcopy(self.config)
                for name in staging.BACKEND_SERVICES:
                    config["services"][name]["environment"][key] = value
                self.assert_rejected(config, f"{key} must be exactly")

    def test_external_preflight_still_rejects_local_configuration(self) -> None:
        with self.assertRaisesRegex(staging.ValidationError, "smokemap-staging"):
            staging.validate_structure(self.config, allow_placeholders=True)
        renamed = copy.deepcopy(self.config)
        renamed["name"] = "smokemap-staging"
        with self.assertRaisesRegex(staging.ValidationError, "differ from the reviewed topology"):
            staging.validate_structure(renamed, allow_placeholders=True)
        for origin in (local.app_origin(PORT), local.media_origin(PORT)):
            with self.subTest(origin=origin):
                with self.assertRaisesRegex(staging.ValidationError, "exact public HTTPS origin"):
                    staging.require_https_origin(origin, "STAGING_APP_URL")
        staging.validate_structure(
            staging.render(staging.TEMPLATE_FILE), allow_placeholders=True
        )

    def test_caller_environment_cannot_override_reviewed_files(self) -> None:
        hostile = {
            "STAGING_APP_URL": "https://staging.example.com",
            "LOCAL_STAGING_HTTPS_PORT": "3000",
            "COMPOSE_PROFILES": "staging-cloudflare",
            "COMPOSE_FILE": str(staging.COMPOSE_FILE),
            "COMPOSE_PROJECT_NAME": "smokemap",
        }
        with mock.patch.dict(os.environ, hostile):
            config = local.render(local.SETTINGS_TEMPLATE, local.RELEASE_TEMPLATE)
        local.validate_structure(config, PORT, allow_placeholders=True)
        self.assertEqual(
            config["services"]["frontend"]["environment"]["NEXT_PUBLIC_BASE_URL"],
            local.app_origin(PORT),
        )


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = local.read_env_file(local.SETTINGS_TEMPLATE)

    def assert_settings_rejected(self, message: str, **changes: str) -> None:
        settings = {**self.settings, **changes}
        with self.assertRaisesRegex(local.ValidationError, message):
            local.validate_settings(settings)

    def test_template_settings_are_valid(self) -> None:
        self.assertEqual(local.validate_settings(self.settings), PORT)

    def test_public_or_mismatched_origins_are_rejected(self) -> None:
        self.assert_settings_rejected("STAGING_APP_URL", STAGING_APP_URL="https://staging.example.com")
        self.assert_settings_rejected("STAGING_APP_URL", LOCAL_STAGING_HTTPS_PORT="9443")
        self.assert_settings_rejected(
            "STAGING_MEDIA_URL", STAGING_MEDIA_URL=local.app_origin(PORT)
        )

    def test_unreviewed_variables_and_identity_changes_are_rejected(self) -> None:
        self.assert_settings_rejected("reviewed variable set", COMPOSE_FILE="/tmp/other.yaml")
        self.assert_settings_rejected("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME="smokemap")
        self.assert_settings_rejected(
            "inert local placeholder", CLOUDFLARED_IMAGE="cloudflare/cloudflared@sha256:" + "1" * 64
        )
        self.assert_settings_rejected("PostgreSQL identifier", POSTGRES_DB='db"; drop')

    def test_external_staging_environment_is_rejected(self) -> None:
        with self.assertRaisesRegex(local.ValidationError, "reviewed variable set"):
            local.validate_settings(local.read_env_file(staging.TEMPLATE_FILE))

    def test_env_file_syntax_is_strict(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            path = Path(directory) / "settings.env"
            for text, message in (
                ("A=1\nA=2\n", "more than once"),
                ("A='quoted'\n", "unquoted value"),
                ("A=${HOME}\n", "without interpolation"),
                ("export A=1\n", "plain KEY=VALUE"),
            ):
                with self.subTest(text=text):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(local.ValidationError, message):
                        local.read_env_file(path)

    def test_release_selection_requires_recorded_local_images(self) -> None:
        template = local.read_env_file(local.RELEASE_TEMPLATE)
        local.validate_release_selection(template, allow_placeholders=True)
        with self.assertRaisesRegex(local.ValidationError, "recorded local release identifier"):
            local.validate_release_selection(template, allow_placeholders=False)
        release = {"RELEASE_ID": FAKE_RELEASE_ID, "RELEASE_VERSION": FRONTEND_COMMIT, **FAKE_IMAGES}
        local.validate_release_selection(release, allow_placeholders=False)
        for key, value, message in (
            ("BACKEND_IMAGE", "smokemap-backend:latest", "content-addressed local image ID"),
            ("RELEASE_VERSION", "v1.0.0", "40-hex"),
            ("CLOUDFLARED_IMAGE", "x", "reviewed variable set"),
        ):
            with self.subTest(key=key):
                with self.assertRaisesRegex(local.ValidationError, message):
                    local.validate_release_selection({**release, key: value}, allow_placeholders=False)


class EdgeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = local.EDGE_CONFIG_FILE.read_text(encoding="utf-8")

    def assert_config_rejected(self, old: str, new: str, message: str) -> None:
        self.assertIn(old, self.text)
        with self.assertRaisesRegex(local.ValidationError, message):
            local.validate_edge_config(self.text.replace(old, new))

    def test_checked_in_edge_config_is_valid(self) -> None:
        local.validate_edge_config(self.text)

    def test_query_strings_and_credentials_are_never_logged(self) -> None:
        for replacement in ("$request", "$request_uri", "$uri?$args", "$http_authorization"):
            with self.subTest(replacement=replacement):
                self.assert_config_rejected('"$request_method $uri"', f'"{replacement}"', "omit query strings")

    def test_error_log_never_records_upstream_failures(self) -> None:
        # Upstream failures are logged at "error" with the full request line.
        directive = "error_log /dev/stderr crit;"
        message = "explicit crit, alert or emerg level"
        for replacement in (
            "error_log /dev/stderr warn;",
            "error_log /dev/stderr error;",
            "error_log /dev/stderr notice;",
            "error_log /dev/stderr info;",
            "error_log /dev/stderr debug;",
            "error_log /dev/stderr;",
            "",
        ):
            with self.subTest(replacement=replacement):
                self.assert_config_rejected(directive, replacement, message)
        for level in ("alert", "emerg"):
            with self.subTest(level=level):
                local.validate_edge_config(self.text.replace(directive, f"error_log /dev/stderr {level};"))
        for nested in ("server_tokens off;", "client_max_body_size 6m;", "return 404;"):
            with self.subTest(nested=nested):
                self.assert_config_rejected(nested, f"{nested} error_log /dev/stderr error;", message)

    def test_backend_or_console_upstream_is_rejected(self) -> None:
        for upstream in ("http://api.smokemap-staging.internal:8000", "http://storage:9001", "http://db:5432"):
            with self.subTest(upstream=upstream):
                self.assert_config_rejected("http://storage:9000", upstream, "only to the frontend and MinIO")
        self.assert_config_rejected(
            "proxy_pass $storage_upstream;", "proxy_pass http://backend:8000;", "only to the frontend and MinIO"
        )

    def test_host_and_forwarding_headers_are_preserved_and_replaced(self) -> None:
        self.assert_config_rejected(
            "proxy_set_header Host $http_host;", "proxy_set_header Host storage;", "Host \\$http_host"
        )
        self.assert_config_rejected(
            "proxy_set_header X-Forwarded-For $remote_addr;",
            "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            "replace, never append",
        )

    def test_listeners_and_names_are_pinned(self) -> None:
        self.assert_config_rejected("listen 127.0.0.1:8081;", "listen 8081;", "listen only for TLS")
        self.assert_config_rejected("ssl_reject_handshake on;", "", "reject TLS names")
        self.assert_config_rejected(
            "server_name media.local-staging.smokemap.internal;",
            "server_name media.local-staging.smokemap.internal uploads.example.com;",
            "exactly the application and media hostnames",
        )


class InitAndReleaseInputTests(unittest.TestCase):
    def test_generated_home_passes_release_input_preflight(self) -> None:
        release_file = HOME.release_file(FAKE_RELEASE_ID)
        config = local.render(HOME.settings, release_file)
        local.validate_structure(config, PORT, allow_placeholders=False)
        local.validate_release_inputs(config, HOME.settings, release_file, HOME.edge_ca)

    def test_init_never_prints_secret_values(self) -> None:
        for path in HOME.secrets.iterdir():
            value = path.read_text(encoding="utf-8").strip()
            with self.subTest(secret=path.name):
                for line in value.splitlines():
                    if "-----" not in line:
                        self.assertNotIn(line, INIT_OUTPUT)

    def test_generated_secrets_meet_application_rules(self) -> None:
        self.assertGreaterEqual(len((HOME.secrets / "django_secret_key").read_text().strip()), 50)
        self.assertGreaterEqual(len((HOME.secrets / "nextauth_secret").read_text().strip()), 32)
        values = [path.read_text() for path in HOME.secrets.iterdir()]
        self.assertEqual(len(values), len(set(values)))
        for path in HOME.authority.iterdir():
            with self.subTest(path=path.name):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_init_refuses_to_overwrite_a_home(self) -> None:
        before = (HOME.secrets / "django_secret_key").read_text()
        with self.assertRaisesRegex(local.ValidationError, "non-empty home"):
            local_staging.command_init(HOME, PORT, None)
        self.assertEqual((HOME.secrets / "django_secret_key").read_text(), before)

    def test_home_inside_a_repository_is_rejected(self) -> None:
        for path in (ROOT / "local-home", ROOT / "smokemap-webapp" / "home"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(local.ValidationError, "outside the repository|Git working tree"):
                    local_staging.resolve_home(str(path))
        with self.assertRaisesRegex(local.ValidationError, "absolute path"):
            local_staging.resolve_home("relative/home")

    def test_edge_certificate_from_another_authority_is_rejected(self) -> None:
        config = local.render(HOME.settings, HOME.release_file(FAKE_RELEASE_ID))
        with self.assertRaisesRegex(local.ValidationError, "chain to the local edge authority"):
            local.validate_edge_certificate(config["secrets"], HOME.secrets / "postgres_tls_ca")

    def test_permissive_settings_file_is_rejected(self) -> None:
        release_file = HOME.release_file(FAKE_RELEASE_ID)
        config = local.render(HOME.settings, release_file)
        HOME.settings.chmod(0o644)
        try:
            with self.assertRaisesRegex(local.ValidationError, "mode 0600, found 0644"):
                local.validate_release_inputs(config, HOME.settings, release_file, HOME.edge_ca)
        finally:
            HOME.settings.chmod(0o600)

    def test_local_images_must_match_recorded_ids_labels_and_users(self) -> None:
        release = local.read_env_file(HOME.release_file(FAKE_RELEASE_ID))
        local.validate_local_images(release, EXPECTED_REVISIONS, inspect=fake_inspect())

        def relabel(metadata):
            metadata["Config"]["Labels"]["org.opencontainers.image.revision"] = "d" * 40
            return metadata

        def root_user(metadata):
            metadata["Config"]["User"] = "root"
            return metadata

        for overrides, message in (
            ({"BACKEND_IMAGE": None}, "not present locally"),
            ({"FRONTEND_IMAGE": relabel}, "revision label differs"),
            ({"MINIO_IMAGE": relabel}, "revision label differs"),
            ({"EDGE_PROXY_IMAGE": root_user}, "non-root user"),
        ):
            with self.subTest(overrides=list(overrides)):
                with self.assertRaisesRegex(local.ValidationError, message):
                    local.validate_local_images(release, EXPECTED_REVISIONS, inspect=fake_inspect(overrides))
        with self.assertRaisesRegex(local.ValidationError, "RELEASE_VERSION must equal"):
            local.validate_local_images(
                {**release, "RELEASE_VERSION": "e" * 40}, EXPECTED_REVISIONS, inspect=fake_inspect()
            )


class Recorder:
    """Stand-in for subprocess execution that records every command."""

    def __init__(self, outputs: dict[str, str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.outputs = outputs or {}

    def __call__(self, arguments, **options):
        self.calls.append(list(arguments))
        stdout = next(
            (value for marker, value in self.outputs.items() if marker in " ".join(arguments)), ""
        )
        return subprocess.CompletedProcess(arguments, 0, stdout=stdout, stderr="")


class LifecycleGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        local_staging.select_release(HOME, HOME.release_file(FAKE_RELEASE_ID))
        self.state_before = HOME.state.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        HOME.release.unlink(missing_ok=True)
        local_staging.write_private(HOME.state, self.state_before)

    def fake_preflight(self, release_overrides: dict | None = None):
        config = local.render(HOME.settings, HOME.release_file(FAKE_RELEASE_ID))
        release = {**local.read_env_file(HOME.release), **(release_overrides or {})}
        return mock.patch.object(
            local_staging, "preflight",
            return_value=(local.read_env_file(HOME.settings), release, {}, config),
        )

    def test_down_and_stop_never_remove_volumes(self) -> None:
        recorder = Recorder()
        with mock.patch.object(local_staging, "run", recorder):
            local_staging.command_down(HOME)
            local_staging.command_stop(HOME)
        self.assertEqual(recorder.calls[0][-2:], ["down", "--remove-orphans"])
        self.assertEqual(recorder.calls[1][-1], "stop")
        for call in recorder.calls:
            self.assertEqual(call[:2], ["docker", "compose"])
            self.assertIn(local.PROJECT_NAME, call)
            self.assertFalse({"--volumes", "-v", "--rmi"} & set(call))

    def test_lifecycle_source_never_deletes_volumes_or_prunes(self) -> None:
        source = (ROOT / "scripts" / "local-staging.py").read_text(encoding="utf-8")
        for forbidden in ('"--volumes"', '"-v"', "volume\", \"rm", '"prune"', '"rmi"', "--force"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_start_requires_a_migration_record_for_the_selected_backend(self) -> None:
        recorder = Recorder()
        with self.fake_preflight(), mock.patch.object(local_staging, "run", recorder):
            with self.assertRaisesRegex(local.ValidationError, "no successful migration record"):
                local_staging.command_start(HOME)
            state = local_staging.load_state(HOME)
            state["migrations"][FAKE_RELEASE_ID] = {"backend_image": "sha256:" + "f" * 64}
            local_staging.save_state(HOME, state)
            with self.assertRaisesRegex(local.ValidationError, "no successful migration record"):
                local_staging.command_start(HOME)
        self.assertEqual(recorder.calls, [])

    def test_rollback_selects_only_previously_migrated_releases(self) -> None:
        recorder = Recorder()
        with self.fake_preflight(), mock.patch.object(local_staging, "run", recorder):
            with self.assertRaisesRegex(local.ValidationError, "previously migrated"):
                local_staging.command_rollback(HOME, FAKE_RELEASE_ID)
            with self.assertRaisesRegex(local.ValidationError, "release identifier"):
                local_staging.command_rollback(HOME, "../../etc")
        self.assertEqual(recorder.calls, [])

    def test_restore_requires_exact_confirmation_before_any_action(self) -> None:
        recorder = Recorder()
        with mock.patch.object(local_staging, "run", recorder):
            for confirm in ("", "yes", "smokemap", "smokemap-staging"):
                with self.subTest(confirm=confirm):
                    with self.assertRaisesRegex(local.ValidationError, "--confirm smokemap-local-staging"):
                        local_staging.command_restore(HOME, "20261025T120000Z", confirm, True)
        self.assertEqual(recorder.calls, [])

    def write_backup(self, backup_id: str, *, backend_image: str, tamper: bool = False) -> None:
        directory = HOME.backups / backup_id
        directory.mkdir(mode=0o700, exist_ok=True)
        files = {}
        for name in ("database.dump", "media.tar"):
            local_staging.write_private(directory / name, f"test-only {name}\n")
            files[name] = {"sha256": local_staging.sha256_file(directory / name), "bytes": 1}
        if tamper:
            local_staging.write_private(directory / "media.tar", "changed\n")
        metadata = {"schema": 1, "project": local.PROJECT_NAME, "release_id": FAKE_RELEASE_ID,
                    "images": {"backend": backend_image}, "files": files}
        local_staging.write_private(directory / "backup.json", json.dumps(metadata))

    def test_restore_rejects_tampered_or_unpaired_backups(self) -> None:
        recorder = Recorder()
        self.write_backup("20261025T120001Z", backend_image=FAKE_IMAGES["BACKEND_IMAGE"], tamper=True)
        self.write_backup("20261025T120002Z", backend_image="sha256:" + "e" * 64)
        state = local_staging.load_state(HOME)
        state["migrations"][FAKE_RELEASE_ID] = {"backend_image": FAKE_IMAGES["BACKEND_IMAGE"]}
        local_staging.save_state(HOME, state)
        with self.fake_preflight(), mock.patch.object(local_staging, "run", recorder):
            with self.assertRaisesRegex(local.ValidationError, "recorded checksum"):
                local_staging.command_restore(HOME, "20261025T120001Z", local.PROJECT_NAME, True)
            with self.assertRaisesRegex(local.ValidationError, "roll back to it before restoring"):
                local_staging.command_restore(HOME, "20261025T120002Z", local.PROJECT_NAME, True)
            with self.assertRaisesRegex(local.ValidationError, "backup identifier"):
                local_staging.command_restore(HOME, "../releases", local.PROJECT_NAME, True)
        self.assertEqual(recorder.calls, [])

    def test_foreign_volumes_and_networks_are_never_adopted(self) -> None:
        config = local.render(HOME.settings, HOME.release_file(FAKE_RELEASE_ID))
        foreign = json.dumps([{"Labels": {"com.docker.compose.project": "smokemap"}}])
        with mock.patch.object(local_staging, "run", Recorder({"inspect": foreign})):
            with self.assertRaisesRegex(local.ValidationError, "does not belong to the smokemap-local-staging"):
                local_staging.validate_resource_ownership(config)
            with self.assertRaisesRegex(local.ValidationError, "does not belong to the smokemap-local-staging"):
                local_staging.project_volume(config, "minio-data")

    def test_backup_helpers_are_isolated_one_volume_containers(self) -> None:
        for writable in (False, True):
            with self.subTest(writable=writable):
                image, volume = "sha256:" + "1" * 64, "smokemap-local-staging_minio-data"
                command = local_staging.volume_helper(image, volume, writable=writable)
                text = " ".join(command)
                self.assertIn("--network none", text)
                self.assertIn("--read-only", text)
                self.assertIn("--cap-drop ALL", text)
                self.assertEqual(command.count("--volume"), 1)
                self.assertIn(f"{volume}:/data" if writable else f"{volume}:/data:ro", command)
                self.assertNotIn("--privileged", command)
                self.assertEqual(command[-4:], ["--entrypoint", "sh", image, "-ec"])


class ReproducibilityTests(unittest.TestCase):
    def test_minio_sources_match_the_development_build(self) -> None:
        compose = (ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
        for key, value in (
            ("SERVER_RELEASE", local_staging.MINIO_SERVER_RELEASE),
            ("SERVER_COMMIT", local_staging.MINIO_SERVER_COMMIT),
            ("CLIENT_RELEASE", local_staging.MINIO_CLIENT_RELEASE),
            ("CLIENT_COMMIT", local_staging.MINIO_CLIENT_COMMIT),
        ):
            with self.subTest(key=key):
                self.assertRegex(compose, rf"\n\s+{key}: {re.escape(value)}\n")

    def test_upstream_images_are_pinned_by_digest(self) -> None:
        for service, reference in local_staging.UPSTREAM_IMAGES.items():
            with self.subTest(service=service):
                self.assertRegex(reference, r"^[a-z0-9./-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")

    def test_sources_are_the_independently_deployed_repositories(self) -> None:
        for name, source in local_staging.SOURCES.items():
            with self.subTest(name=name):
                url = subprocess.run(
                    ["git", "config", "--file", ".gitmodules", f"submodule.{source['path']}.url"],
                    cwd=ROOT, check=True, capture_output=True, text=True,
                ).stdout.strip()
                self.assertEqual(url, source["url"])

    def test_runbook_and_make_targets_document_every_command(self) -> None:
        readme = local.README_FILE.read_text(encoding="utf-8")
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for command in ("init", "build", "releases", "preflight", "migrate", "start", "stop",
                        "down", "status", "smoke", "backup", "restore", "rollback"):
            with self.subTest(command=command):
                self.assertIn(f"local-staging-{command}", makefile)
                self.assertIn(f"make local-staging-{command}", readme)


if __name__ == "__main__":
    unittest.main()
