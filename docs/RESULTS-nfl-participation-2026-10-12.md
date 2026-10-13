# Results: participation tests (pressure and coverage), 2026-10-12

Both tests were pre-registered before their first run (commit `366d977` for test 1, the definition
and tests of test 2 in commit `2fbf3aa`, before its run). Plan: `docs/PLAN-participation-and-spec-b-2026-10-12.md`.
Both were run against the dev DB (`picks.dev.db`, read-only) with `LP_DB_PATH` set. Neither keep rule was loosened.

## Verdicts

| Test | Feature | Verdict | Why |
|---|---|---|---|
| 1 | `participation_keep`: pressure matchup (sacks count as pressure) | NOT KEPT | pooled 2017-2023 F-B interval is `[-0.0010,+0.0005]`, not entirely below zero; 2024 point `+0.0008` is above zero |
| 2 | `coverage_keep`: man/zone matchup | NOT KEPT | pooled 2019-2023 F-B interval is `[-0.0002,+0.0006]`, not entirely below zero; 2025 point is above zero at full precision (printed `+0.0000`) |

## Test 1: pressure (`--feature participation_keep`)

Command: `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db /root/legendarypicks/backend/venv/bin/python nfl_feature_backtest.py --feature participation_keep`
Runtime 31 seconds, exit 0.

```
participation checks: base rows with no league history before the game (column 0) 0
feature: participation pressure matchup (fit from 2016)
  2017-2023 n=1723 Brier v1 0.2274 B 0.2263 F 0.2260 mkt 0.2092 | F-B -0.0003 [-0.0010,+0.0005] | F-mkt +0.0168 [+0.0124,+0.0214] | B-mkt +0.0171 [+0.0127,+0.0217]
                   margin MAE B 10.401 F 10.385 spread 9.873 | F-B -0.016 [-0.043,+0.012]
  2024      n= 256 Brier v1 0.2210 B 0.2225 F 0.2233 mkt 0.2001 | F-B +0.0008 [-0.0018,+0.0036] | F-mkt +0.0232 [+0.0110,+0.0356] | B-mkt +0.0224 [+0.0098,+0.0351]
                   margin MAE B 10.376 F 10.361 spread 9.648 | F-B -0.015 [-0.111,+0.086]
  2025      n= 255 Brier v1 0.2288 B 0.2296 F 0.2298 mkt 0.2137 | F-B +0.0002 [-0.0019,+0.0025] | F-mkt +0.0161 [+0.0047,+0.0273] | B-mkt +0.0159 [+0.0044,+0.0272]
                   margin MAE B 10.682 F 10.708 spread 9.971 | F-B +0.026 [-0.057,+0.107]
   diagnostic 2017 n=240 F-B +0.0015
   diagnostic 2018 n=239 F-B -0.0000
   diagnostic 2019 n=240 F-B -0.0006
   diagnostic 2020 n=239 F-B -0.0003
   diagnostic 2021 n=255 F-B -0.0016
   diagnostic 2022 n=254 F-B +0.0002
   diagnostic 2023 n=256 F-B -0.0009
   diagnostic 2024 n=256 F-B +0.0008
   diagnostic 2025 n=255 F-B +0.0002
   fitted coef on feature, 2016-2024 fit -14.371 (base proj_margin +0.776)
```

Verdict: NOT KEPT. The pooled interval reaches above zero and the 2024 point is above zero. The fitted
coefficient is negative (the pre-registered expected sign), but the keep rule is about Brier, not sign.

## Test 2: coverage matchup (`--feature coverage_keep`)

Command: `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db /root/legendarypicks/backend/venv/bin/python nfl_feature_backtest.py --feature coverage_keep`
Runtime 33 seconds, exit 0.

