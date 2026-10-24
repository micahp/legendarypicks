# NFL sequence generator, LP E1 drive status (2026-10-24, revised)

Stacked on `feat/nfl-sequence-e0-2026-10-24`. Plan: `docs/END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md`
(Gridiron repo, main). Rules: `docs/rules/NFL-2026-GAME-STATE-RULES.md` on legendarypicks `dev`.

**Status: scoped research drive, not a legal game.** The generator produces one possession's drive and its quarter and
half transitions. Second-half kickoffs are not modelled, so no record can say `valid_full_game: true`. Every record is
`valid_full_game: false`, retrospective, and carries its gaps. This is not evidence that sampled drives reproduce NFL
drive outcomes.

This revision replaces the earlier draft. That draft ended drives at Q1 and Q3 expiry and had no punts or field goals.
Its `end_of_period` terminal, survey and fixtures are superseded. They are kept in
`docs/fixtures/e1/superseded-end-of-period-2026-10-24/`.

## Handoff boundaries

These two limits must travel with any handoff from E1. Passing `check_drive` does not remove either one.

1. **A field-goal attempt has no result.** The `nfl_pbp` table has no field-goal result column. I checked for any column
   name containing `kick`, `punt`, `field_goal` or `fg`, and found none. The
   attempt is a terminal with no points and no next possession. A made kick's kickoff, and a missed kick's change of
   possession, are not modelled. The next play after a field goal is usually a kickoff in the pool (3,071 of 4,325 field-goal
   rows), which suggests a derivation, but that derivation is not implemented and has not been checked against any
   result. Until it is, no record can reconcile points or the possession that follows a field-goal attempt.

2. **Clock runoff is a sampled interval, not a clock model.** Runoff is the time between consecutive published snaps
   in the same quarter. It is not a game-clock model: there are no clock-stop rules, timeouts or two-minute warning. A
   runoff longer than the remaining quarter time is clamped to zero, and each play carries `clock_clamped_to_zero`.
   Measured on the survey below (1,200 drives, four starts at 300 seeds each): **594 of 7,016 plays (8.5%) are clamped,
   and 594 of 1,200 drives (49.5%) contain one.** In this sample each clamped drive has exactly one clamp, and it
   leaves the clock at zero on the play that reaches it. Pooled runoffs across
   138,235 plays have a median of 32 s, a 90th percentile of 44 s, and a maximum of 289 s. The checker verifies that the
   clock is monotone and reconciles across plays. It does not verify that the clock is realistic.

## What the generator does

- **Start.** An authored possession state from `STARTS` in `scripts/nfl_sequence/e1_drive.py`. The `dir` field is the
  start offense's authored orientation in its starting quarter, labelled `authored_demo_orientation`.
- **Play.** Each play samples an observed 2022–2025 regular-season play from the same down, distance and field cell.
  Events: `run`, `pass_complete`, `pass_incomplete`, `sack`, `interception`, `fumble_lost`, `punt`,
  `field_goal_attempt`. The reducer applies the sampled outcome.
- **Reducer.** `scripts/nfl_sequence/reducer.py`, shared with E0. A touchdown is decided from the state's own yardline,
  not from the sampled row's flag. A turnover or punt starts the receiving offense at the published spot of its next
  snap. A field-goal attempt is a terminal with no result (boundary 1).
- **Quarter and half transitions** (rules file, sections 2 and 3):
  - Q1 and Q3 expiry: both teams change ends. The drive and series continue, with no kickoff and no drive terminal.
    The start offense's direction flips.
  - Q2 expiry: `halftime` terminal. The first-half drive ends, and the scrimmage state is null.
  - Q4 expiry: `end_of_regulation` terminal. Overtime is not modelled.
- **Halftime and regulation endpoint (schema 1.1).** A `halftime` or `end_of_regulation` record has a null scrimmage state
  and a null field endpoint (`field.after.dir` and `los` are null). The final play's position is kept in
  `outcome.final_play_yardline_100`, and is not a scrimmage state. Records before 1.1 used a field endpoint at these
  terminals, and that is superseded. The drive profile is now `schema_version` 1.1; the E0 record stays at 1.0.
- **Orientation.** The start offense flips at each change of ends only. The other team is always opposite. Halftime does
  not flip. The v1 convention (`e0-field-end-v1`), which gave every offense the same direction, is not used by E1.

## Rules not yet modelled

The rules file, section 7, requires these before E2 can call a game complete:

- **Half-start kickoffs.** Normal simulations require exactly two `half_start` kickoffs, one by each team, with the
  first-choice team choosing to receive. E1 models neither the toss nor the kickoffs, so it cannot test that invariant.
  Halftime records say so.
- **Points.** Touchdown, field-goal and safety points are not computed. There are no extra points, two-point tries, or
  post-score kickoffs.
