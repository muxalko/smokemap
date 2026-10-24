from __future__ import annotations

import copy
import importlib.util
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


class StagingReleaseInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="smokemap-staging-preflight-", dir="/tmp"
        )
        self.root = Path(self.temporary_directory.name)
        self.root.chmod(0o700)
        self.env_file = self.root / "staging.env"
        self.env_file.write_text(
            f"RELEASE_VERSION=test\nSTAGING_SECRETS_DIR={self.root / 'secrets'}\n",
            encoding="utf-8",
        )
        self.env_file.chmod(0o600)
        self.secrets_directory = self.root / "secrets"
        self.secrets_directory.mkdir(mode=0o700)
        self.config = {"secrets": {}}
        for name in validate_staging.EXPECTED_SECRETS:
            secret_file = self.secrets_directory / name
            secret_file.write_text("test-only-non-secret\n", encoding="utf-8")
            secret_file.chmod(0o600)
            self.config["secrets"][name] = {"file": str(secret_file)}

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_secure_external_inputs_are_accepted(self) -> None:
        validate_staging.validate_release_inputs(self.config, self.env_file)

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
            "django_secret_key secret must have mode 0600, found 0644",
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