```
coverage checks: week-1 rows with column 0 (counted) 0
feature: coverage matchup (fit from 2018)
  2019-2023 n=1244 Brier v1 0.2289 B 0.2284 F 0.2286 mkt 0.2111 | F-B +0.0002 [-0.0002,+0.0006] | F-mkt +0.0175 [+0.0120,+0.0229] | B-mkt +0.0173 [+0.0118,+0.0227]
                   margin MAE B 10.381 F 10.397 spread 9.859 | F-B +0.016 [+0.002,+0.030]
  2024      n= 256 Brier v1 0.2210 B 0.2223 F 0.2223 mkt 0.2001 | F-B -0.0001 [-0.0004,+0.0002] | F-mkt +0.0222 [+0.0096,+0.0350] | B-mkt +0.0222 [+0.0096,+0.0350]
                   margin MAE B 10.373 F 10.367 spread 9.648 | F-B -0.007 [-0.018,+0.005]
  2025      n= 255 Brier v1 0.2288 B 0.2293 F 0.2294 mkt 0.2137 | F-B +0.0000 [-0.0000,+0.0000] | F-mkt +0.0157 [+0.0044,+0.0270] | B-mkt +0.0157 [+0.0044,+0.0269]
                   margin MAE B 10.673 F 10.674 spread 9.971 | F-B +0.000 [-0.000,+0.001]
   diagnostic 2019 n=240 F-B +0.0003
   diagnostic 2020 n=239 F-B +0.0008
   diagnostic 2021 n=255 F-B +0.0000
   diagnostic 2022 n=254 F-B +0.0000
   diagnostic 2023 n=256 F-B -0.0000
   diagnostic 2024 n=256 F-B -0.0001
   diagnostic 2025 n=255 F-B +0.0000
   fitted coef on feature, 2018-2024 fit +0.787 (base proj_margin +0.831)
   keep rule: pooled 2019-2023 F-B +0.0002 [-0.0002,+0.0006] entirely below zero: False; 2024 point -0.0001 not above zero: True; 2025 point +0.0000 not above zero: False
verdict coverage_keep: NOT KEPT
```

