"""Shared bounded IO; existing monitoring collector is imported without changes."""
import importlib.util
import json
import math
from pathlib import Path
import re
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location('original_monitor', Path(__file__).parents[1] / 'collector.py')
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)
command = original.bounded_command
atomic_write = original.atomic_write


def read_json(path, limit=16384):
    with open(path, 'rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('bounded input')
    return json.loads(raw)


def number(value):
    if isinstance(value, bool):
        raise ValueError('boolean')
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError('number')
    return result


def timestamp(value, now, empty=False):
    if empty and (value is None or value.startswith('0001-')):
        return None
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('timezone')
    result = dt.timestamp()
    if not 0 < result <= now:
        raise ValueError('timestamp')
    return result


def sample(name, value, **labels):
    if not all(re.fullmatch(r'[a-zA-Z0-9_.:-]+', str(v)) for v in labels.values()):
        raise ValueError('unsafe label')
    return original.sample(name, number(value), **labels).replace('smokemap_', 'deployment_', 1)
