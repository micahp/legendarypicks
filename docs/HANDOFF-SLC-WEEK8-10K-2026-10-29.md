# SLC Week 8 10K run handoff

- **Prepared:** 2026-10-29
- **Checkout:** `/root/lp-slc-preevent`
- **Branch:** `research/slc-decision-layer-2026-10-29`
- **Base HEAD and remote:** `e655f55165db56ee545ed5e98a4f37c9ea8b35c4`
- The QB/player integration commit `03c8c1f7` is earlier in this branch history; `e655f551` is the current branch tip.
- **Status:** Research work is uncommitted. No 10K simulation was started.

## Request and run scope

The requested next experiment is a 10,000-seed Week 8 SLC run with the connected SLC layers enabled. The Week 8 snapshot directory contains multiple games. Confirm which game is the target before running. This handoff assumes one selected matchup; 10,000 seeds for every Week 8 game is a materially larger experiment and must be treated as a separate scope decision.

For an interpretable player-model result, use the same snapshot and seed range for three arms:

1. **Pooled SLC:** score-clock play calling with the frozen play-call artifact and no optional splits.
2. **Team-conditioned SLC:** pooled SLC plus team offense/defense outcome splits, formation-conditioned outcomes, and coverage-conditioned outcomes.
3. **Full player stack:** team-conditioned SLC plus Dirichlet player shares, QB decisions, and all player-conditioned outcome roles.

Use 10,000 common seed IDs in each arm (`--seed-start 1`, `--games 10000`). This is 30,000 simulated games for one matchup. The three arms distinguish the pooled baseline, the existing team/formation/coverage layer, and the added player stack. Do not report an uplift from the full arm alone as a model comparison.

For the full player stack, enable:

```text
--playcall-team-outcomes
--playcall-formation
--playcall-coverage
--playcall-dirichlet-shares
--playcall-qb-decisions
--playcall-player-outcomes
```

`--playcall-dirichlet-shares` also enables the player-share participant adapter. Do not add `--playcall-player-outcomes-receiver-only`; the full arm should include QB, receiver, and rusher outcome roles.

Keep the independent target-role/decision/playbook, point-split, streak, exact-yardline, and contextual-policy experiments off for this comparison. They are separate switches and some overlap with QB decisions or formation/outcome conditioning. If the requested meaning of “all SLC layers” includes those experiments, add them to all applicable arms and identify them separately in the run manifest.

## Preflight and execution

Do not start the 10K job until the receiving agent has:

1. Confirmed the target game and loaded the selected frozen snapshot with `pregame_snapshot.load_frozen_snapshot()` so its hash and cutoff are validated. Do not use target-game outcomes in fitting or inputs.
2. Confirmed the play-call artifact cutoff and the exact model/source manifests in each arm.
3. Run a 100-seed pilot for all three arms using the same seed range. Check runtime, error count, completed/valid game count, player eligibility, participant-before-outcome traces, and score/stat reconciliation.
4. Immediately before the 10K run, checked both `uptime` and `free -h`. The box has 5.8 GB RAM; do not start if available memory is below about 1.5 GB. Run one process at a time with no hidden parallel workers. The earlier 3.0 GB availability reading from this session is stale and must not be used as the run-time gate.

Use the repository virtualenv Python, not host Python. Do not run `npm`, start/restart a server, or use a second dev-server stack.

Command template for the full player stack (replace the two placeholders after the target matchup is selected):

```bash
/root/legendarypicks/backend/venv/bin/python scripts/nfl_sequence/simulate_pregame_batch.py \
  --snapshot-file docs/research/slc-week8-2026/snapshots/<TARGET_WEEK8_GAME>.json \
  --games 10000 --seed-start 1 \
  --playcall-artifact docs/research/SLC-PLAYCALL-ARTIFACT-v1.json \
  --playcall-team-outcomes --playcall-formation --playcall-coverage \
  --playcall-dirichlet-shares --playcall-qb-decisions --playcall-player-outcomes \
  --progress-every 100 \
  --out docs/research/slc-week8-2026/paired-player-stack/<TARGET_WEEK8_GAME>-full-player-stack-10k.json
```

