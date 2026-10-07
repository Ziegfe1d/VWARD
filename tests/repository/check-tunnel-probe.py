#!/usr/bin/env python3
"""A working tunnel is not called dead. Through VLESS (and AmneziaWG's engine) a TLS page from
1.1.1.1 takes seconds on the router; with a 2-second limit the VPN agent switched a working
VLESS tunnel off in Keenetic right after it was enabled (2026-10-07). The VPN agent and the
tunnel check wait as long as the engine's own check (8 s), and the agent gives a restarted
engine time to come up before it judges."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"TUNNEL_PROBE=FAIL: {message}")


engine = (ROOT / "components/tunnel-guard/scripts/vward-vless-engine.sh").read_text()
m = re.search(r"--max-time (\d+)", engine.split("connected() {", 1)[1])
engine_max = int(m.group(1)) if m else 8
for path in ("components/tunnel-guard/scripts/vward-tunnel-guard.sh", "components/tunnel-guard/scripts/vward-tunnel-health.sh"):
    s = (ROOT / path).read_text()
    c = re.search(r'--connect-timeout "\$\{VWARD_PROBE_CONNECT:-(\d+)\}"', s)
    t = re.search(r'--max-time "\$\{VWARD_PROBE_MAX:-(\d+)\}"', s)
    if not c or not t or int(c.group(1)) < 3 or int(t.group(1)) < engine_max:
        fail(f"{path}: the probe through a tunnel is shorter than the engine's own check ({engine_max} s)")
guard = (ROOT / "components/tunnel-guard/scripts/vward-tunnel-guard.sh").read_text()
k = re.search(r'VWARD_GUARD_KICK_WAIT:-(\d+)', guard)
if not k or int(k.group(1)) < 15 or guard.count('wg_wait "${VWARD_GUARD_KICK_WAIT:-') != 2:
    fail("the VPN agent judges a restarted engine before it can come up (both after a failure and on the way back)")
print("TUNNEL_PROBE=PASS")
