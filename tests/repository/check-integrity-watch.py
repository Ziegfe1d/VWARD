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

    script_under_test = SCRIPT

    def run() -> str:
        res = subprocess.run([busybox, "sh", str(script_under_test)], env=env, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            fail(f"housekeeping failed: {res.stderr[-300:]}")
        return log.read_text() if log.exists() else ""

    def spoil(path: Path, body: bytes) -> None:
        st = path.stat()
        path.write_bytes(body[: st.st_size].ljust(st.st_size, b"!"))
        os.utime(path, (st.st_atime, st.st_mtime))

    def new_lines(before: str) -> str:
        return run()[len(before):]

    # Out of the night window the very first look waits (the heaviest; CI budget): only noted.
    env_day = env | {"VWARD_INTEGRITY_NOW": "0"}
    res = subprocess.run([busybox, "sh", str(SCRIPT)], env=env_day, capture_output=True, text=True, timeout=120)
    state = r / "opt/var/lib/vward/integrity/state"
    if res.returncode != 0 or (r / "opt/var/lib/vward/integrity/snapshot.tsv").exists() or "first=" not in state.read_text():
        fail("the first look runs at once instead of waiting for the night")
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
    # A VWARD file cannot be auto-repaired. Its corruption MUST still appear
    # next day, without replacing the previous trusted (good) checksums.
    baseline = r / "opt/var/lib/vward/integrity/snapshot.tsv"
    trusted_before = baseline.read_bytes()
    out2 = new_lines(out); out += out2
    if "SPOILED|/opt/share/vward/engine.sh|pkg=vward" not in out2 or \
       "BASELINE_HELD|spoiled=" not in out2 or baseline.read_bytes() != trusted_before:
        fail("unrepaired VWARD file silently accepted as new baseline")

    # A failed checksum during snapshot is UNKNOWN, not REMOVED. Even one
    # unreadable file must not poison the baseline.
    # Inject failure at the checksum call in a disposable script. The
    # production script and its protected PATH remain untouched.
    scratch_script = t / "housekeeping-md5-fault.sh"
    original_script = SCRIPT.read_text()
    # Admission registration is not a singleton: parallel runs need separate scratch files.
    for scratch in ("list", "raw"):
        if f'"$INTEG_DIR/{scratch}.$$"' not in original_script or f'"$INTEG_DIR/{scratch}.$"' in original_script:
            fail("integrity snapshot scratch files must be PID-scoped")
    checksum_call = 'is_h=$(md5sum < "$is_f" 2>/dev/null) || exit 1'
    if original_script.count(checksum_call) != 1:
        fail("housekeeping checksum contract changed")
    scratch_script.write_text(original_script.replace(
        checksum_call, 'is_h=$(false < "$is_f" 2>/dev/null) || exit 1', 1))
    script_under_test = scratch_script
    try:
        out2 = new_lines(out); out += out2
    finally:
        script_under_test = SCRIPT
    if "|SKIPPED|snapshot_incomplete" not in out2 or baseline.read_bytes() != trusted_before:
        fail("incomplete checksum snapshot was accepted or trusted baseline changed")
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
    # The package was installed long ago (not since the last look): a change now is the stick.
    os.utime(r / "opt/lib/opkg/info/libx.list", (OLD, OLD))
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

    # 11.11.2026: a baseline taken over a spoiled copy (before fix.36.1 the baseline moved on after
    # SPOILED), then the owner or VWARD reinstalls the package. opkg keeps the package's own file
    # times, so the repaired file has the same time and other contents - but opkg rewrote the
    # package's file list after the last look: written by opkg, not spoiled by the stick.
    import hashlib
    snap = r / "opt/var/lib/vward/integrity/snapshot.tsv"
    st_file = r / "opt/var/lib/vward/integrity/state"
    bad_hash = hashlib.md5(lib.read_bytes()).hexdigest()
    rows = []
    for row in snap.read_text().splitlines():
        f = row.split("\t")
        if f[0] == "/opt/lib/libx.so.1":
            f[3] = bad_hash
        rows.append("\t".join(f))
    snap.write_text("\n".join(rows) + "\n")
    now = int(time.time())
    st_file.write_text(f"at={now - 1000}\nfiles=3\n")
    os.utime(snap, (now - 1000, now - 1000))
    lib.write_bytes(good); os.utime(lib, (OLD, OLD))
    (r / "opt/lib/opkg/info/libx.list").write_text("/opt/lib/libx.so.1\n")
    os.utime(r / "opt/lib/opkg/info/libx.list", (now - 500, now - 500))
    if notes.exists():
        notes.unlink()
    out = log.read_text()
    out2 = new_lines(out); out += out2
    if "|WRITTEN|/opt/lib/libx.so.1|by=opkg:libx" not in out2 or "|SPOILED|/opt/lib/libx.so.1" in out2 or \
       "pkg=libx" in out2 or (notes.exists() and "libx" in notes.read_text()):
        fail(f"a package reinstalled by opkg reported as spoiled by the stick: {out2}")
    if f"\t{hashlib.md5(good).hexdigest()}" not in snap.read_text():
        fail("the baseline does not take the reinstalled package's file")
    # The next day the reinstalled file is not told again (while the VWARD file stays spoiled,
    # only that file keeps its former checksum), and the spoiled VWARD file still is.
    out2 = new_lines(out); out += out2
    if "/opt/lib/libx.so.1" in out2 or "|SPOILED|/opt/share/vward/engine.sh|" not in out2 or "/opt/bin/tool" in out2:
        fail(f"a held baseline repeats reinstalled or written files, or drops the spoiled one: {out2}")
    # Reinstalled since the last look, but the file differs from the same version in Entware
    # (spoiled after the reinstall): the reinstall does not hide the stick - still spoiled.
    st_file.write_text(f"at={int(time.time()) - 1000}\nfiles=3\n")
    os.utime(r / "opt/lib/opkg/info/libx.list", (time.time() - 500, time.time() - 500))
    spoil(lib, b"libx after reinstall")
    out2 = new_lines(out); out += out2
    if "|SPOILED|/opt/lib/libx.so.1|pkg=libx" not in out2 or "|WRITTEN|/opt/lib/libx.so.1|" in out2:
        fail(f"a file spoiled after a reinstall is accepted as written by opkg: {out2}")
    lib.write_bytes(good); os.utime(lib, (OLD, OLD))
    os.utime(r / "opt/lib/opkg/info/libx.list", (OLD, OLD))
    run(); out = log.read_text()
    # The same package spoiled after that reinstall (the list is older than the last look): spoiled.
    spoil(lib, b"libx SPOILED third")
    out2 = new_lines(out); out += out2
    if "|SPOILED|/opt/lib/libx.so.1|pkg=libx" not in out2:
        fail(f"a spoiled file after an earlier reinstall is not found: {out2}")

print("INTEGRITY_WATCH=PASS")
