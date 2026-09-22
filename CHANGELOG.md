# Changelog

## Не выпущено: Device Profile без привязки к модели и именам интерфейсов

- Device Profile строит карту интерфейсов через Keenetic RCI (`show interface`,
  `show interface system-name`) и running-config, кэш `/tmp/vward-device-map.tsv` на 5 минут.
- WireGuard-туннели ищутся по типу интерфейса, а не по именам `Wireguard0/1`, `nwg*` или
  `wg*`. При нескольких туннелях выбирается единственный, на который ссылаются
  существующие маршруты; иначе профиль отказывает со списком кандидатов.
- Автоматически определяются `VWARD_WAN_INTERFACE`, новый `VWARD_LAN_INTERFACE`
  (домашний сегмент, с учётом гостевых сегментов по `security-level`) и `VWARD_POLICY_GROUP`.
- Исправлено: ошибки `vward_profile_load` не прерывали загрузку и функция возвращала 0;
  теперь любая ошибка профиля действительно fail-closed.
- Wi-Fi Client Guard определяет диапазон точки доступа по `band`/каналу радиомодуля
  вместо имён `WifiMaster0/1`, а домашний мост берёт из профиля вместо `Bridge0`.
- Console считает WireGuard по типу интерфейса и показывает домашний сегмент; из UI и
  документации убрана привязка к KN-1913.

## 0.2.0-dev.9: Wi-Fi Client Guard foundation

- Добавлен новый канонический компонент `VWARD Wi-Fi Client Guard` только в ветку
  `dev`; beta-feed и beta runtime не изменяются.
- Заложен read-only мониторинг `show associations` с нормализацией MAC/AP/RSSI,
  ограниченной историей сэмплов и фиксацией переходов между 2.4 и 5 ГГц.
- Добавлен анализатор, который формирует `OK/WARNING` и рекомендации `bind_2g/review`
  по настраиваемым порогам, не меняя конфигурацию роутера.
- Добавлен отдельный control-контур только для `bind-2g`, `bind-5g` и `auto`:
  строгая валидация MAC/Bridge, explicit confirmation, backup running-config,
  сохранение startup configuration, acceptance и попытка rollback при ошибке.
- `CONTROL_ENABLED=0` и `AUTO_APPLY=0` являются безопасными значениями по умолчанию;
  cron и изменяющий Console API пока не подключаются до live read-only acceptance.
- Component registry, package map, updater allowlist/health profile, Console display
  mapping, документация и repository consistency checks синхронизированы.

## 0.2.0-dev.8: Ads & Privacy Guard integration candidate

- Добавлен source/design-кандидат `VWARD Ads & Privacy Guard` с безопасным
  управлением правилами AdGuard Home, источниками, расписанием и ручными решениями.
- Добавлен консервативный классификатор доменов с каталогами Steam, Epic Games,
  4PDA, X/Twitter и 18+, блокировками конкурентной записи и dry-run миграцией.
- Подготовлен выключенный по умолчанию HTTPS Content Guard в режиме explicit proxy;
  автоматическая подмена сертификатов, прозрачный перехват и guessed-правила запрещены.
- Добавлены фрагменты интеграции в существующий VWARD Console и выполнена визуальная
  полировка: типографика, сетка, отступы, тени, состояния кнопок и адаптивность.
- Добавлены BusyBox/POSIX-симуляции, проверки настроек, безопасности, блокировок и
  атомарной публикации. Установка на роутер и подписанный dev-feed этим коммитом не выполняются.
- Reclaim-токен Update Engine привязан к `boot_id`; оставшийся после аварийного
  завершения gate снимается только boot-recovery и только для предыдущей загрузки.
- Boot-recovery атомарно переносит подтверждённый orphan reclaim в карантин;
  same-boot, malformed, foreign и symlink-состояния остаются fail-closed.

## 0.2.0-dev.7: настраиваемый обзор и компактные настройки

- Удалены неинформативные мини-графики с карточек обзора; детальные графики
  компонентов остаются только там, где появляется реальная история замеров.
- Карточка хранилища получила компактный индикатор заполнения, а карточки обзора
  можно скрывать, возвращать, переставлять стрелками и перетаскивать мышью.
- Перестроена мобильная карточка: иконка, статус, название и метрики больше не
  конкурируют за одну узкую строку; длинные названия не разбиваются по буквам.
- Увеличены иконки и подписи нижней навигации, особенно действие обновления.
- Технические параметры Settings Registry сгруппированы в сворачиваемые разделы;
  источники и причины ограничений вынесены на второй уровень раскрытия.
- Сохранён единый лёгкий HTML-каркас с общими внешними CSS/JS: дробление на набор
  дублирующихся страниц не применяется, поскольку не снижает нагрузку lighttpd.

## 0.2.0-dev.6: адаптивный центр управления

- Мобильные карточки, панели, статистика, действия и журналы сведены к единой
  адаптивной сетке для экранов от 320 px; нижняя навигация учитывает safe-area и
  больше не перекрывает содержимое.
