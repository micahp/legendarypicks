# SLC work summary — 2026-10-30

**Branch:** `research/slc-player-workload-calibration-2026-10-30`
**Latest code commit before this publication:** `dfd20800` (`research: audit Week 8 batch artifacts`)
**Scope:** SLC football-realism assertions, workload calibration evidence, the separate Model D clock replay, and the remaining Week 8 matchup runs.

## Status update — 20:52 CDT

The latest source commit, `dfd20800` (`research: audit Week 8 batch artifacts`), adds a read-only integrity and workload-tail audit for the eight matchup outputs. The earlier paired QB-style ablation runner is in `30ed3c76`; SLC defaults remain unchanged. The prior daily-summary publication is `d0eb19c3`. This update records the final event-clock diagnostic, focused verifications, and current run-monitoring limit.

## Completed and published

- Resolved the 101 recurring CLE–PIT field-goal period-transition blockers. The fixes preserve series state across quarter boundaries, use audited runoff for period expiration, correct false fourth-down turnovers, and retain blocked-kick evidence. The follow-up also excludes unsupported lateral outcomes while preserving their participant and yardage evidence.
- Added and exercised hard football-state, participation, box-score, field-goal, and overtime checks. A completed overtime tie is included in outcome distributions; a tie at regulation end is not treated as a completed game.
- Built cutoff-safe player-workload references from 2022–2024 training data, 2025 holdout data, 2022–2025 multi-season data, and 2026 Weeks 1–7 target data. The tables include player and position distributions, situational use, dated archetype examples, and source/output hashes. V3 reports QB sneaks as unavailable because the source has no structured sneak field; the residual QB-run category is not mislabeled as designed runs.
- Versioned the football-realism bumper configuration. Historical records are statistical alerts, not legality caps; impossible state transitions remain hard failures. It also records the field-goal and punt policy boundaries and forbids silent clipping or deletion of failed seeds.
- Audited the frozen ARI–DAL 10K without changing or rerunning it. Its 9,994 completed games include 11 overtime ties; six games remain blocked. The decisive-game winner denominator is 9,983. The audit records exact seeds for record exceedances, including Williams at 54 carries and 300 rushing yards, Wilson at 36 targets and 23 receptions, Pickens at 32 targets, Brissett at 147 rushing yards, and Knight at 42 carries. Brissett exceeded 50 rushing yards in 1,387 of 9,994 games.
- Traced the ARI–DAL backup-QB participation defect: backup QBs received 10,440 carries, 35,170 rushing yards, and 351 targets without a recorded entry/substitution mechanism. The serializer now derives QB1 from frozen depth and availability and exports unknown starter status as `null`, rather than falsely defaulting it to `false`. The archived run remains immutable.
- Added an opt-in QB run-role style layer and evaluated it on 2025 holdout and 2026 Weeks 1–7. Brier point estimates improved, but clustered intervals include zero; the layer remains experimental pending paired full-game evaluation.
- Kept Model D event-clock replay separate from the SLC game batch. The corrected full-window replay fits 2022–2024 Weeks 1–18 (815 source games, six development games excluded, 809 fit games, 103,072 fitted plays) and evaluates only 2025. Full-window support is 1,774 `oob_snap` and 7,452 `oob_ready` examples. The earlier v2 counts (485/2,132) and its 4.71% premature / 91.99% missed 20-replicate results came from Weeks 1–5 and are not full-season estimates; those outputs remain preserved and are superseded by the [full-season v3 review](e3/oob-policy-replay-2026-10-30/train-2022-2024-full-season-v3/REVIEW.md). In the refreshed 2025 replay, `oob_snap` short runoff is 98.6% versus 98.1% observed, and `oob_ready` is 3.7% versus 2.6%. Quarter-end hazards remain poorly calibrated (4.31% premature and 92.21% missed), so clock calibration is still open.
- Added the score-clock-only paired ablation switch and a resumable paired-seed ablation-matrix runner. The runner uses matched seeds, box-score exports, immutable manifests, per-worker logs, and paired player/team summaries. It has not yet been run because the fast host is assigned to the Week 8 matchup batch.
- Full-suite verification exposed an archival smoke-gate count that assumed only one disabled layer, plus a sampler crash when every conditioned outcome weight was zero. The smoke gate now compares against the profile's enabled layer set. When outcome modifiers zero every event, the sampler falls back to the base distribution within the already-selected intent and records that fallback in the decision trace.
- Added a dedicated backoff-path regression for the all-zero case, verifying that it retains the selected dropback intent and emits the explicit fallback marker.

The ARI–DAL report explicitly notes that archived artifacts do not retain every play-level participant-selection trace. Its reconstructed game-level shares are not presented as a replay of the original individual selections. A five-yard receiving-source reconciliation discrepancy is also documented in the benchmark artifact.

## Week 8 10K run status

