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


## Follow-up — 2026-11-27, 14:27 CT

- Week 11 invalid-forecast evidence is now merged at `9d58f1a7daea4fbec3886114f4b7dc3d5b9a985a`; the previous blob error was resolved by refetching full source files. All 13 paths preserved as source blobs, with no runtime paths touched.
- November 22 historical context and Madden philosophy merged at `d5793d8f4a6706d271c33b43309293cde550166b` as original dated files, not current architecture authority. Some historical links and status statements are stale.
- Both source branches now have zero unique commits vs dev: `research/week11-1k-batch-2026-11-22` (tip `63d4e30cdc04bdcefcb705cb861fe4f4a18a4029`) and `docs/context-2026-11-22` (tip `965d3b0f6c86ac446f03f8d97ca13ef45a4f513e`). Add to the deletion candidate list (22 total).
- Rechecked original 20: all still ancestry-contained. Four open PRs returned (#29, #33, #35, #46); none has a candidate as head or base. Owner authorized deletion of listed candidates. No remote ref deleted: connector has no delete-ref operation and direct git ls-remote failed DNS resolution. Active worktrees on other hosts and branch-name dependencies still require verification before deletion. Use exact-tip leases and recheck ancestry; do not remove worktrees or local-only commits.
- Runtime integration queue remains pending; no model branch was advanced or model test rerun during this follow-up.

## Runtime integration follow-up

- `v1-complete` fast-forwarded from `eb056489` to `7f628333`; exact Gridiron candidate pin `2e17dadb297a001eae30f80905ff366dd73613ca`. No full-game acceptance claimed. Source branch `feat/slc-v1-complete-implementation-2026-11-24` is ancestry-contained.
- `slc-v1.6` merged at `14e26d0b509b6cd9254d523bdeb0c6e0b6582648` from `8d2284b8` and `cf8fd47b`. Rejected source regression removing verified snapshot gate; retained strict boolean provenance in record and validator, kept boxscore exports default-on and geometry default-off. Added replay/ledger/snapshot identity for the opt-in geometry flag and stricter OT preflight (nonempty pool, all margin buckets and valid probabilities). Three source-extracted Python checks passed; full tests, original stopped seeds, and portable-runtime integration not executed. Frozen model pins unchanged. Source branch `fix/slc-v1.6-rules-2026-11-23` is ancestry-contained (some source behavior intentionally rejected).
- Deletion candidate count now 24, conditional on inactive worktrees, branch-name dependencies and fresh ancestry checks. No branches deleted. No PRs or production changes. Oracle and packaging queue remains outstanding.

## Oracle / roster / portable batch consolidation

- `f80e28b78c0b9f4149e19558f9d88aa49127684d` merges Week 12 snapshot branch tip `44d98f9a24fb1a8aa88b7008a6565beeaa03bb47` onto dev. All 11 changed paths had either identical dev and merge-base blobs or were new. Independent source review covered Oracle, current builder, T−90 conversion/reuse, market identity, roster eligibility, runner and portable output schema. Additional guards recheck frozen QB evidence, compare roster-resolution hashes, reject future depth charts, unknown player/team rows and repeated games, preserve exclusive manifest creation, handle malformed output and record actual acquisition times. ESPN status supplements only players without existing report entries on the same team.
- `a4f021007e3c29887b53141b239ec940a7946cdc` preserves 18 exact historical evidence blobs from `fix/roster-preflight-2026-11-22` tip `4b9709eadbae7f7a55ce6516780207f3bc0fe081`. The earlier exclusion enforcement, trick-pass primary-QB check and smoke tests were already in the newer runtime. Kept the explicit `--models` requirement rather than restoring the older five-model implicit default; PBV1-off and other arms must be named explicitly. No regrading.
- Both source branches are now ancestry-contained in dev; deletion candidates increase to 26. No deletion executed; active worktrees and branch-name references remain unverified.
- Regression tests added to the source; actual repository test execution, live DB/Oracle acquisition, package replay and host smoke/full batches were not performed. Older snapshots without frozen QB evidence now fail the consolidated batch preflight; preserve historical artifacts and rebuild from valid cutoff evidence only. The current-data builder remains a build-time snapshot tool, not an exact T−90 prospective capture tool. The historical converter still needs independent evidence of weekly roster availability at cutoff before any prospective eligibility claim. No frozen package or production changes.
- Next: reconcile the two portable-package branches and PR #51 evidence, then V2 shared participation and CEG integration.

## Batch acceptance follow-up

- Dev `666f81cc3097c91b65efee67843b07acbf5eaf21`: maintained portable runtime rejects unverified snapshots before seeds and aborts strict execution on first invalid seed; preserves separate original and runtime-resealed snapshot identity and attempted count. Research mode explicit; frozen packages unchanged.
- Dev `77cdb86cbd9a56ca5171d3f703bf05f4e06f5fae`: source family runner now preflights the sealed roster, materializes exact runtime source, requires all smoke results before full runs, validates seed census/identity and limits legacy chunks to 25 seeds. Shared bounded scheduler stops subsequent waves after failure; already-started jobs can finish. Portable runner omits unsupported default workers flag and requires the runtime to expose validity contract. Four exact-blob scheduler unit tests passed locally; synthetic Git checkout verified. Full repository suites and runtime integration not executed.
- `v1-complete` at `f766b5550f6174636ff1fc1d135a3cd86237e07b` (same Grid `2e17dadb`) adds model-specific runtime input readiness and strict sequential batch launcher. The first requested seed is counted as smoke; failure aborts subsequent seeds and preserves diagnostics. Four mocked launcher tests passed using source-extracted code and matching test blob. Live engine/host assets, actual full-game smoke and original Thanksgiving failure cohort not executed. External host launchers remain unaudited; use the maintained CLI. No claims of model acceptance, no frozen pins or production changes.
- Generic snapshot builders label runtime readiness as not evaluated, not model ready. New binding rule in AGENTS and maintained [API guide](../API-AGENT-GUIDE.md#mandatory-model-readiness-and-batch-launch). Regression test added but not executed in the full repository.
- Branch deletion candidates remain 26; no remote deletions. Portable compiler branch reconciliation, V2 participation and CEG queue remain outstanding.

## Portable packaging reconciliation

- PR #51 was merged at `a75ed781a708d4a91eae9467fb10210dc3ed6d3d`. Compared both source branch tips `5c770bec174a7368abfe2a562ba6700df64d05ab` and `feaf6ad499beed6af8e38bd402fd3ceeb6c97beb` against dev. All 26 historical research blobs are already identical. Compiler, codec/loader, registry, CLI, parity tools and tests from the newer branch were already present. The older branch's sole commit not in the newer history defaults player box-score exports on; that behavior is already in dev's CLI and runtime. Six changed runtime/test paths were reviewed; retained the newer cutoff/roster, seed census, smoke and abort protections rather than restoring old versions.
- Source reconciliation uses both exact tips as merge parents; keep existing dev code except focused build and parity acceptance hardening. Build smoke now requires the actual planned valid seed, rejects seed-list/resume escapes and key registry variant conflicts. Parity rejects empty cohorts and matching failed games by default; explicit diagnostic-only mode can compare failed records. Use `--expected-seeds 100 --seed-start 300001` to require the planned cohort, not merely equality of supplied files. Parity output is immutable. These are development acceptance safeguards, not new package releases.
- **Pinned source availability blocker:** GitHub commit lookup returned 422 no commit found for frozen V1.5 `2eab8a89efffad23c00a1d451ac80e856579ac5a` and V1.7 `1ca59e0d038b594b87c0dd5b4c78b0711b022043`. V1, V1.6 and shared V2/PBV1 source commits resolve. Recover exact missing objects from existing host/source archives and establish durable refs; do not substitute moving branch tips or rebuild with different code under the same model identity. Existing trusted packages remain unchanged. No source host verification or model parity run performed.
- Two additional ancestry deletion candidates after merge (28 total), subject to existing worktree/ref dependency checks and missing-pin recovery. No deletion, release, production or fast-host run. Next: V2 participation/HE integration; CEG independently.
- Four comparator regression tests passed in an isolated local Python process; the two test/runtime file hashes exactly matched GitHub blobs `9263e882d78d1ba18da11fb97bd99e2f23c04d3e` and `1d4ac86c851a84a9eb19b73fa70228afcabf562c`. Compiler policy/smoke tests were added but not executed; no real pack rebuild, codec/runtime suite or full parity cohort executed.

## Recovered source pins and cleanup recheck

- Owner reported recovery of both missing commits from existing local feature branches without force-pushing. Independently verified exact remote refs and commit resolution: `feat/overtime-required-v15-2026-11-18` → `2eab8a89efffad23c00a1d451ac80e856579ac5a`; `feat/overtime-required-v17-2026-11-18` → `1ca59e0d038b594b87c0dd5b4c78b0711b022043`. Both retained; source availability blocker resolved. No rebuild or parity claim.
- Rechecked all 28 deletion candidates against the current remote destination heads (17 dev, 7 v1-complete, 1 slc-v1.6, 3 slc-v2); all zero ahead with unchanged candidate tips. Four open PRs (#46, #35, #33, #29), none uses a candidate as head or base. User authorized deletion; connector lacks remote-ref deletion and direct Git DNS fails here, so zero refs deleted. A guarded host cleanup script was supplied separately. Other hosts' active worktrees and branch-name dependencies remain unverified; do not delete restored frozen source refs.

## V2, CEG and Thanksgiving evidence consolidation

- Moving `slc-v2` advanced from `fa8c2ff9` to `6d2db7e1ec0cbebbeba08ce1049f1f64b08a2bad` with source HE branch tip `fec4cf53a209646aa03ec6cf9b81398a9900ffd3` as merge parent. HE already existed; preserve newer target PBV1 coupling without claiming it works. Port deterministic feasible lineup repair, reject true shortages, require HE snap counts, preserve CLI aliases and setting in reproduction/pairing/ledger. Explicit HS required for field-only controls. Frozen pack unchanged. Tests from source preserved, not run.
- Independent `research/slc-ceg-2026-11-24` advanced from `8d86d430` to `df6d8e6ffd984d833472f44bec33426f93ff0917` containing player candidate `263a30c003b92b0d6ae9b99a900d34e516c95b86`. Shared eligible roster helper and frozen resolution guards, accepted E1 play commit callback (no penalty-replaced lineup stint), trusted artifact digest/preflight, fail-closed single-matchup runs. No full NFL validity or prospective claim; frozen Phase 9 baseline retained by SHA. Legacy multi-matchup path not changed. Source review traced generator/provider/penalty/E1/stats; tests not run by owner request, host engine verification deferred to team.
- Preserve exactly 40 Thanksgiving retrospective evidence blobs from `e8b479f62f41bbd97bb32b53f08c0946288f48c5` under the original folder. No regrading or host deletion; original report contains no Black Friday DEN–PIT results at this pin. Its CEG "valid full game" wording is historical scoped completion, not independent NFL rule certification. Raw archives not independently checked.
- Retro chart branch `08388db6829352012b9453177a4d67d9d8f825a9`: all four affected file blobs already identical on dev; reconcile ancestry without content changes. Both research/chart tips retained in dev history. Four new ancestry deletion candidates (32 total before any host cleanup); no remote deletions by this session.

## Handbook and architecture diagram ancestry reconciliation

- Modeling handbook `e1f960aa3f1c5fc16b9b46dc01e5eeeda4ac5d12`: full recursive tree comparison against its merge base identified 362 changed paths, of which 342 match dev exactly (including removed paths). All 20 differing files were read against dev. The only missing nonblank source lines were superseded by the Diátaxis link or expanded V1.6 title and definition; the underlying benchmark values and design description are preserved.
- Architecture diagrams `0ef651c7d9f71f307b896b8712f849a2bb61a5c4`: 15 changed paths, 9 exact matches; all six other files retain the source text except the expanded V1.6 label in the registry. All SVG blobs already match. Keep newer dev documentation and reconcile both histories without reverting content. No further archive moves or source changes.
- Both are ancestry deletion candidates after merge (34 total prior to host cleanup); no remote deletion performed here.

## Gridiron Physics — initial cross-repository branch sweep

- Enumerated 80 remote branches and six open PRs. The active V1 Complete engine remains `feat/v1-complete-autonomous-execution-2026-11-24` at `2e17dadb297a001eae30f80905ff366dd73613ca`, 72 ahead and 3 behind main at the time of comparison. Do not merge into main or change the LP engine pin during the team's acceptance testing.
- Ancestry-confirmed cleanup candidates, relative to the active engine, are `feat/v1-complete-runtime-repair-2026-11-26` (`93b527826d0dfb46fe59aa6ee9d6462a0b359b8e`) and `research/slc-v1-consolidation-2026-11-23` (`d375f3f79fdd306f7f8ccfa6f6b87ef282de3da7`). Neither is an open PR head or base. Retain until worktree/ref dependency checks and deletion approval.
- Preserve the overlapping controller branches pending semantic reconciliation: `feat/assigned-pass-controller-2026-11-26` (`61eac5b47a8ca7052a70a69a5f2d4e7f63b9e6aa`), `research/v1-complete-causal-receiver-2026-11-26` (`12b58c97d4d80c0983c84bd01a046f2e8e3c3ddc`), and `research/v1-player-order-arbitration-2026-11-26` (`6b769777e9f734c9fedb15f64278ace51cdd351d`). Active passing code contains the receiving-assignment gate, causal catch-point estimator and shared-snapshot arbitration; several supporting source/test blobs match exactly. Passing code differs and full semantic equivalence is not established. The [assigned-pass candidate report](https://github.com/micahp/gridiron-physics/blob/61eac5b47a8ca7052a70a69a5f2d4e7f63b9e6aa/docs/research/ASSIGNED-PASS-CONTROLLER-CANDIDATE-2026-11-26.md) is not on the active branch.
- Retain `feat/v1-player-state-logic-2026-11-26` at `ea52ed63284e84c7361593c6c44fbfe390bc67d8`: its unique GPIA-01 evidence contains 103 files (~40.6 MB), absent from the active tree. [Play-level summary](https://github.com/micahp/gridiron-physics/blob/ea52ed63284e84c7361593c6c44fbfe390bc67d8/docs/experiments/gpia-01/repinned-abcd-2026-11-26/summary.json); [CHI–DET diagnostic](https://github.com/micahp/gridiron-physics/blob/ea52ed63284e84c7361593c6c44fbfe390bc67d8/docs/experiments/gpia-01/repinned-abcd-2026-11-26/full-game/chi-det-exploratory-fc22ba3e-r64296287/summary.json); [GB–LA diagnostic](https://github.com/micahp/gridiron-physics/blob/ea52ed63284e84c7361593c6c44fbfe390bc67d8/docs/experiments/gpia-01/repinned-abcd-2026-11-26/full-game/gb-la-replay-46c10393-r8b19ea9/summary.json). Both historical full-game diagnostics recorded zero legal games per arm; these older pins and exploratory snapshots are not evidence about the current engine. No duplication or deletion of raw evidence.
- This is a targeted V1 Complete sweep, not a completed audit of every Gridiron branch. No Gridiron refs, engine files, or LP engine pins changed. Engine-level verification is delegated to the owner's team.
