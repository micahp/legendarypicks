# E2 successor: 300-seed survey on the current research source (2026-10-24)

Engine base commit: `dfef3e8e40ab9702c1f021ff726e3959d6f9d63b`. Exact source-tree SHA-256: `79a65db640e587798f2a067853a3ba8f723aadfbb10e3021cddb3c92ec08c117`. Producer files: dirty research snapshot.
Command: `survey_legality_300.py`. Seeds 1-300, regulation-only pool.
Each record passes `validate_game`, is checked by the independent checker (no engine imports) and by `rules_matrix`.
`legal_complete_game` is a candidate under this engine’s modeled rules. It does not mean shared-v1 `valid_full_game`.

## Counts

| measure | count |
|---|---:|
| seeds | 300 |
| validate_game passed | 300 |
| reached regulation end under the simulation (`regulation_end_reached`) | 288 |
| regulation end, guarded by an unmodelled transition (`regulation_end_guarded`) | 288 |
| complete regulation game (`complete_regulation`, unguarded) | 0 |
| complete model-scoped regulation (`complete_game`) | 0 |
| independent model-scoped candidate (`legal_complete_game`) | 0 |
| shared-v1 `valid_full_game=true` | 0 |
| legal under the modelled rules (checker) | 300 |
| blocked | 12 |
| blocked described as complete | 0 |
| guarded described as complete | 0 |
| matrix FAIL rows | 0 |
| try findings | 0 |
| matches the frozen survey on status, blocker, regulation end and matrix (frozen a442dcd7, unmodified) | 281 of 300 |

## Why `valid_full_game` remains false

These records use `mode=legal_game_state_first_piece` and retrospective sampled plays. They do not identify a scheduled upcoming game, a pregame as-of time and kickoff, or an eligible roster snapshot; the shared-v1 audit has nine unresolved contract residuals on the seed-1 record. The engine also keeps unsupported rule families explicit. Reaching regulation end and passing the independent modeled-rule checks is not enough to set the full-game contract flag.

Two-minute warning crossings are marked and independently checked at the actual post-down clock; the play is not rewound to 2:00. The required running/stopped clock state and explicit restart transitions remain unsupported under `clock_start_stop`, so this marker does not establish full clock-rule coverage.

The all-quarter counterfactual classified {'not_explained_by_pool_alone': 13, 'regulation_only_pool': 6} across the 19 changed seeds. Detail: {'regulation_only_pool_changes_frozen_outcome': 6, 'status_or_blocker_differs_with_all_quarter_pool': 2, 'two_minute_guard_keeps_complete_game_false': 11}. In 11 cases the all-quarter run matches the frozen status, blocker and regulation-end outcome, but the current two-minute-warning guard correctly keeps `complete_game=false`; in 2 cases the status or blocker still differs with the all-quarter pool. See `MISMATCH-300-SUCCESSOR-2026-10-24.md` for the per-seed controlled comparison.

## Blocked seeds, with their reason

| seed | blocker | scope reason |
|---:|---|---|
| 36 | `overtime_not_modelled` | overtime;unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning |
| 55 | `overtime_not_modelled` | overtime;unmodelled transition: two_minute_warning |
| 114 | `overtime_not_modelled` | overtime;unmodelled transition: timeout;unmodelled transition: two_minute_warning |
| 163 | `overtime_not_modelled` | overtime;unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning |
| 175 | `overtime_not_modelled` | overtime;unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning |
| 185 | `overtime_not_modelled` | overtime;unmodelled transition: timeout;unmodelled transition: two_minute_warning |
| 194 | `thin_kick_cell:field_goal:50+` | rare kick outcome;unmodelled transition: timeout;unmodelled transition: two_minute_warning |
| 246 | `overtime_not_modelled` | overtime;unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning |
| 276 | `overtime_not_modelled` | overtime;unmodelled transition: timeout;unmodelled transition: two_minute_warning |
| 279 | `overtime_not_modelled` | overtime;unmodelled transition: timeout;unmodelled transition: two_minute_warning |
| 280 | `overtime_not_modelled` | overtime;unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning |
| 290 | `overtime_not_modelled` | overtime;unmodelled transition: two_minute_warning |

Blocker counts: {'overtime_not_modelled': 11, 'thin_kick_cell:field_goal:50+': 1}.

## Per seed

