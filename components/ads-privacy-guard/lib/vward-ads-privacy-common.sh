#!/bin/sh

# Shared helpers for VWARD Ads & Privacy Guard.
# POSIX/BusyBox compatible. Functions use subshells where practical so helper
# variables cannot overwrite caller state.

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

VWARD_ADS_VERSION="0.2.0-rc.1.fix.2"

ADS_ETC="${VWARD_ADS_ETC:-/opt/etc/vward/ads-privacy-guard}"
ADS_STATE="${VWARD_ADS_STATE:-/opt/var/lib/vward/ads-privacy-guard}"
ADS_LOG_DIR="${VWARD_ADS_LOG_DIR:-/opt/var/log}"
ADS_BACKUP_ROOT="${VWARD_ADS_BACKUP_ROOT:-/opt/var/backups/vward/ads-privacy-guard}"
ADS_SHARE="${VWARD_ADS_SHARE:-/opt/share/vward/ads-privacy-guard}"
ADS_CONFIG="${VWARD_ADS_CONFIG:-$ADS_ETC/ads-privacy-guard.conf}"
ADS_LOG="${VWARD_ADS_LOG:-$ADS_LOG_DIR/vward-ads-privacy-guard.log}"
ADS_SOURCE_REGISTRY="${VWARD_ADS_SOURCE_REGISTRY:-$ADS_SHARE/source-registry.json}"
ADS_TRUST_BUILTIN="${VWARD_ADS_TRUST_BUILTIN:-$ADS_SHARE/trust-core.tsv}"
ADS_ALLOWLIST="${VWARD_ADS_ALLOWLIST:-$ADS_ETC/allowlist.tsv}"
ADS_DENYLIST="${VWARD_ADS_DENYLIST:-$ADS_ETC/denylist.tsv}"
ADS_SOURCE_OVERRIDES="${VWARD_ADS_SOURCE_OVERRIDES:-$ADS_ETC/source-overrides.tsv}"
ADS_CONTROL_STATE="${VWARD_ADS_CONTROL_STATE:-$ADS_STATE/control.state}"
ADS_RUNTIME_STATUS="${VWARD_ADS_RUNTIME_STATUS:-/tmp/vward-ads-privacy-guard-current.status}"
ADS_SCHEDULER_STATUS="${VWARD_ADS_SCHEDULER_STATUS:-/tmp/vward-ads-scheduler.status}"
ADS_QUERYLOG="${VWARD_ADS_QUERYLOG:-/opt/etc/AdGuardHome/data/querylog.json}"
ADS_QUERYLOG_OLD="${VWARD_ADS_QUERYLOG_OLD:-/opt/etc/AdGuardHome/data/querylog.json.1}"
ADS_JQ="${VWARD_ADS_JQ:-/opt/bin/jq}"
ADS_CURL="${VWARD_ADS_CURL:-/opt/bin/curl}"
ADS_DEVICE_PROFILE_LIB="${VWARD_ADS_DEVICE_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"
ADS_DEVICE_CONFIG="${VWARD_ADS_DEVICE_CONFIG:-/opt/etc/vward/device.conf}"
ADS_AGH_AUTH_FILE="${VWARD_ADS_AGH_AUTH_FILE:-$ADS_ETC/agh-api.auth}"
ADS_CUSTOM_SOURCES="${VWARD_ADS_CUSTOM_SOURCES:-$ADS_ETC/custom-sources.json}"

