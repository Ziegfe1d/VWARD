#!/usr/bin/env python3
"""«Роутер отвечает медленно» (fix.28.2): the agents that only look at Keenetic's configuration
share one read of it (vward_keenetic_config): readers at the same moment wait for one answer,
a copy younger than its age is not asked again, a change drops it; an answer that took 3 s or
more, or none, goes into the journal «who waited» (keenetic-slow.log). Programs that change the
configuration still read it fresh (vward_running_config), and are timed the same way."""

import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-device-profile.sh"


def fail(message: str) -> None:
    raise SystemExit(f"KEENETIC_CACHE=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    ndmc = tmp / "ndmc"
    ndmc.write_text(f"""#!/bin/sh
echo x >> "{tmp}/calls"
[ -e "{tmp}/down" ] && exit 1
sleep "$(cat "{tmp}/delay" 2>/dev/null || echo 0)"
printf 'interface OpkgTun0\\r\\nip name-server 192.0.2.1:5353\\r\\n'
""")
    ndmc.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "VWARD_NDMC": str(ndmc), "VWARD_KCACHE": str(tmp / "kc"),
           "VWARD_KEENETIC_SLOW_LOG": str(tmp / "slow.log")}

    def sh(script, actor="tester"):
        r = subprocess.run(["sh", "-c", f'. "{LIB}"; {script}'], env=env | {"VWARD_ACTOR": actor},
                           text=True, capture_output=True, timeout=120)
        return r.returncode, r.stdout

    calls = lambda: len((tmp / "calls").read_text().split()) if (tmp / "calls").exists() else 0
    want = "interface OpkgTun0\nip name-server 192.0.2.1:5353\n"

    # Four readers at once, Keenetic answers in 2 s: asked once, everyone has the same answer.
    (tmp / "delay").write_text("2")
    rc, out = sh('for i in 1 2 3 4; do vward_keenetic_config > "$VWARD_KCACHE.out$i" & done; wait; cat "$VWARD_KCACHE".out*')
    if calls() != 1 or out != want * 4:
        fail(f"readers at the same moment must share one read: calls={calls()} out={out!r}")
    if list((tmp / "kc").glob("lock")):
        fail("the lock must go with the read")
    # A young copy: Keenetic is not asked; an older one than the reader wants: asked again.
    (tmp / "delay").write_text("0")
    rc, out = sh("vward_keenetic_config")
    if calls() != 1 or out != want:
        fail("a copy younger than its age must be used")
    rc, out = sh("sleep 2; vward_keenetic_config 1")
    if calls() != 2:
        fail("a copy older than its age must be read again")
    # A change drops the copy.
    sh("vward_keenetic_dirty; vward_keenetic_config >/dev/null")
    if calls() != 3:
        fail("a change must drop the copy")
    # A slow answer (here: 1 s and more; a busy machine adds a second) and a failed one: in the journal, with who asked.
    (tmp / "delay").write_text("1")
    env["VWARD_KEENETIC_SLOW"] = "1"
    sh("vward_keenetic_dirty; vward_keenetic_config >/dev/null", actor="network-agent")
    (tmp / "down").write_text("")
    rc, out = sh("vward_keenetic_dirty; vward_keenetic_config", actor="network-agent")
    if rc == 0 or out:
        fail("no answer from Keenetic must be no copy")
    # Only these two reads: an earlier one slowed by a busy machine is the tester's.
    log = [x for x in (tmp / "slow.log").read_text().splitlines() if "|network-agent|" in x]
    if len(log) != 2 or not re.search(r"\|network-agent\|sh\|running-config\|[1-9][0-9]*\.[0-9][0-9]\|ok$", log[0]) or not re.search(r"\|network-agent\|sh\|running-config\|0\.[0-9][0-9]\|failed$", log[1]):
        fail(f"journal «who waited»: {log}")
    if (tmp / "kc/running-config").exists():
        fail("a failed read must leave no copy")
    # A lock left by a reader that died more than a minute ago does not stop the others.
    (tmp / "down").unlink(); (tmp / "delay").write_text("0")
    (tmp / "kc/lock").mkdir()
    subprocess.run(["touch", "-d", "2 minutes ago", str(tmp / "kc/lock")], check=True)
    rc, out = sh("vward_keenetic_config")
    if rc != 0 or out != want:
        fail("a lock left over must not stop the readers")
    # Without its own place a stand-in ndmc shares nothing (tests of other programs).
    r = subprocess.run(["sh", "-c", f'. "{LIB}"; vward_keenetic_config'], env={"PATH": "/usr/bin:/bin", "VWARD_NDMC": str(ndmc)},
                       text=True, capture_output=True, timeout=30)
    if r.stdout != want:
        fail("a stand-in ndmc without VWARD_KCACHE must be asked directly")

