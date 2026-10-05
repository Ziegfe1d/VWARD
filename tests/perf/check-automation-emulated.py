#!/usr/bin/env python3
"""VWARD's automation, scenario by scenario, on the router emulator.

Each scenario starts a fresh emulated router and runs its crontab minute by minute, as cron
does (every job due in that minute, at the same time; the clock moves a minute a round).
Faults are switched on and off at given minutes, and the test checks what the automation
did and when, from the router's own log of changes (ndmc), the guards' state and the files:

  vpn-blip         the VPN silent for one minute: nothing is switched off
  vpn-down         the VPN silent for 18 minutes: the lists go direct within 2-4 minutes,
                   a recovery test every 5 minutes (not more), back on the VPN once it answers
  vpn-spare        two tunnels, the main one dies: VWARD's routes move to the second one
                   (nothing goes direct) and come back when the main one answers again
  vpn-spare-stay   the same with «Возвращать на основной» off: the routes stay on the second
  guard-off        «Агент VPN» off: a dead VPN is left alone; on again: it acts
  wan-down         no internet for 12 minutes: the internet guard renews and restarts the
                   provider's connection within its limits, the VPN guard does not touch the
                   tunnel (the VPN is not the culprit), all calm once the internet is back
  agh-loop         AdGuard Home restarting every minute: out of the DNS chain at the second
                   crash, back in once it runs steadily, no flapping
  agh-one-crash    one crash, then it answers: stays in the chain
  agh-update       an update VWARD makes: out before it, its restarts are no crash, back at once
  agh-silent       AdGuard Home silent: out within 3 minutes, back after 3 answers
  agh-blip         AdGuard Home silent for one minute: stays in the chain
  agh-and-wan      AdGuard Home silent and no internet: the chain is left as it is
  engine-kill      the route engine killed: running again the next minute, also when killed
                   every minute, without piling up processes
  agh-starter      AdGuard Home dead: started, then the pauses grow (120, 240, 480, 600 s),
                   not started twice while running; a crash at once after start is noticed
  both-dead        two tunnels, both die: the lists go direct; both back: all as before
  vpn-flap         the VPN flickers every other minute: not switched on and off each time
  reboot-failopen  the router reboots while the guard holds the VPN down: it remembers
  vpn-and-agh      VPN and AdGuard Home fail together: each guard does its part
  sentinel         the real-time watcher's actions: «chain-fail» takes a silent AdGuard Home
                   out at once, «dns-fail» starts a dead one, both through the same gates
  vward-off        «Отключить VWARD»: routes into the tunnels and AdGuard Home's DNS line out of
                   Keenetic, VWARD silent for minutes and after a reboot, the Panel's changes
                   refused; «Включить»: everything back exactly, VWARD running again
  vward-off-nodns  the same with no other DNS answering: AdGuard Home's line stays
Needs root (chroot, mount).
  check-automation-emulated.py [--scenario NAME ...] [--report FILE]
"""
import argparse
import collections
import datetime
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("chaos", REPO / "tests/perf/check-chaos-emulated.py")
chaos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chaos)

NS = "ip name-server 192.0.2.1:65053"


