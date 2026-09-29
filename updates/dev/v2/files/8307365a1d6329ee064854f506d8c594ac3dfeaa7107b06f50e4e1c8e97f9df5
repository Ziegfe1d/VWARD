#!/bin/sh
# vward-tunnel-quality.sh: every VPN connection of the router pinged through its own
# device once a minute (from the tunnel health check), all at once: loss and the
# average time. The last hour of samples stays in RAM, never on the USB stick.
#   vward-tunnel-quality.sh           take one sample of every tunnel
#   vward-tunnel-quality.sh summary   per tunnel for the last 30 minutes (for the Panel
#                                     and the tunnel guard):
#       name<TAB>device<TAB>last_loss<TAB>last_ms<TAB>ok_streak<TAB>samples<TAB>loss_pct<TAB>avg_ms<TAB>jitter_ms<TAB>up_pct<TAB>fail_streak<TAB>speed_mbps<TAB>speed_at
#   vward-tunnel-quality.sh speed     download 10 MB through every tunnel, one after another
#                                     (traffic and CPU: at night or by the Panel's button).
#   vward-tunnel-quality.sh services  services on «Автоматически» (Panel «Сервисы»): each one
#                                     opened through every answering tunnel; one that does not
#                                     open through its tunnel moves to the fastest that opens
#                                     it; a category pinned to a tunnel takes its services there.
#                                     With two tunnels or more, every 30 minutes by itself.
# With two tunnels or more, the speed is measured by itself: SPEED=night (default) once a
# night between 03:00 and 05:00, SPEED=6h every 6 hours, SPEED=off never (tunnel-auto.conf).

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}
[ -r "$VWARD_PROFILE_LIB" ] || { echo "VWARD device profile library is unavailable" >&2; exit 1; }
. "$VWARD_PROFILE_LIB"

