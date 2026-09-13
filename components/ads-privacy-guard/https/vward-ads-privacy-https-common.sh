#!/bin/sh

# Shared helpers for the optional VWARD HTTPS Content Guard subcomponent.
# This layer is intentionally isolated from the DNS classifier. It never changes
# firewall/NAT rules and uses an explicit proxy + PAC model only.

ADS_HTTPS_ETC="${ADS_HTTPS_ETC:-$ADS_ETC/https}"
ADS_HTTPS_STATE="${ADS_HTTPS_STATE:-$ADS_STATE/https}"
ADS_HTTPS_CONFIG="${ADS_HTTPS_CONFIG:-$ADS_HTTPS_ETC/https-content-guard.conf}"
ADS_HTTPS_CA_DIR="${ADS_HTTPS_CA_DIR:-$ADS_HTTPS_ETC/ca}"
ADS_HTTPS_CA_CERT="${ADS_HTTPS_CA_CERT:-$ADS_HTTPS_CA_DIR/vward-https-root-ca.crt}"
ADS_HTTPS_CA_KEY="${ADS_HTTPS_CA_KEY:-$ADS_HTTPS_CA_DIR/vward-https-root-ca.key}"
ADS_HTTPS_LEAF_KEY="${ADS_HTTPS_LEAF_KEY:-$ADS_HTTPS_CA_DIR/vward-https-leaf.key}"
ADS_HTTPS_INTERCEPT_FILE="${ADS_HTTPS_INTERCEPT_FILE:-$ADS_HTTPS_ETC/intercept.tsv}"
ADS_HTTPS_BYPASS_FILE="${ADS_HTTPS_BYPASS_FILE:-$ADS_HTTPS_ETC/bypass.tsv}"
ADS_HTTPS_RULES_FILE="${ADS_HTTPS_RULES_FILE:-$ADS_HTTPS_ETC/request-rules.tsv}"
ADS_HTTPS_RUNTIME_DIR="${ADS_HTTPS_RUNTIME_DIR:-$ADS_HTTPS_STATE/runtime}"
ADS_HTTPS_PROVIDER_CONFIG="${ADS_HTTPS_PROVIDER_CONFIG:-$ADS_HTTPS_RUNTIME_DIR/3proxy.cfg}"
ADS_HTTPS_PAC_FILE="${ADS_HTTPS_PAC_FILE:-$ADS_HTTPS_RUNTIME_DIR/vward-https-content-guard.pac}"
ADS_HTTPS_PID_FILE="${ADS_HTTPS_PID_FILE:-$ADS_HTTPS_RUNTIME_DIR/3proxy.pid}"
ADS_HTTPS_STATUS_FILE="${ADS_HTTPS_STATUS_FILE:-/tmp/vward-https-content-guard.status}"
ADS_HTTPS_LOG="${ADS_HTTPS_LOG:-$ADS_LOG_DIR/vward-https-content-guard.log}"
ADS_HTTPS_PROVIDER_LIB="${ADS_HTTPS_PROVIDER_LIB:-$ADS_SHARE/https/providers/3proxy.sh}"

https_mkdirs()
{
    mkdir -p "$ADS_HTTPS_ETC" "$ADS_HTTPS_CA_DIR" "$ADS_HTTPS_STATE" \
        "$ADS_HTTPS_RUNTIME_DIR" "$ADS_HTTPS_STATE/cert-cache" || return 1
    chmod 0700 "$ADS_HTTPS_ETC" "$ADS_HTTPS_CA_DIR" "$ADS_HTTPS_STATE" \
        "$ADS_HTTPS_RUNTIME_DIR" "$ADS_HTTPS_STATE/cert-cache" 2>/dev/null || true
}

https_load_config()
{
    [ -r "$ADS_HTTPS_CONFIG" ] || ads_die "HTTPS config not readable: $ADS_HTTPS_CONFIG"
    if [ "${ADS_REQUIRE_SECURE_CONFIG:-1}" = 1 ] && ! ads_secure_file_ok "$ADS_HTTPS_CONFIG"; then
        ads_die "HTTPS config must be root-owned and mode 0600 or 0400: $ADS_HTTPS_CONFIG"
    fi
    . "$ADS_HTTPS_CONFIG"
}

