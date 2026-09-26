#!/usr/bin/env python3
"""Updates of other software: the check lists packages with a newer version and
reads the firmware state; a package is installed only from that list, after a
copy of its files and of the opkg database; a check that passed before and
fails after puts the copy back.  System packages need a second confirmation and
are never automatic.  Firmware: only automatic updates and channel."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
API = (ROOT / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
HOUSE = (ROOT / "components/runtime/scripts/vward-housekeeping.sh").read_text(encoding="utf-8")


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


FW = {"sandboxes": [{"version": "4.03.C.9.0-0", "name": "lts-4.3"}, {"version": "5.01.C.6.0-1", "name": "stable"},
                    {"version": "5.01.C.6.0-1", "name": "preview"}, {"version": "5.02.A.11.0-1", "name": "draft"}],
      "sandbox": "stable", "release": "5.01.C.6.0-1", "title": "5.1.6", "timestamp": "Sep 26 18:07:08",
      "update-available": False, "auto-update-pending": False, "auto-update-enabled": False, "checking": False}

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    root = tmp / "root"
    for d in ("opt/bin", "opt/lib/opkg/info", "opt/etc/init.d", "tmp"):
        (root / d).mkdir(parents=True)
    # Two packages: adguardhome-go (a service) and curl; the DNS check reads
    # /opt/bin/AdGuardHome, so a broken new AdGuard Home fails it.
    (root / "opt/bin/AdGuardHome").write_text("v0.107.73 good\n")
    (root / "opt/bin/curl-data").write_text("8.15.0\n")
    (root / "opt/lib/opkg/status").write_text("Package: adguardhome-go\nVersion: v0.107.73-1\n\nPackage: curl\nVersion: 8.15.0-2\n\n")
    (root / "opt/lib/opkg/info/adguardhome-go.list").write_text("/opt/bin/AdGuardHome\n")
    write_exec(root / "opt/etc/init.d/S99adguardhome", f'#!/bin/sh\nENABLED=yes\necho "$1" >> "{tmp}/restarts"\n')
    files = {"adguardhome-go": ["/opt/bin/AdGuardHome", "/opt/etc/init.d/S99adguardhome"], "curl": ["/opt/bin/curl-data"]}
    (tmp / "files.json").write_text(json.dumps(files))
    (tmp / "upgradable").write_text("adguardhome-go - v0.107.73-1 - v0.107.74-1\ncurl - 8.15.0-2 - 8.16.0-1\nbusybox - 1.37.0-6 - 1.37.0-7\n")
    (tmp / "new-agh").write_text("v0.107.74 good\n")
    write_exec(tmp / "opkg", f"""#!/usr/bin/env python3
import json, sys
tmp = {str(tmp)!r}; root = {str(root)!r}
a = sys.argv[1:]
open(tmp + "/opkg-calls", "a").write(" ".join(a) + "\\n")
files = json.load(open(tmp + "/files.json"))
if a[0] == "update":
    sys.exit(int(open(tmp + "/update-rc").read()) if __import__("os").path.exists(tmp + "/update-rc") else 0)
if a[0] == "list-upgradable":
    print(open(tmp + "/upgradable").read(), end="")
elif a[0] == "files":
    for f in files.get(a[1], []): print(f)
elif a[:2] == ["upgrade", "--noaction"]:
    for l in open(tmp + "/upgradable"):
        n, old, new = [x.strip() for x in l.split(" - ")]
        if n == a[2]: print(f"Upgrading {{n}} on root from {{old}} to {{new}}...")
elif a[0] == "upgrade":
    lines = open(tmp + "/upgradable").read().splitlines()
    left = [l for l in lines if l.split(" - ")[0] != a[1]]
    open(tmp + "/upgradable", "w").write("".join(l + "\\n" for l in left))
    if a[1] == "adguardhome-go":
        open(root + "/opt/bin/AdGuardHome", "w").write(open(tmp + "/new-agh").read())
    if a[1] == "curl":
        open(root + "/opt/bin/curl-data", "w").write("8.16.0\\n")
    st = open(root + "/opt/lib/opkg/status").read().replace("v0.107.73-1", "v0.107.74-1") if a[1] == "adguardhome-go" else open(root + "/opt/lib/opkg/status").read()
    open(root + "/opt/lib/opkg/status", "w").write(st)
