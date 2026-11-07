# Ревизия PR и веток GitHub — 07.11.2026

Поручение владельца 07.11.2026 (ROADMAP §7), §8. Административная уборка, не выпуск: закрытие PR не
меняет `dev`, `VERSION`, ленту и не доказывает готовность ПО или приёмку на Keenetic. Незакрытые
функции ведутся в PR #38 и ROADMAP. Данные — полная (не shallow) история `origin`, снимок 07.11.2026
~13:30 МСК; `dev` = `3f4802b6574c`, PR #38 = `65f78720773e` на момент снимка.

## 1. Открытые PR (22 до ревизии)

Проверка: `git merge-base --is-ancestor <head> origin/dev` и `git rev-list --count dev..head`.
Интеграционный коммит — первый коммит первой родительской линии `dev`, содержащий head.

| PR | base → head | head SHA | в dev / PR38 | уникальное | до релиза | действие | доказательство |
|----|-------------|----------|--------------|------------|-----------|----------|----------------|
| 38 | dev ← work/unified-routing-20261104 | 65f78720773e | — | вся текущая работа | да | продолжать | этот PR |
| 8 | p7-dns-routing ← p7-fqdn-route-evidence | 1723eeb983cc | да / да | нет (ahead 0) | нет | закрыть: integrated | 75cd38e (PR #29, fix.35) |
| 9 | p7-fqdn-route-evidence ← p7-smartdns-saved-cleanup | 5869f119f6f8 | да / да | нет | нет | закрыть | 75cd38e |
| 11 | plan-routing-sources ← audit-routing-sources | b0bffcc453e9 | да / да | нет | нет | закрыть | 75cd38e |
| 12 | audit-routing-sources ← rs1-service-ownership | d4a63270a329 | да / да | нет | нет | закрыть | 75cd38e |
| 13 | rs1 ← rs2-routing-state-errors | 3f8435c16549 | да / да | нет | нет | закрыть | 75cd38e |
| 14 | rs2 ← rs3-service-transactions | aee436c625b5 | да / да | нет | нет | закрыть | 75cd38e |
| 15 | rs3 ← rs123-failure-matrix | 020b46d59081 | да / да | нет | нет | закрыть | 75cd38e |
| 16 | rs123 ← rs4-routing-measurements | b6148a9e11da | да / да | нет | нет | закрыть | 75cd38e |
| 17 | rs4 ← rs5-routing-audit | f58dd8c73278 | да / да | нет | нет | закрыть | 75cd38e |
| 19 | integrate-p7-b ← rs6-read-only-adapters | 18bad8ee6db8 | да / да | нет | нет | закрыть | 75cd38e |
| 20 | rs6-read-only ← docs/codex-claude-workflow | 80f6ce966ff5 | да / да | нет | нет | закрыть | 75cd38e |
| 21 | docs/codex-claude ← rs6-stage2-claude | 52aff7480123 | да / да | нет | нет | закрыть | 75cd38e |
| 22 | rs6-stage2 ← docs/full-routing-vpn-dns-cycle | 0ce37f275b64 | да / да | нет | нет | закрыть | 75cd38e |
| 23 | rs6-stage2 ← rs6-stage3-observers | 2763461bfc20 | да / да | нет | нет | закрыть | 75cd38e |
| 24 | rs6-stage3 ← rs7-stage1-plan | d50c5d9958e3 | да / да | нет | нет | закрыть | 75cd38e |
| 25 | rs7-stage1 ← fix-policy-audit-reasons | 2e83f88bd393 | да / да | нет | нет | закрыть | 75cd38e |
| 26 | fix-policy-audit ← rs7-stage3-dryrun | f9da844080a9 | да / да | нет | нет | закрыть | 75cd38e |
| 27 | rs7-stage3 ← pkgE-components-status | 832055b19110 | да / да | нет | нет | закрыть | 75cd38e |
| 28 | pkgE ← pkgF-network-cycle | 39ec2029749c | да / да | нет | нет | закрыть | 75cd38e |
| 30 | release-…fix.34.1.1 ← docs/vward-display-version | 2f6474a35905 | нет / нет | 2 docs-коммита | нет (план Панели) | перенесено в ROADMAP, закрыть | см. §3 |
| 32 | dev ← fix/fix36-20261102 | ca1595d9d913 | нет / нет | 6 коммитов | всё уже покрыто | закрыть: superseded | см. §2 |

#10, #18, #31 и #29, #33–#37 уже MERGED; не переоткрывать. Незакрытые требования 19 исторических
PR (RS-6/RS-7/B/пакеты A–F) продолжаются в PR #38 (ROADMAP §7, план
`docs/superpowers/plans/2026-11-06-routing-live.md`), отдельных невыполненных обязательств в
этих PR, кроме уже перенесённых в PR #38/ROADMAP, не найдено.

## 2. Gap matrix PR #32 (fix.36, 6 коммитов впереди dev)

PR #33 (fix.35.2, squash) в заголовке «включает PR #32». Проверка по содержимому: каждая
добавленная #32 строка кода найдена в дереве PR #38, кроме перечисленных.

