# V1.5 outcome ablation: safety-state failure analysis

**Captured:** 2026-11-11 01:48 CT (07:48 UTC)

**Cohort status:** active; 106 paired games complete and valid, 2 games failed, 13 still pending.

## Finding

The two failures occurred in different arms. Each preserved failed-seed artifact contains the full game record, including the last drive, its final play transition, and the following safety free kick. The artifacts are copied unchanged into `failed-seeds/`; their compressed-file SHA-256 values are listed below.

Both records end regulation untied. The final drive ends in a safety, then a `safety_free_kick` is recorded. That kick is marked `clock_expired_during_kickoff=true`, and the record ends at Q4 0:00 with `complete_regulation=true`. The validator rejects both because its game-ending-kick predicate includes post-score and post-field-goal kicks but omits `safety_free_kick`.

This points to a validator coverage defect, not evidence that the safety transition itself was illegal. The kickoff clock rule is marked `authored_modelling_choice` in both records. Its football accuracy still needs a separate rules review. No simulator or validator code was changed, and no seeds were rerun.

## Failure records and final transitions

| Game | Arm | Seed | State before final play | Final play and state after | Following kick |
| --- | --- | ---: | --- | --- | --- |
| `2026_03_LA_DEN` | Ablation without `team_offense_defense_outcomes` | 9 | Q4 0:45; LA offense, DEN defense; 1st-and-10 at yardline 98; DEN 23, LA 13 | LA run for -2 yards; safety to DEN; Q4 0:06; DEN 25, LA 13 | Safety free kick; 0:06 to 0:00; period expired during kick |
| `2026_04_LAC_SEA` | Original control | 16 | Q4 1:32; SEA offense, LAC defense; 2nd-and-7 at yardline 95; SEA 13, LAC 9 | SEA run for -5 yards; safety to LAC; Q4 0:47; SEA 13, LAC 11 | Safety free kick; 0:47 to 0:00; period expired during kick |

The exact assertion in both artifacts is: `ILLEGAL_STATE: the last drive ends with 'safety' in quarter 4 at <clock>, which does not end the game` (6 seconds for `2026_03_LA_DEN`; 47 seconds for `2026_04_LAC_SEA`).

`game_legality.py` defines `POST_SCORE_KICKS = ('post_score', 'post_field_goal')`. `_game_ending_kick()` accepts only those kinds, although the record format and legality code separately recognize `safety_free_kick`. Since `_ends_the_game()` relies on `_game_ending_kick()` for a score followed by a clock-expiring kick, it rejects these records before allowing the recorded safety free kick to end regulation.

The failure envelope alone says `state_before`, `state_after`, and `play_index` are unavailable. The preserved full record supplies the transitions above. The saved control ledger for `2026_03_LA_DEN` has 20 complete seeds (2–21). The treatment failed at seed 9 after 8 completed seeds. For `2026_04_LAC_SEA`, the control failed at seed 16 after 15 completed seeds; the treatment did not start.

## Artifact hashes

These SHA-256 values are for the copied compressed files and match the files on the fast host.

- `failed-seeds/2026_03_LA_DEN-ablation-seed-9.json.gz`: `25fb57e06626903634ac0a5cd033bc39afb40cd2f6dceb8560941656bdda2f53`
- `failed-seeds/2026_04_LAC_SEA-control-seed-16.json.gz`: `ab5d4f74a31c61867f48fa03655dd053bbee63ddcaa0883d9649af34a32f5f51`

## Coverage at capture

At this checkpoint, 106 games had full valid results in both arms (2,120 seeds per arm). The failed games were not included in that paired population. Thirteen other games had not completed. This is a progress snapshot; the final report must give the completed count, valid seed count in each arm, and common paired population separately. Do not treat a partial arm as a complete game or silently drop its failure.

Fast-host source commit: `67d3f5522da13d20f79389cfac2f7495386c4d10`. Run data remain at `/root/ot-sim-out/slc-v15-outcome-ablation-121-2026-11-11` on the fast host. This report does not resolve the authored safety-kick clock assumption or grade predictive metrics.
