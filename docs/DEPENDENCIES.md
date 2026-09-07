# Dependencies

This list is based on command references in the imported source and the package inventory of the working installation.

## KeeneticOS requirements

- `ndmc` and Keenetic RCI on `127.0.0.1:79`;
- interface and FQDN object-group commands used by the scripts;
- standard Keenetic interface state and running-configuration output;
- a compatible BusyBox base for `sh`, `awk`, `sed`, `grep`, `sort`, `wc`, `tail`, `tr`, `cut`, `date`, `sleep`, `mkdir`, `mv`, `cp`, `rm`, `pidof`, `killall`, `nslookup`, `ping` and related utilities.

## Required Entware packages

- `curl` — HTTP probes, RCI queries and generated hint downloads;
- `jq` — JSON parsing and CGI output;
- `tcpdump` — live DNS observation;
- `lighttpd` — local dashboard service;
- `lighttpd-mod-cgi` — CGI API;
- `busybox` — Entware shell/crond and core utilities used by init scripts;
- `ca-bundle` — TLS validation for HTTPS requests.
- `openssl-util` (conditional) — Ed25519 manifest verification for Smart Updater v1;
- `tar` with gzip support (conditional) — updater package inspection and staging.

Package dependencies such as `libcurl`, `libopenssl`, `libpcap`, `zlib` and the C runtime are resolved by Entware and are not direct VWARD install targets.

## Conditional integration

- `adguardhome-go` is required only for the AdGuard Home query-log discovery path; VWARD does not vendor its binary or database.
- `opt-ndmsv2` provides Entware/Keenetic integration on the working installation.

`wget` is not a direct requirement of the imported working VWARD. The obsolete UI-only `scripts/update-ui.sh` was removed. Smart Updater v1 is implementation-stage, disabled and not deployed; it does not yet constitute a supported GitHub-to-router updater. Its deployment gates are documented in [UPDATER_ARCHITECTURE.md](UPDATER_ARCHITECTURE.md).
