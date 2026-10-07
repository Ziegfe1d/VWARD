# Установка VWARD

> **Статус 0.2.0-rc.2.fix.18:** установщик `install.sh` проверен на эмуляторе чистого
> роутера (`tests/perf/check-install-emulated.py`). На реальном роутере «с нуля» он ещё
> не запускался.

Исходное положение: роутер Keenetic включён и настроен, флешка вставлена, в Keenetic
настроено VPN-подключение (WireGuard, AmneziaWG, OpenVPN, SSTP, L2TP, PPTP, IPsec или
Proxy). Больше ничего не нужно: списков доменов, AdGuard Home и своих настроек VWARD не
требует.

## 1. Подготовка роутера (один раз)

VWARD работает в Entware, поэтому сначала роутеру нужна Entware на флешке. Без неё на
роутере нет обычной командной строки, и сделать эти шаги за вас установщик не может.

1. **Компоненты.** Веб-интерфейс Keenetic → «Общие настройки» → «Изменить набор
   компонентов»: отметьте «Поддержка открытых пакетов» и «Файловая система Ext».
   Роутер обновится и перезагрузится.
2. **Флешка в ext4.** Keenetic не форматирует флешки сам. Отформатируйте её в ext4 на
   компьютере: в Linux `mkfs.ext4 -L OPKG /dev/sdX1`, в Windows - программой для
   разделов (например, AOMEI Partition Assistant или Paragon Partition Manager). Все
   данные на флешке будут стёрты.
3. **Entware.** Вставьте флешку в роутер. Откройте в браузере командную строку роутера:
   `http://192.168.1.1/a` (или адрес вашего роутера с `/a`). Узнайте архитектуру
   командой `show version` (строка `arch`) и выполните одну команду, подставив имя
   флешки из «Приложения → Диски и принтеры» (например, `OPKG`):

   | arch | Команда |
   |---|---|
   | mipsel (большинство моделей) | `opkg disk OPKG:/ https://bin.entware.net/mipselsf-k3.4/installer/mipsel-installer.tar.gz` |
   | mips | `opkg disk OPKG:/ https://bin.entware.net/mipssf-k3.4/installer/mips-installer.tar.gz` |
   | aarch64 | `opkg disk OPKG:/ https://bin.entware.net/aarch64-k3.10/installer/aarch64-installer.tar.gz` |

   Затем `system configuration save`. Через 3-5 минут Entware готова (ход установки
   виден в «Диагностика → Системный журнал»).
4. **Вход в Entware.** Подключитесь по SSH к роутеру: порт 222, если в Keenetic стоит
   компонент «Сервер SSH», иначе 22. Логин `root`, пароль `keenetic`; сразу смените
   его командой `passwd`.

## 2. Установка VWARD

В SSH-сессии Entware:

```sh
opkg update && opkg install curl
curl -fsSL https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/install.sh -o /tmp/vward-install.sh
sh /tmp/vward-install.sh
```

Сначала можно только проверить роутер: `sh /tmp/vward-install.sh --check` - ничего не
меняется. Установщик задаёт вопросы на экране, поэтому его запускают файлом, а не через
`curl | sh`. Для установки без вопросов: `--yes` (если VPN-подключений несколько,
установщик всё равно попросит выбрать).

## 3. Что делает установщик

1. **Проверка роутера** (ничего не меняет): KeeneticOS 5.0 или новее (на 3.x и 4.x
   установщик отказывает), Entware на `/opt`, не меньше 20 МБ свободно, VWARD ещё не
   стоит, есть ли AdGuard Home.
2. **Пакеты Entware:** ставит недостающие `curl jq tcpdump openssl-util ca-bundle
   lighttpd lighttpd-mod-cgi lighttpd-mod-setenv cron` - только после вашего «да».
