#!/bin/sh
# Panel data for DNS / VPN / Components: one read-only report. Defines functions only.
#   vward_components_status   ->  TSV: COMPONENT SOURCE STATE VERSION LABEL
# STATE: not-installed | installed-off | enabled-not-running | running-unverified | unknown
# LABEL is what the VWARD Panel shows. "Работает" is never produced here: a running process is
# only "Запущен, не проверен" until a health probe (not part of this report) proves it works.
# Also: dns-mode, and the owner's Entware update permissions (all off by default).
# Requires vward-entware-pkg.sh and vward-dns-mode.sh to be loaded. Nothing is started.

vcs_label() {
    case $1 in
        not-installed) echo 'Не установлен' ;;
        installed-off) echo 'Установлен, выключен' ;;
        enabled-not-running) echo 'Включён, не запущен' ;;
        running-unverified) echo 'Запущен, не проверен' ;;
        *) echo 'Состояние неизвестно' ;;
    esac
}

vward_components_status() (
    command -v vward_entware_status >/dev/null 2>&1 && command -v vward_dns_mode_get >/dev/null 2>&1 || return 2
    R=${VWARD_ROOT_PREFIX:-}
    for p in dnsmasq-full sing-box-go; do
        line=$(vward_entware_status "$p" 2>/dev/null) || line=
        inst=$(printf '%s' "$line" | cut -f2); ver=$(printf '%s' "$line" | cut -f3); svc=$(printf '%s' "$line" | cut -f5)
        case $inst:$svc in
            absent:*) st=not-installed ver=- ;;
            installed:off) st=installed-off ;;
            installed:enabled) st=enabled-not-running ;;
            installed:running) st=running-unverified ;;
            *) st=unknown ver=- ;;
        esac
        printf '%s\tentware\t%s\t%s\t%s\n' "$p" "$st" "${ver:--}" "$(vcs_label "$st")"
    done
    # Existing engines: present or not; their own agents report health elsewhere.
    for e in "xray|$R/opt/share/vward/vless-engine/xray" "amneziawg|$R/opt/share/vward/awg-engine/vward-awg"; do
        n=${e%%|*}; b=${e#*|}
        if [ -x "$b" ]; then st=present; lab='Установлен'; else st=not-installed; lab=$(vcs_label not-installed); fi
        printf '%s\tvward-engine\t%s\t-\t%s\n' "$n" "$st" "$lab"
    done
    m=$(vward_dns_mode_get 2>/dev/null | cut -f1)
    case $m in agh) lab='AdGuard Home' ;; dnsmasq) lab='dnsmasq' ;; native) lab='DNS Keenetic' ;; *) m=unknown lab='Режим неизвестен' ;; esac
    printf 'dns-mode\tvward\t%s\t-\t%s\n' "$m" "$lab"
    for a in check download apply; do
        if vward_entware_allowed "$a" >/dev/null 2>&1; then st=on; else st=off; fi
        printf 'entware-auto-%s\tvward\t%s\t-\t%s\n' "$a" "$st" "$([ "$st" = on ] && echo 'Разрешено' || echo 'Выключено')"
    done
)
