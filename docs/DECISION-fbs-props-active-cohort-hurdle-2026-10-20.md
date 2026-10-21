# Decision: FBS direct props active-cohort veto and hurdle-model research
Date: 2026-10-20
Status: **NOT_ADOPTED for product; authorize research hurdle refit only.** No release, data migration, background scheduler, or official locks authorized.
Source: research/fbs-direct-props-2026-10-20 @ ad535b9b (COHORT.md, cohort_analysis.py, cohort_2025.csv, cohort_detail.json). Previous all-rows research @ 6fe15ca9 is retained, but the product inference is invalidated.

## The falsification

2025 test, same committed per-row predictions as original all-rows research. Paired delta = CRPS_model - CRPS_trailing5; positive means **model worse**.

| Market | All 2025 rows Δ | Observed > 0 rows Δ | 90% game-clustered interval on positive rows |
|---|---:|---:|---|
| Passing attempts | -0.324 | **+0.992** | [+0.932, +1.053] |
| Passing yards | -2.881 | **+10.628** | [+9.816, +11.433] |
| Rush attempts | -0.158 | **+0.307** | [+0.288, +0.327] |
| Rushing yards | -1.582 | **+1.271** | [+1.090, +1.454] |

The all-rows CRPS victory was driven by players recording no stat: passing attempts 6525/9059 (~72%); passing yards 6650/9059 (~73%); rush attempts 13879/21800 (~64%); rushing yards 14023/21800 (~64%). **Not 72–74% for all four markets**. Refit/shrinkage against an all-appearance position mean underpredicts positive-usage QB plays/yards. Regular-volume and high-volume slices also lose. Calibration on positive-usage rows is materially worse than headline coverage.

**Product decision:** Do not publish the four direct models as better player forecasts, model picks, priced edges, or an adopted Props overlay. No new Player Projections tab is warranted. If a versioned research view is ever used internally, label it with this failed cohort verdict. Preserve both studies; do not delete or rewrite the original all-rows measurements.

## Why cohort definitions matter

The COHORT.md diagnostic defines "active" separately per market as **that game's observed stat > 0**. This is an **after-the-fact diagnostic**, not a pregame eligibility rule. Its "regular" and "top_volume" classifications can also involve same-season knowledge not available at each kickoff. Do not select the prospective betting/forecast population with any fact derived from that same game's outcome, or by end-of-season volume rankings computed before the season ends.

- **Positive attempts/carries** are a more faithful *usage* condition than positive yards. A player can attempt passes for zero passing yards or carry for zero/negative rushing yards. In the hurdle implementation, define event usage from attempts/carries, and keep zero/negative yards outcomes inside the conditional yards distribution as appropriate.
- Distinguish **did not dress, DNP, dressed with zero touches, positive usage, and missing/uncertain stat** when publisher data supports it. Do not convert missing to zero. Report what can't be distinguished.
- Published player-prop lines and actual provider grading/void rules determine which outcomes are in the *bettable market* evaluation. No fabricated prices or inferred voids.

## New hypothesis and model contract

Test a two-part pregame model that forecasts opportunity separately from conditional volume and efficiency.

1. **Usage hurdle**: estimate P(pass_attempts > 0) and P(rush_attempts > 0) for each player and game, using **pregame-only** player, team, lineup/depth chart/injury (only if timestamped), prior snap/usage and opponent information. Start with transparent historical-rate/logistic baselines. Never read this game's attempts, positive-yards status, starter designation derived from the final box score, or an end-of-season rank.
2. **Conditional usage**: among historical games with >0 attempts/carries, estimate positive counts using truncated count distributions (e.g., zero-truncated NegBin), with position-specific shrinking to **active** peers. Build a conditional efficiency model for yards/attempt or yards/carry. **Keep zero and negative yards possible** despite positive attempts/carries.
3. **Full distribution**: explicitly retain (a) P(usage), (b) P(volume/stat | usage), and (c) the **unconditional mixture** for the whole pregame outcome. In symbols: P(Y | pregamedata) = [1 - P(usage)] * P(Y | no usage) + P(usage) * P(Y | usage, pregamedata). For attempts/carries Y=0 in the no-usage component; for yards Y=0 absent usage unless data shows other routes to a recorded stat. Tie yards distributions to their matching attempt/carry process so means and probabilities are internally consistent.
4. **Freeze all components**, not just the conditional curve, in any eventual pregame lock: IDs, fixture, usage probability, conditional parameters/quantiles, mixture distribution or reproducible sampler seed, model version, data-version fingerprint, as-of cutoff, market settlement assumptions. Do not introduce a scheduler or locks as part of this research task.

