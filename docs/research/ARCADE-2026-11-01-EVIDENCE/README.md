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

Mobile results are browser emulation. Physical-phone input parity, low-end performance, first-time player feedback, and a live source-correction pilot still need field validation.
