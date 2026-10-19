# DIAGNOSIS: FBS total-score calibration — bias, dispersion or shape?

Date 2026-10-19 · Branch `feat/fbs-archive` · Mode: research-only, no refit, no new candidate.
Works from the frozen Phase 4 artifacts only: `research/fbs/phase4/`, `docs/frozen-fbs-phase4-scores.json`,
and the committed `backend/fbs_phase4_scores.py`. G2h and the Phase 4 fit are untouched.

---

## Verdict

**The G-CAL failure is predominantly conditional bias (location), with a secondary dispersion component
and a small residual shape defect in the extreme upper tail.**

- **Bias — yes, but not a global bias.** The walk-forward mean bias is **+0.04 points** (predicted
  53.08, observed 53.12), i.e. zero. The bias is **conditional on the predicted total**: the model's
  predicted mean is about **twice as variable as the data supports**. OLS of `obs_total` on
  `pred_total` (the PMF mean the PIT is computed against) gives a slope of **0.5032 ± 0.0691**
  (walk-forward), **0.5173 ± 0.1221** (holdout), **0.4138 ± 0.2127** (2026). A calibrated forecast
  has slope 1.0. The model over-shoots at both ends: low predictions are too low, high predictions
  are too high.
- **Dispersion — secondary.** After removing the conditional bias, the model is **~9% too wide**
  (RMSE / mean predictive SD = 0.91), concentrated in the high-total buckets (0.84–0.90) and the
  extreme upper tail. Scaling the NegBin dispersion parameter R by **1.10–1.20** restores PIT
  uniformity (KS p 0.053–0.093). Part of this is a downstream artefact: R is fitted by moments on
  uncalibrated residuals, so it absorbs some of the excess mean variance.
- **Shape — not the primary driver.** The body of the distribution is correctly shaped when it is
  centred correctly: the 50–60 predicted-total bucket is PIT-uniform at baseline (KS p = 0.12), and
  after mean calibration every bucket passes or is marginal. The one genuine shape defect is the
  **extreme upper tail**: the model puts **1.11%** of mass above 110 points uncalibrated
  (**26.6 games**) and **0.60%** after mean calibration (**14.4 games**), against **0.08% observed
  (2 games)**; it is still 0.42% (10 games) at R × 1.15 and 0.30% (7 games) at R × 1.30. It affects
  ~1% of games.

The marginal total PIT is nearly uniform because the low-end and high-end conditional errors
**cancel**. The failure is visible only when the PIT is conditioned on the predicted total — which is
why this diagnosis was required before registering another candidate.

The Phase 4 verdict stands: **NOT_ADOPTED**. Nothing here re-opens it.

---

## 1. What was held fixed

No refit, no retune, no specification change, no new candidate. Every number below is recomputed from
the frozen per-observation outputs:

- `research/fbs/phase4/pmf/per_observation_scores.csv` — 3,554 rows × 6 models, observation-level
  PIT, CRPS, coverage, outcomes.
- `research/fbs/phase4/pmf/margin_total_pmf.npz` — per-observation 241-point PMFs.
- `research/fbs/phase4/per_game_parameters.csv` — per-game μ_h, μ_a, R, λ3 (lets the PMF be rebuilt
  from first principles; rebuild agrees with the npz to 9.3e-10).

The model examined is **H0b**, the Phase 4 primary: independent NegBin2 on decayed points ratings,
`var = μ + μ²/R`. Population is the Phase 4 population: **2,397 walk-forward / 807 frozen holdout /
350 in 2026**, game 401778314 excluded.

Minor artefact note, not part of the diagnosis: `MANIFEST.json` declares `support.total = [0, 120]`,
but the PMF is 241 points and its mean reproduces `pred_total` exactly on support **0…240**. The
declared total support is a documentation error; the arrays are on 0…240.

---

## 2. PIT by season — the marginal test is a noisy cancellation

