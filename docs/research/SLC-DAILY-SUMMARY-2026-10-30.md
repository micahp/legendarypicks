# SLC work summary — 2026-10-30

**Branch:** `research/slc-player-workload-calibration-2026-10-30`
**Code pushed through:** `3265c5fa` (`Test zero-weight backoff fallback`)
**Scope:** SLC football-realism assertions, workload calibration evidence, the separate Model D clock replay, and the remaining Week 8 matchup runs.

## Completed and published

- Resolved the 101 recurring CLE–PIT field-goal period-transition blockers. The fixes preserve series state across quarter boundaries, use audited runoff for period expiration, correct false fourth-down turnovers, and retain blocked-kick evidence. The follow-up also excludes unsupported lateral outcomes while preserving their participant and yardage evidence.
- Added and exercised hard football-state, participation, box-score, field-goal, and overtime checks. A completed overtime tie is included in outcome distributions; a tie at regulation end is not treated as a completed game.
- Built cutoff-safe player-workload references from 2022–2024 training data, 2025 holdout data, 2022–2025 multi-season data, and 2026 Weeks 1–7 target data. The tables include player and position distributions, situational use, dated archetype examples, and source/output hashes. V3 reports QB sneaks as unavailable because the source has no structured sneak field; the residual QB-run category is not mislabeled as designed runs.
- Versioned the football-realism bumper configuration. Historical records are statistical alerts, not legality caps; impossible state transitions remain hard failures. It also records the field-goal and punt policy boundaries and forbids silent clipping or deletion of failed seeds.
- Audited the frozen ARI–DAL 10K without changing or rerunning it. Its 9,994 completed games include 11 overtime ties; six games remain blocked. The decisive-game winner denominator is 9,983. The audit records exact seeds for record exceedances, including Williams at 54 carries and 300 rushing yards, Wilson at 36 targets and 23 receptions, Pickens at 32 targets, Brissett at 147 rushing yards, and Knight at 42 carries. Brissett exceeded 50 rushing yards in 1,387 of 9,994 games.
- Traced the ARI–DAL backup-QB participation defect: backup QBs received 10,440 carries, 35,170 rushing yards, and 351 targets without a recorded entry/substitution mechanism. The serializer now derives QB1 from frozen depth and availability and exports unknown starter status as `null`, rather than falsely defaulting it to `false`. The archived run remains immutable.
- Added an opt-in QB run-role style layer and evaluated it on 2025 holdout and 2026 Weeks 1–7. Brier point estimates improved, but clustered intervals include zero; the layer remains experimental pending paired full-game evaluation.
- Kept Model D event-clock replay separate from the SLC game batch. The 2022–2024 training review records 485 `oob_snap` and 2,132 `oob_ready` examples before censoring; 2025 holdout short-runoff rates are close to observed. Quarter-end hazards remain poorly calibrated (4.71% premature and 91.99% missed in the reported evaluation), so this is not a claim that clock calibration is complete.
- Added the score-clock-only paired ablation switch and a resumable paired-seed ablation-matrix runner. The runner uses matched seeds, box-score exports, immutable manifests, per-worker logs, and paired player/team summaries. It has not yet been run because the fast host is assigned to the Week 8 matchup batch.
- Full-suite verification exposed an archival smoke-gate count that assumed only one disabled layer, plus a sampler crash when every conditioned outcome weight was zero. The smoke gate now compares against the profile's enabled layer set. When outcome modifiers zero every event, the sampler falls back to the base distribution within the already-selected intent and records that fallback in the decision trace.
- Added a dedicated backoff-path regression for the all-zero case, verifying that it retains the selected dropback intent and emits the explicit fallback marker.

The ARI–DAL report explicitly notes that archived artifacts do not retain every play-level participant-selection trace. Its reconstructed game-level shares are not presented as a replay of the original individual selections. A five-yard receiving-source reconciliation discrepancy is also documented in the benchmark artifact.

## Week 8 10K run status

- CLE–PIT is excluded from the replacement launcher, per instruction. A separate interrupted CLE–PIT attempt left 5,639 partial seed-ledger rows and six box-score sidecars; those files were preserved and are not being resumed or overwritten.
- The replacement launcher targets the eight remaining matchups, in sequence: `IND_JAX`, `KC_DEN`, `LAC_LA`, `LV_NYJ`, `MIN_DET`, `NE_MIA`, `PHI_WAS`, and `TEN_CIN`. Each matchup is split across six shards totaling 10,000 seeds. Box-score export is enabled, and outputs are directed to the persistent run directory `/root/slc-week8-player-workload-10k-2026-10-30`.
- The fast-host shell reported IND–JAX workers 01–06 started (PIDs 874711–874716). At the latest check the SSH session remained alive, but no completion line was visible. The foreground shell was left open and untouched. The remaining seven games and the batch artifacts are therefore **not yet verified complete**.

## Verification

Using `/root/.venvs/lp-slc-a-g/bin/python`, two focused runs passed: **90 tests across nine modules** for QB participation, football and box-score assertions, QB decisions/style evaluation, workload references, and paired ablation comparison/runner behavior; plus **401 tests across 17 modules** for football invariants, game state, E1 transitions, clock replay, SLC engine/output, share and player outcomes, kicks, overtime, seed ledgers, and batch handling. Total: **491 passing tests across 26 modules**. After fixing the two failures found by full discovery, `/root/legendarypicks/backend/venv/bin/python -m unittest discover -s scripts/nfl_sequence -p 'test_*.py'` passed **934 tests with 3 skipped**. After adding the dedicated backoff regression, the affected team-outcome, blocker-resolution, and archival-comparison suites passed **24 tests**. The full 934-test discovery was not rerun after that test-only addition. `git diff --check` and focused regressions passed.

## Still open

- Verify all eight remaining 10K matchups finish, reconcile every seed and exported box score, preserve blocked/error outcomes, then publish the artifacts and matchup review.
- Run the matched-seed full-game ablation matrix after the fast host is free. This is required to quantify player-share, QB-decision, team-outcome, player-conditioned-outcome, playbook, and score-clock effects.
- Keep the QB style layer opt-in until full-game paired results support a change. Improve workload-dependent shares/substitutions and Model D quarter-end hazards using the pinned holdout data; do not clip rare legal outcomes.
- Preserve three pre-existing untracked ARI–DAL audit-output directories; they were not included in the code commits.
