"""Publish a completed Jenkins backup pair for the Windows receiver."""
import argparse
import ctypes
import datetime
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path

PAYLOADS = ("database.dump", "media.tar")
MAX_PAIR_BYTES = 16 * 1024**3
MAX_RECEIPT_BYTES = 65536
MIN_FREE_BYTES = 10 * 1024**3
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


@contextmanager
def private_directory(path):
    if not path.is_absolute() or ".." in path.parts or path.anchor != "/":
        raise ValueError("expected a normalized absolute directory")
    directory = os.open("/", DIRECTORY_FLAGS)
    try:
        for component in path.parts[1:]:
            child = os.open(component, DIRECTORY_FLAGS, dir_fd=directory)
            os.close(directory)
            directory = child
        details = os.fstat(directory)
        if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
            raise ValueError("backup directory must be owner-private")
        yield directory
    finally:
        os.close(directory)


@contextmanager
def private_file(directory, name):
    descriptor = os.open(name, FILE_FLAGS, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError("backup input must be an owner-private regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            yield stream, info.st_size
    finally:
        os.close(descriptor)


def distinct_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("capture receipt contains duplicate fields")
    return result


def read_receipt(source, name):
    with private_file(source, "backup.json") as (stream, size):
        if not 1 <= size <= MAX_RECEIPT_BYTES:
            raise ValueError("capture receipt exceeds byte budget")
        data = stream.read(MAX_RECEIPT_BYTES + 1)
        if len(data) != size:
            raise ValueError("capture receipt changed during read")
    receipt = json.loads(data, object_pairs_hook=distinct_fields)
    if (receipt["project"] != "smokemap" or receipt["backup"] != name
            or not all(receipt.get(field) is True for field in (
                "frontend_api_cleanup_storage_quiesced_before_both_archives",
                "originals_resumed_healthy",
                "operator_writer_inventory_and_client_activity_checked",
            ))):
        raise ValueError("capture completion evidence is missing")
    captured = datetime.datetime.fromisoformat(receipt["at"])
    now = datetime.datetime.now(datetime.timezone.utc)
    if captured.utcoffset() is None or captured > now + datetime.timedelta(minutes=1):
        raise ValueError("invalid capture timestamp")
    if set(receipt["files"]) != set(PAYLOADS):
        raise ValueError("capture receipt must cover both archives")
    entries = []
    for name in PAYLOADS:
        entry = receipt["files"][name]
        if (set(entry) != {"bytes", "sha256"} or type(entry["bytes"]) is not int
                or not 1 <= entry["bytes"] <= MAX_PAIR_BYTES
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            raise ValueError("invalid archive length or digest")
        entries.append({"name": name, **entry})
    if sum(entry["bytes"] for entry in entries) > MAX_PAIR_BYTES:
        raise ValueError("archive pair exceeds byte budget")
    return entries, captured.isoformat(), hashlib.sha256(data).hexdigest()


def new_file(directory, name):
    return os.fdopen(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory), "wb")


def copy_verified(source, stage, entry):
    name = entry["name"]
    with private_file(source, name) as (input_file, size):
        if size != entry["bytes"]:
            raise ValueError("capture archive size differs from receipt")
        digest = hashlib.sha256()
        with new_file(stage, name) as output_file:
            remaining = size
            while remaining:
                chunk = input_file.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("capture archive became shorter during copy")
                digest.update(chunk)
                output_file.write(chunk)
                remaining -= len(chunk)
            if input_file.read(1) or digest.hexdigest() != entry["sha256"]:
                raise ValueError("capture archive does not match receipt")
            output_file.flush()
            os.fsync(output_file.fileno())


def rename_without_replacing(directory, stage, run_id):
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    rename_noreplace = 1
    if rename(directory, os.fsencode(stage), directory, os.fsencode(run_id), rename_noreplace):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def publish(source_path, export_path, run_id, fixture=False):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,63}", run_id) or fixture != run_id.startswith("fixture-"):
        raise ValueError("invalid export run ID")
    environment = "fixture" if fixture else "development"
    with private_directory(source_path) as source, private_directory(export_path) as exports:
        fcntl.flock(exports, fcntl.LOCK_EX | fcntl.LOCK_NB)
        entries, captured, receipt_digest = read_receipt(source, source_path.name)
        space = os.fstatvfs(exports)
        if space.f_bavail * space.f_frsize < MIN_FREE_BYTES + sum(entry["bytes"] for entry in entries):
            raise ValueError("export volume has insufficient free space")
        stage_name = ".incoming-" + secrets.token_hex(16)
        os.mkdir(stage_name, 0o700, dir_fd=exports)
        stage = os.open(stage_name, DIRECTORY_FLAGS, dir_fd=exports)
        published = False
        try:
            for entry in entries:
                copy_verified(source, stage, entry)
            manifest = {"schema": 1, "run_id": run_id, "environment": environment, "files": entries}
            manifest_bytes = (json.dumps(manifest, separators=(",", ":")) + "\n").encode("utf-8")
            with new_file(stage, "manifest.json") as output_file:
                output_file.write(manifest_bytes)
                output_file.flush()
                os.fsync(output_file.fileno())
            os.fsync(stage)
            rename_without_replacing(exports, stage_name, run_id)
            published = True
            os.fsync(exports)
        finally:
            try:
                if not published:
                    for name in (*PAYLOADS, "manifest.json"):
                        try:
                            os.unlink(name, dir_fd=stage)
                        except FileNotFoundError:
                            pass
                    os.rmdir(stage_name, dir_fd=exports)
            finally:
                os.close(stage)
        return {"run_id": run_id, "environment": environment, "captured_at": captured,
                "capture_receipt_sha256": receipt_digest,
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fixture", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    root = Path.home() / ".local/state/smokemap-offvm-export"
    print(json.dumps(publish(args.source, root, args.run_id, fixture=args.fixture)))


if __name__ == "__main__":
    main()
