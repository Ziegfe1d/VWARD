#!/usr/bin/env python3
"""Panel «Проверить сайт»: site-test opens the site through the provider and every VPN
connection to one address, says opens / blocked / no answer, refuses a bad name; the
Panel shows it first on «Сеть» and «Домены» with «Сайт не открывается»; a tunnel can be
restarted (nothing saved) or switched on after Keenetic switched it off (saved)."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_SITE_TEST=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    for dev in ("eth3", "nwg0", "nwg1"):
        (tmp / "sys" / dev).mkdir(parents=True)
    (tools / "resolve4").write_text("#!/bin/sh\n[ \"$1\" = nx.example ] && exit 1\nprintf 'Name: %s\\nAddress 1: 203.0.113.9\\n' \"$1\"\n")
    # The provider gets no answer, Wireguard0 a 451 page, Wireguard1 the site.
    (tools / "curl").write_text(f"""#!/bin/sh
echo "$*" >> "{tmp}/curl.args"
dev=
while [ $# -gt 0 ]; do [ "$1" = --interface ] && dev=$2; shift; done
case "$dev" in eth3) printf '000 6.001 '; exit 28 ;; nwg0) printf '451 0.210 ' ;; nwg1) printf '200 0.180 ' ;; esac
""")
    for f in ("resolve4", "curl"):
        (tools / f).chmod(0o755)
    (tmp / "profile.sh").write_text(
        "vward_profile_load(){ VWARD_WAN_DEVICE=eth3; return 0; }\nvward_valid_ifname(){ case \"$1\" in ''|*[!A-Za-z0-9_.:-]*) return 1;; esac; }\n"
        "vward_valid_ipv4(){ printf '%s\\n' \"$1\" | grep -Eq '^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$'; }\n"
        "vward_device_map(){ printf 'I\\tWireguard0\\twireguard\\tnwg0\\nI\\tWireguard1\\twireguard\\tnwg1\\nI\\tISP\\tethernet\\teth3\\n'; }\n"
        "vward_map_vpns(){ printf '%s\\n' \"$1\" | awk -F '\\t' '$1==\"I\" && tolower($3)==\"wireguard\" {print $2 \" \" $4}'; }\n")
    env = os.environ | {"REQUEST_METHOD": "GET", "JQ": shutil.which("jq"), "CURL": str(tools / "curl"),
                        "VWARD_RESOLVE4_BIN": str(tools / "resolve4"), "VWARD_SYSFS_NET": str(tmp / "sys"),
                        "VWARD_PROFILE_LIB": str(tmp / "profile.sh"), "VWARD_ROOT_PREFIX": str(tmp / "root")}

    def site(domain):
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env | {"QUERY_STRING": "action=site-test&domain=" + domain},
                           text=True, capture_output=True, timeout=60)
        if r.returncode != 0:
            fail(f"{domain}: rc={r.returncode} {r.stderr}")
        return json.loads(r.stdout.split("\n\n", 1)[1])

    got = site("Example.COM")
    want = {"ok": True, "domain": "example.com", "ip": "203.0.113.9", "results": [
        {"via": "direct", "device": "eth3", "code": 0, "ms": 6001, "verdict": "none"},
        {"via": "Wireguard0", "device": "nwg0", "code": 451, "ms": 210, "verdict": "blocked"},
        {"via": "Wireguard1", "device": "nwg1", "code": 200, "ms": 180, "verdict": "open"}]}
    if got != want:
        fail(f"result: {got}")
    args = (tmp / "curl.args").read_text()
    if args.count("--resolve example.com:443:203.0.113.9") != 3 or "--interface nwg1" not in args:
        fail(f"every path must go to the same address on its own device: {args}")
    if site("nx.example").get("error") != "domain_not_resolved":
        fail("a name without an address")
    for bad in ("a;reboot", "../x", "", "-x.example", "a..b"):
        if site(bad).get("error") != "invalid_domain":
            fail(f"{bad!r} must be refused")

js = (ROOT / "web/assets/vward-console.js").read_text()
for need in ("return loadError(['route']) + sitePanel()", "return loadError(['status']) + sitePanel()", "apiGet('site-test'",
             "btn('site-fix'", "function siteFix(", "op: 'restart', name: tun", "btn('tunnel-up'", "btn('tunnel-restart'"):
    if need not in js:
        fail(f"the Panel lacks {need}")
helper = (ROOT / "components/console/scripts/vward-console-config.sh").read_text()
for need in ("tunnel-state) op_tunnel_state", 'ndm "interface $2 down"', "save_router || die config_save_failed"):
    if need not in helper:
        fail(f"the helper lacks {need}")
# «Перезапустить» saves nothing: the save is only on «Включить».
body = helper[helper.index("op_tunnel_state() {"):helper.index("op_tunnel_delete() {")]
if body.count("save_router") != 1 or 'if [ "$1" = up ]; then' not in body:
    fail("a restart must not save the router's settings")
print("CONSOLE_SITE_TEST=PASS")
