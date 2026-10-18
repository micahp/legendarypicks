# RESULTS: NFL rushing participation v2 — individualised P(plays) and a single-inflation count

Run 2026-10-18 on `feat/nfl-rushing-participation-v2` (from `origin/dev` 7dd1b62b), against the
pre-registration in `docs/SPEC-nfl-rushing-participation-v2.md` (committed `27917774` before any v2 fit).

Reproduce:

```bash
cd backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_rushing_participation_v2.py \
    --eval-seasons 2025 2026 --json ../docs/frozen-nfl-rushing-participation-v2.json
```

17 seconds, read-only, no prod writes. All numbers below are from that run's JSON.

## Verdict: NOT_ADOPTED

**0 of 6 coverage comparisons pass.** CRPS, log loss, Brier and AUC all improve substantially — this is the
opposite of v1, where CRPS improved and calibration broke. Here the scores improve *and* the intervals
over-cover: at 50% the model contains 74% of outcomes, at 80% it contains 91%, at 90% it contains 96%.
The incumbent's intervals are the tighter, better-calibrated ones at every level in both seasons. Under the
pre-registered rule that coverage is the primary gate, this candidate does not ship.

## Population (identical to v1, restated)

Weeks 3-18, regular season. Candidates are Spec B's own candidate set (players who logged for the team in
its last three games) with a carry mean `m > 0`, at least one game week into the season. 2025 is the
holdout (parameters from 2024); 2026 is development evidence (parameters from 2024-2025). RB and FB folded
into RB and gated; QB reported and not gated; WR/TE out of scope. Outcome is box-score carries, **0 when
the player has no box-score row that week**.

| season | candidates | RB (gated) | QB (not gated) | appeared |
|---|---:|---:|---:|---:|
| 2025 (fit 2024) | 2,500 | 1,714 | 786 | 0.746 |
| 2026 (fit 2024-25) | 489 | 349 | 140 | 0.738 |

## What the audit fixed before the fit

- **Participation is box-score appearance**, not the availability flag: 276 RB candidate-games over
  2024-26 are recorded active yet have no box-score row, and those are zero-carry games.
- **The designation is a minority**: in 2025 it covers 86 of 361 RB non-appearances (23.8%).
- **Spec B's `P_LOG` discriminates on this event** — AUC 0.751 / 0.790 / 0.770 and Brier 0.144 / 0.123 /
  0.141 against 0.182 / 0.166 / 0.183 for a constant, for 2024 / 2025 / 2026. It is close to calibrated
  cell by cell, so it was used as a prior with `κ = 20` shrinkage toward it, not raw.
- v1's "110 of 534" reconciles: `played_flag != 1` gives exactly 534 in 2025; the designation count on
  those candidates is 130 today rather than 110 on 2026-10-17, because the status and availability tables
  have been written since.

## 2025 holdout — fit on 2024

Fitted: `R0` 3.312, `R` (ZINB, untruncated) 3.772, `R_t` 5.00; `q` 0.632 / 0.927 / 0.993 by tier;
`p` by designation 0.774 (none), 0.533 (Questionable), 0.000 (Out), 0.000 (Doubtful).

### All pregame candidates (n = 2,500)

| model | CRPS | log loss | cov50 | cov80 | cov90 | MAE | sd pred | bias | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 incumbent | 2.0605 | 2.4030 | 0.543 | 0.818 | 0.909 | 2.9401 | 3.41 | +0.038 | 0.2380 | 0.7833 |
| Zd ZINB, designation only | 1.9675 | 2.1937 | 0.804 | 0.939 | 0.968 | 2.8133 | 4.90 | −0.089 | 0.1852 | 0.8262 |
| **Zf ZINB, recent form × designation** | **1.8785** | **2.1077** | 0.738 | 0.910 | 0.960 | 2.9399 | 4.39 | +0.038 | **0.1410** | **0.8854** |
| B2ref v1 hurdle, re-fitted | 2.0438 | 2.1820 | 0.754 | 0.899 | 0.944 | 2.9158 | 3.54 | −1.137 | 0.1793 | 0.7976 |

Paired CRPS against B0, clustered by game (2,500 items, 240 games):

| comparison | diff | 95% CI |
|---|---:|---:|
| Zd − B0 | −0.0930 | ± 0.0391 |
| **Zf − B0** | **−0.1820** | **± 0.0282** |
| B2ref − B0 | −0.0167 | ± 0.0430 |
| **Zf − Zd** (the recent-form contribution) | **−0.0890** | **± 0.0231** |

### RB, gated (n = 1,714)

| model | CRPS | log loss | cov50 | cov80 | cov90 | MAE | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 2.4085 | 2.5800 | 0.535 | 0.796 | 0.893 | 3.3661 | 0.2174 | 0.8199 |
| Zd | 2.3343 | 2.3701 | 0.781 | 0.932 | 0.959 | 3.2253 | 0.1731 | 0.8540 |
| **Zf** | **2.2244** | **2.2891** | 0.712 | 0.897 | 0.951 | 3.3657 | **0.1341** | **0.8951** |
| B2ref | 2.4580 | 2.3691 | 0.722 | 0.879 | 0.928 | 3.4573 | 0.1698 | 0.8283 |

Paired: Zf − B0 **−0.1840 ± 0.0384**; Zd − B0 −0.0742 ± 0.0538; Zf − Zd −0.1098 ± 0.0297;
**B2ref − B0 +0.0495 ± 0.0566** (v1's hurdle form, re-fitted on the appearance event, is *worse* than the
incumbent on RB).