# ---------------------------------------------------------------- the emulated router
class Router:
    def __init__(self, tmp, spare=False):
        self.root = chaos.build(tmp)
        self.minute = 0
        self.log = []          # (minute, ndmc change)
        self.errors = []       # (minute, job, line)
        self.hangs = []
        self._seen = 0
        self.patch(spare)

    def sh(self, cmd, timeout=60):
        return chaos.sh(self.root, cmd, timeout=timeout)

    def patch(self, spare):
        r = self.root
        # A silent VPN: only nwg1 (the second tunnel, nwg2, keeps answering).
        wg = r / "opt/bin/wg"
        wg.write_text(wg.read_text().replace("[ ! -e /emu/fault-tunnel ] ||", 'case "$*" in *nwg1*) ;; *) false ;; esac && [ -e /emu/fault-tunnel ] &&', 1))
        # Keenetic's configuration follows the changes VWARD makes: dns-proxy routes and
        # interfaces switched off and on (fake ndmc), and the tunnels' state in RCI (fake curl).
        nd = r / "bin/ndmc"
        nd.write_text(nd.read_text().replace("    show*) : ;;", r"""    'dns-proxy route object-group '*|'dns-proxy no route object-group '*)
        printf '%s\n' "$cmd" >> /emu/ndmc-changes.log
        set -- $cmd; if [ "$2" = no ]; then g=$5 t=$6; else g=$4 t=$5; fi
        awk -v g="$g" -v t="$t" -v add="$([ "$2" = no ] || echo "$cmd")" '
            /^dns-proxy$/ {print; ctx = 1; if (add != "") {sub(/^dns-proxy /, "", add); print "    " add}; next}
            /^!/ {ctx = 0}
            ctx && $1 == "route" && $2 == "object-group" && $3 == g && $4 == t {next}
            {print}' /emu/running-config > /emu/rc.n && cat /emu/rc.n > /emu/running-config ;;
    'ip route '*) printf '%s\n' "$cmd" >> /emu/ndmc-changes.log; grep -qxF "$cmd" /emu/running-config || echo "$cmd" >> /emu/running-config ;;
    'no ip route '*) printf '%s\n' "$cmd" >> /emu/ndmc-changes.log; k=${cmd#no }
        awk -v k="$k" 'index($0, k " ") != 1 && $0 != k' /emu/running-config > /emu/rc.n && cat /emu/rc.n > /emu/running-config ;;
    'system configuration save') : ;;
    'interface '*' down') printf '%s\n' "$cmd" >> /emu/ndmc-changes.log; n=${cmd#interface }; n=${n% down}; echo "$n" >> /emu/iface-down
        d=$(echo "$n" | sed 's/^Wireguard/nwg/'); [ ! -d "/sys/class/net/$d" ] || { echo 0 > "/sys/class/net/$d/carrier"; echo down > "/sys/class/net/$d/operstate"; } ;;
    'interface '*' up') printf '%s\n' "$cmd" >> /emu/ndmc-changes.log; n=${cmd#interface }; n=${n% up}; grep -vx "$n" /emu/iface-down > /emu/iface-down.n; cat /emu/iface-down.n > /emu/iface-down
        d=$(echo "$n" | sed 's/^Wireguard/nwg/'); [ ! -d "/sys/class/net/$d" ] || { echo 1 > "/sys/class/net/$d/carrier"; echo up > "/sys/class/net/$d/operstate"; } ;;
    show*) : ;;""", 1))
        (r / "emu/iface-down").write_text("")
        curl = r / "opt/bin/curl"
        curl.write_text(curl.read_text()
                        .replace("*/rci/show/interface) cat /emu/rci-interface.json ;;",
                                 "*/rci/show/interface) jq --rawfile d /emu/iface-down 'reduce ($d | split(\"\\n\")[] | select(length > 0)) as $n (.; if .[$n] then .[$n].state = \"down\" else . end)' /emu/rci-interface.json ;;", 1)
                        .replace("s/Wireguard1/nwg1/;", "s/Wireguard1/nwg1/;s/Wireguard2/nwg2/;", 1)
                        .replace("*/rci/show/interface\\?name=*) cat /emu/rci-isp.json ;;",
                                 "*/rci/show/interface\\?name=*) n=${url##*name=}; if grep -qx \"$n\" /emu/iface-down; then jq '.state = \"down\" | .link = \"down\" | .connected = \"no\"' /emu/rci-isp.json; else cat /emu/rci-isp.json; fi ;;", 1))
        # AdGuard Home's start script: records each start; it comes up unless told not to.
        init = r / "opt/etc/init.d/S99adguardhome"
        init.write_text("#!/bin/sh\n[ \"$1\" = start ] || exit 0\necho \"$(date +%s)\" >> /emu/agh-starts\n"
                        "[ -e /emu/agh-start-fails ] || echo $((4000 + $(wc -l < /emu/agh-starts))) > /emu/agh-pid\nexit 0\n")
        init.chmod(0o755)
        # The second tunnel can die too (/emu/fault-tunnel2).
        curl = r / "opt/bin/curl"
        curl.write_text(curl.read_text().replace('{ [ "$iface" = nwg1 ] && [ -e /emu/fault-tunnel ]; }',
                                                 '{ [ "$iface" = nwg1 ] && [ -e /emu/fault-tunnel ]; } || { [ "$iface" = nwg2 ] && [ -e /emu/fault-tunnel2 ]; }', 1))
        ping = r / "opt/bin/ping"
        ping.write_text(ping.read_text().replace('case " $* " in', 'case " $* " in *" nwg2 "*) [ ! -e /emu/fault-tunnel2 ] || { printf \'1 packets transmitted, 0 packets received, 100%% packet loss\\n\'; exit 1; } ;;', 1))
        wg = r / "opt/bin/wg"
        wg.write_text("#!/bin/sh\ncase \"$*\" in *nwg2*latest-handshakes*) [ ! -e /emu/fault-tunnel2 ] || { printf 'peerkey=\\t%s\\n' \"$(( $(date +%s) - 900 ))\"; exit 0; } ;; esac\n" + wg.read_text().split("\n", 1)[1])
        if spare:
            ifs = json.loads((r / "emu/rci-interface.json").read_text())
            ifs["Wireguard2"] = {"type": "Wireguard", "security-level": "public", "description": "spare"}
            (r / "emu/rci-interface.json").write_text(json.dumps(ifs))
            rc = r / "emu/running-config"
            rc.write_text(rc.read_text() + "interface Wireguard2\n    description spare\n!\n")
            for f, v in (("carrier", "1"), ("operstate", "up")):
                (r / "sys/class/net/nwg2").mkdir(parents=True, exist_ok=True)
                (r / f"sys/class/net/nwg2/{f}").write_text(v + "\n")
            (r / "sys/class/net/nwg2/wireguard").mkdir(exist_ok=True)

    # cron: the crontab's jobs due this minute, all at once.
    def due(self, field, value):
        for part in field.split(","):
            if part == "*" or (part.startswith("*/") and value % int(part[2:]) == 0) or (part.isdigit() and int(part) == value):
                return True
        return False

    def tick(self, faults=()):
        self.minute += 1
        chaos.advance(self.root)
        chaos.set_faults(self.root, list(faults), self.minute)
        off = int((self.root / "emu/clock-offset").read_text())
        t = datetime.datetime.fromtimestamp(time.time() + off, datetime.timezone.utc)
        jobs = []
        for line in (self.root / "opt/var/spool/cron/crontabs/root").read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            f = line.split(None, 5)
            if len(f) < 6:
                continue
            if all(self.due(a, b) for a, b in zip(f[:5], (t.minute, t.hour, t.day, t.month, t.isoweekday() % 7))):
                jobs.append(f[5])
        procs = [(j, chaos.sh(self.root, j, background=True)) for j in jobs]
        for j, p in procs:
            try:
                p.communicate(timeout=58)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL); p.communicate()
                self.hangs.append((self.minute, j[:60]))
        for out in (self.root / "tmp").glob("*.cron.out"):
            for line in out.read_text(errors="replace").splitlines():
                if chaos.SHELL_ERRORS.search(line) and not chaos.SHELL_OK.search(line):
                    self.errors.append((self.minute, out.name, line.strip()[:160]))
        changes = chaos.ndmc_changes(self.root)
        self.log += [(self.minute, c) for c in changes[self._seen:]]
        self._seen = len(changes)

    def sync(self):
        # Changes made outside cron (a command by hand) belong to this minute.
        changes = chaos.ndmc_changes(self.root)
        self.log += [(self.minute, c) for c in changes[self._seen:]]
        self._seen = len(changes)

    def run(self, minutes, faults=()):
        for _ in range(minutes):
            self.tick(faults)

    def cmds(self, text, since=0, until=10 ** 9):
        return [m for m, c in self.log if text in c and since <= m <= until]

    def guard(self):
        return chaos.guard_state(self.root)

    def device(self, key):
        for line in (self.root / "opt/etc/vward/device.conf").read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
        return ""

    def routes(self, group="vpn-sites"):
        return [l.split()[3] for l in (self.root / "emu/running-config").read_text().splitlines()
                if l.strip().startswith(f"route object-group {group} ")]

    def chain_in(self):
        return NS in (self.root / "emu/running-config").read_text().splitlines()

    def close(self):
        self.sh("/opt/etc/init.d/S91vward-route-engine stop", timeout=30)
        self.sh("/opt/etc/init.d/S92vward-runtime stop", timeout=30)
        for m in ("opt", "proc"):
            subprocess.run(["umount", "-l", str(self.root / m)], stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- the scenarios
def expect(cond, what, out):
    out.append(("PASS" if cond else "FAIL", what))


def s_vpn_blip(r, out):
    r.run(3); r.run(1, ["tunnel"]); r.run(8)
    expect(not r.cmds("interface Wireguard1 down"), "a one-minute VPN silence switches nothing off", out)


def s_vpn_down(r, out):
    r.run(2); r.run(18, ["tunnel"]); r.run(14)
    down = r.cmds("interface Wireguard1 down")
    expect(bool(down) and 4 <= down[0] <= 6, f"the dead VPN is taken out within 2-4 minutes (at minute {down[:1]}, fault from 3)", out)
    ups = r.cmds("interface Wireguard1 up", 3, 20)
    expect(len(ups) <= 18 // 5 + 1, f"recovery tests during the fault every 5 minutes at most ({len(ups)} in 18 min: {ups})", out)
    g = r.guard()
    expect(g.get("FAILOPEN_ACTIVE") == "0", f"back on the VPN after it answers again (guard {g.get('LAST_ACTION')})", out)
    expect("Wireguard1" not in (r.root / "emu/iface-down").read_text().split(), "the tunnel is up at the end", out)
    expect(not r.cmds("interface ISP"), "the provider's connection is not touched", out)
    last_up = [m for m in r.cmds("interface Wireguard1 up") if m > 20]
    expect(bool(last_up) and last_up[0] <= 28, f"switched back within 8 minutes after the VPN answers (at {last_up[:1]})", out)


def s_vpn_spare(r, out, stay=False):
    if stay:
        (r.root / "opt/etc/vward/tunnel-return.disabled").write_text("off\n")
    r.run(4); r.run(14, ["tunnel"])
    on2 = [m for m, c in r.log if "route object-group vpn-sites Wireguard2" in c and " no " not in c]
    expect(bool(on2) and on2[0] <= 9, f"VWARD's routes move to the second tunnel (at {on2[:1]}, fault from 5)", out)
    expect(not r.cmds("interface Wireguard1 down"), "nothing goes direct while another tunnel answers", out)
    expect(r.device("VWARD_TUNNEL_INTERFACE") == "Wireguard2", f"the second tunnel is VWARD's now ({r.device('VWARD_TUNNEL_INTERFACE')})", out)
    r.run(14)
    if stay:
        expect(r.device("VWARD_TUNNEL_INTERFACE") == "Wireguard2" and r.routes() == ["Wireguard2"],
               f"«Возвращать на основной» off: the routes stay on the second tunnel ({r.routes()})", out)
    else:
        expect(r.device("VWARD_TUNNEL_INTERFACE") == "Wireguard1" and r.routes() == ["Wireguard1"],
               f"the routes come back to the main tunnel once it answers ({r.device('VWARD_TUNNEL_INTERFACE')}, {r.routes()})", out)
    moves = [c for m, c in r.log if "route object-group vpn-sites" in c and " no " not in c]
    expect(len(moves) <= 2, f"no back and forth ({len(moves)} moves)", out)


def s_guard_off(r, out):
    flag = r.root / "opt/etc/vward/tunnel-guard.disabled"
    flag.write_text("off\n")
    r.run(2); r.run(8, ["tunnel"])
    expect(not r.cmds("interface Wireguard1 down"), "«Агент VPN» off: a dead VPN is left alone", out)
    flag.unlink()
    r.run(6, ["tunnel"])
    on = r.cmds("interface Wireguard1 down", 11)
    expect(bool(on) and on[0] <= 14, f"on again: it acts within 3 minutes (at {on[:1]}, on from 11)", out)
    r.run(10)
    expect(r.guard().get("FAILOPEN_ACTIVE") == "0", "and brings the VPN back afterwards", out)


def s_wan_down(r, out):
    r.run(2); r.run(12, ["wan"]); r.run(10)
    bounces = r.cmds("interface ISP down")
    expect(len(bounces) <= 2, f"the provider's connection restarted at most twice an hour ({bounces})", out)
    expect(bool(r.cmds("interface ISP")), "the internet guard does try (renew or restart)", out)
    expect(not r.cmds("interface Wireguard1 down"), "the VPN guard does not take the tunnel down for a missing internet", out)
    expect(not r.cmds("interface ISP", 18), "all calm once the internet is back (nothing after minute 17)", out)
    expect(r.chain_in(), "AdGuard Home stays in the DNS chain (the provider is silent too)", out)


def s_agh_loop(r, out):
    r.run(2); r.run(12, ["agh-loop"])
    outs = r.cmds("no " + NS)
    expect(bool(outs) and outs[0] <= 4, f"restarting in a loop: out of the DNS chain at the second crash (at {outs[:1]}, from 3)", out)
    r.run(14)
    expect(r.chain_in(), "back in the chain once it runs steadily", out)
    back = [m for m in r.cmds(NS) if m > 14 and not any(c.startswith("no ") for mm, c in r.log if mm == m and NS in c)]
    expect(len(r.cmds("no " + NS)) <= 1, f"no flapping ({len(r.cmds('no ' + NS))} times out)", out)


def s_agh_one_crash(r, out):
    r.run(3)
    (r.root / "emu/agh-pid").write_text("4999\n")
    r.run(12)
    expect(not r.cmds("no " + NS), "one crash (it answers again) is no loop: stays in the chain", out)


def s_agh_update(r, out):
    g = "/opt/bin/vward-ads-privacy-dns-guard.sh"
    r.run(3)
    r.sh(f"{g} planned 300")
    expect(not r.chain_in(), "an update VWARD makes: out of the chain before it starts", out)
    for pid in (4500, 4501):
        (r.root / "emu/agh-pid").write_text(f"{pid}\n")
        r.run(1)
    expect(not r.chain_in(), "its restarts during the update change nothing", out)
    r.sh(f"{g} planned-done")
    expect(r.chain_in(), "the update is over and it answers: back at once (no 3-minute wait)", out)
    done_at = r.minute
    r.run(6)
    expect(r.chain_in() and not r.cmds("no " + NS, done_at + 1),
           "and stays: the update's restarts are not counted as crashes later", out)


def s_agh_silent(r, out):
    r.run(2); r.run(8, ["agh"])
    outs = r.cmds("no " + NS)
    expect(bool(outs) and outs[0] <= 6, f"silent: out within 3 minutes (at {outs[:1]}, from 3)", out)
    r.run(8)
    expect(r.chain_in(), "back after 3 answers in a row", out)


def s_agh_blip(r, out):
    r.run(3); r.run(1, ["agh"]); r.run(6)
    expect(not r.cmds("no " + NS), "a one-minute silence leaves AdGuard Home in the chain", out)


def s_agh_and_wan(r, out):
    r.run(2); r.run(8, ["agh", "wan"]); r.run(4)
    expect(not r.cmds("no " + NS) and r.chain_in(), "no internet at all: the chain is left as it is", out)


def s_engine_kill(r, out):
    def pids():
        rc, o, _ = r.sh("ps w 2>/dev/null | grep '[v]ward-route-engine.sh' | grep -v grep | wc -l")
        return int((o or "0").strip() or 0)

    def kill():
        r.sh("for p in $(ps w | grep '[v]ward-route-engine.sh' | awk '{print $1}'); do kill -9 $p; done; true")
    r.run(2)
    expect(pids() >= 1, "the route engine runs", out)
    kill(); r.run(1)
    expect(pids() >= 1, "killed: running again the next minute", out)
    for _ in range(6):
        kill(); r.run(1)
    n = pids()
    expect(1 <= n <= 3, f"killed every minute for 6 minutes: running, no pile-up ({n} processes)", out)


def s_agh_starter(r, out):
    lib = "/opt/lib/vward/vward-runtime-admission.sh"
    (r.root / "emu/agh-pid").write_text("")
    # vward_agh_ensure at given uptimes (the clock it reads), AdGuard Home dead unless started.
    def ensure(up):
        (r.root / "emu/uptime").write_text(f"{up}.00 1.00\n")
        rc, o, _ = r.sh(f"VWARD_UPTIME_FILE=/emu/uptime . {lib}; vward_agh_ensure /opt/etc/init.d/S99adguardhome; echo rc=$?")
        return o.strip().splitlines()[-1] if o.strip() else ""
    (r.root / "emu/agh-start-fails").write_text("1\n")
    seen = {up: ensure(up) for up in (100, 150, 221, 300, 462, 700, 943, 1500, 1544)}
    starts = [u for u, x in seen.items() if x == "rc=10"]
    expect(starts == [100, 221, 462, 943, 1544],
           f"dead AdGuard Home: started, then after 120, 240, 480, 600 s ({starts})", out)
    (r.root / "emu/agh-start-fails").unlink()
    ensure(2200)
    expect(ensure(2210) == "rc=0" and (r.root / "emu/agh-pid").read_text().strip() != "",
           "running: not started again", out)
    n = len((r.root / "emu/agh-starts").read_text().splitlines())
    expect(n == 6, f"one start each time, no double starts ({n})", out)


def s_sentinel(r, out):
    r.run(2)
    (r.root / "emu/fault-agh").write_text("1\n")
    rc, o, _ = r.sh("/opt/bin/vward-sentinel-act.sh chain-fail; echo rc=$?")
    expect(not r.chain_in(), f"«chain-fail» with AdGuard Home silent: out of the chain at once ({o.strip()[-40:]})", out)
    (r.root / "emu/fault-agh").unlink()
    r.run(5)
    expect(r.chain_in(), "and back once it answers", out)
    (r.root / "emu/agh-pid").write_text("")
    rc, o, _ = r.sh("/opt/bin/vward-sentinel-act.sh dns-fail; echo rc=$?")
    starts = (r.root / "emu/agh-starts").read_text().splitlines() if (r.root / "emu/agh-starts").exists() else []
    expect(len(starts) == 1, f"«dns-fail» with AdGuard Home dead: started ({len(starts)} starts)", out)
    r.sh("/opt/bin/vward-sentinel-act.sh dns-fail")
    starts = (r.root / "emu/agh-starts").read_text().splitlines()
    expect(len(starts) == 1, "a second «dns-fail» while it runs: no second start", out)


def s_both_dead(r, out):
    r.run(3)
    (r.root / "emu/fault-tunnel2").write_text("1\n")
    r.run(10, ["tunnel"])
    down = r.cmds("interface Wireguard1 down")
    expect(bool(down) and down[0] <= 9, f"both tunnels dead: the lists go direct (at {down[:1]})", out)
    (r.root / "emu/fault-tunnel2").unlink()
    r.run(14)
    g = r.guard()
    expect(g.get("FAILOPEN_ACTIVE") == "0" and r.routes() == ["Wireguard1"],
           f"both back: on the VPN again, routes on the main tunnel ({g.get('LAST_ACTION')}, {r.routes()})", out)


def s_vpn_flap(r, out):
    r.run(2)
    for i in range(10):
        r.run(1, ["tunnel"] if i % 2 == 0 else [])
    r.run(8)
    downs = r.cmds("interface Wireguard1 down")
    expect(len(downs) <= 1, f"a VPN that flickers every other minute is not switched on and off ({downs})", out)
    expect(r.guard().get("FAILOPEN_ACTIVE") == "0", "and is on at the end", out)


def s_reboot_failopen(r, out):
    r.run(2); r.run(6, ["tunnel"])
    expect(r.guard().get("FAILOPEN_ACTIVE") == "1", "the dead VPN is taken out", out)
    # A reboot: the programs and RAM are gone, the USB stick stays; Keenetic starts the tunnel
    # from its saved configuration (the guard does not save its «down»).
    r.close()
    for p in (r.root / "tmp").iterdir():
        shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    (r.root / "emu/iface-down").write_text("")
    for f, v in (("carrier", "1"), ("operstate", "up")):
        (r.root / f"sys/class/net/nwg1/{f}").write_text(v + "\n")
    subprocess.run(["mount", "-t", "proc", "proc", str(r.root / "proc")], check=True)
    subprocess.run(["mount", "--bind", str(r.root / "opt"), str(r.root / "opt")], check=True)
    r.run(6, ["tunnel"])
    expect(r.guard().get("FAILOPEN_ACTIVE") == "1" and "Wireguard1" in (r.root / "emu/iface-down").read_text().split(),
           "after the reboot, still dead: taken out again (the guard remembered)", out)
    r.run(10)
    expect(r.guard().get("FAILOPEN_ACTIVE") == "0" and "Wireguard1" not in (r.root / "emu/iface-down").read_text().split(),
           "and back on once it answers", out)


def s_vpn_and_agh(r, out):
    r.run(2); r.run(10, ["tunnel", "agh"])
    expect(bool(r.cmds("interface Wireguard1 down")) and bool(r.cmds("no " + NS)),
           "VPN and AdGuard Home down together: each guard does its part", out)
    r.run(14)
    expect(r.guard().get("FAILOPEN_ACTIVE") == "0" and r.chain_in(), "both back afterwards", out)


def s_vward_off(r, out, nodns=False):
    rc = r.root / "emu/running-config"
    rc.write_text(rc.read_text() + "ip route 203.0.113.64 255.255.255.192 Wireguard1 auto\nip route 192.0.2.128 255.255.255.128 ISP auto\n")
    r.run(2)
    before = rc.read_text()
    if nodns:
        (r.root / "emu/fault-wan").write_text("")
    _, o, _ = r.sh("VWARD_OFF_BY=test /opt/bin/vward-off.sh; echo rc=$?", timeout=120)
    r.sync()
    if nodns:
        (r.root / "emu/fault-wan").unlink()
    lines = rc.read_text().splitlines()
    tun = [l for l in lines if "Wireguard1" in l and ("route" in l)]
    expect("rc=0" in o and not tun, "off: no route into the tunnel is left in Keenetic", out)
    expect("ip route 192.0.2.128 255.255.255.128 ISP auto" in lines, "a route to the provider is not VWARD's to take", out)
    if nodns:
        expect(r.chain_in() and "dns_kept=1" in o, "no other DNS answers: AdGuard Home's line stays", out)
    else:
        expect(not r.chain_in() and "dns=1" in o, "AdGuard Home's DNS line is out (the provider's DNS answers)", out)
    expect((r.root / "opt/etc/vward/components/vward.off").exists(), "the switch is remembered on the USB drive", out)
    _, o, _ = r.sh("/opt/bin/vward-console-config.sh tunnel-guard 0")
    expect("error=vward_off" in o, "the Panel's changes are refused while off", out)
    m0 = r.minute
    r.run(5, ["tunnel"])
    expect(not [c for m, c in r.log if m > m0], "off: VWARD changes nothing for 5 minutes, a dead VPN included", out)
    _, alive, _ = r.sh("p=$(cat /opt/var/run/vward/route-engine.pid 2>/dev/null); [ -n \"$p\" ] && kill -0 $p 2>/dev/null && echo alive || echo gone")
    expect("gone" in alive, "the route engine does not run while off", out)
    # A reboot while off: still off afterwards.
    r.close()
    for p in (r.root / "tmp").iterdir():
        shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    subprocess.run(["mount", "-t", "proc", "proc", str(r.root / "proc")], check=True)
    subprocess.run(["mount", "--bind", str(r.root / "opt"), str(r.root / "opt")], check=True)
    m0 = r.minute
    r.run(3)
    expect(not [c for m, c in r.log if m > m0] and not [l for l in rc.read_text().splitlines() if "Wireguard1" in l and "route" in l],
           "after a reboot VWARD stays off and puts nothing back", out)
    _, o, _ = r.sh("VWARD_OFF_BY=test /opt/bin/vward-off.sh on; echo rc=$?", timeout=120)
    after = rc.read_text()
    expect("rc=0" in o and sorted(after.splitlines()) == sorted(before.splitlines()), "on: Keenetic's configuration exactly as before", out)
    expect(not (r.root / "opt/etc/vward/components/vward.off").exists(), "on: the switch is gone", out)
    r.run(2)
    _, o, _ = r.sh("p=$(cat /opt/var/run/vward/route-engine.pid 2>/dev/null); [ -n \"$p\" ] && kill -0 $p 2>/dev/null && echo alive || echo gone")
    expect("alive" in o, "on: the route engine runs again", out)
    _, o, _ = r.sh("/opt/bin/vward-off.sh status")
    expect("state=on" in o, "status: on", out)


SCENARIOS = {
    "vpn-blip": (s_vpn_blip, False), "vpn-down": (s_vpn_down, False), "vpn-spare": (s_vpn_spare, True),
    "vpn-spare-stay": (lambda r, o: s_vpn_spare(r, o, stay=True), True), "guard-off": (s_guard_off, False),
    "wan-down": (s_wan_down, False), "agh-loop": (s_agh_loop, False), "agh-silent": (s_agh_silent, False),
    "agh-blip": (s_agh_blip, False), "agh-one-crash": (s_agh_one_crash, False), "agh-update": (s_agh_update, False), "agh-and-wan": (s_agh_and_wan, False), "engine-kill": (s_engine_kill, False),
    "agh-starter": (s_agh_starter, False), "sentinel": (s_sentinel, False),
    "both-dead": (s_both_dead, True), "vpn-flap": (s_vpn_flap, False), "reboot-failopen": (s_reboot_failopen, False),
    "vpn-and-agh": (s_vpn_and_agh, False),
    "vward-off": (s_vward_off, False), "vward-off-nodns": (lambda r, o: s_vward_off(r, o, nodns=True), False),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", action="append", choices=sorted(SCENARIOS))
    ap.add_argument("--report")
    args = ap.parse_args()
    if os.geteuid() != 0:
        print("AUTOMATION_EMULATED=SKIP (needs root)")
        return 0
    results, failed = {}, 0
    for name in args.scenario or list(SCENARIOS):
        fn, spare = SCENARIOS[name]
        tmp = Path(tempfile.mkdtemp(prefix=f"vward-auto-{name}."))
        r, out, t0 = None, [], time.time()
        try:
            r = Router(tmp, spare=spare)
            fn(r, out)
            # SSH to the router: no scenario touches the home network's interface, its addresses
            # or the SSH server.
            for m, c in r.log:
                if "Bridge" in c or " 192.168." in c or " 10." in c or "dropbear" in c or "ssh" in c.lower():
                    out.append(("FAIL", f"minute {m}: a change that could cut SSH: {c}"))
            for m, job, line in r.errors[:5]:
                out.append(("FAIL", f"shell error at minute {m} in {job}: {line}"))
            for m, job in r.hangs[:3]:
                out.append(("FAIL", f"a job hung at minute {m}: {job}"))
        except Exception as e:  # a broken scenario is a failure, not a crash of the run
            out.append(("FAIL", f"scenario crashed: {e!r}"))
        finally:
            if r is not None:
                results[name] = {"checks": out, "log": r.log, "seconds": round(time.time() - t0)}
                r.close()
            shutil.rmtree(tmp, ignore_errors=True)
        bad = [w for s, w in out if s == "FAIL"]
        failed += bool(bad)
        print(f"{'FAIL' if bad else 'PASS'} {name} ({results.get(name, {}).get('seconds', '?')} s)")
        for s, w in out:
            print(f"    {s} {w}")
        if bad and name in results:
            print("    router changes:", [f"{m}:{c}" for m, c in results[name]["log"]][:30])
    if args.report:
        Path(args.report).write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print("AUTOMATION_EMULATED=" + ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
