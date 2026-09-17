#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
TMP="${TMPDIR:-/tmp}/vward-archive-safety-test.$$"
trap 'rm -rf "$TMP"' EXIT INT TERM
mkdir -p "$TMP"

fail(){ echo "FAIL: $*" >&2; exit 1; }

make_fixtures()
{
    python3 - "$TMP" <<'PY'
import io, os, tarfile, sys
root = sys.argv[1]
with tarfile.open(os.path.join(root, "safe.tar.gz"), "w:gz") as tf:
    data = b"example.com\n"
    info = tarfile.TarInfo("catalog/domains.lst")
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))
with tarfile.open(os.path.join(root, "traversal.tar.gz"), "w:gz") as tf:
    data = b"escape\n"
    info = tarfile.TarInfo("../escape.txt")
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))
with tarfile.open(os.path.join(root, "absolute.tar.gz"), "w:gz") as tf:
    data = b"absolute\n"
    info = tarfile.TarInfo("/opt/etc/vward-escape.txt")
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))
with tarfile.open(os.path.join(root, "symlink.tar.gz"), "w:gz") as tf:
    info = tarfile.TarInfo("catalog/link")
    info.type = tarfile.SYMTYPE
    info.linkname = "/opt/etc/passwd"
    tf.addfile(info)
with tarfile.open(os.path.join(root, "hardlink.tar.gz"), "w:gz") as tf:
    info = tarfile.TarInfo("catalog/hardlink")
    info.type = tarfile.LNKTYPE
    info.linkname = "catalog/domains.lst"
    tf.addfile(info)
with tarfile.open(os.path.join(root, "fifo.tar.gz"), "w:gz") as tf:
    info = tarfile.TarInfo("catalog/fifo")
    info.type = tarfile.FIFOTYPE
    tf.addfile(info)
with tarfile.open(os.path.join(root, "large.tar.gz"), "w:gz") as tf:
    data = b"x" * 4096
    info = tarfile.TarInfo("catalog/large.lst")
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))
with tarfile.open(os.path.join(root, "many.tar.gz"), "w:gz") as tf:
    for index in range(3):
        info = tarfile.TarInfo(f"catalog/{index}.lst")
        info.size = 0
        tf.addfile(info, io.BytesIO())
PY
}

check_script()
{
    script="$1"; name="$2"; harness="$TMP/$name-functions.sh"
    sed -n '/^download()/,/^}/p; /^fetch()/,/^}/p; /^archive_validate()/,/^}/p; /^extract_archive()/,/^}/p' "$script" > "$harness"
    grep -q '^archive_validate()' "$harness" || fail "$name has no archive validator"
    grep -q '^extract_archive()' "$harness" || fail "$name has no extractor"

    mkdir -p "$TMP/$name-safe" "$TMP/$name-bad" "$TMP/$name-link"
    sh -c '. "$1"; extract_archive "$2" "$3"' sh "$harness" "$TMP/safe.tar.gz" "$TMP/$name-safe" || fail "$name rejects safe archive"
    [ -f "$TMP/$name-safe/catalog/domains.lst" ] || fail "$name did not extract safe member"
    if sh -c '. "$1"; archive_validate "$2" "$3"' sh "$harness" "$TMP/traversal.tar.gz" "$TMP/$name-bad"; then fail "$name accepts traversal archive"; fi
    [ ! -e "$TMP/escape.txt" ] || fail "$name wrote outside staging"
    if sh -c '. "$1"; archive_validate "$2" "$3"' sh "$harness" "$TMP/absolute.tar.gz" "$TMP/$name-bad"; then fail "$name accepts absolute path"; fi
    if sh -c '. "$1"; archive_validate "$2" "$3"' sh "$harness" "$TMP/symlink.tar.gz" "$TMP/$name-link"; then fail "$name accepts symlink archive"; fi
    [ ! -L "$TMP/$name-link/catalog/link" ] || fail "$name extracted symlink"
    if sh -c '. "$1"; archive_validate "$2" "$3"' sh "$harness" "$TMP/hardlink.tar.gz" "$TMP/$name-bad"; then fail "$name accepts hardlink archive"; fi
    if sh -c '. "$1"; archive_validate "$2" "$3"' sh "$harness" "$TMP/fifo.tar.gz" "$TMP/$name-bad"; then fail "$name accepts special entry"; fi
    if MAX_SOURCE_UNPACKED_BYTES=1024 sh -c '. "$1"; archive_validate "$2" "$3"' sh "$harness" "$TMP/large.tar.gz" "$TMP/$name-bad"; then fail "$name accepts oversized unpacked archive"; fi
    if MAX_SOURCE_ARCHIVE_ENTRIES=2 sh -c '. "$1"; archive_validate "$2" "$3"' sh "$harness" "$TMP/many.tar.gz" "$TMP/$name-bad"; then fail "$name accepts excessive entries"; fi

    mkdir -p "$TMP/fake-bin"
    cat > "$TMP/fake-bin/curl" <<'SH'
#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; *) shift;; esac; done
dd if=/dev/zero of="$out" bs=1024 count=8 2>/dev/null
SH
    chmod +x "$TMP/fake-bin/curl"
    fetch_fn=download; grep -q '^fetch()' "$harness" && fetch_fn=fetch
    if PATH="$TMP/fake-bin:$PATH" MAX_SOURCE_ARCHIVE_BYTES=1024 sh -c '. "$1"; "$2" http://invalid.test/archive "$3"' sh "$harness" "$fetch_fn" "$TMP/$name-download"; then fail "$name accepts oversized download"; fi
    size="$(wc -c < "$TMP/$name-download" 2>/dev/null || echo 0)"
    [ "$size" -le 1024 ] || fail "$name download limit is not enforced during transfer"
}

make_fixtures
check_script "$ROOT/components/policy-sync/scripts/vward-policy-sync.sh" policy-sync
check_script "$ROOT/components/route-tools/scripts/vward-route-hints-update.sh" route-hints
echo EXTERNAL_ARCHIVE_SAFETY=PASS
