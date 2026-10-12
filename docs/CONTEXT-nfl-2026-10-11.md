# NFL model context, updated 2026-10-12

Read `docs/INDEX-nfl-model-research-2026-10-12.md` first. It has every lever, the stat stability table,
the data inventory, the next steps, and the rules. This file is the state of play for today.

## Repos and branches

- Work branch: `feat/nfl-model-foundation` in `/root/lp-nfl-lock-by-version`. Origin is at `f3b5dda`.
  Local commit `782b6f7` (the index) is not pushed.
- Uncommitted: `backend/ingest_nfl_pbp_logs.py`, `backend/nfl_feature_backtest.py`,
  `backend/test_ingest_nfl_pbp_logs.py`, `docs/INDEX-nfl-model-research-2026-10-12.md`, and three untracked
  files: `backend/test_nfl_preseason_prior.py`, `backend/test_nfl_season_to_date_features.py`, and this file.
- `dev` in `/root/legendarypicks` is at `3e5d3cc`, local only, not pushed. It contains Spec A
  (`8d7840f`, `a902ad8`). The earlier note that Spec A was not in `dev` is out of date.
- Spec B: branch `feat/player-projections-availability` in `/root/lp-player-proj`. Start there (see below).
- `lp-nfl-ratings` has 31 uncommitted entries (`git status --short`, checked 10-12), six not in `dev`. Keep it.

## Where the model stands

- The frozen v1 points model is worse than the de-vigged moneyline on Brier in 15 of 16 seasons. Pooled
  2010 to 2025: model 0.2244, market 0.2105, gap +0.0138.
- No model on our own data beats the closing spread, total or moneyline.
- Against 538 Elo (2011 to 2020), v1 ties overall. It is clearly worse in weeks 2 to 4 and ties from week 5.
- Kept: market prior (market-derived, so not our own forecast) and EPA by unit (marginal, +0.0019).
- Not kept, all tested with the pre-registered keep rule (pooled interval entirely below zero):

| Lever | F-B pooled (interval) | Note |
|---|---|---|
| Offseason carryover | no setting passes | v1 keeps shrink 1/3, prior_games 4 |
| Pressure, sack, share absence | from the matchup run | not kept |
| Independent preseason prior (last season EPA, shrunk) | -0.0008 [-0.0017, +0.0002] | per season mixed; 2021 -0.0048 |
| Turnover margin, season to date | +0.0002 [-0.0001, +0.0004] | |
| Penalties committed, season to date | +0.0000 [-0.0003, +0.0004] | re-run after a bug fix; 2 of 4,175 games changed |
| FTN blitz, variant A (fit 2022-23, grade 2024-25) | +0.0001 [-0.0001, +0.0003] | |
| FTN blitz, variant B (fit 2022, grade 2023-25) | -0.0002 [-0.0009, +0.0005] | fitted coefficient flips sign (-0.99 vs +3.84) |

## Stability (per season, not pooled)

Median across seasons (min to max) of the first-half vs second-half r:
- Penalties per game +0.79 (+0.70 to +0.89). Very stable, but stability did not make it a predictor.
- Turnover margin per game +0.17 (-0.38 to +0.45). Weak and unstable.
- Giveaways +0.21, takeaways +0.11.
- Target share +0.71, carry share +0.75, receiving TD share +0.30, rushing TD share +0.46.
- Pressure generated +0.34 (+0.02 to +0.50), sack rate +0.35 (+0.11 to +0.61).
- QB scramble +0.69, no-huddle +0.83.

## Data in the dev DB

- `nfl_pbp`: 58 columns. Added today: `penalty`, `penalty_team`, `fumble_lost`, `fumble`, backfilled for
  2010 to 2025 (every season dry-run first; the 2010 to 2012 applies needed one retry after a DB lock).
  `penalty_yards` and `penalty_type` are not stored. The four columns are null on all 11,327 2026 rows, so a
  2026 use of the turnover or penalty features needs the 2026 refresh first.
