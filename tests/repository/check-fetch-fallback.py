#!/usr/bin/env python3
"""vward_fetch: a download when Entware's curl crashes on HTTPS (its OpenSSL 3.5.5 on some MIPS
routers): uclient-fetch takes the same curl options, curl is not asked again within the hour,
the server's status, --fail, --max-filesize and --retry mean what they mean for curl."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-device-profile.sh"


def fail(message: str) -> None:
    raise SystemExit(f"FETCH_FALLBACK=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "curl").write_text(f'#!/bin/sh\necho "$*" >> "{t}/curl.log"\nexit "${{CURL_RC:-132}}"\n')
    # uclient-fetch: the answer of the «server» from UC_MODE (ok: a body, 404, down: no answer).
    (t / "uclient-fetch").write_text(f'''#!/bin/sh
echo "$*" >> "{t}/uc.log"
out=-
while [ $# -gt 0 ]; do [ "$1" = -O ] && out=$2; shift; done
case "$UC_MODE" in
    ok) if [ "$out" = - ]; then printf 'BODY'; else printf 'BODY' > "$out"; fi; exit 0 ;;
    big) printf '0123456789' > "$out"; exit 0 ;;
    404) echo "HTTP error 404" >&2; exit 8 ;;
    down) echo "Connection error: Connection refused" >&2; exit 4 ;;
esac
''')
    for f in ("curl", "uclient-fetch"):
        (t / f).chmod(0o755)
    flag = t / "tls.broken"
    base = {"PATH": os.environ["PATH"], "VWARD_CURL_BIN": str(t / "curl"), "VWARD_UCLIENT_BIN": str(t / "uclient-fetch"),
            "VWARD_TLS_BROKEN_FLAG": str(flag), "VWARD_CA_BUNDLE": str(t / "ca.crt"), "TMPDIR": tmp}
    (t / "ca.crt").write_text("x")

    def fetch(args: str, **env: str) -> tuple[int, str]:
        r = subprocess.run(["sh", "-c", f'. "{LIB}"; vward_fetch {args}'], env={**base, **env}, text=True,
                           capture_output=True, timeout=30)
        return r.returncode, r.stdout

    def log(name: str) -> list[str]:
        p = t / f"{name}.log"
        return p.read_text().splitlines() if p.exists() else []

    url = "https://example.invalid/feed.json"
    rc, out = fetch(f"--fail --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 180 "
                    f"--retry 3 --max-filesize 100 --output {t}/a.json --write-out '%{{http_code}}' {url}", UC_MODE="ok")
    if rc != 0 or out != "200" or (t / "a.json").read_text() != "BODY":
        fail(f"a crashed curl is not replaced: rc={rc} out={out!r}")
    if not flag.exists() or len(log("curl")) != 1:
        fail("the crash is not remembered")
    uc = log("uc")[-1]
    if f"-O {t}/a.json" not in uc or "-T 180" not in uc or f"--ca-certificate {t}/ca.crt" not in uc or not uc.endswith(url):
        fail(f"uclient-fetch is not asked the same request: {uc}")

    # Within the hour curl is not asked again.
    rc, out = fetch(f"-fsSL -A 'Mozilla/5.0 (X11)' {url}", UC_MODE="ok")
    if rc != 0 or out != "BODY" or len(log("curl")) != 1 or "-U Mozilla/5.0 (X11)" not in log("uc")[-1]:
        fail(f"curl asked again within the hour, or the body/agent lost: rc={rc} out={out!r}")

    rc, out = fetch(f"--fail -o {t}/b -w '%{{http_code}}' {url}", UC_MODE="404")
    if rc != 22 or out != "404":
        fail(f"--fail with 404: rc={rc} out={out!r}")
    rc, out = fetch(f"-s -o {t}/b -w '%{{http_code}}\\n' {url}", UC_MODE="404")
    if rc != 0 or out != "404\n":
        fail(f"without --fail a 404 is an answer: rc={rc} out={out!r}")

    n = len(log("uc"))
    rc, out = fetch(f"--retry 2 -o {t}/c -w '%{{http_code}}' {url}", UC_MODE="down")
    if rc != 7 or out != "000" or len(log("uc")) - n != 3:
        fail(f"no answer: curl's 7, 000 and the retries: rc={rc} out={out!r} tries={len(log('uc')) - n}")

    rc, _ = fetch(f"--max-filesize 5 -o {t}/d {url}", UC_MODE="big")
    if rc != 63 or (t / "d").exists():
        fail(f"--max-filesize: rc={rc}")

    # Options it cannot honour: «not supported», never a request without them.
    n = len(log("uc"))
    for args in (f"--resolve example.invalid:443:192.0.2.1 {url}", f"-X POST {url}", f"-sSo {t}/e {url}"):
        rc, _ = fetch(args, UC_MODE="ok")
        if rc != 2:
            fail(f"{args}: rc={rc}")
    if len(log("uc")) != n:
        fail("an unsupported request reached uclient-fetch")

    # A curl that works is used as it is: its error stays its error.
    flag.unlink()
    rc, _ = fetch(f"--fail {url}", CURL_RC="22", UC_MODE="ok")
    if rc != 22 or flag.exists() or len(log("uc")) != n:
        fail("a working curl's answer went to uclient-fetch")

    r = subprocess.run(["sh", "-c", f'. "{LIB}"; vward_https_broken'], env=base)
    if r.returncode == 0:
        fail("vward_https_broken without a crash")
    flag.write_text("")
    r = subprocess.run(["sh", "-c", f'. "{LIB}"; vward_https_broken'], env=base)
    if r.returncode != 0:
        fail("vward_https_broken after a crash")

print("FETCH_FALLBACK=PASS")
