#!/bin/sh

# Shared primitives for VWARD Smart Updater v1. POSIX sh only.

VU_OK=0
VU_NO_UPDATE=10
VU_DEFERRED=20
VU_CONFIG_ERROR=30
VU_VERIFY_ERROR=31
VU_COMPAT_ERROR=32
VU_SAFETY_ERROR=33
VU_INSTALL_ERROR=40
VU_HEALTH_ERROR=41
VU_ROLLBACK_ERROR=42

VU_ROOT_PREFIX=${VWARD_ROOT_PREFIX:-}
VU_CONFIG=${VWARD_UPDATE_CONFIG:-${VU_ROOT_PREFIX}/opt/etc/vward/update.conf}
VU_STATE_DIR=${VWARD_UPDATE_STATE_DIR:-${VU_ROOT_PREFIX}/opt/var/lib/vward/updater}
VU_LOG_DIR=${VWARD_UPDATE_LOG_DIR:-${VU_ROOT_PREFIX}/opt/var/log/vward}
VU_BACKUP_DIR=${VWARD_UPDATE_BACKUP_DIR:-${VU_ROOT_PREFIX}/opt/var/backups/vward}
VU_RUN_DIR=${VWARD_UPDATE_RUN_DIR:-${VU_ROOT_PREFIX}/opt/var/run/vward}
VU_STAGING_DIR=${VWARD_UPDATE_STAGING_DIR:-${VU_ROOT_PREFIX}/opt/var/cache/vward/updater}

update_enabled=0
auto_apply=0
manifest_url=
public_key_file=${VU_ROOT_PREFIX}/opt/etc/vward/update-public.pem
channel=dev
safe_window_start=03:00
safe_window_end=05:00
minimum_free_kb=8192
backup_keep=3
barrier_integration_ready=0
current_version_file=${VU_ROOT_PREFIX}/opt/share/vward/VERSION
health_timeout_seconds=30
check_interval_seconds=900
request_timeout_seconds=120
minimum_updater_version=1.0.0
VU_REQUEST_MARKER=${VU_ROOT_PREFIX}/tmp/vward-update-requested
VU_BARRIER_LOCK=${VU_ROOT_PREFIX}/tmp/vward-update.lock
VU_REQUEST_OWNED=0
VU_BARRIER_OWNED=0

vu_log() {
    level=$1
    shift
    mkdir -p "$VU_LOG_DIR" 2>/dev/null || :
    message="$(date -u '+%Y-%m-%dT%H:%M:%SZ') [$level] $*"
    printf '%s\n' "$message" >&2
    [ "${VWARD_NO_PERSIST_LOG:-0}" = 1 ] || printf '%s\n' "$message" >> "$VU_LOG_DIR/updater.log" 2>/dev/null || :
}

vu_die() {
    code=$1
    shift
    vu_log ERROR "$*"
    exit "$code"
}

vu_assign_config() {
    key=$1
    value=$2
    case "$key" in
        update_enabled) update_enabled=$value ;;
        auto_apply) auto_apply=$value ;;
        manifest_url) manifest_url=$value ;;
        public_key_file) public_key_file=$value ;;
        channel) channel=$value ;;
        safe_window_start) safe_window_start=$value ;;
        safe_window_end) safe_window_end=$value ;;
        minimum_free_kb) minimum_free_kb=$value ;;
        backup_keep) backup_keep=$value ;;
        barrier_integration_ready) barrier_integration_ready=$value ;;
        current_version_file) current_version_file=$value ;;
        health_timeout_seconds) health_timeout_seconds=$value ;;
        check_interval_seconds) check_interval_seconds=$value ;;
        request_timeout_seconds) request_timeout_seconds=$value ;;
        ''|'#'*) ;;
        *) vu_log WARN "Ignoring unknown config key: $key" ;;
    esac
}