| Пункт #32 | Текущий аналог | Тест | Статус |
|-----------|----------------|------|--------|
| 31dfab5 DNS workers под Live, освобождение мёртвых читателей config (route-engine 49/49 строк, profile 46/48) | route-engine, `vward_keenetic_config` lease | check-route-engine-bind-workers, check-keenetic-cache-owner, check-route-engine-start-phases (идентичны) | реализовано |
| a576703 guarded list DNS, отключённые установки пакетов из Панели (entware-pkg 90/90, api 26/26, js 49/49) | console/entware-pkg/api/js | check-list-smartdns-mode (дальше развит), check-list-dns-job, check-panel-package-install, check-panel-install-buttons, check-panel-xray-install (идентичны) | реализовано |
| 8d2f485 DNS writes в пределах подписанного console target (console 267/268) | console | те же | реализовано; 1 строка заменена более строгой канонической сверкой identity |
| 99af534 раздельный сброс cleanup/signal trap | console/vless-engine (59/59) | check-console-lists-center (идентичен) | реализовано |
| profile doh-alive (2 строки) | `vward_doh_alive` развит (кэш/`-o` в файл) | — | реализовано в новой форме |
| c0cc511, ca1595d docs/FIX36_PLAN/REPORT | docs идентичны в дереве | — | присутствует |
| VERSION/SHA256SUMS/версии `fix.36` в 3 файлах | — | — | НЕ переносить (устаревшие метаданные выпуска) |

Уникальных непокрытых пунктов нет; граница fix.36/fix.37 не пересматривалась.

## 3. PR #30 (формат версии в Панели)

Решение владельца 01.11.2026 (`Версия 0.2.0 RC2 #N.P.ГГММДД`, без технических деталей в Панели)
в действующем дереве отсутствовало и не отменено. Перенесено дословно в ROADMAP §3 и §7 новым
коммитом PR #38 (без старого `SHA256SUMS`); реализация в «О программе» остаётся будущей задачей.

## 4. Ветки (52 на момент снимка)

`ahead` — коммиты, которых нет в истории `dev` (у squash-слитых веток содержимое может быть в dev).

**Не удалять (опорные/активные):** `main` (18 ahead), `beta` (19), `dev`, `work/unified-routing-20261104`
(PR #38), `release-0.2.0-rc.2.fix.34.1.1` (база PR #29/#30), `claude/new-session-933otd` (служебная ветка
этой сессии, = dev).

**С уникальными коммитами — сохранить, показать владельцу:** `archive-beta-0.2.0-beta.1` (137),
`feature/smart-updater-v1` (25; PR #2 merged), `claude/new-session-kl9ijw` (16; PR #33 squash),
`fix/fix36-20261102` (6; PR #32), `awg-engine` (5), `sentinel` (5), `claude/fix-34-1-release-jvr3e8` (5),
`docs/domain-lists-current-release-20261101` (4), `docs/pending` (2), `docs/vward-display-version-20261101`
(2; PR #30), `docs/release-fix35-journal-20261101` (1), `claude/new-session-73a50p` (1; PR #34–36 squash),
`ccr-9abf79f1-lysnb3` (1; PR #5). Расхождение со снимком владельца: `release-prep-console-hotfix` по
полной истории 0 впереди dev (в снимке 30), `main`/`beta` 18/19 впереди (в снимке 116/117 — вероятно,
«позади»); удаление этих веток не предлагается без решения владельца.

**Кандидаты на удаление (0 коммитов вне dev, решение владельца; ничего не удалено):**
`audit-routing-sources-20261030`, `ccr-8453d254-xu7llk`, `ccr-cfc8b48a-43gql3`,
`docs/codex-claude-workflow-20261031`, `docs/full-routing-vpn-dns-cycle-20261031`,
`fix-engine-start-reads-20261031`, `fix-policy-audit-reasons-20261031`, `fix/service-recovery-20261103`,
`fix/tls-probe-state-safety-20261107` (пустая, = dev), `integrate-p7-b-20261030`, `p7-dns-routing-20261030`,
`p7-fqdn-route-evidence-20261030`, `p7-smartdns-saved-cleanup-20261030`, `pkgA-entware-audit-20261101`,
`pkgB-entware-lifecycle-20261101`, `pkgC-dnsmasq-20261101`, `pkgD-singbox-20261101`,
`pkgE-components-status-20261101`, `pkgF-network-cycle-20261101`, `plan-routing-sources-20261030`,
`release-prep-console-hotfix`, `rs1-service-ownership-20261030`, `rs123-failure-matrix-20261030`,
`rs2-routing-state-errors-20261030`, `rs3-service-transactions-20261030`, `rs4-routing-measurements-20261030`,
`rs5-routing-audit-20261030`, `rs6-read-only-adapters-20261030`, `rs6-stage2-claude-20261031`,
`rs6-stage3-observers-20261031`, `rs7-stage1-plan-20261031`, `rs7-stage2-journal-20261031`,
`rs7-stage3-dryrun-20261031` (33 ветки).