- Schedules and scores 2010 to 2026. Play-by-play 2010 to 2026 (regular season only). Week 5 of 2026: only
  1 of 15 games has pbp (172 plays) although 14 are scored (checked 10-12).
- FTN charting 2022 to 2025 (`nfl_hist_ftn_charting`, CC BY-SA, attribution stored).
- Participation: nflverse files exist for 2016 to 2025 (HTTP 200). 2010 to 2015 return 404. Not ingested.
- Injuries 2009 to 2025, snap counts 2013 to 2025, depth charts 2010 to 2024, 538 Elo through 2020.
- Lines: spread, total and moneyline 2010 to 2025 without capture times. Timestamped lines only from 10-11.

## Code (uncommitted)

- `backend/ingest_nfl_pbp_logs.py`: the backfill now covers the four new columns. `_valid()` checks
  flags (0, 1, null) and text (`penalty_team`).
- `backend/nfl_feature_backtest.py`: new pre-registered features `preseason_prior`, `turnover_margin`,
  `penalty_rate`, and `ftn_keep_test` (both FTN variants). `TO_K = 8`, `PRIOR_K = 400`.
  Bug fixed today: a team with no games to date now sits at the league average, as the docstrings say.
- Tests: 24 pass (`test_nfl_preseason_prior.py` 4, `test_nfl_season_to_date_features.py` 4,
  `test_ingest_nfl_pbp_logs.py` 16). Run with `python3 -m pytest -q` from `backend/`.

## Spec B (start here for player projections)

- Branch `feat/player-projections-availability`, worktree `/root/lp-player-proj`.
- Review commit `fd9ad96` addresses the five P1/P2 findings in `docs/REVIEW-SPEC-player-projections-availability-2026-10-10.md`.
  Focused suite: 52 pass.
- Still open: B2 air-yards denominator (355 of 355 2026 season rows differ from the team-game totals;
  ARI 935 vs 944), and the real 2025 WR1-out example for B3. Both need a DEV rebuild from a fresh
  publisher file. Nothing has been rebuilt yet.

## Decided by Micah, 2026-10-12

- The market prior is not our forecast. Our own model is v1 plus EPA by unit.
- No paying for historical timestamped odds.
- Test participation for 2016 to 2025 (window below, pre-registered in code before the run).
- Commit this work; do Spec B.

## Open decisions for Micah

1. Participation: test it for 2016 to 2025? If yes, we need a pre-registered window. The proposal is
   pooled 2016 to 2023 with 2024 and 2025 as the graded checks, and the walk-forward start year needs a
   fitting-season decision like the FTN variants.
2. Commit the uncommitted work. The pre-registrations are in the code and the results are in the index.
3. Push `dev` (ahead, local only) and the branch. Only when asked.
4. Recurring line capture and the Sam recorder: approved 10-11, not set up.
5. Whether the market prior counts as "our" forecast.
6. Whether to pay for historical timestamped odds.
7. Week 6 locks: skipped on instruction. They need the week 5 result and the 2026 pbp refresh.

## Rules

- Pre-register in the docstring before any run. Do not loosen a rule after a result.
- The keep rule is pooled only. No per-season keep rule (Micah). Per-season numbers are diagnostics.
- Walk-forward cannot grade FTN or participation seasons that have no earlier data. Use the fit-early,
  grade-later variants, and say which fitting seasons were used.
- Dev DB only (`picks.dev.db`). Backfills are additive: `--backfill-file` with a dry run first, keyed on
  `(game_id, play_id)`. Never `ingest_nfl_pbp_logs.py --year` on past seasons.
- Check RAM before batch work (`free -h`). Available was 0.8 to 2.6 GiB across today's runs.
- No locks, timers, `--record` or `--apply` on anything outside the approved backfill.
- Pushes and merges into `dev` only when asked. No em dashes. Use `git add` by file name only.
- Never `git stash` bare in a shared worktree (see the worktree note in the environment).