DIR=${VWARD_TUNNEL_QUALITY_DIR:-/tmp/vward-tunnel-quality}
SAMPLES="$DIR/samples.tsv"
TARGET=${VWARD_QUALITY_TARGET:-1.1.1.1}
KEEP=3600
WINDOW=1800
PING=${VWARD_PING:-ping}
SYSFS=${VWARD_SYSFS_NET:-/sys/class/net}
# The speed is kept on the USB stick (one write a day): it outlives a reboot.
SPEED_FILE=${VWARD_TUNNEL_SPEED_FILE:-/opt/var/lib/vward/tunnel-quality/speed.tsv}
SPEED_URL=${VWARD_SPEED_URL:-https://speed.cloudflare.com/__down?bytes=10000000}
SPEED_LOCK=${VWARD_TUNNEL_SPEED_LOCK:-/tmp/vward-tunnel-speed.lock}
AUTO_CONF="${VWARD_ETC:-/opt/etc/vward}/tunnel-auto.conf"
CURL=${VWARD_CURL_BIN:-curl}
SERVICES_ETC="${VWARD_ETC:-/opt/etc/vward}/services"
SERVICES_CATALOGS="${VWARD_SERVICES_FETCHED:-/opt/var/lib/vward/services/catalog.json} ${VWARD_SERVICES_BUNDLED:-/opt/share/vward/console/services-catalog.json}"
SERVICES_DIR=${VWARD_TUNNEL_SERVICES_DIR:-/tmp/vward-tunnel-services}
SERVICES_EVERY=1800
HELPER=${VWARD_CONSOLE_CONFIG_BIN:-/opt/bin/vward-console-config.sh}
RESOLVE=${VWARD_RESOLVE4_BIN:-/opt/bin/vward-route-resolve4.sh}
NDMC=${VWARD_NDMC:-ndmc}
JQ=${JQ:-jq}

summary() {
    [ -s "$SAMPLES" ] || return 0
    sp=/dev/null; [ ! -s "$SPEED_FILE" ] || sp=$SPEED_FILE
    awk -F '\t' -v now="$(date +%s)" -v win="$WINDOW" '
        FILENAME != ARGV[2] {mb[$1] = $4; mat[$1] = $3; next}
        $1 >= now - win {
            n = $2; if (!(n in cnt)) order[++k] = n
            dev[n] = $3; cnt[n]++; lloss[n] = $4; lms[n] = $5
            if ($4 < 100) { up[n]++; streak[n]++; fails[n] = 0; if ($5 != "-") { sum[n] += $5; num[n]++; if (prev[n] != "") { d = $5 - prev[n]; jit[n] += (d < 0 ? -d : d); jn[n]++ } prev[n] = $5 } }
            else { streak[n] = 0; fails[n]++ }
            loss[n] += $4
        }
        END {
            for (i = 1; i <= k; i++) { n = order[i]
                printf "%s\t%s\t%d\t%s\t%d\t%d\t%d\t%s\t%s\t%d\t%d\t%s\t%s\n", n, dev[n], lloss[n], lms[n], streak[n], cnt[n],
                    loss[n] / cnt[n], (num[n] ? sprintf("%d", sum[n] / num[n]) : "-"), (jn[n] ? sprintf("%d", jit[n] / jn[n]) : "-"), 100 * up[n] / cnt[n], fails[n],
                    (n in mb ? mb[n] : "-"), (n in mat ? mat[n] : "-") }
        }' "$sp" "$SAMPLES"
}

conf_get() {
    v=$(awk -F= -v k="$1" '$1 == k {print substr($0, index($0, "=") + 1); exit}' "$AUTO_CONF" 2>/dev/null)
    printf '%s\n' "${v:-$2}"
}

# speed: every tunnel one after another (together they would share the line and the CPU).
speed() {
    mkdir "$SPEED_LOCK" 2>/dev/null || return 0
    trap 'rm -rf "${SPEED_LOCK:?}"' EXIT
    vward_profile_load || return 1
    mkdir -p "$(dirname "$SPEED_FILE")" || return 1
    now=$(date +%s)
    : > "$SPEED_LOCK/new"
    vward_map_vpns "$(vward_device_map 2>/dev/null)" "${VWARD_WAN_DEVICE:-}" > "$SPEED_LOCK/targets"
    while read -r name dev; do
        vward_valid_ifname "$dev" 2>/dev/null && [ -e "$SYSFS/$dev" ] || continue
        # bytes and bytes a second; 30 s at most, what came by then counts (from 1 MB).
        out=$("$CURL" -4 -s -o /dev/null --noproxy '*' --interface "$dev" --connect-timeout 5 --max-time 30 \
            -w '%{size_download} %{speed_download}' "$SPEED_URL" </dev/null 2>/dev/null)
        mbps=$(printf '%s\n' "$out" | awk '$1 >= 1000000 {printf "%.1f", $2 * 8 / 1000000}')
        [ -n "$mbps" ] || mbps=0
        printf '%s\t%s\t%s\t%s\n' "$name" "$dev" "$now" "$mbps" >> "$SPEED_LOCK/new"
    done < "$SPEED_LOCK/targets"
    [ -s "$SPEED_LOCK/new" ] || return 0
    cp "$SPEED_LOCK/new" "$SPEED_FILE.tmp.$$" && mv -f "$SPEED_FILE.tmp.$$" "$SPEED_FILE"
}

# svc_open DOMAIN IP DEV: "verdict ms" of https://DOMAIN/ at IP through DEV, the Panel's
# «Проверить сайт»: no answer, blocked (451 or a redirect to an «unavailable» page) or open.
svc_open() {
    r=$("$CURL" -4 --noproxy '*' --interface "$3" --resolve "$1:443:$2" --connect-timeout 3 --max-time 6 \
        -A "Mozilla/5.0" -s -o /dev/null -w '%{http_code} %{time_total} %{redirect_url}' "https://$1/" </dev/null 2>/dev/null)
    read -r code secs loc <<EOF_R
$r
EOF_R
    case "${code:-000}:$(printf '%s' "$loc" | tr 'A-Z' 'a-z')" in
        000:*) v=none ;;
        451:*|*unavailable*|*region*|*restricted*|*not-available*|*blocked*) v=blocked ;;
        *) v=open ;;
    esac
    printf '%s %s\n' "$v" "$(awk -v t="${secs:-0}" 'BEGIN {printf "%d", t * 1000}')"
}

