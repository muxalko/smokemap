"""Host adapters for numeric-only internal aggregates and anchored event logs."""
import json
from pathlib import Path
import re
from common import command, number, timestamp

WORKER_KEYS = {'scheduled_jobs', 'missing_status_jobs', 'overdue_jobs', 'repeated_failure_jobs',
    'notification_pending', 'notification_failed_pending', 'oldest_pending_age_seconds',
    'operational_pending', 'database_bytes'}
BACKUP_KEYS = {'backup_manifest_present', 'backup_manifest_valid'}


def aggregate(identity, kind):
    helper = Path(__file__).with_name('webchecker_helper.py').read_text()
    values = json.loads(command(['docker', 'exec', identity, 'python', '-c', helper, kind], 4))
    required = WORKER_KEYS if kind == 'worker' else BACKUP_KEYS
    optional = {'oldest_terminal_attempt_age_seconds'} if kind == 'worker' else {'backup_completed_timestamp_seconds', 'backup_bytes'}
    if not isinstance(values, dict) or not required <= values.keys() or values.keys() - required - optional:
        raise ValueError('aggregate shape')
    return {k: number(v) for k, v in values.items()}


def maintenance_logs(raw, now):
    events = []
    for line in raw.decode('utf-8').splitlines():
        # Ignore all other output. Never expose any original text. Docker prefix
        # plus exact app event prefix; optional failed details are discarded.
        match = re.fullmatch(r'(\S+) maintenance event=(completed|failed)(?: .*)?', line)
        if match:
            events.append((timestamp(match[1], now), match[2]))
    successes = [t for t, kind in events if kind == 'completed']
    if not successes:
        return {'maintenance_completion_present': 0}
    last = max(successes)
    return dict(maintenance_completion_present=1, maintenance_last_completed_timestamp_seconds=last,
                maintenance_failures_after_success=sum(t > last and kind == 'failed' for t, kind in events))


def maintenance(identity, now):
    raw = command(['docker', 'logs', '--timestamps', '--since', '48h', '--tail', '200', identity], 4)
    return maintenance_logs(raw, now)
