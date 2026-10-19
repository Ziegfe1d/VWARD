#!/usr/bin/env python3
"""The official AdGuard Home build (fix.28.2): Entware's build for mipsel dies on the MIPS 1004Kc
of Keenetic Viva with an illegal instruction; VWARD puts AdGuard's own softfloat build in its
place. Only the pinned version with both checksums; a copy of the old file first; the DNS chain
guard told before and after; a build that does not start is taken back when the old one ran;
once installed (or found), Entware's package is no longer offered; the bell says what happened.
Everything synthetic: a shell script stands for the program, a fake curl serves the archive."""

import hashlib
import io
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
SRC = HELPER.read_text(encoding="utf-8")
API = (ROOT / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")


def fail(message: str) -> None:
    raise SystemExit(f"AGH_OFFICIAL=FAIL: {message}")


def write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


sha = lambda b: hashlib.sha256(b).hexdigest()

# The real pin: the version and the checksums of AdGuard's archive and program, checked by hand.
for need in ("AGH_OFFICIAL_VERSION=v0.107.73",
             "b56692f9f85676693116c3f4e4922210b6a96c072b8dfa81711185bbabf49bd9 8f316aebdd65aac0090edf005fdb007b9c1bffb28f316f549f79c26a2c479311",
             "https://github.com/AdguardTeam/AdGuardHome/releases/download"):
    if need not in SRC:
        fail(f"the helper lacks {need}")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    root = tmp / "root"
    for d in ("opt/sbin", "opt/etc/init.d", "opt/tmp", "opt/lib/opkg", "tmp"):
        (root / d).mkdir(parents=True)
    (root / "opt/lib/opkg/status").write_text("Package: adguardhome-go\nVersion: v0.107.73-1\n\n")
    agh = root / "opt/sbin/AdGuardHome"
    # The program: «--version» answers unless it is the broken build; «start» runs it.
    broken = b'#!/bin/sh\nexit 132\n'
    good_old = b'#!/bin/sh\necho "AdGuard Home, version v0.107.72"\n'
    official = b'#!/bin/sh\n[ "$1" = --version ] && echo "AdGuard Home, version v0.107.73"\nexit 0\n'

    def archive(program: bytes) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            for name, data in (("./AdGuardHome/AdGuardHome", program), ("./AdGuardHome/README.md", b"readme\n")):
                info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o755
                t.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    arch_bytes = archive(official)
    (tmp / "archive").write_bytes(arch_bytes)
    pin = f"{sha(arch_bytes)} {sha(official)}"
    bindir = tmp / "bin"; bindir.mkdir()
    write_exec(bindir / "curl", f"""#!/bin/sh
echo "$*" >> "{tmp}/curl-calls"
out=; url=
while [ $# -gt 0 ]; do case "$1" in -o) out=$2; shift ;; https://*) url=$1 ;; esac; shift; done
[ -e "{tmp}/offline" ] && exit 6
case "$url" in */v0.107.73/AdGuardHome_linux_mipsle_softfloat.tar.gz) cp "{tmp}/archive" "$out" ;; *) exit 22 ;; esac
""")
    # Running after a start unless told it does not stay up.
    write_exec(bindir / "pidof", f'#!/bin/sh\n[ "$1" = AdGuardHome ] && [ -e "{tmp}/running" ]\n')
    write_exec(root / "opt/etc/init.d/S99adguardhome", f"""#!/bin/sh
echo "$1" >> "{tmp}/init-calls"
case "$1" in stop) rm -f "{tmp}/running" ;; start|restart) [ -e "{tmp}/dies" ] || : > "{tmp}/running" ;; esac
""")
    write_exec(tmp / "dnsguard", f'#!/bin/sh\necho "$*" >> "{tmp}/dnsguard.log"\n')
    write_exec(tmp / "opkg", '#!/bin/sh\n[ "$1" = list-upgradable ] && echo "adguardhome-go - v0.107.73-1 - v0.107.74-1" && echo "curl - 8.15.0-2 - 8.16.0-1"\nexit 0\n')
    (tmp / "profile.sh").write_text(f'. "{ROOT}/components/runtime/lib/vward-device-profile.sh"\nvward_profile_load() {{ :; }}\n')
    state = tmp / "state"
    env = os.environ | {
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "VWARD_CONSOLE_ETC": str(tmp / "etc"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_ROOT_PREFIX": str(root), "VWARD_EXT_ROOT": str(root),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_PROFILE_LIB": str(tmp / "profile.sh"), "VWARD_CONSOLE_NOTES": str(tmp / "notes"),
        "VWARD_OPKG": str(tmp / "opkg"), "VWARD_CURL_BIN": str(bindir / "curl"),
        "VWARD_EXT_UPDATE_STATE": str(state), "VWARD_EXT_UPDATE_BACKUP": str(tmp / "backups"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_ADS_DNS_GUARD_BIN": str(tmp / "dnsguard"),
        "VWARD_COMPONENT_STATE": str(tmp / "components"),
        "VWARD_AGH_INIT": str(root / "opt/etc/init.d/S99adguardhome"), "VWARD_AGH_BIN_DIRS": str(root / "opt/sbin"),
        "VWARD_AGH_ARCH": "mipsle_softfloat", "VWARD_AGH_OFFICIAL_PIN": pin, "VWARD_AGH_START_WAIT": "0", "VWARD_PIDOF_BIN": str(bindir / "pidof"),
    }

    def run(*args, **extra):
        r = subprocess.run(["sh", str(HELPER), *args], env=env | extra, text=True, capture_output=True, timeout=60)
        return r.stdout.strip().splitlines()

    def reset(program: bytes):
        for f in ("init-calls", "dnsguard.log", "curl-calls", "running", "dies", "offline", "notes/notes.tsv"):
            (tmp / f).unlink(missing_ok=True)
        (state / "agh-official").unlink(missing_ok=True)
        agh.write_bytes(program); agh.chmod(0o755)

    notes = lambda: (tmp / "notes/notes.tsv").read_text() if (tmp / "notes/notes.tsv").exists() else ""

    # A program that runs: «repair» leaves it alone, nothing downloaded.
    reset(good_old)
    out = run("ext-agh-official", "repair")
    if out[-1:] != ["result=unchanged"] or (tmp / "curl-calls").exists():
        fail(f"a working program must be left alone: {out}")

    # No network: told in the bell, nothing changed.
    reset(broken); (tmp / "offline").write_text("")
    out = run("ext-agh-official", "repair")
    if out[-1:] != ["error=download_failed"] or agh.read_bytes() != broken or "не смог скачать" not in notes():
        fail(f"no network: {out} {notes()!r}")

    # A changed archive (another file at the address): refused by its checksum.
    reset(broken)
    out = run("ext-agh-official", "repair", VWARD_AGH_OFFICIAL_PIN=f"{'0' * 64} {sha(official)}")
    if out[-1:] != ["error=checksum_mismatch"] or agh.read_bytes() != broken:
        fail(f"a wrong archive must be refused: {out}")
    if list((root / "opt/tmp").iterdir()):
        fail("the download must not stay in /opt/tmp")

    # The broken build (exit 132): replaced, started, recorded, told; the old file kept.
    reset(broken)
    out = run("ext-agh-official", "repair")
    if out[-1:] != ["result=changed"] or agh.read_bytes() != official:
        fail(f"repair: {out}")
    st = (state / "agh-official").read_text()
    if "version=v0.107.73" not in st or "by=repair" not in st:
        fail(f"the official build must be recorded: {st}")
    if (tmp / "dnsguard.log").read_text().split("\n")[:-1] != ["planned 600", "planned-done"]:
        fail("the DNS chain guard must be told before and after")
    if (tmp / "init-calls").read_text().split() != ["stop", "start"]:
        fail(f"stop and start: {(tmp / 'init-calls').read_text()}")
    backups = list((tmp / "backups").glob("*-agh-official/AdGuardHome"))
    if len(backups) != 1 or backups[0].read_bytes() != broken:
        fail("the old file must be kept")
    if "AdGuard Home снова работает" not in notes() or "d-agh" not in notes():
        fail(f"the bell must say AdGuard Home works again: {notes()!r}")
    # Entware's build is no longer offered: it would bring the crash back.
    up = (state / "upgradable.tsv").read_text()
    if "adguardhome-go" in up or "curl" not in up:
        fail(f"upgradable after the official build: {up!r}")
    hist = (state / "history.tsv").read_text().splitlines()[-1].split("\t")
    if hist[1:] != ["adguardhome", "broken", "v0.107.73", "ok"]:
        fail(f"history: {hist}")
    # Installed already: nothing downloaded again.
    (tmp / "curl-calls").unlink(missing_ok=True)
    out = run("ext-agh-official", "install")
    if out[-1:] != ["result=unchanged"] or (tmp / "curl-calls").exists():
        fail(f"the pinned build installed already: {out}")

    # From the Panel over a working older program that the new build cannot replace: taken back.
    reset(good_old); (tmp / "dies").write_text("")
    out = run("ext-agh-official", "install")
    if out[-1:] != ["error=upgrade_rolled_back"] or agh.read_bytes() != good_old:
        fail(f"a build that does not start must be taken back: {out}")
    if (state / "agh-official").exists():
        fail("a build taken back must not be recorded")

    # Put by hand (the owner did, Viva 2026-10-17): found by its checksum at the next check.
    reset(official)
    run("ext-check", "now")
    if "by=found" not in (state / "agh-official").read_text() if (state / "agh-official").exists() else True:
        fail("an official build put by hand must be found")

    # A router VWARD knows no build for: refused, the bell says so on repair.
    reset(broken)
    out = run("ext-agh-official", "repair", VWARD_AGH_ARCH="arm64")
    if out[-1:] != ["error=agh_no_build"] or "нет подходящей сборки" not in notes():
        fail(f"no build: {out}")

# The components agent asks for it; the Panel offers it and shows the build.
SUP = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text(encoding="utf-8")
if '"$CONFIG_BIN" ext-agh-official repair' not in SUP or "-mmin -1440" not in SUP:
    fail("the components agent must ask for the official build, once a day at most")
for need in ("agh-official)", 'ARGS="ext-agh-official install"', "official: {installed:"):
    if need not in API:
        fail(f"the API lacks {need}")
for need in ("'agh-official': () => extOp('agh-official', '', 'AGH_OFFICIAL')", "Установить официальную сборку", "официальная сборка"):
    if need not in JS:
        fail(f"the Panel lacks {need}")
# The processor (fix.33): «mips» from uname and an unreadable byte order is a little-endian
# Keenetic, as the tunnel engines take it; big-endian MIPS and other processors have no build.
import re as _re
_src = HELPER.read_text() if hasattr(HELPER, "read_text") else open(HELPER).read()
_fn = _re.search(r"^agh_official_arch\(\) \{\n.*?^\}\n", _src, _re.S | _re.M).group(0)
for _m, _od, _want in (("mips", "", "mipsle_softfloat"), ("mips", " 1", "mipsle_softfloat"), ("mipsel", " 2", "mipsle_softfloat"),
                       ("mips", " 2", ""), ("aarch64", " 1", "")):
    with tempfile.TemporaryDirectory() as _t:
        Path(_t, "uname").write_text(f"#!/bin/sh\necho {_m}\n"); Path(_t, "uname").chmod(0o755)
        Path(_t, "od").write_text(f"#!/bin/sh\ncat >/dev/null; echo '{_od}'\n" if _od else "#!/bin/sh\nexit 127\n"); Path(_t, "od").chmod(0o755)
        _r = subprocess.run(["sh", "-c", f"PATH={_t}:$PATH; audit() {{ :; }}\n" + _fn + "agh_official_arch"], capture_output=True, text=True)
        if _r.stdout.strip() != _want:
            fail(f"processor {_m}/{_od!r}: {_r.stdout.strip()!r}, expected {_want!r}")
print("AGH_OFFICIAL=PASS")
