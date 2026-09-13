# Source validation snapshot — 2026-09-13

The candidate intentionally does not bundle third-party feed contents. It stores source definitions and downloads them at runtime only when enabled.

Previously reviewed/live-reachable during package research: EasyList, EasyPrivacy, OISD Small, 1Hosts Lite, Peter Lowe, StevenBlack, AWAvenue and ShadowWhisperer Tracking. HaGeZi PRO and the AdGuard DNS filter endpoints were reachable but too large for the research fetcher to display in full. Some dedicated popup endpoints were not fully content-validated in that research pass.

Therefore **all URLs, redirects, formats and licences must be revalidated at integration/staging time**. Runtime protections are intentionally independent of that review: maximum bytes, timeout, minimum normalized entry count, last-known-good retention, source modes, and logical domains/exceptions pair installation.

Default candidate policy:

- ACTIVE: HaGeZi PRO, HaGeZi Pop-Up, AdGuard DNS, AdGuard Popup;
- CHECK: HaGeZi PRO++, EasyList, EasyPrivacy, OISD Small, 1Hosts Lite, Peter Lowe, StevenBlack, AWAvenue, ShadowWhisperer Tracking;
- OFF: available for any source through local overrides.

CHECK means evidence is visible but cannot contribute to automatic block score.
