# Week 11 1000-seed batch: models against the market

Date: 2026-11-22. Scope: the Sunday slate of 2026 week 11, six portable model packs, 1000 seeds per game and model. No grading against final scores in this report.

## Result

- **The batch is not valid as a forecast.** Every game snapshot used the nflverse depth chart captured on 2026-10-22, a month before these games. 6 of 22 starting QBs do not match the QB the market priced.
- **All 66 runs finished** (11 games x 6 models). None failed.
- **Box scores exist for 9 runs only:** LV_DEN v2, pbv1, pbv1-off and all 6 MIN_SF runs. The other 57 ran without `--with-player-lines`, which was off by default. It is now on by default in every model runner.
- **Player props:** the models are far from the market. The mean gap in P(over) is 0.21 to 0.29 per run. Part of the gap is players with a line who are not on the stale sim roster (Mendoza, Cousins, Jennings, Allen, Juszczyk).
- **Game lines:** no model is close to the market. v1.6 is the closest on win probability (mean gap 0.102). Every model makes big favorites too weak.
- **pbv1 and pbv1-off are the same run.** Outcomes match seed by seed in all 11 games. Both packs carry reference data `8e1171dc`.
- **Fixed since the batch** (merged to dev at `b7447a06`): correct snapshots now exist for all 11 games. See "Snapshots for the rerun".

## Stale rosters

Every snapshot's roster `snapshot_at` is 2026-10-22 (source `nflverse_depth_charts_capture`). The snapshots were built on 2026-11-21, but the roster inside was a month old. The builder read a local depth chart archive last updated on 10-29. The 90-minute cutoff job, which saves current snapshots, had crashed every 5 minutes since 2026-11-16, because its database was removed from the fast host.

| team | snapshot QB1 (2026-10-22) | market QB | match |
|---|---|---|---|
| ARI | Jacoby Brissett | Carson Beck, Josh Johnson | no |
| BAL | Lamar Jackson | Jacoby Brissett | no |
| LV | Kirk Cousins | Fernando Mendoza | no |
| MIA | Malik Willis | Kyle McCord | no |
| MIN | Kyler Murray (the sim used Carson Wentz) | Kirk Cousins | no |
| PHI | Tanner McKee | Joe Milton III | no |
| other 16 teams | | | yes |

The QBs match in NO_CHI and TEN_DAL, so the stale QB does not explain the two biggest game-line misses.

## Snapshots for the rerun

- The 90-minute cutoff job runs again. It reads the published nflverse schedule and needs no database.
- Every week 11 game played so far has a cutoff snapshot with the depth chart captured before its cutoff. They were backfilled, so injury and roster status from nflverse are labelled `FETCHED_AFTER_CUTOFF`.
- The run-ready files are in `docs/research/model-snapshots-2026/week-11/`. They use RotoWire injuries published before each cutoff. A v1.6 test run on LV_DEN used Mendoza and Nix at QB.
- `docs/research/SNAPSHOT-INDEX-2026.md` names the file to run on for every game.
- A snapshot build now refuses a depth chart more than 24 hours older than its cutoff, and refuses a QB1 who is not the QB priced in the props.
- MIN_SF's cutoff snapshot is due at 23:50 UTC on 2026-11-22. CIN_WAS's is due at 23:45 UTC on 2026-11-23.

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
- Game lines: nflverse `nfldata/data/games.csv`, fetched 2026-11-22 18:03 UTC, sha256 `9970d1a2...`, at or before every kickoff.
- Player props: `props` in `picks.dev.db`, rows captured before kickoff. The line is the median over-line across books. The market P(over) is the mean no-vig over probability across books that quote both sides at that line. Players join on `players.nfl_gsis_id`.
- Model numbers use seeds with `valid_full_game` true (regulation or overtime). A player with no stats in a seed counts as 0.
- Files: `game_market_comparison.json` (`build_report.py`), `props_comparison.json` (`props_compare.py`), runner manifests in `run-manifests/`.

## Player props

