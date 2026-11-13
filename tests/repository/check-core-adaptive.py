#!/usr/bin/env python3
"""Autopodbor in Go on the router (owner 11.11.2026).

1. S91 (core-install) pins exactly the reproducible builds (tools/vward-core/SHA256SUMS) and
   every pinned build is in tools/vward-core/dist (gunzip gives the pinned SHA-256).
2. S91's core block, taken as it is, with stand-ins for the shell engine and the core:
   no core yet -> fetched in the background once an hour, the shell engine runs; a core ->
   it runs (--apply --etc: it reads Autopodbor's switch itself), the shell engine is stopped
   first; core.observe -> no --apply; a core that dies at start -> the shell engine for an hour; engine.shell ->
   the core is stopped, the shell engine runs; a core that is not the pinned build keeps
   running while the pinned one is fetched in the background.
3. vward_core_adaptive_pid knows the core's process by its command line; while it runs the
   components agent does not start the shell engine and the shell reconciler stands aside.
4. Installing the core needs no new file in the package: the updater's target allowlist (2.0.10
   on the routers) takes only known files; the installer is «S91 core-install»."""
import gzip
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S91 = (ROOT / "components/runtime/init.d/S91vward-route-engine").read_text()
LIB = ROOT / "components/runtime/lib/vward-runtime-admission.sh"


def fail(m):
    raise SystemExit(f"CORE_ADAPTIVE=FAIL: {m}")


# 1. Pins.
sums = {}
for line in (ROOT / "tools/vward-core/SHA256SUMS").read_text().splitlines():
    s, name = line.split()
    sums[name.replace("vward-core-linux-", "")] = s
for arch, s in sums.items():
    if f"{arch}) echo {s} ;;" not in S91:
        fail(f"S91 core_sum does not pin the {arch} build {s}")
    gz = ROOT / f"tools/vward-core/dist/vward-core-linux-{arch}.gz"
    if not gz.exists():
        fail(f"no {gz.name} in tools/vward-core/dist")
    if hashlib.sha256(gzip.decompress(gz.read_bytes())).hexdigest() != s:
        fail(f"{gz.name} is not the pinned build")

# 2. S91's core block.
BLOCK = S91[S91.index("# ---- Autopodbor in Go"):S91.index('\ncase "$1" in')]


def run(tmp: Path, script: str) -> str:
    h = tmp / "h.sh"
    h.write_text(f"""EVENT_LOG="{tmp}/events.log"
VWARD_CORE_BIN="{tmp}/share/vward-core" VWARD_CORE_SELF="{tmp}/install.sh"
VWARD_CORE_LOG="{tmp}/core.log" VWARD_CORE_FALLBACK="{tmp}/fallback" VWARD_CORE_FETCH_TRY="{tmp}/try"
VWARD_ROUTE_ENGINE_ETC="{tmp}/etc" VWARD_CORE_PIDFILE="{tmp}/run/core.pid"
VWARD_LAN_DEVICE=br0 VWARD_WAN_DEVICE=ppp0 VWARD_TUNNEL_DEVICE=opkgtun4
stop_service() {{ echo shell-stop >> "{tmp}/calls"; }}
start_service() {{ echo shell-start >> "{tmp}/calls"; }}
. "{LIB}"
{BLOCK}
{script}
""")
    return subprocess.run(["sh", str(h)], capture_output=True, text=True, timeout=60).stdout


def calls(tmp):
    p = tmp / "calls"
    out = p.read_text().split() if p.exists() else []
    p.unlink(missing_ok=True)
    return out


def fake_core(tmp: Path, dies=False, old=False):
    """old: a core of the previous release - it does not know --etc (and would die on it)."""
    (tmp / "share").mkdir(exist_ok=True)
    c = tmp / "share/vward-core"
    body = "exit 3" if dies else 'echo "$@" > "%s/args"; sleep 60' % tmp
    usage = "echo '  -apply' >&2" if old else "echo '  -apply' >&2; echo '  -etc string' >&2"
    refuse = 'case " $* " in *" --etc "*) echo "flag provided but not defined: -etc" >&2; exit 2 ;; esac' if old else ":"
    c.write_text(f"#!/bin/sh\n[ \"$1\" = adaptive ] || exit 0\n[ \"$2\" != -h ] || {{ {usage}; exit 0; }}\n{refuse}\n{body}\n")
    c.chmod(0o755)