# services: one line per service on «Автоматически» into $SERVICES_DIR/state.tsv:
#   id<TAB>list<TAB>tunnel now<TAB>tunnel:verdict:ms,...<TAB>checked at<TAB>kept|moved|category|none|failed
services() {
    mkdir -p "$SERVICES_DIR" || return 1
    mkdir "$SERVICES_DIR/lock" 2>/dev/null || return 0
    trap 'rm -rf "${SERVICES_DIR:?}/lock"' EXIT
    L="$SERVICES_DIR/lock"
    date +%s > "$SERVICES_DIR/at"
    [ -s "$SERVICES_ETC/enabled.tsv" ] && [ -x "$HELPER" ] || { rm -f "$SERVICES_DIR/state.tsv"; return 0; }
    cat=""
    for c in $SERVICES_CATALOGS; do "$JQ" -e '.schema == 1 and (.services | length) > 0' "$c" >/dev/null 2>&1 && { cat=$c; break; }; done
    [ -n "$cat" ] || return 1
    # The tunnels answering now: name and device.
    summary | awk -F '\t' '$5 >= 2 && $3 < 100 {print $1 "\t" $2}' > "$L/alive"
    [ "$(grep -c . "$L/alive")" -ge 2 ] || { rm -f "$SERVICES_DIR/state.tsv"; return 0; }
    "$NDMC" -c "show running-config" 2>/dev/null | tr -d '\r' |
        awk '/^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)} /^!/ {ctx = 0}
            ctx && $1 == "route" && $2 == "object-group" {print $3 "\t" $4}' > "$L/routes"
    [ -s "$L/routes" ] || return 1
    "$JQ" -r '.services[] | [.id, .category, ([.domains[] | select(index("*") == null)] | sort_by(length) | .[0] // "")] | @tsv' "$cat" > "$L/catalog"
    now=$(date +%s)
    : > "$L/state"
    while IFS="$(printf '\t')" read -r id g pin; do
        [ "$pin" = auto ] && [ -n "$g" ] || continue
        case "$id$g" in *[!A-Za-z0-9.@_-]*) continue ;; esac
        cur=$(awk -F '\t' -v g="$g" '$1 == g {print $2; exit}' "$L/routes")
        [ -n "$cur" ] || continue
        IFS="$(printf '\t')" read -r _ scat probe <<EOF_ROW
$(awk -F '\t' -v i="$id" '$1 == i {print; exit}' "$L/catalog")
EOF_ROW
        # A category pinned to a tunnel that answers: the service goes there, no check.
        pinned=$(awk -F '\t' -v c="$scat" '$1 == c {print $2; exit}' "$SERVICES_ETC/categories.tsv" 2>/dev/null)
        if [ -n "$scat" ] && [ -n "$pinned" ] && awk -F '\t' -v t="$pinned" '$1 == t {f = 1} END {exit f ? 0 : 1}' "$L/alive"; then
            act=category
            if [ "$cur" != "$pinned" ]; then
                if "$HELPER" domain-list "$g" "$pinned" </dev/null 2>/dev/null | tail -n 1 | grep -q '^result='; then cur=$pinned; else act=failed; fi
            fi
            printf '%s\t%s\t%s\t\t%s\t%s\n' "$id" "$g" "$cur" "$now" "$act" >> "$L/state"
            continue
        fi
        # The service's own name when it is a domain, else its shortest domain.
        case "$id" in *.*) probe=$id ;; esac
        case "$probe" in ''|*[!a-z0-9.-]*|.*|*.|*..*) continue ;; esac
        ip=$("$RESOLVE" "$probe" 2>/dev/null | awk '/^Address [0-9]+:/ && $3 ~ /^[0-9]+\./ {ip = $3} END {print ip}')
        vward_valid_ipv4 "$ip" 2>/dev/null || { printf '%s\t%s\t%s\t\t%s\tnone\n' "$id" "$g" "$cur" "$now" >> "$L/state"; continue; }
        # Through every answering tunnel at once.
        k=0
        while IFS="$(printf '\t')" read -r tn td; do
            k=$((k + 1)); printf '%s\n' "$tn" > "$L/n.$k"
            svc_open "$probe" "$ip" "$td" > "$L/r.$k" &
        done < "$L/alive"
        wait
        res="" best="" bms=0 curv=""
        i=0
        while [ "$i" -lt "$k" ]; do
            i=$((i + 1)); tn=$(cat "$L/n.$i"); read -r v ms < "$L/r.$i" || v=none
            res="$res${res:+,}$tn:$v:${ms:-0}"
            [ "$tn" != "$cur" ] || curv=$v
            if [ "$v" = open ] && { [ -z "$best" ] || [ "${ms:-0}" -lt "$bms" ]; }; then best=$tn bms=${ms:-0}; fi
        done
        act=kept
        # Its tunnel opens it (or is not among the answering ones: the guard moves it): kept.
        if [ -n "$curv" ] && [ "$curv" != open ]; then
            if [ -z "$best" ]; then act=none
            elif "$HELPER" domain-list "$g" "$best" </dev/null 2>/dev/null | tail -n 1 | grep -q '^result='; then act=moved cur=$best
            else act=failed; fi
        fi
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "$g" "$cur" "$res" "$now" "$act" >> "$L/state"
    done < "$SERVICES_ETC/enabled.tsv"
    mv -f "$L/state" "$SERVICES_DIR/state.tsv"
}

