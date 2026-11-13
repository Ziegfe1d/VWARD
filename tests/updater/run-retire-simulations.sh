#!/bin/sh
# Update Engine 2.1: removal of retired parts (fix.39).
#
# A signed manifest lists the parts a release drops (files, folders, crontab lines, init.d
# services).  On the router emulator: before -> after (the part is gone, the rest untouched),
# after -> rollback (a failed health check, a failed removal, a power cut: every file, mode and
# the crontab back byte for byte), a second run (nothing left, nothing touched), the v1 whole
# package, a dry run, refused lists and parts skipped rather than half removed.

set -u

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENGINE_SRC=$REPO/components/update-engine
. "$REPO/tests/updater/seed-runtime.sh"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/vward-updater-retire.XXXXXX")
trap '[ -n "${KEEP:-}" ] || rm -rf "$WORK"' EXIT HUP INT TERM

passed=0 failed=0 case_number=0
pass() { passed=$((passed + 1)); case_number=$((case_number + 1)); printf 'ok %s - %s\n' "$case_number" "$1"; }
fail() { failed=$((failed + 1)); case_number=$((case_number + 1)); printf 'not ok %s - %s\n' "$case_number" "$1"; }
check() { name=$1; shift; if "$@"; then pass "$name"; else fail "$name"; sed 's/^/  # /' "$WORK/last.out" 2>/dev/null | tail -n 15; fi; }

openssl genpkey -algorithm ED25519 -out "$WORK/private.pem" >/dev/null 2>&1
openssl pkey -in "$WORK/private.pem" -pubout -out "$WORK/public.pem" >/dev/null 2>&1

ENGINE_FILES="vward-update-bootstrap.sh vward-update-common-base.sh vward-update-common.sh vward-update-delta.sh
vward-update-hardening.sh vward-update-health.sh vward-update-rollback.sh vward-update-watch.sh vward-update.sh"
ENGINE_VERSION=$(sed -n 's/^VU_ENGINE_VERSION=//p' "$ENGINE_SRC/vward-update-common-base.sh")

ENGINE=$WORK/engine
mkdir -p "$ENGINE"
for f in $ENGINE_FILES; do cp "$ENGINE_SRC/$f" "$ENGINE/$f"; done
cp "$REPO/config/components/component-registry.json" "$ENGINE/component-registry.json"

# The part this release retires, as the router has it.
OLD_FILES="/opt/bin/vward-oldpart.sh /opt/share/vward/oldpart/data.json /opt/share/vward/oldpart/sub/rules.txt /opt/etc/init.d/S95vward-oldpart"
RETIRE_OLDPART='[{"part":"oldpart","files":["/opt/bin/vward-oldpart.sh","/opt/share/vward/oldpart/data.json","/opt/share/vward/oldpart/sub/rules.txt","/opt/etc/init.d/S95vward-oldpart","/opt/bin/vward-oldpart-gone.sh"],"dirs":["/opt/share/vward/oldpart","/opt/share/vward/oldpart/sub"],"cron":["/opt/bin/vward-oldpart.sh"],"services":["/opt/etc/init.d/S95vward-oldpart"]}]'

