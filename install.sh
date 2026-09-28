#!/bin/sh
# VWARD installer for a Keenetic router with Entware.
#
# Starting point: the router is set up, Entware runs from a USB drive, and at
# most a VPN connection is configured in Keenetic.  Nothing else is needed.
#
#   sh install.sh              check, ask, install
#   sh install.sh --check      read-only report, changes nothing
#   sh install.sh --yes        no questions (the VPN must be unambiguous)
#   sh install.sh --uninstall  remove VWARD; its settings are kept in a backup
#
# The program comes as the same signed package the updates use: the Update
# Engine checks its Ed25519 signature and SHA-256, installs it with a backup
# and takes it back if the check after installing fails.  Everything this
# script changes before that is undone when a step fails.

set -u

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

BASE_URL=${VWARD_INSTALL_BASE_URL:-https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev}
RCI=${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}
ETC=/opt/etc/vward
SHARE=/opt/share/vward
UPDATER_ROOT=$SHARE/updater
UPDATER_STATE=/opt/var/lib/vward/updater
CRONTAB_DIR=/opt/var/spool/cron/crontabs
CRON_MARK='# VWARD_SMART_UPDATER'
INSTALL_STATE=$ETC/install.state
ADAPTIVE_GROUP=AdaptiveAuto
MIN_FREE_KB=20480
LOG=/opt/var/log/vward/install.log

UPDATER_FILES='vward-update-bootstrap.sh vward-update-common-base.sh vward-update-common.sh vward-update-delta.sh vward-update-hardening.sh vward-update-health.sh vward-update-rollback.sh vward-update-watch.sh vward-update.sh'
# Entware packages by the command or file VWARD needs from them.
PACKAGES='curl:/opt/bin/curl jq:/opt/bin/jq tcpdump:/opt/sbin/tcpdump openssl-util:/opt/bin/openssl ca-bundle:/opt/etc/ssl/certs/ca-certificates.crt lighttpd:/opt/sbin/lighttpd lighttpd-mod-cgi:/opt/lib/lighttpd/mod_cgi.so lighttpd-mod-setenv:/opt/lib/lighttpd/mod_setenv.so cron:/opt/sbin/crond'

ASSUME_YES=0
WORK=
STAGE=none
CRON_BACKUP=
MADE_DEVICE_CONF=0
MADE_ADAPTIVE_GROUP=0
MADE_ADAPTIVE_ROUTE=0
TUNNEL=
TUNNEL_DEV=
LAN_CHOICE=

# ---------- output ----------

line() { printf '%s\n' "$*"; [ -z "${LOG_OK:-}" ] || printf '%s|%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG" 2>/dev/null; }
ok() { line "[ OK ] $*"; }
pass() { line "[ PASS ] $*"; }
warn() { line "[ WARNING ] $*"; }
skip() { line "[ SKIPPED ] $*"; }
step() { line ""; line "=== $* ==="; }

fail() {
    line "[ FAIL ] $*"
    undo
    line ""
    line "Установка не выполнена. Роутер оставлен как был."
    exit 1
}

# ask QUESTION: yes unless answered no.  Without a terminal (a pipe) only --yes answers.
ask() {
    [ "$ASSUME_YES" = 1 ] && return 0
    [ -r /dev/tty ] || fail "нет терминала для вопроса - запустите файлом (sh install.sh) или с --yes"
    printf '%s [Д/н] ' "$1"
    read -r a < /dev/tty || a=
    case "$a" in н|Н|n|N|нет|Нет|no|No) return 1 ;; *) return 0 ;; esac
}