## Experiment, baselines, and proof obligations

- Fork a **new research branch** from ad535b9b; leave original research results untouched. Use scripts/prior_art.py before adding duplicate code; follow AGENTS.md and installed research/testing skills. No writes outside research unless scoped and agreed.
- Preserve chronological 2018–23 fit / 2024 tuning / 2025 replay structure so experiments can be compared, **but explicitly label redesigned 2025 results exploratory**: 2025 was already examined to discover this defect. Require a truly fresh forward-only 2026 test or new prospective locked set for a claim of independent generalization. Never fit/tune using 2025 while calling it untouched.
- Compare four controls on the **same exact game-player-market rows**: old 2-stage direct model, original trailing-5 (zeros included), a fair conditional-active trailing-5 baseline (history filtered by *earlier* positive attempt/carry events), and a simple pregame hurdle baseline. Keep position prior as an additional reference. If the new model beats an artificially weak all-appearance baseline only, verdict is fail.
- Stratify results by **pregame-defined cohorts** (players with actual published offers, depth-chart starters where pregame timestamps exist, recent >0 usage frequency, prior snap/attempt/carry tiers, weeks 1–6 / 7–12 / 13+). Report **postgame** positive/zero usage cohorts as additional *diagnostics*, not as prospective selection.
- Evaluate P(usage) with Brier/log loss, calibration and coverage; conditional count/yards with CRPS, MAE/bias, PIT and interval coverage; unconditional distribution with CRPS + line-specific P(over) Brier/log loss vs matched historical empirical baselines, priced no-vig market when valid. Pair by exact game/player/market/line and pregame odds snapshot. Cluster bootstrap at least game_id and use week-block sensitivity; do not split individual markets from the same game between train/test.
- Report zero-rate capture, top-quartile participation, rookie/no-history coverage, actual-market-line universe, the complete denominator (including missed identity/unknown/DNP/void and all dropped), as-of source availability, and any distribution incoherence.
- The target is not just beating the historical CRPS on every roster row; demonstrate improvement where a user **could identify the player and market before kickoff**. Avoid conditioning any live model on realized activity or on whether the sportsbook happened to grade a winning side.
- Resolve/flag the existing 2026 opponent-ID gap before interpreting opponent adjustments or claiming an actual 2026 prospective market edge.

## Go / no-go

**Research candidate only if** the new pregame hurdle model beats the fair conditional/trailing baselines on paired market-relevant cohorts, does not get its entire win from the zeros, yields materially calibrated usage and conditional tails, and reproduces all numbers/coverage with pinned input hashes. Report failures even if a pooled overall CRPS looks better.

**Product/integration remains blocked** until a separately accepted version also has leakage-proof as-of scoring, verified same-game player IDs/markets/lines, official result/DNP handling, immutable forecast provenance and prospective evidence. Refer to DECISION-forecast-first-leagues-market-first-props-2026-10-20.md for where it would appear after adoption: existing Props cards + player/game detail, not a new model destination.

## Handoff

Worker may start a hurdle refit in a new branch from research/fbs-direct-props-2026-10-20 @ ad535b9b. Keep outputs in a new research/fbs subfolder or a clearly versioned subdirectory, run falsification and deterministic reproduction, and push only when the user has authorized the push. Report the full denominator, model and baseline paired scores by cohort, uncertainty, calibration and next verdict. **No dev/prod merges, timers, lock issuance, or UI changes.**