new_root() {
    ROOT=$WORK/root-$1
    mkdir -p "$ROOT/opt/etc/vward" "$ROOT/opt/share/vward/console/www" "$ROOT/opt/bin" "$ROOT/opt/var/lib/vward/updater" \
        "$ROOT/opt/share/vward/oldpart/sub" "$ROOT/opt/etc/init.d" "$ROOT/opt/var/spool/cron/crontabs" "$ROOT/tmp"
    cp "$WORK/public.pem" "$ROOT/opt/etc/vward/update-public.pem"
    printf '%s\n' '0.2.0-rc.1' > "$ROOT/opt/share/vward/VERSION"
    printf '%s\n' route-old > "$ROOT/opt/bin/vward-route.sh"
    printf '%s\n' wan-same > "$ROOT/opt/bin/vward-wan-guard.sh"
    printf '%s\n' html > "$ROOT/opt/share/vward/console/www/index.html"
    printf '%s\n' oldpart > "$ROOT/opt/bin/vward-oldpart.sh"
    printf '%s\n' '{"old":1}' > "$ROOT/opt/share/vward/oldpart/data.json"
    printf '%s\n' rules > "$ROOT/opt/share/vward/oldpart/sub/rules.txt"
    printf '%s\n' '#!/bin/sh' 'printf "%s\n" "$1" >> "$(dirname "$0")/../../../tmp/oldpart.service"' > "$ROOT/opt/etc/init.d/S95vward-oldpart"
    chmod 0755 "$ROOT/opt/bin/vward-route.sh" "$ROOT/opt/bin/vward-wan-guard.sh" "$ROOT/opt/bin/vward-oldpart.sh" "$ROOT/opt/etc/init.d/S95vward-oldpart"
    chmod 0640 "$ROOT/opt/share/vward/oldpart/data.json"
    CRONTAB=$ROOT/opt/var/spool/cron/crontabs/root
    {
        printf '%s\n' '* * * * * /opt/bin/vward-wan-guard.sh > /tmp/vward-wan-guard.cron.out 2>&1; RC=$?; date > /tmp/vward-wan-guard.cron.last'
        printf '%s\n' '*/5 * * * * /opt/bin/vward-oldpart.sh > /tmp/vward-oldpart.cron.out 2>&1; RC=$?; echo $RC > /tmp/vward-oldpart.cron.rc'
        printf '%s\n' '# off: no longer needed # * * * * * /opt/bin/vward-oldpart.sh watch'
        printf '%s\n' '0 3 * * * /opt/bin/my-own-backup.sh'
        printf '%s\n' '* * * * * /opt/bin/vward-oldpart.sh-not-this-one'
    } > "$CRONTAB"
    chmod 0600 "$CRONTAB"
    printf '%s\n' '{"schema":1,"components":{"oldpart":{"release":"0.2.0-rc.1","files":{"/opt/bin/vward-oldpart.sh":"x"}},"wan-guard":{"release":"0.2.0-rc.1","files":{"/opt/bin/vward-wan-guard.sh":"y"}}}}' \
        > "$ROOT/opt/var/lib/vward/updater/components.json"
    chmod 0600 "$ROOT/opt/var/lib/vward/updater/components.json"
    CONFIG=$ROOT/opt/etc/vward/update.conf
    {
        printf '%s\n' 'update_enabled=1' 'auto_apply=0' 'channel=dev' 'update_method=files'
        printf 'public_key_file=%s\n' "$ROOT/opt/etc/vward/update-public.pem"
        printf 'current_version_file=%s\n' "$ROOT/opt/share/vward/VERSION"
        printf '%s\n' 'minimum_free_kb=1' 'barrier_integration_ready=1' 'safe_window_start=00:00' 'safe_window_end=23:59'
    } > "$CONFIG"
    seed_runtime "$ROOT" || exit 1
    SLOTS=$ROOT/opt/share/vward/updater
    mkdir -p "$SLOTS/slots"
    cp -R "$ENGINE" "$SLOTS/slots/A"
    ln -s "$SLOTS/slots/A" "$SLOTS/current"
    FILES=$WORK/files-$1
    mkdir -p "$FILES"
    snapshot "$ROOT" > "$WORK/before-$1.txt"
    grep -v components.json "$WORK/before-$1.txt" > "$WORK/before-$1.txt.part"
}

# snapshot ROOT: every file of the part and the crontab, with content hash and mode.
snapshot() {
    for t in $OLD_FILES /opt/var/spool/cron/crontabs/root /opt/var/lib/vward/updater/components.json; do
        if [ -f "$1$t" ]; then
            printf '%s %s %s\n' "$t" "$(sha256sum "$1$t" | awk '{print $1}')" "$(stat -c %a "$1$t")"
        else
            printf '%s missing\n' "$t"
        fi
    done
}

blob() {
    digest=$(sha256sum "$1" | awk '{print $1}')
    cp "$1" "$FILES/$digest"
    printf '%s %s\n' "$digest" "$(wc -c < "$1" | tr -d ' ')"
}

sign() {
    jq -cS . "$1" > "$1.c"
    openssl pkeyutl -sign -inkey "$WORK/private.pem" -rawin -in "$1.c" -out "$1.sig"
    jq -n --slurpfile s "$1" --arg sig "$(openssl base64 -A -in "$1.sig")" '{signed:$s[0],signature:$sig}' > "$2"
}

