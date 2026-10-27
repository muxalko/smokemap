#!/usr/bin/env python3
"""Development-only cleanup supervisor and fail-closed Docker health probe.

No Django imports: all command diagnostics are untrusted and stay in memory.
Linux /proc binds status to this runner incarnation, never just PID 1 liveness.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid

STATE_DIRECTORY = Path('/tmp/smokemap-dev-cleanup')
COUNTS = ('expired', 'claimed', 'deleted', 'upload_claimed', 'upload_deleted',
          'redacted', 'failed', 'skipped', 'draft_expired')
PREFIX = 'media cleanup processed: '
OUTPUT_LIMIT = 65536
SCHEDULING_GRACE = 15
SHUTDOWN_GRACE = 2
STATE_KEYS = {'version', 'pid', 'process_start', 'started_at', 'updated_at',
              'last_success_at', 'phase', 'deadline', 'started_elapsed',
              'updated_elapsed', 'last_success_elapsed', 'deadline_elapsed'}


class InvalidOutput(Exception):
    pass


class StateError(Exception):
    pass


def config():
    values = []
    for key, default in (('BATCH_SIZE', '100'), ('INTERVAL_SECONDS', '300'),
                         ('TIMEOUT_SECONDS', '120')):
        value = os.environ.get('MEDIA_CLEANUP_' + key, default)
        # Bound parsing, and reject signs, whitespace, non-ASCII digits and zero.
        if not re.fullmatch(r'[0-9]{1,10}', value) or not 1 <= int(value) <= 2147483647:
            raise ValueError
        values.append(int(value))
    if values[0] > 1000:
        raise ValueError
    return tuple(values)


def event(name, outcome, reason, counts=None):
    value = {'event': name, 'outcome': outcome, 'reason': reason,
             'timestamp': time.time()}
    if counts is not None:
        value['counts'] = counts
    print(json.dumps(value, separators=(',', ':'), allow_nan=False), flush=True)


def parse_counts(output):
    text = output.decode('utf-8', errors='replace')
    lines = [line for line in text.splitlines() if 'media cleanup processed' in line]
    if len(lines) != 1 or not lines[0].startswith(PREFIX):
        raise InvalidOutput
    pairs = lines[0][len(PREFIX):].split(' ')
    if len(pairs) != len(COUNTS):
        raise InvalidOutput
    counts = {}
    for pair in pairs:
        match = re.fullmatch(r'([a-z_]+)=([0-9]{1,10})', pair)
        if not match or match[1] not in COUNTS or match[1] in counts:
            raise InvalidOutput
        counts[match[1]] = int(match[2])
    if set(counts) != set(COUNTS):
        raise InvalidOutput
    return counts


def process_start(pid):
    # comm can contain spaces and parentheses; field 22 follows the final ')'.
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    if fields[0] == 'Z':
        raise ValueError
    return int(fields[19])


class Store:
    def __init__(self, directory):
        self.directory = directory

    def directory_fd(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            os.close(fd)
            raise StateError
        return fd

    def prepare(self):
        try:
            self.directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        with_fd = self.directory_fd()
        try:
            # Invalidate even a well-formed previous success before configuration/check.
            os.unlink('status.json', dir_fd=with_fd)
        except FileNotFoundError:
            pass
        finally:
            os.close(with_fd)

    def write(self, value):
        fd = self.directory_fd()
        stage = '.status-' + uuid.uuid4().hex
        created = False
        try:
            out = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=fd)
            created = True
            with os.fdopen(out, 'w') as stream:
                json.dump(value, stream, separators=(',', ':'), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(stage, 'status.json', src_dir_fd=fd, dst_dir_fd=fd)
        finally:
            try:
                if created:
                    os.unlink(stage, dir_fd=fd)
            except FileNotFoundError:
                pass
            finally:
                os.close(fd)

    def invalidate(self):
        try:
            fd = self.directory_fd()
            try:
                os.unlink('status.json', dir_fd=fd)
            finally:
                os.close(fd)
        except (OSError, StateError):
            pass

    def read(self):
        fd = self.directory_fd()
        try:
            source = os.open('status.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=fd)
        finally:
            os.close(fd)
        with os.fdopen(source, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise StateError
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise StateError
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise StateError
                value[key] = item
            return value
        return json.loads(raw, object_pairs_hook=unique)


def elapsed_time():
    # Linux boot-relative clock shared by runner/probe, including suspended time.
    # Wall-clock adjustments cannot move this clock backwards or revive status.
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def healthy(store, elapsed_now=None):
    try:
        _, interval, timeout = config()
        value = store.read()
        if not isinstance(value, dict) or set(value) != STATE_KEYS:
            return False
        if type(value['version']) is not int or value['version'] != 2:
            return False
        for key in ('pid', 'process_start'):
            if type(value[key]) is not int or value[key] <= 0:
                return False
        for key in ('started_at', 'updated_at', 'last_success_at', 'deadline',
                    'started_elapsed', 'updated_elapsed', 'last_success_elapsed',
                    'deadline_elapsed'):
            item = value[key]
            if type(item) not in (int, float) or not math.isfinite(item) or item <= 0:
                return False
        now = elapsed_time() if elapsed_now is None else elapsed_now
        started, updated, success, deadline = (value[key] for key in
            ('started_elapsed', 'updated_elapsed', 'last_success_elapsed', 'deadline_elapsed'))
        if not started <= success <= updated <= now <= deadline:
            return False
        if process_start(value['pid']) != value['process_start']:
            return False
        if value['phase'] == 'waiting':
            return success == updated and deadline == updated + interval + SCHEDULING_GRACE
        if value['phase'] == 'running':
            return (updated - success <= interval + SCHEDULING_GRACE
                    and deadline == updated + timeout)
        return False
    except (OSError, ValueError, TypeError, KeyError, IndexError, StateError):
        return False


def stop_group(child):
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=SHUTDOWN_GRACE)
    except subprocess.TimeoutExpired:
        pass
    # Also kill descendants that outlived their parent or ignored SIGTERM.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()


def command(arguments, timeout, stopping):
    if stopping():
        return 'shutdown', None
    try:
        child = subprocess.Popen([sys.executable, 'manage.py', *arguments],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 start_new_session=True)
    except OSError:
        return 'spawn_failed', None
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map() or child.poll() is None:
                if stopping():
                    return 'shutdown', None
                if time.monotonic() >= deadline:
                    return 'timeout', None
                for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                    data = os.read(key.fd, 8192)
                    if not data:
                        selector.unregister(key.fd)
                    elif len(output) + len(data) > OUTPUT_LIMIT:
                        return 'output_limit', None
                    else:
                        output.extend(data)
            if stopping():
                return 'shutdown', None
            if child.returncode != 0:
                return 'command_exit', None
            return 'ok', bytes(output)
    finally:
        stop_group(child)
        child.stdout.close()


def run(directory=STATE_DIRECTORY):
    stop_requested = False
    def stop(_signum, _frame):
        # Signal handlers must not acquire Event/Condition locks.
        nonlocal stop_requested
        stop_requested = True
    def stopping():
        return stop_requested
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    store = Store(directory)
    started = time.time()
    started_elapsed = elapsed_time()
    state = {'version': 2, 'pid': os.getpid(), 'process_start': process_start(os.getpid()),
             'started_at': started, 'updated_at': started, 'last_success_at': None,
             'phase': 'starting', 'deadline': started, 'started_elapsed': started_elapsed,
             'updated_elapsed': started_elapsed, 'last_success_elapsed': None,
             'deadline_elapsed': started_elapsed}
    def write(phase, duration, success=False):
        now = time.time()
        elapsed = elapsed_time()
        # Use the same elapsed sample for invalidation and the new deadline.
        # Never extend a stale success into a new healthy running deadline.
        if (phase == 'running' and state['last_success_elapsed'] is not None
                and elapsed > state['deadline_elapsed']):
            state['last_success_at'] = None
            state['last_success_elapsed'] = None
        state.update(phase=phase, updated_at=now, deadline=now + duration,
                     updated_elapsed=elapsed, deadline_elapsed=elapsed + duration)
        if success:
            state['last_success_at'] = now
            state['last_success_elapsed'] = elapsed
        store.write(state)
    try:
        store.prepare()
        write('starting', 0)
        try:
            batch, interval, timeout = config()
        except ValueError:
            event('startup', 'failure', 'config_invalid')
            return 64
        write('starting', timeout)
        reason, _ = command(['check'], timeout, stopping)
        if reason != 'ok':
            write('stopped' if reason == 'shutdown' else 'failed', 0)
            event('startup', 'failure', reason)
            return 0 if reason == 'shutdown' else 1
        event('startup', 'success', 'system_check')
        failed = False
        while not stopping():
            write('running', timeout)
            reason, output = command(['process_media_cleanup', '--batch-size', str(batch)],
                                     timeout, stopping)
            counts = None
            if reason == 'ok':
                try:
                    counts = parse_counts(output)
                    if counts['failed']:
                        reason = 'failed_count'
                except InvalidOutput:
                    reason = 'output_invalid'
            if reason == 'shutdown':
                break
            if reason == 'ok':
                write('waiting', interval + SCHEDULING_GRACE, success=True)
                event('batch', 'recovered' if failed else 'success', 'ok', counts)
                failed = False
            else:
                state['last_success_at'] = None
                state['last_success_elapsed'] = None
                write('failed', interval)
                event('batch', 'failure', reason, counts)
                failed = True
            wake = time.monotonic() + interval
            while not stopping() and time.monotonic() < wake:
                time.sleep(min(.1, max(0, wake - time.monotonic())))
        state['last_success_at'] = None
        state['last_success_elapsed'] = None
        write('stopped', 0)
        event('shutdown', 'stopped', 'shutdown')
        return 0
    except (OSError, StateError, ValueError):
        store.invalidate()
        event('runner', 'failure', 'state_error')
        return 74


def main():
    if sys.argv[1:] == ['health']:
        return 0 if healthy(Store(STATE_DIRECTORY)) else 1
    if sys.argv[1:] == ['run']:
        return run()
    return 64


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        # Never let a traceback expose command/environment data.
        event('runner', 'failure', 'internal_error')
        sys.exit(1)
