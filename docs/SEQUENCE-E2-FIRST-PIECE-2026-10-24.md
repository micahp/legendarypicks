# NFL sequence generator, LP E2 first piece: kickoffs, linkage, the game ledger and the kick outcomes (2026-10-24)

Branch `feat/nfl-sequence-e2-kickoffs-2026-10-24`, rebased onto the E1 head `2248f7e1`. Modules:
`scripts/nfl_sequence/game_state.py` (state machine), `scripts/nfl_sequence/test_game_state.py` (20 tests),
`scripts/nfl_sequence/game_survey.py` (300-game survey) and `scripts/nfl_sequence/measure_kick_outcomes.py` (read-only
kick-outcome table from the dev database, which the survey passes to the engine). This branch does not change the E1
generator or its fixtures.

**Status: the engine consumes the published kick outcomes, and 229 of 300 seeded games are valid full games.** Of the 300,
236 reach the end of regulation. Seven of those are tied, so they are invalid, because overtime is not modelled. The other 64
are blocked, each with a named reason (see "Survey"). No field-goal blocker remains. Each kick draw is a labelled sample from
a published rate, and it is not the outcome of a real game.

## Decision D: E1 uses the shared play-ID form; E2 records use their own mode

At `2248f7e1` E1 emits play IDs `e1-<start>-seed<n>:<sequence>`, the shared form. The earlier form, `e1-seed<seed>:<sequence>`,
is gone: the E1 branch aligned itself to the shared contract. `e1_drive.simulate()` takes a `simulation_id`, and E2 passes
its own profile id, `e2-<seed>-drive<n>`, one per drive. The shared full-game contract `GRIDIRON-CONTRACT-v1` is not
changed by this branch. E2 game records keep their own mode, `legal_game_state_first_piece`. E2 records keep drive summaries
only, so no E1 play ID reaches an E2 record today. A unit test spies on the call and pins the profile id.

## Normal-game policy (rules file, sections 3 and 7)

- The first-choice captain receives. A `kick` or `defend_goal` choice is refused in normal mode.
- Each team kicks off once per half. The defer path gives the loser the first-half choice and the winner the second-half
  choice. The receive path gives the reverse.
- `validate_half_start` fails closed: exactly two half-start kickoffs, one per team, and the Q3 receiver kicked the Q1
  kickoff. A game blocked before halftime has only the Q1 kickoff, so the two-kickoff check applies only once Q3 starts.
- The exception coin-toss paths (`explicit_exception_scenario`) are not implemented. Asking for them raises an error.

## Linkage rules

| E1 terminal | Next restart in this piece |
| --- | --- |
| `punt`, `turnover`, `turnover_on_downs` | The receiving offense continues from its published spot. No kickoff. |
| `touchdown` | Points: 6, then a try. An extra point (1) at the published extra-point rate, or a two-point try (2) at the published two-point rate, chosen at the measured share of post-touchdown attempts (9.5%). Then the scoring team kicks off to the other team (`post_score`). |
| `safety` | Points: 2 for the defense. The conceding team kicks the free kick (`safety_free_kick`). |
| `halftime` | Q3 kickoff from the ledger (`half_start`). The clock resets to 15:00. |
| `end_of_regulation` | Game complete. A tie is not valid, because overtime is not modelled. |
| `field_goal_attempt` | Made, drawn at the published make rate for its `yardline_100` bucket: 3 points, then the kicker kicks off (`post_field_goal`). Missed: the other team takes over at the spot of the kick, `100 - yardline_100`, first and ten. |

Each restart samples a kickoff from the pool: the receiving team's first run or pass in the same quarter gives the spot,
and the kickoff's clock runoff comes from the published interval. If the restart would cross the quarter end, the game
blocks with `restart_crosses_quarter_end`. That includes a score in the last seconds of a half.

A punt, turnover or missed field goal with the clock already at 0:00 blocks the game with `possession_change_at_zero_clock`.
Quarter-end handling for a change of possession is not modelled, so the game is not guessed through it.

**Kickoff convention in the published data.** On a kickoff row `posteam` is the receiving team, and `defteam` is the
kicking team. This is the reverse of the punt convention, and the pool is built on it. A clean receiving snap was found
for 10,037 kickoffs, and 962 were excluded.

## Orientation

Authored, not sourced, and labelled in every record. The goal-first-half team defends x=0 in Q1. Ends change after Q1
and after Q3, and halftime does not flip ends. The Q3 orientation uses the second-half goal choice.

## Survey (300 seeded games, `scripts/nfl_sequence/game_survey.py --games 300`, at `ca418fbd` plus this pass)

