# SLC context summary, 2026-10-30

## Current state

- Research checkout: `/root/lp-slc-preevent`, branch `research/slc-decision-layer-2026-10-29`, source code at `7faa8eda` (context update pending). The unrelated untracked file `docs/research/SLC-SCORING-REDZONE-DECOMPOSITION-2024-2026-10-29.json` is preserved.
- SLC remains research-only. No model defaults or parameters were promoted or retrained.
- A-G football realism assertions, the Week 8 blocker fixes, and the audited out-of-bounds clock policy are on this SLC branch. The fast-host checkout and current pilot use source commit `7faa8eda`.
- The completed 10K batch is one matchup only: CLE at PIT. Six workers are seed shards of that same frozen matchup, not six separate matchups. CAR at GB was an earlier separate run. The next lexicographic Week 8 matchup is ARI at DAL.
- The CLE-PIT report exposed 101 recurring blocked field-goal period-transition cases. The transition fix is now committed and pushed; an ARI-DAL 100-seed diagnostic is in progress on the fast host before any 10K batch.

## Work since the 2026-10-29 context summary

### Assertions and branch integration

- Merged the A-G Football Realism Assertion Suite v1 into this SLC research branch in `ba655cc4` (the earlier isolated assertion commit is `6ec85af8`). The unchanged TODO is [TODO-FOOTBALL-REALISM-ASSERTIONS-2026-10-30.md](../TODO-FOOTBALL-REALISM-ASSERTIONS-2026-10-30.md).
- The assertion commit adds deterministic football, clock, drive, field-goal, box-score, and batch checks; historical joint and situational references; and paired-random-stream support. Statistical realism remains warnings, separate from hard illegal-state failures.
- Merged Week 8 blocker work from `research/slc-week8-missing-10k-2026-10-29` at `c1011ea8` (source fix `81fa84ed`). It includes audited blocked-kick inputs and geometry, safety free-kick boundaries, scramble backoff, and associated game-state and play-call handling.
- Follow-up review of the merged engine found and fixed two field-goal issues: recompute feasibility at the current field spot (`876b7f21`), and apply kick eligibility to the final sampled outcomes without breaking scramble backoff (`bc372975`).
- The 101 CLE-PIT period-transition blockers were addressed in `101725c9`. Q1/Q3 terminal `period_expired` source rows are excluded; live outcomes preserve the series across the change of ends. Q2/Q4 period-expired outcomes are admitted only when audited runoff can reach the simulated clock and resolve by expiring the period. The commit also corrects false fourth-down turnover assertions and permits selected kick actions to resolve as blocked kicks.
- A follow-up commit, `6bc3e76a`, preserves current-state field-goal feasibility evidence on sampled blocked kicks.
- The v2 pilot exposed two completion-yardage failures from the same legal completed-pass-with-lateral source row (`2022_18_NYJ_MIA`, play 3723). The row carries −20 passing yards, −13 receiving yards for the first receiver, and −4 for a lateral receiver; SLC did not model the lateral participant.
- Commit `7faa8eda` preserves lateral identity and yards in sampled evidence, classifies any leaked lateral outcome as `UNSUPPORTED_RULE`, and excludes unmodeled lateral source rows from pregame participant pools and fallback pools. The decision ledger records this source filter. Completion-yardage reconciliation remains a hard check.
- The fast-host focused gate passed 281 tests after `7faa8eda`, covering SLC playcall and football invariants, game state, E1 transitions, clock logic, and cutoff-safe reference loading. The period-transition change also passed 56 focused tests before the later additions.
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

### ARI-DAL diagnostic and next batch

- The fast host uses source `7faa8eda`. Repo: `/root/lp-slc-week8-feasibility-run`. Persistent DB: `/root/slc-week8-missing-10k-2026-10-29/data/simulation-input.sqlite`. Runtime: `/root/slc-week1-7/.venv/bin/python`.
- ARI-DAL uses frozen snapshot `2026_08_ARI_DAL.json`, as-of `2026-10-29T00:02:21Z`, and the same full-stack options and five blocker fixes recorded in the CLE-PIT run. The pilot and subsequent batch must retain `--export-boxscores`.
- The original 100-seed pilot v1 remains diagnostic evidence at `/root/slc-week8-missing-10k-2026-10-29/artifacts/ARI_DAL/pilot-100-v1-full-stack-2026-10-30/` (PID 847801).
- The v2 100-seed pilot completed at `/root/slc-week8-missing-10k-2026-10-29/artifacts/ARI_DAL/pilot-100-v2-period-transition-2026-10-30/`. It has 100 unique seed rows: 84 regulation completions, 4 overtime completions, 10 validation errors, 2 simulation errors, and zero blocked outcomes. The 10 validation errors are missing feasibility evidence because the run used pre-`6bc3e76a` code. The other two are the lateral source-row mismatch fixed in `7faa8eda`. All 88 valid games reconciled; boxscore export was enabled and contains 100 game rows plus a manifest.
- The v3 100-seed ARI-DAL pilot is running as PID 851177 at `/root/slc-week8-missing-10k-2026-10-29/artifacts/ARI_DAL/pilot-100-v3-lateral-source-filter-2026-10-30/`. It uses source `7faa8eda`, frozen snapshot `2026_08_ARI_DAL.json`, `v1_full_stack`, all five blocker fixes, and `--export-boxscores`. Persistent `pilot.json`, `.log`, `.pid`, seed ledger, and boxscore sidecar are under that directory. Preserve tmux shell `shell:0.0`.
- After v3 completes, inspect all seed outcomes, blockers, error classes, roster traces, and boxscore status/reconciliation. If the pilot has zero errors and no material blockers, run ARI-DAL 10K with six persistent, non-overlapping shards: 1–1,667; 1,668–3,334; 3,335–5,001; 5,002–6,668; 6,669–8,334; 8,335–10,000. Keep `--export-boxscores` enabled and do not close the SSH tmux shell.

## Remaining limitations

- The CLE-PIT output has 106 explicit blocked outcomes. Commit `101725c9` addresses the 101 repeated period-transition field-goal blockers (60 `blocked_kick_period_end_not_reached:field_goal`, 20 `blocked_kick_period_expired_next_possession_unresolved:field_goal:Q1`, and 21 Q3 instances). The ARI-DAL v2 pilot recorded zero blockers. Remaining blocked kick/timeout cases must stay explicit and be reviewed from v3 and the 10K artifacts.
- The 10K CLE-PIT distribution does not establish matchup-general calibration. Per-game hard assertions and statistical distribution checks remain separate.
- No Gridiron Physics perception or kneel fixes were made in this SLC task.
- The pregame-batch CLI test path issue above is unresolved and should be handled separately if that module is required in future gates.
