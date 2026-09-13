# VWARD HTTPS Content Guard

`HTTPS Content Guard` is an optional internal engine of `VWARD Ads & Privacy Guard`.
It extends the DNS layer with selective HTTPS request-path filtering without turning
Ads & Privacy Guard into a second standalone product.

## Candidate scope

This candidate implements a **real explicit-proxy backend contract** for Entware
`3proxy` with `SSLPlugin` and `PCREPlugin`:

1. local VWARD CA generation and protected private-key storage;
2. explicit MITM proxy lifecycle (`validate/render/start/stop/status`);
3. PAC generation so only explicitly selected domains enter the MITM proxy;
4. hard bypass precedence;
5. safe request-path rules (`path_prefix` / `path_exact` -> BLOCK);
6. upstream certificate verification is mandatory;
7. no automatic firewall/NAT changes;
8. DNS/AGH protection remains independent if HTTPS Guard is stopped or unsupported.

The engine is **disabled by default** and cannot start without an explicit `--confirm`.

## Why explicit proxy first

Transparent interception on a household router requires firewall/NAT ownership and can
silently break pinned applications. This candidate deliberately avoids that. A PAC file
routes only selected hosts through the MITM listener and returns `DIRECT` for everything
else. Bypass rules win over intercept rules.

This means a bank, identity provider or any other sensitive service is not decrypted
unless it is deliberately placed into the intercept set. VWARD should keep that invariant
when a future Console editor is added.

## Router backend

The initial provider is Entware `3proxy` because the current MIPSEL feed exposes 3proxy
0.9.5 and describes SSL-plugin support when `libopenssl` is installed. Upstream 3proxy
0.9.5 release notes describe the rewritten SSLPlugin as production-ready, including TLS
interception. PCREPlugin provides request/header/data filters used here only for safe
request-path blocking.

The package does not vendor a third-party binary. At runtime it probes:

- `/opt/bin/3proxy` or `/opt/sbin/3proxy`;
- `SSLPlugin.ld.so` / `SSLPlugin.so`;
- `PCREPlugin.ld.so` / `PCREPlugin.so`;
- a trusted upstream CA bundle.

Missing capabilities make the HTTPS subcomponent refuse to start; they do not affect AGH.

## Local paths

```text
/opt/etc/vward/ads-privacy-guard/https/
  https-content-guard.conf
  intercept.tsv
  bypass.tsv
  request-rules.tsv
  ca/
    vward-https-root-ca.crt
    vward-https-root-ca.key
    vward-https-leaf.key

/opt/var/lib/vward/ads-privacy-guard/https/
  runtime/
    3proxy.cfg
    vward-https-content-guard.pac
    3proxy.pid
  cert-cache/
```

Private keys are root-only and are never returned through the Console API.

## Rule format

`request-rules.tsv`:

```text
enabled<TAB>id<TAB>domain<TAB>scope<TAB>kind<TAB>value<TAB>action<TAB>comment
```

Supported in this candidate:

- scope: `exact` / `suffix`;
- kind: `path_prefix` / `path_exact`;
- action: `block`.

Arbitrary PCRE text is intentionally rejected to prevent config injection and accidental
wide matching. The renderer escapes the literal path before producing the provider rule.

## CA workflow

```text
vward-ads-privacy-https.sh ca-init --confirm
vward-ads-privacy-https.sh ca-export
```

Only the `.crt` must be installed as trusted CA on a test client. Never export or copy the
`.key` file to a client.

Android caveat: modern apps may reject user-installed CAs or use certificate pinning. In
that case the app will bypass/fail HTTPS interception even though the proxy works for a
browser. VWARD must treat this as compatibility, not as a reason to disable TLS checks.

## Start workflow

1. Install/copy local config and TSV files.
2. Set `HTTPS_GUARD_ENABLED=1`.
3. Configure a LAN `HTTPS_PROXY_BIND`, `HTTPS_PROXY_ADVERTISE_HOST` and narrow
   `HTTPS_ALLOWED_CLIENTS`.
4. Create the CA.
5. Install the CA certificate on the test client.
6. Enable only one or a few intercept domains.
7. `validate`, then `start --confirm`.
8. Configure the client to use the generated PAC.

The proxy refuses to start if upstream certificate verification cannot be configured.

## Not implemented yet

- transparent iptables/NAT interception;
- automatic QUIC suppression;
- body/JSON structural rewriting;
- DOM cosmetic filtering;
- bypass of certificate pinning;
- mobile/desktop VWARD Agent;
- automatic CA installation on clients.

These are separate follow-up capabilities and must not be represented as working UI.
