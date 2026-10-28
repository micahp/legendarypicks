# SLC integration ledger, 2026-10-28

Model: Score-Clock Layered (SLC), v1. Model id in outputs: `slc_v1_incomplete` until the full path passes. Coaching and physical
player movement are excluded from v1. S0 is the original unconditioned historical sampler and stays as a control.

Branch: `research/slc-model-2026-10-28` at `a68750c1` (pushed). The branch starts from `bbc21f79`, the research head with the
play-call reproduction, version 2 report and uncertainty analysis.

## Status in one paragraph

One complete game (seed 1, SEA at KC) runs through the existing engine with the score-clock play-call layer choosing every
scrimmage play before its outcome is drawn. It reaches regulation (34 to 20, 22 drives, 139 scrimmage decisions). The game is not
complete, because the engine's missed-field-goal return guard applies to it. The run has no pregame snapshot, so it is not a
pregame full-game record and `valid_full_game` is false. The team, playbook, QB and role layers are not connected.

## Connected and exercised at runtime

| Layer | Source (branch, commit) | Files | Runtime call site | Contract | Training window and cutoff | Test coverage |
|---|---|---|---|---|---|---|
| Score-clock play-call policy | `research/slc-model-2026-10-28`, `a589268b` | `slc_playcall.py`, `docs/research/SLC-PLAYCALL-ARTIFACT-v1.json` (sha256 `27c02afd…`) | `e1_drive.simulate` calls `PlayCallSampler.sample(state=…)`; wired by `e2_reference.load(playcall_artifact=…)` | In: down, distance, field position, score difference, quarter, clock, offense team. Out: intent (run or dropback), event and historical row, with a decision record | Frozen on all 2010 to 2025 primary plays (522,235). Recency reference season 2026. Artifact is not a cutoff-safe 2025 backtest | `test_slc_playcall.py`, 12 tests, including score and clock sensitivity and the play-before-outcome order |
| Pre-play state into the drive policy | `research/slc-model-2026-10-28`, `ac7471af` | `e1_drive.py`, `game_state.py` | `game_state._drive_body` passes `score_diff = points[offense] - points[defense]`; `e1` passes quarter, clock, down, distance and field position | Sampler signatures accept `state`; existing samplers ignore it | not applicable | existing engine, sampler and game-state tests: 246 pass |
| Legal game-state machine, clock, scores, possession | inherited from the research head | `game_state.py`, `reducer.py` (authoritative), `e1_drive.py` | every drive | reducer enforces legal transitions; guards record unmodelled transitions | not applicable | existing suites |

## Wired, but not the SLC path

| Component | Status | Why it is not SLC |
|---|---|---|
| Simplified team-tendency sampler | `team_tendency.py`, optional `--team-tendency` in the batch runner | It is an alternative policy. `e2_reference.load` refuses to combine it with the play-call layer. It is not a layer of SLC |
| Opponent-context contextual sampler | `contextual_pool.py`, optional `contextual_mode` | Same restriction: an alternative policy, not a layer |
| Batch runner (`simulate_pregame_batch.py`) | the S0 path | does not load the play-call artifact. Only `run_slc_game.py` connects it |

## Not connected (the SLC layers still to build or connect)

| Layer | Where it lives (to verify) | Current state in the engine |
|---|---|---|
| Detailed offensive and defensive team splits | `research/nfl-historical-splits-2026-10-27` (origin head `1d70898b`) | not connected. Only the offense side is partly covered by the team-by-down effect inside the play-call layer. There is no defensive split |
| Historical team playbooks: formation, personnel, motion, play concept, FTN and participation | Gridiron `research/nfl-team-season-playbooks-2026-10-27` | not connected, and not verified in code yet. FTN and participation cover 2022 to 2025 only |
| Statistical role-based decision model (rusher, QB action, target, defensive response) | `decision_model.py` on `research/nfl-historical-splits-2026-10-27` | not connected, not verified in code yet |
| QB opportunity propensity | `feat/nfl-props-opportunities-propensity` (`06cba41d`) | not connected, not verified in code yet |
| Receiver target-share distribution | `nfl-receiver-target-share-dist-v1` (`79523c00`) | not connected, not verified in code yet |
| Rushing carries and participation | `feat/nfl-rushing-carries-dist-v1` (`24d793c6`), `feat/nfl-rushing-participation-v4` | not connected, not verified in code yet |
| Pre-event participant selection | none | not built. In `game_state._drive_body`, `participants_for` runs after `e1.simulate` has drawn the outcome, so participants follow the outcome |
| Participant-conditioned outcome model | none | not built. The outcome is drawn from historical plays of the chosen type in the same cell, not from the chosen participant |
| Player statistics | `game_stats.py` | allocation, not decision-based. Its docstring says the lines are role allocations, not player projections |
| Pregame roster and snapshot | `pregame_snapshot.py` | not supplied by `run_slc_game.py`. Weeks 5 to 7 cannot be built: 27 QB1 refusals and 15 missing roster files in the smoke test |
| Coaching | separate branch | excluded from v1 by decision |
| Physical QB behaviour | Gridiron `exp/qb-decision-2026-10-25` | separate physical simulation, not the statistical QB model. Not required for v1 |

