#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin

VERSION="1.1"
WG="Wireguard1"

ITDOG_BASE="https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Subnets/IPv4"
LOYAL_BASE="https://raw.githubusercontent.com/Loyalsoldier/geoip/release/text"

STATE="/opt/var/lib/vpn-subnets"
OWNED="$STATE/owned.routes"
WORK="$STATE/work.$$"
LOCK="$STATE/lock"

LOG="/opt/var/log/vpn-subnet-sync.log"

mkdir -p "$STATE"

# Не допускаем одновременных запусков.
if ! mkdir "$LOCK" 2>/dev/null; then
    echo "SUBNET_SYNC=ALREADY_RUNNING"
    exit 0
fi

mkdir -p "$WORK"

cleanup() {
    rm -rf "$WORK" "$LOCK"
}
trap cleanup 0 1 2 15

touch "$OWNED"

log() {
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"
}

# Ограничиваем лог.
if [ -f "$LOG" ]; then
    SIZE="$(wc -c < "$LOG" 2>/dev/null)"
    [ -n "$SIZE" ] || SIZE=0

    if [ "$SIZE" -gt 262144 ]; then
        tail -n 1000 "$LOG" > "$LOG.tmp"
        mv "$LOG.tmp" "$LOG"
    fi
fi

download() {
    URL="$1"
    OUT="$2"

    if command -v curl >/dev/null 2>&1; then
        curl -fsSL \
            --connect-timeout 15 \
            --max-time 60 \
            "$URL" \
            -o "$OUT"
        return $?
    fi

    if command -v wget >/dev/null 2>&1; then
        wget -q -T 60 -O "$OUT" "$URL"
        return $?
    fi

    return 1
}

download_optional() {
    URL="$1"
    OUT="$2"
    LABEL="$3"

    if download "$URL" "$OUT"; then
        echo "SOURCE_$LABEL=OK"
        return 0
    fi

    rm -f "$OUT"
    echo "SOURCE_$LABEL=UNAVAILABLE"
    log "WARN supplemental source unavailable label=$LABEL url=$URL"
    return 0
}

normalize_ipv4() {
    awk '
    function valid(ip, p, a, n) {
        n=split(ip,a,".")
        if (n != 4) return 0

        for (i=1;i<=4;i++) {
            if (a[i] !~ /^[0-9]+$/) return 0
            if (a[i] < 0 || a[i] > 255) return 0
        }

        if (p < 1 || p > 32) return 0

        # Не допускаем локальные/служебные сети.
        if (a[1] == 0) return 0
        if (a[1] == 10) return 0
        if (a[1] == 127) return 0
        if (a[1] >= 224) return 0

        if (a[1] == 100 && a[2] >= 64 && a[2] <= 127) return 0
        if (a[1] == 169 && a[2] == 254) return 0
        if (a[1] == 172 && a[2] >= 16 && a[2] <= 31) return 0
        if (a[1] == 192 && a[2] == 168) return 0

        return 1
    }

    {
        gsub(/\r/,"")
        sub(/#.*/,"")
        gsub(/^[ \t]+|[ \t]+$/,"")

        if ($0 == "") next

        n=split($0,b,"/")
        if (n != 2) next

        ip=b[1]
        p=b[2]+0

        if (valid(ip,p))
            print ip "/" p
    }' | sort -u
}

prefix_mask() {
    case "$1" in
        1)  echo 128.0.0.0 ;;
        2)  echo 192.0.0.0 ;;
        3)  echo 224.0.0.0 ;;
        4)  echo 240.0.0.0 ;;
        5)  echo 248.0.0.0 ;;
        6)  echo 252.0.0.0 ;;
        7)  echo 254.0.0.0 ;;
        8)  echo 255.0.0.0 ;;
        9)  echo 255.128.0.0 ;;
        10) echo 255.192.0.0 ;;
        11) echo 255.224.0.0 ;;
        12) echo 255.240.0.0 ;;
        13) echo 255.248.0.0 ;;
        14) echo 255.252.0.0 ;;
        15) echo 255.254.0.0 ;;
        16) echo 255.255.0.0 ;;
        17) echo 255.255.128.0 ;;
        18) echo 255.255.192.0 ;;
        19) echo 255.255.224.0 ;;
        20) echo 255.255.240.0 ;;
        21) echo 255.255.248.0 ;;
        22) echo 255.255.252.0 ;;
        23) echo 255.255.254.0 ;;
        24) echo 255.255.255.0 ;;
        25) echo 255.255.255.128 ;;
        26) echo 255.255.255.192 ;;
        27) echo 255.255.255.224 ;;
        28) echo 255.255.255.240 ;;
        29) echo 255.255.255.248 ;;
        30) echo 255.255.255.252 ;;
        31) echo 255.255.255.254 ;;
        32) echo 255.255.255.255 ;;
        *) return 1 ;;
    esac
}

