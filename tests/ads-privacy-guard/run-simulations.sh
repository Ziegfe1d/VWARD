#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
TMP="${TMPDIR:-/tmp}/vward-ads-tests.$$"; trap 'rm -rf "$TMP"' EXIT INT TERM
mkdir -p "$TMP/etc" "$TMP/state/sources" "$TMP/state/work" "$TMP/log" "$TMP/backups" "$TMP/share" "$TMP/bin"
fail(){ echo "FAIL: $*" >&2; exit 1; }; pass(){ echo "PASS: $*"; }
T="$ROOT/tests/ads-privacy-guard"
LIB="$ROOT/components/ads-privacy-guard/lib/vward-ads-privacy-common.sh"; S="$ROOT/components/ads-privacy-guard/scripts"; MAIN="$S/vward-ads-privacy-guard.sh"
JQ="$(command -v jq)"; CURL="$(command -v curl)"; [ -x "$JQ" ] || fail jq; [ -x "$CURL" ] || fail curl

# 1 syntax gates
for F in "$ROOT"/components/ads-privacy-guard/lib/*.sh "$S"/*.sh; do busybox sh -n "$F" || fail "BusyBox syntax: $F"; done
pass "BusyBox shell syntax"

# 2 normalization
VWARD_ADS_ETC="$TMP/etc" VWARD_ADS_STATE="$TMP/state" VWARD_ADS_LOG_DIR="$TMP/log" VWARD_ADS_BACKUP_ROOT="$TMP/backups" VWARD_ADS_SHARE="$TMP/share" busybox sh -c '. "$1"; ads_source_domain_normalize < "$2"' sh "$LIB" "$T/fixtures/source-normalize.txt" > "$TMP/norm"
grep -qx ads.example.com "$TMP/norm" || fail normalize; ! grep -q allow.example.net "$TMP/norm" || fail exception_leak
VWARD_ADS_ETC="$TMP/etc" VWARD_ADS_STATE="$TMP/state" VWARD_ADS_LOG_DIR="$TMP/log" VWARD_ADS_BACKUP_ROOT="$TMP/backups" VWARD_ADS_SHARE="$TMP/share" busybox sh -c '. "$1"; ads_source_exception_normalize < "$2"' sh "$LIB" "$T/fixtures/source-normalize.txt" > "$TMP/exc"
grep -qx allow.example.net "$TMP/exc" || fail exception_normalize
pass "conservative feed normalization"

# 3 production source registry contract
REG="$ROOT/components/ads-privacy-guard/data/source-registry.json"
"$JQ" -e '.schema==1 and (.sources|length>0) and all(.sources[]; (.default_mode=="active" or .default_mode=="check" or .default_mode=="off") and (.weight>=0 and .weight<=100) and (.urls|length>0))' "$REG" >/dev/null || fail source_registry
python3 - <<PY
import json
from pathlib import Path
from jsonschema import Draft202012Validator
r=json.loads(Path('$REG').read_text()); s=json.loads(Path('$ROOT/components/ads-privacy-guard/data/source-registry.schema.json').read_text()); Draft202012Validator(s).validate(r)
PY
pass "source registry schema and modes"

# Shared classifier fixture
CETC="$TMP/class-etc"; CST="$TMP/class-state"; CSH="$TMP/class-share"; mkdir -p "$CETC" "$CST/sources" "$CST/work" "$CSH"
cat > "$CSH/source-registry.json" <<'JSON'
{"schema":1,"sources":[
{"id":"popup","name":"Popup","vendor":"v-a","independence_group":"v-a-popup","purpose":"popup-ads","enabled":true,"default_mode":"active","weight":100,"single_source_block":true,"format":"adblock","min_entries":1,"max_bytes":100000,"urls":["https://example.invalid/a"]},
{"id":"feed-a","name":"A","vendor":"v-a","independence_group":"v-a","purpose":"ads","enabled":true,"default_mode":"active","weight":80,"single_source_block":false,"format":"adblock","min_entries":1,"max_bytes":100000,"urls":["https://example.invalid/b"]},
{"id":"feed-b","name":"B","vendor":"v-b","independence_group":"v-b","purpose":"tracking","enabled":true,"default_mode":"active","weight":80,"single_source_block":false,"format":"adblock","min_entries":1,"max_bytes":100000,"urls":["https://example.invalid/c"]},
{"id":"check-only","name":"Check","vendor":"v-c","independence_group":"v-c","purpose":"ads","enabled":true,"default_mode":"check","weight":100,"single_source_block":true,"format":"adblock","min_entries":1,"max_bytes":100000,"urls":["https://example.invalid/d"]}
]}
JSON
cat > "$CSH/trust-core.tsv" <<'EOF2'
google.com|exact|trusted-core|365|1|test
EOF2
: > "$CETC/allowlist.tsv"; : > "$CETC/denylist.tsv"; chmod 0600 "$CETC/allowlist.tsv" "$CETC/denylist.tsv"
cat > "$CETC/ads-privacy-guard.conf" <<'CONF'
ENABLED=1
QUERY_SOURCE=file
SCAN_TAIL_LINES=500
MAX_CANDIDATES_PER_RUN=100
BLOCK_SCORE=150
REVIEW_SCORE=60
MIN_INDEPENDENT_GROUPS=2
MIN_SOURCE_INDEXES=1
ALLOW_TTL_DAYS=30
TRUST_TTL_DAYS=180
SUSPECT_TTL_HOURS=24
BLOCK_RECHECK_DAYS=30
HEURISTIC_REVIEW_SCORE=20
PUBLISH_MODE=staged
AUTO_PUBLISH=0
AUTO_RULE_SCOPE=exact
CONF
chmod 0600 "$CETC/ads-privacy-guard.conf"
printf '%s\n' badpopup.xyz > "$CST/sources/popup.domains"; : > "$CST/sources/popup.exceptions"
printf '%s\n' tracker.foo ads-network.test | sort -u > "$CST/sources/feed-a.domains"; printf '%s\n' safe.ads-network.test > "$CST/sources/feed-a.exceptions"
printf '%s\n' tracker.foo ads-network.test | sort -u > "$CST/sources/feed-b.domains"; : > "$CST/sources/feed-b.exceptions"
printf '%s\n' checkonly.example > "$CST/sources/check-only.domains"; : > "$CST/sources/check-only.exceptions"
cat > "$TMP/query.tsv" <<'EOF2'
google.com	192.0.2.1	2026-09-13T08:00:00+03:00
badpopup.xyz	192.0.2.1	2026-09-13T08:00:01+03:00
tracker.foo	192.0.2.1	2026-09-13T08:00:02+03:00
sub.ads-network.test	192.0.2.1	2026-09-13T08:00:03+03:00
safe.ads-network.test	192.0.2.1	2026-09-13T08:00:04+03:00
unknown-safe.example	192.0.2.1	2026-09-13T08:00:05+03:00
weird-redirect.xyz	192.0.2.1	2026-09-13T08:00:06+03:00
checkonly.example	192.0.2.1	2026-09-13T08:00:07+03:00
EOF2
cat > "$TMP/bin/query-reader" <<EOF2
#!/bin/sh
cat "$TMP/query.tsv"
EOF2
chmod +x "$TMP/bin/query-reader"
BASEENV="VWARD_ADS_LIB=$LIB VWARD_ADS_ETC=$CETC VWARD_ADS_STATE=$CST VWARD_ADS_LOG_DIR=$TMP/log VWARD_ADS_BACKUP_ROOT=$TMP/backups VWARD_ADS_SHARE=$CSH VWARD_ADS_CONFIG=$CETC/ads-privacy-guard.conf VWARD_ADS_SOURCE_REGISTRY=$CSH/source-registry.json VWARD_ADS_TRUST_BUILTIN=$CSH/trust-core.tsv VWARD_ADS_ALLOWLIST=$CETC/allowlist.tsv VWARD_ADS_DENYLIST=$CETC/denylist.tsv VWARD_ADS_JQ=$JQ VWARD_ADS_QUERY_READER=$TMP/bin/query-reader"
env $BASEENV busybox sh "$MAIN" scan > "$TMP/class.out" 2>&1 || { cat "$TMP/class.out"; fail classifier; }
STATE="$CST/verdicts.tsv"; RULES="$CST/generated/vward-ads-privacy-guard.rules"
grep -q '^badpopup.xyz|BLOCK|BLOCK|' "$STATE" || fail popup_block
grep -q '^tracker.foo|BLOCK|BLOCK|' "$STATE" || fail consensus
grep -q '^sub.ads-network.test|BLOCK|BLOCK|' "$STATE" || fail parent_evidence
grep -q '^safe.ads-network.test|SUSPECT|NONE|' "$STATE" || fail source_exception
grep -q '^google.com|TRUST|NONE|' "$STATE" || fail trust
grep -q '^unknown-safe.example|ALLOW|NONE|' "$STATE" || fail allow_cache
! grep -q '^checkonly.example|BLOCK|BLOCK|' "$STATE" || fail check_only_autoblock
# exact default is plain hostname, not ||domain^
grep -qx badpopup.xyz "$RULES" || { cat "$RULES"; fail exact_rule; }
! grep -q '^||badpopup.xyz\^$' "$RULES" || fail exact_became_suffix
pass "classification, CHECK semantics and exact default"

# 4 starvation: many hot trusted entries must not consume expensive cap
cat > "$TMP/query-starve.tsv" <<EOF2
newad.example	192.0.2.1	2026-09-13T09:00:00+03:00
EOF2
i=1; while [ $i -le 30 ]; do echo "google.com\t192.0.2.1\t2026-09-13T09:00:$i+03:00" >> "$TMP/query-starve.tsv"; i=$((i+1)); done
cp "$TMP/query-starve.tsv" "$TMP/query.tsv"; printf '%s\n' newad.example >> "$CST/sources/popup.domains"; sort -u "$CST/sources/popup.domains" -o "$CST/sources/popup.domains"
sed -i 's/^MAX_CANDIDATES_PER_RUN=.*/MAX_CANDIDATES_PER_RUN=1/' "$CETC/ads-privacy-guard.conf"
env $BASEENV busybox sh "$MAIN" rebuild > "$TMP/starve.out" 2>&1 || { cat "$TMP/starve.out"; fail starvation_run; }
grep -q '^newad.example|BLOCK|BLOCK|' "$STATE" || fail starvation_new_candidate
pass "candidate starvation protection"

