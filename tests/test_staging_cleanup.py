"""Disposable Compose 2.35.1 regression; never uses a staging runtime project."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "validate_local_staging", ROOT / "scripts" / "validate-local-staging.py"
)
assert SPEC is not None and SPEC.loader is not None
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)
staging = local.staging


class CleanupComposeWaitTests(unittest.TestCase):
    def test_disabled_probe_fails_but_pid_one_probe_passes_in_both_modes(self) -> None:
        compose = [os.environ["COMPOSE_235_BINARY"]] if os.environ.get(
            "COMPOSE_235_BINARY"
        ) else ["docker", "compose"]
        version = subprocess.run(
            [*compose, "version", "--short"], check=True, text=True,
            capture_output=True, timeout=10,
        ).stdout.strip().removeprefix("v")
        self.assertEqual(version, "2.35.1", "This regression must exercise Compose 2.35.1")
        configs = {
            "external": staging.render(staging.TEMPLATE_FILE),
            "local": local.render(local.SETTINGS_TEMPLATE, local.RELEASE_TEMPLATE),
        }
        project = f"smokemap-cleanup-regression-{uuid.uuid4().hex}"
        with tempfile.TemporaryDirectory(prefix=project, dir="/tmp") as directory:
            root = Path(directory)
            # Same Python family and UID as production, with an inherited web
            # probe and no HTTP listener. No app, database, secrets or storage.
            inherited_probe = [
                "python", "-c", "import urllib.request; "
                "urllib.request.urlopen('http://127.0.0.1:8000/health/live/', timeout=2)",
            ]
            (root / "Dockerfile").write_text(
                'FROM python:3.12-slim-bookworm\n'
                'USER 10001:10001\n'
                f'HEALTHCHECK CMD {json.dumps(inherited_probe)}\n',
                encoding="utf-8",
            )
            image = f"{project}:test"
            subprocess.run(
                ["docker", "build", "--tag", image, str(root)], check=True, timeout=180,
            )
            self.addCleanup(subprocess.run, ["docker", "image", "rm", image],
                            check=True, timeout=30)
            config_file = root / "compose.json"
            prefix = [*compose, "--project-name", project, "--file", str(config_file)]
            try:
                for mode, healthcheck in (
                    ("disabled", {"disable": True}),
                    *((name, config["services"]["media-cleanup"]["healthcheck"])
                      for name, config in configs.items()),
                ):
                    with self.subTest(mode=mode):
                        config_file.write_text(json.dumps({"services": {"media-cleanup": {
                            "image": image, "pull_policy": "never", "network_mode": "none",
                            "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
                            "entrypoint": ["/bin/sh", "-ec"],
                            # Failed batches must not turn process health into a
                            # claim of progress. PID 1 is the shell, not the probe.
                            "command": ["while true; do false || echo batch-failed; sleep 300; done"],
                            "healthcheck": healthcheck,
                        }}}), encoding="utf-8")
                        result = subprocess.run(
                            [*prefix, "up", "--detach", "--wait", "--wait-timeout", "45"],
                            text=True, capture_output=True, timeout=60,
                        )
                        if mode == "disabled":
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIn("has no healthcheck configured", result.stdout + result.stderr)
                        else:
                            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                            container = subprocess.run(
                                [*prefix, "ps", "--quiet", "media-cleanup"],
                                check=True, text=True, capture_output=True, timeout=10,
                            ).stdout.strip()
                            state = json.loads(subprocess.run(
                                ["docker", "inspect", container], check=True,
                                text=True, capture_output=True, timeout=10,
                            ).stdout)[0]
                            self.assertEqual(state["State"]["Health"]["Status"], "healthy")
                            self.assertEqual(state["Config"]["User"], "10001:10001")
                            self.assertEqual(state["Config"]["Healthcheck"]["Test"],
                                             healthcheck["test"])
                            logs = subprocess.run(
                                [*prefix, "logs", "--no-color"], check=True,
                                text=True, capture_output=True, timeout=10,
                            )
                            self.assertIn("batch-failed", logs.stdout)
                        subprocess.run([*prefix, "down", "--timeout", "1"], check=True, timeout=30)
            finally:
                # Only this UUID project: no published ports, mounts or volumes.
                subprocess.run([*prefix, "down", "--timeout", "1"], check=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
