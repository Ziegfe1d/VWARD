#!/usr/bin/env python3
"""Adding a tunnel in the Panel: an Amnezia key (vpn://) is decoded in the browser - a key to one's own
server gives its .conf, a Premium key (access key to Amnezia's servers only) is explained and not
imported; a file already on the router asks «replace / add new / cancel»; a silent server asks
«add anyway»; every message stays in the form (a toast was gone in seconds).  Synthetic keys only."""

import os
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

# Two tunnels of one address: the notification names them (Keenetic connects only one).
d0 = JS.index("function tunDupAddresses(tunnels) {")
d1 = JS.index("function plural(n, one, few, many)")
dup_js = JS[d0:d1] + "\nconsole.log(JSON.stringify([tunDupAddresses([{name:'W0',address:'10.8.16.6'},{name:'W1',address:'10.8.16.6/32'},{name:'W2',address:'10.9.0.2'},{name:'O1',address:''},{name:'V1'}]), tunDupAddresses([{name:'A',address:'10.1.1.1'},{name:'B',address:'10.1.1.2'}]), tunDupAddresses(null)]));"
with tempfile.TemporaryDirectory() as t:
    f = Path(t) / "d.js"; f.write_text(dup_js)
    r = subprocess.run([node, str(f)], text=True, capture_output=True, timeout=60)
if json.loads(r.stdout or "null") != [[{"addr": "10.8.16.6", "names": ["W0", "W1"]}], [], []]:
    fail(f"tunnels with one address: {r.stdout!r} {r.stderr[-200:]}")
if "tunDupAddresses(tunnels).forEach" not in JS or "'У двух туннелей один адрес'" not in JS:
    fail("the notification for two tunnels with one address")

# A tunnel's name: Cyrillic and other UTF-8 pass the API, emoji (flags in server names of a
# subscription) are stripped in the form before it reaches Keenetic.
td0 = JS.index("const tunDesc = ")
td1 = JS.index("\n", td0)
td_js = JS[td0:td1] + "\nconsole.log(JSON.stringify([tunDesc('\\u{1F1E9}\\u{1F1EA} Germany-28s(xHTTP)'), tunDesc('  Германия   2 '), tunDesc(null), tunDesc('x'.repeat(80)).length]));"
with tempfile.TemporaryDirectory() as t:
    f = Path(t) / "td.js"; f.write_text(td_js)
    r = subprocess.run([node, str(f)], text=True, capture_output=True, timeout=60)
if json.loads(r.stdout or "null") != ["Germany-28s(xHTTP)", "Германия 2", "", 64]:
    fail(f"a tunnel's name without emoji: {r.stdout!r} {r.stderr[-200:]}")
API_SRC = (ROOT / "web/cgi-bin/api.cgi").read_text()
if "form_decode description name" not in API_SRC or "form_decode description text" in API_SRC:
    fail("the tunnel's name is decoded as a name (UTF-8 allowed), not as ASCII text")
fd0 = API_SRC.index("form_decode()\n{")
fd1 = API_SRC.index("\n}\n", fd0) + 3
with tempfile.TemporaryDirectory() as t:
    f = Path(t) / "fd.sh"
    f.write_text("form_value() { printf '%s' \"$FV\"; }\n" + API_SRC[fd0:fd1] + "\nform_decode description name\n")
    r = subprocess.run(["sh", str(f)], text=True, capture_output=True, timeout=30,
                       env={"PATH": os.environ["PATH"], "FV": "%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F-2+%28xHTTP%29"})
    bad = subprocess.run(["sh", str(f)], text=True, capture_output=True, timeout=30,
                         env={"PATH": os.environ["PATH"], "FV": "a%22b"})
if r.returncode != 0 or r.stdout != "Германия-2 (xHTTP)":
    fail(f"a Cyrillic tunnel name passes the API: {r.returncode} {r.stdout!r}")
if bad.returncode == 0:
    fail("a quote in a tunnel's name is still refused")

# The form: messages stay in it, the questions exist.
handler = JS[JS.index("  if (f === 'tunnel-conf') {"):JS.index("  if (f === 'blocked-login') {")]
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
