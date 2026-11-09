#!/usr/bin/env python3
"""Process-budget pass 2 keeps the exact verdicts of the replaced primitives.

The service-change chain spawned ~22.6k processes per ordinary change (owner
measurement, BusyBox on Keenetic ~10 ms/process). The rewritten primitives batch
a set of files into one ls/sha256sum/wc/awk, read small records with shell
builtins and drop command-substitution subshells. Here, on sh and BusyBox ash,
each one is compared with the ORIGINAL implementation (git 4cf3388, loaded in a
separate shell) on the same inputs, including every corruption class:

  * consistent-read fingerprint (inputs.fp/generation byte-identical), also
    with an `ls` that refuses --full-time (per-file fallback);
  * journal gate / ready / step validation with the read-only metadata cache
    (one ls/sha256sum/awk per gate) over valid and corrupted journals;
  * plan row/field decoding without awk/cut/tr, generation shape check;
  * lock boot-id / decimal records and the ancestor-chain path gate.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib"
BASE = "4cf3388"
SHELLS = [["sh"]] + ([["busybox", "ash"]] if shutil.which("busybox") else [])
fails = []
sys.path.insert(0, str(Path(__file__).resolve().parent))


def old_lib(tmp, name):
    # Byte-exact reference copy (CI checks out without git history).
    p = Path(tmp) / ("old-" + name)
    p.write_bytes((Path(__file__).resolve().parent / "reference" / BASE / name).read_bytes())
    return p


def run(shell, libs, body, *args, env=None, timeout=120):
    load = "".join(f'. "{l}"\n' for l in libs)
    return subprocess.run(shell + ["-c", load + body, "x", *map(str, args)], capture_output=True, text=True,
                          timeout=timeout, env=env)


# ---------------------------------------------------------------- journal
H = lambda b: hashlib.sha256(b).hexdigest()
G = "g-0123456789abcdef"


def op(j, name, steps, state="committed", native=True, save="done", mutate=None):
    d = j / name
    d.mkdir(mode=0o700)
    kinds = ["group" if native else "manifest"] + ["manifest"] * (steps - 1)
    rows = [f"routing-plan\t2\t{G}\tdenied"]
    for n in range(1, steps + 1):
        pre, post = H(b"pre%d" % n), H(b"post%d" % n)
        rows.append(f"step\t{n}\tmove\t{kinds[n-1]}\tdomain-list{n}\t{pre}\t{post}\tcreation-and-cas\t-\t"
                    f"generation,identity\trestore-own-scope")
    plan = "\n".join(rows) + "\n"
    files = {"schema": "routing-journal\t2\n", "plan": plan, "plan.sha": H(plan.encode()) + "\n",
             "state": state + "\n", "generation": G + "\n"}
    if save is not None:
        files["save"] = save + "\n"
    for k, v in files.items():
        (d / k).write_text(v)
    for n in range(1, steps + 1):
        s = d / f"step.{n}"
        s.mkdir(mode=0o700)
        for k, v in {"pre": H(b"pre%d" % n), "post": H(b"post%d" % n),
                     "state": "done" if state == "committed" else "compensated", "generation": G}.items():
            (s / k).write_text(v + "\n")
    if state == "compensated":
        rec = f"record=resolved\nopid={name}\nplan_sha={H(plan.encode())}\ngeneration={G}\nresult=compensated\n"
        (d / "resolved").write_text(rec)
        (d / "resolved.sha").write_text(H(rec.encode()) + "\n")
    if mutate:
        mutate(d)
    return d


def chmod(p, m):
    os.chmod(p, m)


def plan_edit(d, f):
    t = (d / "plan").read_text()
    t = f(t)
    (d / "plan").write_text(t)
    (d / "plan.sha").write_text(H(t.encode()) + "\n")


JOURNAL_CASES = {
    "valid": lambda d: None,
    "missing-plan.sha": lambda d: (d / "plan.sha").unlink(),
    "plan-0644": lambda d: chmod(d / "plan", 0o644),
    "state-0400": lambda d: chmod(d / "state", 0o400),
    "state-0600-dir": lambda d: chmod(d, 0o755),
    "plan-symlink": lambda d: ((d / "plan").rename(d / "plan.real"), os.symlink(d / "plan.real", d / "plan")),
    "sha-mismatch": lambda d: (d / "plan.sha").write_text("0" * 64 + "\n"),
    "plan-invalid": lambda d: plan_edit(d, lambda t: t.replace("move", "jump", 1)),
    "plan-row-01": lambda d: plan_edit(d, lambda t: t.replace("step\t1\t", "step\t01\t", 1)),
    "plan-row-1.0": lambda d: plan_edit(d, lambda t: t.replace("step\t1\t", "step\t1.0\t", 1)),
    "plan-empty": lambda d: plan_edit(d, lambda t: ""),
    "plan-no-newline": lambda d: plan_edit(d, lambda t: t.rstrip("\n")),
    "schema-bad": lambda d: (d / "schema").write_text("routing-journal\t1\n"),
    "gen-bad": lambda d: (d / "generation").write_text("g-XYZ\n"),
    "gen-multiline": lambda d: (d / "generation").write_text("junk\n" + G + "\n"),
    "state-pending": lambda d: (d / "state").write_text("pending\n"),
    "state-planned-with-steps": lambda d: (d / "state").write_text("planned\n"),
    "state-unknown-word": lambda d: (d / "state").write_text("weird\n"),
    "step-pending": lambda d: (d / "step.1/state").write_text("pending\n"),
    "step-failed-committed": lambda d: (d / "step.1/state").write_text("failed\n"),
    "step-pre-mismatch": lambda d: (d / "step.1/pre").write_text("x\n"),
    "step-file-0644": lambda d: chmod(d / "step.1/post", 0o644),
    "step-dir-0755": lambda d: chmod(d / "step.1", 0o755),
    "step-missing": lambda d: shutil.rmtree(d / "step.2"),
    "step-extra": lambda d: shutil.copytree(d / "step.2", d / "step.3"),
    "step-zero": lambda d: shutil.copytree(d / "step.1", d / "step.0"),
    "step-alias-01": lambda d: shutil.copytree(d / "step.1", d / "step.01"),
    "save-missing": lambda d: (d / "save").unlink(),
    "save-failed": lambda d: (d / "save").write_text("failed\n"),
    "trailing-blank-lines": lambda d: (d / "state").write_text("committed\n\n\n"),
    "oversize-plan": lambda d: plan_edit(d, lambda t: t + "x" * 1048577),
    "bad-op-name": lambda d: d.rename(d.parent / "-bad"),
}

GATE = r'''
J=$1
vward_journal2_gate "$J"; echo "gate=$?"
vrj2_gate_except "$J" r-a; echo "except=$?"
for o in "$J"/*; do n=${o##*/}; vrj2_ready "$J" "$n"; echo "ready:$n=$?"
  for s in "$o"/step.*; do [ -e "$s" ] || continue; vrj2_step_valid "$J" "$n" "${s##*/step.}"; echo "step:$n:${s##*/}=$?"; done
done
'''


def journal_checks(shell, old, new, tmp):
    for case, mut in JOURNAL_CASES.items():
        for second in ("committed", "compensated"):
            base = Path(tempfile.mkdtemp(dir=tmp))
            j = base / "journal"
            j.mkdir(mode=0o700)
            old_umask = os.umask(0o077)
            try:
                op(j, "r-a", 2)
                op(j, "r-b", 2, state=second, native=True, save="done", mutate=mut)
                op(j, "r-c", 3, native=False)
            finally:
                os.umask(old_umask)
            a = run(shell, old, GATE, j)
            b = run(shell, new, GATE, j)
            if a.stdout != b.stdout or "gate=" not in a.stdout:
                fails.append(f"{shell[-1]} journal {case}/{second}:\nold {a.stdout}{a.stderr}\nnew {b.stdout}{b.stderr}")


ROWS = r'''
P=$1
for n in 1 2 3; do
  if [ "$NEW" = 1 ]; then
    if vrj2_row_fields "$P" "$n"; then echo "rc=0 row=[$vrj2_row] pre=[$vrj2_pre] post=[$vrj2_post] d=[$vrj2_dpre]/[$vrj2_dpost]"; else echo "rc=2"; fi
  else
    if vrj2_row=$(vrj2_step_row "$P" "$n"); then
      vrj2_pre=$(printf '%s\n' "$vrj2_row" | cut -f6);vrj2_post=$(printf '%s\n' "$vrj2_row" | cut -f7)
      echo "rc=0 row=[$vrj2_row] pre=[$vrj2_pre] post=[$vrj2_post] d=[$(vrj2_decode "$vrj2_pre")]/[$(vrj2_decode "$vrj2_post")]"
    else echo "rc=2"; fi
  fi
done
for v in "$G1" "$G2" "$G3" "$G4" "$G5"; do vrj2_gen "$v"; echo "gen=$?"; done
'''
ROW_PLANS = {
    "canonical": "routing-plan\t2\tg\tdenied\nstep\t1\tmove\tgroup\tx\ta|b\tc|d|e\tz\t-\tq\tr\nstep\t2\tadd\tdns\ty\tp\tq\tz\t-\tq\tr\n",
    "dup": "h\nstep\t1\ta\tb\tc\td\te\tf\tg\th\ti\nstep\t1\ta\tb\tc\tX\tY\tf\tg\th\ti\n",
    "leading-zero": "h\nstep\t01\ta\tb\tc\td\te\tf\tg\th\ti\n",
    "float": "h\nstep\t1.0\ta\tb\tc\td\te\tf\tg\th\ti\n",
    "short": "h\nstep\t1\ta\tb\tc\n",
    "six": "h\nstep\t1\ta\tb\tc\td\n",
    "no-newline": "h\nstep\t1\ta\tb\tc\td|x\te\tf\tg\th\ti",
    "notab-step": "h\nstep\nstep 1\n",
}


def row_checks(shell, old, new, tmp):
    env = os.environ | {"G1": G, "G2": "g-0123", "G3": "x\n" + G, "G4": G + "\r", "G5": "G-0123456789ABCDEF"}
    for case, text in ROW_PLANS.items():
        d = Path(tempfile.mkdtemp(dir=tmp))
        (d / "plan").write_text(text)
        a = run(shell, old, ROWS, d, env=env | {"NEW": "0"})
        b = run(shell, new, ROWS, d, env=env | {"NEW": "1"})
        if a.stdout != b.stdout or not a.stdout:
            fails.append(f"{shell[-1]} rows {case}:\nold {a.stdout}{a.stderr}\nnew {b.stdout}{b.stderr}")


LOCKS = r'''
for f in "$@"; do
  a=$(vward_lock_boot_id "$f"); echo "boot:${f##*/}=$?:$a"
  a=$(vward_lock_gate_decimal "$f" 2>/dev/null); echo "dec:${f##*/}=$?:$a"
  if [ "$NEW" = 1 ]; then
    vward_lock_boot_var "$f"; echo "bootvar:${f##*/}=$?:$vl_boot"
    vward_lock_gate_decimal_var "$f"; echo "decvar:${f##*/}=$?:$vlg_dec"
  fi
done
'''


def lock_checks(shell, old, new, tmp):
    d = Path(tempfile.mkdtemp(dir=tmp))
    u = "0123abcd-0000-4000-8000-0123456789ab"
    old_umask = os.umask(0o077)
    try:
        bodies = {"uuid": u + "\n", "upper": u.upper() + "\n", "space": " " + u + " \n", "two": u + "\nx\n",
                  "short": u[:-1] + "\n", "nonl": u, "dec": "123\n", "dec-tail": "123\n\n", "dec-extra": "123\n4\n",
                  "dec-zero": "0123\n", "dec-long": "1" * 21 + "\n", "empty": ""}
        for k, v in bodies.items():
            (d / k).write_text(v)
        (d / "mode").write_text(u + "\n"); os.chmod(d / "mode", 0o644)
        (d / "ro").write_text(u + "\n"); os.chmod(d / "ro", 0o400)
        os.symlink(d / "uuid", d / "link")
        os.link(d / "dec", d / "hard")
    finally:
        os.umask(old_umask)
    names = sorted(p.name for p in d.iterdir()) + ["missing"]
    a = run(shell, old, LOCKS, *[d / n for n in names], env=os.environ | {"NEW": "0"})
    b = run(shell, new, LOCKS, *[d / n for n in names], env=os.environ | {"NEW": "1"})
    oldv = a.stdout
    newv = "".join(l + "\n" for l in b.stdout.splitlines() if l.startswith(("boot:", "dec:")))
    if oldv != newv or not oldv:
        fails.append(f"{shell[-1]} locks:\nold {oldv}\nnew {newv}")
    # The var forms equal the printing forms on the NEW library too.
    for l in b.stdout.splitlines():
        if l.startswith("bootvar:") or l.startswith("decvar:"):
            k = l.split(":", 1)[1]
            want = [x for x in b.stdout.splitlines() if x.startswith(("boot:" if l.startswith("bootvar") else "dec:") + k.split("=")[0] + "=")]
            if not want or want[0].split("=", 1)[1].split(":", 1)[1] != l.split("=", 1)[1].split(":", 1)[1] or \
               (want[0].split("=", 1)[1].split(":")[0] == "0") != (l.split("=", 1)[1].split(":")[0] == "0"):
                fails.append(f"{shell[-1]} lock var mismatch: {l} vs {want}")


GATEPATH = r'''
vrb_e=$1/opt/var/lib/vward/routing; vrl_etc=$1/opt/etc/vward; VWARD_ROOT_PREFIX=$1
shift
for p in "$@"; do vrl_path_gate "$p"; echo "${p#$VWARD_ROOT_PREFIX}=$?"; done
'''


def path_checks(shell, old, new, tmp):
    r = Path(tempfile.mkdtemp(dir=tmp))
    e = r / "opt/var/lib/vward/routing"
    (e / "decision").mkdir(parents=True)
    (r / "opt/etc/vward/services/owned").mkdir(parents=True)
    (r / "opt/etc/vward/route-engine/domain-lists").mkdir(parents=True)
    (r / "tmp/sub").mkdir(parents=True)
    os.symlink(r / "tmp/sub", r / "tmp/alias")
    paths = [e / "decision/choices.tsv", r / "opt/etc/vward/services/owned/domain-list0",
             r / "opt/etc/vward/route-engine/domain-lists/x", r / "tmp/sub/f", r / "tmp/alias/f",
             r / "tmp/f", r / "opt/etc/vward/device.conf", r / "etc/passwd", e / "../x", e / "a//b"]
    for mode in (0o700, 0o755, 0o750, 0o711, 0o775, 0o777, 0o705):
        os.chmod(r / "opt/etc/vward/services", mode)
        os.chmod(r / "tmp/sub", mode)
        a = run(shell, old, GATEPATH, r, *paths)
        b = run(shell, new, GATEPATH, r, *paths)
        if a.stdout != b.stdout or not a.stdout:
            fails.append(f"{shell[-1]} path gate {oct(mode)}:\nold {a.stdout}{a.stderr}\nnew {b.stdout}{b.stderr}")


def snapshot_checks(shell, tmp):
    """inputs.fp/generation of a consistent read: new == original, also on fallback."""
    from live_fixture import LiveFixture
    import live_fixture
    for variant in ("batch", "no-full-time", "edge-inputs", "fatal-badname", "fatal-symlink"):
        with LiveFixture() as f:
            old_snap = old_lib(f.p, "vward-routing-snapshot.sh")
            libs_new = list(f.libs)
            libs_old = [old_snap if Path(l).name == "vward-routing-snapshot.sh" else l for l in f.libs]
            env = f.env | {"VWARD_KCACHE": str(f.p / "kcache"), "VWARD_ROUTING_CACHE_AGE": "3600"}
            (f.p / "kcache").mkdir(mode=0o700)
            (f.p / "kcache/running-config").write_text((f.e / "running.cfg").read_text())
            if variant == "no-full-time":
                shim = f.p / "lsshim"; shim.mkdir()
                real = shutil.which("ls")
                (shim / "ls").write_text('#!/bin/sh\nfor a in "$@"; do [ "$a" = --full-time ] && exit 2; done\n'
                                         f'exec {real} "$@"\n')
                (shim / "ls").chmod(0o755)
                env["PATH"] = f"{shim}:{env['PATH']}"
            own = f.etc / "services/owned"
            if variant == "fatal-badname":
                (own / "bad name").write_text("x\n")
            if variant == "fatal-symlink":
                (own / "domain-list0").write_text("include a\n"); (own / "domain-list0").chmod(0o600)
                os.symlink(own / "domain-list0", own / "domain-list9")
            if variant == "edge-inputs":
                # Soft observer inputs: oversize / non-regular stay rc 0.
                (own / "domain-list0").write_text("include a\n"); (own / "domain-list0").chmod(0o600)
                (own / "domain-list1").write_text(""); (own / "domain-list1").chmod(0o400)
                (f.etc / "route-engine").mkdir(exist_ok=True)
                (f.etc / "route-engine/force-vpn.conf").write_bytes(b"0" * 1048577)
                (f.etc / "smartdns.conf").mkdir()
            outs = []
            for libs in (libs_old, libs_new):
                out = Path(tempfile.mkdtemp(dir=f.p))
                os.chmod(out, 0o700)
                body = 'vward_routing_consistent_read2 "$1" "$2"; echo "rc=$?"'
                r = run(shell, libs, body, out, f.live / "decision", env=env)
                fp = (out / "inputs.fp").read_text() if (out / "inputs.fp").exists() else ""
                gen = (out / "generation").read_text() if (out / "generation").exists() else ""
                outs.append((r.stdout, fp, gen, r.stderr[-300:]))
            fatal = variant.startswith("fatal")
            if outs[0][:3] != outs[1][:3] or (not fatal and ("rc=0" not in outs[0][0] or not outs[0][1])) or \
               (fatal and "rc=3" not in outs[0][0]):
                fails.append(f"{shell[-1]} snapshot {variant}:\nold {outs[0]}\nnew {outs[1]}")


with tempfile.TemporaryDirectory() as tmp:
    jold = [old_lib(tmp, "vward-runtime-admission.sh"), old_lib(tmp, "vward-routing-journal.sh")]
    jnew = [LIB / "vward-runtime-admission.sh", LIB / "vward-routing-journal.sh"]
    live_old = jold + [old_lib(tmp, "vward-routing-live.sh")]
    live_new = jnew + [LIB / "vward-routing-live.sh"]
    for shell in SHELLS:
        journal_checks(shell, jold, jnew, tmp)
        row_checks(shell, jold, jnew, tmp)
        lock_checks(shell, jold, jnew, tmp)
        path_checks(shell, live_old, live_new, tmp)
        if shell == ["sh"]:
            snapshot_checks(shell, tmp)
        else:
            os.environ["RS6_BUSYBOX"] = shutil.which("busybox")
            snapshot_checks(shell, tmp)

if fails:
    raise SystemExit("PROCESS_BUDGET_PRIMITIVES=FAIL\n" + "\n".join(fails[:20]))
print(f"PROCESS_BUDGET_PRIMITIVES=PASS {len(SHELLS)} shells: journal gate/ready/step x{len(JOURNAL_CASES)*2} journals, "
      f"plan rows x{len(ROW_PLANS)}, lock records, path gate x7 modes, snapshot fingerprint (batch, no --full-time, "
      f"edge inputs) equal to {BASE}")
