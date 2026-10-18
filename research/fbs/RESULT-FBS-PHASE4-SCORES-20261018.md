# RESULTS: FBS Phase 4 — final-score distributions

Run 2026-10-18 on `feat/fbs-archive`, against the pre-registration in
`research/fbs/RESULT-FBS-PHASE3-B-20261018.md` §21 (committed `3db4b32d` before any Phase 4 model code).

Reproduce:

```bash
cd /root/lp-fbs-archive
/root/legendarypicks/backend/venv/bin/python backend/fbs_phase4_scores.py
```

Runtime 2m21s, read-only against the archive. Every number below is from
`research/fbs/phase4/{summary_by_period,paired,block_parameters}.csv` and the per-observation PMFs.

## Verdict: NOT_ADOPTED — 4 of 5 gates pass, G-CAL fails

H0b (independent NegBin2 on decayed points ratings) beats the winner-only control H1 on **CRPS for margin
and total**, beats **Constant** and **H1** on **spread and total Brier**, and its interval coverage is
near-nominal at all three levels. It fails **G-CAL** on one test: the randomized PIT for the **total**
rejects uniformity on the walk-forward pool (KS p = 0.0016). Fail-closed, so it is not adopted.

That is the carries lesson arriving in a new place: a model that wins the proper scores and loses a
calibration test is not adopted.

## Population (identical to Phase 3)

| period | games | blocks | how fitted |
|---|---:|---:|---|
| walk-forward 2023–25 | 2,397 | 65 | refitted at every UTC date block on strictly earlier games |
| 2025 frozen holdout | 807 | 22 | all parameters fitted once on games before 2025-01-01 |
| 2026 development | 350 | 8 | refitted per block, reported separately, not part of the gates |

Game 401778314 stays out, as pre-registered. The holdout ledger holds 808 games; 807 are scored because
that game is excluded by the registered rule. 28,685 games with final scores (2015–2026) feed the ratings
and the block fits.

**Two declared limitations.** (1) H1 uses G2h's win probability on the walk-forward games but the **frozen
G2** probability on the holdout, because G2h has no frozen form — it is refitted per block. The holdout H1
is therefore a slightly weaker control. (2) Ratings are as-of within the holdout (they use only prior
games) while every fitted parameter is frozen at end-2024; that is the same treatment Phase 3 gave its
as-of features.

## Candidates as implemented

- **H0a** independent Poisson, `μ_h = exp(α + off_h + def_a + γ/2)`, `μ_a = exp(α + off_a + def_h − γ/2)`,
  α and γ by Poisson MLE per block.
- **H0b** same means, NegBin2 with `var = μ + μ²/R`, R by moments per block (fitted R ranges 2.01–5.82).
- **H0c** bivariate Poisson with a shared component λ3 = max(0, Cov(h,a)) per block.
- **H1** league-average Poisson pair tilted by `exp(θ)` on the home-win half to match the win probability,
  θ in closed form because the tilt is a step function on the sign of the margin.
- **Constant** the same league-average pair, untilted. **PriorMean** prior-season team means, independent
  Poisson, no opponent adjustment.

Fitted across 1,025 date blocks: α 3.296–3.411, γ 0.183–0.600, R 2.01–5.82.

**H0c is identical to H0a in every metric because λ3 = 0 in all 1,025 fits.** After team strength, home and
away scores are not positively correlated in this data; the shared component never activates. H0c is
reported as a refuted variant, not a fifth model.

## Walk-forward 2023–25 (n = 2,397)

| model | CRPS margin | CRPS total | log margin | log total | MAE margin | bias margin | bias total | cov50/80/90 margin | cov50/80/90 total | PIT KS margin | PIT KS total | Brier spread | Brier total |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|
| Constant | 12.8474 | 10.5367 | 6.531 | 5.579 | 15.851 | +0.58 | +1.14 | 0.235 / 0.401 / 0.501 | 0.251 / 0.436 / 0.535 | 0.000 | 0.000 | 0.2417 | 0.2602 |
| PriorMean | 12.3466 | 12.1803 | 6.301 | 6.231 | 15.426 | −4.13 | +2.94 | 0.218 / 0.393 / 0.488 | 0.218 / 0.382 / 0.477 | 0.000 | 0.000 | 0.2305 | 0.3233 |
| H1 control | 11.9483 | 10.5283 | 6.375 | 5.577 | 14.773 | −1.41 | +1.04 | 0.247 / 0.422 / 0.509 | 0.250 / 0.436 / 0.537 | 0.000 | 0.000 | 0.2162 | 0.2596 |
| H0a | 10.6369 | 10.4694 | 5.643 | 5.567 | 13.551 | +0.19 | +0.00 | 0.245 / 0.436 / 0.549 | 0.254 / 0.443 / 0.541 | 0.000 | 0.000 | 0.1962 | 0.2725 |
| **H0b** | **9.6226** | **9.4611** | **4.274** | **4.241** | **13.544** | **+0.16** | **−0.04** | **0.524 / 0.800 / 0.904** | **0.534 / 0.818 / 0.914** | **0.968** | **0.0016** | **0.1748** | **0.2329** |
| H0c | 10.6369 | 10.4694 | 5.643 | 5.567 | 13.551 | +0.19 | +0.00 | 0.245 / 0.436 / 0.549 | 0.254 / 0.443 / 0.541 | 0.000 | 0.000 | 0.1962 | 0.2725 |

