"""Only explicitly selected metadata fields ever cross the Docker CLI boundary."""
import json
import re
from common import command, number, timestamp

# No environment, commands, arbitrary label maps, health logs or full inspect.
FORMAT = ('[{{json .Id}},{{json .Name}},{{json (index .Config.Labels "com.docker.compose.project")}},'
          '{{json (index .Config.Labels "com.docker.compose.service")}},{{json .State.Running}},'
          '{{if .State.Health}}{{json .State.Health.Status}}{{else}}"none"{{end}},'
          '{{json .RestartCount}},{{json .Image}},'
          '{{json (index .Config.Labels "org.opencontainers.image.revision")}},'
          '{{json .Created}},{{json .State.StartedAt}}]')


def snapshot():
    ids = command(['docker', 'ps', '-aq', '--no-trunc'], 4).decode('ascii').split()
    if len(ids) > 256 or len(set(ids)) != len(ids) or any(not re.fullmatch('[a-f0-9]{64}', i) for i in ids):
        raise ValueError('inventory limit')
    if not ids:
        return []
    raw = command(['docker', 'inspect', '--format', FORMAT, *ids], 4)
    rows = [json.loads(line) for line in raw.splitlines()]
    if len(rows) != len(ids) or any(not isinstance(r, list) or len(r) != 11 for r in rows):
        raise ValueError('snapshot shape')
    if {r[0] for r in rows} != set(ids):
        raise ValueError('snapshot identity')
    return rows


def observe(rows, project, service, now):
    matches = [r for r in rows if r[2:4] == [project, service]]
    if not matches:
        return None, dict(present=0, running=0, state=0)
    if len(matches) != 1:
        raise ValueError('ambiguous service')
    identity, name, _, _, running, health, restarts, digest, revision, created, started = matches[0]
    if (not re.fullmatch('[a-f0-9]{64}', identity) or not isinstance(name, str)
            or type(running) is not bool or health not in ('none', 'healthy', 'unhealthy', 'starting')
            or type(restarts) is not int or restarts < 0
            or not re.fullmatch('sha256:[a-f0-9]{64}', digest)):
        raise ValueError('metadata')
    values = dict(present=1, running=int(running), health_configured=int(health != 'none'),
                  health=int(health == 'healthy'), restarts_total=number(restarts),
                  created_timestamp_seconds=timestamp(created, now),
                  state=0 if not running else (2 if health == 'none' else (3 if health == 'healthy' else 1)))
    start = timestamp(started, now, empty=True)
    if running and start is None:
        raise ValueError('missing start')
    if start is not None:
        values['started_timestamp_seconds'] = start
    values['container_info'] = dict(image_digest=digest,
        image_revision=revision if isinstance(revision, str) and re.fullmatch('[a-f0-9]{40}', revision) else 'unknown')
    return identity, values
