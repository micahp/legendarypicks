# SLC context summary — 2026-10-31

## Current state

- Checkout: `/root/lp-slc-player-workload-2026-10-30`
- Branch: `research/slc-player-workload-calibration-2026-10-30`
- Latest published commits: `3ce6441f` (quarter-aware boxscores and run report generator) and `bcb25576` (Week 8 matchup run catalog). Both are on `origin`.
- SLC remains research-only. The frozen 10K outputs were not changed.
- The Week 8 run index is [run-index.json](slc-week8-2026/runs/run-index.json); its [README](slc-week8-2026/runs/README.md) defines the standard published run layout and status meanings.
- The most recent run audit recorded zero active Week 8 simulator processes. This summary does not claim a live fast-host check after that audit.

## Work completed today

### Quarter boxscores and automatic run reports

- Added SLC boxscore schema v3 with team and active-player statistics by quarter, quarter scoring including overtime, and drive summaries with start/end period, clock, yardline, result, yards, turnovers, and points.
- Added `scripts/nfl_sequence/render_slc_run_report.py`. It reads run directories, worker JSON/JSONL, and tar archives, then emits Markdown, JSON, and CSV reports with requested/processed counts, success/blocked/error/incomplete outcomes, block reasons and seed IDs, score means/medians, player and team usage, quarter summaries where available, and drive summaries.
- Kept older schemas readable. Reports explicitly mark unavailable quarter data instead of inferring it from final scores or rewriting frozen boxscores.
- Generated the IND–JAX report at [report.md](../reports/slc-run-reviews-2026-10-31/IND_JAX/report.md). It accounts for 10,000 seeds: 9,998 complete, two blocked, zero errors, and 12 final overtime ties. Mean/median points were IND 17.06/17, JAX 24.38/24, and combined 41.43/41. Its archived boxscores predate quarter-level exports, so quarter scoring and quarterly boxscores are unavailable for this run.

### Week 8 run organization

- Added a single catalog for all 14 Week 8 matchups at [run-index.json](slc-week8-2026/runs/run-index.json).
- New published runs belong under `docs/research/slc-week8-2026/runs/<GAME_ID>/<RUN_ID>/`, with a run header, report, summary, and outputs. Keep raw worker files in the persistent fast-host artifact root and record their paths and hashes in the index.
- Existing frozen artifacts were left where they are. The index distinguishes a completed 10K, an older-source 10K, an incomplete attempt, and no completed 10K.

### Verification

- `py_compile` passed for the changed Python modules.
- Focused output, report-generator, and football-realism tests passed: **23 tests**.
- The 14-matchup index was checked against the Week 8 snapshots; JSON parsing and `git diff --check` passed.

## Week 8 run status

Counts below distinguish complete games from blocked attempts. Blocked seeds remain in the requested 10,000-seed denominator.

| Matchup | Completed games | Blocked | Simulation errors | Current status |
|---|---:|---:|---:|---|
| ARI–DAL | 9,994 | 6 | 0 | Completed on player-workload line |
| CLE–PIT | 9,894 | 106 | 0 | Completed on player-workload line; no rerun needed for basic matchup coverage |
| IND–JAX | 9,998 | 2 | 0 | Completed on player-workload line; report published |
| KC–DEN | 9,998 | 2 | 0 | Completed on player-workload line; detailed blocker classification still needed |
| ATL–TB, BAL–BUF, CAR–GB, CHI–SEA | Earlier-source 10K exists for each | Varies | Varies | No completed 10K on the current player-workload line |
| LAC–LA, LV–NYJ, MIN–DET, NE–MIA, PHI–WAS, TEN–CIN | — | — | — | No completed 10K found |

Thus, eight matchups have a completed 10K from some source revision; six have no completed 10K at all. Ten have no completed 10K on the current player-workload line. An empty directory, pilot, smoke game, or interrupted attempt does not count as a completed 10K.

## Blockers that need diagnosis and fixes

