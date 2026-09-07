# Smart Updater v1 security model

Authenticity uses an offline Ed25519 private key and a pinned public key on the router. The private key must never be present in this repository or on the router. Publishers serialize only the signed object with jq -cS, sign those exact bytes, and store the Base64 signature beside it. The router reconstructs the same canonical bytes and verifies them with OpenSSL before trusting metadata.

The package is protected by the SHA-256 digest and byte size inside the signed manifest. Its own package-manifest.json binds each source payload to a target path, mode and SHA-256 digest. Extraction rejects absolute paths and parent traversal. Installation permits only explicit program-path families and rejects configuration, state, temporary, backup and known device-local files.

HTTPS protects transport but does not replace signature verification. Sequence and version checks resist replay and downgrade. All verification failures are fail-closed.

The included public-key.example is deliberately non-functional. A real project public key and an independently reviewed release-signing procedure are prerequisites for deployment.