with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    (tmp / "etc").mkdir()
    (tmp / "install.sh").write_text(f'#!/bin/sh\necho "$@" >> "{tmp}/installed"\n')
    (tmp / "install.sh").chmod(0o755)
    # No core: fetched in the background, the shell engine runs.
    run(tmp, "engine_start")
    time.sleep(0.5)
    if calls(tmp) != ["shell-start"] or (tmp / "installed").read_text().split() != ["core-install"]:
        fail("no core: the shell engine and one background fetch")
    run(tmp, "engine_start")
    time.sleep(0.5)
    if len((tmp / "installed").read_text().splitlines()) != 1:
        fail("the fetch is tried at most once an hour")
    calls(tmp)
    # A core: it runs with --apply, the shell engine stopped first.
    fake_core(tmp)
    out = run(tmp, "engine_start")
    pid = (tmp / "run/core.pid").read_text().strip()
    try:
        if "Autopodbor (Go) started" not in out or calls(tmp) != ["shell-stop"]:
            fail(f"the core starts and the shell engine goes: {out!r}")
        args = (tmp / "args").read_text().split()
        if args[:1] != ["adaptive"] or "--apply" not in args or args[args.index("--tunnel-dev") + 1] != "opkgtun4" or args[args.index("--lan") + 1] != "br0":
            fail(f"core arguments: {args}")
        if "CORE_STARTED" not in (tmp / "events.log").read_text():
            fail("CORE_STARTED not logged")
        # 3. The helper knows it; a second start does nothing.
        got = subprocess.run(["sh", "-c", f'VWARD_CORE_PIDFILE="{tmp}/run/core.pid"; . "{LIB}"; vward_core_adaptive_pid'], capture_output=True, text=True).stdout.strip()
        if got != pid:
            fail(f"vward_core_adaptive_pid: {got!r} != {pid}")
        if "already running" not in run(tmp, "engine_start") or calls(tmp):
            fail("a running core is left alone")
        # engine.shell: the core goes, the shell engine runs.
        (tmp / "etc/engine.shell").write_text("")
        run(tmp, "engine_start")
        if calls(tmp) != ["shell-start"] or (tmp / "run/core.pid").exists():
            fail("engine.shell keeps the shell engine")
        (tmp / "etc/engine.shell").unlink()
        # Autopodbor switched off in the Panel: the core is given the settings directory and stops
        # writing itself (ReadModes: adaptive.disabled), at once and without a restart - started
        # without --apply it could not write again when switched back on.
        if args[args.index("--etc") + 1] != f"{tmp}/etc":
            fail(f"the core must read the owner's switches while running (--etc): {args}")
        # core.observe: no --apply.
        (tmp / "etc/core.observe").write_text("")
        run(tmp, "engine_start")
        calls(tmp)
        if "--apply" in (tmp / "args").read_text().split():
            fail("core.observe must run without --apply")
        run(tmp, "core_stop")
        (tmp / "etc/core.observe").unlink()
        # Autopodbor switched off before the start: the new core still starts with the right to
        # write (it holds itself while the switch is off, and writes again when it is on).
        (tmp / "etc/adaptive.disabled").write_text("")
        run(tmp, "engine_start")
        calls(tmp)
        args = (tmp / "args").read_text().split()
        if "--apply" not in args or "--etc" not in args:
            fail(f"switched off: the new core reads the switch itself: {args}")
        run(tmp, "core_stop")
        # A core of the previous release (until the pinned one is fetched) does not know --etc:
        # it is started the old way, and switched off - without --apply.
        fake_core(tmp, old=True)
        out = run(tmp, "engine_start")
        calls(tmp)
        args = (tmp / "args").read_text().split() if "started" in out else []
        if "--etc" in args or "--apply" in args or not args:
            fail(f"an old core, Autopodbor switched off: no --etc and no --apply: {out!r} {args}")
        run(tmp, "core_stop")
        (tmp / "etc/adaptive.disabled").unlink()
        run(tmp, "engine_start")
        calls(tmp)
        args = (tmp / "args").read_text().split()
        if "--etc" in args or "--apply" not in args:
            fail(f"an old core, Autopodbor on: --apply without --etc: {args}")
        run(tmp, "core_stop")
        (tmp / "etc/core.observe").write_text("")
        fake_core(tmp)
    finally:
        subprocess.run(["pkill", "-f", f"{tmp}/share/vward-core"], capture_output=True)
    # A core that dies at start: the shell engine, and for an hour.
    (tmp / "etc/core.observe").unlink()
    fake_core(tmp, dies=True)
    run(tmp, "engine_start")
    if calls(tmp) != ["shell-stop", "shell-start"] or not (tmp / "fallback").exists():
        fail("a core that does not start: the shell engine")
    if "CORE_START_FAILED" not in (tmp / "events.log").read_text():
        fail("CORE_START_FAILED not logged")
    fake_core(tmp)
    run(tmp, "engine_start")
    if calls(tmp) != ["shell-start"]:
        fail("within the hour after a failed start: the shell engine")

