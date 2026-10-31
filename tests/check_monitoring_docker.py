"""CI-only real Docker template probe; never used by the deployment collector."""
import re
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'monitoring/deployments'))
from docker_metadata import snapshot

def main():
    image = sys.argv[1]
    if not re.fullmatch(r'cloudflare/cloudflared(?::[a-zA-Z0-9_.-]+)?@sha256:[a-f0-9]{64}', image):
        raise ValueError('Expected the existing pinned official CLI image')
    identity = subprocess.check_output(['docker', 'create', '--network', 'none',
        '--read-only', '--user', '65532:65532', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true', '--no-healthcheck',
        image, 'version'], stderr=subprocess.DEVNULL, timeout=10).decode().strip()
    if not re.fullmatch(r'[a-f0-9]{64}', identity):
        raise ValueError('Unexpected created identity')
    try:
        rows = snapshot()
        own = [row for row in rows if row[0] == identity]
        if len(own) != 1 or own[0][4] is not False or own[0][5] != 'none':
            raise ValueError('Stopped container without healthcheck must be readable')
        print('Actual Docker no-health metadata probe passed')
    finally:
        subprocess.run(['docker', 'rm', '--', identity], check=True, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == '__main__':
    main()
