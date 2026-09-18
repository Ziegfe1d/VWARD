#!/bin/sh
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"
ads_admission_enter ads-https
trap ads_admission_leave EXIT
trap 'exit 1' HUP INT TERM
HTTPS_LIB="${VWARD_ADS_HTTPS_LIB:-/opt/share/vward/ads-privacy-guard/https/vward-ads-privacy-https-common.sh}"
[ -r "$HTTPS_LIB" ] || HTTPS_LIB="$SELF_DIR/../https/vward-ads-privacy-https-common.sh"
[ -r "$HTTPS_LIB" ] || { echo "FAIL: HTTPS common library not found" >&2; exit 1; }
. "$HTTPS_LIB"
PROVIDER="${VWARD_ADS_HTTPS_PROVIDER_LIB:-$ADS_HTTPS_PROVIDER_LIB}"
[ -r "$PROVIDER" ] || PROVIDER="$SELF_DIR/../https/providers/3proxy.sh"
[ -r "$PROVIDER" ] || { echo "FAIL: HTTPS provider not found" >&2; exit 1; }
. "$PROVIDER"

https_mkdirs || ads_die "cannot create HTTPS directories"

load_if_present()
{
    if [ -r "$ADS_HTTPS_CONFIG" ]; then https_load_config; else return 1; fi
}

ca_init()
{
    load_if_present || ads_die "HTTPS config missing"
    [ "${1:-}" = --confirm ] || ads_die "CA generation requires --confirm"
    openssl_bin="${HTTPS_OPENSSL_BIN:-$(command -v openssl 2>/dev/null || true)}"
    [ -x "$openssl_bin" ] || ads_die "openssl executable missing"
    days="$(ads_num "${HTTPS_CA_DAYS:-1825}" 1825)"; [ "$days" -ge 365 ] && [ "$days" -le 3650 ] || ads_die "HTTPS_CA_DAYS out of range"
    if [ -e "$ADS_HTTPS_CA_KEY" ] || [ -e "$ADS_HTTPS_CA_CERT" ] || [ -e "$ADS_HTTPS_LEAF_KEY" ]; then
        ads_die "CA already exists; refusing to overwrite"
    fi
    work="$ADS_HTTPS_RUNTIME_DIR/ca-init.$$"; mkdir -p "$work" || ads_die "cannot stage CA"; chmod 0700 "$work"
    trap 'rm -rf "$work"' EXIT
    trap 'exit 1' HUP INT TERM
    cat > "$work/ca.cnf" <<'EOC'
[req]
prompt = no
distinguished_name = dn
x509_extensions = v3_ca
[dn]
O = VWARD Local
CN = VWARD HTTPS Content Guard Root CA
[v3_ca]
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
EOC
    "$openssl_bin" genrsa -out "$work/ca.key" 3072 >/dev/null 2>&1 || ads_die "CA key generation failed"
    "$openssl_bin" req -x509 -new -sha256 -days "$days" -key "$work/ca.key" -out "$work/ca.crt" -config "$work/ca.cnf" -extensions v3_ca >/dev/null 2>&1 || ads_die "CA certificate generation failed"
    "$openssl_bin" genrsa -out "$work/leaf.key" 2048 >/dev/null 2>&1 || ads_die "leaf key generation failed"
    "$openssl_bin" verify -x509_strict -CAfile "$work/ca.crt" "$work/ca.crt" >/dev/null 2>&1 || ads_die "generated CA verification failed"
    cp "$work/ca.key" "$ADS_HTTPS_CA_KEY" || ads_die "cannot install CA key"
    cp "$work/ca.crt" "$ADS_HTTPS_CA_CERT" || ads_die "cannot install CA certificate"
    cp "$work/leaf.key" "$ADS_HTTPS_LEAF_KEY" || ads_die "cannot install leaf key"
    chmod 0600 "$ADS_HTTPS_CA_KEY" "$ADS_HTTPS_LEAF_KEY" || ads_die "cannot protect HTTPS private keys"
    chmod 0644 "$ADS_HTTPS_CA_CERT" || ads_die "cannot chmod CA certificate"
    ads_log "HTTPS|CA_INIT|cert=$ADS_HTTPS_CA_CERT"
    echo "HTTPS_CA_INIT=PASS"
    echo "CA_CERT=$ADS_HTTPS_CA_CERT"
    "$openssl_bin" x509 -in "$ADS_HTTPS_CA_CERT" -noout -fingerprint -sha256 2>/dev/null | sed 's/^/CA_/'
}

