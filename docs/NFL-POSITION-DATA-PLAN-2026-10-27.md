# NFL position data: plan (2026-10-27)

Status: plan, research only. Phase 0 (inventory) is implemented with this plan. Nothing here changes a production table,
a forecast, a simulator default or a frozen snapshot. The 2026 season is the sealed holdout.

## 1. Question

Does information about who plays where, who is available, and how much each player works improve game-winner forecasts
beyond the team strength models (S1 and S2)? And, for the team model, which position information is known before
kickoff?

This plan covers position data only: depth charts, weekly rosters, injury reports, snap counts, and player identity.
Player splits (per-player box-score distributions) wait for direction, as before. Madden ratings get a separate
inventory later and are not part of this plan.

## 2. What the downloaded releases hold

Sizes are from the 2025 or 2026 file on disk (`/root/lp-snapshots/nfl-backfill-2026-10-27/raw`).

| Release | Seasons on disk | Grain | Fields used | Time basis |
|---|---|---|---|---|
| `depth_charts` | 2001 to 2026 (26 files). Two layouts: 2001 to 2024 week-level (15 columns), 2025 to 2026 timestamped (12 columns) | 2001 to 2024: team, week, depth team, depth position, player. 2025 to 2026: team, position group, slot, rank, player | 2001 to 2024: `club_code`, `week`, `depth_team`, `depth_position`, `gsis_id`. 2025 to 2026: `dt`, `team`, `gsis_id`, `pos_grp`, `pos_slot`, `pos_rank` | 2001 to 2024: week only, no publication time. 2025 to 2026: `dt` is a capture time, about 221 snapshots per team per season (roughly daily). Publication time not stored |
| `weekly_rosters` | 2002 to 2026 (25 files) | team, week, player | `status` (ACT, DEV, RES, INA, CUT, RET), `depth_chart_position`, `position`, `gsis_id` | Week of the roster. Snapshot time not stored |
| `injuries` | 2009 to 2026 (18 files). 2009 to 2024 carry `date_modified`; 2025 to 2026 do not | team, week, player | `report_status` (Out, Questionable, Doubtful, or none), `practice_status`, injury descriptions | 2009 to 2024: `date_modified` is the time the row last changed. 2025 to 2026: week only |
| `snap_counts` | 2012 to 2026 (15 files) | game, player | `offense_snaps`, `defense_snaps`, `st_snaps` and their percentages, `position` | Post-game |
| `player_stats` | 1999 to 2026 | player, week | Passing, rushing, receiving, kicking lines | Post-game |
| `players` | one file | player | `gsis_id`, `pfr_id`, `espn_id`, `pff_id`, `position`, `position_group` | Identity table |
| `rosters` | 1920 to 2026 | player, season | Season roster | Season. Not used for pregame features |

2025 counts from the files: depth chart 554,215 rows; injury reports 6,068 rows, of which 1,382 are "Out", 1,283
"Questionable", 120 "Doubtful" and 3,283 carry no designation; weekly roster statuses ACT 27,377, DEV 8,783, RES 5,763,
INA 3,593, CUT 951, RET 361.

The dev database already holds some of the same data (`nfl_hist_depth_charts` 2010 to 2024, `nfl_depth_chart` 2026,
`nfl_hist_injuries`, `nfl_hist_snap_counts`, `nfl_snap_counts` 2024 to 2026, `player_game_availability` 2024 to 2026).
Phase 0 compares them season by season. Where they agree, the dev copy is used. Where they differ or are missing, the
release file is used and the difference is recorded.

## 3. A correction to the situational contract

The contract and the experiment plan listed historical availability as blocked, because only the 2026 availability
snapshots were known. The releases change that, but only partly:

- **Injuries, 2009 to 2024.** Each row carries `date_modified`. A row whose last change came before the cutoff holds the
  status at the cutoff, so it can be used strictly. A row changed after the cutoff cannot be read back, so it is excluded
  from strict tests. In the 2024 file, 4,818 of 6,215 rows were last changed on a Friday, which matches the league's
  weekly report schedule.
- **Injuries, 2025 to 2026.** No timestamp. Week only. Sensitivity tier.
- **Depth charts, 2001 to 2024.** Week-level, with no publication or capture time. Starter identity for these seasons is
  reconstructed, as contract v1 already states. Sensitivity tier.
- **Depth charts, 2025 to 2026.** Timestamped snapshots. Strict use is possible here, but these seasons are the test window
  (2025, previously examined) and the holdout (2026).

So availability has real history back to 2009, but strict time-basis coverage before 2025 is limited to injury rows with a
usable `date_modified`. Strict tests use only information whose time basis is shown to precede the cutoff.

## 4. Time-basis contract

1. A position feature enters a forecast only if its time basis is known to precede the cutoff (kickoff minus 24 hours
   for historical tests; the frozen forecast time for 2026).