ndm() {
    CMD="$1"

    OUT="$(ndmc -c "$CMD" 2>&1)"
    RC=$?

    if [ "$RC" -ne 0 ]; then
        log "NDM_FAIL rc=$RC cmd=$CMD result=$OUT"
        return 1
    fi

    echo "$OUT" | grep -Eqi 'error\[|syntax error|not found|no such entry' && {
        log "NDM_FAIL cmd=$CMD result=$OUT"
        return 1
    }

    return 0
}

echo "SUBNET_SYNC_VERSION=$VERSION"
echo "SOURCES=itdoginfo/allow-domains+Loyalsoldier/geoip"
echo "INTERFACE=$WG"

# =========================================================
# СКАЧИВАЕМ ОСНОВНЫЕ СПИСКИ ITDOG
# =========================================================

download "$ITDOG_BASE/telegram.lst" "$WORK/telegram.itdog.raw" || {
    echo "ERROR=TELEGRAM_DOWNLOAD_FAILED"
    log "ABORT Telegram itdog download failed"
    exit 1
}

download "$ITDOG_BASE/meta.lst" "$WORK/meta.itdog.raw" || {
    download "$ITDOG_BASE/Meta.lst" "$WORK/meta.itdog.raw" || {
        echo "ERROR=META_DOWNLOAD_FAILED"
        log "ABORT Meta itdog download failed"
        exit 1
    }
}

download "$ITDOG_BASE/twitter.lst" "$WORK/twitter.itdog.raw" || {
    download "$ITDOG_BASE/Twitter.lst" "$WORK/twitter.itdog.raw" || {
        echo "ERROR=TWITTER_DOWNLOAD_FAILED"
        log "ABORT Twitter itdog download failed"
        exit 1
    }
}

download "$ITDOG_BASE/discord.lst" "$WORK/discord.itdog.raw" || {
    download "$ITDOG_BASE/Discord.lst" "$WORK/discord.itdog.raw" || {
        echo "ERROR=DISCORD_DOWNLOAD_FAILED"
        log "ABORT Discord itdog download failed"
        exit 1
    }
}

# =========================================================
# ДОПОЛНИТЕЛЬНЫЕ GEOIP-СПИСКИ LOYALSOLDIER
#
# Берём только сервисные диапазоны.
# Целые страны и shared Cloudflare/CloudFront не импортируем.
# =========================================================

download_optional \
    "$LOYAL_BASE/telegram.txt" \
    "$WORK/telegram.loyal.raw" \
    "LOYALSOLDIER_TELEGRAM"

download_optional \
    "$LOYAL_BASE/facebook.txt" \
    "$WORK/meta.loyal.raw" \
    "LOYALSOLDIER_FACEBOOK"

download_optional \
    "$LOYAL_BASE/twitter.txt" \
    "$WORK/twitter.loyal.raw" \
    "LOYALSOLDIER_TWITTER"

# =========================================================
# НОРМАЛИЗАЦИЯ И ОБЪЕДИНЕНИЕ
# =========================================================

normalize_ipv4 < "$WORK/telegram.itdog.raw" > "$WORK/telegram.itdog"
normalize_ipv4 < "$WORK/meta.itdog.raw"     > "$WORK/meta.itdog"
normalize_ipv4 < "$WORK/twitter.itdog.raw"  > "$WORK/twitter.itdog"
normalize_ipv4 < "$WORK/discord.itdog.raw"  > "$WORK/discord.full"

: > "$WORK/telegram.loyal"
: > "$WORK/meta.loyal"
: > "$WORK/twitter.loyal"