# choose PROMPT N DEFAULT: a number from 1..N, asked on the terminal.
choose() {
    n=$2
    if [ "$ASSUME_YES" = 1 ]; then printf '%s\n' "$3"; return 0; fi
    [ -r /dev/tty ] || return 1
    while :; do
        printf '%s [%s]: ' "$1" "$3" > /dev/tty
        read -r a < /dev/tty || a=
        [ -n "$a" ] || a=$3
        case "$a" in *[!0-9]*|'') ;; *) [ "$a" -ge 1 ] && [ "$a" -le "$n" ] && { printf '%s\n' "$a"; return 0; } ;; esac
        printf 'Введите число от 1 до %s\n' "$n" > /dev/tty
    done
}

# ---------- downloads ----------

fetch() {
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
        --connect-timeout 15 --max-time 120 --retry 3 --max-filesize 4194304 \
        --output "$2.part" "$1" 2>/dev/null && mv "$2.part" "$2"
}

# repo_get PATH OUT: a repository file, checked against SHA256SUMS.
repo_get() {
    fetch "$BASE_URL/$1" "$2" || fail "не скачался $1 - проверьте интернет на роутере"
    want=$(awk -v p="$1" '$2 == p {print $1; exit}' "$WORK/SHA256SUMS")
    got=$(sha256sum "$2" | awk '{print $1}')
    [ -n "$want" ] && [ "$want" = "$got" ] || fail "файл $1 не совпадает с контрольной суммой - установка остановлена"
}

rci_json() { curl --fail --silent --connect-timeout 2 --max-time 10 "$RCI/$1" 2>/dev/null; }

crontab_cmd() { crontab -c "$CRONTAB_DIR" "$@"; }

ndm() {
    out=$(ndmc -c "$1" 2>&1) || return 1
    printf '%s\n' "$out" | grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command|not found|no such entry)' && return 1
    return 0
}

# ---------- checks ----------

installed() { [ -e "$UPDATER_STATE/committed.state" ] || [ -e /opt/etc/init.d/S91vward-route-engine ] || [ -e "$SHARE/VERSION" ]; }
beta_present() { [ -e /opt/etc/init.d/S91adaptive-live ] || [ -e /opt/bin/agh-adaptive-live.sh ]; }
agh_present() { [ -r /opt/etc/AdGuardHome/AdGuardHome.yaml ] || [ -x /opt/bin/AdGuardHome ] || [ -x /opt/sbin/AdGuardHome ]; }

missing_packages() {
    for p in $PACKAGES; do [ -e "${p#*:}" ] || printf '%s ' "${p%%:*}"; done
}

keenetic_release() {
    r=$(rci_json show/version | jq -r '.release // .title // empty' 2>/dev/null)
    [ -n "$r" ] || r=$(ndmc -c 'show version' 2>/dev/null | awk '$1 == "release:" || $1 == "title:" {print $2; exit}')
    printf '%s\n' "$r"
}

preflight() {
    step "1. Проверка роутера (ничего не меняется)"
    [ "$(id -u)" = 0 ] || fail "запустите от root (вход по SSH в Entware)"
    command -v ndmc >/dev/null 2>&1 && ndmc -c 'show version' >/dev/null 2>&1 ||
        fail "это не Keenetic или его система недоступна (нет ndmc)"
    rel=$(keenetic_release)
    major=$(printf '%s' "$rel" | sed -n 's/^\([0-9][0-9]*\).*/\1/p')
    if [ -z "$major" ]; then
        warn "версию KeeneticOS прочитать не удалось - продолжаю"
    elif [ "$major" -lt 5 ]; then
        # 5.0 is where Keenetic takes programs' tunnels (OpkgTun) as its own connections;
        # older releases would need workarounds past the firmware, which VWARD does not do.
        fail "KeeneticOS $rel: VWARD работает с KeeneticOS 5.0 и новее. Если для роутера есть 5.x - обновите его (Настройки - Общие - Обновления)"
    else
        ok "KeeneticOS $rel"
    fi
    mount | grep -q ' on /opt ' || fail "/opt не подключён: Entware не установлен на флешку"
    [ -w /opt ] || fail "/opt только для чтения"
    free=$(df -Pk /opt 2>/dev/null | awk 'NR == 2 {print $4}')
    case "$free" in ''|*[!0-9]*) free=0 ;; esac
    [ "$free" -ge "$MIN_FREE_KB" ] || fail "на флешке свободно $((free / 1024)) МБ, нужно не меньше $((MIN_FREE_KB / 1024)) МБ"
    ok "Entware на /opt, свободно $((free / 1024)) МБ"
    if installed; then
        pass "VWARD уже установлен ($(sed -n 1p "$SHARE/VERSION" 2>/dev/null || echo ?)) - обновления приходят сами, ставить заново не нужно"
        exit 0
    fi
    beta_present && fail "на роутере бета VWARD - для неё есть отдельный переход (scripts/beta-to-dev-cutover.sh)"
    ok "VWARD ещё не установлен"
    if agh_present; then ok "AdGuard Home найден - раздел «Реклама» будет работать"
    else skip "AdGuard Home не найден - раздел «Реклама» будет выключен, остальное работает"; fi
}