### QB, reported and not gated (n = 786)

| model | CRPS | log loss | cov50 | cov80 | cov90 | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 | 1.3017 | 2.0170 | 0.560 | 0.864 | 0.944 | 0.2829 | 0.6829 |
| Zf | 1.1241 | 1.7122 | 0.794 | 0.936 | 0.981 | 0.1560 | 0.8655 |

Paired Zf − B0: −0.1776 ± 0.0313.

## 2026 development — fit on 2024-2025

Fitted: `R0` 3.705, `R` 4.127, `R_t` 8.00; `q` 0.622 / 0.941 / 0.997; `p` 0.779 / 0.562 / 0.000 / 0.000.

| model | CRPS | log loss | cov50 | cov80 | cov90 | MAE | sd pred | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 incumbent | 2.0889 | 2.4412 | 0.491 | 0.812 | 0.896 | 2.9972 | 3.38 | 0.2498 | 0.7591 |
| Zd | 1.9946 | 2.1846 | 0.777 | 0.959 | 0.967 | 2.9024 | 4.78 | 0.1942 | 0.7897 |
| **Zf** | **1.8668** | **2.1103** | 0.740 | 0.926 | 0.965 | 2.9959 | 4.64 | **0.1461** | **0.8627** |
| B2ref | 2.0621 | 2.1956 | 0.740 | 0.890 | 0.939 | 3.0566 | 3.45 | 0.1914 | 0.7582 |

Paired (489 items, 48 games): Zf − B0 **−0.2221 ± 0.0668**; Zf − Zd −0.1278 ± 0.0444; RD only (n=349)
Zf − B0 −0.2386 ± 0.0856.

## Pre-registered gate

Coverage error against nominal, on the full pregame population:

| season | level | nominal | B0 | Zf | \|B0 err\| | \|Zf err\| | pass |
|---|---:|---:|---:|---:|---:|---:|---|
| 2025 | 50 | 0.50 | 0.543 | 0.738 | 0.043 | 0.238 | **FAIL** |
| 2025 | 80 | 0.80 | 0.818 | 0.910 | 0.018 | 0.110 | **FAIL** |
| 2025 | 90 | 0.90 | 0.909 | 0.960 | 0.009 | 0.060 | **FAIL** |
| 2026 | 50 | 0.50 | 0.491 | 0.740 | 0.009 | 0.240 | **FAIL** |
| 2026 | 80 | 0.80 | 0.812 | 0.926 | 0.012 | 0.126 | **FAIL** |
| 2026 | 90 | 0.90 | 0.896 | 0.965 | 0.004 | 0.065 | **FAIL** |

MAE gate: 2025 `2.9399` vs B0 `2.9401` (pass), 2026 `2.9959` vs `2.9972` (pass).

**Verdict: NOT_ADOPTED** — the coverage gate requires all six comparisons and none pass. Fail-closed, no
re-specification.

## What this means

The participation question is answered, and the answer is yes: individualised `P(plays)` is a large,
robust improvement in *discrimination*. Brier on `P(carries ≥ 1)` falls from 0.2380 to 0.1410 (2025) and
0.2498 to 0.1461 (2026); AUC rises from 0.783 to 0.885 and 0.759 to 0.863. The recent form contributes
most of it: `Zf − Zd` is −0.0890 ± 0.0231 on CRPS, so the designation-only model gets less than half the
available gain. The 424 non-participants the designation misses are largely predictable from whether the
player logged in the team's last three games and in the most recent one.

What fails is the **shape of the count**, not the probability of playing. Zf's intervals are too wide:
at 50% it holds 74% of outcomes. The observed spread is large (sd 6.24 across all candidates, 6.99 on RB)
while the model's predictive sd averages 4.39 — so the model is *under*-dispersed in variance terms and
still over-covers, which means its mass is in the wrong places: too much at zero and too much in the upper
tail at the same time, leaving the central quantiles too far apart. A single dispersion parameter fitted to
all usage levels cannot fix that. B0 achieves near-nominal coverage with a narrower, mis-shaped
distribution: the quantiles happen to land close even though CRPS and log loss are far worse.

That is precisely the trade the pre-registered gate was written to referee, and it refereed against the new
model. Reporting it the other way round — adopting on the strength of a 9% CRPS gain while the 50% interval
is 24 points over — would repeat v1's mistake with a nicer score.

## Next facet

Participation is now good enough that the binding constraint is dispersion. The next experiment should be
**quantile calibration of the count**, not another participation model:

1. Fit the count with a per-usage-tier dispersion (`R` by the same three tiers as `q`, or `R` as a smooth
   function of `m`), because a single `R` cannot serve both a 2-carry back and a 20-carry back.
2. Consider a discrete quantile map fitted on training seasons — take the ZINB's distribution, then remap
   its quantiles to the empirical ones by tier — and gate on coverage only, with CRPS reported.
3. Keep the participation model from this branch as the zero layer; it is not the problem.

## Provenance

- `backend/audit_nfl_participation_v2.py` — participation audit (read-only).
- `backend/nfl_rushing_participation_v2.py` — harness; `--frozen` reuses the stored parameters.
- `docs/frozen-nfl-rushing-participation-v2.json` — fitted parameters for both seasons, all tables, all
  paired comparisons and the gate verdict.
- v1 remains NOT_ADOPTED and frozen; its prospective window (2026 weeks 7-18) was not touched here beyond
  the ordinary 2026 development evaluation.
