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

### Forward only: the same map, fitted only on earlier weeks

Leave-one-week-out trains on weeks *after* the held-out week, which a production fit could never do. The same
map fitted only on weeks strictly before the target week, which is all production would have:

| forecast | Brier | log loss | vs raw (clustered 95%) |
|---|---:|---:|---:|
| raw v2 | 0.2771 | 0.7598 | |
| platt | 0.2488 | 0.6904 | +0.02831 +/- 0.01075 |
| isotonic | 0.2497 | 0.6949 | +0.02732 +/- 0.01109 |
| market | 0.2462 | 0.6854 | +0.03086 +/- 0.01186 |

On the 25,390 items a forward map can score, weeks 3 to 5, Platt lands on **0.2488, the same number to four
decimals as the leave-one-week-out fit**. The gain is not an artifact of training on the future. Per market,
forward Platt beats the market on receiving yards (0.2474 against 0.2481) and improves every market except
passing touchdowns, 0.2434 to 0.2449 with the interval spanning zero, where raw v2 was already fine.

The fitted map is stable in shape and nowhere near the identity: slope +0.232 fitted on week 2, +0.193 on
weeks 2 to 3, +0.165 on weeks 2 to 4, with intercepts +0.071, +0.101 and +0.120. A slope near 0.2 means v2's
log-odds need shrinking by roughly a factor of five to be honest, and the estimate moves *away* from 1 as data
accumulates instead of converging on it. That is structural overconfidence, not sampling noise.

Two operational consequences. Week 2's 8,129 items, 24% of the population, have no earlier week to fit on, so
the map cannot be served in the first week of a season; every later week can. And the map cannot be
pre-fitted from prior seasons, because props exist for 2026 only, so it has to accumulate in season.

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

## 4. Discrimination, and whether LP adds anything on top of the price

Brier cannot answer the milestone question on its own: a model that says 0.5 for everything scores a
respectable Brier with no information, and shrinking toward 0.5 improves Brier while losing discrimination.
`measure_nfl_prop_discrimination.py` (new) separates the three terms, out of sample and clustered by
player-game.

| forecast | Brier | reliability | resolution | AUC |
|---|---:|---:|---:|---:|
| v2 raw | 0.2747 | 0.0260 | 0.0016 | 0.5241 |
| market | 0.2460 | 0.0001 | 0.0034 | 0.5619 |

Our discrimination is 0.524 against the market's 0.562, so it is barely above a coin flip. Note also that the
calibration *lowers* AUC, from 0.5241 raw to 0.5181 refit, while raising the Brier: the repair is a shrink
toward 0.5 and it costs ranking power to buy score.

By market, ours beats the market on pass attempts (0.5216 against 0.4882) and passing touchdowns (0.6319
against 0.6303), and loses on receiving yards, receptions, passing yards and pass completions. Two of those
are worse than a coin flip: **passing yards at 0.4755 and pass completions at 0.4450**, which means the model
ranks those players backwards. That is a defect to investigate, not a tuning problem. By position, ours beats
the market on running backs (0.5591 against 0.5517) and loses on quarterbacks (0.4893 against 0.5747),
receivers (0.5101 against 0.5589) and tight ends (0.5334 against 0.5547).

**The increment test.** A forward-only logistic stack of the market's log-odds and ours, fitted on earlier
weeks and scored on the target week, asks whether our number carries anything the price does not. The fitted
coefficient on ours is positive every week and shrinks as data accumulates: +0.151 on week 3, +0.126 on week 4,
+0.109 on week 5, against the market's own +0.828, +0.860 and +0.846.

| forecast, out of sample on 25,390 items | Brier | log loss | AUC |
|---|---:|---:|---:|
| market, raw | 0.2462 | 0.6854 | 0.5608 |
| market, refit | 0.2464 | 0.6859 | 0.5556 |
| ours, refit | 0.2488 | 0.6904 | 0.5181 |
| stack (market + ours) | 0.2457 | 0.6843 | 0.5587 |

Clustered by player-game: log loss, market minus stack, +0.00153 with a 95% interval of [-0.00092, +0.00380];
Brier +0.00070 with [-0.00049, +0.00182]; AUC, stack minus market, +0.00307 with [-0.01668, +0.02288].

Read plainly: **the increment is not established.** Every interval spans zero. The point estimates all point
the right way, which is worth something, but on 2026 weeks 3 to 5 Legendary Picks does not demonstrably know
anything about a player's next performance that the market has not already priced. The market's own
probabilities also refit slightly worse than raw, 0.6859 against 0.6854, which is what a well-calibrated
forecast does when you re-estimate it from noise.

The acceptance test for the next milestone should therefore be this table, not a Brier target: a positive
increment over the market on log loss, with the clustered interval excluding zero, on games the model did not
see. A new player-level feature earns its place by moving the stack's coefficient on ours, not by moving the
standalone Brier.

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

1. Ship the Platt map on the served P(over). Two parameters, no new data, and it takes the served number from
   worse than a coin flip to roughly the market. The forward-only check lands on the same 0.2488, so the gain is
   not an artifact of training on the future. Two constraints: refit it each week on the weeks so far, and serve
   the raw number in week 1, where there is nothing to fit on.
2. Do not feed prior seasons into the point estimate. They hurt MAE monotonically. The current season plus
   regression to the position mean is the best point model measured here, and it beats what the site serves.
3. Do use prior seasons for the probability's denominator and for early-season coverage, since that is where
   they demonstrably help.
4. Refit the aging curve on residuals, not levels, before judging it. The version here should not ship.
5. Re-run the paired ladder after calibration is in, because the Marcel-versus-v2 comparison has an interval
   that spans zero and more weeks of 2026 props will narrow it.
6. Investigate the two anti-discriminative markets. Passing yards at AUC 0.4755 and pass completions at 0.4450
   rank players backwards, which is a defect rather than a tuning problem, and neither is worth publishing
   until it is understood.
7. Judge the next feature by the increment table in section 4. The bar is a positive increment over the market
   on log loss with the clustered interval excluding zero, on games the model did not see, not a lower Brier.

## Reproducing

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
FIT="2013 2014 2015 2016 2017 2018 2019 2020 2021"

python3 calibrate_nfl_prop_probabilities.py --season 2026 --csv /tmp/cal_items.csv
python3 calibrate_nfl_prop_probabilities.py --season 2026 --mode forward --csv /tmp/cal_fwd.csv
python3 marcel_nfl_backtest.py --season 2025 --window 3 --fit-seasons $FIT          # MAE ladder
python3 marcel_nfl_backtest.py --season 2026 --props --window 3 --csv /tmp/m3.csv --fit-seasons $FIT
```

Backfill, one season per call, add `--dry-run` first:

```bash
LP_DB_PATH=... python3 ingest_nfl_weekly_stats.py --year 2013 --all-positions
LP_DB_PATH=... python3 ingest_nfl_player_ages.py
```
