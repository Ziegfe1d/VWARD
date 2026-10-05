#!/usr/bin/env python3
"""The real-time watcher in VWARD's runtime.

vward-sentinel.sh: pins the four router builds (tools/vward-sentinel/SHA256SUMS), refuses
a download with another checksum, starts the program with what to watch (VWARD's programs
with their memory limits, the provider's and the tunnels' interfaces, the router's DNS),
stops it, reports its status.
vward-sentinel-act.sh: a provider interface event runs the WAN guard, a tunnel's the tunnel
checks (the network agent); a program gone, a leak and DNS without a running AdGuard Home go
to the components agent as requests, which it alone carries out (start, restart, AdGuard Home
through its one gate); the network agent's restart of a tunnel's module is asked too.
The cron supervisor keeps the watcher running and leaves leaks to it; vward_busy takes the
watcher's busy flag while it runs; the tunnel engines tell it their tunnels changed."""

import gzip
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CTL = ROOT / "components/runtime/scripts/vward-sentinel.sh"
ACT = ROOT / "components/runtime/scripts/vward-sentinel-act.sh"


def fail(message: str) -> None:
    raise SystemExit(f"SENTINEL_RUNTIME=FAIL: {message}")


ctl = CTL.read_text()
for line in (ROOT / "tools/vward-sentinel/SHA256SUMS").read_text().splitlines():
    digest, name = line.split()
    arch = name.rsplit("-", 1)[1]
    if f"        {arch}) echo {digest} ;;" not in ctl:
        fail(f"vward-sentinel.sh must pin {name} as in SHA256SUMS")

