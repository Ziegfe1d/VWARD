#!/usr/bin/env python3
"""The maintenance agent's file integrity journal (fix.28.3).

Once a day every program file of Entware and VWARD (size, time of change, checksum) is compared
with the day before. A program that writes a file changes its time; the USB stick that spoils one
changes only the contents (Viva 2026-10-17: libcares of Smart DNS's client spoiled, its time as
installed). So:
  * the first look only remembers;
  * contents changed, time the same: SPOILED; a package's file is checked against the same
    version in Entware and the package reinstalled, a copy first; a file of VWARD itself is told;
    the owner gets one notification;
  * a file written: WRITTEN, by opkg when its package's file list is newer, else unknown - only
    written down, never reinstalled;
  * never a loop: a package spoiled again after 2 reinstalls within 7 days is left alone and
    named in the notification.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "components/runtime/scripts/vward-housekeeping.sh"


def fail(message: str) -> None:
    raise SystemExit(f"INTEGRITY_WATCH=FAIL: {message}")


busybox = shutil.which("busybox") or fail("busybox is needed")
OLD = time.time() - 86400 * 30

with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    r = t / "root"
    for d in ("opt/var/log/vward", "opt/var/backups/vward", "tmp", "opt/var/spool/cron/crontabs", "opt/bin", "opt/lib/opkg/info", "opt/share/vward"):
        (r / d).mkdir(parents=True)
    good = b"libx good contents"
    lib = r / "opt/lib/libx.so.1"
    lib.write_bytes(good)
    (r / "opt/lib/opkg/info/libx.list").write_text("/opt/lib/libx.so.1\n")
    tool = r / "opt/bin/tool"
    tool.write_bytes(b"#!/bin/sh\necho tool\n")
    own = r / "opt/share/vward/engine.sh"
    own.write_bytes(b"#!/bin/sh\necho vward\n")
    for f in (lib, tool, own, r / "opt/lib/opkg/info/libx.list"):
        os.utime(f, (OLD, OLD))
    # The feed: libx 1.0-1 with the good file.
    feed = t / "feed"; feed.mkdir()
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tf:
        ti = tarfile.TarInfo("./opt/lib/libx.so.1"); ti.size = len(good); tf.addfile(ti, io.BytesIO(good))
    with tarfile.open(feed / "libx_1.0-1_mipsel-3.4.ipk", "w:gz") as tf:
        ti = tarfile.TarInfo("./data.tar.gz"); ti.size = len(data.getvalue()); tf.addfile(ti, io.BytesIO(data.getvalue()))
    (t / "opkg").write_text(f"""#!/bin/sh
