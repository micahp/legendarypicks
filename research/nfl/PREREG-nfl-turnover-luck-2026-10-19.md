# PRE-REGISTRATION: NFL turnover-luck feature, 2026-10-19

Status: **written and committed before any run of this feature.** The run is void if it
starts before this file's commit exists. Base: `origin/dev` `d007e540`; worktree
`/root/lp-nfl-turnover`; branch `research/nfl-turnover-luck-2026-10-19`. Read-only dev DB;
nothing written outside the worktree.

This is the seventh and eighth test on seasons earlier work already used (2011-2023 pooled,
2024, 2025). 2025 has been looked at by six prior tests and is **not** a clean holdout. The
result is evidence only; nothing is adopted even if it passes. No gate, threshold, serving,
scheduler or prod change; no refit of frozen v1. The decision is Micah's.

## 1. Lever and why

Turnover luck. Fumble recovery is close to a coin flip (observed offensive fumble-recovery rate
is about 45-50% in 2010-2025), so a team's actual turnover count mixes turnover-worthy
behaviour with recovery luck. The registered column replaces the actual recovery outcome with
a fixed expected recovery of 0.5, so the column measures turnover-worthy behaviour, not
recovery luck. It is one lever and one column.

One definition is registered, and it is the expected-recovery variant required by the brief.
No actual-recovery column is registered, so the stack cannot spend a column on the luck
component; the luck is removed by construction.

## 2. Data and scope

- Source: `nfl_pbp`, seasons 2010-2025, `posteam IS NOT NULL`. No `game_type` filter, matching
  the PROE registration: playoff games count in the 8-team-game window and in the same-season
  league mean when they are strictly before the game.
- Columns used: `interception` and `fumble` for the column. `fumble_lost` is **not used** in
  the column: the 0.5 expected recovery replaces the actual recovery outcome. All three
  columns are populated for 2010-2025.
- 2026 is **not usable and is not used**. All 16,212 2026 plays have `fumble` and
  `fumble_lost` NULL (`interception` is present). The feature is undefined for 2026; it is not
  imputed, not backfilled, and 2026's 92 completed games are not part of this test. The harness
  already scores 2010-2025 only.
- Offensive play universe: `qb_dropback = 1 OR rush_attempt = 1`. This includes pass attempts,
  sacks and rushes; it excludes punts, kickoffs, field goals, and plays with no `posteam`.

## 3. The registered column (fixed numerically before the run)

Feature name: `turnover_luck`. One column: `turnover_worthy_diff`.

### 3.1 Records

For each team-game `(season, week, game_id, posteam)` in 2010-2025, over the offensive play
universe above:

- `n` = number of offensive plays (`qb_dropback = 1 OR rush_attempt = 1`).
- `s` = `SUM(interception = 1) + 0.5 * SUM(fumble = 1 AND interception = 0)`.

  - `interception = 1` counts an interception thrown by the offense.
  - `fumble = 1 AND interception = 0` counts an offensive fumble. A play with both
    `interception = 1` and `fumble = 1` (2-11 plays per season in 2010-2025) is treated as an
    interception only; the fumble is on the return and is not an offensive fumble. This is a
    small, stated approximation; the count is reported in RESULTS.
  - The 0.5 is fixed, not estimated or tuned. The observed offensive fumble-recovery rate is
    about 45-50% over 2010-2025; 0.5 is the coin-flip expectation, not a fitted value.

### 3.2 Rate before a game

For a team and a game in season `S`, week `w`, cutoff `(S, w, "")`:

- **Window:** the team's last 8 team-games strictly before the cutoff, ordered by
  `(season, week, game_id)`. The window crosses season boundaries and may include the prior
  season's playoff games, as in the PROE registration.
- **League:** `league = sum(s) / sum(n)` pooled over every team-game of the **same season S**
  strictly before the cutoff. If `sum(n) = 0`, the feature is undefined and the run stops; no
  value is imputed.
- **Rate:** `(sum_window(s) + K * league) / (sum_window(n) + K)`, with `K = 200` offensive
  plays, the same shrink weight and window shape as PROE.
