# 2022 Big Data Bowl clock decomposition audit, weeks 1–5 (2026-10-24)

Superseded for the full window by `BDB2022-CLOCK-AUDIT-WEEKS1-9-2026-10-24.md`, which reproduces these weeks 1–5 figures unchanged. The sentence about weeks 6–9 below is no longer current.

Scope: the matched plays of weeks 1–5 (9,225 of the 16,124 tracked plays, from `bdb2022-join-pairs-2026-10-24.csv`). Weeks 6–9 are reserved for scoring and are not read. Overtime is not read. The script is `scripts/bdb/bdb2022_clock_audit.py`; the per-play table is `bdb2022-clock-audit-weeks1-5-2026-10-24.csv`; the summary is the matching `.json`.

## Quantities and labels

| quantity | definition | label | source | resolved |
| --- | --- | --- | --- | ---: |
| snap time | first `ball_snap` frame of the play | observed | tracking event rows | 9208 |
| terminal event | earliest of tackle, out of bounds, touchdown, sack, slide, kneel, spike, incomplete, interception, touchback, fumble recovery | observed | tracking event rows | 9202 (duration) |
| in-play duration | terminal time minus snap time | inferred (difference of two observed times) | tracking | 9202 |
| runoff | `game_seconds_remaining` at this play minus at the next play in the same quarter | inferred (difference of two observed clock stamps) | LP nfl_pbp | 9210 |
| residual | runoff minus in-play duration: clock time with no play in progress | inferred | tracking and LP | 9187 |
| quarter, down, distance, possession | BDB and LP agree on every matched play | observed | BDB plays, LP | 9225 |
| score differential | pre-snap score, offense minus defense | observed | BDB plays | 9225 |
| outcome type | run, complete, incomplete, sack, interception, fumble, touchdown | observed | LP nfl_pbp | 9225 |
| out of bounds, timeout called | flags on the play | observed | LP play flags (play_extras) | 920 OOB, 20 timeout |
| penalty on the play | LP penalty flag | observed | LP nfl_pbp | 134 |
| timeouts remaining | per-play counts | **unresolvable** (neither source carries per-play counts) | — | 0 |
| penalty clock stops | stoppage from a penalty | **unresolvable** (BDB marks every play not nullified; LP flag only) | — | 0 |

## Unresolved plays

| reason | plays |
| --- | ---: |
| no ball_snap for the play | 17 |
| negative runoff (unresolvable) | 9 |
| no next snap in the quarter (unresolvable runoff) | 6 |
| no terminal event for the play | 6 |

## In-play duration, runoff and residual by outcome (seconds)

| outcome | in-play n | median | p10 | p90 | runoff n | median | p10 | p90 | residual n | median | p10 | p90 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fumble | 63 | 5.1 | 2.7 | 8.4 | 63 | 9.0 | 5.0 | 12.0 | 63 | 3.1 | 1.0 | 5.8 |
| interception | 105 | 4.6 | 3.6 | 7.1 | 104 | 7.5 | 5.0 | 11.0 | 104 | 2.4 | 0.0 | 6.9 |
| other | 116 | 0.7 | 0.5 | 1.1 | 115 | 19.0 | 0.0 | 39.0 | 115 | 18.5 | -0.4 | 38.4 |
| pass_complete | 2996 | 5.4 | 4.0 | 7.5 | 2994 | 36.0 | 10.0 | 45.0 | 2993 | 30.9 | 3.5 | 38.9 |
| pass_incomplete | 1692 | 4.4 | 3.1 | 6.4 | 1690 | 5.0 | 3.0 | 7.0 | 1689 | 0.3 | -0.7 | 1.2 |
| run | 3579 | 4.4 | 3.3 | 6.3 | 3591 | 38.0 | 18.0 | 45.0 | 3574 | 33.3 | 13.6 | 39.9 |
| sack | 308 | 4.3 | 3.2 | 6.5 | 307 | 40.0 | 8.0 | 46.0 | 307 | 35.5 | 3.7 | 41.3 |
| touchdown | 343 | 4.4 | 2.9 | 7.6 | 346 | 5.0 | 3.0 | 9.0 | 342 | 0.6 | -0.8 | 2.1 |

## Residual by observed clock-stop flags

| class | n | median residual | p10 | p90 |
| --- | ---: | ---: | ---: | ---: |
| no observed stop | 6231 | 32.9 | 5.0 | 39.8 |
| incomplete pass or touchdown | 2022 | 0.3 | -0.7 | 1.3 |
| out of bounds or timeout (see the two-minute split) | 934 | 26.9 | 0.1 | 34.8 |

Out-of-bounds plays, split by the time remaining in the quarter (LP game clock):

| out-of-bounds plays | n | median residual | p10 | p90 |
| --- | ---: | ---: | ---: | ---: |
| last two minutes of the second or fourth quarter | 117 | 0.1 | -4.9 | 1.0 |
| otherwise | 802 | 28.4 | 8.3 | 35.3 |

The clock stops on out-of-bounds plays only late in a half (median residual 0.1 s), and runs otherwise (28.4 s). This is observed in the data. It is consistent with the two-minute rule, which the rules matrix lists as unmodelled; the rule text is not checked here.

## What the decomposition says

- In-play time is short: a play lasts about 4–5 s from snap to terminal event (median 4.4 s for runs, 5.4 s for completions).
- The game clock runs for much longer on running plays. Between the terminal event and the next snap, a running play leaves a median residual of about 33 s, and a completed pass about 31 s. That between-play time is clock that runs with no play in progress.
- Plays that stop the clock leave almost no residual: incomplete passes and touchdowns (median 0.3 s).
- Out-of-bounds plays are the exception that needs the two-minute split above. Outside the last two minutes they carry the running-clock residual.

## Implications for the three clock models (not evaluated here)

The E2 engine samples a runoff per play from observed plays (the current model). It is a game-clock difference, so it already contains the between-play residual. The decomposition therefore says which quantity each model must predict: the in-play part (short and tight) and the residual (large and state-dependent: running or stopped, and the two-minute rule). A PBP-only conditional model can predict the runoff directly, conditioned on outcome and stop context. A tracking-informed model can predict only the in-play part from the frames, and must add a residual model. Scoring the models is reserved for weeks 6–9 and has not been done.

## Limitations

- The terminal event is the first play-ending label after the snap. Plays whose ending label is missing or precedes the snap are counted above, not guessed.
- BDB plays are runs and passes only, and have no punts or field goals (see the join coverage report).
- Timeouts remaining and penalty stoppages are unresolvable for the matched plays.
- The two-minute finding is observed from the data. The rule itself is not checked against the rulebook text.

