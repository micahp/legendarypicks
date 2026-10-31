# Football realism assertions TODO

Scope: hard football invariants and separate historical distribution warnings for SLC and Gridiron Physics. Preserve predictive parameters and locked outputs; correct only behavior shown to violate an invariant.

## Implemented in this branch

- [x] Check that an explicit QB scramble resolves to a QB rush and does not become a pass.
- [x] Keep sacks outside pass attempts and reconcile scramble, sack, completion, interception, target, and team totals.
- [x] Reconcile every valid full SLC seed before it contributes to batch aggregates, even when box-score export is disabled.
- [x] Add mutation fixtures for impossible player/team accounting and invalid per-seed reconciliation.
- [x] Count a defensive return touchdown for the scoring team without mislabeling it as an offensive touchdown; add a regression fixture for the per-seed accounting failure.
- [x] Carry an unassigned observed overtime offensive touchdown into the exported team line and exclude it explicitly from player-TD reconciliation; add a mutation fixture that proves the gate rejects an incorrect adjustment.
- [x] Give hard assertion exceptions typed failure classes and structured game, seed, play, state, decision, outcome, and artifact-hash context; retain that envelope on per-seed batch errors.
- [x] Add snapshot-pinned named random streams for paired-seed evaluation; isolate E1 playcall, source-row, special-teams, clock-hazard/runoff, kickoff, try, and other event draws, while keeping the default stream behavior unchanged.
- [x] Add `--paired-randomness` to batch runs and a paired-ledger evaluator that requires identical snapshots/seeds/stream roots and exactly one disabled optional layer; retain all failed seeds in its report.
- [x] Reject SLC incomplete passes with gain or credited yards, interceptions without a possession change or with target yards, inconsistent completion yardage, positive-gain sacks, and unsupported play events with the correct failure class.
- [x] Reject nonzero yardage on an incomplete pass in the shared reducer; validate blocked-kick next-snap spot, down, and distance, including strict integer types.
- [x] Preserve the invalid sampled play's game-wide index, state before, selected event, source play, sampled/credited outcome, and unapplied state in a typed assertion failure.
- [x] Require credited passers, targets, and rushers to match the pre-outcome participant selection when that role is active; include a mutated target-attribution fixture with full failure context.
- [x] Count a scramble ending in a lost fumble as both a QB rush and a lost turnover.
- [x] Count a lost fumble by an attributed ball carrier as a rushing attempt in the full-game reconciliation fixture.
- [x] Reconcile an observed no-play overtime offensive touchdown against the team line while keeping a return touchdown out of offensive player statistics.
- [x] Compare SLC scrimmage plays per game with the cutoff-pinned historical pass/run play count.
- [x] GridIron Physics: gate QB reads through delayed visible observations, occlusion, gaze direction, and aging last-seen estimates; estimate defensive ball landing from observed trajectory; cover defensive route privacy and dead-player behavior with tests.
- [x] GridIron Physics: reject positive-gain/scoring kneels, preserve a legal dead-ball kneel, and handle own-goal safety outcomes in either direction.
- [x] GridIron Physics: enforce spike dead-ball/incomplete semantics and reject a spike marked as a touchdown or score.

## Hard football invariant coverage

- [x] Pass semantics: designed QB runs, interception attribution, touchdown scorer, safety conditions, and supported spike semantics in GridIron; SLC spike and unresolved fumble-recovery outcomes fail closed as `UNSUPPORTED_RULE`.
- [x] Field and down transitions: legal bounds, first down, fourth-down failure, touchdown yard cap, both directions, forward progress, out-of-bounds spot, and terminal dead-ball behavior.
- [x] Special teams: field-goal feasibility and distance-aware sampling, punt geometry, blocked-kick recovery, safety free-kick guard, and explicit unresolved outcomes. Safety free kicks remain unsupported and cannot be replaced by an ordinary kickoff.
- [x] Game state: quarter transitions, halftime possession, timeout supply, stoppages, two-minute warning, regulation ending, and the supported overtime procedure; unsupported transitions remain explicitly blocked.
- [x] Pregame eligibility and one-outcome-one-credit rules for player-level statistics, with per-seed team/player reconciliation before aggregation.
- [x] Mutation fixtures for touchdown scorer/yard cap, unresolved fumble recovery, safety, down transitions, field bounds, and dead-ball terminal behavior report typed failure classes and structured context.

