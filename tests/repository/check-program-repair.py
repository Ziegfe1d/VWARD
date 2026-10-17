#!/usr/bin/env python3
"""Housekeeping repairs an Entware program that crashes on a plain local task (a damaged copy,
Viva 2026-10-11): it reinstalls the package, at most once in 6 hours, and logs it. A program that
only fails (no crash) or does not exist is left alone. curl noted as crashing on HTTPS (libnghttp2,
Viva 2026-10-12) gets its HTTP/2 library and the certificates reinstalled, at most once a day,
without a test run first (each is one more crash). Smart DNS's DoH client noted as failing: its
packages are checked against the same version in Entware and only a damaged one is reinstalled
(the USB stick spoiled libcares, Viva 2026-10-17), with a copy first and a note for the owner;
intact files are not reinstalled; curl is not marked for it."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "components/runtime/scripts/vward-housekeeping.sh"


def fail(message: str) -> None:
    raise SystemExit(f"PROGRAM_REPAIR=FAIL: {message}")


busybox = shutil.which("busybox")
if not busybox:
    fail("busybox is needed")
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    r = t / "root"
    for d in ("opt/var/log/vward", "opt/var/backups/vward", "tmp", "opt/var/spool/cron/crontabs"):
        (r / d).mkdir(parents=True)
    # curl crashes until opkg reinstalls it; jq fails without crashing; no openssl at all.
    (t / "curl").write_text(f'#!/bin/sh\necho run >> "{t}/curl.runs"\n[ -e "{t}/fixed" ] && exit 0\nkill -SEGV $$\n')
    (t / "jq").write_text("#!/bin/sh\nexit 5\n")
    (t / "opkg").write_text(f'#!/bin/sh\necho "$*" >> "{t}/opkg.log"\n: > "{t}/fixed"\n')
    for f in ("curl", "jq", "opkg"):
        (t / f).chmod(0o755)
    stub = t / "admission.sh"
    stub.write_text("vward_admission_enter() { :; }\nvward_admission_leave() { :; }\nvward_defer() { return 1; }\nvward_off() { return 0; }\n")
    env = os.environ | {"VWARD_ROOT_PREFIX": str(r), "VWARD_ADMISSION_LIB": str(stub), "VWARD_CONSOLE_CONFIG_BIN": str(t / "none"),
                        "VWARD_CRONTAB": str(t / "none"), "VWARD_OPKG_BIN": str(t / "opkg"), "VWARD_REPAIR_CURL": str(t / "curl"),
                        "VWARD_REPAIR_JQ": str(t / "jq"), "VWARD_REPAIR_OPENSSL": str(t / "no-openssl"), "VWARD_SENTINEL_CTL": str(t / "none"),
                        "VWARD_TLS_BROKEN_FLAG": str(t / "tls.broken"), "VWARD_REPAIR_HTTPS_URL": "https://example.invalid/",
                        "VWARD_DOH_BROKEN_FLAG": str(t / "doh.broken"), "VWARD_CA_BUNDLE": str(t / "no-ca")}

    def run() -> str:
        res = subprocess.run([busybox, "sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            fail(f"housekeeping failed: {res.stderr[-300:]}")
        log = r / "opt/var/log/vward-housekeeping.log"
        return log.read_text() if log.exists() else ""

    log = run()
    opkg = (t / "opkg.log").read_text().splitlines() if (t / "opkg.log").exists() else []
    if opkg != ["install --force-reinstall curl"]:
        fail(f"only the crashing curl is reinstalled: {opkg}")
    if "repair=curl|crash=139|reinstalled=curl|opkg=0|after=0" not in log:
        fail(f"the repair and its outcome are logged: {log}")
    # Crashes again within 6 hours: logged, not reinstalled again.
    (t / "fixed").unlink()
    log = run()
    if len((t / "opkg.log").read_text().splitlines()) != 1 or "repair=curl|crash=139|next_try_later" not in log:
        fail("a second reinstall within 6 hours")
    # A curl that works is not touched (two tries each run at most).
    (t / "fixed").write_text("")
    (r / "opt/var/lib/vward/repair/curl").write_text("0\n")
    runs = len((t / "curl.runs").read_text().splitlines())
    run()
    if len((t / "opkg.log").read_text().splitlines()) != 1 or len((t / "curl.runs").read_text().splitlines()) != runs + 1:
        fail("a working curl is run once and left alone")

    # curl crashes only on HTTPS (libnghttp2, Viva 2026-10-12): the local check passes, vward_fetch
    # noted the crash; the HTTP/2 library, curl and the certificates are reinstalled at once, one
    # HTTPS try after, and the note goes when it works.
    (t / "curl").write_text(f'#!/bin/sh\ncase "$*" in *https://*) echo "$*" >> "{t}/curl.https"; [ -e "{t}/h2fixed" ] || kill -SEGV $$ ;; esac\nexit 0\n')
    (t / "opkg").write_text(f'#!/bin/sh\necho "$*" >> "{t}/opkg.log"\ncase "$*" in install*) : > "{t}/h2fixed" ;; esac\n')
    (t / "tls.broken").write_text("")
    log = run()
    if (t / "opkg.log").read_text().splitlines()[-1] != "install --force-reinstall libnghttp2 libcurl curl ca-bundle":
        fail(f"curl crashing on HTTPS: its HTTP/2 library and the certificates are not reinstalled: {(t / 'opkg.log').read_text()}")
    if "repair=curl-https|reinstalled=libnghttp2,libcurl,curl,ca-bundle|opkg=0|after=0" not in log or (t / "tls.broken").exists():
        fail(f"the HTTPS repair is not logged, or curl is not trusted again: {log[-300:]}")
    if len((t / "curl.https").read_text().splitlines()) != 1:
        fail(f"no HTTPS try before the reinstall (one more crash), one after: {(t / 'curl.https').read_text()}")
    # Crashes again within the day: not reinstalled again, curl not run on HTTPS by the repair.
    (t / "h2fixed").unlink(); (t / "tls.broken").write_text(""); (t / "curl.https").unlink()
    n = len((t / "opkg.log").read_text().splitlines())
    run()
    if len((t / "opkg.log").read_text().splitlines()) != n or (t / "curl.https").exists() or not (t / "tls.broken").exists():
        fail("the HTTPS repair repeats within the day")
    (t / "tls.broken").unlink()
    # No note of an HTTPS crash: nothing is reinstalled for HTTPS.
    run()
    if len((t / "opkg.log").read_text().splitlines()) != n:
        fail("HTTPS repair without a crash noted")
    # Smart DNS's DoH client kept failing: its packages are checked against Entware; only the
    # damaged one (libcares) is reinstalled, after a copy; the owner is told; curl untouched.
    import tarfile, io
    feed = t / "feed"; feed.mkdir()
    good = {"https-dns-proxy": {"opt/sbin/https-dns-proxy": b"client v1", "opt/etc/config/https-dns-proxy": b"defaults"},
            "libcares": {"opt/lib/libcares.so.2.19.5": b"cares good"}}
    for pkg, files in good.items():
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as tf:
            for name, body in files.items():
                ti = tarfile.TarInfo("./" + name); ti.size = len(body); tf.addfile(ti, io.BytesIO(body))
        with tarfile.open(feed / f"{pkg}_1.0-1_mipsel-3.4.ipk", "w:gz") as tf:
            ti = tarfile.TarInfo("./data.tar.gz"); ti.size = len(data.getvalue()); tf.addfile(ti, io.BytesIO(data.getvalue()))
        for name, body in files.items():
            (r / name).parent.mkdir(parents=True, exist_ok=True)
            (r / name).write_bytes(body)
    (r / "opt/etc/config/https-dns-proxy").write_bytes(b"owner's own settings")  # not compared
    (r / "opt/lib/libcares.so.2.19.5").write_bytes(b"cares SPOILED")
    (t / "opkg").write_text(f"""#!/bin/sh
