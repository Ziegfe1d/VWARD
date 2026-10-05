#!/bin/sh

# The emergency switch: VWARD steps aside and the router works as a plain Keenetic,
# for the day VWARD itself is broken.
#
#   vward-off.sh [off]   VWARD off: its services stop, its routes into the tunnels and
#                        AdGuard Home's place in Keenetic's DNS go out of the router
#                        (remembered for «on»), its DNS redirects go out of the firewall.
#                        Files and settings stay where they are; the Panel keeps running
#                        so VWARD can be switched on again from it.
#   vward-off.sh on      everything back as it was, VWARD running again
#   vward-off.sh status  state=on|off and what was taken out
#   vward-off.sh keep    (the cron supervisor, every minute while off) DNS redirects into
#                        AdGuard Home that Keenetic or another program put back go out again
#
# Works with VWARD's own parts broken: only the shell, BusyBox, ndmc and iptables.
# The routes and lines taken out are written down before they go, so «on» always has
# them, a power cut in between included. AdGuard Home's line stays when Keenetic has no
# other DNS that answers: the home must never be left without DNS.

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

STATE_DIR=${VWARD_COMPONENT_STATE:-/opt/etc/vward/components}
FLAG=$STATE_DIR/vward.off
SAVED=$STATE_DIR/vward.off.removed
PARKED=$STATE_DIR/vward.off.iptables
STATUS=$STATE_DIR/vward.off.status
LOCK=${VWARD_OFF_LOCK:-/tmp/vward-off.lock}
LOG=${VWARD_OFF_LOG:-/opt/var/log/vward-off.log}
NDMC=${VWARD_NDMC:-ndmc}
IPT=${VWARD_IPTABLES:-/opt/sbin/iptables}
NSLOOKUP=${VWARD_NSLOOKUP:-nslookup}
PROBE_HOST=${VWARD_OFF_PROBE_HOST:-example.com}
INIT_DIR=${VWARD_INIT_DIR:-/opt/etc/init.d}
BIN_DIR=${VWARD_BIN_DIR:-/opt/bin}
# Keenetic's names of the connections a route can send traffic into a VPN through. PPTP
# and L2TP are left out: at some providers they are the internet connection itself.
TUNNEL_RE='^(Wireguard|OpkgTun|Proxy|OpenVPN|SSTP|IKE|IPSec|Vpn)[0-9]+$'

[ -x "$IPT" ] || IPT=iptables
ipt() { "$IPT" "$@" 2>/dev/null; }

log() { mkdir -p "${LOG%/*}" 2>/dev/null; echo "$(date '+%Y-%m-%d %H:%M:%S')|$*" >> "$LOG" 2>/dev/null; }

ndm() {
    nd_out=$("$NDMC" -c "$1" 2>&1) || return 1
    ! printf '%s\n' "$nd_out" | grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command)'
}

lock_take() {
    n=0
    until mkdir "$LOCK" 2>/dev/null; do
        old=$(cat "$LOCK/pid" 2>/dev/null)
        if [ -n "$old" ] && ! kill -0 "$old" 2>/dev/null; then rm -rf "${LOCK:?}"; continue; fi
        n=$((n + 1)); [ "$n" -lt 30 ] || { echo "result=busy"; exit 75; }
        sleep 1
    done
    echo $$ > "$LOCK/pid"
    trap 'rm -f "$RC" "$RC.cmds"; rm -rf "${LOCK:?}"' EXIT
    trap 'exit 1' HUP INT TERM
}

status_write() { { echo "state=$1"; shift; for kv in "$@"; do echo "$kv"; done; } > "$STATUS.tmp" && mv -f "$STATUS.tmp" "$STATUS"; }

# The running configuration in a root-only file: it holds the tunnels' keys, never printed.
RC=
read_config() {
    [ -n "$RC" ] || RC=$(mktemp /tmp/vward-off.XXXXXX) || return 1
    "$NDMC" -c "show running-config" 2>/dev/null | tr -d '\r' > "$RC" && [ -s "$RC" ]
}

