# Политика VWARD Update Engine

Update Engine развёрнут и принят на целевом роутере. `auto_apply` - master switch;
`auto_critical`, `auto_important`, `auto_routine` отдельно разрешают unattended apply.

- **CRITICAL** - первая hard-safe точка; clock window можно обойти, остальные safety
  checks обязательны.
- **IMPORTANT** - предпочтительно safe window; после configured deadline разрешена
  первая hard-safe точка вне окна.
- **ROUTINE** - quiet window; после более длинного deadline разрешена hard-safe точка.

Verified deferred update сохраняется между watcher cycles и reboot. HTTP 304 без
pending и exact already-installed manifest по HTTP 200 считаются no-update.

## Trust и replay

- `committed.state` - что установлено;
- `trust.state` - highest accepted signed sequence;
- `quarantine.state` - release, который нельзя повторять unattended;
- `pending/` - verified update, ожидающий применения.

Rollback не уменьшает trust sequence. Lower sequence отклоняется. Повтор highest
sequence допустим только при совпадении update ID и canonical signed-manifest hash.
Изменённое содержимое с тем же sequence отклоняется.
