#!/bin/sh
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
LIB=$ROOT/components/runtime/lib/vward-routing-audit.sh
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
[ -f "$LIB" ] || fail 'missing routing audit library (expected RED)'
TMP=$(mktemp -d "${TMPDIR:-/tmp}/vward-routing-audit.XXXXXX")
trap 'rm -rf "$TMP"' 0
trap 'exit 1' INT TERM
# shellcheck disable=SC1090 # Runtime path is the library under test.
. "$LIB"
check() {
    vward_routing_audit "$TMP/intents" "$TMP/snapshot" > "$TMP/actual" || fail "$1 rc"
    cmp -s "$TMP/expected" "$TMP/actual" || {
        diff -u "$TMP/expected" "$TMP/actual" >&2 || :
        fail "$1 output"
    }
}
snapshot() {
    printf 'snapshot\tg1\tknown\nsource\tM\t%s\tknown\nsource\tS\t%s\tknown\nsource\tA\t%s\tknown\nhealth\tDNS\tavailable\nhealth\tAGH\tavailable\nhealth\tVPN:tun1\tavailable\n' "$1" "$2" "$3" > "$TMP/snapshot"
}
expect() {
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\tg1\tunknown\n' "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10:--}" > "$TMP/expected"
}
cat > "$TMP/combinations" <<'CASES'
000|-|-|0|inactive|no-active-intent
001|A:a|exact@VPN:tun1@default|0|review|new-coverage-needed
010|S:s|exact@VPN:tun1@default|0|review|new-coverage-needed
011|A:a,S:s|exact@VPN:tun1@default|1|review|new-coverage-needed
100|M:m|exact@VPN:tun1@default|0|review|new-coverage-needed
101|A:a,M:m|exact@VPN:tun1@default|1|review|new-coverage-needed
110|M:m,S:s|exact@VPN:tun1@default|1|review|new-coverage-needed
111|A:a,M:m,S:s|exact@VPN:tun1@default|2|review|new-coverage-needed
CASES
printf 'M\tm\tx.example\texact\tVPN:tun1\tdefault\t1\nS\ts\tx.example\texact\tVPN:tun1\tdefault\t1\nA\ta\tx.example\texact\tVPN:tun1\tdefault\t1\n' > "$TMP/intents"
combination() {
    while IFS='|' read -r mask active wanted dup decision reason; do
        [ "$mask" = "$1" ] || continue
        bits=$(printf '%s' "$mask" | sed 's/./& /g')
        # Deliberate splitting of the three literal binary digits.
        # shellcheck disable=SC2086
        snapshot $bits
        expect x.example A:a,M:m,S:s "$active" "$wanted" - - "$dup" "$decision" "$reason"
        check "combination $mask"
        return
    done < "$TMP/combinations"
    fail "missing combination $1"
}
while IFS='|' read -r mask rest; do combination "$mask"; done < "$TMP/combinations"
printf 'PASS: all 8 source combinations\n'
cat > "$TMP/transitions" <<'CASES'
000 100
000 010
000 001
001 101
001 011
001 000
010 110
010 000
010 011
011 111
011 001
011 010
100 000
100 110
100 101
101 001
101 111
101 100
110 010
110 100
110 111
111 011
111 101
111 110
CASES
before=$(cksum "$TMP/intents")
while read -r from to; do combination "$from"; combination "$to"; combination "$to"; done < "$TMP/transitions"
[ "$(cksum "$TMP/intents")" = "$before" ] || fail 'transitions changed intent'
printf 'PASS: all 24 directed transitions and repeat idempotence\n'
snapshot 1 1 1
printf 'route\tr\tx.example\texact\tVPN:tun1\tdefault\tmanual\treference\n' >> "$TMP/snapshot"
expect x.example A:a,M:m,S:s A:a,M:m,S:s exact@VPN:tun1@default r@exact@VPN:tun1@default r@manual@reference 2 covered reuse-existing-coverage
check manual
cat "$TMP/intents" >> "$TMP/intents.copy"
cat "$TMP/intents.copy" >> "$TMP/intents"
check 'duplicate rows are idempotent'
printf 'S\tunselected\tx.example\texact\tISP\tother\t0\n' >> "$TMP/intents"
expect x.example A:a,M:m,S:s,S:unselected A:a,M:m,S:s exact@VPN:tun1@default r@exact@VPN:tun1@default r@manual@reference 2 covered reuse-existing-coverage
check 'unselected service ignored'
sed 's/manual\treference/unknown\treference/' "$TMP/snapshot" > "$TMP/other"
mv "$TMP/other" "$TMP/snapshot"
expect x.example A:a,M:m,S:s,S:unselected A:a,M:m,S:s exact@VPN:tun1@default r@exact@VPN:tun1@default r@unknown@reference 2 covered reuse-existing-coverage
check 'unknown ownership is reference'
sed 's/unknown\treference/vward\tmanaged/' "$TMP/snapshot" > "$TMP/other"
mv "$TMP/other" "$TMP/snapshot"
expect x.example A:a,M:m,S:s,S:unselected A:a,M:m,S:s exact@VPN:tun1@default r@exact@VPN:tun1@default r@vward@managed 2 covered reuse-existing-coverage
check 'explicit managed evidence'
for target_dns in 'ISP default' 'VPN:tun2 default' 'VPN:tun1 smartdns'; do
    # shellcheck disable=SC2086
    set -- $target_dns
    snapshot 1 1 1
    printf 'route\tr\tx.example\texact\t%s\t%s\tmanual\treference\n' "$1" "$2" >> "$TMP/snapshot"
    expect x.example A:a,M:m,S:s,S:unselected A:a,M:m,S:s exact@VPN:tun1@default "r@exact@$1@$2" r@manual@reference 2 unresolved conflicting-target-or-dns
    check "observed conflict $target_dns"