- CLE–PIT is excluded from the replacement launcher, per instruction. A separate interrupted CLE–PIT attempt left 5,639 partial seed-ledger rows and six box-score sidecars; those files were preserved and are not being resumed or overwritten.
- The replacement launcher targets the eight remaining matchups, in sequence: `IND_JAX`, `KC_DEN`, `LAC_LA`, `LV_NYJ`, `MIN_DET`, `NE_MIA`, `PHI_WAS`, and `TEN_CIN`. Each matchup is split across six shards totaling 10,000 seeds. Box-score export is enabled, and outputs are directed to the persistent run directory `/root/slc-week8-player-workload-10k-2026-10-30`.
- The fast-host shell reported IND–JAX workers 01–06 started (PIDs 874711–874716). At the latest check the SSH session remained alive, but no completion line was visible. The foreground shell was left open and untouched. The remaining seven games and the batch artifacts are therefore **not yet verified complete**.

## Review outputs published in this update

- Added the three previously untracked ARI–DAL player-tail review iterations: the original audit, v2, and v4. The first two include per-seed findings plus summary and manifest JSON; v4 contains the per-seed findings CSV. Together they preserve the review outputs requested for publication, without changing the frozen 10K run artifacts.
- The latest pane check still showed the original IND–JAX worker startup and no completion evidence. A separate SSH monitor remained at its password prompt, so no new fast-host status was available; the original run shell was left open and untouched.

- Corrected the Model D OOB support window after tracing the prior 485/2,132 table to 2022–2024 Weeks 1–5. The full-season v3 report now publishes exact quarter/window counts, the Q2 120-second and Q4 300-second boundaries, censoring counts, event composition, and source/code hashes. The reported 375 completed passes are one event type within 449 Q4 `oob_snap` plays in the >120 and <300-second cell, not the total stop-class support.

## Late-day Model D findings

- Published the full-season v6 fixed-outcome replay and review. Its 2022–2024 training and 2025 holdout rows were read in a single SQLite transaction; the exact selected-row SHA-256 is `6775da6a10cf209b83c4cc542f24a875d7d0a88971c1369663ef1ffdb674ba33` (141,830 training rows and 46,452 holdout rows). The 2025 holdout has 272 games; 785 quarters have a classifiable boundary marker, replayed 20 times each for 15,700 quarter-replicates.
- In v6, Model D classified 547/15,700 quarter ends accurately (3.48%), ended early in 676 (4.31%), and missed 14,477 (92.21%); the median clock left at a missed observed boundary was 101 seconds. Matched-play clock bias was positive in every quarter (simulated clock remaining too high): Q1 +53.79 sec, Q2 +65.53, Q3 +59.80, Q4 +42.17. Broad stop-class mean runoffs were close to 2025 observations, so those averages do not explain the clock-state bias by themselves. Full results and per-file hashes are in the [v6 review](e3/oob-policy-replay-2026-10-30/train-2022-2024-full-season-v6/REVIEW.md). V4 and v5 raw iterations are retained; v6 is authoritative.
- A first paired 300-seed full-game comparison completed for E2 and Model D. Its raw per-seed statuses show E2 reached regulation in 296 games (4 blocked) and D in 298 (2 blocked); 140 E2 and 136 D games are complete including overtime ties. Among regulation-reached games, E2 averaged 148.21 plays and 23.08 regulation drives; D averaged 147.12 plays and 22.95 drives. The 2025 observed baseline is 123.36 plays and 20.11 drives per game, so Model D still overproduces about 23.76 plays/game (+19.3%) and 2.84 drives/game (+14.1%). The first run's JSON volume summary used only legally complete games for some measures; the archived per-seed CSV is the source for these corrected regulation-reached denominators.
- The corrected paired 300-seed E2/Model D rerun completed. It has 296 E2 and 298 D runs reaching regulation; 140 E2 and 136 D games are legally complete including overtime, with four and two blocked respectively. On the regulation-reached denominator, E2 averages 148.21 plays and 23.08 drives; D averages 147.12 plays and 22.95 drives, versus 2025 observed 123.36 plays and 20.11 drives. Model D cuts only 1.09 of E2's 24.85 excess plays/game and shifts plays from Q1/Q3 into Q2/Q4. The full event and paired-seed comparison is in the [corrected v2 review](e3/clock-d-games-2025-holdout-train-2022-2024-v2/REVIEW.md); Model D remains diagnostic and opt-in.

## Final event-clock diagnostic — 20:39 CDT

