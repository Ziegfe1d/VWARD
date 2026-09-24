#!/usr/bin/env python3
"""Route engine: watched domain lists are moved into the tunnel when their path fails.

The two functions are taken from vward-route-engine.sh as they are and run with
stand-ins for curl, the tunnel probe, DNS and the Console writer.
"""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()
FUNCS = ENGINE[ENGINE.index("list_watch_map()\n"):ENGINE.index("handle_host()\n")]

CFG = """dns-proxy
    route object-group domain-list4 ISP auto
    route object-group domain-list0 Wireguard0 auto
    route object-group domain-list3 ISP auto
!
"""
ALL = "domain-list4|claude.ai\ndomain-list4|claude.com\ndomain-list0|telegram.org\ndomain-list3|chatgpt.com\n"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "cfg").write_text(CFG)
    (tmp / "all").write_text(ALL)
    (tmp / "lists.conf").write_text("watch.domain-list4=1\nwatch.domain-list0=1\nwatch.domain-list3=0\n")
    tools = tmp / "tools"; tools.mkdir()
    # curl answers what $tmp/answer holds, as "code redirect_url".
    (tools / "curl").write_text(f'#!/bin/sh\nprintf "%s" "$(cat {tmp}/answer)"\n')
    (tools / "helper").write_text(f'#!/bin/sh\necho "$*" >> {tmp}/helper.calls\necho result=changed\n')
    for f in ("curl", "helper"):
        (tools / f).chmod(0o755)

    harness = tmp / "harness.sh"
    harness.write_text(f"""
PATH="{tools}:$PATH"
VWARD_TUNNEL_INTERFACE=Wireguard0 WG=nwg0 WAN=eth3
CONNECT_TIMEOUT=1 MAX_TIME=1
VOLATILE_DIR="{tmp}/vol"; mkdir -p "$VOLATILE_DIR"
LISTS_CONF="{tmp}/lists.conf" LIST_WATCH_MAP="$VOLATILE_DIR/list-watch.map"
LIST_WATCH_COOLDOWN=0 LIST_WATCH_FAILS=2
CONSOLE_CONFIG_BIN="{tools}/helper" EVENT_LOG="{tmp}/events" REFRESH_TS="{tmp}/refresh"
resolve_ipv4() {{ echo 203.0.113.9; }}
wg_quick_ok() {{ [ ! -e "{tmp}/wg-down" ]; }}
{FUNCS}
case "$1" in
    map) list_watch_map "{tmp}/cfg" "{tmp}/all" ;;
    check) list_watch_check "$2" ;;
esac
""")

    def sh(*args):
        r = subprocess.run(["sh", str(harness), *args], text=True, capture_output=True)
        if r.returncode != 0:
            fail(f"{args}: rc={r.returncode} {r.stderr}")

    def check(host, answer):
        (tmp / "answer").write_text(answer)
        sh("check", host)

    def calls():
        p = tmp / "helper.calls"
        return p.read_text().splitlines() if p.exists() else []

    sh("map")
    watch_map = sorted((tmp / "vol/list-watch.map").read_text().splitlines())
    if watch_map != ["claude.ai domain-list4", "claude.com domain-list4"]:
        fail(f"only watched lists around the tunnel belong in the map: {watch_map}")

    # A region redirect twice: the second one moves the list into the tunnel.
    check("claude.com", "302 https://claude.com/app-unavailable-in-region")
    if calls():
        fail("one failure must not switch")
    check("claude.com", "302 https://claude.com/app-unavailable-in-region")
    if calls() != ["domain-list domain-list4 vpn"]:
        fail(f"two failures must switch the list: {calls()}")
    events = (tmp / "events").read_text()
    if "LIST_AUTO_VPN|claude.com|domain-list4|result=changed" not in events:
        fail(f"the switch is not logged: {events}")
    if (tmp / "refresh").read_text().strip() != "0":
        fail("the group refresh must be forced after a switch")

    # A success resets the count; 403 and ordinary redirects are not failures.
    (tmp / "helper.calls").unlink()
    check("api.claude.ai", "000 ")
    check("claude.ai", "200 ")
    check("claude.ai", "000 ")
    if calls():
        fail(f"a success between failures must reset the count: {calls()}")
    for answer in ("403 ", "302 https://claude.ai/login", "404 "):
        check("claude.ai", answer)
        check("claude.ai", answer)
    if calls():
        fail(f"403 and ordinary redirects are not failures: {calls()}")

    # The tunnel is down: no switch into a dead tunnel.
    (tmp / "wg-down").touch()
    check("claude.ai", "000 ")
    check("claude.ai", "000 ")
    if calls() or "LIST_AUTO_VPN_SKIP|claude.ai|domain-list4|reason=WG_DOWN" not in (tmp / "events").read_text():
        fail(f"a dead tunnel must not take the list: {calls()}")
    (tmp / "wg-down").unlink()

    # Names outside watched lists are never checked.
    (tmp / "answer").write_text("000 ")
    before = (tmp / "events").read_text()
    for host in ("telegram.org", "chatgpt.com", "notclaude.ai"):
        sh("check", host)
    if (tmp / "events").read_text() != before:
        fail("a name outside watched lists was checked")

    # No watch file: no map.
    (tmp / "lists.conf").unlink()
    sh("map")
    if (tmp / "vol/list-watch.map").exists():
        fail("without watch switches the map must be removed")

print("LIST_WATCH=PASS")
