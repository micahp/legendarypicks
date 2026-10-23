# nfl_sequence v0.1: measured results, 2022–2023 held-out seasons

Status: research measurement. **This is not a prediction of a real game.** Every script the engine writes is labelled
HYPOTHETICAL MODEL SIMULATION. Nothing here is a forecast of an NFL result, a market price or a betting edge.

Integration contract: [NFL-SEQUENCE-INTEGRATION-v0.1.md](NFL-SEQUENCE-INTEGRATION-v0.1.md). Source JSON, committed as
[results/eval-2022-2023-t100-v2.json](results/eval-2022-2023-t100-v2.json), written by the evaluator at the revision named below.

## Setup

| item | value | JSON key |
|---|---|---|
| model version | `nfl-seq-v0.1` | `model_version` |
| headline variant | `main` (decisions condition on down, distance, field, score, quarter) | `variants.main` |
| comparison variants | `state_transition`, `frequency`, and a league-average constant | `variants.*` |
| training seasons | 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021 (3,088 regular-season games) | `train_seasons` |
| test seasons | 2022, 2023 | `test_seasons` |
| test games | 543 (302 home wins, 239 away wins, 2 ties) | `test_game_outcomes` |
| trials per game | 100 (54,300 simulated games per variant) | `trials_per_game`, `variants.main.event_validity.trials` |
| seeds | `derive_seed(game_key, snapshot_hash, model version, trial)`; snapshot hash from pregame identity only | code: `nfl_sequence/evaluate.py` |
| source | nflverse play-by-play 2010–2023; test seasons read only for evaluation | — |

Command (run from `backend/`, with pyarrow available):

```
python -m nfl_sequence.evaluate --source-dir <nflverse parquet dir> --model-dir nfl_sequence/models \
  --test-seasons 2022-2023 --trials 100 --schedule-db <sqlite with nfl_schedule> --out <json>
```

## Unit of inference and baselines

Each game's win probability is the share of its 100 seeded trials won by the home side, among trials with a
decisive score. The trials of one game are not independent evidence about that game, so the unit of inference is the
**game**. Intervals are game-clustered: games are resampled with replacement, 2000 reps, seed 20261022, percentile 95%.
Tied games are excluded from the win metrics (2 games, `scoring_bootstrap.ties`).

No-skill baselines:
- Brier and log loss: a constant forecast equal to the **training** home-win base rate, 0.5569 = 1,714 home wins of 3,078 decisive training games (3,088 games, 10 ties; `backend/nfl_sequence/models/manifest.json`, key `finals`). The value is also in `variants.main.scoring_bootstrap.base_rate_home`.
  The test-season home-win share among decisive games is 0.5582; the always-home accuracy equals that share.
- Accuracy: a coin flip, 0.5.

The bootstrap also gives the difference from the base-rate forecast, paired within each resample. An interval that
excludes 0 on the wrong side of zero means the model is measurably worse than the base rate at this sample size.

The revised run replaces an earlier Laplace-smoothed estimate. A first run with the evaluator at commit `e7de28af` gives
identical validity, calibration and reconstruction aggregates, but its win probabilities were smoothed, so this document
uses only the revised run.

## Game-level scoring

