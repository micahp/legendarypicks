# RESULT: PROE feature test (already registered), 2026-10-19

## Verdict

**Both variants fail the registered keep rule. Neither is kept. Nothing is adopted.**

| Variant | Baseline | Pooled 2011-2023 F−B [95%] | 2024 point | 2025 point | Kept |
|---|---|---|---|---|---|
| `proe_net` | stack B | −0.000045 [−0.001034, +0.000901] | −0.000247 | **+0.002423** | **no** |
| `elo_plus_proe` | Elo stack | +0.000244 [−0.000428, +0.000903] | −0.000011 | **+0.001229** | **no** |

The registered rule is: the pooled 2011-2023 interval of Brier(F) − Brier(B) lies entirely
below zero, **and** the 2024 and 2025 point differences are not above zero. Both variants fail
the first condition (both pooled upper bounds are positive) and both fail the second on 2025
(both 2025 points are positive, and their registered intervals exclude zero on the positive
side). There is no arm to stop for: neither variant is kept.

PROE adds no forecast value on this harness, alone or on top of Elo. The pooled point
differences are indistinguishable from zero, the sign flips by season, and the one holdout with
a resolvable move (2025) is worse for both variants.

## Registration and what was run

No re-registration. The registration is the docstring of `backend/nfl_proe_feature.py`,
committed before its first run:

- canonical commit `ed96a861ad1702b18d346fd166ef94ab7f45d1ec`
- dev-history commit with the identical file `af96cbf6383c4f153a49430d93ef9a7d7b14cec7`
- file sha256 `ad293e700db978362aa546d01051c39c6f3094b598b6348e6992e14afb430d3c`

The file is unchanged from the base commit `fbd1dad6e1c9600c5360536c8d4201f0645222ff`.
`nfl_feature_backtest.py` (the shared harness, `stack`, `report`, groups, keep rule) and
`nfl_metrics.py` are unchanged. The only new file is the runner `backend/nfl_proe_run.py`,
which calls the registered code paths and writes the artifacts; it adds no rule.

What the registration fixes, and what was run:

- Records: per team-game from `nfl_pbp` by the team with the ball: `n` plays with a `pass_oe`
  value, `s` their sum.
- `proe_net`: two columns. (1) offense PROE difference: a team's offense PROE =
  `(sum + 200 x league) / (n + 200)` over its last 8 team games strictly before the game (the
  window crosses season boundaries); `league` = the same mean pooled over every team-game of
  the same season strictly before the game; column = home minus away. (2) PROE faced
  difference: the same quantity on the opponents' offense in those games; column = home minus
  away. No expected sign.
- `proe_net` is judged against stack B (the same frozen-v1 stack with no feature columns).
- `elo_plus_proe` adds the same two columns to the stack that already holds `elo_diff`
  (`nfl_elo_replica.elo_diff`, the fourth model on the Model tab), and is judged against the
  Elo stack.
- Both are scored through the unchanged `nfl_feature_backtest.py` stack: for season S, OLS of
  actual home margin on `[1, v1 projected margin, feature columns]`, fitted on every base row
  of seasons 2010..S-1; sigma = sd of that fit's residuals; `p_home = Phi(margin / sigma)`.
- Groups: 2011-2023 pooled, 2024, 2025. Ties excluded. Read-only dev DB (`mode=ro`).

This is the fifth and sixth test run on seasons earlier work has already used. It is reported
as is; a pass would have been weaker evidence than the first feature's, and there is no pass.

## Baselines reproduced before scoring

The brief requires the judged baselines to reproduce the published numbers on the harness's own
groups, matched-game, before any variant is scored. They do, to four decimals:

| Baseline | 2011-2023 (n 3,158) | 2024 (n 256) | 2025 (n 255) | Published |
|---|---|---|---|---|
| Stack B | 0.222892 | 0.222297 | 0.229221 | 0.2229 / 0.2223 / 0.2292 |
| Frozen v1 | 0.223123 | 0.220971 | 0.228811 | 0.2231 / 0.2210 / 0.2288 |
| Elo stack | 0.219659 | 0.214451 | 0.225512 | 0.2197 / 0.2145 / 0.2255 |
| Closing market | 0.210415 | 0.200114 | 0.213697 | 0.2104 / 0.2001 / 0.2137 |

