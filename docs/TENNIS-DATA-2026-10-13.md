# Tennis data in the dev DB (2026-10-13)

What tennis data we hold, where it came from, what it covers, and what is still missing. The
state described here is the dev DB (`backend/data/picks.dev.db`). Nothing here is in prod.

## 1. Tables

| Table | Rows | What it is | Source |
| --- | --- | --- | --- |
| `tennis_atp_matches` | 988,216 | ATP singles match results, 1968 to 2026-06 (all levels) | GitHub mirror, `atp/` |
| `tennis_atp_matches_doubles` | 26,399 | ATP doubles results | GitHub mirror |
| `tennis_atp_rankings` | 3,420,595 | ATP rankings, 2,333 dates, 1973-08 to 2026-06 | GitHub mirror |
| `tennis_atp_players` | 66,912 | ATP player table | GitHub mirror |
| `tennis_atp_source` | 176 | One row per source file: URL, checksums, licence, load audit | GitHub mirror |
| `usopen_points` | 107,132 | 2026 US Open point-by-point, all rows | see section 3 |
| `player_game_logs_usopen` | 416 | US Open player game logs, 2026 rounds 1 to 3 | usopen.org |

`usopen_points` columns: `source` (`capture` or `history`), `source_file`, `match_id`,
`point_id` (blank for non-point rows), `is_point`, the score and sequence fields, and `raw_json`
(the full original record). The unique index on `(source, match_id, point_id)` covers real
points only.

## 2. ATP history (GitHub mirror)

- **Source:** `AngieXuAU/tennis-point-by-point-archive`, folder `atp/`. The mirror says it copies
  Jeff Sackmann's `tennis_atp` repo. The upstream repo returned 404 through the GitHub API, so the
  copy is not verified against upstream.
- **Licence:** CC BY-NC-SA 4.0. Non-commercial use only, with attribution, and any redistribution
  under the same licence. Recorded on each `tennis_atp_source` row.
- **Coverage:** 988,216 singles rows. Serve stats (aces, double faults, service points, first
  serves, break points) are present on about 259,680 rows. Most rows are lower-level events
  (futures, challengers, amateur), so tour-level serve stats are a minority.
- **Latest data:** 2026-05-25 for tour-level matches, 2026-06-08 for rankings. Nothing after June.
- **Levels:** `G` Grand Slam, `M` Masters 1000, `A` other tour-level, `F` tour finals, `C`
  challenger, `15` and `25` ITF futures (from 2020), `S` satellites (to 2019), `D` Davis Cup,
  `O` one Olympics date (2024). Tour level for our purposes is `G`, `M`, `A` and `F`. Confirm against
  the ATP's own definition before a model depends on it.
- **Backup:** `backend/data/backups-tennis-20261013/`. Taken before the load finished, so it can
  undo the whole load, not a single fix.

Known issues, from the Opus review and the Haiku load report, are in
`docs/PLAN-atp-data-fixes-2026-10-13.md`. The main ones: no primary keys, 780 date-and-player pairs
that appear twice in rankings (580 with conflicting values), 1,582 text `R` values in `draw_size`,
and no link to LP player IDs.

## 3. US Open 2026 points

### What was captured, and how it was fixed

- **Capture (Sep 2 to 13):** `usopen_points.py` in prediction-market-trading polled live matches
  and wrote every new point. It kept a list of seen points for de-duplication, capped at 60,000
  keys. Once a tournament passed that size, the list dropped old keys, and each later poll
  re-wrote them. Files from Sep 14 to Sep 21 were about 4 GB of repeats of a single match.
- **Fix:** the cap was removed, a corrupt or unwritable list now raises an error, and the list was
  rebuilt from the clean data. Regression tests: `test_usopen_points_seen.py`. The fix is
  uncommitted in prediction-market-trading. The capture job is not running.
- **Clean file:** `USOPEN_POINTS_dedup_20260902_20260921.jsonl` (84,173 points, 572 matches). The
  20 duplicate-laden files were deleted after this file was written.

### Official history feed

- **Access:** the feed answers the trade desk's own client (urllib with the script's User-Agent). The
  same URLs fail with `curl` from this box. The request was made as the script makes it.
- **Endpoints used:**
  - `/en_US/json/gen/config_web.json` lists the feed paths.
  - `/en_US/scores/feeds/2026/draws/MS.json` and `WS.json` give the singles draws (127 matches each).
  - `/en_US/scores/feeds/2026/completed_matches/eventDays.json` lists the day files.
  - `/en_US/scores/feeds/2026/slamtracker/history/<matchId>C.json` gives every point of a match.
- **Fetched:** the 127 main-draw singles matches the capture did not see. 22,959 rows, no errors.
  Each row has 57 fields.
- **Non-point rows:** 256 rows have a blank `PointID` (arrivals, warm-ups, match end). They are
  kept with `is_point = 0`. Real point IDs are unique within every match.
- **Check:** in every match, the last point's winner agrees with the set count.

### Coverage

| Event | Status |
| --- | --- |
| Men's and women's singles main draw (254 matches) | all matches have point data |
| Doubles (main draw), qualifying, junior, wheelchair | not loaded |

Draw sizes for the singles main draw are 128 players, so 127 matches per gender.

### Loader

`backend/ingest_usopen_points.py`, committed in `b0935f2`. Dry run by default; `--apply` writes.
It refuses any database that is not `picks.dev.db`, loads both sources in one transaction, and
refuses to run if `usopen_points` already has rows. The capture file path is in the
prediction-market-trading repo, and the history files are in a scratch directory, so the loader
depends on both. Move the history files into the repo before relying on the loader again.

## 4. Shanghai and Wuhan (live points)

- Points come from Kalshi's live-data endpoint, polled every 4 seconds by `kalshi_live_points.py`
  in prediction-market-trading. Output is `data/orderflow/KALSHI_POINTS_YYYYMMDD.jsonl`.
- Kalshi gives no per-point timestamp, so each point is stamped at the first poll that shows it.
  That is up to 4 seconds late, never early.
- These rows are not yet in the dev DB.

## 5. Sources checked and not used

- **tennistemple.com:** returns 403 to this box. Not used.
- **Grand Slam point-by-point, 2011 to 2024:** in the mirror's `slam_pointbypoint/` folder
  (166 files). Not downloaded. Same licence as the ATP data.
- **TennisLive, Enetpulse, Goalserve:** TennisLive has point progressions, and the two commercial
  feeds sell live point data. None has been checked for licence or cost.

## 6. Open items

- Link ATP and WTA player IDs to LP players. The tennis spine docs say TennisExplorer and the WTA
  API; the scoreboard uses ESPN. Neither system links to the other yet.
- Fix the ATP data issues in the plan (keys, rankings conflicts, `R`, levels, player links).
- Load Shanghai and Wuhan points into the dev DB, and decide how they reach the scoreboard
  (`docs/PLAN-tennis-points-scoreboard-2026-10-13.md`).
- Decide whether to fetch doubles and the other main-draw events from the US Open feed.
- Decide whether to download the Grand Slam history from the mirror.
- The 284 match IDs in the points data that are missing from the match index.
- The full integrity check on the live dev DB was started in the background. Record its result.
