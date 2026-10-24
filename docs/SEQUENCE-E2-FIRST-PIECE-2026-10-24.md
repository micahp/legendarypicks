# NFL sequence generator, LP E2 game: kickoffs, scoring, clock across halves, participants and the rules matrix (2026-10-24)

Branch `feat/nfl-sequence-e2-kickoffs-2026-10-24`, on the E1 head `2248f7e1`. Modules, all under `scripts/nfl_sequence/`:

- `game_state.py`: the game. Coin-toss ledger, kickoffs, scoring, the clock across quarters and halves, and the drive linkage.
- `game_stats.py`: team and player lines, computed from the plays.
- `rules_matrix.py`: the 2026 mandatory test matrix (rules file, section 7), recomputed from each record.
- `e2_reference.py`: the observed reference data, loaded read-only from the dev `nfl_pbp` table.
- `measure_kick_outcomes.py`: the published kick rates the engine draws from.
- `emit_game.py`: writes one full game payload, refused if any matrix row fails.
- `game_survey.py`: runs many seeded games through the engine and the matrix.

This branch does not change the E1 generator, its fixtures, or the shared contract `GRIDIRON-CONTRACT-v1`.

**Status: a complete regulation game, from the opening kickoff to the final whistle.** In 300 seeded games, 289 reach the end of regulation untied, and 11 are blocked (9 ties, where overtime is not modelled, and 2 thin field-goal cells). The rules matrix has 0 FAIL rows across all 300. `valid_full_game` is 0, by the contract (decision 1 below).

The emitted payload is `docs/fixtures/e2/e2-game-seed1.json` (seed 1: 24 drives, 144 plays, final score A 11, B 17). It carries the full record, every drive's plays with contiguous game-wide IDs, and the rules-matrix rows recomputed from the record. Reloading the file and re-running the matrix gives the same rows.

## Decisions (settled)

Micah confirmed these four on 2026-10-24. Each keeps the shared contract and the observed data, and the record says what it
does.

1. **`valid_full_game` is `false`, and the completion claim is `complete_regulation`.** The shared contract forbids
   `valid_full_game=true` while a rule is unmodelled and unmarked. Timeouts, the two-minute warning, penalties, onside kicks,
   overtime and player lineups are unmodelled, so each is listed in `unsupported_rules`, and the flag stays `false`.
2. **A tie after regulation stays blocked** as `overtime_not_modelled`. Overtime is not modelled, and it is not modelled just to
   make a game pass.
3. **Two clock rules are provisional practice rules, not rules-file rules.** A touchdown, made field goal or safety whose clock
   expires in Q1 or Q3 is followed by a kickoff in the next quarter. A score whose clock expires in Q2 gets no post-score kickoff.
   Both are labelled `provisional_practice_rule` with status `pending_2026_rulebook`. The record lists them in
   `provisional_rules` with a source note, and it counts their use in `provisional_counts`. The rules matrix reports them as
   PROVISIONAL, never PASS. A third rule, a quarter ending during a kick's return, is an authored modelling choice that matches
   E1's clamp. It is labelled `authored_modelling_choice`.
4. **Player lines are attributed per sampled play, with a per-record label.** Each play's passer, rusher and receiver are the
   ids of the observed play it was sampled from, labelled `sampled_observed_play`. The record's `player_note` says these are not
   this game's roster or lineup, and each player line carries the same label.

The quarter rules other than the two above come from the rules file (sections 2, 3 and 5). The payload seed is the first seed
that completes regulation untied. That is a choice of example, not a rule.

## Clock across quarters and halves

When the clock is at 0:00 after a play, a drive's terminal, or a kick, the event that follows depends on the quarter it
expired in:

