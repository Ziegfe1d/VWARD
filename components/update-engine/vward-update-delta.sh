#!/bin/sh

# VWARD Update Engine 2: per-file (delta) updates and engine self-update.
#
# A schema-2 manifest signs the whole desired state: every program file with its
# sha256, size, mode and component, and the engine's own files.  The router
# compares that list with its files, downloads only the files that differ (each
# checked against its signed sha256), and backs up and replaces only them.
# A newer engine goes into the inactive A/B slot, passes a self-test and becomes
# current; the previous slot stays for --engine-revert.
# Sourced after vward-update-hardening.sh.

# ---------- Feed ----------

# The v2 feed sits next to the v1 manifest:
# .../updates/<channel>/update-manifest.json -> .../updates/<channel>/v2/manifest.json
vu_v2_url() {
    if [ -n "$manifest_v2_url" ]; then
        printf '%s\n' "$manifest_v2_url"
        return 0
    fi
    case "$manifest_url" in
        https://*/update-manifest.json) printf '%s\n' "${manifest_url%/update-manifest.json}/v2/manifest.json" ;;
        *) return 1 ;;
    esac
}

vu_manifest_schema() { jq -r '.signed.schema // empty' "$1" 2>/dev/null; }

# Target rules for engine 2: VWARD's own program places only, never the updater
# slots or user configuration.  Which component owns a target is checked
# against the signed component registry as before.
vu_safe_target() {
    target=$1
    case "$target" in *../*|*/..|*/./*|*//*|*[!A-Za-z0-9/._-]*) return 1 ;; esac
    case "$target" in
        /opt/share/vward/updater|/opt/share/vward/updater/*) return 1 ;;
        /opt/bin/vward-*|/opt/lib/vward/*|/opt/share/vward/*|/opt/etc/init.d/S[0-9][0-9]vward-*|/opt/etc/init.d/S90crond) return 0 ;;
    esac
    return 1
}

vu_target_mode_allowed() {
    case "$2" in 0644|0755) return 0 ;; esac
    return 1
}

# Hex digest and file-name checks without jq regular expressions (Entware jq has none).
VU_JQ_V2_DEFS='
  def hex64: type == "string" and length == 64 and (explode | all(. >= 48 and . <= 57 or . >= 97 and . <= 102));
  def count: type == "number" and . >= 0 and . == floor;
  def fname: type == "string" and length > 0 and length <= 64 and
    (explode | all(. >= 48 and . <= 57 or . >= 65 and . <= 90 or . >= 97 and . <= 122 or . == 45 or . == 46 or . == 95));
'

vu_manifest_validate_v2() {
    manifest=$1
    jq -e "$VU_JQ_V2_DEFS"'
      type == "object" and
      (.signed | type == "object") and
      ((.signature | type) == "string" and (.signature | length) > 0) and
      (.signed.schema == 2) and
      (.signed.update_id | type == "string") and
      (.signed.sequence as $s | ($s | type) == "number" and $s >= 1 and $s == ($s | floor)) and
      (.signed.version | type == "string") and
      (.signed.channel | type == "string") and
      (.signed.priority | IN("ROUTINE", "IMPORTANT", "CRITICAL")) and
      (.signed.published_at | type == "string") and
      (.signed.min_updater_version | type == "string") and
      (.signed.files_base | type == "string" and startswith("https://") and endswith("/")) and
      (.signed.files | type == "array" and length > 0 and length <= 1000) and
      ([.signed.files[].target] | length == (unique | length)) and
      all(.signed.files[];
        (.target | type == "string" and startswith("/")) and (.sha256 | hex64) and (.size | count) and
        (.mode | IN("0644", "0755")) and (.component | type == "string" and length > 0)) and
      (.signed.engine | type == "object") and
      (.signed.engine.version | type == "string") and
      (.signed.engine.files | type == "array" and length > 0 and length <= 32) and
      ([.signed.engine.files[].name] | length == (unique | length)) and
      all(.signed.engine.files[]; (.name | fname) and (.sha256 | hex64) and (.size | count) and (.mode | IN("0644", "0755"))) and
      any(.signed.engine.files[]; .name == "vward-update.sh") and
      (.signed.compatibility.min_vward | type == "string") and
      (.signed.compatibility.max_vward | type == "string") and
      (.signed.affected_services | type == "array") and
      (.signed.health_profile | type == "string") and
      (.signed.requires_reboot | type == "boolean") and
      (.signed.rollback_policy | IN("automatic", "manual")) and
      (.signed.signature.algorithm == "Ed25519") and
      ((.signed.signature.key_id | type) == "string" and (.signed.signature.key_id | length) > 0)
    ' "$manifest" >/dev/null 2>&1 || return 1
    manifest_update_id=$(jq -r '.signed.update_id' "$manifest") || return 1
    case "$manifest_update_id" in ''|*[!A-Za-z0-9._-]*) return 1 ;; esac
    vu_semver_valid "$(jq -r '.signed.engine.version' "$manifest")" || return 1
    total=$(jq '[.signed.files[].size] | add' "$manifest") || return 1
    [ "$total" -le "$max_unpacked_size" ]
}

# Either schema, the right checks for each.
vu_manifest_validate_any() {
    case "$(vu_manifest_schema "$1")" in
        2) vu_manifest_validate_v2 "$1" ;;
        1) vu_manifest_validate "$1" ;;
        *) return 1 ;;
    esac
}

# ---------- Files ----------

# vu_v2_fetch LIST DIR: LIST rows "sha256<TAB>size<TAB>destination"; every file
# is fetched in one curl run (one connection) from files_base, or taken from the
# verified cache, and checked against its signed size and sha256.
vu_v2_fetch() {
    list=$1 base=$2
    cache=$VU_PENDING_DIR/files
    config=$list.curl
    : > "$config" || return 1
    while IFS="$(printf '\t')" read -r sha size destination; do
        mkdir -p "$(dirname "$destination")" || return 1
        if [ "$size" = 0 ]; then
            : > "$destination" || return 1
        elif [ "${persist_pending:-1}" = 1 ] && [ -f "$cache/$sha" ] &&
             [ "$(sha256sum "$cache/$sha" | awk '{print $1}')" = "$sha" ]; then
            cp "$cache/$sha" "$destination" || return 1
        elif [ -n "$VU_ROOT_PREFIX" ] && [ -n "${VWARD_TEST_FILES_DIR:-}" ]; then
            [ ! -f "$VWARD_TEST_FILES_DIR/$sha" ] || cp "$VWARD_TEST_FILES_DIR/$sha" "$destination" || return 1
        else
            printf 'url = "%s%s"\noutput = "%s"\n' "$base" "$sha" "$destination" >> "$config" || return 1
        fi
    done < "$list"
    if [ -s "$config" ]; then
        curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
            --connect-timeout 15 --max-time 300 --retry 3 --retry-all-errors \
            --max-filesize "$max_package_size" --config "$config" || return 1
    fi
    while IFS="$(printf '\t')" read -r sha size destination; do
        [ -f "$destination" ] || return 1
        [ "$(wc -c < "$destination" | tr -d ' ')" = "$size" ] || return 1
        [ "$(sha256sum "$destination" | awk '{print $1}')" = "$sha" ] || return 1
        if [ "${persist_pending:-1}" = 1 ] && [ ! -f "$cache/$sha" ]; then
            mkdir -p "$cache" && cp "$destination" "$cache/$sha.tmp.$$" && mv -f "$cache/$sha.tmp.$$" "$cache/$sha" || return 1
        fi
    done < "$list"
}

# vu_v2_plan MANIFEST OUT: the signed file rows whose file on the router differs
# (content or mode) or is missing, as "target sha size mode component".  One
# sha256sum and one ls for all files.
vu_v2_plan() {
    manifest=$1 out=$2
    rows=$out.rows
    jq -r '.signed.files[] | [.target, .sha256, (.size | tostring), .mode, .component] | @tsv' "$manifest" > "$rows" || return 1
    while IFS="$(printf '\t')" read -r target sha size mode component; do
        vu_safe_target "$target" || return 1
        ! vu_local_target "$target" || return 1
        [ ! -f "$VU_ROOT_PREFIX$target" ] || printf '%s\n' "$VU_ROOT_PREFIX$target"
    done < "$rows" > "$out.present" || return 1
    : > "$out.sums"; : > "$out.modes"
    if [ -s "$out.present" ]; then
        # Paths are checked above: no blanks, so xargs splits them safely.
        xargs sha256sum < "$out.present" > "$out.sums" || return 1
        xargs ls -ln < "$out.present" > "$out.modes" || return 1
    fi
    awk -F '\t' -v root="$VU_ROOT_PREFIX" '
        FILENAME == ARGV[1] { split($0, f, " "); sum[f[2]] = f[1]; next }
        FILENAME == ARGV[2] {
            n = split($0, g, " "); p = substr(g[1], 2, 9); m = 0
            for (i = 1; i <= 9; i++) {
                c = substr(p, i, 1); b = (i - 1) % 3
                if (c != "-" && c != "S" && c != "T") m += ((b == 0) ? 4 : (b == 1) ? 2 : 1) * (i <= 3 ? 64 : i <= 6 ? 8 : 1)
            }
            mode[g[n]] = sprintf("0%o", m); next
        }
        {
            path = root $1
            if (!(path in sum) || sum[path] != $2 || mode[path] != $4) print
        }' "$out.sums" "$out.modes" "$rows" > "$out" || return 1
}

# vu_v2_stage MANIFEST: a package directory holding only the changed files, in
# the v1 layout, so validation, backup, install, health and rollback stay the
# same code.  Sets VU_PACKAGE_DIR (changed files), VU_FULL_DIR (every signed
# file, for the installed-files record), VU_VIEW_MANIFEST, VU_CHANGED_FILES and
# VU_FETCHED_BYTES.
vu_v2_stage() {
    manifest=$1
    transaction_staging=$VU_STAGING_DIR/transaction.$$
    package_dir=$transaction_staging/package
    full_dir=$transaction_staging/full
    mkdir -p "$package_dir" "$full_dir" || return 1
    changed=$transaction_staging/changed.tsv
    vu_v2_plan "$manifest" "$changed" || return 1

    VU_CHANGED_FILES=$(grep -c . "$changed")
    VU_FETCHED_BYTES=$(awk -F '\t' '{sum += $3} END {printf "%.0f\n", sum}' "$changed")
    [ "$VU_FETCHED_BYTES" -le "$max_unpacked_size" ] || return 1
    staging_free=$(vu_free_kb staging "$VU_STAGING_DIR")
    [ -n "$staging_free" ] && [ "$staging_free" -ge $(((VU_FETCHED_BYTES + 1023) / 1024 + minimum_free_kb)) ] || return 1

    base=$(jq -r '.signed.files_base' "$manifest")
    awk -F '\t' -v dir="$package_dir/files" '{print $2 "\t" $3 "\t" dir $1}' "$changed" > "$transaction_staging/fetch.tsv" || return 1
    vu_v2_fetch "$transaction_staging/fetch.tsv" "$base" || return 1

    jq -R -s 'split("\n") | map(select(length > 0) | split("\t")
        | {source: ("files" + .[0]), target: .[0], sha256: .[1], mode: .[3], component: .[4],
           restart_policy: "none", config_policy: "program-only"}) | {schema: 1, files: .}' \
        "$changed" > "$package_dir/package-manifest.json" || return 1
    jq '{schema: 1, files: [.signed.files[] | {source: ("files" + .target), target, sha256, mode, component,
           restart_policy: "none", config_policy: "program-only"}]}' "$manifest" > "$full_dir/package-manifest.json" || return 1
    # The signed manifest with the components this run really changes: what the
    # v1 package checks compare the package with.
    VU_VIEW_MANIFEST=$transaction_staging/view.json
    jq --slurpfile p "$package_dir/package-manifest.json" \
        '.signed.affected_components = ([$p[0].files[].component] | unique)' "$manifest" > "$VU_VIEW_MANIFEST" || return 1
    if [ "$VU_CHANGED_FILES" -gt 0 ]; then
        vu_package_validate "$package_dir" "$VU_VIEW_MANIFEST" || return 1
    fi
    VU_PACKAGE_DIR=$package_dir
    VU_FULL_DIR=$full_dir
}

vu_last_apply_write() {
    mkdir -p "$VU_STATE_DIR" || return 1
    {
        printf 'version=%s\n' "$1"
        printf 'schema=%s\n' "$2"
        printf 'changed_files=%s\n' "$3"
        printf 'fetched_bytes=%s\n' "$4"
        printf 'engine_version=%s\n' "$VU_ENGINE_VERSION"
        printf 'applied_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    } > "$VU_STATE_DIR/last-apply.state.tmp.$$" && mv -f "$VU_STATE_DIR/last-apply.state.tmp.$$" "$VU_STATE_DIR/last-apply.state"
}

# ---------- Engine slots ----------

vu_updater_root() { printf '%s\n' "${VWARD_UPDATER_ROOT:-$VU_ROOT_PREFIX/opt/share/vward/updater}"; }

# The slot the current engine runs from, and the other one.
vu_engine_slots() {
    slots_root=$(vu_updater_root)
    VU_ACTIVE_SLOT=$(CDPATH= cd -- "$slots_root/current" 2>/dev/null && pwd -P) || return 1
    case "$VU_ACTIVE_SLOT" in
        */slots/A) VU_NEXT_SLOT=${VU_ACTIVE_SLOT%/A}/B ;;
        */slots/B) VU_NEXT_SLOT=${VU_ACTIVE_SLOT%/B}/A ;;
        *) return 1 ;;
    esac
}

