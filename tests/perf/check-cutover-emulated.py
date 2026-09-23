#!/usr/bin/env python3
"""scripts/beta-to-dev-cutover.sh, end to end, on the router emulator.

Two runs, each in its own emulated beta 0.1.9-beta router
(tests/perf/emulator/build-rootfs-beta.sh):

  1. --check reports readiness; --apply stops beta's daemons, merges cron,
     retires beta's init scripts and archives its files; a real signed 0.2
     candidate is then applied over the same root through the normal
     Update Engine and must come up healthy with none of beta's processes
     left; re-running --apply is refused.
  2. A fresh root: --apply, then --rollback restores the crontab, init
     scripts and program files byte for byte and beta's daemons start again.

Needs root (chroot, mknod, mount proc, tar) and the tools
tests/perf/run-resource-audit.py needs (jq, openssl, busybox, gcc).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUILD_BETA = REPO / "tests/perf/emulator/build-rootfs-beta.sh"
CUTOVER = REPO / "scripts/beta-to-dev-cutover.sh"
PATH_ENV = "/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
BETA_DAEMON_RE = re.compile(r"^\s*\d+ (/bin/sh /opt/bin/(agh-adaptive-live|crond-supervisor)\.sh"
                             r"|tcpdump -ni any -l -vv src net|/opt/sbin/lighttpd -f )")
DEV_DAEMON_RE = re.compile(r"^\s*\d+ /bin/sh /opt/bin/vward-route-engine\.sh")


def fail(message):
    raise SystemExit(f"FAIL: {message}")


def sh(root, command, timeout=180):
    return subprocess.run(["env", "-i", f"PATH={PATH_ENV}", "HOME=/root",
                           "chroot", str(root), "/bin/sh", "-c", command],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)


def build_beta_root(work, name):
    root = work / name
    subprocess.run([str(BUILD_BETA), str(root)], check=True, stdout=subprocess.DEVNULL)
    shutil.copy(CUTOVER, root / "opt/bin/vward-beta-cutover.sh")
    os.chmod(root / "opt/bin/vward-beta-cutover.sh", 0o755)
    subprocess.run(["mount", "-t", "proc", "proc", str(root / "proc")], check=True)
    subprocess.run(["mount", "--bind", str(root / "opt"), str(root / "opt")], check=True)
    for svc in ("S90crond", "S91adaptive-live", "S92crond-supervisor", "S93keenetic-apps"):
        r = sh(root, f"/opt/etc/init.d/{svc} start")
        if r.returncode != 0:
            fail(f"beta seed did not start {svc}:\n{r.stdout}")
    return root


def teardown(root):
    # Belt and braces: kill by known pattern first, then by chroot root (a
    # process whose root or cwd is under here also pins the bind mount, even
    # with no matching fd open, and ps alone will not show that).
    pids = set(ps_matches(BETA_DAEMON_RE)) | set(ps_matches(DEV_DAEMON_RE))
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            if Path(os.readlink(entry / "root")) == root or Path(os.readlink(entry / "cwd")) == root:
                pids.add(int(entry.name))
        except OSError:
            continue
    for p in pids:
        try:
            os.kill(p, 9)
        except OSError:
            pass
    time.sleep(0.3)
    subprocess.run(["umount", str(root / "opt")])
    subprocess.run(["umount", str(root / "proc")])


def ps_matches(pattern):
    out = subprocess.run(["ps", "-eo", "pid,args"], stdout=subprocess.PIPE, text=True).stdout
    return [int(m.group(0).split()[0]) for m in (pattern.match(l) for l in out.splitlines()) if m]


def read(path):
    return path.read_text() if path.exists() else ""


def crontab_of(root):
    return read(root / "opt/var/spool/cron/crontabs/root")


def latest_backup(root):
    base = root / "opt/var/backups/vward/cutover"
    stamps = sorted(p.name for p in base.iterdir()) if base.exists() else []
    return stamps[-1] if stamps else None


def part1_apply_then_real_install(work):
    root = build_beta_root(work, "cut1")
    try:
        before_daemons = ps_matches(BETA_DAEMON_RE)
        if len(before_daemons) < 3:
            fail(f"beta seed did not bring up its daemons: {before_daemons}")

        check = sh(root, "/opt/bin/vward-beta-cutover.sh --check")
        if "ready for --apply                : yes" not in check.stdout:
            fail(f"--check should report ready before apply:\n{check.stdout}")

        apply1 = sh(root, "/opt/bin/vward-beta-cutover.sh --apply")
        if apply1.returncode != 0:
            fail(f"--apply failed:\n{apply1.stdout}")
        time.sleep(1)

        left = ps_matches(BETA_DAEMON_RE)
        if left:
            fail(f"beta daemons still running after --apply: {left}")
        for s in ("S91adaptive-live", "S92crond-supervisor", "S93keenetic-apps"):
            if (root / f"opt/etc/init.d/{s}").exists():
                fail(f"{s} was not retired")
        if not (root / "opt/etc/init.d/S90crond").exists():
            fail("S90crond must not be touched")
        for p in ("agh-adaptive-live.sh", "wan-guardian.sh", "crond-supervisor.sh"):
            if (root / f"opt/bin/{p}").exists():
                fail(f"beta program file survived cutover: {p}")

        cron = crontab_of(root)
        for marker in ("adaptive-auto-maint.sh", "S91adaptive-live", "wan-guardian.sh"):
            if marker in cron:
                fail(f"beta cron marker still present: {marker}\n{cron}")
        for marker in ("vward-route-engine", "S91vward-route-engine", "vward-wan-guard.sh"):
            if marker not in cron:
                fail(f"dev cron marker missing after cutover: {marker}\n{cron}")

        stamp = latest_backup(root)
        if not stamp:
            fail("no backup snapshot was created")
        bk = root / f"opt/var/backups/vward/cutover/{stamp}"
        for f in ("root.crontab", "running-config.txt", "legacy.tar.gz", "manifest.txt"):
            if not (bk / f).exists():
                fail(f"backup is missing {f}")
        if "adaptive-auto-maint.sh" not in read(bk / "root.crontab"):
            fail("backed-up crontab does not contain the original beta lines")

        check2 = sh(root, "/opt/bin/vward-beta-cutover.sh --check")
        if "cutover already applied         : yes" not in check2.stdout:
            fail(f"--check should report the cutover as applied:\n{check2.stdout}")

        apply2 = sh(root, "/opt/bin/vward-beta-cutover.sh --apply")
        if apply2.returncode == 0:
            fail("a second --apply should be refused")

        # Now the real signed 0.2 candidate, over this now-cut-over root,
        # through the normal, already-tested Update Engine path.
        rehearsal_work = work / "rehearsal"
        rehearsal_work.mkdir()
        priv, pub = rehearsal_work / "private.pem", rehearsal_work / "public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(priv)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["openssl", "pkey", "-in", str(priv), "-pubout", "-out", str(pub)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        version = (REPO / "VERSION").read_text().strip()
        release = rehearsal_work / "release"
        env = os.environ | {"VWARD_SIGNING_KEY_FILE": str(priv), "VWARD_REHEARSAL_PUBLIC_KEY": str(pub)}
        r = subprocess.run([str(REPO / "scripts/prepare-dev-release.sh"), str(release), "2026099901", "0.1.9-beta"],
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if r.returncode != 0:
            fail(f"prepare-dev-release.sh failed:\n{r.stdout}")
        manifest = release / "update-manifest.json"
        package = release / f"candidate/vward-{version}.tar.gz"
        shutil.copy(pub, root / "opt/etc/vward/update-public.pem")
        config = root / "opt/etc/vward/update.conf"
        config.write_text(
            "update_enabled=1\nauto_apply=0\nchannel=dev\n"
            f"public_key_file={root}/opt/etc/vward/update-public.pem\n"
            f"current_version_file={root}/opt/share/vward/VERSION\n"
            "minimum_free_kb=1\nbarrier_integration_ready=1\napply_window=any\n"
        )

        r = subprocess.run(["env", "-i", f"PATH={PATH_ENV}", "HOME=/root",
                            f"VWARD_ROOT_PREFIX={root}", f"VWARD_UPDATE_CONFIG={config}",
                            f"VWARD_TEST_MANIFEST={manifest}", f"VWARD_TEST_PACKAGE={package}",
                            str(REPO / "components/update-engine/vward-update.sh"), "--apply"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
        if r.returncode != 0:
            fail(f"applying the real 0.2 candidate over the cut-over root failed:\n{r.stdout}")

        installed = read(root / "opt/share/vward/VERSION").strip()
        if installed != version:
            fail(f"installed VERSION is {installed!r}, expected {version!r}")
        if not (root / "opt/etc/init.d/S91vward-route-engine").exists():
            fail("dev's init script was not installed")
        print(f"ok - beta {read(root / 'opt/share/vward/VERSION').strip()}: cutover then real {version} install")
    finally:
        teardown(root)


def part2_rollback(work):
    root = build_beta_root(work, "cut2")
    try:
        before_crontab = crontab_of(root)
        before_programs = sorted((root / "opt/bin").glob("*.sh"))
        before_names = sorted(p.name for p in before_programs)

        apply1 = sh(root, "/opt/bin/vward-beta-cutover.sh --apply")
        if apply1.returncode != 0:
            fail(f"--apply failed:\n{apply1.stdout}")
        stamp = latest_backup(root)
        if not stamp:
            fail("no backup snapshot to roll back from")

        rollback = sh(root, f"/opt/bin/vward-beta-cutover.sh --rollback {stamp}")
        if rollback.returncode != 0:
            fail(f"--rollback failed:\n{rollback.stdout}")
        time.sleep(1)

        after_crontab = crontab_of(root)
        if after_crontab != before_crontab:
            fail(f"crontab after rollback differs from before cutover:\n--- before\n{before_crontab}\n--- after\n{after_crontab}")
        after_names = sorted(p.name for p in (root / "opt/bin").glob("*.sh"))
        if after_names != before_names:
            fail(f"program files after rollback differ: {after_names} != {before_names}")
        for s in ("S91adaptive-live", "S92crond-supervisor", "S93keenetic-apps"):
            if not (root / f"opt/etc/init.d/{s}").exists():
                fail(f"{s} was not restored by rollback")

        after_daemons = ps_matches(BETA_DAEMON_RE)
        if len(after_daemons) < 3:
            fail(f"beta daemons did not come back up after rollback: {after_daemons}")

        check = sh(root, "/opt/bin/vward-beta-cutover.sh --check")
        if "cutover already applied         : no" not in check.stdout:
            fail(f"--check should show no active cutover after rollback:\n{check.stdout}")
        print("ok - rollback restores crontab, init scripts, programs and daemons")
    finally:
        teardown(root)


def main():
    if os.geteuid() != 0:
        sys.exit("check-cutover-emulated: needs root (chroot, mknod, mount proc)")
    for tool in ("busybox", "jq", "openssl", "cc"):
        if not shutil.which(tool):
            sys.exit(f"check-cutover-emulated: {tool} is required")
    if subprocess.run(["git", "-C", str(REPO), "rev-parse", "-q", "--verify", "origin/beta"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        sys.exit("check-cutover-emulated: origin/beta is not available")

    work = Path(tempfile.mkdtemp(prefix="vward-cutover."))
    try:
        part1_apply_then_real_install(work)
        part2_rollback(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("CUTOVER_EMULATED=PASS")


if __name__ == "__main__":
    main()
