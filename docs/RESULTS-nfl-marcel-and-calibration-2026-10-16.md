# NFL props: does more history help, and what full Marcel is worth

Measured 2026-10-16 on `picks.dev.db` (read-only for every grade), on `scratch/spec-b-rebase`. Three
questions, in the order they were asked: can v2's probabilities be repaired without new data, does a full
Marcel baseline beat Marcel-lite, and does a third season of history buy more than calibration does.

## What was added to the database

| item | rows | space |
|---|---:|---:|
| per-game logs, seasons 2010 to 2023 (`ingest_nfl_weekly_stats.py --year --all-positions`) | 248,485 | +95.9 MB (`player_game_logs` 91.5 to 187.4 MB) |
| birth dates (`ingest_nfl_player_ages.py`, new table `nfl_player_birth_dates`) | 24,854 | +2.8 MB |
| index and freelist growth | | about +35 MB |
| **total** | | **+134 MB** (dev DB 2,816 to 2,950 MB) |

NFL log coverage is now 17 seasons, 2010 to 2026, 292,415 rows. Load provenance for the 14 new seasons is
recorded in `nfl_hist_loads` with the artifact sha256, and `file_rows = stored_rows` for every one of them.
Birth dates resolve for 100% of skill-position player-seasons in every season 2010 to 2025 and 87% in 2026
(in-season rookies are not in the roster artifact yet); 23,707 of 24,854 rows join to a `players` row.
`players` was not altered: the ages live in their own table because an ALTER on a shared table is a change
other sessions did not agree to.

Scope note: the back-seasons were loaded with `--all-positions` so they match the existing 2024 and 2025
rows, which carry defensive and kicking lines. Mixing scopes across seasons would make a later coverage
claim false.

## 1. Calibration is nearly the whole measured gap, and it needs no new data

`calibrate_nfl_prop_probabilities.py`, leave-one-week-out over weeks 2 to 5: the map is fitted on the other
weeks only, so every number is out of sample. 33,519 items on 920 player-games.

| forecast | Brier | log loss | vs raw v2 (clustered 95%) |
|---|---:|---:|---:|
| raw v2 | 0.2747 | 0.7542 | |
| platt, 2 parameters | **0.2488** | 0.6905 | +0.02583 +/- 0.00933 |
| isotonic | 0.2493 | 0.6916 | +0.02543 +/- 0.00971 |
| isotonic, per market | 0.2494 | 0.6994 | +0.02525 +/- 0.00980 |
| market | 0.2460 | 0.6850 | +0.02868 +/- 0.01010 |

A constant 0.5 scores 0.2500. Per market, Platt wins everywhere except passing touchdowns, where raw v2 was
already fine (0.2410) and Platt slightly hurts. Per-market isotonic overfits on the 122-player-game markets
(pass attempts 0.2691, passing touchdowns 0.2569), so pooled Platt is the robust choice.

Murphy decomposition, Brier = reliability - resolution + uncertainty, uncertainty 0.2500:

| forecast | Brier | reliability | resolution |
|---|---:|---:|---:|
| raw v2 | 0.2747 | 0.0260 | 0.0016 |
| platt | 0.2488 | 0.0007 | 0.0019 |
| market | 0.2460 | 0.0001 | 0.0034 |

Read plainly: the entire excess over the floor was miscalibration. Reliability falls 37x; resolution barely
moves and stays about half the market's. The spread shows the same thing: raw v2 runs p10 to p90 of 0.227 to
0.545, Platt runs 0.464 to 0.543, so the repair works by shrinking toward 0.5 rather than by sharpening.
After calibration the model still disagrees with the market by more than 0.05 on 31% of items and hits only
42.5% of those sides. So this makes the number good without making the model better, and what remains
between v2 and the market is an information gap of about 0.003, not a calibration gap.

## 2. Full Marcel: regression pays, extra seasons and aging do not

`marcel_nfl_backtest.py` implements the full recipe: the target season's earlier weeks on weight 5 and
season k back on weight (5 - k), regression to the position mean with K pseudo-games, and an age multiplier,
all fitted on 2013 to 2021 and graded walk-forward on 2025. MAE on the 2,990 player-games every variant can
score:

| configuration | receiving yards | receptions |
|---|---:|---:|
| window 0, no regression (a plain current-season mean) | 19.722 | 1.411 |
| **window 0, regression fitted** | **19.494** | **1.396** |
| window 1 | 19.579 | 1.417 |
| window 2 | 19.780 | 1.436 |
| window 3 | 19.928 | 1.447 |
| window 5 | 20.013 | 1.452 |
| window 3, aging on | 20.446 | 1.512 |
| marcel-lite, what the site serves | 20.163 | 1.442 |
| position mean only | 22.608 | 1.700 |

Every added season makes the point estimate worse, monotonically, from window 0 through window 5. Regression
to the position mean is the one component that pays (19.722 to 19.494, 1.411 to 1.396). The aging curve hurts
badly (19.928 to 20.446, 1.447 to 1.512). Two things also worth noting: marcel-lite's own weighting is worse
than a plain current-season mean, and the best configuration here beats marcel-lite on both stats.

