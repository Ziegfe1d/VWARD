#!/usr/bin/env python3
"""Services on «Автоматически» with several tunnels: each is opened through every answering
tunnel; one its tunnel does not open moves to the fastest tunnel that opens it, one its
tunnel opens stays; a category pinned to an answering tunnel takes its services there
without a check; a service pinned itself is left alone; the Panel gets the results."""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUALITY = ROOT / "components/tunnel-guard/scripts/vward-tunnel-quality.sh"

CATALOG = {"schema": 1, "categories": [{"id": "video", "title": "Видео"}, {"id": "games", "title": "Игры"}],
           "services": [
               {"id": "tube.example", "category": "video", "title": "Tube", "domains": ["tube.example", "cdn.tube.example"]},
               {"id": "chat", "category": "video", "title": "Chat", "domains": ["long.chat.example", "chat.example"]},
               {"id": "play.example", "category": "games", "title": "Play", "domains": ["play.example"]},
               {"id": "own.example", "category": "video", "title": "Own", "domains": ["own.example"]}]}


def fail(message: str) -> None:
    raise SystemExit(f"TUNNEL_SERVICES=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bin_ = tmp / "bin"; bin_.mkdir()
    etc = tmp / "etc"; (etc / "services").mkdir(parents=True)
    qdir = tmp / "q"; qdir.mkdir()
    sdir = tmp / "s"
    (tmp / "catalog.json").write_text(json.dumps(CATALOG))
    (tmp / "profile.sh").write_text(
        "vward_profile_load(){ VWARD_WAN_DEVICE=eth3; }\n"
        "vward_valid_ipv4(){ printf '%s\\n' \"$1\" | grep -Eq '^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$'; }\n")
    (bin_ / "resolve4").write_text("#!/bin/sh\nprintf 'Name: %s\\nAddress 1: 203.0.113.7\\n' \"$1\"\n")
    # tube.example: 451 through Wireguard0, open through both others (Wireguard2 faster);
    # chat.example (its shortest domain): open everywhere.
    (bin_ / "curl").write_text(f"""#!/bin/sh
echo "$*" >> "{tmp}/curl.log"
dev=; url=
while [ $# -gt 0 ]; do [ "$1" = --interface ] && dev=$2; url=$1; shift; done
case "$url:$dev" in
    https://tube.example/:nwg0) printf '451 0.100 ' ;;
    https://tube.example/:nwg1) printf '200 0.300 ' ;;
    https://tube.example/:nwg2) printf '200 0.120 ' ;;
    https://blocked.example/:*) printf '000 3.000 '; exit 28 ;;
    *) printf '200 0.200 ' ;;
esac
""")
    (bin_ / "ndmc").write_text(f'#!/bin/sh\n[ "$2" = "show running-config" ] && {{ echo dns-proxy; sed "s/^/    /" "{tmp}/routes"; echo "!"; }}\nexit 0\n')
    (bin_ / "helper").write_text(f"""#!/bin/sh
echo "$*" >> "{tmp}/helper.log"
[ "$1" = domain-list ] || exit 64
sed -i "s/^route object-group $2 .*/route object-group $2 $3 auto/" "{tmp}/routes"
echo result=changed
""")
    for f in bin_.iterdir():
        f.chmod(0o755)
    (tmp / "routes").write_text("route object-group domain-list1 Wireguard0 auto\nroute object-group domain-list2 Wireguard0 auto\n"
                                "route object-group domain-list3 Wireguard0 auto\nroute object-group domain-list4 Wireguard0 auto\n")
    (etc / "services/enabled.tsv").write_text("tube.example\tdomain-list1\tauto\nchat\tdomain-list2\tauto\n"
                                              "play.example\tdomain-list3\tauto\nown.example\tdomain-list4\tWireguard0\n")
    (etc / "services/categories.tsv").write_text("games\tWireguard1\n")
    now = int(time.time())
    # Three tunnels answering for a while.
    (qdir / "samples.tsv").write_text("".join(f"{now - 60 * i}\tWireguard{n}\tnwg{n}\t0\t40\n" for i in range(3, 0, -1) for n in range(3)))
    env = os.environ | {"VWARD_PROFILE_LIB": str(tmp / "profile.sh"), "VWARD_TUNNEL_QUALITY_DIR": str(qdir), "VWARD_ETC": str(etc),
                        "VWARD_SERVICES_FETCHED": str(tmp / "none.json"), "VWARD_SERVICES_BUNDLED": str(tmp / "catalog.json"),
                        "VWARD_TUNNEL_SERVICES_DIR": str(sdir), "VWARD_CONSOLE_CONFIG_BIN": str(bin_ / "helper"),
                        "VWARD_RESOLVE4_BIN": str(bin_ / "resolve4"), "VWARD_NDMC": str(bin_ / "ndmc"),
                        "VWARD_CURL_BIN": str(bin_ / "curl"), "JQ": shutil.which("jq"),
                        "VWARD_TUNNEL_SPEED_FILE": str(tmp / "speed.tsv")}

    def services():
        r = subprocess.run(["sh", str(QUALITY), "services"], env=env, text=True, capture_output=True, timeout=60)
        if r.returncode != 0:
            fail(f"rc={r.returncode} {r.stderr[-300:]}")
        return {l.split("\t")[0]: l.split("\t") for l in (sdir / "state.tsv").read_text().splitlines()}

    def route(g):
        return next(l.split()[3] for l in (tmp / "routes").read_text().splitlines() if l.split()[2] == g)

    st = services()
    if route("domain-list1") != "Wireguard2" or st["tube.example"][5] != "moved" or st["tube.example"][2] != "Wireguard2":
        fail(f"a service its tunnel blocks goes to the fastest that opens it: {st.get('tube.example')}")
    if st["tube.example"][3] != "Wireguard0:blocked:100,Wireguard1:open:300,Wireguard2:open:120":
        fail(f"results per tunnel: {st['tube.example'][3]}")
    if route("domain-list2") != "Wireguard0" or st["chat"][5] != "kept" or "https://chat.example/" not in (tmp / "curl.log").read_text():
        fail(f"a service its tunnel opens stays; a name that is no domain is checked by its shortest domain: {st.get('chat')}")
    if route("domain-list3") != "Wireguard1" or st["play.example"][5] != "category" or "play.example" in (tmp / "curl.log").read_text():
        fail(f"a pinned category takes its service without a check: {st.get('play.example')}")
    if route("domain-list4") != "Wireguard0" or "own.example" in st:
        fail("a service pinned itself is left alone")
    if "--resolve tube.example:443:203.0.113.7" not in (tmp / "curl.log").read_text():
        fail("every tunnel opens the same address")
    # Again: everything is where it opens, nothing moves.
    helper_log = (tmp / "helper.log").read_text()
    st = services()
    if (tmp / "helper.log").read_text() != helper_log or st["tube.example"][5] != "kept" or st["play.example"][5] != "category":
        fail("the second check moves nothing")
    # A pinned category on a tunnel that does not answer: checked like the others, and left
    # where it is (the tunnel guard moves lists off a dead tunnel, and back).
    (qdir / "samples.tsv").write_text("".join(f"{now - 60 * i}\tWireguard{n}\tnwg{n}\t{100 if n == 1 else 0}\t40\n" for i in range(3, 0, -1) for n in range(3)))
    st = services()
    if st["play.example"][5] != "kept" or route("domain-list3") != "Wireguard1" or st["play.example"][3] != "Wireguard0:open:200,Wireguard2:open:200":
        fail(f"the category's tunnel is down: the service is checked, the guard moves it: {st.get('play.example')}")
    # One tunnel answering: nothing to choose, nothing kept.
    (qdir / "samples.tsv").write_text(f"{now - 60}\tWireguard0\tnwg0\t0\t40\n{now - 60}\tWireguard0\tnwg0\t0\t40\n")
    subprocess.run(["sh", str(QUALITY), "services"], env=env, check=True, timeout=60)
    if (sdir / "state.tsv").exists():
        fail("with one tunnel there is no choice")

    # The Panel's services-data carries the pins and the last check.
    (qdir / "samples.tsv").write_text("".join(f"{now - 60 * i}\tWireguard{n}\tnwg{n}\t0\t40\n" for i in range(3, 0, -1) for n in range(3)))
    services()
    r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], text=True, capture_output=True, timeout=60,
                       env=env | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=services-data", "VWARD_CONSOLE_ETC": str(etc),
                                  "VWARD_ROOT_PREFIX": str(tmp / "root")})
    got = json.loads(r.stdout.split("\n\n", 1)[1])
    if got.get("category_tunnels") != [{"category": "games", "tunnel": "Wireguard1"}]:
        fail(f"services-data pins: {got.get('category_tunnels')}")
    tube = next((p for p in got.get("probe", []) if p["id"] == "tube.example"), None)
    if not tube or tube["action"] != "kept" or tube["results"][0] != {"via": "Wireguard0", "verdict": "blocked", "ms": 100}:
        fail(f"services-data probe: {got.get('probe')}")

    # Due by itself: two tunnels, a service on «Автоматически», 30 minutes since the last check.
    (tmp / "sys").mkdir()
    for d in ("nwg0", "nwg1"):
        (tmp / "sys" / d).mkdir()
    (tmp / "profile.sh").write_text((tmp / "profile.sh").read_text() +
        "vward_valid_ifname(){ :; }\nvward_device_map(){ :; }\nvward_map_vpns(){ printf 'Wireguard0 nwg0\\nWireguard1 nwg1\\n'; }\n")
    (bin_ / "ping").write_text('#!/bin/sh\nprintf "3 packets transmitted, 3 packets received, 0%% packet loss\\nround-trip min/avg/max = 1/2/3 ms\\n"\n')
    (bin_ / "ping").chmod(0o755)
    senv = env | {"VWARD_PING": str(bin_ / "ping"), "VWARD_SYSFS_NET": str(tmp / "sys")}
    (sdir / "at").write_text(str(now - 600))
    subprocess.run(["sh", str(QUALITY)], env=senv, check=True, timeout=60)
    time.sleep(1)
    if (sdir / "at").read_text().strip() != str(now - 600):
        fail("checked 10 minutes ago: not again")
    (sdir / "at").write_text(str(now - 2000))
    subprocess.run(["sh", str(QUALITY)], env=senv, check=True, timeout=60)
    for _ in range(50):
        if (sdir / "at").read_text().strip() != str(now - 2000):
            break
        time.sleep(0.2)
    else:
        fail("checked 33 minutes ago: again, by itself")

js = (ROOT / "web/assets/vward-console.js").read_text()
for need in ("data-svc-cat=", "op: 'category'", "function svcProbePanel(", "Проверка через туннели"):
    if need not in js:
        fail(f"the Panel lacks {need}")
print("TUNNEL_SERVICES=PASS")
