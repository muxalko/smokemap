"""No Docker daemon, Quick Tunnel provisioning, public traffic, or credentials."""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("quick_operator", ROOT / "scripts/quick-staging.py")
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)
quick, api = operator.quick, operator.api
RELEASE = "20261025T120000Z-0123456789ab"
IMAGES = {key: "sha256:" + f"{i:x}" * 64 for i, key in enumerate(quick.IMAGE_VARIABLES, 1)}
ORIGINS = ["https://example-app.trycloudflare.com", "https://example-media.trycloudflare.com"]
SNAPSHOT = {name: {"id": f"container-{i}", "pid": i + 100, "started_at": "2026-10-25T12:00:00Z",
                   "restart_count": 0, "origin": origin}
            for i, (name, origin) in enumerate(zip(quick.CONNECTORS, ORIGINS))}


def setUpModule():
    global TEMP, HOME, OUTPUT, CONFIG, SETTINGS, MANIFEST, RELEASE_ENV
    TEMP = tempfile.TemporaryDirectory(prefix="quick-unit-", dir="/tmp")
    HOME = api.Home(Path(TEMP.name) / "home")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        operator.command_init(HOME, None)
    OUTPUT = output.getvalue()
    SETTINGS = quick.read_env_file(HOME.settings)
    SETTINGS.update(zip(("STAGING_APP_URL", "STAGING_MEDIA_URL"), ORIGINS))
    operator.write_settings(HOME, SETTINGS)
    RELEASE_ENV = {"RELEASE_ID": RELEASE, "RELEASE_VERSION": quick.PINS["frontend"], **IMAGES}
    directory = HOME.releases / RELEASE
    directory.mkdir(mode=0o700)
    api.write_private(directory / "release.env", "".join(f"{k}={v}\n" for k, v in RELEASE_ENV.items()))
    api.select_release(HOME, directory / "release.env")
    public = operator.public_inputs(SETTINGS)
    MANIFEST = {"schema": 1, "mode": "quick-staging", "release_id": RELEASE, "registry": None,
                "root": {"commit": "c" * 40}, "sources": {k: {"commit": v} for k, v in quick.PINS.items()},
                "release_env": RELEASE_ENV, "frontend_public_build_inputs": public,
                "frontend_public_build_inputs_sha256": operator.hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest(),
                "connectors": SNAPSHOT, "connector_image": quick.CLOUDFLARED_IMAGE,
                "public_origins": {k: SETTINGS[k] for k in ("STAGING_APP_URL", "STAGING_MEDIA_URL")},
                "images": {service: {"id": IMAGES[key]} for key, service in quick.IMAGE_VARIABLES.items()}}
    api.write_private(directory / "manifest.json", json.dumps(MANIFEST))
    CONFIG = quick.render(HOME.settings, directory / "release.env")


def tearDownModule():
    TEMP.cleanup()