The gap is sim P(over) minus market P(over).

| game | model | props | mean P(over) gap | mean abs gap | mean abs gap, players in sim only | players with a line but not in sim |
|---|---|---|---|---|---|---|
| LV_DEN | pbv1 | 86 | -0.144 | 0.289 | 0.262 | Fernando Mendoza |
| LV_DEN | pbv1-off | 86 | -0.144 | 0.289 | 0.262 | Fernando Mendoza |
| LV_DEN | v2 | 86 | -0.140 | 0.279 | 0.251 | Fernando Mendoza |
| MIN_SF | pbv1 | 82 | -0.178 | 0.289 | 0.241 | Jauan Jennings, Keenan Allen, Kirk Cousins, Kyle Juszczyk |
| MIN_SF | pbv1-off | 82 | -0.178 | 0.289 | 0.241 | Jauan Jennings, Keenan Allen, Kirk Cousins, Kyle Juszczyk |
| MIN_SF | v1 | 82 | -0.173 | 0.292 | 0.244 | Jauan Jennings, Keenan Allen, Kirk Cousins, Kyle Juszczyk |
| MIN_SF | v1.5 | 82 | -0.173 | 0.291 | 0.242 | Jauan Jennings, Keenan Allen, Kirk Cousins, Kyle Juszczyk |
| MIN_SF | v1.6 | 82 | -0.126 | 0.207 | 0.137 | Jauan Jennings, Keenan Allen, Kirk Cousins, Kyle Juszczyk |
| MIN_SF | v2 | 82 | -0.151 | 0.272 | 0.219 | Jauan Jennings, Keenan Allen, Kirk Cousins, Kyle Juszczyk |

MIN_SF by market group, players in the sim only:

| model | market group | props | mean P(over) gap | mean abs gap |
|---|---|---|---|---|
| v1 | receiving | 27 | -0.154 | 0.299 |
| v1 | rushing | 11 | -0.131 | 0.234 |
| v1 | passing | 3 | +0.254 | 0.254 |
| v1 | touchdowns | 16 | -0.074 | 0.165 |
| v1 | interceptions | 2 | +0.105 | 0.105 |
| v1.5 | receiving | 27 | -0.152 | 0.298 |
| v1.5 | rushing | 11 | -0.132 | 0.226 |
| v1.5 | passing | 3 | +0.256 | 0.256 |
| v1.5 | touchdowns | 16 | -0.083 | 0.161 |
| v1.5 | interceptions | 2 | +0.137 | 0.137 |
| v1.6 | receiving | 27 | -0.045 | 0.140 |
| v1.6 | rushing | 11 | -0.041 | 0.188 |
| v1.6 | passing | 3 | +0.217 | 0.217 |
| v1.6 | touchdowns | 16 | -0.061 | 0.069 |
| v1.6 | interceptions | 2 | -0.106 | 0.106 |
| v2 | receiving | 27 | -0.089 | 0.254 |
| v2 | rushing | 11 | -0.090 | 0.317 |
| v2 | passing | 3 | +0.217 | 0.217 |
| v2 | touchdowns | 16 | -0.104 | 0.114 |
| v2 | interceptions | 2 | -0.011 | 0.011 |
| pbv1 | receiving | 27 | -0.161 | 0.306 |
| pbv1 | rushing | 11 | -0.128 | 0.229 |
| pbv1 | passing | 3 | +0.211 | 0.211 |
| pbv1 | touchdowns | 16 | -0.078 | 0.157 |
| pbv1 | interceptions | 2 | +0.120 | 0.120 |

Markets the box scores do not hold were skipped: kicking, field goals, extra points, sacks, and longest plays.

## Game lines: summary by model

pbv1-off is left out. It is equal to pbv1.