https_bool_value()
{
    case "${1:-}" in 1|yes|YES|true|TRUE|on|ON) echo 1 ;; *) echo 0 ;; esac
}

https_valid_ip_or_host()
{
    # Bind/advertise host: conservative host/IP token only. No shell/config metacharacters.
    case "${1:-}" in ''|*[!A-Za-z0-9_.:-]*) return 1 ;; *) return 0 ;; esac
}

https_valid_client_acl()
{
    # 3proxy client ACL list. Permit only IPv4/IPv6/CIDR punctuation and commas.
    case "${1:-}" in ''|*[!0-9A-Fa-f:.,/-]*) return 1 ;; *) return 0 ;; esac
}

https_active_tsv_rows()
{
    [ -r "$1" ] || return 0
    awk -F '\t' 'NF && $1 !~ /^[[:space:]]*#/ && tolower($1) ~ /^(1|on|yes|true)$/ {print}' "$1"
}

https_count_active()
{
    https_active_tsv_rows "$1" | awk 'END{print NR+0}'
}

https_scope_target()
{
    https_st_domain="$1"; https_st_scope="$2"
    ads_valid_domain "$https_st_domain" || return 1
    case "$https_st_scope" in
        exact) printf '%s\n' "$https_st_domain" ;;
        suffix) printf '%s,*.%s\n' "$https_st_domain" "$https_st_domain" ;;
        *) return 1 ;;
    esac
}

https_escape_regex_literal()
{
    # Escape a literal path for PCRE without accepting arbitrary regexp input.
    awk 'BEGIN{ORS=""}
    {
      for(i=1;i<=length($0);i++){
        c=substr($0,i,1)
        if(index("\\.^$*+?()[]{}|",c)>0) printf "\\\\%s",c; else printf "%s",c
      }
    }'
}

