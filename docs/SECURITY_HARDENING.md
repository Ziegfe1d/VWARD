# Security hardening

The `dev` branch generates a LAN-only Console listener from the validated Device
Profile. Wildcard listeners are rejected by repository tests.

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

Expected VWARD-owned listener: TCP on the configured LAN address and Console port
only. Any WAN exposure,
wildcard bind, or unexpected listener blocks deployment until investigated.

The custom request header is a CSRF barrier, not user authentication. Until an
authentication design is implemented, Console access must remain limited to a
trusted management LAN by the router firewall.

## Deep audit 2026-09-25

- The API answers only the router's own names (IP literals, localhost, local and
  one-word names, Keenetic names, `ALLOWED_HOSTS`): DNS rebinding cannot reach
  it, with or without the Console login.
- Downloaded backups carry no secrets; the snapshot on the router keeps them for
  a restore.
- WireGuard private and preshared keys reach Keenetic in an RCI request body
  read from a root-only file, never in a process's arguments; uploaded tunnel
  files live in RAM only and go with the helper whatever happens.
- Locks whose owner is gone are removed at boot and hourly, so a power cut no
  longer blocks updates or the nightly IP sync.

Details: `docs/AUDIT_DEEP_2026-09-25.md`.
