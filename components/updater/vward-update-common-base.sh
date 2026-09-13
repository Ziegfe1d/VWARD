#!/bin/sh

# Shared primitives for VWARD Update Engine. POSIX sh only.

VU_OK=0
VU_NO_UPDATE=10
VU_QUARANTINED=11
VU_DEFERRED=20
VU_CONFIG_ERROR=30
VU_VERIFY_ERROR=31
VU_COMPAT_ERROR=32
VU_SAFETY_ERROR=33
VU_NETWORK_ERROR=34
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
auto_critical=0
auto_important=0
auto_routine=0
manifest_url=
public_key_file=${VU_ROOT_PREFIX}/opt/etc/vward/update-public.pem
channel=dev
safe_window_start=03:00
safe_window_end=05:00
minimum_free_kb=8192
max_manifest_size=262144
max_package_size=16777216
max_unpacked_size=67108864
backup_keep=3
barrier_integration_ready=0
current_version_file=${VU_ROOT_PREFIX}/opt/share/vward/VERSION
health_timeout_seconds=30
check_interval_seconds=900
request_timeout_seconds=120
important_max_delay_seconds=7200
routine_max_delay_seconds=86400
minimum_updater_version=1.2.0

VU_REQUEST_MARKER=${VU_ROOT_PREFIX}/tmp/vward-update-requested
VU_BARRIER_LOCK=${VU_ROOT_PREFIX}/tmp/vward-update.lock
VU_REQUEST_OWNED=0
VU_BARRIER_OWNED=0
VU_LOCK_OWNED=0
VU_LOCK_TOKEN=
VU_RUNTIME_QUIESCED=0
VU_RESTART_CROND=0
VU_RESTART_LIVE=0
VU_RESTART_SUPERVISOR=0
VU_COMMITTED_FILE=$VU_STATE_DIR/committed.state
VU_JOURNAL_FILE=$VU_STATE_DIR/journal.state
VU_PENDING_DIR=$VU_STATE_DIR/pending
VU_TRUST_FILE=$VU_STATE_DIR/trust.state
VU_QUARANTINE_FILE=$VU_STATE_DIR/quarantine.state

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
        auto_critical) auto_critical=$value ;;
        auto_important) auto_important=$value ;;
        auto_routine) auto_routine=$value ;;
        manifest_url) manifest_url=$value ;;
        public_key_file) public_key_file=$value ;;
        channel) channel=$value ;;
        safe_window_start) safe_window_start=$value ;;
        safe_window_end) safe_window_end=$value ;;
        minimum_free_kb) minimum_free_kb=$value ;;
        max_manifest_size) max_manifest_size=$value ;;
        max_package_size) max_package_size=$value ;;
        max_unpacked_size) max_unpacked_size=$value ;;
        backup_keep) backup_keep=$value ;;
        barrier_integration_ready) barrier_integration_ready=$value ;;
        current_version_file) current_version_file=$value ;;
        health_timeout_seconds) health_timeout_seconds=$value ;;
        check_interval_seconds) check_interval_seconds=$value ;;
        request_timeout_seconds) request_timeout_seconds=$value ;;
        important_max_delay_seconds) important_max_delay_seconds=$value ;;
        routine_max_delay_seconds) routine_max_delay_seconds=$value ;;
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
    case "$update_enabled:$auto_apply:$auto_critical:$auto_important:$auto_routine:$barrier_integration_ready" in
        [01]:[01]:[01]:[01]:[01]:[01]) ;;
        *) vu_die "$VU_CONFIG_ERROR" "Boolean config values must be 0 or 1" ;;
    esac
    for numeric_value in "$minimum_free_kb" "$max_manifest_size" "$max_package_size" "$max_unpacked_size" "$backup_keep" "$health_timeout_seconds" "$check_interval_seconds" "$request_timeout_seconds" "$important_max_delay_seconds" "$routine_max_delay_seconds"; do
        printf '%s\n' "$numeric_value" | grep -Eq '^[0-9]+$' || vu_die "$VU_CONFIG_ERROR" "Numeric config value is invalid"
    done
    [ "$max_manifest_size" -gt 0 ] && [ "$max_package_size" -gt 0 ] && [ "$max_unpacked_size" -gt 0 ] || vu_die "$VU_CONFIG_ERROR" "Size limits must be greater than zero"
    for window_value in "$safe_window_start" "$safe_window_end"; do
        printf '%s\n' "$window_value" | grep -Eq '^([01][0-9]|2[0-3]):[0-5][0-9]$' || vu_die "$VU_CONFIG_ERROR" "Safe-window time is invalid"
    done
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
    file=${3:-$VU_STATE_DIR/state}
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

vu_atomic_write() {
    destination=$1
    source_file=$2
    mkdir -p "$(dirname "$destination")" || return 1
    temporary=$destination.atomic.$$
    cp "$source_file" "$temporary" || return 1
    chmod 600 "$temporary" || return 1
    cmp -s "$source_file" "$temporary" || { rm -f "$temporary"; return 1; }
    sync
    mv -f "$temporary" "$destination" || return 1
    sync
}

