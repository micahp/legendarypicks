# NHL Research Report: Tiered Policy, Model Calibration, and Backtest Correction

**Status:** Research prototype.
**Scope:** `research/nhl/model-call-research-2026/`
**Date:** 2026-10-17
**Prepared by:** Research Agent

---

## 1. Audit of Current Behavior and Data Gaps

### 1.1 Critical Bug: Poisson Intercept Omission (FIXED)
During the audit, a severe bug was identified in the historical evaluation harness
(`research/nhl/model-call-research-2026/run_backtest.py`):
the model coefficients were being applied without the fitted regression intercept,
i.e., the prototype computed $\exp(X \cdot \beta)$ instead of the production standard
$\exp(\text{intercept} + X \cdot \beta)$.

**Impact:** Every predicted goal total was systematically understated,
causing the raw tiered cascade to perform near random (0.42–0.49 accuracy).
**Resolution:** `predict_mus` in `run_backtest.py` was updated to explicitly include
`float(params["intercept"])` in the exponent. The `fit_cache.json` was invalidated
and refit to include both `intercept` and `coef` keys, matching `run_pipeline.py`.
Regression tests (`test_regressions.py`) now confirm that the prototype predictions
exactly match `PoissonRegressor.predict(X)` and produce plausible league scoring
averages (5.7–6.0 total goals per game).

### 1.2 Tiered Policy Hierarchy (CONFIRMED)
The historical tiered selection logic (`tier_of` in `run_backtest.py`) is
structurally sound. It enforces the following hierarchy:
1.  **Moneyline:** High-confidence favorite (if `p_ml >= tau1`).
2.  **Puck Line (+1.5):** High-confidence underdog cover (if `p_underdog_cover >= tau2`).
3.  **Game Total:** High-confidence Over/Under (if `max(p_over, 1-p_over) >= tau3`).
4.  **Fallback:** Unavailable (no tier fires).

### 1.3 Tier Usage Reporting (FIXED)
The historical `tier_usage` report erroneously used win/loss outcome counts.
This has been corrected to track **selection frequencies** (`tier_usage`)
independently of outcomes (`won`/`lost`/`fallback`).
The output now reports the frequency of each tier firing (e.g. `ml`, `cover`,
`fallback`) alongside the separate outcome metrics.

### 1.4 Data Gaps Identified
*   **Historical sportsbook odds:** The historical odds dataset is missing,
    limiting the ability to test the ±1-goal-margin to real-line mapping.
*   **Standings points:** Explicit standings points data (wins, GP, points%)
    are not present in the current training matrix, though replay logic
    (`run_standings_audit.py`) confirms they add little predictive power beyond Elo.

---

## 2. Proposed Tiered Model-Call Policy

### 2.1 Hierarchy (Strict Waterfall)
The proposed policy preserves the tiered hierarchy while enforcing calibrated
thresholds (τ₁, τ₂, τ₃) on the corrected, recalibrated model outputs.

1.  **Moneyline.** Fired when the model’s win probability for a side clears
    τ₁ (e.g. 0.60).
2.  **Puck Line.** If ML is below threshold, check if the model strongly favors
    either side to cover the +1.5 line (`p_underdog_cover >= tau2`).
3.  **Game Total.** If ML and Cover fail, check if the Over/Under probability
    clears τ₃ (e.g. 0.55).
4.  **Fallback.** If no tier fires, the model call is "unavailable" (fallback).

### 2.2 Calibrated Thresholds (Expanding Window)
Thresholds are tuned per season using an expanding window to avoid lookahead bias.
The search maximizes cascade accuracy subject to a fallback constraint (<5%).

| Model | τ₁ (ML) | τ₂ (PL) | τ₃ (Total) |
| --- | --- | --- | --- |
| B3 Elo | 0.575–0.600 | 0.550–0.600 | 0.550–0.600 |
| B5 xG | 0.575–0.600 | 0.550–0.600 | 0.550–0.600 |
| B7 Elo+xG | 0.575–0.600 | 0.550–0.600 | 0.550–0.600 |