H0b total PIT, randomized, recomputed from the PMFs (mid-point convention; structural result
identical to the randomized run):

| period | n | mean PIT | KS stat | KS p |
|---|---:|---:|---:|---:|
| walk-forward 2023 | 792 | 0.5185 | 0.0460 | 0.0677 |
| walk-forward 2024 | 798 | 0.5280 | 0.0585 | **0.0081** |
| walk-forward 2025 | 807 | 0.5072 | 0.0289 | 0.4992 |
| **walk-forward all** | **2,397** | **0.5179** | **0.0385** | **0.0016** |
| frozen holdout | 807 | 0.5094 | 0.0322 | 0.3668 |
| 2026 development | 350 | 0.5227 | 0.0569 | 0.1995 |

Margin PIT, same construction, for contrast — clean everywhere:

| period | n | mean PIT | KS p |
|---|---:|---:|---:|
| walk-forward all | 2,397 | 0.4986 | 0.9675 |
| 2023 / 2024 / 2025 | 792 / 798 / 807 | 0.4921 / 0.4943 / 0.5093 | 0.771 / 0.699 / 0.690 |

**The marginal failure is not present in every season.** 2023 is marginal (p = 0.068), 2024 rejects
(p = 0.008), 2025 passes (p = 0.499). The pooled test rejects only because n = 2,397 gives it power.
A per-season reading would have said "one noisy season"; that reading is wrong — see §3.

A second reason the marginal test is weak here: the predictive total is right-skewed, so a correctly
centred forecast has a mean PIT slightly above 0.5 by construction. The walk-forward mean PIT of
0.518 is therefore not by itself evidence of bias.

---

## 3. PIT by predicted total — the failure is conditional, and it is large

