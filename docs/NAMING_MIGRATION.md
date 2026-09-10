# Миграция названий VWARD

Канонический machine-readable источник -
`config/components/component-registry.json`. Машинный ID и пользовательское имя -
разные сущности: ID используется контрактами updater, а display name можно переводить.

## Правила

1. В новом UI и актуальной документации используется одно каноническое имя.
2. Legacy-имя допустимо в истории или пояснении «ранее …».
3. `legacy_ids` не удаляются, пока опубликованные manifests/state могут их содержать.
4. Runtime filename, init name, cron command и state path не меняются без совместимой
   миграции, dependency map, backup, health-check и rollback.
5. Каталог `adaptive-routing` нельзя механически переименовать в `route-engine`: им
   владеют три логических компонента.

## Матрица

| Legacy name/path | Канонический владелец | Тип | Статус | Риск | Действие сейчас | Условие дальнейшей миграции |
|---|---|---|---|---|---|---|
| `bootstrap` | VWARD Platform Core | ID | LEGACY-COMPAT | средний | сохранить alias | опубликованные state больше не требуют ID |
| `components/adaptive-routing/` | Route Engine, Reconciler, Tools | source | DEFERRED | высокий | сохранить общий каталог | подтверждённый split package sources и CI |
| `adaptive-routing` | VWARD Route Engine | ID | LEGACY-COMPAT | средний | сохранить alias | schema migration и downgrade test |
| `components/vpn-audit/` | VWARD Policy Sync | source | DEFERRED | средний | display names унифицировать | перенесены все package/test/docs references |
| `vpn-audit` | VWARD Policy Sync | ID | LEGACY-COMPAT | средний | сохранить alias | state/manifest migration завершена |
| `components/wireguard-protection/` | VWARD Tunnel Guard | source | DEFERRED | средний | display names унифицировать | совместимый source move проверен |
| `wireguard-protection` | VWARD Tunnel Guard | ID | LEGACY-COMPAT | средний | сохранить alias | state/manifest migration завершена |
| `components/wan-guardian/` | VWARD WAN Guard | source | DEFERRED | средний | display names унифицировать | совместимый source move проверен |
| `wan-guardian` | VWARD WAN Guard | ID | LEGACY-COMPAT | средний | сохранить alias | state/manifest migration завершена |
| `components/runtime-supervision/` | VWARD Runtime | source | DEFERRED | средний | сохранить | init/package references мигрированы |
| `runtime-supervision` | VWARD Runtime | ID | LEGACY-COMPAT | средний | сохранить alias | state/manifest migration завершена |
| `components/updater/` | VWARD Update Engine | source | LEGACY-COMPAT | средний | сохранить путь | отдельный совместимый source migration |
| Smart Updater | VWARD Update Engine | UI/docs | MIGRATION-READY | низкий | заменить в текущем UI/docs | legacy остаётся только в истории |
| `updater` | VWARD Update Engine | ID | LEGACY-COMPAT | высокий | сохранить alias | все старые manifests/state выведены |
| `web/` | VWARD Console | source | CANONICAL | низкий | сохранить | переименование не даёт пользы |
| `web-ui` | VWARD Console | ID | LEGACY-COMPAT | средний | сохранить alias | state/manifest migration завершена |
| `agh-adaptive-live.sh` и другие legacy scripts | владельцы из registry | runtime | DEFERRED | высокий | не переименовывать | wrapper/symlink, cron/init, package и rollback plan |

## Порядок следующих проходов

- Phase 1: документация, UI display names, русские описания, consistency checks.
- Phase 2: внутренние source references и config aliases при сохранении совместимости.
- Phase 3: runtime/init/cron/state names только отдельными подписанными миграциями.

Любое новое переименование сначала добавляется в эту таблицу. Если невозможно доказать
upgrade и downgrade path, решение остаётся `DEFERRED`.
