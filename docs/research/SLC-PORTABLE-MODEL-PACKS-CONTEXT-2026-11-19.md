# SLC Portable Model Packs — Project Context

Updated 2026-11-20

## Goal

Export each SLC model family as a versioned, self-contained runtime package. The intended coverage is V1, V1.5, V1.6, V1.7, V2, and PBV1. A portable run should use a selected model, frozen pregame inputs, and explicit seeds without a database, loose research fixtures, or retraining.

Every standard package must support full games, including overtime. Preserve each model's original rules policy, code version, and experimental switches. Do not promote or merge until each supported variant passes portable-versus-legacy parity.

## Current implementation

The portable runtime bundles pinned engine code and JSON-serialized model state in a checksum-protected package. Its runner blocks database connections and research-table or fixture reads.

**All registered variants now have portable packages and one-seed build smokes:** V1, V1.5, V1.6, V1.7, V2, PBV1 label-only, and PBV1-off. V1 and V1.7 also completed an offline-runner smoke with source-access guards enabled. This is execution evidence only; full portable-versus-legacy parity remains incomplete for every variant. V1.7's pinned penalty fit is marked research-only, and its candidate penalty layer and research ruling policy remain explicit in the package.

The registry pins the overtime-required release commits. Build-time play-call frame caches are scoped to code commit and season cutoff and are reused only after the pinned loader validates their source fingerprint. V1.6, V1.7, and V2 record a before-game-week cutoff; the runtime rejects snapshots earlier than the package cutoff. PBV1-off and PBV1 label-only are separate variants on the V2 code with the original V1 full-stack profile.

Regulation-only execution is retired as a normal profile. Regulation-end data remains available for diagnostics. `regulation_only=True` remains a historical reference-pool filter and does not disable overtime. Missing overtime dependencies fail before seeds execute.

## RNG v2 and the current-streak fix

Controlled comparisons require matching RNG v2, seed IDs, and frozen inputs. The portable runner accepts the packaged RNG scheme, records its plan, and can reject a run before seeds if the expected stream root differs.

The portable preflight mismatch came from current-streak context: legacy V1 included all 32 rows in its model-input hash, while the pregame snapshot held only the two matchup teams. The fix carries the exact frozen streak table as checksummed `runtime_model_inputs` beside the hash-pinned pregame snapshot. This preserves the legacy pregame hash and the pinned loader's source keys and values. The existing `nfl_team_codes` resolver validates the team bridge.

When the current-streak layer is enabled, provide the snapshot as an envelope with these top-level fields:

```json
{
  "pregame_snapshot": { "...": "hash-pinned snapshot" },
  "runtime_model_inputs": {
    "schema": "lp-slc-runtime-model-inputs-1",
    "current_streak": { "...": "full frozen source table" },
    "source_sha256": "...",
    "sha256": "..."
  }
}
```

The runner validates the model-input digest and its source hash against the compact context in the snapshot before seed execution. Runtime does not open the original streak fixture.

## Verification achieved

Historical WAS–NYG comparison, seed `300001`:

- Pack SHA-256: `9403c9f63e764720799c8a4bd43a67f3fd3554716abc7692a1c4f39bd2078514`; reference SHA-256: `168b59885d1cc5cbe6a60e4560a8017942afad8e26bf4057d2ea1ab7b58019b5`.
- RNG v2 stream root matched legacy: `6d1979d6404e6cbc9cfd383fd02a041710c6790173a194c50b11e4c5e8fddc0f`.
- Portable execution passed preflight and completed the game.
- The complete portable game record matched the legacy record exactly, including transitions, score, and statistics.
- Portable source-read guards were active during execution.

Focused verification for that earlier change passed: 5 tests, Python compilation, and `git diff --check`. It establishes one-seed WAS–NYG parity for the package from that run; it does **not** establish parity for the newly built V1 package or complete the two-game, 10-seed, 100-seed, or full-family gates.

## Branch and working tree