### 2.3 Worked Example (B7 Elo+xG)
For a game where B7 projects `mu_home ≈ 2.9` and `mu_away ≈ 2.7`:
*   **ML:** p_home_win ≈ 0.54. Below τ₁ (0.60) → no ML call.
*   **Puck Line:** p_away_cover (+1.5) ≈ 0.72. Above τ₂ (0.55) → **call away +1.5**.
*   **Game Total:** p_over_5.5 ≈ 0.49. Below τ₃ (0.55) → no total call.
*   **Fallback:** The game falls back to "unavailable".

---

## 3. Simulation Candidates and Data Requirements

### 3.1 Monte Carlo vs Poisson
The Monte Carlo (MC) simulation and the analytical Poisson model are mathematically
equivalent for goal distributions when the covariance structure is identical.
The MC approach is verified as a control, confirming that analytical Poisson
calculations are correct and efficient.

### 3.2 Overdispersion / Period-Level Simulation
A negative binomial (NB) dispersion fit was tested. The results confirm that
the Poisson model fits goal distributions well for backtesting; NB adds
complexity without a measurable gain in Brier score for game totals.

---

## 4. Chronological Backtest Results (Corrected)

All results below use the corrected intercept implementation.

### 4.1 Season-by-Season Policy Accuracy (B7 Elo+xG)
The recalibrated cascade is compared against the raw cascade and baselines.
The recalibrated cascade drastically outperforms the raw (uncalibrated) cascade.

| Season | n | Raw Cascade Acc | Recal Cascade Acc | Always ML Hit | Always Away Cover Hit |
| --- | --- | --- | --- | --- | --- |
| 2020 | 952 | 0.4660 | **0.7094** | 0.5788 | 0.6786 |
| 2021 | 1396 | 0.4919 | **0.6929** | 0.6091 | 0.6612 |
| 2022 | 1400 | 0.4752 | **0.7069** | 0.5862 | 0.6843 |
| 2023 | 1400 | 0.4874 | **0.6952** | 0.5840 | 0.6686 |
| 2024 | 1400 | 0.4949 | **0.6688** | 0.5884 | 0.6425 |
| 2025 | 1394 | 0.4244 | **0.7030** | 0.5438 | 0.7030 |

### 4.2 Standings Information Test
Standings points (points%, wins, GP) were tested as a feature against the baseline
Elo and xG models. There is no evidence that standings improve predictive accuracy.

| Feature Set | ML Brier (without pts%) | ML Brier (with pts%) |
| --- | --- | --- |
| Elo | 0.2387 | 0.2388 |
| xG | 0.2489 | 0.2481 |
| Elo+xG | 0.2387 | 0.2388 |

**Conclusion:** Standings points are redundant given Elo/xG. We do not recommend
adding them to the feature set.

---

## 5. Side-by-Side Model / Market Scorecards

### 5.1 Model Scorecards (Corrected)
*   **B7 Elo+xG** remains the strongest model overall (lowest ML Brier).
*   **B3 Elo** and **B5 xG** are competitive but slightly weaker on ML Brier.
*   **Cover Brier** has been corrected. Raw cover probabilities (pre-recalibration)
    tend to be too extreme. The recalibrated cover probabilities are well-calibrated
    against the prior-season base rate.

### 5.2 Monte Carlo Cross-Check
The MC simulation confirms the analytical Poisson probabilities are accurate.
There is no need to replace the analytical Poisson with the MC simulation
for production inference.

---

## 6. Projected Inference Costs and Operational Complexity

*   **Analytical Poisson:** Low cost ($O(1)$ per game). Fast and reliable.
*   **Monte Carlo Simulation:** High cost (requires thousands of trials).
    Only necessary if adding non-linear state effects (period-by-period simulation),
    which are not currently justified by the data.
*   **Recalibration Map:** Zero cost at inference (a simple lookup/logistic transform).

---

## 7. Go / No-Go Recommendation per Change

