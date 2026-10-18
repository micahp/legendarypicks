# RESULTS: NFL rushing participation v3 — tiered dispersion on v2's zero layer

Run 2026-10-18 on `feat/nfl-rushing-participation-v3` (from `feat/nfl-rushing-participation-v2` a9a46bd0),
against the pre-registration in `docs/SPEC-nfl-rushing-participation-v3.md` (committed `d00588b5` before any
v3 fit).

Reproduce:

```bash
cd backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_rushing_participation_v3.py \
    --eval-seasons 2025 2026 --json ../docs/frozen-nfl-rushing-participation-v3.json
```

18 seconds, read-only, no prod or dev-DB writes beyond reads. Every number below is from that run's JSON.

## Verdict: NOT_ADOPTED

**0 of 6 coverage comparisons pass**, and the calibration is *slightly worse* than v2's: at 50% the model
holds 0.750 (2025) and 0.748 (2026) of outcomes against 0.50 nominal, where v2 held 0.738 and 0.740.
Tiering the dispersion improved every proper score — CRPS 1.8785 → 1.8524 and 1.8668 → 1.8368 against v2,
log loss 2.1077 → 2.0726 and 2.1103 → 2.0851 — and moved coverage the wrong way.

That is the third outcome the SPEC pre-declared: *"V3 is worse than v2 on coverage: tiering is refuted as
the mechanism, and the same quantile-map conclusion follows with more force."* It follows with more force.

## Population (identical to v1 and v2, restated)

Weeks 3–18, regular season. Candidates are Spec B's own set (logged for the team in its last three games)
with carry mean `m > 0`. 2025 is the holdout (fit 2024); 2026 is development evidence (fit 2024–2025).
RB and FB folded into RB and **gated**; QB **reported, not gated**; WR/TE out. Outcome is box-score
carries, **0 when the player has no box-score row that week**.

| season | candidates | RB (gated) | QB (not gated) | appeared |
|---|---:|---:|---:|---:|
| 2025 (fit 2024) | 2,500 | 1,714 | 786 | 0.746 |
| 2026 (fit 2024–25) | 489 | 349 | 140 | 0.738 |

Participation is v2's model, unchanged: `p` from the `(k, last, status)` cross shrunk toward Spec B's
`P_LOG` with κ = 20, `μ = m/(1−π)` so the mean is preserved exactly. The only change is the dispersion.

## Fitted dispersion

| fit window | `R0` (B0) | pooled `R` (v2) | m<3 | 3≤m<8 | m≥8 | `R_t` (B2ref) |
|---|---:|---:|---:|---:|---:|---:|
| 2024 | 3.312 | 3.772 | **1.558** | **2.711** | **5.134** | 5.00 |
| 2024–2025 | 3.705 | 4.127 | **1.350** | **2.659** | **6.232** | 8.00 |

The audit's 3.3×–4.6× spread across tiers reproduces exactly on the fitted values.

## 2025 holdout

### All pregame candidates (n = 2,500)

| model | CRPS | log loss | cov50 | cov80 | cov90 | MAE | sd pred | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 incumbent | 2.0605 | 2.4030 | 0.543 | 0.818 | 0.909 | 2.9401 | 3.41 | 0.2380 | 0.7833 |
| Zf v2 candidate | 1.8785 | 2.1077 | 0.738 | 0.910 | 0.960 | 2.9399 | 4.39 | 0.1410 | 0.8854 |
| **V3 tiered R** | **1.8524** | **2.0726** | 0.750 | 0.919 | 0.965 | 2.9400 | 4.52 | **0.1375** | **0.8864** |
| B2ref v1 hurdle | 2.0438 | 2.1820 | 0.754 | 0.899 | 0.944 | 2.9158 | 3.54 | 0.1793 | 0.7976 |

Paired CRPS against B0, game-clustered (2,500 items, 240 games):

