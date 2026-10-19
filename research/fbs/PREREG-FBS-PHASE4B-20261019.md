# PRE-REGISTRATION — FBS Phase 4b candidate H0b-MC

**Status:** PRE-REGISTERED 2026-10-19, before any Phase 4b code, fit, or evaluation number.
**Branch:** `feat/fbs-archive` at `0bc000ba`. **Diagnosis accepted at:** `0bc000ba`.
**Scope:** this document is the entire deliverable. No code, no harness, no fit, no PMF regeneration,
no Phase 5, no Phase 6, no gate change, no merge to dev, no touch to the frozen Phase 4 JSON/PMF.

---

## 1. Context (accepted, not re-opened)

Phase 4's primary score model H0b fails **G-CAL** on the total: randomized PIT p = **0.0016**
walk-forward, while the margin passes (p = 0.968) and the holdout passes (p = 0.367). The accepted
diagnosis (`research/fbs/DIAGNOSIS-FBS-TOTAL-CALIBRATION-20261019.md`) found:

- OLS `obs_total ~ pred_total` (the PMF mean the PIT is computed against): slope **0.5032 ± 0.0691**,
  intercept **26.410**, r² **0.0784**, n = 2,397 walk-forward.
- Mean bias (predicted minus observed, the Phase 4 convention): **−0.041** (pred 53.0787 / obs 53.1197).
  No global bias. The error is **conditional** on the predicted total.
- Conditional mean PIT by predicted-total bucket: **0.6484 / 0.5873 / 0.5003 / 0.4177 / 0.4037**
  (n 176 / 712 / 971 / 437 / 101), the same ordering in every season and on the holdout.
- Secondary: high-μ over-dispersion, RMSE/SD **0.907**; R × 1.10–1.20 restores PIT in the
  diagnostic decomposition.
- Tertiary: >110 tail **1.11%** (26.6 games) vs **0.08%** (2 observed).

The cause is **conditional mean bias**, not shape. H0b-MC tests that cause directly and nothing else.
The Phase 4 `NOT_ADOPTED` verdict stands.

---

## 2. Candidate H0b-MC — definition

For each game `i`, let `t_i` be the frozen H0b total-PMF mean (`pred_total` in
`research/fbs/phase4/pmf/per_observation_scores.csv`) and `S(i)` its season. The corrected total mean is

```
t'_i = a_{S(i)} + b_{S(i)} · t_i
```

with `(a_S, b_S)` from a single OLS of `obs_total` on `pred_total` over the calibration set `C(S)`
defined in §3. The candidate's **total** distribution is the frozen H0b total PMF re-centred so its
mean is `t'_i` (§4). Nothing else changes: no new covariates, no refit of the Poisson scaling α, the
home advantage γ, or the NegBin2 over-dispersion R, and no change to the margin PMF.

---

## 3. Calibration fit — exact rule

### 3.1 Calibration set `C(S)`

`C(S)` = every game in the Phase 4 run with `season < S` for which H0b produced a total forecast,
under the same eligibility rule as the evaluation ledger (FBS-vs-FBS, final score, no outcome filter).
It includes the 2015–2022 training window and the prior evaluation seasons, and excludes the scoring
season `S` and every later season.

| scoring season | calibration set |
|---|---|
| 2023 | 2015–2022 |
| 2024 | 2015–2023 |
| 2025 | 2015–2024 |
| 2026 (dev only) | 2015–2025 |

The exact row count of each window is computed by the future run and reported; no row estimate is
pre-registered.

### 3.2 Estimator

Unweighted OLS with intercept: `obs_total = a_S + b_S · pred_total`, over all rows of `C(S)`. **One fit
per scoring season**; the same `(a_S, b_S)` applies to every UTC date block in `S`. Per-block fitting
on within-season data is forbidden — it is leakage.

### 3.3 First block with a valid fit

The first scored block is **2023-08-21** (the first UTC date block of the 2023 season), calibrated on
2015–2022.

### 3.4 Minimum prior history

A season `S` is scored only if `|C(S)| ≥ 250` (the G-SAMPLE holdout floor). Every scored season meets
this — 2023 already has the full 2015–2022 window, and later seasons have more. **No scored season is
excluded; the excluded count is zero.** The rule is declared so that a future season without enough
prior history would be excluded and counted, never pooled silently.

### 3.5 Holdout freezing

The 2025 holdout uses `(a_2025, b_2025)`, fitted on 2015–2024 and **frozen at 2025-01-01**. It is not
updated within 2025. It is numerically identical to the 2025 walk-forward season calibration (both use
2015–2024); that is stated, not hidden. The holdout outcomes are never used to calibrate the holdout.

### 3.6 Leakage prohibitions

- No fit may use the scoring season or any later game.
- No per-block refitting within a season.
- No outcome filter, no re-selection, no dropping games because they are hard.
- No holdout outcome may enter any calibration coefficient.

