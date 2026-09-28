#!/usr/bin/env python3
"""Route engine with several tunnels: a domain that opens neither directly nor through
VWARD's tunnel is tried through the other answering tunnels; one that opens it twice is
named in the event (ISP_FAIL_ALT_OK|host|tunnel=NAME) and nothing is added; with none,
ISP_FAIL_WG_FAIL as before; a tunnel that does not answer is not tried.

The functions are taken from vward-route-engine.sh as they are and run with stand-ins."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()
PROBE = ENGINE[ENGINE.index("probe()\n"):ENGINE.index("# ------------------------------------------------------------\n# CHANGE LOCK")]
NEW = ENGINE[ENGINE.index("handle_new()\n"):ENGINE.index("# ------------------------------------------------------------\n# EVENT\n")]


def fail(message: str) -> None:
    raise SystemExit(f"ROUTE_ALT_TUNNEL=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    # The provider and VWARD's tunnel get no answer; the devices in $tmp/open open the site.
    (tools / "curl").write_text(f"""#!/bin/sh
dev=
while [ $# -gt 0 ]; do [ "$1" = --interface ] && dev=$2; shift; done
echo "$dev" >> "{tmp}/tried"
grep -qx "$dev" "{tmp}/open" 2>/dev/null && {{ printf '200|0.2'; exit 0; }}
printf '000|3.0'; exit 28
""")
    (tools / "quality").write_text(f'#!/bin/sh\n[ "$1" = summary ] && cat "{tmp}/summary"\n')
    for f in tools.iterdir():
        f.chmod(0o755)
    harness = tmp / "harness.sh"
    harness.write_text(f"""
PATH="{tools}:$PATH"
WG=nwg0 WAN=eth3 CONNECT_TIMEOUT=1 MAX_TIME=1 QUALITY="{tools}/quality"
vward_valid_ifname() {{ case "$1" in ''|*[!A-Za-z0-9_.:-]*) return 1;; esac; }}
regular_cooldown() {{ return 1; }}
agh_blocked() {{ return 1; }}
resolve_ipv4() {{ echo 203.0.113.9; }}
sleep() {{ :; }}
save_state() {{ echo "$1 $2" >> "{tmp}/states"; }}
event_result() {{ echo "$2" >> "{tmp}/events"; }}
add_adaptive() {{ echo "ADD $1" >> "{tmp}/events"; }}
{PROBE}
{NEW}
handle_new "$1"
""")

    def run(host, open_devs, summary):
        for f in ("tried", "states", "events"):
            (tmp / f).unlink(missing_ok=True)
        (tmp / "open").write_text("".join(d + "\n" for d in open_devs))
        (tmp / "summary").write_text(summary)
        r = subprocess.run(["sh", str(harness), host], text=True, capture_output=True, timeout=60)
        if r.returncode != 0:
            fail(f"rc={r.returncode} {r.stderr}")
        return (tmp / "events").read_text().strip(), (tmp / "tried").read_text().split()

    three = ("Wireguard0\tnwg0\t100\t-\t0\t20\t100\t-\t-\t0\t5\t-\t-\n"
             "Wireguard1\tnwg1\t0\t40\t20\t20\t0\t40\t2\t100\t0\t-\t-\n"
             "Wireguard2\tnwg2\t0\t50\t20\t20\t0\t50\t2\t100\t0\t-\t-\n")
    ev, tried = run("site.example", ["nwg2"], three)
    if ev != "ISP_FAIL_ALT_OK|site.example|tunnel=Wireguard2" or tried.count("nwg2") != 2 or "ISP_FAIL_ALT_OK" not in (tmp / "states").read_text():
        fail(f"another tunnel that opens it twice is named: {ev} {tried}")
    ev, tried = run("site.example", [], three)
    if ev != "ISP_FAIL_WG_FAIL|site.example" or "nwg1" not in tried:
        fail(f"no tunnel opens it: as before: {ev}")
    ev, tried = run("site.example", ["nwg1"], three.replace("Wireguard1\tnwg1\t0\t40\t20", "Wireguard1\tnwg1\t100\t-\t0"))
    if "nwg1" in tried or ev != "ISP_FAIL_WG_FAIL|site.example":
        fail(f"a tunnel that does not answer is not tried: {tried}")
    ev, tried = run("site.example", ["nwg0", "nwg1"], three)
    if ev != "ADD site.example" or "nwg1" in tried:
        fail(f"VWARD's tunnel opens it: AdaptiveAuto as before, no other tunnel tried: {ev} {tried}")
    ev, tried = run("site.example", ["eth3"], three)
    if not ev.startswith("DIRECT_OK|site.example"):
        fail(f"directly: nothing else: {ev}")

js = (ROOT / "web/assets/vward-console.js").read_text()
if "ISP_FAIL_ALT_OK:" not in js:
    fail("the Panel does not explain ISP_FAIL_ALT_OK")
print("ROUTE_ALT_TUNNEL=PASS")
