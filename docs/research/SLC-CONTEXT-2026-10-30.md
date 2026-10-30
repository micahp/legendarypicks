# SLC context summary, 2026-10-30

## Current state

- Research checkout: `/root/lp-slc-preevent`, branch `research/slc-decision-layer-2026-10-29`. Before this context note, local HEAD and origin were both `bc372975`; no source changes were pending. The unrelated untracked file `docs/research/SLC-SCORING-REDZONE-DECOMPOSITION-2024-2026-10-29.json` was preserved.
- SLC remains research-only. No model defaults or parameters were promoted or retrained.
- A-G football realism assertions, the Week 8 blocker fixes, and the audited out-of-bounds clock policy are on this SLC branch. The fast host has the same source commit before this note and the integrated focused suite passed there.
- The completed 10K batch is one matchup only: CLE at PIT. Six workers are seed shards of that same frozen matchup, not six separate matchups. CAR at GB was an earlier separate run. The next lexicographic Week 8 matchup is ARI at DAL.
- The CLE-PIT report exposed 101 recurring blocked field-goal period-transition cases. Resolve the state transition with the NFL rules and clock fixtures before starting the next 10K batch.

## Work since the 2026-10-29 context summary

### Assertions and branch integration

- Merged the A-G Football Realism Assertion Suite v1 into this SLC research branch in `ba655cc4` (the earlier isolated assertion commit is `6ec85af8`). The unchanged TODO is [TODO-FOOTBALL-REALISM-ASSERTIONS-2026-10-30.md](../TODO-FOOTBALL-REALISM-ASSERTIONS-2026-10-30.md).
- The assertion commit adds deterministic football, clock, drive, field-goal, box-score, and batch checks; historical joint and situational references; and paired-random-stream support. Statistical realism remains warnings, separate from hard illegal-state failures.
- Merged Week 8 blocker work from `research/slc-week8-missing-10k-2026-10-29` at `c1011ea8` (source fix `81fa84ed`). It includes audited blocked-kick inputs and geometry, safety free-kick boundaries, scramble backoff, and associated game-state and play-call handling.
- Follow-up review of the merged engine found and fixed two field-goal issues: recompute feasibility at the current field spot (`876b7f21`), and apply kick eligibility to the final sampled outcomes without breaking scramble backoff (`bc372975`).
- The 2026-10-30 focused integrated suite on the fast host passed 276 tests with 7 skipped. It covered game state, QB decisions, SLC outputs, blocker resolution, football invariants, box-score invariants, engine/integration, playcalling, and clock logic. A separate path-dependent pregame-batch CLI test could not run because it refers to absent `/root/legendarypicks/backend/data/picks.dev.db`; the simulation's pinned input database exists at the run path below.

### Event-driven clock model

- Restored the event-driven out-of-bounds clock restart policy in `d7f8cc40`, preserving paired-random-stream support. Q2 plays at or after the two-minute warning restart on the next snap; Q4 plays strictly inside the final five minutes restart on the next snap; other supported OOB plays use the ready signal, subject to turnover, incompletion, score, and kick precedence.
- Added the reproducible OOB audit. It covered 16,269 historical OOB rows; among 791 Q4 observations from 2:01 through 4:59, 731 were classified for snap restart. The audited clock implementation hash is `1b2cb162b44498fa2e71012803648cd156c00d0eb3942f2d5471fb250881dbc7`. The focused clock suite passed 19 tests, and the clock tests are included in the 276-test integrated result.
- This is an event-clock policy correction, not evidence that the whole scoring model is calibrated.

### Completed CLE-PIT 10K run and report

- Artifacts and report were committed and pushed to `research/slc-10k-results-2026-10-30`: artifact commit `db9cedd1`, report commit `532aff41`.
- Report: [CLE-PIT 10K results](https://github.com/micahp/legendarypicks/blob/research/slc-10k-results-2026-10-30/docs/reports/slc-week8-10k-2026-10-30/CLE_PIT/RESULTS.md). Raw outputs, seed ledgers, boxscores, logs, and checksums are in the adjacent `outputs/parallel-6-offensive-td-classified-fixed-2026-10-30/` directory. All 26 files listed in `SHA256SUMS.txt` passed verification after pulling locally.
- One frozen matchup, `2026_08_CLE_PIT`, 10,000 unique seeds across six contiguous, non-overlapping worker shards. Boxscore export was enabled; 10,000 game records were present and configured reconciliation passed for every record.
- Outcomes: 9,494 regulation completions, 400 overtime completions, 106 explicitly blocked games, and zero simulation errors. The 106 unresolved games remain blocked rather than being rewritten as completed.
- The report includes score and player/team summaries, blocker counts, configuration and source hashes, and the dirty producer-checkout caveat. This is a descriptive distribution for one frozen matchup, not a calibration result or paired comparison with CAR-GB.

### Next matchup batch

- On the fast host, the updated source branch is `research/slc-decision-layer-2026-10-29`; the source was pulled through `bc372975`. Repo: `/root/lp-slc-week8-feasibility-run`. Persistent DB: `/root/slc-week8-missing-10k-2026-10-29/data/simulation-input.sqlite`. Runtime: `/root/slc-week1-7/.venv/bin/python`.
- ARI-DAL uses frozen snapshot `2026_08_ARI_DAL.json`, as-of `2026-10-29T00:02:21Z`, and the same full-stack options and five blocker fixes recorded in the CLE-PIT run. The pilot and subsequent batch must retain `--export-boxscores`.
- A 100-seed ARI-DAL pilot was launched on the fast host at `/root/slc-week8-missing-10k-2026-10-29/artifacts/ARI_DAL/pilot-100-v1-full-stack-2026-10-30/`, with PID 847801 and persistent `pilot.log`, `pilot.pid`, and `pilot.json`. Initial preflight passed, the process was live at the last check, and available memory was 8.2 GiB. This pilot started before the 101 field-goal transition issue was isolated, so retain it as diagnostic evidence. Check its unique seeds, simulation errors, roster traces, and per-game boxscore reconciliation. Fix and test the field-goal period transitions before starting the 10,000-seed ARI-DAL batch. If the pilot is otherwise clear and the fix passes, use six disjoint seed shards covering 1 through 10,000, persistent files under the same ARI-DAL artifact root, and boxscore export. Do not close the existing SSH tmux shell `shell:0.0`.

## Remaining limitations

- The CLE-PIT output has 106 explicit blocked outcomes. The blocker fixes reduced but did not eliminate unsupported/unresolved kick and timeout cases. Keep them visible.
- Of those, 101 are the same field-goal period-transition issue: 60 `blocked_kick_period_end_not_reached:field_goal`, 20 `blocked_kick_period_expired_next_possession_unresolved:field_goal:Q1`, and 21 Q3 instances. The rules reference requires Q1/Q3 changes of ends to preserve the live game state and continue the series; the sampled blocked-kick outcome still needs a supported legal possession and spot. The current sampler/drive code refuses these paths. The detailed correction and clock regression tests are the next required work; no full next-matchup batch should run until that passes.
- The 10K CLE-PIT distribution does not establish matchup-general calibration. Per-game hard assertions and statistical distribution checks remain separate.
- No Gridiron Physics perception or kneel fixes were made in this SLC task.
- The pregame-batch CLI test path issue above is unresolved and should be handled separately if that module is required in future gates.