vu_file_mode() {
    path=$1
    find "$path" -prune -printf '%m\n' 2>/dev/null | sed -n '1p'
}

vu_committed_get() { vu_state_get "$1" "$VU_COMMITTED_FILE"; }
vu_trust_get() { vu_state_get "$1" "$VU_TRUST_FILE"; }
vu_pending_get() { vu_state_get "$1" "$VU_PENDING_DIR/pending.state"; }

vu_installed_version() {
    installed=$(vu_committed_get installed_version 2>/dev/null || :)
    if [ -z "$installed" ] && [ -r "$current_version_file" ]; then
        installed=$(sed -n '1p' "$current_version_file")
    fi
    [ -n "$installed" ] || return 1
    printf '%s\n' "$installed"
}

vu_committed_write() {
    installed_version_value=$1
    installed_update_id_value=$2
    sequence_value=$3
    manifest_hash_value=$4
    health_value=$5
    snapshot=$VU_STATE_DIR/committed.new.$$
    mkdir -p "$VU_STATE_DIR" || return 1
    {
        printf 'installed_version=%s\n' "$installed_version_value"
        printf 'installed_update_id=%s\n' "$installed_update_id_value"
        printf 'last_sequence=%s\n' "$sequence_value"
        printf 'manifest_hash=%s\n' "$manifest_hash_value"
        printf 'last_health_check=%s\n' "$health_value"
    } > "$snapshot" || return 1
    vu_atomic_write "$VU_COMMITTED_FILE" "$snapshot" || { rm -f "$snapshot"; return 1; }
    rm -f "$snapshot"
}

vu_journal_set() { vu_state_set "$1" "$2" "$VU_JOURNAL_FILE"; }

vu_transition() {
    next=$1
    vu_journal_set phase "$next" || vu_die "$VU_INSTALL_ERROR" "Cannot persist updater phase"
    vu_journal_set phase_changed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" || vu_die "$VU_INSTALL_ERROR" "Cannot persist updater timestamp"
    vu_log INFO "State transition: $next"
}

vu_owner_token_valid() {
    printf '%s\n' "$1" | grep -Eq '^[1-9][0-9]*:[0-9]+:vward-update$'
}

vu_owner_status() {
    token=$1
    vu_owner_token_valid "$token" || return 2
    pid=${token%%:*}
    if kill -0 "$pid" 2>/dev/null; then
        if [ -r "/proc/$pid/cmdline" ]; then
            tr '\000' ' ' < "/proc/$pid/cmdline" | grep -q 'vward-update' && return 0
            return 2
        fi
        return 2
    fi
    return 1
}

vu_lock_acquire() {
    mkdir -p "$VU_RUN_DIR" || return 1
    lock=$VU_RUN_DIR/updater.lock
    if mkdir "$lock" 2>/dev/null; then
        VU_LOCK_TOKEN="$$:$(date +%s):vward-update"
        printf '%s\n' "$VU_LOCK_TOKEN" > "$lock/owner" || return 1
        VU_LOCK_OWNED=1
        return 0
    fi
    [ -r "$lock/owner" ] || return 1
    owner=$(sed -n '1p' "$lock/owner")
    vu_owner_status "$owner"
    owner_status=$?
    [ "$owner_status" -eq 1 ] || return 1
    case "$lock" in
        */opt/var/run/vward/updater.lock|*/tmp/vward-updater-dryrun.*/run/updater.lock)
            current=$(sed -n '1p' "$lock/owner" 2>/dev/null || :)
            [ "$current" = "$owner" ] || return 1
            rm -f "$lock/owner" || return 1
            rmdir "$lock" 2>/dev/null || return 1
            ;;
        *) return 1 ;;
    esac
    if mkdir "$lock" 2>/dev/null; then
        VU_LOCK_TOKEN="$$:$(date +%s):vward-update"
        printf '%s\n' "$VU_LOCK_TOKEN" > "$lock/owner" || return 1
        VU_LOCK_OWNED=1
        return 0
    fi
    return 1
}

vu_lock_release() {
    lock=$VU_RUN_DIR/updater.lock
    [ "$VU_LOCK_OWNED" = 1 ] || return 0
    [ -d "$lock" ] || return 0
    current=$(sed -n '1p' "$lock/owner" 2>/dev/null || :)
    [ "$current" = "$VU_LOCK_TOKEN" ] || return 1
    rm -f "$lock/owner" || return 1
    rmdir "$lock" 2>/dev/null || return 1
    VU_LOCK_OWNED=0
}

