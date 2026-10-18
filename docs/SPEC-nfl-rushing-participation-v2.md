# SPEC: NFL rushing participation v2 — individualised P(plays) and a single-inflation count

Status: PRE-REGISTERED 2026-10-18, before any v2 parameter fit or any v2 holdout number was computed.
Branch `feat/nfl-rushing-participation-v2`, based on `origin/dev` (7dd1b62b).
Follows `feat/nfl-rushing-carries-dist-v1` (24d793c6), which is NOT_ADOPTED and frozen for prospective
confirmation on 2026 weeks 7-18. **This experiment does not touch that window or its frozen parameters.**

## The question

v1 modelled participation as `P(plays | injury designation)` in four levels and the count as a hurdle.
It gained CRPS but failed the coverage gate: at 50/80/90 the intervals were `0.546/0.819/0.910` against
nominal, because both the participation probability and the count shape were wrong in the same direction.

v2 asks a narrower question: **does an individualised participation probability — Spec B's own recent-form
table `P_LOG`, crossed with the injury designation — fix the zero mass?** The designation identifies only
about a fifth of the non-participants. The rest are players who simply did not appear, and `recent_form`
already knows something about them: whether the player logged in the team's last three games, and whether
he logged in the most recent one.

The count layer changes once, in a way that follows from the same diagnosis: one free zero-inflation
parameter instead of the hurdle's two probabilities multiplied together.

## Population (identical to v1)

- Regular season, weeks 3 to 18, seasons 2025 (holdout) and 2026 (development evidence).
- Candidates: `History.candidates(season, team, week)` — players who logged for the team in its last three
  games before the target week, with a Spec B carry mean `m > 0`. No post-game filter.
- RB and FB folded into RB. **QB is reported separately and is not part of the adoption gate.** WR/TE out.
- Outcome: box-score carries, **0 when the player has no box-score row that week**.
- Audit population sizes (weeks 3-18, `audit_nfl_participation_v2.py`): 2024 2,526 candidate-games
  (RB 1,752, QB 774), 2025 2,500 (1,714 / 786), 2026 489 (349 / 140). Stated again in the results.

## What the audit establishes

### The participation event is box-score appearance, and it is not the availability flag

Over 2024-2026 there are **276 RB candidate-games where the availability table says the player was active
and yet he has no box-score row**. Those are genuine played-and-recorded-nothing games: they carry zero
carries. Conversely a player with no box-score row certainly carried zero times. The event that decides
whether the count can be non-zero is therefore **appearance in the box score**, which is also exactly what
`P_LOG` predicts. v1 used the availability flag instead; v2 uses appearance and reports the difference.

| season | candidates | appeared | availability known | appearance == played_flag (of known) |
|---|---:|---:|---:|---:|
| 2024 | 2,526 | 0.731 | 92.0% | 92.95% |
| 2025 | 2,500 | 0.746 | 90.2% | 95.43% |
| 2026 | 489 | 0.738 | 58.5% | 90.91% |

### The designation is a minority of the non-participation

| season | RB non-appearances | with a designation | share |
|---|---:|---:|---:|
| 2024 | 419 | 116 | 27.7% |
| 2025 | 361 | 86 | 23.8% |
| 2026 | 84 | 8 | 9.5% |

RB+QB 2025: 636 non-appearances, 135 designated (21.2%).

**Reconciliation with v1's "110 of 534".** v1 counted "did not play" as `played_flag != 1`, which includes
the 244 candidates with no availability row. That definition reproduces **exactly: 534 in 2025** (290 with
`played_flag = 0`, 244 with no availability row). The designation count on those 534 is **130 today**
(Out 96, Questionable 27, Doubtful 7) rather than the 110 recorded on 2026-10-17 — the same definition on
the same population, with 20 more designations now recorded as non-participants. The status and
availability tables have been written since v1 ran; the population definition did not change.

### `P_LOG` discriminates, and it is roughly calibrated

On RB candidates, Spec B's frozen `P_LOG_2024` table:

| season | n | mean P_LOG | observed appearance | Brier | Brier (constant) | AUC |
|---|---:|---:|---:|---:|---:|---:|
| 2024 | 1,752 | 0.781 | 0.761 | 0.1440 | 0.1820 | 0.7510 |
| 2025 | 1,714 | 0.797 | 0.789 | 0.1226 | 0.1663 | 0.7902 |
| 2026 | 349 | 0.758 | 0.759 | 0.1411 | 0.1828 | 0.7698 |

Cell-level in 2025 (`k` = games logged of the last three, `last` = logged in the most recent):
`(1,0)` 0.343 → 0.269, `(1,1)` 0.596 → 0.645, `(2,0)` 0.505 → 0.468, `(2,1)` 0.801 → 0.792,
`(3,1)` 0.917 → 0.918. It is close enough to use as a prior and not close enough to use raw.

### The cross is thin in places, so the fit needs shrinkage