- Пустые графики теперь занимают одну компактную строку до второго реального
  замера вместо больших пустых областей; технические состояния на обзорных
  карточках переведены в понятные подписи.
- Settings Registry расширен до 32 фактических параметров: добавлены канал,
  расписание, лимиты, тайм-ауты, резервирование и runtime barrier Update Engine.
- Защитные и пока не поддержанные backend-настройки показаны честно в режиме
  read-only; URL манифеста, путь публичного ключа и служебный version-file в API
  каталога не публикуются.
- Добавлена регрессионная проверка responsive-контракта Console и расширен
  сквозной тест типизированных значений Settings API.

## 0.2.0-dev.5: единый каталог настроек

- Добавлен формальный Settings Registry со схемой и 17 параметрами Device Profile
  и Update Engine.
- Новый read-only API `settings-data` возвращает текущие и эффективные значения,
  источник, тип, риск, требование перезапуска, validation и причину ограничения.
- HTML-центр настроек строит единый каталог из API и группирует параметры по
  назначению вместо дублирования статических карточек.
- Device Profile остаётся read-only до настоящей авторизации; CSRF-заголовок не
  выдаётся за подтверждение пользователя.
- Registry включён в component ownership, updater allowlist, health checks и карту
  установки; добавлен сквозной тест registry → CGI API → типизированный JSON.

## 0.2.0-dev.4: аудит Console и строгий CSP

- CSS и JavaScript вынесены из HTML в локальные assets; CSP больше не конфликтует
  со страницей, а inline-style устранены.
- Исправлена ранняя ошибка инициализации JavaScript, добавлены тайм-ауты запросов,
  предупреждение о несохранённых настройках и мобильный переход в Security.
- Security API читает сгенерированную конфигурацию lighttpd, проверяет bind/port,
  состояние сокета, `mod_setenv` и `lighttpd -tt`, сохраняя `UNKNOWN`, когда факт
  нельзя подтвердить.
- Адрес и порт AdGuard Home перенесены в Device Profile и используются Console.
- WAN Guard использует профильный интерфейс, несколько default route считаются
  неоднозначностью, а tcpdump получает раскрытый безопасный фильтр без `eval`.
- Assets добавлены в registry, updater allowlist, health profile, карту установки
  и регрессионные проверки. Переходный Beta workflow оставлен неизменным.

## 0.2.0-dev.3: Device Profile и VWARD Security

- Фиксированные LAN address/subnet, DNS, WAN device, tunnel device/interface и
  policy group удалены из runtime-компонентов и сведены в единый Device Profile.
- Добавлено fail-closed обнаружение: неоднозначный WAN, LAN или туннель не выбирается
  автоматически.
- Конфигурация lighttpd генерируется init-скриптом из проверенного профиля; wildcard
  bind не используется.
- В Console добавлен read-only раздел VWARD Security с listener, Device Profile и
  состоянием защитных ограничений API; из общих настроек добавлен переход в него.
- Update Engine health check использует обнаруженный адрес и порт Console.

## 0.2.0-dev.2: runtime-унификация и защита Console

- Runtime-файлы, init/cron, PID, lock, state, log и configuration paths напрямую
  переведены в каноническое пространство имён VWARD без aliases и wrappers.
- Update Engine allowlist, health checks, backup/rollback simulations, registry и
  release workflow синхронизированы с новыми runtime-targets.
- Console сохраняет LAN-only bind `192.168.1.1:8088`; wildcard bind запрещён тестом.
- Для всех изменяющих API-запросов обязателен request guard и form content type;
  удалён ненужный CORS-preflight путь.
- Добавлены browser security headers, запрет directory listing и выдачи файлов с
  типичными backup/editor suffixes.
- Проверка живых сокетов и firewall остаётся обязательным блокирующим этапом перед
  первой установкой Dev на роутер.

## 0.2.0-dev.1: начало основной dev-линии

- Ветка `dev` синхронизирована с полностью подписанной базой `0.1.7-beta`.
- Начат этап глубокой унификации VWARD Platform, Zero-Hardcode и совместимых миграций
  внутренних имён компонентов.
- Подписанный beta-feed `0.1.7-beta` сохранён без изменений; dev-пакет на роутер этим
  коммитом не публикуется.
- Зафиксирована односторонняя синхронизация Beta fixes -> Dev и схема версий для обеих
  линий.
- Добавлен поэтапный план Device Discovery, Zero-Hardcode, компонентной унификации и
  завершения VWARD Console.
- В актуальных исходных комментариях старое имя Smart Updater заменено на каноническое
  VWARD Update Engine без изменения runtime-логики.
- Source-дерево напрямую переведено на канонические каталоги Route Engine, Route
  Reconciler, Route Tools, Tunnel Guard, WAN Guard, Policy Sync, Runtime и Update Engine.
- Legacy component IDs удалены из Dev registry и schema; переходные aliases и wrappers
  в Dev не создаются.

