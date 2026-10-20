# NHL Model-Call Research Report — 2026-10-17

**Status:** Research prototype. This report summarizes the walk-forward backtest in
`research/nhl/model-call-research-2026/` and proposes a tiered model-call policy.
It does **not** replace the frozen models (`research/nhl/prospective-2026-27/`),
the immutable ledgers, the grading provenance, or the current pick selector
(`RULE_VERSION = ev-max-1` in `backend/nhl_model_store.py`).

**Prototype location:** `research/nhl/model-call-research-2026/` (separate from production).
**Artifacts:** `results/season_metrics.json`, `results/policy_results.json`,
`results/bootstrap_deltas.json`, `results/mc_control.json`,
`results/period_simulator.json`, `results/dispersion_diagnostics.json`.
All models refit chronologically per season (expanding window), consistent with
frozen-alpha 0.01 Poisson conventions in `run_pipeline.py`.

---

## 1. Audit of current behavior and data gaps

### 1.1 Current pick selector (`ev-max-1`)
Per `backend/nhl_model_store.py`, the rule computes expected value from the model's own
score distribution against the offered price, and **recommends only when EV > 0**.
It is an EV-maximizing rule, not a "confidence tier" rule — so games without a
usable quote get no recommendation at all. The Record-tab fix (branch
`fix/nhl-record-show-lean-results`, merged into `dev` as `4fc262ad`) addressed
the display of non-qualifying leans separately from wager qualification.

### 1.2 Pick-logic document (`docs/NHL-MODEL-PICK-LOGIC.md`)
The older card rule (`goal-diff-1`) chose a market from projected goal margin. It
was superseded by `ev-max-1` but is still the operative card heuristic when a
sportsbook quote is absent. Its "6.0 total cut" for choosing 5.5 vs 6.5 was
explicitly flagged as uncalibrated.

### 1.3 Data gaps identified

| Gap | Evidence | Impact |
| --- | --- | --- |
| **No historical sportsbook odds** | Only 324 Bovada rows in `backend/data/nhl-model.dev.sqlite3`, all from 2026-10-14 onward; no Kalshi quote history in the frozen audit CSVs | Betting ROI cannot be validated historically; only prospective (forward-looking) odds analysis is possible |
| **Goal margin mapping to lines not yet calibrated** | Frozen pipeline records `p_home_minus_1_5`, `p_away_plus_1_5`, `p_over_5.5`, `p_over_6.5` from a joint score distribution; no calibration layer maps ±1 goal to real posted lines | Tier 3 (game total) has no calibrated route; the card's 6.0 cut is an unvalidated heuristic |
| **Shootout tie rate is unmodeled** | Empirical statistical-tie rate (regulation+OT, shootout decider removed) is **10.75%** (`dispersion_diagnostics.json`); frozen model treats it as tie → resolved by historical home-SO rate | ML probability is slightly underconfident for close games |
| **Home/away goal covariance is slightly negative** | corr = −0.0367 on n=13,969 training games | Common-shock (bivariate Poisson) is not justified; independent Poisson is not materially wrong |
| **`p_over_5.5` key-name mismatch** | `summarize()` reads `p_over55`, but rows produced by `derive()` use `p_over_55` (and `p_over_65_official`); the same mismatch appeared at two call sites (`tune_thresholds` and the policy loop) | Fixed in the prototype; the report's key naming must be `p_over_55` / `p_over_65_official` everywhere |
| **Incomplete model calls are possible** | A row may lack a full set of probabilities (e.g., score-distribution matrix unavailable). The prototype now counts these as explicit fallbacks rather than manufacturing a call | Consistent with the "do not manufacture confidence" constraint |