| Expiry in | Possession change (punt, turnover, missed FG) | Score (TD, made FG, safety) | Kick that runs the clock out |
| --- | --- | --- | --- |
| Q1 or Q3 | Quarter changes, the same team keeps the ball at its spot, down 1. No kickoff (rules section 2). | Quarter changes. The scorer kicks off in the new quarter (NFL practice, not stated in the rules file: see below). | The quarter ends on the return. The receiver starts the new quarter at the spot. |
| Q2 | Halftime. No further play. The Q3 kickoff from the ledger (rules section 3). | Halftime. No post-score kickoff: the Q3 kickoff from the ledger replaces it. | Halftime. The Q3 kickoff from the ledger. |
| Q4 | Regulation ends. | Regulation ends after the try. No kickoff. | Regulation ends. |

The Q1, Q3 and Q4 rows come from the rules file (sections 2, 3 and 5), except the two provisional rules: the kickoff after a
score that expires Q1 or Q3, and the absence of one after a score that expires Q2. Those are labelled
`provisional_practice_rule` with status `pending_2026_rulebook`, and the matrix reports them as PROVISIONAL. A kick that runs
the clock out ends the quarter on the return, and the receiver starts the next quarter at the kick's spot. That is an
authored modelling choice, labelled `authored_modelling_choice`, and it matches E1's clamp of a play's runoff at 0:00.

A quarter change inside a drive (a play that expires Q1 or Q3 mid-drive) keeps the drive, as E1 already did. The
`boundaries` list records every quarter change and halftime, with its kind.

## Scoring

- **Touchdown (6), then a try.** The try is an extra point (1) drawn at the published extra-point rate, or a two-point try (2)
  drawn at the published two-point rate. The two-point share of post-touchdown attempts is the measured 9.5%. The scoring team
  then kicks off, unless the clock expired in Q2 or Q4.
- **Field goal.** Made (3, drawn at the bucket's published make rate; the kicker kicks off) or missed (the other team takes over
  at `100 − yardline_100`, first and ten, the same dead-ball spot).
- **Safety (2).** The conceding team kicks the free kick to the scorer.
- **Thin published cells block the game** (`thin_kick_cell:<name>`). Nothing is filled from a neighbouring cell.

## Participants and player lines

Each play carries `participants`: the passer, rusher and receiver ids of the observed play it was sampled from, with
`attribution: sampled_observed_play` and the source's `game_id` and `play_id`. Player lines (passing, rushing, receiving) are
summed from those plays. A touchdown credits no more yards than the distance to the goal line in the simulation, because the
observed yards describe a different spot. Team lines (plays, rushing, passing, turnovers, punts, field goals, possession time,
points) come from the same plays.

### Game-wide play identity

Every generated game has one `simulation_id` (`e2-<model-version>-seed<seed>`). Play `sequence` starts at 1 and increases
across drive boundaries; every play ID is `<simulation_id>:<sequence>`. The game validator checks this namespace and
contiguous ordering. E1's per-drive sequences are normalized after drive validation, and this relabelling does not affect its
sampled outcomes or random draws.

## Rules matrix

Every unmodelled rule (timeouts, the two-minute warning, penalties, onside kicks, overtime, the exception coin toss, lineups) has a named guard in the record's `guards`. The validator requires them, and the matrix checks them. A row that depends on a practice-sourced clock rule is PROVISIONAL, never PASS: the Q1 and Q3 change-of-ends rows, the Q2 halftime row, and the touchdown and field-goal rows whose score expires Q1 or Q3.

Every play's `state_before` and `state_after` carry the game-level `drive_index` of its drive. `validate_game` raises on a
mismatch, and the matrix has an independent row that fails it. E1 writes `drive_index: 1` on every play; E2 overwrites it.

`rules_matrix.check(record)` recomputes each row of the section-7 matrix from the drives, plays, kickoffs and boundaries. It
does not read the engine's flags. Each row is PASS, FAIL, PARTIAL, UNSUPPORTED, NOT_APPLICABLE (this game did not take the
path) or BLOCKED. The emitter refuses to write a payload with a FAIL. The row statuses for the emitted game are in its payload.