# make_manifest LABEL SEQUENCE RETIRE_JSON [EXTRA_TARGET]: route.sh new, wan-guard unchanged,
# the current engine; EXTRA_TARGET is shipped by the release too (a conflict when also retired).
# VERSION: the release version (0.2.0-rc.2 by default).
make_manifest() {
    label=$1 sequence=$2 retire=$3 extra=${4:-} version=${VERSION:-0.2.0-rc.2}
    printf '%s\n' "route-$label" > "$WORK/route-$label"
    set -- $(blob "$WORK/route-$label"); rs=$1 rz=$2
    set -- $(blob "$ROOT/opt/bin/vward-wan-guard.sh"); ws=$1 wz=$2
    : > "$WORK/engine-$label.tsv"
    for f in $ENGINE_FILES component-registry.json; do
        set -- $(blob "$ENGINE/$f")
        case "$f" in *.sh) m=0755 ;; *) m=0644 ;; esac
        printf '%s\t%s\t%s\t%s\n' "$f" "$1" "$2" "$m" >> "$WORK/engine-$label.tsv"
    done
    signed=$WORK/signed-$label.json
    jq -n --argjson sequence "$sequence" --arg rs "$rs" --argjson rz "$rz" --arg ws "$ws" --argjson wz "$wz" \
        --arg ever "$ENGINE_VERSION" --arg version "$version" --rawfile e "$WORK/engine-$label.tsv" --argjson retire "$retire" --arg extra "$extra" '
        {schema:2,update_id:("test-retire-"+($sequence|tostring)),sequence:$sequence,version:$version,channel:"dev",priority:"ROUTINE",
         published_at:"2026-11-13T00:00:00Z",min_updater_version:"2.0.0",files_base:"https://example.invalid/files/",
         files:([{target:"/opt/bin/vward-route.sh",sha256:$rs,size:$rz,mode:"0755",component:"route-tools"},
                {target:"/opt/bin/vward-wan-guard.sh",sha256:$ws,size:$wz,mode:"0755",component:"wan-guard"}]
               + (if $extra == "" then [] else [{target:$extra,sha256:$ws,size:$wz,mode:"0755",component:"route-tools"}] end)),
         engine:{version:$ever,files:($e | split("\n") | map(select(length > 0) | split("\t") | {name:.[0],sha256:.[1],size:(.[2]|tonumber),mode:.[3]}))},
         compatibility:{min_vward:"0.1.0-dev",max_vward:$version},affected_components:["route-tools","wan-guard"],affected_services:[],
         health_profile:"default",requires_reboot:false,rollback_policy:"automatic",signature:{algorithm:"Ed25519",key_id:"test-key"}}
        | if $retire == null then . else .retire = $retire end' > "$signed"
    MANIFEST=$WORK/manifest-$label.json
    sign "$signed" "$MANIFEST"
}

run() {
    VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG VWARD_TEST_MANIFEST=$MANIFEST VWARD_TEST_FILES_DIR=$FILES \
        VWARD_UPDATER_ROOT=$SLOTS "$SLOTS/current/vward-update.sh" "$@" > "$WORK/last.out" 2>&1
}
journal_backup() { sed -n 's/^active_backup=//p' "$ROOT/opt/var/lib/vward/updater/journal.state" | tail -n 1; }
same_as_before() { snapshot "$ROOT" | cmp -s - "$WORK/before-$1.txt"; }
part_kept() { snapshot "$ROOT" | grep -v components.json | cmp -s - "$WORK/before-$1.txt.part"; }
crontab_has() { grep -qF -- "$1" "$ROOT/opt/var/spool/cron/crontabs/root"; }
committed() { grep -qx "installed_version=$1" "$ROOT/opt/var/lib/vward/updater/committed.state" 2>/dev/null; }

