#!/usr/bin/env python3
"""VLESS engine: links and subscriptions (plain or base64) give the servers without their
ids; a link becomes an Xray configuration on Keenetic's adapter (TUN inbound, VLESS
outbound with REALITY / TLS, tcp / ws / grpc / xhttp); an unsupported one is refused; a
tunnel is added on a free OpkgTun with a private /30, kept only when a page opens through
it, and removed with everything it made; the id never reaches a log, an argument or the
output; the Xray archive is checked against its pinned SHA-256."""

import base64
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "components/tunnel-guard/scripts/vward-vless-engine.sh"
UUID = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
REALITY = (f"vless://{UUID}@203.0.113.5:443?encryption=none&security=reality&sni=www.example.com&fp=chrome"
           "&pbk=q8eLHyKpXj2nqzF8h2m6o6VwM2vIxQoT2rj3Zy1v0Ww&sid=ab12&type=tcp&flow=xtls-rprx-vision#%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F")
WS = f"vless://{UUID}@vpn.example.org:8443?security=tls&type=ws&path=%2Fws&host=vpn.example.org#WS"
GRPC = f"vless://{UUID}@[2001:db8::1]:443?security=tls&sni=g.example&type=grpc&serviceName=gun#gRPC"
KCP = f"vless://{UUID}@203.0.113.9:443?security=none&type=kcp#KCP"


