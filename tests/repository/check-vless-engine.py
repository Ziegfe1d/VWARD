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
                        "VWARD_CURL_BIN": str(bin_ / "curl"), "JQ": shutil.which("jq"), "VWARD_VLESS_CONNECT_WAIT": "4", "VWARD_ENGINE_COOLDOWN": "0",
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
    mixed = servers(REALITY + "\ntrojan://pw@t.example:8443?security=tls&type=tcp#Trojan\n")
    if mixed[:2] != ["info.server.1=Германия|203.0.113.5|443|reality|tcp", "info.server.2=Trojan|t.example|8443|tls|tcp"]:
        fail(f"trojan links are servers too: {mixed}")
    (tmp / "sub").write_text(base64.b64encode(("trojan://pw@t.example:443?type=ws#T\n" + WS + "\n").encode()).decode())
    if [x.split("|")[0] for x in servers("https://sub.example/s/mixed\n")[:2]] != ["info.server.1=T", "info.server.2=WS"]:
        fail("a subscription with trojan and vless")
    (tmp / "sub").unlink()
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
    # xHTTP «extra» (the server's padding obfuscation, xmux) and gRPC multi mode / authority
    # go into Xray's settings: without them the server cuts the connection (Viva 2026-10-04).
    import urllib.parse
    extra = {"xPaddingObfsMode": True, "xPaddingKey": "k", "uplinkHTTPMethod": "PUT", "xmux": {"maxConcurrency": "16-32"}}
    xh = (f"vless://{UUID}@x.example:443?encryption=none&type=xhttp&path=%2F&host=x.example&mode=auto"
          f"&extra={urllib.parse.quote(json.dumps(extra))}&security=tls&sni=x.example&fp=chrome&alpn=h2%2Chttp%2F1.1#X")
    st = config(xh)["outbounds"][0]["streamSettings"]
    if st["xhttpSettings"] != {"path": "/", "host": "x.example", "mode": "auto", "extra": extra}:
        fail(f"xhttp extra: {st['xhttpSettings']}")
    if st["tlsSettings"] != {"serverName": "x.example", "fingerprint": "chrome", "alpn": ["h2", "http/1.1"]}:
        fail(f"xhttp tls: {st['tlsSettings']}")
    if "extra" in config(xh.replace("&extra=", "&extra=not-json"))["outbounds"][0]["streamSettings"]["xhttpSettings"]:
        fail("a broken extra is left out, not passed on")
    gm = config(f"vless://{UUID}@g.example:443?type=grpc&serviceName=gun&mode=multi&authority=a.example&security=tls#G")
    if gm["outbounds"][0]["streamSettings"]["grpcSettings"] != {"serviceName": "gun", "multiMode": True, "authority": "a.example"}:
        fail(f"grpc multi / authority: {gm['outbounds'][0]['streamSettings']['grpcSettings']}")
    # Trojan (a subscription mixes it with VLESS): a password instead of the id, TLS by default.
    tj = config("trojan://p%40ss-w0rd@t.example:443?type=ws&path=%2Fws&host=t.example&sni=t.example#France-1h")
    if tj is None or tj["outbounds"][0]["protocol"] != "trojan" or \
            tj["outbounds"][0]["settings"] != {"servers": [{"address": "t.example", "port": 443, "password": "p@ss-w0rd"}]}:
        fail(f"trojan server: {tj and tj['outbounds'][0]}")
    if tj["outbounds"][0]["streamSettings"] != {"network": "ws", "security": "tls", "tlsSettings": {"serverName": "t.example"},
                                                "wsSettings": {"path": "/ws", "host": "t.example"}}:
        fail(f"trojan ws + tls: {tj['outbounds'][0]['streamSettings']}")
    if config("trojan://two%20words@t.example:443#T") is not None:
        fail("a trojan password with a space is refused")
    for bad in (KCP, f"vless://{UUID}@203.0.113.9:0?security=none#P", "vless://x y@203.0.113.9:443#I", f"vless://{UUID}@203.0.113.9:443?security=xtls#S"):
        if config(bad) is not None:
            fail(f"{bad} must be refused")

    # Adding: a stand-in Xray that is already installed.
    share.mkdir(parents=True)
    (share / "xray").write_text(f'#!/bin/sh\necho "$*" >> "{tmp}/xray.args"\n[ "$1 $2" = "run -test" ] && exit 0\nwhile :; do sleep 1; done\n')
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
    # Keenetic switched the interface off and on (the guard does): Xray stays on an adapter
    # that carries nothing, so supervise starts it afresh. Off seen -> a mark; on again ->
    # a new Xray. A switched-on adapter through which no page opens -> a new Xray too.
    sysfs = tmp / "sys"; (sysfs / "opkgtun1").mkdir(parents=True)
    env["VWARD_SYSFS_NET"] = str(sysfs)
    pid0 = (run_ / "v0.pid").read_text()
    (sysfs / "opkgtun1/flags").write_text("0x1090\n")
    if engine("supervise") != ["result=unchanged"] or not (run_ / "v0.down").exists() or (run_ / "v0.pid").read_text() != pid0:
        fail("an adapter switched off: a mark, the program stays")
    (sysfs / "opkgtun1/flags").write_text("0x1091\n")
    if engine("supervise") != ["result=changed"] or (run_ / "v0.down").exists() or (run_ / "v0.pid").read_text() == pid0:
        fail("the adapter on again: Xray must start afresh")
    pid1 = (run_ / "v0.pid").read_text()
    if engine("supervise") != ["result=unchanged"] or (run_ / "v0.pid").read_text() != pid1:
        fail("a working tunnel must be left alone")
    (tmp / "up.opkgtun1").unlink()
    # One silent minute is only marked; the second in a row restarts Xray.
    if engine("supervise") != ["result=unchanged"] or (run_ / "v0.pid").read_text() != pid1 or not (run_ / "v0.miss").exists():
        fail("one silent minute must not restart Xray")
    if engine("supervise") != ["result=changed"] or (run_ / "v0.pid").read_text() == pid1:
        fail("no page through a switched-on adapter: Xray must start afresh")
    # Just restarted (the guard, the Panel): the minute check leaves it alone for 2 minutes.
    pid2 = (run_ / "v0.pid").read_text()
    cool = env | {"VWARD_ENGINE_COOLDOWN": "120"}
    r = subprocess.run(["sh", str(ENGINE), "supervise"], env=cool, text=True, capture_output=True, timeout=60)
    r = subprocess.run(["sh", str(ENGINE), "supervise"], env=cool, text=True, capture_output=True, timeout=60)
    if r.stdout.split() != ["result=unchanged"] or (run_ / "v0.pid").read_text() != pid2:
        fail("a program restarted within the cooldown is not restarted again")
    r = subprocess.run(["sh", str(ENGINE), "kick", "OpkgTun1"], env=cool, text=True, capture_output=True, timeout=60)
    if r.stdout.split() != ["result=unchanged"] or (run_ / "v0.pid").read_text() != pid2:
        fail(f"the guard's kick within the cooldown changes nothing: {r.stdout!r}")
    (tmp / "up.opkgtun1").write_text("")
    shutil.rmtree(sysfs / "opkgtun1")
    pid2 = (run_ / "v0.pid").read_text()
    if engine("supervise") != ["result=unchanged"] or (run_ / "v0.pid").read_text() != pid2:
        fail("no adapter to look at: nothing to do")
    if "restarted OpkgTun1 on its adapter" not in (tmp / "engine.log").read_text():
        fail("the restart on the adapter must be logged")
    del env["VWARD_SYSFS_NET"]
    # A stale pid file (Viva 2026-10-04): «restart» stopped nothing and the broken Xray lived on
    # beside a new one. Now the program is found by its configuration: one copy afterwards.
    def copies(conf):
        n = []
        for d in Path("/proc").iterdir():
            if d.name.isdigit():
                try:
                    if str(conf) in (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace") and (d / "comm").read_text().strip() == "xray":
                        n.append(d.name)
                except OSError:
                    pass
        return n
    import time as _t
    old = copies(etc / "v0.json")
    if len(old) != 1:
        fail(f"one Xray before the restart: {old}")
    (run_ / "v0.pid").write_text("999999\n")
    if engine("restart", "OpkgTun1")[-1] != "result=changed":
        fail("restart with a stale pid file")
    _t.sleep(0.5)
    now = copies(etc / "v0.json")
    if len(now) != 1 or now == old:
        fail(f"after a restart with a stale pid file exactly one new Xray runs: before {old}, after {now}")
    # A program whose tunnel is gone (removed, but not stopped) is stopped by supervise.
    fake = tmp / "fakebin"; fake.mkdir()
    (fake / "xray").write_text("#!/bin/sh\nwhile :; do sleep 1; done\n"); (fake / "xray").chmod(0o755)
    orphan = subprocess.Popen([str(fake / "xray"), "run", "-c", str(etc / "v7.json")])
    _t.sleep(0.5)
    if engine("supervise")[-1] not in ("result=unchanged", "result=changed"):
        fail("supervise with an orphan")
    _t.sleep(0.5)
    if orphan.poll() is None:
        orphan.kill(); fail("the program of a removed tunnel must be stopped")
    if "stopped the program of a removed tunnel (slot 7)" not in (tmp / "engine.log").read_text():
        fail("the stopped orphan is logged")
    if not copies(etc / "v0.json"):
        fail("the live tunnel's program must stay")
    # A server that never answers: nothing stays.
    (tmp / "rc").write_text("interface OpkgTun0\n!\ninterface OpkgTun1\n!\n")
    (tmp / "ndmc.log").write_text("")
    out = engine("add", "Финляндия", str(link))
    if out != ["error=tunnel_no_handshake"] or "no interface OpkgTun2" not in (tmp / "ndmc.log").read_text() or (etc / "v1.json").exists():
        fail(f"a silent server must be undone: {out}")
    # «keep»: the owner chose to keep it though the server is silent - it stays, and says so.
    (tmp / "ndmc.log").write_text("")
    out = engine("add", "Финляндия", str(link), "keep")
    if out[-3:] != ["info.name=OpkgTun2", "info.handshake=none", "result=changed"] or (etc / "v1.json").exists() is False or "no interface OpkgTun2" in (tmp / "ndmc.log").read_text():
        fail(f"a kept tunnel: {out}")
    out = engine("remove", "OpkgTun2")
    if out != ["result=changed"] or (etc / "v1.json").exists():
        fail(f"removing the kept tunnel: {out}")
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
guard = (ROOT / "components/tunnel-guard/scripts/vward-tunnel-guard.sh").read_text()
if guard.count('engine_kick "$VWARD_TUNNEL_INTERFACE"') != 3 or '"$ek_bin" "${2:-restart}" "$1"' not in guard:
    fail("the guard must start an engine tunnel's program afresh after it switched the interface on")
print("VLESS_ENGINE=PASS")
