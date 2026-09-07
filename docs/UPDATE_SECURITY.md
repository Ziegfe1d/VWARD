# Smart Updater v1 security model

Authenticity uses an offline Ed25519 private key and a pinned public key on the router. Publishers sign canonical `jq -cS '.signed'` bytes. The private key must never be stored in this repository or on the router.

- HTTPS protects transport.
- Ed25519 signature verifies authenticity.
- SHA-256 and exact byte counts verify package/payload integrity.
- `trust.state` prevents signed replay/downgrade by remembering the highest accepted sequence independently of rollback.
- `quarantine.state` prevents unattended retry loops for known-bad signed updates.

Package transport is bounded by the signed compressed size and configured maximum. The signed manifest also carries `package.unpacked_size`; preflight reserves compressed + unpacked space, tar metadata is checked before extraction, and extracted regular-file bytes are checked again after extraction. This limits decompression-bomb/staging exhaustion scenarios.

Install targets are exact VWARD-owned paths from the verified installation map; generic `/opt/bin/*.sh` and generic init.d patterns are not accepted. Local configuration, generated hints, runtime state, logs, backups and credentials remain forbidden package targets.

All authenticity/integrity/trust failures are fail-closed. The included example public key is intentionally non-functional; production key provisioning and target Entware OpenSSL/tar/curl validation remain prerequisites for deployment.
