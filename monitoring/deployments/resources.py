"""Strict Docker-reported percentages and SI/IEC memory; CPU may exceed 100%."""
import json
import re
from common import number


def percent(text):
    if not isinstance(text, str) or not re.fullmatch(r'\d+(?:\.\d+)?%', text):
        raise ValueError('percent')
    return number(text[:-1])


def memory(text):
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(B|[kKMGTPE]B|[KMGTPE]iB)', text.strip())
    if not match:
        raise ValueError('memory')
    value, unit = match.groups()
    power = 'BKMGTPE'.index(unit[0].upper()) if unit != 'B' else 0
    return number(number(value) * (1024 if 'i' in unit else 1000) ** power)


def parse_stats(raw):
    result = {}
    for line in raw.decode('ascii').splitlines():
        identity, cpu, mem, mem_percent, pids = json.loads(line)
        if not re.fullmatch(r'[a-f0-9]{64}', identity) or identity in result:
            raise ValueError('stats identity')
        used, limit = mem.split('/')
        values = dict(cpu_percent=percent(cpu), memory_usage_bytes=memory(used),
                      memory_limit_bytes=memory(limit), memory_percent=percent(mem_percent))
        if values['memory_percent'] > 100 or values['memory_usage_bytes'] > values['memory_limit_bytes']:
            raise ValueError('memory range')
        if not re.fullmatch(r'\d{1,12}', pids):
            raise ValueError('pids')
        values['pids'] = int(pids)
        result[identity] = values
    return result


STATS_FORMAT = '[{{json .ID}},{{json .CPUPerc}},{{json .MemUsage}},{{json .MemPerc}},{{json .PIDs}}]'
