#!/usr/bin/env python3
"""Tunnel for routes: switch through the Panel writer, rollback, and policy-sync route move."""

import os
import stat
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
POLICY_SYNC = ROOT / "components/policy-sync/scripts/vward-policy-sync.sh"

# Fake Keenetic CLI.  DNS routes live in the dns-proxy block of $CFG.  Flags:
# .reject-old - withdrawing a route to the old tunnel fails; .reject-no - every
# withdrawal fails; .lie - accepted but not applied; .nosave - save fails.
FAKE_NDMC = r"""#!/bin/sh
CFG="@CFG@"
[ "$1" = -c ] || exit 2
cmd=$2
echo "$cmd" >> "$CFG.log"
case "$cmd" in
  "show running-config") cat "$CFG"; exit 0 ;;
  "system configuration save") [ -e "$CFG.nosave" ] && { echo "Core::ConfigurationSaver: error[1]: failed"; exit 0; }; echo saved; exit 0 ;;
esac
case "$cmd" in
  "ip route "*) echo "$cmd" >> "$CFG"; echo ok; exit 0 ;;
  "no ip route "*) set -- $cmd
    awk -v n="$4" -v m="$5" -v t="$6" '!($1=="ip" && $2=="route" && $3==n && (($4==m && $5==t) || (m=="255.255.255.255" && $4==t)))' "$CFG" > "$CFG.new"; mv "$CFG.new" "$CFG"; echo ok; exit 0 ;;
esac
set -- $cmd
ctx=; [ "$1" = dns-proxy ] && { ctx=dns-proxy; shift; }
neg=0; [ "$1" = no ] && { neg=1; shift; }
[ "$ctx" = dns-proxy ] && [ "$1 $2" = "route object-group" ] || { echo "Command::Base: error[7]: syntax error"; exit 0; }
g=$3 t=$4; shift 4
[ "$neg" = 1 ] && [ -e "$CFG.reject-no" ] && { echo "Dns::Proxy: error[5]: rejected"; exit 0; }
[ "$neg" = 1 ] && [ -e "$CFG.reject-old" ] && case "$t" in *3) echo "Dns::Proxy: error[5]: rejected"; exit 0 ;; esac
[ -e "$CFG.lie" ] && { echo ok; exit 0; }
if [ "$neg" = 1 ]; then
  awk -v g="$g" -v t="$t" '!($1=="route" && $2=="object-group" && $3==g && $4==t)' "$CFG" > "$CFG.new"
else
  awk -v line="    route object-group $g $t${1:+ $*}" '{print} $0=="dns-proxy"{print line}' "$CFG" > "$CFG.new"
fi
mv "$CFG.new" "$CFG"; echo ok
"""

RUNNING = """interface Wireguard3
!
dns-proxy
    route object-group streaming Wireguard3 auto
    route object-group AdaptiveAuto nwg3 auto
    route object-group other Wireguard3 auto
!
object-group fqdn streaming
    include youtube.com
!
"""

DEVICE_CONF = """# pinned for the test
VWARD_LAN_ADDRESS=10.77.0.1
VWARD_LAN_SUBNET=10.77.0.0/24
VWARD_LAN_DEVICE=br2
VWARD_LAN_INTERFACE=Bridge2
VWARD_WAN_DEVICE=eth2.4
VWARD_WAN_INTERFACE=ISP
VWARD_TUNNEL_INTERFACE=Wireguard3
VWARD_POLICY_GROUP=streaming
"""