vu_engine_newer() {
    manifest_engine=$(jq -r '.signed.engine.version // empty' "$1" 2>/dev/null)
    [ -n "$manifest_engine" ] && vu_version_lt "$VU_ENGINE_VERSION" "$manifest_engine"
}

# vu_engine_install_from DIR MANIFEST: DIR holds the engine files of MANIFEST,
# already checked.  Syntax, a self-test of the new engine against the same signed
# manifest, then the inactive slot and an atomic switch of "current".
vu_engine_install_from() {
    dir=$1 manifest=$2
    vu_engine_slots || return 1
    want=$(jq -r '.signed.engine.version' "$manifest")
    jq -r '.signed.engine.files[] | [.name, .mode] | @tsv' "$manifest" |
    while IFS="$(printf '\t')" read -r name mode; do
        chmod "$mode" "$dir/$name" || exit 1
        case "$name" in *.sh) sh -n "$dir/$name" || exit 1 ;; esac
    done || return 1
    got=$(VWARD_ENGINE_SELF_TEST=1 sh "$dir/vward-update.sh" --self-test "$manifest" 2>/dev/null | sed -n 's/^engine_version=//p')
    [ "$got" = "$want" ] || { vu_log ERROR "New engine failed its self-test (reports '${got:-nothing}', expected $want)"; return 1; }
    next_new=$VU_NEXT_SLOT.new.$$
    rm -rf "${next_new:?}"
    mkdir -p "$next_new" || return 1
    jq -r '.signed.engine.files[].name' "$manifest" | while IFS= read -r name; do
        cp -p "$dir/$name" "$next_new/$name" || exit 1
    done || { rm -rf "${next_new:?}"; return 1; }
    rm -rf "${VU_NEXT_SLOT:?}" && mv "$next_new" "$VU_NEXT_SLOT" || return 1
    vu_journal_set engine_previous_slot "$VU_ACTIVE_SLOT" || return 1
    # BusyBox mv would move a new link into the target directory: ln -sfn replaces it.
    ln -sfn "$VU_NEXT_SLOT" "$(vu_updater_root)/current" || return 1
    [ "$(CDPATH= cd -- "$(vu_updater_root)/current" 2>/dev/null && pwd -P)" = "$VU_NEXT_SLOT" ] || return 1
    vu_journal_set engine_version "$want" || :
    vu_log INFO "Update engine $VU_ENGINE_VERSION -> $want (slot ${VU_NEXT_SLOT##*/})"
}

