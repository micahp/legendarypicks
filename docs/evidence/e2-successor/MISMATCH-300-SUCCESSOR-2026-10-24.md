# E2 successor: counterfactual for seeds changed from the frozen survey

Frozen reference `a442dcd72559cfaf2d04737fc2454cea486faf09`. Current engine base `dfef3e8e40ab9702c1f021ff726e3959d6f9d63b`; exact source-tree SHA-256 `79a65db640e587798f2a067853a3ba8f723aadfbb10e3021cddb3c92ec08c117`.
The control holds the current engine and each random seed fixed and changes only the reference population from `regulation_only=True` to `regulation_only=False`.
Changed seeds: 19. Classifications: not_explained_by_pool_alone 13, regulation_only_pool 6.

Detail: regulation_only_pool_changes_frozen_outcome 6, status_or_blocker_differs_with_all_quarter_pool 2, two_minute_guard_keeps_complete_game_false 11. For the two-minute guard cases, the all-quarter run matches the frozen status, blocker and regulation-end outcome, while the current unmodelled-transition guard correctly leaves `complete_game=false`.

| pool | E1 play rows | kickoff rows | overtime rows excluded |
|---|---:|---:|---:|
| regulation only | 137373 | 9963 | 1214 |
| all quarters | 138235 | 10037 | 0 |

| seed | frozen outcome | regulation-only | all-quarter control | classification detail | matrix FAIL rows (frozen / filtered / control) |
|---:|---|---|---|---|---:|
| 9 | blocked/thin_kick_cell:field_goal:50+ | complete_regulation/- | blocked/thin_kick_cell:field_goal:50+ | `regulation_only_pool_changes_frozen_outcome` | 0 / 0 / 0 |
| 36 | complete_regulation/- | blocked/overtime_not_modelled | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 48 | blocked/overtime_not_modelled | complete_regulation/- | blocked/overtime_not_modelled | `regulation_only_pool_changes_frozen_outcome` | 0 / 0 / 0 |
| 55 | complete_regulation/- | blocked/overtime_not_modelled | blocked/overtime_not_modelled | `status_or_blocker_differs_with_all_quarter_pool` | 0 / 0 / 0 |
| 78 | blocked/overtime_not_modelled | complete_regulation/- | blocked/overtime_not_modelled | `regulation_only_pool_changes_frozen_outcome` | 0 / 0 / 0 |
| 87 | blocked/overtime_not_modelled | complete_regulation/- | blocked/overtime_not_modelled | `regulation_only_pool_changes_frozen_outcome` | 0 / 0 / 0 |
| 114 | complete_regulation/- | blocked/overtime_not_modelled | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 163 | complete_regulation/- | blocked/overtime_not_modelled | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 175 | complete_regulation/- | blocked/overtime_not_modelled | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 185 | complete_regulation/- | blocked/overtime_not_modelled | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 194 | complete_regulation/- | blocked/thin_kick_cell:field_goal:50+ | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 216 | blocked/thin_kick_cell:field_goal:50+ | complete_regulation/- | blocked/thin_kick_cell:field_goal:50+ | `regulation_only_pool_changes_frozen_outcome` | 0 / 0 / 0 |
| 246 | complete_regulation/- | blocked/overtime_not_modelled | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 267 | blocked/overtime_not_modelled | complete_regulation/- | complete_regulation/- | `status_or_blocker_differs_with_all_quarter_pool` | 0 / 0 / 0 |
| 276 | complete_regulation/- | blocked/overtime_not_modelled | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 279 | complete_regulation/- | blocked/overtime_not_modelled | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 280 | complete_regulation/- | blocked/overtime_not_modelled | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 290 | complete_regulation/- | blocked/overtime_not_modelled | complete_regulation/- | `two_minute_guard_keeps_complete_game_false` | 0 / 0 / 0 |
| 291 | blocked/overtime_not_modelled | complete_regulation/- | blocked/overtime_not_modelled | `regulation_only_pool_changes_frozen_outcome` | 0 / 0 / 0 |
