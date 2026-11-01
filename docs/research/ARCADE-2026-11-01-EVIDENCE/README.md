# LP Arcade in NFL HQ · review evidence

Captured from the feature branch preview at 1440×1000 desktop and 390×844 mobile emulation. The flow opens the Arcade cabinet in NFL HQ, shows a verified archived ESPN kick, plays it, and returns to HQ.

## Captures

- [NFL HQ Arcade panel · desktop](nfl-hq-arcade-desktop.png)
- [NFL HQ Arcade panel · mobile](nfl-hq-arcade-mobile.png)
- [Historical kick row · mobile panel scrolled to the archive](nfl-hq-arcade-mobile-moments.png)
- [42-yard kick result · desktop](field-goal-result-desktop.png)
- [42-yard kick result · mobile](field-goal-result-mobile.png)
- [Interaction recording](arcade-interaction.webm)

The preview uses the checked-in normalized ESPN replay for Cardinals at Saints on September 7, 2025: game `401772718`, play `401772718645`, a published 42-yard field-goal attempt. The displayed 961 score and real-game outcome came from the backend's archived challenge and scoring functions.

The bundled archive currently yields 34 source-verified field-goal challenges across 8 games, ranging from 21 to 60 yards. All 34 have stable ESPN event IDs, play IDs, 64-character source revisions, and observation timestamps.

For the browser capture, Arcade HTTP responses were intercepted and served from those backend functions and the archived fixture. The mock held the resulting anonymous leaderboard row in memory; no attempt was written to a database. The live-moment list was empty in the capture. This is archived-event UI evidence, not a live-game freshness test.

## Browser checks

- No browser console or page errors.
- At 390px, document scroll width stayed 390px on the HQ and game pages.
- The mobile one-thumb control measured 334×112px; the result and share buttons measured 163×44px.
- The kick started muted and showed the real attempt outcome separately from the arcade score.

## Isolated API-backed browser smoke

The feature branch was also served from a separate Next dev process, proxied to its Arcade FastAPI router and a temporary SQLite database. No Arcade API responses were intercepted. A one-row local coverage fixture exposed the NFL HQ tab; the other NFL research APIs were not mounted in this isolated smoke test.

- [API-backed desktop kick result](real-api-desktop.png) and [API-backed mobile HQ archive](real-api-mobile.png).
- The HQ cabinet listed 34 archived ESPN challenges and no live moments. Opening a 42-yard kick and submitting an attempt returned the server-calculated 961 score; the historical “Real attempt: made” outcome appeared separately after the arcade result.
- The API round-trip created an anonymous claim, persisted a leaderboard result, and created and resolved a score-bound friend share in the temporary database.
- The mobile document width remained 390px. There were no Arcade API errors or browser page errors. Other NFL research endpoints returned 404 because they were intentionally omitted from this isolated server.
- Simulated touch-pointer and keyboard kick paths sent the identical normalized input (`aim=0.2`, `power=0.58`, `release_timing=0.52`) and both received 707. The touch gesture is quantized to the sliders’ 0.01 step. Reduced motion computed to `0s`; mobile result buttons measured 163×44px.
- A fictional Aim Lab kick was also exercised in headless Chromium at 390×844, device scale factor 1, with CPU throttling set to 4×. The football animation began 65.9 ms after the KICK input; the API returned a 961 score, document width stayed 390px, and there were no browser errors. This is a throttled browser measurement, not a physical low-end phone result.

Mobile results are browser emulation. Physical-phone input parity, performance on a real low-end device, first-time player feedback, and a live source-correction pilot still need field validation.

## ESPN historical source audit

An additional read-only audit fetched eight archived game summaries from ESPN's site API and ran them through the production Pixel Red Zone normalizer. It found 34 attempts with explicit published distances from 21–60 yards, ESPN play IDs, and canonical raw-play revision hashes. Ten representative short-to-long attempts are recorded in [the audit](espn-historical-source-audit.md), along with per-game source update timestamps and request timings. All games on the November 1, 2026 scoreboard were still pregame at observation time, so live freshness and correction behavior remain unverified.
