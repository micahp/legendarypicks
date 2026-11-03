# Context summary, 2026-11-02: SLC v2 research

Read this first. Repo `/root/lp-slc-v1`, branch `slc-v1`. Base `a4cbb8db`, pushed head `bac9908a`. Local, unpushed edits are listed in section 6.

Participation research (section 12) is on branch `pbv1-integration-2026-11-02`, pushed head `40035a34`.

## 1. Goal and standing rules

Goal: the SLC v2 research plan, `docs/research/SLC-V2-RESEARCH-PLAN-2026-11-02.md`. Milestones M2 to M7 are in section 3.

Owner rulings, 2026-11-02:

- Hash-pinned simulation layers may change only behind disabled-by-default research flags. Each change needs a numbered freeze amendment listing every changed or new file with its hash and reason. The original freeze is never edited.
- P2 benchmark has three arms: (1) frozen v1_full_stack with Dirichlet shares (primary), (2) the existing fixed-share implementation (diagnostic), (3) the new weekly P2 model.
- Prospective 2026 forecasting: lock Week 10, then Week 11. No retrospective locks. Each game gets an immutable manifest. Outcomes are evaluated only after the game ends.
- PBV1 criterion (c) is preserved, interpreted and tested before integration. The 10-hour publication lag is not approved as universal; it needs source-specific timing evidence.
- Integrate one component at a time: PBV1, then P1 pass share, then P2 target share. Do not integrate P1 tempo, P1 go rate or P3.
- Integration must reproduce v1_full_stack exactly with the flags off (regression test), and the flags-on runs are reported per arm.
- Do not read additional sealed 2026 results to develop or select arms. Keep the holdout exposure rules. No production DB mutation, no SLC default change, no rerun of archived 10K batches, no production deployment.
- Repo rules: never push to `main` or `dev` without explicit approval for that push. Stage named files only, never `git add -A`. Commit only when asked. No em or en dashes in docs, replies or commits. No AI attribution in commits.

## 2. Owner dispositions (D8)

| Item | Disposition |
|---|---|
| PBV1 package sampler | RESEARCH ADOPT (integration pending) |
| P1 pass share | RESEARCH ADOPT (integration pending) |
| P2 target share | RESEARCH ADOPT against prior-only; full-stack comparator pending |
| P1 tempo | REJECT |
| P1 go rate | REJECT |
| P2 snap share | INCONCLUSIVE; a reconstruction from offensive snap counts may be tested as a separate experiment |
| P3 defense | REJECT as built; redesign separately |
| 2025 depth-chart loader | ADOPT as research infrastructure |

## 3. Milestone status

| Milestone | Status |
|---|---|
| M2 PBV1 sampler | Primary target (RB plus FB) passes Milestone 2 under the B0 reading of criterion (c). The SLC's RB-only target has no retrospective fold, so (c) is not evaluated for it. |
| M3 play-call ablation | A2 (situation cell model, K = 20) rejected. Worse than A0 on log loss in both folds: +0.0166 (2023), +0.0116 (2024). Amendment 1 records this. |
| M4 weekly models | P1 pass share and P2 target share built and frozen (C1, C2). P1 tempo, P1 go rate rejected. P3 rejected as built. P2 snap share inconclusive. |
| M5 integration | PBV1 hook written, flag off. Flags-off regression NOT passing (section 8). P1 and P2 hooks not written. |
| M6 prospective locks | NOT started. Lock tooling, per-game manifests and the streak-file builder are not built. Week 10 has 14 games, all unplayed on 2026-11-02. |
| M7 decisions | Decision ledger committed (`SLC-V2-M4-M7-DECISIONS-2026-11-02.md`). |

## 4. What was done on 2026-11-02

1. Confirmed the flags-off baseline: `v1_full_stack`, Week 8 snapshot `2026_08_KC_DEN`, seeds 1 to 3, 3 of 3 valid games, 0 regulation ties. Output JSON SHA-256 `0145bc4440e66674a0bf61e4578f65ec04e7a349244fb136fb00b236cf005082`, per-seed rows SHA-256 `f22f120078f6882eb9819d928a1cbfcbcdba0ac20bb0b45b337dd6e2073ada93`. Both are in the session scratchpad, not in the repo.
2. Checked how personnel is used. It is recorded in the decision row (`slc_playcall.py`) and not read by any outcome rule. Outcome matching in `v1_full_stack` uses formation only (`slc_playcall.py`, the formation match). So a personnel hook changes labels, not simulated plays.
3. Exported the PBV1 training table from the same population and filters as the frozen evaluation: 133,262 scrimmage plays, seasons 2022 to 2025 (33,592 / 33,761 / 33,252 / 32,657), SHA-256 `ab875384a82ea1d6472e12007d0e1f79316508861a1843730253f40253d8a993`.
4. Read the PBV1 spec, the frozen results and the report. Found that (a) criterion (c) was never scored for the RB-only target, and (b) the report's claim that (c) also holds under the B1 reading is wrong.
5. Wrote the runtime PBV1 sampler (`pbv1_package.py`) and its tests:
   - `test_pbv1_package`: reproduces the frozen fold numbers for the primary target (three folds) and the RB-only development folds (two) to 1e-5. 10 tests.
   - `test_pbv1_criterion`: criterion (c) as a verdict. 3 tests.
   - `test_pbv1_hook`: the personnel hook, flag off and on. 5 tests (local only).
