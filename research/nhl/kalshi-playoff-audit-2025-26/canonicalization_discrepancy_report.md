# NHL historical canonicalization and feature readiness

The separate modeling DuckDB was read-only throughout. No production database, market join, training run, or official backtest was performed.

## Reconciliation results

- Canonical games: **23,222** across seasons 2008–2025.
- Venue label corrections: **115**. Each game ID, original venue label, NHL canonical venue, source URL, and response hash is in `historical_corrections_v1_c475b9e4b7db7e63.csv`.
- Shot-table winner label corrections: **2**. Both are resolved to the NHL home winner in the correction file.
- Team-log goal-target corrections to NHL records, including shootout-decider handling: **8**.
- Missing-shot game reconciled from NHL records: **1**.
- Tied team-log records classified: **2,140**, by official last period {"REG": 1, "SO": 2139} and classification {"regulation_game_with_team_log_tie_conflict": 1, "shootout_tie_matches_team_log": 2139}. Full game-level outcome and evidence are in `tied_team_log_classification_v1_84364ac00db68b98.csv`.
- Shootout awarded goal is retained in official final score/winner fields and excluded from the team-log goals model targets.

The NHL schedule snapshot response hash and endpoint are carried on each canonical game. The complete cached game-level response evidence is in `official_nhl_schedule_evidence.jsonl`.

## Pregame features

Features are rolling means over up to the prior 10 games, requiring at least five non-missing values. Same-calendar-date games are excluded because final completion ordering is not available in the source logs. History carries across seasons.
Included: 5-on-5 xGF/xGA, score- and venue-adjusted 5-on-5 xG for/against, 5-on-5 shot attempts for/against, all-situation goals for/against, and days since the previous game. For prior games whose team-log goals disagree with official score-derived regulation/OT goals, xG and shot observations are excluded from rolling averages; official goals remain the target/history value.

Temporal checks passed: all declared source games precede the target game date; target game is absent from its own source IDs; and adding extreme current-day/future observations leaves sampled rolling features unchanged.

## Feature coverage and trainable rows

Trainable means both teams have all eight required rolling-stat features and an official binary winner label. It is a feature-readiness count only, not a backtest sample or claim of model performance.

| Season | Canonical games | Complete features | Trainable games |
| ---: | ---: | ---: | ---: |
| 2008 | 1314 | 1233 | 1233 |
| 2009 | 1318 | 1318 | 1318 |
| 2010 | 1318 | 1318 | 1318 |
| 2011 | 1316 | 1311 | 1311 |
| 2012 | 806 | 806 | 806 |
| 2013 | 1323 | 1323 | 1323 |
| 2014 | 1319 | 1314 | 1314 |
| 2015 | 1321 | 1321 | 1321 |
| 2016 | 1317 | 1317 | 1317 |
| 2017 | 1355 | 1350 | 1350 |
| 2018 | 1358 | 1358 | 1358 |
| 2019 | 1212 | 1212 | 1212 |
| 2020 | 952 | 952 | 952 |
| 2021 | 1401 | 1396 | 1396 |
| 2022 | 1400 | 1400 | 1400 |
| 2023 | 1400 | 1400 | 1400 |
| 2024 | 1398 | 1393 | 1393 |
| 2025 | 1394 | 1394 | 1394 |

## Immutable artifacts

- Canonical game table: `canonical_games_v1_7cd2fc9a6e84470c.csv` (SHA-256 `7cd2fc9a6e84470c177b704aa56ba328ad67522698244ce1f182ddcb9e439f52`).
- Pregame feature table: `pregame_rolling_features_v1_62dcceb77085bc59.csv` (SHA-256 `62dcceb77085bc59fcad3ca9a0a981e0e462909cd09815cde98e45b7e9caf458`).
- All corrections: `historical_corrections_v1_c475b9e4b7db7e63.csv` (SHA-256 `c475b9e4b7db7e635d0584c4cf79a9d5423f4690277f2c90aa0288578cc9e771`).
- Tied-game classifications: `tied_team_log_classification_v1_84364ac00db68b98.csv` (SHA-256 `84364ac00db68b988bde00d6bff36efb98b0d7e07e9ced4fb7128675aa016c63`).
- Content-addressed filenames are write-once; rebuilds create a new file if content changes.
