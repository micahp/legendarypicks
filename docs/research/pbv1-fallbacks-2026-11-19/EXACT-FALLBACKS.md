# PBV1 fallbacks: exact value for each fallback

Run: IND at HOU, PBV1 package with participation field and week-9 snap counts, seeds 300001 to 300100 (100 games). Source: `fallback_events` in the batch output. Label-value counts come from the logging change in `slc_playcall.py` (`labels_unmatched` now records `CATEGORY=VALUE`).

Each label fallback means: the cell's past plays have no row with the drawn value for that category. The engine keeps the rows it had and skips that filter. The play still runs.

## 0. What each label category means

Each category is one fact about the play. The source is the play's charting or play-by-play data. The model draws a value for each category, then looks for past plays with the same value.

| Category | What it measures | Values | Source | Type |
|---|---|---|---|---|
| A | Who got the ball on a pass (receiver role) | RB, WR, TE, Other | play data | pass |
| B | Who got the ball on a non-pass (runner role) | RB, QB, WR_TE, Other | play data | run |
| C | Which gap the run went through | guard, tackle, end | play data | run |
| D | How far the pass was thrown | short, deep | play data | pass |
| E | Which side the pass went to | left, middle, right | play data | pass |
| F | Shotgun formation | yes, no | play data | pre-snap |
| G | Play action fake | yes, no | play data | pass |
| H | Pre-snap motion | yes, no | FTN charting | pre-snap |
| I | Blitz (at least one blitzer) | yes, no | play data | pass |
| J | Where the QB lined up | S, U, P | FTN charting | pre-snap alignment |
| K | Which hash the ball was placed on | L, M, R (left, middle, right) | FTN charting | pre-snap alignment |
| L | Players in the backfield on offense | 0, 1, 2, 3+ | FTN charting | pre-snap alignment |
| M | Defenders in the box | <=5, 6, 7, 8+ | FTN charting | pre-snap alignment |
| N | Pass rushers on a pass play | 3-4, 5+ | play data | pass |

Notes:

- The code writes J, K, L, and M from the FTN charting columns `qb_location`, `starting_hash`, `n_offense_backfield`, and `n_defense_box` (`backend/load_nfl_history.py`, `scripts/nfl_sequence/decision_layer.py` lines 102 to 113).
- J's codes S, U, and P are the FTN values. The repo has no code dictionary for them. Counts in the local parity database's FTN table: S 94,451, U 44,101, P 7,681, 0 34,111 (never used), blank 4,870. S is the most common, which fits shotgun. U fits under center and P fits pistol. This is an inference from counts, not from the FTN dictionary.
- Categories F to M are "pre-snap alignment" in the code (`ALIGN_CATS`). They are drawn on either a pass or a run.

## 1. Label fallbacks (36,596 events, 39 exact values)

| Category | Label values (events) | Category total |
|---|---|---|
| A (ball carrier or receiver) | WR 288, TE 281, RB 204 (Other 0 logged) | 773 |
| B (QB or runner) | QB 37, RB 5, Other 3, WR_TE 34 | 79 |
| C (blocker) | guard 179, tackle 158, end 156 | 493 |
| D (depth) | deep 505, short 325 | 830 |
| E (side) | left 674, right 597, middle 489 | 1,760 |
| F (flag) | no 3,325, yes 875 | 4,200 |
| G (flag) | yes 855, no 388 | 1,243 |
| H (flag) | yes 1,460, no 1,044 | 2,504 |
| I (flag) | yes 1,392, no 928 | 2,320 |
| J (S/U/P) | U 3,602, S 1,320, P 267 | 5,189 |
| K (L/M/R) | R 1,962, L 1,823, M 874 | 4,659 |
| L (count 0 to 3+) | 2 1,548, 1 1,249, 0 624, 3+ 168 | 3,589 |
| M (count buckets) | 6 2,375, 7 2,027, <=5 1,097, 8+ 605 | 6,104 |
| N (3-4 or 5+) | 5+ 1,691, 3-4 1,162 | 2,853 |

