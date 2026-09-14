# VWARD Ads & Privacy Guard: security model

## Основные риски

Новый контур сам получает сторонние данные и потенциально управляет DNS-блокировкой.
Следовательно его failure mode должен быть fail-safe, а не "блокировать побольше".

## Защитные правила

### 1. Remote feed не является executable input

Downloaded content только нормализуется в domain index. Ни одна строка feed не
исполняется shell'ом и не подставляется в командную строку.

### 2. Консервативный parser

Browser path/regex/cosmetic rules игнорируются. Это уменьшает риск превратить URL-rule
в ложный domain-wide block.

### 3. Last-known-good source cache

Неудачное обновление не обнуляет рабочий source index.

### 4. Correlated sources

Weight считается по independence group. PRO + PRO++ и другие родственники не должны
искусственно повышать confidence.

### 5. Heuristic != proof

TLD, lexical pattern и burst activity могут дать SUSPECT, но не BLOCK.

### 6. Trust/allow overrides

Local allowlist имеет приоритет и означает Never Auto Block. Broad vendor wildcard
по умолчанию запрещён организационной политикой.

### 7. No silent auto-unblock

Исторический BLOCK при потере evidence переводится в revalidation review, сохраняя
`action=BLOCK`.

### 8. Publisher отделён от classifier

Default `PUBLISH_MODE=staged`. Даже ошибка classifier не должна напрямую переписать
AdGuard Home.

### 9. AGH API publication transaction

For optional `user_rules_api` backend:

- read current `filtering/status`;
- save the complete previous `user_rules` array;
- remove only an existing VWARD marker block;
- append the newly generated VWARD marker block;
- submit the complete merged array through `filtering/set_rules`;
- read back and verify markers/expected rules;
- roll back the complete previous array on write/verification failure.

Manual/unrelated AGH user rules outside the VWARD markers are preserved. Candidate
v5 never edits `AdGuardHome.yaml` directly and never restarts AGH for rule publication.

### 10. Device-specific values

Ads & Privacy Guard contains no hardcoded current-device LAN address, subnet, AGH
port or interface names. AGH API address/port are derived from the VWARD Device
Profile unless a local component config explicitly overrides `AGH_API_BASE`.

### 11. External verifier boundary

External verifier не включён по умолчанию. Его вывод имеет простой contract, а сам
provider должен проходить отдельный security review: TLS, auth secret storage,
timeouts, data minimization и rate limits.

## Privacy

Query log содержит client IP и историю доменов. VWARD хранит агрегированный verdict
state; публикация source candidate не должна содержать пользовательский query log.
Console должна отдавать только нужные агрегаты и ограниченный review list.

### 12. Console settings are not arbitrary shell input

The web UI must never write raw text into `ads-privacy-guard.conf`. Only a fixed set of
keys and strict enum/integer ranges are accepted by `vward-ads-privacy-settings.sh`. Every
save creates a timestamped backup, builds a temp file, checks shell syntax, installs
atomically and records an audit event.

`AUTO_PUBLISH=1` and manual publish require explicit confirmation paths.

### 13. Low-load scheduler safety

A one-minute scheduler tick is intentionally cheap. It must not imply a one-minute
full scan of large PRO/PRO++ indexes. Before classifier execution it checks pause,
query-log change, elapsed interval, scan lock, load average per CPU, available memory
and free `/opt` space. A failed resource gate yields `DEFERRED`, not a forced scan.

### 14. Lock ownership and stale recovery

Component locks are atomic root-only directories containing PID, acquisition epoch and
the Linux process starttime. PID plus starttime prevents a recycled PID from being
mistaken for the original owner. Stale takeover first atomically renames the old lock,
so competing breakers cannot delete a successor's lock. Release verifies ownership and
removes only known metadata files; symlink lock paths are rejected and recursive deletion
of the public lock path is forbidden.

### 15. HTTPS Content Guard isolation

HTTPS Content Guard is disabled by default and uses explicit-proxy mode only. It does not
own iptables/NAT state. CA private keys are root-only local files and are never returned by
Console/API output. Only the public CA certificate may be exported. Upstream TLS
verification is mandatory; failure to find a trusted CA bundle prevents startup.

PAC bypass rules are evaluated before intercept rules. Arbitrary PCRE is not accepted from
local rule TSV in v6; only validated literal path_exact/path_prefix values are escaped into
provider rules. Missing 3proxy/SSLPlugin/PCREPlugin capability fails the HTTPS subcomponent
without affecting DNS/AGH operation.
