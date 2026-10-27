# Experiment: outdoor 50-69F with 10-14 mph wind and penalties (team-adjusted)

Status: exploratory. Not promoted. Not confirmed on unused data.
Date run: 2026-10-27. Guide: `docs/EXPERIMENTS-GAME-INFO-BACKTESTS-2026-10-27.md` (family E2).

## Question

Do outdoor games played at 50 to 69F with a 10 to 14 mph wind have more flagged penalties and penalty yards than other
outdoor games, once each team's own penalty tendency is removed?

## Why this cell

It was the one cell of the outdoor temperature-by-wind family (E2) that passed its own decision rule on the first run
(raw penalties, q = 0.030). The question was then restated as the team-adjusted test below. The cell was chosen from
the data, so the result is exploratory.

## Data

- Games: regular season, 2022 to 2025, outdoor or retractable-open roof, with observed temperature and wind known:
  736 outdoor games; 42 in the cell.
- Weather: observed game-time temperature and wind from the schedule (`nfl_schedule`). A forecast would be noisier.
- Penalties: `nfl_pbp_penalty`, rows with `penalty = 1` (flagged plays), counted per team by `penalty_team`
  (`LA` and `WAS` mapped to `LAR` and `WSH`). Yards are `penalty_yards` on the same rows.
- 2026 is not read. No betting columns are read.

## Method

1. **Team adjustment.** For each team-season, the expectation for a game is that team's leave-one-out average of flagged
   penalties committed per game (and yards). A game's expected penalties are the home expectation plus the away
   expectation. The residual is actual minus expected. Leave-one-out means the game being scored never explains its own
   residual.
2. **Season centring.** Residuals are centred on each season's mean.
3. **Family test.** The E2 family (temperature by wind) on the residuals, with the same bootstrap (2,000 resamples),
   permutation (2,000) and Benjamini-Hochberg machinery as the rest of the guide. Family of 10 tests (5 cells, 2 outcomes).
4. **Season by season.** The cell against the other outdoor games in each season, with a bootstrap interval.
5. **Global control.** The same p-value pooled across every test run so far: 968 tests from E0 and E2 to E7, plus the 2
   team-adjusted cell tests, 970 in total. Benjamini-Hochberg over the pool.

## Results

Team-adjusted, full sample 2022 to 2025 (42 cell games, 736 outdoor games):

| Outcome | Effect per game | 95% CI | p | q, family of 10 | q, pool of 970 |
|---|---:|---|---:|---:|---:|
| Flagged penalties | +2.38 | [0.95, 3.69] | 0.001 | 0.010 | 0.230 |
| Penalty yards | +17.4 | [5.4, 29.7] | 0.008 | 0.038 | 0.230 |

Raw (not team-adjusted), for comparison: penalties +2.14 [0.78, 3.42], p = 0.002; yards +15.4 [3.4, 27.2], p = 0.016.

By season (team-adjusted penalties, cell against the other outdoor games that season):

| Season | Cell games | Effect | 95% CI |
|---|---:|---:|---|
| 2022 | 6 | +2.04 | [0.00, 4.17] |
| 2023 | 15 | +1.67 | [-0.58, 3.98] |
| 2024 | 13 | +2.15 | [-0.70, 5.16] |
| 2025 | 8 | +3.06 | [0.33, 5.49] |

Yards by season are positive in all four seasons, with wide intervals that include zero except in 2025.

## Reading

- The sign is the same in all four seasons, and the team adjustment changes little, so team tendency is not the
  explanation.
- It passes within its own family, but not across the full search: the pool-wide q is 0.23. The cell was found by
  searching, which is the case the wider control is for.
- Per-season intervals are wide, and only 2022 and 2025 exclude zero, narrowly.
- Possible mechanisms are untested here: colder hands and footing, and the crowd noise or sound a wind carries. None of
  these is evidence.

## Caveats

- Small cell: 42 games in total, between 6 and 15 per season.
- Observed weather, not a pre-game forecast. A forecast-based input would show a smaller effect.
- Penalty counts are flagged plays, not accepted penalties. Declined and offsetting penalties are included.
- The team adjustment is leave-one-out season averages, so early-season games use fewer games for the expectation.
- The cell was chosen after looking at the data, so the in-family q-value overstates the evidence.

## What would settle it

A confirmation on games not yet used. The only season not yet used is 2026, which is reserved as the holdout. Either the
reservation is lifted for this one question, or the test waits for a new season. That decision is not made here.

## Reproduce

From the repository root, with `backend/data/picks.dev.db` present:

```
python3 -I scripts/nfl_sequence/game_info/retest_penalty_cell.py
```

Writes `/root/lp-snapshots/nfl-game-info/experiments/penalty-cell-retest/retest.json`. Its SHA-256 at the time of this
document is `aa5be3bc533dcdede2fcece78b59596ff63681bbf7e2b3c8effdb61590c4c652`. The pool-wide q of 0.230 was computed from the result files of E0, E2 to E7 and this re-test, not by
a committed script.

## Files

- `scripts/nfl_sequence/game_info/retest_penalty_cell.py`: this experiment.
- `scripts/nfl_sequence/game_info/backtest_splits.py`: the shared split machinery (E0).
- Guide: `docs/EXPERIMENTS-GAME-INFO-BACKTESTS-2026-10-27.md`.
