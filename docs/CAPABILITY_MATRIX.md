# Матрица возможностей VWARD Ads & Privacy Guard

Легенда: **CORE** — есть в кандидате; **HTTPS CANDIDATE** — реализован изолированный backend, но требует router/client acceptance; **NEXT** — подготовлен контракт/меню; **FUTURE** — заглушка и архитектурный задел; **CLIENT ONLY** — требует клиентского/browser слоя.

| Возможность | Статус | Комментарий |
|---|---|---|
| Чтение разрешённых DNS-запросов AGH | CORE | Query log -> кандидаты |
| Trust Registry / кэш verdict | CORE | Не перепроверять известное постоянно |
| Сверка по внешним базам | CORE | Индексы HaGeZi/AdGuard/Easy* и др. |
| Ручная проверка домена | CORE | Probe + evidence/history/DNS |
| Автоматический BLOCK/SUSPECT/ALLOW | CORE | Консервативная multi-source policy |
| VWARD-owned фильтр AGH | CORE | staged/local file/user_rules candidate |
| Снять собственный auto-block после ALLOW | CORE | ownership-safe |
| Manual ALLOW/BLOCK | CORE | выше автоматики |
| Pause/resume, manual/scheduled/dynamic | CORE | low-load scheduler contract |
| CPU/RAM/disk gating | CORE | dynamic mode |
| Источники OFF/CHECK/ACTIVE | NEXT | UI + local override contract |
| Категории Ads/Tracking/Telemetry/... | NEXT | UI + config contract |
| История решений и происхождение правила | NEXT | state уже хранит reason/evidence |
| Logger в стиле uBO | NEXT | единый поток verdict/filter/source events |
| Поиск «что сломало сайт» | FUTURE | recent-block correlation + temporary allow |
| Временное исключение 5/15/60 мин | FUTURE | auto-expire override |
| Профили по клиентам/устройствам | FUTURE | Standard/Strict/TV-IoT/Observe |
| Privacy Monitor по устройствам | FUTURE | статистика trackers/telemetry/new domains |
| Anti-bypass monitor | FUTURE | DoH/DoT/DoQ signals, без firewall-автодействий по умолчанию |
| CNAME tracker detection | FUTURE | если доступны безопасные DNS evidence |
| Импорт/экспорт настроек | FUTURE | backup/restore rules, sources, profiles |
| HTTPS explicit proxy + local CA | HTTPS CANDIDATE | 3proxy SSLPlugin, OFF by default, no NAT mutation |
| PAC selective interception / bypass | HTTPS CANDIDATE | Только явно выбранные домены идут через MITM |
| HTTPS request path BLOCK | HTTPS CANDIDATE | Safe literal path_exact/path_prefix through PCREPlugin |
| HTTPS transparent interception | FUTURE | Нужен отдельный firewall/NAT ownership contract |
| JSON/HTML body rewriting | FUTURE | Не реализовано в router candidate |
| Cosmetic filtering / скрытие DOM | CLIENT ONLY | DNS не видит DOM/CSS |
| Scriptlets / anti-adblock JS | CLIENT ONLY | нужен браузерный слой |
| Удаление utm_* из HTTPS URL | CLIENT ONLY | DNS видит домен, не полный HTTPS URL |
| Cookie/Referer/User-Agent/WebRTC tweaks | CLIENT ONLY | нужен клиентский HTTP(S)/browser layer |
