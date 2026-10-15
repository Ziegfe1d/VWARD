#!/usr/bin/env python3
"""vward-fetch, VWARD's own download program (tools/vward-fetch), against a local HTTPS server.

curl's options and exit codes, as the callers use them: a body by its length and in chunks, a
file and its size limit, -w (code, time, size), -L, -f, a time limit, --resolve, -A and -H, a
certificate of another name or of an unknown authority refused, TLS 1.3 and TLS 1.2 (RSA), no
connection, an option it does not have.

FETCH_RUN: the program to run, e.g. «qemu-mipsel-static out/vward-fetch-linux-mipsle» (the
workflow builds it with tools/vward-fetch/build.sh); without it the x86_64 build of FETCH_OUT.
"""
import http.server
import os
import shlex
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def fail(msg):
    print(f"VWARD_FETCH=FAIL: {msg}")
    sys.exit(1)


run_cmd = os.environ.get("FETCH_RUN") or str(Path(os.environ.get("FETCH_OUT", "out")) / "vward-fetch-linux-x86_64")
if not shutil.which(shlex.split(run_cmd)[0]) and not Path(shlex.split(run_cmd)[0]).exists():
    fail(f"no vward-fetch build: {run_cmd} (sh tools/vward-fetch/build.sh OUT)")
if not shutil.which("openssl"):
    fail("openssl is needed for the test certificates")


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def body(self, b, status=200, extra=()):
        self.send_response(status)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path
        if p == "/len":
            self.body(b"hello length\n")
        elif p == "/chunk":
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for part in (b"hello ", b"chunked", b"\n"):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
            self.wfile.write(b"0\r\n\r\n")
        elif p == "/big":
            self.body(b"x" * 200000)
        elif p == "/redir":
            self.body(b"", 302, [("Location", "/len")])
        elif p == "/slow":
            time.sleep(6)
            self.body(b"")
        elif p == "/ua":
            self.body((self.headers.get("User-Agent", "") + "|" + self.headers.get("X-T", "")).encode())
        else:
            self.body(b"", 404)


def serve(port, cert, key):
    s = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    c.load_cert_chain(cert, key)
    s.socket = c.wrap_socket(s.socket, server_side=True)
    threading.Thread(target=s.serve_forever, daemon=True).start()


with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)

    def ossl(*a):
        subprocess.run(["openssl", *a], cwd=t, check=True, capture_output=True)

    ossl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", "ca.key",
         "-out", "ca.pem", "-days", "2", "-subj", "/CN=VWARD test CA")
    (t / "ext").write_text("subjectAltName=DNS:test.vward\n")
    for name, kind in (("ec", ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1"]), ("rsa", ["-newkey", "rsa:2048"])):
        ossl("req", *kind, "-nodes", "-keyout", f"{name}.key", "-out", f"{name}.csr", "-subj", "/CN=test.vward")
        ossl("x509", "-req", "-in", f"{name}.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
             "-out", f"{name}.pem", "-days", "2", "-extfile", "ext")
    serve(18443, t / "ec.pem", t / "ec.key")
    # TLS 1.2 by OpenSSL's own server (Python's TLS 1.2 server answers Zig's client with an internal
    # error; a real server and «openssl s_server -tls1_2» do not).
    s12 = subprocess.Popen(["openssl", "s_server", "-accept", "18444", "-cert", str(t / "rsa.pem"), "-key", str(t / "rsa.key"),
                            "-tls1_2", "-www", "-quiet"], cwd=t, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    ca = str(t / "ca.pem")

    def fetch(*args, port=18443, host="test.vward", ca_file=ca):
        a = ["-sS", "--resolve", f"{host}:{port}:127.0.0.1", *args]
        if ca_file:
            a += ["--cacert", ca_file]
        r = subprocess.run([*shlex.split(run_cmd), *a], capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout

    def url(path, port=18443, host="test.vward"):
        return f"https://{host}:{port}{path}"

    checks = [
        ("a body by its length", fetch(url("/len")), (0, "hello length\n")),
        ("a body in chunks", fetch(url("/chunk")), (0, "hello chunked\n")),
        ("-L follows a redirect", fetch("-L", "-w", "%{http_code}", url("/redir")), (0, "hello length\n200")),
        ("-f: an HTTP error is 22", fetch("-f", url("/nope")), (22, "")),
        ("without -f: the code, rc 0", fetch("-o", "/dev/null", "-w", "%{http_code}", url("/nope")), (0, "404")),
        ("-A and -H are sent", fetch("-A", "ua1", "-H", "X-T: t1", url("/ua")), (0, "ua1|t1")),
        ("-m: time is up, 28", fetch("-m", "2", url("/slow")), (28, "")),
        ("--max-filesize: 63", fetch("--max-filesize", "1000", "-o", "/dev/null", url("/big")), (63, "")),
        ("a certificate of an unknown authority: 60", fetch(url("/len"), ca_file=None), None),
        ("a certificate of another name: 60", fetch(url("/len", host="other.vward"), host="other.vward"), (60, "")),
        ("TLS 1.2 with an RSA certificate", fetch("-o", "/dev/null", "-w", "%{http_code}", url("/", 18444), port=18444), (0, "200")),
        ("an option it does not have: 2", fetch("--data", "x", url("/len")), (2, "")),
    ]
    for what, got, want in checks:
        if want is None:
            if got[0] not in (60, 77):
                fail(f"{what}: {got}")
            continue
        if got != want:
            fail(f"{what}: got {got}, want {want}")
    out = t / "big.out"
    rc, so = fetch("-o", str(out), "-w", "%{http_code}|%{size_download}", url("/big"))
    if rc != 0 or so != "200|200000" or out.stat().st_size != 200000:
        fail(f"a file: {rc} {so}")
    r = subprocess.run([*shlex.split(run_cmd), "-sS", "--connect-timeout", "2", "https://127.0.0.1:1/x"], capture_output=True, timeout=30)
    if r.returncode != 7:
        fail(f"no connection: 7, got {r.returncode}")

    s12.kill()

print("VWARD_FETCH=PASS")