Published sources: `docs/RESULTS-nfl-features-vs-market-2026-10-11.md` (stack B, frozen v1,
market) and `docs/RESULTS-nfl-elo-and-era-2026-10-13.md` (Elo stack). The runner aborts with a
baseline mismatch instead of proceeding; it did not abort.

## Population

Base rows: 3,920 across seasons 2010-2025, weeks 2-18. Week 1 has no prior fit in
`nfl_backtest.backtest_season` and is not a base row. 2010 (240 rows) is training only: the
stack fits on 2010..S-1, so no 2010 game is scored. Scored seasons 2011-2025: 3,680 rows.

| Group | Seasons | Total rows | Ties | No market | No spread | Graded | Weeks |
|---|---|---|---|---|---|---|---|
| 2011-2023 | 2011-2023 | 3,168 | 9 | 1 | 0 | 3,158 | 2-18 |
| 2024 | 2024 | 256 | 0 | 0 | 0 | 256 | 2-18 |
| 2025 | 2025 | 256 | 1 | 0 | 0 | 255 | 2-18 |

Per-season graded counts: 2011 240, 2012 239, 2013 239, 2014 239, 2015 240, 2016 238,
2017 240, 2018 239, 2019 240, 2020 239, 2021 255, 2022 254, 2023 256, 2024 256, 2025 255.

Exclusions are counted, not hidden:

- **10 ties** (`outcome is None`): 2012_10_STL_SF, 2013_12_MIN_GB, 2014_06_CAR_CIN,
  2016_07_SEA_ARI, 2016_08_WAS_CIN, 2018_02_MIN_GB, 2020_03_CIN_PHI, 2021_10_DET_PIT,
  2022_13_WAS_NYG, 2025_04_GB_DAL. Nine are in 2011-2023, one in 2025, none in 2024. Ties are
  excluded from the Brier and log-loss grading; the margin fit inside the stack includes ties
  as the shared rule says.
- **1 no-market game**: `2017_04_CHI_GB` (2017 week 4, GB at CHI, spread 7.5, no moneyline).
  Excluded from the graded set; no probability is imputed. This is the same game the
  history-window benchmark overlap flagged.
- **0 no-spread games**: every non-tie game with a moneyline has a spread line.

## Results: `proe_net` against stack B