Commit `6eb4a49ded7d270bdc43f26de0ae97d320fe5357` is pushed to `feat/slc-portable-model-packs-2026-11-18`. The local branch is `feat/slc-v1-executable-package-2026-11-18`. The remote branch was verified at the same commit. `dev` remains unchanged.

The V1 model card records an earlier package and its failed 10-seed comparisons. Its addendum describes the separate one-seed exact-parity run above; the two artifacts and results should not be conflated.

## Runtime memory audit (in progress)

This is an initial read-only census, not a complete object-level audit. Measurements were taken on the fast host while the DEN–PIT batch was running. No model implementation was changed.

Two V2 personnel-first workers, each running 125 seeds from package `407a514b75febac156dbfe66e4abe30f6eafdfd523eaabccb44a726a7245e3f5`, had RSS of 1,457,188 and 1,452,080 KiB. Their private dirty memory was 1,428,676 and 1,423,528 KiB respectively; PSS was 1,440,565 and 1,435,473 KiB. These are single samples, not per-object retained sizes or peak-load measurements. Each subprocess loads its own reference, so most of the measured memory is not shared. The earlier four-worker V1.6 batch exhausted host memory; these V2 figures cannot establish V1.6's object composition.

Representative package ZIP metadata, in bytes, follows. Compressed archive size is disk use; uncompressed `reference.json` size is serialized data, not RAM. These packages are examples, not necessarily the precise artifacts used by every batch.

| Model | Compressed package | Uncompressed reference.json |
| --- | ---: | ---: |
| V1 | 19,684,308 | 371,237,538 |
| V1.5 | 27,420,927 | 536,256,149 |
| V1.6 | 35,651,506 | 609,926,783 |
| V1.7 | 27,660,668 | 528,309,685 |
| V2 personnel-first | 30,966,014 | 561,614,792 |
| PBV1 | 28,683,973 | 542,886,844 |
| PBV1-off | 28,675,634 | 542,853,093 |

The inspected PBV1 and PBV1-off manifests carry the same reference fingerprint, `8e1171dcbca8415cfff0341bd48e1ef1d7718d93e9174ed531bc4bd2b1c95c2d`, although their payload hashes differ. That establishes matching recorded reference fingerprints, not byte-identical serialized payloads or proof that all their runtime objects are interchangeable. The frozen CEG artifact inspected is 1,985,586 bytes on disk; its retained memory has not been measured.

### Frozen CEG object walk

The frozen Week 12 CEG artifact (`05554214c1ff…`, `ceg-sel-e-2026w12.pkl`) was loaded with `/root/envs/lp-standard/bin/python` on the slow host. An identity-deduplicated walk of the artifact's reachable Python containers, instance dictionaries, scalars and NumPy arrays measured 4,553,101 bytes before execution. This is a reachable shallow-size sum, not a dominator-based retained-size calculation; it excludes interpreter/module overhead, native allocations not reported by `sys.getsizeof`, and untraversed implementation-specific references. The profiler's peak RSS was 290,572 KiB, including imports and instrumentation.

Attributing shared objects once, in top-level traversal order, yielded 2,643,353 bytes for `gen`, 1,536,659 for `clock`, 354,543 for `special`, and 17,687 for `chosen`, plus scalar metadata. The `gen` portion included 1,263,416 bytes of reported NumPy array sizes, 578,381 bytes of strings, 411,760 bytes of tuples and 215,672 bytes of dictionaries. These figures are order-dependent ownership allocations, not individually exclusive retained sizes.

With external data reads blocked, seeds 300001–300010 were executed sequentially with the same artifact and no returned record retained. All returned without a blocker. After collection, the reachable-size sum was 4,553,359 bytes, 258 bytes higher; the walk's visited identity count rose from 47,412 to 47,416. This bounded observation does not prove that no CEG cache can grow in other matchups, configurations, or longer runs. The artifact is fitted tables and small empirical value lists, rather than runtime historical play rows. These ten runs were profiling observations, not an NFL calibration or portable-parity test.