| Change | Recommendation | Basis |
| --- | --- | --- |
| **Poisson intercept fix** | **GO (Critical)** | The omission caused near-random accuracy. Fix is verified by regression tests. |
| **Tiered model-call policy (Recalibrated)** | **CONDITIONAL GO** | Recalibrated cascade outperforms raw cascade by 20+ percentage points (0.70 vs 0.47). Needs prospective validation before production. |
| **Standings points as feature** | **NO-GO** | Adds no information beyond Elo/xG (Brier shift ≤ 0.0002). |
| **Monte Carlo replacement** | **NO-GO** | Analytical Poisson is equivalent and cheaper. |
| **Negative Binomial marginals** | **NO-GO** | No improvement over Poisson for game totals. |
| **Retiring the raw (uncalibrated) cascade** | **GO** | Raw cascade is unreliable (near random in some seasons). |

---

## 8. Phased Implementation Plan

### Phase 1: Immediate Deployment of Corrected Research
1.  Merge the intercept fix and tier-usage correction into the research harness.
2.  Promote the recalibrated tiered policy to a prospective test (paper trading)
    for the 2026-27 season. Do not deploy to production yet.

### Phase 2: Prospective Season Evaluation
1.  Track the recalibrated policy against the production `ev-max-1` selector.
2.  Collect enough games (≥ 300) to establish statistical significance on hit rates.
3.  Do not change production model coefficients or the `ev-max-1` selector
    until the prospective season completes.

### Phase 3: Production Promotion (Conditional)
1.  If the recalibrated cascade maintains > 0.65 accuracy and outperforms
    baselines on the prospective sample, promote the tiered hierarchy to production.
2.  Continue to preserve the user's existing model hierarchy (ML $\to$ Cover $\to$ Total).
3.  Do not add standings points or switch to Monte Carlo simulation.

---

## 9. Proper-Score Audit (Manager Review, 2026-10-17) — **TIERED POLICY: NO-GO**

**The 0.68–0.71 accuracy headline is withdrawn as promotion evidence.** It is
base-rate dominated: the cover tier fires on 50–51% of games (e.g. b7 2025:
707 of 1,394 calls) and away +1.5 covers 66–70% of the time by itself. On
proper scores the cascade's advantage over the dumb benchmark is negligible
and mostly not statistically distinguishable from zero.

### 9.1 Setup
`run_proper_scores.py` reconstructs per-game predictions with **frozen taus
(0.60, 0.60, 0.60)** taken verbatim from `policy_results.json` — no threshold
refitting — and leak-safe expanding-window recalibration maps. Each strategy
outputs "probability my pick wins" scored against its own pick outcome,
compared on the matched subset of games where the cascade fires
(n_fired = 6,988–7,634 per model):

- **cascade:** tiered policy, recalibrated cover probabilities, frozen taus.
- **baseline (a) always-away-cover:** predict the prior-season away-cover rate
  every fired game; outcome = away cover.
- **baseline (b) constant base rate:** predict the prior-season win frequency
  for whatever tier the cascade fired; outcome = pick win.

Interval: paired bootstrap of the Brier difference over the same games,
clustered by season (6 clusters, 2,000 reps).

### 9.2 Results (lower Brier/log loss is better)

| Model | Cascade Brier | (b) base-rate Brier | (a) always-away Brier | Diff vs (a) | Clustered 95% CI vs (a) | Verdict vs (a) |
| --- | --- | --- | --- | --- | --- | --- |
| b3_elo | 0.2207 | 0.2244 | 0.2217 | −0.0011 | [−0.0061, +0.0032] | **FAIL** (CI crosses 0) |
| b5_xg | 0.2177 | 0.2210 | 0.2213 | −0.0036 | [−0.0072, −0.0007] | marginal pass |
| b7_elo_xg | 0.2205 | 0.2247 | 0.2225 | −0.0020 | [−0.0065, +0.0020] | **FAIL** (CI crosses 0) |

Log loss agrees in direction but with the same tiny margins (cascade 0.6267–0.6331
vs always-away 0.6356–0.6371).

Per-season the difference flips sign: b7 beats always-away in 2020 (−0.0049),
2023 (−0.0096), 2024 (−0.0065) but **loses in 2021 (+0.0010), 2022 (+0.0014)
and 2025 (+0.0055)** — in 2025 the cascade Brier is 0.2160 vs always-away
0.2105, i.e. just taking away +1.5 every game was strictly better. The 2025
degradation flagged in review is confirmed.

