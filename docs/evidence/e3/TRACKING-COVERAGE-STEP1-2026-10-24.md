# E3 step 1: 2022 Big Data Bowl tracking joined to nfl_pbp, coverage (2026-10-24)

The join reads the tracking files and the dev database read-only. Every number below is read from
`docs/evidence/e3/tracking-coverage-v1/e3-tracking-coverage-2026-10-24.json`, and the play-level rows are in
`e3-tracking-join-pairs-2026-10-24.csv`. Script: `scripts/bdb/e3_tracking_join.py` (from commit `e1f56b85`, unchanged).
Pairs CSV sha256 `80d8911697b34434`; coverage JSON sha256 `d6c11dd5d502d181`.

## Matched plays, out of 16,124 tracked

- **Identifier match:** 16,124 of 16,124 tracked plays (100.0%) have one LP play with the same game and play identifiers. 0 unmatched.
- **Verified:** 15,768 of 16,124 (97.8%). A verified play also agrees with LP on quarter, game clock, down, distance, possession and spot.
- **Not verified:** 222 with the spot side NA (the spot cannot be checked), and 134 in overtime (the clock convention is not checked here).
- **Tracking frames:** all 16,124 tracked plays have frames; 16,124 have a SNAP frame; 16,062 have a `ball_snap` label; 62 disagree.

## Which join fields match

| join level | field | rule | result |
|---|---|---|---|
| game | season, week, away club, home club | BDB `gameId` to LP `game_id`; LA and WAS mapped to LAR and WSH | 136 of 136 games map to exactly one LP game; 0 unmapped |
| play | `playId` = `play_id` | identifier within the LP game | 16,124 plays matched; 0 duplicate LP (game, play) pairs |
| verification | quarter, game clock, down, distance, possession, spot | agree with LP on the identifier-matched plays | failing counts other than overtime and NA spot: 0 |

## Drives and games covered

LP drives in weeks 1-9: 2,955 (null-drive rows are excluded: they are not drives).

| definition | complete | partial | none |
|---|---:|---:|---:|
| every play in the drive tracked (kickoffs and kicks count as untracked) | 106 | 2,772 | 77 |
| every scrimmage play in the drive tracked | 2,059 | 819 | 67 (and 10 with no scrimmage play) |

Games: 136. Every play tracked: 0 complete, 136 partial. Every scrimmage play tracked: 1 complete, 135 partial.

## LP scrimmage plays

17,143 LP run, pass, kneel and spike plays have a drive. Tracked and verified: 15,768 (92.0%). BDB play failed verification: 356. No BDB play with this identifier: 1,019, by type {'pass': 549, 'qb_kneel': 54, 'qb_spike': 4, 'run': 412}.

## Independent checks

- `plays.csv` in weeks 1-9 has 16,124 rows and 16,124 distinct (gameId, playId) keys (Python csv).
- The nine tracking files have 16,124 distinct (gameId, playId) keys, all in `plays.csv` (an `awk` pass that keeps only the key set).
- LP drive groups in weeks 1-9 on non-null `drive`: 2,955 (SQL on the dev database).
- The rerun of the committed script reproduces the pairs CSV and the coverage JSON byte for byte.

## Not established

- The 1,019 LP scrimmage plays with no BDB play are not in the published tracking. They are reported, not explained.
- Coverage is a join fact. It does not say that a tracked play's movement matches the LP outcome beyond the context fields.
- The 789-versus-790 complete-drive difference between the two earlier reports is not traced.
