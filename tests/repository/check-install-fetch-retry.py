#!/usr/bin/env python3
"""install.sh fetch: curl crashing on HTTPS now and then (Entware's OpenSSL 3.5.5 on MIPS, rc 132)
is tried again (up to 6 times); an ordinary failure (404: rc 22) is an answer at once."""
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "install.sh").read_text()
FUNC = SRC[SRC.index("fetch() {"):SRC.index("\n}\n", SRC.index("fetch() {")) + 3]


def fail(m):
    raise SystemExit(f"INSTALL_FETCH_RETRY=FAIL: {m}")


def run(tmp: Path, crashes: int, final_rc: int):
    (tmp / "n").write_text("0")
    curl = tmp / "curl"
    curl.write_text(f"""#!/bin/sh
n=$(cat "{tmp}/n"); n=$((n + 1)); echo $n > "{tmp}/n"
out=; while [ $# -gt 0 ]; do [ "$1" = --output ] && out=$2; shift; done
[ $n -le {crashes} ] && kill -ILL $$
[ {final_rc} = 0 ] || exit {final_rc}
echo data > "$out"
""")
    curl.chmod(0o755)
    for shell in (["sh"], ["busybox", "sh"]):
        r = subprocess.run([*shell, "-c", f'PATH="{tmp}:$PATH"; sleep() {{ :; }}; {FUNC}\nfetch https://x/y "{tmp}/out"; echo rc=$?'],
                           capture_output=True, text=True, timeout=60)
        yield shell[0], r.stdout.strip().splitlines()[-1], int((tmp / "n").read_text())
        (tmp / "n").write_text("0")


with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    for shell, rc, n in run(tmp, 3, 0):
        if rc != "rc=0" or n != 4 or (tmp / "out").read_text() != "data\n":
            fail(f"{shell}: three crashes then a download: {rc} after {n}")
        (tmp / "out").unlink()
    for shell, rc, n in run(tmp, 0, 22):
        if rc != "rc=22" or n != 1:
            fail(f"{shell}: a 404 is an answer at once: {rc} after {n}")
    for shell, rc, n in run(tmp, 99, 0):
        if rc == "rc=0" or n != 6:
            fail(f"{shell}: crashing every time stops after 6: {rc} after {n}")
print("INSTALL_FETCH_RETRY=PASS")
