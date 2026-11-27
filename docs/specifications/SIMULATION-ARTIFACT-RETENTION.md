# Simulation artifact retention and fast-host storage policy

**Status:** Proposed operating policy, 2026-11-27; cleanup requires owner authorization and the migration gate below. No deletion, process lifecycle action or deployment is authorized by this document alone.
**Scope:** All Legendary Picks simulation families and cross-repository research on shared compute hosts, including SLC, CEG, V1 Complete, Gridiron and retro reference studies. Supersedes ad hoc "compress everything" practices, not existing source-data, cutoff, evidence or ownership safeguards.

## 1. Separate compute from retention

Run as many replications as a preregistered accuracy/cost objective warrants. Default development smoke: 1–10 attempts; diagnostic batch: up to 100; larger statistical runs only with a measured precision/convergence or rare-event objective, disk/CPU budget and explicit stopping rule. Never increase N merely because a larger run looks more impressive. For independent Bernoulli simulations, worst-case Monte Carlo standard error is 0.5/sqrt(N); 100 gives 5 percentage points, 1,000 about 1.6, 10,000 0.5. This is simulation noise, not model accuracy or uncertainty about the real game. Use paired differences only with verified common streams.

**Default hard retention cap: 100 full game/attempt records total per (league, season, week, game ID, model variant), across ordinary reruns, not 100 per invocation.** Non-weekly sports use competition/date/event ID. A model variant is a registered meaningful architecture/configuration arm, not a new label for each commit or seed batch. Record exact revision/configuration separately. Explicitly designate the canonical comparison run before sampling; do not replace a prior prospective lock with a later retrospective run. If there are fewer than 100 records, retain all. Never use this sample to recompute a forecast from a larger batch.

## 2. Retention classes

| Artifact | Retain | Location/format |
|---|---|---|
| Run manifest and full-population aggregates | Every meaningful run, including failures and superseded evaluations | Small immutable JSON/Markdown; indexed in repo |
| Compact seed census and outcome facts | Every attempted seed, status, blocker, score, and compact per-seed team/player sufficient statistics needed for approved grading/regrading, paired comparisons and joint markets | Compressed typed tables, preferably Parquet with Zstandard where already supported; gzip JSONL/CSV acceptable. Store once by content hash. |
| Complete event logs, box scores with play links, replayable trajectories | At most 100 detailed records per retention key | Compressed JSONL or tar archive; sample index and hash |
| Failure evidence | All failure counts and seed IDs; bounded representative traces within the 100-record cap | Compact ledger plus deduplicated stack/failure signature; select additional full traces only through exception |
| Frozen inputs and executable artifacts | Every unique irreproducible or required cutoff-valid input, model package, ratings, roster, participation, configuration, exact source revision and dependency identity | Immutable content-addressed artifact storage; one verified copy per hash in a store, independent backup for irreplaceable inputs |
| Scratch outputs, derived caches, extracted archives and rebuildable worktrees | Only while needed or explicitly pinned | Temporary workspace; remove after verified closeout, subject to ownership/active-use checks |

Compact rows are not full game records. They preserve actual estimates from all N attempts and allow regrading without resimulating; do not retain full play arrays, repeated snapshots or trajectories in them. If budget forces dropping a compact field, document exactly which later analyses become impossible and obtain approval before loss. Preserve full joint seed-aligned statistics for published joint forecasts. Store exact numerator/denominator, push/tie/void policy, market lines/time/source, actual data identity, metric definitions, distribution summaries and tail counts, not just rounded means. Include all attempts, invalid/blocked seeds, and selection/coverage. No fabricated zeros or silently excluded failures.

## 3. Sample selection and reproducibility

Select independently of score/outcome using a versioned deterministic hash rank of stable cohort ID and seed; for verified paired model experiments use the same seed selection across arms and record missing/failed attempts, never silently replace them. Within the 100 slots, reserve up to 20 for distinct failed or diagnostically important paths (record selection criteria and labels), and fill remaining slots by uniform hash rank from the remaining attempts. If fewer failure cases exist, use remaining slots for the representative sample. Report that diagnostic oversampling is not representative. For matched comparisons preserve a common representative subset and explicitly separate diagnostic records. For multiple reruns choose a designated primary sample; no automatic accumulation of another 100 traces. Retain earlier important fixtures by explicit budgeted exception or include within the cap.

Manifest minimum: run ID, model ID and exact code/tree SHA(s), engine/package/configuration/input hashes, immutable input locator, dependency/runtime and RNG algorithm/stream/version, seed generator and complete attempted census, capture/cutoff and launch/completion timestamps, requested/attempted/valid/blocked counts, output schema, sample selector version/IDs, all-seed metrics and full compact evidence hashes, archive checksum and byte size, storage owner, reproducibility test status, retention decision. A seed alone does not guarantee replay. Do not claim exact reproducibility for nondeterministic physics or missing dependencies.

## 4. Lifecycle and storage budgets

