# Plan: NFL data backfill for the model, 2026-10-11

Goal: the data first, then a model on it, graded against the closing spread, total and moneyline.

## How a count is checked

"Published count" below is the row count in the publisher's own file metadata
(`pyarrow ParquetFile(...).metadata.num_rows` for the nflverse release asset, line count for a
CSV), measured on the files downloaded 2026-10-11 into the session scratchpad. After a load, the
stored rows for that (source, season) are counted in the dev DB and printed beside the file
count; any difference stops the load. ESPN is not used as an oracle (standing rule), so
`reconcile_totals.py` is not run.

## Where it goes

New tables only, created by `backend/migrate_nfl_history_tables.py` (idempotent,
`CREATE TABLE IF NOT EXISTS`). No prod code reads them. Rows keep the publisher's ids
(gsis_id, pfr_player_id) rather than our `players` spine, because the existing ingests
(`ingest_nfl_injuries.py`, `ingest_nfl_snap_counts.py`) drop players the spine does not know,
which would make a historical season partial by construction, and they also write
`unresolved_players` and patch `player_game_logs`, tables the app reads. Team codes are mapped
with `team_codes.normalize`, which raises on an unknown code.

## Sources

| Source | Seasons | Table | Published rows (file) |
|---|---|---|---|
| nflverse injuries | 2009-2025 | nfl_hist_injuries | 2009 4,821; 2010 4,491; 2011 4,971; 2012 5,533; 2013 5,070; 2014 5,078; 2015 5,232; 2016 5,115; 2017 5,104; 2018 5,133; 2019 5,392; 2020 5,661; 2021 5,587; 2022 5,682; 2023 5,599; 2024 6,215; 2025 6,068 |
| nflverse snap counts | 2013-2025 (the 2012 file is published with 0 rows) | nfl_hist_snap_counts | 2013 23,799; 2014 23,864; 2015 23,842; 2016 23,890; 2017 23,862; 2018 23,877; 2019 23,862; 2020 24,999; 2021 26,468; 2022 26,381; 2023 26,540; 2024 26,615; 2025 26,613 |
| nflverse depth charts (weekly, old schema) | 2010-2024 | nfl_hist_depth_charts | 2010 38,421; 2011 37,941; 2012 37,312; 2013 37,066; 2014 32,542; 2015 37,058; 2016 36,612; 2017 36,620; 2018 36,560; 2019 36,308; 2020 36,168; 2021 37,487; 2022 37,780; 2023 37,327; 2024 37,312 |
| FTN charting (CC BY-SA 4.0, attribution: FTN Data via nflverse) | 2022-2025 | nfl_hist_ftn_charting | 2022 41,643; 2023 48,225; 2024 48,031; 2025 47,316 |
| 538 NFL Elo archive (`fivethirtyeight/nfl-elo-game`, MIT licence) | 1920-2020 seasons | nfl_elo_538 | 16,810 data lines |
| nflverse PBP | 2010-2025, already loaded | nfl_pbp | checked against the 2010-2023 parquets on disk, REG plays only |

## Not loaded, and why

- Depth charts 2025: nflverse changed the file to dated snapshots with a new schema (554,215
  rows, no week). Not needed for 2011-2024 development; would need its own mapping.
- 538 Elo 2021 onward: the archived repo stops at the 2020 season. Benchmark covers 2011-2020.
- Open-Meteo weather: pre-kickoff forecasts exist only in the historical-forecast archive from
  about 2022; earlier values are reanalysis, i.e. hindsight. nflverse already stores game-time
  temp and wind (also hindsight), and the wind term showed no signal (RESULTS features doc).
  Stadium coordinates are not published by nflverse. Deferred, not guessed.
- PFR advanced stats: not used by any feature below; the Sports Reference terms on reuse were
  not reviewed. Deferred.
- Player stats, team stats, rosters: every feature below is built from PBP, snaps, injuries and
  depth charts, which are loaded. Not needed now.

## Model features (rules pre-registered in the script docstring before any run)

On top of the stacked v1 baseline B from `nfl_points_lines_backtest.py`:
1. QB starter from the published weekly depth chart (QB1 for the game week) in place of the
   previous game's starter; QB quality from pass EPA per dropback.
2. Availability: snap-weighted share of last-4-game snaps held by players listed Out or Doubtful,
   offense and defense separately, 2013 onward (snaps) with 2011-2012 at zero and flagged.
3. FTN play-call tendencies (play action, motion, no huddle): 2022-2023 only for development,
   tested only if the other terms are done; the sample is two seasons.
4. EPA by unit (v2 raw margin), already measured; included in the combined run.
Grading as in `nfl_points_lines_backtest.py`: win Brier vs the moneyline, cover and over Brier
vs the line's 0.5, hit rates, pushes counted, 2011-2023 and 2024 separately, 2025 second look.
