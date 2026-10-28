# Development cleanup health email alerts

Root issue #132 adds an **opt-in, host-side, DEVELOPMENT-only** email monitor
for the `media-cleanup` worker described in
[development cleanup supervision](DEV_MEDIA_CLEANUP.md) (root #130). It is a
single Python-stdlib script, `scripts/dev-cleanup-alert.py`, plus systemd user
unit templates in `deploy/development/cleanup-alert/`.

Nothing in this repository installs, enables or schedules it: not Compose,
not a Make target and not CI. There is no monitor container. The cleanup
runner, its healthcheck, application source, submodule pointers and the
staging, local-staging and Quick contracts are unchanged. This is not a
staging or production alerting design.

## What it observes

Each run issues exactly two read-only Docker CLI queries and never starts,
stops, restarts, recreates or `exec`s into anything:

1. `docker ps --all --no-trunc --quiet` filtered by the labels
   `com.docker.compose.project=<CLEANUP_ALERT_COMPOSE_PROJECT>`,
   `com.docker.compose.service=media-cleanup` and
   `com.docker.compose.oneoff=False`.
2. `docker inspect --type container` with a fixed template that extracts only
   `.State.Status`, `.State.Health.Status` and `.RestartCount`.

Container environment, labels, logs and `.State.Health.Log` are never read.
Docker stderr is discarded; stdout is limited to 4 KiB, must be ASCII and is
parsed strictly (exact keys, no duplicates, no NaN). Docker `healthy` means the
runner's own progress probe passed, i.e. a real successful cleanup batch is
still fresh; the monitor adds no second health definition.

| Reason | Meaning |
| --- | --- |
| `healthy` | Docker reports the progress healthcheck as healthy |
| `starting` | Healthcheck still starting; no successful batch yet |
| `unhealthy` | Docker reports the progress healthcheck as unhealthy |
| `restarting` | The container is restarting because the runner exited |
| `not_running` | The container exists but is created, paused, exited, dead or being removed |
| `no_healthcheck` | The running container has no Docker healthcheck |
| `missing` | No `media-cleanup` container exists for the configured project |
| `ambiguous` | More than one matching container exists |
| `probe_failed` | The Docker CLI failed (daemon unreachable, permission, container vanished) |
| `probe_timeout` | A Docker query exceeded `CLEANUP_ALERT_DOCKER_TIMEOUT_SECONDS` |
| `probe_invalid` | Docker returned unexpected, oversized or malformed output |

Every reason other than `healthy` is a non-healthy check. A monitor that
cannot see the worker therefore alerts instead of staying silent.

## Notification rules

| Mail | Sent when |
| --- | --- |
| `ALERT: <reason>` | `CLEANUP_ALERT_FAILURE_THRESHOLD` consecutive non-healthy checks and no alert yet for this incident |
| `STILL FAILING: <reason>` | Still non-healthy `CLEANUP_ALERT_REPEAT_SECONDS` after the last delivered alert/reminder (`0` disables reminders) |
| `RECOVERED: healthy` | First healthy check after a delivered alert |
| `TEST` | Only on an explicit `send-test`; it does not query Docker |

A healthy check before the threshold ends the incident silently. The reason
may change during an incident; mail reports the latest reason, the first
observation time, the consecutive count and the restart count. A recurrence
before a recovery mail was delivered continues the announced incident.

Delivery is at-least-once toward the operator. A failed delivery is not
recorded as sent, so the next run retries it and the unit run fails (exit
`75`). Partial recipient refusal also remains pending and retries the whole
message on the next run. Recipients that already accepted it can see a duplicate
until every destination accepts; an alert or recovery is suppressed only after
full acceptance. SMTP acceptance confirms relay handoff, not inbox delivery.
Reminder timing uses the
wall clock; if the clock moves backwards, a reminder is sent early rather
than late.

With the template timer (every 5 minutes, 30-second accuracy) and the default
threshold of 2, the first alert arrives roughly 5–10 minutes after the first
non-healthy observation, on top of Docker's own detection delay (the cleanup
interval plus its 15-second scheduling allowance and the 5-second probe
period). The default threshold also keeps a normal worker start quiet: one
timer period (300 s) exceeds the default `MEDIA_CLEANUP_HEALTH_START_PERIOD`
(250 s). If you raise the start period above `(threshold - 1) × timer period`,
raise the threshold too, or startup can alert as `starting`.

Mail is fixed text: environment, sanitized host name, Compose project,
service, reason codes with fixed descriptions, UTC timestamps, numbers and the
read-only operator commands from the supervision document. It never contains
Docker output, logs, environment values, SMTP errors or credentials.

## Configuration

Settings come from environment variables, normally a private systemd
`EnvironmentFile`. Copy
`deploy/development/cleanup-alert/dev-cleanup-alert.env.example`; it lists
every key. Any value containing `REPLACE_ME`, a control character (including
CR/LF) or more than 1024 characters is rejected, so the template cannot run
until it is completed. Invalid configuration exits `64` and names only the
offending key.