```
games=300 validated=300 valid_full_game=229
status {'complete_regulation': 236, 'blocked': 64}
blocker {None: 236, 'thin_kick_cell:field_goal:50+': 2, 'restart_crosses_quarter_end': 36, 'possession_change_at_zero_clock': 25, "thin pool cell (2, '11+', '1-9') (0 observed plays, floor 50); no fallback": 1}
reached the Q3 half-start kickoff: 261 (87.0%)
field goals drawn: {'made': 1014, 'missed': 240}
tries drawn: {'extra_point made': 891, 'two_point made': 43, 'two_point missed': 67, 'extra_point missed': 42}
points per game: mean 34.4
drives per game: mean 20.5, max 30
kickoff pool: usable 10037, excluded {'kickoff without a clean receiving snap': 962}
kick table: nfl_pbp season BETWEEN 2022 AND 2025 AND week <= 18
```

Every game passed `validate_game`. The earlier survey, which stopped every game at its first field goal, is superseded: no
game is blocked by a field goal now. The seven complete games that are not valid are ties. The 64 blocked games are:

- 36 `restart_crosses_quarter_end`: a restart with no time left in the quarter, including a score in the last seconds of a half.
- 25 `possession_change_at_zero_clock`: a punt, turnover or missed field goal with the clock at 0:00.
- 2 `thin_kick_cell:field_goal:50+`: that cell has 4 attempts in the window, below the floor of 30.
- 1 E1 pool cell with no observed plays, `(2, '11+', '1-9')`. E1 refuses it, as it was designed to.

The draws sit inside the published rates. Field goals drawn: 1014 made of 1254, 80.9% (the published rate is 85.2%; the gap is not
explained here, and the per-bucket mix of the E1 sample is not checked). Extra points: 891 of 933, 95.5% (published 95.4%). Two-point tries: 43 of 110, 39.1%
(published 47.2%; 110 draws carry a 95% interval of about ±9 points). Two-point tries are 10.5% of post-touchdown attempts
(published 9.5%).

## Tests

- `python3 -m unittest scripts/nfl_sequence/test_game_state.py`: **20 of 20 pass**. They cover the ledger (refusals, both
  coin-toss paths, the second-half chooser), the half-start validator (same-team refusal, ledger agreement), the kickoff pool
  convention (receiving-team posteam, and exclusion of a kicker's next snap), the bucket labels, a touchdown taking its try
  before the scorer's kickoff, a missed extra point (6), a two-point try (8), a made field goal (3, then the kicker's kickoff),
  a missed field goal (the other team starts at the kick's spot, checked by spying on E1's start state), a thin cell blocking
  without a fill, halftime producing the Q3 kickoff, the kick table being required, a touchdown whose points disagree with its
  try being refused, and the E2 profile id passed to E1 on every drive.
- `python3 -m unittest scripts/nfl_sequence/test_e1_transitions.py` (inherited from E1): **11 of 11 pass**. It had 10 at
  `e621e83e`; the E1 branch added one.
- Both files together: **31 tests OK**.

## Kick outcomes in the dev database: the "not published" claim was false

The earlier text said the dev database has no field-goal or try results. That was checked against column names only.
The ingest for `nfl_pbp` (`backend/ingest_nfl_pbp_logs.py` on dev) keeps nflverse's `series_result` and `success` columns.
It does not keep nflverse's dedicated `field_goal_result`, `extra_point_result`, `two_point_conv_result` or `kick_distance`
columns, which is why the name check came up empty. The outcomes are in the kept columns:

- **Field goal:** `series_result` = `Field goal` (made) or `Missed field goal` (missed), on `play_type = 'field_goal'`.
- **Extra point:** `success` = 1 (good) or 0 (missed), on `play_type = 'extra_point'` with `series_result` in
  (`Touchdown`, `Opp touchdown`).
- **Two-point try:** `success` = 1 (converted) or 0 (not), on `two_point_attempt = 1`.

So the engine's gap text was wrong. It is corrected, and the engine now consumes these outcomes (see "Consumed in E2").

Reproduce with `python3 scripts/nfl_sequence/measure_kick_outcomes.py`. It opens `/root/legendarypicks/backend/data/picks.dev.db`
with `mode=ro` and takes about 5 seconds. The primary window is 2022–2025, weeks 1–18, the same window E1 samples from.

### Field goals: outcome and exclusions (primary window)

| `series_result` | rows | treatment |
| --- | ---: | --- |
| `Field goal` | 3664 | made |
| `Missed field goal` | 634 | missed |
| `QB kneel` | 18 | excluded: a kneel, not a kick |
| `Opp touchdown` | 8 | excluded (see sensitivity) |
| `Turnover` | 1 | excluded |

**Make rate 3664 / 4298 = 85.2%** (Wilson 95%: 84.2–86.3%). Mean EPA: made +0.712, missed −3.106.

