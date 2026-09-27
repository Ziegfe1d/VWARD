#!/usr/bin/env python3
"""Every page of the Panel has its own address, and the address opens that page.

The page registry and the address functions run in node: every section, detail
and event page gets a unique path, the path leads back to the same page, and
the pages made from router data (a tunnel, a list, its addresses, a Wi-Fi
device) do too.  The web server answers any other path with the page itself.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
CONF = (ROOT / "web/lighttpd.conf").read_text()


def fail(msg):
    raise SystemExit(f"CONSOLE_ADDRESSES=FAIL: {msg}")


if 'server.error-handler-404 = "/index.html"' not in CONF:
    fail("the web server must answer a page address with the Panel")
if "'#' + " in JS:
    fail("an address is still made with #")
if not shutil.which("node"):
    print("CONSOLE_ADDRESSES=SKIPPED (node not found)")
    sys.exit(0)

seg = JS[JS.index("const PAGES = ["):JS.index("const navId")]
act = re.findall(r"^  ([a-z]+): \{ title: '[^']*', parent: '([a-z0-9-]+)'", JS.split("const ACTIVITY = {", 1)[1].split("\n};", 1)[0], re.M)
harness = """
const S = { lists: null }; const st = () => ({}); const tunLabel = n => n; const wifiName = n => n;
""" + seg + """
ACT.forEach(([k, p]) => { DETAILS['a-' + k] = { title: k, parent: p }; });
const ids = PAGES.map(x => x.id).concat(Object.keys(DETAILS)), seen = {}, bad = [];
ids.forEach(id => { const p = pathOf(id); if (seen[p]) bad.push('same address ' + p + ': ' + seen[p] + ', ' + id); seen[p] = id;
  if (idOf(p) !== id) bad.push(id + ' -> ' + p + ' -> ' + idOf(p)); if (!/^\\/[a-z0-9\\/:._-]*$/.test(p)) bad.push('address ' + p); });
['t-Wireguard0', 't-OpenVPN0', 'l-domain-list5', 'ip-domain-list5', 'w-aa:bb:cc:dd:ee:ff'].forEach(id => { const p = pathOf(id); if (idOf(p) !== id) bad.push(id + ' -> ' + p + ' -> ' + idOf(p)); });
if (idOf('/') !== 'overview' || idOf('/nothing/here') !== null) bad.push('root or unknown address');
console.log(JSON.stringify({ n: ids.length, bad, vpn: pathOf('t-Wireguard0'), ip: pathOf('ip-domain-list5'), wifi: pathOf('w-aa:bb:cc:dd:ee:ff') }));
""".replace("ACT.forEach", "const ACT = " + json.dumps(act) + "; ACT.forEach", 1)
r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    fail(r.stderr[-800:])
got = json.loads(r.stdout)
if got["bad"]:
    fail("; ".join(got["bad"]))
if (got["vpn"], got["ip"], got["wifi"]) != ("/vpn/tunnel/Wireguard0", "/domains/lists/domain-list5/ip", "/network/wifi/aa:bb:cc:dd:ee:ff"):
    fail(f"addresses: {got}")
if got["n"] < 60:
    fail(f"too few pages: {got['n']}")
print(f"CONSOLE_ADDRESSES=PASS pages={got['n']}")
