#!/usr/bin/env python3
"""«Роутер отвечает медленно» (fix.28.2): the agents that only look at Keenetic's configuration
share one read of it (vward_keenetic_config): readers at the same moment wait for one answer,
a copy younger than its age is not asked again, a change drops it; an answer that took 3 s or
more, or none, goes into the journal «who waited» (keenetic-slow.log). Programs that change the
configuration still read it fresh (vward_running_config), and are timed the same way."""

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
    # A slow answer (here: 1 s and more) and a failed one: in the journal, with who asked.
    (tmp / "delay").write_text("1")
    env["VWARD_KEENETIC_SLOW"] = "1"
    sh("vward_keenetic_dirty; vward_keenetic_config >/dev/null", actor="network-agent")
    (tmp / "down").write_text("")
    rc, out = sh("vward_keenetic_dirty; vward_keenetic_config", actor="network-agent")
    if rc == 0 or out:
        fail("no answer from Keenetic must be no copy")
    log = (tmp / "slow.log").read_text().splitlines()
    if len(log) != 2 or not log[0].endswith("|network-agent|running-config|1|ok") or not log[1].endswith("|network-agent|running-config|0|failed"):
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