vu_barrier_recover_stale() {
    request_exists=0
    barrier_exists=0
    request_token=
    barrier_token=
    [ -e "$VU_REQUEST_MARKER" ] && request_exists=1
    [ -d "$VU_BARRIER_LOCK" ] && barrier_exists=1
    [ "$request_exists" -eq 0 ] && [ "$barrier_exists" -eq 0 ] && return 0

    if [ "$request_exists" -eq 1 ]; then
        [ -f "$VU_REQUEST_MARKER" ] || return 1
        request_token=$(sed -n '1p' "$VU_REQUEST_MARKER" 2>/dev/null || :)
        vu_owner_token_valid "$request_token" || return 1
    fi
    if [ "$barrier_exists" -eq 1 ]; then
        [ -r "$VU_BARRIER_LOCK/owner" ] || return 1
        barrier_token=$(sed -n '1p' "$VU_BARRIER_LOCK/owner" 2>/dev/null || :)
        vu_owner_token_valid "$barrier_token" || return 1
    fi
    if [ -n "$request_token" ] && [ -n "$barrier_token" ] && [ "$request_token" != "$barrier_token" ]; then
        return 1
    fi
    token=${request_token:-$barrier_token}
    vu_owner_status "$token"
    status=$?
    [ "$status" -eq 1 ] || return 1

    if [ "$barrier_exists" -eq 1 ]; then
        current=$(sed -n '1p' "$VU_BARRIER_LOCK/owner" 2>/dev/null || :)
        [ "$current" = "$token" ] || return 1
        rm -f "$VU_BARRIER_LOCK/owner" || return 1
        rmdir "$VU_BARRIER_LOCK" 2>/dev/null || return 1
    fi
    if [ "$request_exists" -eq 1 ]; then
        current=$(sed -n '1p' "$VU_REQUEST_MARKER" 2>/dev/null || :)
        [ "$current" = "$token" ] || return 1
        rm -f "$VU_REQUEST_MARKER" || return 1
    fi
    vu_log WARN "Recovered stale update barrier owned by $token"
    return 0
}

vu_staging_cleanup_orphans() {
    [ -d "$VU_STAGING_DIR" ] || return 0
    for orphan in "$VU_STAGING_DIR"/transaction.*; do
        [ -d "$orphan" ] || continue
        case "$orphan" in "$VU_STAGING_DIR"/transaction.[0-9]*) rm -rf "$orphan" || return 1 ;; *) return 1 ;; esac
    done
}

vu_semver_valid() {
    version_value=$1
    printf '%s\n' "$version_value" | grep -Eq '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$' || return 1
    prerelease=${version_value#*-}
    [ "$prerelease" = "$version_value" ] && return 0
    old_ifs=$IFS
    IFS=.
    for identifier in $prerelease; do
        case "$identifier" in 0|'') ;; 0[0-9]*) IFS=$old_ifs; return 1 ;; esac
    done
    IFS=$old_ifs
}

vu_version_cmp() {
    awk -v left="$1" -v right="$2" '
      function splitver(v, core, pre, p) { p=index(v,"-"); if (p) { core=substr(v,1,p-1); pre=substr(v,p+1) } else { core=v; pre="" } return core SUBSEP pre }
      function numeric(v) { return v ~ /^[0-9]+$/ }
      BEGIN {
        l=splitver(left); split(l,lv,SUBSEP); r=splitver(right); split(r,rv,SUBSEP)
        split(lv[1],lc,"."); split(rv[1],rc,".")
        for(i=1;i<=3;i++){ if((lc[i]+0)<(rc[i]+0)){print -1;exit} if((lc[i]+0)>(rc[i]+0)){print 1;exit} }
        if(lv[2]=="" && rv[2]==""){print 0;exit} if(lv[2]==""){print 1;exit} if(rv[2]==""){print -1;exit}
        ln=split(lv[2],lp,"."); rn=split(rv[2],rp,"."); n=(ln>rn?ln:rn)
        for(i=1;i<=n;i++){
          if(i>ln){print -1;exit} if(i>rn){print 1;exit}
          lnum=numeric(lp[i]); rnum=numeric(rp[i])
          if(lnum && rnum){if((lp[i]+0)<(rp[i]+0)){print -1;exit} if((lp[i]+0)>(rp[i]+0)){print 1;exit}}
          else if(lnum && !rnum){print -1;exit} else if(!lnum && rnum){print 1;exit}
          else {if(lp[i]<rp[i]){print -1;exit} if(lp[i]>rp[i]){print 1;exit}}
        }
        print 0
      }'
}

vu_version_lt() { [ "$(vu_version_cmp "$1" "$2")" -lt 0 ]; }

