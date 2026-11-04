"""An RFC 8484 response for offline writer tests, validated by the real probe."""
from pathlib import Path


def responder(tmp, env):
    curl = Path(tmp) / 'doh-curl'
    curl.write_text('''#!/usr/bin/env python3
import sys
from pathlib import Path
sys.stdin.read()
Path(sys.argv[sys.argv.index('-o')+1]).write_bytes(bytes.fromhex(
    '000081800001000100000000076578616d706c6503636f6d0000010001c00c000100010000012c00045db8d822'))
print('200', end='')
''')
    curl.chmod(0o755)
    env.update(VWARD_CURL_BIN=str(curl), VWARD_DOH_ALIVE='1', VWARD_DOH_ALIVE_DIR=str(Path(tmp) / 'doh-cache'),
               VWARD_TLS_BROKEN_FLAG=str(Path(tmp) / 'no-tls-failure'))