# vward-dnscap, the route engine's DNS capture, is pinned the same way.
for line in (ROOT / "tools/vward-dnscap/SHA256SUMS").read_text().splitlines():
    digest, name = line.split()
    arch = name.rsplit("-", 1)[1]
    if f"        {arch}) echo {digest} ;;" not in ctl[ctl.index("dnscap_sum()"):]:
        fail(f"vward-sentinel.sh must pin {name} as in SHA256SUMS")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bin_ = tmp / "bin"; bin_.mkdir()
    share, run, state = tmp / "share", tmp / "run", tmp / "state"
    (run / "awg-engine").mkdir(parents=True)
    (run / "awg-engine/t0.pid").write_text("1\n")
    (tmp / "profile.sh").write_text(
        f"vward_profile_load(){{ VWARD_WAN_DEVICE=eth3; VWARD_LAN_ADDRESS=192.168.1.1; VWARD_ADGUARD_CONFIG={tmp}/agh.yaml; }}\n"
        "vward_device_map(){ :; }\nvward_map_vpns(){ printf 'Wireguard0 nwg0\\nOpkgTun0 opkgtun0\\n'; }\n")
    (tmp / "agh.yaml").write_text("dns:\n  bind_hosts:\n    - 192.168.1.1\n  port: 65053\n")
    (bin_ / "curl").write_text(f'#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && {{ cp "{tmp}/served.gz" "$2"; exit 0; }}; shift; done\nexit 22\n')
    (bin_ / "curl").chmod(0o755)
    env = os.environ | {"PATH": f"{bin_}:{os.environ['PATH']}", "VWARD_SENTINEL_SHARE": str(share), "VWARD_SENTINEL_STATE": str(state),
                        "VWARD_SENTINEL_PIDFILE": str(run / "sentinel.pid"), "VWARD_RUN_DIR": str(run),
                        "VWARD_SENTINEL_LOG": str(tmp / "sentinel.log"), "VWARD_CURL_BIN": str(bin_ / "curl"),
                        "VWARD_PROFILE_LIB": str(tmp / "profile.sh"), "VWARD_SENTINEL_ARCH": "mipsle",
                        "VWARD_SENTINEL_HOURS": str(tmp / "hours.tsv"), "VWARD_SENTINEL_ACT": str(tmp / "act.sh")}

    def sh(*args, e=None):
        r = subprocess.run(["sh", str(CTL), *args], env=e or env, text=True, capture_output=True, timeout=60)
        return r.stdout.strip()

    # A download with another checksum is refused, nothing installed.
    (tmp / "served.gz").write_bytes(gzip.compress(b"#!/bin/sh\necho x\n"))
    if sh("install") != "error=checksum_mismatch" or (share / "vward-sentinel").exists():
        fail("a program with another checksum must be refused")
    env["VWARD_DNSCAP_SHARE"] = str(tmp / "dnscap")
    if sh("install-dnscap") != "error=checksum_mismatch" or (tmp / "dnscap/vward-dnscap").exists():
        fail("a capture program with another checksum must be refused")
    if [p.name for p in (tmp / "dnscap").iterdir()]:
        fail("a refused download leaves nothing behind")
    if sh("status") != "status=not_installed" or sh("start") != "result=not_installed":
        fail("without the program nothing starts")

    # The program itself (built here) in place of the router's build.
    share.mkdir(exist_ok=True)
    cc = shutil.which("cc") or shutil.which("gcc")
    subprocess.run([cc, "-O2", "-o", str(share / "vward-sentinel"), str(ROOT / "tools/vward-sentinel/sentinel.c")], check=True)
    if sh("start") != "result=changed" or not sh("status").startswith("status=running"):
        fail(f"start: {sh('status')}")
    conf = (state / "sentinel.conf").read_text()
    for need in (f"WATCH=route-engine:{run}/route-engine.pid:16384", "WATCH=panel:/opt/var/run/vward-console-lighttpd.pid:24576",
                 f"WATCH=awg-t0:{run}/awg-engine/t0.pid:65536", "IFACE=eth3", "IFACE=nwg0", "IFACE=opkgtun0", "DNS=127.0.0.1:53",
                 "CHAIN=192.168.1.1:65053", "CHAIN_EVERY=5", "CHAIN_MISS=3"):
        if need not in conf:
            fail(f"configuration lacks {need!r}:\n{conf}")
    if sh("start") != "result=unchanged":
        fail("started once")
    time.sleep(0.5)
    if not (state / "state").exists() or "START|" not in (state / "events.log").read_text():
        fail("the program runs and writes its state")
    if sh("stop") != "result=changed" or sh("status") != "status=stopped":
        fail("stop")

    # Actions.
    initd, obin = tmp / "init.d", tmp / "obin"
    initd.mkdir(); obin.mkdir()
    for f in ("S91vward-route-engine", "S93vward-console", "S99adguardhome"):
        (initd / f).write_text(f'#!/bin/sh\necho "{f} $1" >> "{tmp}/done"\n')
    for f in ("vward-wan-guard.sh", "vward-tunnel-health.sh", "vward-tunnel-guard.sh"):
        (obin / f).write_text(f'#!/bin/sh\necho "{f}" >> "{tmp}/done"\n')
    for f in list(initd.iterdir()) + list(obin.iterdir()):
        f.chmod(0o755)
    (bin_ / "pidof").write_text("#!/bin/sh\nexit 1\n"); (bin_ / "pidof").chmod(0o755)
    req = tmp / "req"
    agent_init = tmp / "agent-init"; agent_init.write_text(f'#!/bin/sh\necho "agent $1" >> "{tmp}/done"\n'); agent_init.chmod(0o755)
    aenv = env | {"VWARD_INITD": str(initd), "VWARD_BIN_DIR": str(obin), "VWARD_CONSOLE_PIDFILE": str(run / "panel.pid"),
                  "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
                  "VWARD_AGENT_REQ": str(req), "VWARD_AGENT_INIT": str(agent_init), "VWARD_AGENT_PIDFILE": str(tmp / "none.pid")}

    def act(*args):
        (tmp / "done").unlink(missing_ok=True)
        r = subprocess.run(["sh", str(ACT), *args], env=aenv, text=True, capture_output=True, timeout=60)
        return r.returncode, ((tmp / "done").read_text().splitlines() if (tmp / "done").exists() else [])

    def asked():
        got = sorted(p.name for p in req.iterdir() if not p.name.startswith(".")) if req.exists() else []
        for p in req.glob("*"):
            p.unlink()
        return got

    if act("link", "eth3", "down") != (0, ["vward-wan-guard.sh"]):
        fail(f"the provider's interface: the WAN guard at once: {act('link', 'eth3', 'down')}")
    if act("link", "nwg0", "down") != (0, ["vward-tunnel-health.sh", "vward-tunnel-guard.sh"]):
        fail("a tunnel's interface: the tunnel checks at once")
    if act("addr", "opkgtun0", "lost")[1] != ["vward-tunnel-health.sh", "vward-tunnel-guard.sh"]:
        fail("a tunnel that lost its address: the tunnel checks")
    # Programs: asked of the components agent (started first when it is not running), never done here.
    rc, done = act("down", "route-engine")
    if rc != 0 or done != ["agent start"] or asked() != ["start:route-engine"]:
        fail(f"a program gone: the components agent is asked to start it: {rc} {done}")
    rc, done = act("leak", "panel", "30000")
    if rc != 0 or "S93vward-console start" in done or asked() != ["restart:panel"]:
        fail(f"a leak: the components agent is asked to restart it: {rc} {done}")
    rc, done = act("dns-fail")
    if rc != 0 or "S99adguardhome start" in done or asked() != ["agh-start"]:
        fail(f"DNS without answers: the components agent is asked to start AdGuard Home: {rc} {done}")

    # The components agent carries the requests out: its functions, from the supervisor itself.
    sup_src = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text()
    funcs = "".join(re.search(rf"^{n}\(\)\n\{{\n.*?^\}}\n", sup_src, re.S | re.M).group(0)
                    for n in ("pidfile_of", "start_of", "engine_of", "agent_do", "process_requests"))
    victim = subprocess.Popen(["sleep", "60"])
    (run / "panel.pid").write_text(f"{victim.pid}\n")
    req.mkdir(exist_ok=True)
    for r_ in ("start:route-engine", "restart:panel", "agh-start", "bogus"):
        (req / r_).write_text("")
    (tmp / "done").unlink(missing_ok=True)
    script = (f'RUN_DIR={run}; CONSOLE_PIDFILE={run}/panel.pid; CONSOLE_INIT={initd}/S93vward-console; INITD={initd}; BIN_DIR={obin}\n'
              f'AGH_INIT={initd}/S99adguardhome; REQ_DIR={req}; OFF_FLAG={tmp}/no-off; UNNICE=\n'
              f'log_event() {{ echo "$*" >> {tmp}/agent.log; }}\n'
              'vward_agh_ensure() { "$1" start; return 10; }\n' + funcs + "process_requests\n")
    r = subprocess.run(["sh", "-c", script], text=True, capture_output=True, timeout=60)
    victim.wait(timeout=10)
    done = (tmp / "done").read_text().splitlines() if (tmp / "done").exists() else []
    if r.returncode != 0 or sorted(done) != ["S91vward-route-engine start", "S93vward-console start", "S99adguardhome start"] or victim.returncode is None:
        fail(f"the components agent: start, restart (stopped first), AdGuard Home: {r.returncode} {done} {r.stderr}")
    if list(req.iterdir()):
        fail("requests stay after the components agent took them")
    log = (tmp / "agent.log").read_text()
    if "STARTED|route-engine|asked" not in log or "RESTARTED|panel|asked" not in log or "AGH_STARTED|asked" not in log:
        fail(f"the components agent logs what it did: {log}")
    # While VWARD is switched off: nothing starts, the requests go.
    (req / "start:route-engine").write_text(""); (tmp / "no-off").write_text("")
    (tmp / "done").unlink(missing_ok=True)
    subprocess.run(["sh", "-c", script], text=True, capture_output=True, timeout=60)
    if (tmp / "done").exists() or list(req.iterdir()):
        fail("VWARD switched off: requests are dropped, nothing starts")
    # AdGuard Home silent in the chain: the DNS guard takes it out (it checks again itself).
    guardbin = obin / "vward-ads-privacy-dns-guard.sh"
    guardbin.write_text(f'#!/bin/sh\necho "dns-guard $*" >> "{tmp}/done"\necho chain_state=out\n'); guardbin.chmod(0o755)
    if act("chain-fail") != (0, ["dns-guard chain-out"]):
        fail(f"chain-fail: the DNS guard takes AdGuard Home out: {act('chain-fail')}")
    guardbin.write_text(f'#!/bin/sh\necho "dns-guard $*" >> "{tmp}/done"\necho chain_state=in\n')
    if act("chain-fail")[0] == 0:
        fail("chain-fail that changed nothing does not count as helped")
    if act("link", "eth3;reboot", "down")[0] != 64 or act("leak", "unknown", "1")[0] != 64 or act("down", "x;reboot")[0] != 64:
        fail("odd names are refused")
    if "|ACT|leak|panel|rss_kb=30000|restart" not in (tmp / "sentinel.log").read_text():
        fail("actions are logged")

sup = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text()
watch = sup[sup.index("watch_services()"):sup.index("log_event \"SUPERVISOR_START")]
if "if sentinel_alive; then" not in watch or "watch_memory" not in watch.split("if sentinel_alive; then", 1)[1] or '"$SENTINEL_CTL" start' not in watch:
    fail("the supervisor keeps the watcher running and leaves leaks to it")
lib = (ROOT / "components/runtime/lib/vward-runtime-admission.sh").read_text()
if '[ -e "$VWARD_SENTINEL_STATE/busy" ]' not in lib:
    fail("vward_busy takes the watcher's flag")
for engine in ("vward-awg-engine.sh", "vward-vless-engine.sh"):
    src = (ROOT / "components/tunnel-guard/scripts" / engine).read_text()
    if 'op_add "$2" "$3" "${4:-}"; sentinel_reload' not in src or 'op_remove "$2"; sentinel_reload' not in src:
        fail(f"{engine} tells the watcher its tunnels changed")
if '"$SENTINEL_CTL" install && "$SENTINEL_CTL" reload' not in (ROOT / "components/runtime/scripts/vward-housekeeping.sh").read_text():
    fail("housekeeping installs the watcher's program")
print("SENTINEL_RUNTIME=PASS")
