#!/bin/sh
# Builds a chroot that models a router as the installer finds it: Keenetic with
# Entware on a USB drive and one VPN connection configured, nothing else - no
# VWARD, no domain lists, no AdGuard Home.  BusyBox userland, real jq/openssl,
# fake ndmc, curl, ip, opkg, tcpdump, crond and lighttpd answering from /emu.
# The repository GitHub serves is /emu/repo (the fake curl reads it).
#   build-rootfs-clean.sh ROOT
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
for tool in curl ping nslookup wg opkg; do cp "$FAKES/$tool" "$ROOT/opt/bin/$tool"; done
cp "$FAKES/ndmc" "$ROOT/bin/ndmc"
cp "$FAKES/ip" "$ROOT/opt/sbin/ip"
cp "$FAKES/ps" "$ROOT/opt/bin/ps"
chmod 755 "$ROOT"/opt/bin/* "$ROOT"/opt/sbin/* "$ROOT/bin/ndmc"
printf 'root:x:0:0:root:/root:/bin/sh\n' > "$ROOT/etc/passwd"
printf 'root:x:0:\n' > "$ROOT/etc/group"
mknod -m 666 "$ROOT/dev/null" c 1 3
mknod -m 444 "$ROOT/dev/urandom" c 1 9
mkdir -p "$ROOT/proc/sys/kernel/random"

# Entware packages: what a fresh Entware has is installed, the rest waits in
# /emu/pkgstore for "opkg install" (the fake unpacks it over /).
store=$ROOT/emu/pkgstore
pkg() { mkdir -p "$store/$1$(dirname "$2")"; }
pkg curl /opt/bin/curl; cp "$FAKES/curl" "$store/curl/opt/bin/curl"
pkg jq /opt/bin/jq; cp "$(command -v jq)" "$store/jq/opt/bin/jq"
ldd "$(command -v jq)" | awk '/=> \// {print $3}' | while read -r lib; do mkdir -p "$ROOT$(dirname "$lib")"; [ -e "$ROOT$lib" ] || cp -L "$lib" "$ROOT$lib"; done
pkg openssl-util /opt/bin/openssl; copy_bin "$(command -v openssl)" /opt/bin/openssl
mv "$ROOT/opt/bin/openssl" "$store/openssl-util/opt/bin/openssl"
pkg tcpdump /opt/sbin/tcpdump; cc -O2 -static -o "$store/tcpdump/opt/sbin/tcpdump" "$FAKES/tcpdump.c"
pkg cron /opt/sbin/crond; cc -O2 -static -o "$store/cron/opt/sbin/crond" "$FAKES/crond.c"
pkg lighttpd /opt/sbin/lighttpd; cc -O2 -static -o "$store/lighttpd/opt/sbin/lighttpd" "$FAKES/lighttpd.c"
for m in cgi setenv; do pkg "lighttpd-mod-$m" /opt/lib/lighttpd/x; : > "$store/lighttpd-mod-$m/opt/lib/lighttpd/mod_$m.so"; done
pkg ca-bundle /opt/etc/ssl/certs/x; : > "$store/ca-bundle/opt/etc/ssl/certs/ca-certificates.crt"
# A fresh Entware already has curl (to fetch the installer) and cron.
cp -a "$store/curl/." "$ROOT/"
cp -a "$store/cron/." "$ROOT/"
# Entware's own cron start script is S10cron; VWARD brings S90crond.
cat > "$ROOT/opt/etc/init.d/S10cron" <<'CROND'
#!/bin/sh
case "$1" in start) pidof crond >/dev/null 2>&1 || /opt/sbin/crond -b -c /opt/var/spool/cron/crontabs ;; stop) killall crond 2>/dev/null ;; esac
exit 0
CROND
chmod 755 "$ROOT/opt/etc/init.d/S10cron"

# The repository as GitHub serves it.
mkdir -p "$ROOT/emu/repo"
(cd "$REPO" && git ls-files -z | xargs -0 tar -cf - 2>/dev/null) | tar -xf - -C "$ROOT/emu/repo"

# Kernel interfaces: home bridge, provider, one WireGuard tunnel.
for dev in br0 eth2.2 nwg1; do
    mkdir -p "$ROOT/sys/class/net/$dev"
    echo 1 > "$ROOT/sys/class/net/$dev/carrier"
    echo up > "$ROOT/sys/class/net/$dev/operstate"
    : > "$ROOT/sys/class/net/$dev/uevent"
done
echo DEVTYPE=wireguard > "$ROOT/sys/class/net/nwg1/uevent"
mkdir -p "$ROOT/sys/class/net/nwg1/wireguard"

# Router answers: a VPN connection and nothing else.
cat > "$ROOT/emu/running-config" <<'CFG'
system
    hostname Keenetic
!
interface Wireguard1
    description "My VPN"
!
dns-proxy
!
CFG
cat > "$ROOT/emu/rci-interface.json" <<'JSON'
{"Bridge0":{"type":"Bridge","security-level":"private"},"ISP":{"type":"GigabitEthernet","security-level":"public"},"Wireguard1":{"type":"Wireguard","security-level":"public","description":"My VPN","connected":"yes","link":"up"}}
JSON
cat > "$ROOT/emu/rci-isp.json" <<'JSON'
{"link":"up","port":{"link":"up"},"connected":"yes","state":"up","address":"203.0.113.10","defaultgw":true,"summary":{"layer":{"ipv4":"running"}}}
JSON
echo '{"gateway":{"address":"203.0.113.1"},"internet":true}' > "$ROOT/emu/rci-internet.json"
printf 'default via 203.0.113.1 dev eth2.2\n192.0.2.0/24 dev br0 scope link\n203.0.113.0/24 dev eth2.2 scope link\n' > "$ROOT/emu/ip-route"
printf 'station:\n' > "$ROOT/emu/associations"
: > "$ROOT/emu/dns-queries"
echo "ROOTFS=$ROOT"