The portable loader streams JSON into objects, but constructs separate Python objects and copies decoded NumPy arrays. The runner deep-copies the game snapshot per seed. Its `rows` and player-box-score `details` lists grow with attempted seeds; optional full records and decision traces also accumulate until output. These are output buffers, not evidence of a leaking cache. The inspected V2 play-call sampler builds `_cells`, grouped outcome counters, sorted row lists, `_team_transition_groups`, and, when enabled, a backoff index lazily. They can grow as previously unseen cells are visited across seeds; retained sizes, ceilings, and behavior in every other pinned engine remain unmeasured. Group lists may contain references to existing rows rather than independent copies: object identity profiling is needed to distinguish the two.

Read-only, immutable fitted tables and historical rows are candidates for sharing across workers. Mutable per-game state, RNG streams, snapshot copies, decision traces and mutable caches need isolation or a verified shared read-only representation. A fork or memory map is not automatically safe or effective: copy-on-write behavior, object mutation, platform, provenance and parity must be measured. CEG currently unpickles its artifact in each worker initializer and collects results in the parent.

Counts and weighted aggregates can replace individual historical rows only when they retain every value used by eligibility, conditional filtering, transition and participant weighting, attribution, downstream state, and any required row identity. The inspected V2 sampler selects historical rows after formation, coverage, streak and label conditioning, player weights and transition grouping; a single unconditional count or mean cannot preserve that joint distribution. Exact grouped representations may be possible for rows proven equivalent across all relevant fields, with multiplicity and ordering retained where seed parity requires it. This has not been demonstrated.

Still required for a complete census: profile every pinned V1, V1.5, V1.6, V1.7, V2, PBV1 and CEG artifact independently; enumerate retained object graphs with shared-reference accounting and native allocations; measure load peaks and growth over seeds; trace field access across representative games and all conditional paths; compare dataset identities and cached indexes; and validate any compression or sharing proposal against full seeded records. No field is declared unused on the basis of this source inspection alone.

### V1.6 OOM incident: exact artifact and confirmed duplicate serialization

The exact DEN–PIT V1.6 package used by the 500-game run is `/root/runs/week-11/inputs/models/portable-models-2026-11-21-pr51-verified-core/v1.6--season-2026.slcpkg`, SHA-256 `6cf1e83677dc325632c49b2659de3ab04c856fc63d44b19fccc26a6f674f03a2`, model code `1bb3bd50c4df5896e4d693245e48329c20c63254`, reference fingerprint `a54b8bb668d20559a77c60a39e2c4636010b8518152d5860cee3167a08cdebef`. It is 35,650,041 compressed bytes and its state payload is 609,927,573 bytes. Its build metadata says `eligible_before: [2026, 11]`, built 2026-11-21 for `2026_11_ARI_KC`; support checks include 9,963 kickoff rows, 140 overtime rows and 75 play cells.

The legacy engine source explicitly aliases `ref.contextual_sampler.source_pool = ref.pool` (`slc_engine.py`, V1.6 bundled line 215). The portable state serializer recursively emits each object occurrence and detects only active recursion cycles; it has no global object-reference/backreference encoding. The decoder constructs each occurrence independently. Therefore, when both attributes are present in the portable reference, those two aliases become separate object graphs. This is a confirmed duplicate-representation defect in the format. The exact duplicate bytes and retained bytes have not been measured because that requires decoding and walking this 610 MB payload under the pinned Python 3.12 runtime.

The prior 2.6 GB RSS observation in this audit was measured on two V2 simplified workers, not on a live V1.6 worker. The V1.6 four-shard attempt did trigger OOM and the batch log records four workers, but no per-PID V1.6 RSS time series, load-stage samples or OOM victim memory snapshot was preserved. Thus “about 2.6 GB per process” is not independently established for the V1.6 incident. Its measured allocation census, startup, post-load, first-seed, subsequent-seed, and peak RSS remain unmeasured. The 499/500 V1.6 batch result does not provide object-memory accounting.

