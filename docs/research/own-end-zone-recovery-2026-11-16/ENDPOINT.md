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

## Rules applied (2026 rulebook, text extracted locally)

- Incomplete forward pass (Rule 8-1-4, Article 4): loss of down, ball returns to the previous spot. The four goal-line
  rows that end in an incomplete pass (2011 NE-DEN, 2013 OAK-DEN, 2017 HOU-JAX, 2024 CAR-CHI) were read in full. Each
  is a legal pass: the recovering quarterback had not thrown a forward pass earlier on the play, and none is a replay
  artifact. The simulator maps them to the previous spot.
- Safety (Rule 11-5-1b): an offensive impetus that sends the ball dead in the offense's end zone, or out of bounds
  behind its goal line, is a safety. The exception for an incomplete forward pass from behind the line in the end zone
  is not a safety.
- Touchback (Rule 11-5-1b exc. 2; Rule 11-6): a defender whose momentum carries him into his own end zone, where the
  ball is dead in his team's possession, gives a touchback. The defense takes over at its 20.
- Defense out of bounds behind its own goal line: a safety for the offense (Rule 11-5-1b). The 2000 ATL-CAR row is an
  example.
- Fourth-down fumble (Rule 8-7-5) and fumble after the two-minute warning (Rule 8-7-6): a teammate's recovery before a
  change of possession makes the ball dead. The next snap is at the fumble spot, or at the recovery spot if that is
  further back.
- A ball awarded behind a goal line is placed on the one-yard line (Rule 8). The rulebook does not state the placement
  of a ball dead exactly on the goal line. The simulator refuses that case by name.

## Source checks

- Replay reversals are excluded from the stage-one spot lists. The goal-line denominator has two: the 2006 DAL-SEA
  defensive recovery (the touchdown was reversed; the replay shows an offensive out-of-bounds safety), and a second
  defensive recovery whose touchdown was reversed. Neither is treated as a recovery event.
- After exclusion, the audited defensive field recoveries are 31: 28 touchdowns and 3 that stop without a score. The
  2000 ATL-CAR row (a defender ran out of bounds behind his own goal line) is an out-of-bounds safety for the offense,
  not a reversal, and is kept in the rulebook examples above.

## Stage one and stage two

- Stage one: the recovery spot for a continuing category, sampled from the audited spots (defense field: 0, 90, 97, 97
  and 27 at 100; offense field: 99 and 16 at 100).
- Stage two: the post-recovery endpoint from the observed pool at that spot. A spot at 100 or past it uses only
  goal-line recoveries.

## Known gaps

- A ball dead exactly on the goal line is refused by name. About 0.2 to 0.4 percent of draws, all in restricted states.
- Out-of-bounds impetus: the simulator treats the offensive impetus as the default, as the rulebook presumes. A defensive
  new force (a bat or kick of a loose ball) would be a touchback, but the audit text does not record it. That branch is
  not measured.
- Real-data smoke run: not yet run. It needs the game snapshot and the penalty model inputs on the fast host.
- Observed versus simulated (goal-line, unrestricted state): touchdown 45 percent simulated against 43 percent observed,
  safety 45 against 46, continued play 7 against 10, turnover 2 against 1 (touchback 0.8 observed). In restricted states,
  continued play falls by rule.