These are unresolved outcomes, not completed-game errors. Preserve their seed records and source artifacts while investigating; do not silently repair or delete them.

### IND–JAX — 2 blocked

- Seed **5650**: `blocked_kick_no_legal_geometry:field_goal:next_snap:kicking_team`. The next-snap blocked-kick state lacks a legal observed start spot, down, and distance.
- Seed **4382**: `blocked_kick_no_legal_geometry:punt:next_snap:receiving_team`; detail is `blocked_kick_next_snap_outside_field:receiving_team`.
- A pushed fix addresses an IND–JAX goal-to-go distance issue. It does not resolve the CLE–PIT field-goal period-transition or timeout blockers below. Match the fix to the preserved seed traces before claiming either remaining IND–JAX blocker is covered.

### ARI–DAL — 6 blocked, 0 simulation errors

- 1 field-goal next-snap geometry issue.
- 4 punt next-snap geometry issues.
- 1 punt-return spot issue.
- The exact seed IDs and pre-play/decision/outcome/post-play traces still need to be extracted from the archived postrun audit and worker ledgers and added to the run review.

### CLE–PIT — 106 blocked, 0 simulation errors

- **101 field-goal period-transition blockers.**
- **3 blocked-kick spot issues.**
- **2 timeout-limit blockers.**
- A later `parallel-6-post-stat-fix` attempt was interrupted and has no final batch count; it is not a replacement result.
- Correction to earlier status notes: these 101 field-goal period-transition and two timeout blockers must be treated as unresolved. The IND–JAX goal-to-go distance fix did **not** resolve them. Verify any separate candidate fix against the preserved CLE–PIT seeds before describing the issue as fixed.

### KC–DEN — 2 blocked

- The six worker outputs account for all 10,000 requested seeds; 9,998 are complete and two are blocked, with no simulation errors.
- Their blocker reasons and exact seeds are not yet in the central catalog. Extract and report them before deciding whether a code fix is needed.

## Todo for today

1. **Close the existing blocker diagnoses.** Recover exact seed IDs and full transition evidence for ARI–DAL, CLE–PIT, and KC–DEN. For IND–JAX, retain seeds 5650 and 4382 as regression fixtures. Add a deterministic regression for each distinct failure class: field-goal period transition, blocked-kick next-snap geometry, punt-return spot, and timeout limit.
2. **Fix and verify the blocker mechanisms.** Keep the CLE–PIT 101 field-goal period-transition cases separate from IND–JAX's goal-to-go correction. Verify timeout accounting independently. Do not change the frozen runs; any rerun must use a new run ID and retain old artifacts and seed outcomes.
3. **Run the six matchups with no completed 10K:** LAC–LA, LV–NYJ, MIN–DET, NE–MIA, PHI–WAS, and TEN–CIN. Use the pinned Week 8 input snapshot, current player-workload branch, six disjoint shards totaling exactly 10,000 seeds, and `--export-boxscores`. Keep output in the persistent fast-host artifact root and do not close the tmux/SSH shell pane running the workers.
4. **Report every completed batch.** Run the report generator on each batch, preserve explicit blocked/error/incomplete counts and seed IDs, and publish its report alongside the per-run catalog entry. New runs should export schema v3 quarter scores, quarter-level team/player boxscores, and drive summaries.
5. **Update the catalog as runs finish.** Record the exact run ID, source/config/snapshot hashes, persistent raw artifact path, requested and processed seeds, final ties, blocked reasons, and report path. Keep the four older-source-only matchups clearly labeled; prioritize the six never-simulated matchups before considering newer-line reruns of ATL–TB, BAL–BUF, CAR–GB, or CHI–SEA.

## Prior context

For the broader football-realism, workload-calibration, and Model D clock work completed on 2026-10-30, see [SLC-DAILY-SUMMARY-2026-10-30.md](SLC-DAILY-SUMMARY-2026-10-30.md). This handoff supersedes its statement that the CLE–PIT period-transition blockers were resolved; the 106 blocked outcomes remain the evidence to diagnose.