### 3.7 Reproduction of the prior-season forecasts

The 2015–2022 H0b forecasts are **not** in the frozen Phase 4 ledger. The future run must reproduce
them deterministically from the frozen `block_parameters.csv` (α, γ, R, μ_h0, μ_a0 read, not re-estimated)
and the archive's game data. Before fitting, it must verify the reproduction by rebuilding the 2023
forecasts and comparing `pred_total` against the frozen `per_observation_scores.csv`; the maximum
absolute difference must be **≤ 1e-6**. If the reproduction fails, **stop and report it** — do not fall
back to a shorter window, do not proceed. This is a reproduction, not a refit.

---

## 4. PMF transformation — exact operation

### 4.1 What is transformed

**Only the total PMF.** The margin, home and away PMFs are the frozen H0b ones, unmodified.

### 4.2 Shift of the support

For game `i`, `δ_i = t'_i − t_i`. The new total CDF is `F'(x) = F(x − δ_i)` for `x = 0…240`, where `F`
is the frozen H0b total CDF extended with `F(x) = 0` for `x < 0` and `F(x) = 1` for `x ≥ 240`. Linear
interpolation between integer support points. The new PMF is `p'(k) = F'(k) − F'(k−1)`, `k = 0…240`,
with `F'(−1) = 0`; negative entries are clipped to zero and the vector is renormalised to sum to 1.

### 4.3 Mean tolerance

After the shift, `|Σ_k k·p'(k) − t'_i| ≤ 1e-3` is required. If it is not, apply one correction
`δ_i ← δ_i + (t'_i − mean)` and repeat. If it is still `> 1e-3` after two iterations, **flag the game
as a transformation failure and report it**. Do not silently accept a mis-centred PMF.

### 4.4 Truncation and renormalisation

Support is fixed at **0…240** (241 points), the same as the frozen H0b total PMF. The CDF clamps at 0
and 1, so mass shifted past either boundary is absorbed into the boundary atom and the renormalisation
restores total mass 1. Report per game the boundary mass before and after the shift and the
renormalisation factor. Flag any game where the boundary mass changes by more than **0.01**.

### 4.5 What is held fixed

α (Poisson scaling), γ (home advantage) and **R** (NegBin2 over-dispersion — the parameter the brief
calls the over-dispersion α) are read from the frozen `block_parameters.csv` and **not refitted**. No
new covariates. The only new estimated quantities are `(a_S, b_S)`.

### 4.6 Joint-consistency caveat

Shifting the total PMF alone leaves the margin PMF unchanged, so the `(home, away)` joint is no longer
internally consistent after the shift. This is deliberate: the candidate isolates the total mean and
the margin-side metrics are inherited from H0b. If the candidate is adopted, a production
implementation must re-derive a consistent joint (e.g. an additive μ shift split equally between the
two sides); that is out of scope here and is **not** part of the adoption test.

---

## 5. Population

Identical to the `3db4b32d` registration:

| period | games | note |
|---|---:|---|
| walk-forward 2023–25 | **2,397** | 792 / 798 / 807 by season |
| 2025 frozen holdout | **807** | the same 2025 games, frozen H0b fit |
| 2026 development | **350** | reported, not gated |

Game **401778314** stays out, as pre-registered. No re-selection, no new exclusions, no outcome
filters. Every model and baseline is scored on exactly the same game set; a game that cannot be scored
is reported as a coverage failure, never silently dropped.

**Scored set:** all 2,397 walk-forward, 807 holdout, 350 dev2026. The calibration fit window is
strictly prior seasons and removes no scored game.

---

## 6. Metrics to report

Everything Phase 4 reported, on the same population, plus the calibration diagnostics:

- **Point:** MAE, RMSE, bias (predicted minus observed) for home, away, margin, total, with week-block
  intervals.
- **Distribution:** CRPS, log score, randomized PIT (KS), central and shortest coverage at 50/80/90,
  endpoint-atom excess, `sd_pred` vs `sd_obs`, for margin and total.
- **Market:** spread Brier/log loss at ±3/7/10/14 and over/under at 45/48/52/56/60, paired against
  Constant and H1, with reliability bins and base rates.
- **Calibration diagnostics:** `(a_S, b_S)`, `|C(S)|`, the fit-window season list, the in-window slope,
  the post-correction slope with its 95% CI, the shift `δ` distribution, the boundary mass, and the
  per-bucket total-PIT table.

---

## 7. Gates — unchanged thresholds

The five Phase 4 gates, exactly as registered in §21.6 of `RESULT-FBS-PHASE3-B-20261018.md`, with **no
threshold change**:

