# SPEC: NFL rushing participation v4 — discrete quantile map by usage tier

Status: PRE-REGISTERED 2026-10-18, before any v4 model code and before any v4 evaluation number.
Branch `feat/nfl-rushing-participation-v4`, based on `feat/nfl-rushing-participation-v3` (d7aaeb77).

## Where this comes from

v1 (hurdle), v2 (single-inflation ZINB) and v3 (tiered dispersion) are all NOT_ADOPTED, all on the same
coverage gate, all with the same zero layer. Each improved CRPS and none fixed calibration:

| candidate | CRPS 2025 | coverage 2025 (50/80/90) | verdict |
|---|---:|---|---|
| B0 incumbent | 2.0605 | 0.543 / 0.818 / 0.909 | reference |
| v1 hurdle | 1.9093 | 0.713 / 0.914 / 0.955 | NOT_ADOPTED |
| v2 ZINB | 1.8785 | 0.738 / 0.910 / 0.960 | NOT_ADOPTED |
| v3 tiered R | 1.8524 | 0.750 / 0.919 / 0.965 | NOT_ADOPTED |

v3's diagnostic settled the diagnosis: the models are under-dispersed in variance (`sd_pred` below
`sd_obs`) and over-cover anyway, and v3 is better calibrated than B0 *inside every tier* while losing the
aggregate. A parametric count family with one spike at zero cannot place its central quantiles where the
carry distribution actually has them. v4 stops assuming a family and fits the quantiles directly.

## Audit: are tier quantiles stable enough to map forward?

`backend/audit_nfl_quantile_stability_v4.py`, quantiles of carries among candidates who **appeared**:

| season | tier | n | q05 | q10 | q25 | q50 | q75 | q90 | q95 | mean | zero share |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2024 | m<3 | 627 | 0 | 0 | 0 | 1 | 3 | 5 | 6 | 2.00 | 0.368 |
| 2024 | 3≤m<8 | 767 | 0 | 1 | 2 | 5 | 8 | 12 | 14 | 5.56 | 0.073 |
| 2024 | m≥8 | 453 | 4 | 6 | 10 | 14 | 19 | 23 | 25 | 14.23 | 0.007 |
| 2025 | m<3 | 732 | 0 | 0 | 0 | 1 | 3 | 5 | 7 | 1.90 | 0.387 |
| 2025 | 3≤m<8 | 653 | 1 | 1 | 3 | 5 | 8 | 12 | 14 | 6.02 | 0.043 |
| 2025 | m≥8 | 479 | 5 | 7 | 10 | 14 | 18 | 22 | 24 | 14.14 | 0.000 |
| 2026 | m<3 | 139 | 0 | 0 | 0 | 1 | 3 | 5 | 6 | 1.94 | 0.367 |
| 2026 | 3≤m<8 | 127 | 0 | 1 | 3 | 5 | 8 | 10 | 13.7 | 5.62 | 0.063 |
| 2026 | m≥8 | 95 | 4 | 6 | 11.5 | 15 | 19 | 22.6 | 24.3 | 15.06 | 0.011 |

**Every anchor moves by at most one carry from 2024 to 2025, in every tier.** That is the empirical case
for a forward-fitted quantile map: the object being carried across seasons is stable, unlike the parametric
shape attempts. The zero share is also stable (0.368 / 0.073 / 0.007 by tier in 2024, 0.387 / 0.043 / 0.000
in 2025).

## The candidate (one, pre-registered)

**V4 = v2's participation layer as the zero mass, over a conditional count distribution whose quantiles are
fitted empirically by tier and interpolated in `m`.**

### Anchors

For each usage tier `t` (`m<3`, `3≤m<8`, `m≥8`, unchanged boundaries), and for levels
`L = {0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95}`:

```
a_t(ℓ) = empirical ℓ-quantile of carries among TRAINING candidates who appeared, in tier t
         (linear interpolation between order statistics, so the anchors are not forced to integers)
c_t    = mean projected mean m of those same training items (the tier's centre)
```

No distributional family is assumed. The seven anchors are the model.

### Interpolation in `m`

A player with projected mean `m` gets anchors interpolated linearly in `m` between the two neighbouring
tier centres; constant beyond the outer centres:

```
m <= c_(1)        -> anchors of tier 1
c_(1) < m < c_(2) -> linear in m between anchors of tier 1 and tier 2
c_(2) <= m <= c_(3)-> linear in m between anchors of tier 2 and tier 3
m > c_(3)         -> anchors of tier 3
```

After interpolation the seven values are clipped to be non-decreasing in ℓ (monotone), so the implied CDF
is valid by construction.

### Discrete distribution from the anchors