Value counts above are from the 100-game run. The category totals match the 2,000-game totals in `REPORT.md` in shape, not in size.

## 2. Non-label fallbacks (4,957 events)

| Fallback | Events | What it means in the code |
|---|---|---|
| no_source_rows_at_exact_yardline | 1,824 | No past play at this exact yardline. Model uses the yard-line group. (`slc_playcall.py` line 763) |
| kick decision: historical share of this situation cell (not yet modelled) | 1,103 | A kick was drawn from the cell's historical kick share. The share is not modelled, so the kick uses the cell count. (`slc_playcall.py` line 488) |
| no_target_identity_match_in_event_cell | 576 | The QB target role found no past target with this player's identity in the event cell. (`slc_playcall.py` line 754) |
| player_outcome_no_history_receiver | 525 | No past receiving outcome for this player. (`slc_engine.py` line 960) |
| no_source_rows_for_current_streak | 334 | No past rows for the current streak bucket. Streak filter skipped. (`slc_playcall.py` line 730) |
| player_outcome_no_history_rusher | 301 | No past rushing outcome for this player. (`slc_engine.py` line 960) |
| no_source_rows_for_chosen_coverage | 128 | No past rows for the chosen coverage. Coverage filter skipped. (`slc_playcall.py` line 724) |
| down_field | 95 | Scramble support fell back to the (down, field) level. Exact cell had fewer than 10 scrambles; this level needs 25. (`qb_decisions.py` line 23 and 390) |
| player_outcome_no_history_passer | 15 | No past passing outcome for this player. (`slc_engine.py` line 960) |
| down_distance | 13 | Scramble support fell back to the (down, distance) level. Needs 25 scrambles. (`qb_decisions.py` line 391) |
| no_source_rows_for_chosen_formation | 13 | No past rows for the chosen formation. Formation filter skipped. (`slc_playcall.py` line 718) |
| field_zone | 8 | Scramble support fell back to the field-zone level. Needs 50 scrambles. (`qb_decisions.py`) |
| no_prior_cell_event:<side>:<team>:<event> | 22 | No prior-season event of this type for this team in this cell (fumble_lost, interception, sack). (`slc_playcall.py` line 1038) |

## Reading

- Label fallbacks are 88% of all fallback events in this run.
- Flag labels (F to I) and count labels (J to N) are the largest groups.
- Player and target history misses are small. They are about 1,400 events in 100 games.

## 3. Why each label fallback happened (100 games, 36,596 events)

Each label fallback is one of three cases:

- **absent_from_cell:** no row in the cell's original candidates has the drawn value. Missing observations.
- **removed_by_non_label_filter:** the value was in the cell, but formation, coverage, streak, or scramble filters removed it.
- **removed_by_earlier_label:** the value was in the cell, but an earlier label filter in category order removed it.

| Reason | Events | Share |
|---|---|---|
| removed_by_earlier_label | 22,271 | 60.9% |
| removed_by_non_label_filter | 13,566 | 37.1% |
| absent_from_cell | 759 | 2.1% |

By category (absent / non-label filter / earlier label):

| Category | absent | non-label | earlier label |
|---|---|---|---|
| A | 194 | 579 | 0 |
| B | 4 | 75 | 0 |
| C | 12 | 133 | 348 |
| D | 206 | 278 | 346 |
| E | 191 | 632 | 937 |
| F | 25 | 2,974 | 1,201 |
| G | 3 | 404 | 836 |
| H | 5 | 449 | 2,050 |
| I | 2 | 503 | 1,815 |
| J | 32 | 4,472 | 685 |
| K | 8 | 697 | 3,954 |
| L | 47 | 811 | 2,731 |
| M | 26 | 988 | 5,090 |
| N | 4 | 571 | 2,278 |

Reading: the main problem is over-conditioning, not missing data. Earlier label filters remove most values that exist in the cell. Non-label filters (mostly J and F, the alignment and shotgun filters) remove another large share.
