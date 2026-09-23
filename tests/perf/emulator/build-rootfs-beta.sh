#!/bin/sh
# Builds a chroot that models a router running the real, currently deployed
# VWARD 0.1.9-beta (branch `beta`): BusyBox userland, the same fake Keenetic
# tools as build-rootfs.sh, and beta's actual program files, crontab and
# init.d scripts fetched from origin/beta. Used to test the beta -> 0.2
# cutover (scripts/beta-to-dev-cutover.sh) without a real router.
#
# Does not mount /proc and does not start any daemon: the caller mounts
# ROOT/proc (and, for realistic df/free-space checks, bind-mounts ROOT/opt
# onto itself) and starts services explicitly, the same way
# tests/perf/run-resource-audit.py drives build-rootfs.sh.
#   build-rootfs-beta.sh ROOT
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
FAKES=$REPO/tests/perf/emulator/fakes
ROOT=$1
[ ! -e "$ROOT" ] || { echo "exists: $ROOT" >&2; exit 1; }
BB=$(command -v busybox)
git -C "$REPO" rev-parse -q --verify origin/beta >/dev/null || { echo "origin/beta is not available" >&2; exit 1; }
show() { git -C "$REPO" show "origin/beta:$1"; }

mkdir -p "$ROOT"/bin "$ROOT"/sbin "$ROOT"/usr/bin "$ROOT"/usr/sbin "$ROOT"/tmp "$ROOT"/proc "$ROOT"/dev \
    "$ROOT"/opt/bin "$ROOT"/opt/sbin "$ROOT"/opt/lib "$ROOT"/opt/etc/init.d "$ROOT"/opt/etc/keenetic-apps \
    "$ROOT"/opt/etc/adaptive-route "$ROOT"/opt/etc/AdGuardHome/data "$ROOT"/opt/etc/vward \
    "$ROOT"/opt/share/keenetic-apps/www/cgi-bin "$ROOT"/opt/share/vward/updater/slot-a \
    "$ROOT"/opt/var/log "$ROOT"/opt/var/run "$ROOT"/opt/var/lib/vward/updater "$ROOT"/opt/var/lib/adaptive-live \
    "$ROOT"/opt/var/lib/wg-failopen "$ROOT"/opt/var/lib/wg-health "$ROOT"/opt/var/lib/vpn-subnets \
    "$ROOT"/opt/var/spool/cron/crontabs "$ROOT"/emu "$ROOT"/sys/class/net "$ROOT"/etc "$ROOT"/root
chmod 1777 "$ROOT/tmp"

copy_bin() {
    cp "$1" "$ROOT$2"
    ldd "$1" | awk '/=> \// {print $3} /^\t\/lib/ {print $1}' | while read -r lib; do
        mkdir -p "$ROOT$(dirname "$lib")"
        [ -e "$ROOT$lib" ] || cp -L "$lib" "$ROOT$lib"
    done
}
copy_bin "$BB" /bin/busybox
for applet in $("$BB" --list); do
    case "$applet" in busybox|ip|ping|nslookup|curl|tcpdump|ps|crond) continue ;; esac
    [ -e "$ROOT/bin/$applet" ] || ln -s busybox "$ROOT/bin/$applet"
