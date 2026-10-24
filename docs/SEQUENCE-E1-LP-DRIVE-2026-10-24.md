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

## What the generator does

- **Start.** An authored possession state from `STARTS` in `scripts/nfl_sequence/e1_drive.py`. The `dir` field is the
  start offense's authored orientation in its starting quarter, labelled `authored_demo_orientation`.
- **Play.** Each play samples an observed 2022–2025 regular-season play from the same down, distance and field cell.
  Events: `run`, `pass_complete`, `pass_incomplete`, `sack`, `interception`, `fumble_lost`, `punt`,
  `field_goal_attempt`. The reducer applies the sampled outcome.
- **Reducer.** `scripts/nfl_sequence/reducer.py`, shared with E0. A touchdown is decided from the state's own yardline,
  not from the sampled row's flag. A turnover or punt starts the receiving offense at the published spot of its next
  snap. A field-goal attempt is a terminal with no result, because made or missed is not in the published columns.
- **Quarter and half transitions** (rules file, sections 2 and 3):
  - Q1 and Q3 expiry: both teams change ends. The drive and series continue, with no kickoff and no drive terminal.
    The start offense's direction flips.
  - Q2 expiry: `halftime` terminal. The first-half drive ends, and the scrimmage state is null.
  - Q4 expiry: `end_of_regulation` terminal. Overtime is not modelled.
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
- **Personnel and game time.** Not conditioned. Time enters only through the derived clock.
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

The drive summary is recomputed from the play records: plays, yards, first downs, turnovers, punts, field-goal attempts,
quarter changes, clock runoff and negative-yardage plays.

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

Each fixture was generated and rerun byte-identically.

| File | Terminal | Plays | Yards | First downs | Quarter changes | Negative-yardage plays | SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `own25_q1_900-seed6-touchdown.json` | touchdown | 11 | 77 | 4 | 0 | 1 | `12a5e26518966c8ef4ad3ed54f5f406b28d03374b2bd33b3f2072486f09eea38` |
| `own25_q1_900-seed12-turnover.json` | turnover | 4 | 21 | 1 | 0 | 0 | `c3404c15eae702e886ea8f0e9500fd8f08440ce83a2624a4f6e308fdecc9371a` |
| `own25_q1_900-seed1-punt.json` | punt | 7 | 26 | 2 | 0 | 0 | `cd1bf00a38257bf33935af9161cd39e0f5034f89d511f426de235b154c39b0b3` |
| `own25_q1_900-seed2-field_goal_attempt.json` | field_goal_attempt | 12 | 55 | 4 | 0 | 2 | `6eca1064d391e1510d69cd4f344a882286b9c0b77f4fa1eb461b9515d15bccdd` |
| `own25_q2_120-seed15-turnover_on_downs.json` | turnover_on_downs | 4 | −9 | 0 | 0 | 2 | `7c5d49a5a0cc39ed1e8d15e24217f0a210451b68a53a6fb6bbf9912ab569ac3b` |
| `own25_q2_120-seed1-halftime.json` | halftime | 4 | 22 | 2 | 0 | 0 | `67785be05b4ae869f4cc93387442f044214e6466e86b21892f9465ec6d37c9bf` |
| `own25_q4_150-seed1-end_of_regulation.json` | end_of_regulation | 5 | 26 | 2 | 0 | 0 | `19b866af330cd3315d9bfe28974f9c26972ac7c49e4c04313cc005b52c2c79b0` |
| `own5_q1_900-seed14-safety.json` | safety | 3 | −18 | 0 | 0 | 2 | `81e062cebc30b6bfd649a269deec8c16206438d2a6b53c8ad1745c2dbc7fcf95` |
| `own25_q1_060-seed1-quarter_change_then_punt.json` | punt | 7 | 26 | 2 | 1 | 0 | `eb8d0d8bafad81f3053233b87b7c47172bfe276de4d9d7e70488ff4845d61f3f` |
| `own25_q3_060-seed1-quarter_change_then_punt.json` | punt | 7 | 26 | 2 | 1 | 0 | `351e6197bc408e7474151d80e18871f4510ad69a7a3fda1e3831c86cb0bb5624` |

What each fixture shows:

- **Touchdown:** positive and negative plays (one negative-yardage play), ending on a touchdown. Points not computed.
- **Turnover:** interception or fumble, with the new offense at the published spot.
- **Turnover on downs in Q2:** the rules-file matrix row. The other offense takes over at the complementary spot, and the
  direction flips.
- **Punt:** the receiving team starts at the published spot.
- **Field-goal attempt:** terminal with no result.
- **Halftime:** Q2 expiry ends the first-half drive. There is no kickoff and no scrimmage state after the half.
- **End of regulation:** Q4 expiry. Overtime is not modelled.
- **Safety:** scrimmage state is null. The free kick is not modelled.
- **Quarter change then punt:** Q1 and Q3 expiry each flip the direction and continue the drive with no kickoff.

Each fixture's `gaps` list states that second-half kickoffs, points, participants and player stats are not modelled.

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
- **Touchdown points and score** are not computed, so score agreement with a play log cannot be tested.
- **Sampling** uses observed plays from 2022–2025 with no as-of cutoff. The rules file notes that a pool containing future
  games does not validate a forecast, and this pool contains them.