# 1. Before -> after: the part is gone, everything else stays.
new_root apply
make_manifest apply 10 "$RETIRE_OLDPART"
run --apply; rc=$?
check 'an update with a retired part applies' [ "$rc" -eq 0 ]
check 'the new file of the release is installed' [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = route-apply ]
check 'every file of the part is removed' sh -c 'for t in $2; do [ ! -e "$1$t" ] || exit 1; done' sh "$ROOT" "$OLD_FILES"
check 'the folders of the part are removed, deepest first' [ ! -e "$ROOT/opt/share/vward/oldpart" ]
check 'its folder parent stays' [ -d "$ROOT/opt/share/vward/console" ]
check 'the service is stopped before removal' grep -qx stop "$ROOT/tmp/oldpart.service"
check 'its crontab line is removed' sh -c '! grep -q "vward-oldpart.sh > " "$1"' sh "$CRONTAB"
check 'its commented crontab line is removed too' sh -c '! grep -q "vward-oldpart.sh watch" "$1"' sh "$CRONTAB"
check 'the other VWARD crontab line stays' crontab_has '/opt/bin/vward-wan-guard.sh > /tmp/vward-wan-guard.cron.out'
check 'the owner line stays' crontab_has '0 3 * * * /opt/bin/my-own-backup.sh'
check 'a program whose name only starts the same stays' crontab_has '/opt/bin/vward-oldpart.sh-not-this-one'
check 'the crontab stays private' [ "$(stat -c %a "$CRONTAB")" = 600 ]
check 'the version is committed' committed 0.2.0-rc.2
backup=$(journal_backup)
check 'the removed files are in the backup' sh -c 'for t in $2; do grep -q "^$t	1	" "$1/files.tsv" && [ -f "$1/files$t" ] || exit 1; done' sh "$backup" "$OLD_FILES"
check 'the crontab before is in the backup' sh -c 'grep -q "vward-oldpart.sh > " "$1/crontab" && grep -q "^crontab_sha=[0-9a-f]\{64\}$" "$1/backup.meta"' sh "$backup"
check 'the installed-files record forgets the part' jq -e '(.components | has("oldpart") | not) and .components["wan-guard"].files["/opt/bin/vward-wan-guard.sh"]' "$ROOT/opt/var/lib/vward/updater/components.json" >/dev/null
check 'the removal is in the log' grep -q 'Retire: part oldpart removed (4 file(s))' "$WORK/last.out"
check 'the crontab removal is in the log' grep -q 'Retire: 2 crontab line(s) removed' "$WORK/last.out"
check 'the last run counts the removed files' grep -qx 'retired_files=4' "$ROOT/opt/var/lib/vward/updater/last-apply.state"

# 2. The next release keeps the list: nothing left, nothing touched, no crontab backup.
cp "$CRONTAB" "$WORK/crontab-after"
VERSION=0.2.0-rc.3 make_manifest again 11 "$RETIRE_OLDPART"
run --apply; rc=$?
check 'a second update with the same list applies' [ "$rc" -eq 0 ]
check 'the crontab is not rewritten again' cmp -s "$CRONTAB" "$WORK/crontab-after"
check 'nothing is backed up for the part again' sh -c '[ ! -e "$1/crontab" ] && ! grep -q oldpart "$1/files.tsv"' sh "$(journal_backup)"
check 'the second run counts no removed file' grep -qx 'retired_files=0' "$ROOT/opt/var/lib/vward/updater/last-apply.state"

# 3. After -> rollback: a failed health check brings back every file, mode and the crontab.
new_root health
make_manifest health 10 "$RETIRE_OLDPART"
VWARD_TEST_FORCE_HEALTH_FAIL=1 run --apply; rc=$?
check 'a failed health check rolls the update back' [ "$rc" -eq 41 ]
check 'files, modes, crontab and record are back byte for byte' same_as_before health
check 'the replaced release file is back too' [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = route-old ]
check 'the version is not committed' sh -c '! grep -qx "installed_version=0.2.0-rc.2" "$1"' sh "$ROOT/opt/var/lib/vward/updater/committed.state"
check 'the update is quarantined' grep -q 'quarantined' "$WORK/last.out"

# 4. A removal that fails half-way (after the crontab is written) is rolled back like a failed install.
new_root halfway
make_manifest halfway 10 "$RETIRE_OLDPART"
VWARD_TEST_FAIL_RETIRE=1 run --apply; rc=$?
check 'a failed removal fails the update' [ "$rc" -eq 40 ]
check 'after a failed removal everything is back' same_as_before halfway

# 5. A power cut after the removal, before the commit: recovery at boot rolls back.
new_root crash
make_manifest crash 10 "$RETIRE_OLDPART"
VWARD_TEST_CRASH_COMMIT=before_snapshot run --apply; rc=$?
check 'the emulated power cut stops the run' [ "$rc" -eq 99 ]
check 'the part was removed before the cut' [ ! -e "$ROOT/opt/bin/vward-oldpart.sh" ]
run --recover; rc=$?
check 'recovery after the power cut succeeds' [ "$rc" -eq 0 ]
check 'recovery brings back every file and the crontab' same_as_before crash

