# Архитектура

## Принцип изоляции

VWARD не должен вмешиваться в системный web UI роутера.

- `/usr/sbin/nginx` — системный компонент Keenetic, не изменяем.
- AdGuard Home — отдельный сервис, не изменяем.
- Apps Center — отдельный lighttpd из Entware.

## Frontend

`web/index.html`

Mobile-first HTML/CSS/JS. Получает live-данные от локального CGI API.

## Backend

Планируемый публичный backend:

- read-only status по умолчанию;
- whitelist разрешённых действий;
- никаких ключей WireGuard в API;
- LAN-only;
- JSON ответы;
- timeout на все внешние/RCI вызовы.

## WAN Guardian

WAN Guardian будет отдельным компонентом с понятной политикой восстановления:

- диагностика;
- DHCP renew;
- controlled interface bounce;
- cooldown;
- rate-limit;
- без автоматической перезагрузки роутера по умолчанию.

Перед публикацией локальная реализация должна быть очищена от привязок к конкретной конфигурации.

## Platform adapters

VWARD проектируется как независимое ядро с адаптерами платформ:

```text
VWARD Core
├── VPN
├── WAN
├── Automation
├── Recovery
├── Diagnostics
└── Adapters
    ├── Keenetic   (первый поддерживаемый)
    ├── OpenWrt    (планируется)
    └── AsusWRT    (планируется)
```

Логика VWARD не должна зависеть от `ndmc`/RCI напрямую. Эти вызовы относятся к Keenetic adapter.
