"""Offline Compose/probe boundary checks; never contact a live application."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent


def render(*files, **overrides):
    env = {**os.environ, "FRONTEND_MEMORY_LIMIT": "",
           "FRONTEND_NODE_MAX_OLD_SPACE_SIZE_MB": "", **overrides}
    command = ["docker", "compose", "--env-file", "/dev/null"]
    for file in files or ("docker-compose.yaml",):
        command.extend(["--file", file])
    result = subprocess.run([*command, "config", "--format", "json"], cwd=ROOT,
                            env=env, check=True, capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)


class FrontendMemoryTests(unittest.TestCase):
    def test_defaults_overrides_and_isolated_e2e_inheritance(self):
        for overrides, memory, heap in (({}, 6 * 1024**3, "4096"),
                                       ({"FRONTEND_MEMORY_LIMIT": "5g",
                                         "FRONTEND_NODE_MAX_OLD_SPACE_SIZE_MB": "3072"},
                                        5 * 1024**3, "3072")):
            for files in (("docker-compose.yaml",),
                          ("docker-compose.yaml", "e2e/docker-compose.e2e.yaml")):
                with self.subTest(overrides=overrides, files=files):
                    config = render(*files, **overrides)
                    frontend = config["services"]["frontend"]
                    self.assertEqual(int(frontend["mem_limit"]), memory)
                    self.assertEqual(frontend["environment"]["NODE_OPTIONS"],
                                     "--max-old-space-size=" + heap)
                    for name, service in config["services"].items():
                        if name != "frontend":
                            self.assertNotIn("mem_limit", service)
                            self.assertNotIn("NODE_OPTIONS", service.get("environment", {}))
                    if len(files) > 1:
                        self.assertFalse(frontend.get("ports"))
                        self.assertTrue(config["networks"]["default"]["internal"])

    def test_actual_healthcheck_against_disposable_http_server(self):
        test = render()["services"]["frontend"]["healthcheck"]["test"]
        self.assertEqual(test[:3], ["CMD", "node", "-e"])
        subprocess.run(["node", "tests/dev-frontend-healthcheck.cjs", test[3]],
                       cwd=ROOT, check=True, timeout=20)


if __name__ == "__main__":
    unittest.main()