Rows that are not modelled are named, not passed:

- timeouts (three per team per half): the published table has no timeout fields, so the observed runoff stands as recorded;
- the two-minute warning;
- penalties and untimed-down extensions: E1 excludes penalty plays from its pool;
- onside kicks: every kickoff is drawn from the observed kickoff pool;
- player lineups and physical motion;
- fourth-down choices are sampled from observed plays by down, distance and field position, not by score or time (PARTIAL).

## Orientation

The toss winner (team A or B) and the winner's choice (receive or defer) are both sampled from the seed. Tests cover both
winners with both choices. Nothing is fixed to team A.

Authored, not sourced, and labelled in every record. The goal-first-half team defends x=0 in Q1. Ends change after Q1 and
after Q3, and halftime does not flip ends. The Q3 orientation uses the second-half goal choice.

## Survey (300 seeded games, `scripts/nfl_sequence/game_survey.py --games 300`)

```
games=300 validated=300 complete_regulation=289 valid_full_game=0
status {'complete_regulation': 289, 'blocked': 11}
blocker {None: 289, 'thin_kick_cell:field_goal:50+': 2, 'overtime_not_modelled': 9}
reached the Q3 half-start kickoff: 298 (99.3%)
boundaries: {'change_of_ends_mid_drive': 567, 'halftime': 298, 'change_of_ends': 25, 'skipped_post_score_kick': 10, 'change_of_ends_during_return': 4}
field goals drawn: {'made': 1122, 'missed': 266}
tries drawn: {'extra_point made': 983, 'two_point made': 46, 'two_point missed': 73, 'extra_point missed': 46}
points per game: mean 38.0; drives per game: mean 22.4, max 30
kickoff pool: usable 10037, excluded {'kickoff without a clean receiving snap': 962}
rules matrix, games per status:
  Opening toss winner defers, opponent receives                          {'NOT_APPLICABLE': 153, 'PASS': 147}
  Opening winner receives (normal policy)                                {'PASS': 153, 'NOT_APPLICABLE': 147}
  Winner chooses kick (normal mode)                                      {'PASS': 300}
  Winner chooses defended goal first (normal mode)                       {'PASS': 300}
  Explicit exception coin-toss path                                      {'PASS': 300}
  Q1->Q2 change of ends                                                  {'PASS': 298, 'NOT_APPLICABLE': 2}
  Q3->Q4 change of ends                                                  {'PASS': 298, 'NOT_APPLICABLE': 2}
  Q2->Q3 halftime: kickoff, clock reset, second-half choice              {'PASS': 298, 'NOT_APPLICABLE': 2}
  Both half-opening kickoffs, one per team, verified against the ledger  {'PASS': 298, 'BLOCKED': 2}
  Turnover on downs in Q2                                                {'NOT_APPLICABLE': 176, 'PASS': 124}
  Touchdown: six points, a distinct try, post-score kickoff              {'PASS': 295, 'NOT_APPLICABLE': 5}
  Made field goal (3) and safety (2), with the correct post-score kick   {'PASS': 297, 'BLOCKED': 2, 'NOT_APPLICABLE': 1}
  Clock: 15-minute quarters, no clock increase, end of Q1/Q3 is not a dr {'PASS': 300}
  Continuity between drives and quarters                                 {'PASS': 300}
  Points equal the points on the drives                                  {'PASS': 300}
  Provisional clock rules: practice-sourced, pending the 2026 rulebook   {'NOT_APPLICABLE': 277, 'PROVISIONAL': 23}
  Timeouts: three per team per half                                      {'UNSUPPORTED': 300}
  Two-minute warning                                                     {'UNSUPPORTED': 300}
  Penalties and untimed-down extensions                                  {'UNSUPPORTED': 300}
  Onside kick                                                            {'UNSUPPORTED': 300}
  Overtime after a tie                                                   {'NOT_APPLICABLE': 289, 'BLOCKED': 11}
  Player lineups and physical motion                                     {'UNSUPPORTED': 300}
  Fourth-down choices: punt, field goal or go for it                     {'PARTIAL': 300}
matrix FAIL rows across all games: 0
```