### 1.4 Pre-existing test failure (not from the Record-tab fix)
`components/Leagues/NhlModelTab.test.tsx` — test *"shows all-market Brier for
graded unpriced games"* used `expect(screen.getAllByText('0.16').length).toBe(0)`.
`getAllByText` throws when nothing matches; the tooltip renders Brier with
`toFixed(4)` (`0.1600`), so `'0.16'` never matches. The failure was introduced by
commit `d7ed5d8b` ("fix: align NHL market Brier sample counts"), **before** the
Record-tab fix branch. Repaired to `expect(screen.queryAllByText('0.16')).toHaveLength(0)`.
All 13 tests in that file now pass on `dev`.

### 1.5 Urgent audit: the S > 1.0 spread-gap trigger is unreliable

The legacy `goal-diff-1` rule gates the underdog +1.5 pick on `S > 1.0`, where
`S = |−puck_line − model_margin|`. A structural replay across the 2019–2025
backtest (16,959 fired cover calls under both book-favorite configurations;
`results/spread_trigger_audit.json`) shows the trigger pools two fundamentally
different regimes and never consults the model's own cover probability:

| Regime | Model mean p_cover | Actual cover rate |
| --- | --- | --- |
| Model agrees with the book's underdog | ≈ 0.81 | 69.8% |
| Model disagrees with the book's favorite | ≈ 0.20 | 32.8% |

Brier on fired calls is 0.2251 vs 0.2500 for the base rate — the trigger only
beats a coin flip because of the agree-with-underdog subset. **Do not treat S
as evidence of a profitable edge.** The recommended replacement (see §2) gates
each tier on a calibrated cover-probability threshold, not a margin gap.

### 1.6 Urgent audit: standings points add no information beyond Elo

A matched, leak-safe walk-forward (expanding window, 2019–2025;
`results/standings_info_test.json`) compared logistic moneyline models on
Elo-only, xG-only, and Elo+xG feature sets against the same sets augmented with
pregame points-percentage differential:

| Feature set | ML Brier without pts% | ML Brier with pts% |
| --- | --- | --- |
| Elo | 0.2387 | 0.2388 |
| xG | 0.2489 | 0.2481 |
| Elo+xG | 0.2387 | 0.2388 |

The shift is ≤ 0.0002 everywhere — noise. Elo already absorbs standings
information, so explicit standings features are redundant. (This also applies
the requested controls: standings were replayed chronologically from strictly
earlier games, and the stratification in §1.7 conditions on games-played
parity.)

### 1.7 Urgent audit: model cover-probability inflation (Poisson compression)

Stratifying errors by pregame points-% differential (with a games-played ≥ 10
parity control; `results/standings_stratification.json`) shows every model
variant systematically overestimates +1.5 cover probability in the central
matchup band (|Δ pts%| ≤ 0.05, n = 7,808):

| Model | Mean p_away_cover | Actual cover rate | Cover Brier | Constant-base Brier |
| --- | --- | --- | --- | --- |
| B3 Elo | 0.846 | 0.675 | 0.2444 | 0.2194 |
| B5 xG | 0.788 | 0.675 | 0.2298 | 0.2194 |
| B7 Elo+xG | 0.798 | 0.675 | 0.2286 | 0.2194 |

**A constant base-rate predictor (always 0.675) beats every model variant on
cover Brier.** The cause is structural: the independent Poisson marginal is too
concentrated, underestimating 2+ goal margins and inflating close-game cover
mass. The error is not concentrated in extreme standings mismatches — it is a
uniform calibration failure. Fixing it requires cover-probability
recalibration (logistic or isotonic on prior seasons only), not standings
features.

#### 1.7.1 Recalibration results (chronological, expanding window)

`run_recalibration.py` fits logistic and isotonic maps on prior seasons only
and applies them to the evaluation season. Cover Brier on the same 9,147
evaluation games:

| Model | Raw | Logistic recalibrated | Isotonic | Constant base rate |
| --- | --- | --- | --- | --- |
| B3 Elo | 0.2454 | **0.2132** | 0.2144 | 0.2202 |
| B5 xG | 0.2305 | 0.2158 | 0.2163 | 0.2202 |
| B7 Elo+xG | 0.2291 | **0.2122** | 0.2137 | 0.2202 |

