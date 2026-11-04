# Weekly matchup intelligence data inventory (SLC v2, Milestone 1), 2026-11-02

Status: inventory of schema, coverage counts and gaps. Research only. No model was fitted. No 2026 outcome or market value was read. 2026 appears only as file names, non-null counts, timestamps and game times, which the as-of audit needs. The plan is `SLC-V2-RESEARCH-PLAN-2026-11-02.md`, section 10.

Revision 2 (same day) replaces the first pass where the second pass measured something the first pass had left open. Changed items are marked "(rev 2)".

## Instruments

- **Raw directory listing and headers**: `/root/gridiron-playbooks-research/data/raw` (file names, headers, and one full-file pass for route coverage on 2022 to 2025).
- **Database table list, columns, season counts and joins**: `/root/legendarypicks/backend/data/picks.dev.db`, opened read-only (`mode=ro`).
- Coverage numbers are for the instrument named. They are claims about that instrument until the publisher's own definition is checked (section 5).

## 1. Feature families

| Family | Source (instrument) | Seasons with rows | Coverage measured | As-of field | Status |
|---|---|---|---|---|---|
| Head coach per game | `nfl_schedule.home_coach`, `away_coach` | 2010 to 2026 | Non-null on every game row: 2022 284 of 284; 2023 to 2025 285 of 285 each; 2026 272 of 272 | game day (schedule); no effective-date field | usable for head coach |
| Coordinators, play caller | none found | none | Search of 136 table names and every `coach` column found only `nfl_schedule` | none | **missing** |
| Injury reports (weekly) | `nfl_hist_injuries` (`report_status`, `practice_status`, `date_modified`) | 2009 to 2025 | Rows: 2022 5,682; 2023 5,599; 2024 6,215; 2025 6,068 | `date_modified` is a **last-modified** time (rev 2, section 3) | usable with a leakage caveat |
| Current injury reports | `injury_reports` (`ingested_at`) | current | Not counted | `ingested_at` is an ingest time, not a report time | not usable for backtests |
| Snap counts, game level | `nfl_hist_snap_counts` (`pfr_player_id`) | 2013 to 2025 | Rows: 2022 26,381; 2023 26,540; 2024 26,615; 2025 26,613 | game (after kickoff) | labels for the matching game; ID join to `players.csv` |
| Snap counts, player and week (rev 2) | `nfl_snap_counts` (`player_id`, `season`, `week`) | 2024 to 2026 | 2024 25,357; 2025 25,344; 2026 9,946 (counts only) | week | 2024 and 2025 usable; no history before 2024 in this table |
| Depth charts, weekly | `nfl_hist_depth_charts` (`depth_team`, `formation`, `gsis_id`) | 2010 to 2024 (regular and playoff weeks) | 2022 37,780; 2023 37,327; 2024 37,312 | week (publication time not stored) | **2025 absent here**; the publisher has a 2025 snapshot file in a new format (rev 2, section 4) |
| Depth charts, current (rev 2) | `nfl_depth_chart` (`snapshot_at`) | 2026 only | 948 rows; snapshot times from 2026-07-27 to 2026-10-19 | `snapshot_at` (snapshot time) | usable for pregame status from 2026, holdout |
| Charted participation: pressure and coverage | `nfl_hist_participation` (`was_pressure`, `defense_coverage_type`, `time_to_throw`) | 2016 to 2025 | Section 2 | play | populated on dropbacks; see section 2 (rev 2) |
| FTN charting | `nfl_hist_ftn_charting` (`is_no_huddle`, `is_motion`, `n_defense_box`, `is_play_action`) | 2022 to 2025 | Rows: 2022 41,643; 2023 48,225; 2024 48,031; 2025 47,316. `is_no_huddle`, `is_motion`, `n_defense_box` non-null on every row | play | usable for tendencies and box counts |
| FTN charting, raw file | `ftn_charting_2022` to `ftn_charting_2026` (raw directory) | 2022 to 2026 | Headers include `n_blitzers`, `n_pass_rushers`, `is_drop`, `is_qb_out_of_pocket`. Not counted | play | 2026 holdout: header only |
| Play-by-play and participation, raw | `pbp_2022` to `pbp_2025`; `pbp_participation_2022` to `2025` | 2022 to 2025 | Used for HPV1 counts (see the HPV1 contract) | play | usable |
| Routes (rev 2) | `route` column in raw `pbp_participation_*` only; **not** a column of `nfl_hist_participation` | 2022 to 2025 | Non-empty share of all rows: 2022 36.2%; 2023 42.5%; 2024 41.6%; 2025 41.8%. On 2024 dropbacks 85.4% (section 2) | play | usable on dropbacks |
| Player game logs, weekly (rev 3) | `player_game_logs` (`league`, `season`, `game_id`, `team`, `stats` JSON), source `nflverse_weekly` | NFL 2019 to 2025 with rows; 2026 is holdout, not used | 2022 18,809; 2023 18,621; 2024 18,961; 2025 19,400 rows. JSON keys in a 3,000-row 2024 sample include `carries`, `dropbacks`, `off_snaps`, `off_pct`, `air_yards_share` | game (after kickoff) | usable: copy the published weekly stats, do not recompute them |
| Player usage shares (rev 3) | `player_game_shares` (`metric`, `share`, `source`) | 2025 and 2026 only | 2025: `carries` (source `derived_carries`), `targets` and `air_yards` (source `nflverse_weekly`). No shares for 2022 to 2024 | week | pre-2025 shares must be built from the logs; the `carries` share is derived, not published |
| Player identities | `players.csv` (`gsis_id`, `pfr_id`, `espn_id`, `pff_id`, `nfl_id`) | all | Header only | none | usable as crosswalk |
| Roster, weekly | `roster_weekly_2025` (`status`, `depth_chart_position`, `week`); `roster_weekly_2026` (holdout, header only) | 2025 | Not counted | week | 2025 is a candidate for pregame status |
| Roster snapshots (rev 2) | `roster_snapshots` (`league`, `published_at`, `captured_at`, `status`) | NFL: 2026 only | NFL: 3 rows. The `2027` label is NHL (1,124 rows) and NBA (4 rows). MLB and NCAAF 2026 rows also present | `published_at` | no usable NFL roster history in this table |
| Team and player stats, season | `stats_player_reg_2025` | 2025 | Header only | none | validation source for derived defense-versus-position |
| Pregame market lines (rev 2) | `nfl_line_snapshots` (`captured_at`, `game_id`) | 2026 only in this table: 165 rows, 46 games | Section 3 | `captured_at` | **not usable as pregame history**: most captured after kickoff |
| Separation (NGS) | none on this box | none | DB table list and raw listing searched; only `ngs_air_yards` in the raw participation header | n/a | **not found** |
| Market props | `prop_odds_snapshots` | to measure | Not counted | snapshot time | benchmark source, not checked |
| Transactions | `nfl_transactions` (`txn_date`) | to measure | Not counted | `txn_date` | possible role-change source |