vu_manifest_validate() {
    manifest=$1
    jq -e '
      type == "object" and
      (.signed | type == "object") and
      ((.signature | type) == "string" and (.signature | length) > 0) and
      (.signed.schema == 1) and
      (.signed.update_id | type == "string") and
      (.signed.sequence as $sequence |
        ($sequence | type) == "number" and
        $sequence >= 1 and
        $sequence == ($sequence | floor)) and
      (.signed.version | type == "string") and
      (.signed.channel | type == "string") and
      (.signed.priority | IN("ROUTINE", "IMPORTANT", "CRITICAL")) and
      (.signed.published_at | type == "string") and
      (.signed.min_updater_version | type == "string") and
      ((.signed.package.url | type) == "string" and
       (.signed.package.url | startswith("https://"))) and
      (.signed.package.sha256 | type == "string") and
      (.signed.package.size as $package_size |
        ($package_size | type) == "number" and
        $package_size > 0 and
        $package_size == ($package_size | floor)) and
      (((.signed.package.unpacked_size as $unpacked_size |
          ($unpacked_size | type) == "number" and
          $unpacked_size > 0 and
          $unpacked_size == ($unpacked_size | floor))) or
       (((env.VWARD_ROOT_PREFIX // "") != "") and
        ((env.VWARD_TEST_PACKAGE // "") != "") and
        ((.signed.package | has("unpacked_size")) | not))) and
      (.signed.compatibility.min_vward | type == "string") and
      (.signed.compatibility.max_vward | type == "string") and
      (.signed.affected_components | type == "array") and
      (.signed.affected_services | type == "array") and
      (.signed.health_profile | type == "string") and
      (.signed.requires_reboot | type == "boolean") and
      (.signed.rollback_policy | IN("automatic", "manual")) and
      (.signed.signature.algorithm == "Ed25519") and
      ((.signed.signature.key_id | type) == "string" and
       (.signed.signature.key_id | length) > 0)
    ' "$manifest" >/dev/null 2>&1 || return 1

    manifest_update_id=$(jq -r '.signed.update_id' "$manifest") || return 1
    case "$manifest_update_id" in
        ''|*[!A-Za-z0-9._-]*) return 1 ;;
    esac

    manifest_package_sha=$(jq -r '.signed.package.sha256' "$manifest") || return 1
    [ "${#manifest_package_sha}" -eq 64 ] || return 1
    case "$manifest_package_sha" in
        *[!0-9a-f]*) return 1 ;;
    esac

    return 0
}

vu_signed_hash() {
    manifest=$1
    jq -cS '.signed' "$manifest" | sha256sum | awk '{print $1}'
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

vu_manifest_static_policy() {
    manifest=$1
    version=$(jq -r '.signed.version' "$manifest")
    manifest_channel=$(jq -r '.signed.channel' "$manifest")
    current_version=$(vu_installed_version) || return "$VU_COMPAT_ERROR"
    vu_semver_valid "$version" || return "$VU_COMPAT_ERROR"
    vu_semver_valid "$current_version" || return "$VU_COMPAT_ERROR"
    [ "$manifest_channel" = "$channel" ] || return "$VU_COMPAT_ERROR"
    [ "$(jq -r '.signed.requires_reboot' "$manifest")" = false ] || return "$VU_COMPAT_ERROR"
    [ "$(jq -r '.signed.affected_services | length' "$manifest")" -eq 0 ] || return "$VU_COMPAT_ERROR"
    required_updater=$(jq -r '.signed.min_updater_version' "$manifest")
    vu_semver_valid "$required_updater" || return "$VU_COMPAT_ERROR"
    vu_version_lt "$minimum_updater_version" "$required_updater" && return "$VU_COMPAT_ERROR"
    min=$(jq -r '.signed.compatibility.min_vward' "$manifest")
    max=$(jq -r '.signed.compatibility.max_vward' "$manifest")
    vu_semver_valid "$min" && vu_semver_valid "$max" || return "$VU_COMPAT_ERROR"
    return "$VU_OK"
}

vu_trust_check_and_maybe_advance() {
    manifest=$1
    persist=${2:-1}
    sequence=$(jq -r '.signed.sequence' "$manifest")
    update_id=$(jq -r '.signed.update_id' "$manifest")
    signed_hash=$(vu_signed_hash "$manifest") || return "$VU_VERIFY_ERROR"
    highest=$(vu_trust_get highest_seen_sequence 2>/dev/null || vu_committed_get last_sequence 2>/dev/null || printf '0')
    highest_id=$(vu_trust_get highest_seen_update_id 2>/dev/null || vu_committed_get installed_update_id 2>/dev/null || :)
    highest_hash=$(vu_trust_get highest_seen_manifest_hash 2>/dev/null || vu_committed_get manifest_hash 2>/dev/null || :)
    if [ "$sequence" -lt "$highest" ]; then
        return "$VU_COMPAT_ERROR"
    fi
    if [ "$sequence" -eq "$highest" ]; then
        [ "$update_id" = "$highest_id" ] && [ "$signed_hash" = "$highest_hash" ] || return "$VU_COMPAT_ERROR"
        return "$VU_OK"
    fi
    [ "$persist" = 1 ] || return "$VU_OK"
    snapshot=$VU_STATE_DIR/trust.new.$$
    mkdir -p "$VU_STATE_DIR" || return "$VU_INSTALL_ERROR"
    {
        printf 'highest_seen_sequence=%s\n' "$sequence"
        printf 'highest_seen_update_id=%s\n' "$update_id"
        printf 'highest_seen_manifest_hash=%s\n' "$signed_hash"
        printf 'trusted_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    } > "$snapshot" || return "$VU_INSTALL_ERROR"
    vu_atomic_write "$VU_TRUST_FILE" "$snapshot" || { rm -f "$snapshot"; return "$VU_INSTALL_ERROR"; }
    rm -f "$snapshot"
    return "$VU_OK"
}

vu_quarantine_matches() {
    manifest=$1
    [ -r "$VU_QUARANTINE_FILE" ] || return 1
    qseq=$(vu_state_get sequence "$VU_QUARANTINE_FILE" 2>/dev/null || :)
    qid=$(vu_state_get update_id "$VU_QUARANTINE_FILE" 2>/dev/null || :)
    qhash=$(vu_state_get manifest_hash "$VU_QUARANTINE_FILE" 2>/dev/null || :)
    seq=$(jq -r '.signed.sequence' "$manifest")
    id=$(jq -r '.signed.update_id' "$manifest")
    hash=$(vu_signed_hash "$manifest") || return 1
    [ "$qseq" = "$seq" ] && [ "$qid" = "$id" ] && [ "$qhash" = "$hash" ]
}

vu_quarantine_store() {
    manifest=$1
    failure_class=$2
    snapshot=$VU_STATE_DIR/quarantine.new.$$
    mkdir -p "$VU_STATE_DIR" || return 1
    {
        printf 'update_id=%s\n' "$(jq -r '.signed.update_id' "$manifest")"
        printf 'sequence=%s\n' "$(jq -r '.signed.sequence' "$manifest")"
        printf 'manifest_hash=%s\n' "$(vu_signed_hash "$manifest")"
        printf 'failure_class=%s\n' "$failure_class"
        printf 'failed_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    } > "$snapshot" || return 1
    vu_atomic_write "$VU_QUARANTINE_FILE" "$snapshot" || { rm -f "$snapshot"; return 1; }
    rm -f "$snapshot"
}

vu_manifest_check_policy() {
    manifest=$1
    persist_trust=${2:-1}
    vu_manifest_static_policy "$manifest"
    rc=$?
    [ "$rc" -eq "$VU_OK" ] || return "$rc"

    sequence=$(jq -r '.signed.sequence' "$manifest")
    version=$(jq -r '.signed.version' "$manifest")
    update_id=$(jq -r '.signed.update_id' "$manifest")
    current_version=$(vu_installed_version) || return "$VU_COMPAT_ERROR"
    committed_seq=$(vu_committed_get last_sequence 2>/dev/null || printf '0')
    committed_id=$(vu_committed_get installed_update_id 2>/dev/null || :)

    if [ "$sequence" -eq "$committed_seq" ] && [ "$update_id" = "$committed_id" ] && [ "$version" = "$current_version" ]; then
        vu_trust_check_and_maybe_advance "$manifest" "$persist_trust"
        rc=$?
        [ "$rc" -eq "$VU_OK" ] || return "$rc"
        return "$VU_NO_UPDATE"
    fi

    [ "$sequence" -gt "$committed_seq" ] || return "$VU_COMPAT_ERROR"
    min=$(jq -r '.signed.compatibility.min_vward' "$manifest")
    max=$(jq -r '.signed.compatibility.max_vward' "$manifest")
    vu_version_lt "$current_version" "$min" && return "$VU_COMPAT_ERROR"
    vu_version_lt "$max" "$current_version" && return "$VU_COMPAT_ERROR"
    vu_version_lt "$current_version" "$version" || return "$VU_COMPAT_ERROR"

    vu_trust_check_and_maybe_advance "$manifest" "$persist_trust"
    rc=$?
    [ "$rc" -eq "$VU_OK" ] || return "$rc"
    vu_quarantine_matches "$manifest" && return "$VU_QUARANTINED"
    return "$VU_OK"
}

vu_pending_store() {
    manifest=$1
    mkdir -p "$VU_PENDING_DIR" || return 1
    manifest_tmp=$VU_PENDING_DIR/manifest.json.tmp.$$
    cp "$manifest" "$manifest_tmp" || return 1
    manifest_hash=$(vu_signed_hash "$manifest_tmp") || return 1
    new_update_id=$(jq -r '.signed.update_id' "$manifest")
    old_update_id=$(vu_pending_get update_id 2>/dev/null || :)
    if [ "$new_update_id" = "$old_update_id" ]; then
        first_seen=$(vu_pending_get first_seen_at 2>/dev/null || vu_now_epoch)
    else
        first_seen=$(vu_now_epoch)
        rm -f "$VU_PENDING_DIR/package.tar.gz"
    fi
    pending_state=$VU_PENDING_DIR/pending.new.$$
    {
        printf 'update_id=%s\n' "$new_update_id"
        printf 'sequence=%s\n' "$(jq -r '.signed.sequence' "$manifest")"
        printf 'version=%s\n' "$(jq -r '.signed.version' "$manifest")"
        printf 'priority=%s\n' "$(jq -r '.signed.priority' "$manifest")"
        printf 'first_seen_at=%s\n' "$first_seen"
        printf 'manifest_hash=%s\n' "$manifest_hash"
        printf 'escalated=0\n'
    } > "$pending_state" || return 1
    vu_atomic_write "$VU_PENDING_DIR/manifest.json" "$manifest_tmp" || return 1
    vu_atomic_write "$VU_PENDING_DIR/pending.state" "$pending_state" || return 1
    rm -f "$manifest_tmp" "$pending_state"
}

vu_pending_clear() {
    for pending_file in manifest.json package.tar.gz pending.state; do
        rm -f "$VU_PENDING_DIR/$pending_file"
    done
}

vu_auto_allowed() {
    [ "$auto_apply" = 1 ] || return 1
    case "$1" in
        CRITICAL) [ "$auto_critical" = 1 ] ;;
        IMPORTANT) [ "$auto_important" = 1 ] ;;
        ROUTINE) [ "$auto_routine" = 1 ] ;;
        *) return 1 ;;
    esac
}

vu_now_epoch() { printf '%s\n' "${VWARD_TEST_NOW_EPOCH:-$(date +%s)}"; }

vu_schedule_ready() {
    priority=$1
    first_seen=$2
    now=$(vu_now_epoch)
    waited=$((now - first_seen))
    [ "$waited" -ge 0 ] || waited=0
    case "$priority" in
        CRITICAL) return 0 ;;
        IMPORTANT)
            vu_in_safe_window && return 0
            [ "$waited" -ge "$important_max_delay_seconds" ] || return 1
            [ ! -r "$VU_PENDING_DIR/pending.state" ] || vu_state_set escalated 1 "$VU_PENDING_DIR/pending.state" || return 1
            return 0 ;;
        ROUTINE)
            vu_in_safe_window && return 0
            [ "$waited" -ge "$routine_max_delay_seconds" ] || return 1
            [ ! -r "$VU_PENDING_DIR/pending.state" ] || vu_state_set escalated 1 "$VU_PENDING_DIR/pending.state" || return 1
            return 0 ;;
        *) return 1 ;;
    esac
}