done
snapshot 1 1 1
printf 'M\tm\tx.example\texact\tISP\tdefault\t1\nS\ts\tx.example\texact\tVPN:tun1\tdefault\t1\n' > "$TMP/intents"
expect x.example M:m,S:s M:m,S:s exact@ISP@default,exact@VPN:tun1@default - - 0 unresolved conflicting-target-or-dns
check 'intent conflict remains unresolved'
printf 'A\ta\tx.example\texact\tVPN:tun1\tdefault\t1\n' > "$TMP/intents"
for dep in DNS AGH VPN:tun1; do
    for state in unavailable unknown; do
        snapshot 0 0 1
        sed "s/health$(printf '\t')$dep$(printf '\t')available/health$(printf '\t')$dep$(printf '\t')$state/" "$TMP/snapshot" > "$TMP/other"
        mv "$TMP/other" "$TMP/snapshot"
        case $state in unavailable) decision=blocked; reason=dependency-unavailable;; unknown) decision=unknown; reason=dependency-unknown;; esac
        expect x.example A:a A:a exact@VPN:tun1@default - - 0 "$decision" "$reason" "$dep:$state"
        check "$dep $state"
    done
done
snapshot 0 0 1
sed '/health.*VPN:/d' "$TMP/snapshot" > "$TMP/other"
mv "$TMP/other" "$TMP/snapshot"
expect x.example A:a A:a exact@VPN:tun1@default - - 0 unknown dependency-unknown VPN:tun1:unknown
check 'absent VPN health is unknown'
for pattern in 'snapshot\tg1\tknown' 'source\tA\t1\tknown'; do
    snapshot 0 0 1
    sed "s/$pattern/$(printf '%b' "$pattern" | sed 's/known$/unknown/')/" "$TMP/snapshot" > "$TMP/other"
    mv "$TMP/other" "$TMP/snapshot"
    case $pattern in snapshot*) issue=snapshot:unknown;; *) issue=source:A:unknown;; esac
    expect x.example A:a A:a exact@VPN:tun1@default - - 0 unknown snapshot-or-source-unknown "$issue"
    check 'unknown snapshot or enabled source'
