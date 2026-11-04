# M5 freeze amendment 6, 2026-11-04: field goals by the team's kicker

Status: owner-authorized (2026-11-04). Research only, behind `--playcall-fg-kicker`, off by default; it needs the
`long_field_goal_feasibility` blocker fix. No SLC default changes. No production activation. No 2026 outcome was read:
kicker ability is fitted on 1999 to 2025, and only the 2026 weekly roster's active kicker (identity) is read.
Earlier freeze documents and amendments are not edited.

## Why

- The engine computes a kick's distance as the snap spot plus 17. The published `kick_distance` is the snap spot plus 18
  on 87% of 2022 to 2025 attempts (19 on 11%), so every kick was one yard short.
- The ordinary 60-yard cutoff and the 70-yard ceiling (the 2022 to 2025 maximum) are not football limits. The longest
  attempt on record is 76 yards (2008_04_SD_OAK, play-by-play).
- The kick decision used the whole situation cell's share. The cell's field bucket `20-49` spans 38 to 67-yard kicks, so a
  4th down at the 47 kicked at the bucket's average field-goal rate; only the 60-yard cutoff hid that. On every 2025 snap
  (pools 2022 to 2024, `fg-kicker-2026-11-04/fg_decision_check.py`), expected attempts against observed:

  | Distance | Observed | Cell share, 60-yard cutoff | Yard-line kernel (2 yards), 76 ceiling |
  |---|---|---|---|
  | 40-49 | 325 | 194 | 316 |
  | 50-54 | 163 | 111 | 159 |
  | 55-59 | 91 | 110 | 76 |
  | 60-64 | 16 | 54 | 14 |
  | 65-69 | 7 | 11 | 2.5 |

- The make probability was the league curve for every kicker.

## The change (flag on)

- Distance = snap spot + 18; ceiling 76 yards in every situation (`field_goal_feasibility.RECORD_RULE`). No 60-yard
  ordinary cutoff and no end-of-half or desperation exception is needed: the ceiling is the same everywhere.
- Kick or not, and field goal or punt, come from the cell's rows weighted by a normal kernel (2 yards) in yard line around
  the snap spot (`kicker_field_goals.kernel_counts`).
- Make probability: the league distance curve plus the offense's kicker's logit offset (posterior mode, normal prior sd
  0.3, seasons weighted 0.5 ** age, each earlier kick judged against its own week's league curve). Selected on 2016 to
  2021; on 2022 to 2025, week over week, it beats the league curve by 0.0015 log loss [0.0002, 0.0028], and at 50+ yards
  by 0.0042 [0.0002, 0.0080] (`fg-kicker-2026-11-04/kicker_fg_check.json`). A kicker with no earlier kick gets the league
  curve, recorded as `league_curve_no_kicker_history`.
- The kicker is the team's one active K on the published weekly roster for the game's week (every 2025 team-week has
  exactly one; one 2026 team-week has none, and a game there is refused).
- The feasibility evidence names its rule, and the game validator recomputes it under the recorded rule (only the pinned
  rule and the record rule are accepted).

## Changed files

Base commit: `7125f630`.

| File | Frozen SHA-256 | Amended SHA-256 | Pinned | Change |
|---|---|---|---|---|
| `scripts/nfl_sequence/slc_playcall.py` | `0cb9eecfeaecd3fe9c959f691eda19c5290b534320632416f8cd0703dd1c6f2c` | `33424b7a2f1548c6cb8518e6a209f5f9e470552b8d4c756380f10b032d364b78` | yes | `fg_kicker` attribute; with it, the record rule, kernel kick counts, the record ceiling in `_field_goal_actions`, the kicker make draw and decision fields. Flag off: unchanged. |
| `scripts/nfl_sequence/game_state.py` | `235b457b...` | `4df3aac7...` | no | Field-goal resolution under the record rule with the offense's kicker; validator recomputes under the recorded rule. |
| `scripts/nfl_sequence/e1_drive.py` | `433c02df...` | `5ea30b1d...` | no | Feasibility under the sampler's rule. |
| `scripts/nfl_sequence/field_goal_feasibility.py` | `0bdbc9ec...` | `e1b847ef...` | no | `evaluate(..., rule=None)`; the default output is unchanged. |
| `scripts/nfl_sequence/slc_engine.py` | `29834b82...` | `a5e36cac...` | no | `load_reference(fg_kicker=(path, sha256))`: needs the blocker fix, refuses a table fitted on the game's season or later, assigns each side's kicker. |
| `scripts/nfl_sequence/simulate_pregame_batch.py` | `68434725...` | `9e3ea552...` | no | `--playcall-fg-kicker`, `--playcall-fg-kicker-sha256`; pinned in the ledger's `research_integration`. |

New: `scripts/nfl_sequence/kicker_field_goals.py` (`5820afb8...`), `test_kicker_field_goals.py` (`cc86583c...`, 11 tests),
`docs/research/fg-kicker-2026-11-04/build_kicker_table.py` (`16278870...`), `fg_decision_check.py`.

## Table

| File | SHA-256 | Content |
|---|---|---|
| `fg-kicker-2026-11-04/kicker_table_through_2025_assign_2026.json` | `9fdc57b223db5c4944b9d84ce7e2f4aa71c0e7639dfea9d41fc80a77e728e81f` | 202 kickers fitted on 1999 to 2025; 241 2026 team-weeks assigned; 3 assigned kickers with no earlier kick |

## Verification

- Tests: 359 passed (`test_kicker_field_goals` 11 new, `test_slc_blocker_resolution`, `test_game_state`,
  `test_e1_transitions`, `test_slc_engine`, `test_slc_playcall`, `test_pre_event`, `test_rng_protocol`, the participation
  and PBV1 hook tests).
- Flags-off regression (frozen extract, Week 8 `2026_08_KC_DEN`, RNG v2, seeds 1 to 3): 0 of 3 seeds differ.
- Flag-on smoke, same command plus `--slc-blocker-fix long_field_goal_feasibility --playcall-fg-kicker
  docs/research/fg-kicker-2026-11-04/kicker_table_through_2025_assign_2026.json`: 3 of 3 valid games (DEN-KC 23-25,
  18-35, 9-27). Kickers DEN `00-0032569` (offset -0.022, 317 earlier kicks), KC `00-0033303` (offset +0.054, 324).
  Field-goal attempts 5, 3 and 6, every one drawn with the kicker offset; the field goal was ruled out beyond 76 yards
  14, 10 and 9 times. The table is pinned in the ledger's `research_integration.fg_kicker`.

## Known limits

- The kick decision is still the league's history near the yard line, not the team's or the kicker's: a strong-legged
  kicker makes more of his long kicks but does not attempt more of them.
- The yard-line kernel has no clock: end-of-half heaves are pooled with ordinary 4th downs at the same spot. 65 to 69-yard
  attempts are under-predicted on 2025 (2.5 against 7).
- The weekly roster is the gameday roster, so a kicker change announced late is already in it.