vu_free_kb() {
    space_kind=$1
    space_path=$2
    case "$space_kind" in
        staging) override=${VWARD_TEST_FREE_STAGING_KB:-} ;;
        backup) override=${VWARD_TEST_FREE_BACKUP_KB:-} ;;
        target) override=${VWARD_TEST_FREE_TARGET_KB:-} ;;
        *) override= ;;
    esac
    if [ -n "$VU_ROOT_PREFIX" ] && [ -n "$override" ]; then
        printf '%s\n' "$override"
        return 0
    fi
    df -Pk "$space_path" 2>/dev/null | awk 'NR==2 {print $4}'
}

vu_manifest_unpacked_size() {
    manifest=$1
    unpacked=$(jq -r '.signed.package.unpacked_size // empty' "$manifest")
    if [ -n "$unpacked" ]; then
        printf '%s\n' "$unpacked"
        return 0
    fi
    if [ -n "$VU_ROOT_PREFIX" ] && [ -r "${VWARD_TEST_PACKAGE:-}" ]; then
        tar -tvzf "$VWARD_TEST_PACKAGE" 2>/dev/null | awk '
          BEGIN {sum=0}
          {t=substr($1,1,1); if(t=="-"){if($3 !~ /^[0-9]+$/) exit 1; sum+=$3} else if(t!="d") exit 1}
          END {printf "%.0f\n",sum}'
        return $?
    fi
    return 1
}

