# TASK — put the game-id vocabulary guard at the boundary, not in one script

**Owner:** delegated (deepseek, hermes pane) · **Effort:** small · **Priority: do before the NFL season firms up.**

Work in `/root/legendarypicks`, absolute DB paths, never a worktree. Back up with
`VACUUM INTO`, never `cp` — a plain copy of a live database races writers and produces a
torn snapshot.

---

## The defect

A **game id is a vocabulary boundary with no boundary module.** NFL 2024 and 2026 are keyed
nflverse-style (`2024_01_BAL_KC`); 2025 is keyed by ESPN event id. `team_game_results` has
`PRIMARY KEY(league, game_id, team)`, so an ESPN-keyed write lands **beside** the nflverse
row for the same game rather than over it.

That already happened: a 2024 run took the season from **285 games to 557** while printing
`"wrote 272 games"`. The row count was true and the claim it implied was false.

`season_keys.py` and `team_codes.py` exist because a wrong key does not raise — it *misses*.
A wrong **game** key does something worse: it inserts, and the season silently doubles.

## Why this is urgent rather than tidy

NFL 2026 schedule and results refreshes will run repeatedly over the next weeks as the
season firms up. The guard exists in exactly one script — the one that already caused the
bug — and its two siblings can still trigger it with no code change at all.

## What to do

`backfill_nfl_postseason.py:133-152` already implements the guard correctly. **Port it, do
not reinvent it.** It reads the distinct `game_id`s for the target `(league, season)`,
detects foreign-vocabulary rows, refuses to write, and gates migration behind an explicit
`--replace-vocabulary` flag, because migrating a vocabulary is a delete-then-write decision
and never a side effect of a backfill.

Two writers are missing it:

* **`backend/ingest_team_results.py`** (writes at ~line 137)
* **`backend/backfill_team_parity.py`** (writes at ~line 271)

Also check and report — do not fix in this task — whether `team_game_stats` needs the same
thing. It shares `game_id` with `team_game_results` and none of its writers
(`backfill_team_stats.py`, `backfill_team_stats_fixture.py`, `stamp_team_result_source.py`,
`_core.py`) check vocabulary either.

**Put the check in one shared place** rather than pasting it a third and fourth time —
`team_codes.py` and `season_keys.py` are the precedent for where a boundary check lives. A
guard copied into N scripts is N places to forget it; that is the entire lesson of this bug.
If a shared home is genuinely wrong here, say why in the commit message.

`ingest_nfl_schedule.py:195-250` is the good counter-example to read first: it upserts with
`COALESCE` on `ON CONFLICT(league,game_id,team)`, never blanks a real score, and states its
vocabulary-ownership decision in the docstring instead of assuming one.

## Constraints

* **Do not migrate any season's vocabulary.** This task adds a refusal; it changes no
  existing row. `--replace-vocabulary` must exist and must not be used here.
* Do not touch `season_keys.py`'s translation or `team_codes.py`'s team aliases — both are
  lossless and correct.
* No Docker, no host config (`/etc`, systemd, cron). The props timers write to prod every
  30 min; if a run collides with one, say so rather than retrying blindly.
* Commit locally, do not push. One commit.

## Done means

* Both scripts refuse to write into a season holding a foreign game-id vocabulary, and the
  refusal is **proved** — construct the case in a scratch copy and show the refusal, do not
  assert it.
* Current row counts unchanged on prod and dev: every `(league, season)` still has exactly
  2 rows per `game_id`. Measure before and after.
* Full `pytest` green, with a test covering the refusal.
* `diff_databases.py` shows no new SCHEMA or SEASONS rows.

Report between `===RESULT===` and `===END===`: what you changed, where you put the shared
check and why, the constructed proof of the refusal, before/after counts, the
`team_game_stats` finding, `git log --oneline -2`. Then stop.