The first survey of this engine reported 6 matrix FAIL rows, in 6 seeds (76, 85, 88, 136, 162, 210). Each was a bug in the checker, not in the engine. Two conditions were too narrow. A kickoff opening Q2 or Q4 after a field goal or score that ran into the new quarter was refused, though the score was legitimate. A halftime reached by a kick running out the clock was not recognised as halftime. Both were corrected in `rules_matrix.py`. Each of the six seeds now passes, and the 300-game survey has 0 FAIL. No engine code changed for the fix.

## Tests

- `python3 -m unittest scripts/nfl_sequence/test_game_state.py`: **29 of 29 pass**. They cover the ledger
  (refusals, both coin-toss paths, the second-half chooser), the half-start validator, the kickoff pool convention, the bucket
  labels, scoring (a touchdown then its try then the scorer's kickoff, a missed extra point, a two-point try, a made and a missed
  field goal, a thin cell that blocks), the clock (a touchdown on the last play of Q1, a score that expires Q2 with no
  post-score kickoff, a punt that expires Q1 with the receiver keeping the ball, a kick that runs the clock out), halftime, the
  reference being required, the game-wide play ID and sequence contract, and the matrix (a clean game has no FAIL, and mutated records do
  fail: a repeated kicker, a points total that disagrees with the drives, and a clock that rises inside a quarter).
- `python3 -m unittest scripts/nfl_sequence/test_e1_transitions.py` (inherited from E1): **11 of 11 pass**.
- Both files together: **40 tests OK**.

## Kick outcomes in the dev database

The published rates the engine draws from. `nfl_pbp` (the curated nflverse table on dev) keeps `series_result` and `success`,
and does not keep the dedicated `field_goal_result`, `extra_point_result`, `two_point_conv_result` or `kick_distance` columns.
The outcomes are in the kept columns:

- **Field goal:** `series_result` = `Field goal` (made) or `Missed field goal` (missed), on `play_type = 'field_goal'`.
  Excluded: 18 `QB kneel`, 8 `Opp touchdown`, 1 `Turnover`.
- **Extra point:** `extra_point_result` = `good` (made) or `failed` (missed), on `play_type = 'extra_point'`. A `blocked`
  extra point and a row with no result are excluded (38 and 11 in the window), not counted as misses. The rebuilt table is
  `docs/fixtures/e2/kick_results_2022_2025.csv`, from the raw nflverse files, with `build_kick_results.py`.
- **Two-point try:** `two_point_conv_result` = `success` or `failure`, on `two_point_attempt = 1`. Nothing is read from
  `success`.

Primary window: 2022–2025, weeks 1–18, the same window E1 samples from.

| draw | published rate | made / missed in the window | floor per cell |
| --- | ---: | ---: | ---: |
| field goal, by `yardline_100` 1–9 / 10–19 / 20–29 / 30–39 / 40–49 / 50+ | 98.2 / 95.0 / 83.1 / 72.6 / 54.9 / 25.0% | 698/13, 1109/58, 980/200, 809/305, 67/55, 1/3 | 30 attempts |
| extra point (`extra_point_result`: good / failed; blocked and missing excluded) | 96.3% | 4643 / 178 | 30 attempts |
| two-point try | 47.2% | 240 / 269 | 30 attempts |
| two-point share of post-touchdown attempts | 9.5% | 509 of 5,379 | none |

Field goals by bucket, rebuilt from the publisher's `field_goal_result` (`build_kick_results.py`), with Wilson 95% intervals.
Kick yards are about `yardline_100 + 17`. Blocked kicks are excluded: a blocked kick is not a missed kick, its spot rule is
different, and the engine does not model it. The window holds 86 blocked field-goal rows and 19 rows whose series label is not
a kick (18 `QB kneel`, 1 `Turnover`); both are excluded and counted.

