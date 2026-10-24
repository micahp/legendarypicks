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

**Status: a complete regulation game, from the opening kickoff to the final whistle.** (the 300-game survey and the emitted payload are pending in this commit; the next commit fills them in.)

The emitted payload is `docs/fixtures/e2/e2-game-seed<seed>.json (not yet emitted in this commit)`. It carries the full record, every drive's plays, and
the rules-matrix rows recomputed from the record.

## Decisions taken without a check-in

These were ambiguous. Each one keeps the shared contract and the observed data, and each is stated here so it can be
reversed.

1. **`valid_full_game` stays `false`.** The contract says a game must not claim `valid_full_game=true` while a rule is not
   modelled and not marked. Timeouts, the two-minute warning, penalties, onside kicks, overtime and player lineups are not
   modelled, so each is listed in `unsupported_rules` and the flag stays false. The completion claim is `complete_regulation`.
   If Micah reads "complete game" as `valid_full_game`, that needs a decision on those six rules, not a change of flag.
2. **A tie after regulation blocks the game** as `overtime_not_modelled`. Overtime rules are version-sensitive and the rules
   file says to guard them, so no overtime is invented.
3. **A clock at 0:00 is resolved by the quarter it expires in**, using the rules file's quarter rules (sections 2 and 3). The
   rules that are not in the file are marked below.
4. **Player lines use the observed play's participants**, labelled `sampled_observed_play`. These are the passer, rusher and
   receiver ids of the play each simulated play was sampled from. They are not this game's roster or lineup, and the record
   says so on every line. Without those ids the player block would be empty, and the stats would not exist.
5. **The emitted seed is the first seed that completes regulation untied.** The survey gives the full distribution.

## Clock across quarters and halves

When the clock is at 0:00 after a play, a drive's terminal, or a kick, the event that follows depends on the quarter it
expired in:

| Expiry in | Possession change (punt, turnover, missed FG) | Score (TD, made FG, safety) | Kick that runs the clock out |
| --- | --- | --- | --- |
| Q1 or Q3 | Quarter changes, the same team keeps the ball at its spot, down 1. No kickoff (rules section 2). | Quarter changes. The scorer kicks off in the new quarter (NFL practice, not stated in the rules file: see below). | The quarter ends on the return. The receiver starts the new quarter at the spot. |
| Q2 | Halftime. No further play. The Q3 kickoff from the ledger (rules section 3). | Halftime. No post-score kickoff: the Q3 kickoff from the ledger replaces it. | Halftime. The Q3 kickoff from the ledger. |
| Q4 | Regulation ends. | Regulation ends after the try. No kickoff. | Regulation ends. |

The Q1, Q3 and Q4 rows are from the rules file (sections 2, 3 and 5). The rule that a score at the end of Q1 or Q3 is kicked
off in the new quarter, and the rule that a score at the end of Q2 gets no post-score kickoff, are standard NFL practice and
are not written in the rules file. They are flagged here for confirmation against the 2026 rulebook. A clock that runs out
during a kick ends the quarter on the return, and the receiver starts the next quarter at the kick's spot. That is also the
clamp E1 applies to a play's runoff.

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

## Rules matrix

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

Authored, not sourced, and labelled in every record. The goal-first-half team defends x=0 in Q1. Ends change after Q1 and
after Q3, and halftime does not flip ends. The Q3 orientation uses the second-half goal choice.

## Survey (300 seeded games, `scripts/nfl_sequence/game_survey.py --games 300`; pending)

```
(pending: the survey is still running)
```

## Tests

- `python3 -m unittest scripts/nfl_sequence/test_game_state.py`: **29 of 29 pass**. They cover the ledger
  (refusals, both coin-toss paths, the second-half chooser), the half-start validator, the kickoff pool convention, the bucket
  labels, scoring (a touchdown then its try then the scorer's kickoff, a missed extra point, a two-point try, a made and a missed
  field goal, a thin cell that blocks), the clock (a touchdown on the last play of Q1, a score that expires Q2 with no
  post-score kickoff, a punt that expires Q1 with the receiver keeping the ball, a kick that runs the clock out), halftime, the
  reference being required, the E2 profile id passed to E1, and the matrix (a clean game has no FAIL, and mutated records do
  fail: a repeated kicker, a points total that disagrees with the drives, and a clock that rises inside a quarter).
- `python3 -m unittest scripts/nfl_sequence/test_e1_transitions.py` (inherited from E1): **11 of 11 pass**.
- Both files together: **40 tests OK**.

## Kick outcomes in the dev database

