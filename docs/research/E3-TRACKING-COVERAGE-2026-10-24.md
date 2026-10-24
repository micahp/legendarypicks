# E3 step 1: 2022 Big Data Bowl tracking joined to LP nfl_pbp, coverage (2026-10-24)

Worktree: `/root/lp-nfl-e3-tracking`, branch `research/nfl-e3-tracking-coverage-2026-10-24`, off `origin/main` (`80f394d8`).
Script: `scripts/bdb/e3_tracking_join.py`. Outputs: `e3-tracking-join-pairs-2026-10-24.csv` (one row per tracked play, 16,124),
`e3-tracking-coverage-2026-10-24.json` (every count in this report).

## Sources (consumed, not invented)

- BDB 2022 tracking: `/root/nfl-tracking-data/bdb2025/code-data/`, repository `b00nk3r/NFL-Big-Data-Bowl-2025` at commit
  `e28d3b25`, per `PROVENANCE.json`. All 13 files were checked against `SHA256SUMS.txt` on 2026-10-24 and matched, including
  `plays.csv` (`a103cbc3…`), `games.csv` (`166456ed…`) and `tracking_week_1..9.csv`.
- LP play-by-play: the dev database `nfl_pbp`, opened read-only (`mode=ro`), season 2022, weeks 1–9: 23,673 rows over 136 games.

## Join keys

- **Game.** BDB `gameId` (from `games.csv`) maps to one LP `game_id` through season, week, away club and home club. BDB `LA` and
  `WAS` map to LP `LAR` and `WSH`. All 136 BDB games map to exactly one LP game, and no game maps to two.
- **Play.** BDB `playId` equals LP `play_id` within that LP game. The LP pair (`game_id`, `play_id`) is unique: 0 duplicates.
- **Verification.** An identifier match is verified only when it also agrees with LP on quarter; game clock (BDB `gameClock`
  against LP `game_seconds_remaining` minus the seconds of later quarters); down; distance (`yardsToGo` against `ydstogo`);
  possession team (`possessionTeam` against `posteam`); and the spot (BDB side and number, converted to offense-relative
  `yardline_100`, against LP `yardline_100`).

Relation to the earlier join: the earlier join matched on the same context fields and found the play by search. It recorded that
all 15,765 of its pairs have LP `play_id` equal to BDB `playId`. This join uses the identifier directly, and it reproduces every one
of those 15,765 pairs with the same LP play.

## BDB side: the 16,124 tracked plays

| status | plays | reason |
| --- | ---: | --- |
| verified: identifiers match, all fields agree | **15,768** | — |
| unverified: spot side is NA | 222 | spot cannot be checked |
| overtime, not checked | 134 | quarter 5; the clock convention is not checked |
| unmatched | **0** | every BDB play has an LP play with its identifiers |

Total 16,124. The verified count is the earlier 15,765 plus 3. Those 3 were the earlier "ambiguous" plays, and the identifier join
resolves them. Unmatched counts by reason are therefore 0 for identifiers. The 356 BDB plays that are not verified are 134 overtime and
222 unresolved spot.

## Tracking coverage (streamed from all nine tracking files)

- Plays with frames: 16,124 of 16,124. The tracking files contain exactly the plays of `plays.csv`: 16,124 distinct
  (gameId, playId) keys in both, none only in tracking, none only in `plays.csv`.
- Plays with a `SNAP` frame: 16,124. Plays with a `ball_snap` event label: 16,062. The two disagree on 62 plays. Each has a snap frame
  but no `ball_snap` label. The count matches the 62 plays the clock audit reported with no `ball_snap`.
- Verified and with a snap frame: 15,768.

## LP side: scrimmage plays with coverage

Scrimmage plays are run, pass, qb_kneel and qb_spike. There are 17,143 such LP plays in weeks 1–9 that belong to a drive.

| LP status | plays | share |
| --- | ---: | ---: |
| tracked (verified, with a snap frame) | **15,768** | 92.0% |
| BDB play with this identifier, not verified: overtime | 134 | |
| BDB play with this identifier, not verified: spot side NA | 222 | |
| no BDB play with this identifier | **1,019** | |

The 1,019 are run 412, pass 549, qb_kneel 54 and qb_spike 4. The published tracking has no frames for them: the tracking files
contain exactly the plays of `plays.csv`. Two flags in LP cover part of the set: 17 are penalty plays, 53 are QB scrambles and 63 are
two-point tries. These flags are not a reason recorded in the sources. For the rest, neither the source nor the join gives one. They
are reported as absent and are not joined.

## Drive and game coverage

Drives are LP `drive` values, weeks 1–9: 2,955 drives. Two definitions are reported, because BDB has no kickoff, punt, field-goal, extra-point
or no-play rows, so a strict "every play tracked" definition cannot be met by a drive that contains one of them.

| definition | complete | partial | none |
| --- | ---: | ---: | ---: |
| every play in the drive tracked (kickoffs and kicks count as untracked) | **106** | 2,772 | 77 |
| every scrimmage play in the drive tracked (run, pass, kneel, spike) | **2,059** | 819 | 67 (and 10 drives with no scrimmage play) |

2,802 of the 2,955 drives contain a non-scrimmage play.

Games: 136. Every play of a game tracked: **0 complete**, 136 partial. Every scrimmage play of a game tracked: **1 complete**, 135 partial.

## Reconciliation with the earlier coverage report

The earlier report gave 789 complete, 2,014 partial and 46 none, against a denominator of 3,091. Its complete criterion counted punts and
field goals as plays that must be tracked. Recomputed with that criterion, on the same LP data and this join's tracking flags, the
counts are 790 complete, 2,013 partial and 43 none, out of 2,846 drives that have at least one run, pass, punt or field goal. The
differences from the earlier figures (+1 complete, −1 partial, −3 none) are not fully traced. The 3 plays this join newly verifies
account for at most 3 of them. The earlier denominator of 3,091 does not reproduce from the same LP rows, and it is not explained here.

## What this does not establish

- The 1,019 LP scrimmage plays with no BDB play are not in the published tracking. They are not invented and not joined. Their absence is
  reported, not explained.
- Overtime and NA-spot plays are tracked but not verified. They are excluded from the verified count.
- Coverage is a join fact. It does not say that a tracked play's movement is the same as the LP play's outcome beyond the context fields.

## Reproduce

```
python3 scripts/bdb/e3_tracking_join.py --out-dir docs/research
```
