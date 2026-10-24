# NFL sequence generator, LP E2 first piece: kickoffs, linkage, the game ledger and the kick outcomes (2026-10-24)

Branch `feat/nfl-sequence-e2-kickoffs-2026-10-24`, rebased onto the E1 head `2248f7e1`. Modules:
`scripts/nfl_sequence/game_state.py` (state machine), `scripts/nfl_sequence/test_game_state.py` (13 tests),
`scripts/nfl_sequence/game_survey.py` (300-game survey) and `scripts/nfl_sequence/measure_kick_outcomes.py` (read-only
measurement of kick outcomes in the dev database). This branch does not change the E1 generator or its fixtures.

**Status: first piece, not a legal game.** The state machine links E1 drives into one game under the normal-game policy,
and it validates every game it produces. No game is valid. The engine still stops a game at its first field-goal attempt
and leaves every touchdown's try pending. Those results are published in `nfl_pbp`, so the stop is a policy decision for
Micah, not a gap in the data (see "Kick outcomes" below). Nothing is invented to fill either gap.

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
| `touchdown` | Points: 6, with the try pending. The scoring team kicks off to the other team (`post_score`). |
| `safety` | Points: 2 for the defense. The conceding team kicks the free kick (`safety_free_kick`). |
| `halftime` | Q3 kickoff from the ledger (`half_start`). The clock resets to 15:00. |
| `end_of_regulation` | Game complete. A tie is not valid, because overtime is not modelled. |
| `field_goal_attempt` | Game blocked: `field_goal_result_unpublished`. The key name predates the measurement below; it is kept so this pass changes no engine behaviour. |

Each restart samples a kickoff from the pool: the receiving team's first run or pass in the same quarter gives the spot,
and the kickoff's clock runoff comes from the published interval. If the restart would cross the quarter end, the game
blocks with `restart_crosses_quarter_end`.

**Kickoff convention in the published data.** On a kickoff row `posteam` is the receiving team, and `defteam` is the
kicking team. This is the reverse of the punt convention, and the pool is built on it. A clean receiving snap was found
for 10,037 kickoffs, and 962 were excluded.

## Orientation

Authored, not sourced, and labelled in every record. The goal-first-half team defends x=0 in Q1. Ends change after Q1
and after Q3, and halftime does not flip ends. The Q3 orientation uses the second-half goal choice.

## Survey (300 seeded games, `scripts/nfl_sequence/game_survey.py --games 300`, at `2248f7e1`)

```
games=300 validated=300 valid_full_game=0
status {'blocked': 298, 'complete_regulation': 2}
blocker {'field_goal_result_unpublished': 296, 'restart_crosses_quarter_end': 2, None: 2}
reached the Q3 half-start kickoff: 17 (5.7%)
games with a pending try: 131
drives per game: mean 4.3, max 25
kickoff pool: usable 10037, excluded {'kickoff without a clean receiving snap': 962}
```

The numbers did not move in the rebase. The RNG seed of each drive is unchanged, and the only E1 change was the play-ID
string, which E2 does not record. Every game passed `validate_game`. The two games that reached regulation were not valid,
because a try was pending or the game was tied.

## Tests

- `python3 -m unittest scripts/nfl_sequence/test_game_state.py`: **13 of 13 pass**. They cover the ledger (refusals, both
  coin-toss paths, the second-half chooser), the half-start validator (same-team refusal, ledger agreement), the kickoff pool
  convention (receiving-team posteam, and exclusion of a kicker's next snap), the post-score kickoff by the scorer, a
  field-goal attempt stopping the game with no invented result, halftime producing the Q3 kickoff, and the E2 profile id
  passed to E1 on every drive. The profile-id test fails when the call is changed to a wrong id (checked by mutation).
- `python3 -m unittest scripts/nfl_sequence/test_e1_transitions.py` (inherited from E1): **11 of 11 pass**. It had 10 at
  `e621e83e`; the E1 branch added one.
- Both files together: 24 tests OK.

## Kick outcomes in the dev database: the "not published" claim was false

The earlier text said the dev database has no field-goal or try results. That was checked against column names only.
The ingest for `nfl_pbp` (`backend/ingest_nfl_pbp_logs.py` on dev) keeps nflverse's `series_result` and `success` columns.
It does not keep nflverse's dedicated `field_goal_result`, `extra_point_result`, `two_point_conv_result` or `kick_distance`
columns, which is why the name check came up empty. The outcomes are in the kept columns:

- **Field goal:** `series_result` = `Field goal` (made) or `Missed field goal` (missed), on `play_type = 'field_goal'`.
- **Extra point:** `success` = 1 (good) or 0 (missed), on `play_type = 'extra_point'` with `series_result` in
  (`Touchdown`, `Opp touchdown`).
- **Two-point try:** `success` = 1 (converted) or 0 (not), on `two_point_attempt = 1`.

So the engine's gap text was wrong. The gap text in each record is corrected in this pass. The engine's blocking behaviour
is unchanged (see "Decision needed").

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

## Proposed table for E2, if the published outcomes are consumed

| attempt | rate (primary window) | interval | record fields |
| --- | --- | --- | --- |
| field goal, by `yardline_100` | see the bucket table above | Wilson 95% | `source: nfl_pbp (nflverse)`, `window: 2022-2025 wk<=18` |
| extra point | 95.4% (4644 / 4870) | 94.7–95.9% | as above |
| two-point try | 47.2% (240 / 509) | 42.9–51.5% | as above, and a note that it is checked against EPA only |

These are league-wide rates for attempts at a field position, not a model of any kicker.

## Decision needed (Micah)

The outcomes are published, so the question is no longer whether a source exists. It is whether E2 should consume the
`nfl_pbp` outcomes:

1. **Consume the published outcomes.** This is the recommendation, since the source is on the box and the table above is
   measured. Each attempt draws its result from the bucket rate, and every record names the window and the query. This is an
   engine change, and it is not part of this pass.
2. Keep the blocker until a policy is chosen.
3. A labelled authored default. This is allowed only for a clearly hypothetical game, and every record must say so.

Also for Micah: whether the 8 `Opp touchdown` field-goal rows count as misses (85.2% becomes 85.1%), and whether the 2-pt
rate should be trusted before a score-based check exists.

## Not done

- **Field-goal and try results are not consumed by the engine.** The blocker stays until the decision above is made.
- **Onside kicks, overtime, penalties, timeouts, the two-minute warning, and the exception coin-toss paths.** Not modelled.
- **Player statistics.** Null. No participants are supplied, and none are sampled.
- **Clock realism.** Kickoff and drive times are the sampled intervals (boundary 2 from E1).
- **Restarts that cross a quarter end.** These block the game. They are not resolved.
