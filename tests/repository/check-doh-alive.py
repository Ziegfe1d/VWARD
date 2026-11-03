#!/usr/bin/env python3
"""fix.35.4: «Smart DNS отвечает» needs a whole DNS answer, not HTTP 200.

03.11.2026: the expired Smart DNS server with 35 domains read «отвечает». vward_doh_alive sent the
body to /dev/null and took HTTP 200 for success, whatever curl's exit code (a run out of time with
200 still «answers»). Now: curl ended well, HTTP 200, our id 0, the answer bit, RCODE 0, at least one
record; the reason is kept (VWARD_DOH_ALIVE_WHY). Without cksum the cache key was empty and the
answer was written over the cache folder; now another checksum, or no cache. No network.
"""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-device-profile.sh"
URL = "https://doh.example/dns-query/synthetic-token"


def fail(msg):
    raise SystemExit("DOH_ALIVE=FAIL: " + msg)


HEAD = "0000818000010001"  # id 0, QR+RD+RA, RCODE 0, 1 question, 1 answer
GOOD = HEAD + "00000000" + "076578616d706c6503636f6d0000010001" + "c00c000100010000012c00045db8d822"
CASES = {
    "ok": ("200", GOOD, 0, 0, "dns:ok"),
    "empty-body": ("200", "", 0, 1, "dns:short"),
    "timeout-after-200": ("200", GOOD, 28, 1, "curl:28"),
    "refused": ("200", "0000818500010000" + "00000000", 0, 1, "dns:rcode5"),
    "servfail": ("200", "0000818200010000" + "00000000", 0, 1, "dns:rcode2"),
    "no-records": ("200", "0000818000010000" + "00000000", 0, 1, "dns:empty"),
    "not-dns": ("200", "3c68746d6c3e3c626f64793e", 0, 1, "dns:invalid"),
    "http-403": ("403", GOOD, 0, 1, "http:403"),
}

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    curl = tmp / "curl"
    # The fake writes the case's body to -o and prints the code; the address comes on stdin only.
    curl.write_text("#!/bin/sh\nout=\nwhile [ $# -gt 0 ]; do [ \"$1\" != -o ] || out=$2; shift; done\n"
                    "cat > " + str(tmp / "stdin") + "\n"
                    "cat " + str(tmp / "body.bin") + " > \"$out\"\n"
                    "printf '%s' \"$(cat " + str(tmp / "code") + ")\"\nexit \"$(cat " + str(tmp / "rc") + ")\"\n")
    curl.chmod(0o755)

    def setbody(h):
        (tmp / "body.bin").write_bytes(bytes.fromhex(h))

    def probe(path=None, fresh="1"):
        env = os.environ | {"VWARD_CURL_BIN": str(curl), "VWARD_DOH_ALIVE_DIR": str(tmp / "cache"),
                            "VWARD_DOH_ALIVE_FRESH": fresh, "VWARD_TLS_BROKEN_FLAG": str(tmp / "none")}
        if path:
            env["PATH"] = path
        r = subprocess.run(["sh", "-c", '. "$1"; vward_doh_alive "$2"; echo "rc=$? why=$VWARD_DOH_ALIVE_WHY"', "sh", str(LIB), URL],
                           env=env, text=True, capture_output=True, timeout=30)
        return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr

    for name, (code, body, rc, want, why) in CASES.items():
        (tmp / "code").write_text(code); setbody(body); (tmp / "rc").write_text(str(rc))
        got = probe()
        if got != f"rc={want} why={why}":
            fail(f"RED: {name}: {got} (want rc={want} why={why})")
    if "synthetic-token" not in (tmp / "stdin").read_text():
        fail("the address must go to curl on stdin")
    # The kept answer is read back with its reason.
    (tmp / "code").write_text("200"); setbody("0000818500010000" "00000000"); (tmp / "rc").write_text("0")
    probe()
    setbody(GOOD)
    if probe(fresh="0") != "rc=1 why=dns:rcode5":
        fail("the kept answer and its reason within 5 minutes")
    # A build without cksum: another checksum names the file; the folder itself is never written.
    bindir = tmp / "bin"; bindir.mkdir()
    for tool in ("sh", "cat", "cut", "find", "mkdir", "mktemp", "od", "tr", "awk", "rm", "sha256sum", "md5sum", "printf"):
        src = subprocess.run(["sh", "-c", f"command -v {tool}"], capture_output=True, text=True).stdout.strip()
        if src.startswith("/"):
            (bindir / tool).symlink_to(src)
    for f in (tmp / "cache").iterdir():
        f.unlink()
    got = probe(path=str(bindir), fresh="0")
    if got != "rc=0 why=dns:ok":
        fail("RED: without cksum the probe must still work: " + got)
    kept = list((tmp / "cache").iterdir())
    if len(kept) != 1 or not kept[0].is_file() or len(kept[0].name) != 64:
        fail("without cksum the answer goes under another checksum: " + str(kept))
# Callers: the Panel's word for it says DNS, not «works».
js = (ROOT / "web/assets/vward-console.js").read_text()
if "отвечает на DNS" not in js:
    fail("the Panel must say the server answers DNS, not that the service works")
print("DOH_ALIVE=PASS")
