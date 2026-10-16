# Tennis data in the dev DB (updated 2026-10-16)

What tennis data we hold, where it came from, what it covers, and what is still missing. The
first table lists `backend/data/picks.dev.db`; section 6 lists the separate canonical point-event
databases. Nothing here is in prod.

## 1. Tables

| Table | Rows | What it is | Source |
| --- | --- | --- | --- |
| `tennis_atp_matches` | 988,216 | ATP singles match results, 1968 to 2026-06 (all levels) | GitHub mirror, `atp/` |
| `tennis_atp_matches_doubles` | 26,399 | ATP doubles results | GitHub mirror |
| `tennis_atp_rankings` | 3,420,595 | ATP rankings, 2,333 dates, 1973-08 to 2026-06 | GitHub mirror |
| `tennis_atp_players` | 66,912 | ATP player table | GitHub mirror |
| `tennis_atp_source` | 176 | One row per source file: URL, checksums, licence, load audit | GitHub mirror |
| `tennis_points` | 25,314 | Archived match-status and game-sequence records; coverage in section 4 | Flashscore archive |
| `kalshi_tennis_points` | 35,608 | Captured live point events; coverage in section 5 | Kalshi live-data endpoint |
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

## 4. Archived match point histories (dev DB snapshot 2026-10-16)

The `tennis_points` table contains Flashscore archived match pages and point-feed responses from
the `records-browser-v2-postcutoff-20261014` dataset. Counts below use one match-status row per
`(tour, source_match_id)`; the table's tour column is the source archive's bucket.

| Source tour bucket | Match-status rows | With point history | Without point history | Walkover / no points played | Game-sequence rows | History match-date range | History matches with tournament/scoreboard reference |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| ATP | 541 | 406 | 134 | 1 | 9,051 | 2026-07-18 to 2026-10-16 | 406 / 406 |
| WTA | 697 | 691 | 6 | 0 | 15,020 | 2026-06-20 to 2026-08-23 | 691 / 691 |
| ITF | 5 | 0 | 5 | 0 | 0 | — | — |
| **Total** | **1,243** | **1,097** | **145** | **1** | **24,071** | **2026-06-20 to 2026-10-16** | **1,097 / 1,097** |

The 24,071 records are game-level point-score sequences, not 24,071 individual point rows. The
source progression is kept in `sequence_text` and `raw_json`; structured per-point winner and
server fields are not populated for these records.

A read-only reconstruction audit found a strict lower bound of 24,010 game rows that can be expanded
to 154,887 individual point outcomes. It accepts a row only when its initial point, every displayed
score transition, server/winner codes, and inferred terminal point all agree. All rows in 1,045 of
the 1,097 matches pass; 52 matches contain one or two rejected game rows. The raw sequences have
not been replaced or expanded in the database because complete match chronology, especially
tiebreak coverage, is not established. See the [sequence audit](../research/tennis/point-events/2026-10-16/flashscore_sequence_audit.json)
and [audit script](../research/tennis/point-events/2026-10-16/audit_flashscore_sequences.py).

All 1,097 ATP/WTA matches with point history now have confirmed tournament references. Of the
previously linked 239 (107 ATP, 132 WTA), one additional match was matched to the local ESPN
scoreboard by player names and final set scores; its scoreboard date is one UTC day earlier than
the archive date. The remaining 857 were resolved from each match's own Flashscore page after both
players matched the page title. Their source tournament path and category are retained in
`tournament_id` and in the [per-match evidence CSV](../research/tennis/point-events/2026-10-16/flashscore_tournament_resolution_2026-10-16.csv);
`tournament_source` is `flashscore_match_page`. The source `tour` bucket was left as ingested. The
page category shows that 124 of the 298 ATP-bucket histories belong to other categories: 49 ITF
women's, 31 ITF men's, 26 Challenger men's, 10 WTA singles, and 8 Challenger women's; all 559
WTA-bucket histories are labeled WTA singles. Use the page category evidence when distinguishing
the actual event tour. There are 138 ATP/WTA status rows without point history whose tournament
reference remains blank. This archive currently covers ATP match dates from July 18 through
October 16, 2026, and WTA dates from June 20 through August 23, 2026. The five ITF records have no
point history.

These are archive-dataset counts, separate from `usopen_points` and `kalshi_tennis_points` below.
Their match identifiers are source-specific, so the counts should not be added as a unique
cross-source match total.

## 5. Shanghai and Wuhan (live points)

- Points come from Kalshi's live-data endpoint, polled every 4 seconds by `kalshi_live_points.py`
  in prediction-market-trading. Output is `data/orderflow/KALSHI_POINTS_YYYYMMDD.jsonl`.
- Kalshi gives no per-point timestamp, so each point is stamped at the first poll that shows it.
  That is up to 4 seconds late, never early.
- `kalshi_tennis_points` in the dev DB contains 35,608 point rows across 268 source match IDs
  (19,854 rows / 148 ATP matches and 15,754 rows / 120 WTA matches), dated October 3 to 16,
  2026 UTC. This is the captured live-data window, not a complete historical archive.