The aging curve as built is crude, a bucket multiplier on the ratio of the cell mean to the position mean
with a 30-game floor, and it is fitted on levels rather than on the residuals of the regressed prediction, so
it conflates age with role and survivorship. It is not evidence that aging does not exist in the NFL. It is
evidence that this version of it should not be shipped.

Full six-stat run at window 3 with aging, against marcel-lite on identical player-games: receiving yards
20.446 against 20.163, receptions 1.512 against 1.442, passing yards 66.652 against 63.395, pass attempts
7.675 against 7.862, completions 5.355 against 5.493. Marcel loses three of five.

## 3. But for the probability, history is worth a lot, and the first season is most of it

Marcel's P(over) is the share of games in the same window that beat the line: the direct analogue of
marcel-lite's `prob_over`, over more games. No fitted distribution, deliberately, so this isolates the
question of whether more history fixes the probability. Graded on 2026 sportsbook props.

| window | items | player-games | mean games behind each number | Brier | market |
|---|---:|---:|---:|---:|---:|
| 0 (current season only) | 14,315 | 349 | 3.4 | 0.3064 | 0.2463 |
| 1 | 31,853 | 832 | 15.4 | 0.2686 | 0.2460 |
| 3 | 32,093 | 842 | 36.0 | 0.2658 | 0.2461 |

Window 0 reproduces marcel-lite (0.3082) to within 0.002 on a near-identical population, which is the control
that says the harness is sound and the difference is the extra seasons. The first prior season is worth
0.0378 and the next two are worth 0.0028 together. History also fixes coverage: a model with prior seasons
can serve weeks 2 and 3, which the live route cannot, so it grades 842 player-games where the live route
grades 354.

## The ladder, paired on identical items

31,843 items on 838 player-games, every forecast scored on the same games, markets, books and lines.

| model | Brier | log loss |
|---|---:|---:|
| market | 0.2461 | 0.6853 |
| **v2 + platt calibration** | **0.2492** | 0.6913 |
| full Marcel, window 3 | 0.2666 | 0.7836 |
| v2, raw | 0.2779 | 0.7618 |
| constant 0.5 | 0.2500 | |

Paired per-item differences, clustered by player-game:

| comparison | difference | clustered 95% |
|---|---:|---:|
| calibration minus raw v2 | +0.02873 | +/- 0.00967 |
| Marcel minus raw v2 | +0.01134 | +/- 0.01193 |
| calibration minus Marcel | +0.01739 | +/- 0.00936 |
| market minus calibration | +0.00308 | +/- 0.00216 |

Read plainly:

1. **Calibration is the biggest single win available and it costs two parameters.** Its interval excludes
   zero. Nothing else measured here comes close per unit of effort.
2. **Multi-season history helps v2 but is not established at this sample.** +0.01134 with the clustered
   interval spanning zero, and no individual market is established either. The direction is consistent with
   the window ladder above, but it is not yet a finding.
3. **Calibration beats history** by 0.01739, and that interval excludes zero. If only one of the two is done
   first, it is calibration.
4. **Marcel's log loss is worse than v2's** (0.7836 against 0.7618) even though its Brier is better. An
   empirical hit rate makes confident wrong calls that log loss punishes harder, so Marcel is not a
   straightforward upgrade on both proper scoring rules.
5. After calibration the market is still ahead by 0.00308 and that interval excludes zero, so the repair
   closes most of the gap and does not close all of it.

## What this says to do

1. Ship the Platt map on the served P(over). Two parameters, fitted on held-out weeks, no new data, and it
   takes the served number from worse than a coin flip to roughly the market.
2. Do not feed prior seasons into the point estimate. They hurt MAE monotonically. The current season plus
   regression to the position mean is the best point model measured here, and it beats what the site serves.
3. Do use prior seasons for the probability's denominator and for early-season coverage, since that is where
   they demonstrably help.
4. Refit the aging curve on residuals, not levels, before judging it. The version here should not ship.
5. Re-run the paired ladder after calibration is in, because the Marcel-versus-v2 comparison has an interval
   that spans zero and more weeks of 2026 props will narrow it.

## Reproducing

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
FIT="2013 2014 2015 2016 2017 2018 2019 2020 2021"

python3 calibrate_nfl_prop_probabilities.py --season 2026 --csv /tmp/cal_items.csv
python3 marcel_nfl_backtest.py --season 2025 --window 3 --fit-seasons $FIT          # MAE ladder
python3 marcel_nfl_backtest.py --season 2026 --props --window 3 --csv /tmp/m3.csv --fit-seasons $FIT
```

Backfill, one season per call, add `--dry-run` first:

```bash
LP_DB_PATH=... python3 ingest_nfl_weekly_stats.py --year 2013 --all-positions
LP_DB_PATH=... python3 ingest_nfl_player_ages.py
```