| `yardline_100` | kick (yards) | made | missed | make rate | Wilson 95% |
| --- | --- | ---: | ---: | ---: | --- |
| 1–9 | 18–26 | 698 | 10 | 98.6% | 97.4–99.2% |
| 10–19 | 27–36 | 1109 | 43 | 96.3% | 95.0–97.2% |
| 20–29 | 37–46 | 980 | 179 | 84.6% | 82.4–86.5% |
| 30–39 | 47–56 | 809 | 273 | 74.8% | 72.1–77.3% |
| 40–49 | 57–66 | 67 | 48 | 58.3% | 49.0–66.9% |
| 50+ | 67+ | 1 | 3 | 25.0% | 4.6–69.9% (n = 4, thin) |

Total: 3664 made, 556 missed, 86.8%. The earlier 85.2% counted the 78 blocked kicks as misses.

Per-season stability (all seasons): field goals stay between 81.7% (2019) and 86.6% (2013). Extra points are 98.8–99.6%
through 2014 and 92.4–95.9% from 2015, a step that fits the 2015 rule change moving the PAT to the 15-yard line. That rule
change is general knowledge, not something the database records.

Checks independent of `series_result`: of 3,664 made field goals, 3,071 are followed by a kickoff received by the other team
and none by a kickoff received by the kicking team; of 634 missed, 464 are followed by a run, pass or kneel by the other team.
Five rows disagree (three made, followed by a scrimmage play; two missed, followed by a pass by the kicking team).

Two-point tries: mean EPA is +1.053 on converted and −0.962 on failed, which is consistent with `success`. No TD flag is set on
any two-point try, and there are no score columns, so the two-point rate is checked against EPA only.

Reproduce: `python3 scripts/nfl_sequence/measure_kick_outcomes.py` (read-only, `mode=ro`, about 5 seconds).

## Settled, and still open

- **Decided (Micah, 2026-10-24): consume the published outcomes.** The field-goal and try blocker is gone. The
  `field_goal_result_unpublished` key appears in no record.
- **Settled (Micah, 2026-10-24):** the four decisions above.
- **Still open, not part of those four:**
  - The two provisional practice rules are pending the 2026 rulebook check. They stay labelled until that check is done.
  - Whether the 8 `Opp touchdown` field-goal rows count as misses (85.2% becomes 85.1%).
  - Whether the two-point rate should be trusted before a score-based check exists.

## Shared contract v1 projection

`shared_v1.py` projects a record onto the shared document (`docs/GRIDIRON-CONTRACT-v1.md`, sha256 `ae7b8a30...`, identical in
all 122 copies on the box). Kickoffs, extra points and two-point tries, period ends, the game end and safeties are plays in the
contract vocabulary. Each state carries the running score, the timeouts (3 per team per half, charged to the side the sampled
play names), `drive_index`, and the v1 field names. Each outcome carries `air_yards`, `yac` and `out_of_bounds` from the
observed play it was sampled from. Team and player summaries are recomputed from the play log alone.

The checker (`check_document`) works from the document alone. Seven violations remain, and each is a field the source cannot
supply: `mode` (no pregame snapshot), `game_id`, `scheduled_kickoff_utc`, `as_of_utc`, `snapshot_hash`, `roster_snapshot_id`,
and play `duration_seconds` (the published table has no play duration). They stay null and are reported; nothing is filled in
to make them pass.

## Not done

- **Timeouts, two-minute warning, penalties, untimed downs, onside kicks, overtime, exception coin-toss paths, and lineups.**
  Listed in `unsupported_rules` for every record.
- **Blocked kicks, returned misses, and touchbacks on a missed kick.** Not modelled.
- **Clock realism.** Kickoff and drive times are the sampled intervals from the observed data.
- **E1 pool coverage.** Some E1 pool cells have too few observed plays; E1 refuses them and the game is blocked.
