"""Executed inside existing containers with Python stdlib; numeric aggregates only.

No worker/store/driver/notifier entrypoints. Each exec has its own 3-second
alarm: killing the host Docker client alone would leave an exec running.
"""
from contextlib import closing
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import stat
import sys
import time

LIMIT = 262144


def stamp(value, now):
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    result = date.timestamp()
    if date.tzinfo is None or not math.isfinite(result) or not 0 < result <= now:
        raise ValueError('timestamp')
    return result


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError('integer')
    return value


def bounded(path, limit):
    # O_NONBLOCK avoids a FIFO hanging an internal exec; refuse nonregular files.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('regular file')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('input limit')
    return raw


def schedules(path):
    from web_checker.config import load_config
    raw = bounded(path, LIMIT)
    # load_config reads a path. Give it an immutable bounded snapshot, not the
    # live file a second time (no writes in /etc or application directories).
    fd = os.memfd_create('monitor-config', os.MFD_CLOEXEC)
    try:
        os.write(fd, raw)
        config = load_config(f'/proc/self/fd/{fd}')
    finally:
        os.close(fd)
    if len(config.jobs) > 256:
        raise ValueError('job limit')
    active = {j.id: j.schedule.interval_seconds for j in config.jobs if j.enabled and j.schedule}
    if any(not math.isfinite(i) or not 0 < i <= 31536000 for i in active.values()):
        raise ValueError('interval')
    return active


def worker(path, active, now):
    deadline = time.monotonic() + 2
    uri = Path(path).absolute().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
        db.execute('PRAGMA query_only = ON')
        db.execute('PRAGMA busy_timeout = 1000')
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 100)
        if db.execute('PRAGMA user_version').fetchone()[0] != 3:
            raise ValueError('schema')
        # Counts are bounded before reading job IDs; content columns never selected.
        if db.execute('SELECT count(*) FROM job_status').fetchone()[0] > 4096:
            raise ValueError('row limit')
        statuses = {}
        for identity, success, failure, count in db.execute(
                'SELECT job_id,last_success_at,last_failure_at,consecutive_failures FROM job_status'):
            if identity in active:
                times = [stamp(t, now) for t in (success, failure) if t is not None]
                statuses[identity] = (max(times) if times else None, integer(count))
        missing, overdue, repeated, ages = 0, 0, 0, []
        for identity, interval in active.items():
            terminal, failures = statuses.get(identity, (None, 0))
            repeated += int(failures >= 3)
            if terminal is None:
                missing += 1
                overdue += 1
            else:
                age = now - terminal
                ages.append(age)
                overdue += int(age > max(3 * interval, 600) + 300)
        result = dict(scheduled_jobs=len(active), missing_status_jobs=missing,
                      overdue_jobs=overdue, repeated_failure_jobs=repeated)
        if ages:
            result['oldest_terminal_attempt_age_seconds'] = max(ages)
        oldest = []
        for table, column, prefix in (
                ('notification_outbox', 'checked_at', 'notification'),
                ('operational_alert_outbox', 'created_at', 'operational')):
            # Bounded SELECT of only approved columns; no URLs/content/errors.
            # SQL aggregates avoid materializing an unbounded queue. Validate all
            # pending timestamps via a deterministic UDF with the same semantics.
            db.create_function('monitor_stamp', 1, lambda t: stamp(t, now))
            count, failed, first, invalid = db.execute(f'''
                SELECT count(*),sum(CASE WHEN attempts>0 THEN 1 ELSE 0 END),
                min(monitor_stamp({column})),
                sum(CASE WHEN typeof(attempts)!='integer' OR attempts<0 THEN 1 ELSE 0 END)
                FROM {table} WHERE delivered_at IS NULL''').fetchone()
            if invalid:
                raise ValueError('attempts')
            result[prefix + '_pending'] = count
            if prefix == 'notification':
                result['notification_failed_pending'] = failed or 0
            if first is not None:
                oldest.append(now - first)
        result['oldest_pending_age_seconds'] = max(oldest) if oldest else 0
        result['database_bytes'] = os.stat(path).st_size
        if time.monotonic() > deadline:
            raise ValueError('query deadline')
        return result


def backup(directory, now):
    directory = Path(directory)
    try:
        raw = bounded(directory / 'last-backup.json', 4096)
    except FileNotFoundError:
        return dict(backup_manifest_present=0, backup_manifest_valid=0)
    result = dict(backup_manifest_present=1, backup_manifest_valid=0)
    try:
        manifest = json.loads(raw)
        completed = stamp(manifest['completed_at'], now)
        size = integer(manifest['bytes'])
        path = Path(manifest['path'])
        if not re.fullmatch(r'web-checker-\d{8}T\d{6}Z\.db', path.name):
            raise ValueError('basename')
        # App writes absolute paths; a basename is also safe within /backups.
        if path != Path(path.name) and path != directory / path.name:
            raise ValueError('directory')
        path = directory / path.name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or size <= 0 or info.st_size != size:
            raise ValueError('backup file')
        result.update(backup_manifest_valid=1, backup_completed_timestamp_seconds=completed,
                      backup_bytes=size)
    except (ValueError, KeyError, TypeError, OSError):
        pass
    return result


def main():
    # Whole helper deadline also bounds config loading, file IO and imports.
    signal.signal(signal.SIGALRM, lambda *_: os._exit(1))
    signal.alarm(3)
    try:
        now = time.time()
        if sys.argv[1:] == ['worker']:
            result = worker('/data/web-checker.db', schedules('/etc/web-checker/jobs.yaml'), now)
        elif sys.argv[1:] == ['backup']:
            result = backup('/backups', now)
        else:
            return 1
        print(json.dumps(result, allow_nan=False))
        return 0
    except Exception:
        # Deliberately no exception, input or traceback output.
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
