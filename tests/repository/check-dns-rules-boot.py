#!/usr/bin/env python3
"""DNS rules of the tunnel after a boot (fix.34.1, r6; «vward-tunnel-health.sh dns-rules» from the components agent since 16.11.2026). 25.10 after a reboot the live
ndnproxymain.conf had 1 of the 16 «ip name-server ... on OpkgTun4» lines of the configuration;
Instagram did not resolve until «no» and the same line again. tunnel-health checks once a boot
(router up 5 minutes, tunnel UP): the missing lines are given again and logged, the next minute
checks again (3 tries); no live file - nothing is done; all there - «ok», resolving checked."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "components/tunnel-guard/scripts/vward-tunnel-health.sh").read_text()
SUP = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text()
SH = ["busybox", "sh"] if shutil.which("busybox") else ["sh"]


def fail(message: str) -> None:
    raise SystemExit(f"DNS_RULES_BOOT=FAIL: {message}")


m = re.search(r"^dns_rules_check\(\)\n\{\n.*?^\}\n", SRC, re.S | re.M)
# 16.11.2026: the VPN agent (tunnel-guard) is off by default since fix.37 and the rules stayed 1 of 16 after a
# reboot - the check is «vward-tunnel-health.sh dns-rules», before the agent's gate, run by the components
# agent (always on) once a minute; the agent's own rounds no longer run it (no second writer).
if not m or SRC.count("    dns_rules_check\n") != 1 or 'if [ "${1:-}" = dns-rules ]; then' not in SRC:
    fail("vward-tunnel-health.sh dns-rules must check the DNS rules of the tunnel, and only that mode")
if SRC.index('if [ "${1:-}" = dns-rules ]; then') > SRC.index("vward_component_gate tunnel-guard"):
    fail("the mode must run whatever the VPN agent's switch")
if "dns_rules_tick()" not in SUP or "|| dns_rules_tick" not in SUP or '"$DNS_RULES_BIN" dns-rules' not in SUP:
    fail("the components agent must run the check once a minute")
FUNC = m.group(0)

DOMAINS = ["youtube.com", "youtu.be", "youtube-nocookie.com", "googlevideo.com", "ytimg.com", "ggpht.com",
           "instagram.com", "cdninstagram.com"]
RULES = [(s, d) for d in DOMAINS for s in ("8.8.8.8", "1.1.1.1")]  # 16
CONFIG = ("dns-proxy\n    https upstream https://doh.example.net/dns-query dot domain ai.example\n!\n"
          "ip name-server 192.168.1.1:5353 ai.example on ISP\n"
          + "".join(f"ip name-server {s} {d} on OpkgTun4\n" for s, d in RULES))


def live(rules) -> str:
    return "dns_server = 192.168.1.1:53 .\n" + "".join(f"dns_server = {s}:53 {d}.\n" for s, d in rules)


# The script itself, as the components agent starts it: its tunnel down - nothing; up - the rules given again.
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "config").write_text("".join(f"ip name-server {s} {d} on OpkgTun0\n" for s, d in RULES))
    (t / "ndmc").write_text(f'#!/bin/sh\necho "$2" >> {t}/ndmc.log\n'); (t / "ndmc").chmod(0o755)
    (t / "uptime").write_text("900.00 1.00\n")
    (t / "live.conf").write_text("dns_server = 8.8.8.8 youtube.com\n")
    (t / "lists.conf").write_text("dns_rules_check=1\n")
    (t / "profile.sh").write_text(f"vward_profile_load() {{ VWARD_TUNNEL_INTERFACE=OpkgTun0; VWARD_TUNNEL_DEVICE=opkgtun0; }}\n"
                                  f"vward_running_config() {{ cat {t}/config; }}\n"
                                  f"ndmc() {{ echo \"$2\" >> {t}/ndmc.log; }}\n")
    (t / "sys/opkgtun0").mkdir(parents=True)
    env = {"PATH": f"{t}:/usr/bin:/bin", "VWARD_PROFILE_LIB": str(t / "profile.sh"), "VWARD_SYSFS_NET": str(t / "sys"),
           "VWARD_UPTIME_FILE": str(t / "uptime"), "VWARD_NDNPROXY_CONF": str(t / "live.conf"), "VWARD_DOMAIN_LISTS_CONF": str(t / "lists.conf"),
           "VWARD_DNS_RULES_STATE": str(t / "state"), "VWARD_DNS_RULES_LOG": str(t / "log"), "VWARD_NSLOOKUP": "true"}
    script = ROOT / "components/tunnel-guard/scripts/vward-tunnel-health.sh"
    (t / "sys/opkgtun0/flags").write_text("0x1002\n")
    subprocess.run(SH + [str(script), "dns-rules"], env=env, timeout=60)
    if (t / "state").exists() or (t / "ndmc.log").exists():
        fail("a tunnel that is down: nothing looked at")
    (t / "sys/opkgtun0/flags").write_text("0x1003\n")
    r = subprocess.run(SH + [str(script), "dns-rules"], env=env, text=True, capture_output=True, timeout=60)
    sent = (t / "ndmc.log").read_text().splitlines() if (t / "ndmc.log").exists() else []
    if r.returncode != 0 or len(sent) != 30 or "RESULT=reapplied" not in (t / "state").read_text():
        fail(f"the tunnel up: 15 rules given again by the script: rc={r.returncode} {r.stderr[-200:]} {sent[:2]}")

with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "config").write_text(CONFIG)
    (t / "ndmc").write_text(f'#!/bin/sh\necho "$2" >> {t}/ndmc.log\n')
    (t / "ndmc").chmod(0o755)
    (t / "nslookup").write_text("#!/bin/sh\nprintf 'Server: 127.0.0.1\\n\\nName: %s\\nAddress 1: 157.240.0.35\\n' \"$1\"\n")
    (t / "nslookup").chmod(0o755)

    def run(uptime: int = 900, conf: str | None = "") -> tuple[str, list[str], str]:
        (t / "ndmc.log").write_text("")
        (t / "uptime").write_text(f"{uptime}.10 100.00\n")
        live_path = str(t / "ndnproxymain.conf") if conf is not None else str(t / "none.conf")
        script = f"""PATH="{t}:$PATH"