# services_due: two tunnels or more, a service on «Автоматически», 30 minutes since the last check.
# Optional work: it waits while the router is busy (vward_defer, at most 2 hours).
VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ ! -r "$VWARD_ADMISSION_LIB" ] || . "$VWARD_ADMISSION_LIB"
command -v vward_defer >/dev/null 2>&1 || vward_defer() { return 1; }

services_due() {
    [ "$1" -ge 2 ] && [ -x "$HELPER" ] && awk -F '\t' '$3 == "auto" {f = 1} END {exit f ? 0 : 1}' "$SERVICES_ETC/enabled.tsv" 2>/dev/null || return 1
    last=$(cat "$SERVICES_DIR/at" 2>/dev/null)
    case "$last" in ''|*[!0-9]*) last=0 ;; esac
    [ $(($2 - last)) -ge "$SERVICES_EVERY" ] && ! vward_defer tunnel-services
}

# speed_due: two tunnels or more, and the time has come.
speed_due() {
    [ "$1" -ge 2 ] || return 1
    ! vward_defer tunnel-speed || return 1
    last=$(awk -F '\t' 'NR == 1 {print $3}' "$SPEED_FILE" 2>/dev/null)
    case "$last" in ''|*[!0-9]*) last=0 ;; esac
    case "$(conf_get SPEED night)" in
        off) return 1 ;;
        6h) [ $(($2 - last)) -ge 21600 ] ;;
        *) h=$(date +%H); [ "$h" = 03 ] || [ "$h" = 04 ] || return 1
           [ $(($2 - last)) -ge 72000 ] ;;
    esac
}

case "${1:-}" in
    summary) summary; exit 0 ;;
    speed) speed; exit $? ;;
    services) vward_profile_load || exit 1; services; exit $? ;;
esac

vward_profile_load || exit 1
# Once a minute: as few processes as can be. The ping results are overwritten each
# time (RAM), one awk reads them all.
[ -d "$DIR" ] || mkdir -p "$DIR" || exit 1
k=0
: > "$DIR/map"
while read -r name dev; do
    vward_valid_ifname "$dev" 2>/dev/null && [ -e "$SYSFS/$dev" ] || continue
    k=$((k + 1))
    printf '%s\t%s\t%s\n' "$DIR/p.$k" "$name" "$dev" >> "$DIR/map"
    "$PING" -I "$dev" -c 3 -W 2 "$TARGET" > "$DIR/p.$k" 2>&1 &
done <<TARGETS
$(vward_map_vpns "$(vward_device_map 2>/dev/null)" "${VWARD_WAN_DEVICE:-}")
TARGETS
wait
now=${VWARD_NOW:-$(date +%s)}
case "$now" in ''|*[!0-9]*) now=$(date +%s) ;; esac
FILES=
i=0
while [ "$i" -lt "$k" ]; do i=$((i + 1)); FILES="$FILES $DIR/p.$i"; done
# shellcheck disable=SC2086
[ "$k" -eq 0 ] || awk -v now="$now" '
    function emit() {if (f != "") printf "%s\t%s\t%s\t%d\t%s\n", now, n[f], d[f], (loss == "" ? 100 : loss), (avg == "" ? "-" : sprintf("%d", avg + 0.5))}
    NR == FNR {split($0, m, "\t"); n[m[1]] = m[2]; d[m[1]] = m[3]; next}
    FNR == 1 {emit(); f = FILENAME; loss = ""; avg = ""}
    /packet loss/ {for (j = 1; j <= NF; j++) if ($j ~ /%$/) {loss = $j; sub(/%/, "", loss)}}
    /min\/avg\/max/ {split($0, a, "= "); split(a[2], b, "/"); avg = b[2]}
    END {emit()}' "$DIR/map" $FILES >> "$SAMPLES"
# The last hour only: trimmed when the oldest row is 10 minutes past it (read by the shell).
first=
[ ! -s "$SAMPLES" ] || read -r first _ < "$SAMPLES" || :
case "$first" in ''|*[!0-9]*) first=$now ;; esac
if [ "$first" -lt $((now - KEEP - 600)) ]; then
    awk -F '\t' -v cut="$((now - KEEP))" '$1 >= cut' "$SAMPLES" > "$DIR/keep" 2>/dev/null && mv -f "$DIR/keep" "$SAMPLES"
fi
# The speed, when due: in the background, the next sample does not wait for it.
if speed_due "$k" "$now"; then
    sh "$0" speed </dev/null >/dev/null 2>&1 &
fi
if services_due "$k" "$now"; then
    sh "$0" services </dev/null >/dev/null 2>&1 &
fi
exit 0