# User sources added from the Console are merged into the built-in registry.
# Every field is rebuilt from a strictly validated subset, so a hand-edited
# file cannot add options, weights or URLs outside the allowed form.
ads_source_registry_merge()
{
    [ -s "$ADS_CUSTOM_SOURCES" ] && [ -r "$ADS_SOURCE_REGISTRY" ] && [ -x "$ADS_JQ" ] || return 0
    ads_srm_out="$ADS_STATE/source-registry.merged.json"
    mkdir -p "$ADS_STATE" 2>/dev/null || return 0
    "$ADS_JQ" -s '
        .[0] as $b
        | [.[1].sources[]?
           | select((.id | type) == "string" and (.id | test("^custom-[a-f0-9]{10}$")))
           | select((.url | type) == "string" and (.url | test("^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?/[A-Za-z0-9._~/%+=&?-]*$")) and (.url | length) <= 300)
           | select(.format | IN("adblock", "hosts", "domains"))
           | {id, name: ("Свой: " + (.url | sub("^https://"; "") | .[:60])), vendor: "custom", independence_group: .id,
              purpose: "custom", enabled: true, weight: 40, single_source_block: false, format,
              min_entries: 10, max_bytes: 8388608, urls: [.url], homepage: .url, default_mode: "check", custom: true}] as $c
        | $b | .sources += [$c[] | select(.id as $i | ($b.sources | map(.id) | index($i)) == null)] | .sources |= .[:40]
    ' "$ADS_SOURCE_REGISTRY" "$ADS_CUSTOM_SOURCES" > "$ads_srm_out.$$" 2>/dev/null &&
        mv -f "$ads_srm_out.$$" "$ads_srm_out" 2>/dev/null &&
        ADS_SOURCE_REGISTRY="$ads_srm_out" || rm -f "$ads_srm_out.$$" 2>/dev/null
    return 0
}
ads_source_registry_merge

ads_now() { date '+%Y-%m-%d %H:%M:%S'; }
ads_epoch() { date '+%s'; }

ads_log() (
    mkdir -p "$ADS_LOG_DIR" 2>/dev/null || true
    printf '%s|%s\n' "$(ads_now)" "$*" >> "$ADS_LOG" 2>/dev/null || true
)

ads_die()
{
    ads_log "FAIL|$*"
    echo "FAIL: $*" >&2
    exit 1
}

ads_bool()
{
    case "${1:-}" in 1|yes|YES|true|TRUE|on|ON) return 0 ;; *) return 1 ;; esac
}

ads_num()
{
    case "${1:-}" in ''|*[!0-9]*) echo "$2" ;; *) echo "$1" ;; esac
}

ads_require() { [ -x "$1" ] || ads_die "required executable missing: $1"; }

ads_admission_enter()
{
    ads_ae_component=${1:-ads-privacy}
    ads_ae_lib=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
    [ -r "$ads_ae_lib" ] || ads_ae_lib="${SELF_DIR:-.}/../../runtime/lib/vward-runtime-admission.sh"
    [ -r "$ads_ae_lib" ] || ads_die "runtime admission library unavailable"
    . "$ads_ae_lib"
    vward_admission_enter "$ads_ae_component" || exit $?
}

ads_admission_leave()
{
    command -v vward_admission_leave >/dev/null 2>&1 && vward_admission_leave 2>/dev/null || true
}

ads_mkdirs()
{
    mkdir -p "$ADS_ETC" "$ADS_STATE" "$ADS_STATE/sources" "$ADS_STATE/generated" \
        "$ADS_STATE/work" "$ADS_STATE/jobs" "$ADS_BACKUP_ROOT" "$ADS_LOG_DIR"
}

ads_secure_file_ok() (
    ads_sf_file="$1"
    [ -r "$ads_sf_file" ] || return 1
    # Keenetic's BusyBox stat has no -c, so owner and mode come from ls.
    ads_sf_meta="$(ls -ln "$ads_sf_file" 2>/dev/null | awk '{sub(/[.+]$/, "", $1); print $3, $1}')"
    case "$ads_sf_meta" in "0 -rw-------"|"0 -r--------") return 0 ;; *) return 1 ;; esac
)

ads_load_config()
{
    [ -r "$ADS_CONFIG" ] || ads_die "config not readable: $ADS_CONFIG"
    if [ "${ADS_REQUIRE_SECURE_CONFIG:-1}" = 1 ] && ! ads_secure_file_ok "$ADS_CONFIG"; then
        ads_die "config must be root-owned and mode 0600 or 0400: $ADS_CONFIG"
    fi
    # Trusted root-owned shell-style local configuration, matching VWARD conventions.
    . "$ADS_CONFIG"
}

