"""Real fresh-PostGIS regression; run explicitly with make test-staging-postgis."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "local_staging", ROOT / "scripts" / "local-staging.py"
)
assert SPEC is not None and SPEC.loader is not None
operations = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operations)
local = operations.local
staging = operations.staging


class FreshStagingPostgisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configs = {
            "external": staging.render(staging.TEMPLATE_FILE),
            "local": local.render(local.SETTINGS_TEMPLATE, local.RELEASE_TEMPLATE),
        }
        # Same reviewed index digest as local staging; never use its live project.
        image = operations.UPSTREAM_IMAGES["db"]
        if "@sha256:" not in image:
            raise AssertionError("The PostGIS regression requires an immutable image")
        subprocess.run(["docker", "pull", image], check=True, timeout=180)
        result = subprocess.run(
            [
                "docker", "run", "--detach", "--rm",
                "--name", f"smokemap-postgis-regression-{uuid.uuid4().hex}",
                "--network", "none",
                "--mount", "type=tmpfs,destination=/var/lib/postgresql/data",
                "--mount", (
                    f"type=bind,source={local.POSTGRES_INIT_FILE},"
                    "destination=/docker-entrypoint-initdb.d/00-create-smokemap-schema.sql,readonly"
                ),
                # Trust is confined to this networkless disposable test container.
                "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
                "--env", "POSTGRES_DB=smokemap_regression",
                image,
            ],
            check=True, text=True, capture_output=True, timeout=30,
        )
        cls.container = result.stdout.strip()
        # Clean up only the container created above, including on setup/test failure.
        cls.addClassCleanup(cls.remove_container)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            logs = subprocess.run(
                ["docker", "logs", cls.container],
                check=True, text=True, capture_output=True, timeout=10,
            )
            # Wait past the temporary init server so tests use the final server.
            if "PostgreSQL init process complete; ready for start up." in logs.stdout:
                ready = cls.sql("-c search_path=public", "SELECT 1;")
                if ready.returncode == 0:
                    break
            time.sleep(1)
        else:
            raise AssertionError("Fresh disposable PostGIS did not become ready")
        baseline = cls.sql(
            "-c search_path=public",
            "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n "
            "ON n.oid=e.extnamespace WHERE e.extname='postgis';"
            "SELECT nspname FROM pg_namespace WHERE nspname='smokemap';",
        )
        if baseline.returncode or baseline.stdout.splitlines() != ["public", "smokemap"]:
            raise AssertionError(f"Unexpected fresh PostGIS layout: {baseline}")

    @classmethod
    def remove_container(cls) -> None:
        subprocess.run(
            ["docker", "rm", "--force", cls.container], check=True, timeout=30,
            stdout=subprocess.DEVNULL,
        )

    @classmethod
    def sql(cls, options: str, statement: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "docker", "exec", "--env", f"PGOPTIONS={options}", cls.container,
                "psql", "--no-psqlrc", "--username=postgres",
                "--dbname=smokemap_regression", "--tuples-only", "--no-align",
                "--quiet", "--set=ON_ERROR_STOP=1", "--set=VERBOSITY=verbose",
                "--command", statement,
            ],
            text=True, capture_output=True, timeout=15,
        )

    def test_old_path_hides_geometry_and_fails_gis_ddl(self) -> None:
        visibility = self.sql(
            "-c search_path=smokemap",
            "SELECT current_schema(), to_regtype('geometry') IS NULL;",
        )
        self.assertEqual(visibility.returncode, 0, visibility.stderr)
        self.assertEqual(visibility.stdout.strip(), "smokemap|t")
        ddl = self.sql(
            "-c search_path=smokemap",
            "CREATE TABLE postgis_old_path_probe (location geometry(Point,4326));",
        )
        self.assertNotEqual(ddl.returncode, 0)
        self.assertIn('42704: type "geometry" does not exist', ddl.stderr)

    def test_rendered_job_options_allow_gis_ddl_in_application_schema(self) -> None:
        for topology, config in self.configs.items():
            for name in staging.BACKEND_SERVICES:
                with self.subTest(topology=topology, service=name):
                    options = config["services"][name]["environment"]["POSTGRES_OPTIONS"]
                    result = self.sql(options, """
                        BEGIN;
                        SELECT current_schema(),
                            to_regtype('geometry') = to_regtype('public.geometry');
                        CREATE TABLE postgis_path_probe (
                            id integer PRIMARY KEY, location geometry(Point,4326)
                        );
                        CREATE INDEX postgis_path_probe_gist
                            ON postgis_path_probe USING gist (location);
                        INSERT INTO postgis_path_probe VALUES
                            (1, ST_SetSRID(ST_Point(35,32),4326));
                        SELECT ST_AsEWKT(location) FROM postgis_path_probe;
                        SELECT n.nspname, c.relname FROM pg_class c
                            JOIN pg_namespace n ON n.oid=c.relnamespace
                            WHERE c.relname IN
                                ('postgis_path_probe', 'postgis_path_probe_gist')
                            ORDER BY c.relname;
                        ROLLBACK;
                    """)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(), [
                        "smokemap|t",
                        "SRID=4326;POINT(35 32)",
                        "smokemap|postgis_path_probe",
                        "smokemap|postgis_path_probe_gist",
                    ])


if __name__ == "__main__":
    unittest.main()
