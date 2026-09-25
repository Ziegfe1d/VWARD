#!/usr/bin/env python3
"""Backups of VWARD's settings: create (root-only, catalogs left out, router
config as a reference copy), list, restore (a snapshot of the current state
first, the update key never replaced), daily automatic, keep seven."""

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    etc = tmp / "etc"; (etc / "route-engine").mkdir(parents=True); (etc / "tunnels/Wireguard0").mkdir(parents=True)
    (etc / "device.conf").write_text("VWARD_WAN_INTERFACE=GigabitEthernet1\n")
    (etc / "route-engine/domain-lists.conf").write_text("watch.domain-list4=1\n")
    (etc / "route-engine/hints-catalog.tsv").write_text("x\n" * 1000)
    (etc / "tunnels/Wireguard0/current.conf").write_text("[Interface]\nPrivateKey = SECRET-TUNNEL-KEY\n")
    (etc / "ads-privacy-guard").mkdir()
    (etc / "ads-privacy-guard/agh-api.auth").write_text("admin:SECRET-AGH-PASSWORD\n")
    (etc / "ads-privacy-guard/allowlist.tsv").write_text("good.example|exact|manual\n")
    (etc / "update-public.pem").write_text("KEY-OLD\n")
    state = tmp / "route"; state.mkdir()
    (state / "adaptive-persist.txt").write_text("slow.example\n")
    ndmc = tmp / "ndmc"; ndmc.write_text('#!/bin/sh\necho "interface Wireguard0"\necho "    wireguard private-key SECRET-ROUTER-KEY"\n'); ndmc.chmod(0o755)
    snaps = tmp / "snaps"
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {"VWARD_CONSOLE_ETC": str(etc), "VWARD_ROUTE_STATE": str(state), "VWARD_NDMC": str(ndmc),
                        "VWARD_SNAPSHOT_DIR": str(snaps), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
                        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_ROOT_PREFIX": str(tmp / "root"),
                        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
                        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv")}

    def run(*args):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True)
        return r.stdout.strip().splitlines()

    out = run("backup-create", "manual")
    if out[-1] != "result=changed":
        fail(f"create: {out}")
    name = [l for l in out if l.startswith("info.name=")][0].split("=", 1)[1]
    arc = snaps / name
    if oct(arc.stat().st_mode & 0o777) != "0o600":
        fail("a backup must be root-only")
    with tarfile.open(arc) as t:
        names = t.getnames()
    for want in ("./etc/device.conf", "./etc/tunnels/Wireguard0/current.conf", "./state/adaptive-persist.txt", "./router-running-config.txt", "./backup.meta"):
        if want not in names:
            fail(f"{want} missing from the backup: {names}")
    if "./etc/route-engine/hints-catalog.tsv" in names:
        fail("the nightly catalog must be left out")
    if run("backup-create", "auto")[-1] != "result=unchanged":
        fail("the automatic backup runs once a day")

    # Restore: settings back, the current state kept, the update key untouched.
    (etc / "device.conf").write_text("VWARD_WAN_INTERFACE=Changed\n")
    (etc / "update-public.pem").write_text("KEY-NEW\n")
    (state / "adaptive-persist.txt").write_text("")
    if run("backup-restore", name)[-1] != "result=changed":
        fail("restore failed")
    if (etc / "device.conf").read_text() != "VWARD_WAN_INTERFACE=GigabitEthernet1\n" or (state / "adaptive-persist.txt").read_text() != "slow.example\n":
        fail("restore did not bring the settings back")
    if (etc / "update-public.pem").read_text() != "KEY-NEW\n":
        fail("a restore must not change the update key")
    if not [p for p in snaps.iterdir() if p.name.endswith("-prerestore.tar.gz")]:
        fail("the state before a restore must be kept")
    for bad in ("../x", "vward-1.tar.gz", "vward-20260925-010101.tar.gz"):
        if run("backup-restore", bad)[-1] not in ("error=invalid_backup", "error=unknown_backup"):
            fail(f"{bad} must be refused")
    damaged = snaps / "vward-20260101-000000.tar.gz"; damaged.write_text("not a tar")
    if run("backup-restore", damaged.name)[-1] != "error=backup_damaged":
        fail("a damaged backup must be refused")
    damaged.unlink()

    # Keep seven.
    for i in range(9):
        (snaps / f"vward-2025010{i}-000000.tar.gz").write_bytes(arc.read_bytes())
    run("backup-create", "manual")
    if len(list(snaps.iterdir())) != 7:
        fail(f"only the newest seven are kept: {sorted(p.name for p in snaps.iterdir())}")

    # API list.
    r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], text=True, capture_output=True,
                       env=env | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=backup-data", "JQ": shutil.which("jq"), "VWARD_PROFILE_LIB": "/nonexistent"})
    data = json.loads(r.stdout.split("\n\n", 1)[1])
    if not data["ok"] or len(data["backups"]) != 7 or data["backups"][0]["kind"] != "manual" or not data["backups"][0]["created"].startswith("20"):
        fail(f"backup-data: {data}")

    # Download: the settings leave the router, the secrets do not.
    newest = data["backups"][0]["name"]
    r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], capture_output=True,
                       env=env | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=backup-download&name=" + newest,
                                  "JQ": shutil.which("jq"), "VWARD_PROFILE_LIB": "/nonexistent"})
    head, _, body = r.stdout.partition(b"\n\n")
    if b"application/gzip" not in head or f'filename="{newest}"'.encode() not in head:
        fail(f"download headers: {head!r} {r.stderr[-300:]!r}")
    got = tmp / "download.tar.gz"; got.write_bytes(body)
    with tarfile.open(got) as t:
        names = t.getnames()
        blob = b"".join(t.extractfile(m).read() for m in t.getmembers() if m.isfile())
    for secret in (b"SECRET-TUNNEL-KEY", b"SECRET-AGH-PASSWORD", b"SECRET-ROUTER-KEY"):
        if secret in blob:
            fail(f"{secret!r} left the router in a downloaded backup")
    for want in ("./etc/device.conf", "./etc/ads-privacy-guard/allowlist.tsv", "./state/adaptive-persist.txt"):
        if want not in names:
            fail(f"{want} missing from the downloaded copy: {names}")
    if b"secrets_removed=1" not in blob:
        fail("the downloaded copy must say its secrets were removed")
    if list((tmp / "root/tmp").glob("vward-console-backup.*")) or list(Path("/tmp").glob("vward-console-backup.*")):
        fail("the download work folder must go")
    # The snapshot on the router keeps everything for a restore.
    with tarfile.open(snaps / newest) as t:
        if "./etc/tunnels/Wireguard0/current.conf" not in t.getnames():
            fail("the snapshot on the router must keep the tunnel store")

print("CONSOLE_BACKUPS=PASS")