vu_load_config() {
    [ -r "$VU_CONFIG" ] || return 0
    while IFS='=' read -r key value; do
        key=$(printf '%s' "$key" | tr -d ' \t\r')
        value=$(printf '%s' "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        case "$value" in
            \"*\") value=${value#\"}; value=${value%\"} ;;
            \'*\') value=${value#\'}; value=${value%\'} ;;
        esac
        vu_assign_config "$key" "$value"
    done < "$VU_CONFIG"
    case "$update_enabled:$auto_apply:$barrier_integration_ready" in
        [01]:[01]:[01]) ;;
        *) vu_die "$VU_CONFIG_ERROR" "Boolean config values must be 0 or 1" ;;
    esac
}

vu_require_commands() {
    missing=
    for command_name in "$@"; do
        command -v "$command_name" >/dev/null 2>&1 || missing="$missing $command_name"
    done
    [ -z "$missing" ] || vu_die "$VU_CONFIG_ERROR" "Missing required commands:$missing"
}

vu_state_get() {
    key=$1
    file=${2:-$VU_STATE_DIR/state}
    [ -r "$file" ] || return 1
    state_value=$(sed -n "s/^${key}=//p" "$file" | tail -n 1)
    [ -n "$state_value" ] || return 1
    printf '%s\n' "$state_value"
}

vu_state_set() {
    key=$1
    value=$2
    mkdir -p "$VU_STATE_DIR" || return 1
    file=$VU_STATE_DIR/state
    tmp=$file.tmp.$$
    if [ -r "$file" ]; then
        sed "/^${key}=/d" "$file" > "$tmp" || return 1
    else
        : > "$tmp" || return 1
    fi
    printf '%s=%s\n' "$key" "$value" >> "$tmp" || return 1
    chmod 600 "$tmp" || return 1
    mv -f "$tmp" "$file" || return 1
    sync
}

vu_transition() {
    next=$1
    vu_state_set phase "$next" || vu_die "$VU_INSTALL_ERROR" "Cannot persist updater phase"
    vu_state_set phase_changed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" || vu_die "$VU_INSTALL_ERROR" "Cannot persist updater timestamp"
    vu_log INFO "State transition: $next"
}

vu_lock_acquire() {
    mkdir -p "$VU_RUN_DIR" || return 1
    lock=$VU_RUN_DIR/updater.lock
    if mkdir "$lock" 2>/dev/null; then
        printf '%s\n' "$$" > "$lock/pid"
        return 0
    fi
    return 1
}

vu_lock_release() {
    lock=$VU_RUN_DIR/updater.lock
    [ -d "$lock" ] || return 0
    case "$lock" in
        */opt/var/run/vward/updater.lock) rm -f "$lock/pid"; rmdir "$lock" 2>/dev/null || : ;;
        *) vu_log ERROR "Refusing unsafe lock cleanup: $lock" ;;
    esac
}

vu_semver_valid() {
    printf '%s\n' "$1" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$'
}

vu_version_core() {
    printf '%s\n' "${1%%-*}"
}

vu_version_lt() {
    left=$(vu_version_core "$1")
    right=$(vu_version_core "$2")
    old_ifs=$IFS
    IFS=.
    set -- $left
    la=$1 lb=$2 lc=$3
    set -- $right
    ra=$1 rb=$2 rc=$3
    IFS=$old_ifs
    [ "$la" -lt "$ra" ] || { [ "$la" -eq "$ra" ] && [ "$lb" -lt "$rb" ]; } || {
        [ "$la" -eq "$ra" ] && [ "$lb" -eq "$rb" ] && [ "$lc" -lt "$rc" ]
    }
}

