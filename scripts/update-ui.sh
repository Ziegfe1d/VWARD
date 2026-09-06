#!/opt/bin/sh
set -u

REPO_RAW="https://raw.githubusercontent.com/Ziegfe1d/VWARD/main"
URL="$REPO_RAW/web/index.html"

DST="/opt/share/keenetic-apps/www/index.html"
TMP="/tmp/keenetic-apps-index.html"
BACKUP_DIR="/opt/var/backups/keenetic-apps"
STAMP="$(date '+%Y%m%d-%H%M%S')"

echo "===== VWARD UI UPDATE ====="

mkdir -p "$BACKUP_DIR" || exit 1

if [ -f "$DST" ]; then
    cp "$DST" "$BACKUP_DIR/index.$STAMP.html" || exit 2
    echo "BACKUP=$BACKUP_DIR/index.$STAMP.html"
fi

rm -f "$TMP"

if ! /opt/bin/wget -qO "$TMP" "$URL"; then
    rm -f "$TMP"
    echo "UPDATE=DOWNLOAD_FAILED"
    exit 3
fi

SIZE="$(wc -c < "$TMP" | tr -d ' ')"
echo "DOWNLOADED=$SIZE"

if [ "$SIZE" -lt 10000 ]; then
    rm -f "$TMP"
    echo "UPDATE=INVALID_SIZE"
    exit 4
fi

if ! grep -q '<title>VWARD' "$TMP"; then
    rm -f "$TMP"
    echo "UPDATE=INVALID_HTML"
    exit 5
fi

mv "$TMP" "$DST" || exit 6

echo "UPDATE=OK"
echo "DST=$DST"
echo "===== END ====="
