#!/usr/bin/env python3
"""Every switch of the VWARD Panel, on and off, in Chromium on the router emulator.

The Panel runs against the emulated router (real api.cgi, fake ndmc). The test opens every
page it can reach, finds every switch, and for each one:

  1. clicks it (and «Да» when the Panel asks to confirm), waits for the router's answer;
  2. opens the page afresh: the switch must show the new state;
  3. clicks it back (confirming again), opens the page afresh: the old state is back.
Along the way: no script error, no API answer that is not JSON, no failure the Panel does
not show, nothing left «busy» (a switch that stays disabled). Afterwards the router's minute
jobs run three times (no shell error, guards and route engine fine) and VWARD's settings and
the router's configuration are what they were before the first click.
Needs root (chroot, mount) and Playwright with Chromium.
  check-panel-toggles-emulated.py [--report FILE] [--only TEXT]
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("crawl", REPO / "tests/perf/check-panel-crawl-emulated.py")
crawl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawl)
chaos = crawl.chaos

# Answers the emulator cannot give (no AdGuard Home web API there): the Panel must show
# them, but they are not VWARD's bugs.
ENV_ERRORS = {"adguard_unavailable", "adguard_not_configured", "adguard_auth_required", "agh_unavailable",
              "action_unavailable"}

TOGGLE = r"""const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [base, exe, only] = [process.argv[2], process.argv[3], process.argv[4] || ''];
  const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const ctx = await b.newContext({ viewport: { width: 390, height: 900 } });
  // Every message the Panel shows (toasts vanish after 3 s): kept for the check.
  await ctx.addInitScript(() => {
    window.__toasts = [];
    new MutationObserver(ms => { for (const m of ms) for (const n of m.addedNodes) if (n.classList && n.classList.contains('toast')) window.__toasts.push(n.textContent); })
      .observe(document, { childList: true, subtree: true });
  });
  const p = await ctx.newPage();
  const out = { switches: [], errors: [] };
  let cur = 'start', inflight = 0, posts = [];
  p.on('pageerror', e => out.errors.push({ page: cur, kind: 'pageerror', text: String(e.stack || e).slice(0, 400) }));
  p.on('console', m => { if (m.type() === 'error') out.errors.push({ page: cur, kind: 'console', text: m.text().slice(0, 300) }); });
  p.on('request', r => { if (r.url().includes('/cgi-bin/')) inflight++; });
  const done = async r => {
    if (!r.url().includes('/cgi-bin/')) return;
    inflight = Math.max(0, inflight - 1);
    if (r.request().method() === 'POST') {
      let body = ''; try { body = await r.text(); } catch (e) {}
      posts.push({ url: r.url().split('?')[1] || '', form: r.request().postData() || '', status: r.status(), body: body.slice(0, 200000) });
    }
  };
  p.on('requestfinished', r => r.response().then(done).catch(() => { inflight = Math.max(0, inflight - 1); }));
  p.on('requestfailed', () => { inflight = Math.max(0, inflight - 1); });
  // settle: no API request in flight for 800 ms (at most 90 s: jobs poll).
  const settle = async () => {
    let quiet = 0;
    for (let i = 0; i < 900 && quiet < 8; i++) { await p.waitForTimeout(100); quiet = inflight === 0 ? quiet + 1 : 0; }
  };
  const open = async path => { await p.goto(base + path, { waitUntil: 'networkidle', timeout: 90000 }); await settle(); };
  await open('/');
  const ids = await p.evaluate(() => __vw.PAGES.map(x => x.id).concat(Object.keys(__vw.DETAILS)));
  // Every reachable page: the listed ones and every link a page shows.
  const queue = ids.slice(), seen = new Set(queue), found = [];
  while (queue.length && seen.size < 500) {
    const id = queue.shift(); cur = id;
    const path = await p.evaluate(id => __vw.pathOf(id), id);
    try { await open(path); } catch (e) { out.errors.push({ page: id, kind: 'goto', text: String(e).slice(0, 200) }); continue; }
    const r = await p.evaluate(() => {
      const sel = el => {
        const a = [...el.attributes].filter(x => x.name.startsWith('data-'));
        return 'input[type=checkbox]' + a.map(x => '[' + x.name + '="' + CSS.escape(x.value) + '"]').join('');
      };
      return {
        links: [...document.querySelectorAll('[data-go]')].map(e => e.getAttribute('data-go')),
        sw: [...document.querySelectorAll('label.switch input[type=checkbox]')].map(e => ({ sel: sel(e), label: e.getAttribute('aria-label') || '', checked: e.checked, disabled: e.disabled }))
      };
    });
    for (const l of r.links) if (l && !seen.has(l)) { seen.add(l); queue.push(l); }
    for (const s of r.sw) {
      if (only && !(s.label + s.sel).includes(only)) continue;
      // The same switch on several pages (a component on its page and in the list): once.
      if (found.some(f => f.sel === s.sel)) continue;
      found.push(Object.assign({ page: id, path: path }, s));
    }
  }
  const state = async s => p.evaluate(sel => { const e = document.querySelector(sel); return e ? { checked: e.checked, disabled: e.disabled } : null; }, s.sel);
  // flip: click the switch (its label), say yes when asked; returns what the router was asked and said.
  const flip = async s => {
    posts = [];
    await p.evaluate(() => { window.__toasts = []; });
    const el = await p.$(s.sel);
    if (!el) return { missing: true };
    await p.evaluate(sel => document.querySelector(sel).closest('label').click(), s.sel);
    await p.waitForTimeout(300);
    let confirmed = false;
    for (let i = 0; i < 3; i++) {
      if (!await p.$('[data-act="confirm-yes"]')) break;
      // The page may draw itself again meanwhile: click by selector, which finds it afresh.
      try { await p.click('[data-act="confirm-yes"]', { timeout: 5000 }); confirmed = true; } catch (e) {}
      await p.waitForTimeout(300);
    }
    await settle();
    const toast = await p.evaluate(() => (window.__toasts || []).join(' | ').slice(0, 200));
    const local = await state(s);
    return { confirmed, posts: posts.slice(), toast, after: local };
  };
  for (const s of found) {
    if (s.disabled) { out.switches.push(Object.assign({}, s, { skipped: 'disabled' })); continue; }
    cur = s.page;
    const rec = Object.assign({}, s, { steps: [] });
    try {
      await open(s.path);
      const before = await state(s);
      if (!before) { rec.skipped = 'gone'; out.switches.push(rec); continue; }
      rec.before = before.checked;
      for (const want of [!before.checked, before.checked]) {
        const f = await flip(s);
        await open(s.path);
        const now = await state(s);
        f.want = want; f.reloaded = now ? now.checked : null; f.stuck = now ? now.disabled : null;
        rec.steps.push(f);
        if (now && now.checked !== want) break;
      }
    } catch (e) { rec.error = String(e).slice(0, 300); }
    out.switches.push(rec);
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


def prepare(root):
    """What a real router has and the bare emulator lacks, so that every switch can move:
    the component registry (the updater installs it) and a second tunnel that may be
    switched off (the default one never is), whose state follows ndmc."""
    slot = root / "opt/share/vward/updater/current"
    slot.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "config/components/component-registry.json", slot / "component-registry.json")
    ifs = json.loads((root / "emu/rci-interface.json").read_text())
    ifs["Wireguard2"] = {"type": "Wireguard", "security-level": "public", "description": "second"}
    (root / "emu/rci-interface.json").write_text(json.dumps(ifs))
    rc = root / "emu/running-config"
    rc.write_text(rc.read_text() + "interface Wireguard2\n    description second\n!\n")
    curl = root / "opt/bin/curl"
    curl.write_text(curl.read_text().replace(
        "*/rci/show/interface) cat /emu/rci-interface.json ;;",
        "*/rci/show/interface) jq --rawfile d /emu/iface-down 'reduce ($d | split(\"\\n\")[] | select(length > 0)) as $n (.; if .[$n] then .[$n].state = \"down\" else . end)' /emu/rci-interface.json 2>/dev/null || cat /emu/rci-interface.json ;;", 1))
    (root / "emu/iface-down").write_text("")
    nd = root / "bin/ndmc"
    nd.write_text(nd.read_text().replace(
        "    show*) : ;;",
        "    'interface '*' down') printf '%s\\n' \"$cmd\" >> /emu/ndmc-changes.log; n=${cmd#interface }; echo \"${n% down}\" >> /emu/iface-down ;;\n"
        "    'interface '*' up') printf '%s\\n' \"$cmd\" >> /emu/ndmc-changes.log; n=${cmd#interface }; grep -vx \"${n% up}\" /emu/iface-down > /emu/iface-down.n; cat /emu/iface-down.n > /emu/iface-down ;;\n"
        "    show*) : ;;", 1))


