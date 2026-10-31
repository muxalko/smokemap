"""Bounded curl adapter: network failure is observed DOWN, execution error UNKNOWN."""
import os
import signal
import subprocess
import sys


def main():
    signal.signal(signal.SIGALRM, lambda *_: os._exit(1))
    signal.alarm(3)
    ca, host, path = sys.argv[1:]
    if host not in ('app.local-staging.smokemap.internal', 'media.local-staging.smokemap.internal'):
        return 1
    if path not in ('/', '/minio/health/ready') or not os.path.isfile(ca):
        return 1
    # communicate is bounded here: curl's only output is a fixed three-digit code.
    result = subprocess.run(['curl', '--disable', '--silent', '--noproxy', '*',
        '--resolve', f'{host}:8443:127.0.0.1', '--cacert', ca, '--output', '/dev/null',
        '--write-out', '%{http_code}', '--max-time', '2.5', '--max-redirs', '0',
        f'https://{host}:8443{path}'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2.8)
    if result.returncode not in (0, 5, 6, 7, 28, 35, 51, 52, 55, 56, 60):
        return 1
    if len(result.stdout) != 3 or not result.stdout.isdigit():
        return 1
    print(int(result.returncode == 0 and result.stdout == b'200'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit(1)
