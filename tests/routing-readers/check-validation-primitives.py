#!/usr/bin/env python3
"""Process-budget rewrite of the validation primitives keeps their exact verdicts.

check-live-first-request exceeded invoke45: one cold request spawned ~52k
processes, nearly all from per-file checks repeated hundreds of times
(ls|awk mode pipelines, two wc runs, one sha256sum per sealed file). The
primitives now use one fork per check and ONE wc/sha256sum per sealed set.
Here, on sh and BusyBox ash, every primitive is compared with the ORIGINAL
pipeline expression on the same files, and vr2_seal_valid keeps the exact
return code of the per-file version for every tamper class.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib"
SHELLS = [["sh"]] + ([["busybox", "ash"]] if shutil.which("busybox") else [])
fails = []

# Original expressions, verbatim from the previous primitives.
REFERENCE = r'''
ref_vr2_file() { [ -f "$1" ] && [ ! -L "$1" ] && [ -r "$1" ] && [ "$(wc -c < "$1")" -le 1048576 ] && [ "$(wc -l < "$1")" -le 4096 ]; }
ref_mode() { ls -ldn "$1" 2>/dev/null | awk '{print substr($1,1,10)}'; }
ref_mode_links() { ls -ldn "$1" 2>/dev/null | awk '{print substr($1,1,10),$2}'; }
ref_mode_uid() { ls -ldn "$1" 2>/dev/null | awk '{print substr($1,1,10),$3}'; }
ref_links() { LC_ALL=C ls -ldn "$1" 2>/dev/null | awk '{print $2}'; }
ref_vrj2_file() {
    [ -f "$1" ] && [ ! -L "$1" ] && [ -O "$1" ] && [ -r "$1" ] || return 2
    case $(ls -ldn "$1" | awk '{print substr($1,1,10)}') in -rw-------|-r--------) ;; *) return 2 ;; esac
    [ "$(wc -c < "$1")" -le 1048576 ]
}
'''
NAMES = "f600 fnonl fempty f400 f644 fbig flines d700 d755 lnk hard nope ftrail fmulti fspace"
PROBE = REFERENCE + r'''
cd "$1"
for f in ''' + NAMES + r'''; do
  P=$PWD/$f
  ref_vr2_file "$P"; a=$?; vr2_file "$P"; b=$?
  [ "$a" = 0 ] && a=0 || a=1; [ "$b" = 0 ] && b=0 || b=1
  [ "$a" = "$b" ] || echo "DIFF vr2_file $f $a $b"
  ref_vrj2_file "$P" 2>/dev/null; a=$?; vrj2_file "$P"; b=$?
  [ "$a" = "$b" ] || echo "DIFF vrj2_file $f $a $b"
  if [ -e "$P" ] || [ -L "$P" ]; then
    vrj_ls "$P"; [ "$(ref_mode_uid "$P")" = "$vrj_lmode $vrj_luid" ] || echo "DIFF vrj_ls mode/uid $f"
    [ "$(ref_links "$P")" = "$vrj_llinks" ] || echo "DIFF vrj_ls links $f"
    vward_lock_ls "$P"; [ "$(ref_mode_links "$P")" = "$vl_lsmode $vl_lslinks" ] || echo "DIFF lock_ls $f"
    vr2_ls "$P"; [ "$(ref_mode "$P")" = "$vr2_lmode" ] || echo "DIFF vr2_ls $f"
  fi
  vrj_slurp "$P"; [ "$(cat "$P" 2>/dev/null)" = "$vrj_sv" ] || echo "DIFF slurp $f"
  a=$( [ -d "$P" ] && [ ! -L "$P" ] && [ -O "$P" ] && [ "$(ref_mode "$P")" = drwx------ ]; echo $?)
  b=$(vr2_private_dir "$P"; echo $?); [ "$a" = "$b" ] || echo "DIFF private_dir $f $a $b"
done
echo PROBE-END
'''


def tree(d):
    old = os.umask(0o077)
    try:
        (d / "f600").write_text("a\nb\n")
        (d / "fnonl").write_text("nonl")
        (d / "fempty").write_text("")
        (d / "f400").write_text("x\n"); (d / "f400").chmod(0o400)
        (d / "f644").write_text("y\n"); (d / "f644").chmod(0o644)
        (d / "fbig").write_bytes(b"\0" * 1048577)
        (d / "flines").write_text("".join(f"{i}\n" for i in range(5000)))
        (d / "d700").mkdir()
        (d / "d755").mkdir(); (d / "d755").chmod(0o755)
        os.symlink(d / "f600", d / "lnk")
        os.link(d / "f600", d / "hard")
        (d / "ftrail").write_text("a\n\n\n")
        (d / "fmulti").write_text("x\ny\n\n")
        (d / "fspace").write_text("  lead\\back\ttab  \n")
    finally:
        os.umask(old)


def seal(d, files, rows=None, typ="t", gen="g-0123456789abcdef"):
    d.mkdir(mode=0o700)
    for name, body in files.items():
        (d / name).write_bytes(body)
    (d / "generation").write_text(gen + "\n")
    if rows is None:
        rows = [(hashlib.sha256(files[n]).hexdigest(), n) for n in files]
    text = f"{typ}\t2\t{gen}\n" + "".join(f"{h}\t{n}\n" for h, n in rows)
    (d / "seal").write_text(text)
    (d / "seal.sha").write_text(hashlib.sha256(text.encode()).hexdigest() + "\n")


H = lambda b: hashlib.sha256(b).hexdigest()
BASE = {"a": b"1\n", "b": b"two\nlines\n", "c": b""}
# Expected codes are those of the previous per-file implementation (verified
# old==new on both shells before the old code was replaced).
SEAL_CASES = {
    "valid": (lambda d: seal(d, BASE), 0),
    "tamper-content": (lambda d: (seal(d, BASE), (d / "b").write_bytes(b"x\n")), 3),
    "tamper-digest": (lambda d: seal(d, BASE, rows=[("0" * 64, "a"), (H(BASE["b"]), "b"), (H(b""), "c")]), 3),
    "missing-file": (lambda d: (seal(d, BASE), (d / "c").unlink()), 3),
    "missing-row": (lambda d: seal(d, BASE, rows=[(H(BASE["a"]), "a"), (H(BASE["b"]), "b")]), 1),
    "duplicate-row": (lambda d: seal(d, BASE, rows=[(H(BASE["a"]), "a")] * 2 + [(H(b""), "c")]), 2),
    "unknown-name": (lambda d: seal(d, {"a": b"1\n", "b": b"2\n", "zz": b""}), 2),
    "symlink": (lambda d: (seal(d, BASE), (d / "c").unlink(), os.symlink(d / "a", d / "c")), 3),
    "directory": (lambda d: (seal(d, BASE), (d / "c").unlink(), (d / "c").mkdir()), 3),
    "oversize": (lambda d: seal(d, {"a": b"0" * 1048577, "b": b"", "c": b""}), 3),
    "too-many-lines": (lambda d: seal(d, {"a": b"\n" * 4097, "b": b"", "c": b""}), 3),
    "at-limits": (lambda d: seal(d, {"a": b"\n" * 4096, "b": b"0" * (1048576 - 4096), "c": b""}), 0),
    "extra-field": (lambda d: seal(d, BASE, rows=[(H(BASE["a"]), "a\tx"), (H(BASE["b"]), "b"), (H(b""), "c")]), 2),
    "wrong-type": (lambda d: seal(d, BASE, typ="other"), 3),
    "non-hex-digest": (lambda d: seal(d, BASE, rows=[("Z" * 64, "a"), (H(BASE["b"]), "b"), (H(b""), "c")]), 3),
}

LOAD = f'. "{LIB}/vward-routing-journal.sh"; . "{LIB}/vward-routing-project.sh"; . "{LIB}/vward-runtime-admission.sh"\n'
for shell in SHELLS:
    n = shell[-1]
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "probe"; d.mkdir(mode=0o700); tree(d)
        r = subprocess.run(shell + ["-c", LOAD + PROBE, "x", str(d)], capture_output=True, text=True, timeout=120)
        if "PROBE-END" not in r.stdout or "DIFF" in r.stdout:
            fails.append(f"{n} primitives: {r.stdout}{r.stderr}")
    for name, (make, want) in SEAL_CASES.items():
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "s"; make(d)
            r = subprocess.run(shell + ["-c", LOAD + 'vr2_seal_valid "$1" t "a b c"; echo "rc=$?"', "x", str(d)],
                               capture_output=True, text=True, timeout=60)
            if r.stdout.strip() != f"rc={want}":
                fails.append(f"{n} seal {name}: want rc={want}, got {r.stdout.strip()} {r.stderr.strip()}")

if fails:
    raise SystemExit("VALIDATION_PRIMITIVES=FAIL\n" + "\n".join(fails))
print(f"VALIDATION_PRIMITIVES=PASS {len(SHELLS)} shells: ls/wc/cat primitives equal the original pipelines; "
      f"batched seal keeps all {len(SEAL_CASES)} per-file verdicts")
