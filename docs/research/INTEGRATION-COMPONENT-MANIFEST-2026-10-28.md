# Component manifest: event-based NFL simulator integration, 2026-10-28

Purpose: where each component of the combined model lives, whether it is on `research/lp-event-phase1-2026-10-28`, and
whether it can be used without touching the 2026 holdout. Holdout status is the rule in `HOLDOUT-EXPOSURE-RECORD-2026.md`.

Branch base: `origin/dev` `382f5ffe`. Nothing here is merged. Nothing is pushed.

| # | component | where it lives | on this branch | holdout status | what it contributes | blocker |
|---|---|---|---|---|---|---|
| 1 | Authoritative reducer | `scripts/nfl_sequence/reducer.py` | yes | no data read | legal play transitions; must not change | none |
| 2 | E2 game framework (coin toss, kickoffs, scoring, clock, tries, overtime, special teams) | `game_state.py` | yes | no data read; the kickoff pool is 2022 to 2025 | game-level accounting and the drive linkage | participants are still chosen after the event (row 13) |
| 3 | E1 observed play pool | `e1_drive.py` | yes | 2022 to 2025 only; `load` and `load_seasons` refuse 2026 | conditional event outcomes by down, distance and field cell | no team or QB conditioning yet |
| 4 | Contextual pool (team offense and defense reweighting, S1) | `contextual_pool.py`, `e2_reference.py` | yes | refuses 2026 periods; cutoff rule enforced by `e1.load(eligible_before=...)` | matchup weighting of the pool | source ratings come from the pool itself, not from playbooks or splits |
| 5 | Opponent-adjusted team ratings and prior-week context | `pregame_context.py`, `backend/nfl_ratings_data.py` | yes | refuses a 2026 matchup | team offense and defense points ratings before each week | context modes need a decision on 2026 cutoffs |
| 6 | Pregame snapshot (schedule as of the cutoff, depth chart at the cutoff) | `pregame_snapshot.py` | yes | refuses a 2026 game row | participants' pregame roles | depth chart is a roster input only; no team tendencies |
| 7 | Batch runner, seed ledger, resume, error stop | `simulate_pregame_batch.py` | yes | v1 comparator refused for 2026 | per-seed outputs, resume, early stop | none for the infrastructure |
| 8 | v1 baseline and aggregation | `pregame_batch.py` (in `backend/`), `_baseline_v1` | yes | refused for 2026 targets | comparison arm only | not a component of the new model |
| 9 | Team playbooks, offense and defense profiles | Gridiron repo `data/playbooks/{TEAM}-2025.json`; branch `research/nfl-team-season-playbooks-2026-10-27` at `97841be` | **no** | the 2025 files are season 2025, which is not the holdout; each file also holds a `pregame_2026_comparison` block with 2026 data (NE-2025.json has 11,315 "2026" strings) | team tendencies by situation and formation | 14 of 32 teams only; full-season 2025 priors cannot drive an earlier 2025 game; the 2026 block must be stripped or the file rebuilt from 2025 play-by-play only; `pregame_2026_comparison` must never be read |
| 10 | Opponent-adjusted offensive and defensive splits | `scripts/nfl_sequence/splits/team_splits_build.py`, `team_splits_query.py`, `team_box_build.py` on `origin/research/nfl-historical-splits-2026-10-27` | **no** | not audited for 2026 reads | team splits by situation | not on this branch; cutoff audit not done |
| 11 | Decision model v1: role-based run and pass decisions by situation and alignment | `scripts/nfl_sequence/splits/decision_model.py` on the same splits branch | **no** | prior fit on 2025 only, `k` chosen on 2025 validation; **the one 2026 test has already run** (`test2026.json` exists) | decision probabilities by role | holdout spent for v1; needs your decision before any use |
| 12 | Decision model v2: participation categories | specification `docs/NFL-DECISION-MODEL-SPEC-V2-PARTICIPATION-2026-10-27.md` on the splits branch | **no** | not checked | participation-based decision categories | implementation status not checked; spec only as far as read |
| 13 | Statistical QB and player opportunity model (participants chosen before the event) | not built | no | none | the change from post-event to pre-event participants | must be built; `game_stats.py` still assigns players after the event |
| 14 | Participant accounting (player, team and drive totals) | `game_stats.py` (used by `game_state` and its test only) | yes | no data read | player stat lines from the generated game | assignment order must change with row 13 |
| 15 | Holdout fixture: week 7 KC at SEA (pregame snapshot and simulated record) | `docs/fixtures/pregame/game-kc-sea-seed1-full-depth.json` | yes | **2026 simulation output** | none | tests skipped; quarantine decision pending |
| 16 | Sanitized 2022 to 2025 research database | not built | no | must contain no 2026 rows | the database the faster machine would use | extraction, row counts, hashes and licensing check not done; the full `picks.dev.db` (3.4 GB) holds 2026 data and must not be copied |

## Integration order (proposed, not started)

1. Team splits from 2022 to 2024 only, for 2025 cutoffs. Check that a change in a team split changes the matching event rates
   in the pool, and that S0 is unchanged.
2. Cutoff-safe playbooks, rebuilt per cutoff from play-by-play before that cutoff, with the 2026 block removed from every
   derived file. Check the team tendency changes the formation and play-type mix.
3. Pre-event participant selection: QB and receivers chosen from the depth chart and the team's usage before the event is
   drawn, behind a research flag. Check the participant totals equal the drive totals.
4. Decision mix: decision model v1 priors applied as importance weights on the E1 pool rows, behind a research flag. The
   weights come from 2025 only. Decision model v1's 2026 test status must be settled first (row 11).
5. Pre-2026 chronological diagnostic: one 2025 game with a pre-kickoff cutoff, unconditioned against each team-context mode,
   with the event distributions and accounting checked.
6. Only after steps 1 to 5 pass locally: plan the larger batch. A 10,000-seed run is a final compute step.

## Blockers

- Decision on row 11 (decision model v1 2026 test already run).
- Decision on quarantining row 15 and the 2026 block in row 9.
- Decision on whether any 2026 result may enter a model before a cutoff. Current answer: no.
- Playbook coverage: 14 of 32 teams, all 2025.
- Participant assignment (row 13) is not built.
- The research database (row 16) is not built.