## Statistical warnings, not per-play failures

- [x] Add a pinned, hash-verified, cutoff-checked warning evaluator for game and player opportunity distributions; unsupported PBP-row-volume and roster-zero comparisons remain explicit.
- [x] Preserve per-decision down, distance, field position, score, and clock in batch outputs; compare action and fourth-down choices in matched historical context cells.
- [x] Report empirical variation, within-batch correlations, and historical joint-distribution distances without per-seed historical thresholds.
- [x] Add a cutoff-pinned joint reference from nflverse PBP and score-ledger-verified E3 data; verify source keys, score differentials, and output hashes.
- [x] Add paired-seed ablations that preserve the pregame snapshot and unrelated random draws.
- [x] Extend the resumable paired-ablation runner so the opt-in QB run-style layer can be enabled in every control arm and isolated as its own matched-seed ablation; SLC defaults remain unchanged.
- [x] Add a read-only Week 8 batch auditor for all eight matchup outputs, seed ledgers, exported box scores, per-seed reconciliation, artifact hashes, and player workload tails.
- [x] Require every seed outcome row to carry a nonempty final status; shard headers remain metadata and are not treated as game outcomes. Regression test covers a ledger/report row missing status.

## Current verification

- [x] Fast-host `test_game_state` and `test_slc_outputs`: 166 tests passed, including the return-TD and scrimmage-TD regressions.
- [x] Replayed formerly failing seed 1668 on the fast host: 1/1 valid game with box-score export and no accounting error.
- [x] Joint-reference producer and evaluator fixtures cover key parity, score differential, source immutability, hash pinning, historical joint distances, situational action distances, and missing-stat coverage.
- [x] Exported the 2022-2025 joint reference: 1,087 games, 2,174 team-games, 188,282 key-matched regular-season PBP rows, and zero score-differential mismatches.
- [x] Local SLC invariant/reconciliation suites: 183 tests passed, including typed failure envelopes and overtime touchdown cases.
- [x] SLC reducer and failure-context regression suites: 64 tests passed after incomplete-pass and blocked-kick next-snap mutations.
- [x] Paired-stream, ablation-ledger, transition, full-game, seed-ledger, box-score, and version suites: 242 tests passed; batch and paired-evaluator CLI help and Python compilation passed.
- [x] Paired clock hazard/runoff isolation plus transition/full-game/version regressions: 241 tests passed; Python compilation and `git diff --check` passed.
- [x] Rebuilt the Model D OOB support using full 2022–2024 Weeks 1–18 training and the 2025 holdout. The 815-game source window excludes six development games and fits 103,072 plays; support is 1,774 `oob_snap` and 7,452 `oob_ready`. The earlier v2 counts (485/2,132) were Weeks 1–5 only and are superseded by the full-season v3 review. The report splits Q4's model bucket at the exact 300-second policy boundary; the clock replay suite passes 11 tests.
- [x] Frozen Week 8 SLC integration rush-attempt assertion now includes attributed lost-fumble carries; the focused reconciliation test passed.
- [x] Local SLC hard-invariant, state, box-score, integration, historical-evaluation, and paired-ablation suites: 307 tests passed.
- [x] GridIron Physics `npm run test:autonomous` passed, including perception, kneel, spike, rule mutations, acceptance fixtures, and the batch legality gate.
- [x] `git diff --check` passed in both repositories.
- [x] Full-game SLC integration: 7 tests passed on the frozen Week 8 test fixture.
- [x] Football Realism Assertion Suite v1 sections A through G are implemented and covered by the listed deterministic and historical-evaluation tests.
- [x] Current research-branch regression verification: full NFL-sequence discovery passed 945 tests with 3 skipped using `/root/legendarypicks/backend/venv/bin/python`, which includes the required `pyarrow` and `pytz` dependencies.
- [x] Completed the corrected 300-seed full-game E2/Model D comparison against 2025: 296/298 seeds reached regulation, with 140/136 legally complete games and 4/2 blocked games; the regulation-reached play-volume gaps remain +20.1%/+19.3%. The review preserves the separate denominators and event/runoff breakdown in `docs/research/e3/clock-d-games-2025-holdout-train-2022-2024-v2/REVIEW.md`.
- [x] The paired-ablation matrix's QB-style control/ablation configuration passed its focused 25-test suite; runner and test modules compile, CLI exposes the opt-in switch, and `git diff --check` passes.
- [x] Week 8 batch-audit fixtures cover complete and blocked seeds, missing seed detection, failed reconciliation, shard allocation, and historical record-exceedance reporting; 4 focused tests passed.
- [x] Extended player-share validation to match SLC's position-conditioned share groups, game-level offensive participation eligibility, hash-pinned nflverse inputs, and the exact model position map. Three chronological folds (2022→2023, 2023→2024, 2024→2025) repeatedly find excess share variance for RB carries and WR targets; QB-carry likelihood gains are negligible. No default calibration was changed. The focused share suites pass 45 tests.
- [x] Fit and evaluate a pooled concentration candidate on 2022–2024 and untouched 2025. It retains the RB-carry and WR-target likelihood gains but still predicts 1.77× and 1.40× the observed share variance, respectively; SLC defaults remain unchanged. Results are in `docs/research/share-distribution-holdout-2026-10-31/REVIEW.md` and the pooled JSON artifact.
- [x] Audit completion-yard mismatches in the read-only source DB for 2010–2025: 168 unequal passer/receiver records, of which 167 have lateral evidence; the sole non-lateral mismatch is `2022_16_LAC_IND` play 3371 (13 passing yards, 12 receiving yards). Exclude inconsistent single-receiver completions from SLC's source pool, retain source IDs and yardages in the run manifest, and keep a hard per-play assertion with richer sampled-yardage failure context. Regression tests cover the observed row and filter manifest.
- [x] Focused player-share and source-row-filter validation: 113 tests passed across the share, playcall, SLC invariant, and engine-manifest modules; Python compilation and `git diff --check` passed.
- [x] Blocked-kick geometry with a missing state returns the explicit `blocked_kick_geometry_state_missing` result and records the `state_missing` diagnostic category; the regression test reproduced the prior `UnboundLocalError`, then all 176 `test_game_state.py` tests passed. Fix is commit `0006bb0f`.
- [x] Replayed LAC–LA seeds 196 and 344 with the source-yardage filter at `f1c82e55`; both are valid regulation games and both exported box scores reconcile. The original run rows remain unchanged. The six purported statusless ledger records are the six shard headers; seed outcomes store status at `outcome.status`. Recovery outputs and hashes are committed at `2c64751e` in `docs/research/slc-week8-recoveries-2026-10-31/LAC_LA/source-yardage-filter-f1c82e55/`.