ads_pid_start() (
    ads_ps_pid="${1:-$$}"
    case "$ads_ps_pid" in ''|*[!0-9]*) return 1 ;; esac
    [ -r "/proc/$ads_ps_pid/stat" ] || return 1
    # starttime is field 22. Strip pid/comm first because comm may contain spaces.
    sed 's/^.*) //' "/proc/$ads_ps_pid/stat" 2>/dev/null | awk 'NF>=20 {print $20; exit}'
)

ads_lock_create() (
    ads_lc_dir="$1"
    mkdir "$ads_lc_dir" 2>/dev/null || return 1
    chmod 0700 "$ads_lc_dir" 2>/dev/null || { rmdir "$ads_lc_dir" 2>/dev/null; return 1; }
    ads_lc_started="$(ads_epoch)"
    ads_lc_pid_start="$(ads_pid_start $$ 2>/dev/null)" || ads_lc_pid_start=unknown
    if ! printf '%s\n' "$$" > "$ads_lc_dir/pid" ||
       ! printf '%s\n' "$ads_lc_started" > "$ads_lc_dir/started" ||
       ! printf '%s\n' "$ads_lc_pid_start" > "$ads_lc_dir/pid_start"; then
        rm -f "$ads_lc_dir/pid" "$ads_lc_dir/started" "$ads_lc_dir/pid_start" 2>/dev/null
        rmdir "$ads_lc_dir" 2>/dev/null
        return 1
    fi
    chmod 0600 "$ads_lc_dir/pid" "$ads_lc_dir/started" "$ads_lc_dir/pid_start" 2>/dev/null || {
        rm -f "$ads_lc_dir/pid" "$ads_lc_dir/started" "$ads_lc_dir/pid_start" 2>/dev/null
        rmdir "$ads_lc_dir" 2>/dev/null
        return 1
    }
)

ads_lock_acquire() (
    ads_l_dir="$1"
    ads_l_stale="$(ads_num "${2:-900}" 900)"
    [ -n "$ads_l_dir" ] || return 1
    [ ! -L "$ads_l_dir" ] || return 1
    ads_lock_create "$ads_l_dir" && return 0
    [ -d "$ads_l_dir" ] && [ ! -L "$ads_l_dir" ] || return 1

    ads_l_pid="$(cat "$ads_l_dir/pid" 2>/dev/null)"
    case "$ads_l_pid" in ''|*[!0-9]*) ads_l_pid=0 ;; esac
    ads_l_alive=0
    if [ "$ads_l_pid" -gt 0 ] && kill -0 "$ads_l_pid" 2>/dev/null; then
        ads_l_saved_start="$(cat "$ads_l_dir/pid_start" 2>/dev/null)"
        ads_l_live_start="$(ads_pid_start "$ads_l_pid" 2>/dev/null)" || ads_l_live_start=unknown
        # Legacy locks have no pid_start and retain their former conservative
        # liveness behavior. New locks distinguish a reused PID.
        if [ -z "$ads_l_saved_start" ] || [ "$ads_l_saved_start" = unknown ] || [ "$ads_l_saved_start" = "$ads_l_live_start" ]; then
            ads_l_alive=1
        fi
    fi
    [ "$ads_l_alive" -eq 0 ] || return 1

    ads_l_started="$(ads_num "$(cat "$ads_l_dir/started" 2>/dev/null)" 0)"
    ads_l_now="$(ads_epoch)"
    [ "$ads_l_started" -eq 0 ] || [ $((ads_l_now - ads_l_started)) -ge "$ads_l_stale" ] || return 1

    # Atomic rename elects exactly one stale-lock breaker. Never recursively
    # delete the public lock path: it may already belong to a successor.
    ads_l_old="${ads_l_dir}.stale.$$"
    [ ! -e "$ads_l_old" ] && [ ! -L "$ads_l_old" ] || return 1
    mv "$ads_l_dir" "$ads_l_old" 2>/dev/null || return 1
    rm -f "$ads_l_old/pid" "$ads_l_old/started" "$ads_l_old/pid_start" 2>/dev/null
    rmdir "$ads_l_old" 2>/dev/null || true
    ads_lock_create "$ads_l_dir"
)