H0b walk-forward, bucketed on `pred_total` (the model's own mean total):

| predicted total | n | mean PIT | KS p |
|---|---:|---:|---:|
| < 40 | 176 | **0.6484** | **< 0.0001** |
| 40–50 | 712 | **0.5873** | **< 0.0001** |
| 50–60 | 971 | 0.5003 | 0.1203 |
| 60–70 | 437 | **0.4177** | **< 0.0001** |
| > 70 | 101 | **0.4037** | **0.0029** |

The two ends fail in **opposite directions**. Low predicted totals land at the 65th percentile of
their own forecast distribution (the games score more than the model says); high predicted totals
land at the 40th (they score less). The bucket boundaries were fixed in advance (the brief's own
example bins) and were not tuned.

**The pattern is present in every season**, which is the point the marginal per-season test misses:

| season | <40 | 40–50 | 50–60 | 60–70 | >70 |
|---|---:|---:|---:|---:|---:|
| 2023 | 0.638 | 0.593 | 0.507 | 0.418 | 0.402 |
| 2024 | 0.706 | 0.588 | 0.512 | 0.413 | 0.431 |
| 2025 | 0.602 | 0.582 | 0.481 | 0.421 | 0.382 |

**And it is present on the holdout that passed the marginal test**, and in 2026:

| period | <40 | 40–50 | 50–60 | 60–70 | >70 |
|---|---:|---:|---:|---:|---:|
| holdout (n=807) | 0.589 | 0.585 | 0.485 | 0.421 | 0.371 |
| 2026 dev (n=350) | 0.606 | 0.597 | 0.492 | 0.439 | — (n=6) |

The holdout's marginal pass (p = 0.367) is a **power artefact**: its regression slope is
**0.5173 ± 0.1221**, statistically indistinguishable from the walk-forward 0.5032. The holdout is not
a different regime; it is the same conditional bias with a third of the sample.

This is the single most important finding in the document: **a marginal PIT pass at n = 807 does not
certify a total distribution when the conditional bias is this large.** The gate's walk-forward test
was right to refuse.

---

## 4. Mean and variance diagnostics — the direct bias/dispersion measurement

H0b walk-forward, by predicted-total bucket. `pred ψ` is the mean of the PMF's mean; `E[var]` is the
mean of the PMF's own variance; `obs var` is the realised variance of outcomes in the bucket.

| bucket | n | pred μ | obs μ | bias (obs−pred) | mean pred SD | RMSE | RMSE/SD | E[var] | obs var | obs var / E[var] |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| < 40 | 176 | 36.15 | 43.44 | **+7.29** | 12.49 | 16.68 | **1.33** | 157.2 | 235.9 | 1.50 |
| 40–50 | 712 | 45.58 | 50.02 | **+4.44** | 15.39 | 16.55 | 1.07 | 237.9 | 257.0 | 1.08 |
| 50–60 | 971 | 54.64 | 53.95 | −0.69 | 18.15 | 16.18 | 0.89 | 330.4 | 258.2 | 0.78 |
| 60–70 | 437 | 63.63 | 57.24 | **−6.39** | 20.86 | 17.61 | 0.84 | 435.8 | 276.5 | 0.63 |
| > 70 | 101 | 74.74 | 65.97 | **−8.77** | 23.93 | 19.73 | 0.82 | 573.9 | 311.4 | 0.54 |
| **all** | **2,397** | **53.08** | **53.12** | **+0.04** | **17.65** | **16.76** | **0.94** | **319.7** | **281.4** | **0.88** |

Two effects, in order of size:

1. **The bias is a gradient, not a level.** +7.3 points at the low end, −8.8 at the high end, +0.04
   pooled. The model is unbiased on average and wrong at both ends.
2. **The dispersion gradient is a consequence of the bias.** Where the model's mean is too low
   (<40), the realised spread exceeds its own (ratio 1.50, RMSE/SD 1.33 — too narrow). Where the
   mean is too high (>70), the reverse (ratio 0.54, RMSE/SD 0.82 — too wide). The middle bucket is
   near-nominal on both (0.78, 0.89). This is the signature of a mean error, not an independent
   dispersion error: the residuals are inflated or deflated by the location miss.

The direct slope estimate makes the location error explicit. The estimator is **OLS of `obs_total` on
`pred_total`** over the H0b rows of each period — the same `pred_total` the PIT is computed against.
(The csv column is the PMF mean; it differs from the untruncated `mu_h + mu_a` by up to 3.4 points on
749 of 2,397 games because the NegBin vectors are truncated at 120 and renormalised, so `pred_total`
is the correct x-variable here.)

| period | slope (obs on pred) | 95% CI | intercept | r² |
|---|---:|---|---:|---:|
| walk-forward | **0.5032** | ±0.0691 | 26.41 | 0.0784 |
| frozen holdout | **0.5173** | ±0.1221 | 25.09 | 0.0789 |
| 2026 dev | 0.4138 | ±0.2127 | 30.76 | 0.0401 |
| by season 2023 / 2024 / 2025 | 0.5037 / 0.4889 / 0.5164 | ±0.115 / ±0.123 / ±0.122 | 26.38 / 27.81 / 25.08 | 0.0852 / 0.0707 / 0.0789 |

The slope is **stable at ~0.50 in every season and every period**. The ratings explain **7.8%** of
total-score variance (r² = 0.078), against **29%** of margin variance (margin slope 0.898 walk-forward,
0.975 holdout). Same ratings, much weaker signal for the total — and the model uses the rating
contribution at full strength, so the predicted total is over-dispersed by roughly the reliability
factor.

---

## 5. Scoring range — where the mass actually is

Pooled walk-forward, before and after a diagnostic mean calibration (calibration = the fitted line
above, applied only to decompose the error; not a proposed model):

| total range | predicted % | predicted % (mean-calibrated) | observed % |
|---|---:|---:|---:|
| 0–9 | 0.04 | 0.02 | 0.08 |
| 10–19 | 1.56 | 0.97 | 1.13 |
| 20–29 | 8.23 | 6.68 | 5.72 |
| 30–39 | 17.10 | 16.46 | 13.85 |
| 40–49 | 21.13 | 22.38 | 23.24 |
| 50–59 | 19.00 | 20.84 | 23.03 |
| 60–69 | 13.87 | 15.01 | 16.69 |
| 70–79 | 8.79 | 9.01 | 9.30 |
| 80–89 | 5.03 | 4.73 | 4.84 |
| 90–109 | 4.05 | 3.24 | 2.04 |
| **>110** | **1.12** | **0.60** | **0.08** |

Threshold view (walk-forward, uncalibrated): the model puts **29.0%** of mass at ≤ 40 against
**23.1%** observed (+5.9 pp), **19.1%** at ≥ 70 against **16.3%** (+2.8 pp), **10.3%** at ≥ 80
against **7.0%** (+3.3 pp), and **7.4%** at ≥ 85 against **4.1%** (+3.3 pp). Both tails are
over-weighted before calibration.

After mean calibration the low end is close (30–39 still +2.6 pp heavy), but **the upper tail stays
heavy**: **0.60%** of mass above 110 against **0.08%** observed — **14.4 games** predicted, 2 observed.
At R × 1.30 it is still 0.30% (7 games), and at R × 1.5, 0.20% (4.8 games), 2.5× observed. That is a
genuine **shape** excess in the extreme tail, though it is ~1% of games and may not be the binding
constraint once the mean and R are corrected.

The very low end (0–9) is *under*-predicted (0.02% vs 0.08%) — but that is 2 observed games out of
2,397, so it is not a material part of the failure.

---

## 6. Decomposition — how much is bias, how much is dispersion?

The diagnostic decomposition shifts each frozen PMF so its mean equals the fitted calibration line
(shape preserved, NegBin2 μ scaled, R held), then optionally rescales the spread. This is a
**measurement device**, not a fit, not a candidate, and not used to claim any gate would pass.

**A. Mean correction only** (shrink predicted total by the fitted slope; NegBin2 mean scaled, R held):

| bucket | n | residual bias after | mean PIT after | KS p after |
|---|---:|---:|---:|---:|
| < 40 | 176 | −1.16 | 0.484 | 0.518 |
| 40–50 | 712 | +0.68 | 0.520 | 0.043 |
| 50–60 | 971 | +0.05 | 0.511 | 0.060 |
| 60–70 | 437 | −1.19 | 0.494 | 0.138 |
| > 70 | 101 | +1.95 | 0.548 | 0.088 |

Every bucket's conditional mean PIT moves to ~0.50 and every bucket passes or is marginal. The
conditional bias is essentially removed by a single scale on the mean.

But the pooled PIT **still rejects** (KS p = 0.0025) and the per-season picture is mixed
(2023 p = 0.100, 2024 p = 0.009, 2025 p = 0.361). So the mean is not the whole story.

**B. Dispersion after mean correction.** RMSE / mean predictive SD = 16.10 / 17.76 = **0.91**, i.e.
~9% too wide, concentrated at the high end:

| bucket | RMSE/SD before | RMSE/SD after mean correction |
|---|---:|---:|
| < 40 | 1.33 | **1.00** |
| 40–50 | 1.07 | 0.96 |
| 50–60 | 0.89 | 0.90 |
| 60–70 | 0.84 | 0.85 |
| > 70 | 0.82 | 0.84 |
| all | 0.94 | 0.91 |

Mean correction fixes the low-end narrowness exactly (1.33 → 1.00) and leaves the high-end
over-dispersion nearly intact (0.82 → 0.84). So there are **two separable components**: a location
gradient (large, fixes the low end and most of the conditional PIT) and a high-μ over-dispersion
(small, survives the location fix).

**C. R sensitivity after mean correction** (shape fixed, dispersion scaled):

| R multiplier | pooled PIT KS p | mean PIT |
|---|---:|---:|
| 1.00 | 0.0025 | 0.5102 |
| 1.10 | 0.0527 | 0.5082 |
| 1.15 | **0.0932** | 0.5074 |
| 1.20 | 0.0784 | 0.5066 |
| 1.30 | 0.0552 | 0.5051 |

A **10–20% increase in R** (less over-dispersion) takes the pooled PIT from rejection to marginal
acceptance, peaking at R × 1.15 (p = 0.093). Since R is fitted per block by moments on
**uncalibrated** residuals, this is coherent: the too-variable means inflate the residual variance,
the moment fit answers with a too-small R, and after the mean is corrected the fitted R is too small
by roughly 10–20%.

**D. Shape.** With the mean corrected and R × 1.15, the PIT passes by the 5% threshold but only just,
and the >110 tail is still heavy. The body shape is not the problem — the 50–60 bucket is uniform at
baseline and after correction. The residual is a **tail** defect at high totals.

---

## 7. Verdict, with the numbers that carry it

**Primary — conditional bias (location).** Predicted total is over-extreme: slope **0.5032 ± 0.0691**
walk-forward, **0.5173 ± 0.1221** holdout, **0.489–0.516** by season. Conditional mean PIT runs
**0.648 (<40) → 0.404 (>70)** walk-forward, the same ordering in every season and on the holdout.
Mean bias is **+0.04**, so this is a slope error, not a level error. Correcting the mean alone moves
every bucket to ~0.50 and removes the low-end narrowness (RMSE/SD 1.33 → 1.00).

**Secondary — over-dispersion at high totals.** After mean correction, RMSE/SD = **0.91** pooled,
**0.84–0.85** in the 60+ buckets; R × 1.10–1.20 restores PIT uniformity (p 0.053–0.093). The
moment-fitted R is entangled with the mean error, so this is partly a downstream artefact and partly
a real high-μ dispersion miss.

**Tertiary — heavy extreme upper tail (shape).** Predicted mass above 110 is **1.11% uncalibrated
(26.6 games) and 0.60% after mean calibration (14.4 games)**, against **0.08% observed (2 games)**;
still **0.42% (10 games)** at R × 1.15 and **0.20% (4.8 games)** at R × 1.5. This is a genuine
NegBin2 tail excess, but it is ~1% of games and is not the binding constraint on the gate by itself.

**Not implicated:** a global mean bias (it is zero), and a wrong body shape (the central buckets are
uniform when centred correctly). The marginal PIT's near-uniform histogram — deciles
[208, 220, 210, 237, 250, 251, 253, 281, 233, 254], χ² p = 0.022 — is the low-end and high-end errors
cancelling, not evidence of calibration.

---

## 8. The smallest plausible fix — a hypothesis, not implemented

Nothing below was fitted into a candidate, registered, or run through the gates. It is the smallest
change the evidence points at.

1. **Put a reliability scale on the predicted total.** The rating-derived mean total needs shrinking
   toward the league mean by a factor fitted on **strictly prior** seasons. The empirical slope is
   ~0.50 and stable, so one scale parameter is enough. Mechanically this is the same kind of
   correction the margin side already receives implicitly: margin's slope is 0.90–0.98, close enough
   to 1 that the miss is invisible in its PIT; the total's 0.50 is not.
2. **Refit R after (or jointly with) the mean scale.** Expect R to rise ~10–20%. Fitting R on
   calibrated residuals instead of raw ones is the principled version of the same change.
3. **Only if the tail still fails after 1–2:** address the upper tail explicitly. A NegBin2 variance
   function with a less aggressive μ² term (or a lighter-tailed family) is the candidate; the
   evidence does not distinguish "R too small" from "family too heavy-tailed" above 110 without a
   refit.

The order matters: (1) is the dominant effect and is measurable from the frozen data; (2) is a
consequence of (1); (3) is a residual that may not bind once (1) and (2) are in.

**What would have to be true for this to be wrong:** if the ~0.50 slope were an artefact of the
holdout-style rating freeze rather than the ratings themselves. It is not — the slope is the same on
walk-forward (refit per block) and holdout (frozen), and the same in all three seasons.

---

## 9. What this diagnosis does NOT establish

- It does **not** re-open or overturn the Phase 4 verdict. NOT_ADOPTED stands; G-CAL failed correctly.
- It does **not** show that the §8 fix passes the gates. The residual tail defect may still fail
  G-CAL after (1) and (2); that is exactly what a future pre-registered candidate would test.
- It does **not** establish the correct functional form of the mean calibration. The linear slope is
  a diagnostic summary of a monotone pattern; whether the true map is linear, isotonic, or
  feature-dependent is untested.
- It does **not** establish *why* the predicted mean is over-dispersed — rating noise, missing
  features, the exponential link, or the decay rate are all consistent with the data. Only the
  symptom (mean too variable) is measured.
- It does **not** establish whether R should be constant across the μ range. The high-μ dispersion
  gradient suggests it should not be, but no varying-R model was fitted.
- It does **not** establish whether the >110 tail excess is a family defect or an R defect. Both
  reduce it; only a refit separates them.
- It does **not** test anything prospectively. 2026 is development data, not confirmation.
- It does **not** audit margin at finer resolution. Margin's slope (0.90–0.98) is close to 1 but
  still below it; a finer margin analysis could find a smaller version of the same issue. Margin's
  PIT passes, so it is not the failure at hand.
- It does **not** change any gate, any coefficient, or any Phase 4 artifact.

---

## 10. Reproduce

```bash
cd /root/lp-fbs-archive
/root/legendarypicks/backend/venv/bin/python3 - <<'PY'
import numpy as np, pandas as pd
from scipy import stats

# The calibration slope and intercept (Sec. 4, Sec. 7)
h = pd.read_csv('research/fbs/phase4/pmf/per_observation_scores.csv')
wf = h[(h.model == 'H0b') & (h.period == 'walk_forward')]
s = stats.linregress(wf.pred_total, wf.obs_total)
print(f"OLS obs_total ~ pred_total: slope={s.slope:.4f} +/-{1.96*s.stderr:.4f} "
      f"intercept={s.intercept:.3f} r2={s.rvalue**2:.4f} n={len(wf)}")

# The >110 predicted mass (Sec. 5, Sec. 7)
z = np.load('research/fbs/phase4/pmf/margin_total_pmf.npz', allow_pickle=True)
ids = {str(g): i for i, g in enumerate(z['game_id'])}
idx = [ids[str(g)] for g in wf.game_id]
pmf = z['H0b_total'][idx].astype(np.float64)
print(f"uncalibrated >110: {pmf[:, 111:].sum(1).mean()*100:.2f}% "
      f"({pmf[:, 111:].sum(1).sum():.1f} games)")
print(f"observed >110:     {np.mean(wf.obs_total > 110)*100:.2f}% "
      f"({int((wf.obs_total > 110).sum())} games)")
PY
```

The PMFs are rebuilt from `per_game_parameters.csv` (μ_h, μ_a, R) with the same NegBin2
parameterisation as `backend/fbs_phase4_scores.py`; the rebuild matches the frozen npz to
9.3e-10 on the max element. All PIT values quoted use the mid-point convention; the randomized
convention gives the same structural result (walk-forward total KS p = 0.0016).

---

## Artifacts

- This document: `research/fbs/DIAGNOSIS-FBS-TOTAL-CALIBRATION-20261019.md`.
- Source artifacts (unchanged, frozen): `research/fbs/phase4/`, `docs/frozen-fbs-phase4-scores.json`.
- Log entry: `research/fbs/LEARNINGS.md`.
- No model code, no candidate, no gate, and no Phase 4 artifact was modified.