done
snapshot 0 0 1
sed -e 's/health\tDNS\tavailable/health\tDNS\tunavailable/' -e 's/health\tAGH\tavailable/health\tAGH\tunknown/' -e '/health.*VPN:/d' "$TMP/snapshot" > "$TMP/other"
mv "$TMP/other" "$TMP/snapshot"
printf 'route\tr\tx.example\texact\tISP\tdefault\tmanual\treference\n' >> "$TMP/snapshot"
expect x.example A:a A:a exact@VPN:tun1@default r@exact@ISP@default r@manual@reference 0 unresolved conflicting-target-or-dns AGH:unknown,DNS:unavailable,VPN:tun1:unknown
check 'conflict preserves every health issue'
snapshot 0 0 1
sed 's/source\tM\t0\tknown/source\tM\t0\tunknown/' "$TMP/snapshot" > "$TMP/other"
mv "$TMP/other" "$TMP/snapshot"
expect x.example A:a A:a exact@VPN:tun1@default - - 0 review new-coverage-needed
check 'disabled unknown source does not block active source'
snapshot 1 0 0
: > "$TMP/intents"
vward_routing_audit "$TMP/intents" "$TMP/snapshot" > "$TMP/actual" || fail 'empty manual rc'
[ ! -s "$TMP/actual" ] || fail 'empty manual output'
printf 'route\tr\tx.example\texact\tISP\tdefault\tmanual\treference\n' >> "$TMP/snapshot"
expect x.example - - - r@exact@ISP@default r@manual@reference 0 inactive no-active-intent
check 'external routes remain visible with no active intent'
sed 's/source\tM\t1/source\tM\t0/' "$TMP/snapshot" > "$TMP/other"
mv "$TMP/other" "$TMP/snapshot"
check 'all sources off preserve manual route visibility'
printf 'PASS: duplicates, ownership, conflicts, health, empty manual\n'
# Literal expectations for partial/apex/subdomain coverage, no reverse matching.
snapshot 0 1 0
printf 'S\ts\tx.example\tsubtree\tVPN:tun1\tdefault\t1\nA\ta\tchild.x.example\texact\tVPN:tun1\tdefault\t0\n' > "$TMP/intents"
printf 'route\tr\tx.example\texact\tVPN:tun1\tdefault\tmanual\treference\n' >> "$TMP/snapshot"
{
    printf 'child.x.example\tA:a\tS:s\tsubtree@VPN:tun1@default\t-\t-\t0\treview\tnew-coverage-needed\t-\tg1\tunknown\n'
    printf 'x.example\tS:s\tS:s\tsubtree@VPN:tun1@default\tr@exact@VPN:tun1@default\tr@manual@reference\t0\treview\tnew-coverage-needed\t-\tg1\tunknown\n'
} > "$TMP/expected"
check 'exact apex does not cover subtree'
sed 's/\texact\t/\tsubtree\t/' "$TMP/snapshot" > "$TMP/other"
mv "$TMP/other" "$TMP/snapshot"
{
    printf 'child.x.example\tA:a\tS:s\tsubtree@VPN:tun1@default\tr@subtree@VPN:tun1@default\tr@manual@reference\t0\tcovered\treuse-existing-coverage\t-\tg1\tunknown\n'
    printf 'x.example\tS:s\tS:s\tsubtree@VPN:tun1@default\tr@subtree@VPN:tun1@default\tr@manual@reference\t0\tcovered\treuse-existing-coverage\t-\tg1\tunknown\n'
} > "$TMP/expected"
check 'subtree parent covers child'
awk '{a[NR]=$0} END {for(i=NR;i;i--) print a[i]}' "$TMP/intents" > "$TMP/other"
mv "$TMP/other" "$TMP/intents"
awk '{a[NR]=$0} END {for(i=NR;i;i--) print a[i]}' "$TMP/snapshot" > "$TMP/other"
mv "$TMP/other" "$TMP/snapshot"
check 'input-order determinism'
reject() {
    if vward_routing_audit "$TMP/intents" "$TMP/snapshot" > "$TMP/actual" 2> "$TMP/error"; then fail "$1 accepted"; else rc=$?; fi
    [ "$rc" -eq 2 ] || fail "$1 incorrect rc $rc"
    [ ! -s "$TMP/actual" ] || fail "$1 partial stdout"
    [ -s "$TMP/error" ] || fail "$1 no diagnostic"
}
cp "$TMP/intents" "$TMP/good-intents"
cp "$TMP/snapshot" "$TMP/good-snapshot"
for bad in 'S\ts\tUPPER.example\texact\tISP\tdefault\t1' 'S\ts\tx.example\texact\tISP\tdefault\t2' 'S\ts\tx.example\twildcard\tISP\tdefault\t1' 'X\ts\tx.example\texact\tISP\tdefault\t1' 'S\ts\tx..example\texact\tISP\tdefault\t1' 'S\ts\tx.example\texact\tISP\tdefault\t1\textra' 'S\ts\t-bad.example\texact\tISP\tdefault\t1' 'S\ts\tx.example\texact\tVPN:\tdefault\t1'; do
    cp "$TMP/good-intents" "$TMP/intents"
    printf '%b\n' "$bad" >> "$TMP/intents"
    reject malformed-intent