- [ ] CLE–PIT failed-seed replay after the no-play overtime fix is deferred per user instruction: do not rerun CLE–PIT. Preserve its existing outputs and the separate 5,639-row partial attempt.
- [ ] Run the full same-seed player-workload ablation matrix on the pinned ARI–DAL inputs, including `qb_run_role_style`; report per-player and team mean, spread, zero rates, quantiles, and record-exceedance changes before selecting calibration updates.
- [ ] Refit player opportunity and workload-dependent substitution behavior from cutoff-safe historical benchmarks; validate team volume, player share, QB run role, and player-conditioned yards separately without hard caps. The pooled concentration candidate confirms excess dispersion for RB carries and WR targets; a full paired simulation ablation, role/game-state-conditioned candidate, and untouched follow-up comparison are still required before changing defaults.
- [ ] Run the Week 8 batch auditor against all eight target matchups after transfer: completed IND–JAX and KC–DEN plus the six current runs. Require all 80,000 requested seeds and their box-score sidecars to be accounted for before publishing aggregates.
- [ ] Improve Model D quarter-end hazards: the refreshed 2025 holdout still has 4.31% premature and 92.21% missed quarter endings across 15,700 eligible quarter-replicates.
- [ ] Complete the six remaining Week 8 10K matchups with box-score export: `LAC_LA`, `LV_NYJ`, `MIN_DET`, `NE_MIA`, `PHI_WAS`, and `TEN_CIN`. Persistent run `research-8b7d5a2e-2026-10-31` is active on the fast host, pinned to source commit `8b7d5a2e`; at the latest check all six LAC–LA workers were active at roughly 500–750 of 1,666–1,667 seeds. Worker 01 had logged the two known source-yardage errors; both pass as separate filtered replays at `f1c82e55`, while the original error rows remain preserved. No 10K from this six-matchup run has completed yet. Keep CLE–PIT excluded and preserve all outputs.

Never drop a failed seed, silently repair its result, or count it as a valid complete game.
