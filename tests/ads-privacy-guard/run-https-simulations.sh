#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
TMP="${TMPDIR:-/tmp}/vward-https-test.$$"
trap 'if [ -r "$TMP/state/https/runtime/3proxy.pid" ]; then kill "$(cat "$TMP/state/https/runtime/3proxy.pid" 2>/dev/null)" 2>/dev/null || true; fi; rm -rf "$TMP"' EXIT INT TERM
mkdir -p "$TMP/etc/https/ca" "$TMP/state/https/runtime" "$TMP/state/https/cert-cache" "$TMP/log" "$TMP/share/https/providers"
mkdir -p "$TMP/proc"
cp "$ROOT/components/ads-privacy-guard/https/providers/3proxy.sh" "$TMP/share/https/providers/3proxy.sh"

OPENSSL_BIN="$(command -v openssl)"
cat > "$TMP/fake-3proxy" <<'EOS'
#!/bin/sh
cfg="$1"
pidfile="$(awk '$1=="pidfile"{print $2;exit}' "$cfg")"
"$(dirname "$0")/fake-3proxy-daemon" 300 >/dev/null 2>&1 &
pid="$!"; echo "$pid" > "$pidfile"
mkdir -p "$FAKE_PROC_ROOT/$pid"; printf 'fake-3proxy-daemon\000300\000' > "$FAKE_PROC_ROOT/$pid/cmdline"
exit 0
EOS
chmod 0755 "$TMP/fake-3proxy"
cp "$(command -v sleep)" "$TMP/fake-3proxy-daemon"; chmod 0755 "$TMP/fake-3proxy-daemon"
: > "$TMP/SSLPlugin.ld.so"
: > "$TMP/PCREPlugin.ld.so"
: > "$TMP/upstream-ca.crt"

cat > "$TMP/etc/https/https-content-guard.conf" <<EOF2
HTTPS_GUARD_ENABLED=1
HTTPS_GUARD_PROVIDER=3proxy
HTTPS_GUARD_MODE=explicit_proxy
HTTPS_PROXY_BIND=127.0.0.1
HTTPS_PROXY_ADVERTISE_HOST=192.0.2.1
HTTPS_PROXY_PORT=3128
HTTPS_ALLOWED_CLIENTS=127.0.0.1
HTTPS_MAX_CONNECTIONS=16
HTTPS_CA_DAYS=365
HTTPS_DEBUG_LOG=0
HTTPS_3PROXY_BIN=$TMP/fake-3proxy
HTTPS_3PROXY_PROCESS_NAME=fake-3proxy-daemon
HTTPS_SSL_PLUGIN=$TMP/SSLPlugin.ld.so
HTTPS_PCRE_PLUGIN=$TMP/PCREPlugin.ld.so
HTTPS_UPSTREAM_CA_FILE=$TMP/upstream-ca.crt
HTTPS_OPENSSL_BIN=$OPENSSL_BIN
EOF2
chmod 0600 "$TMP/etc/https/https-content-guard.conf"
printf '1\tapi.ozon.ru\texact\tOzon API test\n' > "$TMP/etc/https/intercept.tsv"
printf '1\tauth.ozon.ru\texact\tbypass test\n' > "$TMP/etc/https/bypass.tsv"
printf '1\tozon-path\tapi.ozon.ru\texact\tpath_prefix\t/api/ads\tblock\ttest rule\n' > "$TMP/etc/https/request-rules.tsv"
chmod 0600 "$TMP/etc/https/"*.tsv

export VWARD_ADS_LIB="$ROOT/components/ads-privacy-guard/lib/vward-ads-privacy-common.sh"
export VWARD_ADS_HTTPS_LIB="$ROOT/components/ads-privacy-guard/https/vward-ads-privacy-https-common.sh"
export VWARD_ADS_HTTPS_PROVIDER_LIB="$ROOT/components/ads-privacy-guard/https/providers/3proxy.sh"
export ADS_ETC="$TMP/etc"
export ADS_STATE="$TMP/state"
export ADS_SHARE="$TMP/share"
export ADS_LOG_DIR="$TMP/log"
export ADS_BACKUP_ROOT="$TMP/backups"
export ADS_CONFIG="$TMP/base.conf"
export ADS_HTTPS_ETC="$TMP/etc/https"
export ADS_HTTPS_STATE="$TMP/state/https"
export ADS_HTTPS_CONFIG="$TMP/etc/https/https-content-guard.conf"
export ADS_HTTPS_CA_DIR="$TMP/etc/https/ca"
export ADS_HTTPS_CA_CERT="$TMP/etc/https/ca/vward-https-root-ca.crt"
export ADS_HTTPS_CA_KEY="$TMP/etc/https/ca/vward-https-root-ca.key"
export ADS_HTTPS_LEAF_KEY="$TMP/etc/https/ca/vward-https-leaf.key"
export ADS_HTTPS_INTERCEPT_FILE="$TMP/etc/https/intercept.tsv"
export ADS_HTTPS_BYPASS_FILE="$TMP/etc/https/bypass.tsv"
export ADS_HTTPS_RULES_FILE="$TMP/etc/https/request-rules.tsv"
export ADS_HTTPS_RUNTIME_DIR="$TMP/state/https/runtime"
export ADS_HTTPS_PROVIDER_CONFIG="$TMP/state/https/runtime/3proxy.cfg"
export ADS_HTTPS_PAC_FILE="$TMP/state/https/runtime/vward.pac"
export ADS_HTTPS_PID_FILE="$TMP/state/https/runtime/3proxy.pid"
export ADS_HTTPS_STATUS_FILE="$TMP/status"
export ADS_HTTPS_LOG="$TMP/log/https.log"
export ADS_REQUIRE_SECURE_CONFIG=0
export HTTPS_PROC_ROOT="$TMP/proc"
export FAKE_PROC_ROOT="$TMP/proc"
: > "$TMP/base.conf"

