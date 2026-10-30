# SLC 10K Run Results — 2026 Week 8, CAR at GB

## Run outcome

The six-worker batch processed all 10,000 requested seeds for `2026_08_CAR_GB` (Carolina at Green Bay). It completed 9,490 games and explicitly blocked 510 games. The 510 blocked games are incomplete simulations; they were not converted into ordinary outcomes.

| Outcome | Games | Share of requested |
| --- | ---: | ---: |
| Completed in regulation | 9,127 | 91.27% |
| Completed in overtime | 363 | 3.63% |
| **Completed** | **9,490** | **94.90%** |
| Blocked | 510 | 5.10% |
| Guarded | 0 | 0.00% |
| Invalid or simulation/validation error | 0 | 0.00% |

Seven completed games ended tied. Score and winner distributions below use the 9,483 decisive completed games; tied games are excluded from win-probability denominators. All six worker summaries report zero simulation or validation errors and zero guarded games.

## Score distribution

These are prospective simulation outputs, not observed results. The batch did not have an available paired SLC v1 baseline, so the distributions are descriptive and do not establish predictive accuracy or improvement.

| Measure | CAR | GB | Total / margin |
| --- | ---: | ---: | ---: |
| Mean points | 21.81 | 26.78 | 48.59 total; GB +4.97 margin |
| Median | 21 | 27 | 48 total; GB +5 margin |
| 10th–90th percentile | 11–33 | 16–38 | 33–64 total; GB −10 to +20 margin |

Among decisive completed games, GB won 6,301 (66.45%) and CAR won 3,182 (33.55%). Total points by band:

| Total points | Games | Share |
| --- | ---: | ---: |
| 0–29 | 520 | 5.48% |
| 30–39 | 1,656 | 17.46% |
| 40–49 | 2,815 | 29.69% |
| 50–59 | 2,778 | 29.30% |
| 60–69 | 1,278 | 13.48% |
| 70+ | 436 | 4.60% |

## Blocked games

| Blocker family | Games |
| --- | ---: |
| QB scramble source rows missing | 211 |
| Designed-run source rows/outcomes missing | 144 |
| Blocked-kick resolution or field geometry | 106 |
| Thin 50+ yard field-goal cell | 43 |
| Safety free kick not modeled | 6 |
| **Total** | **510** |

The largest single reason was an unsupported QB scramble in the third-down, 7–10-yard, 80–99 yardline cell (140 games). Run and scramble gaps account for 355 of the 510 blockers (69.6%). Blocked-kick cases remain explicit when their source resolution is unresolved or their projected spot is outside the field.

The following table preserves every blocker key and count from the worker summaries.

| Exact blocker key | Games |
| --- | ---: |
| `qb_scramble_source_rows_missing:(3, '7-10', '80-99')` | 140 |
| `qb_scramble_source_rows_missing:(2, '7-10', '50-79')` | 19 |
| `qb_scramble_source_rows_missing:(3, '1-3', '10-19')` | 10 |
| `qb_scramble_source_rows_missing:(2, '1-3', '1-9')` | 7 |
| `qb_scramble_source_rows_missing:(3, '1-3', '1-9')` | 7 |
| `qb_scramble_source_rows_missing:(2, '7-10', '20-49')` | 6 |
| `qb_scramble_source_rows_missing:(4, '1-3', '50-79')` | 5 |
| `qb_scramble_source_rows_missing:(3, '1-3', '20-49')` | 4 |
| `qb_scramble_source_rows_missing:(4, '11+', '50-79')` | 4 |
| `qb_scramble_source_rows_missing:(2, '7-10', '10-19')` | 3 |
| `qb_scramble_source_rows_missing:(2, '1-3', '50-79')` | 2 |
| `qb_scramble_source_rows_missing:(1, '1-3', '1-9')` | 1 |
| `qb_scramble_source_rows_missing:(2, '11+', '10-19')` | 1 |
| `qb_scramble_source_rows_missing:(2, '4-6', '10-19')` | 1 |
| `qb_scramble_source_rows_missing:(4, '1-3', '1-9')` | 1 |
| `non_scramble_run_source_rows_missing:(3, '4-6', '10-19')` | 2 |
| `non_scramble_run_source_rows_missing:(3, '4-6', '80-99')` | 30 |
| `non_scramble_run_source_rows_missing:(4, '11+', '10-19')` | 13 |
| `non_scramble_run_source_rows_missing:(4, '4-6', '10-19')` | 32 |
| `non_scramble_run_source_rows_missing:(4, '4-6', '20-49')` | 32 |
| `playcall_no_run_outcomes_in_cell:(4, '4-6', '80-99')` | 12 |
| `playcall_no_run_outcomes_in_cell:(4, '7-10', '1-9')` | 13 |
| `playcall_no_run_outcomes_in_cell:(4, '7-10', '80-99')` | 10 |
| `thin_kick_cell:field_goal:50+` | 43 |
| `blocked_kick_outcome_unresolved:field_goal:guarded_penalty_fumble_or_review` | 47 |
| `blocked_kick_outcome_unresolved:punt:guarded_penalty_fumble_or_review` | 24 |
| `blocked_kick_receiving_return_outside_field` | 18 |
| `blocked_kick_kicking_recovery_outside_field` | 12 |
| `blocked_kick_kicking_return_outside_field` | 3 |
| `blocked_kick_dead_ball_outside_field` | 2 |
| `safety_free_kick_not_modelled` | 6 |