## 6. Canonical point-event databases

These four standalone SQLite databases are under `backend/data/tennis_point_archives/`. They are
separate from `picks.dev.db` and from its `tennis_points`, `usopen_points`, and
`kalshi_tennis_points` tables. Each file has the same `tennis_point_sources`,
`tennis_point_matches`, and `tennis_point_events` schema. Match rows hold player names, event,
date, tournament, and source match ID. Event rows hold source sequence, server and point winner
codes and resolved names where available, score before/after, event type, timestamps where the
source provides them, and the original record in `raw_json`. The shared event columns are
`source`, `source_dataset`, `source_match_id`, `sequence_no`, `point_server`/`point_server_name`,
`point_winner`/`point_winner_name`, `score_before_json`, `score_after_json`, `event_type`,
`event_time_start_utc`, and `event_time_end_utc`. Join `source_match_id` to the match table for
players and tournament. Setup/status rows are kept with `is_point=0`.

| Database | Source rows | Point outcomes | Match records | Matches with point rows | File size |
| --- | ---: | ---: | ---: | ---: | ---: |
| `grand_slam_archive.db` | 2,314,887 | 2,300,770 | 13,154 | 13,142 | 5.46 GB |
| `match_charting_project.db` | 1,877,757 | 1,877,757 | 11,822 | 11,785 | 2.20 GB |
| `usopen.db` | 107,132 | 106,876 | 699 | 699 | 240 MB |
| `kalshi.db` | 35,608 | 35,608 | 268 | 268 | 151 MB |

The Grand Slam archive has 83 point files and 83 paired match files from 2011–2024. Its played
point outcomes include ATP, WTA, and mixed events; another 14,117 setup/status or incomplete rows
are retained. Thirty-two match rows referenced by point files have at least one participant name
missing in the source metadata. The Match Charting Project contributes 1,877,757 individual point
rows from 11,785 matches with point data. Its source metadata has 37 additional matches without
point rows. The exact year, tournament, event-category, match, row, and point counts are in the
[point archive coverage manifest](TENNIS-POINT-ARCHIVE-COVERAGE-2026-10-16.csv).

Grand Slam tournament coverage is Australian Open, French Open, US Open, and Wimbledon in
2011–2019 and 2021; Australian Open, French Open, and US Open in 2020; and US Open plus Wimbledon
in 2022–2024. Event-category coverage varies by year: singles are the broadest set, while doubles
and mixed-doubles rows appear in later files. The manifest lists each category and count. Match
Charting spans 1960–2026 and has 595 distinct tournament labels as supplied in its source metadata;
the manifest lists those labels by year. These are source labels, not a de-duplicated tournament
identity system.

The US Open database copies the existing 2026 capture and official-history rows, including 256
non-point status records. It has 699 source match IDs across the event categories represented in
those feeds. The 254 main-draw singles histories described in section 3 are present, but canonical
metadata explicitly identifies 157 as singles (82 ATP, 75 WTA). The other 127 official-history IDs
are preserved with unknown tour/category and blank player names, so they cannot yet be used for
player-specific cross-source evaluation. The Kalshi database
contains 268 ATP/WTA match IDs from October 3–16, 2026 UTC, from ATP Beijing, ATP Shanghai, ATP
Tokyo, WTA Beijing, and WTA Wuhan. Tournament and year coverage for these sources is also in the
manifest.

For score timing, the Grand Slam and US Open sources report the post-point score; the before-score
is carried forward within the same game, with 0–0 at a new game. Match Charting and Kalshi report
the pre-point score. Match Charting's `Pt` field is the point order; 2,080 matches had source CSV
rows out of chronological order, so canonical `sequence_no` follows `Pt`. Fourteen matches have
repeated point numbers, and fourteen do not cover a continuous 1-to-N point range; exclude these
cases from analyses that require a complete point chronology. The Match Charting `Pts` field is
server/returner oriented; the canonical
player-one/player-two score is resolved using `Svr`. `set_no` and within-set `game_no` are derived
from the source set and game tallies. Original source fields remain in `raw_json`. After-scores are
filled only when the next chronological point number is consecutive; gaps and terminal points keep
a null after-score. This filled 1,863,347 Match Charting and 33,131 Kalshi after-scores. The US Open
point timestamps are from its source epoch fields. Kalshi timestamps are poll-observation times, up
to four seconds late. The historical archives do not provide point-level timestamps; Match Charting
has match dates only.

### Walk-forward simulation and direct-model evaluation (2026-10-16)

The evaluation crosswalked complete point histories to main-tour results by tour, year, tournament,
and both player names. After removing 968 duplicate source histories, the verified pool contained
13,023 matches: 6,174 selected from the Grand Slam archive and 6,849 from Match Charting. The US
Open and Kalshi captures are later than the available result archive, so they contribute point-label
and score-state checks but not match-winner test cases. Match-winner forecasts were calibrated on
2021 (623 matches) and tested on 2022–2024 (2,749 matches), with same-day matches forecast before
that day's data updates.