| gate | requirement |
|---|---|
| **G-SAMPLE** | walk-forward n ≥ 1,500 and holdout n ≥ 250 |
| **G-DIST** | H0b-MC beats H1 on CRPS for **margin and total**, paired week-block interval entirely below zero, on the 2,397 walk-forward games; and the point difference is negative on the 807-game frozen holdout for both |
| **G-CAL** | randomized PIT does not reject `U(0,1)` at the 5% level (KS) for margin and total on walk-forward **and** holdout; and central coverage is within ±0.05 of nominal at 50/80/90 for margin and total on walk-forward. **Total-PIT p > 0.05 is required.** |
| **G-SPREAD** | beats **both** Constant and H1 on Brier for cover probability, pooled over the eight lines, paired interval entirely below zero on walk-forward, and negative on the holdout |
| **G-TOTAL** | the same test for over/under at the five totals |

Adoption requires all five. Fail-closed. A model that wins CRPS and loses PIT is **not adopted**.

**Inheritance note.** Because only the total PMF is transformed, the margin CRPS/PIT/coverage and the
spread probabilities are numerically identical to H0b's. G-DIST margin, G-CAL margin and G-SPREAD are
therefore inherited passes and are still reported. The candidate's own tests are **G-DIST total,
G-CAL total and G-TOTAL**.

### 7.1 Pre-declared slope-recovery check

After correction, re-fit `obs_total = a* + b* · t'` on the scored walk-forward games. The 95% CI for
`b*` must contain **1.0**. If it does not, the calibration did not remove the conditional bias; the
candidate is **not adopted**, and the failure is reported as a transformation failure, not a model
failure. Report the same check on the holdout (not gated).

### 7.2 Pre-declared per-bucket total PIT

Report the total PIT by **corrected** predicted-total bucket (<40, 40–50, 50–60, 60–70, >70), with n,
mean PIT and KS p per bucket, on walk-forward and holdout. Pre-declared reading: a pooled G-CAL pass
does not override a persisting bucket gradient. If, after correction, the low bucket's mean PIT is
still > 0.55, or the high bucket's is still < 0.45, with n ≥ 100 in that bucket and KS p < 0.05 for
that bucket, the conditional bias is not fixed and the candidate is **not adopted**, even if the
pooled p > 0.05. This is not a new threshold; it is the pre-declared meaning of "the conditional mean
was corrected".

---

## 8. Arms and multiplicity

**One primary arm: H0b-MC**, exactly as defined in §2–§4. **No secondary arms.** No multiplicity
adjustment is needed. Any variant run (e.g. the additive-μ joint-consistent transformation) is a
diagnostic, reported separately, and **cannot carry adoption**.

---

## 9. What would falsify the fix

- **F1 — transformation failed.** The post-correction slope CI excludes 1.0. The calibration did not
  remove the bias; diagnose the fit window/transformation. Do not proceed to a dispersion candidate.
- **F2 — bias was not the binding constraint.** The post-correction slope CI contains 1.0 (bias
  removed) but G-CAL total still rejects at 5%, pooled or per-bucket. The mean was necessary but not
  sufficient; the binding constraint is the residual dispersion/shape. The next candidate is the
  **R adjustment** (R × 1.10–1.20, fitted on strictly prior seasons), not another mean transform.
- **F3 — the correction hurt.** The corrected total CRPS is worse than H0b's by a paired interval
  excluding zero. The mean error was not the cause; record it and stop.
- **F4 — a gate fails.** Any of the five gates fails. Fail-closed; no re-specification.

The headline falsifier for "bias was not the binding constraint" is **F2**.

---

## 10. Expected outcome (an expectation, not a criterion)

The diagnosis's decomposition suggests the mean correction alone will substantially reduce the
conditional PIT gradient (bucket means toward 0.50) but **may not clear G-CAL pooled at 5%**: the
shift-based decomposition left p ≈ 0.01 and the rebuild-based left p ≈ 0.003, both using a global fit.
This candidate uses a leakage-free, per-season prior fit, so the actual p may differ. A pass would be
the first evidence that the mean was the binding constraint. A fail under F2 is an informative result
that sets up the R candidate — it is not a reason to loosen the gate or re-specify H0b-MC.

---

## 11. Artifacts the future run must persist (not produced here)

- The calibration coefficients `(a_S, b_S)`, `|C(S)|`, and the fit-window season list, per scoring season.
- The per-game shift `δ`, boundary mass before/after, renormalisation factor, and any transformation
  failure.
- The corrected total PMF per observation, so every aggregate is recomputable (the discrete-prop
  contract).
- The frozen H0b margin PMF, copied unchanged with a SHA-256 check against the Phase 4 artifact.
- The post-correction slope and its CI, and the per-bucket PIT table.
- The five-gate table and the verdict.

---

## 12. What this pre-registration does not do

- No code, no harness, no fit, no PMF regeneration, no result.
- No Phase 5, no Phase 6, no gate change, no merge to dev, no touch to the frozen Phase 4 JSON/PMF.
- No claim that H0b-MC passes; §10 is a prior, not a result.
- No re-opening of the Phase 4 `NOT_ADOPTED` verdict.
