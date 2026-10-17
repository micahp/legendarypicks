# NFL props: does plays x pass-rate beat the incumbent on team attempts?

Measured 2026-10-16 on `picks.dev.db` (read-only for every grade), on
`feat/nfl-props-opportunities-propensity`. The incumbent
(`nfl_player_projection_v2.project_qb`) projects a team's pass attempts as

    att = team_volume('att', K_T=8) * qb_share

where `team_volume` blends the team's own season-to-date attempts with what its
opponent allowed, each regressed to the league mean with K_T = 8 pseudo-games.
Section 6 of `RESULTS-nfl-marcel-and-calibration-2026-10-16.md` showed that this
compresses dispersion badly: the projection has sd 1.7 against an actual sd of
9.7, because with one to four games behind a team, 67% to 89% of the projection
is the league mean.

This tests the decomposition

    att = opportunities(team) * propensity(team) * qb_share

with opportunities = offensive plays per game and propensity = pass attempts per
play, each regressed to its own league mean with its own pseudo-count
(K_OPP pseudo-games, K_PROP pseudo-plays). The claim under test is that a team's
play count and its pass rate vary independently enough that separating them
carries more signal than the blended attempt rate.

Both models are fitted on the fit seasons (2013 to 2021) in the early-week
regime only (weeks 2 to 5), the only regime props exist in, then evaluated on
seasons neither fit saw. The script is `backend/nfl_qb_opportunities_propensity.py`.

## What was added

Nothing was added to the database. The script reads `nfl_pbp` and
`player_game_logs` only.

## Results

### Fit on 2013-2021, weeks 2 to 5 (MAE)

| model | K_T / K_OPP, K_PROP | MAE | n |
|---|---|---:|---:|
| incumbent | K_T 8.00 | 6.5647 | 1108 |
| separated | K_OPP 8.0, K_PROP 400 | 6.5605 | 1108 |

### Holdout 2026 (MAE-fitted)

| model | n | MAE | sd proj (act) | bias | AUC |
|---|---:|---:|---:|---:|---:|
| incumbent | 128 | 6.4798 | 1.095 (8.812) | -1.734 | 0.5774 |
| separated | 128 | 6.4745 | 1.157 (8.812) | -1.739 | 0.5770 |
| paired |sep| - |inc| | | -0.0053 | +/- 0.0188 | | |

### Holdout 2026 (AUC-fitted)

| model | params | AUC (fit) | MAE | AUC (holdout) |
|---|---|---:|---:|---:|
| incumbent | K_T 4.00 | 0.5796 | 6.4611 | 0.5897 |
| separated | K_OPP 8.0, K_PROP 200 | 0.5815 | 6.4822 | 0.5852 |
| paired |sep| - |inc| | | +0.0210 | +/- 0.0625 |

### By season and regime

Both models are evaluated on every holdout season, in the early-week regime
(weeks 2 to 5) and across all weeks:

| season | regime | inc MAE | sep MAE | paired sep-inc |
|---:|---|---:|---:|---:|
| 2010 | wk2-5 | 7.0612 | 7.0440 | -0.0173 +/- 0.0234 |
| 2010 | all wk | 6.5207 | 6.5086 | -0.0121 +/- 0.0109 |
| 2011 | wk2-5 | 6.4321 | 6.4351 | +0.0030 +/- 0.0238 |
| 2011 | all wk | 6.5557 | 6.5465 | -0.0092 +/- 0.0115 |
| 2012 | wk2-5 | 7.0586 | 7.0443 | -0.0143 +/- 0.0244 |
| 2012 | all wk | 7.0783 | 7.0628 | -0.0156 +/- 0.0122 |
| 2022 | wk2-5 | 7.0435 | 7.0271 | -0.0164 +/- 0.0268 |
| 2022 | all wk | 6.6060 | 6.5746 | -0.0314 +/- 0.0128 |
| 2023 | wk2-5 | 6.0303 | 6.0326 | +0.0023 +/- 0.0242 |
| 2023 | all wk | 5.9193 | 5.9135 | -0.0059 +/- 0.0099 |
| 2024 | wk2-5 | 6.8136 | 6.8090 | -0.0046 +/- 0.0185 |
| 2024 | all wk | 6.1005 | 6.0977 | -0.0029 +/- 0.0093 |
| 2025 | wk2-5 | 6.3636 | 6.3582 | -0.0054 +/- 0.0160 |
| 2025 | all wk | 6.1097 | 6.0986 | -0.0111 +/- 0.0075 |
| 2026 | wk2-5 | 6.3913 | 6.3849 | -0.0064 +/- 0.0190 |
| 2026 | all wk | 6.4798 | 6.4745 | -0.0053 +/- 0.0188 |

## Verdict: NOT ADOPTED

The differences in point accuracy and discrimination are not established. On the
2026 holdout, separated beats incumbent on MAE by 0.0053 but the paired clustered
interval is +/- 0.0188, so it spans zero. On the AUC objective, separated wins
the fit (0.5815 vs 0.5796) but loses the holdout (0.5852 vs 0.5897), with a paired
difference of +0.0210 +/- 0.0625, also spanning zero. Across all seasons and
regimes, the separated model is at best tied and at worst slightly worse (2011
wk2-5: +0.0030), and every paired interval spans zero.

Three observations explain why:

1. **The dispersion problem is unchanged.** Both models project sd ~1.1 against
   actual sd 8.8 on 2026. The separated model adds marginal variance (1.157 vs
   1.095) but remains far below the true spread. The plays x pass-rate decomposition
   does not solve the core issue identified in section 6 of the calibration doc:
   the team-level projection is dominated by early-season shrinkage regardless of
   how the volume is parameterized.

2. **The two components are not independently informative.** The fit selects
   K_OPP 8.0 and K_PROP 800 (MAE) or 200 (AUC), which are the high-regression
   corners of the grid. That means the separated model is regressing both plays
   and pass rate heavily toward their league means, which is nearly equivalent to
   regressing the blended attempt rate toward the league mean — the incumbent
   with K_T 8.

3. **Pass rate barely varies.** The fit-season pass rate has sd 0.047 around a
   mean of 0.538, so splitting it into a separate term adds little discriminatory
   signal. Plays explain about 40% of attempt variance in the fit season; the
   remaining 60% is the pass-rate layer, and it is low-variance by nature.

## One distinction for the report

This experiment tested point accuracy (MAE) and discrimination (AUC), not the
complete predictive distribution. The experiment does not establish that the
separated approach improves the full distribution, but a definitive
distribution-level conclusion would require CRPS and interval-coverage testing,
which this script does not perform.

Separately, the standard deviation of actual team attempts (9.7) should not be
treated as comparable to the standard deviation of projected means (1.1). Much of
the observed variation is irreducible game-to-game noise.

## Reuse note: Gridiron Physics

The plays x pass-rate decomposition is retained for Gridiron Physics, where it
serves a different purpose: generating coherent sequences of plays for offensive
narratives, not improving pregame attempt predictions. The structure is sound
there because the goal is internally consistent play-by-play sequencing, not the
point forecast.

## Closing the experiment

The script (`backend/nfl_qb_opportunities_propensity.py`) and this results
document are committed on `feat/nfl-props-opportunities-propensity` as the
read-only record. No further tuning of this particular decomposition will be
pursued. The experiment is NOT_ADOPTED, but the incumbent parameters
(K_T 8.0 for attempts, as fitted in `refit_nfl_qb_volume.py`) are retained.

## Reproducing

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
python3 nfl_qb_opportunities_propensity.py \
    --fit-seasons 2013 2014 2015 2016 2017 2018 2019 2020 2021 --season 2026
```
