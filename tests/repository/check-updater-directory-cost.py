#!/usr/bin/env python3
"""Repeated journal/log writes keep their errors and avoid redundant directory processes."""
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/update-engine/vward-update-common-base.sh"
SHELLS = [["sh"]]
if shutil.which("busybox"):
    SHELLS.append([shutil.which("busybox"), "ash"])

for shell in SHELLS:
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        counter = t / "mkdir.calls"
        counter.touch()

        def run(body):
            # Count actual mkdir invocations; never replace its result with success.
            script = (f'. {shlex.quote(str(LIB))}\n'
                      f'mkdir() {{ printf "call\\n" >> {shlex.quote(str(counter))}; command mkdir "$@"; }}\n' + body)
            return subprocess.run(shell + ["-c", script], env=os.environ | {
                "VWARD_ROOT_PREFIX": str(t / "root"),
                "VWARD_UPDATE_STATE_DIR": str(t / "state"),
                "VWARD_UPDATE_LOG_DIR": str(t / "log"),
            }, capture_output=True, text=True, timeout=30, umask=0o022)

        # First use must create its own missing directories and persist actual bytes.
        r = run('vu_state_set sample first && vu_log INFO first')
        assert r.returncode == 0, r.stderr
        assert (t / "state/state").read_text() == "sample=first\n"
        assert "[INFO] first\n" in (t / "log/updater.log").read_text()
        assert (t / "state/state").stat().st_mode & 0o777 == 0o600
        assert counter.read_text(), "missing directories were not created"

        # Repeats preserve replacement, other keys and modes without spawning mkdir.
        counter.write_text("")
        r = run('vu_state_set other kept && vu_state_set sample second && '
                'vu_log INFO second && vu_log WARN third')
        assert r.returncode == 0, r.stderr
        assert (t / "state/state").read_text() == "other=kept\nsample=second\n"
        assert (t / "state/state").stat().st_mode & 0o777 == 0o600
        assert "[WARN] third\n" in (t / "log/updater.log").read_text()
        assert counter.read_text() == "", "RED: repeated writes spawn redundant mkdir processes"

        # An existing directory does not make a failed write successful.
        before = (t / "state/state").read_bytes()
        r = run('vu_state_set sample forbidden "$VU_STATE_DIR/missing/state"')
        assert r.returncode != 0 and (t / "state/state").read_bytes() == before
        assert not (t / "state/missing").exists()

        # A file in place of the directory still reaches real mkdir and refuses.
        shutil.rmtree(t / "state")
        (t / "state").write_bytes(b"foreign\n")
        counter.write_text("")
        r = run('vu_state_set sample forbidden')
        assert r.returncode != 0 and (t / "state").read_bytes() == b"foreign\n"
        assert counter.read_text(), "directory refusal was bypassed"

        # Logging remains best effort, but never replaces a file blocking its directory.
        shutil.rmtree(t / "log")
        (t / "log").write_bytes(b"foreign-log\n")
        counter.write_text("")
        r = run('vu_log ERROR refused')
        assert r.returncode == 0 and "[ERROR] refused" in r.stderr
        assert (t / "log").read_bytes() == b"foreign-log\n" and counter.read_text()

        # Existing directory symlinks retain the previous mkdir -p semantics.
        (t / "state").unlink()
        (t / "actual").mkdir()
        (t / "state").symlink_to(t / "actual", target_is_directory=True)
        r = run('vu_state_set sample linked')
        assert r.returncode == 0 and (t / "actual/state").read_text() == "sample=linked\n", r.stderr

print("UPDATER_DIRECTORY_COST=PASS")