Verdict: NOT KEPT. The pooled interval is not entirely below zero, and the 2025 point difference is
above zero at full precision (the code's check `p25 <= 0` is False; the four-decimal print rounds it to `+0.0000`).

Coverage checks, measured:
- The graded rows start at week 2 in every season (`base_rows` has 16 week-2 rows per season 2018 to 2025
  and no week-1 rows). So the week-1 column-0 branch is never reached on graded data; the printed count is 0.
  The branch is exercised only by the hand-built fixture in `backend/test_nfl_participation_features.py`.
- One labelled dropback has null epa and is dropped by the definition: 2019 week 1, `2019_01_PIT_NE`, play 4166,
  zone coverage. No other labelled non-sack dropback has null epa in 2018 to 2025.
- Unlabelled dropbacks (not MAN_COVERAGE or ZONE_COVERAGE) are excluded from the share denominators.
  Labelled non-sack dropbacks with a participation row, per season: 2018 17,510; 2019 17,717; 2020 17,879;
  2021 18,604; 2022 17,979; 2023 19,296; 2024 18,867; 2025 18,528. Of the unlabelled, the NULL
  `defense_man_zone_type` count is 974, 929, 1,010, 1,059, 1,022 for 2018 to 2022 and 0 for 2023 to 2025
  (2023 has 19,360 dropbacks in total, so 64 carry a non-NULL value that is neither label; not broken down further).

## Data table (by season, REG dropbacks, from the plan; measured 2026-10-12)

| Season | pressure flag on sacks | man/zone labelled | man share of labelled | Cover 1 / Cover 3 |
|---|---|---|---|---|
| 2016-2017 | null | 0% | none | none |
| 2018-2022 | null | 88.6 to 89.3% (sacks 0%) | 35.0, 37.2, 34.4, 30.3, 28.8 | about 23-30% / 30-34% |
| 2023 | true | 99.6% (sacks 98.5%) | 41.3 | 32.0 / 18.3 |
| 2024 | true | 99.8% | 48.5 | 36.5 / 17.7 |
| 2025 | true | 99.9% | 31.0 | 22.4 / 27.7 |

Defenders in box (about 6.0) and pass rushers (about 4.25) read the same in all ten seasons.
Team man share, first half vs second half of a season, r = 0.81, 0.72, 0.77, 0.70, 0.65, 0.85, 0.67, 0.62 (2018 to 2025).

## Stored data

Participation is stored as `nfl_hist_participation` (2016 to 2025, one row per play; loaded by
`load_nfl_history.py --source participation`, file rows = stored rows for all 10 seasons, 0 mismatches,
sha256 in `nfl_hist_loads`).


## Step 6: contention, "has this team checked out"

Pre-registered in `a8c3518` (plan) and `a6c1fe2` (code and tests, committed before the run). Definition
as in the plan: P(playoffs) per team from `nfl_sim.run(nfl_sim.inputs(con, s, as_of_week=w - 1), 1000,
k=0.0, seed=s * 100 + w)`, out = P < 0.01 (strict), weeks >= 10 only, column = out_home - out_away, expected
sign negative. Division map checked on every run against `nfl_schedule.div_game` (4,175 REG games, 2010-2025).

Command (single process, dev DB read-only):

```
cd /root/lp-nfl-lock-by-version/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db nice /root/legendarypicks/backend/venv/bin/python nfl_feature_backtest.py --feature contention_keep
```

Measured run: wall clock 10:07, peak resident set 203 MB (`/usr/bin/time -v`), exit 0. Before the run: 2.4 GiB
available, load average 1.9 (swap was fully used, which the run did not change).

Output, verbatim:

```
division map check: 4175 REG games 2010-2025 agree with div_game (0 disagreements, 0 unknown codes)
feature: contention (has this team checked out), fit from 2010
  2011-2023 n=1635 Brier v1 0.2172 B 0.2182 F 0.2177 mkt 0.2059 | F-B -0.0006 [-0.0017,+0.0006] | F-mkt +0.0118 [+0.0077,+0.0159] | B-mkt +0.0123 [+0.0082,+0.0165]
                   margin MAE B 10.558 F 10.562 spread 10.178 | F-B +0.003 [-0.044,+0.051]
  2024      n= 134 Brier v1 0.1987 B 0.2036 F 0.1990 mkt 0.1808 | F-B -0.0046 [-0.0089,-0.0003] | F-mkt +0.0181 [+0.0045,+0.0329] | B-mkt +0.0227 [+0.0090,+0.0367]
                   margin MAE B 9.947 F 9.822 spread 9.414 | F-B -0.125 [-0.312,+0.060]
  2025      n= 137 Brier v1 0.2154 B 0.2180 F 0.2177 mkt 0.2126 | F-B -0.0003 [-0.0045,+0.0043] | F-mkt +0.0051 [-0.0103,+0.0206] | B-mkt +0.0054 [-0.0107,+0.0215]
                   margin MAE B 9.913 F 9.891 spread 9.562 | F-B -0.022 [-0.195,+0.155]
   diagnostic 2010 games wk>=10 126 team-games out 77 games with exactly one out 45 coin flips 0
   diagnostic 2011 games wk>=10 126 team-games out 85 games with exactly one out 57 coin flips 0
   diagnostic 2012 games wk>=10 124 team-games out 78 games with exactly one out 42 coin flips 0
   diagnostic 2013 games wk>=10 123 team-games out 77 games with exactly one out 49 coin flips 0
   diagnostic 2014 games wk>=10 122 team-games out 77 games with exactly one out 47 coin flips 0
   diagnostic 2015 games wk>=10 124 team-games out 75 games with exactly one out 47 coin flips 0
   diagnostic 2016 games wk>=10 123 team-games out 70 games with exactly one out 44 coin flips 0
   diagnostic 2017 games wk>=10 124 team-games out 75 games with exactly one out 51 coin flips 0
   diagnostic 2018 games wk>=10 122 team-games out 83 games with exactly one out 49 coin flips 0
   diagnostic 2019 games wk>=10 121 team-games out 96 games with exactly one out 48 coin flips 0
   diagnostic 2020 games wk>=10 123 team-games out 66 games with exactly one out 48 coin flips 0
   diagnostic 2021 games wk>=10 136 team-games out 62 games with exactly one out 40 coin flips 0
   diagnostic 2022 games wk>=10 135 team-games out 57 games with exactly one out 47 coin flips 0
   diagnostic 2023 games wk>=10 136 team-games out 61 games with exactly one out 49 coin flips 0
   diagnostic 2024 games wk>=10 134 team-games out 85 games with exactly one out 65 coin flips 0
   diagnostic 2025 games wk>=10 137 team-games out 98 games with exactly one out 54 coin flips 0
   fitted coef on feature, 2010-2024 fit -2.160 (base proj_margin +0.761)
   keep rule: pooled 2011-2023 F-B -0.0006 [-0.0017,+0.0006] entirely below zero: False; 2024 point -0.0046 not above zero: True; 2025 point -0.0003 not above zero: True
verdict contention_keep: NOT KEPT
```

Verdict: NOT KEPT. The pooled 2011-2023 interval is not entirely below zero (upper end +0.0006). The 2024
point is -0.0046 and its interval [-0.0089, -0.0003] excludes zero; the rule is pooled, so this does not change
the verdict, and the 2024 result is recorded here as it stands, not as support for the feature.

Measured notes (not part of the rule):
- Coin flips reported by the simulator: 0 in every season 2010-2025. This is the instrument's count; it was
  not checked against a second source.
- Team-games flagged out are a large share of each week 10+ slate (57 to 98 per season out of about 250 team-games).
  Games with exactly one team out are 40 to 65 per season.
- The fitted coefficient on the column is -2.160 (2010-2024 fit), while the base proj_margin coefficient is
  +0.761. A coefficient that size would move margins by about two points for games with one team out, yet margin
  MAE (F-B, 2011-2023) is +0.003. This was not reconciled and was not investigated, per the plan's rule to report
  and stop.
