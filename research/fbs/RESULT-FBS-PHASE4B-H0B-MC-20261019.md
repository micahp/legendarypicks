# RESULTS: FBS Phase 4b — H0b-MC conditional-mean calibration

Run 2026-10-19 on `feat/fbs-archive`, against the pre-registration in
`research/fbs/PREREG-FBS-PHASE4B-20261019.md` (commit `680b259a`), before any Phase 4b code
existed. Every number below is from `research/fbs/phase4b/{summary_by_period,paired,bucket_pit,
calibration,per_game_shift}.csv` and the per-observation PMFs.

Reproduce:

```bash
cd /root/lp-fbs-archive
/root/legendarypicks/backend/venv/bin/python3 backend/fbs_phase4b_h0bmc.py
```

Deterministic: seed 20261017, 2,000 bootstrap replicates, read-only against the frozen Phase 4
artifacts. Runtime ~3m.

## Verdict: NOT_ADOPTED — 4 of 5 gates pass, G-CAL fails on the 50% total coverage

The conditional-mean correction **does what it was registered to do**: the total PIT goes from
**p = 0.0016 to p = 0.0869** (no longer rejecting at 5%), total CRPS falls from **9.4611 to
9.1371**, and the paired total CRPS advantage over H1 widens from **−1.0672 to −1.3912**. The
per-bucket mean PIT collapses to ~0.50 in every bucket with n ≥ 100.

It still fails G-CAL: the walk-forward **50% central interval covers 0.5561 of outcomes against
0.50 nominal**, a **+0.0561** deviation against the registered **±0.05** tolerance. The gate is
unchanged and fail-closed, so H0b-MC is **not adopted**. The binding constraint has moved from the
PIT (mean bias) to the 50% central-interval coverage — a different defect from the one Phase 4 had.

This is a completed experiment, not a reason to re-specify.

## Reproduction gate (§3.7) — PASS

Rebuilt the 2023 forecasts from the frozen `block_parameters.csv` (α, γ, R, μ_h0, μ_a0 read, never
re-estimated) and the archive's game data, then compared `pred_total` to the frozen
`per_observation_scores.csv`:

| check | value |
|---|---:|
| games compared (2023 walk-forward) | 792 |
| **max absolute difference** | **6.963e-13** |
| mean absolute difference | 1.710e-14 |
| pre-registered threshold | 1e-6 |
| result | **PASS** |

The fit window reproduces the frozen pipeline at 6.963e-13, six orders of magnitude inside the
threshold. No fallback, no shortened window.

## Calibration (§3–§4)

One OLS of `obs_total` on `pred_total` per scoring season, over strictly prior seasons, FBS-vs-FBS,
no outcome filter:

| scoring season | calibration window | n | slope [95% CI] | intercept | r² |
|---|---|---|---:|---|---:|
| 2023 | 2015–2022 | 5,849 | 0.5598 [0.5227, 0.5969] | 23.863 | 0.1300 |
| 2024 | 2015–2023 | 6,641 | 0.5566 [0.5216, 0.5916] | 23.988 | 0.1275 |
| 2025 | 2015–2024 | 7,439 | 0.5513 [0.5179, 0.5847] | 24.314 | 0.1234 |
| 2026 (dev) | 2015–2025 | 8,247 | 0.5523 [0.5203, 0.5843] | 24.153 | 0.1220 |

The prior-season slope is **~0.55**, slightly steeper than the 2023–2025 global 0.5032 from the
diagnosis. That is expected: the 2015–2022 relationship is stronger (r² 0.130 vs 0.078). The
evaluation-time slope after correction is 0.904, not 1.0 (see §7.1), so the calibration removed most
but not all of the over-extremity.

The PMF transformation is the registered support shift: `δ = t' − t`, CDF interpolation on 0…240,
clipped and renormalised. Diagnostics over all 3,554 evaluation games:

| diagnostic | max | threshold |
|---|---:|---:|
| absolute mean error after shift | 1.290e-4 | 1e-3 |
| boundary-mass change | 7.014e-5 | 0.01 |
| transformation failures | 0 | 0 |
| iterations beyond the first shift | 0 | — |

