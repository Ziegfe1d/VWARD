# VWARD Ads & Privacy Guard: настройки, пауза и low-load runtime

Этот документ фиксирует обязательное поведение контура в общей VWARD Console.
Отдельная страница-приложение не создаётся: настройки входят в существующий раздел
**«Настройки»**, а краткое состояние и быстрые действия доступны из карточки
«Реклама и трекинг».

## 1. Что пользователь должен уметь делать из Console

Обязательно:

- включить/выключить контур;
- поставить автоматическую работу на паузу и продолжить её;
- увидеть, идёт ли сейчас анализ, какой домен проверяется и прогресс batch;
- запустить проверку вручную;
- обновить reference-базы вручную;
- выбрать режим `manual / scheduled / dynamic`;
- настроить интервал плановой проверки;
- настроить минимальный интервал динамической проверки;
- задать resource gates, чтобы тяжёлый анализ откладывался при высокой нагрузке;
- включить/выключить автообновление reference-баз и его период;
- выбрать режим публикации и отдельно разрешить/запретить auto-publish;
- добавить собственное правило ALLOW / BLOCK;
- выбрать `exact` или `suffix` для своего правила;
- удалить локальный override;
- увидеть количество manual allow/block rules и review queue;
- вручную применить staged rules только после отдельного подтверждения.

## 2. Разница между «выключить» и «пауза»

`ENABLED=0` означает, что компонент отключён как функция. Scanner должен завершаться
без анализа.

`PAUSED=1` - runtime control state. Настройки, cache, reference indexes и verdicts
сохраняются. Scheduler не запускает автоматические scan/source actions. Ручная кнопка
«Проверить сейчас» остаётся допустимой: пользователь явно инициировал операцию.

Пауза хранится в persistent local state:

```text
/opt/var/lib/vward/ads-privacy-guard/control.state
```

и не входит в signed package.

## 3. Режимы

### manual

Никакого автоматического анализа. Доступны ручные `scan`, `sources-update`, probe,
локальные ALLOW/BLOCK и staged publish.

### scheduled

Один lightweight scheduler tick запускается раз в минуту, но тяжёлый classifier
стартует только когда наступил `SCHEDULE_INTERVAL_MIN` и прошли resource gates.

Scheduler tick сам по себе не должен читать целиком большие HaGeZi/AdGuard indexes.

### dynamic

Это low-load near-continuous mode, а не тяжёлый scan каждую минуту.

Tick:

1. проверяет ENABLED / PAUSED;
2. проверяет, изменился ли persisted AdGuard Home query log;
3. проверяет минимальный интервал;
4. проверяет load average, MemAvailable и свободное место `/opt`;
5. проверяет отсутствие уже работающего classifier;
6. только после этого запускает уменьшенный batch.

Поскольку AdGuard Home буферизует query log, режим не обещает секундный real-time.
Он реагирует на новые **persisted** записи настолько быстро, насколько их пишет AGH.

## 4. Resource gates

Console-safe параметры:

```text
DYNAMIC_MAX_LOAD_PER_CPU_X100=80
DYNAMIC_MIN_MEM_AVAILABLE_KB=16384
DYNAMIC_MIN_OPT_FREE_KB=32768
DYNAMIC_MAX_CANDIDATES_PER_RUN=100
DYNAMIC_SCAN_TAIL_LINES=5000
```

Load gate нормируется по числу logical CPU:

```text
load1 * 100 <= cpu_count * DYNAMIC_MAX_LOAD_PER_CPU_X100
```

Если gate не пройден, scheduler возвращает `DEFERRED`, ничего не ломает и пытается
снова на следующем tick.

## 5. Почему scheduler один

Не рекомендуется иметь одновременно несколько cron entries вида `*/10 scan`,
`daily sources-update`, отдельный dynamic daemon и UI timers. Это создаёт гонки и
усложняет pause/resume.

Предлагаемый единственный cron owner:

```text
* * * * * /opt/bin/vward-ads-privacy-scheduler.sh ...
```

Сам scheduler решает, что действительно пора делать.

## 6. Что показывать в «Текущая проверка»

Volatile status:

```text
/tmp/vward-ads-privacy-guard-current.status
/tmp/vward-ads-scheduler.status
```

Поля минимум:

- `phase`;
- `mode`;
- `domain`;
- `current / total`;
- scheduler `reason`;
- `next_due_epoch`;
- timestamp.

Status в `/tmp` намеренно не пишет каждый домен на флешку.

## 7. Свои правила

Local allowlist и denylist остаются authoritative manual overrides:

```text
/opt/etc/vward/ads-privacy-guard/allowlist.tsv
/opt/etc/vward/ads-privacy-guard/denylist.tsv
```

Формат:

```text
domain|exact|note
domain|suffix|note
```

Приоритет:

```text
manual ALLOW / Never Auto Block
        > automatic verdict
manual BLOCK
        > automatic ALLOW/TRUST cache
```

`scope=suffix` нельзя включать автоматически: только явным выбором пользователя.

## 8. Публикация отделена от анализа

Даже если режим dynamic включён, это не означает, что AGH будет изменяться после
каждого scan.

Два независимых предохранителя:

```text
PUBLISH_MODE=staged|user_rules_api
AUTO_PUBLISH=0|1
```

Без `AUTO_PUBLISH=1` classifier только обновляет managed rule set. Ручная кнопка
«Применить» требует confirm token.

## 9. Settings API

Нельзя передавать содержимое config как произвольный shell text.

Console может менять только whitelist параметров через `vward-ads-privacy-settings.sh`:

- строгая валидация каждого значения;
- timestamped backup;
- temp file;
- `sh -n`;
- atomic replace;
- rollback при ошибке;
- audit log.

Enabling `AUTO_PUBLISH=1` требует отдельного подтверждения.

## 10. UI layout

В существующем разделе «Настройки» три панели:

1. **Реклама и трекинг** - master switch, mode, intervals, resource gates, source
   refresh, publication policy.
2. **Текущая проверка** - live status, progress, next run, `Проверить сейчас`,
   `Обновить базы`, `Применить`.
3. **Свои правила** - domain, exact/suffix, always allow, always block, remove.

Рабочая реализация встроена в `web/index.html`, `web/assets/vward-console.css`,
`web/assets/vward-console.js` и `web/cgi-bin/api.cgi`.

## 11. Acceptance для low-load режима

Перед интеграцией измерить на целевом Keenetic:

- idle cost минутного scheduler tick;
- peak CPU и duration одного dynamic batch;
- flash read volume с полными PRO/PRO++ indexes;
- RAM во время source update/classification;
- задержку других VWARD cron jobs;
- отсутствие параллельных scan instances;
- корректность pause/resume после reboot;
- dynamic mode при неизменившемся query log не должен запускать classifier.

Если полные reference indexes дают слишком большой I/O, integration pass должен
перейти на bucketed/on-disk lookup index, а не увеличивать частоту полного scan.