| model | games | home win vs market (mean abs) | margin minus spread (mean) | margin minus spread (mean abs) | total minus line (mean) | total minus line (mean abs) |
|---|---|---|---|---|---|---|
| v1 | 11 | 0.147 | -2.42 | 5.59 | +0.77 | 4.20 |
| v1.5 | 11 | 0.159 | -2.59 | 5.78 | +0.63 | 4.21 |
| v1.6 | 11 | 0.102 | -2.46 | 4.17 | -4.06 | 4.76 |
| v2 | 11 | 0.110 | -2.76 | 4.38 | -4.63 | 4.98 |
| pbv1 | 11 | 0.151 | -2.42 | 5.32 | -0.48 | 4.33 |

Margin and spread are for the home team. A negative "margin minus spread" means the model likes the home team less than the market.

## Moneyline: home win probability

Market is the moneyline pair with the vig removed.

| game | spread | total | market home win | v1 | v1.5 | v1.6 | v2 | pbv1 |
|---|---|---|---|---|---|---|---|---|
| ARI_KC | +15.5 | 40.5 | 0.899 | 0.765 | 0.700 | 0.768 | 0.755 | 0.710 |
| BAL_CAR | +2.5 | 44.5 | 0.562 | 0.392 | 0.380 | 0.488 | 0.581 | 0.408 |
| JAX_NYG | -6 | 45.5 | 0.302 | 0.385 | 0.446 | 0.265 | 0.333 | 0.449 |
| LV_DEN | +10.5 | 40.5 | 0.823 | 0.755 | 0.751 | 0.653 | 0.623 | 0.729 |
| MIA_BUF | +16.5 | 45.5 | 0.911 | 0.680 | 0.673 | 0.805 | 0.715 | 0.685 |
| MIN_SF | +3.5 | 46.5 | 0.613 | 0.576 | 0.542 | 0.711 | 0.689 | 0.546 |
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
| LV_DEN | +10.5 | +8.1 (0.40) | +8.4 (0.41) | +4.0 (0.28) | +3.9 (0.29) | +8.5 (0.43) |
| MIA_BUF | +16.5 | +5.1 (0.17) | +5.4 (0.17) | +10.9 (0.32) | +7.4 (0.24) | +6.0 (0.19) |
| MIN_SF | +3.5 | +1.9 (0.46) | +0.9 (0.42) | +6.5 (0.61) | +6.3 (0.58) | +1.8 (0.43) |
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
| LV_DEN | 40.5 | 44.8 (0.62) | 45.0 (0.64) | 40.4 (0.51) | 40.5 (0.49) | 45.8 (0.67) |
| MIA_BUF | 45.5 | 48.8 (0.60) | 48.8 (0.61) | 43.9 (0.44) | 45.4 (0.49) | 48.4 (0.58) |
| MIN_SF | 46.5 | 50.3 (0.59) | 49.8 (0.59) | 43.3 (0.39) | 42.3 (0.35) | 48.4 (0.56) |
| NO_CHI | 47.5 | 44.9 (0.41) | 44.0 (0.36) | 41.5 (0.29) | 40.0 (0.24) | 42.8 (0.33) |
| NYJ_LAC | 43.5 | 42.6 (0.46) | 42.3 (0.43) | 34.6 (0.20) | 34.3 (0.20) | 39.9 (0.35) |
| PIT_PHI | 37.5 | 43.5 (0.68) | 43.9 (0.68) | 35.8 (0.42) | 35.8 (0.43) | 41.5 (0.62) |
| TB_DET | 48.5 | 50.7 (0.56) | 50.8 (0.57) | 43.7 (0.34) | 43.9 (0.34) | 48.8 (0.50) |
| TEN_DAL | 55.5 | 41.5 (0.11) | 42.0 (0.12) | 42.0 (0.12) | 39.5 (0.09) | 41.0 (0.11) |

## Next

1. Run week 11 again on `docs/research/model-snapshots-2026/week-11/`. Box scores are on by default.
2. Drop pbv1-off, or rebuild it so the switch changes the reference data.
3. Grade against final scores in a separate step.

## Speed

- Each game took about 90 minutes for all six models on the shared 4-worker runner.
- On one core per model, a game took most of a day.
