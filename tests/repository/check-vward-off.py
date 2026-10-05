#!/usr/bin/env python3
"""«Отключить VWARD» (vward-off.sh): VWARD steps aside, the router works as a plain Keenetic.

off   the routes into tunnels (lists of domains and subnets) and AdGuard Home's DNS line go
      out of Keenetic, written down first; DNS redirects into AdGuard Home go out of the
      firewall (VWARD's own and the owner's), the owner's kept for «on»; a route to the
      provider and Keenetic's other lines stay
keep  a redirect Keenetic put back while off goes again
on    everything back exactly as it was
The Panel's API runs it detached, an «off» only with its confirmation, and says its state."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OFF = ROOT / "components/runtime/scripts/vward-off.sh"


def fail(message: str) -> None:
    raise SystemExit(f"VWARD_OFF=FAIL: {message}")


RUNNING = """object-group fqdn vpn-sites
    include youtube.com
!
dns-proxy
    route object-group vpn-sites Wireguard0 auto
    route object-group direct-sites ISP auto
    route object-group AdaptiveAuto OpkgTun0 auto
!
interface Wireguard0
    description vpn
!
ip route 198.51.100.0 255.255.255.0 Wireguard0 auto
ip route 203.0.113.0 255.255.255.0 ISP auto
ip name-server 192.0.2.1:65053
ip name-server 192.0.2.53
"""

NDMC = r"""#!/bin/sh
cmd=$2; rc=$T/rc
case "$cmd" in
  'show running-config') cat "$rc" ;;
  'show ip name-server') printf '  address: 192.0.2.1\n     port: 65053\n  address: 192.0.2.53\n' ;;
  'system configuration save') echo saved >> "$T/saves" ;;
  'dns-proxy no route object-group '*) set -- $cmd
     awk -v g="$5" -v t="$6" '!($1 == "route" && $2 == "object-group" && $3 == g && $4 == t)' "$rc" > "$rc.n" && mv "$rc.n" "$rc" ;;
  'dns-proxy route object-group '*) l=${cmd#dns-proxy }
     awk -v l="    $l" '{print} /^dns-proxy$/ {print l}' "$rc" > "$rc.n" && mv "$rc.n" "$rc" ;;
  'no ip route '*|'no ip name-server '*) k=${cmd#no }
     awk -v k="$k" 'index($0, k " ") != 1 && $0 != k' "$rc" > "$rc.n" && mv "$rc.n" "$rc" ;;
  'ip route '*|'ip name-server '*) echo "$cmd" >> "$rc" ;;
  *) echo "unknown command"; exit 1 ;;
esac
"""

# iptables -S of nat PREROUTING and filter FORWARD from files; -D/-C/-I on them.
IPT = r"""#!/bin/sh
f=$T/filter; [ "$1" = -t ] && { f=$T/$2; shift 2; }
op=$1; shift
rule="-A $*"
case "$op" in
  -S) cat "$f" ;;
  -D) grep -vxF -- "$rule" "$f" > "$f.n"; mv "$f.n" "$f" ;;
  -C) grep -qxF -- "$rule" "$f" ;;
  -I) shift; shift; rest=$*; { echo "-A PREROUTING $rest"; cat "$f"; } > "$f.n"; mv "$f.n" "$f" ;;
