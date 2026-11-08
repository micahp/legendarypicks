# Allocation models against real carries and targets, 2026-11-08

Script: `scripts/nfl_sequence/evaluate_workload_calibration.py`. Tests: `test_evaluate_workload_calibration.py` (10 tests, and a mutation check showed the leakage test fails if the harness reads the game it scores). Outputs: `eval-<season>-<role>.json` and `.csv` in this folder. No game is simulated.

All results are **exploratory**. The test has no pregame injury or roster data. For each team-game, the player set is every player with earlier usage for that team (previous seasons, or earlier weeks of the same season). Real usage by anyone else is pooled as OTHER, which holds 3.2% to 5.3% of opportunities. Each model receives the real team total N, so the test measures who gets the opportunities, not how many there are.

## Models

| Model | What it does |
|---|---|
| A | League-average share by position and prior-season usage rank. This is a proxy for the layers-off fallback, because historical depth charts are not available. |
| B | Fixed shares from 2022 up to the season before the evaluation. A multinomial draw, with no per-game variation. |
| C | The current layer: previous-season shares with the fitted Dirichlet concentration. |
| D | Previous-season shares blended with the team's earlier games this season: w = 4 / (4 + g). It reuses C's concentration. N0 = 4 is the existing default. Nothing was tuned. |

## Results

Mean negative log-likelihood (NLL) per team-game: lower is better. "vs C" is the paired mean difference with a 95% interval from resampling games. A negative number means the model beats C.

| Run | Team-games | A | B | C | D | D vs C |
|---|---:|---:|---:|---:|---:|---|
| 2025 targets | 544 | 33.23 | 54.55 | 32.71 | **26.29** | -6.41 [-6.84, -6.01] |
| 2025 carries | 544 | 19.12 | 51.35 | 18.41 | **14.12** | -4.28 [-4.67, -3.92] |
| 2026 weeks 1-8 targets | 242 | 33.46 | 58.63 | 32.50 | **27.91** | -4.59 [-5.17, -4.04] |
| 2026 weeks 1-8 carries | 242 | 17.79 | 50.82 | 17.51 | **14.64** | -2.87 [-3.30, -2.47] |

A against C: +0.53 [0.39, 0.66], +0.72 [0.63, 0.80], +0.96 [0.75, 1.15], +0.28 [0.11, 0.46] in the same order. B against C: +21.8 to +33.3 in every run.

Other measures for model C and model D:

| Run | Mean absolute share error (C / D) | Top player correct (C / D) | 80% interval coverage, main players (C / D) |
|---|---|---|---|
| 2025 targets | 0.0311 / 0.0256 | 0.388 / 0.450 | 0.670 / 0.777 |
| 2025 carries | 0.0425 / 0.0326 | 0.498 / 0.689 | 0.690 / 0.757 |
| 2026 w1-8 targets | 0.0265 / 0.0232 | 0.302 / 0.401 | 0.688 / 0.783 |
| 2026 w1-8 carries | 0.0355 / 0.0302 | 0.591 / 0.702 | 0.606 / 0.675 |

"Main players" are players the model gives at least 10% of the opportunities. The target for an 80% interval is 0.80.

## What this shows

- **Adapting to the current season helps, in all four runs.** Model D beats the current layer on NLL, share error and top-player accuracy. The paired interval excludes zero each time. The Charbonnet and floor-weight problems in `README.md` are the kind of error this fixes.
- **The current layer is only slightly better than a position-and-rank rule (A).** The gap is 0.3 to 1.0 NLL, against D's gain of 2.9 to 6.4.
- **Fixed shares with no per-game variation (B) are much worse.** The mean share error is only a little higher than C's, so the large NLL gap comes from the multinomial being too sure of itself. Per-game variation is useful.
- **No model reaches 80% coverage for its main players.** D comes closest (0.68 to 0.78). Counts are discrete, so some under-coverage is expected, and I did not measure how much. The spread is not yet shown to be right.

## Limits

- Exploratory only. No pregame injury report or verified roster is used. The harness cannot test injury or new-starter replacement.
- Model A is a proxy, not the layers-off fallback in the engine.
- D reuses C's concentration. A concentration fitted for D was not tested.
- The OTHER weight (0.02) is a fixed choice and is the same for all models.
- The plan asks for results by position (RB, WR, TE, QB rushing). This harness reports totals only. The by-position breakdown is not done.
- This is not a full-game result. A model that wins here must still be tested inside the simulator, where position filters and lineups change the shares (see the Wilson result in `README.md`).