NOW_EPOCH=1761400000; NOW_TEXT="2026-10-25 15:15:00"; LOG="{t}/health.log"; VWARD_TUNNEL_INTERFACE=OpkgTun4
VWARD_DNS_RULES_STATE="{t}/state"; VWARD_UPTIME_FILE="{t}/uptime"; VWARD_NDNPROXY_CONF="{live_path}"
VWARD_DOMAIN_LISTS_CONF="{t}/lists.conf"; VWARD_NSLOOKUP="{t}/nslookup"
vward_running_config() {{ cat "{t}/config"; }}
{FUNC}dns_rules_check
"""
        r = subprocess.run(SH + ["-c", script], text=True, capture_output=True, timeout=60)
        if r.returncode != 0 or r.stderr:
            fail(f"dns_rules_check: {r.returncode} {r.stderr}")
        state = (t / "state").read_text() if (t / "state").exists() else ""
        return state, (t / "ndmc.log").read_text().splitlines(), (t / "health.log").read_text() if (t / "health.log").exists() else ""

    # The default (owner 08.11): observation only - the mismatch logged once a boot, nothing sent.
    (t / "ndnproxymain.conf").write_text(live(RULES[:1]))
    for conf in (None, "dns_rules_check=observe\n"):
        if conf is None:
            (t / "lists.conf").unlink(missing_ok=True)
        else:
            (t / "lists.conf").write_text(conf)
        (t / "state").unlink(missing_ok=True)
        (t / "health.log").unlink(missing_ok=True)
        state, ndmc, log = run()
        if ndmc or "RESULT=observed" not in state or "LIVE=1" not in state:
            fail(f"observation must send nothing: {ndmc[:2]} {state!r}")
        if "DNS_RULES result=mismatch_observed config=16 live=1 would_reapply=15" not in log:
            fail(f"the observed mismatch must be logged: {log!r}")
        state, ndmc, _ = run()
        if ndmc:
            fail("observation: once a boot")
    (t / "state").unlink()
    (t / "health.log").unlink()
    (t / "lists.conf").write_text("dns_rules_check=1\n")

    # Too early after a boot: nothing.
    (t / "ndnproxymain.conf").write_text(live(RULES[:1]))
    state, ndmc, _ = run(uptime=120)
    if state or ndmc:
        fail("the check waits 5 minutes after a boot")

    # 16 in the configuration, 1 live: the 15 given again («no» + the line), logged.
    state, ndmc, log = run()
    missing = RULES[1:]
    want = [x for s, d in missing for x in (f"no ip name-server {s} {d} on OpkgTun4", f"ip name-server {s} {d} on OpkgTun4")]
    if ndmc != want:
        fail(f"the 15 missing rules must be given again: {ndmc[:4]}")
    if "RESULT=reapplied" not in state or "CONFIG=16" not in state or "LIVE=1" not in state or "TRIES=1" not in state:
        fail(f"state: {state!r}")
    if "DNS_RULES result=mismatch config=16 live=1 reapplied=15 try=1" not in log:
        fail(f"the mismatch must be logged: {log!r}")
    if any("ai.example" in c for c in ndmc):
        fail("only the rules of the tunnel are touched")

    # The next minute: all 16 live - ok, resolving through the router checked, nothing given.
    (t / "ndnproxymain.conf").write_text(live(RULES))
    state, ndmc, log = run()
    if ndmc or "RESULT=ok" not in state or "LIVE=16" not in state or "RESOLVES=yes" not in state:
        fail(f"16 of 16: ok and nothing done: {state!r} {ndmc}")
    if "DNS_RULES result=ok config=16 live=16 tries=1 resolves=yes" not in log:
        fail(f"ok logged: {log!r}")
    # Done for this boot.
    (t / "ndnproxymain.conf").write_text(live([]))
    state, ndmc, _ = run()
    if ndmc:
        fail("once a boot")

    # Never fixed: 3 tries, then given up and nothing more.
    (t / "ndnproxymain.conf").write_text(live(RULES[:1]))
    (t / "state").unlink()
    (t / "health.log").unlink()
    for _ in range(3):
        run()
    state, ndmc, log = run()
    if ndmc or "RESULT=gave_up" not in state or log.count("result=mismatch") != 3:
        fail(f"3 tries, then gave_up: {state!r} {log!r}")

    # No live file: nothing done, said so.
    (t / "state").unlink()
    state, ndmc, _ = run(conf=None)
    if ndmc or "RESULT=no_live_file" not in state:
        fail(f"no live file: nothing done: {state!r}")

    # Not one rule live: the file is read wrong or empty - nothing done, said so.
    (t / "state").unlink()
    (t / "ndnproxymain.conf").write_text(live([]))
    state, ndmc, _ = run()
    if ndmc or "RESULT=unknown" not in state:
        fail(f"0 of 16 live: nothing done: {state!r}")

    # Turned off.
    (t / "state").unlink(missing_ok=True)
    (t / "lists.conf").write_text("dns_rules_check=0\n")
    state, ndmc, _ = run()
    if ndmc or "RESULT=off" not in state:
        fail("dns_rules_check=0 turns it off")
print("DNS_RULES_BOOT=PASS")
