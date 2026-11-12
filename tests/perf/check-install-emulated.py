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
  3. two VPN connections, none connected or routed: the installer asks nothing,
     takes the first and says where the Panel changes it.
  4. --check changes nothing.
  5. KeeneticOS 4 is refused.
  6. KeeneticOS 5.0, AdGuard Home present, two VPN connections: the installer takes
     one by itself (routed, else connected, else the first); VWARD routes through it and «Реклама» stays on;
     AdGuard Home's own DNS server in Keenetic stays. After --uninstall the same router installs again.
  7. A reformatted USB drive (owner 12.11.2026): AdGuard Home is gone, Keenetic still asks
     192.0.2.1:65053 and has its own DNS off. --check says so and changes nothing; install takes both out
     (Keenetic answers DNS by itself again) before anything else.
  8. A router that lived before (owner 12.11.2026): lists of its own (YouTube, Discord), AdaptiveAuto with
     names routed into another VPN that is not connected, a subnet and a Smart DNS line. The installer
     takes the connected VPN, moves only AdaptiveAuto's route there and leaves everything else as it is.
  9. The old VPN tunnel (owner 12.11.2026): a VWARD engine tunnel (OpkgTun4) whose settings went with the
     USB drive still carries lists, AdaptiveAuto and a subnet; the installer names them. With a working VPN they all move there
     (a list already on it only loses the dead route); a list on the working VPN is not touched; a
     failed installation puts everything back. With nothing but the dead tunnel nothing moves and
     the installer says how to bring the lists back.

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
        if r.returncode != 0 or "[ PASS ] VWARD установлен" not in r.stdout or "VPN: Wireguard1 (из 2; сменить: Панель VWARD" not in r.stdout:
            fail(f"two VPNs: the first is taken without a question:\n{r.stdout}")
        if "Номер VPN" in r.stdout:
            fail(f"the installer must not ask for the VPN:\n{r.stdout}")
        print("ok - two VPN connections: the first is taken, no question")
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


def on_terminal(root, command, answers, timeout=600):
    """COMMAND in the chroot with a real terminal (/dev/tty) that types ANSWERS."""
    tty = root / "dev/tty"
    if not tty.exists():
        subprocess.run(["mknod", "-m", "666", str(tty), "c", "5", "0"], check=True)
    inner = f"env -i PATH={PATH_ENV} HOME=/root chroot {root} /bin/sh -c '{command}'"
    return subprocess.run(["script", "-qec", inner, "/dev/null"], input=answers, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=timeout)


def part6_choice_agh_reinstall(work, release):
    root = build(work, "clean6", release)
    try:
        (root / "emu/version").write_text("5.0.8\n")
        ifs = json.loads(read(root / "emu/rci-interface.json"))
        ifs["OpenVPN0"] = {"type": "OpenVPN", "security-level": "public", "description": "Work", "connected": "yes"}
        (root / "emu/rci-interface.json").write_text(json.dumps(ifs))
        curl = root / "opt/bin/curl"
        curl.write_text(read(curl).replace("s/Wireguard1/nwg1/", "s/Wireguard1/nwg1/;s/OpenVPN0/ovpn_br0/"))
        (root / "sys/class/net/ovpn_br0").mkdir()
        (root / "sys/class/net/ovpn_br0/tun_flags").write_text("0x1002\n")
        (root / "opt/etc/AdGuardHome").mkdir(parents=True)
        (root / "opt/etc/AdGuardHome/AdGuardHome.yaml").write_text("http:\n  address: 127.0.0.1:3000\n")
        (root / "emu/running-config").write_text(read(root / "emu/running-config") + "ip name-server 192.0.2.1:65053\n")
        # Enter: install (no question about packages or the VPN).
        r = on_terminal(root, "sh /emu/repo/install.sh", "\n")
        out = r.stdout.replace("\r", "")
        m = re.search(r"VPN: (\S+) \(из 2;", out)
        if r.returncode != 0 or "[ PASS ] VWARD установлен" not in out or not m or "Номер VPN" in out:
            fail(f"install on a terminal, the VPN taken without a question, failed:\n{out}")
        chosen = m.group(1)
        for text in ("KeeneticOS 5.0.8", "AdGuard Home найден", f"VPN: {chosen}", f"список AdaptiveAuto идёт через {chosen}"):
            if text not in out:
                fail(f"install output lacks {text!r}:\n{out}")
        if read(root / "opt/etc/vward/device.conf").strip() != f"VWARD_TUNNEL_INTERFACE={chosen}":
            fail(f"device.conf: {read(root / 'opt/etc/vward/device.conf')!r}")
        if f"dns-proxy route object-group AdaptiveAuto {chosen} auto" not in read(root / "emu/ndmc-changes.log"):
            fail(f"AdaptiveAuto must go through the chosen VPN:\n{read(root / 'emu/ndmc-changes.log')}")
        if (root / "opt/etc/vward/components/ads-privacy-guard.disabled").exists():
            fail("with AdGuard Home «Реклама» stays on")
        if "name-server" in read(root / "emu/ndmc-changes.log"):
            fail(f"AdGuard Home is here: its DNS server in Keenetic stays:\n{read(root / 'emu/ndmc-changes.log')}")
        un = sh(root, "sh /emu/repo/install.sh --uninstall --yes")
        if un.returncode != 0 or "[ PASS ] VWARD удалён" not in un.stdout:
            fail(f"uninstall failed:\n{un.stdout}")
        if not (root / "opt/etc/init.d/S90crond").exists():
            fail("uninstall must keep S90crond: cron is shared and still running")
        again = on_terminal(root, "sh /emu/repo/install.sh", "\n")
        out = again.stdout.replace("\r", "")
        if again.returncode != 0 or "[ PASS ] VWARD установлен" not in out or read(root / "opt/share/vward/VERSION").strip() != VERSION:
            fail(f"a reinstall after uninstall failed:\n{out}")
        if not re.search(r"^\d+$", read(root / "opt/var/run/vward-console-lighttpd.pid").strip()):
            fail("the Panel is not running after the reinstall")
        print("ok - KeeneticOS 5.0, AdGuard Home, the connected VPN taken; uninstall and install again")
    finally:
        teardown(root)


