# TASK — the destructive 2024 write in `ingest_nfl_logs.py`

## The defect, reproduced

`ingest_nfl_logs.ingest_nfl_logs()` builds `stats = {}` fresh per row (line 87) and writes
it with `INSERT OR REPLACE` (line 95). The conflict key is
`(league, source_player_key, season, game_no)` — the same row that
`ingest_nfl_snap_counts.py` and `ingest_nfl_ngs_receiving.py` write their keys into. So a
re-run does not merge, it **replaces the whole stats blob**, and every snap and Next Gen
key on that row is gone. Same shape as the bug fixed in `866dbf1`.

It also passes literal `None` for `game_id`, `game_date` and `home_away` (lines 99–100),
so REPLACE blanks those columns too. `docs/NFL-DATA-INVENTORY.md:175` already noted this
and called it "not a source limitation."

**Live blast radius, measured against `picks.dev.db` just now — not quoted from a handoff:**

| season | rows | carrying snap keys | carrying NGS keys |
|---|---|---|---|
| 2024 | 5,597 | **5,329** | **1,253** |

`venv/bin/python ingest_nfl_logs.py --season 2024` destroys all 6,582 of those today.

## Read this before you start: the component may not deserve a fix

`ingest_nfl_logs.py` calls `nfl.import_weekly_data([season])`. That is the **same nflverse
weekly dataset** `ingest_nfl_weekly_stats.py` now copies directly from the parquet release.
The differences are that this one filters to `season_type == "REG"` (line 79, so no
postseason), stores raw nflverse column names instead of the mapped `att`/`cmp`/`pass_yds`
vocabulary the app reads, and has the merge bug above.

Current `player_game_logs` state for NFL:

```
2024 | nflverse         |    14
2024 | nflverse_weekly  | 5,583
2025 | nflverse_pbp     |     2
2025 | nflverse_weekly  | 5,633
```

Your `--year 2024` run already took over that season. **14 rows are all that is left of
this ingest's output.** So the question to answer first is the one that governed the swap
you just did: *should this component exist?*

**My read — verify it, do not take it:** this is now a duplicate of the ingest that
replaced it, minus the postseason, plus a data-destroying merge. Retire it the same way
you retired the pbp rollup. Note `ensure_table` lives in this module and
`ingest_nfl_weekly_stats.py` imports it, so the file must survive as a schema module even
if the ingest path goes.

If you find a reason it must stay an ingest, then fix the merge properly — read the
existing row, preserve every key this module does not own, and stop writing `None` over
`game_id`/`game_date`/`home_away`.

## Also: leftover rows from the swap

Two residues where the old source still wins because the published artifact never emitted
those rows, so your upsert never touched them:

- `2025`, `source='nflverse_pbp'`, 2 rows — `00-0036187` wk11, `00-0038953` wk15. Both
  carry real snap data alongside a phantom `targets: 1, rec: 0` from a two-point play the
  published source does not count.
- `2024`, `source='nflverse'`, 14 rows.

Decide what is correct for these and say why. They are the only rows where the database
disagrees with the published source, which is the one thing the swap was supposed to make
impossible. Stripping a stale key while keeping the snap data is probably right; deleting
rows that carry real snap counts is probably not.

## Scope lock

**Files you may create or modify — nothing else:**
- `backend/ingest_nfl_logs.py`
- `backend/test_ingest_nfl_logs.py` (new if absent)
- `docs/NFL-DATA-INVENTORY.md`
- `backend/ingest_nfl_weekly_stats.py` — **only** if retiring the ingest path requires
  moving `ensure_table`, and only that change.

**Do not touch:**
- `backend/espn_client.py`, `backend/ingest_ufc_fight_stats.py`, `backend/ingest_wc_logs.py`
  — your own uncommitted WIP. Leave byte-identical; a release is blocked on them and I am
  not going to commit them for you.
- `backend/ingest_nfl_schedule.py`, `backend/test_ingest_nfl_schedule.py`, and the
  `nfl_schedule` / `team_game_results` tables — mine, landed in `f771751`.
- `backend/ingest_nfl_snap_counts.py`, `backend/ingest_nfl_ngs_receiving.py` — read them to
  learn which keys they own, do not edit.
- Host config: `/etc`, systemd units/timers, cron. `venv/`, `node_modules/`.

**Process constraints:**
- Dev server live on `:8095`/`:8096`. **No `git checkout`, `switch`, `reset`, or `stash`.**
  Stay on `dev`.
- `export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db` — the **absolute**
  path. A relative `picks.dev.db` silently creates an empty database.
- **Back up the 6,582 at-risk rows before any write you cannot undo**, and verify the
  restore path works. Do not prove the bug by running the destructive ingest against the
  dev database.
- `git add <exact paths>` only, never `-A` or `-u`. One commit per logical slice. Do not
  push.
- **No AI attribution** in commit messages — no `Co-Authored-By`, no "Generated with", no
  tool name in the message or trailers.
- Baseline suite: **247 passed, 4 pre-existing failures** (`test_league_stats_contract`,
  3× `test_nfl_offseason_api`). Any new failure is yours.

## Definition of done

Either the ingest is retired and cannot destroy anything, or it merges correctly and a
test proves a re-run preserves snap and NGS keys — checked against a deliberately broken
implementation, so the assertion can actually fail. The 16 leftover rows are resolved with
a stated reason. `docs/NFL-DATA-INVENTORY.md` reflects reality.