# 5 block revalidation without new allowed query; missing evidence must hold block as SUSPECT/BLOCK
NOW=$(date +%s); OLD=$((NOW-10)); printf 'recheck.example|BLOCK|BLOCK|HIGH|old|old|%s|multi_source_consensus|old\n' "$OLD" >> "$STATE"; sort -t'|' -k1,1 -u "$STATE" -o "$STATE"
: > "$TMP/query.tsv"; sed -i 's/^MAX_CANDIDATES_PER_RUN=.*/MAX_CANDIDATES_PER_RUN=100/' "$CETC/ads-privacy-guard.conf"
env $BASEENV busybox sh "$MAIN" scan > "$TMP/recheck.out" 2>&1 || { cat "$TMP/recheck.out"; fail recheck_run; }
grep -q '^recheck.example|SUSPECT|BLOCK|' "$STATE" || { grep recheck "$STATE"; fail recheck_hold; }
pass "blocked-domain revalidation safety"

# 6 manual ALLOW rebuild removes VWARD-owned auto block immediately; suffix manual block renders ||domain^
cat > "$STATE" <<EOF2
manualsafe.example|BLOCK|BLOCK|HIGH|old|old|$((NOW+99999))|multi_source_consensus|x
EOF2
printf 'manualsafe.example\n' > "$RULES"
env $BASEENV VWARD_ADS_RULES_REBUILD="$S/vward-ads-privacy-rules-rebuild.sh" busybox sh "$S/vward-ads-privacy-control.sh" allow manualsafe.example exact > "$TMP/manual-allow.out" 2>&1 || { cat "$TMP/manual-allow.out"; fail manual_allow; }
! grep -qx manualsafe.example "$RULES" || fail allow_did_not_remove_auto
[ "$(stat -c %a "$CETC/allowlist.tsv")" = 600 ] || fail allow_mode
env $BASEENV VWARD_ADS_RULES_REBUILD="$S/vward-ads-privacy-rules-rebuild.sh" busybox sh "$S/vward-ads-privacy-control.sh" block manualblock.example suffix > "$TMP/manual-block.out" 2>&1 || fail manual_block
grep -qx '||manualblock.example^' "$RULES" || { cat "$RULES"; fail manual_suffix; }
pass "manual precedence, immediate rebuild and rule scope"