class OriginsAndIsolation(unittest.TestCase):
    def test_exact_single_label_https_origins_only(self):
        for origin in ORIGINS:
            quick.require_origin(origin)
        for value in ("http://foo.trycloudflare.com", "https://foo.trycloudflare.com/", "https://foo.trycloudflare.com:443",
                      "https://foo.trycloudflare.com:444", "https://a.b.trycloudflare.com", "https://trycloudflare.com",
                      "https://FOO.trycloudflare.com", "https://-a.trycloudflare.com", "https://a-.trycloudflare.com",
                      "https://a.trycloudflare.com.evil.test", "https://a.trycloudflare.com?token=x",
                      "https://user:password@a.trycloudflare.com", "https://a.trycloudflare.com#x",
                      "https://*.trycloudflare.com", "https://localhost", "https://a.local-staging.smokemap.internal"):
            with self.subTest(value=value), self.assertRaises(quick.ValidationError):
                quick.require_origin(value)
        with self.assertRaisesRegex(quick.ValidationError, "must differ"):
            quick.validate_settings({**SETTINGS, "STAGING_MEDIA_URL": ORIGINS[0]})

    def test_existing_contracts_keep_reserved_and_registry_rules(self):
        local = quick.local
        settings = local.read_env_file(local.SETTINGS_TEMPLATE)
        local.validate_settings(settings)
        with self.assertRaises(quick.ValidationError):
            local.validate_settings({**settings, "STAGING_APP_URL": ORIGINS[0]})
        external = quick.staging.render(quick.staging.TEMPLATE_FILE)
        external["services"]["backend"]["image"] = IMAGES["BACKEND_IMAGE"]
        with self.assertRaisesRegex(quick.ValidationError, "immutable"):
            quick.staging.validate_structure(external, allow_placeholders=True)
        self.assertEqual(api.MODE, "quick-staging")
        self.assertEqual(quick.local.PROJECT_NAME, "smokemap-local-staging")

    def test_reviewed_topology_and_origin_wiring(self):
        quick.validate_structure(CONFIG, allow_placeholders=False)
        frontend = CONFIG["services"]["frontend"]["environment"]
        backend = CONFIG["services"]["backend"]["environment"]
        self.assertEqual(frontend["NEXT_PUBLIC_BASE_URL"], ORIGINS[0])
        self.assertEqual(frontend["NEXTAUTH_URL"], ORIGINS[0])
        self.assertEqual(backend["CORS_ALLOWED_ORIGINS"], ORIGINS[0])
        self.assertEqual(backend["CSRF_TRUSTED_ORIGINS"], ORIGINS[0])
        self.assertEqual(backend["AWS_S3_ENDPOINT_URL"], ORIGINS[1])
        self.assertEqual(backend["MEDIA_UPLOAD_ENDPOINT_URL"], ORIGINS[1])
        self.assertEqual(backend["POSTGRES_SSLMODE"], "verify-full")
        self.assertEqual(backend["DJANGO_TRUST_X_FORWARDED_PROTO"], "true")
        self.assertNotIn("cloudflared_token", CONFIG["secrets"])

    def test_mutated_isolation_argv_logs_and_credentials_are_rejected(self):
        mutations = [
            lambda c: c["services"]["backend"].update(ports=[{"target": 8000, "published": "8000"}]),
            lambda c: c["services"]["quick-app"]["networks"].update(database={}),
            lambda c: c["services"]["quick-media"]["networks"].update(application={}),
            lambda c: c["services"]["frontend"]["networks"].update(edge={}),
            lambda c: c["networks"]["media"].update(internal=False),
            lambda c: c["volumes"]["minio-data"].update(name="smokemap-local-staging_minio-data"),
            lambda c: c["volumes"]["postgres-data"].update(external=True),
            lambda c: c["services"]["quick-app"].update(command=["tunnel", "--url", "http://backend:8000"]),
            lambda c: c["services"]["quick-media"].update(command=["tunnel", "--url", "http://storage:9001"]),
            lambda c: c["services"]["quick-app"].update(user="0:0"),
            lambda c: c["services"]["quick-app"].update(cap_add=["NET_ADMIN"]),
            lambda c: c["services"]["quick-app"].update(security_opt=[]),
            lambda c: c["services"]["quick-app"].update(restart="unless-stopped"),
            lambda c: c["services"]["quick-app"].update(logging={"driver": "json-file"}),
            lambda c: c["services"]["quick-app"].update(secrets=[{"source": "cloudflared_token"}]),
            lambda c: c["services"]["quick-app"].update(volumes=[{"type": "bind", "source": "/private", "target": "/token"}]),
            lambda c: c["services"]["quick-app"].update(depends_on={"frontend": {"condition": "service_healthy"}}),
            lambda c: c["services"]["quick-app"].update(image="cloudflare/cloudflared:latest"),
            lambda c: c["services"]["frontend"].update(image="example.test/frontend@sha256:" + "1" * 64),
            lambda c: c["services"]["frontend"].update(pull_policy="always"),
            lambda c: c["services"]["storage"]["environment"].update(MINIO_BROWSER="on"),
            lambda c: c["services"]["backend"]["environment"].update(CSRF_TRUSTED_ORIGINS="https://*.trycloudflare.com"),
        ]
        for i, mutation in enumerate(mutations):
            with self.subTest(mutation=i):
                config = copy.deepcopy(CONFIG)
                mutation(config)
                with self.assertRaises(quick.ValidationError):
                    quick.validate_structure(config, allow_placeholders=False)

    def test_init_independent_private_files_and_no_token_or_secret_output(self):
        operator.validate_home(HOME)
        quick.staging.validate_secret_files(CONFIG)
        self.assertEqual({p.name for p in HOME.secrets.iterdir()}, quick.EXPECTED_SECRETS)
        for path in HOME.secrets.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertNotIn(path.read_text().strip(), OUTPUT)
        self.assertEqual(HOME.path.stat().st_mode & 0o777, 0o700)
        self.assertEqual(HOME.settings.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(quick.ValidationError, "non-empty"):
            operator.command_init(HOME, None)
        with self.assertRaises(quick.ValidationError):
            api.resolve_home(str(ROOT / "quick-home"))


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.before = HOME.state.read_text()
        state = api.load_state(HOME)
        state.update(connectors=copy.deepcopy(SNAPSHOT), reader_image=IMAGES["POSTGIS_IMAGE"])
        api.save_state(HOME, state)

    def tearDown(self):
        api.write_private(HOME.state, self.before)
        operator.write_settings(HOME, SETTINGS)
        api.select_release(HOME, HOME.release_file(RELEASE))
        api.write_private(HOME.release_file(RELEASE).with_name("manifest.json"), json.dumps(MANIFEST))

    def test_url_process_restart_or_start_time_change_closes_ingress(self):
        for field, value in (("origin", "https://new-app.trycloudflare.com"), ("id", "replacement"),
                             ("restart_count", 1), ("pid", 9999), ("started_at", "later")):
            with self.subTest(field=field):
                actual = copy.deepcopy(SNAPSHOT)
                actual["quick-app"][field] = value
                state = api.load_state(HOME)
                state.pop("invalidated", None)
                api.save_state(HOME, state)
                with mock.patch.object(operator, "connector_snapshot", return_value=actual), mock.patch.object(operator, "close_ingress") as close:
                    with self.assertRaisesRegex(quick.ValidationError, "rebuild frontend"):
                        operator.check_connectors(HOME)
                    close.assert_called_once_with(HOME)
                self.assertTrue(api.load_state(HOME)["invalidated"])

    def test_missing_metrics_fails_closed_without_logs(self):
        with mock.patch.object(operator, "connector_snapshot", side_effect=quick.ValidationError("probe failed")), mock.patch.object(operator, "close_ingress") as close:
            with self.assertRaisesRegex(quick.ValidationError, "rebuild frontend"):
                operator.check_connectors(HOME)
            close.assert_called_once()

    def test_manifest_rejects_source_public_inputs_origins_ids_and_generation_drift(self):
        mutations = [lambda m: m.update(mode="local-staging"),
                     lambda m: m["sources"]["backend"].update(commit="d" * 40),
                     lambda m: m["frontend_public_build_inputs"].update(NEXT_PUBLIC_BASE_URL="https://old.trycloudflare.com"),
                     lambda m: m["public_origins"].update(STAGING_MEDIA_URL="https://old.trycloudflare.com"),
                     lambda m: m["images"]["frontend"].update(id="sha256:" + "e" * 64),
                     lambda m: m["connectors"]["quick-media"].update(pid=9999),
                     lambda m: m.update(connector_image="cloudflare/cloudflared:latest")]
        for i, mutate in enumerate(mutations):
            with self.subTest(mutation=i):
                manifest = copy.deepcopy(MANIFEST)
                mutate(manifest)
                api.write_private(HOME.release_file(RELEASE).with_name("manifest.json"), json.dumps(manifest))
                with mock.patch.object(operator, "check_connectors", return_value=SNAPSHOT), mock.patch.object(quick, "validate_local_images"), mock.patch.object(api, "validate_resource_ownership"), mock.patch.object(operator, "runtime_inventory", return_value={}):
                    with self.assertRaises(quick.ValidationError):
                        operator.preflight(HOME, HOME.release_file(RELEASE))

    def test_preflight_accepts_fully_recorded_release_without_starting(self):
        with mock.patch.object(operator, "check_connectors", return_value=SNAPSHOT), mock.patch.object(quick, "validate_local_images"), mock.patch.object(api, "validate_resource_ownership"), mock.patch.object(operator, "runtime_inventory", return_value={}), mock.patch.object(operator, "compose") as compose:
            operator.preflight(HOME, HOME.release_file(RELEASE))
            compose.assert_not_called()

    def test_start_requires_migration_before_any_runtime_mutation(self):
        with mock.patch.object(operator, "preflight"), mock.patch.object(operator, "compose") as compose:
            with self.assertRaisesRegex(quick.ValidationError, "no successful migration"):
                operator.command_start(HOME)
            compose.assert_not_called()

    def test_recovery_cannot_resume_unsupervised_apps(self):
        for command in ("backup", "restore", "rollback"):
            argv = ["--home", str(HOME.path), command]
            if command == "restore":
                argv += ["--backup", "20261025T120000Z", "--confirm", quick.PROJECT_NAME]
            elif command == "rollback":
                argv += ["--release", RELEASE]
            with self.subTest(command=command), mock.patch.object(operator, "close_ingress") as close, mock.patch.object(api, f"command_{command}") as recovery, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(operator.main(argv), 1)
                close.assert_called_once_with(mock.ANY)
                recovery.assert_not_called()

    def test_migration_rejects_running_writers(self):
        with mock.patch.object(operator, "runtime_inventory", return_value={"frontend": {"State": {"Running": True}}}), mock.patch.object(api, "command_migrate") as migrate:
            with self.assertRaisesRegex(quick.ValidationError, "writers must be stopped"):
                operator.command_migrate(HOME, RELEASE)
            migrate.assert_not_called()

    def test_migration_uses_only_one_shot_job_then_checks_generation(self):
        calls = []
        with mock.patch.object(api, "preflight", return_value=(SETTINGS, RELEASE_ENV, MANIFEST, CONFIG)), mock.patch.object(api, "require_root_merged"), mock.patch.object(operator, "runtime_inventory", return_value={}), mock.patch.object(api, "compose", side_effect=lambda h, *args, **kw: calls.append((args, kw))), mock.patch.object(operator, "check_connectors", return_value=SNAPSHOT):
            operator.command_migrate(HOME, RELEASE)
        self.assertEqual(calls[0][0], ("run", "--rm", "migrate"))
        self.assertEqual(calls[0][1]["profiles"], quick.PROFILES)
        self.assertEqual(api.load_state(HOME)["migrations"][RELEASE]["backend_image"], IMAGES["BACKEND_IMAGE"])

    def test_connector_allocation_never_starts_apps_and_records_urls_ownership(self):
        calls = []
        with mock.patch.object(operator, "runtime_inventory", return_value={}), mock.patch.object(api, "validate_resource_ownership"), mock.patch.object(api, "ensure_upstream", return_value=(IMAGES["POSTGIS_IMAGE"], "tag")), mock.patch.object(quick, "inspect_image", return_value={"Id": "cloudflared"}), mock.patch.object(operator, "compose", side_effect=lambda h, *args, **kw: calls.append((args, kw))), mock.patch.object(operator, "connector_snapshot", return_value=SNAPSHOT), contextlib.redirect_stdout(io.StringIO()):
            operator.command_connectors(HOME)
        self.assertEqual(calls[0][0], ("up", "--detach", "--no-deps", "--force-recreate", *quick.CONNECTORS))
        self.assertEqual(api.load_state(HOME)["connectors"], SNAPSHOT)
        self.assertFalse(HOME.release.exists())
        self.assertIsNone(api.load_state(HOME)["current_release"])

    def test_existing_runtime_prevents_reallocation(self):
        with mock.patch.object(api, "validate_resource_ownership"), mock.patch.object(operator, "runtime_inventory", return_value={"db": {"State": {"Running": True}}}), mock.patch.object(operator, "compose") as compose:
            with self.assertRaisesRegex(quick.ValidationError, "stop the quick project"):
                operator.command_connectors(HOME)
            compose.assert_not_called()

    def test_build_records_exact_public_inputs_sources_local_ids_and_connector_generation(self):
        root = {"commit": "c" * 40, "on_remote_development": True}
        sources = {name: {"commit": pin} for name, pin in quick.PINS.items()}
        image_ids = {service: IMAGES[key] for key, service in quick.IMAGE_VARIABLES.items()}
        def build(archive, tag, target, arguments, work):
            service = "frontend" if "/frontend:" in tag else "backend" if "/backend:" in tag else "storage-init" if "/mc:" in tag else "storage"
            return image_ids[service], {}
        def run(argv, **options):
            output = json.dumps({"Client": {"Version": "mock"}, "Server": {"Version": "mock"}}) if "version" in argv and "buildx" not in argv else "mock"
            return subprocess.CompletedProcess(argv, 0, output)
        with mock.patch.object(operator, "check_connectors", return_value=SNAPSHOT), mock.patch.object(api, "require_clean_root"), mock.patch.object(api, "gitlink", side_effect=lambda path: quick.PINS["backend" if "backend" in path else "frontend"]), mock.patch.object(api, "verify_sources", return_value=(root, sources)), mock.patch.object(api, "archive_tree", return_value="f" * 64), mock.patch.object(api, "git", return_value="e" * 40), mock.patch.object(api, "build_image", side_effect=build), mock.patch.object(api, "ensure_upstream", return_value=(image_ids["db"], "db-tag")), mock.patch.object(api, "describe_image", side_effect=lambda image, tag, **details: {"id": image, "tag": tag, **details}), mock.patch.object(quick, "validate_local_images"), mock.patch.object(api, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            operator.command_build(HOME)
        release_id = api.load_state(HOME)["history"][-1]["release"]
        manifest = operator.load_manifest(HOME, release_id)
        self.assertEqual(manifest["frontend_public_build_inputs"], operator.public_inputs(SETTINGS))
        self.assertEqual(manifest["connectors"], SNAPSHOT)
        self.assertEqual(manifest["connector_image"], quick.CLOUDFLARED_IMAGE)
        self.assertEqual(manifest["root"], root)
        self.assertIsNone(manifest["registry"])
        self.assertEqual(manifest["release_env"]["BACKEND_IMAGE"], image_ids["backend"])
        self.assertEqual(manifest["release_env"]["FRONTEND_IMAGE"], image_ids["frontend"])
        self.assertEqual({name: manifest["sources"][name]["commit"] for name in quick.PINS}, quick.PINS)

    def test_supervisor_closes_ingress_before_stopping_apps_on_change(self):
        state = api.load_state(HOME)
        state["migrations"][RELEASE] = {"backend_image": IMAGES["BACKEND_IMAGE"]}
        api.save_state(HOME, state)
        calls = []
        with mock.patch.object(operator, "preflight"), mock.patch.object(operator, "compose", side_effect=lambda h, *a, **kw: calls.append(a)), mock.patch.object(operator, "check_connectors", side_effect=quick.ValidationError("changed")), mock.patch.object(operator, "close_ingress", side_effect=lambda h: calls.append(("close-ingress",))), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(quick.ValidationError, "changed"):
                operator.command_start(HOME)
        self.assertEqual(calls[0][:3], ("up", "--detach", "--wait"))
        self.assertEqual(calls[1], ("close-ingress",))
        self.assertEqual(calls[2], ("stop", *operator.APP_SERVICES))
        self.assertNotIn("supervisor", api.load_state(HOME))

    def test_stop_without_release_keeps_all_volumes_and_other_projects(self):
        HOME.release.unlink()
        calls = []
        with mock.patch.object(api, "run", side_effect=lambda argv, **kw: calls.append(argv)):
            operator.command_stop(HOME)
        self.assertEqual(calls[0][-3:], ["stop", *quick.CONNECTORS])
        for call in calls:
            self.assertIn(quick.PROJECT_NAME, call)
            self.assertNotIn("--volumes", call)
            self.assertNotIn("kill", call)
            self.assertNotIn("down", call)

    def test_metrics_probe_has_only_one_internal_network_no_secrets_logs_or_token(self):
        inventory = {name: {"Id": SNAPSHOT[name]["id"], "State": {"Pid": SNAPSHOT[name]["pid"], "Running": True,
                      "StartedAt": SNAPSHOT[name]["started_at"]}, "RestartCount": 0} for name in quick.CONNECTORS}
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            origin = ORIGINS[len(calls)-1]
            body = json.dumps({"hostname": origin.removeprefix("https://")})
            return subprocess.CompletedProcess(argv, 0, "HTTP/1.0 200 OK\n\n" + body)
        with mock.patch.object(operator, "runtime_inventory", return_value=inventory), mock.patch.object(api, "run", side_effect=run):
            self.assertEqual(operator.connector_snapshot(HOME, IMAGES["POSTGIS_IMAGE"]), SNAPSHOT)
        for call in calls:
            self.assertEqual(call.count("--network"), 1)
            self.assertNotIn("--volume", call)
            self.assertIn("GET /quicktunnel", call[-1])
            self.assertNotIn("logs", call)
            self.assertNotIn("token", " ".join(call))
            self.assertNotIn(f"{quick.PROJECT_NAME}_edge", call)

    def test_foreign_resources_are_not_adopted(self):
        foreign = json.dumps([{"Labels": {"com.docker.compose.project": "smokemap-local-staging"}}])
        with mock.patch.object(api, "run", return_value=subprocess.CompletedProcess([], 0, foreign)):
            with self.assertRaisesRegex(quick.ValidationError, "does not belong"):
                api.validate_resource_ownership(CONFIG)

    def test_restore_confirmation_is_dedicated_to_quick_project(self):
        with mock.patch.object(api, "run") as run:
            for project in ("smokemap", "smokemap-local-staging", "smokemap-staging"):
                with self.assertRaisesRegex(quick.ValidationError, "confirm smokemap-quick-staging"):
                    api.command_restore(HOME, "20261025T120000Z", project, True)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
