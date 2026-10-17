#!/usr/bin/env python3
"""vward_fetch: a download when Entware's curl crashes on HTTPS (its OpenSSL 3.5.5 on some MIPS
routers): uclient-fetch takes the same curl options, curl is not asked again within the hour,
the server's status, --fail, --max-filesize and --retry mean what they mean for curl."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-device-profile.sh"


def fail(message: str) -> None:
    raise SystemExit(f"FETCH_FALLBACK=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "curl").write_text(f'#!/bin/sh\necho "$*" >> "{t}/curl.log"\nexit "${{CURL_RC:-132}}"\n')
    # uclient-fetch: the answer of the «server» from UC_MODE (ok: a body, 404, down: no answer).
    (t / "uclient-fetch").write_text(f'''#!/bin/sh
echo "$*" >> "{t}/uc.log"
out=-
while [ $# -gt 0 ]; do [ "$1" = -O ] && out=$2; shift; done
case "$UC_MODE" in
    ok) if [ "$out" = - ]; then printf 'BODY'; else printf 'BODY' > "$out"; fi; exit 0 ;;
    big) printf '0123456789' > "$out"; exit 0 ;;
    404) echo "HTTP error 404" >&2; exit 8 ;;
    down) echo "Connection error: Connection refused" >&2; exit 4 ;;
esac
''')
    for f in ("curl", "uclient-fetch"):
        (t / f).chmod(0o755)
    flag = t / "tls.broken"
    base = {"PATH": os.environ["PATH"], "VWARD_CURL_BIN": str(t / "curl"), "VWARD_UCLIENT_BIN": str(t / "uclient-fetch"),
            "VWARD_TLS_BROKEN_FLAG": str(flag), "VWARD_CA_BUNDLE": str(t / "ca.crt"), "TMPDIR": tmp}
    (t / "ca.crt").write_text("x")

    def fetch(args: str, **env: str) -> tuple[int, str]:
        r = subprocess.run(["sh", "-c", f'. "{LIB}"; vward_fetch {args}'], env={**base, **env}, text=True,
                           capture_output=True, timeout=30)
        return r.returncode, r.stdout

    def log(name: str) -> list[str]:
        p = t / f"{name}.log"
        return p.read_text().splitlines() if p.exists() else []

    url = "https://example.invalid/feed.json"
    rc, out = fetch(f"--fail --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 180 "
                    f"--retry 3 --max-filesize 100 --output {t}/a.json --write-out '%{{http_code}}' {url}", UC_MODE="ok")
    if rc != 0 or out != "200" or (t / "a.json").read_text() != "BODY":
        fail(f"a crashed curl is not replaced: rc={rc} out={out!r}")
    if not flag.exists() or len(log("curl")) != 1:
        fail("the crash is not remembered")
    uc = log("uc")[-1]
    if f"-O {t}/a.json" not in uc or "-T 180" not in uc or f"--ca-certificate {t}/ca.crt" not in uc or not uc.endswith(url):
        fail(f"uclient-fetch is not asked the same request: {uc}")

    # Within the hour curl is not asked again.
    rc, out = fetch(f"-fsSL -A 'Mozilla/5.0 (X11)' {url}", UC_MODE="ok")
    if rc != 0 or out != "BODY" or len(log("curl")) != 1 or "-U Mozilla/5.0 (X11)" not in log("uc")[-1]:
        fail(f"curl asked again within the hour, or the body/agent lost: rc={rc} out={out!r}")

    rc, out = fetch(f"--fail -o {t}/b -w '%{{http_code}}' {url}", UC_MODE="404")
    if rc != 22 or out != "404":
        fail(f"--fail with 404: rc={rc} out={out!r}")
    rc, out = fetch(f"-s -o {t}/b -w '%{{http_code}}\\n' {url}", UC_MODE="404")
    if rc != 0 or out != "404\n":
        fail(f"without --fail a 404 is an answer: rc={rc} out={out!r}")

    n = len(log("uc"))
    rc, out = fetch(f"--retry 2 -o {t}/c -w '%{{http_code}}' {url}", UC_MODE="down")
    if rc != 7 or out != "000" or len(log("uc")) - n != 3:
        fail(f"no answer: curl's 7, 000 and the retries: rc={rc} out={out!r} tries={len(log('uc')) - n}")

    rc, _ = fetch(f"--max-filesize 5 -o {t}/d {url}", UC_MODE="big")
    if rc != 63 or (t / "d").exists():
        fail(f"--max-filesize: rc={rc}")

    # Options it cannot honour: «not supported», never a request without them.
    n = len(log("uc"))
    for args in (f"--resolve example.invalid:443:192.0.2.1 {url}", f"-X POST {url}", f"-sSo {t}/e {url}"):
        rc, _ = fetch(args, UC_MODE="ok")
        if rc != 2:
            fail(f"{args}: rc={rc}")
    if len(log("uc")) != n:
        fail("an unsupported request reached uclient-fetch")

    # The updater's per-file fetch: a curl config with url/output pairs (a Viva 2026-10-12: with
    # curl crashing, every per-file update failed «Проверка обновления не прошла»). Each pair
    # goes through the fallback, the other options kept.
    flag.unlink(missing_ok=True)
    cfg = t / "list.curl"
    cfg.write_text(f'url = "https://example.invalid/f/1"\noutput = "{t}/f1"\nurl = "https://example.invalid/f/2"\noutput = "{t}/sub dir/f2"\n')
    (t / "sub dir").mkdir()
    n0 = len(log("uc"))
    rc, _ = fetch(f"--fail --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 300 --retry 3 "
                  f"--retry-all-errors --max-filesize 1000 --config {cfg}", UC_MODE="ok")
    got = log("uc")[n0:]
    if rc != 0 or (t / "f1").read_text() != "BODY" or (t / "sub dir/f2").read_text() != "BODY" or len(got) != 2:
        fail(f"a config list through the fallback: rc={rc} {got}")
    if not got[0].endswith("https://example.invalid/f/1") or "-T 300" not in got[1] or not flag.exists():
        fail(f"each pair with the same options: {got}")
    rc, _ = fetch(f"--fail --config {cfg}", UC_MODE="404")
    if rc != 22:
        fail(f"the first failure of a list is the answer: rc={rc}")
    n = len(log("uc"))

    # A curl that works is used as it is: its error stays its error.
    flag.unlink()
    rc, _ = fetch(f"--fail {url}", CURL_RC="22", UC_MODE="ok")
    if rc != 22 or flag.exists() or len(log("uc")) != n:
        fail("a working curl's answer went to uclient-fetch")

    # Stopped from outside (a time limit: 143, 137) or a closed pipe (141): the request goes
    # through the fallback, curl is not marked broken (Viva 2026-10-17: a working curl was
    # avoided for hours and reinstalled every 6 hours).
    for code in ("137", "141", "143"):
        rc, _ = fetch(f"--fail {url}", CURL_RC=code, UC_MODE="ok")
        if rc != 0 or flag.exists():
            fail(f"curl stopped from outside ({code}) is marked broken: rc={rc}")
    r = subprocess.run(["sh", "-c", f'. "{LIB}"; vward_https_broken'], env=base)
    if r.returncode == 0:
        fail("vward_https_broken without a crash")
    flag.write_text("")
    r = subprocess.run(["sh", "-c", f'. "{LIB}"; vward_https_broken'], env=base)
    if r.returncode != 0:
        fail("vward_https_broken after a crash")

# No uclient-fetch (Keenetic's Entware has none): the VLESS module's Xray speaks TLS for curl.
# A stand-in Xray: a plain HTTP server on the port of its configuration that answers with what
# it was asked and how it was configured; curl crashes on https:// and is real for http://.
real_curl = subprocess.run(["sh", "-c", "command -v curl"], capture_output=True, text=True).stdout.strip()
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "curl").write_text(f'#!/bin/sh\nfor a in "$@"; do case "$a" in https://*) kill -SEGV $$ ;; esac; done\nexec {real_curl} "$@"\n')
    (t / "xray").write_text(f"""#!/usr/bin/env python3