ads_lock_release() (
    ads_lr_dir="${1:-}"
    [ -n "$ads_lr_dir" ] && [ -d "$ads_lr_dir" ] && [ ! -L "$ads_lr_dir" ] || return 1
    ads_lr_pid="$(cat "$ads_lr_dir/pid" 2>/dev/null)"
    [ "$ads_lr_pid" = "$$" ] || return 1
    ads_lr_saved_start="$(cat "$ads_lr_dir/pid_start" 2>/dev/null)"
    ads_lr_own_start="$(ads_pid_start $$ 2>/dev/null)" || ads_lr_own_start=unknown
    [ -z "$ads_lr_saved_start" ] || [ "$ads_lr_saved_start" = unknown ] || [ "$ads_lr_saved_start" = "$ads_lr_own_start" ] || return 1
    rm -f "$ads_lr_dir/pid" "$ads_lr_dir/started" "$ads_lr_dir/pid_start" 2>/dev/null || return 1
    rmdir "$ads_lr_dir" 2>/dev/null
)

ads_atomic_copy() (
    ads_ac_src="$1"; ads_ac_dest="$2"; ads_ac_mode="${3:-0644}"
    ads_ac_tmp="${ads_ac_dest}.new.$$"
    mkdir -p "$(dirname "$ads_ac_dest")" || return 1
    cp "$ads_ac_src" "$ads_ac_tmp" || { rm -f "$ads_ac_tmp"; return 1; }
    chmod "$ads_ac_mode" "$ads_ac_tmp" || { rm -f "$ads_ac_tmp"; return 1; }
    mv "$ads_ac_tmp" "$ads_ac_dest" || { rm -f "$ads_ac_tmp"; return 1; }
)

# Installs SRC only when it differs from DEST: an unchanged result is not
# rewritten on USB.
ads_install_if_changed()
{
    cmp -s "$1" "$2" 2>/dev/null && return 0
    ads_atomic_copy "$1" "$2" "${3:-0644}"
}

# Scratch directory for one run: RAM when /tmp has room, USB otherwise.
ads_scratch_dir()
{
    ads_sd_need="$(ads_num "${ADS_SCRATCH_RAM_MIN_KB:-32768}" 32768)"
    ads_sd_free="$(df -Pk /tmp 2>/dev/null | awk 'NR==2 {print $4+0}')"
    if [ "$(ads_num "$ads_sd_free" 0)" -ge "$ads_sd_need" ]; then
        echo "/tmp/vward-ads-$1.$$"
    else
        echo "$ADS_STATE/work/$1.$$"
    fi
}

ads_valid_domain()
{
    printf '%s\n' "$1" | awk '
      length($0)<1 || length($0)>253 {exit 1}
      $0 ~ /\.\./ {exit 1}
      $0 !~ /^[a-z0-9_][a-z0-9_.-]*[a-z0-9_]$/ {exit 1}
      index($0,".")==0 {exit 1}
      {exit 0}'
}

ads_normalize_domain()
{
    printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' |
      sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^\.//;s/\.$//'
}

ads_is_reverse_or_local_name()
{
    case "$1" in *.in-addr.arpa|*.ip6.arpa|localhost|*.localhost|*.local|*.lan|*.home.arpa|retracker.local) return 0 ;; esac
    return 1
}

