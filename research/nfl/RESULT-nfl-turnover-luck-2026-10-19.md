# RESULT: NFL turnover-luck feature, 2026-10-19

## Verdict

**Both placements fail the registered keep rule. Nothing is kept, nothing is adopted.**

| Placement | Baseline | Pooled 2011-2023 F−B [95%] | 2024 point | 2025 point | Kept |
|---|---|---|---|---|---|
| `turnover_luck` | stack B | −0.000186 [−0.000703, +0.000329] | +0.000518 | +0.000753 | **no** |
| `elo_plus_turnover` | Elo stack | +0.000048 [−0.000300, +0.000400] | +0.000305 | +0.000305 | **no** |

The registered rule requires the pooled 2011-2023 interval of Brier(F) − Brier(B) to lie
entirely below zero **and** the 2024 and 2025 point differences to be not above zero. Both
placements fail the first condition (both pooled upper bounds are positive) and both fail the
second (both holdout points are positive). Neither is kept. The pooled
`turnover_luck` point is slightly negative (−0.000186) and its margin MAE improves by 0.010,
but the interval includes zero and both holdout points are positive; that is not a pass under
the registered rule, and it is not presented as one.

## Registration and what was run

The registration is `research/nfl/PREREG-nfl-turnover-luck-2026-10-19.md`, committed before
this run:

- prereg commit `b6b24a9820bfb552212c3128509af0b5534ad9f4`
- prereg sha256 `502ee5e66ce5aaf75a19b4006af0a41ffe41488fa06a6a6bbf9ee9f0ad24ca74`
- base `origin/dev` `d007e540609e7ca241b82d3416499addf6a17603`
- branch `research/nfl-turnover-luck-2026-10-19`

No re-registration. `nfl_feature_backtest.py`, `nfl_metrics.py`, `nfl_elo_replica.py` and
`nfl_proe_feature.py` are unchanged. Frozen v1 is untouched: `half_life 6.0`, `cap 14.0`,
`cap_points None`, `sigma 13.295`. The only new code is `backend/nfl_turnover_run.py`, which
implements the registered column and calls the unchanged `fb.stack`, `fb.graded`, `fb.GROUPS`
and the shared keep rule.

Registered column, exactly as run:

- One column, `turnover_worthy_diff`, on the feature `turnover_luck`.
- Per team-game from `nfl_pbp`, 2010-2025, over the offensive play universe
  `qb_dropback = 1 OR rush_attempt = 1`:
  - `n` = number of those plays.
  - `s` = `SUM(interception = 1) + 0.5 * SUM(fumble = 1 AND interception = 0)`.
  - `fumble_lost` is **not used** in the column; the fixed 0.5 expected recovery replaces the
    actual recovery outcome, so the column measures turnover-worthy behaviour, not recovery
    luck.
  - A play with both `interception = 1` and `fumble = 1` is treated as an interception only;
    the fumble is on the return, not an offensive fumble. There are 93 such plays in
    2010-2025 (2-11 per season), 0.9% of the 10,162 offensive fumbles. This is a small, stated
    approximation.
- Rate before a game in season S, week w, cutoff `(S, w, "")`:
  - window = the team's last 8 team-games strictly before the cutoff, ordered by
    `(season, week, game_id)`, crossing season boundaries and including prior-season playoff
    games, as in the PROE registration;
  - league = `sum(s) / sum(n)` over every team-game of the **same season S** strictly before
    the cutoff;
  - rate = `(sum_window(s) + 200 * league) / (sum_window(n) + 200)`;
  - column = `rate(home) - rate(away)`.
- No expected sign; the keep rule needs none.

Two placements only:

1. `turnover_luck` alone on frozen v1, judged against stack B.
2. `elo_plus_turnover` on top of the Elo stack (`elo_diff`), judged against the Elo stack.

## Baselines reproduced before scoring

Both judged baselines reproduce the published numbers on the harness's own groups, matched-game,
to four decimals:

| Baseline | 2011-2023 (n 3,158) | 2024 (n 256) | 2025 (n 255) | Published |
|---|---|---|---|---|
| Stack B | 0.222892 | 0.222297 | 0.229221 | 0.2229 / 0.2223 / 0.2292 |
| Frozen v1 | 0.223123 | 0.220971 | 0.228811 | 0.2231 / 0.2210 / 0.2288 |
| Elo stack | 0.219659 | 0.214451 | 0.225512 | 0.2197 / 0.2145 / 0.2255 |
| Closing market | 0.210415 | 0.200114 | 0.213697 | 0.2104 / 0.2001 / 0.2137 |

