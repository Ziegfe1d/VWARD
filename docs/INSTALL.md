# Установка VWARD

> **Статус 0.1.5-dev:** безопасного универсального установщика всей платформы пока
> нет. Репозиторий содержит проверенный source/runtime map и production bootstrap
> Update Engine, но текущий dev-feed не является цепочкой первичной установки на
> пустой роутер. Не запускайте отдельные production-скрипты до адаптации параметров.

Эта инструкция отделяет действия, которые можно выполнить сейчас, от действий,
которые требуют будущего first-install installer или ручного контролируемого окна.

## 1. Перед началом

Нужны:

- Keenetic с поддержкой Entware и USB-накопителем;
- резервная копия startup-config Keenetic;
- локальный доступ к веб-интерфейсу и SSH;
- возможность вернуть исходный cron и файлы `/opt`;
- понимание, какой WireGuard-интерфейс можно использовать для политики VWARD.

VWARD может менять маршруты, состояние WireGuard и WAN. Первый запуск выполняйте,
находясь в той же локальной сети, а не через единственный удалённый канал.

## 2. Подготовка USB и Entware

1. Подключите исправный USB-накопитель к Keenetic.
2. Установите компонент KeeneticOS «Поддержка открытых пакетов».
3. Назначьте накопитель для Entware в интерфейсе Keenetic.
4. Убедитесь, что `/opt` доступен и сохраняется после перезагрузки.

Безопасные проверки по SSH:

```sh
mount | grep ' /opt '
df -h /opt
test -w /opt && echo OPT_WRITABLE
```

Если `OPT_WRITABLE` не появился, VWARD устанавливать нельзя.

## 3. Установка зависимостей

После успешной установки Entware:

```sh
opkg update
opkg install busybox curl jq tcpdump lighttpd lighttpd-mod-cgi ca-bundle openssl-util tar
```

AdGuard Home нужен только для DNS query-driven discovery. Пакет и конфигурация
AdGuard Home не входят в VWARD. Проверка команд:

```sh
for c in sh awk sed grep curl jq tcpdump lighttpd openssl tar sha256sum ndmc; do
  command -v "$c" >/dev/null 2>&1 || echo "MISSING: $c"
done
```

## 4. Обязательное discovery устройства

До копирования runtime-файлов определите:

| Что | Значение рабочего профиля | Требуемое действие |
|---|---|---|
| LAN/router address | `192.168.1.1` | подтвердить свой LAN-адрес |
| LAN subnet | `192.168.1.0/24` | определить фактическую подсеть |
| WAN connection | `ISP` | определить имя активного подключения |
| physical WAN | `eth3` | определить устройство физического WAN |
| VPN connections | `Wireguard0/1` | выбрать реальные интерфейсы |
| curl device | `nwg1` | сопоставить с выбранным WireGuard |
| managed FQDN group | `AdaptiveAuto` | проверить отсутствие конфликта |
| policy group | `domain-list22` | выбрать локальную группу или отключить сценарий |

Используйте read-only команды и интерфейс Keenetic:

```sh
ndmc -c 'show version'
ndmc -c 'show interface'
ip -4 address show
ip -4 route show
```

Не публикуйте вывод: в нём могут быть локальные адреса и сведения конфигурации.
Все места использования значений перечислены в
[INSTALLATION_MAP.md](INSTALLATION_MAP.md).

## 5. Почему нельзя просто скопировать репозиторий

- каталоги source не совпадают с runtime destination;
- `/opt/etc` содержит локальные настройки и не должен заменяться обновлением;
- cron необходимо объединить, а не перезаписать;
- часть скриптов сразу выполняет сетевые действия;
- текущий package `0.1.5-dev` совместим с установленной `0.1.4-dev`, а не с пустой
  системой;
- release package должен быть подписан и проверен Update Engine.

До появления first-install installer ручная установка всей VWARD считается
**неподдерживаемой**. Таблица в `INSTALLATION_MAP.md` предназначена для аудита и
разработки установщика, а не как команда массового копирования.

## 6. Bootstrap VWARD Update Engine

`components/update-engine/install-vward-update-engine.sh` - production bootstrap только движка
обновлений. Он проверяет зависимости и control plane, скачивает файлы по HTTPS,
сверяет `SHA256SUMS`, устанавливает pinned Ed25519 public key, создаёт backup,
активирует slot и добавляет одну помеченную cron-строку.

Важно: bootstrap сам изменяет `/opt`, updater cron и локальные updater-файлы. Его
следует запускать только на уже подготовленной совместимой VWARD-установке и после
проверки текущего feed. Он не заменяет универсальный first installer.

Перед запуском сохраните:

```sh
mkdir -p /opt/var/backups/vward/manual-preflight
crontab -l > /opt/var/backups/vward/manual-preflight/root.crontab.before
cp -p /opt/etc/vward/update.conf /opt/var/backups/vward/manual-preflight/update.conf.before 2>/dev/null || true
```

После контролируемого запуска проверяются:

```sh
/opt/share/vward/updater/current/vward-update.sh --status
crontab -l | grep VWARD_SMART_UPDATER
test -r /opt/etc/vward/update-public.pem && echo PUBLIC_KEY_PRESENT
```

Не передавайте и не заменяйте `update-public.pem` случайным ключом. Приватный signing
key на роутере находиться не должен.

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

- VWARD Console открывается только из LAN;
- `/cgi-bin/api.cgi?action=ping` возвращает JSON с `ok:true`;
- Overview, каждая карточка, «Журналы» и все вкладки журналов открываются;
- в браузере нет JavaScript/API ошибок;
- после перезагрузки фоновые службы и Console вернулись;
- обычный интернет, прямые исключения и VPN-политики работают ожидаемо.

## 8. VWARD Console

Console - локальная панель наблюдения. Фактический адрес и порт определяются
установленным `lighttpd.conf`; не считайте `192.168.1.1:8088` универсальным адресом.
Frontend использует same-origin API. Внешние ссылки строятся от текущего LAN-host.

Редактируются только четыре allowlisted boolean-флага VWARD Update Engine. Backend
проверяет метод и размер запроса, значения `0/1`, блокировку updater, создаёт backup,
делает атомарную запись и проверяет результат. WAN/WireGuard/routing доступны только
для чтения.

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
| Console не открывается | bind/port, PID lighttpd, document root и LAN-доступ |
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

Полного автоматического uninstaller пока нет. Безопасное удаление должно выполняться
по ownership map и начинаться с отключения VWARD cron/init, затем остановки служб,
backup local config/state и удаления только VWARD-owned targets.

Нельзя:

- удалять весь `/opt`;
- перезаписывать root crontab пустым файлом;
- удалять общие Entware-пакеты без проверки других consumers;
- удалять WireGuard/Keenetic-подключения как часть uninstall VWARD;
- удалять backup до проверки восстановленного интернета.

До появления uninstaller используйте `INSTALLATION_MAP.md` как ownership checklist и
выполняйте удаление только в контролируемом окне.

## 13. Известные ограничения

- нет поддерживаемой установки всей системы «с нуля»;
- discovery большинства сетевых параметров ещё не автоматизирован;
- текущие runtime-имена сохранены для совместимости;
- live acceptance относится к целевому устройству, а не ко всем Keenetic;
- версия `0.x-dev` может менять внутренние схемы при документированной миграции.