The published rates the engine draws from. `nfl_pbp` (the curated nflverse table on dev) keeps `series_result` and `success`,
and does not keep the dedicated `field_goal_result`, `extra_point_result`, `two_point_conv_result` or `kick_distance` columns.
The outcomes are in the kept columns:

- **Field goal:** `series_result` = `Field goal` (made) or `Missed field goal` (missed), on `play_type = 'field_goal'`.
  Excluded: 18 `QB kneel`, 8 `Opp touchdown`, 1 `Turnover`.
- **Extra point:** `success` = 1 (good) or 0 (missed), on `play_type = 'extra_point'` with `series_result` in (`Touchdown`,
  `Opp touchdown`).
- **Two-point try:** `success` = 1 (converted) or 0 (not), on `two_point_attempt = 1`.

Primary window: 2022–2025, weeks 1–18, the same window E1 samples from.

| draw | published rate | made / missed in the window | floor per cell |
| --- | ---: | ---: | ---: |
| field goal, by `yardline_100` 1–9 / 10–19 / 20–29 / 30–39 / 40–49 / 50+ | 98.2 / 95.0 / 83.1 / 72.6 / 54.9 / 25.0% | 698/13, 1109/58, 980/200, 809/305, 67/55, 1/3 | 30 attempts |
| extra point | 95.4% | 4644 / 226 | 30 attempts |
| two-point try | 47.2% | 240 / 269 | 30 attempts |
| two-point share of post-touchdown attempts | 9.5% | 509 of 5,379 | none |

Field goals by bucket, with Wilson 95% intervals (kick yards are about `yardline_100 + 17`):

| `yardline_100` | kick (yards) | made | missed | make rate | Wilson 95% |
| --- | --- | ---: | ---: | ---: | --- |
| 1–9 | 18–26 | 698 | 13 | 98.2% | 96.9–98.9% |
| 10–19 | 27–36 | 1109 | 58 | 95.0% | 93.6–96.1% |
| 20–29 | 37–46 | 980 | 200 | 83.1% | 80.8–85.1% |
| 30–39 | 47–56 | 809 | 305 | 72.6% | 69.9–75.2% |
| 40–49 | 57–66 | 67 | 55 | 54.9% | 46.1–63.5% |
| 50+ | 67+ | 1 | 3 | 25.0% | 4.6–69.9% (n = 4, thin) |

Sensitivity: counting the 8 `Opp touchdown` field-goal rows as misses moves the make rate from 85.2% to 85.1%. Five of those
eight are followed by an extra point by the other team, which fits a missed kick returned for a touchdown. They stay excluded.

Per-season stability (all seasons): field goals stay between 81.7% (2019) and 86.6% (2013). Extra points are 98.8–99.6%
through 2014 and 92.4–95.9% from 2015, a step that fits the 2015 rule change moving the PAT to the 15-yard line. That rule
change is general knowledge, not something the database records.

Checks independent of `series_result`: of 3,664 made field goals, 3,071 are followed by a kickoff received by the other team
and none by a kickoff received by the kicking team; of 634 missed, 464 are followed by a run, pass or kneel by the other team.
Five rows disagree (three made, followed by a scrimmage play; two missed, followed by a pass by the kicking team).

Two-point tries: mean EPA is +1.053 on converted and −0.962 on failed, which is consistent with `success`. No TD flag is set on
any two-point try, and there are no score columns, so the two-point rate is checked against EPA only.

Reproduce: `python3 scripts/nfl_sequence/measure_kick_outcomes.py` (read-only, `mode=ro`, about 5 seconds).

## Decided and still open

- **Decided (Micah, 2026-10-24): consume the published outcomes.** The field-goal and try blocker is gone. The
  `field_goal_result_unpublished` key appears in no record.
- **Open, for Micah:**
  - The six unmodelled rules listed under "Decisions" (timeouts, two-minute warning, penalties, onside kicks, overtime,
    lineups). Each one blocks `valid_full_game`.
  - The two rules marked as NFL practice rather than the rules file (the post-score kickoff at the end of Q1 or Q3, and the
    absence of one at the end of Q2). Confirm against the 2026 rulebook.
  - Whether the 8 `Opp touchdown` field-goal rows count as misses (85.2% becomes 85.1%).
  - Whether the two-point rate should be trusted before a score-based check exists.

## Not done

- **Timeouts, two-minute warning, penalties, untimed downs, onside kicks, overtime, exception coin-toss paths, and lineups.**
  Listed in `unsupported_rules` for every record.
- **Blocked kicks, returned misses, and touchbacks on a missed kick.** Not modelled.
- **Clock realism.** Kickoff and drive times are the sampled intervals from the observed data.
- **E1 pool coverage.** Some E1 pool cells have too few observed plays; E1 refuses them and the game is blocked.