| variant | winner accuracy [95% CI] | coin flip | Brier [95% CI] | Brier, base-rate forecast | Brier − base [95% CI] | log loss [95% CI] | log loss, base-rate forecast | log loss − base [95% CI] | total-points MAE | total-points bias |
|---|---|---|---|---|---|---|---|---|---|---|
| `main` | 0.4935 [0.4529, 0.5323] | 0.5000 | 0.2543 [0.2499, 0.2588] | 0.2466 | 0.0077 [0.0012, 0.0143] | 0.7018 [0.6931, 0.7108] | 0.6864 | 0.0154 [0.0025, 0.0287] | 11.615 | -6.474 |
| `state_transition` | 0.4455 [0.4048, 0.4861] | 0.5000 | 0.2567 [0.2526, 0.2608] | 0.2466 | 0.0101 [0.0039, 0.0167] | 0.7066 [0.6985, 0.7149] | 0.6864 | 0.0202 [0.0078, 0.0335] | 11.510 | -6.209 |
| `frequency` | 0.4861 [0.4455, 0.5287] | 0.5000 | 0.2531 [0.2486, 0.2573] | 0.2466 | 0.0065 [0.0001, 0.0130] | 0.6995 [0.6905, 0.7080] | 0.6864 | 0.0132 [0.0003, 0.0263] | 10.770 | -2.126 |
| `constant_league_average` | 0.5582 [0.5176, 0.6026] | 0.5000 | 0.2466 [0.2416, 0.2512] | 0.2466 | 0.0000 [0.0000, 0.0000] | 0.6864 [0.6762, 0.6956] | 0.6864 | 0.0000 [0.0000, 0.0000] | 11.132 | 2.056 |

Keys: `variants.<name>.scoring_bootstrap.metrics.{accuracy,brier,base_brier,brier_minus_base,log_loss,base_log_loss,log_loss_minus_base}`;
`variants.<name>.scoring.{mae_total,bias_total}`. The always-home accuracy, 0.5582, is the test home-win share
(`test_game_outcomes`), and the constant forecast's accuracy (`variants.constant_league_average`) equals it.

Read the table in this order. Accuracy is compared with the coin flip **and** with the always-home share, not with
zero. Brier and log loss are compared with the base-rate forecast in the adjacent columns.

Coverage of the 80% central interval of simulated totals across trials (`variants.<name>.scoring.coverage80_total`): `main` 0.694, `state_transition` 0.689, `frequency` 0.783.

## Event validity (simulated trials)

| variant | trials | valid full games | validation problems | run exceptions | scrimmage plays/game | drives/game | turnovers/game | sacks/game | points/game (both teams) |
|---|---|---|---|---|---|---|---|---|---|
| `main` | 54,300 | 1.0000 | 0 | 0 | 141.83 | 22.08 | 2.35 | 4.65 | 37.18 |
| `state_transition` | 54,300 | 1.0000 | 0 | 0 | 142.10 | 22.10 | 2.38 | 4.73 | 37.44 |
| `frequency` | 54,300 | 1.0000 | 0 | 0 | 141.06 | 28.43 | 2.40 | 4.73 | 41.52 |
| held-out actual | 543 games | — | — | — | 135.47 | 22.07 | 2.45 | 4.95 | 43.65 |

Keys: `variants.<name>.event_validity.*` and `actual.*`. Validity means every script reached a final score and passed
`validate_script`; plausibility is the comparison with the held-out seasons, not a claim of realism.

Call mix, share of scrimmage calls (`variants.main.event_validity.call_share`, `actual.call_share`):

| call | simulated `main` | held-out actual |
|---|---|---|
| run | 0.355 | 0.354 |
| pass | 0.536 | 0.548 |
| punt | 0.067 | 0.056 |
| field_goal | 0.029 | 0.029 |
| kneel | 0.011 | 0.012 |
| spike | 0.002 | 0.002 |

## Play-level calibration (held-out plays)

| variant | calls (n) | call log loss | call top-1 accuracy | call ECE | pass-class (n) | pass log loss | pass top-1 accuracy | pass ECE |
|---|---|---|---|---|---|---|---|---|
| `main` | 73559 | 0.6294 | 0.6775 | 0.0105 | 40313 | 1.0753 | 0.5728 | 0.0069 |
| `state_transition` | 73559 | 0.6662 | 0.6510 | 0.0081 | 40313 | 1.0719 | 0.5740 | 0.0070 |
| `frequency` | 73559 | 1.0235 | 0.5480 | 0.0028 | 40313 | 1.0818 | 0.5728 | 0.0054 |

Keys: `variants.<name>.calibration.{call,pass_class}`. ECE uses 10 bins over the top predicted probability.

