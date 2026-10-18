#!/usr/bin/env python3
"""«Очистка» and «Сброс настроек» (fix.30): only VWARD's own leftovers go, the newest copy of
every kind stays, the owner's backups and settings are never touched; a settings reset turns
the switches back as after installation, with a copy of the settings first, and leaves the
tunnels, lists and the update channel alone."""

import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_CLEANUP=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    etc = tmp / "etc"; (etc / "route-engine").mkdir(parents=True); (etc / "components").mkdir()
    bk = tmp / "backups"; logs = tmp / "log"

    def files(d: Path, names, size=2048):
        d.mkdir(parents=True, exist_ok=True)
        for i, n in enumerate(names):
            p = d / n
            if n.endswith("/"):
                p.mkdir(); (p / "f").write_bytes(b"x" * size); p = p
            else:
                p.write_bytes(b"x" * size)
            t = time.time() - 1000 + i * 10
            os.utime(p, (t, t))

    files(logs / "vward/archive", ["a.log.1.gz", "b.log.1.gz"])
    files(logs / "vward/diagnostics", ["r1.txt"])
    files(bk / "forensics", ["inc-1/", "inc-2/", "inc-3/"])
    files(bk / "ext-update", ["agh-1/", "agh-2/"])
    files(tmp / "console-backup", ["c1", "c2", "c3"])
    files(bk / "ads-privacy-guard", ["publish-1/", "publish-2/"])
    files(bk / "ads-privacy-guard/manual", ["m1/", "m2/"])
    files(bk / "snapshots", ["vward-20261001-010101.tar.gz"])
    files(logs, ["vward-route.log"], 4096)
    (etc / "tunnels").mkdir(); (etc / "tunnels/key.conf").write_text("PrivateKey = SECRET\n")
    for f in ("tunnel-guard.disabled", "wan-guard.disabled", "agents.conf", "route-engine/adaptive.disabled", "components/wifi-client-guard.disabled", "components/vward.off.keep"):
        (etc / f).write_text("x\n")
    (etc / "route-engine/domain-lists.conf").write_text("smartdns_guard=0\nwatch.list1=1\n")
    (etc / "update.conf").write_text("manifest_url=https://example.invalid/updates/dev/update-manifest.json\n")
    (etc / "ext-update.conf").write_text("AGH_AUTO=1\nENTWARE_AUTO=1\n")
    ndmc = tmp / "ndmc"; ndmc.write_text("#!/bin/sh\necho 'interface Test0'\n"); ndmc.chmod(0o755)
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {"VWARD_CONSOLE_ETC": str(etc), "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_NDMC": str(ndmc),
                        "VWARD_SNAPSHOT_DIR": str(bk / "snapshots"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
                        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "console-backup"), "VWARD_ROOT_PREFIX": str(tmp / "root"),
                        "VWARD_BACKUPS_ROOT": str(bk), "VWARD_LOG_ROOT": str(logs), "VWARD_COMPONENT_STATE": str(etc / "components"),
                        "VWARD_EXT_UPDATE_CONF": str(etc / "ext-update.conf"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "lock"),
                        "VWARD_ROUTE_ENGINE_INIT": str(tmp / "no-init"),
                        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
                        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv")}

    def run(*args):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True)
        return r.stdout.strip().splitlines()

    sizes = {l.split("=", 1)[1].split(":")[0]: int(l.split(":")[1]) for l in run("cleanup", "sizes") if l.startswith("size=")}
    for g in ("archive", "diagnostics", "forensics", "packages", "settings", "ads", "journals"):
        if not sizes.get(g):
            fail(f"group {g} must show what it frees: {sizes}")
    if run("cleanup", "../x")[-1] != "error=invalid_value":
        fail("an unknown group must be refused")
    if run("cleanup", "forensics")[-1] != "result=changed" or sorted(p.name for p in (bk / "forensics").iterdir()) != ["inc-3"]:
        fail("a group keeps its newest copy only")
    if run("cleanup", "all")[-1] != "result=changed":
        fail("cleanup all")
    left = {d: sorted(p.name for p in (bk / d).iterdir() if p.is_dir() or d != "ads-privacy-guard") for d in ("ext-update", "ads-privacy-guard/manual")}
    if left != {"ext-update": ["agh-2"], "ads-privacy-guard/manual": ["m2"]}:
        fail(f"the newest copy of every kind stays: {left}")
    if sorted(p.name for p in (bk / "ads-privacy-guard").iterdir() if p.name.startswith("publish")) != ["publish-2"]:
        fail("the newest published filter stays")
    if list((logs / "vward/archive").iterdir()) or list((tmp / "console-backup").iterdir()) != [tmp / "console-backup/c3"]:
        fail("archives go, the newest settings copy stays")
    if not (bk / "snapshots/vward-20261001-010101.tar.gz").exists() or not (logs / "vward-route.log").exists() or not (etc / "tunnels/key.conf").exists():
        fail("the owner's backups, live journals and keys are never cleaned")
    if run("cleanup", "all")[-1] != "result=unchanged":
        fail("a second cleanup has nothing to do")

    # Reset: the switches back on, a copy first; lists and the update channel stay.
    out = run("reset", "settings")
    if out[-1] != "result=changed":
        fail(f"reset: {out}")
    for f in ("tunnel-guard.disabled", "wan-guard.disabled", "agents.conf", "route-engine/adaptive.disabled", "components/wifi-client-guard.disabled"):
        if (etc / f).exists():
            fail(f"reset must remove {f}")
    if "smartdns_guard=1" not in (etc / "route-engine/domain-lists.conf").read_text() or "watch.list1=1" not in (etc / "route-engine/domain-lists.conf").read_text():
        fail("the Smart DNS agent back on, the lists' settings kept")
    if "AGH_AUTO=0" not in (etc / "ext-update.conf").read_text() or not (etc / "update.conf").exists() or not (etc / "tunnels/key.conf").exists():
        fail("automatic package updates off; the update channel and keys stay")
    if not [p for p in (bk / "snapshots").iterdir() if p.name.endswith("-prereset.tar.gz")]:
        fail("a copy of the settings must come first")
    if run("reset", "full")[-1] != "error=invalid_value":
        fail("only the settings reset exists")
    API = (ROOT / "web/cgi-bin/api.cgi").read_text()
    if "reset) set -- \"$OP\" \"$TARGET\"; REQUIRED=RESET_SETTINGS ;;" not in API or "if [ \"$ACTION\" = cleanup-data ]; then" not in API:
        fail("the API: cleanup-data and a confirmed reset")

print("CONSOLE_CLEANUP=PASS")