| seed | status | blocker | regulation end | complete_game | valid_full_game | unmodelled | scope | FAIL rows | vs frozen |
|---:|---|---|:-:|:-:|:-:|---:|---|---:|---|
| 1 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 2 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 3 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 4 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 5 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 6 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 7 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 8 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 9 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | differs |
| 10 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 11 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 12 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 13 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 14 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 15 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 16 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 17 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 18 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 19 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 20 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 21 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 22 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 23 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 24 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 25 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 26 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 27 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 28 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 29 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 30 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 31 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 32 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 33 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 34 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 35 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 36 | blocked | overtime_not_modelled | False | False | False | 3 | overtime;unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | differs |
| 37 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 38 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 39 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 40 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 41 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 42 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 43 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 44 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 45 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 46 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 47 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 48 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | differs |
| 49 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 50 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 51 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 52 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 53 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 54 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 55 | blocked | overtime_not_modelled | False | False | False | 2 | overtime;unmodelled transition: two_minute_warning | 0 | differs |
| 56 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 57 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 58 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 59 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 60 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 61 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 62 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 63 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 64 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 65 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 66 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 67 | regulation_end_guarded | - | True | False | False | 6 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 68 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 69 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 70 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 71 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 72 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 73 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 74 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 75 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 76 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 77 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 78 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | differs |
| 79 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 80 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 81 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 82 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 83 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 84 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 85 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 86 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 87 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | differs |
| 88 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 89 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 90 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 91 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 92 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 93 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 94 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 95 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 96 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 97 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 98 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 99 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 100 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 101 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 102 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 103 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 104 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 105 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 106 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 107 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 108 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 109 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 110 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 111 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 112 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 113 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 114 | blocked | overtime_not_modelled | False | False | False | 3 | overtime;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | differs |
| 115 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 116 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 117 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 118 | regulation_end_guarded | - | True | False | False | 6 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 119 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 120 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 121 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 122 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 123 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 124 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 125 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 126 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 127 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 128 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 129 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 130 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 131 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 132 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 133 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 134 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 135 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 136 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 137 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 138 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 139 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 140 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 141 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 142 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 143 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 144 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 145 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 146 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 147 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 148 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 149 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 150 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 151 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 152 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 153 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 154 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 155 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 156 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 157 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 158 | regulation_end_guarded | - | True | False | False | 6 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 159 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 160 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 161 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 162 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 163 | blocked | overtime_not_modelled | False | False | False | 3 | overtime;unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | differs |
| 164 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 165 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 166 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 167 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 168 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 169 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 170 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 171 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 172 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 173 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 174 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 175 | blocked | overtime_not_modelled | False | False | False | 4 | overtime;unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | differs |
| 176 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 177 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 178 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 179 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 180 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 181 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 182 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 183 | regulation_end_guarded | - | True | False | False | 6 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 184 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 185 | blocked | overtime_not_modelled | False | False | False | 3 | overtime;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | differs |
| 186 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 187 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 188 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 189 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 190 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 191 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 192 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 193 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 194 | blocked | thin_kick_cell:field_goal:50+ | False | False | False | 2 | rare kick outcome;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | differs |
| 195 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 196 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 197 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 198 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 199 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 200 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 201 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 202 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 203 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 204 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 205 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 206 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 207 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 208 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 209 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 210 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 211 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 212 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 213 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 214 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 215 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 216 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | differs |
| 217 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 218 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 219 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 220 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 221 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 222 | regulation_end_guarded | - | True | False | False | 6 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 223 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 224 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 225 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 226 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 227 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 228 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 229 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 230 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 231 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 232 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 233 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 234 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 235 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 236 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 237 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 238 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 239 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 240 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 241 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 242 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 243 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 244 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 245 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 246 | blocked | overtime_not_modelled | False | False | False | 3 | overtime;unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | differs |
| 247 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 248 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 249 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 250 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 251 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 252 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 253 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 254 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 255 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 256 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 257 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 258 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 259 | regulation_end_guarded | - | True | False | False | 7 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 260 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 261 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 262 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 263 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 264 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 265 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 266 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 267 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | differs |
| 268 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 269 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 270 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 271 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 272 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 273 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 274 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 275 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 276 | blocked | overtime_not_modelled | False | False | False | 3 | overtime;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | differs |
| 277 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 278 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 279 | blocked | overtime_not_modelled | False | False | False | 3 | overtime;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | differs |
| 280 | blocked | overtime_not_modelled | False | False | False | 4 | overtime;unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | differs |
| 281 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 282 | regulation_end_guarded | - | True | False | False | 4 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 283 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 284 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 285 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 286 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 287 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 288 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 289 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 290 | blocked | overtime_not_modelled | False | False | False | 2 | overtime;unmodelled transition: two_minute_warning | 0 | differs |
| 291 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | differs |
| 292 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 293 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 294 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 295 | regulation_end_guarded | - | True | False | False | 6 | unmodelled transition: missed_field_goal_return;unmodelled transition: timeout;unmodelled transition: two_minute_warning | 0 | same |
| 296 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 297 | regulation_end_guarded | - | True | False | False | 5 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 298 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
| 299 | regulation_end_guarded | - | True | False | False | 2 | unmodelled transition: two_minute_warning | 0 | same |
| 300 | regulation_end_guarded | - | True | False | False | 3 | unmodelled transition: missed_field_goal_return;unmodelled transition: two_minute_warning | 0 | same |
