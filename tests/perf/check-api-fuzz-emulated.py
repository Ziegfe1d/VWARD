#!/usr/bin/env python3
"""The Panel's API under hostile input, on the router emulator.

Every action api.cgi knows is called with GET and POST, every parameter it reads set to
the same bad value: shell code («;», «$( )», backticks), a way out of a folder, quotes and
markup, a newline, a very long value, an empty one. Then:

  * no shell code ran (no marker file appears anywhere in the router);
  * no file outside VWARD is shown (no /etc/passwd lines in an answer);
  * every answer is JSON (or the file asked for) and comes within 60 s;
  * the shell said nothing (no syntax error, «not found», bad number) on stderr;
  * the router is the same afterwards: ndmc got no change it should not have.
Needs root (chroot, mount).
  check-api-fuzz-emulated.py [--report FILE]
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
import time
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, REPO / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


crawl = load("crawl", "tests/perf/check-panel-crawl-emulated.py")
chaos = crawl.chaos

API = (REPO / "web/cgi-bin/api.cgi").read_text()
ACTIONS = re.search(r"^    (status\|ping\|[a-z|-]+)\) ;;", API, re.M).group(1).split("|")
PARAMS = sorted(set(re.findall(r"\b(?:val|form_value|form_decode|qget) ([a-z_]+)", API)) |
                {"op", "name", "path", "root", "kind", "q", "f", "k", "lines", "tunnel", "iface", "list", "id"})
PAYLOADS = {
    "semicolon": ";touch /tmp/PWNED-a;",
    "subshell": "$(touch /tmp/PWNED-b)",
    "backtick": "`touch /tmp/PWNED-c`",
    "pipe": "x|touch /tmp/PWNED-d",
    "traversal": "../../../../etc/passwd",
    "abs": "/etc/passwd",
    "quotes": "'\"<img src=x onerror=1>{}[]\\",
    "newline": "a\nip name-server 6.6.6.6",
    "long": "a" * 2000,
    "dash": "-rf",
    "glob": "*",
    "empty": "",
    "number": "99999999999999999999",
}
SHELL_ERRORS = re.compile(r"syntax error|unexpected|not found|bad number|integer expression|arithmetic|"
                          r"Segmentation|Illegal|parameter not set|bad substitution|unterminated", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report")
    args = ap.parse_args()
    if os.geteuid() != 0:
        print("API_FUZZ=SKIP (needs root)")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="vward-fuzz-"))
    root = None
    problems, n = [], 0
    try:
        root = chaos.build(tmp)
        changes = root / "emu/ndmc-changes.log"
        for action in ACTIONS:
            for pname, payload in PAYLOADS.items():
                q = {p: payload for p in PARAMS}
                q["action"] = action
                enc = urllib.parse.urlencode(q)
                for method in ("GET", "POST"):
                    query = f"action={action}" + ("" if method == "POST" else "&" + enc)
                    body = enc.encode() if method == "POST" else b""
                    t0 = time.time()
                    status, headers, out, err = crawl.cgi(root, method, query, body, "")
                    n += 1
                    took = time.time() - t0
                    what = f"{method} {action} [{pname}]"
                    text = out.decode(errors="replace")
                    errt = err.decode(errors="replace")
                    if status >= 500:
                        problems.append(f"{what}: HTTP {status} {text[:100]!r}")
                    if took > 30:
                        problems.append(f"{what}: {took:.0f} s")
                    if "root:x:0:0" in text:
                        problems.append(f"{what}: /etc/passwd shown")
                    ctype = headers.get("Content-Type", "")
                    if "json" in ctype:
                        try:
                            json.loads(text)
                        except ValueError:
                            problems.append(f"{what}: not JSON: {text[:120]!r}")
                    elif status < 500 and "download" not in action and action not in ("files", "log", "log-archive"):
                        problems.append(f"{what}: Content-Type {ctype!r}: {text[:80]!r}")
                    if SHELL_ERRORS.search(errt):
                        problems.append(f"{what}: shell said: {errt.strip()[-240:]}")
                    pw = subprocess.run(["find", str(root), "-xdev", "-name", "PWNED-*"], capture_output=True, text=True).stdout
                    if pw.strip():
                        problems.append(f"{what}: SHELL CODE RAN: {pw.strip()}")
                        for f in pw.split():
                            Path(f).unlink(missing_ok=True)
                    if changes.exists() and "6.6.6.6" in changes.read_text():
                        problems.append(f"{what}: a newline reached ndmc: {changes.read_text()[-200:]}")
                        changes.write_text("")
        rc = (root / "emu/running-config").read_text()
        if "6.6.6.6" in rc:
            problems.append("running-config got a name-server from input")
        seen = set()
        problems = [x for x in problems if not (x in seen or seen.add(x))]
        if args.report:
            Path(args.report).write_text("\n".join(problems) + "\n")
        for x in problems[:200]:
            print("FAIL", x)
        print(f"API_FUZZ={'PASS' if not problems else 'FAIL'} actions={len(ACTIONS)} params={len(PARAMS)} "
              f"requests={n} problems={len(problems)}")
        return 1 if problems else 0
    finally:
        if root is not None:
            for m in ("opt", "proc"):
                subprocess.run(["umount", "-l", str(root / m)], stderr=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
