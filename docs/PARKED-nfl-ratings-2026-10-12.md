# Parked and dropped: the 10-10 NFL ratings work (read this before reviving any of it)

The original uncommitted work was committed as-is on `feat/nfl-ratings-playoff-odds` (`dd17544`, 10-12) and
then reconciled onto `dev` as `feat/nfl-playoff-odds`. The old branch was deleted; its full contents are the
tag `archive/feat/nfl-ratings-playoff-odds`. Nothing below needs re-analysis: each item says what it is, the
decision, and how to get the code. Retrieve a file with
`git show archive/feat/nfl-ratings-playoff-odds:<path>`; restore the whole branch with
`git branch feat/nfl-ratings-playoff-odds archive/feat/nfl-ratings-playoff-odds`.

## Landed (on `feat/nfl-playoff-odds`)
`/api/nfl/playoff-odds`, `/api/nfl/ratings`, `jobs/nfl_playoff_odds.py` (ratings and odds only), the playoff
odds page and its link, timer and service files in `ops/systemd` (not installed).

## Parked: real work that needs something `dev` does not have yet
| Item | Path in the archive tag | What it needs before it can land |
|---|---|---|
| Empirical scoreline sampler and tie handling in the season sim | `backend/nfl_sim.py` (`ScorelineSampler`) | `dev`'s sim uses a placeholder 40-point split and no ties. Landing this changes the model, so it needs its own pre-registered test against the placeholder, and the seeding on `dev` must accept ties. |
| Touchdown data for the net-touchdowns tiebreaker | `backend/nfl_tiebreaker_data.py`, `backend/test_nfl_tiebreaker_data.py`, and the 3-line `td_team` addition in `backend/ingest_nfl_pbp_logs.py` | `nfl_pbp.td_team` does not exist in the dev DB. It needs an update-only backfill (dry run first), and it touches the same ingest file as the research branch's penalty and fumble columns. |
| Published-seed comparison for the bracket check | `backend/nfl_bracket_check.py` (`compare_published_seeds`), `backend/test_nfl_bracket_check.py` (+37 lines) | Check against `dev`'s `nfl_bracket_check.py` first; `dev` rewrote seeding on 10-11. |

## Superseded by `dev` (do not revive)
- WIP seeding, standings, sim, lock and migrate edits: `dev` rewrote all of them on 10-11 (`34d3f98`, `9763658`,
  `3a23d65`, `546ef62`, `844f15a`) after the 10-10 base.
- `backend/nfl_grading.py`: `dev` has `grade_nfl_locks.py`.
- `/api/nfl/game-projections` and `/api/nfl/model-record`: `dev` has `/api/nfl/model/locks` and the Model tab.
  The WIP versions also read `game_projections.market_*` columns that `dev` dropped.
- The WIP edits that deleted `NflModelTab` and replaced `dev`'s `nfl_model` router. Never carry these over.
- `jobs/nfl_weekly_model.py`: ported as `nfl_playoff_odds.py`. Its lock, grade and movers-file steps were
  dropped on purpose (locking is `nfl_lock.lock_week` only; no consumer of the movers file exists on `dev`).

## Dropped on purpose
- `backend/nfl_tune_2024.py`, `test_nfl_tune_2024.py`, `test_record_nfl_backtests.py`: widened the 2024 tuning grid from
  36 to 60 configurations. That grid was pre-registered and frozen before the 2025 holdout; changing it afterwards
  would loosen a fixed rule.
- `backend/ingest_nfl_teams.py` multi-season mode and upsert: not needed for 2026; the old default-path change
  from `picks.db` to `picks.dev.db` is also not carried over.

## Known facts about the original WIP
- Its API test could not be collected on this box (Python 3.8, `int | None` in FastAPI signatures), so it had
  never been run here. The reconciled router uses `Optional`.
