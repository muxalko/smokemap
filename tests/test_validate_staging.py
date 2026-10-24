from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "validate_staging", ROOT / "scripts" / "validate-staging.py"
)
assert SPEC is not None and SPEC.loader is not None
validate_staging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_staging)


class StagingStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = validate_staging.render(validate_staging.TEMPLATE_FILE)

    def test_checked_in_template_is_structurally_valid(self) -> None:
        validate_staging.validate_structure(self.config, allow_placeholders=True)

    def test_mutable_image_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["services"]["backend"]["image"] = "ghcr.io/muxalko/backend:latest"

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "backend image is not an immutable sha256 reference",
        ):
            validate_staging.validate_structure(config, allow_placeholders=False)

    def test_published_port_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["services"]["db"]["ports"] = [{"published": "5432", "target": 5432}]

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "db must not publish or expose a port",
        ):
            validate_staging.validate_structure(config, allow_placeholders=True)

    def test_environment_secret_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["services"]["backend"]["environment"]["DJANGO_SECRET_KEY"] = "unsafe"

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "backend places sensitive input DJANGO_SECRET_KEY in its environment",
        ):
            validate_staging.validate_structure(config, allow_placeholders=True)

    def test_render_rejects_env_file_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="smokemap-compose-render-", dir="/tmp"
        ) as directory:
            root = Path(directory)
            service_env = root / "service.env"
            service_env.write_text("SAFE_VALUE=test\n", encoding="utf-8")
            compose_file = root / "compose.yaml"
            compose_file.write_text(
                "services:\n"
                "  check:\n"
                "    image: example.invalid/check:latest\n"
                f"    env_file: {service_env}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                validate_staging.ValidationError,
                "check must not load an unreviewed environment file",
            ):
                validate_staging.render(
                    validate_staging.TEMPLATE_FILE, compose_file=compose_file
                )

    def test_frontend_outbound_edge_network_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["services"]["frontend"]["networks"]["edge"] = None

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "frontend network reachability changed",
        ):
            validate_staging.validate_structure(config, allow_placeholders=True)

    def test_tunnel_backend_media_network_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        networks = config["services"]["cloudflared"]["networks"]
        networks.pop("media-ingress")
        networks["media"] = None

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "cloudflared network reachability changed",
        ):
            validate_staging.validate_structure(config, allow_placeholders=True)

    def test_privilege_and_namespace_drift_is_rejected(self) -> None:
        unsafe_values = {
            "privileged": True,
            "cap_add": ["SYS_ADMIN"],
            "pid": "host",
            "env_file": ["/tmp/unreviewed.env"],
        }
        messages = {
            "privileged": "backend must not run privileged",
            "cap_add": "backend must not add Linux capabilities",
            "pid": "backend must not join another PID namespace",
            "env_file": "backend must not load an unreviewed environment file",
        }
        for key, value in unsafe_values.items():
            with self.subTest(key=key):
                config = copy.deepcopy(self.config)
                config["services"]["backend"][key] = value
                with self.assertRaisesRegex(
                    validate_staging.ValidationError, messages[key]
                ):
                    validate_staging.validate_structure(
                        config, allow_placeholders=True
                    )

    def test_bind_volume_driver_options_are_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["volumes"]["postgres-data"]["driver_opts"] = {
            "type": "none",
            "o": "bind",
            "device": "/srv/staging/postgres",
        }

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "postgres-data must not use driver options",
        ):
            validate_staging.validate_structure(config, allow_placeholders=True)

    def test_minio_cors_console_and_backend_health_are_pinned(self) -> None:
        services = self.config["services"]
        storage_environment = services["storage"]["environment"]

        self.assertEqual(
            storage_environment["MINIO_API_CORS_ALLOW_ORIGIN"],
            services["backend"]["environment"]["CORS_ALLOWED_ORIGINS"],
        )
        self.assertEqual(storage_environment["MINIO_BROWSER"], "off")
        self.assertNotIn(
            "mc cors", validate_staging.command_text(services["storage-init"]).lower()
        )
        self.assertIn(
            "http://backend:8000/health/ready/",
            " ".join(services["backend"]["healthcheck"]["test"]),
        )

    def test_secret_consumers_share_nonroot_read_group(self) -> None:
        services = self.config["services"]
        expected_group = services["backend"]["group_add"]

        self.assertEqual(len(expected_group), 1)
        self.assertNotEqual(expected_group, ["0"])
        for name, service in services.items():
            if service.get("secrets"):
                with self.subTest(service=name):
                    self.assertEqual(service["group_add"], expected_group)


class StagingReleaseInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="smokemap-staging-preflight-", dir="/tmp"
        )
        self.root = Path(self.temporary_directory.name)
        self.root.chmod(0o750)
        self.env_file = self.root / "staging.env"
        self.env_file.write_text(
            f"RELEASE_VERSION=test\nSTAGING_SECRETS_DIR={self.root / 'secrets'}\n",
            encoding="utf-8",
        )
        self.env_file.chmod(0o600)
        self.secrets_directory = self.root / "secrets"
        self.secrets_directory.mkdir(mode=0o750)
        self.config = {
            "services": {
                "test-service": {
                    "group_add": [str(os.getegid())],
                    "secrets": ["test-secret"],
                }
            },
            "secrets": {},
        }
        for name in validate_staging.EXPECTED_SECRETS:
            secret_file = self.secrets_directory / name
            secret_file.write_text("test-only-non-secret\n", encoding="utf-8")
            secret_file.chmod(0o640)
            self.config["secrets"][name] = {"file": str(secret_file)}

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_secure_external_inputs_are_accepted(self) -> None:
        validate_staging.validate_release_inputs(self.config, self.env_file)

    def test_external_release_preflight_is_accepted_end_to_end(self) -> None:
        release_environment = validate_staging.TEMPLATE_FILE.read_text(
            encoding="utf-8"
        )
        release_environment = release_environment.replace(
            "/opt/smokemap/staging/secrets", str(self.secrets_directory)
        )
        release_environment = release_environment.replace(
            "STAGING_SECRET_GID=1000", f"STAGING_SECRET_GID={os.getegid()}"
        )
        release_environment = release_environment.replace(
            "example.invalid/smokemap/", "registry.test/smokemap/"
        )
        release_environment = release_environment.replace("0" * 64, "1" * 64)
        self.env_file.write_text(release_environment, encoding="utf-8")

        config = validate_staging.render(self.env_file)
        validate_staging.validate_structure(config, allow_placeholders=False)
        validate_staging.validate_release_inputs(config, self.env_file)

    def test_relative_environment_file_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "STAGING_ENV_FILE must be an absolute path",
        ):
            validate_staging.resolve_release_env_file(Path("staging.env"))

    def test_permissive_secret_is_rejected(self) -> None:
        secret_file = Path(self.config["secrets"]["django_secret_key"]["file"])
        secret_file.chmod(0o644)

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "django_secret_key secret must have mode 0640, found 0644",
        ):
            validate_staging.validate_release_inputs(self.config, self.env_file)

    def test_secret_directory_is_rejected(self) -> None:
        secret_file = Path(self.config["secrets"]["django_secret_key"]["file"])
        secret_file.unlink()
        secret_file.mkdir(mode=0o600)

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "django_secret_key secret must be a regular file",
        ):
            validate_staging.validate_release_inputs(self.config, self.env_file)

    def test_secret_value_in_environment_file_is_rejected(self) -> None:
        self.env_file.write_text("NEXTAUTH_SECRET=unsafe\n", encoding="utf-8")

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "environment file must contain secret paths, never secret values",
        ):
            validate_staging.validate_release_inputs(self.config, self.env_file)


if __name__ == "__main__":
    unittest.main()