def part7_reformatted_drive(work, release):
    root = build(work, "clean7", release)
    try:
        (root / "emu/running-config").write_text(read(root / "emu/running-config") + "ip name-server 192.0.2.1:65053\nopkg dns-override\n")
        chk = sh(root, "sh /emu/repo/install.sh --check")
        if "остались настройки DNS от AdGuard Home" not in chk.stdout or "192.0.2.1:65053" not in chk.stdout or read(root / "emu/ndmc-changes.log").strip():
            fail(f"--check must name the DNS left by AdGuard Home and change nothing:\n{chk.stdout}")
        r = sh(root, "sh /emu/repo/install.sh --yes")
        if r.returncode != 0 or "[ PASS ] VWARD установлен" not in r.stdout:
            fail(f"install failed:\n{r.stdout}")
        changes = read(root / "emu/ndmc-changes.log").splitlines()
        want = ["no ip name-server 192.0.2.1:65053", "no opkg dns-override", "system configuration save",
                "object-group fqdn AdaptiveAuto", "dns-proxy route object-group AdaptiveAuto Wireguard1 auto", "system configuration save"]
        if changes != want:
            fail(f"RED: the DNS of a gone AdGuard Home must go first: {changes}")
        if "DNS отвечает сам Keenetic" not in r.stdout:
            fail(f"install must say DNS is Keenetic's own again:\n{r.stdout}")
        print("ok - reformatted drive: the DNS left by AdGuard Home is taken out, Keenetic answers")
    finally:
        teardown(root)


LIVED_CONFIG = """system
    hostname Keenetic
!
interface Wireguard1
    description "My VPN"
!
interface OpenVPN0
    description "Old VPN"
!
object-group fqdn YouTube
    include youtube.com
    include googlevideo.com
!
object-group fqdn Discord
    include discord.com
!
object-group fqdn AdaptiveAuto
    include chatgpt.com
    include old.example.com
!
dns-proxy
    route object-group YouTube Wireguard1 auto
    route object-group Discord Wireguard1 auto
    route object-group AdaptiveAuto OpenVPN0 auto
    https upstream https://dns.example/dns-query domain chatgpt.com
!
ip route 8.8.8.0 255.255.255.0 Wireguard1 auto
"""