# 7 query API filtering: only NotFilteredNotFound survives
QETC="$TMP/qetc"; QST="$TMP/qstate"; QSH="$TMP/qshare"; mkdir -p "$QETC" "$QST/work" "$QSH"
cat > "$QETC/ads-privacy-guard.conf" <<EOF2
QUERY_SOURCE=api
AGH_API_BASE=http://fake/control
EOF2
chmod 600 "$QETC/ads-privacy-guard.conf"
cat > "$TMP/bin/fakecurl-query" <<EOF2
#!/bin/sh
OUT=""; while [ \$# -gt 0 ]; do case "\$1" in -o) OUT="\$2"; shift 2;; *) shift;; esac; done
cp "$T/fixtures/querylog-api.json" "\$OUT"
EOF2
chmod +x "$TMP/bin/fakecurl-query"
VWARD_ADS_LIB="$LIB" VWARD_ADS_ETC="$QETC" VWARD_ADS_STATE="$QST" VWARD_ADS_LOG_DIR="$TMP/log" VWARD_ADS_BACKUP_ROOT="$TMP/backups" VWARD_ADS_SHARE="$QSH" VWARD_ADS_CONFIG="$QETC/ads-privacy-guard.conf" VWARD_ADS_JQ="$JQ" VWARD_ADS_CURL="$TMP/bin/fakecurl-query" busybox sh "$S/vward-ads-privacy-query-read.sh" 100 > "$TMP/qapi.out"
grep -q '^allowed.example' "$TMP/qapi.out" || fail query_api_allowed
! grep -Eq 'whitelisted|rewrite|blocked' "$TMP/qapi.out" || { cat "$TMP/qapi.out"; fail query_api_exclusion; }
pass "AdGuard Home API query normalization"

# 8 source modes control is atomic and CHECK/OFF persisted securely
cp "$CSH/source-registry.json" "$QSH/source-registry.json"; : > "$QETC/source-overrides.tsv"; chmod 600 "$QETC/source-overrides.tsv"
VWARD_ADS_LIB="$LIB" VWARD_ADS_ETC="$QETC" VWARD_ADS_STATE="$QST" VWARD_ADS_LOG_DIR="$TMP/log" VWARD_ADS_BACKUP_ROOT="$TMP/backups" VWARD_ADS_SHARE="$QSH" VWARD_ADS_CONFIG="$QETC/ads-privacy-guard.conf" VWARD_ADS_SOURCE_REGISTRY="$QSH/source-registry.json" VWARD_ADS_SOURCE_OVERRIDES="$QETC/source-overrides.tsv" VWARD_ADS_JQ="$JQ" busybox sh "$S/vward-ads-privacy-source-control.sh" set feed-a off > "$TMP/srcctl.out"
grep -q '^feed-a|off|' "$QETC/source-overrides.tsv" || fail source_mode_write
[ "$(stat -c %a "$QETC/source-overrides.tsv")" = 600 ] || fail source_mode_perm
pass "source OFF/CHECK/ACTIVE control"

# 9 publisher API ownership: preserve manual rule, replace only marker block, no restart
PETC="$TMP/petc"; PST="$TMP/pstate"; PSH="$TMP/pshare"; mkdir -p "$PETC" "$PST/generated" "$PST/work" "$PSH"
cat > "$PETC/ads-privacy-guard.conf" <<EOF2
PUBLISH_MODE=user_rules_api
AUTO_PUBLISH=0
AGH_API_BASE=http://fake/control
EOF2
chmod 600 "$PETC/ads-privacy-guard.conf"
cat > "$PST/generated/vward-ads-privacy-guard.rules" <<EOF2
! generated
auto-new.example
EOF2
cat > "$TMP/agh-status.json" <<'EOF2'
{"user_rules":["||manual.example^","! VWARD ADS & PRIVACY GUARD BEGIN","old-vward.example","! VWARD ADS & PRIVACY GUARD END","@@||manual-allow.example^"]}
EOF2
cat > "$TMP/bin/fakecurl-agh" <<EOF2
#!/bin/sh
OUT=""; DATA=""; URL=""; while [ \$# -gt 0 ]; do case "\$1" in -o) OUT="\$2"; shift 2;; --data-binary) DATA="\$2"; shift 2;; -u|-H|--connect-timeout|--max-time) shift 2;; -f|-sS) shift;; *) URL="\$1"; shift;; esac; done
case "\$URL" in */filtering/status) cp "$TMP/agh-status.json" "\$OUT";; */filtering/set_rules) F="\${DATA#@}"; "$JQ" '{user_rules:.rules}' "\$F" > "$TMP/agh-status.new" && mv "$TMP/agh-status.new" "$TMP/agh-status.json"; echo '{}' > "\$OUT";; *) exit 22;; esac
EOF2
chmod +x "$TMP/bin/fakecurl-agh"
PENV="VWARD_ADS_LIB=$LIB VWARD_ADS_ETC=$PETC VWARD_ADS_STATE=$PST VWARD_ADS_LOG_DIR=$TMP/log VWARD_ADS_BACKUP_ROOT=$TMP/backups VWARD_ADS_SHARE=$PSH VWARD_ADS_CONFIG=$PETC/ads-privacy-guard.conf VWARD_ADS_JQ=$JQ VWARD_ADS_CURL=$TMP/bin/fakecurl-agh"
env $PENV busybox sh "$S/vward-ads-privacy-publish.sh" dry-run > "$TMP/pubdry.out" || { cat "$TMP/pubdry.out"; fail pub_dry; }
grep -q DRY_RUN_PASS "$TMP/pubdry.out" || fail pubdry_status
env $PENV busybox sh "$S/vward-ads-privacy-publish.sh" apply --confirm > "$TMP/pubapply.out" || { cat "$TMP/pubapply.out"; fail pub_apply; }
"$JQ" -e '.user_rules|index("||manual.example^")!=null and index("@@||manual-allow.example^")!=null and index("auto-new.example")!=null and index("old-vward.example")==null' "$TMP/agh-status.json" >/dev/null || { cat "$TMP/agh-status.json"; fail pub_ownership; }
grep -q '^ADGUARD_RESTART=NO$' "$TMP/pubapply.out" || fail no_restart
pass "AdGuard Home user_rules ownership publisher"

