# Post-recovery endpoint audit, 1999 to 2025

Scope: the fumble plays in `AUDIT.md`, followed to the dead-ball spot. This file records how the endpoint was measured and
what the simulator takes from it. It supports the V1.7 continued-play branch only.

## Method

- `endpoint_audit.py` reads each fumble play's description. It records the recovering team, the recovery spot, whether
  the fumbler recovered his own fumble, and the terminal (touchdown, safety, incomplete, touchback, out of bounds, or a
  final spot). It keeps the text of the tail after the recovery.
- Movement is measured from the recovery spot, not from the play's `yards_gained`. The play total includes movement
  before the fumble, so it is not a return distance.
- Plays whose end cannot be read from the text carry `terminal = unparsed` and are not used. About 24 percent of
  non-kick recoveries are unparsed. Kick recoveries (punt and kickoff muffs) are excluded from the pool.
- The pool is `scripts/nfl_sequence/data/recovery_endpoint_pool_1999_2025.csv`, built from the same columns.

## Counts used by the simulator

| Recovery | Pool rows at the goal line (recovery spot 100 to 110) | Terminals |
|---|---|---|
| Offense | 53 (50 with a usable terminal) | safety 36, spot 7, incomplete 4, touchdown 2, out of bounds 1, touchback 3 |
| Defense | 69 | touchdown 69 |

The offense sub-pool is thin. Seven spot rows give the continuation movement. Those seven are field endpoints
(80, 97, 99, and so on). A goal-line base uses only goal-line recoveries. Own-deep recoveries, at 90 to 99, are tackled
on the spot far more often, so they are not used for a goal-line base.

## Rules applied from the endpoint

- Fourth down: an offensive teammate of the fumbler who recovers makes the ball dead at the recovery spot. The draw of
  teammate versus fumbler uses the observed share (about 57 percent fumbler, from 3,268 parsed offensive recoveries).
- Two-minute warning (second and fourth quarters, 2:00 or less): the same teammate rule applies.
- A dead ball in the offense's own end zone through its own action is a safety.
- An incomplete pass dead in the own end zone is named, not decided. The official record gives no safety there, and no
  spot rule is established. The simulator refuses it with `incomplete_pass_from_own_end_zone_unverified`.

## Known gaps

- Defensive field returns that stop short of a score are not represented. The defense goal-line sub-pool is all
  touchdowns (69 of 69). The audit has such returns at spots 90 to 97, so the base for field recoveries needs its own
  spot distribution.
- The out-of-bounds safety rule still uses the audit category. Impetus is not coded.
- Touchback in the defense's end zone is not reachable from the offense's goal-line state.
- The model's play-continues share (about 1 percent of draws) is below the audit's continuation share (about 10
  percent). The gap comes from the two gaps above.
