#!/bin/sh
# vward-tunnel-quality.sh: every VPN connection of the router pinged through its own
# device once a minute (from the tunnel health check), all at once: loss and the
# average time. The last hour of samples stays in RAM, never on the USB stick.
#   vward-tunnel-quality.sh           take one sample of every tunnel
#   vward-tunnel-quality.sh summary   per tunnel for the last 30 minutes (for the Panel
#                                     and the tunnel guard):
#       name<TAB>device<TAB>last_loss<TAB>last_ms<TAB>ok_streak<TAB>samples<TAB>loss_pct<TAB>avg_ms<TAB>jitter_ms<TAB>up_pct<TAB>fail_streak

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

summary() {
    [ -s "$SAMPLES" ] || return 0
    awk -F '\t' -v now="$(date +%s)" -v win="$WINDOW" '
        $1 >= now - win {
            n = $2; if (!(n in cnt)) order[++k] = n
            dev[n] = $3; cnt[n]++; lloss[n] = $4; lms[n] = $5
            if ($4 < 100) { up[n]++; streak[n]++; fails[n] = 0; if ($5 != "-") { sum[n] += $5; num[n]++; if (prev[n] != "") { d = $5 - prev[n]; jit[n] += (d < 0 ? -d : d); jn[n]++ } prev[n] = $5 } }
            else { streak[n] = 0; fails[n]++ }
            loss[n] += $4
        }
        END {
            for (i = 1; i <= k; i++) { n = order[i]
                printf "%s\t%s\t%d\t%s\t%d\t%d\t%d\t%s\t%s\t%d\t%d\n", n, dev[n], lloss[n], lms[n], streak[n], cnt[n],
                    loss[n] / cnt[n], (num[n] ? sprintf("%d", sum[n] / num[n]) : "-"), (jn[n] ? sprintf("%d", jit[n] / jn[n]) : "-"), 100 * up[n] / cnt[n], fails[n] }
        }' "$SAMPLES"
}

if [ "${1:-}" = summary ]; then summary; exit 0; fi

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
exit 0