packages() {
    step "2. Пакеты Entware"
    need=$(missing_packages)
    if [ -z "$need" ]; then ok "все нужные пакеты уже есть"; return 0; fi
    line "Нужно поставить: $need"
    [ "$MODE" = check ] && return 0
    ask "Установить эти пакеты из Entware?" || fail "без пакетов VWARD работать не сможет"
    mkdir -p "${LOG%/*}" && LOG_OK=1
    opkg update >/dev/null 2>&1 || fail "opkg update не прошёл - проверьте интернет на роутере"
    # shellcheck disable=SC2086
    opkg install $need >> "$LOG" 2>&1 || fail "не удалось поставить пакеты: $need (подробности: $LOG)"
    left=$(missing_packages)
    [ -z "$left" ] || fail "пакеты не появились: $left"
    ok "пакеты установлены"
}

# ---------- network and VPN ----------

network() {
    step "3. Интернет, домашняя сеть и VPN"
    fetch "$BASE_URL/SHA256SUMS" "$WORK/SHA256SUMS" || fail "не удалось скачать VWARD с GitHub - проверьте интернет на роутере"
    repo_get components/runtime/lib/vward-device-profile.sh "$WORK/profile.sh"
    VWARD_DEVICE_MAP_CACHE=$WORK/map.tsv
    VWARD_DEVICE_CONFIG=$WORK/absent.conf
    export VWARD_DEVICE_MAP_CACHE VWARD_DEVICE_CONFIG
    . "$WORK/profile.sh"
    VWARD_RCI_BASE=$RCI
    map=$(vward_device_map 2>/dev/null) || fail "Keenetic не отдаёт список интерфейсов"
    wan=$(vward_discover_wan_device)
    [ -n "$wan" ] || fail "не найдено подключение к провайдеру (нет маршрута по умолчанию)"
    ok "провайдер: $(vward_map_ndm_for_kernel "$map" "$wan" | head -n 1) ($wan)"
    VWARD_WAN_DEVICE=$wan; export VWARD_WAN_DEVICE

    tunnels=$(vward_map_vpns "$map" "$wan")
    [ -n "$tunnels" ] || fail "в Keenetic нет VPN-подключения. Настройте VPN (WireGuard, OpenVPN и др.) в Keenetic и запустите установку снова"
    ifaces=$(rci_json show/interface)
    n=0 def=1
    routed=$(vward_select_tunnel "$map" 2>/dev/null | awk '{print $1}')
    list=$WORK/tunnels
    : > "$list"
    printf '%s\n' "$tunnels" | while read -r name dev; do
        [ -n "$name" ] || continue
        info=$(printf '%s\n' "$ifaces" | jq -r --arg n "$name" '.[$n] // {} |
            [(.description // ""), ((.type // "") | ascii_downcase), (if (.connected // "") == "yes" or (.link // "") == "up" then "работает" else "не подключён" end)] | join("\t")' 2>/dev/null)
        printf '%s\t%s\t%s\n' "$name" "$dev" "${info:-		}" >> "$list"
    done
    n=$(wc -l < "$list" | tr -d ' ')
    if [ "$n" -eq 1 ]; then
        TUNNEL=$(cut -f1 "$list"); TUNNEL_DEV=$(cut -f2 "$list")
        ok "VPN: $TUNNEL ($(cut -f5 "$list"))"
    else
        line "VPN-подключений: $n. Через какое пускать сайты, которые не открываются напрямую?"
        i=0
        while IFS="$(printf '\t')" read -r name dev desc type state; do
            i=$((i + 1))
            [ "$name" != "$routed" ] || def=$i
            line "  $i) $name${desc:+ «$desc»} - $type, $state"
        done < "$list"
        [ "$ASSUME_YES" = 0 ] || [ -n "$routed" ] || fail "VPN-подключений несколько - запустите без --yes и выберите"
        k=$(choose "Номер VPN" "$n" "$def") || fail "нет терминала для выбора - запустите файлом (sh install.sh)"
        TUNNEL=$(sed -n "${k}p" "$list" | cut -f1); TUNNEL_DEV=$(sed -n "${k}p" "$list" | cut -f2)
        ok "VPN: $TUNNEL"
    fi

    # The home network: the profile's own choice, or the owner's when there are several.
    lan=$(vward_discover_lan_record "$wan" "$map")
    if [ -n "$lan" ]; then
        ok "домашняя сеть: ${lan#* } ($(vward_map_ndm_for_kernel "$map" "${lan%% *}" | head -n 1))"
    else
        cands=$(ip -o -4 addr show scope global 2>/dev/null | awk -v w="$wan" -v t="$TUNNEL_DEV" '$2 != w && $2 != t {split($4, a, "/"); print $2, a[1]}' |
            while read -r d a; do vward_is_tunnel_sysfs "$d" || printf '%s %s\n' "$d" "$a"; done)
        c=$(printf '%s\n' "$cands" | sed '/^$/d' | wc -l | tr -d ' ')
        [ "$c" -gt 0 ] || fail "домашняя сеть не найдена"
        [ "$ASSUME_YES" = 0 ] || fail "сетей несколько - запустите без --yes и выберите домашнюю"
        line "Найдено сетей: $c. Какая из них домашняя (где ваши устройства)?"
        printf '%s\n' "$cands" | sed '/^$/d' | awk '{printf "  %d) %s (%s)\n", NR, $2, $1}'
        k=$(choose "Номер сети" "$c" 1) || fail "нет терминала для выбора - запустите файлом (sh install.sh)"
        LAN_CHOICE=$(printf '%s\n' "$cands" | sed '/^$/d' | sed -n "${k}p" | awk '{print $2}')
        ok "домашняя сеть: $LAN_CHOICE"
    fi

    # The whole profile, as VWARD will load it.
    {
        printf 'VWARD_TUNNEL_INTERFACE=%s\n' "$TUNNEL"
        [ -z "$LAN_CHOICE" ] || printf 'VWARD_LAN_ADDRESS=%s\n' "$LAN_CHOICE"
    } > "$WORK/device.conf"
    chmod 600 "$WORK/device.conf"
    probe=$(VWARD_DEVICE_CONFIG=$WORK/device.conf VWARD_DEVICE_MAP_CACHE=$WORK/map2.tsv sh -c '
        . "$1"; vward_profile_load && printf "%s %s %s\n" "$VWARD_LAN_ADDRESS" "$VWARD_TUNNEL_INTERFACE" "${VWARD_CONSOLE_PORT:-8088}"' sh "$WORK/profile.sh" 2>&1) ||
        fail "настройки сети не сходятся: $probe"
    set -- $probe
    LAN_ADDR=$1 CONSOLE_PORT=$3
    curl --fail --silent --connect-timeout 10 --max-time 20 -o /dev/null "$BASE_URL/VERSION" ||
        fail "GitHub недоступен с роутера"
    ok "интернет есть"
}

# ---------- changes ----------

undo() {
    [ "$STAGE" != none ] || return 0
    line "-- возврат изменений"
    if [ "$STAGE" = installed ]; then
        remove_program quiet
    fi
    if [ "$MADE_ADAPTIVE_ROUTE" = 1 ]; then ndm "dns-proxy no route object-group $ADAPTIVE_GROUP $TUNNEL" || :; fi
    if [ "$MADE_ADAPTIVE_GROUP" = 1 ]; then ndm "no object-group fqdn $ADAPTIVE_GROUP" || :; fi
    if [ "$MADE_ADAPTIVE_ROUTE" = 1 ] || [ "$MADE_ADAPTIVE_GROUP" = 1 ]; then ndm "system configuration save" || :; fi
    [ -z "$CRON_BACKUP" ] || crontab_cmd "$CRON_BACKUP" >/dev/null 2>&1 || :
    rm -rf "${UPDATER_ROOT:?}" "${UPDATER_STATE:?}" /opt/var/cache/vward/updater
    rm -f "$ETC/update.conf" "$ETC/update-public.pem" "$INSTALL_STATE"
    [ "$MADE_DEVICE_CONF" = 0 ] || rm -f "$ETC/device.conf"
    rmdir "$ETC/components" "$ETC" "$SHARE" /opt/var/lib/vward /opt/var/cache/vward /opt/var/run/vward 2>/dev/null || :
    STAGE=none
    line "[ OK ] изменения возвращены"
}

install_engine() {
    step "4. Установка VWARD (подписанная сборка)"
    mkdir -p "$WORK/engine" "$ETC" /opt/var/log/vward || fail "не создать каталоги VWARD"
    for f in $UPDATER_FILES; do
        repo_get "components/update-engine/$f" "$WORK/engine/$f"
        sh -n "$WORK/engine/$f" || fail "повреждён файл $f"
    done
    repo_get config/components/component-registry.json "$WORK/engine/component-registry.json"
    repo_get config/updater/update-public.pem "$WORK/update-public.pem"
    repo_get config/updater/update.conf.production "$WORK/update.conf"
    repo_get config/cron/root.crontab "$WORK/root.crontab"
    openssl pkey -pubin -in "$WORK/update-public.pem" -noout >/dev/null 2>&1 || fail "ключ подписи повреждён"

    CRON_BACKUP=$WORK/crontab.before
    crontab_cmd -l > "$CRON_BACKUP" 2>/dev/null || : > "$CRON_BACKUP"
    STAGE=engine
    if [ ! -e "$ETC/device.conf" ]; then
        (umask 077; cp "$WORK/device.conf" "$ETC/device.conf") || fail "не записать настройки сети"
        MADE_DEVICE_CONF=1
    else
        warn "настройки сети $ETC/device.conf уже есть - оставляю их"
    fi
    mkdir -p "$UPDATER_ROOT/slots/A" "$UPDATER_STATE/pending" /opt/var/cache/vward/updater /opt/var/run/vward || fail "не создать каталоги движка обновлений"
    for f in $UPDATER_FILES component-registry.json; do
        cp "$WORK/engine/$f" "$UPDATER_ROOT/slots/A/$f" || fail "не установить $f"
    done
    chmod 755 "$UPDATER_ROOT"/slots/A/*.sh && chmod 644 "$UPDATER_ROOT/slots/A/component-registry.json" || fail "права файлов движка"
    ln -sfn "$UPDATER_ROOT/slots/A" "$UPDATER_ROOT/current" || fail "не включить движок обновлений"
    cp "$WORK/update-public.pem" "$ETC/update-public.pem" && chmod 644 "$ETC/update-public.pem" || fail "не записать ключ подписи"
    (umask 077; cp "$WORK/update.conf" "$ETC/update.conf") || fail "не записать настройки обновлений"

    line "Скачиваю и проверяю подпись сборки..."
    "$UPDATER_ROOT/current/vward-update.sh" --install > "$WORK/engine.out" 2>&1
    rc=$?
    cat "$WORK/engine.out" >> "$LOG" 2>/dev/null
    ver=$(sed -n 's/^Version: //p' "$WORK/engine.out" | head -n 1)
    if [ "$rc" -ne 0 ]; then
        reason=$(grep -o 'ERROR.*' "$WORK/engine.out" | tail -n 1)
        fail "сборка не установилась (код $rc${reason:+: $reason}) - движок вернул файлы назад"
    fi
    STAGE=installed
    pass "VWARD $ver установлен: подпись и все файлы проверены"
}

configure() {
    step "5. Настройка"
    # Ads without AdGuard Home: the component stays installed and switched off.
    if ! agh_present; then
        mkdir -p "$ETC/components" || fail "не записать состояние компонентов"
        printf 'disabled by install.sh %s: AdGuard Home not found\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$ETC/components/ads-privacy-guard.disabled" ||
            fail "не выключить раздел «Реклама»"
        skip "«Реклама» выключена (нет AdGuard Home); включается в VWARD → Компоненты"
    fi

    # VWARD's own domain list, routed to the VPN: what autopick finds goes there.
    rc_now=$(ndmc -c 'show running-config' 2>/dev/null)
    if printf '%s\n' "$rc_now" | grep -qx "object-group fqdn $ADAPTIVE_GROUP"; then
        ok "список $ADAPTIVE_GROUP уже есть"
    else
        ndm "object-group fqdn $ADAPTIVE_GROUP" || fail "Keenetic не создал список $ADAPTIVE_GROUP"
        MADE_ADAPTIVE_GROUP=1
        ok "создан список $ADAPTIVE_GROUP (сюда автоподбор добавляет сайты для VPN)"
    fi
    if printf '%s\n' "$rc_now" | awk -v g="$ADAPTIVE_GROUP" '
        /^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)} /^!/ {ctx = 0}
        ctx && $1 == "route" && $2 == "object-group" && $3 == g {f = 1} END {exit !f}'; then
        ok "маршрут списка $ADAPTIVE_GROUP уже есть"
    else
        ndm "dns-proxy route object-group $ADAPTIVE_GROUP $TUNNEL auto" || fail "Keenetic не принял маршрут $ADAPTIVE_GROUP → $TUNNEL"
        MADE_ADAPTIVE_ROUTE=1
        ok "список $ADAPTIVE_GROUP идёт через $TUNNEL"
    fi
    if [ "$MADE_ADAPTIVE_GROUP" = 1 ] || [ "$MADE_ADAPTIVE_ROUTE" = 1 ]; then
        ndm "system configuration save" || fail "Keenetic не сохранил настройки"
    fi

    # Scheduled jobs: VWARD's lines are added, the owner's lines stay.
    tmp=$WORK/crontab.new
    cp "$CRON_BACKUP" "$tmp"
    while IFS= read -r l; do
        [ -n "$l" ] || continue
        m=$(printf '%s\n' "$l" | grep -oE '/opt/(bin|etc/init\.d)/[A-Za-z0-9_.-]+' | head -n 1)
        [ -n "$m" ] || continue
        grep -qF "$m" "$tmp" || printf '%s\n' "$l" >> "$tmp"
    done < "$WORK/root.crontab"
    grep -qF "$CRON_MARK" "$tmp" ||
        echo "*/15 * * * * $UPDATER_ROOT/current/vward-update-watch.sh --once >>/opt/var/log/vward/updater-watch.log 2>&1 $CRON_MARK" >> "$tmp"
    mkdir -p "$CRONTAB_DIR"
    crontab_cmd "$tmp" || fail "не записать задания cron"
    ok "задания по расписанию добавлены ($(grep -c . "$WORK/root.crontab") + обновления)"

    {
        printf 'installed_at=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
        printf 'tunnel=%s\n' "$TUNNEL"
        printf 'adaptive_group_created=%s\n' "$MADE_ADAPTIVE_GROUP"
        printf 'adaptive_route_created=%s\n' "$MADE_ADAPTIVE_ROUTE"
    } > "$INSTALL_STATE" && chmod 600 "$INSTALL_STATE"
}

start_all() {
    step "6. Запуск и проверка"
    [ -x /opt/etc/init.d/S90crond ] && /opt/etc/init.d/S90crond start >/dev/null 2>&1
    pidof crond >/dev/null 2>&1 || fail "cron не запустился"
    ok "cron работает"
    /opt/etc/init.d/S91vward-route-engine start >/dev/null 2>&1 </dev/null
    /opt/etc/init.d/S92vward-runtime start >/dev/null 2>&1 </dev/null
    /opt/etc/init.d/S93vward-console start >/dev/null 2>&1 </dev/null
    t=0
    until pong=$(curl --fail --silent --max-time 5 "http://$LAN_ADDR:$CONSOLE_PORT/cgi-bin/api.cgi?action=ping" 2>/dev/null) &&
          printf '%s\n' "$pong" | jq -e '.ok == true' >/dev/null 2>&1; do
        t=$((t + 1)); [ "$t" -lt 10 ] || fail "Панель VWARD не отвечает"
        sleep 1
    done
    ok "Панель VWARD отвечает"
    t=0
    until [ -r /opt/var/run/vward/route-engine.pid ] && kill -0 "$(sed -n 1p /opt/var/run/vward/route-engine.pid)" 2>/dev/null; do
        t=$((t + 1)); [ "$t" -lt 10 ] || { warn "автоподбор ещё не запустился - cron поднимет его в течение минуты"; break; }
        sleep 1
    done
    [ "$t" -ge 10 ] || ok "автоподбор работает"
    # The catalogs of known services, so autopick has hints from the first day.
    [ -x /opt/bin/vward-route-hints-update.sh ] && nohup /opt/bin/vward-route-hints-update.sh </dev/null >/dev/null 2>&1 &
    STAGE=finished
}

remove_program() {
    quiet=${1:-}
    for s in S93vward-console S92vward-runtime S91vward-route-engine; do
        [ -x "/opt/etc/init.d/$s" ] && "/opt/etc/init.d/$s" stop >/dev/null 2>&1 </dev/null
    done
    # What VWARD set in AdGuard Home and in the firewall goes first.
    [ -x /opt/bin/vward-ads-privacy-route-dns.sh ] && /opt/bin/vward-ads-privacy-route-dns.sh off >/dev/null 2>&1
    if [ -x /opt/bin/vward-ads-privacy-dns-guard.sh ]; then
        /opt/bin/vward-ads-privacy-dns-guard.sh set enforce 0 >/dev/null 2>&1
        /opt/bin/vward-ads-privacy-dns-guard.sh set bypass 0 >/dev/null 2>&1
    fi
    map=$SHARE/package-map.tsv
    if [ -r "$map" ]; then
        awk -F '\t' '!/^#/ && NF >= 3 && $3 ~ /^\/opt\// && $3 !~ /\.\./ {print $3}' "$map" > /tmp/vward-uninstall.$$
        while IFS= read -r t; do rm -f "$t"; done < /tmp/vward-uninstall.$$
        rm -f /tmp/vward-uninstall.$$
    fi
    rm -rf "${SHARE:?}" /opt/lib/vward /opt/var/lib/vward /opt/var/cache/vward /opt/var/run/vward
    t=$WORK/crontab.clean
    crontab_cmd -l 2>/dev/null | grep -vE '/opt/bin/vward-|/opt/etc/init\.d/S9[123]vward-' | grep -vF "$CRON_MARK" > "$t"
    crontab_cmd "$t" >/dev/null 2>&1 || :
    [ -n "$quiet" ] || ok "программа VWARD удалена, задания cron убраны"
}

cmd_install() {
    LOG_OK=
    preflight
    packages
    if [ "$MODE" = check ] && [ -n "$(missing_packages)" ]; then
        step "3. Интернет, домашняя сеть и VPN"
        skip "проверятся после установки пакетов (нужен jq)"
    else
        network
    fi
    [ "$MODE" = check ] && { line ""; pass "роутер готов к установке. Запустите без --check"; exit 0; }
    mkdir -p /opt/var/log/vward && LOG_OK=1
    line ""
    line "Будет установлено: VWARD в /opt, задания cron, список $ADAPTIVE_GROUP через $TUNNEL."
    ask "Устанавливать?" || { line "Отменено. Ничего не изменено."; exit 0; }
    trap 'fail "прервано"' INT TERM HUP
    install_engine
    configure
    start_all
    trap - INT TERM HUP
    line ""
    pass "VWARD установлен"
    line "Панель VWARD: http://$LAN_ADDR:$CONSOLE_PORT"
    line "Сайты, которые не открываются напрямую, VWARD сам отправит через $TUNNEL."
    line "Обновления приходят сами. Удаление:"
    line "  curl -fsSL $BASE_URL/install.sh -o /tmp/vward-install.sh && sh /tmp/vward-install.sh --uninstall"
}

cmd_uninstall() {
    [ "$(id -u)" = 0 ] || fail "запустите от root"
    installed || [ -e "$ETC" ] || { pass "VWARD не установлен"; exit 0; }
    line "VWARD будет удалён. Настройки сохранятся в /opt/var/backups/vward."
    ask "Удалить VWARD?" || { line "Отменено."; exit 0; }
    tun=$(sed -n 's/^tunnel=//p' "$INSTALL_STATE" 2>/dev/null)
    g=$(sed -n 's/^adaptive_group_created=//p' "$INSTALL_STATE" 2>/dev/null)
    r=$(sed -n 's/^adaptive_route_created=//p' "$INSTALL_STATE" 2>/dev/null)
    remove_program
    if [ -d "$ETC" ]; then
        b=/opt/var/backups/vward/uninstall-$(date '+%Y%m%d-%H%M%S')
        mkdir -p "$b" && cp -pR "$ETC" "$b/etc" && rm -rf "${ETC:?}" && ok "настройки сохранены: $b"
    fi
    if [ "$r" = 1 ] || [ "$g" = 1 ]; then
        if ask "Убрать из Keenetic список $ADAPTIVE_GROUP, который создал установщик?"; then
            [ "$r" != 1 ] || [ -z "$tun" ] || ndm "dns-proxy no route object-group $ADAPTIVE_GROUP $tun" || :
            [ "$g" != 1 ] || ndm "no object-group fqdn $ADAPTIVE_GROUP" || :
            ndm "system configuration save" || :
            ok "список $ADAPTIVE_GROUP убран"
        fi
    fi
    pass "VWARD удалён. Пакеты Entware оставлены"
}

MODE=install
for a in "$@"; do
    case "$a" in
        --check) MODE=check ;;
        --yes|-y) ASSUME_YES=1 ;;
        --uninstall) MODE=uninstall ;;
        *) echo "usage: sh install.sh [--check] [--yes] | --uninstall" >&2; exit 64 ;;
    esac
done
WORK=$(mktemp -d /tmp/vward-install.XXXXXX) || { echo "[ FAIL ] нет места в /tmp"; exit 1; }
trap 'rm -rf "${WORK:?}"' EXIT

case "$MODE" in
    uninstall) cmd_uninstall ;;
    *) cmd_install ;;
esac
