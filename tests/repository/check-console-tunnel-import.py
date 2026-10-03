#!/usr/bin/env python3
"""Adding a tunnel in the Panel: an Amnezia key (vpn://) is decoded in the browser - a key to one's own
server gives its .conf, a Premium key (access key to Amnezia's servers only) is explained and not
imported; a file already on the router asks «replace / add new / cancel»; a silent server asks
«add anyway»; every message stays in the form (a toast was gone in seconds).  Synthetic keys only."""

import base64
import json
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_TUNNEL_IMPORT=FAIL: {message}")


def key(obj, compress=True):
    raw = json.dumps(obj).encode()
    body = struct.pack(">I", len(raw)) + zlib.compress(raw) if compress else raw
    return "vpn://" + base64.urlsafe_b64encode(body).decode().rstrip("=")


CONF = "[Interface]\nPrivateKey = " + "A" * 42 + "A=\nAddress = 10.8.1.2/32\nDNS = $PRIMARY_DNS, $SECONDARY_DNS\n\n[Peer]\nPublicKey = " + "B" * 42 + "A=\nAllowedIPs = 0.0.0.0/0\nEndpoint = 203.0.113.9:51820\n"
PREMIUM = {"name": "Premium", "description": "Premium", "api_config": {"service_type": "amnezia-premium", "service_protocol": "awg"}, "auth_data": {"api_key": "x" * 45}}
OWN = {"name": "Home server", "description": "Home server", "dns1": "9.9.9.9", "dns2": "1.1.1.1", "defaultContainer": "amnezia-awg",
       "containers": [{"container": "amnezia-awg", "awg": {"last_config": json.dumps({"config": CONF})}}]}
OTHER = {"name": "x", "containers": [{"container": "amnezia-xray", "xray": {"last_config": "{}"}}]}

a = JS.index("const confName = n =>")
b = JS.index("function tunnelConfSheet(mode, name) {")
code = JS[a:b]
node = shutil.which("node")
if not node:
    print("CONSOLE_TUNNEL_IMPORT=SKIPPED: no node")
    raise SystemExit(0)
cases = {"premium": key(PREMIUM), "own": key(OWN), "own_plain": key(OWN, compress=False), "other": key(OTHER), "broken": "vpn://@@@@"}
script = code + "\n(async () => { const k = " + json.dumps(cases) + "; const o = {}; for (const n in k) o[n] = await amneziaKey(k[n]); console.log(JSON.stringify(o)); })();\n"
with tempfile.TemporaryDirectory() as t:
    f = Path(t) / "k.js"; f.write_text(script)
    r = subprocess.run([node, str(f)], text=True, capture_output=True, timeout=60)
if r.returncode != 0:
    fail(f"node: {r.stderr[-400:]}")
res = json.loads(r.stdout)
if "Premium" not in res["premium"].get("error", "") or "conf" in res["premium"]:
    fail(f"a Premium key must be explained, not imported: {res['premium']}")
for name in ("own", "own_plain"):
    c = res[name].get("conf", "")
    if "[Interface]" not in c or "DNS = 9.9.9.9, 1.1.1.1" not in c or res[name].get("name") != "Home server":
        fail(f"a key to one's own server gives its .conf with the DNS filled in: {name} {res[name]}")
if "amnezia-xray" not in res["other"].get("error", ""):
    fail(f"a key without WireGuard/AmneziaWG names what it holds: {res['other']}")
if "повреждён" not in res["broken"].get("error", ""):
    fail(f"a broken key: {res['broken']}")

# The form: messages stay in it, the questions exist.
handler = JS[JS.index("  if (f === 'tunnel-conf') {"):JS.index("  if (f === 'agh-connect') {")]
if "toast(" in handler:
    fail("the add form must keep its messages in the form, not in a toast")
for need in ("tcDup(form, x, text, desc)", "x.same || x.sameaddr", "tcPreview(form, x, mode, name)"):
    if need not in handler:
        fail(f"the add form lacks {need}")
for need in ("function tcDup(", "data-choice=\"replace\"", "data-choice=\"new\"", "data-choice=\"cancel\"", "const canReplace = kind === 'firmware' || kind === 'awg', canNew = !taken;",
             "else if (a === 'tc-dup')", "else if (a === 'tun-keep')", "let TUN_KEEP = null;", "r.code === 'tunnel_no_handshake' && !fields.keep",
             "Object.assign({}, k.fields, { keep: '1' })", "'Добавить всё равно'", "'Заменить всё равно'", "i.handshake === 'none'",
             "code: /^error=/.test(last) ? last.slice(6) : ''"):
    if need not in JS:
        fail(f"the Panel lacks {need}")
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
for need in ('TKEEP=""; [ "$(form_value keep)" != 1 ] || TKEEP=" keep"', 'tunnel-conf replace $TFILE $TNAME$TKEEP', 'tunnel-conf create $TFILE @$TFILE.desc$TKEEP'):
    if need not in API:
        fail(f"the API lacks {need}")
print("CONSOLE_TUNNEL_IMPORT=PASS")
