# VWARD Ads & Privacy Guard: политика источников

## Назначение source registry

Reference feeds - это evidence database для VWARD. Они не обязаны одновременно быть
активными подписками AdGuard Home.

Это особенно важно для роутера с ограниченной RAM: полный HaGeZi PRO/PRO++ можно
держать как нормализованный дисковый index и проверять только новые домены, сохраняя
в AGH более лёгкий active filter set.

## Initial registry

| ID | Семейство | Назначение | Weight | Single-source block |
|---|---|---|---:|---|
| `hagezi-pro` | HaGeZi | ads/tracking/security | 85 | no |
| `hagezi-pro-plus` | HaGeZi | более агрессивное evidence | 80 | no |
| `hagezi-popup` | HaGeZi Popup | popup ads | 100 | yes |
| `adguard-dns` | AdGuard/EasyList family | DNS ads/tracking | 90 | no |
| `adguard-popup` | AdGuard Popup | popup hosts | 100 | yes |
| `easylist` | AdGuard/EasyList family | ads | 75 | no |
| `easyprivacy` | AdGuard/EasyList family | tracking | 70 | no |
| `oisd-small` | OISD | ads-focused | 70 | no |
| `onehosts-lite` | 1Hosts | ads/tracking/security | 70 | no |
| `peter-lowe` | Peter Lowe | ads/tracking | 65 | no |
| `stevenblack` | StevenBlack | ads/malware | 65 | no |
| `awavenue-ads` | AWAvenue | mobile ads | 70 | no |
| `shadowwhisperer-tracking` | ShadowWhisperer | tracking | 60 | no |

Initial registry intentionally remains curated rather than attempting to ingest every list on the Internet. New sources are data-driven entries in `source-registry.json` and do not require classifier code changes.

Weights - policy VWARD, а не утверждение авторов списков о качестве.

## Почему PRO и PRO++ оба есть

Пользовательская задача требует проверять пропущенный AGH домен максимально широко.
PRO++ может содержать записи, которых нет в PRO. Но оба относятся к одной evidence
family, поэтому наличие домена сразу в обоих **не считается независимым двойным
подтверждением**.

## Почему EasyList/EasyPrivacy не загружаются целиком как browser rules

EasyList содержит URL-path, resource type и cosmetic правила. На DNS-уровне нельзя
безопасно интерпретировать их все. VWARD извлекает только явно domain-anchored правила
и тем самым использует список как conservative DNS evidence source.

## Source health

Updater:

- загружает источники последовательно;
- ограничивает размер;
- нормализует;
- проверяет минимальное число записей;
- ставит файл атомарно;
- при ошибке оставляет last-known-good index;
- пишет per-source metadata и aggregate status.

Если healthy source indexes меньше минимального числа, неизвестный домен не получает
долгий ALLOW cache; он остаётся SUSPECT с короткой перепроверкой.

## Лицензии

VWARD source registry содержит только URL/metadata и **не перепубликует contents
сторонних списков**. При распространении bundled snapshots в будущем нужно отдельно
проверять лицензии каждого upstream. В текущем дизайне snapshots остаются runtime
cache и не входят в репозиторий/package.

## Источники для последующей проверки перед merge

- HaGeZi DNS Blocklists: `https://github.com/hagezi/dns-blocklists`
- AdGuard DNS Filter: `https://github.com/AdguardTeam/AdGuardSDNSFilter`
- AdGuard Hostlists Registry: `https://github.com/AdguardTeam/HostlistsRegistry`
- EasyList/EasyPrivacy: `https://easylist.to/`
- OISD: `https://oisd.nl/`
- 1Hosts: `https://github.com/badmojr/1Hosts`

Перед фактическим merge source URLs/min counts нужно повторно smoke-test'ить в CI.
