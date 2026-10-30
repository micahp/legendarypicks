# CAR at GB 10k run: interrupted run error record

The single-process run used `v1_full_stack` for seeds 1–10,000 on the fast host at source commit `6f8fbbc4`. Input preflight passed: the database opened read-only, all five decision Parquets, 32 manifest-pinned playbooks, and all 16 play-call frame sources were present.

The run was stopped after seed 581 to move to parallel workers. Its append-only ledger is preserved at:

`/root/slc-10k-2026-10-29/artifacts/CAR-GB-v1-full-stack-10k-try3.seeds.jsonl`

No final 10k report was written for this interrupted attempt. The ledger contains seeds 1–581 and is the source for these counts:

| Outcome status | Count |
| --- | ---: |
| `complete_regulation` | 450 |
| `complete_overtime` | 15 |
| `blocked` | 32 |
| `simulation_error` | 84 |

## Simulation errors

All 84 simulation errors had the same cause: `ValueError: receive eligible population changed within <team> game <seed>`. There were 42 CAR errors and 42 GB errors. The listed seed is the game number embedded in each ledger error message.

The Dirichlet receiver-share population was being built from the per-play receiver candidates. On a trick pass by an eligible RB, WR, or TE, that removed passer was also removed from the population used for the game-level share draw. The cached population then changed between plays and correctly raised an error. The population must remain the full eligible roster; only the candidate list for that play excludes its passer.

| Team | Error seeds |
| --- | --- |
| CAR | 8, 38, 40, 45, 58, 63, 64, 84, 91, 102, 114, 135, 144, 147, 149, 152, 159, 162, 195, 204, 226, 227, 237, 263, 265, 267, 323, 368, 374, 404, 419, 436, 441, 451, 464, 478, 483, 491, 535, 538, 546, 547 |
| GB | 4, 12, 14, 17, 53, 60, 65, 95, 116, 127, 151, 154, 156, 180, 217, 230, 251, 253, 257, 269, 273, 279, 289, 296, 299, 311, 313, 337, 342, 346, 367, 396, 426, 431, 444, 445, 459, 462, 490, 518, 523, 553 |

The correction in commit `9edfc7b0` derives the share population from the full eligible roster, checks that invariant at runtime, and adds a regression test that forces multiple non-QB trick passers while checking the team-game population stays fixed. The focused pre-event suite passed on the fast host: 15 tests.

## Blocked outcomes

The 32 `blocked` results are simulator outcomes, not Python exceptions. They remain separate from `simulation_error`:

| Blocker family | Count |
| --- | ---: |
| `qb_scramble_source_rows_missing` | 10 |
| `non_scramble_run_source_rows_missing` | 8 |
| `blocked_kick_outcome_unresolved` | 7 |
| `blocked_kick_receiving_return_outside_field` | 2 |
| `thin_kick_cell` | 2 |
| `blocked_kick_kicking_recovery_outside_field` | 1 |
| `playcall_no_run_outcomes_in_cell` | 1 |
| `safety_free_kick_not_modelled` | 1 |