Sources: `docs/RESULTS-nfl-features-vs-market-2026-10-11.md` and
`docs/RESULTS-nfl-elo-and-era-2026-10-13.md`. The runner aborts on a baseline mismatch; it did
not abort.

## Population

Base rows: 3,920 across 2010-2025, weeks 2-18. 2010 (240 rows) is training only. Scored
seasons 2011-2025: 3,680 rows.

| Group | Seasons | Total rows | Ties | No market | No spread | Graded | Weeks |
|---|---|---|---|---|---|---|---|
| 2011-2023 | 2011-2023 | 3,168 | 9 | 1 | 0 | 3,158 | 2-18 |
| 2024 | 2024 | 256 | 0 | 0 | 0 | 256 | 2-18 |
| 2025 | 2025 | 256 | 1 | 0 | 0 | 255 | 2-18 |

Per-season graded counts: 2011 240, 2012 239, 2013 239, 2014 239, 2015 240, 2016 238,
2017 240, 2018 239, 2019 240, 2020 239, 2021 255, 2022 254, 2023 256, 2024 256, 2025 255.

Exclusions, counted not hidden:

- 10 ties (`outcome is None`): nine in 2011-2023, one in 2025, none in 2024. They are listed in
  `forecasts.csv` with `exclusion = tie`; the shared stack's margin fit includes ties, the
  scoring set does not.
- 1 no-market game: `2017_04_CHI_GB` (2017 week 4, GB at CHI, spread 7.5, no moneyline).
  Excluded from grading; no probability is imputed.
- 0 no-spread games.

## Data facts, including 2026

- `interception`, `fumble` and `fumble_lost` are populated for 2010-2025.
- **2026 is not usable and is not used.** All 16,212 2026 plays have `fumble` NULL and
  `fumble_lost` NULL (`interception` is present; 487 plays have no interception value, which is
  normal for non-pass plays). The feature is undefined for 2026; it is not imputed, not
  backfilled, and the 92 completed 2026 games are not part of this test. The harness's scored
  seasons already stop at 2025.
- Offensive fumbles 2010-2025: 10,162; offensive fumbles lost: 4,658; observed offensive
  fumble-recovery rate 45.84%. The 0.5 in the column is the fixed coin-flip expectation, not a
  fitted value; it is close to the observed rate by construction, and the small gap is why the
  column removes most of the recovery luck.
- The feature covers all 3,920 base rows (no missing values). Its range is −0.02428 to
  +0.02564, mean +0.000035. The small mean is expected for a home-minus-away column.

## Results: `turnover_luck` against stack B

Registered interval: `nfl_metrics.bootstrap_mean_diff_ci`, paired games (no block key), 5,000
resamples, seed 20261009, alpha 0.05. The clustered interval in the table is secondary and is
not part of the verdict.

| Group | n | Brier B | Brier F | F−B [95% registered] | F−B [95% clustered, secondary] | Margin MAE B | Margin MAE F | F−B margin |
|---|---|---|---|---|---|---|---|---|
| 2011-2023 | 3,158 | 0.222892 | 0.222706 | −0.000186 [−0.000703, +0.000329] | −0.000186 [−0.000727, +0.000320], 211 blocks | 10.511 | 10.500 | −0.0105 [−0.0304, +0.0089] |
| 2024 | 256 | 0.222297 | 0.222814 | +0.000518 [−0.001037, +0.002079] | +0.000518 [−0.000590, +0.001699], 17 blocks | 10.373 | 10.350 | −0.0237 [−0.0794, +0.0338] |
| 2025 | 255 | 0.229221 | 0.229974 | +0.000753 [−0.000529, +0.002114] | +0.000753 [−0.000302, +0.001877], 17 blocks | 10.671 | 10.696 | +0.0250 [−0.0232, +0.0758] |

Gap to market (Brier; benchmark only, not a keep condition; the market's own Brier is
0.2104 / 0.2001 / 0.2137):

| Group | F − market | B − market |
|---|---|---|
| 2011-2023 | +0.012291 [+0.009251, +0.015516] | +0.012477 [+0.009477, +0.015682] |
| 2024 | +0.022700 [+0.009982, +0.035388] | +0.022183 [+0.009557, +0.034887] |
| 2025 | +0.016277 [+0.005186, +0.027361] | +0.015524 [+0.004274, +0.026753] |