## Playcalling and layer execution

Sixteen of the 17 configured playcalling layers were enabled. Every enabled layer reported `executed`; the run reported no missing layer inputs. `fixed_player_target_carry_shares` was disabled.

| Enabled layer | Runtime applications across workers |
| --- | ---: |
| `current_streak_context` | 1,433,290 |
| `decision_labels` | 1,291,868 |
| `decision_row_filter` | 1,291,868 |
| `defensive_coverage_outcomes` | 713,915 |
| `dirichlet_player_target_carry_shares` | 1,328,306 |
| `exact_yardline_outcomes` | 77,925 |
| `formation_personnel_outcomes` | 1,328,306 |
| `league_streak_splits` | 1,433,290 |
| `playbook_priors` | 1,328,291 |
| `player_conditioned_outcomes` | 1,433,290 |
| `point_splits` | 1,433,290 |
| `qb_decisions` | 748,999 |
| `score_clock_playcalling` | 1,433,290 |
| `target_role_priors` | 750,353 |
| `team_offense_defense_outcomes` | 1,433,290 |
| `team_streak_splits` | 1,433,290 |

Across completed games, the playcall counters averaged 147.07 decisions, 136.31 scrimmage decisions, 59.29 runs, 77.02 dropbacks, 3.74 QB scrambles, and 10.76 kick-decision fallbacks per game. These are simulator counters, not independently reconciled official play totals.

Fallback telemetry records 3,833,869 events across the batch; events can occur multiple times in a game. The most frequent labels were `decision_row_missing_category_M` (595,462), `decision_row_missing_category_J` (562,055), `decision_row_missing_category_K` (417,500), `decision_row_missing_category_F` (385,892), `decision_row_missing_category_L` (342,966), and `decision_row_missing_category_N` (265,496). The category letters are emitted as-is by the artifact schema; this report does not assign them an interpretation. Full fallback counts are in each worker JSON.

## Player projections

The worker outputs contain per-game mean projections, combined with weights equal to each worker's completed-game count (9,490 games). Values below are simulated averages, not observed player results or per-game distributions. `boxscore_export` was disabled, so the run did not produce a separate per-game player boxscore file.

| Player | Team | Pass att | Comp | Pass yds | Pass TD | Rush att | Rush yds | Rush TD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Jordan Love | GB | 35.46 | 24.08 | 265.56 | 1.64 | 4.60 | 27.08 | 0.26 |
| Bryce Young | CAR | 36.21 | 22.43 | 233.73 | 1.19 | 4.43 | 31.05 | 0.30 |

| Receiver | Team | Targets | Receptions | Rec yds | Rec TD |
| --- | --- | ---: | ---: | ---: | ---: |
| Tetairoa McMillan | CAR | 10.50 | 6.11 | 69.50 | 0.34 |
| Christian Watson | GB | 7.85 | 5.01 | 61.07 | 0.38 |
| Matthew Golden | GB | 6.35 | 4.24 | 51.18 | 0.33 |
| Xavier Legette | CAR | 5.49 | 3.14 | 35.62 | 0.18 |

| Runner | Team | Rush att | Rush yds | Rush TD |
| --- | --- | ---: | ---: | ---: |
| Josh Jacobs | GB | 22.36 | 90.10 | 0.95 |
| Chuba Hubbard | CAR | 19.19 | 79.94 | 0.64 |

## Provenance and limitations

- Model: `slc_v1_qb_decisions_player_outcomes_research`; evaluation class: prospective forecast; context mode: unconditioned.
- Historical source cutoff: eligible before 2026-01; the playcall artifact lists fit seasons 2010–2025.
- Six contiguous worker seed ranges cover seeds 1–10,000. The 10,000 seed-ledger entries match the 10,000 game records, with no duplicate or missing seeds.
- All workers used configuration hash `977308c7ad60eddd4368c3e62d166f95a5080db22b12efa062c8ccec46b58dad` and game ID `2026_08_CAR_GB`.
- The comparison output says `baseline_status: unavailable`; there is no paired same-seed v1 comparison in this artifact set.
- The raw per-worker JSON, seed ledgers, and logs are stored in [`outputs/parallel-6`](outputs/parallel-6/).

The run completed successfully as a batch process, but 5.1% of requested games remain blocked by unsupported transitions. Fewer blockers alone would not establish improved realism; that requires a paired baseline and evaluation of score, drive, play, and player distributions.