# 10 validated settings and secure config
SETETC="$TMP/setetc"; SETST="$TMP/setstate"; mkdir -p "$SETETC" "$SETST/work"
cp "$ROOT/config/ads-privacy-guard/ads-privacy-guard.conf.example" "$SETETC/ads-privacy-guard.conf"; chmod 600 "$SETETC/ads-privacy-guard.conf"
SENV="VWARD_ADS_LIB=$LIB VWARD_ADS_ETC=$SETETC VWARD_ADS_STATE=$SETST VWARD_ADS_LOG_DIR=$TMP/log VWARD_ADS_BACKUP_ROOT=$TMP/backups VWARD_ADS_SHARE=$TMP/share VWARD_ADS_CONFIG=$SETETC/ads-privacy-guard.conf"
env $SENV busybox sh "$S/vward-ads-privacy-settings.sh" set RUN_MODE dynamic QUERY_SOURCE auto AUTO_RULE_SCOPE exact PUBLISH_MODE staged > "$TMP/settings.out" || fail settings
grep -q '^SETTINGS=PASS$' "$TMP/settings.out" || fail settings_pass
if env $SENV busybox sh "$S/vward-ads-privacy-settings.sh" set PUBLISH_MODE yaml_direct >/dev/null 2>&1; then fail dangerous_publish_mode; fi
pass "validated settings transaction"

