# TASK — swap NFL per-game logs from a pbp derivation to the published nflverse box score

## Context (already established, do not re-litigate)

`backend/ingest_nfl_pbp_logs.py` aggregates 372-column play-by-play into per-player-game
lines. Its docstring justified that with "nflverse's pre-built weekly summary 404s for
2025." **That is false** — the release was renamed `player_stats` → `stats_player`:

```
https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{YEAR}.parquet
```

200 for 2024 and 2025, **145 columns**, containing every field the rollup computes
(including `passing_epa` and `passing_cpoe`). All eight defects found last week were bugs
in a reimplementation of arithmetic nflverse does correctly.

`backend/ingest_nfl_weekly_stats.py` already exists (untracked, ~246 lines, dry-run
clean): a column mapping plus one derived value (`dropbacks = attempts + sacks_suffered`,
verified equal). **Your job is to land it and retire the rollup.**

Two gaps this closes that no further pbp fix would:

1. **The entire 2025 postseason is missing** — weeks 19–22, 258 player-games, zero rows in
   `player_game_logs`. The pbp path has never produced playoff data. The artifact has it
   (POST wk19=398, wk20=280, wk21=137, wk22=67 player-weeks).
2. **`fpts` is still wrong after `4075c2b`** — 312 rows. The hand-rolled scorer at
   `ingest_nfl_pbp_logs.py:261` omits fumbles lost (184 rows), 2pt conversions (83),
   special-teams TDs (15). You named all three in an earlier review; they were not acted on.

## Deliverables

1. **Land `backend/ingest_nfl_weekly_stats.py`** with tests
   (`backend/test_ingest_nfl_weekly_stats.py`, new file — match the style of
   `backend/test_ingest_nfl_pbp_logs.py`). Cover at minimum: group gating (a QB must not
   acquire a zero receiving line), null-vs-zero handling in `_num`, snap/NGS key
   preservation on upsert, and the postseason rows landing.

2. **Fix the latent week-collision hazard.** `_NEEDED` selects `season_type` and
   `build_rows` never uses it. `game_no` is `str(week)`. For 2025 the artifact carries no
   PRE rows and POST weeks continue 19–22, so weeks are globally unique — but that is an
   empirical fact about one file, not a guarantee. Either incorporate `season_type` into
   the key or assert uniqueness explicitly and fail loudly. **Verify 2024 as well.**

3. **Run it for real against the DEV database, 2024 and 2025.** Then report the row diff
   vs. the pre-swap data — how many rows changed, on which fields, and confirm the 258
   postseason player-games now exist and the 312 `fpts` rows now match the artifact.

4. **Retire the rollup half of `ingest_nfl_pbp_logs.py`.** Keep the raw play retention
   (`nfl_pbp`, 46k plays × 50 cols) — that table is genuinely additive. Delete only the
   per-player-game aggregation and its hand-rolled `fpts()`. Prune the corresponding tests
   from `backend/test_ingest_nfl_pbp_logs.py`; do not delete that file.

5. **Update `docs/NFL-DATA-INVENTORY.md`** where it describes `source='nflverse_pbp'` as
   the origin of per-game logs (lines ~29, ~153, ~175).

## Scope lock

**Files you may create or modify — nothing else:**
- `backend/ingest_nfl_weekly_stats.py`
- `backend/test_ingest_nfl_weekly_stats.py` (new)
- `backend/ingest_nfl_pbp_logs.py`
- `backend/test_ingest_nfl_pbp_logs.py`
- `docs/NFL-DATA-INVENTORY.md`

**Do not touch:**
- `backend/espn_client.py`, `backend/ingest_ufc_fight_stats.py`, `backend/ingest_wc_logs.py`
  — your own uncommitted WIP, leave it exactly as-is.
- `backend/ingest_nfl_logs.py`, `ingest_nfl_snap_counts.py`, `ingest_nfl_ngs_receiving.py`
  — shared/adjacent ingests. (`ingest_nfl_logs.ensure_table` is imported; read it, don't
  edit it.)
- `backend/ingest_nfl_schedule*.py` or anything touching `prop_games` /
  `team_game_results` / `game_context` — **Claude is working in there concurrently.**
- Host-level config: `/etc`, systemd units/timers, cron. Worktree isolation does not cover
  these.
- `venv/`, `node_modules/`.

**Process constraints:**
- A dev server is live on `:8095`/`:8096`. **Do not `git checkout`, `git switch`,
  `git reset`, or `git stash`.** Stay on `dev`.
- **Dev DB only.** Export the **absolute** path:
  `export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db`.
  A bare relative `picks.dev.db` silently creates an empty database — there is already a
  0-byte `/root/legendarypicks/picks.dev.db` from someone making exactly that mistake.
  Never point an ingest at the prod DB (`backend/data/picks.db`).
- Cached artifacts, already downloaded — reuse them, don't refetch:
  `/tmp/claude-0/-root/f9798c80-dc52-45bd-ba98-be25c4818df0/scratchpad/`
  (`stats_player_week_2025.parquet` sha256
  `afc45559f6385a3f253887f37efcb1124006db799c91a58d8c7151429136f0cc`,
  `stats_player_week_2024.parquet`, `snap_counts_2025.parquet`). Pass via `--cache-dir`.
- **Commit with explicit paths only** — `git add <exact file>`, never `git add -A` or
  `-u`. Claude is committing to the same branch in parallel; a broad add will pick up
  work that is not yours.
- **One commit per logical slice** (land-the-ingest / retire-the-rollup / docs), not one
  bundle. Do not push — leave that for review.
- **No AI attribution in commit messages.** No `Co-Authored-By`, no "Generated with",
  no tool name anywhere in the message or trailers.
- Run the backend suite before you finish. Baseline is **241 passed, 4 pre-existing
  failures** (`test_league_stats_contract`, 3× `test_nfl_offseason_api`) — those are
  unrelated and expected. Any new failure is yours.

## Definition of done

The swap is diffable and diffed, the postseason exists, `fpts` matches the published
source, the rollup is gone, tests pass, and verification against the numbers is now
tautological — you cannot disagree with your own source.