α, γ and R were read from the frozen `block_parameters.csv` and never refitted. The margin PMF is
byte-identical to the Phase 4 artifact: SHA-256
`726683cb91572f5552429e3707a24118e20fdabfcdcf1dcc22d1b77709750bee`, asserted in the harness and
recorded in the frozen JSON.

## Population

Identical to the `3db4b32d` registration:

| period | games | blocks |
|---|---:|---:|
| walk-forward 2023–25 | 2,397 | 65 |
| 2025 frozen holdout | 807 | 22 |
| 2026 development | 350 | 8 |

Game 401778314 stays out. No re-selection, no new exclusions, no outcome filters. The scored set is
the full 2,397 / 807 / 350; the prior-season calibration adds no scoring exclusions.

## Walk-forward 2023–25 (n = 2,397): before and after

| metric | H0b (Phase 4) | H0b-MC | change |
|---|---:|---:|---:|
| CRPS total | 9.4611 | **9.1371** | −0.3240 |
| log total | 4.2412 | 4.2208 | −0.0204 |
| MAE total | 13.3508 | 12.9336 | −0.4172 |
| RMSE total | 16.7561 | 16.1162 | −0.6399 |
| bias total (pred − obs) | −0.0410 | **+0.4424** | +0.4834 |
| **PIT total KS p** | **0.0016** | **0.0869** | **+0.0853** |
| **cov50 total** | 0.5340 | **0.5561** | +0.0221 |
| cov80 total | 0.8181 | 0.8306 | +0.0125 |
| cov90 total | 0.9136 | 0.9182 | +0.0046 |
| shortest 50 total | 0.4960 | 0.4977 | +0.0017 |
| Brier total | 0.2329 | 0.2259 | −0.0069 |
| CRPS margin (inherited) | 9.6226 | 9.6226 | 0 |
| PIT margin KS (inherited) | 0.9675 | 0.9675 | 0 |
| cov50/80/90 margin (inherited) | 0.5240 / 0.8002 / 0.9040 | same | 0 |
| Brier spread (inherited) | 0.1748 | 0.1748 | 0 |

The total PIT is fixed, the proper scores improve, and the point error falls. The cost is a small
bias overshoot: the prior-season calibration predicts **+0.44 points** high on average, against
H0b's −0.04. The 50% central interval also widens in coverage from 0.5340 to 0.5561 — just past the
gate's tolerance.

## Holdout (n = 807) and 2026 development (n = 350)

| metric | holdout H0b | holdout H0b-MC | 2026 H0b | 2026 H0b-MC |
|---|---:|---:|---:|---:|
| CRPS total | 9.2690 | **8.9961** | 9.1881 | **8.8551** |
| log total | 4.2155 | 4.2068 | 4.2060 | 4.1679 |
| MAE total | 13.1490 | 12.7915 | 12.9975 | 12.5701 |
| bias total | +0.3443 | +1.0123 | −0.1311 | +0.6311 |
| PIT total KS p | 0.3668 | 0.2646 | 0.1995 | 0.6647 |
| cov50 total | 0.5167 | 0.5551 | 0.5457 | 0.5457 |
| Brier total | 0.2322 | 0.2254 | 0.2361 | 0.2291 |

The holdout total PIT still passes (0.2646) and the holdout CRPS improves. The holdout cov50 is also
0.5551, over the ±0.05 tolerance, but the holdout is gated only on PIT and only the walk-forward is
gated on coverage.

## Paired comparisons vs H1 (2,000 UTC-week-block bootstrap)

| period | metric | H0b | H0b-MC |
|---|---|---:|---:|
| walk-forward | CRPS margin | −2.3257 [−2.6051, −2.0475] | −2.3257 [−2.6051, −2.0475] |
| walk-forward | **CRPS total** | **−1.0672 [−1.3276, −0.8099]** | **−1.3912 [−1.5487, −1.2336]** |
| walk-forward | Brier spread | −0.0414 [−0.0464, −0.0363] | −0.0414 [−0.0464, −0.0363] |
| walk-forward | **Brier total** | **−0.0267 [−0.0337, −0.0197]** | **−0.0337 [−0.0385, −0.0290]** |
| holdout | CRPS margin | −3.1046 [−3.6786, −2.5402] | −3.1046 [−3.6786, −2.5402] |
| holdout | **CRPS total** | **−1.1227 [−1.5879, −0.6662]** | **−1.3955 [−1.6762, −1.0979]** |
| holdout | Brier total | −0.0284 [−0.0411, −0.0157] | −0.0352 [−0.0436, −0.0270] |