Sensitivity: counting the 8 `Opp touchdown` rows as misses gives 3664 / 4306 = 85.1%. Five of those eight are followed by an
extra point by the other team, which fits a missed kick returned for a touchdown. That is a judgment call, so it stays excluded
here.

### Field goals: make rate by field position (primary window)

`yardline_100` is the distance to the opponent's end zone at the snap. The kick is about `yardline_100 + 17` yards.

| `yardline_100` | kick (yards, approx.) | made | missed | make rate | Wilson 95% |
| --- | --- | ---: | ---: | ---: | --- |
| 1–9 | 18–26 | 698 | 13 | 98.2% | 96.9–98.9% |
| 10–19 | 27–36 | 1109 | 58 | 95.0% | 93.6–96.1% |
| 20–29 | 37–46 | 980 | 200 | 83.1% | 80.8–85.1% |
| 30–39 | 47–56 | 809 | 305 | 72.6% | 69.9–75.2% |
| 40–49 | 57–66 | 67 | 55 | 54.9% | 46.1–63.5% |
| 50+ | 67+ | 1 | 3 | 25.0% | 4.6–69.9% (n = 4) |

The gradient is as expected: near-certain inside the 10, falling through the 30s and 40s. The 50+ bucket has four attempts,
so it says almost nothing.

### Extra points (primary window)

**4644 made / 226 missed = 95.4%** (Wilson 95%: 94.7–95.9%). Made rows: `Touchdown` with `success` 1, 4431; `Opp touchdown`
with `success` 1, 213. Missed rows: `Touchdown` with `success` 0, 209; `Opp touchdown` with `success` 0, 17.
Exclusions in the window: none. Across all seasons, two extra-point rows carry the `Punt` and `First down` labels; they are
excluded.

### Two-point tries (primary window)

**240 converted / 509 tries = 47.2%** (Wilson 95%: 42.9–51.5%). The brief's "~46.8%" does not reproduce; the measured value is 47.2%.
The 509 include 7 tries whose `play_type` is `no_play` (5 converted, 2 not). The check is weaker than the other two: mean EPA is
+1.053 on converted tries and −0.962 on failed ones, which is consistent with `success`. But no TD flag (`touchdown`,
`pass_touchdown`, `rush_touchdown`) is set on any of the 509, converted or not, and the table has no score columns. So the
two-point rate is consistent with EPA but not independently verified.

### Field goals: the next play in the same game (primary window; does not use `series_result`)

- **Made (3664):** 3071 are followed by a kickoff received by the other team. None is followed by a kickoff received by the
  kicking team. 3 are followed by a scrimmage play (1 by the other team, 2 by the kicking team). The rest: 424 by a `no_play`
  (a penalty), 132 with no following row, 34 with a null `play_type`.
- **Missed (634):** 464 are followed by a run, pass or QB kneel by the other team. 2 are followed by a pass by the kicking team.
  The rest: 125 by a `no_play`, 43 with no following row or a null `play_type`.

Across those rows the labels agree with the next play except five: three made field goals followed by a scrimmage play, and
two missed ones followed by a pass from the kicking team. Those five are the residual disagreement, and they are not explained here.

### Per-season stability (all seasons)

| season | FG made | FG missed | FG make | EP made | EP missed | EP make |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2010 | 794 | 168 | 82.5% | 1203 | 14 | 98.8% |
| 2011 | 835 | 173 | 82.8% | 1200 | 7 | 99.4% |
| 2012 | 849 | 162 | 84.0% | 1229 | 8 | 99.4% |
| 2013 | 862 | 133 | 86.6% | 1262 | 5 | 99.6% |
| 2014 | 828 | 156 | 84.1% | 1222 | 9 | 99.3% |
| 2015 | 833 | 152 | 84.6% | 1145 | 71 | 94.2% |
| 2016 | 848 | 157 | 84.4% | 1118 | 76 | 93.6% |
| 2017 | 864 | 160 | 84.4% | 1066 | 68 | 94.0% |
| 2018 | 800 | 143 | 84.8% | 1164 | 71 | 94.3% |
| 2019 | 799 | 179 | 81.7% | 1136 | 74 | 93.9% |
| 2020 | 812 | 147 | 84.7% | 1244 | 103 | 92.4% |
| 2021 | 870 | 152 | 85.1% | 1174 | 83 | 93.4% |
| 2022 | 899 | 157 | 85.1% | 1123 | 64 | 94.6% |
| 2023 | 906 | 148 | 86.0% | 1121 | 48 | 95.9% |
| 2024 | 934 | 175 | 84.2% | 1190 | 56 | 95.5% |
| 2025 | 925 | 154 | 85.7% | 1210 | 58 | 95.4% |
| 2026 (to wk 7) | 337 | 57 | 85.5% | 410 | 25 | 94.3% |

