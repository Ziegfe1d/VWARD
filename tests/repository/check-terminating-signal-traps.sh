#!/bin/sh
set -u

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/vward-signal-traps.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
trap 'exit 1' HUP INT TERM

fail(){ echo "FAIL: $*" >&2; exit 1; }

FILES="$(find "$ROOT/components" "$ROOT/web/cgi-bin" -type f \
    \( -name '*.sh' -o -name '*.cgi' -o -path '*/init.d/*' \) | sort)"

BAD="$WORK/combined-traps.txt"
: > "$BAD"
for FILE in $FILES; do
    awk '
        /trap / && /EXIT|[[:space:]]0([[:space:]]|$)/ && /INT|TERM|HUP|[[:space:]][12]([[:space:]]|$)|[[:space:]]15([[:space:]]|$)/ {
            print FILENAME ":" FNR ":" $0
        }
    ' "$FILE" >> "$BAD"
done

[ ! -s "$BAD" ] || {
    cat "$BAD" >&2
    fail "cleanup and terminating signals share a trap; caught signals can resume execution"
}

# Prove the required shell behavior: signal handler exits, then EXIT cleanup
# runs exactly once, and protected work after the signal is never reached.
cat > "$WORK/probe.sh" <<'SH'
#!/bin/sh
cleanup(){ echo CLEANUP; }
trap cleanup EXIT
trap 'exit 73' HUP INT TERM
kill -TERM "$$"
echo CONTINUED
SH

PROBE_OUT="$(sh "$WORK/probe.sh" 2>&1)"
PROBE_RC=$?
[ "$PROBE_RC" -eq 73 ] || fail "terminating signal probe rc=$PROBE_RC"
[ "$PROBE_OUT" = CLEANUP ] || fail "terminating signal probe continued or cleaned incorrectly: $PROBE_OUT"

echo TERMINATING_SIGNAL_TRAPS=PASS
