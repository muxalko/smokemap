"""Fixed aliases/endpoints; no bodies, redirects, environment proxies or TLS bypass."""
import http.client
import json
import os
from pathlib import Path
import re
import ssl
from urllib.parse import urlsplit
from common import command, read_json, timestamp

NODE = """const http=require('http');
let finished=false;
function done(v){if(finished)return;finished=true;clearTimeout(deadline);
process.stdout.write(String(v)+'\\n',()=>process.exit(0));}
const deadline=setTimeout(()=>done(0),3000);
const r=http.get('http://127.0.0.1:3000/',{timeout:2500},s=>{
done(s.statusCode===200?1:0);s.destroy();});
r.on('timeout',()=>{done(0);r.destroy();});
r.on('error',()=>done(0));"""
PYTHON = """import http.client,signal,sys
signal.signal(signal.SIGALRM,lambda *_:sys.exit(1));signal.alarm(3)
try:
 c=http.client.HTTPConnection('127.0.0.1',8000,timeout=2.5)
 c.request('GET','/health/ready/');r=c.getresponse();print(int(r.status==200));c.close()
except (OSError,http.client.HTTPException): print(0)
"""


def http_probe(host, port, path, tls=False):
    cls = http.client.HTTPSConnection if tls else http.client.HTTPConnection
    try:
        connection = cls(host, port, timeout=3, **({'context': ssl.create_default_context()} if tls else {}))
        try:
            connection.request('GET', path)
            return int(connection.getresponse().status == 200)
        finally:
            connection.close()
    except (OSError, http.client.HTTPException):
        return 0


def exec_probe(identity, frontend):
    args = ['node', '-e', NODE] if frontend else ['python', '-c', PYTHON]
    raw = command(['docker', 'exec', identity, *args], 4).strip()
    if raw not in (b'0', b'1'):
        raise ValueError('probe output')
    return int(raw)


def quick_origin(value):
    if not isinstance(value, str) or not re.fullmatch(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com', value):
        raise ValueError('origin')
    return urlsplit(value).hostname


def quick_state(path, now):
    state = read_json(path)
    for key in ('quick-app', 'quick-media'):
        item = state['connectors'][key]
        quick_origin(item['origin'])
        if (not isinstance(item['id'], str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,128}', item['id'])
                or type(item['pid']) is not int or item['pid'] <= 0
                or type(item['restart_count']) is not int or item['restart_count'] < 0):
            raise ValueError('connector')
        timestamp(item['started_at'], now)
    supervisor = state.get('supervisor')
    if supervisor is not None:
        if (type(supervisor['pid']) is not int or supervisor['pid'] <= 0
                or not re.fullmatch(r'\d{1,24}', str(supervisor['proc_start']))):
            raise ValueError('supervisor')
        timestamp(supervisor['started_at'], now)
    return state


def supervisor_probe(state, proc=Path('/proc')):
    supervisor = state.get('supervisor')
    if not supervisor:
        return 0
    try:
        # comm may contain spaces and parentheses; fields after final ')' start
        # with field 3. starttime is field 22, index 19 in this suffix.
        with open(proc / str(supervisor['pid']) / 'stat') as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError('stat limit')
        fields = raw.rsplit(')', 1)[1].split()
        if len(fields) < 20 or not fields[19].isdigit():
            raise ValueError('stat parse')
        return int(fields[0] != 'Z' and fields[19] == str(supervisor['proc_start']))
    except FileNotFoundError:
        return 0


def local_probe(ca, media):
    host = ('media' if media else 'app') + '.local-staging.smokemap.internal'
    path = '/minio/health/ready' if media else '/'
    # curl errors 5/6/7/28/35/51/52/56/60 are valid network/TLS failure
    # observations; retain a numeric status even for those exit codes. Execution
    # errors and malformed output remain UNKNOWN. No environment proxy.
    script = Path(__file__).with_name('curl_probe.py')
    raw = command([os.sys.executable, str(script), ca, host, path], 4).strip()
    if raw not in (b'0', b'1'):
        raise ValueError('curl output')
    return int(raw)


def host_probe(host, port, path, tls=False):
    # DNS also runs under an internal process alarm, rather than relying only on
    # socket timeout (which does not bound getaddrinfo).
    raw = command([os.sys.executable, str(Path(__file__)), host, str(port), path, str(int(tls))], 4).strip()
    if raw not in (b'0', b'1'):
        raise ValueError('HTTP output')
    return int(raw)


if __name__ == '__main__':
    import signal
    signal.signal(signal.SIGALRM, lambda *_: (os.write(1, b'0\n'), os._exit(0)))
    signal.alarm(3)
    print(http_probe(os.sys.argv[1], int(os.sys.argv[2]), os.sys.argv[3], os.sys.argv[4] == '1'))