# ---------------------------------------------------------------- the firewall
# VWARD's own jumps into its DNS chains, and redirects of port 53 into a port on the router
# that is not 53 (AdGuard Home), whoever put them there: «-A» lines, one per rule.
dns_rules() {
    ipt -t nat -S PREROUTING | grep -e '-j VWARD_DNS$' -e '-j VWARD_DNS '
    ipt -t nat -S PREROUTING | grep -e '--dport 53 ' | grep -e '-j REDIRECT --to-ports ' | grep -v -e '--to-ports 53$' | grep -v '"'
    ipt -t nat -S PREROUTING | grep -e '--dport 53 ' | grep -e '-j DNAT ' | grep -e '--to-destination [0-9.]*:[0-9]*' | grep -v -e ':53$' | grep -v '"'
}

dns_rules_off() {
    dr_found=$(dns_rules | awk 'NF && !s[$0]++')
    [ -n "$dr_found" ] || return 0
    # VWARD's own come back with VWARD («on»: its DNS guard); the others are written down.
    printf '%s\n' "$dr_found" | grep -v -e '-j VWARD_DNS' | {
        [ ! -r "$PARKED" ] || cat "$PARKED"; cat; } | awk 'NF && !s[$0]++' > "$PARKED.tmp" && mv -f "$PARKED.tmp" "$PARKED"
    printf '%s\n' "$dr_found" | while IFS= read -r r; do
        # shellcheck disable=SC2046
        ipt -t nat $(printf '%s' "$r" | sed 's/^-A /-D /')
    done
    ipt -S FORWARD | grep -e '-j VWARD_DNS_FWD' | while IFS= read -r r; do
        # shellcheck disable=SC2046
        ipt $(printf '%s' "$r" | sed 's/^-A /-D /')
    done
    log "DNS_REDIRECT_OFF|rules=$(printf '%s\n' "$dr_found" | grep -c .)"
}

dns_rules_back() {
    [ -s "$PARKED" ] || return 0
    while IFS= read -r r; do
        [ -n "$r" ] || continue
        # shellcheck disable=SC2046
        ipt -t nat $(printf '%s' "$r" | sed 's/^-A /-C /') ||
            ipt -t nat $(printf '%s' "$r" | sed 's/^-A PREROUTING /-I PREROUTING 1 /')
    done < "$PARKED"
    rm -f "$PARKED"
}

# ---------------------------------------------------------------- Keenetic's configuration
# What VWARD's routing puts into Keenetic, as the commands that put it back:
#   N dns-proxy route object-group GROUP TUNNEL ...   (lists of domains into a tunnel)
#   I ip route NET MASK TUNNEL ...                    (subnets into a tunnel)
#   D ip name-server ADDRESS:PORT ...                 (AdGuard Home in the DNS chain)
collect() {
    awk -v re="$TUNNEL_RE" '
        /^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)}
        /^!/ {ctx = 0}
        ctx && $1 == "route" && $2 == "object-group" && $4 ~ re {sub(/^[ \t]+/, ""); print "N dns-proxy " $0; next}
        $1 == "ip" && $2 == "route" && ($3 ~ /\// ? $4 : $5) ~ re {print "I " $0; next}
        $1 == "ip" && $2 == "name-server" && $3 ~ /:[0-9]+$/ && $3 !~ /:53$/ {print "D " $0}' "$RC"
}

# Keenetic's other DNS servers: one answers (the provider's, from DHCP or set by hand).
other_dns_answers() {
    od=$("$NDMC" -c "show ip name-server" 2>/dev/null | awk '$1 == "address:" {print $2}' |
        grep -E '^[0-9]+(\.[0-9]+){3}$' | grep -vxF -f "$1" | awk '!s[$0]++' | head -n 3)
    for a in $od; do
        "$NSLOOKUP" "$PROBE_HOST" "$a" 2>/dev/null | awk '/^Name:/ {f = 1} f && /^Address/ {n++} END {exit !n}' && return 0
    done
    return 1
}

undo_cmd() {
    # The command that takes a saved line out.
    # shellcheck disable=SC2086
    set -- $1
    case "$1" in
        dns-proxy) echo "dns-proxy no route object-group $4 $5" ;;
        ip) case "$2" in
                route) if [ "${3#*/}" != "$3" ]; then echo "no ip route $3 $4"; else echo "no ip route $3 $4 $5"; fi ;;
                name-server) echo "no ip name-server $3" ;;
            esac ;;
    esac
}

