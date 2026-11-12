#!/usr/bin/env python3
"""USB drive: free space read right, fewer writes (owner 12.11.2026).

1. Free space is read with «df -P» everywhere: BusyBox df without -P puts a long device name on a
   line of its own and the number was read as empty - the Panel's helper took that as 0 and refused
   with «нет места» on a drive with room. An unreadable answer is «unknown» (space_unknown), never «full».
2. The Panel's storage card: a df without -T still gives the sizes (plain df -Pk), never «0 free».
3. The routing core writes its journal in batches and saves its list of names at most every 30
   minutes (a removal at once, everything at stop).
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(m):
    raise SystemExit(f"FLASH_WRITES=FAIL: {m}")


# 1. No «df -k» without -P where a number is read.
for p in [*ROOT.glob("components/**/*.sh"), *ROOT.glob("components/*/init.d/*"), ROOT / "web/cgi-bin/api.cgi", ROOT / "install.sh"]:
    if p.is_file():
        for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if re.search(r"\bdf -k\b", line) and not line.lstrip().startswith("#"):
                fail(f"RED: {p.relative_to(ROOT)}:{n} reads df without -P: {line.strip()}")

helper = ROOT / "components/console/scripts/vward-console-config.sh"
src = helper.read_text()
fn = src[src.index("opt_free_kb() {"):src.index("\n}\n", src.index("opt_free_kb() {")) + 3]
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    shim = td / "bin"; shim.mkdir()
    def run(df_out):
        (shim / "df").write_text("#!/bin/sh\ncase \"$*\" in *-P*) printf '%s' \"$DF_P\" ;; *) printf '%s' \"$DF_PLAIN\" ;; esac\n")
        (shim / "df").chmod(0o755)
        env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}", DF_P=df_out, DF_PLAIN="Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/disk/by-uuid/0123456789abcdef-long\n  30000000 1000 29000000 1% /opt\n")
        return subprocess.run(["sh", "-c", fn + "opt_free_kb; echo rc=$?"], env=env, capture_output=True, text=True).stdout.split()
    good = run("Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/disk/by-uuid/0123456789abcdef-long 30000000 1000 29000000 1% /opt\n")
    if good != ["29000000", "rc=0"]:
        fail(f"free space with -P: {good}")
    bad = run("garbage\n")
    if bad != ["rc=1"]:
        fail(f"an unreadable df is «unknown», not 0: {bad}")
if "die space_unknown" not in src or "space_unknown:" not in (ROOT / "web/assets/vward-console.js").read_text():
    fail("an unknown free space is said as such")

# 2. The storage card without df -T.
api = (ROOT / "web/cgi-bin/api.cgi").read_text()
if "set -- $(df -Pk /opt 2>/dev/null | awk 'NR==2 {print $2, $3, $4}')" not in api:
    fail("the storage card needs a plain df -Pk when -T is missing")

# 3. The core: batched journal, the list of names saved at most every 30 minutes.
core = (ROOT / "tools/vward-core/cmd_adaptive.go").read_text()
for need in ("const logBatch = 64", "func urgentEvent(event string) bool", "log.flush()", "const ownedEvery = 30 * time.Minute",
             "if len(remove) > 0 || time.Since(ownedSaved) >= ownedEvery {"):
    if need not in core:
        fail(f"the routing core lacks {need!r}")
print("FLASH_WRITES=PASS: df -P everywhere, unknown is not full, batched core journal, list saved at most every 30 min")
