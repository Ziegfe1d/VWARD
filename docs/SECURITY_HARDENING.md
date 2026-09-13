# Security hardening

The `dev` branch uses a LAN-only Console listener by default:
`192.168.1.1:8088`. Wildcard listeners are rejected by repository tests.

Console mutations accept only `POST` requests with the expected form content
type and the `X-VWARD-Request: console` request guard. The API does not expose
CORS or an `OPTIONS` preflight path. Static and CGI responses add restrictive
browser security headers, directory listing is disabled, and common backup or
editor suffixes are denied.

This source review does not prove the live router's listening sockets or
firewall rules. Before any `dev` deployment, verify them on the target:

```sh
ss -lntup 2>/dev/null || netstat -lntup
```

Expected VWARD-owned listener: TCP `192.168.1.1:8088` only. Any WAN exposure,
wildcard bind, or unexpected listener blocks deployment until investigated.

The custom request header is a CSRF barrier, not user authentication. Until an
authentication design is implemented, Console access must remain limited to a
trusted management LAN by the router firewall.