2024 RB candidates live in 5 main `(k,last)` cells plus designation splits: 12 cells have n < 20 and
cover 89 of 1,752 candidates. Hence the fixed shrinkage constant below.

## Models

Let `m` be Spec B's frozen carry mean for the player-game (conditional on appearing), `p` the fitted
probability of appearing, `π = 1 - p`, `R` a NegBin dispersion (`var = μ + μ²/R`).

| id | distribution | what it is |
|---|---|---|
| B0 | `NB(m, R0)` | the incumbent: no zero inflation, Spec B's conditional mean |
| Zd | `π[0] + (1-π) NB(m/(1-π), R)` | single-inflation ZINB, `p` from **designation only** |
| **Zf** | `π[0] + (1-π) NB(m/(1-π), R)` | single-inflation ZINB, `p` from **recent form × designation** (primary) |
| B2ref | `(1-pq)[0] + pq ZTNB(m/q, R_t)` | v1's hurdle, re-fitted here as a reference only, not gated |

`Zf` and `Zd` share the count layer, so `Zf - Zd` isolates the recent-form participation and `Zd - B0`
isolates the single-inflation form. `B2ref` answers "does this beat the v1 candidate", which the gates do
not require but a reader will ask.

The count component is **untruncated**: `μ = m/(1-π)` makes the ZINB mean equal `m`, so Spec B's point
estimate is preserved exactly and only the shape around it changes. `π` is floored at 0.02 so `μ` stays
finite; with `p` ≤ 0.02 the model degenerates to `NB(m/0.98, R)`, a 2% zero mass.

### Fitting: forward only, training seasons only

For each evaluation season, everything is fitted on **seasons strictly before it** (2025 ← 2024;
2026 ← 2024-2025), on the same candidate population and the same weeks 3-18.

- **`p` (primary):** `p = (a + κ·p_log) / (n + κ)` where, over training candidates, `n` is the count in
  cell `(k, last, status)` and `a` the number who appeared. `p_log` is Spec B's frozen table value for
  `(k, last)`. **κ = 20**, chosen from the audit (thin cells have n < 20) and not tuned on any
  evaluation season. `status` is the report designation, `""` when there is none.
- **`p` (designation-only, for Zd):** share appeared by `status`, pooled fallback for an unseen status.
- **`R`:** method of moments on training candidates **who appeared**, with `μ_i = m_i/(1-π_i)`:
  `R = Σμ² / Σ((k-μ)² - μ)`, floored at 0.5. `R0` for B0 uses the same formula with `μ = m`.
- **`B2ref`:** v1's q by usage tier (`m<3`, `3<=m<8`, `m>=8`) and `R_t` on a fixed grid, both fitted on
  training candidates who appeared, exactly as v1 did.
- Spec B's constants are frozen at their current values (`P_LOG_2024`, `K_T = 8`). Nothing in the engine
  is refitted.

## Metrics

Primary: **coverage** of the 50/80/90% central intervals (exact discrete quantiles) on the full pregame
population. Secondary: CRPS, MAE of the predictive mean, bias, sd of the predictive distribution, Brier
and AUC for `P(carries >= 1)`. Reported for all candidates, RB (gated), QB (not gated), played-only, and
weeks 3-5.

Paired comparisons are per player-game against B0, with a 95% interval clustered by game.

## Adoption gate (pre-registered)

`Zf` is adopted only if **all** of the following hold:

1. **Coverage (primary):** for every level ℓ ∈ {50%, 80%, 90%} and every evaluation season
   s ∈ {2025, 2026}, `|cov_Zf(ℓ,s) - ℓ| < |cov_B0(ℓ,s) - ℓ|`. All six comparisons.
2. **MAE:** `MAE_Zf <= MAE_B0 + 0.02` carries on both seasons.
3. **Reported, not gating:** CRPS lower than B0 with a paired game-clustered 95% interval excluding zero
   on both seasons. v1 showed that a CRPS gain can coexist with broken calibration, so a CRPS gain alone
   cannot carry adoption here.

Fail closed: if the coverage gate fails, the verdict is NOT_ADOPTED, the result is recorded, and the
workstream moves on. No post-hoc change to the population, the shrinkage constant, the cells or the gate.

## Research discipline

2026 is **explored development evidence** and has been analysed repeatedly in this workstream. 2025 is the
holdout. The only genuinely new evidence for this facet will be the frozen prospective window, if a
candidate is adopted. 2026 weeks 7-18 belong to the v1 prospective confirmation and are not used here
beyond the ordinary evaluation season.

## Deliverables

- `backend/audit_nfl_participation_v2.py` — the audit above (already run, read-only).
- `backend/nfl_rushing_participation_v2.py` — the harness.
- `docs/RESULTS-nfl-rushing-participation-v2.md` — results, verdict, next step.
- `docs/frozen-nfl-rushing-participation-v2.json` — fitted parameters, for reproduction and any later
  prospective run.