Point error by side (H0b): home MAE 9.952, away MAE 9.071, margin MAE 13.544, total MAE 13.351; home bias
+0.060, away bias −0.101, margin bias +0.160, total bias −0.041. RMSE margin 17.030, total 16.756.

### Paired differences, 95% UTC-week-block bootstrap (65 blocks)

| comparison | metric | diff | 95% interval |
|---|---|---:|---|
| **H0b − H1** | CRPS margin | **−2.3257** | **[−2.6051, −2.0475]** |
| **H0b − H1** | CRPS total | **−1.0672** | **[−1.3276, −0.8099]** |
| **H0b − H1** | Brier spread | **−0.0414** | **[−0.0464, −0.0363]** |
| **H0b − H1** | Brier total | **−0.0267** | **[−0.0337, −0.0197]** |
| H0b − Constant | CRPS margin | −3.2249 | [−3.5756, −2.8895] |
| H0b − Constant | CRPS total | −1.0756 | [−1.3343, −0.8157] |
| H0b − Constant | Brier spread | −0.0670 | [−0.0745, −0.0596] |
| H0b − Constant | Brier total | −0.0273 | [−0.0344, −0.0203] |
| H0a − H1 | CRPS margin | −1.3113 | [−1.5988, −1.0106] |
| H0a − H1 | CRPS total | −0.0589 | [−0.3572, +0.2295] |

## 2025 frozen holdout (n = 807, all parameters from before 2025-01-01)

| model | CRPS margin | CRPS total | MAE margin | cov50/80/90 margin | cov50/80/90 total | PIT KS margin | PIT KS total | Brier spread | Brier total |
|---|---:|---:|---:|---|---|---:|---:|---:|---:|
| Constant | 12.9184 | 10.4052 | 15.938 | 0.226 / 0.388 / 0.508 | 0.258 / 0.441 / 0.549 | 0.000 | 0.000 | 0.2407 | 0.2614 |
| PriorMean | 12.3532 | 11.7702 | 15.406 | 0.233 / 0.399 / 0.504 | 0.203 / 0.392 / 0.482 | 0.000 | 0.000 | 0.2273 | 0.3197 |
| H1 | 12.5615 | 10.3916 | 15.603 | 0.253 / 0.418 / 0.503 | 0.258 / 0.441 / 0.549 | 0.000 | 0.000 | 0.2306 | 0.2606 |
| H0a | 10.3815 | 10.2825 | 13.262 | 0.247 / 0.449 / 0.561 | 0.262 / 0.434 / 0.528 | 0.000 | 0.000 | 0.1884 | 0.2730 |
| **H0b** | **9.4568** | **9.2689** | **13.263** | **0.535 / 0.797 / 0.902** | **0.517 / 0.819 / 0.916** | **0.633** | **0.367** | **0.1702** | **0.2322** |

Paired on the holdout (22 blocks): H0b − H1 CRPS margin **−3.1046 [−3.6786, −2.5402]**, total
**−1.1227 [−1.5879, −0.6662]**, Brier spread −0.0604 [−0.0725, −0.0501], Brier total −0.0284
[−0.0411, −0.0157]. Every interval excludes zero.

## 2026 development (n = 350, 8 blocks — not a gate)

H0b: CRPS margin 10.4510, total 9.1881; MAE margin 14.441; PIT margin p = 0.0563, total p = 0.1995;
coverage 0.506 / 0.757 / 0.857 (margin) and 0.546 / 0.837 / 0.906 (total); Brier spread 0.1791, total
0.2361. Paired vs H1: margin −2.2711 [−2.7659, −1.7227], total −0.8175 [−1.5535, −0.1659].

## Gates, as pre-registered