vu_manifest_space_preflight() {
    manifest=$1
    package_size=$(jq -r '.signed.package.size' "$manifest")
    unpacked_size=$(vu_manifest_unpacked_size "$manifest") || return 1
    [ "$package_size" -le "$max_package_size" ] || return 1
    [ "$unpacked_size" -le "$max_unpacked_size" ] || return 1
    package_kb=$(((package_size + 1023) / 1024))
    unpacked_kb=$(((unpacked_size + 1023) / 1024))
    required_kb=$((package_kb + unpacked_kb + minimum_free_kb))
    mkdir -p "$VU_STAGING_DIR" || return 1
    staging_free=$(vu_free_kb staging "$VU_STAGING_DIR")
    [ -n "$staging_free" ] && [ "$staging_free" -ge "$required_kb" ]
}

vu_fetch_bounded() {
    url=$1
    output=$2
    max_bytes=$3
    case "$url" in https://*) ;; *) return 1 ;; esac
    tmp=$output.part.$$
    rm -f "$tmp"
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
        --connect-timeout 15 --max-time 180 --retry 3 --retry-all-errors \
        --max-filesize "$max_bytes" --output "$tmp" "$url" || { rm -f "$tmp"; return 1; }
    size=$(wc -c < "$tmp" | tr -d ' ')
    [ "$size" -le "$max_bytes" ] || { rm -f "$tmp"; return 1; }
    mv -f "$tmp" "$output"
}