Calibration fits explicitly include both player orders and complementary outcomes. This prevents the Match Charting
source's side-one win rate (53.2%, versus 50.9% in the Grand Slam archive) from becoming a side preference in the direct
model's calibrated probability. The fitter checks that the paired data produce a zero intercept.

On held-out matches, Elo's Brier score was 0.20878, the point-level simulator's was 0.22273, and a
direct point-count logistic model that does not simulate the match scored 0.22336. The direct
model's paired Brier difference from Elo was +0.01458 (95% tournament-cluster interval +0.00610 to
+0.02208); the simulator's difference from Elo was +0.01396 (+0.00562 to +0.02171). The direct
model and simulator were effectively tied with each other. Applying the same 2021 calibration to
Elo lowered its test Brier to 0.20691; the direct model's paired difference from calibrated Elo was
+0.01645 (+0.00962 to +0.02241). Point-count estimates did slightly
improve point-outcome Brier over a surface-only baseline (0.23411 vs 0.23533, averaged within each
of 3,667 matches), but this did not improve match-winner forecasts. Keep Elo as the match forecast
incumbent; keep the direct model and simulator in research.

Point-level ace and double-fault flags were not used as features in the match-winner or simulator
evaluation. Separately, the broader main-tour match-stat archive supports walk-forward ace and
double-fault count forecasts. Their 2022–2024 threshold Brier comparison, alongside match-winner
and total-games Brier scores, is recorded in the [cross-target Brier report](../research/tennis/point-events/2026-10-16/prop_brier_comparison.md).
The point-event flag captures remain useful for future score-state and event-level diagnostics;
Match Charting lacks ace/DF labels, and the 2026 US Open/Kalshi captures do not yet have matched
final outcomes.

The simulator also produced longer matches than observed: 24.50 vs 22.14 total games on average
(+2.36 games; 95% tournament-cluster interval +2.12 to +2.59), and a deciding-set rate of 45.8% vs
31.0% (+14.9 percentage points; +13.1 to +16.6). Its expected set length was 9.96 games vs 9.54
observed (+0.43; +0.37 to +0.48). Service-game outcomes were reconstructed only
for matches whose counts matched official service-game totals (3,255 of 3,667 histories). In that
validated subset, predicted hold rate was 75.7% vs 74.1% observed, corresponding to a predicted
break rate 1.6 points too low. The full report includes set-game-length distributions, score-state
conditional point results, source coverage, and tournament-level model scores:
[four-archive point model and simulator audit](../research/tennis/point-events/2026-10-16/findings.md)
and [tournament-level scores](../research/tennis/point-events/2026-10-16/tournament_scores.csv).
Uncertainty is clustered by tournament; point observations are not treated as independent matches.
In both historical sources, the model's predicted server point-win rate at break points was above
the observed rate (61.4% vs 59.1% in the Grand Slam archive; 60.7% vs 58.8% in Match Charting).
These are descriptive point summaries without point-level confidence intervals. They suggest a
candidate gap in the simulator's score-independent point probabilities, consistent with the
observed excess holds; the match and tournament backtests are the basis for uncertainty estimates.

The Grand Slam archive mirror and Match Charting Project source files are pinned to commits
`83733587353df8a41f2fd4f516147d5aa83f5a8d` and
`1813a1309b7ed7ebf1c7e884b32bf675d00e4edf`. Both identify their data as CC BY-NC-SA 4.0, so the
imported material is for non-commercial use with attribution and share-alike terms. The US Open
and Kalshi capture terms have not been assessed. Loaders: `backend/ingest_historical_tennis_point_events.py`,
`backend/ingest_canonical_live_tennis_points.py`, and
`backend/normalize_tennis_point_score_events.py`.

## 7. Sources checked and not used

- **tennistemple.com:** returns 403 to this box. Not used.
- The Grand Slam point-by-point archive and Match Charting Project are loaded; see section 6.
- **TennisLive, Enetpulse, Goalserve:** TennisLive has point progressions, and the two commercial
  feeds sell live point data. None has been checked for licence or cost.

## 8. Open items

- Link ATP and WTA player IDs to LP players. The tennis spine docs say TennisExplorer and the WTA
  API; the scoreboard uses ESPN. Neither system links to the other yet.
- Fix the ATP data issues in the plan (keys, rankings conflicts, `R`, levels, player links).
- Review the 138 ATP/WTA status rows without point histories and decide whether they need
  tournament references; review the source-tour/category mismatches before using these rows in
  canonical tour-level analyses.
- Calibrate ace and double-fault projections from source-supported event flags; Match Charting
  does not provide these fields. Main-tour count-projection candidates now have historical Brier
  comparisons; point-event flags still need source-specific player and outcome links for a separate
  score-state model.
- Decide how Kalshi live points reach the scoreboard (`docs/PLAN-tennis-points-scoreboard-2026-10-13.md`).
- Decide whether to fetch doubles and the other main-draw events from the US Open feed.
- The 284 US Open match IDs in `usopen_points` that are missing from the match index.
- The full integrity check on the live dev DB was started in the background. Record its result.