6. Wrote the P1 and P2 runtime estimators (`team_pass_share.py`, `weekly_target_share.py`). They reproduce the frozen 2025 manifests exactly: 544 P1 team-games; every P2 player-prior row. 63 of 18,522 P2 position-group rows disagree because the DB players table and the gridiron players file label positions differently. Reported, not hidden.
7. Applied the PBV1 hook to `pre_event.py`, `slc_engine.py` and `simulate_pregame_batch.py` behind `--playcall-pbv1-package` (default off). Outcome rows and the ledger header gain a `research_integration` block only when the flag is on.
8. Ran the flags-off regression on the same batch command. It does not match the baseline (section 8).
9. Started a control run of the HEAD code, from a detached worktree, against the DB state at that time.
10. Committed and pushed the non-pinned set (`bac9908a`). Pinned files and the hook were held back.

## 5. Results on record

PBV1, K = 20, frozen results (`docs/research/pbv1-sampler-2026-11-02/outputs/pbv1_results.json`):

| Target (frozen name) | Table column | Fold | Gain over B0 (95% CI) | Gap to B1 | Unsupported sampler / B1 |
|---|---|---|---|---|---|
| `package` (RB plus FB, primary) | `package_comparable` | dev 2023 | +0.05940 (+0.05356 to +0.06515) | -0.00033 | 8 / 181 |
| `package` | `package_comparable` | dev 2024 | +0.06668 (+0.06141 to +0.07205) | -0.00037 | 4 / 71 |
| `package` | `package_comparable` | retro 2025 | +0.06905 (+0.06273 to +0.07520) | +0.00007 | 8 / 49 |
| `package_rb` (RB only, SLC code) | `package` | dev 2023 | +0.03698 (+0.03094 to +0.04281) | -0.00025 | 10 / 190 |
| `package_rb` | `package` | dev 2024 | +0.05102 (+0.04573 to +0.05640) | -0.00036 | 3 / 81 |
| `package_rb` | `package` | retro 2025 | not in the frozen results | | |

Criterion (c), quoted from `PBV1-SAMPLER-SPEC-2026-11-02.md`, section 9: "A sampler "passes" PBV1 Milestone 2 only if: (a) its log-likelihood gain over B0 is positive with a 95% CI above zero on both development folds; (b) its unsupported-combination rate is at or below the B1 rate on the same folds; and (c) the retrospective fold agrees in sign. Failure is reported as failure."

- Intended property of (c): the advantage over the marginal package distribution must not be an artifact of the development seasons.
- Reading used: the B0 comparison, the same statistic as (a). The spec does not name the comparison. Under B0 the primary target passes. Under B1 it fails, because the development gaps are negative and the retrospective gap is positive. The owner must confirm the B0 reading.

Simulator finding: personnel does not reach outcomes in `v1_full_stack` (section 4, item 2). The PBV1 hook therefore changes the recorded label only, unless personnel is added to the outcome match, which is a model change needing a decision.

## 6. Repo state

Pushed in `bac9908a` (46 files, no pinned file):

- Runtime: `scripts/nfl_sequence/pbv1_package.py`, `team_pass_share.py`, `weekly_target_share.py`, and their tests `test_pbv1_package.py`, `test_pbv1_criterion.py`, `test_team_pass_share.py`, `test_weekly_target_share.py`.
- Research record: `docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md`; `pbv1-sampler-2026-11-02/` (evaluation, outputs, report); `pbv1-package-integration-2026-11-02/` (export script, training CSV, manifest); `slc-v2-p1-team-2026-11-02/`; `slc-v2-p2-usage-2026-11-02/`; `slc-v2-depth-adapter-2026-11-02/`; `SLC-V2-M6-FREEZE-2026-11-02.md`; `SLC-V2-M4-M7-DECISIONS-2026-11-02.md`; `SLC-V2-TIME-SAFE-AVAILABILITY-MATRIX-2026-11-02.md`; `PLAYCALL-M3-FREEZE-AMENDMENT-1-2026-11-02.md` and its folder.

