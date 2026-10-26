#!/usr/bin/env python3
"""Shrink guard of the IP categories (fix.34.1, r2). 25.10 14:18 one pass of
«vward-policy-sync.sh --reconcile» removed 442 of 508 routes («SYNC active=3 wanted=66
removed=442»): Instagram and the sites behind Cloudflare went direct. Now a pass removes at
most shrink_max_routes (50) or shrink_max_pct (20 %) of the owned routes; more is held, owned,
written to shrink.pending and the log, removed by «--confirm-shrink» only. A busy router removes
nothing, an incomplete running configuration stops the pass. Smart DNS held address by address
with 9 active categories removes only the subnets around the held blocks. BusyBox ash when there."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYNC = (ROOT / "components/policy-sync/scripts/vward-policy-sync.sh").read_text()
SH = ["busybox", "sh"] if shutil.which("busybox") else ["sh"]


def fail(message: str) -> None:
    raise SystemExit(f"POLICY_SHRINK_GUARD=FAIL: {message}")


def func(name: str) -> str:
    m = re.search(rf"^{name}\(\)\n\{{\n.*?^\}}\n", SYNC, re.S | re.M)
    if not m:
        fail(f"missing shell function {name}")
    return m.group(0)


FUNCS = "".join(func(n) for n in ("prefix_mask", "route_line", "lists_conf", "smartdns_split", "run_partial", "reconcile_routes"))
# The 25.10 picture: 9 categories, 508 routes; 3 of them (66 routes) left.
CATS = {f"cat{i}": [f"45.{i}.{j}.0/24" for j in range(n)] for i, n in enumerate((22, 22, 22, 100, 100, 100, 50, 50, 42))}
ALL = [c for nets in CATS.values() for c in nets]


def route(c: str) -> str:
    return f"ip route {c.split('/')[0]} 255.255.255.0 OpkgTun4 auto"


with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "catalog").mkdir()
    (t / "work").mkdir()
    for c, nets in CATS.items():
        (t / f"catalog/{c}.cidr").write_text("".join(n + "\n" for n in nets))
    RUNNING = "object-group fqdn domain-list1\n    include example.com\n!\n" + "".join(route(c) + "\n" for c in ALL)
    (t / "running").write_text(RUNNING)

    def run(cats: list[str], conf: str = "", busy: bool = False, confirmed: bool = False,
            blocks: str = "") -> tuple[str, list[str], list[str]]:
        (t / "cats").write_text("".join(c + "\n" for c in cats))
        (t / "lists.conf").write_text(conf)
        (t / "work/smartdns-blocks").write_text(blocks)
        (t / "ndm.log").write_text("")
        script = FUNCS + f"""