`F_app(k) = 0` below `a(0.05)`, `1` above `a(0.95)`, and piecewise-linear in `k` between consecutive
anchors. The conditional PMF is `P_app(k) = F_app(k) - F_app(k-1)` for integer `k >= 0`. This is a proper
distribution on the integers with the fitted quantiles, and it supports CRPS, log loss, Brier and AUC
exactly, with no simulation.

### Zero layer (v2, unchanged)

`p` is v2's participation probability — the `(k, last, status)` cross shrunk toward Spec B's `P_LOG` with
κ = 20, fitted on the same training seasons. `π = 1 - p`. The predictive distribution is

```
P(0)   = π + (1-π) * P_app(0)
P(k)   = (1-π) * P_app(k)          k >= 1
```

so a player who is unlikely to appear gets more mass at zero without the conditional quantiles moving.

### Reference models (reported, not gated)

- **B0** — the incumbent `NB(m, R0)`; unchanged, so every comparison is against the same baseline as v1–v3.
- **Zf** — v2's candidate, for continuity.
- **V4u** — *diagnostic reference only*: the same anchors fitted on the **unconditional** training
  distribution (non-appearances included as zeros) and applied with no mixture. It exists to separate
  "the anchors are wrong" from "the mixture widens the intervals", and it cannot be adopted.

## Which coverage statistic the gate optimises

**The gate is the AGGREGATE coverage on the full pregame population** — not per-tier. For every level
ℓ ∈ {50%, 80%, 90%} and every season s ∈ {2025, 2026}:

```
|aggregate_cov_V4(ℓ, s) - ℓ|  <  |aggregate_cov_B0(ℓ, s) - ℓ|
```

All six comparisons must pass. This is the same gate v1–v3 were judged by, in the same form, and it is
deliberately unchanged.

**Per-tier coverage is a diagnostic, not a gate.** v3 showed the two can disagree in sign — v3 was better
inside every tier and worse in aggregate because B0's tier errors cancel. Reporting per-tier numbers is
required, and they carry no adoption weight whatsoever.

Secondary gate: `MAE_V4 <= MAE_B0 + 0.02` on both seasons.

Reported, not gating: CRPS, log loss, Brier and AUC for `P(carries ≥ 1)`, with paired game-clustered 95%
intervals against B0, and `sd_pred` against `sd_obs`.

## Population (identical to v1–v3, restated)

Weeks 3–18, regular season; Spec B candidates who logged for the team in its last three games with carry
mean `m > 0`; RB and FB folded into RB and **gated**, QB **reported and not gated**, WR/TE out. Outcome is
box-score carries, **0 when the player has no box-score row that week**. No post-game filter.

Fit windows: 2025 ← 2024; 2026 ← 2024–2025. Expected sizes 2,500 (RB 1,714) and 489 (RB 349).

## Guards

- A tier with fewer than **30** appeared training items uses the pooled anchors (all appeared training
  items), and the fallback is recorded in the frozen JSON.
- Anchors are clipped non-decreasing after interpolation.
- PMF support is `0..160`; mass beyond is negligible and `crps_discrete` already charges the excess.
- `p` is floored at 0.02 as in v2, so `π` cannot reach 1.

## What this construction does not do

- **It does not preserve Spec B's mean.** v1–v3 were built so the predictive mean equals `m` exactly
  (`μ = m/(1-π)`). A quantile map cannot do that and stay a quantile map: its mean is whatever the fitted
  quantiles imply. Bias and MAE are therefore reported, and MAE is gated at `B0 + 0.02`. This is a
  deliberate trade of the mean-preservation rule for shape fidelity, declared before the run.
- **It does not re-fit or replace participation.** `p` is v2's, unchanged.
- **2026 is sampling-noise-limited.** At n = 489 the standard error of a 90% coverage estimate is about
  1.4 points, while B0's 2026 error at that level is 0.4 points. A perfectly calibrated model would still
  be close to a coin flip against that comparison. Stated here so the result is read correctly whichever
  way it lands; it is not a reason to relax the gate.

## Fail-closed

If the six aggregate comparisons do not all pass, the verdict is NOT_ADOPTED, the result is recorded, and
the workstream reports where it stands. No post-hoc change to the anchors, the levels, the tiers, the
interpolation or the gate.

## Deliverables

- `backend/audit_nfl_quantile_stability_v4.py` — the audit above (already run, read-only).
- `backend/nfl_rushing_quantile_map_v4.py` — harness; reuses v2's population, participation fit, scoring
  and game-clustered paired intervals.
- `docs/RESULTS-nfl-rushing-participation-v4.md` — results, verdict, honest reading.
- `docs/frozen-nfl-rushing-participation-v4.json` — anchors, tier centres, participation parameters, all
  tables, all paired comparisons, the six gate checks and the verdict.