def fail(message: str) -> None:
    raise SystemExit(f"VLESS_ENGINE=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bin_ = tmp / "bin"; bin_.mkdir()
    etc, share, run_ = tmp / "etc", tmp / "share", tmp / "run"
    (tmp / "rc").write_text("interface OpkgTun0\n!\n")
    (bin_ / "ndmc").write_text(f'#!/bin/sh\necho "$2" >> "{tmp}/ndmc.log"\n[ "$2" = "show running-config" ] && cat "{tmp}/rc"\n'
                               f'[ -e "{tmp}/refuse" ] && grep -q "$(cat "{tmp}/refuse")" <<EOF\n$2\nEOF\n'
                               '[ $? = 0 ] && [ -e "' + str(tmp) + '/refuse" ] && echo "error: refused"\nexit 0\n')
    # curl: the subscription (served), the connection check through an adapter, the archive.
    (bin_ / "curl").write_text(f"""#!/bin/sh
echo "$*" >> "{tmp}/curl.log"
out=; dev=; url=
while [ $# -gt 0 ]; do case "$1" in -o) out=$2; shift ;; --interface) dev=$2; shift ;; http*) url=$1 ;; esac; shift; done
case "$url" in
    https://sub.example/*) [ -f "{tmp}/sub" ] || exit 22; cp "{tmp}/sub" "$out" ;;
    https://xray.example/*) cp "{tmp}/x.zip" "$out" ;;
    *) [ -n "$dev" ] && [ -e "{tmp}/up.$dev" ] && exit 0; exit 7 ;;
esac
""")
    for f in bin_.iterdir():
        f.chmod(0o755)
    env = os.environ | {"PATH": f"{bin_}:{os.environ['PATH']}", "VWARD_VLESS_ETC": str(etc), "VWARD_VLESS_SHARE": str(share),
                        "VWARD_VLESS_RUN": str(run_), "VWARD_VLESS_LOG": str(tmp / "engine.log"), "VWARD_NDMC": str(bin_ / "ndmc"),
                        "VWARD_CURL_BIN": str(bin_ / "curl"), "JQ": shutil.which("jq"), "VWARD_VLESS_CONNECT_WAIT": "4",
                        "VWARD_XRAY_URL": "https://xray.example/d", "VWARD_VLESS_ARCH": "mipsle"}

    def engine(*args):
        r = subprocess.run(["sh", str(ENGINE), *args], env=env, text=True, capture_output=True, timeout=120)
        return r.stdout.splitlines()

    def servers(text):
        f = tmp / "in.txt"; f.write_text(text)
        return engine("servers", str(f))

    out = servers(REALITY + "\n" + WS + "\n" + GRPC + "\n")
    want = ["info.server.1=Германия|203.0.113.5|443|reality|tcp", "info.server.2=WS|vpn.example.org|8443|tls|ws",
            "info.server.3=gRPC|2001:db8::1|443|tls|grpc", "info.kind=vless", "info.servers=3", "result=checked"]
    if out != want:
        fail(f"servers of links: {out}")
    (tmp / "sub").write_text(base64.b64encode((WS + "\n" + REALITY + "\n").encode()).decode())
    if servers("https://sub.example/s/abc\n")[:2] != ["info.server.1=WS|vpn.example.org|8443|tls|ws", "info.server.2=Германия|203.0.113.5|443|reality|tcp"]:
        fail("a base64 subscription")
    (tmp / "sub").write_text(GRPC + "\n")
    if servers("https://sub.example/s/plain\n")[0] != "info.server.1=gRPC|2001:db8::1|443|tls|grpc":
        fail("a plain subscription")
    (tmp / "sub").unlink()
    if servers("https://sub.example/s/gone\n") != ["error=subscription_unavailable"]:
        fail("an unreachable subscription")
    for bad in ("hello\n", "vmess://abc\n", "https://sub example/x\n"):
        if servers(bad) != ["error=vless_syntax"]:
            fail(f"{bad!r} must be refused")
    if UUID in "\n".join(servers(REALITY)):
        fail("the id must never be printed")

    # The configuration a link gives (the functions as they are in the engine).
    src = ENGINE.read_text()
    funcs = src[src.index("parse() {"):src.index("# chosen FILE LINKS")]
    (tmp / "cfg.sh").write_text(f'JQ={shutil.which("jq")}\n{funcs}\nconfig "$1" opkgtun3 "$2"\n')

    def config(link):
        out = tmp / "c.json"; out.unlink(missing_ok=True)
        r = subprocess.run(["sh", str(tmp / "cfg.sh"), link, str(out)], text=True, capture_output=True)
        return json.loads(out.read_text()) if r.returncode == 0 else None

    c = config(REALITY)
    ob = c["outbounds"][0]
    if c["inbounds"] != [{"tag": "tun", "port": 0, "protocol": "tun", "settings": {"name": "opkgtun3", "mtu": 1400}}]:
        fail(f"TUN inbound on Keenetic's adapter: {c['inbounds']}")
    if ob["settings"]["vnext"][0] != {"address": "203.0.113.5", "port": 443, "users": [{"id": UUID, "encryption": "none", "flow": "xtls-rprx-vision"}]}:
        fail(f"vless server: {ob['settings']}")
    if ob["streamSettings"] != {"network": "tcp", "security": "reality", "realitySettings": {"serverName": "www.example.com", "fingerprint": "chrome",
                                "publicKey": "q8eLHyKpXj2nqzF8h2m6o6VwM2vIxQoT2rj3Zy1v0Ww", "shortId": "ab12", "spiderX": ""}}:
        fail(f"reality: {ob['streamSettings']}")
    ws = config(WS)["outbounds"][0]["streamSettings"]
    if ws != {"network": "ws", "security": "tls", "tlsSettings": {"serverName": "vpn.example.org"}, "wsSettings": {"path": "/ws", "host": "vpn.example.org"}}:
        fail(f"ws + tls: {ws}")
    g = config(GRPC)["outbounds"][0]
    if g["settings"]["vnext"][0]["address"] != "2001:db8::1" or g["streamSettings"]["grpcSettings"] != {"serviceName": "gun"}:
        fail(f"grpc on IPv6: {g}")
    for bad in (KCP, f"vless://{UUID}@203.0.113.9:0?security=none#P", "vless://x y@203.0.113.9:443#I", f"vless://{UUID}@203.0.113.9:443?security=xtls#S"):
        if config(bad) is not None:
            fail(f"{bad} must be refused")

    # Adding: a stand-in Xray that is already installed.
    share.mkdir(parents=True)
    (share / "xray").write_text(f'#!/bin/sh\necho "$*" >> "{tmp}/xray.args"\n[ "$1 $2" = "run -test" ] && exit 0\nexec sleep 300\n')
    (share / "xray").chmod(0o755)
    (share / "version").write_text(src.split("XRAY_VERSION=", 1)[1].split("\n", 1)[0] + "\n")
    link = tmp / "link.txt"
    link.write_text("#server=2\n" + WS + "\n" + REALITY + "\n")
    (tmp / "up.opkgtun1").write_text("")
    out = engine("add", "", str(link))
    if out[-2:] != ["info.name=OpkgTun1", "result=changed"]:
        fail(f"add: {out}")
    cmds = (tmp / "ndmc.log").read_text()
    for need in ("interface OpkgTun1\n", 'interface OpkgTun1 description "Германия"', "interface OpkgTun1 ip address 198.18.1.1 255.255.255.252",
                 "interface OpkgTun1 up", "system configuration save"):
        if need not in cmds:
            fail(f"Keenetic lacks {need!r}: {cmds}")
    conf = etc / "v0.json"
    if oct(conf.stat().st_mode & 0o777) != "0o600" or json.loads(conf.read_text())["inbounds"][0]["settings"]["name"] != "opkgtun1":
        fail("the configuration is root-only and on the adapter")
    row = (etc / "tunnels.tsv").read_text()
    if row != "0\tOpkgTun1\t203.0.113.5:443\tГермания\n":
        fail(f"tunnels.tsv: {row!r}")
    everything = cmds + row + (tmp / "engine.log").read_text() + (tmp / "xray.args").read_text() + "\n".join(out)
    if UUID in everything:
        fail("the id leaked into a command, a log or the output")
    st = engine("status")
    if not any(l.startswith("tunnel=OpkgTun1\t1\t") and l.endswith("\t203.0.113.5:443\tГермания\t0") for l in st):
        fail(f"status: {st}")
    # A server that never answers: nothing stays.
    (tmp / "rc").write_text("interface OpkgTun0\n!\ninterface OpkgTun1\n!\n")
    (tmp / "ndmc.log").write_text("")
    out = engine("add", "Финляндия", str(link))
    if out != ["error=tunnel_no_handshake"] or "no interface OpkgTun2" not in (tmp / "ndmc.log").read_text() or (etc / "v1.json").exists():
        fail(f"a silent server must be undone: {out}")
    # Removal.
    out = engine("remove", "OpkgTun1")
    if out != ["result=changed"] or conf.exists() or (etc / "tunnels.tsv").read_text() != "" or "no interface OpkgTun1" not in (tmp / "ndmc.log").read_text():
        fail(f"remove: {out}")
    engine("stop")

    # The archive: a wrong checksum is refused, nothing installed.
    shutil.rmtree(share)
    with zipfile.ZipFile(tmp / "x.zip", "w") as z:
        z.writestr("xray_softfloat", "#!/bin/sh\necho Xray\n")
    if engine("install") != ["error=checksum_mismatch"] or (share / "xray").exists():
        fail("an archive with another checksum must be refused")
    env["VWARD_VLESS_ARCH"] = "x86"
    if engine("install") != ["error=arch_unsupported"]:
        fail("an unknown processor")

# The Panel, the helper and the health check use it.
helper = (ROOT / "components/console/scripts/vward-console-config.sh").read_text()
for need in ("op_tunnel_vless()", '"$VLESS_ENGINE" servers', '"$VLESS_ENGINE" add', "VLESS_TUNNELS"):
    if need not in helper:
        fail(f"the helper lacks {need}")
js = (ROOT / "web/assets/vward-console.js").read_text()
for need in ("'#server=' + num", "vlessOf(", "name=\"vless-server\""):
    if need not in js:
        fail(f"the Panel lacks {need}")
if "vward-vless-engine.sh supervise" not in (ROOT / "components/tunnel-guard/scripts/vward-tunnel-health.sh").read_text():
    fail("a stopped Xray is not started again")
print("VLESS_ENGINE=PASS")
