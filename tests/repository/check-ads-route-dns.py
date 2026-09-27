#!/usr/bin/env python3
"""Routed domains are resolved through Keenetic's DNS, so its routes learn them.

Stand-ins for ndmc (Keenetic's running-config) and curl (AdGuard Home's API)
keep the router in a JSON file.  The AdGuard Home stand-in enforces the one rule
that matters: a row sending domains to Keenetic's DNS may exist only while the
router's own client (with servers of its own) exists, or queries would loop.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-route-dns.sh"
CLIENT = "Keenetic DNS (VWARD)"
SECRET = "https://smart.example/dns-query/TOKEN123"

FAKE_CURL = r'''#!/usr/bin/env python3
import json, sys, os
from pathlib import Path
p = Path(os.environ["FAKE_AGH"])
st = json.loads(p.read_text())
args = sys.argv[1:]
if "-K" in args: sys.stdin.read()
url = [a for a in args if a.startswith("http")][-1]
out = args[args.index("-o") + 1]
method = args[args.index("-X") + 1] if "-X" in args else "GET"
body = json.loads(Path(args[args.index("--data-binary") + 1][1:]).read_text()) if "--data-binary" in args else {}
path = url.split("/control/", 1)[1]
if st.get("down"): sys.exit(7)
st.setdefault("calls", []).append(method + " " + path)
def ours(r): return r.startswith("[/") and r.endswith("]192.168.1.1:53")
def check():
    rows = [r for r in st["upstream_dns"] if ours(r)]
    rc = [c for c in st["clients"] if c["name"] == "Keenetic DNS (VWARD)"]
    if rows and (not rc or any(ours(u) for u in rc[0].get("upstreams", [])) or not rc[0].get("upstreams")):
        st.setdefault("violations", []).append(method + " " + path)
def save(obj=None):
    check(); p.write_text(json.dumps(st))
    Path(out).write_text(json.dumps(obj) if obj is not None else "OK"); sys.exit(0)
if path == "dns_info" and method == "GET":
    save({"upstream_dns": st["upstream_dns"], "bootstrap_dns": ["9.9.9.10"], "upstream_mode": "parallel"})
if path == "clients" and method == "GET":
    save({"clients": st["clients"] or None, "auto_clients": []})
if method != "POST": sys.exit(22)
if path == "dns_config":
    st["upstream_dns"] = body["upstream_dns"]; save()
if path == "cache_clear": st["cache_clears"] = st.get("cache_clears", 0) + 1; save()
if path == "test_upstream_dns":
    ok = not st.get("chain_down") and any(c["name"] == "Keenetic DNS (VWARD)" for c in st["clients"])
    save({u: ("OK" if ok else "couldn't communicate") for u in body["upstream_dns"]})
ids = lambda c: {i.lower() for i in c.get("ids", [])}
if path == "clients/add":
    if any(c["name"] == body["name"] or ids(c) & ids(body) for c in st["clients"]): sys.exit(22)
    st["clients"].append(body); save()
if path == "clients/update":
    old = [c for c in st["clients"] if c["name"] == body["name"]]
    if not old or any(c is not old[0] and ids(c) & ids(body["data"]) for c in st["clients"]): sys.exit(22)
    st["clients"][st["clients"].index(old[0])] = body["data"]; save()
if path == "clients/delete":
    if not any(c["name"] == body["name"] for c in st["clients"]): sys.exit(22)
    st["clients"] = [c for c in st["clients"] if c["name"] != body["name"]]; save()
sys.exit(22)
'''

FAKE_NDMC = r'''#!/bin/sh
[ "$2" = "show running-config" ] || exit 1
[ -s "$FAKE_RC" ] || exit 1
cat "$FAKE_RC"
'''

FAKE_PROFILE = r'''
vward_profile_load() {
    VWARD_LAN_ADDRESS=192.168.1.1
    VWARD_LAN_SUBNET=192.168.1.0/24
    VWARD_ADGUARD_CONFIG=$FAKE_AGH_YAML
}
'''

RC_VIA_AGH = "ip name-server 192.168.1.1:65053\nip name-server 1.1.1.1 \"\" on Wireguard0\n"
RC_REST = """ip name-server 77.88.8.1 netcraze.cloud on ISP
object-group fqdn domain-list1
    description YouTube
    include ggpht.com
    include googlevideo.com
    include *.YouTube.com
    include 142.250.0.0/15
!
object-group fqdn domain-list2
    include clients3.google.com
    include chatgpt.com
!
object-group fqdn domain-list9
    include notrouted.example