""")
    bindir = tmp / "bin"; bindir.mkdir()
    write_exec(bindir / "nslookup", f'#!/bin/sh\ngrep -q good "{root}/opt/bin/AdGuardHome"\n')
    write_exec(bindir / "curl", f"""#!/bin/sh
for a do :; done
case "$a" in */rci/) cat "{tmp}/fw.json" ;; --version) echo curl ;; *) exit 7 ;; esac
""")
    (tmp / "fw.json").write_text(json.dumps([{"parse": FW}]))
    write_exec(tmp / "ndmc", f'#!/bin/sh\necho "$2" >> "{tmp}/ndmc-calls"\n')
    (tmp / "profile.sh").write_text("vward_profile_load() { VWARD_DNS_SERVER=127.0.0.1; VWARD_CONSOLE_PORT=; }\n")
    state = tmp / "state"
    env = os.environ | {
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "VWARD_CONSOLE_ETC": str(tmp / "etc"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "cbackup"), "VWARD_ROOT_PREFIX": str(root),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_PROFILE_LIB": str(tmp / "profile.sh"), "VWARD_OPKG": str(tmp / "opkg"), "VWARD_NDMC": str(tmp / "ndmc"),
        "VWARD_CURL_BIN": str(bindir / "curl"), "VWARD_EXT_ROOT": str(root),
        "VWARD_EXT_UPDATE_STATE": str(state), "VWARD_EXT_UPDATE_BACKUP": str(tmp / "backups"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_NSLOOKUP_BIN": str(bindir / "nslookup"),
    }

    def run(*args):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True)
        return r.returncode, r.stdout.strip().splitlines()

    rc, out = run("ext-check", "now")
    if out[-1:] != ["result=changed"]:
        fail(f"check: {rc} {out}")
    up = (state / "upgradable.tsv").read_text().splitlines()
    if up != ["adguardhome-go\tv0.107.73-1\tv0.107.74-1", "curl\t8.15.0-2\t8.16.0-1", "busybox\t1.37.0-6\t1.37.0-7"]:
        fail(f"upgradable list: {up}")
    fw = json.loads((state / "firmware.json").read_text())
    if fw["title"] != "5.1.6" or fw["channel"] != "stable" or fw["auto_update"] or len(fw["channels"]) != 4:
        fail(f"firmware state: {fw}")

    # Only packages the check found.
    rc, out = run("ext-upgrade", "jq", "manual")
    if out[-1:] != ["error=not_upgradable"]:
        fail(f"a package outside the list must be refused: {out}")
    # A system package needs the second confirmation.
    rc, out = run("ext-upgrade", "busybox", "manual")
    if out[-1:] != ["error=confirmation_required"]:
        fail(f"busybox without confirmation: {out}")

    # A good AdGuard Home: installed, service restarted, recorded.
    rc, out = run("ext-upgrade", "adguardhome-go", "manual")
    if out[-1:] != ["result=changed"] or "v0.107.74 good" not in (root / "opt/bin/AdGuardHome").read_text():
        fail(f"good upgrade: {out}")
    if "restart" not in (tmp / "restarts").read_text():
        fail("the AdGuard Home service must be restarted")
    if "v0.107.74-1" not in (root / "opt/lib/opkg/status").read_text():
        fail("status must show the new version")
    hist = (state / "history.tsv").read_text().splitlines()
    if not hist[-1].endswith("\tadguardhome-go\tv0.107.73-1\tv0.107.74-1\tok"):
        fail(f"history: {hist}")
    backups = sorted((tmp / "backups").iterdir())
    listed = (backups[0] / "files.list").read_text().split()
    for want in ("opt/bin/AdGuardHome", "opt/lib/opkg/status", "opt/lib/opkg/info/adguardhome-go.list"):
        if want not in listed:
            fail(f"{want} missing from the copy: {listed}")

    # A broken AdGuard Home: DNS fails, the old files and the old database return.
    (root / "opt/bin/AdGuardHome").write_text("v0.107.73 good\n")
    (root / "opt/lib/opkg/status").write_text("Package: adguardhome-go\nVersion: v0.107.73-1\n\nPackage: curl\nVersion: 8.15.0-2\n\n")
    (tmp / "upgradable").write_text("adguardhome-go - v0.107.73-1 - v0.107.75-1\n")
    (tmp / "new-agh").write_text("v0.107.75 broken\n")
    run("ext-check", "now")
    env["VWARD_EXT_HEALTH_WAIT"] = "0"
    rc, out = run("ext-upgrade", "adguardhome-go", "manual")
    if out[-1:] != ["error=upgrade_rolled_back"]:
        fail(f"broken upgrade must roll back: {out}")
    if (root / "opt/bin/AdGuardHome").read_text() != "v0.107.73 good\n":
        fail("the old AdGuard Home must be back")
    if "v0.107.73-1" not in (root / "opt/lib/opkg/status").read_text():
        fail("the old opkg database must be back")
    if not (state / "history.tsv").read_text().splitlines()[-1].endswith("\trolled_back"):
        fail("a rollback must be recorded")

    # Automatic: AdGuard Home only when switched on, system packages never.
    (tmp / "upgradable").write_text("adguardhome-go - v0.107.73-1 - v0.107.76-1\ncurl - 8.15.0-2 - 8.16.0-1\nbusybox - 1.37.0-6 - 1.37.0-7\n")
    (tmp / "new-agh").write_text("v0.107.76 good\n")
    (tmp / "opkg-calls").write_text("")
    rc, out = run("ext-auto", "agh", "1")
    if out[-1:] != ["result=changed"]:
        fail(f"ext-auto: {out}")
    rc, out = run("ext-daily", "now")
    calls = (tmp / "opkg-calls").read_text().splitlines()
    if "upgrade adguardhome-go" not in calls or any(c in calls for c in ("upgrade curl", "upgrade busybox")):
        fail(f"daily run with AdGuard Home automatic: {calls}")
    run("ext-auto", "entware", "1")
    (tmp / "opkg-calls").write_text("")
    run("ext-daily", "now")
    calls = (tmp / "opkg-calls").read_text().splitlines()
    if "upgrade curl" not in calls or "upgrade busybox" in calls:
        fail(f"daily run with Entware automatic: {calls}")

    # Firmware: Keenetic's own settings through ndmc, then saved.
    rc, out = run("firmware", "auto", "1")
    ndmc = (tmp / "ndmc-calls").read_text().splitlines()
    if out[-1:] != ["result=changed"] or ndmc != ["components auto-update enable", "system configuration save"]:
        fail(f"firmware auto: {out} {ndmc}")
    rc, out = run("firmware", "channel", "stable")
    if out[-1:] != ["result=unchanged"]:
        fail(f"the current channel is unchanged: {out}")
    rc, out = run("firmware", "channel", "draft")
    if (tmp / "ndmc-calls").read_text().splitlines()[-2:] != ["components auto-update channel draft", "system configuration save"]:
        fail("firmware channel")
    rc, out = run("firmware", "channel", "lts-4.3")
    if out[-1:] != ["error=invalid_value"]:
        fail(f"only stable, preview and draft: {out}")

# The console: the list comes from the last check, a test firmware channel and a
# system package need a confirmation, the daily run starts from housekeeping.
for marker in ('ACTION" = ext-update-data', 'ACTION" = ext-update-control', 'REQUIRED=FIRMWARE_CHANNEL_TEST',
               "EXT_UPGRADE_CRITICAL", 'run_detached "$EXT_RUN_DIR" ext_update_busy'):
    if marker not in API:
        fail(f"API marker missing: {marker}")
if '"$BACKUP_HELPER" "$EXT_OP" now' not in HOUSE:
    fail("housekeeping must start the daily check")

print("EXT_UPDATE=PASS")
