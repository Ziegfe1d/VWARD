#!/usr/bin/env python3
"""No data of the owner's own router in the repository.

VWARD learns addresses, tunnels and lists from the router it runs on; tests and
documentation use made-up values (RFC 5737 addresses, example.com). The owner's
values are listed here only as SHA-256 fingerprints, so this file does not
carry them either. Also refused: a WireGuard secret key that looks real and an
Amnezia vpn:// key.
"""
import base64
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# sha256 of lower-case tokens: the owner's tunnel servers and addresses, the names of his
# tunnels, his mail, numbers from his AmneziaWG files.
FINGERPRINTS = {
    "9a30b280bd0984187a9d2577d1bfa22468f7210fcc5dd0722ed0f356a2716428",
    "83632213179825af26d775d7d6f4bba73c63abc14712257c5fa1663bfc8c784b",
    "fd5baea27f2ef4ee235292b45f381b10f3c6fe4075ddd68ca3c3ebd75769c2ea",
    "2f3ff24109b8f972d0c41210ec773ab8ee9fb6534318d5161a195e44a087e87a",
    "8a860f00e1e4ca3bff08eaccae84e7d6e72c3c70a70fb8c96d956eb306995a23",
    "0d481ce165ec4313bcefd32222435b218ef1b18dd0982ed8a57ff0e31dab8a33",
    "5db717ebe9aead602e00129bce00fb77feddf85bf31dfb6441a8d487dd73ada7",
    "43f04c910835bce84cce7942b0514e412042a5384ffa50ba4f70fe9f1fb03968",
    "a41aa769998882c734b36015c47774682c4225cddb8539395b69e2745085f1e1",
    "073533189c8c554c66e7cf00a218a5ee67ad335a305fad063fb8eeb43ab2c421",
}
SECRET_KEY = re.compile(r"(?i)(private[-_ ]?key|preshared[-_ ]?key|header[-_ ]?protection[-_ ]?key)\s*[=:]?\s*\"?([A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=)")
VPN_KEY = re.compile(r"vpn://[A-Za-z0-9_-]{40,}")
TOKEN = re.compile(r"[A-Za-z0-9_.@-]+")


def fingerprints(token):
    t = token.lower().strip(".-_")
    parts = {t} | set(re.split(r"[_@-]", t)) | set(t.split("."))
    return {hashlib.sha256(p.encode()).hexdigest() for p in parts if p}


def looks_real(key):
    # Made-up keys in tests repeat a few characters; a real one is 32 random bytes.
    b = base64.b64decode(key)
    return len(b) == 32 and len(set(b)) >= 20


def main():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.split()
    bad = []
    for name in files:
        if name.startswith("updates/") or name.endswith(("go.sum", ".png", ".gz", ".pem")):
            continue
        p = ROOT / name
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for tok in TOKEN.findall(line):
                if fingerprints(tok) & FINGERPRINTS:
                    bad.append(f"{name}:{n}: the owner's own value")
                    break
            m = SECRET_KEY.search(line)
            if m and looks_real(m.group(2)):
                bad.append(f"{name}:{n}: a real-looking tunnel secret key")
            if VPN_KEY.search(line):
                bad.append(f"{name}:{n}: an Amnezia vpn:// key")
    if bad:
        print("\n".join(bad))
        sys.exit("NO_PERSONAL_DATA=FAIL")
    print("NO_PERSONAL_DATA=PASS")


if __name__ == "__main__":
    main()