Run the other two arms sequentially with the same snapshot, artifact, `--games 10000`, and seed range. Keep output and `.seeds.jsonl` files in a new research subdirectory; do not overwrite existing Week 8 artifacts. Preserve every failed or blocked seed in the ledgers.

## Metrics and review gates

Report, by arm and paired difference:

- Valid complete games, ties, blocked games, and simulation errors.
- Home/away points, win/tie rates, total points, plays, drives, possessions, touchdowns, red-zone trips, and red-zone conversions.
- Passing, rushing, target, and carry counts; player count means, variance, quantiles, and zero-opportunity rates.
- QB action counts, QB target-role counts, target-role history support, source-row conditioning/fallback counts, and draw-time roster-role fallbacks.
- Player eligibility failures, missing-history participation, and any emitted participant not found on the frozen roster.
- Exact snapshot, artifact, source, model-version, code, and seed-ledger hashes.

Use matched seeds and game-level uncertainty for arm comparisons. Treat the Week 8 10K run as an exploratory simulation of the frozen inputs, not evidence of historical calibration. Player shares should change player opportunity allocations; they should not be credited with improving scoring unless the player-conditioned outcome model is enabled. Team scoring and win probability remain unvalidated by the earlier event-level tests.

## Work completed in this checkout during this session

### Receiver and outcome isolation

- Added a receiver-only outcome ablation switch to `run_slc_game.py` and `simulate_pregame_batch.py`. It requires player outcomes to be enabled and is included in run/seed manifests.
- Routed the enabled player roles through `player_outcomes.py`, `slc_playcall.py`, and `slc_engine.py`; receiver-only weighting leaves QB and rusher outcome weights at neutral.
- Added tests proving receiver-only outcome sampling responds to receiver identity but ignores QB identity, and that receiver result weights are attached to the selected receiver.
- The pre-event participant chooser now applies frozen `Out`/`Doubtful` eligibility across QB, receiver, and rusher choices even when QB decisions and Dirichlet shares are off. The fallback QB is selected from the available roster when an injury report exists.

### QB target-role diagnosis and test findings

- Added `scripts/nfl_sequence/diagnose_qb_target_role.py` and a reproducible JSON/Markdown report under `docs/research/SLC-PLAYER-CONDITIONING-2026-10-29/`.
- Inputs are the local read-only play-by-play database plus official nflverse 2024 and 2025 depth-chart parquet files. Their SHA-256 hashes are in the JSON report. The 2025 file is available from the [official nflverse release](https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_2025.parquet); the 2024 file uses the corresponding [2024 release](https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_2024.parquet).
- 2024 is a tuning holdout (fit 2022–2023); 2025 is the chronological final holdout (fit 2022–2024). Candidate own-QB shrinkage strengths were 0, 5, 10, 20, 40, 80, and 160, while the team prior remains shrunk by 20 observations.
- At the current strength 20, 2025 QB target-role log loss is worse than the team-conditioned baseline by `0.00734` per target (95% game-bootstrap CI `[-0.00894, -0.00576]` in the new diagnostic; the prior report gives `[-0.00889, -0.00572]`). The same direction remains when scoring only targets whose receiver and role appear in the pregame depth chart: `-0.00702` on 16,437 targets.
- Tuning on 2024 selects strength 160, the weakest QB-specific effect in the candidate grid. It still regresses on 2025 by `0.00114` log loss (95% CI `[-0.00154, -0.00072]`). Zero-support rows match the team prior; deterioration is concentrated among supported QB/team/situation cells, so sparse history is not the only explanation.
- The diagnostic was generated before the new zero-mass handling in `qb_decisions.draw()`. That edit did not change `_target_distribution`, `_distribution`, or the validation scoring path, so these scores are unaffected; the JSON's QB source hash identifies the pre-fallback file. Rerun the diagnostic if the final report must carry a post-fallback source hash.
- The depth-chart inputs are only role/roster proxies. Historical 2025 injury rows have no `date_modified`, so the report does not claim frozen injury eligibility or complete roster-valid calibration. The role-model regression remains a promotion blocker.

