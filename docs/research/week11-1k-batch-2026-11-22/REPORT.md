# Week 11 1000-seed batch: models against the market

Date: 2026-11-22. Scope: the Sunday slate of 2026 week 11, six portable model packs, 1000 seeds per game and model.

## Result

- 9 games are complete for all models. LV_DEN has v1 and v1.5 only. MIN_SF is still running. CIN_WAS (Monday) is not in this batch.
- No model is close to the market. The smallest error is v1.6: its home win probability is 0.095 from the market on average.
- Every model makes big favorites too weak. ARI_KC, MIA_BUF and NO_CHI miss the spread by 4 to 15 points.
- NO_CHI is the worst game. The market has CHI by 11.5. The models have CHI by -3 to +0.4.
- TEN_DAL total is the worst total. The market is 55.5. Every model is 39 to 42.
- v1.6 and v2 are closest on win probability. They are also the lowest on totals (about 5 points under the line).
- **pbv1 and pbv1-off are the same run.** Their outcomes match seed by seed in all 9 games. Both packs carry reference data `8e1171dc`. The "off" switch does not reach the pack. That run gives no new information.
- **No player props comparison.** The runner did not pass `--with-player-lines`, so the outputs hold no player box scores. See "Player props" below.
- No game is final yet. Grades against the real result come later.

## Inputs

| model | pack sha256 | code commit | reference |
|---|---|---|---|
| v1 | 6286d341 | 58ef3861 | ee4e61c0 |
| v1.5 | 727820b9 | 2eab8a89 | 22d9a584 |
| v1.6 | 6cf1e836 (verified pack) | 1bb3bd50 | a54b8bb6 |
| v2 | 97c4a01e | 8a1d9842 | 13909c65 |
| pbv1 | 77436659 | 8a1d9842 | 8e1171dc |
| pbv1-off | 48cca8b6 | 8a1d9842 | 8e1171dc |

- Seeds 300001 to 301000 for every game and model.
- Market lines: nflverse `nfldata/data/games.csv`, fetched 2026-11-22 18:03 UTC, sha256 `9970d1a2...`. That is at or before kickoff for every game in this report.
- The `nfl_line_snapshots` table was not used. It has no row for PIT_PHI, NYJ_LAC, LV_DEN or MIN_SF.
- Model numbers use every seed with `valid_full_game` true (regulation or overtime). That is 955 to 1000 seeds per run.
- Runner manifests are in `run-manifests/`. Full numbers are in `game_market_comparison.json`. `build_report.py` makes that file.

## Summary by model

pbv1-off is left out. It is equal to pbv1.

| model | games | home win vs market (mean abs) | margin minus spread (mean) | margin minus spread (mean abs) | total minus line (mean) | total minus line (mean abs) |
|---|---|---|---|---|---|---|
| v1 | 10 | 0.158 | -2.50 | 5.99 | +0.47 | 4.24 |
| v1.5 | 10 | 0.168 | -2.59 | 6.10 | +0.36 | 4.30 |
| v1.6 | 9 | 0.095 | -2.62 | 4.05 | -4.60 | 5.45 |
| v2 | 9 | 0.103 | -2.96 | 4.30 | -5.19 | 5.62 |
| pbv1 | 9 | 0.167 | -2.54 | 6.09 | -1.39 | 4.49 |

Margin and spread are for the home team. A negative "margin minus spread" means the model likes the home team less than the market.

## Moneyline: home win probability

Market is the moneyline pair with the vig removed.

| game | spread | total | market home win | v1 | v1.5 | v1.6 | v2 | pbv1 |
|---|---|---|---|---|---|---|---|---|
| ARI_KC | +15.5 | 40.5 | 0.899 | 0.765 | 0.700 | 0.768 | 0.755 | 0.710 |
| BAL_CAR | +2.5 | 44.5 | 0.562 | 0.392 | 0.380 | 0.488 | 0.581 | 0.408 |
| JAX_NYG | -6 | 45.5 | 0.302 | 0.385 | 0.446 | 0.265 | 0.333 | 0.449 |
| LV_DEN | +10.5 | 40.5 | 0.823 | 0.755 | 0.751 | - | - | - |
| MIA_BUF | +16.5 | 45.5 | 0.911 | 0.680 | 0.673 | 0.805 | 0.715 | 0.685 |
| NO_CHI | +11.5 | 47.5 | 0.837 | 0.380 | 0.399 | 0.511 | 0.499 | 0.388 |
| NYJ_LAC | +3 | 43.5 | 0.609 | 0.773 | 0.751 | 0.583 | 0.568 | 0.769 |
| PIT_PHI | -3.5 | 37.5 | 0.364 | 0.510 | 0.534 | 0.408 | 0.355 | 0.478 |
| TB_DET | +3.5 | 48.5 | 0.662 | 0.747 | 0.721 | 0.758 | 0.761 | 0.707 |
| TEN_DAL | +7.5 | 55.5 | 0.752 | 0.799 | 0.791 | 0.737 | 0.699 | 0.776 |

