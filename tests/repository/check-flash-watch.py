#!/usr/bin/env python3
"""The USB stick watch of the maintenance agent (fix.28.2): file system and read/write errors in
the kernel's messages, only the new ones each hour, one journal line with the device and the
damaged place (an inode's path looked for once), the bell once a day. It only looks.
flash_watch is taken from vward-housekeeping.sh as it is and run with a stand-in dmesg."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "components/runtime/scripts/vward-housekeeping.sh").read_text(encoding="utf-8")
FUNC = SRC[SRC.index("FLASH_STATE="):SRC.index("\nflash_watch\n")]


def fail(message: str) -> None:
    raise SystemExit(f"FLASH_WATCH=FAIL: {message}")


EXT4 = "[ 9071.300000] EXT4-fs error (device sda1): htree_dirblock_to_tree:1080: inode #{ino}: comm ls: Directory block failed checksum"
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    root = tmp / "root"
    damaged = root / "opt/etc/ndm/usb.d"
    damaged.mkdir(parents=True)
    ino = damaged.stat().st_ino
    dmesg = tmp / "dmesg.txt"
    (tmp / "dmesg").write_text(f'#!/bin/sh\ncat "{dmesg}"\n')
    (tmp / "dmesg").chmod(0o755)
    harness = tmp / "h.sh"
    harness.write_text(f"""R="{root}" HOUSE_LOG="{tmp}/house.log"
VWARD_FLASH_STATE="{tmp}/flash" VWARD_DMESG_BIN="{tmp}/dmesg" VWARD_CONSOLE_NOTES="{tmp}/notes"
VWARD_PROFILE_LIB="{ROOT}/components/runtime/lib/vward-device-profile.sh"
export VWARD_CONSOLE_NOTES
{FUNC}
flash_watch
""")

    def run():
        subprocess.run(["sh", str(harness)], check=True, timeout=60)
        log = (tmp / "house.log").read_text().splitlines() if (tmp / "house.log").exists() else []
        notes = (tmp / "notes/notes.tsv").read_text().splitlines() if (tmp / "notes/notes.tsv").exists() else []
        return log, notes

    # A clean stick: nothing written.
    dmesg.write_text("[    1.0] usb 1-1: new high-speed USB device\n[    2.0] EXT4-fs (sda1): mounted filesystem with ordered data mode\n")
    log, notes = run()
    if log or notes:
        fail(f"a clean stick must leave no trace: {log} {notes}")
    # Two errors on one directory: one line with the device and the path, the bell once.
    dmesg.write_text(dmesg.read_text() + EXT4.format(ino=ino) + "\n" + EXT4.format(ino=ino).replace("9071.3", "9072.1").replace("comm ls", "comm find") + "\n")
    log, notes = run()
    summary = [l for l in log if "flash_errors=" in l]
    if len(summary) != 1 or "flash_errors=2|io=0|device=sda1|where=/opt/etc/ndm/usb.d" not in summary[0]:
        fail(f"journal: {log}")
    if len(notes) != 1 or "Флешка: ошибки файловой системы" not in notes[0] or "/opt/etc/ndm/usb.d" not in notes[0] or "\twarn\t" not in notes[0]:
        fail(f"bell: {notes}")
    # The same messages an hour later: nothing new, nothing written.
    n_log = len(log)
    log, notes = run()
    if len(log) != n_log or len(notes) != 1:
        fail("errors already seen must not be counted again")
    # A read/write error the same day: in the journal, the bell waits for tomorrow.
    dmesg.write_text(dmesg.read_text() + "[ 9100.0] blk_update_request: I/O error, dev sda, sector 123456\n")
    log, notes = run()
    if "io=1|device=sda" not in log[n_log] or len(notes) != 1:
        fail(f"a new read/write error: {log[n_log:]} {notes}")
    # Tomorrow: the bell says the stick itself may be failing.
    (tmp / "flash/told").unlink()
    dmesg.write_text(dmesg.read_text() + "[ 9200.0] Buffer I/O error on dev sda1, logical block 77\n")
    log, notes = run()
    if len(notes) != 2 or "Флешка: ошибки чтения и записи" not in notes[1] or "\terr\t" not in notes[1]:
        fail(f"read/write errors: {notes}")

if "\nflash_watch\n" not in SRC or SRC.index("\nflash_watch\n") > SRC.index("if ! vward_off; then"):
    fail("the stick is watched every hour, VWARD switched off too")
for bad in ("fsck ", "rm -rf", "mv -f \"$R/opt"):
    if bad in FUNC:
        fail(f"the watch only looks: {bad}")
print("FLASH_WATCH=PASS")
