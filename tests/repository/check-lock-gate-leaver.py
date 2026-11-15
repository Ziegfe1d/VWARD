#!/usr/bin/env python3
"""The lock election (vward_lock_gate_enter): a contender that leaves while it is looked at.

Two writers of the routing journal: the winner enters the gate again while the loser leaves - its
«leave» removes its own ticket. The ticket was still in the listing, passed «is it there» and was
gone before its metadata was read; the vanished ticket read as «not a ticket», the winner's entry
was refused and none of the two began (tests/routing-readers/check-journal.py, CI 12.11 and
15.11.2026: about 2-5 rounds of 100 on Ubuntu 24.04, 2 runs of 3 on a newer runner image).

Deterministic here: the look at the other contender's ticket removes that ticket first, exactly
the moment of the race - in the choosing loop and in the waiting loop. A ticket that is gone is no
contender: the entry succeeds. A path that is still there and is not a ticket directory (a file,
a directory with other rights) refuses the entry as before, and so does a live contender ahead of
us that stays."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-runtime-admission.sh"
SHELL = os.environ.get("LOCK_GATE_SHELL", "sh").split()


def fail(m):
    raise SystemExit(f"LOCK_GATE_LEAVER=FAIL: {m}")


# The look at a ticket as the library does it, with the fault before it: the ticket named OTHER is
# removed on its VANISH_AT-th look (1: the choosing loop, 2: the first round of the waiting loop).
SCRIPT = r'''. "$LIB"
looks=0
vward_lock_gate_dir() {
    if [ "$1" = "$OTHER" ]; then
        looks=$((looks + 1))
        [ "$looks" != "${VANISH_AT:-0}" ] || rm -rf "$1"
    fi
    [ -d "$1" ] && [ ! -L "$1" ] && [ -O "$1" ] && vward_lock_ls "$1" && [ "$vl_lsmode" = drwx------ ]
}
vward_lock_gate_enter "$LOCK"; rc=$?
echo "enter=$rc looks=$looks"
[ "$rc" != 0 ] || { vward_lock_gate_leave "$LOCK"; echo "leave=$?"; }
'''
# The library's own look must be what the stand-in above repeats.
if '[ -d "$1" ] && [ ! -L "$1" ] && [ -O "$1" ] && vward_lock_ls "$1" && [ "$vl_lsmode" = drwx------ ]' not in LIB.read_text():
    fail("vward_lock_gate_dir changed: repeat its checks in this test")

boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def start_of(pid):
    return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]


def case(name, vanish_at, want_enter, other="ticket", number="1"):
    holder = subprocess.Popen(["sleep", "60"])
    try:
        with tempfile.TemporaryDirectory() as t:
            lock = Path(t) / "journal" / ".lock"
            lock.parent.mkdir(mode=0o700)
            gate = Path(str(lock) + ".gate")
            gate.mkdir(mode=0o700)
            ticket = gate / f"{boot}.{holder.pid}.{start_of(holder.pid)}"
            if other == "file":
                ticket.write_text("not a ticket\n")
            else:
                ticket.mkdir(mode=0o700 if other == "ticket" else 0o755)
                if other != "ticket":
                    ticket.chmod(0o755)
                for leaf, text in (("pid", holder.pid), ("start", start_of(holder.pid)), ("number", number)):
                    (ticket / leaf).write_text(f"{text}\n")
                    (ticket / leaf).chmod(0o600)
            r = subprocess.run([*SHELL, "-c", SCRIPT], text=True, capture_output=True, timeout=60,
                               env={"PATH": os.environ["PATH"], "LIB": str(LIB), "LOCK": str(lock), "OTHER": str(ticket),
                                    "VANISH_AT": str(vanish_at)})
            out = r.stdout.split()
            if not out or out[0] != f"enter={want_enter}":
                fail(f"{name}: {r.stdout!r} {r.stderr[-300:]!r}, want enter={want_enter}")
            if want_enter == 0 and "leave=0" not in out:
                fail(f"{name}: the entry must be left cleanly: {r.stdout!r}")
            left = [p.name for p in gate.iterdir()]
            if want_enter == 0 and left:
                fail(f"{name}: tickets left behind: {left}")
            return out
    finally:
        holder.kill(); holder.wait()


# The other contender leaves at the very look: it is no contender.
case("gone in the choosing loop", 1, 0)
out = case("gone in the waiting loop", 2, 0)
if "looks=2" not in out:
    fail(f"the waiting loop must have looked at the ticket: {out}")
# Still there and not a ticket directory: refused, as before.
case("a file in the gate", 0, 75, other="file")
case("a directory with other rights", 0, 75, other="open")
# A live contender ahead of us that stays: we wait and give way.
case("a live contender ahead stays", 0, 75)
print("LOCK_GATE_LEAVER=PASS")
