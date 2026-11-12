#!/usr/bin/env python3
"""The Panel's diagnostics see a running VWARD script with the router's BusyBox grep (11.11.2026):
the script's name follows «/bin/sh» after a NUL in /proc/PID/cmdline, and BusyBox grep stops at
the first NUL of a line."""
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"DIAG_RUNNING=FAIL: {message}")


api = (ROOT / "web/cgi-bin/api.cgi").read_text()
m = re.search(r"^    diag_running\(\) \{.*\}$", api, re.M)
if not m:
    fail("api.cgi has no diag_running")
bb = shutil.which("busybox") or fail("busybox is needed (the router's grep)")
with tempfile.TemporaryDirectory() as tmp:
    bbdir = Path(tmp) / "keenetic-bin"
    bbdir.mkdir()
    (bbdir / "grep").symlink_to(bb)
    # The strictest grep a router may have: every line ends at its first NUL, in any mode
    # (BusyBox -F does so; its regex mode depends on the build).
    strict = Path(tmp) / "strict-bin"
    strict.mkdir()
    (strict / "grep").write_text(
        "#!/usr/bin/env python3\nimport re, sys\n"
        "a = [x for x in sys.argv[1:] if x not in ('-q', '-s', '-qs', '--')]\n"
        "pat, files = a[0], a[1:] or ['/dev/stdin']\n"
        "for f in files:\n"
        "    try:\n        data = open(f, 'rb').read()\n    except OSError:\n        continue\n"
        "    for line in data.split(b'\\n'):\n"
        "        if re.search(pat, line.split(b'\\0')[0].decode(errors='replace')):\n"
        "            sys.exit(0)\n"
        "sys.exit(1)\n")
    (strict / "grep").chmod(0o755)
    # Named only in its second argument, as «/bin/sh /opt/bin/vward-route-engine.sh».
    proc = subprocess.Popen(["sh", "-c", "sleep 30", f"{tmp}/vward-route-engine.sh"])
    try:
        time.sleep(0.2)
        def running(regex, gdir):
            script = f"PATH={gdir}:$PATH\n{m.group(0).strip()}\ndiag_running '{regex}' && echo PASS || echo FAIL\n"
            return subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=20).stdout.strip()
        for gdir in (bbdir, strict):
            if running("[v]ward-route-engine[.]sh", gdir) != "PASS":
                fail(f"a script run by the shell is not seen with {gdir.name} grep")
            if running("[v]ward-not-running-anywhere[.]sh", gdir) != "FAIL":
                fail("diag_running must not match its own command line")
    finally:
        proc.kill()
        proc.wait()
print("DIAG_RUNNING=PASS")
