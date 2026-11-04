# M5 freeze amendment 5, 2026-11-04: grouping drawn given the run or pass call

Status: owner-authorized (2026-11-04). Research only, behind the `--participation-field` flag, off by default. No SLC
default changes. No production activation. No 2026 outcome was read. Earlier freeze documents and amendments are not edited.

## Why

The lineup grouping was drawn without the play's call. Drawn that way, every grouping carried about the league's average
pass rate: on 2025, a simulated 22 was a dropback 51% of the time against 28% observed, and a six-lineman 12 50% against
22%. In real games personnel comes first and the call follows it. The engine draws the call first, so the grouping is now
drawn given the call. That gives the same joint distribution of call and grouping as personnel first; what it cannot
reproduce is a call forced by the roster (for example no healthy TE), which needs the real order and is left for later.

## The change

- The scrimmage table carries `qb_dropback` (the published nflverse field). A snap is a dropback when it is 1, a run
  otherwise.
- Table schema v4 adds `league_transitions_by_intent` and `team_transitions_by_intent`: the same grouping transitions,
  counted separately for runs and dropbacks, with the same shrinkage (team to league 50, league to the cell's call marginal 20).
- `participation_field.Field.group_probs(team, cell, prev, call=None)` and `draw_group(..., call=None)` use the by-call
  tables when the table has them. A v2 or v3 table ignores the call, so earlier tables draw as before.
- `pre_event._advance_lineup` passes the play's intent (`run` or `dropback`) as the call.

## Changed files

Base commit: `7ca70d06`.

| File | Frozen SHA-256 | Amended SHA-256 | Pinned | Change |
|---|---|---|---|---|
| `scripts/nfl_sequence/pre_event.py` | `6b91c7de4b11de975197d8c0f4af3cfccd5435784a67699c07ae1dca9c25ee3f` | `0d83a7d0f0934e7a59b460e62a8df79b6b1ebcf44cf13230fa93da32f5c5fe7c` | yes | `_advance_lineup` passes the intent to `draw_group`. Flag off: unchanged. |
| `scripts/nfl_sequence/participation_field.py` | `75c54dcec70d84cb05feaefa6a6cdaffd29f58305326939128ade6818596f5ce` | `9525a68969e020869f25542c703fc71424920951ce436e7a6c155fb227ed7c58` | no | Schema v4 accepted; by-call transition tables; `group_probs` and `draw_group` take `call`. |

Research files (not pinned): `build_tables.py` `0b418b69...` (writes `qb_dropback`), `lineup_fit.py` `22514c34...` (counts
transitions by call), `export_field.py` `3c24694f...` (schema v4), `call_grouping_check.py` `b534a301...` (new). Tests:
`test_participation_field_hook.py` `f6b8ad2d...`.

## New tables

| File | SHA-256 | Fit seasons |
|---|---|---|
| `participation-model-2026-11-02/outputs/field_v4_2022_2025.json` | `b53b2566e3abf3874f738f1c26f3e2975c6f03d65887bad9590c276006c9a4c3` | 2022 to 2025, for 2026 games |
| `participation-model-2026-11-02/outputs/field_v4_2022_2024.json` | `1dfd02770c0bdc4d2616f406b8112f680a0c13bc91da1e065a51b81f9a2dc4bd` | 2022 to 2024, for the 2025 check |

The committed builder rebuilds the scrimmage table byte for byte (`6bcbca48...`), and the tables above were exported from it.

## Verification

- 2025 check (`call_grouping_check.py`, fit 2022 to 2024, the observed previous grouping and call given on each snap, 3 seeds;
  `outputs/call_grouping_check_2025.json`, `ef0ae2e6...`). Dropback rate by drawn grouping:

  | Grouping | Observed | v3, no call | v4, given call |
  |---|---|---|---|
  | 11 | 0.710 | 0.642 | 0.689 |
  | 12 | 0.527 | 0.545 | 0.498 |
  | 21 | 0.458 | 0.530 | 0.444 |
  | 13 | 0.403 | 0.530 | 0.396 |
  | 22 | 0.282 | 0.513 | 0.269 |
  | 12-OL6 | 0.219 | 0.501 | 0.216 |
  | 11-OL6 | 0.340 | 0.496 | 0.264 |
  | 21-OL6 | 0.138 | 0.460 | 0.141 |

  Snap-weighted absolute error 0.0713 (v3) to 0.0215 (v4). Mean log probability of the observed grouping -1.270 to -1.254.
- Tests: 93 passed (`test_participation_field`, `test_participation_field_hook`, `test_pre_event`, `test_pbv1_hook`,
  `test_rng_protocol`, `test_slc_playcall`). New: a v4 table draws heavy groupings on runs more often than on dropbacks
  (dropback share lower by more than 0.2); a v3 table ignores the call.
- Flags-off regression (frozen extract, Week 8 `2026_08_KC_DEN`, RNG v2, seeds 1 to 3): 0 of 3 seeds differ.
- Flag-on smoke with `field_v4_2022_2025.json`: 3 of 3 seeds complete (DEN-KC 26-13, 33-23, 29-26). Groupings per game
  include 13, 21, 22 and six-lineman codes (seed 1: DEN 11 x41, 12 x14, 13 x5, 21 x3, 11-OL6 x2, 22 x2; KC 11 x33, 12 x12,
  22 x3, 22-OL6 x2). No cell fallbacks. One short lineup (DEN, seed 2): the drawn grouping needed more players of a class
  than were available.

## Known limits

- The call is still drawn first. A call forced by the roster (injured TEs, a missing FB) is not modelled.
- The table is fitted with fixed season weights and has no current-season update. The week-over-week backtest from 2022 is next.
- The substitution shortfall (1.21 against 1.39 entries per snap) is unchanged.