## Spread: mean home margin (share of seeds where the home team covers)

| game | spread | v1 | v1.5 | v1.6 | v2 | pbv1 |
|---|---|---|---|---|---|---|
| ARI_KC | +15.5 | +7.3 (0.20) | +6.3 (0.20) | +7.2 (0.21) | +7.3 (0.23) | +6.4 (0.22) |
| BAL_CAR | +2.5 | -3.3 (0.33) | -3.9 (0.33) | -0.1 (0.42) | +1.9 (0.51) | -2.0 (0.35) |
| JAX_NYG | -6 | -3.4 (0.57) | -2.1 (0.61) | -7.6 (0.43) | -4.9 (0.55) | -2.2 (0.63) |
| LV_DEN | +10.5 | +8.1 (0.40) | +8.4 (0.41) | - | - | - |
| MIA_BUF | +16.5 | +5.1 (0.17) | +5.4 (0.17) | +10.9 (0.32) | +7.4 (0.24) | +6.0 (0.19) |
| NO_CHI | +11.5 | -3.2 (0.08) | -3.2 (0.10) | +0.4 (0.17) | +0.0 (0.17) | -3.3 (0.09) |
| NYJ_LAC | +3 | +8.5 (0.67) | +7.4 (0.64) | +2.4 (0.48) | +2.0 (0.46) | +8.7 (0.68) |
| PIT_PHI | -3.5 | +0.4 (0.62) | +0.8 (0.64) | -2.3 (0.54) | -4.0 (0.47) | -0.9 (0.58) |
| TB_DET | +3.5 | +7.3 (0.64) | +6.6 (0.61) | +8.7 (0.66) | +8.5 (0.67) | +6.6 (0.61) |
| TEN_DAL | +7.5 | +9.1 (0.54) | +9.3 (0.55) | +7.3 (0.49) | +5.6 (0.42) | +8.2 (0.49) |

## Total: mean total points (share of seeds over the line)

| game | line | v1 | v1.5 | v1.6 | v2 | pbv1 |
|---|---|---|---|---|---|---|
| ARI_KC | 40.5 | 48.2 (0.74) | 47.4 (0.71) | 44.3 (0.62) | 42.4 (0.55) | 47.3 (0.70) |
| BAL_CAR | 44.5 | 43.6 (0.45) | 43.6 (0.43) | 37.7 (0.27) | 39.2 (0.30) | 42.6 (0.42) |
| JAX_NYG | 45.5 | 45.0 (0.48) | 45.0 (0.47) | 43.6 (0.42) | 41.3 (0.36) | 43.8 (0.43) |
| LV_DEN | 40.5 | 44.8 (0.62) | 45.0 (0.64) | - | - | - |
| MIA_BUF | 45.5 | 48.8 (0.60) | 48.8 (0.61) | 43.9 (0.44) | 45.4 (0.49) | 48.4 (0.58) |
| NO_CHI | 47.5 | 44.9 (0.41) | 44.0 (0.36) | 41.5 (0.29) | 40.0 (0.24) | 42.8 (0.33) |
| NYJ_LAC | 43.5 | 42.6 (0.46) | 42.3 (0.43) | 34.6 (0.20) | 34.3 (0.20) | 39.9 (0.35) |
| PIT_PHI | 37.5 | 43.5 (0.68) | 43.9 (0.68) | 35.8 (0.42) | 35.8 (0.43) | 41.5 (0.62) |
| TB_DET | 48.5 | 50.7 (0.56) | 50.8 (0.57) | 43.7 (0.34) | 43.9 (0.34) | 48.8 (0.50) |
| TEN_DAL | 55.5 | 41.5 (0.11) | 42.0 (0.12) | 42.0 (0.12) | 39.5 (0.09) | 41.0 (0.11) |

## What to check next

1. **NO_CHI and TEN_DAL.** All five models miss these games the same way. A shared miss points at the game snapshot (rosters, injuries, depth), not at one model. Check those two snapshots first.
2. **Big favorites.** ARI_KC and MIA_BUF are also shrunk toward even in every model. Team strength does not carry through to the margin.
3. **pbv1-off.** Rebuild the pack so the switch changes the reference data, or drop the arm. Today it costs about 15 minutes per game for no new data.
4. **Grade** every run against the final scores when the games settle.

## Player props

The prop table holds about 2,800 to 3,800 player lines per game for this slate. They were not compared. The portable runner writes player box scores only with `--with-player-lines`. This batch did not use it.

To compare player props, the games must run again with that flag. On 4 workers that is about 90 minutes per game for all models, or about 10 to 25 minutes per game for one model. The flag adds player data to each output file. It should not change the game results. That is not checked yet.

## Speed

- Each game took about 90 minutes for all six models on the shared 4-worker runner.
- On one core per model it took most of a day for a game.
- See `run-manifests/` for the stopped, out-of-memory and completed runner passes.