vu_safe_target() {
    target=$1
    case "$target" in *../*|*/..|*/./*|*//* ) return 1 ;; esac
    case "$target" in
        /opt/bin/adaptive-2ip-test.sh|/opt/bin/adaptive-auto-maint.sh|/opt/bin/adaptive-hints-update.sh|/opt/bin/adaptive-housekeeping.sh|/opt/bin/adaptive-resolve4.sh|/opt/bin/adaptive-route.sh|/opt/bin/agh-adaptive-live.sh|/opt/bin/agh-adaptive-route.sh|/opt/bin/crond-supervisor.sh|/opt/bin/vpn-domain-audit-chain.sh|/opt/bin/vpn-domain-audit.sh|/opt/bin/vpn-night-reconcile.sh|/opt/bin/vpn-subnet-sync.sh|/opt/bin/wan-guardian.sh|/opt/bin/wan-recovery-actuator.sh|/opt/bin/wg-failopen-guard.sh|/opt/bin/wg-health-watch.sh|/opt/etc/init.d/S90crond|/opt/etc/init.d/S91adaptive-live|/opt/etc/init.d/S92crond-supervisor|/opt/etc/init.d/S93keenetic-apps|/opt/etc/keenetic-apps/lighttpd.conf|/opt/share/keenetic-apps/www/index.html|/opt/share/keenetic-apps/www/cgi-bin/api.cgi|/opt/share/vward/VERSION) return 0 ;;
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
    jq -e '.schema == 1 and
      ((.files | type) == "array" and (.files | length) > 0) and
      all(.files[];
        (.source | type) == "string" and
        (.target | type) == "string" and
        (.sha256 | type) == "string" and
        (.mode | type) == "string" and
        ((.component | type) == "string" and (.component | length) > 0) and
        (.restart_policy | IN("none", "deferred")) and
        (.config_policy == "program-only"))' "$package_manifest" >/dev/null 2>&1 || return 1
    jq -r '.files[] | [.source,.target,.sha256,.mode] | @tsv' "$package_manifest" |
    while IFS="$(printf '\t')" read -r source target expected mode; do
        case "$source" in ''|..|/*|*../*|../*|*/..) return 1 ;; esac
        [ "${#expected}" -eq 64 ] || return 1
        case "$expected" in *[!0-9a-f]*) return 1 ;; esac
        vu_safe_target "$target" || return 1
        vu_local_target "$target" && return 1
        [ -f "$package_dir/$source" ] || return 1
        actual=$(sha256sum "$package_dir/$source" | awk '{print $1}')
        [ "$actual" = "$expected" ] || return 1
        [ "$mode" = 0644 ] || [ "$mode" = 0755 ] || return 1
    done
}

vu_in_safe_window() {
    now=${VWARD_TEST_NOW_HM:-$(date '+%H:%M')}
    if [ "$safe_window_start" \< "$safe_window_end" ]; then
        [ "$now" \> "$safe_window_start" ] && [ "$now" \< "$safe_window_end" ]
    else
        [ "$now" \> "$safe_window_start" ] || [ "$now" \< "$safe_window_end" ]
    fi
}

vu_activity_clear() {
    [ ! -e "$VU_RUN_DIR/runtime-active" ] || return 1
    for conflict in "$VU_ROOT_PREFIX/tmp/adaptive-auto-maint.lock" "$VU_ROOT_PREFIX/tmp/agh-adaptive-live.lock" "$VU_ROOT_PREFIX/tmp/vpn-domain-audit.lock" "$VU_ROOT_PREFIX/tmp/vpn-night-reconcile.lock" "$VU_ROOT_PREFIX/tmp/wg-failopen.lock" "$VU_ROOT_PREFIX/tmp/wan-guardian.lock" "$VU_ROOT_PREFIX/tmp/wan-guardian.lock.d"; do
        [ ! -e "$conflict" ] || return 1
    done
    return 0
}

vu_runtime_quiesce() {
    [ "$VU_RUNTIME_QUIESCED" = 0 ] || return 0

    if [ -n "$VU_ROOT_PREFIX" ]; then
        VU_RUNTIME_QUIESCED=1
        return 0
    fi

    supervisor_pid=$(sed -n '1p' /opt/var/run/crond-supervisor.pid 2>/dev/null || :)
    live_pid=$(sed -n '1p' /opt/var/run/agh-adaptive-live.pid 2>/dev/null || :)

    [ -z "$supervisor_pid" ] || ! kill -0 "$supervisor_pid" 2>/dev/null || VU_RESTART_SUPERVISOR=1
    pidof crond >/dev/null 2>&1 && VU_RESTART_CROND=1
    [ -z "$live_pid" ] || ! kill -0 "$live_pid" 2>/dev/null || VU_RESTART_LIVE=1
    VU_RUNTIME_QUIESCED=1

    if [ "$VU_RESTART_SUPERVISOR" = 1 ]; then
        /opt/etc/init.d/S92crond-supervisor stop >/dev/null 2>&1 || return 1
    fi
    if [ "$VU_RESTART_CROND" = 1 ]; then
        /opt/etc/init.d/S90crond stop >/dev/null 2>&1 || return 1
    fi
    if [ "$VU_RESTART_LIVE" = 1 ]; then
        /opt/etc/init.d/S91adaptive-live stop >/dev/null 2>&1 || return 1
    fi

    waited=0
    while ! vu_activity_clear && [ "$waited" -lt "$request_timeout_seconds" ]; do
        sleep 1
        waited=$((waited + 1))
    done
    vu_activity_clear || return 1
    pidof crond >/dev/null 2>&1 && return 1

    VU_RUNTIME_QUIESCED=1
    vu_log INFO "Runtime quiesced for update"
    return 0
}