[ -f "$WORK/telegram.loyal.raw" ] &&
    normalize_ipv4 < "$WORK/telegram.loyal.raw" > "$WORK/telegram.loyal"

[ -f "$WORK/meta.loyal.raw" ] &&
    normalize_ipv4 < "$WORK/meta.loyal.raw" > "$WORK/meta.loyal"

[ -f "$WORK/twitter.loyal.raw" ] &&
    normalize_ipv4 < "$WORK/twitter.loyal.raw" > "$WORK/twitter.loyal"

cat "$WORK/telegram.itdog" "$WORK/telegram.loyal" |
sort -u > "$WORK/telegram"

cat "$WORK/meta.itdog" "$WORK/meta.loyal" |
sort -u > "$WORK/meta"

cat "$WORK/twitter.itdog" "$WORK/twitter.loyal" |
sort -u > "$WORK/twitter"

# =========================================================
# DISCORD
#
# Не маршрутизируем целиком огромные shared Cloudflare/GCP
# сети. Оставляем узкие Discord/voice диапазоны.
# =========================================================

grep -v -E \
'^(162\.158\.0\.0/15|172\.64\.0\.0/13|34\.0\.0\.0/15|34\.2\.0\.0/15|35\.192\.0\.0/12|35\.208\.0\.0/12|104\.16\.0\.0/12)$' \
"$WORK/discord.full" > "$WORK/discord"

TG="$(wc -l < "$WORK/telegram")"
META="$(wc -l < "$WORK/meta")"
TW="$(wc -l < "$WORK/twitter")"
DC="$(wc -l < "$WORK/discord")"

TG_ITDOG="$(wc -l < "$WORK/telegram.itdog")"
TG_LOYAL="$(wc -l < "$WORK/telegram.loyal")"
META_ITDOG="$(wc -l < "$WORK/meta.itdog")"
META_LOYAL="$(wc -l < "$WORK/meta.loyal")"
TW_ITDOG="$(wc -l < "$WORK/twitter.itdog")"
TW_LOYAL="$(wc -l < "$WORK/twitter.loyal")"

echo "TELEGRAM_CIDR=$TG | itdog=$TG_ITDOG loyal=$TG_LOYAL"
echo "META_CIDR=$META | itdog=$META_ITDOG loyal=$META_LOYAL"
echo "TWITTER_CIDR=$TW | itdog=$TW_ITDOG loyal=$TW_LOYAL"
echo "DISCORD_SAFE_CIDR=$DC | itdog=$DC"

# Защита от пустого/битого источника.
if [ "$TG" -lt 5 ]; then
    echo "ERROR=BAD_TELEGRAM_FEED"
    exit 1
fi

if [ "$META" -lt 30 ]; then
    echo "ERROR=BAD_META_FEED"
    exit 1
fi

if [ "$TW" -lt 5 ]; then
    echo "ERROR=BAD_TWITTER_FEED"
    exit 1
fi

if [ "$DC" -lt 3 ]; then
    echo "ERROR=BAD_DISCORD_FEED"
    exit 1
fi

: > "$WORK/wanted"

awk '{print $0 "|Telegram"}' "$WORK/telegram" >> "$WORK/wanted"
awk '{print $0 "|Meta"}' "$WORK/meta" >> "$WORK/wanted"
awk '{print $0 "|Twitter-X"}' "$WORK/twitter" >> "$WORK/wanted"
awk '{print $0 "|Discord"}' "$WORK/discord" >> "$WORK/wanted"

sort -u "$WORK/wanted" > "$WORK/wanted.sorted"
mv "$WORK/wanted.sorted" "$WORK/wanted"

WANTED="$(wc -l < "$WORK/wanted")"
echo "TOTAL_WANTED=$WANTED"

# =========================================================
# ТЕКУЩИЙ КОНФИГ
# =========================================================

ndmc -c "show running-config" > "$WORK/running" 2>/dev/null || {
    echo "ERROR=CANNOT_READ_RUNNING_CONFIG"
    log "ABORT cannot read running-config"
    exit 1
}

: > "$WORK/next-owned"

CHANGED=0
ADDED=0
REMOVED=0
EXISTING_MANUAL=0
ERRORS=0