import http.server, json, os, sys
c = json.load(open(sys.argv[3]))
i, o = c["inbounds"][0], c["outbounds"][0]["streamSettings"]
seen = dict(address=i["settings"]["address"], port=i["settings"]["port"], sni=o["tlsSettings"]["serverName"],
            alpn=o["tlsSettings"]["alpn"], sockopt=o.get("sockopt"), ca=os.environ.get("SSL_CERT_FILE"))
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # GitHub sends a release file on to another server; a path on the same server too.
        go = {{"/rel/f.tar.gz": "https://objects.example.invalid/f/1?s=2", "/rel/same": "/other/x", "/loop": "/loop"}}.get(self.path)
        if go:
            self.send_response(302); self.send_header("Location", go); self.send_header("Content-Length", "5"); self.end_headers()
            self.wfile.write(b"moved"); return
        b = json.dumps(dict(seen, path=self.path, host=self.headers.get("Host"))).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
open("{t}/xray.pid", "w").write(str(os.getpid()))
http.server.HTTPServer((i["listen"], i["port"]), H).serve_forever()
""")
    for f in ("curl", "xray"):
        (t / f).chmod(0o755)
    (t / "ca.crt").write_text("x")
    env = {"PATH": os.environ["PATH"], "VWARD_CURL_BIN": str(t / "curl"), "VWARD_UCLIENT_BIN": "", "VWARD_XRAY_BIN": str(t / "xray"),
           "VWARD_TLS_BROKEN_FLAG": str(t / "flag"), "VWARD_CA_BUNDLE": str(t / "ca.crt"), "TMPDIR": tmp}
    import json
    r = subprocess.run(["sh", "-c", f'. "{LIB}"; vward_fetch --fail --silent --show-error --location --proto =https --tlsv1.2 '
                       f'--interface eth3 --resolve feed.example.invalid:443:192.0.2.7 --output {t}/m.json --write-out "%{{http_code}}" '
                       'https://feed.example.invalid/a/b/manifest.json?x=1'],
                       env=env, text=True, capture_output=True, timeout=60)
    if r.returncode != 0 or r.stdout != "200":
        fail(f"through Xray: rc={r.returncode} out={r.stdout!r} err={r.stderr!r}")
    got = json.loads((t / "m.json").read_text())
    want = {"address": "192.0.2.7", "port": 443, "sni": "feed.example.invalid", "alpn": ["http/1.1"], "sockopt": {"interface": "eth3"},
            "ca": str(t / "ca.crt"), "path": "/a/b/manifest.json?x=1", "host": "feed.example.invalid"}
    if got != want:
        fail(f"Xray is not asked the same request: {got}")
    pid = int((t / "xray.pid").read_text())
    import time
    def gone(p):
        # The process may end between two looks at /proc: gone either way.
        try:
            return "Z" in Path(f"/proc/{p}/stat").read_text().split(")")[-1][:3]
        except FileNotFoundError:
            return True
    for _ in range(20):
        if gone(pid):
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        fail("the short-lived Xray is left running")
    if list(t.glob("vward-fetch.*")):
        fail("Xray's configuration is left behind")
    # A redirect to another server: a new Xray for it, the provider's interface kept, --resolve
    # only for the first server; what is printed and the headers are the last answer's.
    def follow(url, extra=""):
        return subprocess.run(["sh", "-c", f'. "{LIB}"; vward_fetch -fsSL --proto =https --interface eth3 --resolve feed.example.invalid:443:192.0.2.7 '
                              f'{extra} -D {t}/h -o {t}/r.json -w "%{{http_code}}" {url}'], env=env, text=True, capture_output=True, timeout=60)
    r = follow("https://feed.example.invalid/rel/f.tar.gz")
    got = json.loads((t / "r.json").read_text()) if (t / "r.json").exists() else {}
    if r.returncode != 0 or r.stdout != "200" or got.get("sni") != "objects.example.invalid" or got.get("address") != "objects.example.invalid" \
            or got.get("path") != "/f/1?s=2" or got.get("sockopt") != {"interface": "eth3"} or not (t / "h").read_text().startswith("HTTP/1.0 200"):
        fail(f"a redirect to another server: rc={r.returncode} out={r.stdout!r} {got} err={r.stderr!r}")
    r = follow("https://feed.example.invalid/rel/same")
    got = json.loads((t / "r.json").read_text())
    if r.stdout != "200" or got.get("path") != "/other/x" or got.get("sni") != "feed.example.invalid":
        fail(f"a redirect to a path on the same server: {r.stdout!r} {got}")
    r = follow("https://feed.example.invalid/loop", "--max-redirs 2")
    if r.returncode != 0 or r.stdout != "302":
        fail(f"redirects without end must stop: rc={r.returncode} out={r.stdout!r}")
    if list(t.glob("vward-fetch.*")):
        fail("the files of a followed request are left behind")
    # A host that is not a plain name never reaches the configuration.
    r = subprocess.run(["sh", "-c", f'. "{LIB}"; vward_fetch -o {t}/x \'https://a"b.example/\''], env=env, capture_output=True, timeout=30)
    if r.returncode != 3:
        fail(f"a host with quotes: rc={r.returncode}")

# HTTP/1.1 on every HTTPS request: Entware's curl crashed in libnghttp2 (HTTP/2), Viva 2026-10-12.
# A crash in a tunnel probe read as «the tunnel does not answer».
lib = LIB.read_text() if hasattr(LIB, "read_text") else open(LIB).read()
if '"$_vf_curl" --http1.1 "$@"' not in lib:
    fail("vward_fetch asks curl for HTTP/2")
REPO = Path(__file__).resolve().parents[2]
for path in ("components/tunnel-guard/scripts/vward-tunnel-guard.sh", "components/tunnel-guard/scripts/vward-tunnel-health.sh",
             "components/tunnel-guard/scripts/vward-tunnel-quality.sh", "components/tunnel-guard/scripts/vward-vless-engine.sh",
             "components/policy-sync/scripts/vward-policy-sync.sh", "components/runtime/scripts/vward-housekeeping.sh", "web/cgi-bin/api.cgi"):
    if "--http1.1" not in (REPO / path).read_text():
        fail(f"{path}: HTTPS probes without --http1.1")

print("FETCH_FALLBACK=PASS")