Against Constant the walk-forward total CRPS is −1.3996 [−1.5595, −1.2428] and the total Brier is
−0.0343 [−0.0392, −0.0297]. Every interval excludes zero.

## Gates, exactly as registered

| gate | requirement | result |
|---|---|---|
| **G-SAMPLE** | walk-forward n ≥ 1,500 and holdout n ≥ 250 | 2,397 / 807 — **PASS** |
| **G-DIST** | H0b-MC beats H1 on CRPS margin and total, interval below zero on walk-forward; point-negative on holdout | −2.3257 [−2.6051, −2.0475]; −1.3912 [−1.5487, −1.2336]; holdout −3.1046 / −1.3955 — **PASS** |
| **G-CAL** | PIT not rejecting at 5% for margin and total on walk-forward and holdout; central coverage within ±0.05 of nominal at 50/80/90 on walk-forward | margin p = 0.9675, total p = **0.0869**, holdout margin p = 0.6330, total p = 0.2646 — all pass; coverage margin 0.5240 / 0.8002 / 0.9040 pass; **total 0.5561 / 0.8306 / 0.9182 — cov50 = 0.5561 deviates +0.0561 > 0.05 → FAIL** |
| **G-SPREAD** | beats Constant and H1 on Brier, interval below zero, walk-forward; negative on holdout | −0.0670 [−0.0745, −0.0596], −0.0414 [−0.0464, −0.0363]; holdout −0.0604 — **PASS** (inherited; margin unchanged) |
| **G-TOTAL** | same for over/under | −0.0343 [−0.0392, −0.0297], −0.0337 [−0.0385, −0.0290]; holdout −0.0352 — **PASS** |

**Verdict: NOT_ADOPTED.** Four of five gates pass; G-CAL fails on one coverage level by 0.0061.
Nothing was re-specified after seeing the result.

### 7.1 Slope recovery — PASS

OLS of `obs_total` on the corrected `t'`:

| period | slope | 95% CI | contains 1.0 |
|---|---:|---|---|
| walk-forward | 0.9043 | [0.7800, 1.0285] | **yes** |
| holdout | 0.9384 | [0.7169, 1.1599] | yes |

The conditional bias is gone in the statistical sense: the post-correction slope is consistent with
1.0. The point estimate (0.904) is still below 1.0, which is the residual over-extremity the
coverage leg detects.

### 7.2 Per-bucket total PIT — reported, no pre-declared extreme-bucket failure

Bucketed on the **corrected** predicted total `t'`:

| period | bucket | n | mean PIT | KS p |
|---|---|---:|---:|---:|
| walk-forward | <40 | 9 | — | — |
| walk-forward | 40–50 | 597 | 0.5043 | 0.2402 |
| walk-forward | 50–60 | 1,546 | 0.5001 | 0.0686 |
| walk-forward | 60–70 | 242 | 0.5270 | **0.0053** |
| walk-forward | >70 | 3 | — | — |
| holdout | 40–50 | 211 | 0.4805 | 0.1357 |
| holdout | 50–60 | 525 | 0.4939 | 0.2094 |
| holdout | 60–70 | 71 | 0.5114 | 0.2569 |

The pre-declared reading (low bucket > 0.55 or high bucket < 0.45, n ≥ 100, KS p < 0.05) **does not
trigger**: the <40 and >70 buckets are nearly empty after the correction (the calibration
deliberately compresses the extremes), and every bucket with n ≥ 100 has a mean PIT within
[0.45, 0.55].

**But the 60–70 bucket rejects at 5% (p = 0.0053) with a mean PIT of 0.527.** That is a residual
conditional non-uniformity the pre-declared reading was not written to catch. It is reported here as
a finding, not used to re-specify the candidate.

## Falsifier reading (registered F1–F4, no new ones)

- **F1 — transformation failed.** The post-correction slope CI contains 1.0. **Not triggered.**
- **F2 — bias was not the binding constraint.** F2's trigger is "slope CI contains 1.0 but G-CAL
  total still rejects at 5%, pooled or per-bucket". The total PIT **passes** (0.0869) and the
  per-bucket reading does not fail. **F2's PIT trigger is not met.**