vu_manifest_validate() {
    manifest=$1
    jq -e '
      type == "object" and
      (.signed | type == "object") and
      (.signature | type == "string" and length > 0) and
      (.signed.schema == 1) and
      (.signed.update_id | type == "string" and test("^[A-Za-z0-9._-]+$")) and
      (.signed.sequence | type == "number" and floor == . and . >= 1) and
      (.signed.version | type == "string") and
      (.signed.channel | type == "string") and
      (.signed.priority | IN("ROUTINE", "IMPORTANT", "CRITICAL")) and
      (.signed.published_at | type == "string") and
      (.signed.min_updater_version | type == "string") and
      (.signed.package.url | type == "string" and startswith("https://")) and
      (.signed.package.sha256 | test("^[0-9a-f]{64}$")) and
      (.signed.package.size | type == "number" and floor == . and . > 0) and
      (.signed.compatibility.min_vward | type == "string") and
      (.signed.compatibility.max_vward | type == "string") and
      (.signed.affected_components | type == "array") and
      (.signed.affected_services | type == "array") and
      (.signed.health_profile | type == "string") and
      (.signed.requires_reboot | type == "boolean") and
      (.signed.rollback_policy | IN("automatic", "manual")) and
      (.signed.signature.algorithm == "Ed25519") and
      (.signed.signature.key_id | type == "string" and length > 0)
    ' "$manifest" >/dev/null 2>&1
}

vu_manifest_verify_signature() {
    manifest=$1
    [ -r "$public_key_file" ] || return 1
    signed=$VU_STAGING_DIR/signed.json
    signature=$VU_STAGING_DIR/signature.bin
    mkdir -p "$VU_STAGING_DIR" || return 1
    jq -cS '.signed' "$manifest" > "$signed" || return 1
    jq -r '.signature' "$manifest" | openssl base64 -d -A > "$signature" 2>/dev/null || return 1
    openssl pkeyutl -verify -pubin -inkey "$public_key_file" -rawin -in "$signed" -sigfile "$signature" >/dev/null 2>&1
}

vu_manifest_check_policy() {
    manifest=$1
    version=$(jq -r '.signed.version' "$manifest")
    sequence=$(jq -r '.signed.sequence' "$manifest")
    manifest_channel=$(jq -r '.signed.channel' "$manifest")
    current_version=0.0.0
    [ -r "$current_version_file" ] && current_version=$(sed -n '1p' "$current_version_file")
    vu_semver_valid "$version" || return 1
    vu_semver_valid "$current_version" || return 1
    [ "$manifest_channel" = "$channel" ] || return 1
    [ "$(jq -r '.signed.requires_reboot' "$manifest")" = false ] || return 1
    [ "$(jq -r '.signed.affected_services | length' "$manifest")" -eq 0 ] || return 1
    last_sequence=$(vu_state_get last_sequence 2>/dev/null || printf '0')
    [ "$sequence" -gt "$last_sequence" ] || return 1
    vu_version_lt "$current_version" "$version" || return 1
    required_updater=$(jq -r '.signed.min_updater_version' "$manifest")
    vu_semver_valid "$required_updater" || return 1
    vu_version_lt "$minimum_updater_version" "$required_updater" && return 1
    min=$(jq -r '.signed.compatibility.min_vward' "$manifest")
    max=$(jq -r '.signed.compatibility.max_vward' "$manifest")
    vu_semver_valid "$min" && vu_semver_valid "$max" || return 1
    vu_version_lt "$current_version" "$min" && return 1
    vu_version_lt "$max" "$current_version" && return 1
    return 0
}

vu_fetch() {
    url=$1
    output=$2
    case "$url" in https://*) ;; *) return 1 ;; esac
    tmp=$output.part.$$
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
        --connect-timeout 15 --max-time 180 --retry 3 --retry-all-errors \
        --output "$tmp" "$url" || { rm -f "$tmp"; return 1; }
    mv -f "$tmp" "$output"
}

vu_safe_target() {
    target=$1
    case "$target" in *../*|*/..|*/./*|*//* ) return 1 ;; esac
    case "$target" in
        /opt/bin/*.sh|/opt/etc/init.d/S[0-9][0-9]*|/opt/etc/lighttpd/*.conf|/opt/share/keenetic-apps/www/*|/opt/share/vward/*) return 0 ;;
        *) return 1 ;;
    esac
}

vu_local_target() {
    case "$1" in
        /opt/etc/vward/*|/opt/var/*|/tmp/*|/opt/share/vward/updater/*|*/hints.conf|*/skip-domains.conf|*.bak|*.before-*|*.failed-*) return 0 ;;
        *) return 1 ;;
    esac
}