### Additional tests and robustness fix

- Added QB tests for team-keyed histories across a transfer, new-QB backoff to the team prior, normalized target-role probabilities after roster filtering, and zero estimated mass across all available roles.
- Found and fixed a real zero-mass failure: `qb_decisions.draw()` divided by zero when every model prior assigned zero mass to roles available on the frozen roster. It now falls back uniformly across the available roles and records `no_model_mass_for_available_roles`.
- Added pre-event and sampler tests for that fallback, for filtering source outcomes by the selected QB target role, and for recording the fallback when the source cell contains no row matching the chosen role. In that latter case the current sampler retains the original candidate row; the trace counts it as `no_target_identity_match_in_event_cell`, so the Week 8 run should report its frequency and role mismatch implications.
- Decision traces now include the normalized role probabilities and draw-time fallback count. `slc_engine.summary()` records these separately from the later source-row role-match fallback.
- Added player-outcome tests proving event/result weights follow the matching selected role and do not leak across passer, receiver, and rusher identities.
- Latest focused run: **61 tests passed** across `test_qb_decisions`, `test_pre_event`, `test_slc_playcall`, `test_player_outcomes`, and `test_slc_engine`. Earlier, before the last zero-mass tests/trace fields, the wider SLC integration set reported **93 tests passed**. No 10K job has been launched.

### Existing evidence and unresolved model issues

- Existing 2025 event holdout: receiver event and completion-result log-loss improvements are `+0.00746` and `+0.02066`; QB pass/scramble is inconclusive (`-0.00099`); QB target role regresses (`-0.00734`); QB completion result regresses (`-0.00448`); rusher scores are near zero/inconclusive. These are event-level scores, not full-game validation.
- The 2024-fit/2025-held-out Dirichlet player-share report shows joint log-score improvements over fixed shares of `+4.30` per team-game for targets and `+5.54` for carries for the tested returning-player cohort. Zero rates and some quantiles remain miscalibrated.
- Team-strength pass-through remains unresolved. The simulation still produces roughly 10% too many scrimmage plays, and the 2024 replay has too few red-zone trips/too little touchdown conversion. Those mechanisms can distort player totals and game probabilities.
- No player-specific model is promoted or on by default. There is no complete QB progression/pressure-response model or defensive adaptation model.

## Checkout safety and ownership

- Do not discard/reset the worktree. The diagnostic and integration changes above are uncommitted.
- The uncommitted **engine and runner** changes are `scripts/nfl_sequence/slc_engine.py`, `slc_playcall.py`, `run_slc_game.py`, and `simulate_pregame_batch.py`. They include receiver-only role wiring, QB target-role probability/fallback traces and summaries, and runner/batch flags and manifests. The other uncommitted implementation files are `player_outcomes.py`, `pre_event.py`, `qb_decisions.py`, and `validate_qb_player_outcomes.py`.
- The uncommitted tests are `test_player_outcomes.py`, `test_pre_event.py`, `test_pregame_batch.py`, `test_qb_decisions.py`, `test_run_slc_game_flags.py`, `test_slc_engine.py`, and `test_slc_playcall.py`. The target-role diagnostic script and its report/data inputs are also uncommitted.
- A 10K run from this checkout would execute these dirty engine/runner changes while its base commit remains `e655f551`. Before starting, the receiving agent must either use this exact worktree and record the patch/source hashes with the run, or obtain a reviewed/committed research revision. Do not assume the base commit alone identifies the executed code.
- `scripts/nfl_sequence/scoring_redzone_decomp_2024.py` was already untracked before the current QB-test additions; preserve it and do not stage it accidentally.
- This session did not commit or push. The branch remote matched `e655f551` at inspection. No production promotion is authorized.
- The 10K run is a research batch, not a release. Keep all outputs under `docs/research/slc-week8-2026/`; do not change defaults or deploy.