stop_services() {
    [ ! -x "$INIT_DIR/S91vward-route-engine" ] || "$INIT_DIR/S91vward-route-engine" stop </dev/null >/dev/null 2>&1
    [ ! -x "$BIN_DIR/vward-sentinel.sh" ] || "$BIN_DIR/vward-sentinel.sh" stop </dev/null >/dev/null 2>&1
    # VWARD's own tunnels: with their programs gone Keenetic stops sending into them at
    # once (their routes are «auto»), before the routes themselves are out.
    for e in vward-awg-engine.sh vward-vless-engine.sh; do
        [ ! -x "$BIN_DIR/$e" ] || "$BIN_DIR/$e" stop </dev/null >/dev/null 2>&1
    done
    [ ! -x "$BIN_DIR/vward-ads-privacy-https.sh" ] || "$BIN_DIR/vward-ads-privacy-https.sh" stop </dev/null >/dev/null 2>&1
    :
}

start_services() {
    [ ! -x "$INIT_DIR/S92vward-runtime" ] || "$INIT_DIR/S92vward-runtime" start </dev/null >/dev/null 2>&1
    [ ! -x "$INIT_DIR/S91vward-route-engine" ] || "$INIT_DIR/S91vward-route-engine" start </dev/null >/dev/null 2>&1
    [ ! -x "$BIN_DIR/vward-sentinel.sh" ] || "$BIN_DIR/vward-sentinel.sh" start </dev/null >/dev/null 2>&1
    [ ! -x "$BIN_DIR/vward-ads-privacy-dns-guard.sh" ] || "$BIN_DIR/vward-ads-privacy-dns-guard.sh" apply </dev/null >/dev/null 2>&1
    # The tunnels' programs and the guards: their minute's run, now rather than in a minute.
    [ ! -x "$BIN_DIR/vward-tunnel-health.sh" ] || ( "$BIN_DIR/vward-tunnel-health.sh" </dev/null >/dev/null 2>&1 & )
    :
}

op_off() {
    lock_take
    mkdir -p "$STATE_DIR" || { echo "result=failed"; echo "error=write_failed"; exit 1; }
    was=on; [ ! -e "$FLAG" ] || was=off
    # First of all: every VWARD job that starts from now on leaves at once.
    [ "$was" = off ] || echo "off since $(date '+%Y-%m-%dT%H:%M:%S%z') by ${VWARD_OFF_BY:-ssh}" > "$FLAG" ||
        { echo "result=failed"; echo "error=write_failed"; exit 1; }
    status_write working "op=off" "since=$(date +%s)"
    log "OFF_START|by=${VWARD_OFF_BY:-ssh}"
    stop_services
    dns_rules_off
    if ! read_config; then
        status_write off "since=$(date +%s)" "error=router_config_unavailable"
        log "OFF_DONE|router_config_unavailable"
        echo "result=partial"; echo "error=router_config_unavailable"; exit 1
    fi
    collect > "$RC.cmds"
    # AdGuard Home's DNS line goes only when another DNS of Keenetic answers.
    dns_kept=0
    if grep -q '^D ' "$RC.cmds"; then
        sed -n 's/^D ip name-server \([^ :]*\):.*/\1/p' "$RC.cmds" > "$RC.dns"
        if ! other_dns_answers "$RC.dns"; then
            grep -v '^D ' "$RC.cmds" > "$RC.keep"; mv -f "$RC.keep" "$RC.cmds"
            dns_kept=1
            log "OFF_DNS_KEPT|Keenetic has no other DNS that answers"
        fi
        rm -f "$RC.dns"
    fi
    # Written down before anything goes (appended: a second «off» keeps what the first took).
    if ! { [ ! -r "$SAVED" ] || cat "$SAVED"; sed 's/^[NID] //' "$RC.cmds"; } | awk 'NF && !s[$0]++' > "$SAVED.tmp" ||
       ! mv -f "$SAVED.tmp" "$SAVED"; then
        echo "result=failed"; echo "error=write_failed"; exit 1
    fi
    # DNS first, then the lists of domains (few), then the subnets (thousands).
    n_ok=0 n_fail=0
    for k in D N I; do
        grep "^$k " "$RC.cmds" | sed 's/^. //' | while IFS= read -r line; do
            c=$(undo_cmd "$line")
            [ -n "$c" ] || continue
            if ndm "$c"; then echo ok; else echo fail; log "OFF_REFUSED|$c"; fi
        done
    done > "$RC.res"
    n_ok=$(grep -c '^ok$' "$RC.res"); n_fail=$(grep -c '^fail$' "$RC.res")
    rm -f "$RC.res"
    n_lists=$(grep -c '^N ' "$RC.cmds"); n_nets=$(grep -c '^I ' "$RC.cmds"); n_dns=$(grep -c '^D ' "$RC.cmds")
    ndm "system configuration save" || log "OFF_SAVE_FAILED"
    status_write off "since=$(date +%s)" "lists=$n_lists" "subnets=$n_nets" "dns=$n_dns" "dns_kept=$dns_kept" "refused=$n_fail"
    log "OFF_DONE|lists=$n_lists|subnets=$n_nets|dns=$n_dns|dns_kept=$dns_kept|refused=$n_fail"
    echo "result=$([ "$was" = off ] && [ "$n_ok" = 0 ] && echo unchanged || echo changed)"
    echo "lists=$n_lists"; echo "subnets=$n_nets"; echo "dns=$n_dns"; echo "dns_kept=$dns_kept"; echo "refused=$n_fail"
}

