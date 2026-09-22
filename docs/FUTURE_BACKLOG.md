# Future backlog: VWARD Ads & Privacy Guard

## P0 — минимально работающий контур

- allowed AGH query -> candidate -> trust/history -> source evidence -> verdict;
- ручной domain probe;
- manual ALLOW/BLOCK;
- VWARD-owned publish/remove in AGH;
- pause/resume + scheduled/dynamic low-load mode;
- health/rollback/ownership guarantees.

## P1 — полноценное меню

- source OFF/CHECK/ACTIVE backend;
- rules table CRUD + enable/disable without deletion;
- category-aware classification;
- decision history / Logger;
- source health and stale indicators;
- one-click recheck selected rule.

## P2 — защита от false positives

- Breakage Assistant;
- temporary ALLOW with expiry;
- correlation with recent client requests;
- automatic rollback of only the newest VWARD auto rules;
- «не менять ручные правила» invariant tests.

## P3 — privacy intelligence

- per-client Privacy Monitor;
- client profiles;
- new tracker detection;
- CNAME tracking research;
- local privacy score built from explicit metrics, not opaque magic number.

## P4 — bypass/security adjacent

- DoH/DoT/DoQ bypass monitor;
- optional handoff to a separate security/network-policy component;
- no implicit firewall mutation from Ads & Privacy Guard.

## Не переносить в DNS-компонент

Cosmetic filters, DOM element hiding, browser scriptlets, HTTPS header rewriting,
tracking-parameter removal and cookie/WebRTC manipulation require a client/browser or
HTTPS interception layer. They remain outside this component.


## P5 — HTTPS Content Guard (v6 foundation)

Implemented candidate foundation: explicit proxy lifecycle, local CA, PAC selective
interception, bypass precedence and narrow request-path blocking. Remaining work:

- live Keenetic/Entware acceptance of 3proxy plugins and resource usage;
- Console config editor with explicit confirmations;
- QUIC behavior study;
- optional client/agent backend;
- structural JSON/HTML filtering only after a safe parser/backend exists;
- Ozon first-party banner path discovery and pinning compatibility test.