done
cp "$TMP/good-intents" "$TMP/intents"
for bad in 'source\tM\t1\tknown' 'route\tr\tx.example\tsubtree\tISP\tdefault\tmanual\tmanaged' 'snapshot\tg2\tknown' 'health\tDNS\tbroken' 'unknown\tfield'; do
    cp "$TMP/good-snapshot" "$TMP/snapshot"
    printf '%b\n' "$bad" >> "$TMP/snapshot"
    reject malformed-snapshot
done
cp "$TMP/good-snapshot" "$TMP/snapshot"
sed '/source.*M/d' "$TMP/snapshot" > "$TMP/other"
mv "$TMP/other" "$TMP/snapshot"
reject missing-source
cp "$TMP/good-snapshot" "$TMP/snapshot"
if vward_routing_audit "$TMP/missing" "$TMP/snapshot" > "$TMP/actual" 2> "$TMP/error"; then fail missing-file; fi
[ ! -s "$TMP/actual" ] || fail 'missing file partial stdout'
# Source-load and runtime purity: mutating/probing command names would fail.
mkdir "$TMP/empty"
# shellcheck disable=SC2123,SC1090 # Deliberately remove commands during source-load.
(cd "$TMP/empty"; PATH=/nonexistent; . "$LIB") || fail 'source-load executes command'
[ -z "$(ls -A "$TMP/empty")" ] || fail 'source-load writes'
# Limits reject atomically even when every preceding row was valid.
cp "$TMP/good-snapshot" "$TMP/snapshot"
awk 'BEGIN {for(i=1;i<=4097;i++) print "S\ts\tx.example\texact\tISP\tdefault\t1"}' > "$TMP/intents"
reject line-limit
awk 'BEGIN {for(i=1;i<=1025;i++) print "S\ts" i "\td" i ".example\texact\tISP\tdefault\t1"}' > "$TMP/intents"
reject domain-limit
awk 'BEGIN {a=""; b=""; for(i=1;i<=63;i++) a=a "a"; for(i=1;i<=64;i++) b=b "b"; for(i=1;i<=3000;i++) print "S\t" b "\t" a "." a "." a ".example\texact\tVPN:" b "\t" b "\t1"}' > "$TMP/intents"
reject byte-limit
cp "$TMP/good-intents" "$TMP/intents"
# Only awk is available while evaluating. Unexpected commands leave stderr;
# input checksums and a clean cwd detect file changes as well as new files.
mkdir "$TMP/pure-bin"
ln -s "$(command -v awk)" "$TMP/pure-bin/awk"
input_before=$(cksum "$TMP/intents" "$TMP/snapshot")
# shellcheck disable=SC2123 # Deliberately expose only awk to the pure evaluator.
(cd "$TMP/empty"; PATH=$TMP/pure-bin; vward_routing_audit "$TMP/intents" "$TMP/snapshot") > "$TMP/actual" 2> "$TMP/error" || fail 'restricted command surface'
[ ! -s "$TMP/error" ] || fail 'audit ran unexpected command'
[ -z "$(ls -A "$TMP/empty")" ] || fail 'audit wrote files'
[ "$(cksum "$TMP/intents" "$TMP/snapshot")" = "$input_before" ] || fail 'audit changed inputs'
printf 'PASS: scope, order, malformed input, bounds, load/call purity\n' 
printf 'ROUTING_AUDIT_SIMULATIONS=PASS\n'
