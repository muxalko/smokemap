#!/usr/bin/env python3
"""Separate deployment pass. Source-only: no service actions, listeners or installs."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import os
from pathlib import Path
import signal
import stat
import time

from common import atomic_write, command, number, read_json, sample
from docker_metadata import snapshot, observe
from inventory import SERVICES, WEB, group
from probes import exec_probe, host_probe, local_probe, quick_origin, quick_state, supervisor_probe
from resources import parse_stats, STATS_FORMAT
from webchecker import aggregate, maintenance


def validate(config):
    if not isinstance(config, dict) or set(config) != {'version', 'quick_state_path', 'local_ca_path'} or type(config['version']) is not int or config['version'] != 1:
        raise ValueError('config')
    for key in ('quick_state_path', 'local_ca_path'):
        if not isinstance(config[key], str) or not Path(config[key]).is_absolute() or '\x00' in config[key]:
            raise ValueError('config path')
    return config


def collect(config):
    validate(config)  # Malformed configuration must leave the old file stale.
    start, now = time.monotonic(), time.time()
    output = sample('collector_timestamp_seconds', now)
    containers = {}
    running = []
    try:
        rows = snapshot()
    except Exception:
        rows = None
    for labels, project in SERVICES:
        output += sample('expected', 1, **labels)
        try:
            if rows is None:
                raise ValueError('snapshot unavailable')
            identity, values = observe(rows, project, labels['service'], now)
            info = values.pop('container_info', None)
            rendered = ''.join(sample(k, v, **labels) for k, v in values.items())
            if info:
                rendered += sample('container_info', 1, **labels, **info)
            output += rendered + sample('observation_success', 1, **labels)
            containers[(labels['deployment'], labels['service'])] = (identity, values['running'])
            if values['running']:
                running.append((identity, labels))
            else:
                output += sample('resource_success', 1, **labels)
        except Exception:
            output += sample('observation_success', 0, **labels)
            output += sample('resource_success', 0, **labels)

    tasks = []

    def add(kind, labels, function):
        tasks.append((kind, labels, function))

    def container(deployment, service):
        identity, is_running = containers.get((deployment, service), (None, None))
        if is_running is None:
            raise ValueError('container unknown')
        return identity, is_running

    def inside(deployment, service):
        identity, is_running = container(deployment, service)
        return exec_probe(identity, service == 'frontend') if is_running else 0

    def internal_signal(service, kind):
        identity, is_running = container('production', service)
        if not is_running:
            raise ValueError('signal unavailable')
        return maintenance(identity, now) if kind == 'maintenance_log' else aggregate(identity, kind)

    def public(which):
        state = quick_state(config['quick_state_path'], now)  # reloaded each pass/probe
        item = state['connectors']['quick-' + which]
        return host_probe(quick_origin(item['origin']), 443, '/' if which == 'app' else '/minio/health/ready', True)

    for service, port, path in (('frontend', 3000, '/'), ('backend', 8000, '/health/ready/')):
        add('probe', dict(**group('development'), probe=service + '_ready'),
            lambda port=port, path=path: host_probe('127.0.0.1', port, path))
    for deployment in ('quick', 'local'):
        for service in ('frontend', 'backend'):
            add('probe', dict(**group(deployment), probe=service + '_ready'),
                lambda d=deployment, s=service: inside(d, s))
    for which in ('app', 'media'):
        add('probe', dict(**group('quick'), probe='public_' + which), lambda w=which: public(w))
        add('probe', dict(**group('local'), probe='public_' + which),
            lambda w=which: local_probe(config['local_ca_path'], w == 'media'))
    add('probe', dict(**group('quick'), probe='supervisor'),
        lambda: supervisor_probe(quick_state(config['quick_state_path'], now)))
    for alias, service, kind in (('worker_status', 'checker', 'worker'), ('backup', 'maintenance', 'backup'),
                                 ('maintenance_log', 'maintenance', 'maintenance_log')):
        add('signal', dict(**WEB, signal=alias), lambda s=service, k=kind: internal_signal(s, k))

    def stats():
        if not running:
            return {}
        raw = command(['docker', 'stats', '--no-stream', '--no-trunc', '--format', STATS_FORMAT,
                       *[identity for identity, _ in running]], 4)
        result = parse_stats(raw)
        if result.keys() - {i for i, _ in running}:
            raise ValueError('unexpected stats')
        return result

    add('resources', {}, stats)
    # Four independent bounded operations at most. Per-exec IO deadlines plus
    # global alarm ensure a slow Docker daemon cannot produce a fresh partial pass.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): (kind, labels) for kind, labels, fn in tasks}
        for future in as_completed(futures):
            kind, labels = futures[future]
            try:
                result, success = future.result(), 1
            except Exception:
                result, success = None, 0
            if kind == 'resources':
                for identity, service_labels in running:
                    values = result.get(identity) if success else None
                    output += sample('resource_success', int(values is not None), **service_labels)
                    if values is not None:
                        output += ''.join(sample(k, v, **service_labels) for k, v in values.items())
            else:
                output += sample(kind + '_expected', 1, **labels)
                output += sample(kind + '_observation_success', success, **labels)
                output += sample(kind + '_success', (result if kind == 'probe' else 1) if success else 0, **labels)
                if success:
                    output += sample(kind + '_timestamp_seconds', now, **labels)
                    if kind == 'signal':
                        metric_labels = {k: v for k, v in labels.items() if k != 'signal'}
                        output += ''.join(sample(k, v, **metric_labels) for k, v in result.items())
    elapsed = time.monotonic() - start
    if elapsed >= 25:
        raise ValueError('global budget')
    output += sample('collector_duration_seconds', elapsed)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    # Systemd timeout is a second guard; this process alarm enforces <=25s even
    # on a manual invocation. No timeout publishes a partially fresh file.
    signal.signal(signal.SIGALRM, lambda *_: os._exit(1))
    signal.alarm(25)
    try:
        config = validate(read_json(args.config))
        if Path(args.output).name != 'deployments.prom':
            raise ValueError('owned output filename')
        parent = Path(args.output).parent
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('output directory')
        fd = os.open(parent / '.deployments.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            lock_info = os.fstat(fd)
            if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid() or stat.S_IMODE(lock_info.st_mode) != 0o600:
                raise ValueError('private lock')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            atomic_write(args.output, collect(config))
        return 0
    except Exception:
        print('deployment_collection_failed')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