Registered interval: `nfl_metrics.bootstrap_mean_diff_ci`, paired games (no block key),
5,000 resamples, seed 20261009 (the helper's fixed default), alpha 0.05. This is the interval
the keep rule uses. The clustered interval is reported separately and is secondary.

| Group | n | Brier B | Brier F | F−B [95% registered] | F−B [95% clustered, secondary] | Margin MAE B | Margin MAE F | F−B margin |
|---|---|---|---|---|---|---|---|---|
| 2011-2023 | 3,158 | 0.222892 | 0.222847 | −0.000045 [−0.001034, +0.000901] | −0.000045 [−0.000971, +0.000897], 211 blocks | 10.511 | 10.513 | +0.0028 [−0.0364, +0.0419] |
| 2024 | 256 | 0.222297 | 0.222050 | −0.000247 [−0.002667, +0.002162] | −0.000247 [−0.002933, +0.002547], 17 blocks | 10.373 | 10.340 | −0.0332 [−0.1212, +0.0546] |
| 2025 | 255 | 0.229221 | 0.231644 | **+0.002423 [+0.000340, +0.004566]** | +0.002423 [+0.001060, +0.004054], 17 blocks | 10.671 | 10.703 | +0.0321 [−0.0468, +0.1136] |

Gap to market (Brier; lower is better; the market's own Brier is 0.2104 / 0.2001 / 0.2137):

| Group | F − market | B − market |
|---|---|---|
| 2011-2023 | +0.012432 [+0.009334, +0.015715] | +0.012477 [+0.009477, +0.015682] |
| 2024 | +0.021936 [+0.009191, +0.034710] | +0.022183 [+0.009557, +0.034887] |
| 2025 | +0.017947 [+0.006617, +0.029312] | +0.015524 [+0.004274, +0.026753] |

The feature does not close any of the market gap. In 2025 it widens it by 0.0024 relative to
stack B, which is the one group where the feature's move is resolvable.

## Results: `elo_plus_proe` against the Elo stack

Same registered interval. The baseline is the Elo stack (`elo_diff` on frozen v1), not stack B.

| Group | n | Brier B | Brier F | F−B [95% registered] | F−B [95% clustered, secondary] | Margin MAE B | Margin MAE F | F−B margin |
|---|---|---|---|---|---|---|---|---|
| 2011-2023 | 3,158 | 0.219659 | 0.219903 | +0.000244 [−0.000428, +0.000903] | +0.000244 [−0.000397, +0.000890], 211 blocks | 10.399 | 10.417 | +0.0181 [−0.0092, +0.0444] |
| 2024 | 256 | 0.214451 | 0.214439 | −0.000011 [−0.001244, +0.001239] | −0.000011 [−0.001409, +0.001525], 17 blocks | 10.150 | 10.133 | −0.0169 [−0.0643, +0.0318] |
| 2025 | 255 | 0.225512 | 0.226740 | **+0.001229 [+0.000222, +0.002264]** | +0.001229 [+0.000495, +0.002147], 17 blocks | 10.501 | 10.526 | +0.0243 [−0.0135, +0.0641] |

Gap to market (Brier):

| Group | F − market | B − market |
|---|---|---|
| 2011-2023 | +0.009488 [+0.006573, +0.012516] | +0.009244 [+0.006332, +0.012308] |
| 2024 | +0.014325 [+0.002785, +0.025985] | +0.014336 [+0.002848, +0.026048] |
| 2025 | +0.013044 [+0.002975, +0.023049] | +0.011815 [+0.001720, +0.021830] |

On top of Elo the feature is also a small negative: the pooled point is +0.000244, 2024 is
flat to five decimals, and 2025 is +0.001229 with a registered interval that excludes zero on
the positive side. Elo already carries the signal; PROE adds nothing and costs a little in
2025.

## Keep rule, applied exactly

Registered rule: pooled 2011-2023 interval of Brier(F) − Brier(B) entirely below zero, AND the
2024 and 2025 point differences not above zero.

| Variant | Pooled upper bound < 0? | 2024 point ≤ 0? | 2025 point ≤ 0? | Kept |
|---|---|---|---|---|
| `proe_net` | no: +0.000901 | yes: −0.000247 | **no: +0.002423** | **no** |
| `elo_plus_proe` | no: +0.000903 | yes: −0.000011 | **no: +0.001229** | **no** |

Both fail. The pooled interval is not entirely below zero for either variant, and both 2025
points are above zero. The 2024 point is flat for both (within ±0.0003), so it cannot rescue
the rule. There is no kept variant, so no stop for direction is required; nothing is adopted,
no gate or threshold is changed, and no serving or coefficient is touched.

## Per-season breakdown (Brier F − B)

Five decimals; the group rows above are the registered aggregates. A negative number means the
feature is better than its baseline in that season.

| Season | n | `proe_net` F−B | `elo_plus_proe` F−B |
|---|---|---|---|
| 2011 | 240 | −0.00156 | −0.00054 |
| 2012 | 239 | +0.00326 | +0.00358 |
| 2013 | 239 | +0.00107 | +0.00021 |
| 2014 | 239 | +0.00156 | +0.00132 |
| 2015 | 240 | −0.00077 | −0.00033 |
| 2016 | 238 | −0.00022 | −0.00022 |
| 2017 | 240 | +0.00035 | +0.00038 |
| 2018 | 239 | +0.00084 | +0.00060 |
| 2019 | 240 | −0.00099 | −0.00046 |
| 2020 | 239 | +0.00105 | +0.00055 |
| 2021 | 255 | −0.00063 | +0.00005 |
| 2022 | 254 | −0.00392 | −0.00199 |
| 2023 | 256 | −0.00031 | +0.00019 |
| 2024 | 256 | −0.00025 | −0.00001 |
| 2025 | 255 | +0.00242 | +0.00123 |

`proe_net` is negative in 8 of 15 seasons and positive in 7; `elo_plus_proe` is negative in 6
and positive in 9. The largest single-season gain for both is 2022 (`proe_net` −0.00392,
`elo_plus_proe` −0.00199); the largest single-season loss is 2012 (+0.00326 / +0.00358), with
2025 the second largest for `proe_net` (+0.00242). The sign is not stable, and the pooled point
is inside noise.

## Secondary diagnostics (not part of the verdict)

These are labelled secondary and are not folded into the keep rule. The registered rule is
Brier with `nfl_metrics.bootstrap_mean_diff_ci`; everything below is additional description.

**Log loss** (paired games, 5,000 resamples, seed 20261009; secondary):

| Variant | Group | Log loss B | Log loss F | F−B [95%] |
|---|---|---|---|---|
| `proe_net` | 2011-2023 | 0.636179 | 0.636113 | −0.000066 [−0.002252, +0.001978] |
| `proe_net` | 2024 | 0.635194 | 0.634516 | −0.000679 [−0.005900, +0.004477] |
| `proe_net` | 2025 | 0.649317 | 0.654378 | +0.005061 [+0.000428, +0.009827] |
| `elo_plus_proe` | 2011-2023 | 0.629005 | 0.629526 | +0.000522 [−0.000952, +0.001944] |
| `elo_plus_proe` | 2024 | 0.617870 | 0.617805 | −0.000066 [−0.002797, +0.002652] |
| `elo_plus_proe` | 2025 | 0.641185 | 0.643757 | +0.002572 [+0.000351, +0.004862] |

The log-loss reading agrees with Brier: flat pooled, flat 2024, worse in 2025. It is not a
second chance for the feature.

**Clustered interval** (secondary): `week_block_bootstrap_mean_diff`, copied from the
history-window runner, block key `(season, Monday gameday week)`, 2,000 resamples, seed
20261019, game-count weighted. It resamples week blocks, not games. The numbers are in the
tables above and in `arm_scores.csv`; they agree with the registered game-level interval to
four decimals. The registered interval remains the one the keep rule uses; the clustered
interval is a robustness check, not a substitute.

## What was and was not tested

Tested: the two registered PROE columns (offense PROE difference, PROE faced difference), the
registered last-8-team-game window crossing season boundaries, the registered 200-play shrink,
the same-season league prior strictly before the game, alone on frozen v1 against stack B, and
on top of `elo_diff` against the Elo stack. Seasons 2011-2023 pooled, 2024, 2025; weeks 2-18;
REG games; ties excluded and counted. Brier, the registered paired interval, margin MAE, the
gap to the market, per-season breakdowns, and the secondary log-loss and clustered readings.

Not tested: other windows (4, 12, 16 team games), other shrink weights (100, 400), one column
instead of two, PROE on top of EPA or the full stack, recency weights other than the 8-game
window, a different xpass model, QB- or player-specific PROE, opponent adjustment beyond the
faced column, playoff games, week 1, 2010 as a scored season, alternate sigma models, any gate
or threshold change, and any serving, coefficient or adoption change. No re-registration and
no new feature definition were made.

Limits: 2011-2023 has carried several feature tests already, and 2024 and 2025 are no longer
untouched holdouts. The result is therefore weaker evidence than the first feature test, as
the registration itself states. The 2025 move is the one resolvable signal, and it is against
the feature for both variants; it is reported as is, not softened. A future PROE test with a
different window or shrinkage would be a new registration, not an amendment to this one.

## Reproduction

```
cd /root/lp-nfl-proe/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_feature_backtest.py --feature base
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_proe_feature.py --feature proe_net
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_proe_feature.py --feature elo_plus_proe
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_proe_run.py
```

The first three are the registered entry points; the fourth reproduces the same stacks and
writes the per-game and paired artifacts. The DB is opened `mode=ro`; nothing is written to it.

Artifacts under `research/nfl/proe-2026-10-19/`:

| File | Rows | Contents |
|---|---|---|
| `forecasts.csv` | 3,680 | every scored-season game 2011-2025, including exclusions; `p_v1`, `p_B`, `p_elo`, `p_proe_net`, `p_elo_plus_proe`, `p_market`, `graded`, `exclusion` |
| `paired.csv` | 7,338 | one row per variant x group x graded game: Brier and log loss for B and F, their differences, margin errors, block |
| `arm_scores.csv` | 6 | variant x group: n, Brier v1/B/F/market, registered and clustered intervals, log loss, margin MAE, gap to market, kept |
| `per_season.csv` | 30 | variant x season: n, Brier B/F and difference, log loss B/F, margin MAE B/F |
| `exclusions.csv` | 18 | group and season: total, ties, no market, no spread, graded, week range |
| `MANIFEST.json` | — | registration hash and commits, base commit, DB, population, published and reproduced baselines, interval definitions, results, verdict, file hashes |

The runner is `backend/nfl_proe_run.py` (new, this branch). The registration and harness files
are unchanged from `fbd1dad6`.