# 5a. The crontab changes after the plan, before the barrier (hourly housekeeping): the line
# written meanwhile survives the removal, and a rollback returns the crontab with it.
new_root late
make_manifest late 10 "$RETIRE_OLDPART"
VWARD_TEST_CRONTAB_LATE='17 * * * * /opt/bin/vward-housekeeping.sh' run --apply; rc=$?
check 'a crontab changed after the plan: the update applies' [ "$rc" -eq 0 ]
check 'the line written after the plan survives' crontab_has '17 * * * * /opt/bin/vward-housekeeping.sh'
check 'the retired line is still removed' sh -c '! grep -q "vward-oldpart.sh > " "$1"' sh "$CRONTAB"
new_root latefail
make_manifest latefail 10 "$RETIRE_OLDPART"
cp "$CRONTAB" "$WORK/crontab-latefail"; printf '%s\n' '17 * * * * /opt/bin/vward-housekeeping.sh' >> "$WORK/crontab-latefail"
VWARD_TEST_CRONTAB_LATE='17 * * * * /opt/bin/vward-housekeeping.sh' VWARD_TEST_FORCE_HEALTH_FAIL=1 run --apply; rc=$?
check 'a rollback returns the crontab as it was inside the barrier' sh -c '[ "$1" -eq 41 ] && cmp -s "$2" "$3"' sh "$rc" "$CRONTAB" "$WORK/crontab-latefail"

# 6. A dry run shows the removal and changes nothing.
new_root dry
make_manifest dry 10 "$RETIRE_OLDPART"
run --dry-run; rc=$?
check 'the dry run succeeds' [ "$rc" -eq 0 ]
check 'the dry run lists the part and its files' sh -c 'grep -q "\[oldpart\] apply: 4 file(s)" "$1" && grep -q "\[oldpart\] remove /opt/bin/vward-oldpart.sh" "$1" && grep -q "crontab: 2 line(s) removed" "$1"' sh "$WORK/last.out"
check 'the dry run removes nothing' same_as_before dry

# 7. The v1 whole package carries the same list.
new_root v1
mkdir -p "$WORK/pkg-v1/files"
printf 'route-v1\n' > "$WORK/pkg-v1/files/vward-route.sh"
d=$(sha256sum "$WORK/pkg-v1/files/vward-route.sh" | awk '{print $1}')
jq -n --arg d "$d" '{schema:1,files:[{source:"files/vward-route.sh",target:"/opt/bin/vward-route.sh",sha256:$d,mode:"0755",component:"route-tools",restart_policy:"none",config_policy:"program-only"}]}' > "$WORK/pkg-v1/package-manifest.json"
tar -czf "$WORK/pkg-v1.tar.gz" -C "$WORK/pkg-v1" .
ps=$(sha256sum "$WORK/pkg-v1.tar.gz" | awk '{print $1}'); pz=$(wc -c < "$WORK/pkg-v1.tar.gz" | tr -d ' ')
uz=$(find "$WORK/pkg-v1" -type f -exec wc -c {} \; | awk '{s += $1} END {print s}')
jq -n --arg s "$ps" --argjson z "$pz" --argjson u "$uz" --argjson retire "$RETIRE_OLDPART" '{schema:1,update_id:"test-v1",sequence:10,version:"0.2.0-rc.2",channel:"dev",priority:"ROUTINE",published_at:"2026-11-13T00:00:00Z",min_updater_version:"1.0.0",package:{url:"https://example.invalid/p.tar.gz",sha256:$s,size:$z,unpacked_size:$u},compatibility:{min_vward:"0.1.0-dev",max_vward:"0.2.0-rc.2"},affected_components:["route-tools"],affected_services:[],health_profile:"default",requires_reboot:false,rollback_policy:"automatic",retire:$retire,signature:{algorithm:"Ed25519",key_id:"test-key"}}' > "$WORK/signed-v1.json"
MANIFEST=$WORK/manifest-v1.json
sign "$WORK/signed-v1.json" "$MANIFEST"
VWARD_TEST_PACKAGE=$WORK/pkg-v1.tar.gz run --apply; rc=$?
check 'the v1 whole package applies with the list' sh -c '[ "$1" -eq 0 ] && [ "$(cat "$2/opt/bin/vward-route.sh")" = route-v1 ]' sh "$rc" "$ROOT"
check 'the v1 whole package removes the part' sh -c 'for t in $2; do [ ! -e "$1$t" ] || exit 1; done' sh "$ROOT" "$OLD_FILES"

