#!/usr/bin/env python3
"""install.sh, end to end, on an emulated clean router.

The router (tests/perf/emulator/build-rootfs-clean.sh) has Entware on a USB
drive and one VPN connection in Keenetic, nothing else.  GitHub is a copy of
this repository with a release signed by a one-time key.

  1. install --yes: missing packages come from opkg, the signed package is
     installed by the Update Engine, AdaptiveAuto is created and routed to the
     VPN, cron has VWARD's jobs, the Panel answers; "Реклама" is off without
     AdGuard Home.  A second run says VWARD is already installed.  --uninstall
     removes the program and its cron lines, keeps the settings in a backup
     and takes AdaptiveAuto out of Keenetic again.
  2. a package that does not match its signature: nothing is left behind.
  3. two VPN connections and --yes: the installer asks for a choice and
     changes nothing.
  4. --check changes nothing.

Needs root (chroot, mknod, mount) and busybox, jq, openssl, cc.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUILD = REPO / "tests/perf/emulator/build-rootfs-clean.sh"
PATH_ENV = "/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
VERSION = (REPO / "VERSION").read_text().strip()


def fail(message):
    raise SystemExit(f"INSTALL_EMULATED=FAIL: {message}")


def sh(root, command, timeout=300):
    return subprocess.run(["env", "-i", f"PATH={PATH_ENV}", "HOME=/root",
                           "chroot", str(root), "/bin/sh", "-c", command],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)


def read(path):
    return path.read_text() if path.exists() else ""


def sign_release(work):
    """A release of this tree signed with a one-time key, as the pipeline signs it."""
    priv, pub = work / "private.pem", work / "public.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(priv)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["openssl", "pkey", "-in", str(priv), "-pubout", "-out", str(pub)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    release = work / "release"
    env = os.environ | {"VWARD_SIGNING_KEY_FILE": str(priv), "VWARD_REHEARSAL_PUBLIC_KEY": str(pub)}
    r = subprocess.run([str(REPO / "scripts/prepare-dev-release.sh"), str(release), "2026099901", "0.1.9-beta"],
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        fail(f"prepare-dev-release.sh failed:\n{r.stdout}")
    return pub, release / "update-manifest.json", release / f"candidate/vward-{VERSION}.tar.gz"


def build(work, name, release, tamper=False):
    root = work / name
    subprocess.run([str(BUILD), str(root)], check=True, stdout=subprocess.DEVNULL)
    pub, manifest, package = release
    repo = root / "emu/repo"
    shutil.copy(pub, repo / "config/updater/update-public.pem")
    (repo / "updates/dev/packages").mkdir(parents=True, exist_ok=True)
    shutil.copy(manifest, repo / "updates/dev/update-manifest.json")
    target = repo / f"updates/dev/packages/vward-{VERSION}.tar.gz"
    shutil.copy(package, target)
    if tamper:
        with open(target, "r+b") as f:
            f.seek(100)
            b = f.read(1)
            f.seek(100)
            f.write(bytes([b[0] ^ 1]))
    # SHA256SUMS as the repository would have it with this key.
    lines = []
    for line in read(repo / "SHA256SUMS").splitlines():
        digest, path = line.split(None, 1)
        p = repo / path.strip()
        if p.is_file():
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.strip()}")
    (repo / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    subprocess.run(["mount", "-t", "proc", "proc", str(root / "proc")], check=True)
    subprocess.run(["mount", "--bind", str(root / "opt"), str(root / "opt")], check=True)
    return root


def teardown(root):
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            if Path(os.readlink(entry / "root")) == root:
                os.kill(int(entry.name), 9)
        except OSError:
            continue
    time.sleep(0.3)
    subprocess.run(["umount", str(root / "opt")])
    subprocess.run(["umount", str(root / "proc")])


def crontab(root):
    return read(root / "opt/var/spool/cron/crontabs/root")


def untouched(root, label):
    for p in ("opt/share/vward", "opt/etc/vward", "opt/lib/vward", "opt/var/lib/vward", "opt/bin/vward-route-engine.sh",
              "opt/etc/init.d/S91vward-route-engine"):
        if (root / p).exists():
            fail(f"{label}: {p} was left behind")
    if "vward" in crontab(root).lower():
        fail(f"{label}: cron still has VWARD lines:\n{crontab(root)}")
    changes = read(root / "emu/ndmc-changes.log")
    if "AdaptiveAuto" in changes.replace("no object-group fqdn AdaptiveAuto", "").replace("dns-proxy no route object-group AdaptiveAuto", ""):
        if "no object-group fqdn AdaptiveAuto" not in changes:
            fail(f"{label}: AdaptiveAuto was created and not removed:\n{changes}")


def part1_install_uninstall(work, release):
    root = build(work, "clean1", release)
    try:
        r = sh(root, "sh /emu/repo/install.sh --yes")
        out = r.stdout
        if r.returncode != 0 or "[ PASS ] VWARD установлен" not in out:
            fail(f"install failed:\n{out}")
        for text in ("KeeneticOS 5.1.6", "VPN: Wireguard1", "AdGuard Home не найден", "подпись и все файлы проверены",
                     "список AdaptiveAuto идёт через Wireguard1", "Панель VWARD отвечает", "Панель VWARD: http://192.0.2.1:8088"):
            if text not in out:
                fail(f"install output lacks {text!r}:\n{out}")
        installed = read(root / "emu/opkg-installed.log").split()
        for p in ("jq", "openssl-util", "tcpdump", "lighttpd", "lighttpd-mod-cgi", "lighttpd-mod-setenv", "ca-bundle"):
            if p not in installed:
                fail(f"opkg did not install {p}: {installed}")
        if "curl" in installed or "cron" in installed:
            fail(f"packages already there were installed again: {installed}")
        if read(root / "opt/share/vward/VERSION").strip() != VERSION:
            fail("VERSION is not the signed release")
        committed = read(root / "opt/var/lib/vward/updater/committed.state")
        if f"installed_version={VERSION}" not in committed or "last_sequence=2026099901" not in committed:
            fail(f"the Update Engine did not commit the install:\n{committed}")
        dconf = root / "opt/etc/vward/device.conf"
        if read(dconf).strip() != "VWARD_TUNNEL_INTERFACE=Wireguard1" or oct(dconf.stat().st_mode & 0o777) != "0o600":
            fail(f"device.conf: {read(dconf)!r} {oct(dconf.stat().st_mode)}")
        if not (root / "opt/etc/vward/components/ads-privacy-guard.disabled").exists():
            fail("Ads must be off without AdGuard Home")
        changes = read(root / "emu/ndmc-changes.log").splitlines()
        want = ["object-group fqdn AdaptiveAuto", "dns-proxy route object-group AdaptiveAuto Wireguard1 auto", "system configuration save"]
        if changes != want:
            fail(f"Keenetic changes: {changes}")
        cron = crontab(root)
        for marker in ("vward-route-engine", "S92vward-runtime", "vward-wan-guard.sh", "vward-tunnel-health.sh", "VWARD_SMART_UPDATER"):
            if marker not in cron:
                fail(f"cron lacks {marker}:\n{cron}")
        if not re.search(r"^\d+$", read(root / "opt/var/run/vward-console-lighttpd.pid").strip()):
            fail("the Panel is not running")

        again = sh(root, "sh /emu/repo/install.sh --yes")
        if again.returncode != 0 or "VWARD уже установлен" not in again.stdout:
            fail(f"a second run must only say it is installed:\n{again.stdout}")
        direct = sh(root, "/opt/share/vward/updater/current/vward-update.sh --install")
        if direct.returncode == 0:
            fail("the engine must refuse --install over an installation")

        (root / "emu/ndmc-changes.log").write_text("")
        un = sh(root, "sh /emu/repo/install.sh --uninstall --yes")
        if un.returncode != 0 or "[ PASS ] VWARD удалён" not in un.stdout:
            fail(f"uninstall failed:\n{un.stdout}")
        for p in ("opt/share/vward", "opt/etc/vward", "opt/bin/vward-route-engine.sh", "opt/etc/init.d/S93vward-console",
                  "opt/share/vward/console/www/cgi-bin/api.cgi"):
            if (root / p).exists():
                fail(f"uninstall left {p}")
        if "vward" in crontab(root).lower():
            fail(f"uninstall left cron lines:\n{crontab(root)}")
        backups = list((root / "opt/var/backups/vward").glob("uninstall-*/etc/device.conf"))
        if not backups:
            fail("settings were not kept in a backup")
        changes = read(root / "emu/ndmc-changes.log").splitlines()
        if changes != ["dns-proxy no route object-group AdaptiveAuto Wireguard1", "no object-group fqdn AdaptiveAuto", "system configuration save"]:
            fail(f"uninstall Keenetic changes: {changes}")
        if not (root / "opt/bin/jq").exists():
            fail("Entware packages must stay")
        print("ok - clean router: install, second run, uninstall")
    finally:
        teardown(root)


def part2_bad_package(work, release):
    root = build(work, "clean2", release, tamper=True)
    try:
        before = crontab(root)
        r = sh(root, "sh /emu/repo/install.sh --yes")
        if r.returncode == 0 or "сборка не установилась" not in r.stdout or "изменения возвращены" not in r.stdout:
            fail(f"a tampered package must stop the install:\n{r.stdout}")
        untouched(root, "tampered package")
        if crontab(root) != before:
            fail("cron changed")
        if read(root / "emu/ndmc-changes.log"):
            fail(f"Keenetic was changed: {read(root / 'emu/ndmc-changes.log')}")
        print("ok - a package that does not match its signature leaves nothing behind")
    finally:
        teardown(root)


def part3_two_vpns(work, release):
    root = build(work, "clean3", release)
    try:
        ifs = json.loads(read(root / "emu/rci-interface.json"))
        ifs["OpenVPN0"] = {"type": "OpenVPN", "security-level": "public", "description": "Work"}
        (root / "emu/rci-interface.json").write_text(json.dumps(ifs))
        curl = root / "opt/bin/curl"
        curl.write_text(read(curl).replace("s/Wireguard1/nwg1/", "s/Wireguard1/nwg1/;s/OpenVPN0/ovpn_br0/"))
        (root / "sys/class/net/ovpn_br0").mkdir()
        (root / "sys/class/net/ovpn_br0/tun_flags").write_text("0x1002\n")
        r = sh(root, "sh /emu/repo/install.sh --yes")
        if r.returncode == 0 or "VPN-подключений: 2" not in r.stdout or "выберите" not in r.stdout:
            fail(f"two VPNs with --yes must ask for a choice:\n{r.stdout}")
        if "OpenVPN0 «Work» - openvpn" not in r.stdout:
            fail(f"the VPN list must show each connection:\n{r.stdout}")
        untouched(root, "two VPNs")
        print("ok - two VPN connections: the owner chooses, nothing changes before")
    finally:
        teardown(root)


def part4_check(work, release):
    root = build(work, "clean4", release)
    try:
        r = sh(root, "sh /emu/repo/install.sh --check")
        if r.returncode != 0 or "роутер готов к установке" not in r.stdout or "Нужно поставить" not in r.stdout:
            fail(f"--check:\n{r.stdout}")
        untouched(root, "--check")
        if read(root / "emu/opkg-installed.log"):
            fail("--check installed packages")
        print("ok - --check changes nothing")
    finally:
        teardown(root)


def part5_old_firmware(work, release):
    root = build(work, "clean5", release)
    try:
        (root / "emu/version").write_text("4.3.2\n")
        r = sh(root, "sh /emu/repo/install.sh --check")
        if r.returncode == 0 or "KeeneticOS 4.3.2: VWARD работает с KeeneticOS 5.0" not in r.stdout:
            fail(f"KeeneticOS 4 must be refused:\n{r.stdout}")
        untouched(root, "old firmware")
        print("ok - KeeneticOS 4 is refused and nothing changes")
    finally:
        teardown(root)


def main():
    if os.geteuid() != 0:
        sys.exit("check-install-emulated: needs root (chroot, mknod, mount)")
    for tool in ("busybox", "jq", "openssl", "cc"):
        if not shutil.which(tool):
            sys.exit(f"check-install-emulated: {tool} is required")
    work = Path(tempfile.mkdtemp(prefix="vward-install."))
    try:
        release = sign_release(work)
        part1_install_uninstall(work, release)
        part2_bad_package(work, release)
        part3_two_vpns(work, release)
        part4_check(work, release)
        part5_old_firmware(work, release)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("INSTALL_EMULATED=PASS")


if __name__ == "__main__":
    main()