vu_runtime_resume() {
    [ "$VU_RUNTIME_QUIESCED" = 1 ] || return 0

    if [ -z "$VU_ROOT_PREFIX" ]; then
        resume_rc=0
        if [ "$VU_RESTART_CROND" = 1 ]; then
            /opt/etc/init.d/S90crond start >/dev/null 2>&1 || resume_rc=1
        fi
        if [ "$VU_RESTART_LIVE" = 1 ]; then
            /opt/etc/init.d/S91adaptive-live start >/dev/null 2>&1 || resume_rc=1
        fi
        if [ "$VU_RESTART_SUPERVISOR" = 1 ]; then
            /opt/etc/init.d/S92crond-supervisor start >/dev/null 2>&1 || resume_rc=1
        fi
        [ "$resume_rc" -eq 0 ] || return 1
        vu_log INFO "Runtime resumed after update"
    fi

    VU_RUNTIME_QUIESCED=0
    return 0
}

vu_hard_safety_check() {
    package_dir=$1
    [ "$barrier_integration_ready" = 1 ] || return 1
    vu_activity_clear || return 1
    mkdir -p "$VU_STAGING_DIR" "$VU_BACKUP_DIR" || return 1
    [ -w "$VU_STAGING_DIR" ] && [ -w "$VU_BACKUP_DIR" ] || return 1

    jq -r '.files[].target' "$package_dir/package-manifest.json" | while IFS= read -r target; do
        source=$VU_ROOT_PREFIX$target
        [ ! -f "$source" ] || wc -c < "$source"
    done > "$package_dir/backup-sizes" || return 1
    backup_bytes=$(awk '{sum += $1} END {print sum+0}' "$package_dir/backup-sizes")
    backup_required=$(((backup_bytes + 1023) / 1024 + minimum_free_kb))
    backup_free=$(vu_free_kb backup "$VU_BACKUP_DIR")
    [ -n "$backup_free" ] && [ "$backup_free" -ge "$backup_required" ] || return 1

    plan=$package_dir/target-space.tsv
    : > "$plan" || return 1
    jq -r '.files[] | [.target,.source] | @tsv' "$package_dir/package-manifest.json" |
    while IFS="$(printf '\t')" read -r target source; do
        destination=$VU_ROOT_PREFIX$target
        parent=$(dirname "$destination")
        probe=$parent
        while [ ! -d "$probe" ] && [ "$probe" != / ]; do probe=$(dirname "$probe"); done
        fskey=$(df -Pk "$probe" 2>/dev/null | awk 'NR==2 {print $1}')
        [ -n "$fskey" ] || exit 1
        payload_bytes=$(wc -c < "$package_dir/$source")
        printf '%s\t%s\t%s\n' "$fskey" "$probe" "$payload_bytes"
    done > "$plan" || return 1

    awk -F '\t' '{sum[$1]+=$3; if(!path[$1]) path[$1]=$2} END {for(k in sum) printf "%s\t%s\t%.0f\n",k,path[k],sum[k]}' "$plan" |
    while IFS="$(printf '\t')" read -r fskey probe total_bytes; do
        target_free=$(vu_free_kb target "$probe")
        target_required=$(((total_bytes + 1023) / 1024 + minimum_free_kb))
        [ -n "$target_free" ] && [ "$target_free" -ge "$target_required" ] || return 1
    done
}

vu_barrier_enter() {
    vu_barrier_recover_stale || return 1
    mkdir -p "$(dirname "$VU_REQUEST_MARKER")" || return 1
    printf '%s\n' "$VU_LOCK_TOKEN" > "$VU_REQUEST_MARKER" || return 1
    VU_REQUEST_OWNED=1
    waited=0
    while ! vu_activity_clear && [ "$waited" -lt "$request_timeout_seconds" ]; do
        sleep 1
        waited=$((waited + 1))
    done
    vu_activity_clear || return 1
    mkdir "$VU_BARRIER_LOCK" 2>/dev/null || return 1
    printf '%s\n' "$VU_LOCK_TOKEN" > "$VU_BARRIER_LOCK/owner" || return 1
    VU_BARRIER_OWNED=1
    [ -z "$VU_ROOT_PREFIX" ] || [ "${VWARD_TEST_CONFLICT_AFTER_BARRIER:-0}" != 1 ] || : > "$VU_ROOT_PREFIX/tmp/wan-guardian.lock"
    vu_activity_clear || return 1
    return 0
}

vu_barrier_leave() {
    if [ "$VU_BARRIER_OWNED" = 1 ] && [ -d "$VU_BARRIER_LOCK" ]; then
        current=$(sed -n '1p' "$VU_BARRIER_LOCK/owner" 2>/dev/null || :)
        [ "$current" = "$VU_LOCK_TOKEN" ] || return 1
        rm -f "$VU_BARRIER_LOCK/owner" || return 1
        rmdir "$VU_BARRIER_LOCK" 2>/dev/null || return 1
        VU_BARRIER_OWNED=0
    fi
    if [ "$VU_REQUEST_OWNED" = 1 ] && [ -f "$VU_REQUEST_MARKER" ]; then
        current=$(sed -n '1p' "$VU_REQUEST_MARKER" 2>/dev/null || :)
        [ "$current" = "$VU_LOCK_TOKEN" ] || return 1
        rm -f "$VU_REQUEST_MARKER" || return 1
        VU_REQUEST_OWNED=0
    fi
}
