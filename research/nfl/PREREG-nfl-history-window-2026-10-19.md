# PRE-REGISTRATION — NFL history-window ablation on fixed test games

**Status:** PRE-REGISTERED 2026-10-19, before any ablation run.
**Branch:** `research/nfl-history-window-2026-10-19`, off `origin/dev` at `fbd1dad6`.
**Mode:** research only. No adoption, no gate/threshold/serving/model-coefficient change, no prod DB,
no merge to dev. Frozen forecasts and historical picks are preserved. Dev DB is opened `mode=ro`.

---

## 1. Question

Does the recency of the team-rating prior's history window change the game model's proper scores?

The incumbent prior uses **exactly one prior season's final fit**. This ablation asks whether widening
that window (recursively chained) improves Brier and log loss on identical test games.

## 2. Incumbent code path (named, not changed)

| step | code | what it does |
|---|---|---|
| prior for season `S` | `backend/nfl_ratings_data.py:125 prior_for_season` | `f, _ = season_fit(con, S - 1, **fit_kwargs)` then `prior_from_fit(f, shrink)` |
| one-season fit | `backend/nfl_ratings_data.py:54 season_fit` | `nr.fit(games, teams_in_season(con, S), **fit_kwargs)`; **no prior** unless the caller passes one |
| shrink | `backend/nfl_ratings_data.py:66 prior_from_fit` | `prior = (1 - shrink) * final_rating`, for both `o` and `d` |
| season backtest | `backend/nfl_backtest.py:84 backtest_season` | for each week `w >= 2`: train on **current-season weeks < w only** (anchored at `w - 1`), fit with the season-level prior, project the week-`w` games |
| prior hook | `backend/nfl_backtest.py:68 prior_for` | calls `nrd.prior_for_season`; `None` if no earlier season |

So the incumbent is **W=1**: the prior for `S` is `(1 - 1/3) x` the final fit of `S-1`, where `S-1`'s
fit used no prior. This is the arm that must remain numerically unchanged.

## 3. Frozen parameters (all arms identical)

From the frozen v1 configuration (`docs/SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md` §243;
`docs/RESULTS-benchmark-ladder-2010-2020-2026-10-13.md`; `backend/benchmark_ladder_2010_2020.py`
`FROZEN`):

| parameter | value |
|---|---:|
| `half_life` | 6.0 |
| `cap` | 14.0 |
| `cap_points` | None |
| `prior_games` | 4.0 |
| `shrink` | 1/3 |
| `sigma` | 13.295 |

No arm changes any of these. The only difference between arms is the prior's history window.

## 4. Arms and the exact chain definition

Four arms, registered:

| arm | prior for season `S` |
|---|---|
| **W=1** | incumbent: final fit of `S-1` with **no prior**, then `shrink`. Exactly `prior_for_season`. |
| **W=2** | chain over `S-2 .. S-1` |
| **W=3** | chain over `S-3 .. S-1` |
| **all-available** | chain over `2010 .. S-1` |

**Chain definition (recursive prior, stated so a later run cannot reinterpret it).** Let
`first = 2010` (the earliest season in `nfl_schedule` with scored REG games). For a target season `S`:

```
base = S - 1                                       # W=1
base = max(first, S - 2)                           # W=2
base = max(first, S - 3)                           # W=3
base = first                                       # all-available

f = season_fit(con, base, half_life=6.0, cap=14.0, prior_games=4.0)   # NO prior
for t in range(base + 1, S):
    f = season_fit(con, t, prior=prior_from_fit(f, shrink=1/3),
                   half_life=6.0, cap=14.0, prior_games=4.0)
prior_S = prior_from_fit(f, shrink=1/3)
```

For W=1 the loop is empty and `base = S-1`, so the result is identical to `prior_for_season`
(verified below). The shrink is applied at **every** link of the chain; the chain is a recursive prior
passed into `season_fit`, not a pooled multi-season fit and not an average of final fits. Seasons before
`base` do not influence the prior.

**Verification that W=1 is the incumbent.** Before scoring, the harness must reproduce
`nfl_backtest.backtest_season(con, S)` for every graded game in 2013-2020, 2024 and 2025 using the
explicit W=1 prior and the shared backtest loop; the maximum absolute difference in `p_model` must be
**0.0** (bit-identical). If it is not, stop and report — do not proceed.

## 5. Test set

- **Primary:** scored REG games, **weeks 2+**, seasons **2013-2020**, where every arm has a prediction.
  2013 is the first season with three prior seasons available (2010-2012), so W=3 is defined for every
  primary season.
- **Holdouts:** **2024** and **2025**, scored separately from the primary and from each other.
- **Identical game set for every arm.** The backtest loop is the same for every arm; only the prior
  differs. The harness must verify the `game_id` set is identical across arms for each period and
  report any difference (expected: none).
- **Ties excluded and counted** (`outcome is None`). Ties are excluded from Brier/log loss but counted
  per season and pooled.
