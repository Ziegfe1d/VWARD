#!/usr/bin/env python3
"""«Домены → Проверить адрес»: after the check the Panel offers every way a domain can go -
through VPN, through Smart DNS, directly, or blocked in AdGuard Home - marks the current one,
and a choice takes the steps it needs (Smart DNS and VPN exclude each other; directly takes
the domain out of VWARD's lists and excludes it from lists sent into a tunnel)."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()
API = (ROOT / "web/cgi-bin/api.cgi").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_SITE_DO=FAIL: {message}")


def piece(start, end):
    a = JS.index(start)
    return JS[a:JS.index(end, a)]


script = "\n".join([
    piece("const esc =", "\n"), piece("const btn =", "\n"), piece("function confirmBox(", "\nfunction resultBox"),
    piece("const hasDom", "async function siteCheck("),
]) + r"""
const ico = () => '', errText = x => x.error || 'ошибка', render = () => {};
let confirm = null, calls = [], S, RPROBE, CFG;
const cfgOk = () => true, cfgRoute = () => CFG, st = () => ({ wg: { interfaces: [{ name: 'Wireguard0' }] } }), prof = () => ({ tunnel_interface: 'Wireguard0' });
const apiPost = async (api, f) => { calls.push(api + ':' + (f.op === 'agh' ? 'agh ' + f.value + ' ' + f.kind : f.op + ' ' + (f.action || '') + (f.target && f.op === 'list-domain' ? ' ' + f.target : ''))); return { ok: true }; };
const load = async () => {};
const siteCheck = async d => { RPROBE = { value: d, x: RPROBE.x, b: RPROBE.b }; };
function setup(d, o) {
  CFG = { group: 'domain-list0', domains: o.mine ? [d] : [], force_vpn: [], adaptive: o.adaptive ? [d] : [] };
  S = { lists: { smartdns_domains: o.smart ? [o.smart] : ['claude.ai'], smartdns_sources: { adguard: ['claude.ai'] },
                 lists: [{ name: 'domain-list3', description: 'Google', domains: o.own ? [d] : ['google.com'] }] } };
  RPROBE = { value: d, x: { ok: true, type: 'domain', value: d, adaptive_auto: false, names: {},
                            routes: (o.routes || []).map(g => ({ group: g, interface: 'Wireguard0' })) },
             b: { ok: true, blocked: !!o.blocked, user_block: !!o.blocked } };
  calls = [];
}
(async () => {
  const out = {};
  setup('gemini.google.com', { mine: true, routes: ['domain-list0'] });
  out.html = siteDoText(RPROBE);
  await siteDo('smart', 'gemini.google.com'); out.smart = calls;
  setup('gemini.google.com', { smart: 'gemini.google.com' });
  out.htmlSmart = siteDoText(RPROBE);
  await siteDo('vpn', 'gemini.google.com'); out.vpn = calls;
  setup('mail.google.com', { routes: ['domain-list3'], adaptive: true });
  await siteDo('direct', 'mail.google.com'); out.direct = calls;
  setup('google.com', { routes: ['domain-list3'], own: true });
  await siteDo('direct', 'google.com'); out.directOwn = calls;
  setup('x.com', { blocked: true });
  out.htmlBlocked = siteDoText(RPROBE);
  await siteDo('direct', 'x.com'); out.unblock = calls;
  setup('x.com', {});
  await siteDo('block', 'x.com'); out.block = calls; out.did = RPROBE.did.map(x => x.text);
  confirm = { id: 'site-block' }; out.htmlConfirm = siteDoText(RPROBE);
  console.log(JSON.stringify(out));
})();
"""
r = subprocess.run(["node", "-e", script], text=True, capture_output=True)
if r.returncode:
    fail(r.stderr[-600:])
o = json.loads(r.stdout)
h = o["html"]
for need in ("Через VPN · сейчас", "Через Smart DNS", "Напрямую", "Заблокировать", 'data-how="block"', "Что сделать с gemini.google.com"):
    if need not in h:
        fail(f"choices: {need!r} missing in {h}")
if "Через Smart DNS · сейчас" not in o["htmlSmart"] or "Разблокировать" not in o["htmlBlocked"]:
    fail("the current way is marked; a block of your own is lifted with «Разблокировать»")
if o["smart"] != ["config:route-domain remove", "config:smartdns-domain add"]:
    fail(f"Smart DNS takes the domain out of VPN first: {o['smart']}")
if o["vpn"] != ["config:smartdns-domain remove", "config:route-domain add"]:
    fail(f"VPN takes the domain out of Smart DNS first: {o['vpn']}")
if o["direct"] != ["config:adaptive remove", "config:list-domain exclude domain-list3"]:
    fail(f"directly: out of auto-selection, excluded from the list: {o['direct']}")
if o["directOwn"] != ["config:list-domain remove domain-list3"]:
    fail(f"a domain the list holds itself is removed from it: {o['directOwn']}")
if o["unblock"] != ["ads-control:agh remove block"]:
    fail(f"a blocked domain chosen directly is unblocked first: {o['unblock']}")
if o["block"] != ["ads-control:agh add block"] or not o["did"][0].startswith("x.com заблокирован"):
    fail(f"block: {o['block']} {o['did']}")
if "Сайт перестанет открываться на всех устройствах" not in o["htmlConfirm"]:
    fail("blocking asks first")
if "route-domain|force-vpn|adaptive|smartdns-domain) set --" not in API:
    fail("the API passes smartdns-domain to the helper")
for need in ("'site-block': c => siteDo('block', c.dom)", "a === 'site-do'", "apiGet('ads-view', { view: 'check', search: v })"):
    if need not in JS:
        fail(f"the Panel lacks {need!r}")
print("CONSOLE_SITE_DO=PASS")