https_validate_path_value()
{
    https_pv="$1"
    [ "${#https_pv}" -ge 1 ] && [ "${#https_pv}" -le 512 ] || return 1
    case "$https_pv" in
        /*) ;;
        *) return 1 ;;
    esac
    # Deliberately exclude quotes, backslashes, whitespace and control characters.
    printf '%s\n' "$https_pv" | grep -Eq '^/[A-Za-z0-9_./~%?&=:+,@!#-]{0,511}$' || return 1
    return 0
}

https_compile_request_rules()
{
    https_cr_in="$1"; https_cr_out="$2"
    : > "$https_cr_out" || return 1
    [ -r "$https_cr_in" ] || return 0
    while IFS="$(printf '\t')" read -r enabled rid domain scope kind value action note; do
        case "$enabled" in ''|'#'*) continue ;; esac
        case "$(printf '%s' "$enabled" | tr '[:upper:]' '[:lower:]')" in 1|on|yes|true) ;; *) continue ;; esac
        domain="$(ads_normalize_domain "$domain")"
        ads_valid_domain "$domain" || { echo "invalid rule domain: $rid" >&2; return 1; }
        target="$(https_scope_target "$domain" "$scope")" || { echo "invalid rule scope: $rid" >&2; return 1; }
        case "$action" in block) ;; *) echo "invalid rule action: $rid" >&2; return 1 ;; esac
        case "$kind" in path_prefix|path_exact) ;; *) echo "invalid rule kind: $rid" >&2; return 1 ;; esac
        https_validate_path_value "$value" || { echo "invalid rule path: $rid" >&2; return 1; }
        escaped="$(printf '%s' "$value" | https_escape_regex_literal)"
        case "$kind" in
            path_prefix) regex="^[A-Z]+[[:space:]]+(https?://[^/]+)?${escaped}" ;;
            path_exact) regex="^[A-Z]+[[:space:]]+(https?://[^/]+)?${escaped}([?#][^[:space:]]*)?[[:space:]]+HTTP/" ;;
        esac
        # ACE: user source target targetport operation weekdays timeperiods.
        # Do not narrow operation to HTTP: after CONNECT+MITM the inner request
        # operation can vary by 3proxy build. Target hostname still scopes the rule.
        printf 'pcre request deny "%s" * * %s * * * *\n' "$regex" "$target" >> "$https_cr_out" || return 1
    done < "$https_cr_in"
}

https_render_pac()
{
    https_rp_out="$1"
    https_rp_host="${HTTPS_PROXY_ADVERTISE_HOST:-${HTTPS_PROXY_BIND:-}}"
    https_rp_port="$(ads_num "${HTTPS_PROXY_PORT:-3128}" 3128)"
    https_valid_ip_or_host "$https_rp_host" || { echo "invalid HTTPS_PROXY_ADVERTISE_HOST" >&2; return 1; }
    case "$https_rp_host" in 0.0.0.0|::|127.0.0.1|::1) echo "advertise host must be a client-reachable LAN address/host" >&2; return 1 ;; esac
    {
        echo 'function FindProxyForURL(url, host) {'
        echo '  host = host.toLowerCase();'
        echo '  if (isPlainHostName(host) || dnsDomainIs(host, ".local") || dnsDomainIs(host, ".lan") || dnsDomainIs(host, ".home.arpa")) return "DIRECT";'
        [ -r "$ADS_HTTPS_BYPASS_FILE" ] && while IFS="$(printf '\t')" read -r enabled domain scope note; do
            case "$(printf '%s' "$enabled" | tr '[:upper:]' '[:lower:]')" in 1|on|yes|true) ;; *) continue ;; esac
            domain="$(ads_normalize_domain "$domain")"; ads_valid_domain "$domain" || return 1
            case "$scope" in
                exact) printf '  if (host === "%s") return "DIRECT";\n' "$domain" ;;
                suffix) printf '  if (host === "%s" || dnsDomainIs(host, ".%s")) return "DIRECT";\n' "$domain" "$domain" ;;
                *) return 1 ;;
            esac
        done < "$ADS_HTTPS_BYPASS_FILE"
        [ -r "$ADS_HTTPS_INTERCEPT_FILE" ] && while IFS="$(printf '\t')" read -r enabled domain scope note; do
            case "$(printf '%s' "$enabled" | tr '[:upper:]' '[:lower:]')" in 1|on|yes|true) ;; *) continue ;; esac
            domain="$(ads_normalize_domain "$domain")"; ads_valid_domain "$domain" || return 1
            case "$scope" in
                exact) printf '  if (host === "%s") return "PROXY %s:%s";\n' "$domain" "$https_rp_host" "$https_rp_port" ;;
                suffix) printf '  if (host === "%s" || dnsDomainIs(host, ".%s")) return "PROXY %s:%s";\n' "$domain" "$domain" "$https_rp_host" "$https_rp_port" ;;
                *) return 1 ;;
            esac
        done < "$ADS_HTTPS_INTERCEPT_FILE"
        echo '  return "DIRECT";'
        echo '}'
    } > "$https_rp_out" || return 1
    chmod 0644 "$https_rp_out" 2>/dev/null || true
}

https_ca_ready()
{
    [ -r "$ADS_HTTPS_CA_CERT" ] && [ -r "$ADS_HTTPS_CA_KEY" ] && [ -r "$ADS_HTTPS_LEAF_KEY" ] || return 1
    [ -x "${HTTPS_OPENSSL_BIN:-}" ] || command -v openssl >/dev/null 2>&1 || return 1
    openssl_bin="${HTTPS_OPENSSL_BIN:-$(command -v openssl)}"
    "$openssl_bin" x509 -in "$ADS_HTTPS_CA_CERT" -noout -checkend 86400 >/dev/null 2>&1 || return 1
    return 0
}

https_write_status()
{
    https_ws_tmp="${ADS_HTTPS_STATUS_FILE}.new.$$"
    {
        echo "phase=${1:-UNKNOWN}"
        echo "reason=${2:-}"
        echo "updated=$(ads_now)"
    } > "$https_ws_tmp" 2>/dev/null || return 1
    mv "$https_ws_tmp" "$ADS_HTTPS_STATUS_FILE" 2>/dev/null || return 1
}