INTERFACES = '{"Bridge2":{"type":"Bridge","security-level":"private"},"Wireguard3":{"type":"Wireguard","security-level":"public"},"Wireguard8":{"type":"Wireguard","security-level":"public"}}'


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def routes(cfg: Path) -> list:
    return sorted(" ".join(l.split()[2:]) for l in cfg.read_text().splitlines() if l.split()[:2] == ["route", "object-group"])


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tools / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    (tmp / "interface.json").write_text(INTERFACES)
    curl = tools / "curl"
    curl.write_text(f"""#!/bin/sh
for URL do :; done
case "$URL" in
  */show/interface) cat "{tmp}/interface.json" ;;
  */show/interface?name=Wireguard8) if [ -e "{tmp}/off8" ]; then echo '{{"id":"Wireguard8","state":"down","link":"down"}}'; else echo '"nwg8"'; fi ;;
  *name=Wireguard3) echo '"nwg3"' ;;
  *name=Wireguard8) echo '"nwg8"' ;;
  *name=Bridge2) echo '"br2"' ;;
  *) exit 22 ;;
esac
""")
    curl.chmod(0o755)
    devconf = tmp / "device.conf"; devconf.write_text(DEVICE_CONF); devconf.chmod(0o600)
    policy = tmp / "policy"; policy.mkdir()
    (policy / "owned.dynamic.routes").write_text("203.0.113.0/24\n")
    guard = tmp / "guard.state"; health = tmp / "health.state"
    init = tools / "S91"; init.write_text(f'#!/bin/sh\necho "$1" >> "{tmp}/engine"\n'); init.chmod(0o755)
    sync = tools / "policy-sync"; sync.write_text(f'#!/bin/sh\necho "$*" >> "{tmp}/policy-sync"\n'); sync.chmod(0o755)
    (tmp / "root/tmp").mkdir(parents=True)

    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_CURL_BIN": str(curl), "VWARD_DEVICE_CONFIG": str(devconf),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_POLICY_STATE": str(policy), "VWARD_TUNNEL_GUARD_STATE": str(guard), "VWARD_TUNNEL_HEALTH_STATE": str(health),
        "VWARD_ROUTE_ENGINE_INIT": str(init), "VWARD_POLICY_SYNC_BIN": str(sync), "VWARD_ROUTE_STATE": str(tmp / "route"),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
    }

    def run(target, expect, rc=None, move=None):
        r = subprocess.run(["sh", str(HELPER), "tunnel", target] + ([move] if move else []), env=env, text=True, capture_output=True)
        out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        if out != expect:
            fail(f"tunnel {target}: {out!r} != {expect!r} (rc={r.returncode}) {r.stderr.strip()}")
        if rc is not None and r.returncode != rc:
            fail(f"tunnel {target}: rc {r.returncode} != {rc}")

    before_routes, before_conf = routes(cfg), devconf.read_text()

    def untouched(why):
        if routes(cfg) != before_routes or devconf.read_text() != before_conf:
            fail(f"{why}: router or device.conf changed: {routes(cfg)} / {devconf.read_text()!r}")
        if (tmp / "change.lock").exists() or (policy / "lock").exists():
            fail(f"{why}: locks left behind")

    # Input and preconditions never touch the router.
    run("a;reboot", "error=invalid_tunnel", 64)
    run("Wireguard9", "error=unknown_tunnel", 64)
    run("Bridge2", "error=unknown_tunnel", 64)
    run("Wireguard3", "result=unchanged", 0)
    guard.write_text("FAILOPEN_ACTIVE=1\n")
    run("Wireguard8", "error=failopen_active")
    guard.write_text("FAILOPEN_ACTIVE=0\nDOWN_STREAK=2\n")
    # A tunnel switched off cannot become the default: the lists would lose their route.
    (tmp / "off8").touch()
    run("Wireguard8", "error=tunnel_off", 64)
    (tmp / "off8").unlink()
    (policy / "lock").mkdir()
    run("Wireguard8", "error=policy_sync_busy", 75)
    (policy / "lock").rmdir()
    untouched("preconditions")

    # Keenetic refuses to withdraw the old route: the added routes are undone.
    (tmp / "running.cfg.reject-old").touch()
    run("Wireguard8", "error=router_rejected")
    (tmp / "running.cfg.reject-old").unlink()
    untouched("rejected withdraw")
    # No withdrawal works at all (e.g. a CLI form this firmware does not accept):
    # the rollback cannot remove the added route and must say so.
    (tmp / "running.cfg.reject-no").touch()
    run("Wireguard8", "error=rollback_incomplete")
    (tmp / "running.cfg.reject-no").unlink()
    if devconf.read_text() != before_conf or "rollback incomplete" not in (tmp / "audit.log").read_text():
        fail("an incomplete rollback must still restore device.conf and be audited")
    cfg.write_text(RUNNING)
    untouched("incomplete rollback, router restored by the test")
    # Keenetic accepts but applies nothing: verification fails.
    (tmp / "running.cfg.lie").touch()
    run("Wireguard8", "error=verification_failed")
    (tmp / "running.cfg.lie").unlink()
    untouched("unapplied change")
    # Save fails after everything was applied: full rollback, device.conf included.
    (tmp / "running.cfg.nosave").touch()
    run("Wireguard8", "error=config_save_failed")
    (tmp / "running.cfg.nosave").unlink()
    untouched("failed save")
    if (tmp / "engine").exists() or (tmp / "policy-sync").exists():
        fail("failed switches must not restart anything")

    # Successful switch.
    run("Wireguard8", "result=changed", 0)
    want = sorted(["streaming Wireguard8 auto", "AdaptiveAuto nwg8 auto", "other Wireguard3 auto"])
    if routes(cfg) != want:
        fail(f"routes after switch {routes(cfg)} != {want} (other groups must stay, name form must be kept)")
    conf = devconf.read_text()
    for line in ("VWARD_TUNNEL_INTERFACE=Wireguard8", "VWARD_TUNNEL_DEVICE=nwg8", "VWARD_POLICY_GROUP=streaming", "# pinned for the test", "VWARD_LAN_DEVICE=br2"):
        if line not in conf.splitlines():
            fail(f"device.conf missing {line!r}: {conf!r}")
    if conf.count("VWARD_TUNNEL_INTERFACE=") != 1 or stat.S_IMODE(devconf.stat().st_mode) != 0o600:
        fail("device.conf must keep one value per key and mode 0600")
    if guard.exists() or (policy / "owned.interface").read_text().strip() != "Wireguard3":
        fail("guard state must reset and owned IP routes must stay attributed to the old tunnel")
    if (tmp / "engine").read_text().split() != ["restart"]:
        fail("route engine must restart with the new tunnel")
    for _ in range(50):
        if (tmp / "policy-sync").exists():
            break
        time.sleep(0.1)
    if (tmp / "policy-sync").read_text().split() != ["--reconcile"]:
        fail("policy-sync must be started to move the IP routes")
    if "system configuration save" not in (tmp / "running.cfg.log").read_text().splitlines()[-1]:
        fail("router configuration must be saved last")
    if "tunnel Wireguard3(nwg3) -> Wireguard8(nwg8) group=streaming routes=2 subnets=0 result=changed" not in (tmp / "audit.log").read_text():
        fail("audit line missing")
    if (tmp / "change.lock").exists() or (policy / "lock").exists() or list(tmp.glob("device.conf.console.*")):
        fail("locks or temporary files left behind")
    run("Wireguard8", "result=unchanged", 0)

    # device.conf names no group (the profile could not tell it: the old tunnel lost its settings
    # with the USB stick, Viva 2026-10-18): the group comes from the routes, the switch goes on.
    devconf.write_text("\n".join(l for l in devconf.read_text().splitlines() if not l.startswith("VWARD_POLICY_GROUP=")) + "\n")
    run("Wireguard3", "result=changed", 0)
    if "streaming Wireguard3 auto" not in routes(cfg) or "VWARD_POLICY_GROUP=streaming" not in devconf.read_text().splitlines():
        fail(f"a switch without a known group: {routes(cfg)} / {devconf.read_text()!r}")

    # «all»: every list and static subnet of the old tunnel comes along (Viva 2026-10-19: 19
    # lists stayed on the dead OpkgTun2); the routes policy-sync owns stay with it.
    run("Wireguard8", "error=invalid_arguments", 64, move="every")
    with cfg.open("a") as f:
        f.write("ip route 198.51.100.0 255.255.255.0 Wireguard3 auto\nip route 192.0.2.7 Wireguard3 auto\n"
                "ip route 203.0.113.0 255.255.255.0 Wireguard3 auto\nip route 100.64.9.0 255.255.255.0 Wireguard5 auto\n")
    run("Wireguard8", "result=changed", 0, move="all")
    want = sorted(["streaming Wireguard8 auto", "AdaptiveAuto nwg8 auto", "other Wireguard8 auto"])
    if routes(cfg) != want:
        fail(f"all: routes {routes(cfg)} != {want}")
    nets = sorted(l for l in cfg.read_text().splitlines() if l.startswith("ip route "))
    want = sorted(["ip route 198.51.100.0 255.255.255.0 Wireguard8 auto", "ip route 192.0.2.7 255.255.255.255 Wireguard8 auto",
                   "ip route 203.0.113.0 255.255.255.0 Wireguard3 auto", "ip route 100.64.9.0 255.255.255.0 Wireguard5 auto"])
    if nets != want:
        fail(f"all: subnets {nets} != {want}")
    if "routes=3 subnets=2 result=changed" not in (tmp / "audit.log").read_text():
        fail("all: audit line must count the lists and subnets")

    # A refusal goes to the journal with the router's answer.
    if "tunnel Wireguard8 error=router_rejected reason=" not in (tmp / "audit.log").read_text():
        fail("a refused command must be audited with its reason")


