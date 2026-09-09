#!/bin/sh

set -u

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

BASE_URL=${VWARD_REPOSITORY_RAW_URL:-https://raw.githubusercontent.com/Ziegfe1d/VWARD/main}
ROOT=/opt/share/vward
UPDATER_ROOT=$ROOT/updater
SLOT=$UPDATER_ROOT/slots/A
CURRENT=$UPDATER_ROOT/current
CONFIG_DIR=/opt/etc/vward
CONFIG=$CONFIG_DIR/update.conf
PUBLIC_KEY=$CONFIG_DIR/update-public.pem
STATE=/opt/var/lib/vward/updater
LOG=/opt/var/log/vward
BACKUP_ROOT=/opt/var/backups/vward/bootstrap
WORK=/opt/var/tmp/vward-updater-bootstrap.$$
BACKUP=$BACKUP_ROOT/$(date '+%Y%m%d-%H%M%S')-$$
CRON_MARK='# VWARD_SMART_UPDATER'
MUTATION_STARTED=0
HAD_UPDATER=0
HAD_CONFIG=0
HAD_PUBLIC_KEY=0
HAD_VERSION=0

UPDATER_FILES='
vward-update-bootstrap.sh
vward-update-common-base.sh
vward-update-common.sh
vward-update-hardening.sh
vward-update-health.sh
vward-update-rollback.sh
vward-update-watch.sh
vward-update.sh
'

rollback_bootstrap()
{
    [ "$MUTATION_STARTED" = 1 ] || return 0

    if [ -f "$BACKUP/crontab.before" ]; then
        crontab "$BACKUP/crontab.before" >/dev/null 2>&1 || :
    fi

    if [ "$HAD_UPDATER" = 1 ] && [ -d "$BACKUP/updater" ]; then
        rm -rf "$UPDATER_ROOT"
        cp -pR "$BACKUP/updater" "$UPDATER_ROOT" >/dev/null 2>&1 || :
    else
        rm -rf "$UPDATER_ROOT"
    fi

    if [ "$HAD_CONFIG" = 1 ]; then
        cp -p "$BACKUP/etc/update.conf" "$CONFIG" >/dev/null 2>&1 || :
    else
        rm -f "$CONFIG"
    fi

    if [ "$HAD_PUBLIC_KEY" = 1 ]; then
        cp -p "$BACKUP/etc/update-public.pem" "$PUBLIC_KEY" >/dev/null 2>&1 || :
    else
        rm -f "$PUBLIC_KEY"
    fi

    if [ "$HAD_VERSION" = 1 ]; then
        cp -p "$BACKUP/VERSION" "$ROOT/VERSION" >/dev/null 2>&1 || :
    else
        rm -f "$ROOT/VERSION"
    fi
}

fail()
{
    rollback_bootstrap
    echo "BOOTSTRAP_RESULT=FAIL"
    echo "ERROR=$*"
    exit 1
}

cleanup()
{
    rm -rf "$WORK"
}

trap cleanup EXIT INT TERM

for C in awk cmp cp curl date df find grep jq kill mkdir mv openssl sed \
         sha256sum sleep stat tar tr wc; do
    command -v "$C" >/dev/null 2>&1 || fail "missing command: $C"
done

openssl version >/dev/null 2>&1 || fail "openssl CLI is unavailable"
ndmc -c "show version" >/dev/null 2>&1 || fail "Keenetic control plane is unavailable"

mkdir -p "$WORK/files" "$BACKUP" ||
    fail "cannot create bootstrap directories"

download()
{
    URL=$1
    DEST=$2

    curl --fail --silent --show-error --location \
        --proto '=https' \
        --tlsv1.2 \
        --connect-timeout 15 \
        --max-time 120 \
        --retry 3 \
        --retry-all-errors \
        --max-filesize 1048576 \
        --output "$DEST.part" \
        "$URL" ||
        return 1

    mv "$DEST.part" "$DEST"
}

download "$BASE_URL/SHA256SUMS" "$WORK/SHA256SUMS" ||
    fail "cannot download SHA256SUMS"

for F in $UPDATER_FILES; do
    download "$BASE_URL/components/updater/$F" "$WORK/files/$F" ||
        fail "cannot download $F"

    EXPECTED=$(
        awk -v p="components/updater/$F" '$2==p {print $1; exit}' \
            "$WORK/SHA256SUMS"
    )
    ACTUAL=$(sha256sum "$WORK/files/$F" | awk '{print $1}')

    [ -n "$EXPECTED" ] && [ "$ACTUAL" = "$EXPECTED" ] ||
        fail "SHA256 mismatch: $F"

    sh -n "$WORK/files/$F" || fail "shell syntax failed: $F"
done

for SPEC in \
    "config/updater/update-public.pem|update-public.pem" \
    "config/updater/update.conf.production|update.conf" \
    "VERSION|VERSION"; do

    SOURCE=${SPEC%%|*}
    NAME=${SPEC##*|}

    download "$BASE_URL/$SOURCE" "$WORK/files/$NAME" ||
        fail "cannot download $SOURCE"

    EXPECTED=$(awk -v p="$SOURCE" '$2==p {print $1; exit}' "$WORK/SHA256SUMS")
    ACTUAL=$(sha256sum "$WORK/files/$NAME" | awk '{print $1}')

    [ -n "$EXPECTED" ] && [ "$ACTUAL" = "$EXPECTED" ] ||
        fail "SHA256 mismatch: $SOURCE"
done

openssl pkey -pubin -in "$WORK/files/update-public.pem" \
    -noout >/dev/null 2>&1 ||
    fail "invalid Ed25519 public key"

if [ -e "$UPDATER_ROOT" ]; then
    HAD_UPDATER=1
    cp -pR "$UPDATER_ROOT" "$BACKUP/updater" ||
        fail "cannot back up existing updater"
fi

if [ -f "$CONFIG" ]; then
    HAD_CONFIG=1
    mkdir -p "$BACKUP/etc"
    cp -p "$CONFIG" "$BACKUP/etc/update.conf" ||
        fail "cannot back up updater configuration"
fi

if [ -f "$PUBLIC_KEY" ]; then
    HAD_PUBLIC_KEY=1
    mkdir -p "$BACKUP/etc"
    cp -p "$PUBLIC_KEY" "$BACKUP/etc/update-public.pem" ||
        fail "cannot back up updater public key"
fi

if [ -f "$ROOT/VERSION" ]; then
    HAD_VERSION=1
    cp -p "$ROOT/VERSION" "$BACKUP/VERSION" ||
        fail "cannot back up bootstrap version"
fi

crontab -l > "$BACKUP/crontab.before" 2>/dev/null || : > "$BACKUP/crontab.before"

MUTATION_STARTED=1

mkdir -p "$SLOT" "$CONFIG_DIR" "$STATE/pending" "$LOG" \
    /opt/var/cache/vward/updater /opt/var/run/vward ||
    fail "cannot create updater runtime layout"

for F in $UPDATER_FILES; do
    cp "$WORK/files/$F" "$SLOT/$F" || fail "cannot install $F"
    chmod 0755 "$SLOT/$F" || fail "cannot chmod $F"
done

cp "$WORK/files/update-public.pem" "$PUBLIC_KEY" ||
    fail "cannot install public key"
chmod 0644 "$PUBLIC_KEY" || fail "cannot chmod public key"

cp "$WORK/files/update.conf" "$CONFIG" ||
    fail "cannot install updater configuration"
chmod 0600 "$CONFIG" || fail "cannot chmod updater configuration"

# Bootstrap represents the currently installed router source state.
printf '%s\n' '0.1.0-dev' > "$ROOT/VERSION" ||
    fail "cannot initialize VWARD version"
chmod 0644 "$ROOT/VERSION"

ln -s "$SLOT" "$UPDATER_ROOT/current.new.$$" ||
    fail "cannot create updater slot link"
mv -f "$UPDATER_ROOT/current.new.$$" "$CURRENT" ||
    fail "cannot activate updater slot"

{
    grep -vF "$CRON_MARK" "$BACKUP/crontab.before"
    echo "*/15 * * * * $CURRENT/vward-update-watch.sh --once >>/opt/var/log/vward/updater-watch.log 2>&1 $CRON_MARK"
} > "$WORK/crontab.new"

crontab "$WORK/crontab.new" || fail "cannot install updater cron"

"$CURRENT/vward-update.sh" --status ||
    fail "updater status check failed"

"$CURRENT/vward-update-watch.sh" --once
WATCH_RC=$?

case "$WATCH_RC" in
    0|20)
        ;;
    *)
        fail "signed feed check failed: RC=$WATCH_RC"
        ;;
esac

if [ -r "$STATE/pending/manifest.json" ]; then
    PENDING_STATUS=VERIFIED
else
    CURRENT_PHASE=$(sed -n 's/^phase=//p' "$STATE/journal.state" 2>/dev/null || :)
    case "$CURRENT_PHASE" in
        RECOVERY_REQUIRED|ROLLING_BACK)
            # An existing interrupted transaction may have already consumed
            # its pending manifest. Keep the newly installed updater so its
            # corrected rollback path can complete deterministic recovery.
            PENDING_STATUS=RECOVERY_REQUIRED
            ;;
        *)
            fail "verified pending manifest was not stored"
            ;;
    esac
fi

MUTATION_STARTED=0

echo "BOOTSTRAP_BACKUP=$BACKUP"
echo "UPDATER_MODE=CHECK_ONLY"
echo "AUTO_APPLY=0"
echo "PENDING_UPDATE=$PENDING_STATUS"
echo "BOOTSTRAP_RESULT=PASS"
