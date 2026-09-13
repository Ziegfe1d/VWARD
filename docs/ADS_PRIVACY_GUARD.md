# VWARD Ads & Privacy Guard: архитектура контура

## Цель

Контур закрывает разрыв между двумя классами решений:

- AdGuard Home быстро блокирует то, что уже известно его активным фильтрам;
- VWARD Ads & Privacy Guard периодически изучает **разрешённые** DNS-запросы и ищет
  домены, которые первая линия пропустила.

Контур не пытается заменить браузерный cosmetic filtering. DNS-система может
заблокировать отдельный рекламный/redirect/telemetry host, но не способна удалить
HTML/CSS/JavaScript-элемент, который отдается с того же origin, что и полезный сайт.

## Конвейер

```text
AdGuard Home persisted query log
        |
        | Result.IsFiltered != true
        v
Normalization / noise removal
        |
        +--> manual allowlist / Trust Registry ----> TRUST/ALLOW cache
        |
        +--> fresh verdict cache ------------------> reuse verdict
        |
        v
Reference evidence indexes
        |
        +--> dedicated high-confidence feed ------> BLOCK
        |
        +--> >= 2 independent evidence groups
        |    + score threshold -------------------> BLOCK
        |
        +--> weak/one-source evidence ------------> SUSPECT
        |
        v
Deep/review stage
        |
        +--> local frequency / clients / lexical/TLD context
        +--> single-domain probe
        +--> optional RDAP
        +--> optional external verifier provider
        |
        +--> evidence insufficient ---------------> ALLOW (TTL cache)
        +--> suspicious only ---------------------> SUSPECT
        +--> provider/high-confidence evidence ---> BLOCK
        v
VWARD-managed rules
        |
        +--> staged (default)
        +--> local filter file (optional)
        +--> managed AGH user_rules (optional)
```

## 1. Вход: только то, что AGH пропустил

Основной скрипт читает `querylog.json` и `.1` и использует фактическую схему AGH:

- домен: `.QH`;
- клиент: `.IP`;
- решение: `.Result.IsFiltered`;
- время: `.T`.

В анализ попадает только `Result.IsFiltered != true`.

Исключаются:

- `in-addr.arpa`;
- `ip6.arpa`;
- local/LAN names;
- синтаксически некорректные домены.

AdGuard Home буферизует query log, поэтому этот контур проектируется как periodic
analysis, а не real-time packet engine. Для real-time DNS observation в VWARD уже
существует другая ответственность; новый контур не должен смешиваться с ней.

## 2. Trust Registry

Trust Registry решает задачу: не перепроверять Google/Yandex/Apple/Ozon и другие
известные безопасные сервисы каждый цикл.

Но доверие **не наследуется автоматически на весь vendor namespace**. Например,
`google.com` и `www.google.com` могут быть trusted exact entries, но это не означает
`*.google.com`, потому что у крупных вендоров встречаются telemetry/ad endpoints.

Формат built-in/local trust:

```text
pattern|scope|class|recheck_days|never_auto_block|note
```

`scope`:

- `exact` - только конкретное имя;
- `suffix` - имя и его поддомены; используется только намеренно.

Local allowlist имеет самый высокий приоритет и означает `Never Auto Block`.

## 3. Verdict cache

Повторная проверка домена не выполняется до `next_check_epoch`.

Рекомендуемая политика:

- TRUST: 180+ дней;
- ALLOW: 30 дней по умолчанию;
- SUSPECT: 24 часа;
- BLOCK: revalidation раз в 30 дней.

Это резко сокращает CPU/I/O и сетевые запросы на маломощном Keenetic.

## 4. Reference feeds

Полные PRO/PRO++/EasyList и т.п. используются **не как активный AGH filter set**, а
как локальные reference indexes VWARD. Это позволяет иметь широкое покрытие без
загрузки всех больших списков в runtime-фильтрацию AdGuard Home.

Каждый источник имеет:

- `vendor`;
- `independence_group`;
- `purpose`;
- `weight`;
- `single_source_block`;
- формат;
- минимальный health count;
- max download size;
- primary/fallback URLs.

Нормализатор намеренно принимает только DNS-safe правила:

- `||domain.example^`;
- HOSTS `0.0.0.0 domain.example` / `127.0.0.1 ...`;
- plain domains.

Не извлекаются:

- cosmetic rules;
- URL path patterns;
- regex;
- exception rules `@@`;
- browser-only resource rules.

Это важный false-positive barrier.

## 5. Independence groups

Два списка одного семейства не считаются двумя независимыми подтверждениями.
Например HaGeZi PRO и PRO++ имеют один evidence group, а EasyList/EasyPrivacy и
AdGuard DNS Filter объединены в коррелированную семью для scoring.

Итоговый score считается как **максимальный weight на independence_group**, а не
сумма всех совпавших файлов.

## 6. Автоматический BLOCK

BLOCK разрешён только в одном из случаев:

1. domain match в dedicated high-confidence feed с `single_source_block=true`
   (например Pop-Up Ads);
2. совпадение минимум в `MIN_INDEPENDENT_GROUPS` evidence groups и итоговый score
   выше `BLOCK_SCORE`;
3. manual denylist;
4. подключенный external verifier возвращает явный BLOCK по своему контракту.

Heuristics никогда не дают auto-block сами по себе.

## 7. Неизвестные домены

Если домен отсутствует в reference feeds, VWARD оценивает локальные сигналы:

- частоту запросов;
- число клиентов;
- подозрительный TLD;
- advertising/tracking lexical markers;
- текущую историю AGH;
- optional DNS/RDAP/provider evidence через `vward-ads-privacy-probe.sh`.

Эти признаки отправляют домен в SUSPECT/Review, но не блокируют его автоматически.

Причина принципиальная: роутер не имеет встроенного универсального web-search/AI
reputation engine. Притворяться, что одно имя `.xyz` или слово `track` доказывает
рекламность, опасно. Для третьего этапа предусмотрен provider contract:

```text
EXTERNAL_VERIFIER_COMMAND=/opt/bin/...
```

Команда получает DOMAIN и должна вывести одну строку:

```text
VERDICT|CONFIDENCE|REASON
```

Это место для будущего reputation service, собственного VWARD cloud verifier или
другого проверенного источника.

## 8. Защита от ошибочного автоматического разблокирования

Если домен раньше имел `action=BLOCK`, а при плановой revalidation evidence исчезло,
он **не переводится автоматически в ALLOW**. Verdict становится SUSPECT, но action
остаётся BLOCK до review/allowlist.

Это защищает от:

- временно недоступного feed;
- удаления записи из upstream из-за технической ошибки;
- неполного source update;
- изменения scoring.

## 9. Generated filter

Authoritative output:

```text
/opt/var/lib/vward/ads-privacy-guard/generated/vward-ads-privacy-guard.rules
```

Пример:

```text
! VWARD Ads & Privacy Guard
! generated: ...
||example-ad-domain.xyz^
```

Файл generated/state и не должен входить в signed source package.

## 10. Публикация

Публикация отделена от classifier.

### `staged`

Default. Только строит generated rules. AdGuard Home не изменяется.

### `user_rules_api`

Live publisher candidate through the official AdGuard Home filtering API. It reads
the complete `user_rules` array, removes only a previous marker-delimited VWARD block,
preserves all unrelated rules, appends the new VWARD block and submits the complete
array through `filtering/set_rules`. The result is read back and verified. A failed
write or verification triggers a best-effort API rollback to the saved previous array.

No direct `AdGuardHome.yaml` rewrite and no AGH restart are part of candidate v5.
Default remains `staged` until live Dev staging confirms API compatibility on the
target AdGuard Home build.

## 11. Runtime modes and Console control

Candidate v5 adds an explicit runtime-control layer. Automatic work is owned by
`vward-ads-privacy-scheduler.sh`, not by multiple unrelated cron entries.

Modes:

- `manual` - only explicit user scan;
- `scheduled` - batch analysis on a configured interval;
- `dynamic` - near-continuous low-load mode triggered by persisted AGH query-log
  changes, with minimum interval and CPU/RAM/storage gates.

`PAUSED` is separate from `ENABLED`. Pause stops automatic scheduler actions but keeps
state/config and permits an explicit manual scan. Current phase/domain/progress is
written only to `/tmp` to avoid flash churn.

Settings are managed by a whitelist backend with backup/validation/atomic replace.
`PUBLISH_MODE` and `AUTO_PUBLISH` are separate, so analysis can run continuously
without automatically changing AdGuard Home.

Detailed contract: `docs/ADS_PRIVACY_GUARD_SETTINGS_AND_RUNTIME.md`.