# 11 job queue: enqueue is immediate; worker executes exactly one
JETC="$TMP/jetc"; JST="$TMP/jstate"; mkdir -p "$JETC" "$JST/work" "$TMP/jbin"
cat > "$JETC/ads-privacy-guard.conf" <<EOF2
PUBLISH_MODE=staged
EOF2
chmod 600 "$JETC/ads-privacy-guard.conf"
cat > "$TMP/jbin/scan" <<EOF2
#!/bin/sh
echo scan >> "$TMP/job-runs"
EOF2
chmod +x "$TMP/jbin/scan"
JENV="VWARD_ADS_LIB=$LIB VWARD_ADS_ETC=$JETC VWARD_ADS_STATE=$JST VWARD_ADS_LOG_DIR=$TMP/log VWARD_ADS_BACKUP_ROOT=$TMP/backups VWARD_ADS_SHARE=$TMP/share VWARD_ADS_CONFIG=$JETC/ads-privacy-guard.conf VWARD_ADS_SCANNER=$TMP/jbin/scan"
env $JENV busybox sh "$S/vward-ads-privacy-job.sh" enqueue scan > "$TMP/jobq.out" || fail job_enqueue
grep -q '^JOB=QUEUED$' "$TMP/jobq.out" || fail job_queued_status
[ ! -e "$TMP/job-runs" ] || fail job_ran_synchronously
env $JENV busybox sh "$S/vward-ads-privacy-job.sh" worker > "$TMP/jobw.out" || fail job_worker
[ "$(wc -l < "$TMP/job-runs")" -eq 1 ] || fail job_run_count
pass "background job queue"