## 0.1.7-beta: критический переходный hotfix VWARD Console

- Route Engine получил read-only сводку фактических доменных и IP/CIDR-каталогов: источники, категории, AdaptiveAuto, активные IP-категории и количество маршрутов Policy Sync без расширения mutation API.
- Журналы переведены с одиночных вкладок на компактный multi-source workspace: выбор нескольких источников, поиск, счётчик строк, ручное и автоматическое обновление, копирование, TXT-сохранение и системный Share.
- Добавлена общая контекстная лампочка-подсказка; текст зависит от открытого раздела и текущего backend-state.
- Detail pages очищены от повторяющихся заголовков, видимые статусы и служебные поля частично русифицированы, графики получили скруглённые окончания и соединения.
- Удалена жёсткая привязка Console к `Wireguard0` и `nwg1`.
- Console API теперь обнаруживает фактические WireGuard-интерфейсы динамически через RCI и отдаёт их как `wg.interfaces[]`.
- Frontend поддерживает 0, 1 и несколько туннелей без фиксированных `g.wg0` / `g.wg1`.
- Исправлен подтверждённый случай, когда запрос отсутствующего `Wireguard0` постоянно загрязнял системный журнал Keenetic.
- Учтена целевая среда Keenetic/Entware: для этой логики не требуются regex-функции `jq` с ONIGURUMA и сложные GNU-only конструкции `awk`.
- Релиз является переходным beta-мостом для установленных `0.1.6-dev`; большой Zero-Hardcode refactor продолжается в линии `0.2.0-dev.x`.
- Не изменяются Route Engine, Tunnel Guard, Policy Sync и высокорисковые runtime paths.

## 0.1.6-dev: панель управления и документация

- Обновлена русская документация по установке, компонентам и обновлениям.
- Добавлены локальные SVG-иконки, названия компонентов и плавающая нижняя панель на мобильных экранах.
- Уточнены настройки автообновления, диагностика и отображение журналов.
- Добавлены проверки согласованности документации и элементов панели.
- Подписанный пакет обновляет панель и VERSION с 0.1.4-dev или 0.1.5-dev.

## 0.1.5-dev — Interactive VWARD Console

- Rebuilt VWARD Console as a Keenetic-inspired component dashboard with
  clickable cards, responsive navigation and real session sparklines.
- Added detailed read-only component screens and a guarded editor for the four
  existing Smart Updater automatic-apply policy flags.
- Kept routing, tunnel, WAN recovery and other production settings read-only.

## 0.1.3-dev — Component-aware selective updates

- Corrected updater-slot activation for BusyBox `mv` symlink-to-directory semantics and added post-swap verification.
- Enforced canonical component ownership across the signed feed, package manifest and bundled registry.
- Added rejection of unknown/mismatched components, duplicate targets or sources, incorrect modes, missing dependencies and undeclared package files.
- Added atomic per-component installed state with rollback support and `--status-components`.
- Added component-specific health profiles while retaining the accepted default profile and legacy component aliases.
- Kept Update Engine self-update isolated behind the existing atomic slot installer.

## Unreleased

- Added the canonical VWARD Platform component registry and unified product
  names without changing runtime filenames, paths or the active signed feed.
- Added updater-owned runtime quiescing/resume orchestration, Entware-compatible
  file-mode verification and recovery-aware idempotent updater installation.
- Added the signed `0.1.2-dev` runtime-barrier acceptance package.
- Enabled signed automatic apply after live-router apply, rollback, runtime
  quiescing, service-resume and production-file preservation acceptance passed.
- Added the signed Smart Updater production bootstrap, pinned Ed25519 public
  key, check-only production configuration and live-router installer.
- Corrected the Keenetic updater health probe to use the supported
  `ndmc -c "show version"` invocation.
- Imported the working VWARD shell, init, CGI and web sources from the verified
  2026-09-06 read-only router snapshot.
- Added the production cron schedule as managed source.
- Added the installation map, dependency inventory and future updater design.
- Classified generated and device-local configuration separately from source.
- Removed the obsolete initial UI-only updater placeholder.
- Added the disabled, implementation-stage Smart Updater v1 subsystem, signed
  manifest schema, rollback model and isolated simulation suite. It is not deployed.
- Synchronized the verified 2026-09-09 production fixes: Adaptive maintenance
  probe compatibility, Adaptive Live group-refresh throttling, self-healing
  tcpdump watchdog grace, cached WireGuard RCI checks, and bounded log/storage
  housekeeping with the active hourly cron schedule.

## 0.1.0-dev — 2026-09-06

- Добавлен текущий frontend snapshot v28.
- Подготовлена структура публичного репозитория.
- Добавлен безопасный updater интерфейса.
- Добавлены README, SECURITY, CONTRIBUTING и документация.
- Backend и WAN Guardian пока не публикуются как стабильные компоненты:
  требуется отдельная универсализация и security-аудит.