Field-goal make rate stays between 81.7% (2019) and 86.6% (2013) in every season. Extra points show a step at 2015: 98.8–99.6%
before, 92.4–95.9% after. The step fits the 2015 rule change that moved the PAT to the 15-yard line. That rule change is from
general knowledge; nothing in the database records it.

### SQL behind the primary-window numbers

```sql
-- field goals: outcome and exclusions
SELECT series_result, COUNT(*) FROM nfl_pbp
WHERE play_type = 'field_goal' AND season BETWEEN 2022 AND 2025 AND week <= 18
GROUP BY series_result;

-- field goals: make rate by yardline_100
SELECT CASE WHEN yardline_100 < 10 THEN '1-9' WHEN yardline_100 < 20 THEN '10-19'
            WHEN yardline_100 < 30 THEN '20-29' WHEN yardline_100 < 40 THEN '30-39'
            WHEN yardline_100 < 50 THEN '40-49' ELSE '50+' END AS bucket,
       SUM(series_result = 'Field goal') AS made,
       SUM(series_result = 'Missed field goal') AS missed
FROM nfl_pbp
WHERE play_type = 'field_goal' AND season BETWEEN 2022 AND 2025 AND week <= 18
  AND series_result IN ('Field goal', 'Missed field goal')
GROUP BY bucket ORDER BY bucket;

-- extra points
SELECT success, COUNT(*) FROM nfl_pbp
WHERE play_type = 'extra_point' AND series_result IN ('Touchdown', 'Opp touchdown')
  AND season BETWEEN 2022 AND 2025 AND week <= 18
GROUP BY success;

-- two-point tries
SELECT success, COUNT(*) FROM nfl_pbp
WHERE two_point_attempt = 1 AND season BETWEEN 2022 AND 2025 AND week <= 18
GROUP BY success;
```

The next-play check and the per-season tables are in `measure_kick_outcomes.py` (sections 2, 4 and 5).

## Consumed in E2 (this pass)

The engine takes its kick table from `measure_kick_outcomes.load_kick_table()`, which reads the primary window above, and it
refuses to run without one. Each draw is a labelled sample at the published rate:

| draw | published rate | made / missed in the window | floor per cell |
| --- | ---: | ---: | ---: |
| field goal, by `yardline_100` bucket | 98.2, 95.0, 83.1, 72.6, 54.9, 25.0% | 698/13, 1109/58, 980/200, 809/305, 67/55, 1/3 | 30 attempts |
| extra point | 95.4% | 4644 / 226 | 30 attempts |
| two-point try | 47.2% | 240 / 269 | 30 attempts |
| two-point share of post-touchdown attempts | 9.5% | 509 of 5,379 | none (the try cell has its own floor) |

A cell below its floor blocks the game (`thin_kick_cell:<name>`). Nothing is filled from a neighbouring cell. The
`yardline_100` buckets are 1–9, 10–19, 20–29, 30–39, 40–49 and 50+. Only the 50+ cell is thin.

These are league-wide rates for attempts at a field position, not a model of any kicker. The missed-field-goal spot follows the
rules file's change-of-possession rule, `new yardline_100 = 100 - old yardline_100`, with the ball at the same dead-ball spot.
Blocked kicks, returned misses and touchbacks on a missed kick are not modelled.

## Decided and still open

- **Decided (Micah, 2026-10-24): consume the published outcomes.** The field-goal and try blocker is gone. The
  `field_goal_result_unpublished` key appears in no record.
- **Open, for Micah:**
  - The 36 `restart_crosses_quarter_end` and 25 `possession_change_at_zero_clock` blocks are clock-edge cases. The rules
    file does not settle them in this piece: a change of possession at quarter end, and a score in the last seconds of a
    half. They are blocked, not guessed. Resolving them is the next rules step.
  - Whether the 8 `Opp touchdown` field-goal rows count as misses (85.2% becomes 85.1%).
  - Whether the two-point rate should be trusted before a score-based check exists. `nfl_pbp` has no score columns, and no TD
    flag is set on any two-point try, so the check is EPA only.

## Not done

- **Clock-edge cases** (above). 61 of the 64 blocked games stop on them.
- **Onside kicks, overtime, penalties, timeouts, the two-minute warning, and the exception coin-toss paths.** Not modelled.
- **Blocked kicks, returned misses, and touchbacks on a missed kick.** Not modelled.
- **Player statistics.** Null. No participants are supplied, and none are sampled.
- **Clock realism.** Kickoff and drive times are the sampled intervals (boundary 2 from E1).
- **E1 pool coverage.** One cell, `(2, '11+', '1-9')`, has no observed plays. E1 refuses it, and the game is blocked.