render_all()
{
    load_if_present || ads_die "HTTPS config missing"
    [ "$(https_bool_value "${HTTPS_GUARD_ENABLED:-0}")" = 1 ] || ads_die "HTTPS_GUARD_ENABLED=0"
    [ "${HTTPS_GUARD_PROVIDER:-3proxy}" = 3proxy ] || ads_die "unsupported HTTPS provider"
    [ "${HTTPS_GUARD_MODE:-explicit_proxy}" = explicit_proxy ] || ads_die "only explicit_proxy mode is implemented"
    https_ca_ready || ads_die "HTTPS CA is not ready"
    https_render_pac "$ADS_HTTPS_PAC_FILE" || ads_die "PAC render failed"
    https_3proxy_render || ads_die "3proxy render failed rc=$?"
    echo "HTTPS_RENDER=PASS"
    echo "PROXY_CONFIG=$ADS_HTTPS_PROVIDER_CONFIG"
    echo "PAC_FILE=$ADS_HTTPS_PAC_FILE"
    echo "INTERCEPT_COUNT=$(https_count_active "$ADS_HTTPS_INTERCEPT_FILE")"
    echo "RULE_COUNT=$(https_count_active "$ADS_HTTPS_RULES_FILE")"
}

validate_all()
{
    load_if_present || ads_die "HTTPS config missing"
    echo "HTTPS_GUARD_ENABLED=$(https_bool_value "${HTTPS_GUARD_ENABLED:-0}")"
    echo "HTTPS_GUARD_MODE=${HTTPS_GUARD_MODE:-explicit_proxy}"
    echo "HTTPS_GUARD_PROVIDER=${HTTPS_GUARD_PROVIDER:-3proxy}"
    [ "${HTTPS_GUARD_MODE:-explicit_proxy}" = explicit_proxy ] || ads_die "transparent interception is intentionally unsupported"
    https_ca_ready || ads_die "HTTPS CA not ready"
    https_3proxy_probe; rc=$?
    case "$rc" in
      0) ;;
      11) ads_die "3proxy binary missing" ;;
      12) ads_die "SSLPlugin missing" ;;
      13) ads_die "PCREPlugin missing" ;;
      14) ads_die "upstream CA bundle missing" ;;
      *) ads_die "provider probe failed rc=$rc" ;;
    esac
    tmp="$ADS_HTTPS_RUNTIME_DIR/validate-rules.$$"; https_compile_request_rules "$ADS_HTTPS_RULES_FILE" "$tmp" || ads_die "request rule validation failed"; rm -f "$tmp"
    https_render_pac "$ADS_HTTPS_PAC_FILE" || ads_die "PAC validation failed"
    echo "HTTPS_VALIDATE=PASS"
    echo "PROVIDER_BIN=$HTTPS_3PROXY_BIN_RESOLVED"
    echo "SSL_PLUGIN=$HTTPS_SSL_PLUGIN_RESOLVED"
    echo "PCRE_PLUGIN=$HTTPS_PCRE_PLUGIN_RESOLVED"
    echo "CA_CERT=$ADS_HTTPS_CA_CERT"
    echo "INTERCEPT_COUNT=$(https_count_active "$ADS_HTTPS_INTERCEPT_FILE")"
    echo "RULE_COUNT=$(https_count_active "$ADS_HTTPS_RULES_FILE")"
}

