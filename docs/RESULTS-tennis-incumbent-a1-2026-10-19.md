# Tennis incumbent selection, A1: rolling-origin M1 versus M2, per tour, 2026-10-19

- **Status:** Development evidence. This gives CP2 evidence only. Nothing is promoted, merged to `dev`, deployed,
  or written to the lock table. CP4 (prospective) and CP5 (Micah's decision) are untouched.
- **Data status:** 2015 to 2026 was inspected by the earlier replays
  ([`TENNIS-ROLLING-VALIDATION-2026-10-18.md`](TENNIS-ROLLING-VALIDATION-2026-10-18.md)), so no year is an untouched
  holdout. 2026 is partial, to May.
- **Task:** `CLAUDE-TENNIS-A1-2026-10-19.md`. **Branch:** `feat/tennis-track-b-2026-10-18`.
- **Code and records:** research commit `ad582786`. [`research/tennis/rolling/2026-10-19/`](../research/tennis/rolling/2026-10-19/)
  (`a1_per_tour.py`, `a1_per_tour.json`, `render_a1_tables.py`, `A1-TABLES.md`) and
  [`research/tennis/lock-audit/2026-10-19/`](../research/tennis/lock-audit/2026-10-19/) (`lock_audit.py`, `lock_audit.json`).
- **Databases:** read-only. The replay used `backend/data/picks.dev.db`. The lock audit read `backend/data/picks.db`
  (prod) and `picks.dev.db`. Neither file is in the repository.

## Answer

**ATP: the incumbent is M2 on 2000 history.** This is not the version the lock table writes.

**WTA: null.** Neither M1 nor M2 has earned incumbency. M1 stays as the reference by rule 4, which is a default and not a
validation.

| | ATP | WTA |
|---|---|---|
| Matches, 2015 to 2026 | 37,196 | 41,862 |
| M1 Elo Brier, pooled | 0.22475 | 0.21658 |
| M2 on 2000 history minus M1, pooled, match-clustered 95% | −0.00218 [−0.00273, −0.00164] | −0.00032 [−0.00079, +0.00016] |
| Years negative (of 12) | 12 | 9 |
| Clear win over M1 (rule 1) | yes | no |
| **Incumbent** | **M2 on 2000 history** | **M1, by default (rule 4)** |
| Post-warm-up, 2020 to 2026: M2 on 2000 history minus M1 | −0.00212 [−0.00290, −0.00138], 7 of 7 years | −0.00014 [−0.00085, +0.00055], 4 of 7 years |
| M2 as deployed (2020 history) minus M1, pooled | +0.01385 [+0.01243, +0.01527], 4 of 12 years | +0.01905 [+0.01770, +0.02033], 1 of 12 years |
| M2 as deployed, post-warm-up, 2020 to 2026 | +0.00084 [−0.00059, +0.00215], 4 of 7 years | +0.00760 [+0.00624, +0.00904], 1 of 7 years |
| **M2 as deployed, status** | **unvalidated in production** | **unvalidated in production, and worse than M1** |

Three points follow from the table:

- The pooled winner incumbent from 2026-10-18 (M2 on 2000 history) rests on ATP alone. The WTA interval includes zero.
- Even on ATP, the margin is about 0.2 Brier points. The rolling evidence is development data, and the ATP result is small.
- The deployed M2 (2020 history) does not pass rule 1 on either tour. On ATP, after warm-up, it is not clearly different
  from M1. On WTA, it is clearly worse.

## Lock table: what it writes, and the honest state of its rows

- **Writer.** `backend/routers/games/misc.py` stores `candidate.modelVersion` from `backend/tennis_daily_projections.py`
  (`project_day`) on each lock, once per match in the hour before the start. Locks are `INSERT OR IGNORE`, so a row
  is never rewritten.
- **Label and rule history** (commits, times as committed and in UTC):

| Commit | Time (−0500 / UTC) | Label written | Surface term in the winner forecast |
|---|---|---|---|
| `1778f328` | 2026-10-14 11:36 / 16:36 | `tennis-free-daily-v1` | Shanghai (315) and Wuhan (381) only |
| `ae90ca46` | 2026-10-15 18:03 / 23:03 | `tennis-global-surface-elo-blend-v1` | Same as above |
| `396d78d6` | 2026-10-16 15:22 / 20:22 | `tennis-global-surface-elo-blend-v2` | Same as above |
| `ab0080b7` | 2026-10-18 19:42 / 10-19 00:42 | `…-v2` (label unchanged) | Adds ESPN ids 189 and 959, and surfaces for majors by name |
| `ae5cb074` | 2026-10-18 20:00 / 10-19 01:00 | `…-v2` (label unchanged) | Adds Ningbo Open (Hard) to the surface-by-major map |

  The winner formula is the same 50/50 logit average of global and surface Elo, starting 2020-01-01, in every row of
  the table. `1778f328` to `396d78d6` deletes only a SELECT column list (double-fault columns added) and the label line.

- **Which rule wrote each row.** `lock_audit.py` rebuilds the Elo state at the match day, then tests the stored
  probability against global Elo alone and against the blend with each surface. Tolerance 1e-9.

| Database | Label | Rule that reproduces the row | Rows | Status |
|---|---|---|---:|---|
| prod | `tennis-free-daily-v1` | not testable: no player identity stored | 9 | unvalidated, superseded label |
| prod | `tennis-global-surface-elo-blend-v1` | not testable: no player identity stored | 6 | unvalidated, superseded label |
| prod | `tennis-global-surface-elo-blend-v2` | blend, Hard surface, 8 of 8 | 8 | unvalidated, current |
| dev | `tennis-free-daily-v1` | not testable: no player identity stored | 13 | unvalidated, superseded label |
| dev | `tennis-global-surface-elo-blend-v2` | blend, Hard surface, 7 of 8 (one has no identity; see below) | 8 | unvalidated, current |

- **Did any live lock come from an unvalidated model?** Yes. Of the 44 rows (prod 23, dev 21), 15 reproduce the
  deployed formula exactly. The other 29 have no stored player identity, so the row alone cannot show their rule. Their
  only evidence is the code history, which shows the same formula under older labels, and one dev row that carries the
  v2 label early (see below). None of the 44 is validated. The ATP 2000-history version, the only candidate that earned
  status, has no lock rows.
- **The v2 label covers two surface rules.** Through 2026-10-18, every v2 row is on Shanghai or Wuhan, so the
  Shanghai and Wuhan map and the broader map give the same surface. The first row that separates them is prod
  WTA Ningbo (event 963), locked 2026-10-19 09:38:33 UTC. It uses a Hard surface, which only the post-`ae5cb074`
  map produces. Dev has the same pattern (10:56:05 UTC). The label did not change, so the same `v2` now means two
  forecasts. The deploy time of each commit to prod is not in this repository.
- **Dev row without a v2 commit.** Dev has one v2 row dated 2026-10-16 10:56:06 UTC (game 185369, WTA, Wuhan). That is
  before `396d78d6` (2026-10-16 20:22 UTC), and no committed backend code carries the v2 label before that commit.
  The row has no stored player identity, so its rule cannot be checked. Prod holds the same game (185369) labelled v1,
  locked 2026-10-16 10:12:48 UTC, with the same probability. This is recorded as an open item.
- **Frozen locks.** No row was deleted, rewritten or re-labelled. This document records them.
- **The rolling M2 candidate is not the pre-19 rule.** `rolling_origin.py` gives M2 a surface term on every
  main-tour row, which is the post-`ae5cb074` behaviour. The Shanghai and Wuhan rule, which wrote the rows through
  2026-10-18, was not scored, because the Sackmann rows carry no ESPN event id. Both forms are unvalidated, since no test
  passed for either one.

## Method

- **Population.** Completed best-of-three main-tour matches with a recorded surface, from the point-model tour filter
  (`backend/tennis_point_model.py`, `TOUR_FILTER`). Ratings start from 2000-01-01, and matches are scored for 2015 to 2026.
  The counts equal the 2026-10-18 run exactly (37,196 ATP, 41,862 WTA).
- **Rolling origin.** Each match is forecast from matches dated before it. Ratings update after each event-start date,
  so no match informs another on the same date. M1 is global Elo (K 32, start 1500) over surface-carrying rows.
  M2 on 2000 history is the 50/50 logit blend of global and surface Elo over the same history. M2 as deployed uses the
  same formula with history from 2020-01-01 and updates global Elo on every row. Constant 0.5 is the floor.
- **Identical matches.** Every model scores every match. Sides are randomized with the 2026-10-18 seed.
- **Rebuilt forecasts.** `a1_per_tour.py` rebuilds the forecasts (it needs the probabilities, not only the scores) and
  checks the Brier and log-loss arrays against `rolling_origin.py`'s own records. The largest difference is 1.1e-16.
- **Scores.** Brier (primary), log loss, and calibration: the outcome regressed on the forecast logit, giving slope and
  intercept with a match-clustered bootstrap, plus a 10-bin expected calibration error.
- **Intervals.** Paired difference against M1 on identical rows. Match-clustered bootstrap, 1,000 resamples, seed
  `20261018`. Tournament-clustered as a sensitivity.
- **Selection rule.** `research/tennis/rolling/2026-10-18/PROTOCOL.md` was written for both tours pooled. This task asks
  for each tour separately, so I applied the same thresholds within each tour: rule 1 (interval entirely below zero and
  negative in at least 9 of 12 years), rule 2 (lowest pooled Brier among candidates that clearly beat M1), rule 3 (the
  top candidate must clear the runner-up by the same bar, or the simpler model is the incumbent), rule 4 (the reference
  stays if nothing clearly beats it). The candidates and the thresholds are unchanged.
- **Interval seeds.** Each tour has its own bootstrap seed label, so ATP and WTA endpoints can differ from the pooled
  summary in the fifth decimal. For ATP the upper bound is −0.00164 here and −0.00162 in the 2026-10-18 summary. No
  conclusion changes.

## Rolling-origin tables

Generated from `a1_per_tour.json` and `lock_audit.json` by `render_a1_tables.py`, which writes
[`A1-TABLES.md`](../research/tennis/rolling/2026-10-19/A1-TABLES.md). Negative differences favour the candidate.

#### Population per tour (winner target: completed best-of-three main-tour matches with a surface, one forecast per match)

| Year | ATP | WTA |
| --- | ---: | ---: |
| 2015 | 3,845 | 3,987 |
| 2016 | 3,332 | 4,073 |
| 2017 | 3,336 | 4,036 |
| 2018 | 3,475 | 4,027 |
| 2019 | 3,212 | 3,789 |
| 2020 | 1,562 | 1,681 |
| 2021 | 3,269 | 3,583 |
| 2022 | 3,388 | 3,620 |
| 2023 | 3,450 | 3,782 |
| 2024 | 3,570 | 3,893 |
| 2025 | 3,191 | 3,633 |
| 2026 | 1,566 | 1,758 |
| **Total** | **37,196** | **41,862** |

#### ATP: Brier per match, by evaluation year (each year forecast from data before it)

| Model | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled | Log loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M1 Elo (reference) | 0.20925 | 0.21243 | 0.22171 | 0.23061 | 0.23290 | 0.23386 | 0.22734 | 0.22565 | 0.22721 | 0.22753 | 0.22975 | 0.22742 | 0.22475 | 0.64169 |
| M2 on 2000 history | 0.20838 | 0.21064 | 0.21940 | 0.22796 | 0.22901 | 0.23060 | 0.22572 | 0.22306 | 0.22553 | 0.22628 | 0.22706 | 0.22459 | 0.22257 | 0.63606 |
| M2 as deployed (2020 history) | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.24159 | 0.23126 | 0.22737 | 0.22719 | 0.22744 | 0.22739 | 0.22353 | 0.23861 | 0.66922 |
| Constant 0.5 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.69315 |

#### ATP: paired Brier difference against M1 (candidate minus M1; negative is better)

| Candidate | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled, match-clustered 95% | Years negative |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M2 on 2000 history | -0.00087 | -0.00179 | -0.00231 | -0.00266 | -0.00388 | -0.00326 | -0.00162 | -0.00259 | -0.00168 | -0.00125 | -0.00270 | -0.00283 | -0.00218 [-0.00273, -0.00164] | 12 of 12 |
| M2 as deployed (2020 history) | +0.04075 | +0.03757 | +0.02829 | +0.01939 | +0.01710 | +0.00773 | +0.00392 | +0.00172 | -0.00002 | -0.00008 | -0.00236 | -0.00389 | +0.01385 [+0.01243, +0.01527] | 4 of 12 |
| Constant 0.5 | +0.04075 | +0.03757 | +0.02829 | +0.01939 | +0.01710 | +0.01614 | +0.02266 | +0.02435 | +0.02279 | +0.02247 | +0.02025 | +0.02258 | +0.02525 [+0.02337, +0.02712] | 0 of 12 |

#### WTA: Brier per match, by evaluation year (each year forecast from data before it)

| Model | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled | Log loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M1 Elo (reference) | 0.21562 | 0.21860 | 0.21793 | 0.22178 | 0.21768 | 0.21403 | 0.21190 | 0.21494 | 0.21346 | 0.21635 | 0.21929 | 0.21360 | 0.21658 | 0.62244 |
| M2 on 2000 history | 0.21504 | 0.21790 | 0.21736 | 0.22137 | 0.21734 | 0.21236 | 0.21127 | 0.21551 | 0.21372 | 0.21700 | 0.21924 | 0.21172 | 0.21626 | 0.62125 |
| M2 as deployed (2020 history) | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.23894 | 0.22655 | 0.22556 | 0.22000 | 0.21906 | 0.22009 | 0.21128 | 0.23563 | 0.66264 |
| Constant 0.5 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.69315 |

#### WTA: paired Brier difference against M1 (candidate minus M1; negative is better)

| Candidate | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled, match-clustered 95% | Years negative |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M2 on 2000 history | -0.00058 | -0.00070 | -0.00057 | -0.00041 | -0.00034 | -0.00167 | -0.00063 | +0.00056 | +0.00026 | +0.00065 | -0.00005 | -0.00188 | -0.00032 [-0.00079, +0.00016] | 9 of 12 |
| M2 as deployed (2020 history) | +0.03438 | +0.03140 | +0.03207 | +0.02822 | +0.03232 | +0.02491 | +0.01465 | +0.01061 | +0.00654 | +0.00271 | +0.00080 | -0.00232 | +0.01905 [+0.01770, +0.02033] | 1 of 12 |
| Constant 0.5 | +0.03438 | +0.03140 | +0.03207 | +0.02822 | +0.03232 | +0.03597 | +0.03810 | +0.03506 | +0.03654 | +0.03365 | +0.03071 | +0.03640 | +0.03342 [+0.03165, +0.03510] | 0 of 12 |

#### Summary: pooled paired differences against M1, per tour

| Tour | Candidate | Diff | Match-clustered 95% | Tournament-clustered 95% | Years negative | 2020 to 2026 diff, 95%, years negative | 2023 to 2026 diff, 95%, years negative |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ATP | M2 on 2000 history | -0.00218 | [-0.00273, -0.00164] | [-0.00275, -0.00159] | 12 of 12 | -0.00212 [-0.00290, -0.00138], 7 of 7 | -0.00198 [-0.00294, -0.00098], 4 of 4 |
| ATP | M2 as deployed (2020 history) | +0.01385 | [+0.01243, +0.01527] | [+0.01191, +0.01594] | 4 of 12 | +0.00084 [-0.00059, +0.00215], 4 of 7 | -0.00119 [-0.00252, +0.00021], 4 of 4 |
| WTA | M2 on 2000 history | -0.00032 | [-0.00079, +0.00016] | [-0.00081, +0.00019] | 9 of 12 | -0.00014 [-0.00085, +0.00055], 4 of 7 | +0.00000 [-0.00085, +0.00083], 2 of 4 |
| WTA | M2 as deployed (2020 history) | +0.01905 | [+0.01770, +0.02033] | [+0.01705, +0.02121] | 1 of 12 | +0.00760 [+0.00624, +0.00904], 1 of 7 | +0.00261 [+0.00134, +0.00394], 1 of 4 |

#### Calibration of the winner forecasts, per tour (logistic recalibration of the outcome on the forecast logit)

Slope 1 and intercept 0 are perfect calibration. Slope below 1 means the forecasts are too confident.
Intervals are match-clustered bootstrap (1,000 resamples). ECE is 10-bin expected calibration error.

| Tour | Window | Model | Slope [95%] | Intercept [95%] | ECE (10 bins) |
| --- | --- | --- | ---: | ---: | ---: |
| ATP | 2015 to 2026 | M1 Elo | 0.745 [0.721, 0.769] | +0.0102 [-0.0110, +0.0316] | 0.0341 |
| ATP | 2015 to 2026 | M2 on 2000 history | 0.836 [0.808, 0.865] | +0.0102 [-0.0108, +0.0310] | 0.0193 |
| ATP | 2015 to 2026 | M2 as deployed | 1.002 [0.951, 1.055] | +0.0064 [-0.0150, +0.0277] | 0.0034 |
| ATP | 2020 to 2026 | M1 Elo | 0.717 [0.682, 0.750] | +0.0156 [-0.0125, +0.0451] | 0.0387 |
| ATP | 2020 to 2026 | M2 on 2000 history | 0.805 [0.767, 0.844] | +0.0158 [-0.0135, +0.0450] | 0.0246 |
| ATP | 2020 to 2026 | M2 as deployed | 1.002 [0.951, 1.051] | +0.0144 [-0.0148, +0.0449] | 0.0059 |
| ATP | 2023 to 2026 | M1 Elo | 0.714 [0.669, 0.757] | +0.0269 [-0.0117, +0.0641] | 0.0410 |
| ATP | 2023 to 2026 | M2 on 2000 history | 0.802 [0.754, 0.853] | +0.0285 [-0.0090, +0.0654] | 0.0263 |
| ATP | 2023 to 2026 | M2 as deployed | 0.941 [0.880, 1.010] | +0.0268 [-0.0098, +0.0659] | 0.0065 |
| WTA | 2015 to 2026 | M1 Elo | 0.857 [0.834, 0.882] | +0.0031 [-0.0186, +0.0233] | 0.0202 |
| WTA | 2015 to 2026 | M2 on 2000 history | 0.965 [0.938, 0.992] | +0.0033 [-0.0167, +0.0235] | 0.0065 |
| WTA | 2015 to 2026 | M2 as deployed | 1.183 [1.133, 1.235] | +0.0052 [-0.0137, +0.0234] | 0.0104 |
| WTA | 2020 to 2026 | M1 Elo | 0.857 [0.824, 0.889] | +0.0150 [-0.0149, +0.0435] | 0.0221 |
| WTA | 2020 to 2026 | M2 on 2000 history | 0.966 [0.930, 1.003] | +0.0145 [-0.0143, +0.0424] | 0.0080 |
| WTA | 2020 to 2026 | M2 as deployed | 1.183 [1.135, 1.238] | +0.0129 [-0.0140, +0.0408] | 0.0204 |
| WTA | 2023 to 2026 | M1 Elo | 0.842 [0.802, 0.884] | +0.0118 [-0.0258, +0.0491] | 0.0268 |
| WTA | 2023 to 2026 | M2 on 2000 history | 0.945 [0.900, 0.995] | +0.0140 [-0.0217, +0.0515] | 0.0111 |
| WTA | 2023 to 2026 | M2 as deployed | 1.121 [1.062, 1.180] | +0.0097 [-0.0258, +0.0427] | 0.0135 |

#### Lock table: which rule reproduces each locked probability

Each row is one `tennis_model_locks` row. The rule is the one whose probability matches the stored probability to 1e-9, with the Elo state rebuilt from 2020-01-01 up to the match day.

| Database | model_version (label) | Rule that reproduces the row | Rows | First locked_at (UTC) | Last locked_at (UTC) |
| --- | --- | --- | ---: | --- | --- |
| prod | tennis-free-daily-v1 | no player identity stored in the row | 9 | 2026-10-15 06:30:05 | 2026-10-15 18:07:26 |
| prod | tennis-global-surface-elo-blend-v1 | no player identity stored in the row | 6 | 2026-10-16 02:52:33 | 2026-10-16 10:12:48 |
| prod | tennis-global-surface-elo-blend-v2 | blend, Hard surface | 8 | 2026-10-17 08:12:59 | 2026-10-19 11:12:42 |
| dev | tennis-free-daily-v1 | no player identity stored in the row | 13 | 2026-10-15 18:21:44 | 2026-10-16 09:22:02 |
| dev | tennis-global-surface-elo-blend-v2 | blend, Hard surface | 7 | 2026-10-17 07:56:23 | 2026-10-19 10:56:05 |
| dev | tennis-global-surface-elo-blend-v2 | no player identity stored in the row | 1 | 2026-10-16 10:56:06 | 2026-10-16 10:56:06 |

## Verification

- **Anchors pass.** M1 Brier, 2023 to 2026: ATP 0.22802 (n 11,777) and WTA 0.21596 (n 13,066), matching the 2026-10-14
  backtest. The script stops if either fails.
- **Row-for-row cross-check.** The rebuilt Brier and log-loss values match `rolling_origin.py`'s records on every match, to
  1.1e-16, for all four models on both tours.
- **Two runs agree.** `a1_per_tour.py` was run twice, once before and once after the post-warm-up calibration was added.
  The pooled differences and the years-negative counts matched between the two runs.
- **Lock reproduction.** The 15 resolved v2 rows match the blend with Hard surface to 1e-9. The same rows did not match
  global Elo alone, or the blend with Clay or Grass.
- **Read-only.** Both databases were opened with `mode=ro`. Nothing was written to them.

## What I did not do

- No lock row was changed, deleted, re-labelled or added. No database was written.
- Nothing was merged to `dev`, deployed, restarted, or changed in serving.
- No model was refitted. No protocol rule was changed after results were seen.
- No 500 rows were added to any population. The count reconciliation is open (below).
- E2 was not re-evaluated. It stays excluded, as in the 2026-10-18 document.
- Calibration was reported but not used for selection. The protocol does not use it.
- I did not check prod's deployed commit. The repository does not record it.

## Open items

1. **500 coverage.** The population is unchanged, and the ATP `A` level already contains both the 250 and 500 events in the
   Sackmann feed. The 500 work (`ae5cb074`, `745549da`) stores draws and scoreboards, and none of its files is a
   match-table loader. Reconciling ESPN 500 draws with the Sackmann 500 rows is still open, as Micah asked.
2. **Dev row labelled v2 before any v2 commit** (2026-10-16 10:56:06 UTC). The row has no identity, so its rule is untested.
3. **Prod deploy times** for `ab0080b7` and `ae5cb074` are not in this repository. The first prod row that shows the
   broader map is 2026-10-19 09:38:33 UTC.
4. **Deployed M2 rule.** The rolling candidate uses a surface on every row. The live rule before 2026-10-19 used two
   events. Scoring the narrow rule needs an event-to-surface map for the Sackmann rows, which does not exist yet.
5. **Decisions for Micah (CP5).** Whether to keep writing v2 locks, whether to version the surface change, and whether
   the ATP 2000-history version should be pinned as a new prospective version. WTA has no candidate. Nothing has been
   changed.

## Reproduce

```bash
python3 -I research/tennis/rolling/2026-10-19/a1_per_tour.py --db backend/data/picks.dev.db \
  --out research/tennis/rolling/2026-10-19/a1_per_tour.json
python3 -I research/tennis/lock-audit/2026-10-19/lock_audit.py --db prod=backend/data/picks.db \
  --db dev=backend/data/picks.dev.db --out research/tennis/lock-audit/2026-10-19/lock_audit.json
python3 -I research/tennis/rolling/2026-10-19/render_a1_tables.py
```