- **Column:** `rate(home) - rate(away)`.

No expected sign is registered. The keep rule does not need one.

## 4. Placements, exactly two

Both use the unchanged `nfl_feature_backtest.py`: the same `stack`, `graded`, `GROUPS`, report
and KEEP rule. Frozen v1 parameters are untouched: `half_life 6.0`, `cap 14.0`,
`cap_points None`, `sigma 13.295`. The stack is, for season S, OLS of actual home margin on
`[1, v1 projected margin, feature columns]` fitted on every base row of seasons 2010..S-1;
sigma is the sd of that fit's residuals; `p_home = Phi(margin / sigma)`.

1. **`turnover_luck` alone on frozen v1.** `F = stack(rows, [turnover_worthy_diff])`,
   `B = stack(rows)` (plain stack B, no feature columns). Judged against stack B.
2. **`elo_plus_turnover` on top of the Elo stack.** `F = stack(rows, [elo_diff,
   turnover_worthy_diff])`, `B = stack(rows, [elo_diff])` (`nfl_elo_replica.elo_diff`, the
   fourth model on the Model tab). Judged against the Elo stack.

No other placement, no third variant, no interaction, no extra column.

## 5. Population and groups (unchanged from the harness)

- Base rows: `nfl_backtest.backtest_season` for seasons 2010-2025, frozen v1, weeks 2-18, REG.
  2010 is training only (no 2011+ stack fits on it).
- Graded set: games with an outcome (no tie), a moneyline and a spread; groups
  **2011-2023** pooled (development), **2024** (confirmation), **2025** (second look only; it
  was v1's holdout and has been used by six prior tests, so it is not a clean holdout).
- Ties are excluded and counted. Missing moneyline or spread games are excluded and counted;
  no probability is imputed.
- 2026 is not in the population: `fumble`/`fumble_lost` are NULL for all 16,212 plays.

## 6. Interval and rule

- **Registered interval:** `nfl_metrics.bootstrap_mean_diff_ci`, paired games, **5,000
  resamples, seed 20261009**, alpha 0.05. This is the verdict interval.
- A week-block clustered interval may be reported only as a secondary diagnostic and is kept
  out of the verdict; if reported, it must name its helper, block key, reps and seed and be
  labelled secondary.
- **KEEP rule (unchanged):** the pooled 2011-2023 interval of Brier(feature) − Brier(stack B or
  Elo stack) lies entirely below zero, **AND** the 2024 and 2025 point differences are not
  above zero. Anything else is not kept.
- Brier is the verdict. Log loss is reported as a secondary diagnostic, not folded into the
  verdict. **No accuracy anywhere.**
- Margin MAE is reported as in the shared harness. The gap to the market is reported as a
  benchmark only; it is not a keep condition and the market is never treated as a rung to beat
  with a different n. Never compare rungs with different n.

## 7. What is not tested

Defensive takeaways (the column is the team's own offensive turnover-worthy rate, not its
defense's forced turnovers); actual-recovery turnovers as a separate column; other windows
(4, 12, 16 team-games); other shrink weights (100, 400); other expected-recovery values (0.4,
0.6); fumble-lost as a separate column; a turnover-differential column; QB- or player-specific
turnovers; playoff games as a scored population; week 1; 2010 as a scored season; any gate,
threshold, serving, scheduler or prod change; any refit of frozen v1; any re-registration
after this commit.

## 8. Reproduction (run only after this file's commit exists)

```
cd /root/lp-nfl-turnover/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_feature_backtest.py --feature base
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_turnover_run.py
```

The first command reproduces stack B and frozen v1 on the harness groups. The second runs the
two registered placements and writes `research/nfl/turnover-2026-10-19/`. The DB is opened
`mode=ro`; nothing is written to it.

## 9. Commit gate

This prereg is committed on `research/nfl-turnover-luck-2026-10-19` before the first run. The
commit SHA is reported in the final message and in `MANIFEST.json`. If any run output exists
before that commit, the run is void and the deviation is reported, not repaired.