| gate | requirement | result |
|---|---|---|
| **G-SAMPLE** | walk-forward ≥ 1,500, holdout ≥ 250 | 2,397 / 807 — **PASS** |
| **G-DIST** | H0b beats H1 on CRPS margin **and** total, interval below zero, walk-forward; point-negative on holdout | −2.3257 [−2.6051, −2.0475] and −1.0672 [−1.3276, −0.8099]; holdout −3.1046 / −1.1227 — **PASS** |
| **G-CAL** | randomized PIT not rejecting U(0,1) at 5% for margin and total, walk-forward **and** holdout; central coverage within ±0.05 at 50/80/90 | PIT total walk-forward **p = 0.0016** — **FAIL**; all other PIT tests pass (0.968, 0.633, 0.367) and all coverage levels are within 0.05 |
| **G-SPREAD** | beats Constant **and** H1 on Brier, interval below zero, walk-forward; negative on holdout | −0.0670 [−0.0745, −0.0596] vs Constant, −0.0414 [−0.0464, −0.0363] vs H1; holdout −0.0706 / −0.0604 — **PASS** |
| **G-TOTAL** | same for over/under | −0.0273 [−0.0344, −0.0203] vs Constant, −0.0267 [−0.0337, −0.0197] vs H1; holdout −0.0293 / −0.0284 — **PASS** |

**Verdict: NOT_ADOPTED.** Four of five gates pass; G-CAL fails on one of its four PIT tests and the
pre-registered rule is fail-closed. Nothing was re-specified after seeing the result.

## What the numbers say

**The score model learned something the winner model does not have.** H1 is the control that matters, and
H0b beats it by 2.33 CRPS on margin and 1.07 on total, with intervals nowhere near zero, on both the
walk-forward pool and the frozen holdout. The market-shaped outputs agree: Brier on cover probability falls
from 0.2162 to 0.1748 and on over/under from 0.2596 to 0.2329, against both Constant and H1. The team
ratings carry genuine information about the score, not just about who wins.

**The independent-Poisson family is structurally too narrow.** H0a and H0c cover 0.245 of their 50%
intervals — half of nominal — because a Poisson margin has a standard deviation near 7 points while
observed margins spread over 14. Their PIT rejects at any resolution (p ≈ 0). Only over-dispersion (H0b)
brings coverage to nominal.

**The remaining defect is the shape of the total.** H0b's margin PIT is clean (p = 0.968 walk-forward,
0.633 holdout) and its interval coverage is within 0.05 everywhere. The total PIT rejects on the
walk-forward pool (p = 0.0016) while passing on the holdout (p = 0.367) — the same test on 2,397 games has
the power to see a small miss that 807 games cannot. Coverage does not detect it because coverage is coarse;
the PIT does, which is exactly why G-CAL was written to require it.

**Prior-season means are worse than no information on totals** (CRPS 12.18 vs Constant's 10.54, bias
+2.94): scoring rises and falls by season, and a raw prior-season average carries that level forward.

## Checkpoints

| # | checkpoint | status after Phase 4 |
|---|---|---|
| CP1 | baseline established | **passed** — Constant, PriorMean, H1 and G2h all scored on the same games |
| CP2 | candidate validated chronologically | **passed for the winner model** (G2h, §20); the score models are walk-forward and paired but not adopted |
| CP3 | distribution calibrated | **not passed** — proper scores and PMFs are now preserved observation-by-observation, and the margin distribution is calibrated, but the total distribution fails PIT |
| CP4 | prospective confirmation | not passed |
| CP5 | production integration approved | not passed, and not an agent's to grant |

Phase 3 was credited with CP1 and CP2 and marked not-passed on CP3; Phase 4 does not change that. It
narrows the CP3 gap to one sub-market.

## What I deliberately did not do

- No Phase 5 play-by-play simulation, and no claim that these distributions are good enough to build one.
- No player props (Phase 6).
- No gate changes after seeing the result, no re-fitting to chase the total PIT, no dropping the 2026
  development season from the report.
- No adoption: H0b is a research result on a branch, not a shipped forecast.

## Artifacts

- `backend/fbs_phase4_scores.py` — ratings, six models, PMFs, metrics, gates.
- `research/fbs/phase4/pmf/margin_total_pmf.npz` — per-observation margin and total PMFs for all six
  models on all 3,554 forecast rows (float32, support declared in the manifest).
- `research/fbs/phase4/pmf/per_observation_scores.csv` — every score input at observation level: CRPS, log
  score, randomized PIT, interval hits, spread and total probabilities, outcomes.
- `research/fbs/phase4/{per_game_parameters,block_parameters,summary_by_period,paired}.csv` and
  `MANIFEST.json` (SHA-256 of every artifact, population counts, gate verdict).
- `docs/frozen-fbs-phase4-scores.json` — the frozen summary of this run.
- `docs/MODEL-CHECKPOINTS.md` — the five-checkpoint standard, copied from the manager brief.
