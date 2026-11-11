#!/usr/bin/env python3
"""Lightened VWARD (owner 11.11.2026): only Adaptive auto and the VPN run by default.

lite_defaults is taken from vward-housekeeping.sh as it is: the guards, Wi-Fi, the night check
of IP categories and the ad protection go off once as the Panel switches them off; a component
the owner switches back on stays on; a tunnel guard holding the tunnel down and the ad
protection while AdGuard Home is in use are kept. vward_extra: optional parts are off unless
NAME.on, VWARD_EXTRAS=all turns them all on; the optional parts are gated in the code."""
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HK = (ROOT / "components/runtime/scripts/vward-housekeeping.sh").read_text(encoding="utf-8")
SUP = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text(encoding="utf-8")
LIB = ROOT / "components/runtime/lib/vward-runtime-admission.sh"
INSTALL = (ROOT / "install.sh").read_text(encoding="utf-8")


def fail(message: str) -> None:
    raise SystemExit(f"LITE_DEFAULTS=FAIL: {message}")


if "\nlite_defaults()\n" not in HK or "\nlite_defaults\n" not in HK:
    fail("housekeeping has no lite_defaults step")
FUNC = HK[HK.index("\nlite_defaults()\n"):HK.index("\nlite_defaults\n")]


def run(tmp: Path, extra_env: str = "") -> list[str]:
    h = tmp / "h.sh"
    h.write_text(f"""R="{tmp}/root" HOUSE_LOG="{tmp}/house.log"
VWARD_COMPONENT_STATE="{tmp}/components" VWARD_LITE_STATE="{tmp}/components"
VWARD_TUNNEL_GUARD_STATE="{tmp}/guard.state"
VWARD_ADGUARD_CONFIG="{tmp}/AdGuardHome.yaml"
{extra_env}
. "{LIB}"
{FUNC}
lite_defaults
""")
    subprocess.run(["sh", str(h)], check=True, timeout=30)
    return sorted(p.name for p in (tmp / "components").glob("*")) if (tmp / "components").exists() else []


ALL = ["ads-privacy-guard", "policy-sync", "tunnel-guard", "wan-guard", "wifi-client-guard"]
with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    # No AdGuard Home: all five go off, each once.
    names = run(tmp)
    want = sorted([f"{c}.disabled" for c in ALL] + [f"{c}.lite" for c in ALL])
    if names != want:
        fail(f"first run: {names}")
    if len((tmp / "house.log").read_text().splitlines()) != 5:
        fail("one journal line per component switched off")
    # The owner switches the tunnel guard back on in the Panel: it stays on.
    (tmp / "components/tunnel-guard.disabled").unlink()
    run(tmp)
    if (tmp / "components/tunnel-guard.disabled").exists():
        fail("a component the owner switched back on was switched off again")
    if len((tmp / "house.log").read_text().splitlines()) != 5:
        fail("a second run writes nothing")

with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    # AdGuard Home in use, the guard holding the tunnel down: both kept, tried again later.
    (tmp / "AdGuardHome.yaml").write_text("dns: {}\n")
    (tmp / "guard.state").write_text("FAILOPEN_ACTIVE=1\n")
    names = run(tmp)
    for c in ("ads-privacy-guard", "tunnel-guard"):
        if f"{c}.disabled" in names or f"{c}.lite" in names:
            fail(f"{c} must be kept for now: {names}")
    (tmp / "guard.state").write_text("FAILOPEN_ACTIVE=0\n")
    (tmp / "components/adguardhome.disabled").write_text("off\n")
    names = run(tmp)
    if "tunnel-guard.disabled" not in names or "ads-privacy-guard.disabled" not in names:
        fail(f"once safe they go off: {names}")

with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    # Without its own setting the step writes under R, never the host's /opt (the shared
    # library's VWARD_COMPONENT_STATE has no R).
    h = tmp / "r.sh"
    h.write_text(f"""R="{tmp}/root" HOUSE_LOG="{tmp}/house.log" VWARD_ADGUARD_CONFIG="{tmp}/none"
VWARD_TUNNEL_GUARD_STATE="{tmp}/none"
. "{LIB}"
{FUNC}
lite_defaults
""")
    subprocess.run(["sh", str(h)], check=True, timeout=30)
    if not (tmp / "root/opt/etc/vward/components/tunnel-guard.disabled").exists():
        fail("lite_defaults does not write under R")

with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    # Everything on as before.
    if run(tmp, "VWARD_EXTRAS=all"):
        fail("VWARD_EXTRAS=all switches nothing off")
    (tmp / "components").mkdir()
    (tmp / "components/all.on").write_text("")
    if run(tmp) != ["all.on"]:
        fail("all.on switches nothing off")

with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    out = subprocess.run(["sh", "-c", f'VWARD_COMPONENT_STATE="{tmp}"; . "{LIB}"; '
                          'vward_extra sentinel && echo on1; touch "$VWARD_COMPONENT_STATE/sentinel.on"; '
                          'vward_extra sentinel && echo on2; vward_extra integrity || echo off3; '
                          'VWARD_EXTRAS=all vward_extra integrity && echo on4; vward_extra "../x" || echo bad5; '
                          'touch "$VWARD_COMPONENT_STATE/all.on"; vward_extra backup && echo on6'],
                         capture_output=True, text=True, check=True).stdout.split()
    if out != ["on2", "off3", "on4", "bad5", "on6"]:
        fail(f"vward_extra: {out}")

# The optional parts are behind their switch in the code.
for part, where in (("backup", HK), ("repair", HK), ("ext-update", HK), ("sentinel", HK),
                    ("services-refresh", HK), ("flash-watch", HK), ("integrity", HK),
                    ("sentinel", SUP), ("memory-watch", SUP)):
    if f"vward_extra {part}" not in where:
        fail(f"{part} is not behind vward_extra")
if "vward_extra repair || repair_if_crashing() { return 0; }" not in HK:
    fail("package repairs (opkg --force-reinstall) must be off by default")
for c in ("tunnel-guard", "wan-guard", "wifi-client-guard", "policy-sync"):
    if c not in INSTALL[INSTALL.index("Lightened VWARD"):INSTALL.index("Lightened VWARD") + 800]:
        fail(f"install.sh does not start {c} switched off")
print("LITE_DEFAULTS=PASS")
