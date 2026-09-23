#!/usr/bin/env python3
"""Disable every optional component in turn: nothing else may break.

For each component the real Console writer disables it (with its cascade);
then every entry point of the disabled components must stop at its gate
without touching anything, every other entry point must be gated only by its
own component, the Console API must keep answering, manual actions of the
disabled components must be refused, and the updater health profiles must
still pass because the files stay installed.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config/components/component-registry.json"
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
API = ROOT / "web/cgi-bin/api.cgi"
HEALTH = ROOT / "components/update-engine/vward-update-health.sh"
ADMISSION = ROOT / "components/runtime/lib/vward-runtime-admission.sh"
registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
comps = {c["id"]: c for c in registry["components"]}
optional = [c for c in comps if not comps[c]["core"]]
JQ = shutil.which("jq")


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


# Entry points that run on a schedule, from the supervisor or from the Console,
# with the arguments they need to reach their gate.
ENTRY = {
    "components/route-engine/scripts/vward-route-engine.sh": ("route-engine", []),
    "components/runtime/init.d/S91vward-route-engine": ("route-engine", ["start"]),
    "components/route-reconciler/scripts/vward-route-reconciler.sh": ("route-reconciler", []),
    "components/route-tools/scripts/vward-route-hints-update.sh": ("route-tools", []),
    "components/route-tools/scripts/vward-route.sh": ("route-tools", []),
    "components/route-tools/scripts/vward-route-discovery.sh": ("route-tools", []),
    "components/tunnel-guard/scripts/vward-tunnel-health.sh": ("tunnel-guard", []),
    "components/tunnel-guard/scripts/vward-tunnel-guard.sh": ("tunnel-guard", []),
    "components/wan-guard/scripts/vward-wan-guard.sh": ("wan-guard", []),
    "components/wan-guard/scripts/vward-wan-recovery.sh": ("wan-guard", ["dhcp-renew"]),
    "components/wifi-client-guard/scripts/vward-wifi-client-scheduler.sh": ("wifi-client-guard", []),
    "components/wifi-client-guard/scripts/vward-wifi-client-control.sh": ("wifi-client-guard", ["bind-2g", "aa:bb:cc:dd:ee:01", "WIFI_BIND_2G"]),
    "components/policy-sync/scripts/vward-policy-chain.sh": ("policy-sync", []),
    "components/policy-sync/scripts/vward-policy-sync.sh": ("policy-sync", ["--reconcile"]),
    "components/policy-sync/scripts/vward-policy-reconcile.sh": ("policy-sync", []),
    "components/ads-privacy-guard/scripts/vward-ads-privacy-scheduler.sh": ("ads-privacy-guard", []),
    "components/ads-privacy-guard/scripts/vward-ads-privacy-job.sh": ("ads-privacy-guard", []),
}
# Console manual actions and the component that owns them.
CONTROL = {
    "refresh-hints": ("route-tools", ""), "route-reconcile": ("route-reconciler", "ROUTE_RECONCILE"),
    "policy-refresh": ("policy-sync", "POLICY_REFRESH"), "tunnel-health": ("tunnel-guard", ""),
    "wan-renew": ("wan-guard", "WAN_RENEW"), "wan-bounce": ("wan-guard", "WAN_BOUNCE"),
}

# 1. Every entry point is gated exactly by the component that owns it.
owner_of = {}
for line in (ROOT / "config/components/package-map.tsv").read_text().splitlines():
    if line and not line.startswith("#"):
        comp, source, _t, _m = line.split("\t")
        owner_of[source] = comp
for path, (cid, _args) in ENTRY.items():
    gates = re.findall(r"vward_component_(?:gate|enabled) ([a-z-]+)", (ROOT / path).read_text())
    if gates != [cid]:
        fail(f"{path} must be gated by {cid} alone, found {gates}")
    if owner_of.get(path) not in (cid, "runtime"):
        fail(f"{path} belongs to {owner_of.get(path)}, not {cid}")
scheduled = set(re.findall(r"/opt/bin/(vward-[a-z0-9-]+\.sh)", (ROOT / "config/cron/root.crontab").read_text()))
scheduled |= set(re.findall(r"/opt/bin/(vward-[a-z0-9-]+\.sh)", (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text()))
gated = {Path(p).name for p in ENTRY}
for name in scheduled:
    source = next((s for s in owner_of if s.endswith("/" + name)), None)
    if source and not comps[owner_of[source]]["core"] and name not in gated:
        fail(f"scheduled entry point {name} of {owner_of[source]} has no component gate")
health = HEALTH.read_text()
if "ads-privacy-guard.disabled" not in health:
    fail("updater health must not run the Ads functional check while Ads is disabled")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "root/tmp").mkdir(parents=True)
    profile = tmp / "profile.sh"
    profile.write_text("""vward_profile_load(){
VWARD_WAN_DEVICE=eth9; VWARD_WAN_INTERFACE=Uplink9; VWARD_LAN_ADDRESS=10.9.0.1; VWARD_LAN_SUBNET=10.9.0.0/24
VWARD_LAN_DEVICE=br9; VWARD_LAN_INTERFACE=Bridge9; VWARD_DNS_SERVER=10.9.0.1; VWARD_PROBE_DNS=10.9.0.1
VWARD_TUNNEL_DEVICE=nwg9; VWARD_TUNNEL_INTERFACE=Wireguard9; VWARD_POLICY_GROUP=policy9; VWARD_RCI_BASE=http://127.0.0.1:9/rci
VWARD_ADGUARD_ADDRESS=10.9.0.1; VWARD_ADGUARD_PORT=3000; VWARD_CONSOLE_PORT=8088; }
vward_discover_lan_interface(){ echo Bridge9; }
""")
    # Collection switched on, so the Wi-Fi scheduler reaches its component gate.
    (tmp / "wifi.conf").write_text("ENABLED=1\nCONTROL_ENABLED=1\n")
    installed = tmp / "installed"
    for line in (ROOT / "config/components/package-map.tsv").read_text().splitlines():
        if line and not line.startswith("#"):
            _c, source, target, mode = line.split("\t")
            dest = installed / target.lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / source, dest)
            dest.chmod(int(mode, 8))
    # The updater itself lives in a slot installed by its own installer.
    slot = installed / "opt/share/vward/updater/current"
    slot.mkdir(parents=True)
    for f in (ROOT / "components/update-engine").glob("*.sh"):
        shutil.copy(f, slot / f.name); (slot / f.name).chmod(0o755)
    shutil.copy(REGISTRY, slot / "component-registry.json")

    for cid in optional:
        state = tmp / f"state-{cid}"
        base = os.environ | {
            "VWARD_COMPONENT_STATE": str(state), "VWARD_COMPONENT_REGISTRY": str(REGISTRY),
            "VWARD_ADMISSION_LIB": str(ADMISSION), "VWARD_ROOT_PREFIX": str(tmp / "root"),
            "VWARD_PROFILE_LIB": str(profile), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
            "VWARD_ROUTE_ENGINE_INIT": str(tmp / "absent"), "VWARD_TUNNEL_GUARD_STATE": str(tmp / "absent"),
            "JQ": JQ, "VWARD_WIFI_CLIENT_GUARD_CONF": str(tmp / "wifi.conf"),
        }
        r = subprocess.run(["sh", str(HELPER), "component", cid, "0"], env=base, text=True, capture_output=True)
        if r.stdout.strip().splitlines()[-1:] != ["result=changed"]:
            fail(f"disabling {cid}: {r.stdout!r} {r.stderr!r}")
        off = {p.name[:-len(".disabled")] for p in state.glob("*.disabled")}
        want = {cid} | {c for c in comps if set(comps[c]["requires_running"]) & off}
        if off != want or cid not in off:
            fail(f"disabling {cid} disabled {sorted(off)}, expected {sorted(want)}")

        # 2. Disabled entry points stop at their gate; nothing past it runs.
        for path, (owner, args) in ENTRY.items():
            if owner not in off:
                continue
            try:
                r = subprocess.run(["sh", str(ROOT / path), *args], env=base, text=True, capture_output=True, timeout=30)
            except subprocess.TimeoutExpired:
                fail(f"{path} kept running although {owner} is disabled")
            if f"COMPONENT_DISABLED={owner}" not in r.stdout or r.returncode not in (0, 69):
                fail(f"{path} with {owner} disabled: rc={r.returncode} out={r.stdout[-200:]!r} err={r.stderr[-200:]!r}")
        if list((tmp / "root/tmp").glob("vward-runtime-active/*")):
            fail(f"a disabled entry point left an admission slot ({cid})")

        # 3. The Console keeps answering and refuses actions of disabled components.
        def api(query, body="", method="GET"):
            env = base | {"REQUEST_METHOD": method, "QUERY_STRING": query, "CONTENT_TYPE": "application/x-www-form-urlencoded",
                          "CONTENT_LENGTH": str(len(body)), "HTTP_X_VWARD_REQUEST": "console", "VWARD_PROFILE_LIB": "/nonexistent",
                          "CURL": "/bin/false"}
            r = subprocess.run(["sh", str(API)], input=body, env=env, text=True, capture_output=True, timeout=60)
            try:
                return json.loads(r.stdout.split("\n\n", 1)[1])
            except (IndexError, ValueError):
                fail(f"API {query} with {sorted(off)} disabled returned no JSON: {r.stdout[-200:]!r} {r.stderr[-200:]!r}")
        for action in ("status", "config-data", "route-data", "wifi-data", "ads-data", "update-data", "security-data", "diagnostics"):
            data = api("action=" + action)
            if action in ("status", "config-data", "route-data", "ads-data", "wifi-data") and data.get("ok") is not True:
                fail(f"API {action} broke with {sorted(off)} disabled: {data}")
        shown = {c["id"] for c in api("action=config-data")["components"] if not c["enabled"]}
        if shown != off:
            fail(f"config-data shows {sorted(shown)} disabled, expected {sorted(off)}")
        for op, (owner, token) in CONTROL.items():
            if owner in off:
                got = api("action=control", f"op={op}&confirm={token}" if token else f"op={op}", "POST")
                if got.get("error") != "component_disabled":
                    fail(f"control {op} with {owner} disabled: {got}")
        if "wifi-client-guard" in off and api("action=wifi-control", "op=auto&mac=aa:bb:cc:dd:ee:01&confirm=WIFI_BAND_AUTO", "POST").get("error") != "component_disabled":
            fail("Wi-Fi control must be refused while Wi-Fi Client Guard is disabled")
        if "ads-privacy-guard" in off and api("action=ads-control", "op=pause", "POST").get("error") != "component_disabled":
            fail("Ads actions must be refused while Ads & Privacy Guard is disabled")

        # 4. Files stay installed, so every updater health profile still passes.
        for profile_name in sorted({c["health_profile"] for c in comps.values()} | {"full"}):
            r = subprocess.run(["sh", str(HEALTH), profile_name], env=base | {"VWARD_ROOT_PREFIX": str(installed)},
                               text=True, capture_output=True, timeout=120)
            if r.returncode != 0:
                fail(f"health profile {profile_name} failed with {sorted(off)} disabled: {r.stderr[-300:]}")

        # 5. Enabling brings it back, with what it requires.
        r = subprocess.run(["sh", str(HELPER), "component", cid, "1"], env=base, text=True, capture_output=True)
        left = {p.name[:-len(".disabled")] for p in state.glob("*.disabled")}
        if cid in left or set(comps[cid]["requires_running"]) & left:
            fail(f"enabling {cid} left {sorted(left)} disabled")

    # Core components cannot be disabled, alone or through a cascade.
    for cid in (c for c in comps if comps[c]["core"]):
        r = subprocess.run(["sh", str(HELPER), "component", cid, "0"], env=base, text=True, capture_output=True)
        if r.stdout.strip().splitlines()[-1:] != ["error=core_component"]:
            fail(f"core component {cid} was not protected: {r.stdout!r}")

print(f"COMPONENT_RESILIENCE=PASS ({len(optional)} components)")
