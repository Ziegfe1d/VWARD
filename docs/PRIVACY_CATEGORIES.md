# Категории VWARD Ads & Privacy Guard

| ID | Интерфейс | Назначение | DNS-реализуемость |
|---|---|---|---|
| `ads` | Реклама | ad servers / ad delivery | высокая |
| `popup_redirect` | Popup / Redirect | рекламные redirect/popunder domains | высокая/средняя |
| `tracking` | Трекинг | cross-site/device tracking domains | высокая |
| `analytics` | Аналитика | counters/metrics | высокая, с риском breakage |
| `telemetry` | Телеметрия | app/device telemetry | высокая, включать осторожно |
| `affiliate` | Партнёрские переходы | affiliate/attribution domains | средняя |
| `mail_tracking` | Трекинг почты | known tracking-pixel domains | средняя |
| `social_tracking` | Социальный трекинг | external social tracking endpoints | средняя |
| `resource_abuse` | Злоупотребление ресурсами | coin miners/abusive endpoints | высокая |

Категория описывает причину verdict. Один домен может иметь несколько evidence
категорий. `ALLOW`/`TRUST` не является категорией — это политика действия.
