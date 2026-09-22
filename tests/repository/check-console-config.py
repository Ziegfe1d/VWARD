#!/usr/bin/env python3
"""Simulate the Console configuration writer against a fake Keenetic CLI."""

import os
import stat
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"

FAKE_NDMC = r"""#!/bin/sh
# Fake ndmc: running-config lives in $CFG; REJECT=1 makes group changes fail,
# LIE=1 accepts a group change without applying it.
CFG="@CFG@"
[ "$1" = -c ] || exit 2
cmd=$2
echo "$cmd" >> "@CFG@.log"
case "$cmd" in
  "show running-config") cat "$CFG"; exit 0 ;;
  "system configuration save") [ -e "@CFG@.nosave" ] && { echo "Core::ConfigurationSaver: error: failed"; exit 0; }; echo "saved"; exit 0 ;;
esac
[ -e "@CFG@.reject" ] && { echo "Command::Base: error: rejected"; exit 0; }
[ -e "@CFG@.lie" ] && { echo "ok"; exit 0; }
set -- $cmd
if [ "$1" = no ]; then shift; mode=del; else mode=add; fi
[ "$1 $2" = "object-group fqdn" ] && [ "$4" = include ] || { echo "error: unknown command"; exit 1; }
g=$3 d=$5
awk -v g="$g" -v d="$d" -v m="$mode" '
  /^object-group fqdn / {if (cur==g && m=="add" && !done) {print "    include " d; done=1} cur=$3; print; next}
  /^!/ {if (cur==g && m=="add" && !done) {print "    include " d; done=1} cur=""; print; next}
  cur==g && $1=="include" && $2==d && m=="del" {next}
  {print}
  END {if (!seen && m=="add" && !done) {}}' "$CFG" > "$CFG.new" && mv "$CFG.new" "$CFG"
echo ok
"""

