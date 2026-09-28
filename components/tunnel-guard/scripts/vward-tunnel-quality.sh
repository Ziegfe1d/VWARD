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

# speed_due: two tunnels or more, and the time has come.
speed_due() {
    [ "$1" -ge 2 ] || return 1
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
esac

vward_profile_load || exit 1
mkdir -p "$DIR" || exit 1
W=$(mktemp -d "$DIR/run.XXXXXX" 2>/dev/null) || exit 1
trap 'rm -rf "${W:?}"' EXIT
vward_map_vpns "$(vward_device_map 2>/dev/null)" "${VWARD_WAN_DEVICE:-}" > "$W/targets"
k=0
while read -r name dev; do
    vward_valid_ifname "$dev" 2>/dev/null && [ -e "$SYSFS/$dev" ] || continue
    k=$((k + 1))
    printf '%s\t%s\n' "$name" "$dev" > "$W/t.$k"
    "$PING" -I "$dev" -c 3 -W 2 "$TARGET" > "$W/p.$k" 2>&1 &
done < "$W/targets"
wait
now=$(date +%s)
i=0
while [ "$i" -lt "$k" ]; do
    i=$((i + 1))
    IFS="$(printf '\t')" read -r name dev < "$W/t.$i"
    awk -v now="$now" -v n="$name" -v d="$dev" '
        /packet loss/ {for (j = 1; j <= NF; j++) if ($j ~ /%$/) {loss = $j; sub(/%/, "", loss)}}
        /min\/avg\/max/ {split($0, a, "= "); split(a[2], b, "/"); avg = b[2]}
        END {if (loss == "") loss = 100; printf "%s\t%s\t%s\t%d\t%s\n", now, n, d, loss, (avg == "" ? "-" : sprintf("%d", avg + 0.5))}' "$W/p.$i" >> "$SAMPLES"
done
# The last hour only.
awk -F '\t' -v cut="$((now - KEEP))" '$1 >= cut' "$SAMPLES" > "$W/keep" 2>/dev/null && mv -f "$W/keep" "$SAMPLES"
# The speed, when due: in the background, the next sample does not wait for it.
if speed_due "$k" "$now"; then
    sh "$0" speed </dev/null >/dev/null 2>&1 &
fi
exit 0