2. **Depth chart, 2025 to 2026.** Use the latest snapshot whose `dt` is before the cutoff. The capture time can be later than
   the publication time, so this is conservative. Validate it against known starters before use (section 6, Phase 1).
   **Depth chart, 2001 to 2024.** Week-level only. Use as a sensitivity tier, with starter identity marked reconstructed.
3. **Injury report.** For 2009 to 2024, a row is used at a cutoff only if its `date_modified` is before the cutoff. For
   2025 to 2026, injury rows are a sensitivity tier. **Weekly roster.** Publication time is not stored, so it is a
   sensitivity tier, and strict tests use only an earlier week than the game.
4. **Snap counts and player stats.** Post-game. They enter only as earlier-game aggregates (prior games of the same
   player or team, before the cutoff).
5. **Identity.** Players are joined by `gsis_id`. A player with no `gsis_id` match is kept as unmatched, never dropped
   silently, and counted in the coverage table.
6. No market prices, no Madden ratings, no postgame statistic in a pregame field, and nothing from the 2026 season used
   to choose anything.

## 5. Features to be considered (after Phase 1)

- Starting quarterback identity (QB1 from the depth chart at the cutoff), and whether it changed from the previous game.
- QB1 unavailable at the cutoff, using the injury report of the prior week and the depth chart.
- Count of starters unavailable by position group (offensive line, receivers, cornerbacks), using the prior week's report.
- Workload: share of snaps by the team's top players at each position, from earlier games only.

Each feature is a separate layer, tested the same way as the situational groups (section 7).

## 6. Phases, with gates

- **Phase 0. Inventory. Done.** Schemas, season coverage, timestamps, and a comparison of overlapping seasons with the dev
  database. Output: `/root/lp-snapshots/nfl-position-2026-10-27/inventory.sqlite` (tables `release_coverage`,
  `dev_coverage`, `overlap`), built by `position_inventory.py`. Results:
  - Every release has a known grain, time basis and coverage (section 2).
  - Injury rows match the dev table exactly by season (2009 to 2025). Overlap on the same keys is 100% from 2020 and
    90% to 97% for 2009 to 2019.
  - Snap-count rows match the dev table by season (2013 to 2025). Overlap is 100% from 2020 and 91% to 97% for 2013 to 2019.
  - The 2009 to 2019 gap (3% to 10% of dev rows without a release match) is not yet explained. Phase 1 resolves it before
    either source is preferred for those seasons.
  - Depth charts: the dev table holds 2010 to 2024 week-level rows (552,514), and the release holds 2001 to 2024 week-level
    rows plus 2025 to 2026 snapshots. The comparison is Phase 1 work.
- **Phase 1. Identity and starter validation.** Join depth-chart players to `gsis_id`. Check that the depth-chart QB1 at the
  cutoff matches the quarterback who started (from `player_stats`) on a sample of team-weeks. Gate: agreement reported
  with its sample; any gap explained or kept as a sensitivity case.
- **Phase 2. Research store.** Tables: starter snapshot (team, season, week, cutoff-usable depth chart), availability
  (team, season, week, player, status, practice status, source), workload (game, player, snaps). Built read-only, with
  counts checked against the source files. Gate: row counts reconcile to the source per season.
- **Phase 3. Features and layers.** Build the features in section 5 from earlier games only. Gate: each feature has a
  coverage count and its time-basis label.
- **Phase 4. Tests.** Add each layer to S1 with the same protocol as the situational groups: calibration on 2010 to 2017
  (where the data exists), selection on 2018 to 2020, test on 2021 to 2025 (previously examined), 2026 untouched. Report
  Brier, log loss, calibration, and intervals against S1 on the identical games. Report nulls.
- **Phase 5. Report.** One document, with the coverage limits in the first section.

## 7. How a result would count

- A layer counts as an improvement only if its validation difference against S1 is below zero and its test difference
  is also below zero, with an interval that excludes zero on the pooled windows. Otherwise it is a null result.
- A layer that depends on an unverified time basis is reported as a sensitivity result, and is not promoted.
- Splits by position group, season and time basis are reported, with a sample size. Subgroups under 30 games are not
  interpreted.

## 8. Risks

- Depth-chart capture times may lag publication. Treated as conservative, but unverified.
- Injury designations are weekly. A player listed "Questionable" may or may not play, and the practice status is the
  better signal. Both are kept.
- Identity matching across releases may fail for some players. Counted, not hidden.
- Coverage differs by position group and era. Pre-2010 features are not used in fit or test.

## 9. Files

- Inventory script: `scripts/nfl_sequence/splits/position_inventory.py` (Phase 0).
- Research store: `/root/lp-snapshots/nfl-position-2026-10-27/` (outside the repo, outside production).