!
dns-proxy
    rebind-protect auto
    route object-group domain-list1 Wireguard0 auto
    route object-group domain-list2 ISP auto
!
"""
WANT_ROW = "[/clients3.google.com/ggpht.com/googlevideo.com/youtube.com/]192.168.1.1:53"
BASE = ["https://dns.quad9.net/dns-query", "https://freedns.controld.com/p0", "[/chatgpt.com/]" + SECRET]


def fail(msg):
    raise SystemExit(f"ADS_ROUTE_DNS=FAIL: {msg}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bindir = tmp / "bin"; bindir.mkdir()
    for name, body in (("curl", FAKE_CURL), ("ndmc", FAKE_NDMC)):
        f = bindir / name; f.write_text(body); f.chmod(0o755)
    (tmp / "profile.sh").write_text(FAKE_PROFILE)
    (tmp / "agh.yaml").write_text("dns:\n  bind_hosts:\n    - 192.168.1.1\n  port: 65053\n")
    etc = tmp / "etc"; etc.mkdir()
    auth = etc / "agh-api.auth"; auth.write_text("admin:pw\n"); auth.chmod(0o600)
    lib = (ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh").read_text()
    patched = tmp / "lib.sh"
    patched.write_text(lib.replace('case "$ads_auth_meta" in "0 -rw-------"', f'case "$ads_auth_meta" in "{os.getuid()} -rw-------"'))
    (tmp / "root/tmp").mkdir(parents=True)
    agh, rc, status = tmp / "agh.json", tmp / "rc.txt", tmp / "route-dns.status"
    env = os.environ | {
        "VWARD_ADS_LIB": str(patched), "VWARD_ADS_ETC": str(etc), "VWARD_ADS_STATE": str(tmp / "state"),
        "VWARD_ADS_LOG_DIR": str(tmp / "log"), "VWARD_ADS_JQ": shutil.which("jq"), "VWARD_ADS_CURL": str(bindir / "curl"),
        "VWARD_ADS_AGH_AUTH_FILE": str(auth), "AGH_API_BASE": "http://192.0.2.1:3001/control",
        "VWARD_ADS_DEVICE_PROFILE_LIB": str(tmp / "profile.sh"), "VWARD_NDMC": str(bindir / "ndmc"),
        "VWARD_ROUTE_DNS_STATUS": str(status), "VWARD_ROUTE_DNS_LOCK": str(tmp / "route-dns.lock"),
        "FAKE_AGH": str(agh), "FAKE_RC": str(rc), "FAKE_AGH_YAML": str(tmp / "agh.yaml"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "TMPDIR": str(tmp),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
    }
    shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])

    def S():
        return json.loads(agh.read_text())

    def run(op, shell):
        r = subprocess.run([*shell, str(SCRIPT), op], env=env, text=True, capture_output=True, timeout=60)
        logs = "".join(f.read_text(errors="ignore") for f in (tmp / "log").glob("*") if f.is_file()) if (tmp / "log").is_dir() else ""
        if "TOKEN123" in r.stdout + r.stderr + logs:
            fail("the Smart DNS token must never be printed or logged")
        return r

    def st():
        return dict(l.split("=", 1) for l in status.read_text().splitlines())

    def client():
        c = [c for c in S()["clients"] if c["name"] == CLIENT]
        return c[0] if c else None

    def ours():
        return [r for r in S()["upstream_dns"] if r.endswith("]192.168.1.1:53")]

    for shell in shells:
        tag = shell[0]
        status.unlink(missing_ok=True)
        (etc / "route-dns.disabled").unlink(missing_ok=True)
        rc.write_text(RC_VIA_AGH + RC_REST)
        # The router as left by the manual test: one row and the client already there.
        agh.write_text(json.dumps({
            "upstream_dns": BASE[:2] + ["[/ggpht.com/]192.168.1.1:53"] + BASE[2:],
            "clients": [{"name": "HONOR 600", "ids": ["192.168.1.139"]},
                        {"name": CLIENT, "ids": ["127.0.0.1", "192.168.1.1"], "upstreams": BASE,
                         "use_global_settings": True, "upstreams_cache_enabled": True, "upstreams_cache_size": 1048576}]}))

        r = run("apply", shell)
        if r.returncode != 0 or "ROUTE_DNS=OK" not in r.stdout:
            fail(f"{tag} first apply: {r.returncode} {r.stdout} {r.stderr[-400:]}")
        if S()["upstream_dns"] != BASE + [WANT_ROW]:
            fail(f"{tag} rows: {S()['upstream_dns']}")
        c = client()
        if c["upstreams"] != BASE or sorted(c["ids"]) != ["127.0.0.1", "192.168.1.1"]:
            fail(f"{tag} client: {c}")
        s = st()
        if (s["result"], s["domains"], s["skipped"]) != ("ok", "4", "1"):
            fail(f"{tag} status: {s}")
        if not S().get("cache_clears"):
            fail(f"{tag} the cache must be cleared once the row changes")

        # A tick right after: no call at all.
        calls = len(S()["calls"])
        run("tick", shell)
        if len(S()["calls"]) != calls:
            fail(f"{tag} tick within 5 minutes must not call AdGuard Home: {S()['calls'][calls:]}")

        # Nothing changed: an apply reads, and writes nothing.
        calls = len(S()["calls"])
        r = run("apply", shell)
        if [x for x in S()["calls"][calls:] if x.startswith("POST")]:
            fail(f"{tag} unchanged apply wrote: {S()['calls'][calls:]}")

        # The owner changes AdGuard Home's servers: the router's client follows.
        s = S(); s["upstream_dns"] = ["https://dns.example/dns-query"] + s["upstream_dns"]; agh.write_text(json.dumps(s))
        run("apply", shell)
        if client()["upstreams"] != ["https://dns.example/dns-query"] + BASE or ours() != [WANT_ROW]:
            fail(f"{tag} servers changed: {client()['upstreams']} {ours()}")

        # A domain added to a routed group joins the row.
        rc.write_text(RC_VIA_AGH + RC_REST.replace("    include clients3.google.com\n", "    include clients3.google.com\n    include new.example\n"))
        run("apply", shell)
        if ours() != [WANT_ROW.replace("googlevideo.com/", "googlevideo.com/new.example/")]:
            fail(f"{tag} new domain: {ours()}")

        # Keenetic's DNS stops asking AdGuard Home: the row goes, then the client.
        rc.write_text(RC_REST)
        r = run("apply", shell)
        if ours() or client() or st()["result"] != "not_via_agh" or r.returncode != 0:
            fail(f"{tag} not via AdGuard Home: {r.stdout} {ours()} {client()}")

        # Back, but the chain does not answer: nothing of ours stays.
        rc.write_text(RC_VIA_AGH + RC_REST)
        s = S(); s["chain_down"] = True; agh.write_text(json.dumps(s))
        r = run("apply", shell)
        if ours() or client() or st()["result"] != "chain_failed" or r.returncode == 0:
            fail(f"{tag} chain down: {r.stdout} {ours()} {client()}")
        s = S(); s["chain_down"] = False; agh.write_text(json.dumps(s))

        # Another client holds the router's address: left alone, no row.
        s = S(); s["clients"].append({"name": "router by hand", "ids": ["192.168.1.1"]}); agh.write_text(json.dumps(s))
        r = run("apply", shell)
        if ours() or client() or st()["result"] != "client_conflict" or not any(c["name"] == "router by hand" for c in S()["clients"]):
            fail(f"{tag} conflict: {r.stdout} {S()['clients']}")
        s = S(); s["clients"] = [c for c in s["clients"] if c["name"] != "router by hand"]; agh.write_text(json.dumps(s))
        run("apply", shell)
        if ours() != [WANT_ROW] or not client():
            fail(f"{tag} back on: {ours()}")

        # AdGuard Home down: nothing changes, reported.
        s = S(); s["down"] = True; agh.write_text(json.dumps(s))
        r = run("apply", shell)
        s = S(); s["down"] = False; agh.write_text(json.dumps(s))
        if st()["result"] != "agh_unavailable" or ours() != [WANT_ROW]:
            fail(f"{tag} AdGuard Home down: {r.stdout}")

        # Switched off: the row first, then the client; a tick after that is free.
        r = run("off", shell)
        if ours() or client() or st()["result"] != "off" or "enabled=0" not in run("status", shell).stdout:
            fail(f"{tag} off: {r.stdout} {ours()} {client()}")
        if S()["upstream_dns"] != ["https://dns.example/dns-query"] + BASE:
            fail(f"{tag} off must leave the owner's rows as they were: {S()['upstream_dns']}")
        calls = len(S()["calls"])
        run("tick", shell)
        if len(S()["calls"]) != calls:
            fail(f"{tag} tick while off must do nothing: {S()['calls'][calls:]}")
        r = run("on", shell)
        if ours() != [WANT_ROW] or not client():
            fail(f"{tag} on: {r.stdout}")

        if S().get("violations"):
            fail(f"{tag} a row existed without the router's client: {S()['violations']}")

print("ADS_ROUTE_DNS=PASS")
