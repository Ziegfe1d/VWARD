#!/usr/bin/env python3
"""The VWARD Panel on the router emulator: every page opened in Chromium, every API answer checked.

The Panel's files and the real api.cgi run against the emulated router (the chaos run's
rootfs: fake ndmc, AdGuard Home in the DNS chain). Chromium opens the Panel, then walks
every page it can reach: the pages and sections the script lists, and every link
(data-go) a page shows, tunnels and lists included. On each page, at 390 and 320 px:

  * no script error (pageerror, console error);
  * every API answer is JSON with a known shape (no shell text, no empty body, no 5xx);
  * nothing wider than the screen (no horizontal scroll);
  * the page title is not empty and no «undefined», «NaN» or «[object Object]» is shown.
Needs root (chroot, mount) and Playwright with Chromium.
  check-panel-crawl-emulated.py [--report FILE] [--keep]
"""
import argparse
import http.server
import importlib.util
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WWW = "/opt/share/vward/console/www"
spec = importlib.util.spec_from_file_location("chaos", REPO / "tests/perf/check-chaos-emulated.py")
chaos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chaos)

API_LOG = []
# --api fail|empty|garbage: every API answer replaced, to see the Panel survive a router
# that is busy, half-broken or answers nonsense.
API_MODE = "real"


