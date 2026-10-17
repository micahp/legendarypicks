# NFL receiver target-share distribution v1

Measured 2026-10-16 on `picks.dev.db` (read-only), on
`nfl-receiver-target-share-dist-v1`. The incumbent is Spec B
(`nfl_player_projection_v2.project`): team targets via
`team_volume('tgt', K_T=8)` times a recency-weighted share regressed to the
prior, with the v2.0 injury-report redistribution. All parameters are frozen
from 2024; 2026 is held out for prospective confirmation.

The experiment tests three candidate ways to allocate the team's target total
among its skill-position players.

## What was added to the database

Nothing. The script (`backend/nfl_receiver_target_share_dist_v1.py`) reads
`player_game_logs`, `player_game_availability`, and the engine's in-memory
`History` view.

## The three candidates

1. **Baseline.** Spec B as-is: `eng.project()` produces a point estimate of
   player targets, then `eng.simulate()` draws from a negative binomial
   (R = 3.41, frozen from 2024). Availability is handled by v2.0: remove
   Out/Doubtful, redistribute proportionally.

2. **Availability-adjusted.** Same as baseline, but each candidate's share is
   probability-weighted by their pre-kickoff play probability `p_play`
   (from `player_game_availability.report_status`): Out/Doubtful p_play = 0
   (removed), Questionable p_play = 0.634, null/empty p_play = 0.899. The
   effective share = base_share * p_play, normalized to (1 - OTHER).

3. **Dirichlet-multinomial.** Team targets T are distributed among available
   players where the share vector is drawn from Dirichlet(alpha), with alpha_i
   = base_share_i * p_play_i * phi. phi is grid-searched on 2024 to minimize
   CRPS on targets. No negative-binomial layer: the count variability comes
   entirely from the Dirichlet-multinomial.

## Results

464 eligible player-games on 2026 weeks 3 to 18 (RB/WR/TE with 3+ prior games).

### Primary test: CRPS on targets

| model | CRPS mean | ± 1.96 SE | n |
|---|---:|---:|---:|
| baseline | 1.4153 | 0.1492 | 464 |
| avail_adj | 1.4134 | 0.1489 | 464 |
| dirichlet (phi=20) | 1.3977 | 0.1478 | 464 |

### Paired CRPS differences (per player-game, same 464 games)

| comparison | mean | ± 1.96 SE | interval |
|---|---:|---:|---:|
| avail_adj - baseline | -0.0019 | 0.0061 | [-0.0139, +0.0101] |
| dirichlet - baseline | -0.0176 | 0.0154 | [-0.0480, +0.0128] |
| dirichlet - avail_adj | -0.0156 | 0.0132 | [-0.0416, +0.0104] |

### Coverage on targets

| model | 50% nominal | 80% nominal | 90% nominal |
|---|---:|---:|---:|
| baseline | 0.668 | 0.853 | 0.925 |
| avail_adj | 0.670 | 0.853 | 0.925 |
| dirichlet | 0.390 | 0.623 | 0.754 |

### MAE on point estimates (mean of simulated draws)

| model | targets |
|---|---:|
| baseline | 1.8898 |
| avail_adj | 1.8885 |
| dirichlet | 1.8658 |

## Verdict: NOT_ADOPTED

### Availability-adjusted

Avails_adj is directionally better than baseline on CRPS (-0.0019) and MAE
(-0.013 targets), but the paired clustered interval on CRPS spans zero
[-0.0139, +0.0101], so the improvement is **not established**. Coverage is
essentially unchanged. The probability-weighted share adjustment reduces
bias slightly for Questionable players, but the effect is too small to be
distinguished from noise at this sample. The model is worth revisiting if
p_play is jointly calibrated rather than fixed from 2024 rates, but the
current version does not clear the gate.

### Dirichlet-multinomial

The Dirichlet model achieves the lowest CRPS (1.3977 vs 1.4153) and MAE
(1.8658 vs 1.8898), but the paired interval still spans zero
[-0.0480, +0.0128]. More importantly, **coverage fails the acceptance test**:
50% coverage is 39.0% (nominal 50%), 80% is 62.3% (nominal 80%), and 90% is
75.4% (nominal 90%). The model is systematically under-dispersed.

The cause is structural. The phi grid search selected phi = 20.0, the
highest candidate tested, which means CRPS keeps improving as phi increases
(more certainty). But high phi makes the Dirichlet-multinomial collapse toward
the multinomial, which has less variance than the negative binomial (R = 3.41)
that the baseline uses. The Dirichlet-multinomial has no independent
overdispersion parameter: its variance is determined by T, p, and phi, and it
cannot match the observed target-count variance that the negative binomial
captures.

A lower phi would improve coverage but worsen CRPS — the two objectives
diverge because the Dirichlet-multinomial variance structure does not match
the data. The right follow-up would be a Dirichlet + negative-binomial hybrid:
draw shares from Dirichlet, then draw counts from NegBin(T * share, R). This
preserves the inter-player correlation of the Dirichlet while retaining the
count-level overdispersion that the data requires.

## What stays on the branch

- `backend/nfl_receiver_target_share_dist_v1.py` — the experiment script,
  read-only, reproduces the numbers above.
- `docs/PLAN-nfl-receiver-target-share-dist-v1.md` — the pre-registered plan.
- `docs/RESULTS-nfl-receiver-target-share-dist-v1-2026-10-16.md` — this file.

The incumbent (Spec B with K_T = 8.0 for team targets, DEFAULTS for shares)
remains the baseline. The next candidate to test is rushing carries.

## Reproducing

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
python3 nfl_receiver_target_share_dist_v1.py --season 2026
```