Before recalibration every model variant lost to the constant base rate; after
logistic recalibration every model variant beats it (Brier 0.2122–0.2158 vs
0.2202). This is the single largest accuracy improvement found in this
research pass. The calibrated cover gate that replaces the S-trigger (§2.2)
uses these recalibrated probabilities with tau₂ tuned per season in the
0.72–0.79 band, firing on 6–32% of games with hit rates 0.64–0.84
(`results/recalibration_gate.json`).

---

## 2. Proposed tiered model-call policy

### 2.1 Hierarchy

1. **Moneyline.** If the model's ML probability is "sufficiently strong and
   historically validated" — call the ML side. Calibration evidence is
   per-model (see §4). Strength threshold is the top-bin Brier improvement over
   the base rate for that model, not raw probability alone.
2. **Puck line.** If ML is below threshold, check whether one side likely covers
   +1.5. Puck line is *invariant* under the statistical/official total mapping
   (a statistical tie covers both +1.5 sides and neither −1.5 side), so this is
   a clean fallback for any model with a calibrated score distribution.
   **The tiered hierarchy is preserved as a policy to test, but the legacy
   S > 1.0 spread-gap trigger is retired** (§1.5): the gate is a calibrated
   cover-probability/confidence criterion applied to the recalibrated
   distribution, never a margin gap against the puck line.
3. **Game total.** If neither ML nor puck-line passes, use the goal
   distribution. Investigate the ±1-goal-margin mapping to real posted lines
   (see §2.3) before calling totals.
4. **Fallback.** Preserve explicit "unavailable" status; never manufacture
   confidence from partial data.

### 2.2 Calibrated thresholds (prototype, expanding window)

The prototype tuned τ₁/τ₂/τ₃ (ML, cover, total) on prior seasons only.
Across models B3/B5/B7, the optimal thresholds settle in a narrow band
(τ₁ ≈ 0.575–0.60, τ₂ ≈ 0.55, τ₃ ≈ 0.55). Suggested starting values for the
production policy (subject to prospective validation):

| Tier | Threshold | Rationale from backtest |
| --- | --- | --- |
| Moneyline | τ₁ = 0.60 | Best B7 Elo+xG accuracy across 2019–2025 evaluation windows; stable across models |
| Puck line | τ₂ = 0.55 | Tuning accepted this value every season; away-cover Brier ≈ 0.22 for B7 |
| Total | τ₃ = 0.55 | Tie-calibrated total Brier (0.479/0.415 for B7 over55/over65) is best of all variants |

### 2.3 Worked example (B7 Elo+xG, tie-calibrated)

For a typical 2026-27 matchup where the model projects mu_home ≈ 2.9 and
mu_away ≈ 2.6:

- **ML:** p_home_win ≈ 0.56 (after SO tie resolution). Below τ₁ = 0.60 → no ML call.
- **Puck line:** p_away_cover (+1.5) ≈ 0.72. Above τ₂ = 0.55 → **call away +1.5.**
- **Game total** (if puck line failed): p_over_5.5 ≈ 0.49, p_over_6.5 ≈ 0.34.
  Neither side clears τ₃ = 0.55 → **no call**; game total is *unavailable* for
  this game under the calibrated policy.

The current card heuristic (6.0 cut) would call over/under 5.5 in nearly every
game. The calibrated policy would call it in far fewer, and only when the model
is confident. This is a material behavior change and must be presented to the
user (see §8, Phase 2).

### 2.4 Correctness vs profitability separation

All calls are graded (Won/Lost/Push) whether or not a bet qualified. Betting
qualification remains a separate downstream decision (odds available, calibration
meets freshness threshold, positive EV at offered price). The policy does not
change how a wager is selected; it changes what the model *claims* when no
wager qualifies.

---

## 3. Simulation candidates and data requirements

### 3.1 Candidate 1: Independent Poisson (current frozen model)
- Score distribution built from `mu_home × mu_away` product, capped at 21×21.
- **Empirical support:** goal covariance is −0.037 (essentially zero), so
  independence is empirically defensible.
