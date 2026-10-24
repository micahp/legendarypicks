# 2022 Big Data Bowl clock decomposition audit, weeks 1–9 (2026-10-24)

Scope: the matched plays of weeks 1–9 (15,765 of the 16,124 tracked plays, from `bdb2022-join-pairs-2026-10-24.csv`). The 359 unmatched plays are 222 with no resolved spot (side `NA`), 3 ambiguous, and 134 in overtime, which the join does not check. Overtime is not read here (the audit's plays are quarters 1–4 only). The script is `scripts/bdb/bdb2022_clock_audit.py`; the per-play table is `bdb2022-clock-audit-weeks1-9-2026-10-24.csv`; the summary is the matching `.json`. The weeks 1–5 report (`BDB2022-CLOCK-AUDIT-WEEKS1-5-2026-10-24.md`) uses the same definitions; its figures are reproduced here unchanged.

The focus section (the 2026 weekend's matchups that appear in the 2022 weeks 1–9 games) is at the end.

## Quantities and labels

| quantity | definition | label | source | resolved |
| --- | --- | --- | --- | ---: |
| snap time | first `ball_snap` frame of the play | observed | tracking event rows | 15,703 |
| terminal event | earliest of tackle, out of bounds, touchdown, sack, slide, kneel, spike, incomplete, interception, touchback, fumble recovery | observed | tracking event rows | 15,641 (with a snap) |
| in-play duration | terminal time minus snap time | inferred (difference of two observed times) | tracking | 15,641 |
| runoff | `game_seconds_remaining` at this play minus at the next play in the same quarter | inferred (difference of two observed clock stamps) | LP nfl_pbp | 15,748 |
| residual | runoff minus in-play duration: clock time with no play in progress | inferred | tracking and LP | 15,624 |
| quarter clock | game seconds remaining minus the seconds in later quarters | inferred | LP nfl_pbp | 15,765 |
| quarter, down, distance, possession | BDB and LP agree on every matched play | observed | BDB plays, LP | 15,765 |
| score differential | pre-snap score, offense minus defense | observed | BDB plays | 15,765 |
| outcome type | run, complete, incomplete, sack, interception, fumble, touchdown | observed | LP nfl_pbp | 15,765 |
| out of bounds, timeout called | flags on the play | observed | LP play flags (play_extras) | 1,656 OOB, 37 timeout |
| penalty on the play | LP penalty flag | observed | LP nfl_pbp | 211 |
| timeouts remaining | per-play counts | **unresolvable** (neither source carries per-play counts) | — | 0 |
| penalty clock stops | stoppage from a penalty | **unresolvable** (BDB marks every play not nullified; LP flag only) | — | 0 |

## Unresolved plays

| reason | plays |
| --- | ---: |
| no ball_snap for the play | 62 |
| no terminal event for the play (snap present) | 62 |
| negative runoff (unresolvable) | 11 |
| no next snap in the quarter (unresolvable runoff) | 6 |

Residual is unresolved on 141 plays (62 + 62 + 11 + 6; the four sets do not overlap).

## Weeks 1–9 against weeks 1–5

| | weeks 1–5 | weeks 1–9 |
| --- | ---: | ---: |
| matched plays | 9,225 | 15,765 |
| out-of-bounds flags | 920 | 1,656 |
| timeout flags | 20 | 37 |
| penalty flags | 134 | 211 |

The median residuals for the two main classes barely move when the window grows: runs 33.3 s (weeks 1–5) and 33.5 s (weeks 1–9); completions 30.9 s and 30.6 s.

## In-play duration, runoff and residual by outcome (seconds)

| outcome | in-play n | median | p10 | p90 | runoff n | median | p10 | p90 | residual n | median | p10 | p90 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fumble | 100 | 4.95 | 2.7 | 8.4 | 100 | 8.0 | 4.0 | 12.0 | 100 | 3.1 | -0.2 | 5.9 |
| interception | 168 | 4.7 | 3.7 | 7.0 | 167 | 8.0 | 5.0 | 12.0 | 167 | 2.7 | 0.0 | 7.1 |
| other | 180 | 0.7 | 0.5 | 1.2 | 179 | 22.0 | 1.0 | 41.0 | 179 | 21.5 | -0.1 | 40.3 |
| pass_complete | 5,109 | 5.4 | 4.0 | 7.5 | 5,111 | 36.0 | 9.0 | 45.0 | 5,104 | 30.6 | 2.4 | 38.9 |
| pass_incomplete | 2,781 | 4.4 | 3.1 | 6.5 | 2,829 | 5.0 | 3.0 | 7.0 | 2,778 | 0.2 | -0.8 | 1.2 |
| run | 6,157 | 4.4 | 3.3 | 6.3 | 6,209 | 38.0 | 18.0 | 45.0 | 6,152 | 33.45 | 13.3 | 39.9 |
| sack | 544 | 4.3 | 3.2 | 6.3 | 546 | 40.0 | 8.0 | 46.0 | 543 | 34.9 | 3.1 | 41.0 |
| touchdown | 602 | 4.5 | 2.8 | 7.8 | 607 | 5.0 | 3.0 | 9.0 | 601 | 0.6 | -0.7 | 2.0 |

## Residual by observed clock-stop class

The three classes are exclusive. An incomplete pass or touchdown is taken first; then any play with an out-of-bounds or timeout flag; the rest have no observed stop.

| class | in-play n | in-play median | residual n | median | p10 | p90 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| no observed stop | 10,589 | 4.6 | 10,576 | 32.9 | 5.0 | 39.9 |
| incomplete pass or touchdown | 3,383 | 4.4 | 3,379 | 0.3 | -0.8 | 1.3 |
| out of bounds or timeout | 1,669 | 5.6 | 1,669 | 27.1 | 0.1 | 34.9 |

The weeks 1–5 report counted these classes with a different precedence, so its class counts differ slightly (for example 934 out-of-bounds-or-timeout plays there, 925 in the weeks 1–5 rerun here). The medians agree to 0.1 s, and the weeks 1–5 rerun reproduces its `by_outcome` and `stats` exactly.

## Out-of-bounds plays, split by the time remaining in the half

"Last two minutes of the half" means the second or fourth quarter, with the quarter clock at 120 s or less, on the LP game clock.

| out-of-bounds plays | n | residual median | p10 | p90 |
| --- | ---: | ---: | ---: | ---: |
| last two minutes of the second or fourth quarter | 216 | 0.1 | -4.9 | 1.0 |
| otherwise | 1,435 | 28.6 | 8.9 | 35.3 |

Under the same definition, weeks 1–5 gives 117 plays at 0.1 s and 802 at 28.4 s, matching the weeks 1–5 report. The stop at the end of a half is therefore not a one-week artefact. It is observed, and it is consistent with the two-minute rule. The rule text itself is not checked here (the rules matrix lists it as unmodelled).

## What the decomposition says

- In-play time is short: 4–5 s from snap to terminal event (median 4.4 s for runs, 5.4 s for completions), unchanged from weeks 1–5.
- Running clock dominates between plays: a running play leaves a median residual of 33.5 s and a completed pass 30.6 s, with no play in progress.
- Plays that stop the clock leave almost none: incomplete passes and touchdowns have a median residual of 0.3 s.
- Out-of-bounds plays stop the clock only late in a half (median 0.1 s), and run otherwise (28.6 s).

## Focus: this weekend's matchups that appear in the dataset

The 2026 fixtures come from `nfl_schedule` in the dev database (read only), for 2026-10-25 and 2026-10-26: 13 games. A matchup counts as appearing in the dataset when the same two clubs, in either home/away order, play in a 2022 game in weeks 1–9. The medians are the clock figures of those 2022 meetings. They are not predictions for the 2026 game.

Six of the 13 games repeat a 2022 pairing. In each of the six, the 2022 meeting has the same home club as the 2026 game.

| 2026 game | 2022 meeting in dataset | matched plays | in-play median | runoff median | residual median | residual n |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| CIN @ BAL (Oct 25) | 2022_05_CIN_BAL (week 5) | 115 | 5.0 | 37.0 | 31.9 | 115 |
| GB @ DET (Oct 25) | 2022_09_GB_DET (week 9) | 117 | 4.4 | 34.0 | 28.6 | 115 |
| MIA @ NYJ (Oct 25) | 2022_05_MIA_NYJ (week 5) | 108 | 4.9 | 37.0 | 31.9 | 107 |
| SF @ ATL (Oct 25) | 2022_06_SF_ATL (week 6) | 107 | 4.6 | 37.0 | 31.9 | 107 |
| TB @ CAR (Oct 25) | 2022_07_TB_CAR (week 7) | 108 | 4.8 | 33.5 | 28.05 | 108 |
| DAL @ PHI (Oct 26) | 2022_06_DAL_PHI (week 6) | 128 | 4.5 | 30.0 | 26.3 | 128 |

The other seven 2026 games have no 2022 weeks 1–9 meeting: CLE @ TEN, DEN @ ARI, IND @ MIN, KC @ SEA, LAR @ LV, NYG @ HOU, PIT @ NO. These pairs may have met in 2022 weeks 10–18 or in other seasons, which the dataset does not cover.

Checks on the focus section:
- The six pairings and the seven non-pairings were checked against the raw `games.csv` for weeks 1–9, not through the LP join. The results agree.
- Four pairs meet twice in weeks 1–9 (IND–JAX, IND–TEN, LAR–SF, ARI–SEA). None is on this weekend's list. The 136 games cover 132 distinct pairs.
- All 26 clubs playing this weekend appear in the 2022 weeks 1–9 games, so the team-level version of the question has full coverage.

Each focus row rests on one 2022 game (107–128 matched plays). Treat the medians as a description of that game, not as a team estimate.

## Limitations

- This report is the decomposition only. The three-model comparison (current sampled runoff, PBP-only conditional, tracking-informed) is not done here.
- Timeouts remaining and penalty stoppages are unresolvable for the matched plays.
- The two-minute finding is observed in the data. The rule itself is not checked against the rulebook text.
- The terminal event is the first play-ending label after the snap. Plays whose label is missing or precedes the snap are counted above, not guessed.
- BDB plays are runs and passes only, and have no punts or field goals (see the join coverage report).
- The play-flags table (timeout, out of bounds) is read from `/root/lp-nfl-sequence-e2/docs/fixtures/e2/play_extras_2022_2025.csv` in the E2 worktree. Reproducing this audit needs that file at that path.

## Reproduce

```
python3 scripts/bdb/bdb2022_clock_audit.py --events-dir <dir with events_w1..w9.csv> \
    --first-week 1 --last-week 9 --focus-from 2026-10-25 --focus-to 2026-10-26 \
    --out-dir docs/research
```

The `events_wN.csv` files are the tracking event rows (ball_snap and terminal labels) extracted from `tracking_week_N.csv` in `/root/nfl-tracking-data/bdb2025/code-data/`.