Local, NOT pushed:

- Pinned edits: `pre_event.py`, `slc_engine.py`, `simulate_pregame_batch.py` (PBV1 hook, default off).
- `scripts/nfl_sequence/test_pbv1_hook.py` (5 tests, pass).
- `docs/research/PLAYCALL-M5-FREEZE-AMENDMENT-2-2026-11-02.md` (draft; the regression rows are PENDING).
- `docs/research/SLC-V2-WEEKLY-MATCHUP-DATA-INVENTORY-2026-11-02.md`: two lines were added before this session. Not my change; not committed.

Hashes, HEAD to amended (listed in amendment 2):

| File | HEAD (frozen) | Amended (working tree) |
|---|---|---|
| `pre_event.py` | `635c9286…58f8` | `f5b79276…5601` |
| `slc_engine.py` | `e0dda6e4…de29` | `3504fa4c…04df` |
| `simulate_pregame_batch.py` | `bd2f1f1e…52ab` | `57d031b7…55b9` |
| `slc_playcall.py` | `0cb9eecf…f2` | unchanged |

Full hashes are in `PLAYCALL-M5-FREEZE-AMENDMENT-2-2026-11-02.md`.

## 7. Verification

- `cd scripts/nfl_sequence && python3 -m unittest test_pbv1_package test_pbv1_criterion test_team_pass_share test_weekly_target_share`: all pass (run after the last `pbv1_package.py` edit, before the push).
- `python3 -m unittest test_pbv1_hook`: 5 pass (local).
- Flags-off regression: NOT passing (section 8).
- No flags-on run has been made.
- No 2026 outcome was compared. The smokes used Week 8 pre-game inputs only.

## 8. Open problems

1. **Flags-off regression does not match the baseline.** Per-seed outcomes differ (for example seed 1, home points 44 against 36), the decision count differs (150 against 156), and `observed_reference_sha256` changed from `63e85483…` to `36f5281a…`. The reference hash is computed from DB rows. The dev DB `/root/legendarypicks/backend/data/picks.dev.db` was modified at 14:49:11 (during the flags-off run) and again at 14:50:10. The writer is unknown. Either the DB moved or the code edits changed behaviour; the HEAD control run decides which.
   - Control: `git worktree add --detach` at `scratchpad/headwt` (HEAD), batch output `scratchpad/regress/head_control_seeds1-3.json`. Still running at the time of writing. Remove the worktree after the comparison (`git worktree remove`).
   - Comparison script: `scratchpad/regress/compare_runs.py`.
2. **Pushed error in `pbv1-sampler-2026-11-02/REPORT.md`.** Section on criterion (c) says the retrospective fold agrees in sign under the B1 reading. It does not. The correction is in the unpushed amendment only. Needs a follow-up commit to the report.
3. **The DB cannot be snapshotted on this box.** It is 3.6 GB; the root disk is 99 percent full with about 5 GB free. Simulations are not reproducible against a fixed input until a read snapshot exists or the writer is identified.
4. **`run_slc_game.py` refuses `v1_full_stack`.** `player_shares_for` returns true when Dirichlet is requested, so `validate_engine_layers` sees the fixed-share layer on. The batch runner is not affected. Not fixed.
5. **Baseline evidence is only in the scratchpad.** `scratchpad/baseline/` is not in the repo. Copy the baseline JSON and per-seed rows into `docs/research/` before the regression is cited.
6. **P1 and P2 hooks not written.** P1 would be a log-odds shift in `slc_playcall.sample()`. P2 would replace the receiving base in the Dirichlet branch of `slc_engine.py`.
7. **Prospective lock tooling not built.** Week 10 starts Thursday 2026-11-12. The early horizon (Tuesday 2026-11-10, 12:00 ET) is judged unsupported because a full simulation cannot finish before it. The final horizon is kickoff minus 90 minutes. Each lock needs its own snapshot, arms, immutable manifest and as-fetched evidence from DB ingest timestamps. The streak file (`wl-streaks-2026-10-29.json`) predates Weeks 9 and 10 and must be rebuilt as of each lock; no builder exists yet.

## 9. Decisions needed from the owner

