#!/bin/sh
# Builds a chroot that models a healthy Keenetic router with Entware and an
# installed VWARD package: BusyBox userland, real jq/openssl, fake ndmc, curl,
# ip, ping, wg and tcpdump that answer from /emu, package files from the
# package map, example configs and the VWARD crontab.
#   build-rootfs.sh ROOT
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
FAKES=$REPO/tests/perf/emulator/fakes
ROOT=$1
[ ! -e "$ROOT" ] || { echo "exists: $ROOT" >&2; exit 1; }
BB=$(command -v busybox)

mkdir -p "$ROOT"/bin "$ROOT"/sbin "$ROOT"/usr/bin "$ROOT"/usr/sbin "$ROOT"/tmp "$ROOT"/proc "$ROOT"/dev \
    "$ROOT"/opt/bin "$ROOT"/opt/sbin "$ROOT"/opt/lib "$ROOT"/opt/etc/init.d "$ROOT"/opt/var/log "$ROOT"/opt/var/run \
    "$ROOT"/opt/var/spool/cron/crontabs "$ROOT"/emu "$ROOT"/sys/class/net "$ROOT"/etc "$ROOT"/root
chmod 1777 "$ROOT/tmp"

# Binaries with their shared libraries.
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
printf '#!/bin/sh\nexit 0\n' > "$ROOT/opt/sbin/lighttpd"
chmod 755 "$ROOT"/opt/bin/* "$ROOT"/opt/sbin/* "$ROOT/bin/ndmc"
printf 'root:x:0:0:root:/root:/bin/sh\n' > "$ROOT/etc/passwd"
printf 'root:x:0:\n' > "$ROOT/etc/group"
mknod -m 666 "$ROOT/dev/null" c 1 3
mknod -m 444 "$ROOT/dev/urandom" c 1 9

# Package files exactly as the package map installs them.
while IFS="$(printf '\t')" read -r component source target mode; do
    case "$component" in ''|'#'*) continue ;; esac
    mkdir -p "$ROOT$(dirname "$target")"
    cp "$REPO/$source" "$ROOT$target"
    chmod "$mode" "$ROOT$target"
done < "$REPO/config/components/package-map.tsv"

# Local configuration a configured router has.
for example in $(cd "$REPO/config" && find route-engine wifi-client-guard ads-privacy-guard -name '*.example'); do
    target="$ROOT/opt/etc/vward/${example%.example}"
    mkdir -p "$(dirname "$target")"
    cp "$REPO/config/$example" "$target"
    chmod 600 "$target"
done
cp "$REPO/config/updater/update.conf.production" "$ROOT/opt/etc/vward/update.conf"
cp "$REPO/config/updater/update-public.pem" "$ROOT/opt/etc/vward/update-public.pem"
cat > "$ROOT/opt/etc/vward/device.conf" <<'EOF'
VWARD_LAN_ADDRESS=192.0.2.1
VWARD_LAN_SUBNET=192.0.2.0/24
VWARD_LAN_INTERFACE=Bridge0
VWARD_DNS_SERVER=192.0.2.1
VWARD_PROBE_DNS=192.0.2.1
VWARD_ADGUARD_ADDRESS=192.0.2.1
VWARD_ADGUARD_PORT=3000
VWARD_WAN_DEVICE=eth2.2
VWARD_WAN_INTERFACE=ISP
VWARD_TUNNEL_DEVICE=nwg1
VWARD_TUNNEL_INTERFACE=Wireguard1
VWARD_POLICY_GROUP=vpn-sites
VWARD_CONSOLE_PORT=8088
VWARD_RCI_BASE=http://127.0.0.1:79/rci
EOF
chmod 600 "$ROOT/opt/etc/vward/device.conf"
cp "$REPO/config/cron/root.crontab" "$ROOT/opt/var/spool/cron/crontabs/root"

# Update Engine in its slot, as the bootstrap installs it.
mkdir -p "$ROOT/opt/share/vward/updater/slot-a"
cp "$REPO"/components/update-engine/vward-update*.sh "$ROOT/opt/share/vward/updater/slot-a/"
chmod 755 "$ROOT"/opt/share/vward/updater/slot-a/*.sh
ln -s slot-a "$ROOT/opt/share/vward/updater/current"
cp "$REPO/updates/dev/update-manifest.json" "$ROOT/emu/update-manifest.json"

# Healthy kernel interfaces.
for dev in br0 eth2.2 nwg1; do
    mkdir -p "$ROOT/sys/class/net/$dev"
    echo 1 > "$ROOT/sys/class/net/$dev/carrier"
    echo up > "$ROOT/sys/class/net/$dev/operstate"
done
mkdir -p "$ROOT/sys/class/net/nwg1/wireguard"

# Router answers.
cat > "$ROOT/emu/running-config" <<'EOF'
object-group fqdn vpn-sites
    include youtube.com
    include googlevideo.com
    include instagram.com
!
object-group fqdn AdaptiveAuto
    include adaptive-one.example
!
dns-proxy
    route object-group vpn-sites Wireguard1 auto
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
# Home DNS traffic: most queries repeat a few popular names, the rest is a long tail.
awk 'BEGIN {
    split("youtube.com googlevideo.com instagram.com adaptive-one.example popular1.example popular2.example popular3.example popular4.example popular5.example popular6.example", p, " ")
    x = 7
    for (i = 1; i <= 600; i++) {
        x = (x * 1103515245 + 12345) % 2147483648
        if (x % 10 < 7) print p[1 + int(x / 10) % 10]
        else printf "tail%03d.example\n", int(x / 100) % 150
    }
}' > "$ROOT/emu/dns-queries"
printf '%s\n' "$(sed -n 1p "$REPO/VERSION")" > "$ROOT/emu/version"
echo "ROOTFS=$ROOT"