## 2. Charted participation: the null structure (rev 2, measured)

The first pass said about half of the coverage and time-to-throw values were null for an unknown reason. Measured on 2024 (raw `pbp_participation_2024.csv` joined to `nfl_pbp` on game and play ID, using the nflverse `qb_dropback` flag):

| Play class | Rows | Route populated | Coverage type populated |
|---|---:|---:|---:|
| Dropback | 20,215 | 85.4% | 99.8% |
| Run | 13,255 | 0.1% | 0.2% |
| Other (non-dropback, non-run) | 10,396 | 10.1% | 12.0% |

Unmatched participation rows (2,053) are the no-play and marker rows the HPV1 contract already excludes.

Reading: the coverage nulls are **applicability**. Coverage type is charted on dropbacks, and dropbacks are about 44% of 2024 plays, which matches the 49% non-null rate in the season table. Runs carry no coverage. Route fields on 2024 dropbacks, split by class (same join): pass dropbacks 96.7% populated (17,256 of 17,839); sacks 0.2% (2 of 1,314); scrambles 0.5% (5 of 1,062). The 85.4% dropback figure above includes sacks and scrambles, which have no route. The residual route nulls on true pass dropbacks are 3.3%, the part to count and report.

Pressure: `was_pressure` is populated on every 2023 to 2025 row, but only on 38% to 39% of rows in 2016 to 2022 (section 1 table).

Time to throw (2024, same join): populated on 94.1% of dropbacks (17,790 of 18,901), 1.9% of sacks (25 of 1,314) and 4.7% of other plays (1,104 of 23,651). The same applicability pattern: the field is charted on dropbacks.

## 3. Cutoff safety (rev 2, measured)

**Injury reports (`nfl_hist_injuries.date_modified`).** Matched to each team's game day for 2024 and 2025 regular season: 5,954 team-week rows, all matched.

| Game day minus report date | Rows |
|---|---:|
| 2 to 6 days before | 5,438 (91%) |
| 0 to 1 day before | 515 (9%) |
| After kickoff | 1 |

Reading: the timestamps cluster in the days before the game, consistent with the weekly report. But the field stores the last modification, not the first publication. Earlier versions of a report are not recoverable from it. The one row modified after kickoff shows that a backtest using this field can leak. An as-of reconstruction must treat it as an upper bound on the value known at a cutoff.

**Market lines (`nfl_line_snapshots.captured_at`).** The table holds only 2026 rows (165 rows, 46 games). Capture time against kickoff: 139 rows after kickoff, 2 between 6 and 24 hours before, 24 more than 24 hours before. The line values were not read. This table cannot serve as a pregame market history for backtests on this box.