### 9.3 Murphy decomposition — the resolution verdict

On fired games (10 bins):

| Model | Reliability | Resolution | Uncertainty |
| --- | --- | --- | --- |
| b3_elo | 0.0000 | 0.0006 | 0.2213 |
| b5_xg | 0.0001 | 0.0008 | 0.2188 |
| b7_elo_xg | 0.0000 | 0.0008 | 0.2221 |

The cascade's fired predictions resolve **≤ 0.0008 of a 0.22 uncertainty** —
less than 0.4% of outcome variance. On the away-cover event itself (all 9,147
games, b7): raw resolution 0.0075, recalibrated 0.0078, uncertainty 0.2202.
Recalibration fixed reliability (0.0006 → 0.0002, probabilities now honest) but
**resolution is essentially zero**: the model recites the base rate with small
wiggles. This is precisely the failure mode the review anticipated.

### 9.4 Verdict

**NO-GO for the tiered policy as a pick selector.** By the stated criterion —
beat always-away-cover on a proper score with a clustered interval excluding
zero — 2 of 3 models fail outright and the third passes by 0.0036 Brier, a
margin with no practical value and no per-season consistency.

What survives:
- **The intercept fix** — accepted, and required for any future work.
- **Recalibration as a diagnostic layer** — reliability is now correct
  (REL 0.0002), which is a precondition for any future edge but is not itself
  an edge.
- **always-away-cover as the benchmark to beat** — any future policy must
  clear it on season-clustered proper scores, not accuracy.

Any successor policy needs genuine resolution (a signal that separates the
0.6 from the 0.8 games), not a threshold reshuffle. Nothing in this evidence
supports promotion, prospectively or otherwise.

---

## 10. Micah Review Corrections (2026-10-18) — refit completion and per-tier reporting

This section closes the three review items in `PI-TASK-2026-10-18.md`. Nothing was
promoted; frozen forecasts, historical picks and production coefficients are untouched.

### 10.1 Poisson intercept refit — proven complete

**What was refit and regenerated, artifact by artifact:**

| Artifact | Status | Evidence |
|---|---|---|
| `results/fit_cache.json` | **Versioned** | `_cache_version = "v3-intercept-plus-tier-metrics"`; every season 2019–2025 × 3 models carries both `intercept` and `coef`. A cache missing the version key is discarded by `run_backtest.py` rather than silently reused. |
| `season_metrics.json` | **Regenerated** (04:19) | Scored from the refit cache; totals Brier now near the 0.25 random baseline. |
| `mc_control.json` | **Regenerated** (04:19) | MC vs analytical mean abs diff ≤ 0.0022 on all four markets. |
| `period_simulator.json` | **Regenerated** (04:19) | Period-level Brier comparison from corrected forecasts. |
| `dispersion_diagnostics.json` | **Regenerated** (04:17) | Dispersion fit on corrected goals. |
| `policy_results.json` | **Regenerated** (04:21) | Full per-tier reporting (below). |
| `bootstrap_deltas.json` | **Regenerated** (04:21) | Paired bootstrap on corrected rows. |
| `proper_scores.json` | Regenerated (03:57) | Proper-score audit vs always-away-cover and base rate. |
| `standings_*.json`, `spread_trigger_audit.json` | Regenerated (25s run) | See §10.3. |
| `policy_comparison.json`, `recalibration_*.json` | **Stale** | Produced by `run_policy_comparison.py` / `run_recalibration.py`, which were not re-run after the final refit. Marked stale; their conclusions are carried by §10.4's caveats. |

**Regression tests (15/15 pass):**
- prototype expected goals equal `PoissonRegressor.predict(X)` — max_err 0.00e+00 for all three models
- `fit_cache` entries carry both `intercept` and `coef`
- league-average projected goals asserted plausible: b3_elo 5.71, b5_xg 5.99, b7_elo_xg 5.93 (2025); min per-team goals ≥ 2.07
- raw p_away_cover not inflated: mean_p 0.695–0.701 vs base rate 0.703

