# NFL contextual simulation, Phase 0: candidate feature inventory (2026-10-26)

Phase 0 of the contextual full-game spec (section 15): inspect the data before any predictive change. Nothing in the
simulator was changed by this inventory. Sources were read without writes: the dev database `picks.dev.db` (opened
read-only) and the nflverse play-by-play parquet files for 2022-2025 under `/root/nflverse-raw`.

Terms used below. "As-of" means the source records when a value was known. "Ingest stamp" means the time a row was loaded
into this database, which proves nothing about when the value was published.

## 1. Candidate features and their sources

| Spec feature (section) | Source table(s) | Seasons | As-of stamp | Pregame use |
|---|---|---|---|---|
| Game identity: season, week, season type, kickoff, home/away (4.1) | `nfl_schedule` (`game_type`, `gameday`, `gametime`, `location`) | 2010-2026 | `ingested_at` 2026-07-27 onward (backfill) | Yes. `gametime` has no timezone; keep the raw string. |
| Team record before kickoff (4.1) | `team_game_results` (`result`, `game_date`); `nfl_schedule` | 2010-2026 | `ingested_at` 2026-07-14 onward (backfill) | Yes, filtered by `game_date` before the kickoff date. |
| Points scored and allowed (4.1) | `nfl_schedule` scores; `team_game_results` (`score_for`, `score_against`) | 2010-2025 complete | backfill stamp | Yes, with the same date filter. |
| Yards per play, efficiency, explosive plays, red zone, pace (6.1) | `nfl_pbp` (`yards_gained`, `play_type`, `yardline_100`, `down`, `ydstogo`, `game_seconds_remaining`, `air_yards`) | 2010-2026 (2026 weeks 1-7) | none (retrospective; `game_date` only) | Yes, derived per game and filtered by `game_date`. |
| Turnovers, sacks, pressure (6.1) | `nfl_pbp` (`interception`, `fumble_lost`, `sack`, `qb_hit`) | 2010-2026 | none | Yes, same filter. |
| Expected starting QB (4.1, 6.1) | `nfl_schedule` (`home_qb_id`, `away_qb_id`, names); `nfl_depth_chart`; `nfl_hist_depth_charts` | schedule 2010-2026; depth 2026 only (`nfl_depth_chart`); historical depth 2010-2024 | `nfl_depth_chart.snapshot_at` (2026) is as-of; the others have no as-of stamp | Schedule QB ids: not verified (see risk 2). Depth chart: 2026 only. |
| Roster and position roles (4.1) | `roster_snapshots` (`captured_at`, `published_at`); `roster_snap`; `nfl_hist_depth_charts` | roster 2026-2027; historical depth 2010-2024 | roster: yes (2026 onward) | 2026 only for as-of roster; history is approximate. |
| Verified availability and injuries (4.1) | `injury_reports` (`date_modified`, `ingested_at`); `nfl_hist_injuries` (`date_modified`); `player_game_availability` | `injury_reports` 2024-2026; `nfl_hist_injuries` 2009-2025 | `injury_reports.ingested_at` 2026-10-09 to 2026-10-20 only; history has `date_modified` only | Limited. See risk 6. |
| Snap shares and workload (6.1) | `nfl_hist_snap_counts` (game level); `nfl_snap_counts` | `nfl_hist_snap_counts` 2013-2025; `nfl_snap_counts` 2024-2026 | none in history | Yes for history at game level. |
| Division, standings, situation (4.1) | `nfl_schedule.div_game`; `nfl_teams` (division) | `div_game` 2010-2026; `nfl_teams` 2024-2026 | none | `div_game` yes. Standings must be derived from results. |
| Venue and home field (4.1) | `nfl_schedule` (`location`, `home_team`, `roof`, `surface`, `stadium`) | 2010-2026 | none | Yes for roof and surface. |
| Rest days (6.1 context) | `nfl_schedule` (`away_rest`, `home_rest`) | 2010-2026 | none | Yes. |
| Stakes (4.1, experimental) | `game_story` (`has_stakes`) | NFL: 156 stories, `has_stakes` = 0 on all of them | `generated_at` 2026-07-21 onward | No. Not available for NFL. |
| Weather (4.1, deferred in V1) | `nfl_schedule` (`temp`, `wind`) | 2010-2026 | none | No. These are game-time observations, so using them pregame leaks. |
| Market lines (evaluation baseline) | `nfl_line_snapshots` (120 rows, three sources); `nfl_schedule` (`spread_line`, `total_line`, moneylines) | snapshots 2026-10-11 to 2026-10-25; schedule lines 2010-2026 | snapshots: `captured_at`; schedule lines: none | Snapshots only, and only for 2026. |
| LP v1 projections (evaluation baseline) | `game_projections` (`locked`, `locked_at`) | 2026 weeks 5-7 only (126 rows, 121 locked) | `locked_at` | Too short to evaluate. |

## 2. Coverage by season and week