show_status()
{
    echo "HTTPS_COMPONENT=VWARD_HTTPS_CONTENT_GUARD"
    if ! load_if_present; then echo "CONFIG=MISSING"; echo "RUNNING=0"; exit 0; fi
    echo "CONFIG=READY"
    echo "ENABLED=$(https_bool_value "${HTTPS_GUARD_ENABLED:-0}")"
    echo "MODE=${HTTPS_GUARD_MODE:-explicit_proxy}"
    echo "PROVIDER=${HTTPS_GUARD_PROVIDER:-3proxy}"
    echo "PROXY_BIND=${HTTPS_PROXY_BIND:-127.0.0.1}"
    echo "PROXY_PORT=${HTTPS_PROXY_PORT:-3128}"
    echo "PROXY_ADVERTISE_HOST=${HTTPS_PROXY_ADVERTISE_HOST:-}"
    if https_ca_ready; then
        echo "CA_READY=1"
        openssl_bin="${HTTPS_OPENSSL_BIN:-$(command -v openssl 2>/dev/null || true)}"
        [ -x "$openssl_bin" ] && "$openssl_bin" x509 -in "$ADS_HTTPS_CA_CERT" -noout -fingerprint -sha256 2>/dev/null | sed 's/^/CA_/'
    else echo "CA_READY=0"; fi
    p="$(cat "$ADS_HTTPS_PID_FILE" 2>/dev/null)"; case "$p" in ''|*[!0-9]*) echo "RUNNING=0" ;; *) if https_3proxy_pid_matches "$p"; then echo "RUNNING=1"; echo "PID=$p"; else echo "RUNNING=0"; echo "PID_STATE=STALE_OR_FOREIGN"; fi ;; esac
    if https_3proxy_probe >/dev/null 2>&1; then echo "PROVIDER_READY=1"; else echo "PROVIDER_READY=0"; fi
    echo "INTERCEPT_COUNT=$(https_count_active "$ADS_HTTPS_INTERCEPT_FILE")"
    echo "RULE_COUNT=$(https_count_active "$ADS_HTTPS_RULES_FILE")"
    echo "PAC_FILE=$ADS_HTTPS_PAC_FILE"
    [ -r "$ADS_HTTPS_STATUS_FILE" ] && sed 's/^/STATE_/' "$ADS_HTTPS_STATUS_FILE"
}

start_guard()
{
    load_if_present || ads_die "HTTPS config missing"
    [ "${1:-}" = --confirm ] || ads_die "HTTPS start requires --confirm"
    [ "$(https_bool_value "${HTTPS_GUARD_ENABLED:-0}")" = 1 ] || ads_die "HTTPS_GUARD_ENABLED=0"
    https_write_status STARTING "manual_start" || true
    render_all >/dev/null || { https_write_status FAILED "render_failed" || true; ads_die "HTTPS render failed"; }
    if https_3proxy_start; then
        https_write_status RUNNING "explicit_proxy" || true
        ads_log "HTTPS|START|mode=explicit_proxy|port=${HTTPS_PROXY_PORT:-3128}"
        echo "HTTPS_START=PASS"
        echo "PAC_FILE=$ADS_HTTPS_PAC_FILE"
        echo "CA_CERT=$ADS_HTTPS_CA_CERT"
    else
        rc=$?; https_write_status FAILED "provider_start_rc_$rc" || true; ads_die "HTTPS provider start failed rc=$rc"
    fi
}

stop_guard()
{
    load_if_present >/dev/null 2>&1 || true
    if https_3proxy_stop; then
        https_write_status STOPPED "manual_stop" || true
        ads_log "HTTPS|STOP"
        echo "HTTPS_STOP=PASS"
    else rc=$?; https_write_status FAILED "provider_stop_rc_$rc" || true; ads_die "HTTPS provider stop failed rc=$rc"; fi
}

case "${1:-status}" in
    status) show_status ;;
    ca-init) shift; ca_init "${1:-}" ;;
    ca-export) load_if_present || ads_die "HTTPS config missing"; https_ca_ready || ads_die "HTTPS CA not ready"; echo "CA_CERT=$ADS_HTTPS_CA_CERT"; openssl_bin="${HTTPS_OPENSSL_BIN:-$(command -v openssl 2>/dev/null || true)}"; "$openssl_bin" x509 -in "$ADS_HTTPS_CA_CERT" -noout -fingerprint -sha256 2>/dev/null | sed 's/^/CA_/' ;;
    validate) validate_all ;;
    render) render_all ;;
    start) shift; start_guard "${1:-}" ;;
    stop) stop_guard ;;
    restart) shift; [ "${1:-}" = --confirm ] || ads_die "HTTPS restart requires --confirm"; stop_guard >/dev/null 2>&1 || true; start_guard --confirm ;;
    pac) load_if_present || ads_die "HTTPS config missing"; https_render_pac "$ADS_HTTPS_PAC_FILE" || ads_die "PAC render failed"; echo "HTTPS_PAC=PASS"; echo "PAC_FILE=$ADS_HTTPS_PAC_FILE" ;;
    *) echo "Usage: $0 {status|ca-init --confirm|ca-export|validate|render|start --confirm|stop|restart --confirm|pac}" >&2; exit 2 ;;
esac