# A core left by the previous release (its sum is not the pinned one): it keeps running and the
# pinned build is fetched in the background, once an hour (fix.39: a router updated from fix.37
# kept fix.37's core for good - «no such command: auto» in Keenetic's journal, owner 13.11.2026).
with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    (tmp / "etc").mkdir()
    (tmp / "install.sh").write_text(f'#!/bin/sh\necho "$@" >> "{tmp}/installed"\n')
    (tmp / "install.sh").chmod(0o755)
    fake_core(tmp, old=True)
    old_sum = hashlib.sha256((tmp / "share/vward-core").read_bytes()).hexdigest()
    try:
        out = run(tmp, "VWARD_CORE_ARCH=mipsle\nengine_start")
        time.sleep(0.5)
        if "Autopodbor (Go) started" not in out:
            fail(f"an old core keeps working until the new one is fetched: {out!r}")
        if not (tmp / "installed").exists() or (tmp / "installed").read_text().split() != ["core-install"]:
            fail("a core that is not the pinned build is never replaced (no background core-install)")
        run(tmp, "VWARD_CORE_ARCH=mipsle\ncore_stop\nengine_start")
        time.sleep(0.5)
        if len((tmp / "installed").read_text().splitlines()) != 1:
            fail("the fetch of a newer core is tried at most once an hour")
        (tmp / "installed").unlink()
        (tmp / "try").unlink()
        run(tmp, f'VWARD_CORE_ARCH=mipsle\ncore_sum() {{ echo {old_sum}; }}\ncore_stop\nengine_start')
        time.sleep(0.5)
        if (tmp / "installed").exists():
            fail("the pinned core is not fetched again")
    finally:
        subprocess.run(["pkill", "-f", f"{tmp}/share/vward-core"], capture_output=True)