log() {{ echo "$*" >> "{t}/log"; }}
ndm() {{ echo "$*" >> "{t}/ndm.log"; }}
vward_busy() {{ {'return 0' if busy else 'return 1'}; }}
WORK="{t}/work"; CATALOG="{t}/catalog"; OWNED="{t}/owned"; OWNED_DEVICE="{t}/owned-device"; ACTIVE="{t}/active"
LISTS_CONF="{t}/lists.conf"; SHRINK_PENDING="{t}/shrink.pending"; LAST_GOOD="{t}/last-good"
SMARTDNS_HOLD_PREFIX=24; SHRINK_CONFIRMED={1 if confirmed else 0}; RT=OpkgTun4; WG=opkgtun4
reconcile_routes "{t}/running" "{t}/cats"
"""
        r = subprocess.run(SH + ["-c", script], text=True, capture_output=True, timeout=120)
        if r.stderr:
            fail(f"reconcile_routes: {r.stderr}")
        return r.stdout, (t / "ndm.log").read_text().splitlines(), (t / "owned").read_text().split()

    def owned(cs: list[str]) -> None:
        (t / "owned").write_text("".join(c + "\n" for c in sorted(cs)))

    # 1. The incident: 442 of 508 at once - nothing removed, all kept, the reason noted.
    owned(ALL)
    out, ndm, own = run(["cat0", "cat1", "cat2"])
    if any(c.startswith("no ip route") for c in ndm) or "REMOVED=0" not in out or len(own) != 508:
        fail(f"442 of 508 routes must not be removed in one pass: {out}")
    pend = (t / "shrink.pending").read_text()
    if "reason=limit" not in pend or "remove=442" not in pend or "SHRINK_HOLD reason=limit remove=442 owned=508" not in (t / "log").read_text():
        fail(f"the held removal goes to shrink.pending and the log: {pend!r}")
    if (t / "last-good").exists():
        fail("a held pass is not the last good set")

    # 2. Checked again: still too many - still held. Confirmed: removed, the note cleared.
    out, ndm, own = run(["cat0", "cat1", "cat2"])
    if "REMOVED=0" not in out or len(own) != 508:
        fail("the next pass holds again")
    out, ndm, own = run(["cat0", "cat1", "cat2"], confirmed=True)
    if sum(c.startswith("no ip route") for c in ndm) != 442 or len(own) != 66 or (t / "shrink.pending").exists():
        fail(f"--confirm-shrink removes the held routes: {out}")
    # A confirmation covers the held set only: a bigger one is held again.
    owned(ALL)
    run(["cat0", "cat1", "cat2"])
    out, ndm, own = run(["cat0"], confirmed=True)
    if "REMOVED=0" not in out or len(own) != 508:
        fail("a confirmation must not remove more than was held")

    # 3. A small change goes through: 22 of 508 (one service off).
    owned(ALL)
    out, ndm, own = run([c for c in CATS if c != "cat0"])
    if "REMOVED=22" not in out or len(own) != 486 or (t / "shrink.pending").exists():
        fail(f"22 of 508 routes are removed as before: {out}")
    if (t / "last-good").read_text().split() != own:
        fail("a clean pass is the last good set")

    # 4. The guard off: as before fix.34.1. A busy router: nothing removed.
    owned(ALL)
    out, ndm, own = run(["cat0", "cat1", "cat2"], conf="shrink_guard=0\n")
    if "REMOVED=442" not in out:
        fail("shrink_guard=0 turns the guard off")
    owned(ALL)
    out, ndm, own = run([c for c in CATS if c != "cat0"], busy=True)
    if "REMOVED=0" not in out or "SHRINK_HELD=busy" not in out or len(own) != 508:
        fail("a busy router removes nothing")

    # 5. Smart DNS by address, 9 active categories: only the subnets holding a held block go.
    owned(ALL)
    blocks = "45.3.7.0/24|ai1.example|cat3\n45.8.1.0/24|ai2.example|cat8\n"
    out, ndm, own = run(list(CATS), blocks=blocks)
    removed = [c for c in ndm if c.startswith("no ip route")]
    if "ACTIVE_CATEGORIES=9" not in out or "REMOVED=2" not in out or len(removed) != 2:
        fail(f"only the 2 subnets with a Smart DNS address leave the tunnel: {out}")
    if "45.3.7.0/24" in own or "45.8.1.0/24" in own or len(own) != 506:
        fail("the held blocks are not owned routes")

    # 6. An incomplete running configuration: the pass stops before any change.
    owned(ALL)
    part = subprocess.run(SH + ["-c", FUNCS + f'OWNED="{t}/owned"; RT=OpkgTun4\n'
                                f'run_partial "$1" && echo PARTIAL || echo FULL', "x", str(t / "running")],
                          text=True, capture_output=True).stdout.split()
    (t / "cut1").write_text("".join(route(c) + "\n" for c in ALL))                    # no FQDN group
    (t / "cut2").write_text("object-group fqdn domain-list1\n    include example.com\n!\n")  # none of ours
    for name in ("cut1", "cut2"):
        part += subprocess.run(SH + ["-c", FUNCS + f'OWNED="{t}/owned"; RT=OpkgTun4\n'
                                     f'run_partial "$1" && echo PARTIAL || echo FULL', "x", str(t / name)],
                               text=True, capture_output=True).stdout.split()
    if part != ["FULL", "PARTIAL", "PARTIAL"]:
        fail(f"incomplete running configuration not found: {part}")

main = SYNC[SYNC.index('echo "SUBNET_SYNC_VERSION=$VERSION"'):]
i, j = main.find('if run_partial "$RUN"; then'), main.find('reconcile_routes "$RUN" "$CATS"')
if i < 0 or j < i or "exit 0" not in main[i:main.find("fi\n", i)]:
    fail("an incomplete running configuration must stop the pass before reconcile_routes")
for mode in ("--confirm-shrink", "--restore-last-good"):
    if mode not in main:
        fail(f"mode {mode} missing")
print("POLICY_SHRINK_GUARD=PASS")