echo "$*" >> "{t}/opkg.log"
case "$1" in
list-installed) case "$2" in https-dns-proxy|libcares) echo "$2 - 1.0-1" ;; esac ;;
download) cp "{feed}/$2"_*.ipk . 2>/dev/null ;;
files) case "$2" in libcares) echo "Package libcares (1.0-1) is installed on root and has the following files:"; echo /opt/lib/libcares.so.2.19.5 ;; esac ;;
install) [ "$3" = libcares ] && printf 'cares good' > "{r}/opt/lib/libcares.so.2.19.5" ;;
esac
""")
    notes = t / "notes"
    env = env | {"VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"), "VWARD_CONSOLE_NOTES": str(notes),
                 "VWARD_DOH_PKGS": "https-dns-proxy libcares libev"}
    (t / "doh.broken").write_text("")
    log = run()
    ops = (t / "opkg.log").read_text().splitlines()[n:]
    installs = [o for o in ops if o.startswith("install")]
    if installs != ["install --force-reinstall libcares"] or (t / "doh.broken").exists():
        fail(f"only the damaged library is reinstalled: {ops}")
    if "repair=doh|damaged=libcares|reinstalled|opkg=0|still_damaged=|copy=" not in log or "copy=none" in log:
        fail(f"the DoH repair is not logged with a copy: {log[-300:]}")
    copies = list((r / "opt/var/lib/vward/repair").glob("doh-*.tar.gz"))
    if len(copies) != 1 or b"SPOILED" not in __import__("gzip").open(copies[0]).read():
        fail("the damaged files are not copied before the reinstall")
    if "Флешка портит файлы программ" not in (notes / "notes.tsv").read_text():
        fail("the owner is not told that the stick spoils files")
    if any("curl" in o for o in installs):
        fail("curl is touched for the DoH client")
    # Within the day: not again. A day later with intact files: checked, nothing reinstalled.
    m = len((t / "opkg.log").read_text().splitlines())
    (t / "doh.broken").write_text("")
    run()
    if len((t / "opkg.log").read_text().splitlines()) != m:
        fail("the DoH repair repeats within the day")
    (r / "opt/var/lib/vward/repair/doh").write_text("0\n")
    log = run()
    if any(o.startswith("install") for o in (t / "opkg.log").read_text().splitlines()[m:]) or "repair=doh|files=intact" not in log:
        fail(f"intact files are reinstalled: {log[-200:]}")

print("PROGRAM_REPAIR=PASS")