## Engine guards and open defects

1. **`missed_field_goal_return` (drive 12, seed 1).** The missed kick was drive 12 (1-based), offense B, Q2, `field_goal_made False`. Its last play has `field_goal_return: null`. The guard in `unmodelled_transitions` accepts only a sampled next-drive spot or a period expiry, so it flags this transition. The cause is in the first-piece branch of `_drive_body`: it records the sampled return only when `self.pregame_snapshot` is set. Without a snapshot it uses the fixed dead-ball spot and records no return. The pregame branch does sample a return, and the guard accepts that. I tried removing the gate. Five existing tests encode the first-piece fixed spot as a contract, and the change would also make a no-pool reference block, so I reverted it. **Decision needed:** whether first-piece games should sample the missed-kick return like pregame games, which changes those five tests, or keep first-piece games guarded.
2. **Blocked-kick period expiry at Q1 and Q3.** A fix exists, uncommitted, in the other machine's worktree `fix/week08-simulation-errors`. It needs review, a commit and a rerun.
3. **`NoneType` `<=` TypeError** in the S0 week 8 runs (ARI seed 5722, BAL seeds 6917 and 9243, CHI seeds 1261 and 7805). Not reproduced on the SLC path, and not fixed.
4. **Provisional clock rule.** A touchdown, field goal or safety that expires the clock in Q1 or Q3 kicks off at the start of the next quarter. This is NFL practice, not in `docs/rules/NFL-2026-GAME-STATE-RULES.md`. It appears in the trace (`skipped_post_score_kicks_at_halftime: 1`). It needs checking against the 2026 rulebook.
5. **Kick decisions.** Field goal and punt choices use the situation cell's historical share, labelled `fallback` on every decision. The seed 1 trace has 11 such decisions, including a field goal from the 4 yard line.

## Verification status

- Engine and layer tests: 12 layer tests and 246 engine, sampler and game-state tests pass on `a68750c1`, with the diagnosis changes applied.
- One-game trace: a corrected trace with the runner's contract block is being regenerated. It records `complete_game`, `valid_full_game`, the status, blocker, unmodelled transitions, unsupported rules, scope-out reasons, `regulation_end_reached`, and that player statistics are historical allocations.
- Not verified: the Gridiron playbook branch and every branch in the "not connected" table. Their presence on origin is confirmed for the Legendary Picks branches. Their code is not yet inspected.
- Not claimed: any chronologically valid 2025 backtest. The artifact contains every 2010 to 2025 primary play, so 2025 results from this layer are development results.
- Not run: any 10,000-seed batch, and any Weeks 1 to 7 or Week 8 SLC batch.

## Next steps, in order

1. Decide the missed-kick return contract (defect 1).
2. Review and commit the blocked-kick fix (defect 2), then rerun seed 1.
3. Reproduce the `NoneType` TypeError on the pinned code for the listed seeds (defect 3).
4. Verify the Gridiron playbook and historical-splits code, then connect the team split layer, with a rule for combining it with the play-call layer.
5. Connect the playbook and role layers, and build pre-event participant selection before the outcome is drawn.
6. Add pregame roster input for a historical game with verified snapshots, or accept a team-level partial diagnostic.
7. Check the provisional clock rule against the 2026 rulebook.
