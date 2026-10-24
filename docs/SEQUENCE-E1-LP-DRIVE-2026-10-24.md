# NFL sequence generator, LP E1 drive status (2026-10-24)

Stacked on `feat/nfl-sequence-e0-2026-10-24` (693e1767). Plan: `docs/END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md`
(Gridiron repo, main). E1 is LP's complete-drive gate.

**Status: partial E1.** The drive generator runs, and every complete drive it produces passes the drive checker. Four
authored starts were surveyed over 1,200 seeds each. Four drives are pinned as fixtures. Safety was not reached, and
punts, field goals, kickoffs, penalties, timeouts, quarter changes, score and participants are not modelled. The
outcome pool is retrospective, and the Gridiron E0a/E0b gate is still pending. This is not evidence that sampled
drives reproduce real NFL drive outcomes.

## What the generator does

- Starts from an **authored** possession state (`STARTS` in `scripts/nfl_sequence/e1_drive.py`). These are demonstration
  states, not pregame states from a real game.
- For each play, samples an outcome from observed 2022–2025 regular-season plays in the same down, distance and
  field cell (`e0_single_play.ydstogo_bucket`, `yardline_bucket`). The sampled event is one of `run`, `pass_complete`,
  `pass_incomplete`, `sack`, `interception`, `fumble_lost`.
- Applies the E1 reducer (`apply_play`). The drive ends at a terminal: `touchdown`, `safety`, `turnover`,
  `turnover_on_downs`, or `end_of_period` when the derived clock reaches zero.

## Rules that changed from E0, and why

1. **Touchdown is decided from the state's own yardline.** A run or completion that gains at least the current
   `yardline_100` is a touchdown. The sampled row's `touchdown` flag refers to its own yardline, which only shares the
   cell's bucket, so it is recorded (`outcome.sampled_touchdown_flag`) and not used. The first run of the
   generator failed on exactly this: a 13-yard sample from a bucket-mate at the 15 was applied to a state at the 13, and
   the reducer raised.
2. **Turnovers keep the spot published on the new offense's next snap** in the same game. `yards_gained` does not
   encode the spot on an interception (it is 0 in the pool), so the next published position is used. Pool rows are
   kept only when that next snap is a run or pass by the new offense in the same quarter (2,037 of 2,720 turnovers).
3. **Clock runoff is derived** from consecutive published `game_seconds_remaining` values in the same quarter. Rows
   without a same-quarter next snap, and negative derived runoffs, are excluded and counted.
4. **Fourth downs are go-for-it only.** Punts and field goals are not in the pool, so a fourth-down play is sampled
   from observed go-for-it plays. Every fourth-down play carries that note in `decision.note`.

## Pool

Usable plays: 127,151 (2022–2025 regular season). Excluded from the pool, with counts printed by the generator:

- penalty (not modelled): 1,962
- qb_scramble (not in the E1 vocabulary): 3,883
- no same-quarter next snap for clock runoff: 27
- negative derived clock runoff: 43
- turnover that is a touchdown (not modelled): 204
- turnover without a clean new-offense snap: 366

Pool digest (sha256 of the sorted pool items): `35ab31eb623cc26fac0d30bc38390757d543418e600b67dfc4c95de1a48c4ef9`.

Cells with fewer than 50 observed plays stop that drive with the reason `thin pool cell` and are counted as incomplete.
No fallback is used. Examples the generator printed: the fourth-down cell (4, '11+', '10-19') has 20 plays and
(4, '4-6', '10-19') has 34. The survey does not count how many cells are thin in total.

## Survey (seeds 1–1,200 per start)

| Authored start | Touchdown | Turnover | Turnover on downs | End of period | Complete | Incomplete (thin cell) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| own25_q1_900 (own 25, 1st & 10, Q1, 15:00) | 330 | 162 | 546 | 0 | 1,038 | 162 |
| midfield_q3_900 (own 50, 1st & 10, Q3, 15:00) | 459 | 137 | 484 | 0 | 1,080 | 120 |
| own25_q4_150 (own 25, 1st & 10, Q4, 2:30) | 52 | 103 | 262 | 724 | 1,141 | 59 |
| own40_q4_4th5_600 (own 40, 4th & 5, Q4, 10:00) | 247 | 107 | 783 | 0 | 1,137 | 63 |
| **Total** | **1,088** | **509** | **2,075** | **724** | **4,396** | **404** |

Terminal counts are complete drives. `turnover` combines interceptions and fumbles. **Safety was not reached** in any
of the 4,396 complete drives.