op_on() {
    lock_take
    [ -e "$FLAG" ] || [ -s "$SAVED" ] || { status_write on; echo "result=unchanged"; exit 0; }
    status_write working "op=on" "since=$(date +%s)"
    log "ON_START|by=${VWARD_OFF_BY:-ssh}"
    n_back=0 n_fail=0
    if [ -s "$SAVED" ]; then
        read_config || { status_write off "error=router_config_unavailable"; echo "result=failed"; echo "error=router_config_unavailable"; exit 1; }
        # The subnets and lists first, AdGuard Home's DNS line last.
        { grep -v '^ip name-server ' "$SAVED"; grep '^ip name-server ' "$SAVED"; } | while IFS= read -r line; do
            [ -n "$line" ] || continue
            case "$line" in
                'dns-proxy '*) l=${line#dns-proxy }
                    awk -v l="$l" '/^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)} /^!/ {ctx = 0}
                        ctx {sub(/^[ \t]+/, ""); if ($0 == l) f = 1} END {exit !f}' "$RC" && continue ;;
                *) grep -qxF "$line" "$RC" && continue ;;
            esac
            if ndm "$line"; then echo ok; else echo fail; log "ON_REFUSED|$line"; fi
        done > "$RC.res"
        n_back=$(grep -c '^ok$' "$RC.res"); n_fail=$(grep -c '^fail$' "$RC.res")
        rm -f "$RC.res"
        ndm "system configuration save" || log "ON_SAVE_FAILED"
    fi
    dns_rules_back
    [ "$n_fail" = 0 ] && mv -f "$SAVED" "$SAVED.last" 2>/dev/null
    rm -f "$FLAG"
    start_services
    status_write on "since=$(date +%s)" "restored=$n_back" "refused=$n_fail"
    log "ON_DONE|restored=$n_back|refused=$n_fail"
    echo "result=changed"; echo "restored=$n_back"; echo "refused=$n_fail"
}

op_keep() {
    [ -e "$FLAG" ] || exit 0
    mkdir "$LOCK" 2>/dev/null || exit 0
    trap 'rm -rf "${LOCK:?}"' EXIT
    echo $$ > "$LOCK/pid"
    dns_rules_off
}

op_status() {
    if [ -e "$FLAG" ]; then echo "state=off"; else echo "state=on"; fi
    [ ! -r "$STATUS" ] || grep -v '^state=' "$STATUS"
    [ ! -r "$SAVED" ] || echo "saved=$(grep -c . "$SAVED")"
    :
}

case "${1:-off}" in
    off) op_off ;;
    on) op_on ;;
    keep) op_keep ;;
    status) op_status ;;
    *) echo "usage: vward-off.sh [off|on|status]" >&2; exit 64 ;;
esac
