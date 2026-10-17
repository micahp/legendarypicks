# FBS baseline ladder - 2026-10-17

Pre-registered before the run: markets passing_yards, rushing_yards; walk-forward week by week; keep rule is a player-game-clustered bootstrap interval for the Brier difference that excludes zero.

## 0. The holdout, and why it is not 2025

| measure | value |
|---|---|
| seasons with ncaaf props | 2026 |
| fixtures with a 2025 date | 0 |
| settled props, all seasons | 64416 |

The plan's holdout was 2025 as the first complete season and 2026 as a separate live forward-recorded test. The first half of that is not available: there is no 2025 NCAAF prop board in this database, so there is no 2025 line and no 2025 result to grade. The holdout is therefore a **week walk-forward within 2026**: every game strictly before the graded week is training data, and the graded week is never in its own fit.

What this costs, stated plainly: a within-season walk-forward cannot separate a model that is right from a model that is right for this season's players. It measures the models against one season's schedule. That is the limitation the keep rule's interval exists to surface, and it is reported rather than hidden.

## 1. The week calendar

| week starting | game dates | count |
|---|---|---|
| 2025-08-23 | 2025-08-23, 2025-08-28, 2025-08-29 | 3 |
| 2025-08-30 | 2025-08-30, 2025-08-31, 2025-09-02, 2025-09-05 | 4 |
| 2025-09-06 | 2025-09-06, 2025-09-07, 2025-09-11, 2025-09-12 | 4 |
| 2025-09-13 | 2025-09-13, 2025-09-14, 2025-09-18, 2025-09-19 | 4 |
| 2025-09-20 | 2025-09-20, 2025-09-21, 2025-09-25, 2025-09-26 | 4 |
| 2025-09-27 | 2025-09-27, 2025-09-28, 2025-10-03 | 3 |
| 2025-10-04 | 2025-10-04, 2025-10-05, 2025-10-08, 2025-10-09, 2025-10-10 | 5 |
| 2025-10-11 | 2025-10-11, 2025-10-12, 2025-10-14, 2025-10-15, 2025-10-16, 2025-10-17 | 6 |
| 2025-10-18 | 2025-10-18, 2025-10-19, 2025-10-21, 2025-10-22, 2025-10-23, 2025-10-24 | 6 |
| 2025-10-25 | 2025-10-25, 2025-10-26, 2025-10-29, 2025-10-30, 2025-10-31 | 5 |
| 2025-11-01 | 2025-11-01, 2025-11-02, 2025-11-05, 2025-11-06, 2025-11-07 | 5 |
| 2025-11-08 | 2025-11-08, 2025-11-09, 2025-11-12, 2025-11-13, 2025-11-14 | 5 |
| 2025-11-15 | 2025-11-15, 2025-11-16, 2025-11-19, 2025-11-20, 2025-11-21 | 5 |
| 2025-11-22 | 2025-11-22, 2025-11-23, 2025-11-25, 2025-11-26, 2025-11-28 | 5 |
| 2025-11-29 | 2025-11-29, 2025-11-30 | 2 |
| 2025-12-06 | 2025-12-06, 2025-12-07 | 2 |
| 2025-12-13 | 2025-12-13 | 1 |
| 2026-08-29 | 2026-08-29, 2026-08-30, 2026-09-03, 2026-09-04 | 4 |
| 2026-09-05 | 2026-09-05, 2026-09-06, 2026-09-07, 2026-09-11 | 4 |
| 2026-09-12 | 2026-09-12, 2026-09-13, 2026-09-17, 2026-09-18 | 4 |
| 2026-09-19 | 2026-09-19, 2026-09-20, 2026-09-24, 2026-09-25 | 4 |
| 2026-09-26 | 2026-09-26, 2026-09-27, 2026-10-02 | 3 |
| 2026-10-03 | 2026-10-03, 2026-10-04 | 2 |

## 2. The item set

An item is a (week, player, game, market) with a settled result, a non-whole-number line, a player with an ESPN id, and a stored log row in that game. The population is measured before any model is fitted, because every model below is graded on it and a model that quietly grades a different population is not a result.