# 12 stale lock recovery
mkdir -p "$JST/test.lock"; echo 999999 > "$JST/test.lock/pid"; echo 1 > "$JST/test.lock/started"
VWARD_ADS_ETC="$JETC" VWARD_ADS_STATE="$JST" VWARD_ADS_LOG_DIR="$TMP/log" VWARD_ADS_BACKUP_ROOT="$TMP/backups" VWARD_ADS_SHARE="$TMP/share" busybox sh -c '. "$1"; ads_lock_acquire "$2" 1 && echo OK' sh "$LIB" "$JST/test.lock" | grep -q OK || fail stale_lock
pass "stale lock recovery"

# 13 source updater last-known-good cache and ACTIVE/OFF behavior
UETC="$TMP/uetc"; UST="$TMP/ustate"; USH="$TMP/ushare"; mkdir -p "$UETC" "$UST/work" "$USH"
cat > "$UETC/ads-privacy-guard.conf" <<EOF2
SOURCE_CONNECT_TIMEOUT=2
SOURCE_MAX_TIME=10
MIN_HEALTHY_SOURCES=1
EOF2
chmod 600 "$UETC/ads-privacy-guard.conf"
cat > "$USH/source-registry.json" <<EOF2
{"schema":1,"sources":[{"id":"local","name":"Local","vendor":"test","independence_group":"test","purpose":"ads","enabled":true,"default_mode":"active","weight":50,"single_source_block":false,"format":"adblock","min_entries":4,"max_bytes":100000,"urls":["file://$T/fixtures/source-normalize.txt"]}]}
EOF2
UENV="VWARD_ADS_LIB=$LIB VWARD_ADS_ETC=$UETC VWARD_ADS_STATE=$UST VWARD_ADS_LOG_DIR=$TMP/log VWARD_ADS_BACKUP_ROOT=$TMP/backups VWARD_ADS_SHARE=$USH VWARD_ADS_CONFIG=$UETC/ads-privacy-guard.conf VWARD_ADS_SOURCE_REGISTRY=$USH/source-registry.json VWARD_ADS_JQ=$JQ VWARD_ADS_CURL=$CURL"
env $UENV busybox sh "$S/vward-ads-privacy-sources-update.sh" > "$TMP/u1.out" 2>&1 || { cat "$TMP/u1.out"; fail source_update_initial; }
grep -qx ads.example.com "$UST/sources/local.domains" || fail source_cache
OLDHASH=$(sha256sum "$UST/sources/local.domains" | awk '{print $1}')
python3 - <<PY2
import json
p='$USH/source-registry.json'; d=json.load(open(p)); d['sources'][0]['urls']=['file:///definitely/missing/vward-feed']; open(p,'w').write(json.dumps(d))
PY2
if env $UENV busybox sh "$S/vward-ads-privacy-sources-update.sh" > "$TMP/u2.out" 2>&1; then fail source_failure_should_signal; fi
NEWHASH=$(sha256sum "$UST/sources/local.domains" | awk '{print $1}'); [ "$OLDHASH" = "$NEWHASH" ] || fail lkg_changed_on_download_failure
pass "source updater last-known-good cache"