CTL="$ROOT/components/ads-privacy-guard/scripts/vward-ads-privacy-https.sh"

"$CTL" ca-init --confirm > "$TMP/ca.out"
grep -q '^HTTPS_CA_INIT=PASS$' "$TMP/ca.out"
[ "$(stat -c '%a' "$ADS_HTTPS_CA_KEY")" = 600 ]
[ "$(stat -c '%a' "$ADS_HTTPS_LEAF_KEY")" = 600 ]
"$CTL" validate > "$TMP/validate.out"
grep -q '^HTTPS_VALIDATE=PASS$' "$TMP/validate.out"
"$CTL" render > "$TMP/render.out"
grep -q '^ssl_client_verify$' "$ADS_HTTPS_PROVIDER_CONFIG"
grep -q 'pcre request deny' "$ADS_HTTPS_PROVIDER_CONFIG"
grep -q 'api\\/ads' "$ADS_HTTPS_PROVIDER_CONFIG" || grep -q '/api/ads' "$ADS_HTTPS_PROVIDER_CONFIG"
grep -q 'host === "auth.ozon.ru".*DIRECT' "$ADS_HTTPS_PAC_FILE"
grep -q 'host === "api.ozon.ru".*PROXY 192.0.2.1:3128' "$ADS_HTTPS_PAC_FILE"
echo 'PASS: CA, provider validation, PAC and path-rule render'

cp "$ADS_HTTPS_RULES_FILE" "$TMP/rules.good"
printf '1\tbad\tapi.ozon.ru\texact\tpath_prefix\t/bad"path\tblock\tunsafe\n' > "$ADS_HTTPS_RULES_FILE"
if "$CTL" render >/dev/null 2>&1; then echo 'FAIL: unsafe path accepted' >&2; exit 1; fi
cp "$TMP/rules.good" "$ADS_HTTPS_RULES_FILE"
echo 'PASS: unsafe request-path rule rejected'

"$CTL" start --confirm > "$TMP/start.out"
grep -q '^HTTPS_START=PASS$' "$TMP/start.out"
"$CTL" status > "$TMP/status.out"
grep -q '^RUNNING=1$' "$TMP/status.out"
"$CTL" stop > "$TMP/stop.out"
grep -q '^HTTPS_STOP=PASS$' "$TMP/stop.out"
echo 'PASS: explicit proxy lifecycle with isolated provider adapter'

sleep 300 >/dev/null 2>&1 & foreign_pid=$!; echo "$foreign_pid" > "$ADS_HTTPS_PID_FILE"; mkdir -p "$HTTPS_PROC_ROOT/$foreign_pid"; printf 'sleep\000300\000' > "$HTTPS_PROC_ROOT/$foreign_pid/cmdline"
if "$CTL" stop >/dev/null 2>&1; then echo 'FAIL: foreign PID accepted' >&2; kill "$foreign_pid" 2>/dev/null || true; exit 1; fi
kill -0 "$foreign_pid" 2>/dev/null || { echo 'FAIL: foreign PID was killed' >&2; exit 1; }
kill "$foreign_pid" 2>/dev/null || true; rm -f "$ADS_HTTPS_PID_FILE"
echo 'PASS: stale or foreign PID is never terminated'

sed 's/^HTTPS_GUARD_ENABLED=1$/HTTPS_GUARD_ENABLED=0/' "$ADS_HTTPS_CONFIG" > "$TMP/disabled" && mv "$TMP/disabled" "$ADS_HTTPS_CONFIG"
chmod 0600 "$ADS_HTTPS_CONFIG"
if "$CTL" start --confirm >/dev/null 2>&1; then echo 'FAIL: disabled HTTPS guard started' >&2; exit 1; fi
echo 'PASS: disabled-by-default gate'

echo HTTPS_SIMULATIONS=PASS