done
ln -s /bin/busybox "$ROOT/opt/bin/sh"
ln -s /bin/busybox "$ROOT/opt/bin/busybox"
copy_bin "$(command -v jq)" /opt/bin/jq
copy_bin "$(command -v openssl)" /opt/bin/openssl
for tool in curl ping nslookup wg; do cp "$FAKES/$tool" "$ROOT/opt/bin/$tool"; done
cp "$FAKES/ndmc" "$ROOT/bin/ndmc"
cp "$FAKES/ip" "$ROOT/opt/sbin/ip"
cc -O2 -static -o "$ROOT/opt/sbin/tcpdump" "$FAKES/tcpdump.c"
cc -O2 -static -o "$ROOT/opt/sbin/crond" "$FAKES/crond.c"
cp "$FAKES/ps" "$ROOT/opt/bin/ps"
cc -O2 -static -o "$ROOT/opt/sbin/lighttpd" "$FAKES/lighttpd.c"
chmod 755 "$ROOT"/opt/bin/* "$ROOT"/opt/sbin/* "$ROOT/bin/ndmc"
printf 'root:x:0:0:root:/root:/bin/sh\n' > "$ROOT/etc/passwd"
printf 'root:x:0:\n' > "$ROOT/etc/group"
mknod -m 666 "$ROOT/dev/null" c 1 3
mknod -m 444 "$ROOT/dev/urandom" c 1 9

# Beta's actual program files, at their real beta targets (docs/INSTALLATION_MAP.md
# on origin/beta), fetched from the beta tree itself.
install_from_beta() {
    src=$1 dst=$2 mode=${3:-0755}
    mkdir -p "$ROOT$(dirname "$dst")"
    show "$src" > "$ROOT$dst"
    chmod "$mode" "$ROOT$dst"
}
for name in adaptive-2ip-test adaptive-auto-maint adaptive-hints-update adaptive-housekeeping \
            adaptive-resolve4 adaptive-route agh-adaptive-live agh-adaptive-route; do
    install_from_beta "components/adaptive-routing/scripts/$name.sh" "/opt/bin/$name.sh"
done
for name in vpn-domain-audit-chain vpn-domain-audit vpn-night-reconcile vpn-subnet-sync; do
    install_from_beta "components/vpn-audit/scripts/$name.sh" "/opt/bin/$name.sh"
done
for name in wg-failopen-guard wg-health-watch; do
    install_from_beta "components/wireguard-protection/scripts/$name.sh" "/opt/bin/$name.sh"
done
for name in wan-guardian wan-recovery-actuator; do
    install_from_beta "components/wan-guardian/scripts/$name.sh" "/opt/bin/$name.sh"
done
install_from_beta "components/runtime-supervision/scripts/crond-supervisor.sh" "/opt/bin/crond-supervisor.sh"
for name in S90crond S91adaptive-live S92crond-supervisor S93keenetic-apps; do
    install_from_beta "components/runtime-supervision/init.d/$name" "/opt/etc/init.d/$name"
done
install_from_beta "web/lighttpd.conf" "/opt/etc/keenetic-apps/lighttpd.conf" 0644
install_from_beta "web/index.html" "/opt/share/keenetic-apps/www/index.html" 0644
install_from_beta "web/cgi-bin/api.cgi" "/opt/share/keenetic-apps/www/cgi-bin/api.cgi"
show "VERSION" > "$ROOT/opt/share/vward/VERSION"
show "config/cron/root.crontab" > "$ROOT/opt/var/spool/cron/crontabs/root"

# Local configuration a real beta install has accumulated.
show "config/adaptive-route/hints.conf.example" 2>/dev/null > "$ROOT/opt/etc/adaptive-route/hints.conf" || printf 'legacy.example\n' > "$ROOT/opt/etc/adaptive-route/hints.conf"
printf 'legacy-skip.example\n' > "$ROOT/opt/etc/adaptive-route/skip-domains.conf"
printf 'AGH_ADDR=192.0.2.1\nAGH_PORT=3000\n' > "$ROOT/opt/etc/adaptive-route/adaptive-route.conf"
: > "$ROOT/opt/var/lib/adaptive-live/adaptive-persist.txt"
: > "$ROOT/opt/var/lib/wg-failopen/state"

# Update Engine: shared canonical paths between beta and dev, already installed.
cp "$REPO"/components/update-engine/vward-update*.sh "$ROOT/opt/share/vward/updater/slot-a/"
chmod 755 "$ROOT"/opt/share/vward/updater/slot-a/*.sh
ln -s slot-a "$ROOT/opt/share/vward/updater/current"
cp "$REPO/config/updater/update-public.pem" "$ROOT/opt/etc/vward/update-public.pem"
cp "$REPO/config/updater/update.conf.production" "$ROOT/opt/etc/vward/update.conf"
sed -i "s#/VWARD/dev/updates/#/VWARD/beta/updates/#" "$ROOT/opt/etc/vward/update.conf"
printf 'installed_version=%s\ninstalled_update_id=vward-0.1.9-beta\nlast_sequence=2026091701\nmanifest_hash=beta\nlast_health_check=beta\n' \
    "$(sed -n 1p "$ROOT/opt/share/vward/VERSION")" > "$ROOT/opt/var/lib/vward/updater/committed.state"

# Healthy kernel interfaces and router answers, same as the dev emulator.
for dev in br0 eth2.2 nwg1; do
    mkdir -p "$ROOT/sys/class/net/$dev"
    echo 1 > "$ROOT/sys/class/net/$dev/carrier"
    echo up > "$ROOT/sys/class/net/$dev/operstate"
done
mkdir -p "$ROOT/sys/class/net/nwg1/wireguard"
cat > "$ROOT/emu/running-config" <<'EOF'
object-group fqdn domain-list22
    include youtube.com
    include googlevideo.com
    include instagram.com
!
object-group fqdn AdaptiveAuto
    include adaptive-one.example
!
dns-proxy
    route object-group domain-list22 Wireguard1 auto
    route object-group AdaptiveAuto Wireguard1 auto
!
interface Wireguard1
    description vpn
!
ip route 198.51.100.0 255.255.255.0 Wireguard1 auto
EOF
cat > "$ROOT/emu/rci-interface.json" <<'EOF'
{"Bridge0":{"type":"Bridge","security-level":"private"},"ISP":{"type":"GigabitEthernet","security-level":"public"},"Wireguard1":{"type":"Wireguard","security-level":"public"}}
EOF
cat > "$ROOT/emu/rci-isp.json" <<'EOF'
{"link":"up","port":{"link":"up"},"connected":"yes","state":"up","address":"203.0.113.10","defaultgw":true,"summary":{"layer":{"ipv4":"running"}}}
EOF
cat > "$ROOT/emu/rci-internet.json" <<'EOF'
{"gateway":{"address":"203.0.113.1"},"gateway-accessible":true,"dns-accessible":true,"internet":true,"reliable":true}
EOF
printf 'default via 203.0.113.1 dev eth2.2\n192.0.2.0/24 dev br0 scope link\n198.51.100.0/24 dev nwg1 scope link\n203.0.113.0/24 dev eth2.2 scope link\n' > "$ROOT/emu/ip-route"
printf 'station:\n' > "$ROOT/emu/associations"
: > "$ROOT/emu/dns-queries"
cp "$REPO/updates/dev/update-manifest.json" "$ROOT/emu/update-manifest.json" 2>/dev/null || true

echo "ROOTFS=$ROOT"