esac
"""

with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "rc").write_text(RUNNING)
    for name, body in (("ndmc", NDMC), ("iptables", IPT),
                       ("nslookup", "#!/bin/sh\n[ -e \"$T/dns-dead\" ] && exit 1\nprintf 'Name: %s\\nAddress 1: 198.51.100.7\\n' \"$1\"\n")):
        (t / name).write_text(body); (t / name).chmod(0o755)
    owner = "-A PREROUTING -i br0 -p udp -m udp --dport 53 -j REDIRECT --to-ports 65053"
    nat = "-P PREROUTING ACCEPT\n" + owner + "\n-A PREROUTING -s 192.0.2.0/24 -p udp -m udp --dport 53 -j VWARD_DNS\n-A PREROUTING -p tcp --dport 80 -j REDIRECT --to-ports 8080\n"
    (t / "nat").write_text(nat)
    (t / "filter").write_text("-P FORWARD ACCEPT\n-A FORWARD -s 192.0.2.0/24 -j VWARD_DNS_FWD\n")
    (t / "bin").mkdir(); (t / "init").mkdir()
    env = dict(os.environ, T=str(t), VWARD_COMPONENT_STATE=str(t / "state"), VWARD_NDMC=str(t / "ndmc"),
               VWARD_IPTABLES=str(t / "iptables"), VWARD_NSLOOKUP=str(t / "nslookup"), VWARD_INIT_DIR=str(t / "init"),
               VWARD_BIN_DIR=str(t / "bin"), VWARD_OFF_LOCK=str(t / "lock"), VWARD_OFF_LOG=str(t / "off.log"))

    def run(*args):
        r = subprocess.run(["sh", str(OFF), *args], env=env, text=True, capture_output=True, timeout=60)
        if r.returncode != 0 or r.stderr.strip():
            fail(f"{args}: rc={r.returncode} {r.stderr.strip()[:300]}")
        return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)

    o = run()
    rc = (t / "rc").read_text()
    if o.get("result") != "changed" or o.get("lists") != "2" or o.get("subnets") != "1" or o.get("dns") != "1":
        fail(f"off counts: {o}")
    for gone in ("vpn-sites Wireguard0", "AdaptiveAuto OpkgTun0", "198.51.100.0 255.255.255.0 Wireguard0", "192.0.2.1:65053"):
        if gone in rc:
            fail(f"off left {gone!r} in Keenetic")
    for kept in ("route object-group direct-sites ISP auto", "ip route 203.0.113.0 255.255.255.0 ISP auto", "ip name-server 192.0.2.53", "interface Wireguard0"):
        if kept not in rc:
            fail(f"off took {kept!r}, which is not VWARD's routing")
    if not (t / "state/vward.off").exists() or "saved" not in (t / "saves").read_text():
        fail("the switch is not remembered or Keenetic's configuration not saved")
    natnow = (t / "nat").read_text()
    if owner in natnow or "VWARD_DNS" in natnow or "VWARD_DNS_FWD" in (t / "filter").read_text():
        fail(f"DNS redirects are still there: {natnow}")
    if "--to-ports 8080" not in natnow:
        fail("a redirect that is not DNS was taken")
    if (t / "state/vward.off.iptables").read_text().strip() != owner:
        fail("the owner's redirect is not kept for «on» (VWARD's own come back with VWARD)")
    if (t / "state/vward.off.removed").stat().st_mode & 0o077:
        fail("the list of what was taken out is readable by others")
    st = run("status")
    if st.get("state") != "off" or st.get("saved") != "4":
        fail(f"status: {st}")
    # Keenetic rebuilt its firewall: the owner's hook put the redirect back.
    (t / "nat").write_text(natnow + owner + "\n")
    run("keep")
    if owner in (t / "nat").read_text():
        fail("keep: the redirect put back by Keenetic stays")
    # A second «off» changes nothing and loses nothing.
    o2 = run("off")
    if o2.get("result") != "unchanged" or len((t / "state/vward.off.removed").read_text().splitlines()) != 4:
        fail(f"a second off: {o2}")
    o = run("on")
    if o.get("result") != "changed" or o.get("restored") != "4" or o.get("refused") != "0":
        fail(f"on: {o}")
    if sorted((t / "rc").read_text().splitlines()) != sorted(RUNNING.splitlines()):
        fail("on: Keenetic's configuration is not as before:\n" + (t / "rc").read_text())
    if owner not in (t / "nat").read_text() or (t / "state/vward.off").exists():
        fail("on: the owner's redirect is not back, or the switch stays")
    if run("on").get("result") != "unchanged":
        fail("a second on is not a no-op")
    # No other DNS answers: AdGuard Home's line stays, the home keeps its DNS.
    (t / "dns-dead").write_text("")
    o = run("off")
    if o.get("dns_kept") != "1" or "ip name-server 192.0.2.1:65053" not in (t / "rc").read_text():
        fail(f"no other DNS: AdGuard Home's line must stay: {o}")
    run("on")

    # The Panel's API.
    fake = t / "fake-off.sh"
    fake.write_text("#!/bin/sh\ncase \"$1\" in status) printf 'state=off\\nsince=1790640000\\nlists=2\\nsubnets=4741\\ndns=1\\ndns_kept=0\\nrefused=0\\nsaved=4744\\n' ;;"
                    " *) echo \"$1 $VWARD_OFF_BY\" >> \"$T/ran\" ;; esac\n")
    fake.chmod(0o755)

    def api(method, body=""):
        e = {"PATH": os.environ["PATH"], "T": str(t), "REQUEST_METHOD": method, "QUERY_STRING": "action=vward-off", "JQ": shutil.which("jq"),
             "VWARD_PROFILE_LIB": "/nonexistent", "VWARD_OFF_BIN": str(fake), "VWARD_COMPONENT_STATE": str(t / "state"),
             "CONTENT_TYPE": "application/x-www-form-urlencoded", "CONTENT_LENGTH": str(len(body)), "HTTP_X_VWARD_REQUEST": "console"}
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=e, input=body, text=True, capture_output=True, timeout=30)
        return json.loads(r.stdout.split("\n\n", 1)[1])

    d = api("GET")
    if d != {"ok": True, "state": "off", "op": None, "since": 1790640000, "lists": 2, "subnets": 4741, "dns": 1, "dns_kept": False,
             "refused": 0, "saved": 4744, "error": None}:
        fail(f"API state: {d}")
    if api("POST", "op=off").get("error") != "confirmation_required":
        fail("the API switches VWARD off without the confirmation")
    if api("POST", "op=sideways").get("error") != "invalid_operation":
        fail("the API takes an unknown operation")
    api("POST", "op=off&confirm=VWARD_OFF"); api("POST", "op=on")
    for _ in range(50):
        if (t / "ran").exists() and len((t / "ran").read_text().splitlines()) == 2:
            break
        subprocess.run(["sleep", "0.1"])
    if sorted((t / "ran").read_text().splitlines()) != ["off panel", "on panel"]:
        fail(f"the API did not run the switch: {(t / 'ran').read_text() if (t / 'ran').exists() else 'nothing'}")

# Every VWARD job gives way while it is off; the Panel shows it and the way back.
adm = (ROOT / "components/runtime/lib/vward-runtime-admission.sh").read_text()
if 'vward_off() { [ -e "$VWARD_COMPONENT_STATE/vward.off" ]; }' not in adm or "! vward_off || return 1" not in adm:
    fail("components do not give way while VWARD is off")
for path, need in (("components/runtime/scripts/vward-cron-supervisor.sh", '"$OFF_BIN" keep'),
                   ("components/ads-privacy-guard/scripts/vward-ads-privacy-dns-guard.sh", "DNS_GUARD=VWARD_OFF"),
                   ("components/runtime/scripts/vward-sentinel.sh", "result=vward_off"),
                   ("components/console/scripts/vward-console-config.sh", "die vward_off 75"),
                   ("components/runtime/scripts/vward-housekeeping.sh", "if ! vward_off; then")):
    if need not in (ROOT / path).read_text():
        fail(f"{path} lacks {need!r}")
js = (ROOT / "web/assets/vward-console.js").read_text()
for need in ("function offNotice()", "patchContent(offNotice() + html", "'vward-off': () => vwardPower('off')", "offPanel()",
             "{ op: 'off', confirm: 'VWARD_OFF' }", "off: () => apiGet('vward-off')"):
    if need not in js:
        fail(f"the Panel lacks {need!r}")
print("VWARD_OFF=PASS")
