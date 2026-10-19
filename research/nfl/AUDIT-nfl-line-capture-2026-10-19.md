# AUDIT: NFL pre-kickoff line capture (2026-10-19)
This is a data-plumbing audit, not a model result, and it changes nothing about the gates.

## Method
Read-only (`sqlite3 file:...?mode=ro`) on the dev DB, base `d007e540`, worktree
`/root/lp-nfl-lines`, branch `research/nfl-line-capture-audit-2026-10-19`. No writes, no
`--write`, no scheduler, no edits to capture scripts, `nfl_lock.py`, model code or gates.
Kickoff = `check_nfl_schedule_scores.kickoff_utc(gameday, gametime)` (US Eastern → UTC);
`captured_at` is parsed as UTC; raw strings are never compared across the two clocks.

## Inventory (2026)
| Source | Writer | Rows | Games | Captures | Range (UTC) | Locked |
|---|---|---|---|---|---|---|
| `bovada` | `capture_nfl_game_lines.py` | 2 | 2 | 1 | 2026-10-11T21:46:48Z | 0/2 |
| `theoddsapi:draftkings` | `capture_odds_api_nfl.py` | 5 | 5 | 1 | 2026-10-11T22:01:32Z | 0/5 |
| `nflverse` | `nfl_lock.py` `_snapshot` | 42 | 13 | 6 | 2026-10-15T22:45Z .. 2026-10-18T22:50Z | 41/42 |
| **Total** | | **49** | **18** | **8** | 2026-10-11T21:46Z .. 2026-10-18T22:50Z | 41/49 |
20 distinct `(game_id, source)` pairs. The 7 Bovada/OddsAPI rows are independent captures, not
lock lines; the one unreferenced nflverse row is snapshot 38 below.

## Coverage, 2026 weeks 1-6
| Week | Schedule REG | Games with snapshot | Rows | Coverage |
|---|---|---|---|---|
| 1 | 16 | 0 | 0 | 0% |
| 2 | 16 | 0 | 0 | 0% |
| 3 | 16 | 0 | 0 | 0% |
| 4 | 16 | 0 | 0 | 0% |
| 5 | 15 | 5 | 7 | 33.3% |
| 6 | 14 | 13 | 42 | 92.9% |
| **1-6** | **93** | **18** | **49** | **19.4%** |
Weeks 5-6 alone: 18/29 = 62.1%. Week 5's 10 missing games all kicked off before the one-off
22:01Z capture (Thursday, London 09:30 ET, and the 13:00 ET window). Week 6's only missing game
is `2026_06_WAS_SF` (Monday 10/19 20:15 ET), not yet locked at audit time. Weeks 1-4 have zero.

## Duplicates and why
`nflverse` has 3 rows per game per lock run, not one: the three model versions (`nfl-v1`,
`nfl-epa-v2`, `nfl-v1+elo`) each call `nfl_lock.py` `_snapshot` with the same `captured_at`
(the batch `as_of`). 13 games x 3 = 39, plus a second lock run for `2026_06_ARI_LA`
(18:40 and 18:55) adds 3, giving 42; the 18:55 v1 row (id 38) is orphaned because v1 was already
locked at 18:40. There are 14 exact duplicate groups `(game_id, source, captured_at)` of 3 rows;
no unique key and no upsert, every writer uses plain `INSERT`. Bovada/OddsAPI have one row per
game and one run each. The grain is "one row per writer call", not per game/source/capture.

## Was every snapshot captured before kickoff?
No. 15/18 games have every snapshot before kickoff (leads +70 to +1573 min). Three have their
only capture after kickoff, all from the single Odds API run at 22:01:32Z:
| Game | Kickoff (UTC) | Last capture (UTC) | Lead |
|---|---|---|---|
| `2026_05_DEN_LAC` | 2026-10-11 20:05 | 2026-10-11 22:01 | **-116.5 min** |
| `2026_05_DET_ARI` | 2026-10-11 20:25 | 2026-10-11 22:01 | **-96.5 min** |
| `2026_05_SF_SEA` | 2026-10-11 20:25 | 2026-10-11 22:01 | **-96.5 min** |
Root cause: `capture_odds_api_nfl.py` matches unscored games (`home_score IS NULL`), which
includes games in progress because scores stay NULL until final; it never checks kickoff.
`capture_nfl_game_lines.py` has the same filter, but its one run happened to catch only
pre-kickoff games. `nfl_lock.py` is guarded (`kickoff <= now` is "started", never written), so
all 42 nflverse rows are pre-kickoff by construction.