- **F3 — the correction hurt.** Paired on `game_id` against the frozen H0b per-game `crps_total`,
  UTC week-block bootstrap (2000 reps, seed 20261017): walk-forward mean **−0.323993**
  [**−0.433123, −0.213093**], 65 blocks, n = 2,397; holdout mean **−0.272873** [**−0.461849,
  −0.079834**], 22 blocks, n = 807. Both intervals lie entirely below zero — the correction improved
  total CRPS. **Not triggered.**
- **F4 — a gate fails.** **Triggered.** G-CAL fails on the walk-forward 50% total coverage
  (0.5561 vs 0.50 ± 0.05).

**The registered reading of this run is F4.** The mean correction fixed the PIT and the proper
scores; it did not clear the coverage leg of G-CAL. The candidate is not adopted.

## Honest limitations

- **The 50% central coverage and the 50% shortest coverage disagree.** The central interval covers
  0.5561; the shortest contiguous interval covers 0.4977, essentially nominal. The gate is defined
  on the central interval, so it fails, but the failure is not a uniform "too wide" error — it is
  concentrated in the skew of the central interval. Recorded as a fact about the gate's behaviour,
  not an argument with the verdict.
- **The correction overshoots the level.** Bias (pred − obs) moves from −0.041 to +0.442 on
  walk-forward and +1.012 on the holdout. The prior-season slope (~0.55) is steeper than the
  evaluation-window relationship (~0.50), so the corrected mean is slightly high.
- **The 60–70 bucket still rejects** (p = 0.0053) even though its mean PIT (0.527) is inside the
  pre-declared band. The conditional mean is largely fixed; the conditional shape at the high end is
  not perfect.
- **The margin side is inherited by construction.** Because only the total PMF is shifted, the
  margin, spread and home/away metrics are numerically identical to H0b's. The joint is no longer
  internally consistent (pre-registered §4.6); a production implementation would need a consistent
  joint, and that is not part of this adoption test.
- **The calibration slope is steeper than the diagnosis's 0.5032.** The diagnosis measured
  2023–2025; the calibration windows add 2015–2022, where the relationship is stronger. The
  evaluation-time slope recovery (0.904) is the relevant check, and it passes.
- **2026 is development data**, reported but never gated.
- **One arm, no multiplicity.** No secondary arm was declared and none was run.

## Checkpoints

| # | checkpoint | status after Phase 4b |
|---|---|---|
| CP1 | baseline established | passed |
| CP2 | candidate validated chronologically | passed for the winner model (G2h) |
| CP3 | distribution calibrated | **not passed** — the total PIT is fixed, but the 50% central coverage fails |
| CP4 | prospective confirmation | not passed |
| CP5 | production integration approved | not passed, and not an agent's to grant |

## Artifacts

- `backend/fbs_phase4b_h0bmc.py` — the harness (reproduction gate, calibration, shift, metrics, gates).
- `research/fbs/phase4b/calibration.csv` — (a_S, b_S), n, CI, r², season windows.
- `research/fbs/phase4b/per_game_shift.csv` — δ, mean error, boundary mass, renormalisation, failures.
- `research/fbs/phase4b/pmf/h0bmc_pmf.npz` — corrected total PMF per observation + the unchanged
  margin PMF, float32.
- `research/fbs/phase4b/pmf/per_observation_scores.csv` — every score input at observation level.
- `research/fbs/phase4b/{summary_by_period,paired,bucket_pit}.csv`.
- `research/fbs/phase4b/MANIFEST.json` — SHA-256 and bytes of every artifact.
- `docs/frozen-fbs-phase4b-h0bmc.json` — the frozen summary (reproduction, calibration, gates,
  slope recovery, per-bucket reading, verdict).
- Margin PMF SHA-256: `726683cb91572f5552429e3707a24118e20fdabfcdcf1dcc22d1b77709750bee`,
  asserted byte-identical to the Phase 4 artifact.

## What I deliberately did not do

- No gate edit, no re-specification, no second arm, no post-hoc window.
- No refit of α, γ or R; no new covariates.
- No Phase 5 play-by-play simulation, no Phase 6 player props.
- No merge to dev, no production or prod-DB write, no touch to the frozen Phase 4 JSON/PMF.
- No re-opening of the Phase 4 `NOT_ADOPTED` verdict.
