from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit


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
        healthcheck = " ".join(services["backend"]["healthcheck"]["test"])
        for marker in validate_staging.BACKEND_READINESS_PROBE:
            with self.subTest(marker=marker):
                self.assertIn(marker, healthcheck)
        self.assertNotIn("backend:8000", healthcheck)

    def test_readiness_without_trusted_proxy_header_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        healthcheck = config["services"]["backend"]["healthcheck"]
        healthcheck["test"] = [
            part.replace(", 'X-Forwarded-Proto': 'https'", "")
            for part in healthcheck["test"]
        ]

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "backend readiness must send the allowed Host and trusted",
        ):
            validate_staging.validate_structure(config, allow_placeholders=True)

    def test_cleanup_requires_the_exact_pid_one_process_probe(self) -> None:
        expected = {
            "test": ["CMD", "python", "-c", "import os; os.kill(1, 0)"],
            "interval": "10s", "timeout": "5s", "retries": 3, "start_period": "5s",
        }
        self.assertEqual(self.config["services"]["media-cleanup"]["healthcheck"], expected)
        invalid = [None, {}, {"disable": True}, {"disable": False},
                   self.config["services"]["backend"]["healthcheck"]]
        for key, value in (
            ("test", ["NONE"]),
            ("test", ["CMD", "python", "-c", "import os; os.kill(os.getpid(), 0)"]),
            ("disable", True), ("interval", "1h"), ("timeout", "1m"),
            ("retries", 0), ("start_period", "1h"),
        ):
            invalid.append({**expected, key: value})
        for healthcheck in invalid:
            with self.subTest(healthcheck=healthcheck):
                config = copy.deepcopy(self.config)
                config["services"]["media-cleanup"]["healthcheck"] = healthcheck
                with self.assertRaisesRegex(
                    validate_staging.ValidationError,
                    "media-cleanup must use the exact PID 1 process-only healthcheck",
                ):
                    validate_staging.validate_structure(config, allow_placeholders=True)

    def test_anonymous_policy_drift_is_rejected(self) -> None:
        for old, new in (
            ('"s3:GetObject"', '"s3:GetObject","s3:ListBucket"'),
            ('"s3:GetObject"', '"s3:PutObject"'),
            ('"s3:GetObject"', '"s3:DeleteObject"'),
            ('"s3:GetObject"', '"s3:*"'),
            ('"Version":"2012-10-17"', '"Version":invalid'),
            ('cat >"$${policy_file}" <<PUBLIC_READ_POLICY',
             'cat >"$${unused_policy}" <<PUBLIC_READ_POLICY'),
            ('<<PUBLIC_READ_POLICY', '<<UNREVIEWED_POLICY'),
            ('arn:aws:s3:::$${MINIO_BUCKET}/*', 'arn:aws:s3:::$${MINIO_PRIVATE_MEDIA_BUCKET}/*'),
            ('arn:aws:s3:::$${MINIO_BUCKET}/*', 'arn:aws:s3:::*/*'),
            ('mc anonymous set-json "$${policy_file}"', 'mc anonymous set download'),
            ('mc anonymous set private', 'mc anonymous set download'),
        ):
            with self.subTest(replacement=new):
                config = copy.deepcopy(self.config)
                command = config["services"]["storage-init"]["command"]
                command[0] = command[0].replace(old, new, 1)
                with self.assertRaisesRegex(validate_staging.ValidationError,
                                            "storage-init must install only anonymous GetObject"):
                    validate_staging.validate_structure(config, allow_placeholders=True)

    def test_storage_init_installs_only_public_object_reads_with_bucket_overrides(self) -> None:
        # Execute the rendered init shell with an mc recorder and synthetic
        # secrets. No Docker, object store, or external credentials are used.
        recorder = r'''
cat() {
    case "${1:-}" in
        /run/secrets/*) printf 'test-only-value' ;;
        *) command cat "$@" ;;
    esac
}
mc() {
    if [ "$1" = anonymous ]; then
        case "$2" in
            set-json) printf '%s\n' "$4"; command cat "$3" ;;
            set) printf '%s:%s\n' "$3" "$4" ;;
            *) exit 90 ;;
        esac
    fi
}
'''
        command = self.config["services"]["storage-init"]["command"][0].replace("$$", "$")
        for public, private in (("legacy-fixture", "private-fixture"),
                                ("other-public", "other-private")):
            with self.subTest(public=public):
                result = subprocess.run(
                    ["/bin/sh", "-ec", recorder + command],
                    env={"PATH": os.environ["PATH"], "MINIO_BUCKET": public,
                         "MINIO_PRIVATE_MEDIA_BUCKET": private},
                    check=True, text=True, capture_output=True,
                )
                bucket, _, remainder = result.stdout.partition("\n")
                policy, offset = json.JSONDecoder().raw_decode(remainder)
                self.assertEqual(bucket, f"local/{public}")
                self.assertEqual(policy, {
                    "Version": "2012-10-17",
                    "Statement": [{"Effect": "Allow", "Principal": {"AWS": ["*"]},
                                   "Action": ["s3:GetObject"],
                                   "Resource": [f"arn:aws:s3:::{public}/*"]}],
                })
                self.assertEqual(remainder[offset:].strip(), f"private:local/{private}")

    def test_secret_consumers_share_nonroot_read_group(self) -> None:
        services = self.config["services"]
        expected_group = services["backend"]["group_add"]

        self.assertEqual(len(expected_group), 1)
        self.assertNotEqual(expected_group, ["0"])
        for name, service in services.items():
            if service.get("secrets"):
                with self.subTest(service=name):
                    self.assertEqual(service["group_add"], expected_group)


class BackendProductionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = validate_staging.render(validate_staging.TEMPLATE_FILE)

    def assert_rejected(self, config: dict, message: str) -> None:
        with self.assertRaisesRegex(validate_staging.ValidationError, message):
            validate_staging.validate_structure(config, allow_placeholders=True)

    def test_every_backend_job_receives_the_exact_contract(self) -> None:
        for name in validate_staging.BACKEND_SERVICES:
            environment = self.config["services"][name]["environment"]
            for key, expected in validate_staging.BACKEND_CONTRACT.items():
                with self.subTest(service=name, key=key):
                    self.assertEqual(environment[key], expected)
            self.assertNotIn("ALLOWED_HOSTS", environment)

    def test_backend_facing_hosts_avoid_rejected_development_names(self) -> None:
        environment = self.config["services"]["backend"]["environment"]
        frontend = self.config["services"]["frontend"]["environment"]
        hosts = {
            environment["DJANGO_ALLOWED_HOSTS"],
            environment["POSTGRES_HOST"],
            urlsplit(environment["MEDIA_STORAGE_INTERNAL_ENDPOINT_URL"]).hostname,
            urlsplit(frontend["BACKEND_INTERNAL_URL"]).hostname,
        }

        self.assertFalse(hosts & validate_staging.BACKEND_DEVELOPMENT_HOSTS)
        self.assertEqual(
            urlsplit(frontend["BACKEND_INTERNAL_URL"]).hostname,
            environment["DJANGO_ALLOWED_HOSTS"],
        )

    def test_search_path_requires_application_schema_then_public_postgis(self) -> None:
        for name in validate_staging.BACKEND_SERVICES:
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
                for name in validate_staging.BACKEND_SERVICES:
                    config["services"][name]["environment"]["POSTGRES_OPTIONS"] = value
                self.assert_rejected(config, "backend POSTGRES_OPTIONS must be")

    def test_development_service_names_are_rejected(self) -> None:
        cases = {
            "POSTGRES_HOST": "db",
            "DJANGO_ALLOWED_HOSTS": "backend",
            "MEDIA_STORAGE_INTERNAL_ENDPOINT_URL": "http://storage:9000",
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                config = copy.deepcopy(self.config)
                for name in validate_staging.BACKEND_SERVICES:
                    config["services"][name]["environment"][key] = value
                self.assert_rejected(config, f"backend {key} must be")

    def test_weaker_database_tls_or_untrusted_proxy_is_rejected(self) -> None:
        cases = {
            "POSTGRES_SSLMODE": "require",
            "DJANGO_TRUST_X_FORWARDED_PROTO": "false",
            "PGSSLROOTCERT": "/tmp/ca.pem",
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                config = copy.deepcopy(self.config)
                for name in validate_staging.BACKEND_SERVICES:
                    config["services"][name]["environment"][key] = value
                self.assert_rejected(config, f"backend {key} must be")

    def test_legacy_allowed_hosts_name_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        for name in validate_staging.BACKEND_SERVICES:
            config["services"][name]["environment"]["ALLOWED_HOSTS"] = "backend"

        self.assert_rejected(config, "must use DJANGO_ALLOWED_HOSTS")

    def test_backend_job_environment_drift_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["services"]["media-cleanup"]["environment"]["POSTGRES_SSLMODE"] = "require"

        self.assert_rejected(config, "media-cleanup must receive the same backend")

    def test_private_alias_hijack_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["services"]["frontend"]["networks"]["application"] = {
            "aliases": [validate_staging.BACKEND_ALIAS]
        }

        self.assert_rejected(config, "frontend private alias on application changed")

    def test_database_serves_tls_with_an_isolated_private_key(self) -> None:
        database = self.config["services"]["db"]
        for argument in validate_staging.DATABASE_TLS_ARGUMENTS:
            with self.subTest(argument=argument):
                self.assertIn(argument, validate_staging.command_text(database))
        self.assertIn(validate_staging.DATABASE_TLS_DIRECTORY, database["tmpfs"])

        config = copy.deepcopy(self.config)
        config["services"]["db"]["command"] = [
            part.replace("-c ssl=on ", "") for part in config["services"]["db"]["command"]
        ]
        self.assert_rejected(config, "PostgreSQL must serve TLS")

        config = copy.deepcopy(self.config)
        config["services"]["backend"]["secrets"].append(
            {
                "source": "postgres_tls_private_key",
                "target": "/run/secrets/postgres_tls_private_key",
            }
        )
        self.assert_rejected(config, "backend must not mount the PostgreSQL TLS private key")

    def test_redirected_secret_target_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["services"]["backend"]["secrets"][0]["target"] = "/run/secrets/postgres_tls_ca"

        self.assert_rejected(config, "backend must mount each secret at its default path")


class FrontendProductionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = validate_staging.render(validate_staging.TEMPLATE_FILE)

    def frontend_rejects(self, key: str, value: str, message: str) -> None:
        config = copy.deepcopy(self.config)
        config["services"]["frontend"]["environment"][key] = value
        with self.assertRaisesRegex(validate_staging.ValidationError, message):
            validate_staging.validate_structure(config, allow_placeholders=True)

    def test_template_matches_the_frontend_runtime_contract(self) -> None:
        environment = self.config["services"]["frontend"]["environment"]
        for key, expected in validate_staging.FRONTEND_CONTRACT.items():
            with self.subTest(key=key):
                self.assertEqual(environment[key], expected)
        self.assertEqual(environment["NEXTAUTH_URL"], environment["NEXT_PUBLIC_BASE_URL"])

    def test_release_version_must_be_a_full_source_commit(self) -> None:
        self.frontend_rejects("NEXT_PUBLIC_VERSION", "v1.0.0", "full lowercase 40-hex")
        self.frontend_rejects("NEXT_PUBLIC_VERSION", "A" * 40, "full lowercase 40-hex")

        with self.assertRaisesRegex(
            validate_staging.ValidationError, "RELEASE_VERSION still uses the placeholder"
        ):
            validate_staging.validate_frontend_contract(
                self.config["services"],
                self.config["services"]["backend"]["environment"],
                allow_placeholders=False,
            )

    def test_public_build_inputs_must_match_the_frontend_validator(self) -> None:
        self.frontend_rejects(
            "NEXTAUTH_URL", "https://other.example.com", "must equal NEXT_PUBLIC_BASE_URL"
        )
        self.frontend_rejects(
            "NEXT_PUBLIC_MAP_STYLE", "http://tiles.example.com/style", "NEXT_PUBLIC_MAP_STYLE"
        )
        self.frontend_rejects("NEXT_PUBLIC_LOG_LEVEL", "verbose", "LOG_LEVEL must be")
        self.frontend_rejects(
            "BACKEND_INTERNAL_URL", "http://backend:8000", "frontend BACKEND_INTERNAL_URL"
        )
        self.frontend_rejects(
            "NEXT_PUBLIC_GRAPHQL_ENDPOINT",
            "https://staging.example.com/graphql",
            "frontend NEXT_PUBLIC_GRAPHQL_ENDPOINT",
        )

    def test_application_origin_must_be_exact_and_public(self) -> None:
        for value in (
            "https://staging.example.com/",
            "https://staging.internal",
            "https://10.0.0.5",
            "https://staging.example.com:8443",
        ):
            with self.subTest(value=value):
                config = copy.deepcopy(self.config)
                config["services"]["frontend"]["environment"].update(
                    NEXT_PUBLIC_BASE_URL=value, NEXTAUTH_URL=value
                )
                with self.assertRaisesRegex(
                    validate_staging.ValidationError, "exact public HTTPS origin"
                ):
                    validate_staging.validate_structure(config, allow_placeholders=True)


class ControlledMigrationTests(unittest.TestCase):
    def test_migration_command_needs_both_profiles(self) -> None:
        with self.assertRaisesRegex(
            validate_staging.ValidationError, "depends on undefined service"
        ):
            validate_staging.compose_config(
                validate_staging.TEMPLATE_FILE,
                validate_staging.COMPOSE_FILE,
                profiles=(validate_staging.MIGRATION_PROFILE,),
            )
        for profile in (
            validate_staging.RUNTIME_PROFILE,
            validate_staging.MIGRATION_PROFILE,
        ):
            self.assertIn(f"--profile {profile}", validate_staging.MIGRATION_COMMAND)
        self.assertTrue(validate_staging.MIGRATION_COMMAND.endswith(" run --rm migrate"))

    def test_runtime_command_never_selects_the_migration_job(self) -> None:
        runtime = validate_staging.compose_config(
            validate_staging.TEMPLATE_FILE,
            validate_staging.COMPOSE_FILE,
            profiles=(validate_staging.RUNTIME_PROFILE,),
        )

        self.assertNotIn("migrate", runtime["services"])
        self.assertNotIn(
            validate_staging.MIGRATION_PROFILE, validate_staging.RUNTIME_COMMAND
        )

    def test_migration_checks_deployment_then_precedes_backend(self) -> None:
        config = validate_staging.render(validate_staging.TEMPLATE_FILE)
        migration = validate_staging.command_text(config["services"]["migrate"])

        self.assertLess(
            migration.index("manage.py check --deploy"),
            migration.index("manage.py migrate --noinput"),
        )
        self.assertEqual(
            config["services"]["backend"]["depends_on"]["migrate"],
            {"condition": "service_completed_successfully", "required": False},
        )

        unordered = copy.deepcopy(config)
        unordered["services"]["backend"]["depends_on"].pop("migrate")
        with self.assertRaisesRegex(
            validate_staging.ValidationError, "backend must start only after"
        ):
            validate_staging.validate_structure(unordered, allow_placeholders=True)

    def test_readme_documents_the_exact_release_commands(self) -> None:
        readme = validate_staging.README_FILE.read_text(encoding="utf-8")

        self.assertIn(validate_staging.MIGRATION_COMMAND, readme)
        self.assertIn(validate_staging.RUNTIME_COMMAND, readme)
        self.assertLess(
            readme.index(validate_staging.MIGRATION_COMMAND),
            readme.index(validate_staging.RUNTIME_COMMAND),
        )


def openssl(directory: Path, *arguments: str) -> None:
    subprocess.run(
        ["openssl", *arguments],
        cwd=directory,
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )


def generate_database_tls(directory: Path, hostname: str) -> dict[str, str]:
    """Create a throwaway CA and server pair; nothing is committed."""

    curve = ("-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes")
    openssl(
        directory, "req", "-x509", *curve, "-keyout", "ca.key", "-out", "ca.crt",
        "-subj", "/CN=smokemap-test-ca", "-days", "2",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )
    openssl(
        directory, "req", *curve, "-keyout", "server.key", "-out", "server.csr",
        "-subj", f"/CN={hostname}",
    )
    (directory / "server.ext").write_text(
        f"subjectAltName=DNS:{hostname}\nextendedKeyUsage=serverAuth\n",
        encoding="utf-8",
    )
    openssl(
        directory, "x509", "-req", "-in", "server.csr", "-CA", "ca.crt",
        "-CAkey", "ca.key", "-set_serial", "1", "-days", "1",
        "-extfile", "server.ext", "-out", "server.crt",
    )
    return {
        "postgres_tls_ca": (directory / "ca.crt").read_text(encoding="utf-8"),
        "postgres_tls_certificate": (directory / "server.crt").read_text(encoding="utf-8"),
        "postgres_tls_private_key": (directory / "server.key").read_text(encoding="utf-8"),
    }


class StagingReleaseInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tls_directory = tempfile.TemporaryDirectory(
            prefix="smokemap-staging-tls-", dir="/tmp"
        )
        root = Path(cls.tls_directory.name)
        cls.tls_material = generate_database_tls(root, validate_staging.DATABASE_ALIAS)
        wrong_host = root / "wrong-host"
        wrong_host.mkdir()
        cls.wrong_host_material = generate_database_tls(wrong_host, "db")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tls_directory.cleanup()

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
            secret_file.write_text(
                self.tls_material.get(name, f"test-only-non-secret-{name}-{'x' * 50}\n"),
                encoding="utf-8",
            )
            secret_file.chmod(0o640)
            self.config["secrets"][name] = {"file": str(secret_file)}

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def replace_secret(self, name: str, value: str) -> None:
        Path(self.config["secrets"][name]["file"]).write_text(value, encoding="utf-8")

    def test_secure_external_inputs_are_accepted(self) -> None:
        validate_staging.validate_release_inputs(self.config, self.env_file)

    def test_short_or_padded_application_secrets_are_rejected(self) -> None:
        cases = {
            "django_secret_key": ("x" * 49 + "\n", "at least 50 characters"),
            "nextauth_secret": ("x" * 31 + "\n", "at least 32 characters"),
            "postgres_password": (" padded-test-value\n", "surrounding whitespace"),
        }
        for name, (value, message) in cases.items():
            with self.subTest(secret=name):
                original = Path(self.config["secrets"][name]["file"]).read_text(
                    encoding="utf-8"
                )
                self.replace_secret(name, value)
                with self.assertRaisesRegex(
                    validate_staging.ValidationError, f"{name} secret must .*{message}"
                ) as raised:
                    validate_staging.validate_release_inputs(self.config, self.env_file)
                self.assertNotIn(value.strip(), str(raised.exception))
                self.replace_secret(name, original)

    def test_database_certificate_for_another_host_is_rejected(self) -> None:
        for name, value in self.wrong_host_material.items():
            self.replace_secret(name, value)

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            f"chain to postgres_tls_ca, and name {validate_staging.DATABASE_ALIAS}",
        ):
            validate_staging.validate_release_inputs(self.config, self.env_file)

    def test_database_certificate_from_another_authority_is_rejected(self) -> None:
        self.replace_secret(
            "postgres_tls_ca", self.wrong_host_material["postgres_tls_ca"]
        )

        with self.assertRaisesRegex(
            validate_staging.ValidationError, "chain to postgres_tls_ca"
        ):
            validate_staging.validate_release_inputs(self.config, self.env_file)

    def test_mismatched_database_private_key_is_rejected(self) -> None:
        self.replace_secret(
            "postgres_tls_private_key",
            self.wrong_host_material["postgres_tls_private_key"],
        )

        with self.assertRaisesRegex(
            validate_staging.ValidationError,
            "private key must be unencrypted and match its certificate",
        ) as raised:
            validate_staging.validate_release_inputs(self.config, self.env_file)
        self.assertNotIn("PRIVATE KEY", str(raised.exception))

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
        release_environment = release_environment.replace(
            f"RELEASE_VERSION={'0' * 40}", f"RELEASE_VERSION={'a' * 40}"
        )
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
