# Классификация файлов

Исходный архив роутера содержал 36 файлов. SHA-256 архива и 34 записи внутреннего
`SHA256SUMS` были проверены до импорта.

## Публикуемый source

- рабочие shell-скрипты и init scripts;
- VWARD Console и CGI API;
- очищенные примеры `force-vpn.conf` и `services.conf`;
- восемь production cron entries в `config/cron/root.crontab`;
- schemas, public verification key и документация.

## Generated

`/opt/etc/vward/route-engine/hints.conf` создаётся из внешних allow-domain lists. Он не
публикуется как source.

## Local configuration и state

- `skip-domains.conf` - локальная routing policy;
- `tunnel-guard.disabled` - control state, отсутствовавший в snapshot;
- `/opt/var/lib`, `/opt/var/log`, `/tmp`, backups и PID/lock files.

Они сохраняются при обновлении и не входят в package payload.

## Непубликуемые snapshot metadata

Inventory, collection notes, security-candidate output, package inventory, crontab
installation-path note и локальные состояния нужны для аудита, но не являются
программой. Существенные факты перенесены в документацию.

## Сторонние файлы

VWARD не публикует binaries Entware, AdGuard Home, curl, jq, lighttpd, crond или
tcpdump. Они остаются внешними зависимостями.

История Git не переписывалась. Устаревшие placeholders были удалены обычными commits.