The available V1.7 package is SHA-256 `16092cde86403e4b2dfc14d11ca2669b9ea2000434edc471c9de5b578e0a463f`, source `1ca59e0d038b594b87c0dd5b4c78b0711b022043`, reference fingerprint `08142b3db56be09744cfd635535db2fded87e230c02372b036d342b0deb2e8cf`, and payload size 528,309,685 bytes. Its cutoff is `eligible_before: [2026, 10]`, versus V1.6's `[2026, 11]`. V1.6's payload is 81,617,888 bytes (15.45%) larger, despite V1.7's additional penalty layer. The later V1.6 cutoff makes a larger historical pool a plausible contributor, but the two fingerprints and payloads alone cannot assign the difference to a specific object or prove the cutoff is the cause. A like-for-like attribute census is required.

The DEN–PIT V1.6 output buffers are bounded by each shard's 125 seeds. Each output file is about 1.06–1.08 MB with player box scores enabled. The runner's in-process `rows` and `details` retain these records until writing the JSON at batch end; for 125-seed shards this is not a credible explanation for gigabytes of RSS. The model's historical pool, sampler indexes, duplicate pool alias, JSON decode peak, extracted engine modules and NumPy/SciPy/runtime mappings remain the candidates to quantify, not measured allocations.

### Exact V1.6 load-stage measurement

With approval, I ran the exact package above using `/usr/bin/python3.12` on the fast host while the registered V2 Support-Aware shard was active. Package verification, bundled engine extraction, and streamed reference deserialization completed in 317.9 seconds. Immediately after `load_pack()` returned and before any seed ran, `/proc/self/smaps_rollup` measured RSS 2,958,000 KiB, PSS 2,952,564 KiB, and private dirty 2,923,080 KiB; `VmPeak` was 3,663,264 KiB. This directly explains the roughly 2.6 GB process reports: V1.6 alone is already about 2.89 GiB RSS after load, before game-state and output allocations. The earlier number was a rough/inaccurate shorthand; this instrumented measurement is the exact package and runtime.

The recursive identity-walk profiler then exceeded 5 GiB RSS and exited before producing its graph report or beginning the three requested seed probes. That extra memory is profiler overhead, not part of the model footprint. No game seed was executed by this failed profile. The normal V1.6 batch workers were left running. The load measurement is valid; ranked attribute sizes, row and participant counts, cache sizes, first-seed delta, per-seed growth and process peak during normal simulation remain outstanding.

No numeric savings estimate is yet defensible. Priority from confirmed evidence is: first, preserve alias identity during portable serialization and reconstruction (targets the proven duplicate `pool`/`source_pool` representation); second, reduce decode-time transient copies using a reference-preserving streaming or memory-mapped format; third, share immutable decoded state across workers. Removing historical fields/rows is lower priority and requires inference access tracing. These measures must be evaluated separately. Every change requires the exact 500 V1.6 seeds 300001–300500, same pack inputs and RNG protocol, and exact normalized per-seed game records including player box scores, invalid-seed outcomes and failures. Sharing additionally requires confirming mutable caches and simulation state do not cross-contaminate workers. Because the identity walker exhausted resources, a lower-overhead object census must run alone after the current family batch; its method must avoid a Python object-sized `seen` set or account for its overhead explicitly.

Remediation objectives are distinct. (A) Remove unused fields or rows only after proving they do not affect any inference branch; retain all seed behavior and full record equality. (B) Eliminate duplicate representations by adding reference-preserving serialization or reconstructing the alias after decode; require exact object-alias assertions and full game-record parity for the same 500 V1.6 seeds, including failures and player box scores. (C) Share immutable decoded references between workers using read-only shared memory or fork copy-on-write only after measuring private/shared/PSS memory and proving per-game mutation isolation; require the same paired seed records and RNG streams. No savings estimate is asserted for A–C until the exact V1.6 runtime object graph is measured. The next safe measurement must use an isolated compatible worker after the active family batch completes; this audit has launched no new fast-host workload.