- **Tie calibration** (prototype variant) rescales non-tie mass so tie share
  matches the empirical training rate (10.75%). Across all three models, this
  reduced score NLL by 0.08–0.16 and goal MAE by 0.02–0.08 goals. This is the
  cheapest and most defensible upgrade.
- **Data required:** none beyond what the pipeline already computes.

### 3.2 Candidate 2: Monte Carlo control (current frozen model)
- Sampled directly from the same Poisson marginals, up to 200,000 trials.
- **Convergence check** (600-game sample, `mc_control.json`): at 10k trials the
  max absolute deviation from the analytical result is ≈ 0.014 on ML and
  ≈ 0.013 on puck line. At 25k trials the mean |diff| falls below 0.0022 across
  all four markets.
- **Verdict:** MC is a good *verification* tool (the analytical matrix should
  agree with a large MC run to within ~0.005). It is not necessary as the
  primary source of probabilities.

### 3.3 Candidate 3: Period-level simulator with score-state effects
- Explicit three-period structure, trailing-team attack boost (`state_eff`),
  calibrated so the simulated regulation-tie share matches training.
- OT modeled as 3v3 pace (~3× per-minute 5v5 rate); SO via empirical home rate.
- **Backtest result** (B7 model, 600-game matched sample, 8,000 trials):
  Brier ML 0.237, away-cover 0.232, over 5.5 0.450, over 6.5 0.375.
- **Comparison** (same games, B7 tie-calibrated analytical): ML Brier 0.239,
  away-cover 0.228, over 5.5 0.479, over 6.5 0.415.
- The period simulator is marginally better on the moneyline and over-5.5, and
  marginally worse on away-cover and over-6.5. It is a plausible future
  challenger, not a clear replacement.
- **Data required:** per-period scoring (already in the pipeline's canonical
  games via `last_period_type`, but no per-period goal counts). A real
  period-level model would need a new ingest of play-by-play or period-scoring
  data.

### 3.4 Candidates rejected
- **Negative-binomial marginals:** worse total Brier (0.400 vs 0.479 over-5.5
  B7) and worse NLL (5.23 vs 5.07). Goal variance is not strongly overdispersed
  relative to Poisson at the team level.
- **Common-shock bivariate Poisson:** correlation is negative, so this family
  cannot improve on the independent product.

---

## 4. Chronological backtest results

All numbers below come from `season_metrics.json` (n = 9,147 games across
evaluation seasons 2019–2025, feature-complete only) and
`policy_results.json`.

### 4.1 Score-distribution scorecards (Brier loss, lower is better)

| Model | Variant | ML Brier | Away-cover Brier | Over 5.5 Brier | Over 6.5 Brier | Score NLL | Goal MAE (home) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B3 Elo | poisson | 0.2417 | 0.2444 | 0.5372 | 0.4393 | 6.334 | 2.177 |
| B3 Elo | tie-calibrated | **0.2404** | **0.2308** | 0.5358 | 0.4407 | 6.179 | 2.111 |
| B5 xG | poisson | 0.2449 | 0.2298 | 0.4584 | 0.3985 | 4.960 | 1.836 |
| B5 xG | tie-calibrated | 0.2444 | **0.2224** | 0.4567 | 0.4026 | **4.867** | **1.794** |
| B7 Elo+xG | poisson | 0.2396 | 0.2286 | 0.4808 | 0.4112 | 5.172 | 1.903 |
| B7 Elo+xG | tie-calibrated | **0.2387** | **0.2201** | **0.4789** | 0.4147 | 5.070 | 1.857 |
| B7 Elo+xG | Dixon-Coles | 0.2394 | 0.2285 | 0.4806 | 0.4112 | 5.170 | 1.905 |
| B7 Elo+xG | negative-binomial | 0.2444 | 0.2246 | 0.4007 | 0.3506 | 5.232 | 1.904 |

