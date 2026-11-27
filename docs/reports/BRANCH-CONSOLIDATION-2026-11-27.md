# Branch consolidation sweep — 2026-11-27

Status: partial audit and integration queue. Scope: Legendary Picks remote refs, Nov 20–27 focus. Inventory enumerated 315 branch names; names do not establish creation or last-activity dates. Compared selected recent and relevant older branches against dev and model destinations. Not a comprehensive patch-ID audit; local-only worktrees, open agent sessions, active host jobs, full runtime tests, and other repositories not inspected.

## Landed without PRs
- Retention proposal: dev fast-forward `1ff146e0` from `e463a90c`; no cleanup authorization.
- Diátaxis: merge `86aaa7df` from `docs/diataxis-philosophy-2026-11-27`; retained new retention rule and canonical navigation.
- Historical GB–LAR grade bundle: merge `dbcc08b8`; exact source blobs retained, no regrading or model promotion. Report documents partial coverage and normalized-name fallback.

## Priority runtime integration queue
| Destination | Source | State / required action |
|---|---|---|
| v1-complete | feat/slc-v1-complete-implementation-2026-11-24 | Source `7f6283334bd3763c3b3e43cd0125931f33f172f5`, target `eb0564890c6abe7fb964341a3ae6842db7da84e3`: 3 ahead, 0 behind. Candidate Gridiron `2e17dadb297a001eae30f80905ff366dd73613ca`; verify actual paired repository execution, recover 26 calls and replay 35 failed games, then 300-game cohort. No full-game success claim. |
| slc-v1.6 | fix/slc-v1.6-rules-2026-11-23 | Source `cf8fd47b9ce648b1b0ad370f652ba7083432e94b`, target `8d2284b8d0325ac7c1890a7d90b74b66b0c08924`: 3 ahead / 1 behind. Preserve default box-score export and opt-in geometry filter; ensure compiler/portable runtime wiring and replay original stopped seeds; do not silently change frozen V1.6. |
| slc-v2 | feat/slc-v2-he-entry-2026-11-26 | 4 ahead / 30 behind. Integrate or explicitly decline shared participation candidate after rebase and matched controls; no forced PBV1 coupling. |
| CEG research | feat/slc-ceg-player-integration-2026-11-26 | 48 ahead / 44 behind relative to slc-v2; distinct architecture, do not wholesale merge into V2. Preserve shared mechanisms with validated contract. |
| dev / packaging | feat/week12-pregame-snapshots-2026-11-26 | 5 source commits; Oracle, cutoff conversion, roster preflight, identity, portable batch, tests. Review and integrate exact fixes after end-to-end snapshot/pack validation. |
| dev / packaging | fix/roster-preflight-2026-11-22 | 15 source commits; 21 files incl. evidence, runner and rule-pack changes. Reconcile overlapping changes with Week 12 branch. |
| dev / packaging | feat/slc-portable-model-packs-2026-11-18; feat/slc-v1-executable-package-2026-11-18 | 48 and 33 source commits respectively in initial comparison. Resolve PR #51 export/parity blocker; reconcile runtime before merge. |
| research | research/slc-week12-blackfriday-runs-2026-11-27 | 6 source commits / 41 changed paths, research evidence; preserve exact frozen outputs and archive hashes, coordinate active append work before merging. |
| research | research/week11-1k-batch-2026-11-22 | Source `63d4e30cdc04bdcefcb705cb861fe4f4a18a4029`, 3 commits / 13 paths, invalid forecast due stale rosters. Attempt to preserve all source blobs blocked by GitHub 422 invalid blob for one OOM manifest. No ref updated. Preserve branch until resolved. |

Additional review: docs/context-2026-11-22 (2 commits, historical context + Madden philosophy); docs/retro-pace-efficiency-charts-2026-11-27 (1 commit); docs/modeling-handbook-2026-11-26 (3 commits, compare truncated at 300 files); docs/slc-architecture-diagrams-2026-11-26 (3 commits; some paths match dev, some differ; do not assume equivalent); chore/track-package-lock (1 commit); docs/madden-pace-efficiency-charts-2026-11-27 and research/madden-mechanism-audit-2026-11-26 (no common ancestor with dev; extract only relevant artifacts). PBV1 legacy integration has 1 unique research commit vs slc-v2; preserve. Keep frozen experiment pins and results.

## Ancestry-confirmed deletion candidates
Recheck current ref tips, open PRs, active worktrees and downstream branch-name references before deleting. No branch deletion performed; connector does not expose a delete-ref action.

Contained in dev at `dbcc08b8`:
- docs/diataxis-philosophy-2026-11-27
- docs/simulation-artifact-retention-2026-11-27
- research/week12-gbla-grades-2026-11-26
- docs/lp-api-first-snapshot-2026-11-26
- fix/current-snapshot-guard-2026-11-22
- research/nfl-finalized-roster-recovery-extracted-2026-11-21
- research/oracle-walkforward-tooling-extracted-2026-11-21
- fix/nfl-boxscore-layout-2026-11-21
- feat/slc-family-runner
- test/oracle-forward-platt-parity-2026-11-21
- feat/snapshot-roster-text-2026-11-22

Contained in v1-complete at comparison:
- feat/v1-complete-combined-2026-11-26
- feat/v1-complete-persistent-lineups-2026-11-26
- feat/v1-complete-persistent-lineups-control-2026-11-26
- feat/v1-complete-player-state-2026-11-26
- feat/v1-complete-runtime-repair-2026-11-26
- feat/v1-complete-shared-policy-2026-11-26

Contained in slc-v2 at comparison:
- fix/slc-v2-kicker-code-normalization-2026-11-21
- feat/slc-v2-pbp-release-2026-11-17
- slc-v2-reconciled-2026-11-17

## Completion gate
A complete sweep requires all remote tips with committer timestamps (including undated names), ancestry and patch-equivalence checks against intended destination, current open PRs and local-only commits/worktree ownership. For code integrations, independently review execution path and run target suites; preserve frozen configs and artifact identity. Delete only proven-contained, inactive refs; never delete unique work simply because a newer branch exists. No production, fast-host, model runtime or release changes made during this sweep.