| Key | Default | Rule |
| --- | --- | --- |
| `CLEANUP_ALERT_COMPOSE_PROJECT` | required | Compose project of the active DEVELOPMENT release (`[a-z0-9][a-z0-9_-]{0,62}`) |
| `CLEANUP_ALERT_DOCKER` | `/usr/bin/docker` | Absolute Docker CLI path |
| `CLEANUP_ALERT_DOCKER_TIMEOUT_SECONDS` | `15` | `1..300` per query |
| `CLEANUP_ALERT_SMTP_HOST` | required | Host name or IPv4 address (`::1` for IPv6 loopback) |
| `CLEANUP_ALERT_SMTP_PORT` | `587` | `1..65535` |
| `CLEANUP_ALERT_SMTP_SECURITY` | `starttls` | `starttls`, `tls` (implicit, usually port 465) or `none` |
| `CLEANUP_ALERT_SMTP_TIMEOUT_SECONDS` | `20` | `1..300` per SMTP socket operation |
| `CLEANUP_ALERT_SMTP_USERNAME` | empty | Optional; printable ASCII without spaces |
| `CLEANUP_ALERT_SMTP_PASSWORD_FILE` | empty | Required with a username unless systemd provides `$CREDENTIALS_DIRECTORY/smtp-password`; forbidden without one |
| `CLEANUP_ALERT_FROM` | required | One plain address, no display name |
| `CLEANUP_ALERT_TO` | required | 1–10 comma-separated distinct plain addresses |
| `CLEANUP_ALERT_FAILURE_THRESHOLD` | `2` | `1..100` consecutive non-healthy checks |
| `CLEANUP_ALERT_REPEAT_SECONDS` | `21600` | `0` (off) or `60..2592000` |
| `CLEANUP_ALERT_STATE_DIRECTORY` | systemd `STATE_DIRECTORY` | One absolute directory; set only for manual runs |

Integers are ASCII decimal without signs or whitespace. `starttls` and `tls`
verify the server certificate and host name against the system trust store;
STARTTLS must succeed before any credential is sent. `none` is accepted only
for `localhost`, `127.0.0.1` or `::1` and never with credentials.

The SMTP relay, sender and recipients for DEVELOPMENT are intentionally not
decided by this change; the template carries placeholders for them.

### Credentials

Never put a password in the environment file or the unit. Store it in its own
file owned by the service user, with no group or other permissions (for
example `0600` or `0400`), no symlink, at most 4 KiB, one line; a single
trailing newline is ignored. Each run reads it into memory only and fails
with `credential_unavailable` (exit `64`) before querying Docker if it is
unusable. Alternatively, uncomment the template's
`LoadCredential=smtp-password:...` line, leave
`CLEANUP_ALERT_SMTP_PASSWORD_FILE` empty and the monitor uses
`$CREDENTIALS_DIRECTORY/smtp-password`. Credentials in user units depend on
the host's systemd version; if `LoadCredential=` is unsupported, use the
password-file setting.

## Install on the DEVELOPMENT host

Prerequisites: a systemd user manager, `python3` 3.9 or newer (tested with
3.12), an operator account that can already run `docker` (Docker access is
root-equivalent; the monitor itself only reads), and decided SMTP details.
Install from the reviewed, frozen release checkout, never from a mutable
working tree, and copy the script so later checkouts cannot change it:

```sh
install -D -m 0755 scripts/dev-cleanup-alert.py \
  ~/.local/libexec/smokemap/dev-cleanup-alert.py
install -D -m 0600 deploy/development/cleanup-alert/dev-cleanup-alert.env.example \
  ~/.config/smokemap/dev-cleanup-alert.env
install -D -m 0644 -t ~/.config/systemd/user \
  deploy/development/cleanup-alert/smokemap-dev-cleanup-alert.service \
  deploy/development/cleanup-alert/smokemap-dev-cleanup-alert.timer
```

Edit `~/.config/smokemap/dev-cleanup-alert.env` and replace every
`REPLACE_ME`. Find the project name with `docker compose ls`. If the relay
needs authentication, create the password file with an editor (not `echo`,
which records shell history):

```sh
install -m 0600 /dev/null ~/.config/smokemap/dev-cleanup-alert.smtp-password
"${EDITOR:-vi}" ~/.config/smokemap/dev-cleanup-alert.smtp-password
```

Then verify in increasing order of effect. The first command is offline; the
second performs only the two read-only Docker queries and writes nothing; the
third sends one real `TEST` mail and should be run deliberately:

```sh
alert() (
  set -a; . ~/.config/smokemap/dev-cleanup-alert.env; set +a
  CLEANUP_ALERT_STATE_DIRECTORY="$HOME/.local/state/smokemap-dev-cleanup-alert" \
    python3 -I ~/.local/libexec/smokemap/dev-cleanup-alert.py "$@"
)
alert validate
alert preview
alert send-test
```

`preview` prints the next decision and, when a mail would be due, the full
message; it never locks, writes state or sends. Enable the timer only after
the test mail arrives:

```sh
systemctl --user daemon-reload
systemctl --user enable --now smokemap-dev-cleanup-alert.timer
systemctl --user list-timers smokemap-dev-cleanup-alert.timer
journalctl --user -u smokemap-dev-cleanup-alert.service -n 50
```

A user timer runs only while the user manager runs. For checks while the
operator is logged out, an administrator must enable lingering
(`loginctl enable-linger <user>`); that is a host-level change requiring its
own approval.

## Operating it

- **Planned maintenance or release switch:** stop the timer first
  (`systemctl --user stop smokemap-dev-cleanup-alert.timer`), otherwise a
  stopped or recreated worker alerts as `missing`, `not_running` or `starting`.
  Update `CLEANUP_ALERT_COMPOSE_PROJECT` if the new release uses another
  project name, run `preview`, then start the timer again.
- **Script update:** reinstall the reviewed copy from the new frozen release
  checkout and run `validate`/`preview` before relying on it.
- **Removal:** `systemctl --user disable --now smokemap-dev-cleanup-alert.timer`,
  delete the two unit files, the environment and password files, and
  `~/.local/state/smokemap-dev-cleanup-alert`.

Each run prints one-line JSON events (`event`, `outcome`, `reason`,
`timestamp`, and only numeric `streak`, a `kind` or a config `key`) to the
journal:

| Event | Outcome | Reason |
| --- | --- | --- |
| `config` | `failure` | `config_invalid` (with `key`), `credential_unavailable` |
| `config` | `valid` | `ok` (from `validate`) |
| `check` | `healthy` / `problem` | observed reason, with `streak` |
| `check` | `skipped` | `busy` (another run holds the lock) |
| `notify` | `sent` | `alert`, `reminder`, `recovery`, `test` |
| `notify` | `failure` | `smtp_connect`, `smtp_tls`, `smtp_auth`, `smtp_send`, `smtp_partial` (with `kind`) |
| `preview` | `alert` / `reminder` / `recovery` / `none` | observed reason |
| `state` | `reset` | `state_invalid` |
| `state` | `failure` | `state_error` |
| `monitor` | `failure` | `internal_error` |

| Exit | Meaning |
| --- | --- |
| `0` | Check completed, including any due mail delivered |
| `64` | Usage, configuration or credential problem |
| `70` | Unexpected internal error (no traceback is printed) |
| `74` | Unsafe or unusable state directory or file |
| `75` | Delivery failed or partially refused, or another run was active |

## Private state

The state directory (systemd user `StateDirectory=`, normally
`~/.local/state/smokemap-dev-cleanup-alert`) must be owned by the service
user with mode `0700`. It holds a `lock` file (non-blocking `flock`, so
overlapping runs skip with `busy`) and `state.json`, a `0600` single-link
regular file written through an exclusive random staging file, `fsync` and
atomic replacement. It contains only `version`, `streak`, `reason`, `since`,
`alerted_at`, `recovery_pending` and `checked_at`. A symlink, wrong owner,
wrong mode, extra hard link or non-regular file stops the run with
`state_error` (exit `74`) before Docker is queried. Malformed content in a
safely owned file (bad JSON, duplicate keys, NaN, unknown fields or values,
inconsistent incident fields, more than 4 KiB) is reset with a `state_invalid`
event. A reset forgets a delivered alert, so the incident is alerted again
after the threshold and its recovery is reported only for the new alert.

## Verification

`make test-dev-cleanup-alert` runs Python-stdlib tests with a fake Docker CLI
and a fake SMTP client in disposable private temp directories. Sockets, DNS
and the real SMTP classes are patched to fail any network attempt; command-
line tests point SMTP at a closed loopback port and never send. They cover
configuration bounds, placeholders and header injection, credential-file
safety, every Docker state and malformed probe output, read-only query
arguments and environment isolation, threshold/reminder/recovery transitions,
delivery retry and partial refusal, clock rewind, private atomic state,
locking, unsafe and malformed state, verified STARTTLS/TLS ordering, redaction
of untrusted text and the password, the example settings and the unit
templates. The suite is part of `make test` and the required root
`integration` CI job; it needs no Docker, database, storage or mail relay.

## Limitations

- This change provides source, tests and templates only. It has not been
  installed, enabled or run on the DEVELOPMENT host, and no mail has been
  delivered through a real relay. The relay, sender and recipients are still
  undecided placeholders.
- The unit files are checked structurally by the tests, not with
  `systemd-analyze verify` on the target host.
- There is no dead-man's switch. If the host, user manager, timer, Docker CLI
  or relay is down, or the run fails before delivery, the result is silence or
  a failed unit visible only in `systemctl --user` and the journal. Absence of
  mail does not prove health; periodic `send-test` or an external heartbeat
  would be separate work.
- It watches only Docker health of one Compose project's `media-cleanup`
  service, not the backend, frontend, database, storage or cleanup policy.
- It is development tooling. Staging, local-staging, Quick and production
  alerting remain separate decisions.