| Source | 2010-2020 | 2021-2025 | 2026 |
|---|---|---|---|
| `nfl_schedule`, regular season | 256 games each season (2,816 total) | 272, 271, 272, 272, 272 | 272 scheduled, 106 with final scores |
| `nfl_pbp`, distinct games | 2,816 total, 256 each season | 272, 271, 272, 272, 272 | weeks 1-7, 106 games |
| `team_game_results` (NFL rows) | present | present | present |
| `nfl_hist_depth_charts` | 2010-2020 | 2021-2024 (no 2025) | none |
| `nfl_hist_snap_counts` | 2013-2020 | 2021-2025 | none |
| `nfl_hist_injuries` | 2010-2020 (85,931 rows 2010-2025) | 2021-2025 | none |
| `injury_reports` | none | 2024-2025 (`date_modified` 2024-09-04 to 2025-02-07) | rows ingested 2026-10-09 to 2026-10-20 |
| `nfl_hist_participation` | 2016-2020 | 2021-2025 | none |
| `nfl_depth_chart`, `roster_snapshots`, `nfl_line_snapshots`, `game_projections` | none | none | 2026 only |

Regular-season games 2010-2025: 4,175, all with scores. Every season's schedule count matches its play-by-play game count
for 2021-2025, and for 2010-2020 the play-by-play count is 256 per season.

Season length changed from 17 weeks (2010-2020, 256 games) to 18 weeks (2021 onward, 271-272 games). Per-game rates need
normalising across that change.

## 3. As-of provenance assessment

- **Strong (captured at the time).** `roster_snapshots` (`captured_at`, `published_at`), `nfl_depth_chart` (`snapshot_at`),
  `nfl_line_snapshots` (`captured_at`), `game_projections` (`locked_at`). All start in 2026, so they support prospective
  evaluation only.
- **Weak (load-time only).** Most historical tables carry `ingested_at` stamps from the 2026 backfill. They show when a
  row entered this database, not when its value was known in 2022.
- **None.** `nfl_pbp` is retrospective, with the outcome of each play in the same row as its context. `nfl_hist_*` tables
  except `date_modified` on injuries. Schedule scores, results and the QB id columns have no as-of stamp.

## 4. Missing data and leakage risks

1. **Outcomes sit beside context.** Scores, results and play outcomes share tables with pregame fields. Every feature must be
   computed from rows with `game_date` strictly before the kickoff date.
2. **Starting QB ids are unverified.** `nfl_schedule.home_qb_id` and `away_qb_id` have no as-of stamp and may name the
   starter who played, which would be hindsight (the spec forbids hindsight starter IDs, section 5.1). The test: compare
   them against `nfl_depth_chart` snapshots for 2026 weeks 5-7 before any use.
3. **Weather is observed at game time.** `temp` and `wind` in the schedule are game-time values, so they are excluded.
4. **Fitted model outputs.** `nfl_pbp` carries `epa`, `wpa`, `qb_epa`, `cpoe`, `xpass` and `pass_oe`. They are fitted from
   outcomes, so they are not as-of features unless re-fitted chronologically (spec section M0).
5. **Closing lines have no capture time.** Schedule `spread_line`, `total_line` and moneylines lack a timestamp. Pregame
   lines can only come from `nfl_line_snapshots`, which exist for 2026 only.
6. **Injury history has no ingestion stamp.** A report's `date_modified` may fall after kickoff. A cutoff rule is needed
   (a decision for the user), and it cannot be verified for 2009-2025.
7. **Postseason is not a play-level field.** `nfl_pbp` has no `season_type`. Join to `nfl_schedule.game_type`
   (`REG`, `WC`, `DIV`, `CON`, `SB`).
8. **Team codes differ between sources.** The play extras file uses `LA` and `WAS`; the database uses `LAR` and `WSH`.
   The database tables agree with each other (schedule, play-by-play, team results, depth charts, injuries, snap counts),
   and the play extras are mapped in `e2_reference.py`.
9. **No NFL stakes.** `game_story.has_stakes` is 0 on all 156 NFL stories. Playoff-position context is not in these tables.
10. **Partial 2026 season.** The schedule holds future games with null scores; only weeks 1-7 have results.

## 5. Feasibility of historical comparison

- **Team efficiency and recent form, 2010-2025: feasible.** About 4,175 regular-season games with scores, a complete
  play-by-play for every season, and `game_date` cutoffs. Opponent adjustment and shrinkage (spec 6.1) are possible.
- **Personnel and workload, history: approximate only.** Historical depth charts (2010-2024) and snap counts have no
  as-of stamps. Usable only as approximate pregame information.
- **Availability and injuries, history: not verifiable.** Only `date_modified` exists before 2026.
- **Market baselines: 2026 only.** 120 snapshots across three sources, from 2026-10-11 to 2026-10-25. A historical
  calibrated market comparison (spec Phase 7) is not feasible.
- **LP v1 baseline: 2026 weeks 5-7 only.** Too short to compare the contextual model with v1 on history.

## 6. Verdict and next steps

Phase 0 is partly complete. Team-strength and form features can be built and backtested on 2010-2025 with date cutoffs.
Personnel, availability and the market and v1 baselines are only as-of in 2026, so their comparisons are prospective and
small.

Before Phase 2 (dynamic pools) and Phase 3 (team conditioning) start:

1. Test whether `home_qb_id` and `away_qb_id` match the pregame depth chart for 2026 weeks 5-7 (risk 2).
2. Decide the injury-report cutoff rule (risk 6). This needs a decision from the user.
3. Build team-strength features from `nfl_pbp` and `team_game_results` with `game_date` cutoffs, and verify each with a
   leakage test (no row with `game_date` on or after the kickoff date may enter a feature).
