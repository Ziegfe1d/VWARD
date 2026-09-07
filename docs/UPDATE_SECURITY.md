# Smart Updater security model

VWARD unattended updates require three independent protections:

- HTTPS protects transport.
- Ed25519 authenticates the canonical `.signed` manifest.
- SHA-256 verifies the compressed package and every installable payload file.

Authenticity/integrity failures are fail-closed.

## Replay protection

A valid signature is not enough to make an old release acceptable. `trust.state` stores the monotonic `highest_seen_sequence`, update ID and canonical signed-manifest hash. A lower sequence is rejected. Reuse of the highest sequence is allowed only for the exact same signed update. Rollback never lowers this ledger.

## Package/resource limits

The signed package contains `size` and `unpacked_size`. Local policy additionally caps `max_manifest_size`, `max_package_size` and `max_unpacked_size`. Package transfer is bounded while downloading and is checked again by exact byte size and SHA-256. Extracted regular-file bytes must not exceed the signed/local unpacked limit.

Package entries may only be regular files/directories, may not traverse paths, and payload targets must match the exact VWARD ownership allow-list derived from the installation map. Generic `/opt/bin/*.sh` and generic init.d patterns are intentionally forbidden.

No private signing key is committed to the repository. The example public key is not a production trust anchor.
