# SPEC: NFL rushing participation v3 — tiered dispersion on v2's zero layer

Status: PRE-REGISTERED 2026-10-18, before any v3 parameter fit or any v3 evaluation number was computed.
Branch `feat/nfl-rushing-participation-v3`, based on `feat/nfl-rushing-participation-v2` (a9a46bd0).
Extends v2, which is NOT_ADOPTED with coverage 0/6.

## The question

v2 fixed participation and left one defect: **the count shape**. Its single-inflation ZINB improved every
proper score (CRPS 2.0605 → 1.8785 in 2025, 2.0889 → 1.8668 in 2026) and then failed the pre-registered
coverage gate, holding 0.738 / 0.910 / 0.960 of outcomes in its 50/80/90 intervals against 0.50 / 0.80 /
0.90 nominal. The diagnosis recorded in `docs/RESULTS-nfl-rushing-participation-v2.md` is that one
dispersion parameter cannot serve a 2-carry back and a 20-carry back.

v3 asks exactly that: **with the participation layer held fixed, does fitting one dispersion per usage
tier restore calibration?**

## What the audit shows (training seasons only, no v3 fit)

Moment dispersion computed from v2's own estimator (`μ = m/(1-π)`, candidates who appeared), split by the
three usage tiers that already define `q`:

| fit window | pooled R | m<3 | 3≤m<8 | m≥8 | spread |
|---|---:|---:|---:|---:|---:|
| 2024 | 3.772 | **1.558** | **2.711** | **5.134** | 3.30× |
| 2024–2025 | 4.127 | **1.350** | **2.659** | **6.232** | 4.62× |

The single R v2 used sits in the middle and is wrong at both ends: too dispersed for low-usage backs
(their own moment fit is 1.4–1.6, not 3.8) and too tight for lead backs (5.1–6.2). That is a direct,
measured mechanism for the observed over-coverage at 50%: the low-usage half of the population — where
intervals should be tight — is being given a distribution with roughly 2.4× the dispersion its own data
supports.

The audit also records a known limitation that v3 does **not** fix: within the `m<3` tier the conditional
mean `m/p` runs 2.81 against an observed 2.00 carries, so the ZINB's location is high for low-usage backs.
That is a property of the participation layer, which the brief freezes. It is reported, not corrected.

## The candidate (one, pre-registered)

**V3 = v2's single-inflation ZINB with `R` replaced by `R_tier`.** Nothing else changes:

```
eta-free form:   P(0) = π + (1-π)·NB(0; μ, R_tier)
                 P(k) = (1-π)·NB(k; μ, R_tier)        k >= 1
                 μ = m/(1-π),  π = 1 - p               (mean preserved exactly, as in v2)
```

| element | v3 | source |
|---|---|---|
| `p` (participation) | **identical to v2**: cross of `(k, last, status)` shrunk toward `P_LOG`, κ = 20 | v2, unchanged |
| count component | untruncated NegBin | v2, unchanged |
| `μ` | `m/(1-π)` | v2, unchanged |
| **`R`** | **three values, one per usage tier** (`m<3`, `3≤m<8`, `m≥8`) | **the only change** |
| tier fit | moment equation `R_tier = Σμ² / Σ((k-μ)² - μ)` over appeared training items **in that tier**, floored at 0.5 | same estimator as v2, applied per tier |
| guard | a tier with fewer than 30 appeared training items, or a non-positive denominator, uses the pooled `R` | declared here |

The tier boundaries are the ones already used for `q` and for v2's own reporting. They are not re-tuned.

## Reference models (reported, not candidates)

- **B0** — the incumbent: `NB(m, R0)`, no zero inflation, single dispersion. Unchanged, so the gate
  compares like with like.
- **B2ref** — v1's hurdle form, re-fitted on the appearance event as in v2, for continuity.

## Population (identical to v1 and v2, restated)

Weeks 3–18, regular season; Spec B candidates who logged in the team's last three games with a carry mean
`m > 0`; RB and FB folded into RB and **gated**, QB **reported and not gated**, WR/TE out. Outcome is
box-score carries, **0 when the player has no box-score row that week**. 2025 is the holdout (fit 2024);
2026 is development evidence (fit 2024–2025). Sizes: 2,500 (RB 1,714) and 489 (RB 349).

## Gate (unchanged from v2 — not relaxed, not re-weighted)

1. **Coverage, primary:** for every level ℓ ∈ {50%, 80%, 90%} and every season s ∈ {2025, 2026},
   `|cov_V3(ℓ,s) - ℓ| < |cov_B0(ℓ,s) - ℓ|`. All six comparisons must pass.
2. **MAE, secondary:** `MAE_V3 ≤ MAE_B0 + 0.02` on both seasons.
3. **Reported, not gating:** CRPS, log loss, Brier and AUC for `P(carries ≥ 1)`, with paired
   game-clustered 95% intervals against B0.

Fail-closed. If coverage fails, the verdict is NOT_ADOPTED and the result is recorded as-is.

## Pre-declared interpretation of each outcome

- **V3 passes all six:** dispersion was the binding constraint; the model is a keeper and the participation
  layer ships with it.
- **V3 improves coverage but still fails:** report which levels moved and by how much. If the 50% interval
  is still wide while 80/90 are near nominal, the residual defect is the zero mass rather than the
  dispersion, and the next candidate is the discrete quantile map (option b of the v3 brief) — named here
  in advance so the follow-up is not a post-hoc story.
- **V3 is worse than v2 on coverage:** tiering is refuted as the mechanism, and the same quantile-map
  conclusion follows with more force.

## No look-ahead

Every parameter is fitted on seasons strictly before the evaluation season, on the same weeks and the same
candidate population. `p` uses only prior games' appearances. `R_tier` uses only training items. Nothing
about the evaluated game enters its own prediction, and `m` remains Spec B's frozen pregame mean.

## Deliverables

- `backend/audit_nfl_dispersion_v3.py` — the audit above (already run, read-only).
- `backend/nfl_rushing_participation_v3.py` — harness; reuses v2's distributions, participation fit,
  scoring and clustering, and replaces only the dispersion.
- `docs/RESULTS-nfl-rushing-participation-v3.md` — results, verdict, next step.
- `docs/frozen-nfl-rushing-participation-v3.json` — fitted parameters, all tables, all paired
  comparisons, gate verdict.
