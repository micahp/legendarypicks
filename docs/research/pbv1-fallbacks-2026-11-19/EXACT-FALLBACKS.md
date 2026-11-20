# PBV1 fallbacks: exact value for each fallback

Run: IND at HOU, PBV1 package with participation field and week-9 snap counts, seeds 300001 to 300100 (100 games). Source: `fallback_events` in the batch output. Label-value counts come from the logging change in `slc_playcall.py` (`labels_unmatched` now records `CATEGORY=VALUE`).

Each label fallback means: the cell's past plays have no row with the drawn value for that category. The engine keeps the rows it had and skips that filter. The play still runs.

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
