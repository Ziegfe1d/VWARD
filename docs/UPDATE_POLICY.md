# Политика VWARD Update Engine

Update Engine развёрнут и принят на целевом роутере. `auto_apply` - master switch;
`auto_critical`, `auto_important`, `auto_routine` отдельно разрешают unattended apply.

- **CRITICAL** - первая hard-safe точка; clock window можно обойти, остальные safety
  checks обязательны.
- **IMPORTANT** - предпочтительно safe window; после configured deadline разрешена
  первая hard-safe точка вне окна.
- **ROUTINE** - quiet window; после более длинного deadline разрешена hard-safe точка.

`apply_window` задаёт, ждут ли IMPORTANT и ROUTINE окна: `window` (по умолчанию) - как
выше; `any` - устанавливаются в первой hard-safe точке сразу после проверки («Автоматически»
в Console). Подпись, trust, replay, compatibility и health checks от этого не зависят.

Канал в Console («Бета» / «Dev») - это ветка, чей подписанный feed читает updater: меняется
только ветка в стандартном `manifest_url`
(`https://raw.githubusercontent.com/<owner>/<repo>/<beta|dev>/updates/<feed>/update-manifest.json`).
Подписанный `channel`, ключ и защита от отката версии не меняются: после перехода с Dev на
бету обновления придут, когда бета догонит установленную версию. Свой адрес манифеста Console
не переписывает.

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