**Turnover on downs is over-represented.** Of the 2,075 turnovers on downs, most come from go-for-it fourth-down plays
sampled where teams would have punted. The own-40 4th-and-5 start ends that way in 783 of 1,137 complete drives. These
rates describe the sampler, not football. Do not read them as an estimate of how drives end.

## Checks

`check_drive` runs on every complete drive before it can be written. It fails loudly on any inconsistency. It checks:

- each play's `state_before` equals the previous play's `state_after` for quarter, offense, down, distance, field and
  clock;
- the clock never increases and never goes negative;
- a non-terminal play has a legal down (1–4), field (1–99) and distance (at least 1);
- the last play carries the drive's terminal, and only the last play does;
- possession changes exactly when `outcome.turnover` is true (turnovers and turnovers on downs);
- `outcome.touchdown` is true exactly when the terminal is a touchdown;
- `los` is inside 0–100.

The drive summary is recomputed from the play records: play count, yards, first downs (a play that keeps possession,
reaches a first down, and does not end the drive), turnovers, clock runoff total, and negative-yardage plays.

All 4,396 complete drives from the search passed `check_drive`. Each fixture also passed on its own run.

## Fixtures (`docs/fixtures/e1/`)

| File | Terminal | Plays | Yards | First downs | Negative-yardage plays | SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `own25_q1_900-seed4-touchdown.json` | touchdown | 12 | 78 | 4 | 2 | `ecea19d958d2cc3ed2975223f9b964794af887a3efa30289d6bca55bdfbbee98` |
| `own25_q1_900-seed12-turnover.json` | turnover | 4 | 21 | 1 | 0 | `dd482098b487a1a422ac9723f3d0b8e82956c5d13b6b87d805af295543c07ea4` |
| `own25_q1_900-seed1-turnover_on_downs.json` | turnover_on_downs | 13 | 53 | 4 | 1 | `4774c306fa47f9cddf1abacc489bddb15a6e64b2c62a055bbd13521d5503f0d5` |
| `own25_q4_150-seed1-end_of_period.json` | end_of_period | 5 | 26 | 2 | 0 | `e52e83a5f0a723fa7a6ad4e91fba696c03021a144bcbdbd2e6d4392106450ee4` |

The touchdown fixture is the plan's "complete legal drive with positive and negative plays". It has two negative-yardage
plays and ends in a touchdown. Each fixture reruns byte-identically with the commands below.

Safety is not represented by any fixture. Its terminal branch is implemented, but no seed reached it.

## Reproduce

```
cd /root/lp-nfl-sequence-e1
python3 scripts/nfl_sequence/e1_drive.py --start own25_q1_900 --seed 4 --out docs/fixtures/e1/own25_q1_900-seed4-touchdown.json
python3 scripts/nfl_sequence/e1_drive.py --start own25_q1_900 --survey 200
```

The survey command prints the pool counts and the terminal counts for seeds 1–200. The pool is read from
`/root/legendarypicks/backend/data/picks.dev.db` read-only. The 2022–2025 rows must be unchanged for the digest to match.

## Not modelled, and what the record says about it

Every record's `gaps` list states the following:

- punts, field goals, kickoffs, extra points and two-point tries;
- penalties, quarter changes, timeouts and the two-minute rules;
- score, points and player stats (null; touchdown points are not computed);
- participants (null; no pregame roster);
- fourth-down choices (go-for-it only);
- turnovers that are touchdowns (excluded from the pool).

The records also carry `temporal_eligibility.status = retrospective`. The pool spans 2022–2025 with no as-of cutoff.

## Known defect in E0 (not yet fixed)

The E0 reducer (`scripts/nfl_sequence/e0_single_play.py`, on `feat/nfl-sequence-e0-2026-10-24`) decides touchdowns from the
sampled row's `touchdown` flag, and it raises an error when a gain reaches the goal line without that flag. E1 hit the same
mismatch at the state level, so E0 can fail for other seeds. The committed E0 fixture (seed 1042) is unaffected, because its
sampled yards are 0. E0 has not been regenerated for other seeds, and its reducer has not been changed. The fix is the E1 rule
above, and it is pending.

## Interface

E1 writes the same top-level shape as E0, with `mode: drive_statistical_demo`, `valid_full_game: false`, and a per-play
`field` block (authored convention `e0-field-end-v1`). Each play also carries `sampling` (cell, cell size, event counts)
and `outcome.sampled_touchdown_flag`. Gridiron has not agreed to this drive shape yet, and E1 needs that agreement before
the drive record is used.