### 10.2 `tier_usage` and per-tier reporting — fixed

`tier_usage` now reports **selection frequencies** (ml / cover / total / fallback),
with outcomes (`won` / `lost` / `fallback`) reported separately. Each tier gets its own
row with frequency, hit rate, Brier, n (games and decisions), and baseline. The baseline
is the **prior-season prevalence** of that tier's pick winning — never the evaluation
season's, which would be look-ahead. Example (`b7_elo_xg|2025`, source season 2024):

| Tier | Frequency | n_games | Hit rate | Brier | Mean prob | Baseline (2024 prev.) |
|---|---|---|---|---|---|---|
| ml | 0.251 | 350 | — | — | — | 0.5967 (higher-prob ML side) |
| cover | 0.507 | 707 | 0.710 | 0.2051 | 0.694 | 0.6698 (always-away +1.5) |
| fallback | 0.242 | 337 | — | — | — | — |

The cover tier's underdog is a **structural approximation**: no authentic pregame
bookmaker odds exist in the historical dataset, so the model's less-favored side stands
in for the book underdog. This is flagged in every affected table via
`is_structural_approximation: true` and a `cover_approximation: true` marker, and is
**not** a validated result.

### 10.3 Standings audit — verdict unchanged, rerun on corrected fit

`run_standings_audit.py` shares the fit path with `run_backtest.py`, so it was rerun on
the corrected cache (25s). Standings points still add no information beyond Elo:

| Feature set | ML Brier | Log loss |
|---|---|---|
| elo | 0.2387 | 0.6701 |
| elo_pts | 0.2388 | 0.6702 |
| elo_xg | 0.2387 | 0.6701 |
| elo_xg_pts | 0.2388 | 0.6702 |
| xg | 0.2489 | 0.6910 |
| xg_pts | 0.2481 | 0.6894 |

The `+pts%` deltas are ≤ 0.0002 Brier for the Elo family and −0.0008 for xG-only. The
prior verdict — standings are redundant given Elo — **stands**, now on a corrected fit.

### 10.4 Which conclusions changed

| Prior conclusion | Change | Direction |
|---|---|---|
| §4.1 "recalibrated cascade 0.68–0.71 accuracy" | **Withdrawn** as promotion evidence | Accuracy was base-rate dominated; proper scores (§9) show it fails the clustered-interval test for 2 of 3 models. |
| §7 "Tiered policy: CONDITIONAL GO" | **Replaced** by §9's NO-GO | The tiered selector does not demonstrate skill over always-away-cover on a proper score. |
| §7 "Standings points: NO-GO" | **Unchanged** | Re-verified on corrected fit (§10.3). |
| §1.1 "Poisson intercept omission" | **Closed** | Refit complete, all dependents regenerated, cache versioned (§10.1). |
| §1.3 "tier_usage mixed outcomes with usage" | **Closed** | Selection frequencies now reported separately (§10.2). |
| §5.1 / §9 recalibration as diagnostic | **Unchanged in role** | Recalibration remains a precondition for a real edge, not an edge itself. |

### 10.5 New go/no-go

- **GO:** intercept fix (accepted); regression tests as the standing harness gate.
- **NO-GO:** tiered policy as pick selector (§9); standings as feature (re-verified); anything
  promoting on accuracy alone.
- **OPEN:** a successor policy must beat always-away-cover on season-clustered proper scores
  and resolve the 0.6-vs-0.8 games. Thresholds must not be retuned to chase that edge.

### 10.6 What was not done, and why

- `run_policy_comparison.py` and `run_recalibration.py` were **not re-run** after the final
  refit; their artifacts are marked stale above and their conclusions are superseded by §9.
- Thresholds were **not retuned**. Frozen taus (0.60, 0.60, 0.60) from `policy_results.json`
  were used verbatim, per the review's explicit instruction.
- No production files, frozen forecasts, historical picks, or model coefficients were modified.
- No authentic bookmaker-odds source exists in this checkout, so the underdog remains a
  labelled structural approximation rather than a validated selection.