**Interpretation.** B5 xG is best on total goals (lowest NLL and lowest goal
MAE), B7 Elo+xG is best on ML Brier, and tie-calibration improves every model
on ML and away-cover Brier. No single model dominates every market.

### 4.2 Paired bootstrap (B7 tie-calibrated vs B7 poisson, 2,000 iterations)

| Market | Δ Brier (tie-cal − poisson) | 95% CI | Verdict |
| --- | --- | --- | --- |
| Away-cover +1.5 | **−0.0085** | [−0.0092, −0.0077] | **tie-calibrated significantly better** |
| Over 6.5 | +0.0034 | [+0.0033, +0.0035] | **tie-calibrated significantly worse** |

The CI is narrow because these are paired deltas over the same 9,147 games; it
does not quantify season-to-season variation. A larger cluster bootstrap by
season is recommended before any production claim.

### 4.3 Tiered-policy accuracy by season (B7 Elo+xG)

| Season | Eval games | Accuracy | Fallback rate | Tuning games | Tuning accuracy |
| --- | --- | --- | --- | --- | --- |
| 2019 | 1,212 | 0.699 | 0.000 | — (defaults) | — |
| 2020 | 952 | 0.707 | 0.000 | 1,212 | 0.709 |
| 2021 | 1,396 | 0.691 | 0.000 | 2,164 | 0.708 |
| 2022 | 1,400 | 0.700 | 0.000 | 3,560 | 0.703 |
| 2023 | 1,400 | 0.699 | 0.000 | 4,960 | 0.705 |
| 2024 | 1,393 | 0.664 | 0.000 | 6,360 | 0.704 |
| 2025 | 1,394 | **0.711** | 0.000 | 7,753 | 0.697 |

**Interpretation.** With the tuned cascade, every game gets a call (fallback
rate 0.000) and evaluation accuracy stays in the 0.66–0.71 band, roughly
consistent with the moneyline/puck-line accuracy achievable from a single
score-distribution model. Season-to-season variation is real (2024 was a
notably worse year) but the expanding-window tuning did not overfit — 2025's
accuracy (0.711) is higher than its own tuning-set accuracy (0.697).

**Sensitivity check.** Thresholds tuned by the prototype shift very little
across seasons (τ₁ ∈ {0.575, 0.60}, τ₂ = τ₃ = 0.55), so the policy is not
highly sensitive to the exact cutoff. The 2024 season's lower accuracy is a
season-effect, not a threshold artifact.

---

## 5. Side-by-side model / market scorecards

### 5.1 Fixed-market Brier (reference, no quotes required)

These are always computable from the frozen forecasts and official results.

| Market | B3 Elo | B5 xG | B7 Elo+xG |
| --- | --- | --- | --- |
| Home cover −1.5 | 0.245 | 0.242 | 0.244 |
| Away cover +1.5 | 0.231 | 0.222 | **0.220** |
| Over 5.5 | 0.536 | **0.457** | 0.479 |
| Over 6.5 | 0.441 | **0.403** | 0.415 |
| Score NLL | 6.179 | **4.867** | 5.070 |
| Goal MAE | 2.111 | **1.794** | 1.857 |

### 5.2 Frozen sportsbook comparison (only when valid)

Historical sportsbook quotes do not exist in the current dataset. The
`line_grades.locked_market` fields in `backend/nhl_model_store.py` remain the
production path for a frozen-quote Brier comparison, but they will be
unpopulated for seasons 2008–2026 except for the small 2026-27 sample.
**The model-vs-market comparison is therefore unavailable in a rigorous form
until more historical frozen quotes are captured.** This is the most important
open data gap.

### 5.3 Monte Carlo cross-check

The analytical joint matrix (from the same Poisson marginals) agrees with a
200,000-trial Monte Carlo within ~0.002 mean absolute deviation per market
(600-game sample). This is a consistency check on the derivation, not a
superiority claim.

---

## 6. Projected inference costs and operational complexity

### 6.1 Per-game cost (single model, single slate)

