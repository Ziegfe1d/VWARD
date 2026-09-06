# Backend

Публичная версия backend будет добавлена после универсализации текущего локального CGI.

Критические требования:
- LAN-only;
- read-only by default;
- no secrets in responses;
- explicit action whitelist;
- timeout + error classification;
- backup/verify/rollback для write actions.