- Compared Model D's broad 0–120-second late-game runoff pool with finer remaining-clock buckets using the pinned 2025 holdout outcomes. The broad pool is too long for 30–60-second completed-pass and run states (observed means 11.04/9.62 seconds; Model D expected 14.64/14.04) and too short for 61–120-second states (observed 19.10/18.85; expected 15.44/16.73).
- An unsaved, diagnostic-only finer-bucket prototype reduced quarter-level clock-path bias by roughly 7–8 seconds in each quarter, and reduced missed boundary classifications from 14,477 to 14,347 of 15,700. It also increased premature endings from 676 to 815 and slightly reduced total boundary accuracy (547 to 538 correct). This is evidence of clock-bucket mixing, not a validated fix; no Model D defaults or SLC outputs were changed.
- A read-only attempt to inspect the fast-host workers from a separate SSH session was denied by the host's current authentication setup. The original launcher pane shows the six IND–JAX worker starts followed by inspection commands queued behind the foreground launcher; those commands have not produced results. No additional matchup completion or artifact status is verified, and the launcher shell remains untouched.
- At 20:42 CDT, the original SSH client process was still live and the pane remained inside the foreground launcher; the queued `ps` and artifact listing still had no results. The local host has neither the batch's simulation database nor frozen input files, so the paired player-workload ablation cannot be run locally while the fast-host batch is active. The run was not restarted or interrupted.

## Paired workload-ablation runner update

- The resumable paired-ablation runner previously validated only default-on layers. The opt-in `qb_run_role_style` could not be enabled in the control arm, so it could not be measured by the full-game paired runner.
- Added `--enable-qb-run-role-style`. It enables that layer for all control/ablation arms and adds its isolated comparison when the default layer list is used. Explicitly requesting `--layer qb_run_role_style` also enables it in the control automatically. The run manifest records the enabled optional layer. SLC's default profile and the runner's default six-layer matrix are unchanged.
- The fast host remains occupied by the Week 8 matchup batch, and the local host lacks the pinned simulation DB and matchup inputs, so no paired full-game ablation has been launched yet.

## Week 8 artifact audit readiness — 20:52 CDT

- Added `scripts/nfl_sequence/audit_week8_matchup_batch.py`. It checks the six expected worker shards per matchup, exact contiguous seed coverage, report/ledger agreement, `boxscore_export=true`, sidecar parity, consistent snapshot/config/source hashes, and passing reconciliation for every valid full game.
- The auditor preserves blocked/error seed details and reports player means, standard deviations, zero rates, P95/P99, maxima, and historical-record exceedance seeds from reconciled valid games. It writes only to a separate report path and refuses output paths inside the run root.
- Synthetic fixtures and the paired-ablation regression suite passed **13 tests**; compilation, CLI help, and `git diff --check` passed. The auditor has not run against the fast-host batch because its artifacts are not yet accessible locally.

## Verification

Using `/root/.venvs/lp-slc-a-g/bin/python`, two focused runs passed: **90 tests across nine modules** for QB participation, football and box-score assertions, QB decisions/style evaluation, workload references, and paired ablation comparison/runner behavior; plus **401 tests across 17 modules** for football invariants, game state, E1 transitions, clock replay, SLC engine/output, share and player outcomes, kicks, overtime, seed ledgers, and batch handling. Total: **491 passing tests across 26 modules**. After fixing the two failures found by full discovery, `/root/legendarypicks/backend/venv/bin/python -m unittest discover -s scripts/nfl_sequence -p 'test_*.py'` passed **934 tests with 3 skipped**. After adding the dedicated backoff regression, the affected team-outcome, blocker-resolution, and archival-comparison suites passed **24 tests**. The full 934-test discovery was not rerun after that test-only addition. In this update, the focused clock replay suite passed **11 tests**; a 20-replicate full-window Model D holdout replay completed, and an independent raw nflverse reconstruction matched all 42 support cells, 141,830 PBP keys, and 12,246 OOB-flag keys. `git diff --check` and focused regressions passed.

The continuation check also passed **61 tests** across `test_pre_event`, `test_participant_invariants`, `test_slc_outputs`, `test_paired_seed_ablation`, and `test_run_paired_seed_ablation_matrix`, covering backup-QB eligibility, box-score metadata, paired ledgers, and resumable ablation shard validation.

The runner change passed **25 tests** across `test_run_paired_seed_ablation_matrix` and `test_slc_config`; Python compilation, CLI help, and `git diff --check` also passed.

The batch auditor's four tests passed with `test_audit_week8_matchup_batch`; combined with the paired-runner module, the latest focused run passed **13 tests**.

## Still open

- Verify all eight remaining 10K matchups finish, reconcile every seed and exported box score, preserve blocked/error outcomes, then publish the artifacts and matchup review.
- Diagnose the remaining Model D quarter-end hazard errors and 19.3% excess play volume; the corrected full-game review narrows the volume gap chiefly to excess drives, but a causal layer decomposition still requires same-seed ablations.
- Run the matched-seed full-game ablation matrix after the fast host is free. This is required to quantify player-share, QB-decision, team-outcome, player-conditioned-outcome, playbook, and score-clock effects.
- Keep the QB style layer opt-in until full-game paired results support a change. Improve workload-dependent shares/substitutions and Model D quarter-end hazards using the pinned holdout data; do not clip rare legal outcomes.
- The eight-matchup run and paired ablation matrix still need fast-host completion and artifact review; do not infer completion from worker startup alone.
