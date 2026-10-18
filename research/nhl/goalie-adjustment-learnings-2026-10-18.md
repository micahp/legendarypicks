# Learnings log — NHL goalie adjustment (build-order step 2)

Appended as the work progressed. Nulls included deliberately. Nothing here revisits the
tiered pick policy, which remains NO-GO.

## 2026-10-18 — Step 0 data audit

- **Located shot-level data exists on this host** (`shots`, 2,079,359 rows, 2007–2025) with
  per-shot coordinates, angle, xGoal, and `goalieIdForShot`. Shot difficulty keeps its full
  meaning. No degraded proxy needed.
- **No pre-puck-drop starter feed exists anywhere on this host.** The only starter flag is
  2025-postseason-only and post-hoc. Any expected-starter work must be a statistical estimate.
- `shots.game_id` is a per-season index (20000 + game number), not the NHL gameId. Mapping:
  `shots.game_id − 20000 == goalies_gamelogs.gameId % 10000`, verified consistent across all
  seasons; goalie IDs match `goalies_gamelogs.playerId` exactly.
- `homeTeamScore`/`roadTeamScore` are null everywhere; final reg+OT score must be
  reconstructed as `SUM(goal)` per team side from `shots`. `homeTeamWon` is populated and
  includes shootout outcomes (ties split ~50/50, as expected).
- MoneyPuck danger-zone splits exist in `goalies_gamelogs`/`goalies_seasons` but the shot-level
  table is the only located source; the gamelogs are aggregate per situation.

## 2026-10-18 — Pre-registration committed before fitting

- G1 (league-average goalie, rolling-10 multiplicative Poisson), G2 (G1 × exp(κ·regressed
  GSAx/shot), k=1500 shots, trailing-3-season league mean), windows 2008–2022 train / 2023
  validation / 2024–2025 test, gates on paired game-clustered Brier+log-loss CIs, CRPS, PIT.
- Committed as `f64757a4` before any fit was run.

## 2026-10-18 — Protocol correction (disclosed, not silent)

- First implementation predicted the expected starter from prior *appearances*; the
  pre-registration says prior *starts*. Corrected to starts (identified by first
  shot-against faced) and re-run. This moved nothing material: test Brier diff −0.000167 →
  −0.000207, still a null. The corrected run is the pre-registered one.
- The pre-registration's gate-5 prose contains an internal sign contradiction: it defines
  GSAx = xG against − goals against (positive = above-average goalie) but then claims an
  above-average goalie has *negative* GSAx/shot and derives κ > 0. Under the document's own
  formula the goaltending direction is κ < 0, which is what was fitted (κ = −4.72). Recorded
  as a pre-registration defect; the frozen document was not edited after results.

## 2026-10-18 — Main result (NULL)

- **G2 does not beat G1 on the game outcome.** Test window (2024–25 + 2025-26, 2,624 games,
  5,248 goalie-starts): Brier diff G1−G2 = −0.000167 [−0.000573, +0.000230]; log-loss diff
  −0.000258 [−0.001129, +0.000590]. Both CIs include zero. On the validation season (2023)
  G2 is significantly WORSE on both. Fail-closed → **G2 rejected**.
- The goal distribution itself improves: CRPS 1.3917 → 1.3872 and PIT KS improves on both
  sides (0.0285→0.0234 home, 0.0246→0.0225 away). The goalie rating is real; the game-level
  forecast cannot exploit it.
- **Why: starter prediction is near coin-flip.** The naive "most recent start" heuristic
  predicts the observed starter only 49.7% of the time; the raw same-starter repeat rate in
  this data is 52.5% (25% on back-to-backs, ~61% at 3+ days rest, ~65% at 4+). NHL teams
  rotate goalies far more than the brief's GSAx plan assumes. Picking the wrong starter half
  the time injects as much noise as the goalie signal itself.
- **Fitted effect size is small but correctly signed:** κ = −4.72 ⇒ GA rate multiplier ranges
  0.968 (95th-pct goalie) to 1.020 (5th-pct goalie) — a ±2–3% GA swing, within the ±15%
  plausibility band. Consistent with the literature: goaltending is a real but modest lever.
- **Confirmation movement is real but small:** once the starter is observed, the win
  probability moves by |Δp| = 0.0071 on average (max 0.057), and GA rates move ~±0.004 goals.
  Recording both forecasts is worth doing; the movement is a finding, not a rounding error.
- **Lesson:** a goalie adjustment needs a real pre-game starter signal (Daily Faceoff-class
  feed) before it can beat a league-average baseline on game outcomes. Without it, the
  distribution-level gains are the honest ceiling of this feature.

## 2026-10-18 — Not done

- The tiered pick policy was not revisited (NO-GO stands).
- No production code touched; no prospective ledger modified; nothing pushed without approval.