# 8. Lists that are refused outright: the update stops before anything is touched.
refused() {
    label=$1 retire=$2 extra=${3:-}
    new_root "$label"
    make_manifest "$label" 10 "$retire" "$extra"
    run --apply; rc=$?
    check "refused: $4" sh -c '[ "$1" -eq 31 ]' sh "$rc"
    check "refused, nothing touched: $4" sh -c '[ "$(cat "$1/opt/bin/vward-route.sh")" = route-old ]' sh "$ROOT"
    check "refused, the part stays: $4" same_as_before "$label"
}
refused ship '[{"part":"oldpart","files":["/opt/bin/vward-oldpart.sh"]}]' /opt/bin/vward-oldpart.sh 'a file the release still ships'
refused system '[{"part":"oldpart","files":["/etc/passwd"]}]' '' 'a file outside the VWARD program places'
refused config '[{"part":"oldpart","files":["/opt/etc/vward/update.conf"]}]' '' 'the owner settings'
refused updater '[{"part":"oldpart","files":["/opt/share/vward/updater/current/vward-update.sh"]}]' '' 'the update engine'
refused climb '[{"part":"oldpart","files":["/opt/bin/../etc/vward/update.conf"]}]' '' 'a path that climbs out'
refused crondef '[{"part":"oldpart","files":["/opt/bin/vward-oldpart.sh"],"cron":["/opt/sbin/crond"]}]' '' 'a crontab program that is not VWARD'
refused service '[{"part":"oldpart","files":["/opt/bin/vward-oldpart.sh"],"services":["/opt/etc/init.d/S95vward-oldpart"]}]' '' 'a service outside the part files'
refused dirroot '[{"part":"oldpart","files":["/opt/bin/vward-oldpart.sh"],"dirs":["/opt/share/vward"]}]' '' 'the VWARD folder itself'
refused twice '[{"part":"oldpart","files":["/opt/bin/vward-oldpart.sh"]},{"part":"oldpart","files":["/opt/bin/vward-oldpart.sh"]}]' '' 'one part named twice'
refused nofiles '[{"part":"oldpart","files":[]}]' '' 'a part without files'

# 9. Parts skipped, never half removed: the update itself applies.
new_root owned
printf '%s\n' scheduler > "$ROOT/opt/bin/vward-wifi-client-scheduler.sh"
make_manifest owned 10 '[{"part":"oldpart","files":["/opt/bin/vward-oldpart.sh","/opt/bin/vward-wifi-client-scheduler.sh"],"cron":["/opt/bin/vward-oldpart.sh"]}]'
run --apply; rc=$?
check 'a part the registry still owns: the update applies' [ "$rc" -eq 0 ]
check 'a part the registry still owns is kept whole' sh -c '[ -f "$1/opt/bin/vward-oldpart.sh" ] && [ -f "$1/opt/bin/vward-wifi-client-scheduler.sh" ]' sh "$ROOT"
check 'a part the registry still owns keeps its crontab line' crontab_has '/opt/bin/vward-oldpart.sh > /tmp/vward-oldpart.cron.out'
check 'the skipped part is in the log' grep -q 'Retire: part oldpart skipped: component wifi-client-guard still owns /opt/bin/vward-wifi-client-scheduler.sh' "$WORK/last.out"

new_root shared
printf '%s\n' '* * * * * /opt/bin/vward-oldpart.sh && /opt/bin/vward-wan-guard.sh' >> "$CRONTAB"
snapshot "$ROOT" | grep -v components.json > "$WORK/before-shared.txt.part"
make_manifest shared 10 "$RETIRE_OLDPART"
run --apply; rc=$?
check 'a crontab line shared with a live program: the update applies' [ "$rc" -eq 0 ]
check 'a part sharing a crontab line is kept whole' part_kept shared
check 'the shared line is in the log' grep -q 'Retire: part oldpart skipped: 1 crontab line(s) also run another VWARD program' "$WORK/last.out"

# 10. Without a list nothing changes in how an update works.
new_root plain
make_manifest plain 10 null
run --apply; rc=$?
check 'an update without a list applies' [ "$rc" -eq 0 ]
check 'an update without a list leaves the part' part_kept plain

printf 'retire simulations: %s passed, %s failed\n' "$passed" "$failed"
[ "$failed" -eq 0 ]
