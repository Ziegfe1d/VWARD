#!/usr/bin/env python3
"""List domains are bound to AdGuard Home in Keenetic (route engine, agh_bind).

Keenetic routes a list by the addresses it resolved itself; it asked the provider's DNS while
the devices asked AdGuard Home, and Google answers each with other addresses (Viva 2026-10-13:
9 of 148 addresses of YouTube in the route; with «ip name-server <AdGuard Home> s.youtube.com»
8 of 8). On a name of a list:
  * its list domain (the longest it falls under, «*.» taken off) is bound once, to AdGuard
    Home's address from its yaml (bind host, else the router), and Keenetic's configuration is
    left to be saved within the hour;
  * another name under that domain asks Keenetic nothing;
  * nothing while AdGuard Home is out of Keenetic's DNS chain or AdGuard Home already sends the
    list domains to Keenetic (route-dns: a binding back would make a circle);
  * a domain bound by hand (Smart DNS) is left alone; a refused one is not asked again;
  * at most AGH_BIND_MAX domains (logged once);
  * at a start only the bindings Keenetic still has count, a refused one is tried again.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()


def fail(msg):
    print(f"AGH_BIND=FAIL: {msg}")
    sys.exit(1)


fns = ENGINE[ENGINE.index("valid_fqdn()\n"):ENGINE.index("restore_adaptive_from_persist()\n")] + \
    ENGINE[ENGINE.index("AGH_BIND=\"${VWARD_AGH_BINDINGS"):ENGINE.index("handle_host()\n")]
shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])

for shell in shells:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "bin").mkdir()
        (t / "bin/ndmc").write_text('#!/bin/sh\necho "$2" >> "$T/ndmc.log"\n'
                                    '[ ! -e "$T/refuse" ] || { echo "Command::Base error: refused"; exit 1; }\n')
        (t / "bin/ndmc").chmod(0o755)
        (t / "manual").write_text("youtube.com\ngooglevideo.com\n*.video.example.net\nsmart.example\nzone\n")
        (t / "adaptive").write_text("blocked.example\n")
        yaml = t / "AdGuardHome.yaml"
        yaml.write_text("http:\n  address: 0.0.0.0:3000\ndns:\n  bind_hosts:\n    - 192.0.2.1\n  port: 65053\n")
        rc = t / "rc"
        rc.write_text("ip name-server 192.0.2.1:65053\nip name-server 192.0.2.1:65053 smart.example\n")
        script = t / "run.sh"
        script.write_text(f"""STATE_DIR="{t}"; MANUAL="{t}/manual"; ADAPTIVE="{t}/adaptive"; EVENT_LOG="{t}/events"
VWARD_DNS_SERVER=192.0.2.1
vward_running_config() {{ cat "{rc}"; }}
{fns}
case "$1" in
    ns) agh_ns ;;
    bind) agh_bind "$2" ;;
    prune) agh_bind_prune ;;