# vu_engine_update MANIFEST: fetch the engine files a newer signed engine has and
# install them.  Only the files that differ from the running engine are fetched.
vu_engine_update() {
    manifest=$1
    stage=$VU_STAGING_DIR/engine.$$
    rm -rf "${stage:?}"
    mkdir -p "$stage" || return 1
    base=$(jq -r '.signed.files_base' "$manifest")
    : > "$stage.fetch" || return 1
    jq -r '.signed.engine.files[] | [.name, .sha256, (.size | tostring)] | @tsv' "$manifest" |
    while IFS="$(printf '\t')" read -r name sha size; do
        if [ -f "$SELF_DIR/$name" ] && [ "$(sha256sum "$SELF_DIR/$name" | awk '{print $1}')" = "$sha" ]; then
            cp "$SELF_DIR/$name" "$stage/$name" || exit 1
        else
            printf '%s\t%s\t%s\n' "$sha" "$size" "$stage/$name" >> "$stage.fetch" || exit 1
        fi
    done || { rm -rf "${stage:?}" "$stage.fetch"; return 1; }
    vu_v2_fetch "$stage.fetch" "$base" || { rm -rf "${stage:?}" "$stage.fetch" "$stage.fetch.curl"; return 1; }
    rm -f "$stage.fetch" "$stage.fetch.curl"
    vu_engine_install_from "$stage" "$manifest"
    rc=$?
    rm -rf "${stage:?}"
    return "$rc"
}

# vu_engine_check_dir DIR MANIFEST: every engine file of MANIFEST in DIR, as signed.
vu_engine_check_dir() {
    jq -r '.signed.engine.files[] | [.name, .sha256, (.size | tostring)] | @tsv' "$2" |
    while IFS="$(printf '\t')" read -r name sha size; do
        [ -f "$1/$name" ] && [ ! -L "$1/$name" ] || exit 1
        [ "$(wc -c < "$1/$name" | tr -d ' ')" = "$size" ] || exit 1
        [ "$(sha256sum "$1/$name" | awk '{print $1}')" = "$sha" ] || exit 1
    done
}
