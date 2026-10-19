# Learnings log — NHL research

Appended as work progresses. Nulls and dead ends included deliberately. Nothing here
revisits the tiered pick policy, which remains NO-GO. Live focus is NFL; NHL entries are
research-only unless stated.

## 2026-10-19 — Starter-feed feasibility (DROP)

Full write-up: `research/nhl/starter-feed-feasibility-2026-10-19.md`.

- **No free, reliable, historical pre-puck-drop starter feed exists.** Verified live against
  the free NHL API on 2026-10-19 (game `2026020137`): the gamecenter `landing` endpoint exposes
  only season goalie stats in `matchup.goalieComparison`; it has **no** `starter`/`probable`/
  `projected` field. `roster`, `summary` and `line-score` return **HTTP 404** for a future
  game. The `starter` concept appears only post-hoc in box scores.
- The only probable-starter sources are third-party: Daily Faceoff and Left Wing Lock (free
  to read, no pre-game archive, ToS-restricted scraping) and Rotowire (paid history). There is
  no free, self-hosted, archivable option.
- **Perfect-feed ceiling is below the noise floor.** The goalie report's retrospective
  observed-starter recomputation *is* the perfect-feed bound: win probability moves
  `|Δp| = 0.0071` on average (max 0.0573). That changes Brier by ~`5×10⁻⁵`, about 10× smaller
  than the outcome-gate CI half-width (~`4×10⁻⁴`). Even a 100%-accurate feed cannot convert the
  G2 null.
- The G2 null is **not** caused by the starter gap alone: the fitted goalie lever is a
  ±2–3% GA swing (`κ = −4.72`, multiplier 0.968–1.020). Closing the gap raises starter accuracy,
  not the lever's size. The goal distribution already improves without a feed (CRPS 1.3917 →
  1.3872; PIT improves both sides).
- **Recommendation: DROP.** The information gap is real and correctly identified; a feed's
  operating cost (fragile scraping, no history) exceeds its measured value. A "not worth it"
  verdict is the honest answer.
- Deliberately not done: no GSAx re-run or re-parameterisation, no production/ingest changes,
  no dev merge, no deploy, no paid feed purchased.
