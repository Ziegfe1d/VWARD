#!/usr/bin/env python3
"""Device names reach AdGuard Home through its API, with no restart.

A stand-in for curl answers Keenetic's RCI (show/ip/hotspot) and the AdGuard
Home clients API from a JSON state and enforces AdGuard Home's own rules:
unique names, an id belongs to one client, update by the old name.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-clients.sh"

FAKE_CURL = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
st_path = Path("@STATE@")
st = json.loads(st_path.read_text())
args = sys.argv[1:]
with open(str(st_path) + ".argv", "a") as f: f.write(" ".join(args) + "\n")
conf = sys.stdin.read() if "-K" in args else ""
url = [a for a in args if a.startswith("http")][-1]
out = args[args.index("-o") + 1]
if url.startswith("http://rci/"):
    if st.get("rci_down"): sys.exit(7)
    Path(out).write_text(json.dumps({"host": st["hosts"]}))
    sys.exit(0)
if conf.strip() != 'user = "admin:pw"': sys.exit(22)
if st.get("agh_down"): sys.exit(7)
method = args[args.index("-X") + 1] if "-X" in args else "GET"
body = json.loads(Path(args[args.index("--data-binary") + 1][1:]).read_text()) if "--data-binary" in args else {}
path = url.split("/control/", 1)[1]
clients = st["clients"]
def taken(c, skip=None):
    for o in clients:
        if o is skip: continue
        if o["name"] == c["name"]: return True
        if {i.lower() for i in o["ids"]} & {i.lower() for i in c["ids"]}: return True
    return False
st.setdefault("calls", []).append(path)
if path == "clients" and method == "GET":
    Path(out).write_text(json.dumps({"clients": clients or None, "auto_clients": [], "supported_tags": []}))
elif path == "clients/add" and method == "POST":
    if taken(body) or not body["ids"]: sys.exit(22)
    clients.append(body)
elif path == "clients/update" and method == "POST":
    old = [c for c in clients if c["name"] == body["name"]]
    if not old or taken(body["data"], old[0]) or not body["data"]["ids"]: sys.exit(22)
    clients[clients.index(old[0])] = body["data"]
else:
    sys.exit(22)
st_path.write_text(json.dumps(st))
if not Path(out).exists(): Path(out).write_text("OK")
'''


def fail(message):
    raise SystemExit(f"ADS_AGH_CLIENTS=FAIL: {message}")


def host(name, mac, ip, active=True, registered=True):
    return {"name": name, "mac": mac, "ip": ip, "active": active, "registered": registered}


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    state = tmp / "state.json"
    curl = tmp / "curl"
    curl.write_text(FAKE_CURL.replace("@STATE@", str(state)))
    curl.chmod(0o755)
    etc = tmp / "etc"
    etc.mkdir()
    auth = etc / "agh-api.auth"
    auth.write_text("admin:pw\n")
    auth.chmod(0o600)
    crontab = tmp / "root.crontab"
    crontab.write_text("*/5 * * * * /opt/bin/vward-route-reconciler.sh\n# */10 * * * * /opt/bin/agh-keenetic-clients-sync.sh\n")
    lib = (ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh").read_text()
    patched = tmp / "lib.sh"
    patched.write_text(lib.replace('case "$ads_auth_meta" in "0 -rw-------"', f'case "$ads_auth_meta" in "{os.getuid()} -rw-------"'))
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {
        "VWARD_ADS_LIB": str(patched), "VWARD_ADS_ETC": str(etc), "VWARD_ADS_STATE": str(tmp / "state"),
        "VWARD_ADS_LOG_DIR": str(tmp / "log"), "VWARD_ADS_JQ": shutil.which("jq"), "VWARD_ADS_CURL": str(curl),
        "VWARD_ADS_AGH_AUTH_FILE": str(auth), "AGH_API_BASE": "http://192.0.2.1:3001/control",
        "VWARD_RCI_BASE": "http://rci", "VWARD_CRONTAB_FILE": str(crontab),
        "VWARD_ADS_CLIENTS_STATUS": str(tmp / "clients.status"), "VWARD_ADS_CLIENTS_LOCK": str(tmp / "clients.lock"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "TMPDIR": str(tmp),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
    }
    shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])

    def S():
        return json.loads(state.read_text())

    def run(op="tick", shell=("sh",)):
        r = subprocess.run([*shell, str(SYNC), op], env=env, text=True, capture_output=True, timeout=60)
        return r

    def status():
        return dict(l.split("=", 1) for l in (tmp / "clients.status").read_text().splitlines())

    for shell in shells:
        (tmp / "clients.status").unlink(missing_ok=True)
        state.write_text(json.dumps({
            "hosts": [
                host("TCL TV", "0C:0F:D8:58:51:65", "192.168.1.118"),
                host("HONOR 600", "3e:d5:c2:ef:c5:9a", "192.168.1.139"),
                host("Macbi", "aa:bb:cc:dd:ee:01", "192.168.1.50"),
                host("Offline phone", "aa:bb:cc:dd:ee:02", "192.168.1.60", active=False),
                host("Guest", "aa:bb:cc:dd:ee:03", "192.168.1.70", registered=False),
                host("Twin", "aa:bb:cc:dd:ee:04", "192.168.1.80"),
                host("Twin", "aa:bb:cc:dd:ee:05", "192.168.1.81"),
            ],
            "clients": [
                # Old style: renamed by hand in AdGuard Home, with its own settings.
                {"name": "Телевизор", "ids": ["192.168.1.118", "0c:0f:d8:58:51:65"], "use_global_settings": False,
                 "filtering_enabled": False, "blocked_services": ["youtube"], "tags": ["device_tv"], "upstreams": []},
                # IP only, and the address now belongs to HONOR 600.
                {"name": "old-phone", "ids": ["192.168.1.139"], "use_global_settings": True, "tags": [], "upstreams": []},
                # A second address for Macbi: the stale one is dropped, the ClientID kept.
                {"name": "Macbi", "ids": ["192.168.1.49", "aa:bb:cc:dd:ee:01", "macbi-doh"], "use_global_settings": True,
                 "tags": [], "upstreams": []},
                # Not a Keenetic device: left alone.
                {"name": "NAS", "ids": ["192.168.1.2"], "use_global_settings": True, "tags": [], "upstreams": []},
            ],
        }))
        r = run("tick", shell)
        if r.returncode != 0 or "CLIENTS=OK" not in r.stdout:
            fail(f"{shell[0]} first sync: {r.returncode} {r.stdout} {r.stderr[-400:]}")
        got = {c["name"]: c for c in S()["clients"]}
        if set(got) != {"TCL TV", "HONOR 600", "Macbi", "NAS", "Twin"}:
            fail(f"{shell[0]} names: {sorted(got)}")
        tv = got["TCL TV"]
        if tv["ids"] != ["192.168.1.118", "0c:0f:d8:58:51:65"] or tv["blocked_services"] != ["youtube"] or tv["use_global_settings"] is not False:
            fail(f"{shell[0]} TV must keep its settings: {tv}")
        if got["HONOR 600"]["ids"] != ["192.168.1.139", "3e:d5:c2:ef:c5:9a"]:
            fail(f"{shell[0]} IP-only client must take the MAC: {got['HONOR 600']}")
        if got["Macbi"]["ids"] != ["192.168.1.50", "aa:bb:cc:dd:ee:01", "macbi-doh"]:
            fail(f"{shell[0]} Macbi ids: {got['Macbi']['ids']}")
        if got["NAS"]["ids"] != ["192.168.1.2"] or got["Twin"]["ids"] != ["192.168.1.80", "aa:bb:cc:dd:ee:04"]:
            fail(f"{shell[0]} NAS/Twin: {got['NAS']} {got['Twin']}")
        st = status()
        if (st["result"], st["devices"], st["added"], st["updated"], st["failed"]) != ("ok", "4", "1", "3", "0"):
            fail(f"{shell[0]} status: {st}")
        if any("admin" in l for l in (tmp / "state.json.argv").read_text().splitlines()):
            fail("the AdGuard Home login must never reach argv")

        # Nothing changed: no API call at all.
        calls = len(S()["calls"])
        r = run("tick", shell)
        if "CLIENTS=UNCHANGED" not in r.stdout or len(S()["calls"]) != calls:
            fail(f"{shell[0]} unchanged tick: {r.stdout} {S()['calls'][calls:]}")

        # A device took another one's address: the address moves, in one pass.
        s = S()
        s["hosts"] = [host("TCL TV", "0c:0f:d8:58:51:65", "192.168.1.50"), host("Macbi", "aa:bb:cc:dd:ee:01", "192.168.1.51")]
        state.write_text(json.dumps(s))
        r = run("tick", shell)
        got = {c["name"]: c["ids"] for c in S()["clients"]}
        if r.returncode != 0 or got["TCL TV"][0] != "192.168.1.50" or got["Macbi"][0] != "192.168.1.51":
            fail(f"{shell[0]} address swap: {r.stdout} {got}")

        # AdGuard Home down: reported, retried on the next tick.
        s = S(); s["agh_down"] = True; s["hosts"].append(host("New", "aa:bb:cc:dd:ee:09", "192.168.1.90"))
        state.write_text(json.dumps(s))
        r = run("tick", shell)
        if "CLIENTS=AGH_UNAVAILABLE" not in r.stdout or status()["result"] != "agh_unavailable":
            fail(f"{shell[0]} AdGuard Home down: {r.stdout}")
        s = S(); s["agh_down"] = False; state.write_text(json.dumps(s))
        r = run("tick", shell)
        if "New" not in {c["name"] for c in S()["clients"]}:
            fail(f"{shell[0]} retry after AdGuard Home is back: {r.stdout}")

    # The old script in cron: VWARD stays out of its way.
    crontab.write_text("*/10 * * * * /opt/bin/agh-keenetic-clients-sync.sh >/dev/null 2>&1\n")
    calls = len(S()["calls"])
    r = run("sync")
    if "CLIENTS=OLD_SCRIPT" not in r.stdout or len(S()["calls"]) != calls or status()["result"] != "old_script":
        fail(f"old script: {r.stdout}")
    crontab.write_text("")

    # Switched off from the Console.
    (etc / "clients-sync.disabled").write_text("")
    r = run("sync")
    if "CLIENTS=DISABLED" not in r.stdout or "enabled=0" not in run("status").stdout:
        fail(f"disabled: {r.stdout}")
    (etc / "clients-sync.disabled").unlink()

    # Keenetic unreachable.
    s = S(); s["rci_down"] = True; state.write_text(json.dumps(s))
    r = run("sync")
    if "CLIENTS=ROUTER_UNAVAILABLE" not in r.stdout:
        fail(f"router down: {r.stdout}")

print("ADS_AGH_CLIENTS=PASS")