# policy-sync: owned IP routes move to the new tunnel (Keenetic takes interface names).

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    harness = tmp / "fn.sh"
    src = POLICY_SYNC.read_text()
    fns = subprocess.run(["sed", "-n", "/^prefix_mask()/,/^}/p; /^ndm()/,/^}/p; /^log()/,/^}/p; /^route_line()/,/^}/p; /^reconcile_routes()/,/^}/p", str(POLICY_SYNC)],
                         text=True, capture_output=True).stdout
    for name in ("prefix_mask()", "ndm()", "reconcile_routes()"):
        if name not in fns:
            fail(f"policy-sync function missing: {name}")
    harness.write_text(fns)
    tools = tmp / "tools"; tools.mkdir()
    (tools / "ndmc").write_text(f"""#!/bin/sh
echo "$2" >> "{tmp}/calls"
case "$2" in *" Wireguard3"|*" Wireguard3 "*) [ -e "{tmp}/stuck" ] && echo "error[5]: no such entry" ;; esac
exit 0
""")
    (tools / "ndmc").chmod(0o755)
    state = tmp / "state"; (state / "catalog").mkdir(parents=True)
    (state / "catalog/video.cidr").write_text("203.0.113.0/24\n198.51.100.0/24\n")
    (state / "owned.dynamic.routes").write_text("203.0.113.0/24\n")
    (state / "owned.interface").write_text("Wireguard3\n")
    (tmp / "cats").write_text("video\n")
    (tmp / "run").write_text("ip route 203.0.113.0 255.255.255.0 Wireguard3 auto\n")
    work = tmp / "work"; work.mkdir()
    script = f'''. "{harness}"; STATE="{state}"; WORK="{work}"; OWNED="{state}/owned.dynamic.routes"
OWNED_DEVICE="{state}/owned.interface"; ACTIVE="{state}/active.categories"; CATALOG="{state}/catalog"; LOG="{tmp}/log"; WG=nwg8; RT=Wireguard8
reconcile_routes "{tmp}/run" "{tmp}/cats"'''
    penv = os.environ | {"PATH": f"{tools}{os.pathsep}{os.environ['PATH']}"}

    (tmp / "stuck").touch()
    r = subprocess.run(["sh", "-c", script], env=penv, text=True, capture_output=True)
    if r.returncode == 0 or "MOVE_PENDING=1" not in r.stdout:
        fail(f"a route that cannot be withdrawn must keep the move pending: {r.stdout}")
    if (state / "owned.interface").read_text().strip() != "Wireguard3" or any("Wireguard8" in c for c in (tmp / "calls").read_text().splitlines()):
        fail("nothing may be added through the new device while the old routes remain")
    (tmp / "stuck").unlink(); (tmp / "calls").unlink()

    r = subprocess.run(["sh", "-c", script], env=penv, text=True, capture_output=True)
    calls = (tmp / "calls").read_text().splitlines()
    if r.returncode != 0 or calls[0] != "no ip route 203.0.113.0 255.255.255.0 Wireguard3":
        fail(f"old route must be withdrawn first: {calls} {r.stdout}")
    if sorted(c for c in calls if c.startswith("ip route")) != ["ip route 198.51.100.0 255.255.255.0 Wireguard8 auto", "ip route 203.0.113.0 255.255.255.0 Wireguard8 auto"]:
        fail(f"routes must be re-added through the new device: {calls}")
    if (state / "owned.interface").read_text().strip() != "Wireguard8" or sorted((state / "owned.dynamic.routes").read_text().split()) != ["198.51.100.0/24", "203.0.113.0/24"]:
        fail("owned routes must now belong to the new device")
    if "MOVED=1" not in r.stdout or calls[-1] != "system configuration save":
        fail(f"move must be reported and saved: {r.stdout}")

print("CONSOLE_TUNNEL=PASS")
