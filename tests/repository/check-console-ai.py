#!/usr/bin/env python3
"""«ИИ-сервисы» and Smart DNS without AdGuard Home (fix.30): the owner's own DoH server comes on
stdin and is never printed or journaled; without AdGuard Home a Smart DNS domain becomes a line
in Keenetic of the same form as the lines already there, at most 8; an AI service set to Smart
DNS gets its main domains there and loses them on «Провайдер»; the API passes the address
through stdin and shows only the server's host."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
TOKEN = "SYNTHETIC-TOKEN-1234"
OWN = f"https://dns.example.test/dns-query/{TOKEN}"
OLD = "https://old.example.test/dns-query"

RUNNING = "\n".join([
    "interface Wireguard0", "!",
    "dns-proxy",
    f"    https upstream {OLD} dnsm on ISP domain old.example",
    "!",
]) + "\n"

FAKE_NDMC = r'''#!/usr/bin/env python3
import sys
from pathlib import Path
cfg = Path("@CFG@")
cmd = sys.argv[2]
if cmd == "show running-config":
    print(cfg.read_text(), end=""); sys.exit(0)
if cmd == "system configuration save":
    print("saved"); sys.exit(0)
lines = cfg.read_text().splitlines()
s = lines.index("dns-proxy"); e = lines.index("!", s)
block = [l.strip() for l in lines[s + 1:e]]
w = cmd.split()
if w[:2] == ["dns-proxy", "no"]:
    line = " ".join(w[2:])
    if line not in block:
        print("Command::Base: error[7]: not found"); sys.exit(0)
    block.remove(line)
elif w[:3] == ["dns-proxy", "https", "upstream"]:
    if sum(1 for b in block if b.startswith("https upstream") and " domain " in b) >= 8:
        print("Command::Base: error[7]: limit"); sys.exit(0)
    block.append(" ".join(w[1:]))
else:
    print("Command::Base: error[7]: syntax error"); sys.exit(0)
cfg.write_text("\n".join(lines[:s + 1] + ["    " + b for b in block] + lines[e:]) + "\n")
'''

CATALOG = '{"schema": 1, "categories": [], "services": [' \
    '{"id": "chat.example", "category": "ai", "title": "Chat", "domains": ["chat.example", "api.chat.example", "cdn.chatstatic.example"]},' \
    '{"id": "video.example", "category": "video", "title": "Video", "domains": ["video.example"]}]}'

DEVICE_CONF = """VWARD_LAN_ADDRESS=10.77.0.1
VWARD_LAN_SUBNET=10.77.0.0/24
VWARD_LAN_DEVICE=br0
VWARD_LAN_INTERFACE=Bridge0
VWARD_WAN_DEVICE=eth3
VWARD_WAN_INTERFACE=GigabitEthernet1
VWARD_TUNNEL_INTERFACE=Wireguard0
VWARD_TUNNEL_DEVICE=nwg0
"""


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_AI=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tools / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    devconf = tmp / "device.conf"; devconf.write_text(DEVICE_CONF); devconf.chmod(0o600)
    cat = tmp / "catalog.json"; cat.write_text(CATALOG)
    etc = tmp / "etc"; etc.mkdir()
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_DEVICE_CONFIG": str(devconf), "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(etc),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_ADS_CONTROL_BIN": str(tmp / "no-ads-control"), "VWARD_ADGUARD_CONFIG": str(tmp / "no-adguard.yaml"),
        "VWARD_SERVICES_FETCHED": str(cat), "VWARD_SERVICES_BUNDLED": str(cat),
    }

    def run(*args, stdin=""):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True, input=stdin)
        out = r.stdout.strip().splitlines()
        if TOKEN in r.stdout or TOKEN in r.stderr:
            fail(f"{args}: the server's token was printed")
        return out[-1] if out else r.stderr.strip()[-300:]

    def doh():
        return [l.strip() for l in cfg.read_text().splitlines() if l.strip().startswith("https upstream")]

    # Without its own server: the one already used in Keenetic, in the same form.
    if run("smartdns-domain", "add", "first.example") != "result=changed" or f"https upstream {OLD} dnsm on ISP domain first.example" not in doh():
        fail(f"a line of the form already there: {doh()}")
    if run("smartdns-domain", "add", "first.example") != "result=unchanged":
        fail("a domain already in Smart DNS")

    # The owner's own server: on stdin, kept root-only, never in the journal.
    for bad in ("http://x.example/q", "https://x.example/q?x=1", "https://x.example/a b", ""):
        if run("smartdns-server", "set", stdin=bad + "\n") != "error=invalid_value":
            fail(f"{bad!r} must be refused")
    if run("smartdns-server", "set", stdin=OWN + "\n") != "result=changed":
        fail("own server")
    conf = etc / "smartdns.conf"
    if oct(conf.stat().st_mode & 0o777) != "0o600" or OWN not in conf.read_text():
        fail("the own server is kept root-only")
    if TOKEN in (tmp / "audit.log").read_text():
        fail("the token must not reach the journal")

    # An AI service on Smart DNS: its own main domains as the catalog names them (never cut to the
    # second level: aistudio.google.com gave google.com), a name inside one taken left out.
    if run("ai", "chat.example", "dns") != "result=changed":
        fail(f"ai dns: {run('ai', 'chat.example', 'dns')}")
    want = {f"https upstream {OWN} dnsm on ISP domain chat.example", f"https upstream {OWN} dnsm on ISP domain cdn.chatstatic.example"}
    if not want <= set(doh()):
        fail(f"the service's main domains through Smart DNS: {doh()}")
    if run("ai", "video.example", "dns") != "error=unknown_service" or run("ai", "chat.example", "tor") != "error=invalid_value":
        fail("only AI services and known ways")
    if run("ai", "chat.example", "isp") != "result=changed" or any("chat" in l for l in doh()):
        fail(f"«Провайдер» takes them out: {doh()}")
    if f"https upstream {OLD} dnsm on ISP domain old.example" not in doh():
        fail("the owner's other lines stay")

    # Keenetic keeps at most 8 lines.
    for i in range(6):
        run("smartdns-domain", "add", f"d{i}.example")
    if run("smartdns-domain", "add", "over.example") != "error=smartdns_keenetic_full":
        fail(f"the 9th line must be refused: {len(doh())}")
    if run("smartdns-domain", "remove", "d0.example") != "result=changed" or any(l.endswith(" d0.example") for l in doh()):
        fail("remove a Smart DNS domain from Keenetic")
    # No room for all of a service's domains (7 of 8 taken, it needs 2): the one added goes again,
    # the service stays as it was and waits for room; the Panel asks which way (fix.31).
    before = sorted(doh())
    if run("ai", "chat.example", "dns") != "error=smartdns_keenetic_full" or sorted(doh()) != before:
        fail(f"no room: nothing half-done: {doh()}")
    if (etc / "smartdns-wait").read_text().split() != ["chat.example"]:
        fail("a service with no room waits for Smart DNS")
    if run("ai", "chat.example", "isp", "keep") != "result=changed" or not (etc / "smartdns-wait").exists():
        fail("the answer to the question keeps it waiting")
    if run("ai", "chat.example", "isp") != "result=changed" or (etc / "smartdns-wait").exists():
        fail("a way chosen by the owner ends the wait")
    if run("smartdns-server", "clear") != "result=changed" or conf.exists():
        fail("clear the own server")

    API = (ROOT / "web/cgi-bin/api.cgi").read_text()
    for need in ('printf \'%s\\n\' "$SSURL" | "$CONFIG_HELPER" smartdns-server "$SSOP"', 'if [ "$ACTION" = ai-data ]; then',
                 'sub(/[\\/:].*$/, "", h)', 'ai) case "$STO" in dns|isp) ARGS="ai $SID $STO"'):
        if need not in API:
            fail(f"the API lacks {need}")

# The Panel finds the same main domains as the helper (one rule in two languages, one shared list).
import re as _re
helper = (ROOT / "components/console/scripts/vward-console-config.sh").read_text()
shared = _re.search(r"^AI_SHARED=.*$", helper, _re.M).group(0)
if shared not in API:
    fail("the API and the helper must share one list of platforms")
cat = ROOT / "components/console/data/services-catalog.json"
fn = helper[helper.index("ai_main() {"):helper.index("\n}\n", helper.index("ai_main() {")) + 3]
sh_out = subprocess.run(["sh", "-c", shared + "\nJQ=jq; SV_CAT=" + str(cat) + "\n" + fn +
    "for i in $(jq -r '.services[] | select(.category == \"ai\") | .id' \"$SV_CAT\"); do echo \"$i $(ai_main \"$i\" | tr '\\n' ' ')\"; done"],
    text=True, capture_output=True).stdout
jq_def = API[API.index("def main($id; $ds)"):API.index(".[:4];", API.index("def main($id; $ds)")) + 6]
jq_out = subprocess.run(["jq", "-r", "--arg", "shared", shared.split("=", 1)[1].strip('"'), jq_def +
    ' .services[] | select(.category == "ai") | "\\(.id) \\(main(.id; .domains) | map(. + " ") | add // "")"', str(cat)], text=True, capture_output=True).stdout
if sh_out.split("\n") != jq_out.split("\n") or "google.com" in sh_out.split():
    fail(f"main domains differ between the helper and the API:\n{sh_out}\n{jq_out}")
print("CONSOLE_AI=PASS")