ads_source_domain_normalize()
{
    awk '
    function emit(d) {
        gsub(/\r/,"",d); d=tolower(d); sub(/^\*\./,"",d); sub(/^\./,"",d); sub(/\.$/,"",d)
        if (length(d)>0 && length(d)<=253 && d ~ /^[a-z0-9_][a-z0-9_.-]*[a-z0-9_]$/ && index(d,".")>0 && d !~ /\.\./) print d
    }
    {
        gsub(/\r/,""); line=$0; sub(/^[ \t]+/,"",line); sub(/[ \t]+$/, "", line)
        if (line=="" || line ~ /^[!#\[]/) next
        if (line ~ /^@@/) next
        if (line ~ /##|#@#|#\?#/) next
        if (line ~ /^\|\|/) {x=line; sub(/^\|\|/,"",x); sub(/\^.*/,"",x); if (x !~ /[\/*?=&:]/) emit(x); next}
        if (line ~ /^(0\.0\.0\.0|127\.0\.0\.1|::1)[ \t]+/) {n=split(line,a,/[ \t]+/); if(n>=2)emit(a[2]); next}
        if (line ~ /^[A-Za-z0-9_][A-Za-z0-9_.-]*[A-Za-z0-9_]$/) {emit(line); next}
    }' | sort -u
}

ads_source_exception_normalize()
{
    awk '
    function emit(d) {
        gsub(/\r/,"",d); d=tolower(d); sub(/^\*\./,"",d); sub(/^\./,"",d); sub(/\.$/,"",d)
        if (length(d)>0 && length(d)<=253 && d ~ /^[a-z0-9_][a-z0-9_.-]*[a-z0-9_]$/ && index(d,".")>0 && d !~ /\.\./) print d
    }
    {gsub(/\r/,""); line=$0; sub(/^[ \t]+/,"",line); sub(/[ \t]+$/, "", line); if(line !~ /^@@\|\|/)next; x=line; sub(/^@@\|\|/,"",x); sub(/\^.*/,"",x); if(x !~ /[\/*?=&:]/)emit(x)}' | sort -u
}

ads_trust_match_file() (
    ads_tm_domain="$1"; ads_tm_file="$2"
    [ -r "$ads_tm_file" ] || return 1
    awk -F'|' -v d="$ads_tm_domain" '
      /^[[:space:]]*#/ || NF<2 {next}
      {p=tolower($1); scope=tolower($2); if(scope=="exact"&&d==p){print $0;exit} if(scope=="suffix"&&(d==p||(length(d)>length(p)&&substr(d,length(d)-length(p))=="." p))){print $0;exit}}' "$ads_tm_file"
)

ads_allowlist_match() { [ -n "$(ads_trust_match_file "$1" "$ADS_ALLOWLIST")" ]; }
ads_denylist_match() { [ -n "$(ads_trust_match_file "$1" "$ADS_DENYLIST")" ]; }
ads_builtin_trust_match() { [ -n "$(ads_trust_match_file "$1" "$ADS_TRUST_BUILTIN")" ]; }

ads_source_mode() (
    ads_sm_sid="$1"
    ads_sm_mode=""
    if [ -r "$ADS_SOURCE_OVERRIDES" ]; then
        ads_sm_mode="$(awk -F'|' -v s="$ads_sm_sid" '$1==s {print tolower($2); exit}' "$ADS_SOURCE_OVERRIDES")"
    fi
    case "$ads_sm_mode" in active|check|off) echo "$ads_sm_mode"; return 0 ;; esac
    [ -r "$ADS_SOURCE_REGISTRY" ] && [ -x "$ADS_JQ" ] || { echo off; return 0; }
    ads_sm_mode="$($ADS_JQ -r --arg id "$ads_sm_sid" '.sources[] | select(.id==$id) | (.default_mode // (if .enabled==true then "active" else "off" end))' "$ADS_SOURCE_REGISTRY" 2>/dev/null | head -n1)"
    case "$ads_sm_mode" in active|check|off) echo "$ads_sm_mode" ;; *) echo off ;; esac
)

ads_rule_for() (
    ads_rf_domain="$1"; ads_rf_scope="${2:-exact}"
    case "$ads_rf_scope" in exact) printf '%s\n' "$ads_rf_domain" ;; suffix) printf '||%s^\n' "$ads_rf_domain" ;; *) return 1 ;; esac
)

ads_file_sha256() (
    ads_fs_file="$1"
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$ads_fs_file" | awk '{print $1}'
    elif command -v openssl >/dev/null 2>&1; then openssl dgst -sha256 "$ads_fs_file" 2>/dev/null | awk '{print $NF}'
    else echo UNAVAILABLE; fi
)

ads_load_device_profile() (
    [ -r "$ADS_DEVICE_PROFILE_LIB" ] || return 1
    VWARD_DEVICE_CONFIG="$ADS_DEVICE_CONFIG"; export VWARD_DEVICE_CONFIG
    . "$ADS_DEVICE_PROFILE_LIB" || return 1
    vward_profile_load >/dev/null 2>&1 || return 1
    printf '%s|%s\n' "${VWARD_ADGUARD_ADDRESS:-}" "${VWARD_ADGUARD_PORT:-}"
)

ads_agh_api_base() (
    if [ -n "${AGH_API_BASE:-}" ]; then printf '%s\n' "${AGH_API_BASE%/}"; return 0; fi
    ads_ab_profile="$(ads_load_device_profile 2>/dev/null)" || return 1
    ads_ab_host="${ads_ab_profile%%|*}"; ads_ab_port="${ads_ab_profile#*|}"
    [ -n "$ads_ab_host" ] && [ -n "$ads_ab_port" ] || return 1
    printf 'http://%s:%s/control\n' "$ads_ab_host" "$ads_ab_port"
)

ads_agh_curl_auth_args() (
    if [ -r "$ADS_AGH_AUTH_FILE" ]; then
        ads_auth_meta="$(ls -ln "$ADS_AGH_AUTH_FILE" 2>/dev/null | awk '{sub(/[.+]$/, "", $1); print $3, $1}')"
        case "$ads_auth_meta" in "0 -rw-------"|"0 -r--------") ;; *) return 1 ;; esac
        printf '%s\n' "$(cat "$ADS_AGH_AUTH_FILE")"
    fi
)

ads_agh_api_get() (
    ads_ag_path="$1"; ads_ag_out="$2"
    ads_ag_base="$(ads_agh_api_base)" || return 2
    ads_ag_auth="$(ads_agh_curl_auth_args 2>/dev/null || true)"
    if [ -n "$ads_ag_auth" ]; then
        "$ADS_CURL" -f -sS --connect-timeout "${AGH_API_CONNECT_TIMEOUT:-3}" --max-time "${AGH_API_MAX_TIME:-15}" -u "$ads_ag_auth" "$ads_ag_base/$ads_ag_path" -o "$ads_ag_out"
    else
        "$ADS_CURL" -f -sS --connect-timeout "${AGH_API_CONNECT_TIMEOUT:-3}" --max-time "${AGH_API_MAX_TIME:-15}" "$ads_ag_base/$ads_ag_path" -o "$ads_ag_out"
    fi
)

ads_agh_api_post() (
    ads_ap_path="$1"; ads_ap_json="$2"; ads_ap_out="$3"
    ads_ap_base="$(ads_agh_api_base)" || return 2
    ads_ap_auth="$(ads_agh_curl_auth_args 2>/dev/null || true)"
    if [ -n "$ads_ap_auth" ]; then
        "$ADS_CURL" -f -sS --connect-timeout "${AGH_API_CONNECT_TIMEOUT:-3}" --max-time "${AGH_API_MAX_TIME:-15}" -u "$ads_ap_auth" -H 'Content-Type: application/json' --data-binary "@$ads_ap_json" "$ads_ap_base/$ads_ap_path" -o "$ads_ap_out"
    else
        "$ADS_CURL" -f -sS --connect-timeout "${AGH_API_CONNECT_TIMEOUT:-3}" --max-time "${AGH_API_MAX_TIME:-15}" -H 'Content-Type: application/json' --data-binary "@$ads_ap_json" "$ads_ap_base/$ads_ap_path" -o "$ads_ap_out"
    fi
)