- 2021-2023 are **not** in the registered evaluation. 2010-2012 are warm-up history only (2010-2012
  cannot be primary because W=3 is undefined for 2012 and earlier). Neither is scored as evidence.
- A game missing a score is not in the set (the backtest already requires scores).
- No game is dropped for being hard, unusual, or a bad forecast. The only exclusions are ties and
  missing scores, both counted.

## 6. Scores and the exact bootstrap

For every arm and every period:

- **Brier** and **log loss** on P(home wins), ties excluded.
- **Paired difference: arm minus incumbent**, per game, on the identical game set. Negative means the
  arm is better.
- **95% interval: `week_block_bootstrap_mean_diff` in `backend/nfl_history_window.py`.**
  - Block key: `(season, week_start_utc)`, where `week_start_utc` is the **Monday** of the game's
    `nfl_schedule.gameday` week (`gameday - timedelta(days=gameday.weekday())`).
  - Resample the **blocks** with replacement, 2,000 reps, weight each sampled block by its number of
    graded games, and take the weighted mean of the paired per-game differences.
  - **Seed: 20261019.** Percentile interval at 2.5% and 97.5%.
  - Returns `(point_estimate, lo, hi, blocks, n)`, where `point_estimate` is the sample mean of the
    paired differences and `blocks` is the number of distinct `(season, week_start_utc)` blocks.
- Report **n games, n blocks, and ties excluded** for every score and every period.
- Report **each primary season 2013-2020 separately**, the primary pooled, and 2024 / 2025 separately.

This is the only interval used. It is not `nfl_metrics.bootstrap_mean_diff_ci` (that helper resamples
games, not blocks, and is not used here). The name, block key, reps and seed above are the registration.

## 7. Benchmarks (benchmark only — never an adoption argument)

From `docs/RESULTS-benchmark-ladder-2010-2020-2026-10-13.md`:

- **538 Elo: 0.2193** (the doc's 2010-2020 set, n=2,633; `elo_prob1`, constants fit on this history,
  so it is a flattering bar).
- **Closing market: 0.2104** (the doc's 2010-2020 set, de-vigged moneyline).

On the **overlapping primary games only** (2013-2020, same graded game set as the arms), the harness
also recomputes the 538 Elo and closing-market Brier from the same definitions used in
`backend/benchmark_ladder_2010_2020.py`:

- 538 Elo: `nfl_elo_538.elo_prob1` joined on `(gameday, home_team, away_team)`, OAK read as LV, and
  the reversed pair matched with `1 - elo_prob1` for the nine listed neutral/relocated games. A game
  with no Elo row either way is **excluded from the benchmark subset and counted**, never from the arm
  evaluation.
- Closing market: `p_market` from the backtest rows (de-vigged moneyline).

Both are labeled **benchmark**, reported beside the arms, and never used in the keep rule. The doc's
published 0.2193 / 0.2104 are on a different (2010-2020) set and are not mixed with the 2013-2020
subset; both are shown with their own n.

## 8. Keep rule (evidence only; the verdict is Micah's)

For each arm, the registered keep rule is met only if **all three** hold:

1. pooled 2013-2020 Brier improves (paired arm-minus-incumbent interval entirely below 0);
2. the 2024 holdout Brier improves (paired interval entirely below 0);
3. the 2025 holdout Brier improves (paired interval entirely below 0).

Otherwise the arm is **NOT_ADOPTED**. The rule is applied to Brier, as registered. Log loss is
reported for completeness and is not a second gate. No arm is adopted by this document; the report
states whether each arm meets the registered rule and leaves the verdict to Micah.

## 9. What would falsify the idea

- If no window wider than W=1 improves the pooled 2013-2020 Brier with an interval below zero, the
  prior's history window is not a lever under this model and should be recorded as such.
- If a wider window improves the pooled primary but fails either 2024 or 2025, the gain does not hold
  out of sample and the arm is NOT_ADOPTED by the registered rule.
- If W=1 reproduction fails, the harness is wrong and the run does not count.

## 10. Deliverables and artifacts

- `research/nfl/PREREG-nfl-history-window-2026-10-19.md` (this file, committed before the run).
- `backend/nfl_history_window.py` — the chain, the shared backtest loop, the week-block bootstrap,
  the arm comparison and the benchmark join.
- `research/nfl/RESULT-nfl-history-window-2026-10-19.md` — every number from the script's own output,
  the population for every score, per-season and pooled, the keep-rule result, the benchmark block,
  and the limitations.
- Per-game and per-season CSVs under `research/nfl/history-window-2026-10-19/` so every aggregate is
  recomputable (forecasts, arms, paired differences, block counts).

All writes are on `research/nfl-history-window-2026-10-19`. `research/fbs/phase4/` and the Phase 4
JSON/PMF are untouched. No production or prod-DB write; the dev DB is opened `mode=ro`.

## 11. Deviation policy

Run exactly as registered. If a deviation is unavoidable, **stop and report the deviation** rather than
silently changing the registration. Any post-hoc window, parameter, test-set, or bootstrap change is a
new pre-registration, not this one.
