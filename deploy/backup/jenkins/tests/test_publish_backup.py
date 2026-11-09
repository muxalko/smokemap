"""Synthetic Linux fixture tests for the completed-export publisher."""
import datetime
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from publish_backup import PAYLOADS, publish


class PublishBackupTest(unittest.TestCase):
    run_id = "fixture-unit-test"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / "source"
        self.exports = Path(temporary.name) / "exports"
        self.source.mkdir(mode=0o700)
        self.exports.mkdir(mode=0o700)
        self.payloads = {name: f"Public synthetic test bytes for {name}\n".encode() for name in PAYLOADS}
        self.receipt = {
            "project": "smokemap",
            "backup": self.source.name,
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "frontend_api_cleanup_storage_quiesced_before_both_archives": True,
            "originals_resumed_healthy": True,
            "operator_writer_inventory_and_client_activity_checked": True,
            "files": {},
        }
        for name, data in self.payloads.items():
            self.write_private(name, data)
            self.receipt["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        self.write_private("backup.json", json.dumps(self.receipt).encode())

    def write_private(self, name, data):
        path = self.source / name
        path.write_bytes(data)
        path.chmod(0o600)

    def publish(self):
        return publish(self.source, self.exports, self.run_id, fixture=True)

    def test_publish_verified_pair(self):
        receipt = self.publish()
        output = self.exports / self.run_id
        manifest_bytes = (output / "manifest.json").read_bytes()
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), receipt["manifest_sha256"])
        manifest = json.loads(manifest_bytes)
        self.assertEqual(manifest["run_id"], self.run_id)
        self.assertEqual(manifest["environment"], "fixture")
        self.assertEqual([item["name"] for item in manifest["files"]], list(PAYLOADS))
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        for name, data in self.payloads.items():
            self.assertEqual((output / name).read_bytes(), data)
            self.assertEqual((output / name).stat().st_mode & 0o777, 0o600)

    def test_reject_changed_payload_and_remove_stage(self):
        self.write_private("media.tar", b"x" * len(self.payloads["media.tar"]))
        with self.assertRaisesRegex(ValueError, "does not match receipt"):
            self.publish()
        self.assertEqual(list(self.exports.iterdir()), [])

    def test_reject_duplicate_and_preserve_existing_output(self):
        output = self.exports / self.run_id
        output.mkdir(mode=0o700)
        with self.assertRaises(FileExistsError):
            self.publish()
        self.assertEqual(list(self.exports.iterdir()), [output])
        self.assertEqual(list(output.iterdir()), [])

    def test_reject_linked_archive(self):
        archive = self.source / "media.tar"
        archive.unlink()
        archive.symlink_to(self.source / "database.dump")
        with self.assertRaises(OSError):
            self.publish()
        self.assertEqual(list(self.exports.iterdir()), [])

    def test_reject_incomplete_capture(self):
        self.receipt["originals_resumed_healthy"] = False
        self.write_private("backup.json", json.dumps(self.receipt).encode())
        with self.assertRaisesRegex(ValueError, "completion evidence"):
            self.publish()
        self.assertEqual(list(self.exports.iterdir()), [])


if __name__ == "__main__":
    os.umask(0o077)
    unittest.main()
