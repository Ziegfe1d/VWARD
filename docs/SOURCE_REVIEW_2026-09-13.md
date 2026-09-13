# External source review - 2026-09-13

Этот файл фиксирует, почему начальный source registry содержит именно эти семейства.
Перед будущим merge URL и policies нужно smoke-test'ить ещё раз.

## HaGeZi

Официальная документация на момент подготовки кандидата различает:

- Multi PRO - recommended balanced/full tier;
- PRO Mini - size-optimized subset для limited hardware;
- PRO++ - более агрессивный tier;
- Pop-Up Ads - отдельный специализированный список popup advertising.

VWARD использует full PRO/PRO++/Pop-Up только как evidence indexes, не предлагает
загружать их все в active AGH filtering одновременно.

Reference URLs:

- https://github.com/hagezi/dns-blocklists
- https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/adblock/pro.txt
- https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/adblock/pro.plus.txt
- https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/adblock/popupads.txt

## AdGuard Hostlists Registry

Официальный registry подтверждает отдельные DNS-oriented subscriptions, включая:

- HaGeZi Pro (filter 48);
- HaGeZi Pro++ (filter 51);
- AdGuard DNS Popup Hosts (filter 59);
- OISD Small (filter 5).

AdGuard Popup description прямо указывает назначение для сайтов, открывающихся в
новом окне, и DNS-level popup blocking.

Reference:

- https://adguardteam.github.io/HostlistsRegistry/assets/filters.json
- https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt
- https://adguardteam.github.io/AdGuardSDNSFilter/Filters/adguard_popup_filter.txt

## EasyList / EasyPrivacy

EasyList предназначен для рекламы, EasyPrivacy - для tracking. Это browser-oriented
rulesets, поэтому VWARD **не импортирует любую строку**. Используются только
однозначные DNS-domain anchors/hosts/plain domains.

- https://easylist.to/easylist/easylist.txt
- https://easylist.to/easylist/easyprivacy.txt

## OISD

OISD Small позиционируется как ads-focused список с приоритетом функциональности.

- https://small.oisd.nl/
- https://oisd.nl/

## 1Hosts Lite

Lite используется как дополнительное evidence family, а не как единственный
автоматический критерий блокировки.

- https://raw.githubusercontent.com/badmojr/1Hosts/master/Lite/adblock.txt
- https://github.com/badmojr/1Hosts

## Корреляция источников

Списки часто агрегируют или используют общие upstream. Поэтому наличие домена в двух
файлах не всегда означает два независимых подтверждения. Initial registry сознательно
группирует HaGeZi и AdGuard/EasyList семьи, а scoring берёт максимум на group.

## Дополнительные medium evidence sources

Initial registry также включает несколько отдельных семейств, чтобы один большой
aggregator не был единственной опорой:

- Peter Lowe's Blocklist;
- StevenBlack Unified Hosts;
- AWAvenue Ads Rule (mobile advertising SDK/network rules);
- ShadowWhisperer Tracking List.

Они не имеют `single_source_block=true`; одиночное совпадение само по себе переводит
домен максимум в evidence/review, если не выполнено общее consensus rule.
