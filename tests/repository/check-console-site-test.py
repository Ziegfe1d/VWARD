#!/usr/bin/env python3
"""Panel «Проверить сайт»: site-test opens the site through the provider and every VPN
connection to one address, says opens / blocked / no answer, refuses a bad name; the
Panel shows it first on «Сеть» and «Домены» with «Диагностика и восстановление»; a tunnel can be
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
    (tools / "resolve4").write_text("#!/bin/sh\n[ \"$1\" = nx.example ] && exit 1\nprintf 'Server:    10.77.0.1\\nAddress 1: 10.77.0.1\\n\\nName: %s\\nAddress 1: 203.0.113.9\\n' \"$1\"\n")
    # fix.35.3: Keenetic answers api.smart.example through Smart DNS (a line of its dns-proxy).
    (tools / "ndmc").write_text("#!/bin/sh\n[ \"$2\" = 'show running-config' ] || exit 1\nprintf 'dns-proxy\\n    https upstream https://sd.example/dns-query domain smart.example\\n!\\n'\n")
    # The provider gets no answer, Wireguard0 a 451 page, Wireguard1 the site.
    (tools / "curl").write_text(f"""#!/bin/sh
echo "$*" >> "{tmp}/curl.args"
case "$*" in *denied.example*) printf '403 0.100 '; exit 0 ;; *missing.example*) printf '404 0.100 '; exit 0 ;; *broken.example*) printf '502 0.100 '; exit 0 ;; esac
dev=
while [ $# -gt 0 ]; do [ "$1" = --interface ] && dev=$2; shift; done
case "$dev" in eth3) printf '000 6.001 '; exit 28 ;; nwg0) printf '451 0.210 ' ;; nwg1) printf '200 0.180 ' ;; esac
""")
    for f in ("resolve4", "curl", "ndmc"):
        (tools / f).chmod(0o755)
    (tmp / "profile.sh").write_text(
        "vward_profile_load(){ VWARD_WAN_DEVICE=eth3; return 0; }\nvward_valid_ifname(){ case \"$1\" in ''|*[!A-Za-z0-9_.:-]*) return 1;; esac; }\n"
        "vward_valid_ipv4(){ printf '%s\\n' \"$1\" | grep -Eq '^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$'; }\n"
        "vward_device_map(){ printf 'I\\tWireguard0\\twireguard\\tnwg0\\nI\\tWireguard1\\twireguard\\tnwg1\\nI\\tISP\\tethernet\\teth3\\n'; }\n"
        "vward_map_vpns(){ printf '%s\\n' \"$1\" | awk -F '\\t' '$1==\"I\" && tolower($3)==\"wireguard\" {print $2 \" \" $4}'; }\n")
    env = os.environ | {"REQUEST_METHOD": "GET", "JQ": shutil.which("jq"), "CURL": str(tools / "curl"),
                        "VWARD_RESOLVE4_BIN": str(tools / "resolve4"), "VWARD_SYSFS_NET": str(tmp / "sys"),
                        "VWARD_PROFILE_LIB": str(tmp / "profile.sh"), "VWARD_ROOT_PREFIX": str(tmp / "root"),
                        "VWARD_NDMC": str(tools / "ndmc"), "VWARD_CONSOLE_CACHE_TTL": "0"}

    def site(domain):
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env | {"QUERY_STRING": "action=site-test&domain=" + domain},
                           text=True, capture_output=True, timeout=60)
        if r.returncode != 0:
            fail(f"{domain}: rc={r.returncode} {r.stderr}")
        return json.loads(r.stdout.split("\n\n", 1)[1])

    got = site("Example.COM")
    want = {"ok": True, "domain": "example.com", "ip": "203.0.113.9", "dns": "10.77.0.1", "smartdns": False, "results": [
        {"via": "direct", "device": "eth3", "code": 0, "ms": 6001, "verdict": "none"},
        {"via": "Wireguard0", "device": "nwg0", "code": 451, "ms": 210, "verdict": "blocked"},
        {"via": "Wireguard1", "device": "nwg1", "code": 200, "ms": 180, "verdict": "open"}]}
    if got != want:
        fail(f"result: {got}")
    args = (tmp / "curl.args").read_text()
    if args.count("--resolve example.com:443:203.0.113.9") != 3 or "--interface nwg1" not in args:
        fail(f"every path must go to the same address on its own device: {args}")
    # fix.35.3: only a page or a redirect «opens»; 403, 404 and server errors are named as they are.
    for dom, verdict in (("denied.example", "denied"), ("missing.example", "answer"), ("broken.example", "error")):
        if {r["verdict"] for r in site(dom)["results"]} != {verdict}:
            fail(f"RED: {dom} must be {verdict}, not «opens»: {site(dom)}")
    # A Smart DNS domain (or below one): the address may be the Smart DNS proxy's - said so.
    if site("api.smart.example").get("smartdns") is not True or site("notsmart.example").get("smartdns") is not False:
        fail("the probe must say when the address came for a Smart DNS domain")
    if site("nx.example").get("error") != "domain_not_resolved":
        fail("a name without an address")
    for bad in ("a;reboot", "../x", "", "-x.example", "a..b"):
        if site(bad).get("error") != "invalid_domain":
            fail(f"{bad!r} must be refused")

js = (ROOT / "web/assets/vward-console.js").read_text()
for need in ("return loadError(['route']) + sitePanel()", "apiGet('site-test'",
             "btn('site-fix'", "function siteFix(", "await tunnelState('restart', tun)", "btn('tunnel-up'", "btn('tunnel-restart'",
             "])) + adsCheckPanel() + aghTopPanel() +", "view: 'check'", "setting: 'user-rule'"):
    if need not in js:
        fail(f"the Panel lacks {need}")
helper = (ROOT / "components/console/scripts/vward-console-config.sh").read_text()
for need in ("tunnel-state) op_tunnel_state", 'ndm "interface $2 down"', "save_router || die config_save_failed"):
    if need not in helper:
        fail(f"the helper lacks {need}")
# «Перезапустить» saves nothing: the save is only on «Включить» and «Выключить».
body = helper[helper.index("op_tunnel_state() {"):helper.index("op_tunnel_delete() {")]
down = body[body.index('if [ "$1" = down ]; then'):body.index('done_ok "tunnel-state down $2" changed')]
if body.count("save_router") != 2 or down.count("save_router") != 1 or '[ "$1" != up ] || save_router' not in body:
    fail("a restart must not save the router's settings")
# One address check: in «Маршрутизация» only; the Ads page's is «Проверка блокировки» (owner 2026-10-12).
if js.count("sitePanel()") != 2 or "panel('Проверка блокировки', inputBar({ form: 'ads-check'" not in js:
    fail("the address check stands once (routing), the ads check is named for what it does")
# fix.35.3.1: «проверяется…» always ends - an error clears it, and the late answer of an older check
# is not taken for the result of the new one.
a = js.index("let AISEQ = 0;"); b = js.index("\n}\n", js.index("async function aiCheck(")) + 3
script = "const AICHK = {}; const render = () => {}; let calls = [];\n" \
    "function apiGet(a, q) { return new Promise((ok, no) => calls.push({ ok, no })); }\n" + js[a:b] + """
(async () => {
  const p1 = aiCheck('x', 'x.example'), p2 = aiCheck('x', 'x.example');
  calls[1].ok({ ok: true, results: [{ via: 'direct', verdict: 'open', code: 200 }] }); await p2;
  calls[0].ok({ ok: true, results: [{ via: 'direct', verdict: 'none', code: 0 }] }); await p1;
  const kept = AICHK.x.results[0].verdict;
  const p3 = aiCheck('y', 'y.example'); calls[2].no(new Error('роутер не передал ответ за 20 секунд')); await p3;
  console.log(JSON.stringify({ kept, busy: !!AICHK.y.busy, why: AICHK.y.why }));
})();"""
r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
o = json.loads(r.stdout or "{}")
if o != {"kept": "open", "busy": False, "why": "роутер не передал ответ за 20 секунд"}:
    fail(f"RED: a check must end and keep its own answer: {r.stdout} {r.stderr[-300:]}")
print("CONSOLE_SITE_TEST=PASS")