vu_package_validate() {
    package_dir=$1
    package_manifest=$package_dir/package-manifest.json
    jq -e '.schema == 1 and (.files | type == "array" and length > 0) and all(.files[]; (.source | type == "string") and (.target | type == "string") and (.sha256 | test("^[0-9a-f]{64}$")) and (.mode | test("^(0644|0755)$")) and (.component | type == "string" and length > 0) and (.restart_policy | IN("none", "deferred")) and (.config_policy == "program-only"))' "$package_manifest" >/dev/null 2>&1 || return 1
    jq -r '.files[] | [.source,.target,.sha256,.mode] | @tsv' "$package_manifest" |
    while IFS="$(printf '\t')" read -r source target expected mode; do
        case "$source" in ''|..|/*|*../*|../*|*/..) return 1 ;; esac
        vu_safe_target "$target" || return 1
        vu_local_target "$target" && return 1
        [ -f "$package_dir/$source" ] || return 1
        actual=$(sha256sum "$package_dir/$source" | awk '{print $1}')
        [ "$actual" = "$expected" ] || return 1
        [ "$mode" = 0644 ] || [ "$mode" = 0755 ] || return 1
    done
}

vu_in_safe_window() {
    now=$(date '+%H:%M')
    if [ "$safe_window_start" \< "$safe_window_end" ]; then
        [ "$now" \> "$safe_window_start" ] && [ "$now" \< "$safe_window_end" ]
    else
        [ "$now" \> "$safe_window_start" ] || [ "$now" \< "$safe_window_end" ]
    fi
}

vu_safety_check() {
    priority=$1
    [ "$barrier_integration_ready" = 1 ] || return 1
    [ ! -e "$VU_RUN_DIR/runtime-active" ] || return 1
    for conflict in "$VU_ROOT_PREFIX/tmp/adaptive-auto-maint.lock" "$VU_ROOT_PREFIX/tmp/agh-adaptive-live.lock" "$VU_ROOT_PREFIX/tmp/vpn-domain-audit.lock" "$VU_ROOT_PREFIX/tmp/vpn-night-reconcile.lock" "$VU_ROOT_PREFIX/tmp/wg-failopen.lock" "$VU_ROOT_PREFIX/tmp/wan-guardian.lock"; do
        [ ! -e "$conflict" ] || return 1
    done
    mkdir -p "$VU_STAGING_DIR" "$VU_BACKUP_DIR" || return 1
    [ -w "$VU_STAGING_DIR" ] && [ -w "$VU_BACKUP_DIR" ] || return 1
    free_kb=$(df -Pk "$VU_STATE_DIR" 2>/dev/null | awk 'NR==2 {print $4}')
    [ -n "$free_kb" ] && [ "$free_kb" -ge "$minimum_free_kb" ] || return 1
    case "$priority" in
        CRITICAL) return 0 ;;
        IMPORTANT|ROUTINE) vu_in_safe_window ;;
        *) return 1 ;;
    esac
}

vu_barrier_enter() {
    mkdir -p "$(dirname "$VU_REQUEST_MARKER")" || return 1
    : > "$VU_REQUEST_MARKER" || return 1
    VU_REQUEST_OWNED=1
    waited=0
    while [ -e "$VU_RUN_DIR/runtime-active" ] && [ "$waited" -lt "$request_timeout_seconds" ]; do
        sleep 1
        waited=$((waited + 1))
    done
    [ ! -e "$VU_RUN_DIR/runtime-active" ] || return 1
    mkdir "$VU_BARRIER_LOCK" 2>/dev/null || return 1
    VU_BARRIER_OWNED=1
    printf '%s\n' "$$" > "$VU_BARRIER_LOCK/pid"
}

vu_barrier_leave() {
    [ "$VU_REQUEST_OWNED" = 0 ] || rm -f "$VU_REQUEST_MARKER"
    if [ "$VU_BARRIER_OWNED" = 1 ] && [ -d "$VU_BARRIER_LOCK" ]; then
        rm -f "$VU_BARRIER_LOCK/pid"
        rmdir "$VU_BARRIER_LOCK" 2>/dev/null || :
    fi
}