- Hot: active runs, current and previous week working inputs only if needed; close successful/blocked runs promptly. Do not retain extracted and compressed copies indefinitely. No default new full database clone for each arm.
- Warm: compressed capped samples and compact results; older completed weeks moved off fast host to approved durable storage after verification. No default local copy once restore is tested.
- Cold: retain manifests, grading evidence and irreproducible inputs indefinitely until explicitly reviewed; retain published/release/locked benchmark artifacts and exceptions under their registered requirements. An archive on the same disk is not a backup. If no approved durable store exists, report the blocker instead of deleting required evidence.
- Proposed host defaults: target >=15 GiB available on 96 GiB host; hard reserve max(10 GiB, 10% filesystem capacity) after estimated peak concurrent writes. No new large run/download/extraction below reserve; bounded recovery operations only if they fit and are owner-approved. At each checkpoint record df bytes/inodes, uptime, free memory, du and peak working + archive + log + database/WAL growth; existing RAM rules remain in force. Stop before the reserve is crossed. /tmp shares root disk; tmpfs uses RAM and is not archival storage. Check shared active jobs before writing or cleaning.
- Prefer streaming/chunked aggregators and writing only selected full traces at source. Keep a compact census and incrementally checkpoint aggregates. Benchmark compression on a small representative sample; reuse existing environment and format before adding dependencies. Do not write the entire 10k trace archive just to shrink it later.
- Content-hash deduplicate frozen DBs/packages and materialized histories only after verifying byte identity or validated regeneration with preserved semantics. Preserve distinct cutoff snapshots even if sizes match. Use explicit reference index, not uncontrolled hardlinks of mutable SQLite databases. Keep one verified immutable object plus backup where needed. Remove clean inactive worktrees using git worktree procedures only after pushing required commits and preserving untracked evidence. No blanket cache, agent-state, package, database, log or process cleanup. Apply existing agent ownership rules.

## 5. Legacy migration: existing 10k+ runs

Do not delete a 10k archive based on filename or size. Use one small, completed, inactive archive first:
1. Inventory path, owner, open handles, bytes, original checksum, model/run identity, expected count and downstream references. Establish the canonical run for its retention key and any holds. Dry-run list exact candidate files and peak staging space; no unpack-all on a full disk.
2. Stream archive members, extract compact full-population facts and choose the bounded deterministic sample. Write new immutable manifest, compressed sample, all-seed census/results, summary and migration mapping (old hash/path -> new hashes/paths). Preserve original report and exact N; mark missing facts unavailable.
3. Verify archive integrity and hashes; read back records; reconcile every attempted seed, validity and counts, totals, prop/score grading numerators/denominators and published metrics against original. Verify sample membership/cap, input availability, and deterministic replay on a small selected subset where supported. If exact reconstruction, source availability or replay fails, hold original or transfer to approved cold store. An approximate summary is not equivalent.
4. Confirm new durable artifacts are accessible (restore test and independent backup of irreplaceable evidence); document byte savings and owner-approved deletion list. Only then remove verified obsolete original/extracted duplicates and record final free space and deletion receipt. Never mutate active outputs, forecast locks or shared databases. Apply the same gate to each subsequent archive, not a blanket rm.
5. Stop on any mismatch, active consumer, missing provenance, no backup/restore path or inadequate staging space. Keep original unchanged. Do not restart Hermes or any service to reclaim deleted-open files without explicit owner approval.

For current inventory see [fast-host storage report](https://github.com/micahp/legendarypicks/blob/e463a90cac5a3a5212792512e1078f5dd3197315/docs/reports/FAST-HOST-STORAGE-REVIEW-2026-11-27.md). The 99%-full host warrants a cleanup plan before additional large batches. Week 11 inputs dominate its footprint, so trace pruning alone cannot restore headroom. Compare the two multi-GB frozen DBs and repeated history artifacts by hash/references; do not assume duplicates. Deleted-open Hermes state is a separate owner-controlled action.

## 6. Exceptions and acceptance

Allow an explicitly approved, time-bounded exception for publication/competition artifacts, regression fixtures, irreproducible traces, long-lived benchmarks, rare-event investigation or required full-distribution evidence. Register objective, owner, byte budget, scope, location, expiry/review and why compact results plus 100 traces cannot suffice. Prefer cold storage rather than unbounded fast-host retention. Never silently discard required evidence to satisfy a quota.

Implementation acceptance: on a known large inactive batch, demonstrate all-seed grading parity, sample cap across reruns, failure preservation, deterministic sample selection, manifest/restore/replay checks, no active file mutation and measured peak/final disk savings. Test crash/resume, missing/corrupt input, duplicate IDs, failed seeds, nondeterministic results and insufficient space. Until tooling passes these gates, policy is a manual review procedure, not automated cleanup.

## External precedents (not a mandated 100-seed standard)

- [ACM SIGSIM artifact evaluation](https://sigsim.acm.org/conf/pads/2026/blog/artifact-evaluation/): documented, functional and reusable computational artifacts; preserve enough to exercise reported results.
- [FAIR principles](https://www.nature.com/articles/sdata201618): persistent identifiers, metadata, provenance and reusability.
- [SimDesign Monte Carlo documentation](https://philchalmers.github.io/SimDesign/reference/runSimulation.html): replication summaries and RNG state for reproducibility.
- [Apache Parquet compression](https://parquet.apache.org/docs/file-format/data-pages/compression/): compressed columnar facts for analysis.

These sources support the general approach, not any universal numeric cap or retention period. The 100-record cap and host headroom are proposed Legendary Picks engineering choices. See [evaluation methodology](../evaluation/METHODOLOGY.md) and [agent rules](../../AGENTS.md).