esac
""")
        env = {"PATH": f"{t}/bin:/usr/bin:/bin", "T": str(t), "VWARD_ADGUARD_CONFIG": str(yaml),
               "VWARD_DNS_CHAIN_STATE": str(t / "chain"), "VWARD_AGH_BIND_MAX": "4",
               "VWARD_ROUTE_DNS_ENABLED": str(t / "route-dns.enabled"), "VWARD_AGH_BINDINGS": str(t / "agh-bindings.txt")}
        bindings, ndlog, dirty, events = t / "agh-bindings.txt", t / "ndmc.log", t / "keenetic-config.dirty", t / "events"

        def run(*args):
            r = subprocess.run([*shell, str(script), *args], env=env, capture_output=True, text=True, timeout=30)
            if r.returncode:
                fail(f"{shell[0]} {args}: rc={r.returncode} {r.stderr}")
            return r.stdout.strip()

        def asked():
            return ndlog.read_text().splitlines() if ndlog.exists() else []

        def lines():
            return bindings.read_text().splitlines() if bindings.exists() else []

        if run("ns") != "192.0.2.1:65053":
            fail(f"{shell[0]} AdGuard Home's address from its yaml: {run('ns')!r}")
        yaml.write_text("dns:\n  bind_hosts:\n    - 0.0.0.0\n  port: 65053\n")
        if run("ns") != "192.0.2.1:65053":
            fail(f"{shell[0]} bound to all addresses: the router's: {run('ns')!r}")
        yaml.write_text("dns:\n  bind_hosts:\n    - 192.0.2.1\n  port: 53\n")
        if run("ns") != "":
            fail(f"{shell[0]} AdGuard Home on port 53 is Keenetic's place: no binding")
        yaml.write_text("dns:\n  bind_hosts:\n    - 192.0.2.1\n  port: 65053\n")

        # Out of the chain: nothing; without its yaml: nothing.
        (t / "chain").mkdir()
        (t / "chain/state").write_text("out\n")
        run("bind", "rr1---sn-a.googlevideo.com")
        if asked() or lines():
            fail(f"{shell[0]} AdGuard Home out of the chain: a list domain bound to it: {asked()}")
        (t / "chain/state").write_text("in\n")
        # «Домены маршрутов через DNS Keenetic» on: AdGuard Home sends them to Keenetic already.
        (t / "route-dns.enabled").write_text("")
        run("bind", "rr1---sn-a.googlevideo.com")
        if asked() or lines():
            fail(f"{shell[0]} route-dns on: a binding back would make a circle: {asked()}")
        (t / "route-dns.enabled").unlink()

        run("bind", "rr1---sn-a.googlevideo.com")
        if asked() != ["ip name-server 192.0.2.1:65053 googlevideo.com"] or lines() != ["googlevideo.com 192.0.2.1:65053"]:
            fail(f"{shell[0]} the list domain of a video server bound once: {asked()} {lines()}")
        if not dirty.exists() or "|AGH_BIND|googlevideo.com|" not in events.read_text():
            fail(f"{shell[0]} the binding is left to the hourly save and logged")
        run("bind", "rr7---sn-b.googlevideo.com")
        run("bind", "googlevideo.com")
        if len(asked()) != 1:
            fail(f"{shell[0]} another name of a bound domain asks Keenetic: {asked()}")
        run("bind", "a.b.video.example.net")
        if asked()[-1] != "ip name-server 192.0.2.1:65053 video.example.net":
            fail(f"{shell[0]} «*.» list entries: the domain under it: {asked()}")
        run("bind", "unlisted.example.org")
        run("bind", "a.zone")
        if len(asked()) != 2:
            fail(f"{shell[0]} a name of no list or a whole zone bound: {asked()}")
        # Bound by hand (Smart DNS): left alone, not looked at again.
        run("bind", "api.smart.example")
        if len(asked()) != 2 or "smart.example ext" not in lines():
            fail(f"{shell[0]} a domain bound by hand is changed: {asked()} {lines()}")
        # Keenetic refuses: not asked again.
        (t / "refuse").write_text("")
        run("bind", "www.youtube.com")
        run("bind", "m.youtube.com")
        if asked().count("ip name-server 192.0.2.1:65053 youtube.com") != 1 or "youtube.com failed" not in lines():
            fail(f"{shell[0]} a refused domain is asked again: {asked()} {lines()}")
        (t / "refuse").unlink()
        # At most 4 lines here: the fifth domain waits, logged once.
        run("bind", "x.blocked.example")
        run("bind", "y.blocked.example")
        if any("blocked.example" in a for a in asked()) or events.read_text().count("AGH_BIND_FULL") != 1:
            fail(f"{shell[0]} the limit: {asked()} {events.read_text()}")

        # A start: Keenetic has googlevideo.com (saved) and smart.example; video.example.net was
        # not saved before a reboot, youtube.com was refused - both go, to be made again on use.
        rc.write_text("ip name-server 192.0.2.1:65053\nip name-server 192.0.2.1:65053 smart.example\n"
                      "ip name-server 192.0.2.1:65053 googlevideo.com\n")
        run("prune")
        if lines() != ["googlevideo.com 192.0.2.1:65053", "smart.example ext"]:
            fail(f"{shell[0]} after a start only what Keenetic has: {lines()}")
        run("bind", "www.youtube.com")
        if asked().count("ip name-server 192.0.2.1:65053 youtube.com") != 2:
            fail(f"{shell[0]} a refused domain is tried again after a start: {asked()}")

print("AGH_BIND=PASS")