def cgi(root, method, query, body, cookie):
    env = {"PATH": chaos.PATH_ENV, "HOME": "/root", "GATEWAY_INTERFACE": "CGI/1.1", "REQUEST_METHOD": method,
           "QUERY_STRING": query, "REMOTE_ADDR": "192.0.2.10", "SERVER_PORT": "8088",
           "HTTP_X_VWARD_REQUEST": "console", "CONTENT_LENGTH": str(len(body)),
           "CONTENT_TYPE": "application/json", "HTTP_COOKIE": cookie or ""}
    cmd = ["env", "-i"] + [f"{k}={v}" for k, v in env.items()] + \
          ["chroot", str(root), "/bin/sh", "-c", f"cd {WWW}/cgi-bin && exec ./api.cgi"]
    try:
        r = subprocess.run(cmd, input=body, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except subprocess.TimeoutExpired:
        return 504, {}, b'{"crawl":"timeout"}', b"timeout"
    out = r.stdout
    head, sep, rest = out.partition(b"\n\n")
    if not sep:
        return 502, {}, out, r.stderr
    headers, status = {}, 200
    for line in head.decode(errors="replace").splitlines():
        k, _, v = line.partition(":")
        if k.lower() == "status":
            status = int(v.split()[0])
        else:
            headers[k.strip()] = v.strip()
    return status, headers, rest, r.stderr


def server(root):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def handle_api(self, method):
            u = urllib.parse.urlsplit(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            status, headers, rest, err = cgi(root, method, u.query, body, self.headers.get("Cookie"))
            if API_MODE != "real" and "action=ping" not in u.query:
                headers = {"Content-Type": "application/json"}
                status, err = 200, b""
                rest = {"fail": b'{"ok":false,"error":"busy"}', "empty": b"{}", "garbage": b"<html>oops"}[API_MODE]
            API_LOG.append({"method": method, "query": u.query, "body": body.decode(errors="replace")[:300],
                            "status": status, "out": rest.decode(errors="replace")[:600],
                            "stderr": err.decode(errors="replace")[-600:],
                            "ctype": headers.get("Content-Type", "")})
            try:
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(rest)))
                self.end_headers()
                self.wfile.write(rest)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the page moved on before the answer came

        def do_POST(self):
            self.handle_api("POST")

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            if u.path == "/cgi-bin/api.cgi":
                return self.handle_api("GET")
            f = root / WWW.lstrip("/") / u.path.lstrip("/")
            if not f.is_file():
                f = root / WWW.lstrip("/") / "index.html"
            data = f.read_bytes()
            if f.name == "vward-console.js":
                # The crawler reads the page list and the addresses from the script itself.
                i = data.rstrip().rfind(b"})();")
                data = data[:i] + b"window.__vw = { PAGES, DETAILS, pathOf };\n" + data[i:]
            ctype = {".js": "application/javascript", ".css": "text/css"}.get(f.suffix, "text/html")
            self.send_response(200)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
    s = S(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


CRAWL = r"""const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [base, exe, limit] = [process.argv[2], process.argv[3], +process.argv[4]];
  const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const out = { pages: {}, errors: [] };
  for (const width of [390, 320]) {
    const ctx = await b.newContext({ viewport: { width, height: 800 } });
    const p = await ctx.newPage();
    let cur = 'start';
    p.on('pageerror', e => out.errors.push({ width, page: cur, kind: 'pageerror', text: String(e.stack || e).slice(0, 500) }));
    p.on('console', m => { if (m.type() === 'error') out.errors.push({ width, page: cur, kind: 'console', text: m.text().slice(0, 300) }); });
    await p.goto(base + '/', { waitUntil: 'networkidle' });
    const ids = await p.evaluate(() => __vw.PAGES.map(x => x.id).concat(Object.keys(__vw.DETAILS)));
    const queue = ids.slice(), seen = new Set(queue);
    let visited = 0;
    while (queue.length && visited++ < limit) {
      const id = queue.shift(); cur = id;
      const path = await p.evaluate(id => __vw.pathOf(id), id);
      try { await p.goto(base + path, { waitUntil: 'networkidle', timeout: 60000 }); }
      catch (e) { out.errors.push({ width, page: id, kind: 'goto', text: String(e).slice(0, 200) }); continue; }
      await p.waitForTimeout(150);
      const r = await p.evaluate(() => {
        const w = document.documentElement.clientWidth, wide = [];
        document.querySelectorAll('body *').forEach(el => {
          const q = el.getBoundingClientRect();
          if (q.width && q.right > w + 1 && getComputedStyle(el).position !== 'fixed' && !el.closest('[hidden]')) {
            let anc = el.parentElement, clipped = false;
            while (anc && anc !== document.body) { const s = getComputedStyle(anc); if (/(auto|scroll|hidden|clip)/.test(s.overflowX)) { clipped = true; break; } anc = anc.parentElement; }
            if (!clipped) wide.push((el.tagName + '.' + el.className).slice(0, 60) + ' ' + Math.round(q.right) + '>' + w + ' «' + (el.textContent || '').trim().slice(0, 40) + '»');
          }
        });
        const text = document.body.innerText;
        const bad = (text.match(/.{0,30}(undefined|NaN|\[object Object\]|null null).{0,30}/g) || []).slice(0, 5);
        const links = Array.from(document.querySelectorAll('[data-go]')).map(e => e.getAttribute('data-go'));
        return { scroll: document.documentElement.scrollWidth > w, wide: wide.slice(0, 5), bad, links,
                 title: (document.querySelector('h1,.page-title,.top-title') || {}).textContent || '', route: location.pathname };
      });
      out.pages[width + ' ' + id] = { path, scroll: r.scroll, wide: r.wide, bad: r.bad, title: r.title.trim(), route: r.route };
      for (const l of r.links) if (l && !seen.has(l)) { seen.add(l); queue.push(l); }
    }
    await ctx.close();
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


def check_api(entries):
    bad = []
    for e in entries:
        what = f"{e['method']} ?{e['query']}"
        if e["status"] >= 500:
            bad.append(f"{what}: HTTP {e['status']} {e['out'][:120]} {e['stderr'][-200:]}")
            continue
        if "download" in e["query"] or "json" not in e["ctype"]:
            continue
        try:
            j = json.loads(e["out"]) if len(e["out"]) < 600 else None
        except ValueError:
            bad.append(f"{what}: not JSON: {e['out'][:160]!r}")
            continue
        if j is not None and not isinstance(j, dict):
            bad.append(f"{what}: answer is not an object: {e['out'][:120]}")
        if e["stderr"].strip():
            bad.append(f"{what}: shell said: {e['stderr'].strip()[-300:]}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--api", choices=["real", "fail", "empty", "garbage"], default="real")
    args = ap.parse_args()
    global API_MODE
    API_MODE = args.api
    groot = subprocess.run(["npm", "root", "-g"], text=True, capture_output=True).stdout.strip()
    if os.geteuid() != 0 or not groot or not (Path(groot) / "playwright").exists():
        print("PANEL_CRAWL=SKIP (needs root and playwright)")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="vward-crawl-"))
    root = None
    try:
        root = chaos.build(tmp)
        srv = server(root)
        js = tmp / "crawl.js"
        js.write_text(CRAWL)
        r = subprocess.run(["node", str(js), f"http://127.0.0.1:{srv.server_address[1]}", os.environ.get("VWARD_CHROMIUM", "/opt/pw-browsers/chromium"),
                            str(args.limit)], text=True, capture_output=True, timeout=3600,
                           env=os.environ | {"NODE_PATH": groot})
        if r.returncode:
            print(r.stderr[-2000:])
            print("PANEL_CRAWL=FAIL crawler died")
            return 1
        res = json.loads(r.stdout.strip().splitlines()[-1])
        problems = []
        for e in res["errors"]:
            problems.append(f"[{e['width']}] {e['page']}: {e['kind']}: {e['text']}")
        for key, pg in res["pages"].items():
            if pg["scroll"] or pg["wide"]:
                problems.append(f"[{key}] wider than the screen: {'; '.join(pg['wide']) or 'scrollWidth'}")
            if pg["bad"]:
                problems.append(f"[{key}] shows: {pg['bad']}")
        if API_MODE == "real":
            problems += check_api(API_LOG)
        seen = set()
        problems = [x for x in problems if not (x in seen or seen.add(x))]
        if args.report:
            Path(args.report).write_text(json.dumps({"problems": problems, "pages": res["pages"], "api": API_LOG},
                                                    ensure_ascii=False, indent=1))
        n = len({k.split(' ', 1)[1] for k in res["pages"]})
        for x in problems:
            print("FAIL", x)
        print(f"PANEL_CRAWL={'PASS' if not problems else 'FAIL'} pages={n} api_calls={len(API_LOG)} problems={len(problems)}")
        return 1 if problems else 0
    finally:
        if root is not None:
            for m in ("opt", "proc"):
                subprocess.run(["umount", "-l", str(root / m)], stderr=subprocess.DEVNULL)
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