# fix.33.2 (WP-A): every ndmc of the programs that load the library is timed and counted by the
# hour; one of 1 s or more goes into the journal with the agent, the program and the command
# (a DoH address masked); a refused command keeps its exit code and is not «no answer»; the read
# of the configuration is one entry, not one for RCI and one for ndmc; VWARD_KEENETIC_TIMING=0
# turns the counting off.
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "bin").mkdir()
    ndmc = tmp / "bin/ndmc"
    ndmc.write_text("""#!/bin/sh
case "$*" in *slow*|*running-config*) sleep 1.2 ;; esac
case "$*" in *refuse*) echo 'Command::Base error'; exit 3 ;; esac
echo "answer $*"
""")
    ndmc.chmod(0o755)
    env2 = {"PATH": f"{tmp}/bin:/usr/bin:/bin", "VWARD_KEENETIC_SLOW_LOG": str(tmp / "slow.log"),
            "VWARD_KEENETIC_CALLS": str(tmp / "calls"), "VWARD_KEENETIC_SLOWN": str(tmp / "slown"),
            "VWARD_RCI_CALLS": str(tmp / "rci-calls"), "VWARD_RCI_FAIL_LOG": str(tmp / "rci-fail"),
            "VWARD_RCI_BASE": "http://127.0.0.1:9/rci", "VWARD_KCACHE": str(tmp / "kc"), "VWARD_ACTOR": "route-engine"}

    def sh2(script, extra=None):
        r = subprocess.run(["sh", "-c", f'. "{LIB}"; {script}'], env=env2 | (extra or {}), text=True, capture_output=True, timeout=60)
        return r.returncode, r.stdout

    dots = lambda d: sum(len(f.read_text().splitlines()[1]) if len(f.read_text().splitlines()) > 1 else 0 for f in (tmp / d).glob("*")) if (tmp / d).exists() else 0
    rc, out = sh2('ndmc -c "show version"; echo "rc=$?"; command -v ndmc >/dev/null && echo has')
    if out != "answer -c show version\nrc=0\nhas\n" or dots("calls") != 1 or (tmp / "slow.log").exists():
        fail(f"a quick ndmc must be counted and not journaled: {out!r} calls={dots('calls')}")
    rc, out = sh2('ndmc -c "ip name-server https://dns.example/q slow"; ndmc -c "refuse"; echo "rc=$?"')
    log = (tmp / "slow.log").read_text().splitlines()
    if not out.endswith("rc=3\n") or len(log) != 1 or "|route-engine|sh|ndmc:-c ip name-server <url> slow|1." not in log[0] or not log[0].endswith("|ok") or "dns.example" in log[0]:
        fail(f"a slow ndmc must be journaled with the agent and the command, the address masked; a refusal keeps its code: {out!r} {log}")
    if dots("calls") != 3 or dots("slown") != 1:
        fail(f"counters by the hour: calls={dots('calls')} slow={dots('slown')}")
    # RCI does not answer (no connection), ndmc does in 1.2 s: one entry for the read.
    rc, out = sh2("vward_running_config")
    log = (tmp / "slow.log").read_text().splitlines()
    if rc != 0 or "answer -c show running-config" not in out or len(log) != 2 or "|route-engine|sh|running-config|1." not in log[1]:
        fail(f"the read of the configuration must be one entry: rc={rc} {log}")
    # fix.33.2 (WP-C): a command that may change the configuration drops the shared copy, a look
    # or a save does not.
    for cmd, kept in (("show version", True), ("system configuration save", True), ("ip name-server 192.0.2.9 x.example", False)):
        (tmp / "kc").mkdir(exist_ok=True); (tmp / "kc/running-config").write_text("copy\n")
        sh2(f'ndmc -c "{cmd}"')
        if (tmp / "kc/running-config").exists() != kept:
            fail(f"ndmc -c {cmd!r}: the shared copy must be {'kept' if kept else 'dropped'}")
    before = dots("calls")
    sh2('ndmc -c "show version"', {"VWARD_KEENETIC_TIMING": "0"})
    if dots("calls") != before:
        fail("VWARD_KEENETIC_TIMING=0 must not count")
    # No ndmc on the machine: no function in its place («command -v ndmc» stays honest).
    r = subprocess.run(["sh", "-c", f'. "{LIB}"; command -v ndmc || echo none'], env={"PATH": "/usr/bin:/bin"}, text=True, capture_output=True, timeout=30)
    if r.stdout.strip() != "none":
        fail("without ndmc there must be no ndmc function")

# Who reads the shared copy, and who drops it.
uses = {
    "components/tunnel-guard/scripts/vward-tunnel-guard.sh": ["vward_keenetic_config > \"$LW/rc\"", "FB_RC=$(vward_keenetic_config)"],
    "components/tunnel-guard/scripts/vward-tunnel-quality.sh": ["vward_keenetic_config |"],
    "components/ads-privacy-guard/scripts/vward-ads-privacy-dns-guard.sh": ["ndm_running | chain_line \"$co_ns\"", "cs_rc=$(ndm_running)", "ndm_running | chain_line \"$cp_ns\"", "/tmp/vward-keenetic}/running-config\" 2>/dev/null\n    nd_out="],
    "web/cgi-bin/api.cgi": ["vward_keenetic_config \"$nc_ttl\""],
    "components/console/scripts/vward-console-config.sh": ["/tmp/vward-keenetic}/running-config\" 2>/dev/null"],
}
for path, needs in uses.items():
    src = (ROOT / path).read_text(encoding="utf-8")
    for need in needs:
        if need not in src:
            fail(f"{path} lacks {need}")
for path in ("components/tunnel-guard/scripts/vward-tunnel-guard.sh", "components/tunnel-guard/scripts/vward-tunnel-quality.sh", "components/ads-privacy-guard/scripts/vward-ads-privacy-dns-guard.sh"):
    src = (ROOT / path).read_text(encoding="utf-8")
    # One direct read is left: the fallback when the device library is older.
    if src.count('-c "show running-config"') > 1:
        fail(f"{path} still reads Keenetic's configuration for itself")
lib = LIB.read_text(encoding="utf-8")
if 'vward_keenetic_timed running-config "$_vrc_t0"' not in lib:
    fail("the fresh read of the programs that change the configuration must be timed too")
print("KEENETIC_CACHE=PASS")