echo "$*" >> "{t}/opkg.log"
case "$1" in
list-installed) [ "$2" = libx ] && echo "libx - 1.0-1" ;;
download) cp "{feed}/$2"_*.ipk . 2>/dev/null ;;
files) [ "$2" = libx ] && {{ echo "Package libx (1.0-1) is installed on root and has the following files:"; echo /opt/lib/libx.so.1; }} ;;
install) [ "$3" = libx ] && printf 'libx good contents' > "{lib}" ;;
esac
""")
    (t / "opkg").chmod(0o755)
    stub = t / "admission.sh"
    stub.write_text("vward_admission_enter() { :; }\nvward_admission_leave() { :; }\nvward_defer() { return 1; }\nvward_off() { return 0; }\n")
    notes_dir = t / "notes"
    notes = notes_dir / "notes.tsv"
    env = os.environ | {"VWARD_ROOT_PREFIX": str(r), "VWARD_ADMISSION_LIB": str(stub), "VWARD_CONSOLE_CONFIG_BIN": str(t / "none"),
                        "VWARD_CRONTAB": str(t / "none"), "VWARD_OPKG_BIN": str(t / "opkg"), "VWARD_REPAIR_CURL": str(t / "none"),
                        "VWARD_REPAIR_JQ": str(t / "none"), "VWARD_REPAIR_OPENSSL": str(t / "none"), "VWARD_SENTINEL_CTL": str(t / "none"),
                        "VWARD_TLS_BROKEN_FLAG": str(t / "tls.broken"), "VWARD_DOH_BROKEN_FLAG": str(t / "doh.broken"),
                        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"), "VWARD_CONSOLE_NOTES": str(notes_dir),
                        "VWARD_INTEGRITY_NOW": "1", "VWARD_DMESG_BIN": str(t / "none")}
    log = r / "opt/var/log/vward-integrity.log"

    def run() -> str:
        res = subprocess.run([busybox, "sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            fail(f"housekeeping failed: {res.stderr[-300:]}")
        return log.read_text() if log.exists() else ""

    def spoil(path: Path, body: bytes) -> None:
        st = path.stat()
        path.write_bytes(body[: st.st_size].ljust(st.st_size, b"!"))
        os.utime(path, (st.st_atime, st.st_mtime))

    def new_lines(before: str) -> str:
        return run()[len(before):]

    # The first look only remembers.
    out = run()
    if "|SUMMARY|files=3|first=1|" not in out or (r / "opt/var/lib/vward/integrity/snapshot.tsv").read_text().count("\n") != 3:
        fail(f"the first look: {out}")
    # Nothing changed: nothing found, nothing told.
    out2 = new_lines(out)
    if "|SUMMARY|files=3|spoiled=0|written=0|unknown=0|" not in out2 or notes.exists():
        fail(f"an unchanged day: {out2}")
    out += out2
    # The stick spoils libx (contents, not the time): found, checked, reinstalled, a copy, told.
    spoil(lib, b"libx SPOILED contents")
    out2 = new_lines(out); out += out2
    if "|SPOILED|/opt/lib/libx.so.1|pkg=libx" not in out2 or "|REPAIR|spoiled=libx|confirmed=libx|reinstalled=libx|held=|still=|" not in out2:
        fail(f"a spoiled package file: {out2}")
    if lib.read_bytes() != good or not list((r / "opt/var/lib/vward/repair").glob("integrity-*.tar.gz")):
        fail("the package is not reinstalled after a copy")
    note = notes.read_text() if notes.exists() else ""
    if "Флешка портит файлы программ" not in note or "libx" not in note:
        fail(f"the owner is not told: {note}")
    # A file of VWARD itself spoiled: written down and told, nothing reinstalled for it.
    n_ops = len((t / "opkg.log").read_text().splitlines())
    spoil(own, b"#!/bin/sh\necho XXXXXX\n")
    out2 = new_lines(out); out += out2
    if "|SPOILED|/opt/share/vward/engine.sh|pkg=vward" not in out2 or "/opt/share/vward/engine.sh" not in notes.read_text():
        fail(f"a spoiled VWARD file: {out2}")
    if any(o.startswith("install") for o in (t / "opkg.log").read_text().splitlines()[n_ops:]):
        fail("a package reinstalled for a VWARD file")
    # A program writes a file (its time changes): only written down, by whom when known.
    tool.write_bytes(b"#!/bin/sh\necho tool v2\n")
    out2 = new_lines(out); out += out2
    if "|WRITTEN|/opt/bin/tool|by=unknown" not in out2 or "|REPAIR|" in out2:
        fail(f"a written file: {out2}")
    lib.write_bytes(b"libx v2 contents!!")
    (r / "opt/lib/opkg/info/libx.list").write_text("/opt/lib/libx.so.1\n")
    later = time.time() + 100
    for f in (lib, r / "opt/lib/opkg/info/libx.list"):
        os.utime(f, (later, later))
    out2 = new_lines(out); out += out2
    if "|WRITTEN|/opt/lib/libx.so.1|by=opkg:libx" not in out2:
        fail(f"a file opkg wrote: {out2}")
    lib.write_bytes(good)
    os.utime(lib, (OLD, OLD))
    run()
    # Never a loop: libx reinstalled twice this week and spoiled again - left alone, named.
    book = r / "opt/var/lib/vward/repair/packages.tsv"
    now = int(time.time())
    book.write_text(f"{now - 3 * 86400} libx integrity\n{now - 2 * 86400} libx integrity\n")
    notes.unlink()
    out = log.read_text()
    n_ops = len((t / "opkg.log").read_text().splitlines())
    spoil(lib, b"libx SPOILED again!!")
    out2 = new_lines(out)
    if "|REPAIR|spoiled=libx|confirmed=libx|reinstalled=|held=libx|" not in out2:
        fail(f"a third reinstall within the week: {out2}")
    if any(o.startswith("install") for o in (t / "opkg.log").read_text().splitlines()[n_ops:]):
        fail("reinstalled again in a loop")
    if "чтобы не повторять по кругу: libx" not in notes.read_text():
        fail(f"the package left alone is not named: {notes.read_text()}")

print("INTEGRITY_WATCH=PASS")