# =========================================================
# ДОБАВЛЯЕМ НОВЫЕ / СОХРАНЯЕМ АКТУАЛЬНЫЕ
# =========================================================

while IFS='|' read -r CIDR SERVICE; do
    [ -n "$CIDR" ] || continue

    NET="${CIDR%/*}"
    PREFIX="${CIDR#*/}"
    MASK="$(prefix_mask "$PREFIX")" || continue

    ROUTE="ip route $NET $MASK $WG auto"

    # Уже существует точный такой маршрут.
    if grep -Fq "$ROUTE" "$WORK/running"; then

        # Если наш — продолжаем им управлять.
        if grep -Fq "$CIDR|" "$OWNED"; then
            printf '%s|%s\n' "$CIDR" "$SERVICE" >> "$WORK/next-owned"
        else
            # Чужой/ручной маршрут не присваиваем себе.
            EXISTING_MANUAL=$((EXISTING_MANUAL + 1))
        fi

        continue
    fi

    if ndm "ip route $NET $MASK $WG auto"; then
        printf '%s|%s\n' "$CIDR" "$SERVICE" >> "$WORK/next-owned"
        ADDED=$((ADDED + 1))
        CHANGED=1
    else
        ERRORS=$((ERRORS + 1))
    fi
done < "$WORK/wanted"

# =========================================================
# УДАЛЯЕМ УСТАРЕВШИЕ
#
# Только те маршруты, которые ранее создал ЭТОТ скрипт.
# Ручные маршруты пользователя не удаляются.
# =========================================================

while IFS='|' read -r CIDR SERVICE; do
    [ -n "$CIDR" ] || continue

    if grep -Fq "$CIDR|" "$WORK/wanted"; then
        continue
    fi

    NET="${CIDR%/*}"
    PREFIX="${CIDR#*/}"
    MASK="$(prefix_mask "$PREFIX")"

    if [ -z "$MASK" ]; then
        printf '%s|%s\n' "$CIDR" "$SERVICE" >> "$WORK/next-owned"
        continue
    fi

    if ndm "no ip route $NET $MASK $WG"; then
        REMOVED=$((REMOVED + 1))
        CHANGED=1
    else
        printf '%s|%s\n' "$CIDR" "$SERVICE" >> "$WORK/next-owned"
        ERRORS=$((ERRORS + 1))
    fi
done < "$OWNED"

sort -u "$WORK/next-owned" > "$WORK/owned.sorted"
mv "$WORK/owned.sorted" "$OWNED"

MANAGED="$(wc -l < "$OWNED")"

TG_MANAGED="$(grep -c '|Telegram$' "$OWNED" 2>/dev/null)"
META_MANAGED="$(grep -c '|Meta$' "$OWNED" 2>/dev/null)"
TW_MANAGED="$(grep -c '|Twitter-X$' "$OWNED" 2>/dev/null)"
DC_MANAGED="$(grep -c '|Discord$' "$OWNED" 2>/dev/null)"

# =========================================================
# СОХРАНЕНИЕ
# =========================================================

if [ "$CHANGED" -eq 1 ]; then
    if ndm "system configuration save"; then
        SAVE="YES"
    else
        SAVE="FAILED"
        ERRORS=$((ERRORS + 1))
    fi
else
    SAVE="NOT_NEEDED"
fi

echo
echo "===== SYNC RESULT ====="
echo "ADDED=$ADDED"
echo "REMOVED=$REMOVED"
echo "EXISTING_MANUAL=$EXISTING_MANUAL"
echo "MANAGED_TOTAL=$MANAGED"
echo "MANAGED_TELEGRAM=$TG_MANAGED"
echo "MANAGED_META=$META_MANAGED"
echo "MANAGED_TWITTER=$TW_MANAGED"
echo "MANAGED_DISCORD=$DC_MANAGED"
echo "ERRORS=$ERRORS"
echo "CONFIG_SAVE=$SAVE"

log "SYNC version=$VERSION wanted=$WANTED managed=$MANAGED added=$ADDED removed=$REMOVED manual=$EXISTING_MANUAL errors=$ERRORS save=$SAVE"

if [ "$ERRORS" -eq 0 ]; then
    echo "SUBNET_SYNC=OK"
else
    echo "SUBNET_SYNC=PARTIAL"
fi

exit 0