RUNNING = """interface Wireguard0
!
object-group fqdn MyVPN
    include old.example
!
object-group fqdn AdaptiveAuto
    include slow.example
    include other.example
!
"""


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    etc = tmp / "etc"; (etc / "route-engine").mkdir(parents=True)
    state = tmp / "state"; state.mkdir()
    (tmp / "root/tmp").mkdir(parents=True)
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tmp / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    profile = tmp / "profile.sh"
    profile.write_text("vward_profile_load(){ VWARD_POLICY_GROUP=MyVPN; }\n")
    (etc / "route-engine/categories.tsv").write_text(
        "# id|title|target_group|catalog|enabled\nsteam|Steam|AUTO|@catalogs/steam.domains|1\nadult|18+|AUTO|@catalogs/adult.domains|1\n")
    (etc / "route-engine/force-vpn.conf").write_text("# forced\nkept.example # note\n")
    upd = etc / "update.conf"; upd.write_text("update_enabled=1\nsafe_window_start=03:00\nsafe_window_end=05:00\ncheck_interval_seconds=900\n")
    upd.chmod(0o600)
    (state / "adaptive-persist.txt").write_text("slow.example\nother.example\n")
    (state / "adaptive-domains.txt").write_text("slow.example\nother.example\n")

    env = os.environ | {
        "VWARD_CONSOLE_ETC": str(etc), "VWARD_ROUTE_STATE": str(state),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"), "VWARD_NDMC": str(ndmc),
        "VWARD_PROFILE_LIB": str(profile), "VWARD_ROOT_PREFIX": str(tmp / "root"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
    }

    def run(*args, expect=None, rc=None):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True)
        out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        if expect is not None and out != expect:
            fail(f"{' '.join(args)}: {out!r} != {expect!r} (rc={r.returncode}, stderr={r.stderr.strip()})")
        if rc is not None and r.returncode != rc:
            fail(f"{' '.join(args)}: rc {r.returncode} != {rc}")
        return out

    def group(name):
        cur, out = None, []
        for line in cfg.read_text().splitlines():
            if line.startswith("object-group fqdn "):
                cur = line.split()[2]
            elif line.startswith("!"):
                cur = None
            elif cur == name and line.split()[:1] == ["include"]:
                out.append(line.split()[1])
        return out

    # Route domains: add, idempotent add, remove, invalid input never reaches ndmc.
    run("route-domain", "add", "New.Example", expect="result=changed", rc=0)
    if group("MyVPN") != ["old.example", "new.example"]:
        fail(f"domain not added to the policy group: {group('MyVPN')}")
    if (state / "groups-refresh").read_text().strip() != "0":
        fail("route engine must be told to re-read the groups")
    if "system configuration save" not in (tmp / "running.cfg.log").read_text():
        fail("router configuration must be saved")
    run("route-domain", "add", "new.example", expect="result=unchanged", rc=0)
    run("route-domain", "remove", "old.example", expect="result=changed")
    if group("MyVPN") != ["new.example"]:
        fail("domain not removed from the policy group")
    calls = (tmp / "running.cfg.log").read_text()
    for bad in ("bad..example", "-x.example", "a b.example", "x.example;reboot", "localhost", "1.2.3.4", "x" * 64 + ".example"):
        run("route-domain", "add", bad, expect="error=invalid_domain", rc=64)
    if (tmp / "running.cfg.log").read_text() != calls:
        fail("invalid input must not reach the router CLI")

    # Keenetic rejects the command: error, nothing saved.
    (tmp / "running.cfg.reject").touch()
    run("route-domain", "add", "rejected.example", expect="error=router_rejected", rc=1)
    (tmp / "running.cfg.reject").unlink()
    # Keenetic claims success but the group did not change: verification fails.
    (tmp / "running.cfg.lie").touch()
    run("route-domain", "add", "ghost.example", expect="error=verification_failed", rc=1)
    (tmp / "running.cfg.lie").unlink()
    if "ghost.example" in group("MyVPN") or "rejected.example" in group("MyVPN"):
        fail("failed changes must not stay in the group")
    (tmp / "running.cfg.nosave").touch()
    run("route-domain", "add", "unsaved.example", expect="error=config_save_failed")
    (tmp / "running.cfg.nosave").unlink()

    # The change lock is honoured and released.
    lock = tmp / "change.lock"; lock.mkdir(); (lock / "pid").write_text(f"{os.getpid()}\n")
    run("route-domain", "add", "locked.example", expect="error=route_change_busy", rc=75)
    (lock / "pid").unlink(); lock.rmdir()
    if lock.exists():
        fail("change lock must be released")

    # AdaptiveAuto: pin moves the domain to the policy group, remove drops it everywhere.
    run("adaptive", "pin", "slow.example", expect="result=changed")
    if "slow.example" in group("AdaptiveAuto") or "slow.example" not in group("MyVPN"):
        fail("pin must move the domain from AdaptiveAuto to the policy group")
    for f in ("adaptive-persist.txt", "adaptive-domains.txt"):
        if "slow.example" in (state / f).read_text():
            fail(f"pin must drop the domain from {f}")
    run("adaptive", "remove", "other.example", expect="result=changed")
    if group("AdaptiveAuto") or (state / "adaptive-persist.txt").read_text().strip():
        fail("remove must clear AdaptiveAuto and the persist list")
    run("adaptive", "remove", "other.example", expect="result=unchanged")

    # Force VPN list: comments and other entries survive.
    force = etc / "route-engine/force-vpn.conf"
    run("force-vpn", "add", "claude.ai", expect="result=changed")
    run("force-vpn", "add", "claude.ai", expect="result=unchanged")
    run("force-vpn", "remove", "kept.example", expect="result=changed")
    if force.read_text() != "# forced\nclaude.ai\n":
        fail(f"force-vpn list edited incorrectly: {force.read_text()!r}")

    # Domain categories.
    cats = etc / "route-engine/categories.tsv"
    run("domain-category", "adult", "0", expect="result=changed")
    if "adult|18+|AUTO|@catalogs/adult.domains|0" not in cats.read_text() or "steam|Steam|AUTO|@catalogs/steam.domains|1" not in cats.read_text():
        fail("category flag not written")
    run("domain-category", "missing", "1", expect="error=invalid_category")
    run("domain-category", "adult", "2", expect="error=invalid_value")

    # Tunnel guard flag.
    flag = etc / "tunnel-guard.disabled"
    run("tunnel-guard", "0", expect="result=changed")
    if not flag.exists():
        fail("tunnel guard disable flag missing")
    run("tunnel-guard", "1", expect="result=changed")
    if flag.exists():
        fail("tunnel guard disable flag must be removed")
    run("tunnel-guard", "1", "x", expect="error=usage")

    # Wi-Fi config: created on first write, strict values, no shell injection.
    wifi = etc / "wifi-client-guard.conf"
    run("wifi", "ENABLED", "1", expect="result=changed")
    run("wifi", "WEAK_5G_RSSI", "-70", expect="result=changed")
    run("wifi", "WINDOW_SEC", "0086400", expect="error=invalid_value")
    run("wifi", "ENABLED", "1;reboot", expect="error=invalid_value")
    run("wifi", "WEAK_5G_RSSI", "-20", expect="error=invalid_value")
    run("wifi", "AUTO_APPLY", "1", expect="error=invalid_setting")
    run("wifi", "HOME_BRIDGE", "Bridge0", expect="error=invalid_setting")
    if wifi.read_text() != "ENABLED=1\nWEAK_5G_RSSI=-70\n":
        fail(f"wifi config written incorrectly: {wifi.read_text()!r}")

    # Update config: mode is kept, window stays valid for the updater.
    run("update", "safe_window_start", "02:30", expect="result=changed")
    run("update", "safe_window_end", "02:30", expect="error=invalid_window")
    run("update", "safe_window_end", "25:00", expect="error=invalid_value")
    run("update", "check_interval_seconds", "60", expect="error=invalid_value")
    run("update", "manifest_url", "http://evil", expect="error=invalid_setting")
    run("update", "check_interval_seconds", "3600", expect="result=changed")
    if stat.S_IMODE(upd.stat().st_mode) != 0o600:
        fail("update.conf mode must be preserved")
    if upd.read_text() != "update_enabled=1\nsafe_window_start=02:30\nsafe_window_end=05:00\ncheck_interval_seconds=3600\n":
        fail(f"update.conf written incorrectly: {upd.read_text()!r}")

    if not any((tmp / "backup").glob("update.conf.*")):
        fail("changes must leave a backup")
    audit = (tmp / "audit.log").read_text()
    if "CONSOLE_CONFIG|route-domain add new.example group=MyVPN result=changed" not in audit:
        fail("audit log line missing")
    if list(etc.rglob("*.console.*")):
        fail("temporary files left behind")

    # An update in progress blocks every write.
    (tmp / "root/tmp/vward-update-requested").write_text("x")
    run("wifi", "ENABLED", "0", expect="error=updater_busy", rc=75)
    (tmp / "root/tmp/vward-update-requested").unlink()

    # ---- Through the Console API ----
    import json
    import shutil

    def api(query, body="", method="GET", helper=HELPER):
        e = env | {"REQUEST_METHOD": method, "QUERY_STRING": query, "CONTENT_TYPE": "application/x-www-form-urlencoded",
                   "CONTENT_LENGTH": str(len(body.encode())), "HTTP_X_VWARD_REQUEST": "console", "JQ": shutil.which("jq"),
                   "VWARD_CONSOLE_CONFIG_BIN": str(helper)}
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], input=body, env=e, text=True, capture_output=True)
        if r.returncode != 0:
            fail(f"api {query}: rc={r.returncode} {r.stderr}")
        return json.loads(r.stdout.split("\n\n", 1)[1])

    data = api("action=config-data")
    if not data.get("ok") or not data.get("writable"):
        fail(f"config-data: {data}")
    route = data["route"]
    if route["force_vpn"] != ["claude.ai"] or route["adaptive"] != [] or route["categories"][1] != {"id": "adult", "title": "18+", "enabled": False}:
        fail(f"config-data route section: {route}")
    if data["tunnel_guard"] != {"enabled": True}:
        fail("config-data tunnel guard")
    if data["wifi"] != {"ENABLED": True, "CONTROL_ENABLED": False, "WINDOW_SEC": 86400, "BAND_SWITCH_WARN": 20, "WEAK_5G_SAMPLE_WARN": 5, "WEAK_5G_RSSI": -70}:
        fail(f"config-data wifi: {data['wifi']}")
    if data["update"] != {"safe_window_start": "02:30", "safe_window_end": "05:00", "check_interval_seconds": 3600}:
        fail(f"config-data update: {data['update']}")

    post = lambda body: api("action=config", body, "POST")
    if post("op=update&target=safe_window_end&value=06%3A15") != {"ok": True, "op": "update", "result": "changed"}:
        fail("percent-encoded time must be accepted")
    if post("op=wifi&target=WEAK_5G_RSSI&value=-72")["result"] != "changed":
        fail("negative RSSI must pass through the API")
    if post("op=force-vpn&action=add&target=Example.ORG")["result"] != "changed" or "example.org" not in (etc / "route-engine/force-vpn.conf").read_text():
        fail("force-vpn add through the API")
    if post("op=route-domain&action=add&target=api.example")["result"] != "changed" or "api.example" not in group("MyVPN"):
        fail("route-domain add through the API")
    for body, err in (
        ("op=tunnel-guard&value=0", "confirmation_required"),
        ("op=wifi&target=CONTROL_ENABLED&value=1", "confirmation_required"),
        ("op=wifi&target=ENABLED&value=1%3Breboot", "invalid_value"),
        ("op=force-vpn&action=add&target=a%20b.example", "invalid_value"),
        ("op=force-vpn&action=add&target=$(reboot).example", "invalid_value"),
        ("op=shell&target=x", "invalid_operation"),
        ("op=wifi&target=ENABLED&value=1&extra=1", "unknown_parameter"),
        ("op=update&target=manifest_url&value=x", "invalid_setting"),
        ("op=route-domain&action=add&target=bad..example", "invalid_domain"),
    ):
        got = post(body)
        if got.get("error") != err:
            fail(f"{body}: {got} (expected {err})")
    if (etc / "tunnel-guard.disabled").exists():
        fail("tunnel guard must not be disabled without confirmation")
    if post("op=tunnel-guard&value=0&confirm=TUNNEL_GUARD_DISABLE")["result"] != "changed" or not (etc / "tunnel-guard.disabled").exists():
        fail("confirmed tunnel guard disable")
    if post("op=wifi&target=CONTROL_ENABLED&value=1&confirm=WIFI_CONTROL_ENABLE")["result"] != "changed":
        fail("confirmed Wi-Fi control enable")
    if api("action=config", "op=wifi", "GET").get("error") != "method_not_allowed":
        fail("config must be POST only")
    if api("action=config-data", "x=1", "POST").get("error") != "method_not_allowed":
        fail("config-data must be GET only")
    if api("action=config", "op=wifi&target=ENABLED&value=0", "POST", tmp / "missing").get("error") != "action_unavailable":
        fail("missing helper must be reported")

print("CONSOLE_CONFIG=PASS")