| comparison | diff | 95% CI |
|---|---:|---:|
| Zf − B0 | −0.1820 | ± 0.0282 |
| **V3 − B0** | **−0.2080** | **± 0.0281** |
| **V3 − Zf** (the tiering contribution) | **−0.0261** | **± 0.0041** |

### RB, gated (n = 1,714)

| model | CRPS | log loss | cov50 | cov80 | cov90 | MAE | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 2.4085 | 2.5800 | 0.535 | 0.796 | 0.893 | 3.3661 | 0.2174 | 0.8199 |
| Zf | 2.2244 | 2.2891 | 0.712 | 0.897 | 0.951 | 3.3657 | 0.1341 | 0.8951 |
| **V3** | **2.1889** | **2.2357** | 0.726 | 0.905 | 0.954 | 3.3659 | **0.1294** | **0.8975** |

Paired: V3 − B0 **−0.2195 ± 0.0377**; V3 − Zf −0.0355 ± 0.0055.

### QB, reported and not gated (n = 786)

| model | CRPS | log loss | cov50 | cov80 | cov90 | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 | 1.3017 | 2.0170 | 0.560 | 0.864 | 0.944 | 0.2829 | 0.6829 |
| Zf | 1.1241 | 1.7122 | 0.794 | 0.936 | 0.981 | 0.1560 | 0.8655 |
| **V3** | **1.1186** | 1.7170 | 0.802 | 0.949 | 0.989 | **0.1550** | 0.8644 |

Paired V3 − B0 −0.1831 ± 0.0328; V3 − Zf −0.0055 ± 0.0055.

## 2026 development (fit 2024–2025)

| model | CRPS | log loss | cov50 | cov80 | cov90 | MAE | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 incumbent | 2.0889 | 2.4412 | 0.491 | 0.812 | 0.896 | 2.9972 | 0.2498 | 0.7591 |
| Zf v2 candidate | 1.8668 | 2.1103 | 0.740 | 0.926 | 0.965 | 2.9959 | 0.1461 | 0.8627 |
| **V3 tiered R** | **1.8368** | **2.0851** | 0.748 | 0.930 | 0.973 | 2.9967 | **0.1432** | **0.8708** |

Paired (489 items, 48 games): Zf − B0 −0.2221 ± 0.0668; **V3 − B0 −0.2521 ± 0.0684**;
V3 − Zf −0.0300 ± 0.0133. RB only (n = 349): V3 − B0 −0.2837 ± 0.0874; V3 − Zf −0.0452 ± 0.0164.

## Pre-registered gate

| season | level | nominal | B0 | V3 | \|B0 err\| | \|V3 err\| | pass |
|---|---:|---:|---:|---:|---:|---:|---|
| 2025 | 50 | 0.50 | 0.543 | 0.750 | 0.043 | 0.250 | **FAIL** |
| 2025 | 80 | 0.80 | 0.818 | 0.919 | 0.018 | 0.119 | **FAIL** |
| 2025 | 90 | 0.90 | 0.909 | 0.965 | 0.009 | 0.065 | **FAIL** |
| 2026 | 50 | 0.50 | 0.491 | 0.748 | 0.009 | 0.248 | **FAIL** |
| 2026 | 80 | 0.80 | 0.812 | 0.930 | 0.012 | 0.130 | **FAIL** |
| 2026 | 90 | 0.90 | 0.896 | 0.973 | 0.004 | 0.073 | **FAIL** |

MAE gate: 2.9400 vs 2.9401 (2025), 2.9967 vs 2.9972 (2026) — pass. **Verdict NOT_ADOPTED.**

## Why tiering did not fix calibration

`backend/audit_nfl_interval_width_v3.py`, 2025, empirical quantiles of carries against the bounds the
model publishes:

| tier | n | observed q25/q50/q75/q90/q95 | 50% width B0 → V3 | 50% coverage B0 → V3 |
|---|---:|---|---:|---:|
| m<3 | 1,140 | 0 / 0 / 2 / 4 / 6 | 1.91 → 2.12 | 0.612 → **0.829** |
| 3≤m<8 | 837 | 0 / 4 / 7 / 11 / 14 | 4.39 → 5.75 | 0.436 → **0.703** |
| m≥8 | 523 | 9 / 13 / 18 / 21 / 23 | 9.54 → 10.61 | 0.562 → **0.652** |
| all | 2,500 | 0 / 2 / 8 / 14 / 18 | 4.34 → 5.12 | 0.543 → 0.750 |

Two things are true at once, and they point in opposite directions:

1. **Within every usage tier, V3 is better calibrated than B0** at 50% — by 22, 27 and 9 points. The model
   is now closer to nominal *for each kind of back* than the incumbent is.
2. **In aggregate V3 is much worse**, because B0's tier-level errors cancel: it under-covers the middle
   tier by 6 points and over-covers the two outer tiers, landing at 0.543 overall. V3 over-covers every
   tier, so nothing cancels and the aggregate is 0.750.

The gate is written on the aggregate. It is not changed here — the brief is explicit that the gate and the
promotion rule are not to be touched — so the verdict is NOT_ADOPTED and the aggregate number is the one
that counts. The tier-level table is recorded because it changes what the next candidate should be, not
because it argues with this verdict.

The mechanical reason tiering did not help: fitting the dispersion faithfully *widened* the tiers that
dominate the interval. `R` for m≥8 went from a pooled 3.77 to 5.13 (2025) and 6.23 (2026), so the upper
interval bound for lead backs moved up, while the zero mass stayed where v2 put it. The model now
reproduces the variance of each tier and still cannot place its central quantiles: the mixture holds a
large spike at zero (~45% of candidates do not appear, plus zero-carry appearances) and a long right tail,
so a 50% central interval has to span almost the whole range. That is a shape problem, not a scale problem,
and no choice of `R` fixes it.

## What this means for the workstream

Three candidates have now been tested against the same gate and all three fail it:

| candidate | CRPS 2025 | coverage 2025 (50/80/90) | verdict |
|---|---:|---|---|
| B0 incumbent | 2.0605 | 0.543 / 0.818 / 0.909 | reference |
| B2 (v1 hurdle) | 1.9093 * | 0.713 / 0.914 / 0.955 | NOT_ADOPTED |
| Zf (v2) | 1.8785 | 0.738 / 0.910 / 0.960 | NOT_ADOPTED |
| V3 (tiered) | 1.8524 | 0.750 / 0.919 / 0.965 | NOT_ADOPTED |

\* v1's own harness and fit; not re-graded here.

Each step improves CRPS and each step slightly worsens coverage. The pattern is consistent: proper scores
reward the participation layer, and the coverage gate keeps rejecting the count shape.

**Next candidate, as pre-declared: the discrete quantile map (option b).** Fit it on training seasons by
tier — take the ZINB's probabilities, remap the quantile levels to the empirical quantiles of the tier —
and gate on coverage. That attacks the shape directly instead of hoping a parametric family bends into it.
A pre-registration for it should also state *which* coverage statistic it is optimising, because this run
shows the aggregate and the per-tier numbers can disagree in sign.

## Provenance

- `backend/audit_nfl_dispersion_v3.py` — tier-wise dispersion audit (read-only).
- `backend/audit_nfl_interval_width_v3.py` — interval-width and tier-coverage diagnostic (read-only).
- `backend/nfl_rushing_participation_v3.py` — harness; imports v2's distributions, participation fit,
  scoring and clustering, and replaces only the dispersion.
- `docs/frozen-nfl-rushing-participation-v3.json` — fitted parameters, all tables, all paired comparisons,
  the six gate checks and the verdict.
- v1 stays NOT_ADOPTED and frozen; its prospective window (2026 weeks 7–18) was not touched beyond the
  ordinary 2026 development evaluation. No prod writes; the dev DB was opened read-only.