- **Participants and player stats.** Null. There is no pregame roster.
- **Personnel and game time.** Not conditioned. Time enters only through the derived clock (boundary 2).
- **Timeouts, two-minute warnings, penalties, overtime.** Not modelled. Penalty plays are excluded from the pool.
- **Fourth downs.** The choice is sampled from the observed mix in the cell: go-for-it, punt or field-goal attempt. It is
  not conditioned on time or score, which the pool does not carry.
- **Quarter in sampling.** The pool does not condition on quarter, so Q1 and Q3 starts draw the same plays from the same
  seed. Their outcomes differ only in quarter labels and in when a quarter change happens.

## Pool

Usable plays: **138,235** (2022–2025 regular season). Pool digest:
`cf2872733890820801822cdfb914256e3f8adcc3398c5895bad40e747092cfd4`.

Excluded from the pool, counted by the generator:

| Reason | Plays |
| --- | ---: |
| penalty (not modelled) | 2,666 |
| qb_scramble (not in the E1 vocabulary) | 3,883 |
| punt without a clean receiving-team snap | 969 |
| turnover without a clean new-offense snap | 366 |
| turnover that is a touchdown (not modelled) | 204 |
| negative derived clock runoff | 53 |
| no same-quarter next snap for clock runoff | 27 |

A punt is kept only if its next snap is a run or pass by the receiving team in the same quarter. That excludes return
touchdowns, penalties and plays with no following snap, so it conditions on the punt's outcome.

A field-goal attempt is kept if the next row is in the same quarter. It is not selected on its result.

Cells with fewer than 50 observed plays stop the drive with the reason `thin pool cell`. No fallback is used. In this
survey no drive stopped that way.

## Survey (1,200 seeds per start, six starts)

| Start | Touchdown | Turnover | Turnover on downs | Punt | Field-goal attempt | Safety | Halftime | End of regulation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `own25_q1_900` (own 25, 1st & 10, Q1 15:00) | 212 | 117 | 110 | 504 | 257 | 0 | 0 | 0 |
| `midfield_q3_900` (own 50, 1st & 10, Q3 15:00) | 342 | 94 | 126 | 200 | 438 | 0 | 0 | 0 |
| `own25_q2_120` (own 25, 1st & 10, Q2 2:00) | 34 | 74 | 32 | 313 | 23 | 0 | 724 | 0 |
| `own25_q4_150` (own 25, 1st & 10, Q4 2:30) | 48 | 84 | 41 | 378 | 52 | 0 | 0 | 597 |
| `own40_q4_4th5_600` (own 40, 4th & 5, Q4 10:00) | 16 | 15 | 69 | 1,078 | 22 | 0 | 0 | 0 |
| `own5_q1_900` (own 5, 1st & 10, Q1 15:00) | 147 | 113 | 67 | 653 | 174 | 46 | 0 | 0 |
| **Total** | **799** | **497** | **445** | **3,126** | **966** | **46** | **724** | **597** |

All 7,200 complete drives passed `check_drive`. None were incomplete.

Two short-clock starts (600 seeds each) exercise quarter changes:

| Start | Touchdown | Turnover | Turnover on downs | Punt | Field-goal attempt | Drives with a quarter change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `own25_q1_060` (Q1 0:60) | 105 | 49 | 54 | 266 | 126 | 511 of 600 |
| `own25_q3_060` (Q3 0:60) | same as `own25_q1_060` | | | | | |

These drives reach halftime or regulation after a change of ends. Turnover on downs is the rate the sampler produces,
not a football estimate. The 4th-down mix is observed, and time and score are not conditioned.

## Checks

`check_drive` runs on every complete drive before it can be written. It fails on any inconsistency. It checks:

- each play's `state_before` equals the previous play's `state_after` for quarter, offense, down, distance, field and
  clock;
- the clock never goes negative, never increases within a quarter, and changes only with a quarter change (which resets
  it to 15:00 and sets `quarter_change`);
- a quarter change never ends a drive, and it moves exactly one quarter forward;
- a halftime terminal sits at the end of Q2 with clock 0. A regulation terminal sits at the end of Q4 with clock 0;
- a non-terminal play has a legal down (1–4), field (1–99) and distance (at least 1);
- the last play carries the drive's terminal, and only the last play does;
- possession changes exactly when the outcome is a turnover or a punt;
- `touchdown` is true exactly when the terminal is a touchdown;
- field-goal attempts have no next field position, and punts give the receiving spot;
- each direction is +1 or −1, and each `los` is in 0–100.

The checker is bookkeeping. It does not test the realism of runoff (boundary 2) or of field-goal outcomes (boundary 1).

The drive summary is recomputed from the play records: plays, yards, first downs, turnovers, punts, field-goal attempts,
quarter changes, clock-clamped plays, clock runoff and negative-yardage plays.

The transition tests (`scripts/nfl_sequence/test_e1_transitions.py`, eight tests) cover:

- Q1 and Q3 expiry continuing the drive with the direction flipped;
- Q2 expiry as halftime, not a turnover on downs;
- Q4 expiry as regulation end;
- turnover on downs complementing field position;
- unknown events refused;
- a punt giving the receiving spot;
- a field-goal attempt with no result.