def part8_lived_router(work, release):
    root = build(work, "clean8", release)
    try:
        ifs = json.loads(read(root / "emu/rci-interface.json"))
        ifs["OpenVPN0"] = {"type": "OpenVPN", "security-level": "public", "description": "Old VPN", "connected": "no", "link": "down"}
        (root / "emu/rci-interface.json").write_text(json.dumps(ifs))
        curl = root / "opt/bin/curl"
        curl.write_text(read(curl).replace("s/Wireguard1/nwg1/", "s/Wireguard1/nwg1/;s/OpenVPN0/ovpn_br0/"))
        (root / "sys/class/net/ovpn_br0").mkdir()
        (root / "sys/class/net/ovpn_br0/tun_flags").write_text("0x1002\n")
        (root / "emu/running-config").write_text(LIVED_CONFIG)
        r = sh(root, "sh /emu/repo/install.sh --yes")
        out = r.stdout
        if r.returncode != 0 or "[ PASS ] VWARD установлен" not in out:
            fail(f"install on a lived router failed:\n{out}")
        for text in ("VPN: Wireguard1", "список AdaptiveAuto уже есть", "маршрут списка AdaptiveAuto перенесён: OpenVPN0 → Wireguard1"):
            if text not in out:
                fail(f"install output lacks {text!r}:\n{out}")
        changes = read(root / "emu/ndmc-changes.log").splitlines()
        want = ["dns-proxy route object-group AdaptiveAuto Wireguard1 auto", "dns-proxy no route object-group AdaptiveAuto OpenVPN0",
                "system configuration save"]
        if changes != want:
            fail(f"RED: only AdaptiveAuto's route moves on a lived router, nothing else is touched: {changes}")
        if read(root / "opt/etc/vward/device.conf").strip() != "VWARD_TUNNEL_INTERFACE=Wireguard1":
            fail(f"device.conf: {read(root / 'opt/etc/vward/device.conf')!r}")
        print("ok - lived router: own lists, subnet and Smart DNS kept; AdaptiveAuto moved to the VPN autopick checks through")
    finally:
        teardown(root)
    # The same router, the installation failing after the move (cron cannot be written): AdaptiveAuto's
    # old route comes back as it was.
    root = build(work, "clean8b", release)
    try:
        ifs = json.loads(read(root / "emu/rci-interface.json"))
        ifs["OpenVPN0"] = {"type": "OpenVPN", "security-level": "public", "description": "Old VPN", "connected": "no", "link": "down"}
        (root / "emu/rci-interface.json").write_text(json.dumps(ifs))
        curl = root / "opt/bin/curl"
        curl.write_text(read(curl).replace("s/Wireguard1/nwg1/", "s/Wireguard1/nwg1/;s/OpenVPN0/ovpn_br0/"))
        (root / "sys/class/net/ovpn_br0").mkdir()
        (root / "sys/class/net/ovpn_br0/tun_flags").write_text("0x1002\n")
        (root / "emu/running-config").write_text(LIVED_CONFIG)
        cdir = root / "opt/var/spool/cron/crontabs"
        shutil.rmtree(cdir, ignore_errors=True); cdir.parent.mkdir(parents=True, exist_ok=True); cdir.write_text("")
        r = sh(root, "sh /emu/repo/install.sh --yes")
        if r.returncode == 0:
            fail(f"the installation had to fail on cron:\n{r.stdout}")
        changes = read(root / "emu/ndmc-changes.log").splitlines()
        want = ["dns-proxy route object-group AdaptiveAuto Wireguard1 auto", "dns-proxy no route object-group AdaptiveAuto OpenVPN0",
                "system configuration save", "dns-proxy no route object-group AdaptiveAuto Wireguard1",
                "dns-proxy route object-group AdaptiveAuto OpenVPN0 auto", "system configuration save"]
        if changes != want:
            fail(f"a failed installation must put AdaptiveAuto's old route back: {changes}\n{r.stdout}")
        print("ok - lived router, failed installation: AdaptiveAuto's old route is back")
    finally:
        teardown(root)


OLD_TUNNEL_CONFIG = """system
    hostname Keenetic
!
interface Wireguard1
    description "My VPN"
!
interface OpkgTun4
    description "VLESS Germany"
!
object-group fqdn YouTube
    include youtube.com
!
object-group fqdn Discord
    include discord.com
!
object-group fqdn Telegram
    include telegram.org
!
object-group fqdn AdaptiveAuto
    include chatgpt.com
!
dns-proxy
    route object-group YouTube OpkgTun4 auto
    route object-group Discord OpkgTun4 auto
    route object-group Discord Wireguard1 auto
    route object-group Telegram Wireguard1 auto
    route object-group AdaptiveAuto OpkgTun4 auto
!
ip route 91.108.4.0 255.255.252.0 OpkgTun4 auto
"""