**Depth charts.** `nfl_hist_depth_charts` has no publication time. `nfl_depth_chart.snapshot_at` covers 2026 only, and it is a snapshot time. The 2025 publisher file (section 4, item 3) carries a snapshot time on every row (`dt`), so 2025 depth charts can be made as-of. The 2010 to 2024 season files cannot.

**Head coach.** Game-day only, with no effective-date field. A mid-season change is visible only by comparing consecutive games. Not measured.

**Snap counts and participation.** Game-level outputs, available only after the game. They are labels for the matching week, not pregame inputs.

## 4. Gaps

1. **Coordinators and play caller**: no source on this box. P1 is limited to head coach until a source is chosen (plan owner decision 12.6).
2. **Separation**: no NGS table or file. P4 separation is deferred. Pressure and coverage proxies (section 2) are the available substitute.
3. **2025 depth charts** (rev 2): the publisher did release them, in a different format. The nflverse file `depth_charts_2025.parquet` returns HTTP 200 and holds 554,215 rows in 12 columns (`dt`, `team`, `player_name`, `espn_id`, `gsis_id`, `pos_grp`, `pos_slot`, `pos_rank`, and others). It is a snapshot series: 221 distinct timestamps from 2025-08-03 to 2026-03-14, 32 teams, and 5,577 rows with no `gsis_id`. The 2010 to 2024 files use the season and week format, which the loader expects, so 2025 was never loaded. The gap is a publisher format change, not a missing release. The 2025 file is a previously exposed season, not the 2026 holdout. Its `dt` values are usable as as-of times.
4. **Route nulls on pass dropbacks** (rev 2): 3.3% in 2024 (583 of 17,839). Split by the FTN `is_throw_away` flag: non-throwaway pass dropbacks 98.8% populated (211 null, 1.2%); throwaways 47.3% populated (372 null of 706). Most nulls are throwaways. Whether a throwaway has a route by definition is not checked.
5. **Injury reports**: last-modified time only (section 3). An earlier-cutoff reconstruction needs another source.
6. **Pregame market history**: none on this box before 2026.
7. **Roster snapshots** (rev 2): the `2027` label belongs to NHL and NBA snapshots. No NFL roster snapshot for 2022 to 2025 is in this table.
8. **Route field outside the raw file**: `route` is not in `nfl_hist_participation`. Any feature needs the raw file or a new ingest.

## 5. Published-first check

Head coach per game, snap counts, depth charts, injury reports and participation fields are published by the nflverse sources already ingested. They are copied, not derived. Coordinators are not in those sources. Defense-versus-position is not published on this box. It must be derived from play-by-play and participation, and validated against published player totals (for example `stats_player_reg_2025`) before use.

## 6. Schematic example (no values)

The plan asks for one offense and one defense represented before kickoff. This is the field structure only.

- **Offense record** (team, `as_of`): head coach (`nfl_schedule`, game row); FTN tendencies over games before `as_of` (`is_no_huddle`, `is_motion`, `is_play_action` rates); player usage over games before `as_of` (`nfl_hist_snap_counts` shares); every count shown with its `n`.
- **Defense record** (team, `as_of`): box counts (`n_defense_box`, FTN); pressure rate (`was_pressure` share of defense plays, with the non-null count); coverage-type shares on dropbacks, with the non-null count; opponent-adjusted allowed rates by position group, built from the team's earlier opponents.
- **Matchup row**: offense record, defense record, `as_of`, and a count of every null field that was not imputed.

## 7. Baseline candidates (not frozen)

- P1: head-coach tendencies with league and team shrinkage (coordinators excluded until a source exists).
- P2: player usage as a prior-season share, shrunk toward the position-group mean and updated with earlier weeks.
- P3: defense allowed per opportunity against league rates, opponent-adjusted, shrunk by sample size.

The frozen protocol is written after the owner decides the open items in the plan.

## 8. Milestone 1 status

Done in rev 2:
- Publication-time semantics for injury reports (section 3).
- Route and coverage measured by season and play class; the null reason is applicability (section 2).
- 2025 depth-chart gap confirmed in both depth tables.
- Snap-count, roster-snapshot and market-line coverage by season.

Also done in rev 2: time to throw by play class; route nulls by sack, scramble and throwaway; the `2027` roster label; the publisher check for 2025 depth charts (section 4, item 3).

Still open:
1. Depth charts: decide how the 2025 snapshot series maps to the season and week format (an identity join on `espn_id` or `gsis_id`, with 5,577 rows lacking `gsis_id`). Not built here.
2. Routes on throwaways: confirm from the charting definition whether a throwaway should carry a route.
3. Owner: a coordinator source, or keep P1 at head-coach level.
4. Owner: an as-of source for injury reports (the field stores only the last modification), and for pregame market lines (none before 2026 on this box).