def snapshot(root):
    """VWARD's settings and the router's configuration, without backups, logs and run state."""
    snap = {}
    for base in ("opt/etc/vward", "emu"):
        for p in sorted((root / base).rglob("*")):
            rel = str(p.relative_to(root))
            if not p.is_file() or re.search(r"backup|\.bak|\.log$|emu/(clock-offset|fault-|agh-pid|iface-down|rc\.n)|ndmc-(changes|refused)|\.tmp|\.lock|stamp|last", rel):
                continue
            try:
                snap[rel] = p.read_text(errors="replace")
            except OSError:
                pass
    return snap


def kv(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), v.strip().strip('"'))
    return out


def modes(text):
    out = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#") and "|" in line:
            a = line.split("|")
            out.setdefault(a[0], a[1])
    return out


def compare(before, after, info):
    """What the switches changed and did not put back: the router's configuration exactly;
    VWARD's settings by meaning (a setting written out at its default value is the same)."""
    reg = json.loads((REPO / "components/ads-privacy-guard/data/source-registry.json").read_text())
    defaults = {x["id"]: x.get("default_mode") or ("active" if x.get("enabled") else "off") for x in reg["sources"]}
    bad = []
    for k in sorted(set(before) | set(after)):
        a, b = before.get(k), after.get(k)
        if a == b:
            continue
        if k.endswith("source-overrides.tsv"):
            ma, mb = modes(a or ""), modes(b or "")
            diff = [i for i in set(ma) | set(mb) if ma.get(i, defaults.get(i)) != mb.get(i, defaults.get(i))]
            if diff:
                bad.append(f"not as before: {k}: sources {sorted(diff)}")
            continue
        if a is None:
            info.append(f"written out by a switch (new file): {k}")
            continue
        ka, kb = kv(a), kv(b or "")
        if ka and set(ka) <= set(kb) and all(ka[x] == kb[x] for x in ka):
            added = {x: kb[x] for x in kb if x not in ka}
            info.append(f"written out at their values: {k}: {added}")
            continue
        la, lb = (a or "").splitlines(), (b or "").splitlines()
        d = [f"-{x}" for x in la if x not in lb][:3] + [f"+{x}" for x in lb if x not in la][:3]
        bad.append(f"not as before: {k}: {' '.join(d)[:220]}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    groot = subprocess.run(["npm", "root", "-g"], text=True, capture_output=True).stdout.strip()
    if os.geteuid() != 0 or not groot or not (Path(groot) / "playwright").exists():
        print("PANEL_TOGGLES=SKIP (needs root and playwright)")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="vward-toggles-"))
    root = None
    problems, info = [], []
    try:
        root = chaos.build(tmp)
        prepare(root)
        chaos.sh(root, "/opt/etc/init.d/S91vward-route-engine start")
        before = snapshot(root)
        srv = crawl.server(root)
        js = tmp / "toggles.js"
        js.write_text(TOGGLE)
        r = subprocess.run(["node", str(js), f"http://127.0.0.1:{srv.server_address[1]}",
                            os.environ.get("VWARD_CHROMIUM", "/opt/pw-browsers/chromium"), args.only],
                           text=True, capture_output=True, timeout=7200, env=os.environ | {"NODE_PATH": groot})
        if r.returncode:
            print(r.stderr[-3000:])
            print("PANEL_TOGGLES=FAIL the browser script died")
            return 1
        res = json.loads(r.stdout.strip().splitlines()[-1])
        for e in res["errors"]:
            problems.append(f"{e['page']}: {e['kind']}: {e['text']}")
        n_ok = n_env = n_skip = 0
        for s in res["switches"]:
            name = f"{s['page']} «{s['label']}» {s['sel'][20:90]}"
            if s.get("skipped"):
                n_skip += 1
                info.append(f"skipped ({s['skipped']}): {name}")
                continue
            if s.get("error"):
                problems.append(f"{name}: {s['error']}")
                continue
            env_only, bad = False, []
            for st in s["steps"]:
                answers = []
                for pst in st["posts"]:
                    try:
                        j = json.loads(pst["body"])
                    except ValueError:
                        bad.append(f"answer not JSON: {pst['body'][:100]!r}")
                        continue
                    answers.append(j)
                    err = j.get("error") or (re.search(r"ERROR=([a-z_]+)", str(j.get("result", ""))) or [None, None])[1]
                    if not j.get("ok"):
                        if err in ENV_ERRORS:
                            env_only = True
                        else:
                            bad.append(f"router said {err or j} ({pst['url']} {pst['form'][:80]})")
                if st["stuck"]:
                    bad.append("switch stays disabled after the answer")
                if st["reloaded"] is not None and st["reloaded"] != st["want"] and not st["posts"]:
                    # Nothing sent: a switch that opens a form (the login), or one the Panel
                    # refuses itself with a message (a full tab bar).
                    if "data-auth=" in s["sel"]:
                        info.append(f"opens the login form: {name}")
                    elif st["toast"]:
                        info.append(f"refused by the Panel, shown «{st['toast'][:80]}»: {name}")
                    else:
                        bad.append(f"wanted {'on' if st['want'] else 'off'}, nothing sent and nothing said")
                    break
                if st["reloaded"] is not None and st["reloaded"] != st["want"] and not env_only:
                    failed = [a for a in answers if not a.get("ok")]
                    if failed:
                        # Refused: the Panel must have said so.
                        if not st["toast"]:
                            bad.append(f"refused but the Panel said nothing: {failed[0]}")
                        else:
                            info.append(f"refused, shown «{st['toast'][:80]}»: {name}")
                    else:
                        bad.append(f"wanted {'on' if st['want'] else 'off'}, after reload {'on' if st['reloaded'] else 'off'}"
                                   f" (posts {len(st['posts'])}, toast «{st['toast'][:60]}»)")
            if bad:
                problems += [f"{name}: {x}" for x in bad]
            elif env_only:
                n_env += 1
                info.append(f"no AdGuard Home in the emulator: {name}")
            else:
                n_ok += 1
        # The router afterwards: three minutes of its jobs, then everything as before.
        findings = []
        for minute in range(1, 4):
            chaos.advance(root)
            chaos.run_round(root, minute, [], findings, "after-toggles")
        problems += [f"after the toggles, {job}: {what} {d}" for _, _, job, what, d in findings]
        if chaos.guard_state(root).get("FAILOPEN_ACTIVE") == "1":
            problems.append("after the toggles: the tunnel guard is in fail-open")
        if not chaos.engine_running(root):
            problems.append("after the toggles: the route engine is not running")
        after = snapshot(root)
        problems += compare(before, after, info)
        if args.report:
            Path(args.report).write_text(json.dumps({"problems": problems, "info": info, "switches": res["switches"]},
                                                    ensure_ascii=False, indent=1))
        for x in info:
            print("INFO", x)
        for x in problems:
            print("FAIL", x)
        total = len(res["switches"])
        print(f"PANEL_TOGGLES={'PASS' if not problems else 'FAIL'} switches={total} on_off_ok={n_ok} "
              f"no_agh={n_env} skipped={n_skip} problems={len(problems)}")
        return 1 if problems else 0
    finally:
        if root is not None:
            chaos.sh(root, "/opt/etc/init.d/S91vward-route-engine stop", timeout=30)
            for m in ("opt", "proc"):
                subprocess.run(["umount", "-l", str(root / m)], stderr=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