def old_tunnel_router(work, name, wireguard=True):
    root = build(work, name, OLD_TUNNEL_RELEASE[0])
    ifs = json.loads(read(root / "emu/rci-interface.json"))
    ifs["OpkgTun4"] = {"type": "OpkgTun", "security-level": "public", "description": "VLESS Germany", "connected": "no", "link": "down"}
    if not wireguard:
        ifs.pop("Wireguard1")
    (root / "emu/rci-interface.json").write_text(json.dumps(ifs))
    curl = root / "opt/bin/curl"
    curl.write_text(read(curl).replace("s/Wireguard1/nwg1/", "s/Wireguard1/nwg1/;s/OpkgTun4/opkgtun4/"))
    (root / "sys/class/net/opkgtun4").mkdir()
    (root / "sys/class/net/opkgtun4/tun_flags").write_text("0x1001\n")
    cfg = OLD_TUNNEL_CONFIG if wireguard else OLD_TUNNEL_CONFIG.replace("interface Wireguard1\n    description \"My VPN\"\n!\n", "").replace(
        "    route object-group Discord Wireguard1 auto\n", "").replace("    route object-group Telegram Wireguard1 auto\n", "")
    (root / "emu/running-config").write_text(cfg)
    return root


OLD_TUNNEL_RELEASE = [None]


def part9_old_tunnel(work, release):
    OLD_TUNNEL_RELEASE[0] = release
    root = old_tunnel_router(work, "clean9")
    try:
        r = sh(root, "sh /emu/repo/install.sh --yes")
        out = r.stdout
        if r.returncode != 0 or "[ PASS ] VWARD установлен" not in out or "VPN: Wireguard1" not in out or \
                "туннели VWARD без настроек" not in out or "OpkgTun4: списков доменов 2, подсетей 1" not in out or \
                "перенесено в Wireguard1: списков доменов 2, подсетей 1 (было через OpkgTun4" not in out:
            fail(f"install with an old tunnel failed:\n{out}")
        changes = read(root / "emu/ndmc-changes.log").splitlines()
        want = ["dns-proxy route object-group AdaptiveAuto Wireguard1 auto", "dns-proxy no route object-group AdaptiveAuto OpkgTun4",
                "dns-proxy route object-group YouTube Wireguard1 auto", "dns-proxy no route object-group YouTube OpkgTun4",
                "dns-proxy no route object-group Discord OpkgTun4",
                "ip route 91.108.4.0 255.255.252.0 Wireguard1 auto", "no ip route 91.108.4.0 255.255.252.0 OpkgTun4",
                "system configuration save"]
        if changes != want:
            fail(f"RED: everything on the old tunnel moves to the working VPN, nothing else: {changes}\n{out}")
        print("ok - old tunnel: its lists, AdaptiveAuto and subnet moved to the working VPN; Telegram untouched")
    finally:
        teardown(root)
    root = old_tunnel_router(work, "clean9b")
    try:
        cdir = root / "opt/var/spool/cron/crontabs"
        shutil.rmtree(cdir, ignore_errors=True); cdir.parent.mkdir(parents=True, exist_ok=True); cdir.write_text("")
        r = sh(root, "sh /emu/repo/install.sh --yes")
        changes = read(root / "emu/ndmc-changes.log").splitlines()
        back = changes[changes.index("system configuration save") + 1:]
        want = ["dns-proxy no route object-group AdaptiveAuto Wireguard1",
                "dns-proxy no route object-group YouTube Wireguard1", "no ip route 91.108.4.0 255.255.252.0 Wireguard1",
                "dns-proxy route object-group YouTube OpkgTun4 auto", "dns-proxy route object-group Discord OpkgTun4 auto",
                "ip route 91.108.4.0 255.255.252.0 OpkgTun4 auto", "dns-proxy route object-group AdaptiveAuto OpkgTun4 auto",
                "system configuration save"]
        if r.returncode == 0 or back != want:
            fail(f"a failed installation must put the old tunnel's routes back: {back}\n{r.stdout}")
        print("ok - old tunnel, failed installation: every route is back on it")
    finally:
        teardown(root)
    root = old_tunnel_router(work, "clean9c", wireguard=False)
    try:
        r = sh(root, "sh /emu/repo/install.sh --yes")
        out = r.stdout
        if r.returncode != 0 or "[ PASS ] VWARD установлен" not in out or "туннель VWARD без настроек" not in out or "переедет туда само" not in out:
            fail(f"only the old tunnel: install, say how the lists come back:\n{out}")
        if any("no route" in c or c.startswith("ip route") for c in read(root / "emu/ndmc-changes.log").splitlines()):
            fail(f"only the old tunnel: nothing may move:\n{read(root / 'emu/ndmc-changes.log')}")
        print("ok - only the old tunnel: nothing moves, the installer says how the lists come back")
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
        part6_choice_agh_reinstall(work, release)
        part7_reformatted_drive(work, release)
        part8_lived_router(work, release)
        part9_old_tunnel(work, release)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("INSTALL_EMULATED=PASS")


if __name__ == "__main__":
    main()
