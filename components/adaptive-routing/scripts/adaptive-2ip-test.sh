#!/bin/sh

HOST="2ip.io"
GROUP="domain-list22"
WAN="eth3"
FORCE_FAIL="${FORCE_FAIL:-0}"

echo "===== ADAPTIVE ROUTE TEST ====="
echo "HOST=$HOST"
echo

# Для честной проверки ISP временно убираем домен из VPN-группы.
ndmc -c "no object-group fqdn $GROUP include $HOST" >/dev/null 2>&1
sleep 2

IP=$(nslookup "$HOST" 9.9.9.10 2>/dev/null | \
awk '/^Address [0-9]+:/ && $3 ~ /^[0-9]+\./ {ip=$3} END{print ip}')

echo "$HOST -> $IP"

OK=0

if [ "$FORCE_FAIL" = "1" ]; then
    echo "TEST MODE: ISP failure forced"
else
    OUT=$(curl -4 \
        --interface "$WAN" \
        --resolve "$HOST:443:$IP" \
        --connect-timeout 5 \
        --max-time 8 \
        -A "Mozilla/5.0" \
        -sS -o /dev/null \
        -w '%{http_code} %{time_total}' \
        "https://$HOST/ru/" 2>/dev/null)

    RC=$?
    CODE=$(echo "$OUT" | awk '{print $1}')
    TIME=$(echo "$OUT" | awk '{print $2}')

    echo "curl exit: $RC"
    echo "HTTP code: $CODE"
    echo "response time: ${TIME}s"

    if [ "$RC" = "0" ] && [ "$CODE" != "000" ] && [ -n "$CODE" ]; then
        OK=1
    fi
fi

echo

if [ "$OK" = "1" ]; then
    echo "RESULT: ISP REACHABLE"
    echo "ROUTE: ISP"
else
    echo "RESULT: ISP UNREACHABLE"
    echo "ROUTE: WireGuard"

    ndmc -c "object-group fqdn $GROUP include $HOST" >/dev/null 2>&1
    nslookup "$HOST" 192.168.1.1 >/dev/null 2>&1
    sleep 2
fi

echo
echo "===== FINAL STATE ====="

if ndmc -c "show object-group fqdn $GROUP" 2>/dev/null | \
   grep -q "fqdn: $HOST"; then
    echo "$HOST -> WireGuard"
else
    echo "$HOST -> ISP"
fi