| measure | count |
|---|---|
| props joined to a settled result and a stored log | 45888 |
| distinct markets | 15 |
| distinct players | 924 |
| distinct games | 209 |

| measure | count |
|---|---|
| items | 15988 |
| dropped: not a pre-registered market | 29872 |
| dropped: whole-number line | 0 |
| dropped: no value | 28 |

Items by week:

| week | items | players | games | markets |
|---|---|---|---|---|
| 2026-08-29 | 1014 | 60 | 15 | 2 |
| 2026-09-05 | 3646 | 121 | 35 | 2 |
| 2026-09-12 | 2874 | 133 | 34 | 2 |
| 2026-09-19 | 4000 | 172 | 46 | 2 |
| 2026-09-26 | 4454 | 156 | 34 | 2 |

## 3. Player history

| measure | count |
|---|---|
| players with prior games | 15460 |
| player-games | 81441 |
| seasons | [2025, 2026] |

## 4. The models

All four are functions of the player's prior games, read with a cutoff date. Nothing here reads the graded week.

## 5. Walk-forward grading

Each graded week is scored with models fitted on every game strictly before that week. The P(over) is a normal approximation with a player-specific variance shrunk toward the league variance, floored at 1.0.

| measure | value |
|---|---|
| weeks in the calendar | 5 |
| weeks graded | 4 |
| graded weeks | 2026-09-05, 2026-09-12, 2026-09-19, 2026-09-26 |
| minimum weeks of history before the first graded week | 1 |

The graded window is the last 4 weeks of the season's calendar, subject to every graded week having at least 1 weeks of history behind it. This is a pre-registered floor; the first graded week with fewer weeks behind it would be measuring the absence of history rather than the model.

| model | items | MAE | Brier | log loss |
|---|---|---|---|---|
| season_avg | 14796 | 47.46 | 0.3036 | 0.8292 |
| rolling_5 | 14796 | 49.60 | 0.2971 | 0.8154 |
| marcel | 14796 | 45.96 | 0.2951 | 0.8000 |
| share_adj | 14796 | 57.70 | 0.3548 | 1.0081 |

Per graded week:

| week | season_avg | rolling_5 | marcel | share_adj |
|---|---|---|---|---|
| 2026-09-05 | 3468 / 0.2966 | 3468 / 0.2980 | 3468 / 0.2888 | 3468 / 0.3407 |
| 2026-09-12 | 2874 / 0.3462 | 2874 / 0.3391 | 2874 / 0.3243 | 2874 / 0.3844 |
| 2026-09-19 | 4000 / 0.2812 | 4000 / 0.2892 | 4000 / 0.2882 | 4000 / 0.3202 |
| 2026-09-26 | 4454 / 0.3016 | 4454 / 0.2764 | 4454 / 0.2873 | 4454 / 0.3777 |

Each cell is `items / Brier`. A model whose pooled Brier is better but whose per-week Briers are not consistently better is not a model, and the per-week view is what makes that visible.

## 6. The keep rule

A model is adopted only if its Brier is lower than `season_avg`'s by a player-game-clustered bootstrap interval that excludes zero. The interval is reported, not just the point difference.

| model | shared clusters | Brier difference vs season_avg | clustered 95% interval | verdict |
|---|---|---|---|---|
| rolling_5 | 751 | -0.0039 | [-0.0120, 0.0050] | not kept |
| marcel | 751 | -0.0103 | [-0.0220, 0.0023] | not kept |
| share_adj | 751 | 0.0416 | [0.0230, 0.0598] | not kept |

Control: `season_avg` Brier 0.3036 on 14796 items across 751 clusters.

## 7. The control

| measure | count |
|---|---|
| control items | 14796 |
| control clusters (player-games) | 751 |
| control distinct players | 272 |
| control distinct games | 149 |
| control markets | passing_yards, rushing_yards |
| control weeks | 2026-09-05, 2026-09-12, 2026-09-19, 2026-09-26 |
