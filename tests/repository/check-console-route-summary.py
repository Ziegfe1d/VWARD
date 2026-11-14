#!/usr/bin/env python3
"""One summary of the routes (owner 13.11.2026: one value - one place).

The Overview's «Маршруты» card counted only the IP categories' subnets («0 подсетей · 0
IP-категорий» beside 21 lists, 418 domains and 1 388 subnets of the tunnel), the «Маршруты» page
counted its lists itself, a tunnel's page its subnets: three answers to «what goes through VPN».
routeSummary() is the one place: the page, both cards and the tunnel's page show its numbers.
  * the summary counts lists, domains, the tunnels' subnets (the real count, not the 300 sent);
  * no other place counts subnets of a tunnel or the lists through VPN itself;
  * the «Маршруты» card shows lists, domains and subnets; a tunnel's «Маршруты» only with two and
    more tunnels (owner 13.11.2026).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")


def fail(m):
    raise SystemExit(f"CONSOLE_ROUTE_SUMMARY=FAIL: {m}")


def cut(start):
    a = JS.index(start)
    return JS[a:JS.index("\n}\n", a) + 2]


if "function routeSummary() {" not in JS:
    fail("RED: no one summary of the routes")
fn = cut("function routeSummary() {")
# The summary on a router's answer: two tunnels, the API sent 300 of 1 388 subnets.
if shutil.which("node"):
    prog = ("const num = v => (v === '' || v == null || isNaN(+v)) ? null : +v, viaIs = (l, v) => l.via === v, compOn = id => id !== 'policy-sync';"
            "const S = {route: {ip: {categories: 0, active_count: 0, managed_routes: 0}}, services: {enabled: [{group: 'svc1'}]}, lists: {"
            "lists: [{name: 'l1', count: 400, via: 'vpn', route: 'OpkgTun0'}, {name: 'l2', count: 18, via: 'bypass', route: ''},"
            " {name: 'svc1', count: 50, via: 'vpn', route: 'OpkgTun0'}, {name: 'l3', count: 0, via: 'vpn', route: 'OpkgTun1', auto: {at: 'x'}}],"
            "subnet_counts: {OpkgTun0: 1388}, subnets: {OpkgTun0: new Array(300).fill('x'), OpkgTun1: ['a', 'b']}}};"
            "const svcOf = g => (S.services.enabled || []).find(e => e.group === g);\n" + fn +
            "\nconst r = routeSummary(); console.log(JSON.stringify({lists: r.lists, domains: r.domains, vpn: r.vpnLists, bypass: r.bypassLists,"
            " auto: r.autoMoved, nets: r.nets, t0: r.netsOf('OpkgTun0'), t1: r.netsOf('OpkgTun1'), via0: r.listsOf('OpkgTun0').length, ip: r.ipOn}));"
            "S.lists = null; const e = routeSummary(); console.log(JSON.stringify([e.lists, e.domains, e.nets, e.netsOf('OpkgTun0')]));")
    out = subprocess.run(["node", "-e", prog], capture_output=True, text=True)
    lines = out.stdout.strip().splitlines()
    if len(lines) != 2:
        fail(f"the summary does not run: {out.stderr[-300:]}")
    want = {"lists": 3, "domains": 418, "vpn": 3, "bypass": 1, "auto": 1, "nets": 1390, "t0": 1388, "t1": 2, "via0": 2, "ip": False}
    if json.loads(lines[0]) != want:
        fail(f"the summary: {lines[0]}, want {want}")
    if json.loads(lines[1]) != [None, None, None, None]:
        fail(f"not loaded is unknown, never zero: {lines[1]}")
# No place counts it itself.
rest = JS.replace(fn, "")
for own in ("subnet_counts", "filter(l => viaIs(l, 'vpn')).length", "filter(l => viaIs(l, 'bypass')).length", "reduce((n, l) => n + (num(l.count) || 0), 0)"):
    if own in rest:
        fail(f"RED: a place counts the routes itself: {own!r}")
card = JS[JS.index("    case 'routes': {"):JS.index("    case 'ads':")]
for need in ("const rs = routeSummary(),", "plural(rs.lists, 'списке', 'списках', 'списках')", "plural(rs.domains, 'домен', 'домена', 'доменов')",
             "plural(rs.nets, 'подсеть', 'подсети', 'подсетей')"):
    if need not in card:
        fail(f"RED: the «Маршруты» card lacks {need!r}")
if "r.ip.managed_routes" in card or "r.ip && r.ip.managed_routes" in card:
    fail("RED: the «Маршруты» card counts the IP categories' subnets only")
tun = cut("function tunnelTrafficPanel(name) {")
if "if (((st().wg && st().wg.interfaces) || []).length < 2) return '';" not in tun or "routeSummary()" not in tun:
    fail("a tunnel's «Маршруты»: from the summary, only with two and more tunnels")
page = JS[JS.index("  routes() {"):JS.index("  },", JS.index("  routes() {"))]
if "routeSummary()" not in page or "['Подсети туннелей'" not in page or "!rs.ipOn ? 'выкл'" not in page:
    fail("the «Маршруты» page: the summary, the tunnels' subnets, «выкл» for IP categories switched off")
print("CONSOLE_ROUTE_SUMMARY=PASS")