1. Authorize one retrospective RB-only fold for 2025 (scored once, the spec's pre-registered fold definition, reported whatever the result), or accept the RB-only integration as research-only with criterion (c) open.
2. Confirm the B0 reading of criterion (c).
3. Should personnel condition the outcome match (a model change) or should PBV1 stay label-only?
4. Who writes to `picks.dev.db`? The dev server is not to be restarted by me.
5. Approve the Week 10 lock design and the early-horizon decision before the first lock.

## 10. Next steps, in order

1. Compare the HEAD control with the flags-off run. If they match, the pinned edits are not the cause: finish amendment 2 (fill the regression rows) and push the hook commit, then run the flags-on comparison. If they do not match, find the cause before pushing anything pinned.
2. Push the correction to `REPORT.md`.
3. Copy the baseline evidence into `docs/research/`.
4. Build the Week 10 lock tooling and freeze the code before the first lock. This is the schedule risk.
5. Write P1 and P2 hooks, each behind its own flag, with its own amendment.

## 11. Commands

Tests (from `scripts/nfl_sequence`):

    python3 -m unittest test_pbv1_package test_pbv1_criterion test_team_pass_share test_weekly_target_share
    python3 -m unittest test_pbv1_hook

Baseline batch (about 7 minutes; reference build about 6 minutes; about 1.3 GB RSS):

    python3 simulate_pregame_batch.py --snapshot-file docs/research/slc-week8-2026/snapshots/2026_08_KC_DEN.json --slc-profile v1_full_stack --playcall-artifact docs/research/SLC-PLAYCALL-ARTIFACT-v1.json --playcall-streak-file docs/research/slc-week8-2026/wl-streaks-2026-10-29.json --games 3 --seed-start 1 --db /root/legendarypicks/backend/data/picks.dev.db --progress-every 1 --max-simulation-errors 0 --out <out.json>

Resources: 5.8 GB RAM (about 3 GB available during runs), root disk 99 percent full. One batch at a time.

## 12. Participation research, later on 2026-11-02

Scope: the substitution and participation research in `docs/research/participation-model-2026-11-02/`. Research only. No SLC wiring, no default change, nothing integrated into `scripts/nfl_sequence/`. Holdout is 2025; fits use 2022 to 2024 unless stated.

Commits, in order (all on `pbv1-integration-2026-11-02`):

- `1e1c7244` root cause of the substitution gap, candidates scored.
- `ec44fe99`, `f9583cc7` availability gate: ACT bench, zero-usage arm.
- `67c340d0` feasibility-constrained substitutions; postseason roster rows added (the REG-only filter had emptied every playoff bench).
- `e3bf96b2` removed the two gate outputs built with that bug.
- `838ad184` season-primary classes for pools; observed snaps keep their listed position.
- `07130a51` position prior re-derived from season labels (prior check passes to 1e-16).
- `b8c568cd` cutoff-safe individual substitution evaluation.
- `0d9b066e` player identity model (conditional logit).
- `f3653c5c` snap share, depth roles, touch-conditioned leave rates.
- `23b211a4` touch analysis: outcome filter removed.
- `40035a34` 2022 position reconstruction from PFR snap counts; snap-share bug fix.

Results, 2025 holdout:

- Gate, forced arm, clean pairs (observed 1.342 entries per pair): JD feasible 1.313 (gap 0.029); B0 feasible 1.182 (gap 0.160); JD ungated 1.326. Feasible arms have zero unfillable steps. Pools use full-season 2025 labels, so this is a retrospective oracle.
- Cutoff-safe individual substitutions (teacher-forced, 33,905 transitions): for transitions with at least one real entrant, exact IN match is persistence 0.160, rate-only 0.125, B0 0.110, JD 0.086. Persistence precision is 0.70; JD precision is 0.38, JD recall 0.39. Unreachable entrants 0.9%. The role and snap-label disagree on 91 of 46,857 entrant snaps (0.19%).
- Identity model (conditional logit, trained 2022 to 2024, pre-game features): entrant recall 0.783 against recency 0.763 and share 0.733; exact set 0.745 against 0.722. Leaver recall 0.837 against 0.825 for lowest share. 520 holdout entrants (1.1%) are outside the pool and excluded.
- Snap share (overall, not package-conditional, cutoff-safe, reconstructed groups): 2023 MSE 0.0689 against group 0.1047; 2024 0.0699 against 0.1057; 2025 0.0702 against 0.1030; prior-only 2025 0.1085. QB is worse than the group baseline in 2025 (0.091 against 0.066). About 38% of targets have no prior-season group on the same team.
- Depth roles: cover 97.7% of 2025 WR and TE targets. Role offsets lower weeks 10 to 18 MSE from 0.07410 to 0.07345, about 1%. The depth file has only the 3WR 1TE offense group, so RB and OL roles are not available.
- Touch and play type (holdout log-loss per pair): class and stint 0.562504; with touch 0.561107; with touch and play type 0.560470. Small effect.
- 2022 positions: reconstructed from `nfl_hist_snap_counts` (PFR) joined to GSIS through `nfl_hist_player_ids`, with LAR and WSH mapped to LA and WAS. Matched agreement with the 2023 to 2025 on-field labels: WR 99.97%, TE 99.96%, RB 98.95%, FB 96.6%.

Bugs found and fixed today (earlier outputs are superseded):

- The REG-only roster filter emptied every playoff bench in the gated arms.
- Snap share zipped IDs with the blank 2022 position list, which dropped every 2022 snap. The 2023 numbers reported before `40035a34` were wrong.
- The touch analysis conditioned on the next snap's grouping, which is an outcome. Removed in `23b211a4`.
- Observed snaps were rewritten with primary classes (WR snaps became TE). Fixed in `838ad184`.
- PFR team codes LAR and WSH did not match the participation codes LA and WAS. Fixed in the reconstruction.

Open problems:

1. 2022 skill labels are kept. `lineup_fit.sequences` and `touch_hazard.pairs` use `participation_labels.aligned_labels` with the PFR reconstruction (`40035a34`, `cfab760a`), guarded by `test_participation_inputs`. The workload gate (`336f34d3`) fits on 2022 to 2024 with these labels.
2. The gate's 2025 pools use full-season labels, a retrospective oracle. A forecast needs labels from games before the cutoff. The cutoff-safe evaluation exists separately.
3. The identity model is not wired into the simulator, and its entrant gain over recency is small.
4. Snap share is not package-conditional. The 2026 weekly snap counts are in the local database as `nfl_snap_counts` (nflverse, weeks 1 to 7, published `off_pct`). `nfl_hist_snap_counts` is the PFR history through 2025. Neither splits by package.
5. Depth roles cover WR and TE only.
6. Workload and fatigue are not in the simulator, and the touch effect is too small to justify a closed-loop test on its own. Carry-load and rest are not modeled.
7. Not built: regression tests (2022 coverage, leakage, Week 1, new players, deterministic output), hierarchical smoothing for sparse groups.
8. The role table in `snap_share.py` uses the season's own labels. It is descriptive and not scored, but it should be relabelled or use the prior season.
9. `players.csv` is a 2026-10-22 snapshot. The cutoff-safe paths do not use it, but the gate's default positions and the diagnose and validate scripts still do.

Decisions needed from the owner:

1. Drop or keep the leave-scaling option (`leave_beta`, default off). My recommendation is to drop it.
2. Decide whether the gate moves to cutoff-safe pools before any SLC integration.
3. Confirm whether the identity model and the depth offsets go into the candidate simulator, given the small gains.

Next steps, in order:

1. Add an on-field lineup layer to the engine before any live snap-share tracking. Today the engine emits play records with a sampled passer, rusher and receiver only.
2. Write the regression tests listed in item 7 of the open problems.
3. Build cutoff-safe pools for the gate, using only pre-game labels and the frozen depth state.
4. Verify the 2026 snap-count join (`nfl_snap_counts` to `players.nfl_gsis_id`; one player has no GSIS id) before the snap-share layer is used for a 2026 forecast.
5. Decide on the workload model only after the substitution and identity gates pass.

Later on 2026-11-02:

- Workload gate (`workload_gate.py`, `336f34d3`). It simulates 2025 team-games in free mode with the JD model and the ACT bench, and compares them with 570 observed games. Simulated starters play less than observed: RB snap share P95 is 0.61 against 0.82, and WR stint P95 is 24 against 35. Legality uses season-primary classes on both sides: observed 0.993, simulated 1.0. The leave-scaling option is default off. At beta 1, simulated legality falls to 0.930 and the RB gap does not close. Carries and targets are not simulated.
- Snap share cannot be computed from the engine yet. The engine emits play-by-play, but it samples only a passer, rusher and receiver per play, and builds no 22-player lineup and no substitutions (`game_state.py`, guard `lineups`). Live tracking needs that lineup layer first.
- Published-data scripts, uncommitted until this commit: `league_snap_share.py` (per-player snap share, season or week, from `off_pct`) and `role_snap_share.py` (WR1 to WR3, TE1 to TE3 and RB1 to RB3 by rank within each team-week; 2026 covers weeks 1 to 7).

Working tree: this section is part of the committed handoff. Other uncommitted files in the tree belong to other sessions and are not listed here.