3. **Сеть и VPN:** находит провайдера, домашнюю сеть и VPN-подключения по типам, а не
   по именам. Если VPN несколько - показывает список и спрашивает, через какое пускать
   сайты; если домашних сетей несколько - спрашивает, какая домашняя. Выбор
   записывается в `/opt/etc/vward/device.conf`, остальное VWARD находит сам при каждом
   запуске.
4. **Программа:** скачивает движок обновлений (файлы сверяются с `SHA256SUMS`), и тот
   ставит подписанную сборку тем же путём, что и обновления: подпись Ed25519, SHA-256
   архива и каждого файла, копия до установки, проверка после; при сбое файлы
   возвращаются назад (`vward-update.sh --install`, только на роутере без VWARD).
5. **Настройка:** создаёт в Keenetic список `AdaptiveAuto` и маршрут этого списка через
   выбранный VPN - сюда автоподбор добавляет сайты, которые не открываются напрямую;
   добавляет задания cron (свои строки владельца остаются); без AdGuard Home выключает
   раздел «Реклама» (включается в «VWARD → Компоненты»).
6. **Запуск и проверка:** cron, автоподбор, панель VWARD; в конце - адрес панели.

Если любой шаг не прошёл, установщик возвращает всё, что успел изменить (файлы,
cron, настройки Keenetic), и пишет причину. Журнал: `/opt/var/log/vward/install.log`.

## 4. Удаление

```sh
curl -fsSL https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/install.sh -o /tmp/vward-install.sh
sh /tmp/vward-install.sh --uninstall
```

Останавливает службы VWARD, выключает то, что VWARD включал в AdGuard Home и в
фаерволе, удаляет программу и её строки cron. Настройки сохраняются в
`/opt/var/backups/vward/uninstall-<дата>`. Список `AdaptiveAuto` убирается из Keenetic
по вашему согласию, если его создал установщик. Пакеты Entware и VPN-подключения
остаются.

## 5. Роутер с бетой VWARD

На роутере с бетой (`0.1.9-beta`) установщик не работает: для неё есть переход
`scripts/beta-to-dev-cutover.sh`, после которого новая версия приходит обычным
обновлением.

## 6. Параметры устройства

Модель роутера и имена интерфейсов не зашиты: Device Profile строит карту интерфейсов
через Keenetic RCI (`show interface`, `show interface system-name`) и running-config и
кэширует её в `/tmp/vward-device-map.tsv` на 5 минут. Пустыми можно оставить значения,
для которых discovery возвращает ровно одного кандидата.

Правила discovery:

- VPN-туннели ищутся по типу интерфейса, а не по имени: WireGuard (и AmneziaWG),
  OpenVPN, SSTP, PPTP, L2TP, IPsec/IKE и Proxy. Подключение к провайдеру (PPTP/L2TP у
  некоторых провайдеров) туннелем не считается. Если туннель один, он выбирается сразу;
  если их несколько, выбирается единственный, на который уже ссылаются `route
  object-group` или `ip route`; иначе нужен `VWARD_TUNNEL_INTERFACE` (его записывает
  установщик или Панель VWARD: «VPN» → туннель → «Использовать для маршрутов»);
- `VWARD_WAN_INTERFACE` - интерфейс Keenetic, чьё системное имя совпадает с
  устройством маршрута по умолчанию; VPN, назначенный основным подключением, не
  считается провайдером, а при двух провайдерах берётся основной (меньшая метрика);
- LAN - единственный глобальный IPv4-адрес вне WAN/туннелей; при гостевых сегментах
  выбирается сегмент с `security-level: private`;
- `VWARD_POLICY_GROUP` - FQDN-группа, маршрутизируемая в выбранный туннель, кроме
  собственной группы VWARD `AdaptiveAuto`. На чистом роутере её нет - «Мои домены»
  появятся, когда в Keenetic будет список через VPN.

Все места использования значений перечислены в [INSTALLATION_MAP.md](INSTALLATION_MAP.md).

## 7. Проверка работающей установки

На уже установленной VWARD:

```sh
test -r /opt/share/vward/VERSION && sed -n '1p' /opt/share/vward/VERSION
ps w | grep '[v]ward-route-engine.sh'
ps w | grep '[c]rond-supervisor.sh'
crontab -l | grep VWARD
/opt/share/vward/updater/current/vward-update.sh --status
```

Проверьте локально:

- Панель VWARD открывается только из LAN;
- `/cgi-bin/api.cgi?action=ping` возвращает JSON с `ok:true`;
- Overview, каждая карточка, «Журналы» и все вкладки журналов открываются;
- в браузере нет JavaScript/API ошибок;
- после перезагрузки фоновые службы и Панель VWARD вернулись;
- обычный интернет, прямые исключения и VPN-политики работают ожидаемо.

## 8. VWARD Panel

Панель VWARD - локальная панель наблюдения. Init-скрипт генерирует рабочий lighttpd config
из проверенных `VWARD_LAN_ADDRESS` и `VWARD_CONSOLE_PORT`.
Frontend использует same-origin API. Внешние ссылки строятся от текущего LAN-host.

Настройки из Панели VWARD записывает `vward-console-config.sh` (строгие значения, backup,
атомарная запись, проверка результата, журнал аудита); полный список - в `docs/PANEL.md`.

Вход по учётной записи Keenetic по умолчанию выключен. Включается в «Настройки → Доступ к
Панель VWARD» вводом логина и пароля от веб-интерфейса роутера: пароль проверяет сам роутер
(`/auth`, challenge-response), VWARD его не хранит. Если доступ потерян, вход выключается по
SSH: `rm /opt/etc/vward/console/auth.conf`.

## 9. Ручная проверка обновлений

```sh
/opt/share/vward/updater/current/vward-update-watch.sh --once
/opt/share/vward/updater/current/vward-update.sh --status
```

Не редактируйте manifest, sequence или trust state вручную. Поведение при приоритетах,
safe window и rollback описано в [UPDATE_POLICY.md](UPDATE_POLICY.md) и
[UPDATE_RECOVERY.md](UPDATE_RECOVERY.md).

## 10. Диагностика

| Симптом | Проверить |
|---|---|
| Панель VWARD не открывается | bind/port, PID lighttpd, document root и LAN-доступ |
| «Журналы» не реагируют | совпадение deployed/source hash, cache, JS console, `action=log` |
| API недоступен | CGI mapping, execute mode `0755`, `jq`, response headers |
| Компонент остановлен | init-script, PID, cron `.last/.rc/.out`, свободное место |
| Update Engine завис | journal/lock, status, pending manifest; не удалять state вслепую |
| После обновления проблема | health result и штатный rollback, затем backup |

Логи могут содержать домены и локальные сведения. Не прикладывайте их публично без
очистки.

## 11. Backup, rollback и recovery

- Bootstrap хранит свои копии в `/opt/var/backups/vward/bootstrap`.
- Update Engine создаёт target-specific backup до установки.
- Local config и persistent state не входят в package targets.
- При failed health-check используется детерминированный rollback.
- При `RECOVERY_REQUIRED` сначала сохраните state/log и используйте documented
  recovery path; не удаляйте lock/journal до определения активной транзакции.

Подробности: [UPDATE_RECOVERY.md](UPDATE_RECOVERY.md).

## 12. Отключение и удаление

Удаление - `install.sh --uninstall` (раздел 4). Отдельные части выключаются в
«VWARD → Компоненты» без удаления.

Нельзя:

- удалять весь `/opt`;
- перезаписывать root crontab пустым файлом;
- удалять VPN-подключения Keenetic как часть удаления VWARD.

## 13. Известные ограничения

- установка «с нуля» проверена на эмуляторе, на реальном чистом роутере ещё нет;
- подготовку роутера (компоненты, ext4, Entware) установщик сделать не может;
- текущие runtime-имена сохранены для совместимости;
- live acceptance относится к целевому устройству, а не ко всем Keenetic;
- версия `0.x-dev` может менять внутренние схемы при документированной миграции.