## Provenance mismatch: schedule vs latest snapshot
`nfl_schedule.source` is `nflverse_games`, `ingested_at` is `2026-10-19 10:00:01` for all
18 games — after every game. The schedule line is a post-game/closing refresh, not a
pre-kickoff line. The latest snapshot is the lock-time/capture line. Different times, often
different sources; not interchangeable.
| Comparison (latest snapshot per game) | Games differing |
|---|---|
| Home or away moneyline | 15/18 (11 nflverse, 4 theoddsapi) |
| Spread line | 6/18 (2 nflverse, 4 theoddsapi) |
| Total line | 8/18 (3 nflverse, 5 theoddsapi) |
| Any of the above | 18/18 |
Excluding the three in-play rows, magnitudes are moneyline 2-202, spread 0.5-3.0, total 1.0.
Including them: moneyline max 1,525 (DET_ARI home; 9,735 away), spread max 13, total max 10.
Those three rows are in-play prices (e.g. DET_ARI home ML 1740 vs schedule 215; SF_SEA 214 vs
-166), not valid pre-kickoff comparisons; they inflate the tail, not the typical gap. The
nflverse week-6 rows differ from the 10/19 refresh by up to 202 because the schedule moved after
the 90-minute lock. `source_ingested_at` is also inconsistent: nflverse rows carry the schedule's
lock-time stamp (`2026-10-15 20:22:36`, `2026-10-18 10:00:01`, `2026-10-18 20:56:30`;
space-separated, no timezone); capture rows carry ISO UTC `+00:00`.

## Writers and provable cadence
1. `capture_nfl_game_lines.py` — Bovada, source `bovada`, dry-run by default, `--write` inserts.
   One run 2026-10-11T21:46:48Z (2 games); no recurring cadence provable.
2. `capture_odds_api_nfl.py` — The Odds API, source `theoddsapi:<book>` (here `draftkings`),
   3 credits/run, dry-run by default, `--write` inserts. One run 2026-10-11T22:01:32Z (5 games);
   no recurring cadence provable.
3. `nfl_lock.py` `_snapshot` — copies the nflverse schedule line at lock time, source
   `nflverse`, one row per model version per game. Six lock runs tied to 90-minute pre-kickoff
   windows: 10/15 22:45; 10/18 12:00, 15:30, 18:40, 18:55, 22:50. This is the lock job, not a
   line-capture feed, and it covers only games being locked.
`test_home_featured.py` and `test_nfl_lock.py` use test fixtures, not the dev DB. No cron,
timer, systemd unit or job-runner reference to either capture script exists in the repo; only
their own docstrings/usage lines. The timestamps prove one-off manual runs, not a schedule.

## What a recurring pre-kickoff capture would need (proposal only — do not install)
1. **Which script:** `capture_nfl_game_lines.py --write` primary (Bovada, free);
   `capture_odds_api_nfl.py --write` secondary (3 credits/run) if Bovada lacks a game. Do not
   use `nfl_schedule` lines as the pre-kickoff record; they refresh after games.
2. **How often:** every 15-30 minutes from ~24h before the first kickoff of the slate to the
   last kickoff, or hourly across the weekend. One run covers the whole coupon; a game-aware
   window is cheaper than a 24/7 fixed interval.
3. **Pre-kickoff guard:** filter `kickoff_utc(gameday, gametime) > now` in both scripts before
   writing; that removes the three in-play rows and makes the property true by construction.
4. **Idempotency:** unique `(game_id, source, captured_at)` (or `run_id` +
   `(game_id, source, run_id)`) with `INSERT ... ON CONFLICT DO NOTHING`; a retry must not
   duplicate. For the lock path, write one snapshot per game per run and share it across the
   three projections, or add `run_id`/`model_version` so the three rows are distinguishable.
5. **Monitoring:** per-week coverage (games with a pre-kickoff snapshot / scheduled) and a hard
   post-kickoff check (`COUNT(*) WHERE captured_at >= kickoff` must be 0).
6. **Scheduling itself:** a systemd timer or the existing job runner is Micah's call; this audit
   installs nothing.

## Reproduce
```
sqlite3 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro' \
  "select source, count(*), count(distinct game_id), min(captured_at), max(captured_at)
   from nfl_line_snapshots group by source;"
```
For kickoff checks, join to `nfl_schedule` on `game_id`, convert `gameday` + `gametime` with
`check_nfl_schedule_scores.kickoff_utc`, and compare each `captured_at` to that kickoff; never
compare raw strings. The per-game and provenance tables are reproducible from the same dev DB.