The feature closes 0.000186 of the pooled +0.012477 market gap — about 1.5% of it. That is
inside noise, and it does not transfer to either holdout.

## Results: `elo_plus_turnover` against the Elo stack

Same registered interval. The baseline is the Elo stack, not stack B.

| Group | n | Brier B | Brier F | F−B [95% registered] | F−B [95% clustered, secondary] | Margin MAE B | Margin MAE F | F−B margin |
|---|---|---|---|---|---|---|---|---|
| 2011-2023 | 3,158 | 0.219659 | 0.219707 | +0.000048 [−0.000300, +0.000400] | +0.000048 [−0.000302, +0.000376], 211 blocks | 10.399 | 10.393 | −0.0062 [−0.0199, +0.0076] |
| 2024 | 256 | 0.214451 | 0.214756 | +0.000305 [−0.000430, +0.001043] | +0.000305 [−0.000236, +0.000867], 17 blocks | 10.150 | 10.147 | −0.0033 [−0.0311, +0.0251] |
| 2025 | 255 | 0.225512 | 0.225816 | +0.000305 [−0.000264, +0.000900] | +0.000305 [−0.000144, +0.000771], 17 blocks | 10.501 | 10.504 | +0.0023 [−0.0200, +0.0257] |

Gap to market (Brier; benchmark only):

| Group | F − market | B − market |
|---|---|---|
| 2011-2023 | +0.009292 [+0.006331, +0.012346] | +0.009244 [+0.006332, +0.012308] |
| 2024 | +0.014642 [+0.003053, +0.026336] | +0.014336 [+0.002848, +0.026048] |
| 2025 | +0.012120 [+0.002080, +0.021958] | +0.011815 [+0.001720, +0.021830] |

On top of Elo the column is flat: +0.000048 pooled, +0.000305 in both holdouts, all intervals
spanning zero. Elo already carries what little team-level turnover signal is usable; the
turnover-worthy column adds nothing and costs a little margin MAE.

## Keep rule, applied exactly

| Placement | Pooled upper bound < 0? | 2024 point ≤ 0? | 2025 point ≤ 0? | Kept |
|---|---|---|---|---|
| `turnover_luck` | no: +0.000329 | **no: +0.000518** | **no: +0.000753** | **no** |
| `elo_plus_turnover` | no: +0.000400 | **no: +0.000305** | **no: +0.000305** | **no** |

Both fail. The pooled interval is not entirely below zero for either placement, and both
holdout points are above zero. There is no kept placement, so no stop for direction is
required. Nothing is adopted; no gate, threshold, serving, scheduler or prod change was made;
frozen v1 is untouched.

## Per-season breakdown (Brier F − B, five decimals)

| Season | n | `turnover_luck` | `elo_plus_turnover` |
|---|---|---|---|
| 2011 | 240 | +0.00057 | +0.00105 |
| 2012 | 239 | +0.00009 | +0.00018 |
| 2013 | 239 | +0.00013 | −0.00000 |
| 2014 | 239 | −0.00062 | +0.00000 |
| 2015 | 240 | −0.00001 | −0.00005 |
| 2016 | 238 | −0.00109 | −0.00045 |
| 2017 | 240 | −0.00039 | −0.00018 |
| 2018 | 239 | −0.00182 | −0.00110 |
| 2019 | 240 | −0.00052 | −0.00004 |
| 2020 | 239 | +0.00148 | +0.00114 |
| 2021 | 255 | +0.00033 | +0.00029 |
| 2022 | 254 | −0.00098 | −0.00051 |
| 2023 | 256 | +0.00038 | +0.00028 |
| 2024 | 256 | +0.00052 | +0.00031 |
| 2025 | 255 | +0.00075 | +0.00030 |

Both placements are negative in 7 of 15 seasons and positive in 8. The largest gain for both is
2018 (`turnover_luck` −0.00182, `elo_plus_turnover` −0.00110); the largest loss is 2020
(+0.00148 / +0.00114). The sign is not stable, and the pooled point is inside noise. The two
holdouts are both positive for both placements.

## Secondary diagnostics (not part of the verdict)

Log loss, paired games, 5,000 resamples, seed 20261009; secondary only:

| Placement | Group | Log loss B | Log loss F | F−B [95%] |
|---|---|---|---|---|
| `turnover_luck` | 2011-2023 | 0.636179 | 0.635731 | −0.000448 [−0.001552, +0.000656] |
| `turnover_luck` | 2024 | 0.635194 | 0.636383 | +0.001189 [−0.002163, +0.004555] |
| `turnover_luck` | 2025 | 0.649317 | 0.651358 | +0.002041 [−0.000795, +0.005101] |
| `elo_plus_turnover` | 2011-2023 | 0.629005 | 0.629061 | +0.000057 [−0.000693, +0.000807] |
| `elo_plus_turnover` | 2024 | 0.617870 | 0.618610 | +0.000740 [−0.000859, +0.002347] |
| `elo_plus_turnover` | 2025 | 0.641185 | 0.642046 | +0.000862 [−0.000407, +0.002189] |

The log-loss reading agrees with Brier: a small pooled improvement for `turnover_luck` that is
inside noise, a small worsening in both holdouts, and a flat-to-slightly-worse Elo placement.
It is not a second chance for the feature.

Clustered interval (secondary): `week_block_bootstrap_mean_diff`, copied from the history-window
runner, block key `(season, Monday gameday week)`, 2,000 resamples, seed 20261019, game-count
weighted. It resamples week blocks, not games. It agrees with the registered game-level interval
to four decimals; the registered interval remains the verdict interval.

## What was and was not tested

Tested: the one registered turnover-worthy column (interceptions plus 0.5 times offensive
fumbles), the registered K=200 shrink, the last-8-team-game window crossing season boundaries,
the same-season league mean strictly before the game, and the home-minus-away column; alone on
frozen v1 against stack B, and on top of `elo_diff` against the Elo stack. Seasons 2011-2023
pooled, 2024, 2025; weeks 2-18; REG games; ties excluded and counted. Brier, the registered
paired interval, log loss as a secondary diagnostic, margin MAE, the market gap as a benchmark,
and per-season breakdowns.

Not tested: defensive takeaways (the column is the team's own offensive turnover-worthy rate,
not its defense's forced turnovers); actual-recovery turnovers as a separate column; other
windows (4, 12, 16 team-games); other shrink weights (100, 400); other expected-recovery values
(0.4, 0.6); a turnover-differential column; QB- or player-specific turnovers; playoff games as a
scored population; week 1; 2010 as a scored season; any gate, threshold, serving, scheduler or
prod change; any refit of frozen v1; any re-registration after the prereg commit.

Limits: this is the seventh and eighth test on seasons earlier work already used. 2025 has now
been looked at by six prior tests and is **not** a clean holdout; 2024 is also reused. The
result is weaker evidence than the first feature test, and no placement passes even on this
reused evidence. 2026 cannot be tested with the current data because `fumble` and `fumble_lost`
are NULL for every 2026 play; the 92 completed 2026 games are not used, not imputed and not
counted. A future turnover test with a different window, shrink or defensive column would be a
new registration, not an amendment to this one.

## Reproduction

```
cd /root/lp-nfl-turnover/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_feature_backtest.py --feature base
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_turnover_run.py
```

The DB is opened `mode=ro`; nothing is written to it. The first command reproduces stack B and
frozen v1; the second runs the two registered placements and writes the artifacts.

Artifacts under `research/nfl/turnover-2026-10-19/`:

| File | Rows | Contents |
|---|---|---|
| `forecasts.csv` | 3,680 | every scored-season game 2011-2025, including exclusions; `p_v1`, `p_B`, `p_elo`, `p_turnover_luck`, `p_elo_plus_turnover`, `p_market`, `graded`, `exclusion` |
| `paired.csv` | 7,338 | one row per placement x group x graded game: Brier and log loss for B and F, their differences, margin errors, block |
| `arm_scores.csv` | 6 | placement x group: n, Brier v1/B/F/market, registered and clustered intervals, log loss, margin MAE, market gap, kept |
| `per_season.csv` | 30 | placement x season: n, Brier B/F and difference, log loss B/F, margin MAE B/F |
| `exclusions.csv` | 18 | group and season: total, ties, no market, no spread, graded, week range |
| `MANIFEST.json` | — | prereg commit and sha256, base commit, feature definition, DB, population, data facts (including the 2026 nulls), published and reproduced baselines, interval definitions, results, verdict, file sha256s |

`backend/nfl_turnover_run.py` is new on this branch; the harness and registration files are
unchanged from `d007e540`.
