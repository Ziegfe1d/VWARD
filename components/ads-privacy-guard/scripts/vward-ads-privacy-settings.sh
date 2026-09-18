#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"

ads_mkdirs || ads_die "cannot create component directories"
[ -r "$ADS_CONFIG" ] || ads_die "config not readable: $ADS_CONFIG"

OP="${1:-show}"
shift 2>/dev/null || true

show_settings()
{
    # Output only the Console-safe settings contract. Do not expose arbitrary
    # shell config or secrets through the web API.
    awk -F= '
        $1 ~ /^(ENABLED|RUN_MODE|SCHEDULE_INTERVAL_MIN|DYNAMIC_MIN_INTERVAL_SEC|DYNAMIC_MAX_LOAD_PER_CPU_X100|DYNAMIC_MIN_MEM_AVAILABLE_KB|DYNAMIC_MIN_OPT_FREE_KB|DYNAMIC_MAX_CANDIDATES_PER_RUN|AUTO_SOURCE_UPDATE|SOURCE_UPDATE_INTERVAL_HOURS|AUTO_PUBLISH|PUBLISH_MODE|QUERY_SOURCE|AUTO_RULE_SCOPE|SCAN_TAIL_LINES|MAX_CANDIDATES_PER_RUN)$/ {
            print $1 "=" substr($0,index($0,"=")+1)
        }
    ' "$ADS_CONFIG"
    PAUSED=0
    [ -r "$ADS_CONTROL_STATE" ] && PAUSED="$(awk -F= '$1=="paused"{print $2; exit}' "$ADS_CONTROL_STATE")"
    case "$PAUSED" in 1) ;; *) PAUSED=0 ;; esac
    echo "PAUSED=$PAUSED"
}

validate_num()
{
    V="$1" MIN="$2" MAX="$3"
    case "$V" in ''|*[!0-9]*) return 1 ;; esac
    [ "$V" -ge "$MIN" ] && [ "$V" -le "$MAX" ]
}

validate_pair()
{
    K="$1" V="$2"
    case "$K" in
        ENABLED|AUTO_SOURCE_UPDATE|AUTO_PUBLISH)
            case "$V" in 0|1) return 0 ;; *) return 1 ;; esac
            ;;
        RUN_MODE)
            case "$V" in manual|scheduled|dynamic) return 0 ;; *) return 1 ;; esac
            ;;
        PUBLISH_MODE)
            case "$V" in staged|user_rules_api) return 0 ;; *) return 1 ;; esac
            ;;
        QUERY_SOURCE)
            case "$V" in auto|api|file) return 0 ;; *) return 1 ;; esac
            ;;
        AUTO_RULE_SCOPE)
            case "$V" in exact|suffix) return 0 ;; *) return 1 ;; esac
            ;;
        SCHEDULE_INTERVAL_MIN) validate_num "$V" 5 1440 ;;
        DYNAMIC_MIN_INTERVAL_SEC) validate_num "$V" 60 3600 ;;
        DYNAMIC_MAX_LOAD_PER_CPU_X100) validate_num "$V" 20 300 ;;
        DYNAMIC_MIN_MEM_AVAILABLE_KB) validate_num "$V" 4096 1048576 ;;
        DYNAMIC_MIN_OPT_FREE_KB) validate_num "$V" 8192 10485760 ;;
        DYNAMIC_MAX_CANDIDATES_PER_RUN) validate_num "$V" 10 500 ;;
        SOURCE_UPDATE_INTERVAL_HOURS) validate_num "$V" 6 168 ;;
        SCAN_TAIL_LINES) validate_num "$V" 1000 200000 ;;
        MAX_CANDIDATES_PER_RUN) validate_num "$V" 10 5000 ;;
        *) return 1 ;;
    esac
}

set_key()
{
    FILE="$1" K="$2" V="$3" OUT="$4"
    awk -v k="$K" -v v="$V" '
        BEGIN{done=0}
        index($0,k "=")==1 {if(!done){print k "=" v; done=1}; next}
        {print}
        END{if(!done) print k "=" v}
    ' "$FILE" > "$OUT"
}

case "$OP" in
    show)
        show_settings
        exit 0
        ;;
    set)
        [ "$#" -ge 2 ] && [ $(( $# % 2 )) -eq 0 ] || {
            echo "Usage: $0 set KEY VALUE [KEY VALUE ...]" >&2
            exit 2
        }
        ;;
    *)
        echo "Usage: $0 {show|set KEY VALUE [KEY VALUE ...]}" >&2
        exit 2
        ;;
esac

STAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP_DIR="$ADS_BACKUP_ROOT/settings/$STAMP"
mkdir -p "$BACKUP_DIR" || ads_die "cannot create settings backup"
chmod 0700 "$BACKUP_DIR"
cp -p "$ADS_CONFIG" "$BACKUP_DIR/ads-privacy-guard.conf.before" || ads_die "config backup failed"

WORK="$ADS_STATE/work/settings.$$"
mkdir -p "$WORK" || ads_die "cannot create settings workdir"
trap 'rm -rf "$WORK"' EXIT
trap 'exit 1' HUP INT TERM
cp "$ADS_CONFIG" "$WORK/current" || ads_die "cannot stage config"

while [ "$#" -gt 0 ]; do
    KEY="$1"; VALUE="$2"; shift 2
    validate_pair "$KEY" "$VALUE" || ads_die "invalid setting: $KEY=$VALUE"
    set_key "$WORK/current" "$KEY" "$VALUE" "$WORK/next" || ads_die "cannot update $KEY"
    mv "$WORK/next" "$WORK/current" || ads_die "cannot stage $KEY"
done

# Shell syntax is a useful final gate because config is sourced by POSIX sh.
/bin/sh -n "$WORK/current" >/dev/null 2>&1 || ads_die "resulting config syntax invalid"
chmod 0600 "$WORK/current" || ads_die "cannot chmod staged config"

TMP="${ADS_CONFIG}.new.$$"
cp "$WORK/current" "$TMP" || ads_die "cannot prepare install temp"
chmod 0600 "$TMP" || { rm -f "$TMP"; ads_die "cannot chmod install temp"; }
if ! mv "$TMP" "$ADS_CONFIG"; then
    cp -p "$BACKUP_DIR/ads-privacy-guard.conf.before" "$ADS_CONFIG" 2>/dev/null || true
    ads_die "config install failed; rollback attempted"
fi

# Re-read and verify only Console-safe values are syntactically usable.
if ! /bin/sh -n "$ADS_CONFIG" >/dev/null 2>&1; then
    cp -p "$BACKUP_DIR/ads-privacy-guard.conf.before" "$ADS_CONFIG" 2>/dev/null || true
    ads_die "installed config failed validation; rollback attempted"
fi

ads_log "SETTINGS|saved|backup=$BACKUP_DIR"
echo "SETTINGS=PASS"
echo "BACKUP_DIR=$BACKUP_DIR"
show_settings
exit 0
