# Безопасность VWARD Update Engine

Authenticity обеспечивает offline Ed25519 private key и pinned public key на роутере.
Подписываются canonical bytes `jq -cS '.signed'`. Private key никогда не хранится в
репозитории или на роутере.

- SHA-256 и exact byte counts проверяют package/payload integrity.
- `trust.state` предотвращает signed replay и downgrade.
- Signed compressed/unpacked sizes, preflight reserve, tar metadata и повторная
  проверка extracted bytes ограничивают decompression-bomb/staging exhaustion.
- Разрешены точные VWARD-owned targets; generic `/opt/bin/*.sh` и init patterns
  запрещены.
- Local config, state, logs, backups и credentials не являются package targets.
- Любая ошибка authenticity/integrity/trust обрабатывается fail-closed.

Example public key намеренно непригоден для production. Production key provisioning
и проверка совместимости OpenSSL/tar/curl обязательны.