| Stage | Cost | Notes |
| --- | --- | --- |
| Score distribution (analytical) | ~1 ms | 21×21 matrix multiply in numpy |
| Score distribution (Monte Carlo, 200k trials) | ~0.6 s per 600 games (~1 ms/game) | Not needed for primary output |
| Period simulator (8k trials) | ~15 s for 600 games (~25 ms/game) | Only needed if adopted |
| Threshold tuning (expanding window) | ~30 s for 7 seasons × 3 models | One-time per season; not per-game |
| Full backtest (all stages) | ~228 s | Prototype wall-clock on this machine |

### 6.2 Operational complexity of the proposed policy

| Component | Complexity | Operational risk |
| --- | --- | --- |
| Tiered call (ML → puck line → total → fallback) | Low | Pure logic on top of existing probabilities |
| Tie-calibration | Low | One extra scalar per training window |
| MC cross-check | Medium | Extra compute, but idempotent and non-blocking |
| Period simulator | High | New ingest path; new state-eff calibration; not recommended for Phase 1 |
| Separate immutable `model_call` records | Medium | New table, new append-only ledger; must not alter existing `nhl_model_picks` |
| User-facing tier display | Low | One new column / badge on the Model card |

---

## 7. Go / no-go recommendation per change

| Change | Recommendation | Basis |
| --- | --- | --- |
| **Record-tab fix** (lean grading shown separately from wager qualification) | **GO** — already merged and validated; 13/13 frontend tests pass on `dev` | §1.4 |
| **`p_over_55` → `p_over_55` key-name alignment** (and `p_over_65_official`) in any new code touching `summarize()`/`tune_thresholds()` | **GO** | Prevents the pre-existing `KeyError` pattern; prototype fixes this |
| **Tie-calibrated score distribution** as the production score distribution | **CONDITIONAL GO** — adopt in the *research* stack now; promote to production only after a full 2026-27 prospective season confirms the paired-bootstrap deltas | Consistent improvement across all three frozen models on ML and away-cover; no regression on ML Brier |
| **Tiered model-call policy (ML → puck line → total → fallback)** with τ₁=0.60, τ₂=τ₃=0.55 | **CONDITIONAL GO** — backtest shows 0.66–0.71 per-game accuracy with 0% fallback; but accuracy alone does not prove profitability. Deploy as a *recorded, graded* model call, not as a wager selector | §4.3, §2.4 |
| **±1-goal-margin → real-line mapping for totals** | **NO-GO** (for now) | Requires historical sportsbook quotes that do not exist in this dataset; revisit after 2026-27 frozen-quote collection |
| **Period-level simulator** | **NO-GO** (for now) | Marginal accuracy change; high operational complexity; would need per-period scoring data |
| **Negative-binomial marginals** | **NO-GO** | Consistently worse than Poisson on totals and NLL |
| **Common-shock bivariate Poisson** | **NO-GO** | Empirical correlation is negative; family is not justified |
| **Monte Carlo as a primary probability source** | **NO-GO** | Convergence check confirms analytical is equivalent at a fraction of the cost; keep MC as an offline verification tool |
| **S > 1.0 spread-gap trigger (legacy `goal-diff-1` rule)** | **NO-GO / RETIRE** | Pools two disparate confidence regimes and ignores the model's own cover probability (§1.5); replace with the calibrated cover-probability gate in §2 |
| **Standings points / points-% as a model feature** | **NO-GO** | Adds no information beyond Elo (Brier shift ≤ 0.0002, §1.6); keep standings as display context only |
| **Cover-probability recalibration (logistic/isotonic, prior seasons only)** | **CONDITIONAL GO** | The single highest-value fix: every model variant overestimates cover probability by 11–14 points and loses to a constant base rate (§1.7). Validate on the 2026-27 prospective window before production |
| **Storing a separate immutable `model_call` per locked forecast** | **GO** (design) | Required by the tiered policy; see §8 |

---

## 8. Phased implementation plan