## Historical reconstruction (one-step replay of recorded plays; not prediction)

Each recorded play is applied to its recorded pre-play state and compared with the recorded pre-play state of the next play.
Steps do not cascade. Keys: `reconstruction.2022.counts` and `reconstruction.2023.counts`, summed.

- rows: 91,786 total; 71,615 checked (68,496 matches, 3,119 mismatches); 20,171 excluded, in these categories:
  - `unsupported_play_row`: 10,452
  - `next_row_is_penalty_or_no_play`: 8,949
  - `overtime_not_checked`: 571
  - `next_state_incomplete`: 182
  - `runoff_anomaly`: 16
  - `event_invalid:ValueError`: 1
- mismatches by recorded-play attribution, largest first:
  - `mismatch:yardline_100@kickoff_return`: 1434
  - `mismatch:yardline_100@interception`: 615
  - `mismatch:yardline_100@fumble_lost`: 259
  - `mismatch:yardline_100@field_goal`: 217
  - `mismatch:ydstogo+yardline_100@run`: 107
  - `mismatch:yardline_100@pass`: 92
  - `mismatch:phase@interception`: 71
  - `mismatch:offense+yardline_100@fumble_lost`: 60
- rows excluded as unsupported (penalties, no-plays, two-point tries): `unsupported_play_row` 10452, `next_row_is_penalty_or_no_play` 8949

The largest mismatch sources are the unmodelled interception and fumble return yards, and the kickoff-return spot convention
(`kickoff_return`), which nflverse's `return_yards` does not measure consistently from the 25.

## Denominators and unsupported mechanics

| quantity | value | denominator (named) | JSON key |
|---|---|---|---|
| penalty rows | 6135 | 94556 regular-season rows: 0.0649 | `denominators.penalty_rows`, `denominators.penalty_share_of_reg_rows` |
| penalty rows | 6135 | 76470 run, pass and no-play rows: 0.0802 | `denominators.penalty_share_of_run_pass_no_play_rows` |
| two-point tries | 246 | 2602 conversion attempts (extra points 2356 + two-point 246): 0.0945 | `denominators.two_point_share_of_conversion_attempts` |
| overtime games | 33 | 543 games: 0.0608 | `unsupported_mechanics.overtime` |

Not modelled, and listed in every script's `unsupported_mechanics`: penalties, two-point tries (every try is an extra point),
timeouts and challenges, participants and rosters, interception and fumble return yards, and an approximate regular-season
overtime. Team strength is not an input to v0.1: it is team-agnostic apart from the playbook's call weights, so no team
quality is evaluated here.

## Schedule reconciliation

Final scores derived from play-by-play against the published `nfl_schedule` table: 543 games checked, 543 published, 0 score mismatches, 0 missing (`schedule_reconciliation`).

## Interpretation

- The engine does not outperform a no-skill forecast on game outcomes. The main variant's Brier score is measurably worse
  than the base-rate forecast, and its winner accuracy is below a coin flip (`variants.main.scoring_bootstrap`).
  That is expected for a team-agnostic model: it carries no team strength, and winner accuracy is not a target for it.
- The simulation scores fewer points than the held-out seasons: 37.18 points per game against 43.65 actual, a bias of -6.47
  for total points (`variants.main.scoring.bias_total`). This is a calibration gap of the outcome layer, not a sign of fidelity.
- Drive counts agree with the held-out seasons, 22.08 against 22.07 per game. Drive-level behaviour is evaluated separately, in a drive-level report that is still in progress.
- This is a research measurement. It does not show that the engine predicts real games, and nothing here is a betting or forecasting claim.

## Reproducibility

Two complete runs at the same settings agree exactly on every `event_validity` key, every `calibration` key and the reconstruction counts.
Their scoring keys differ only because the first run stored Laplace-smoothed win probabilities. The first run used the evaluator at commit `e7de28af`.
