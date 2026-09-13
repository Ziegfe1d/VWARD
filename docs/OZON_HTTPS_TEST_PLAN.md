# Ozon banner: HTTPS Content Guard acceptance test

Goal: hide the advertising placement on the Ozon home screen without breaking the app.
This is a test case, not a preloaded block rule.

## Why there is no guessed Ozon rule in the package

Previous DNS testing showed that blocking known Ozon advertising/analytics domains does
not remove the banner. The likely remaining case is first-party content delivered through
a normal Ozon API/CDN. Blocking `api.ozon.ru`, `xapi.ozon.ru` or the image CDN at DNS level
is too broad.

Therefore this package deliberately ships **no invented `/ads/...` path**.

## Safe sequence

1. Keep HTTPS Guard OFF globally.
2. Create VWARD CA and install only the public CA certificate on one test client.
3. Add only the candidate Ozon API hostname to `intercept.tsv`.
4. Use generated PAC on that client.
5. Validate that ordinary Ozon navigation works through the proxy.
6. Temporarily enable `HTTPS_DEBUG_LOG=1` only while reproducing the home-screen banner.
7. Identify the exact request path associated with the advertising placement.
8. Disable debug logging again.
9. Add a narrow `path_exact` or `path_prefix` BLOCK rule.
10. Re-test launch, search, product card, images, cart, login and checkout.

If Ozon rejects the VWARD CA, uses certificate pinning, ignores the system/PAC proxy or
moves the placement inside a shared response that cannot be safely blocked by path, mark
the router backend `INCOMPATIBLE` for this use case. Do not weaken upstream certificate
verification and do not intercept all household HTTPS to force the test.