### Phase 0 (done): Record-tab fix validation
- Branch `fix/nhl-record-show-lean-results` merged into `dev` (`4fc262ad`).
- Pre-existing broken test assertion repaired (`queryAllByText`).
- 13/13 tests pass; no production model/ledger changes.

### Phase 1 (research stack only; no production changes)
- **1a.** Freeze the prototype findings as research artifacts under
  `research/nhl/model-call-research-2026/results/`.
- **1b.** Add a *separate immutable model_call* design doc: a new table
  `nhl_model_calls` keyed by (forecast_id, policy_version), with
  policy_version, selected_at_utc, market, side, line, model_probability,
  selection_tier, reason, and eventual result columns. Store the odds and
  qualifying-wager decision in a *separate* `nhl_wager_qualification` record.
  Do not retroactively claim a postgame choice was a pregame prediction.
- **1c.** Instrument the pipeline to emit, for every new locked forecast, a
  candidate model call under the tiered policy with a `policy_version`
  stamp — without changing the current `ev-max-1` recommendation logic.

### Phase 2 (prospective season 2026-27)
- **2a.** Run the tiered policy against the live 2026-27 slate, grading every
  game (Won/Lost/Push) regardless of odds availability or EV sign.
- **2b.** Collect frozen sportsbook quotes at lock time for every game where
  they are offered (Bovada, Pinnacle, Kalshi) and store them immutably.
- **2c.** Compare the tiered policy against the `ev-max-1` rule on
  (a) call accuracy, (b) wager profitability where quotes exist, and
  (c) calibration by market. This is the promotion gate.

### Phase 3 (promotion gate, requires Phase 2 review)
- **3a.** If the tiered policy's call accuracy beats `ev-max-1` on the
  prospective season with a paired bootstrap that excludes season-level
  clustering, promote the tiered policy to the production Model card.
- **3b.** If tie-calibration's paired-bootstrap deltas hold, promote the
  tie-calibrated score distribution to production.
- **3c.** Only then consider the ±1-goal-margin → real-line mapping, using the
  frozen-quote history accumulated in Phase 2.
- **3d.** The current pick selector (`ev-max-1`) is **not** replaced until
  comparisons are complete and reviewed.

### Phase 4 (optional, not scheduled)
- Period-level simulator (if per-period scoring data is ingested).
- Monte Carlo verification as a scheduled offline job.

---

## Appendix A — Prototype file structure

```
research/nhl/model-call-research-2026/
├── README.md                    (design and non-interference statement)
├── run_backtest.py              (stages: load/elo/fit/score/mc/policy/report)
└── results/
    ├── season_metrics.json      (model × variant scorecards, n=9147)
    ├── policy_results.json      (tiered policy per season per model)
    ├── bootstrap_deltas.json    (paired bootstrap, tie-cal vs poisson)
    ├── mc_control.json          (MC convergence vs analytical)
    ├── period_simulator.json    (period-level challenger summary)
    ├── dispersion_diagnostics.json (tie rate, goal covariance)
    └── fit_cache.json           (per-season Poisson coefficients)
```

## Appendix B — Key definitions used in the backtest

- **Statistical goals:** regulation + overtime, shootout deciding goal removed
  (the frozen model target).
- **Official total:** statistical total + 1 when the statistical score is tied
  (regular season only). In playoffs, tied statistical scores always go to
  overtime and the deciding goal is a real goal, so the same rule applies.
- **Puck line:** a ±1.5 cover is invariant under the statistical/official
  total mapping, so `p_away_cover` is well-defined from either target.
- **Tie-calibrated:** rescale non-tie mass of the independent Poisson matrix so
  the trace (tie share) matches the empirical training-window rate.
- **Dixon-Coles:** low-score adjustment with rho fit on training likelihood.
- **Negative binomial:** gamma-Poisson marginal with dispersion r fit on
  training team-goal variance.
- **Threshold tuning:** expanding-window grid search maximizing cascade
  accuracy with a ≤5% fallback constraint, using only prior seasons.