Run them with `python3 -m unittest scripts/nfl_sequence/test_e1_transitions.py`.

## Fixtures (`docs/fixtures/e1/`)

Each fixture was generated and rerun byte-identically after the boundary change.

| File | Terminal | Plays | Yards | First downs | Quarter changes | Negative-yardage plays | SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `own25_q1_900-seed6-touchdown.json` | touchdown | 11 | 77 | 4 | 0 | 1 | `fcef11c09b2992c8c0cb602588d75a1de054df79aac9c0cd2b591b5ffca3537a` |
| `own25_q1_900-seed12-turnover.json` | turnover | 4 | 21 | 1 | 0 | 0 | `0f42f55bd616b298548a37c4c0d14b8a3647a6b86111ec17f4043e4e7dcc74c3` |
| `own25_q1_900-seed1-punt.json` | punt | 7 | 26 | 2 | 0 | 0 | `67ae504795361501a09ce3e94317073576fc443ca7c3a542a009526106189182` |
| `own25_q1_900-seed2-field_goal_attempt.json` | field_goal_attempt | 12 | 55 | 4 | 0 | 2 | `e76ab3e343d58e5c567a14e7bf92d6300200f68b8333afaed97c5c697eb18e79` |
| `own25_q2_120-seed15-turnover_on_downs.json` | turnover_on_downs | 4 | −9 | 0 | 0 | 2 | `fac40496678828cdedf840c0a96d35075cfeaa22349068483418041b25b64002` |
| `own25_q2_120-seed1-halftime.json` | halftime | 4 | 22 | 2 | 0 | 0 | `ee58944fbb86503f7ac8dd14202afa427c57872ed9eb167b0813c9aecbb95e62` |
| `own25_q4_150-seed1-end_of_regulation.json` | end_of_regulation | 5 | 26 | 2 | 0 | 0 | `cecde97f37ede4a0c49028f18e165f0178ae2a36038dee04d1ffca95fb9e48a7` |
| `own5_q1_900-seed14-safety.json` | safety | 3 | −18 | 0 | 0 | 2 | `60e1acf10bba25634ecc82b70ca0afea4ece7b47d4fdf53c8e85221c419a1f60` |
| `own25_q1_060-seed1-quarter_change_then_punt.json` | punt | 7 | 26 | 2 | 1 | 0 | `1e1ad6ea0682de35f3b7cf487298b639d1953bc9dcb9eecd403fc292aa3dc0ba` |
| `own25_q3_060-seed1-quarter_change_then_punt.json` | punt | 7 | 26 | 2 | 1 | 0 | `740e5c5335f349224808ae116148cf51d34f527029c1a093b93de6893e4764a0` |

What each fixture shows:

- **Touchdown:** positive and negative plays (one negative-yardage play), ending on a touchdown. Points not computed.
- **Turnover:** interception or fumble, with the new offense at the published spot.
- **Turnover on downs in Q2:** the rules-file matrix row. The other offense takes over at the complementary spot, and the
  direction flips.
- **Punt:** the receiving team starts at the published spot.
- **Field-goal attempt:** terminal with no result (boundary 1).
- **Halftime:** Q2 expiry ends the first-half drive. There is no kickoff and no scrimmage state after the half.
- **End of regulation:** Q4 expiry. Overtime is not modelled.
- **Safety:** scrimmage state is null. The free kick is not modelled.
- **Quarter change then punt:** Q1 and Q3 expiry each flip the direction and continue the drive with no kickoff.

Each fixture's `gaps` list states both boundaries, the second-half kickoff, points, participants and player stats.

## Reproduce

```
cd /root/lp-nfl-sequence-e1
python3 -m unittest scripts/nfl_sequence/test_e1_transitions.py
python3 scripts/nfl_sequence/e1_drive.py --start own25_q1_900 --seed 6 --out docs/fixtures/e1/own25_q1_900-seed6-touchdown.json
python3 scripts/nfl_sequence/e1_drive.py --start own25_q1_060 --seed 1 --out docs/fixtures/e1/own25_q1_060-seed1-quarter_change_then_punt.json
python3 scripts/nfl_sequence/e1_drive.py --start own25_q1_900 --survey 200
```

The pool is read from `/root/legendarypicks/backend/data/picks.dev.db` read-only. The 2022–2025 rows must be unchanged
for the digest to match.

## Known defects and limitations

- **Half-start kickoffs** are the largest open item. Until they are modelled and tested, E1 cannot establish the rules
  file's normal-game invariant, and no E1 output may be presented as a game.
- **Field-goal results** (boundary 1). Points and the following possession cannot be reconciled until a made or missed
  result is sourced or derived and tested.
- **Clock realism** (boundary 2). Runoff is a sampled snap interval with quarter-end clamping, not a clock model.
- **Touchdown points and score** are not computed, so score agreement with a play log cannot be tested.
- **Sampling** uses observed plays from 2022–2025 with no as-of cutoff. The rules file notes that a pool containing future
  games does not validate a forecast, and this pool contains them.