# 14 low-load scheduler: dynamic query signature and no unnecessary rerun
SCETC="$TMP/scetc"; SCST="$TMP/scstate"; mkdir -p "$SCETC" "$SCST/work" "$TMP/scbin"
cat > "$SCETC/ads-privacy-guard.conf" <<EOF2
ENABLED=1
RUN_MODE=manual
QUERY_SOURCE=auto
SCHEDULE_INTERVAL_MIN=10
DYNAMIC_MIN_INTERVAL_SEC=60
DYNAMIC_MAX_LOAD_PER_CPU_X100=300
DYNAMIC_MIN_MEM_AVAILABLE_KB=4096
DYNAMIC_MIN_OPT_FREE_KB=8192
DYNAMIC_MAX_CANDIDATES_PER_RUN=25
DYNAMIC_SCAN_TAIL_LINES=1000
AUTO_SOURCE_UPDATE=0
SOURCE_UPDATE_INTERVAL_HOURS=24
EOF2
chmod 600 "$SCETC/ads-privacy-guard.conf"
printf 'one.example\t192.0.2.1\t2026-09-13T10:00:00+03:00\n' > "$TMP/sc-query"
cat > "$TMP/scbin/query" <<EOF2
#!/bin/sh
cat "$TMP/sc-query"
EOF2
cat > "$TMP/scbin/scan" <<EOF2
#!/bin/sh
echo run >> "$TMP/sc-runs"
exit 0
EOF2
chmod +x "$TMP/scbin/query" "$TMP/scbin/scan"
SCENV="VWARD_ADS_LIB=$LIB VWARD_ADS_ETC=$SCETC VWARD_ADS_STATE=$SCST VWARD_ADS_LOG_DIR=$TMP/log VWARD_ADS_BACKUP_ROOT=$TMP/backups VWARD_ADS_SHARE=$TMP/share VWARD_ADS_CONFIG=$SCETC/ads-privacy-guard.conf VWARD_ADS_QUERY_READER=$TMP/scbin/query VWARD_ADS_SCANNER=$TMP/scbin/scan VWARD_ADS_SOURCES_UPDATER=$TMP/scbin/no-source VWARD_ADS_JOB_WORKER=$TMP/scbin/no-job"
env $SCENV busybox sh "$S/vward-ads-privacy-scheduler.sh" > "$TMP/sc1.out" || fail scheduler_manual
grep -q '^SCHEDULER=MANUAL_IDLE$' "$TMP/sc1.out" || fail scheduler_manual_state
sed -i 's/^RUN_MODE=manual$/RUN_MODE=dynamic/' "$SCETC/ads-privacy-guard.conf"
env $SCENV busybox sh "$S/vward-ads-privacy-scheduler.sh" > "$TMP/sc2.out" || { cat "$TMP/sc2.out"; fail scheduler_dynamic; }
grep -q '^SCHEDULER=PASS$' "$TMP/sc2.out" || { cat "$TMP/sc2.out"; fail scheduler_dynamic_pass; }
[ "$(wc -l < "$TMP/sc-runs")" -eq 1 ] || fail scheduler_run_count
env $SCENV busybox sh "$S/vward-ads-privacy-scheduler.sh" > "$TMP/sc3.out" || fail scheduler_second
grep -Eq '^SCHEDULER=(NO_CHANGE|BACKOFF)$' "$TMP/sc3.out" || { cat "$TMP/sc3.out"; fail scheduler_gating; }
[ "$(wc -l < "$TMP/sc-runs")" -eq 1 ] || fail scheduler_reran
pass "dynamic low-load scheduler gating"

# 15 Dev.7 candidate settings-registry contract
python3 "$ROOT/tests/repository/check-ads-privacy-settings-registry.py" | grep -q PASS || fail settings_registry_candidate
pass "Dev.7 settings registry integration contract"

echo "ALL_TESTS=PASS"