# core_install: a local build stands in for the download (file://), its sum for the pinned one.
with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    dist = tmp / "dist"
    dist.mkdir()
    subprocess.run(["go", "build", "-o", str(tmp / "core-amd64"), "."], cwd=ROOT / "tools/vward-core", check=True,
                   env={**os.environ, "CGO_ENABLED": "0"})
    raw = (tmp / "core-amd64").read_bytes()
    (dist / "vward-core-linux-amd64.gz").write_bytes(gzip.compress(raw))
    good = hashlib.sha256(raw).hexdigest()
    (dist / "vward-core-linux-mipsle.gz").write_bytes((ROOT / "tools/vward-core/dist/vward-core-linux-mipsle.gz").read_bytes())

    def install(arch, extra=""):
        h = tmp / "i.sh"
        h.write_text(f"""EVENT_LOG="{tmp}/events.log" VWARD_CORE_BIN="{tmp}/share/vward-core" VWARD_CORE_URL="file://{dist}"
VWARD_CORE_ARCH={arch}
vward_fetch() {{ curl "$@"; }}
{BLOCK}
{extra}
core_install
""")
        return subprocess.run(["sh", str(h)], capture_output=True, text=True, timeout=120).stdout.strip()

    sum_amd64 = f'core_sum() {{ [ "$1" = amd64 ] && echo {good}; }}'
    if install("amd64", sum_amd64) != "result=changed" or not os.access(tmp / "share/vward-core", os.X_OK):
        fail("core_install: a good build is installed")
    if install("amd64", sum_amd64) != "result=unchanged":
        fail("core_install: the same build again is unchanged")
    (dist / "vward-core-linux-amd64.gz").write_bytes(gzip.compress(raw + b"x"))
    (tmp / "share/vward-core").write_bytes(b"#!/bin/sh\n")
    (tmp / "share/vward-core").chmod(0o755)
    if install("amd64", sum_amd64) != "error=checksum_mismatch" or (tmp / "share/vward-core").read_bytes() != b"#!/bin/sh\n":
        fail("core_install: a changed download is refused and the old program stays")
    mips = tmp / "mipsle-probe"
    mips.write_bytes(gzip.decompress((dist / "vward-core-linux-mipsle.gz").read_bytes()))
    mips.chmod(0o755)
    try:  # qemu binfmt on the host runs it: then this case says nothing
        runs_here = subprocess.run([str(mips), "version"], capture_output=True).returncode == 0
    except OSError:
        runs_here = False
    if not runs_here and install("mipsle") != "error=binary_not_runnable":
        fail("core_install: a build for another processor does not replace the program")
    if "CORE_INSTALLED" not in (tmp / "events.log").read_text() or "CORE_INSTALL_FAILED|checksum_mismatch" not in (tmp / "events.log").read_text():
        fail("core_install journal lines")

# 3. One writer of AdaptiveAuto.
SUP = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text()
REC = (ROOT / "components/route-reconciler/scripts/vward-route-reconciler.sh").read_text()
keep = SUP[SUP.index("keep_route_engine()"):]
if keep.index("vward_core_adaptive_pid") > keep.index("start_of route-engine"):
    fail("the components agent must not start the shell engine while the core runs")
if REC.index("vward_core_adaptive_pid") > REC.index("ndmc"):
    fail("the shell reconciler must stand aside while the core runs")

# 4. Nothing new in the package.
if "vward-core-install" in (ROOT / "config/components/package-map.tsv").read_text():
    fail("a new file in the package map: the installed updater would refuse it")
for word in ("core-install)", "core_install()", "CORE_INSTALLED", "checksum_mismatch"):
    if word not in S91:
        fail(f"S91 core-install: {word} missing")
# 5. Its journal in the Panel (and in «Все журналы»), with the zone written out.
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
JS = (ROOT / "web/assets/vward-console.js").read_text()
CMD = (ROOT / "tools/vward-core/cmd_adaptive.go").read_text()
# A router that lived before (owner 12.11.2026): on the core's first start the names already in
# AdaptiveAuto are rechecked, as the shell engine rechecked the whole group (TestAdoptGroupOnFirstStart).
MODES = (ROOT / "tools/vward-core/internal/adaptive/modes.go").read_text()
if '"adaptive.disabled", "core.observe"' not in MODES or "w.Observe = held || m.Observe" not in CMD or CMD.count("reread()") < 3:
    fail("the core must reread adaptive.disabled before every write (batch, reconcile round)")
if "firstStart := os.IsNotExist(ownedErr)" not in CMD or "owned.AdoptGroup(inGroup(m), time.Now())" not in CMD or "OWNED_ADOPTED" not in CMD:
    fail("the core's first start must recheck the names already in AdaptiveAuto")
if "echo /opt/var/log/vward-core-adaptive.log" not in API or "{ id: 'core', label: 'Автоподбор (Go)' }" not in JS:
    fail("the core's journal is not a Panel journal")
if '"2006-01-02T15:04:05-0700"' not in CMD or 'log.put("STATS"' not in CMD:
    fail("the core's journal: the zone in every line and an hourly summary")
print("CORE_ADAPTIVE=PASS")
