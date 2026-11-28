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

### V1.6 OOM incident: measured object composition and duplicate serialization

The exact DEN–PIT V1.6 package is `/root/runs/week-11/inputs/models/portable-models-2026-11-21-pr51-verified-core/v1.6--season-2026.slcpkg`, SHA-256 `6cf1e83677dc325632c49b2659de3ab04c856fc63d44b19fccc26a6f674f03a2`, model code `1bb3bd50c4df5896e4d693245e48329c20c63254`, and reference fingerprint `a54b8bb668d20559a77c60a39e2c4636010b8518152d5860cee3167a08cdebef`. It contains 609,927,573 uncompressed state bytes (35,650,041 compressed). Build cutoff is `eligible_before: [2026, 11]`; support checks include 9,963 kickoff rows, 140 overtime rows and 75 play cells.

A bounded Python 3.12.3 profile instrumented the existing streaming JSON reader at each top-level reference attribute. It did not walk the object graph recursively. Four attributes account for 608,149,053 bytes, 99.71% of the payload:

| Reference attribute | Serialized bytes | Entries / rows | RSS after attribute | RSS increase at boundary |
| --- | ---: | ---: | ---: | ---: |
| `pool` | 105,928,513 | 75 cells; 141,180 historical rows | 591,784 KiB | 569,880 KiB |
| `participants` | 95,670,132 | 188,282 entries | 982,624 KiB | 384,476 KiB |
| `contextual_sampler` | 203,253,870 | includes source pool and fitted sampler state | 1,998,080 KiB | 1,014,528 KiB |
| `_describe_memo` | 203,296,538 | 2-tuple | 2,951,860 KiB | 953,756 KiB |

The remaining 23 reference attributes total 1,778,520 serialized bytes. RSS increments are observed process-boundary changes, not exclusive allocation totals; allocator reuse and object lifetimes affect them.

The portable decode breaks the legacy alias `ref.contextual_sampler.source_pool = ref.pool`: the loaded objects are not identical (`is` false) but compare equal, each has 75 cells and 141,180 rows. A bounded shallow count of each pool's mapping, cells, row tuples and row dictionaries is 128,831,904 bytes. Thus the duplicate pool representation alone adds at least that much retained container/row memory; this lower bound excludes nested field values and strings. The two serialized pool copies contribute about 106 MB each, one under `reference.pool` and one under the sampler.

A larger duplicate is `_describe_memo`. The pinned `slc_engine.describe()` stores `(sources, description)`, where `sources` directly retains the sampler, model-input mapping and sampler artifact. The serializer emits these referenced objects again inside `_describe_memo` rather than preserving aliases. Its 203.30 MB serialized size is effectively another sampler-sized object graph. Since the decoder creates independent objects, the cached source sampler cannot be identical to `reference.contextual_sampler`; the next `describe()` call must invalidate and rebuild the memo. The measured RSS increase at the `_describe_memo` boundary was 953,756 KiB (931.4 MiB). This is the strongest immediate removable duplication and is unrelated to model probabilities.

The measured attribute sizes also rank participants as a large independent component: 188,282 entries serialize to 95.67 MB and add 384,476 KiB RSS at their decode boundary. Repeated strings, identifiers and dictionary-key sharing were not individually counted; the profile does not claim their allocation savings.

The V1.7 comparison package remains SHA-256 `16092cde86403e4b2dfc14d11ca2669b9ea2000434edc471c9de5b578e0a463f`, source `1ca59e0d038b594b87c0dd5b4c78b0711b022043`, reference fingerprint `08142b3db56be09744cfd635535db2fded87e230c02372b036d342b0deb2e8cf`, and payload 528,309,685 bytes. Its cutoff is `eligible_before: [2026, 10]` versus V1.6's `[2026, 11]`. V1.6 is 81,617,888 bytes (15.45%) larger. The later cutoff may explain part of that difference; this profile has not performed a same-window V1.7 attribute comparison.

### V1.6 load, seed and cache measurements

Two isolated profiles used the exact package above with `/usr/bin/python3.12` on the fast host. The load-only attribute profile completed deserialization in 365.1 seconds. Immediately after `load_pack()` returned, RSS was 2,955,888 KiB, PSS 2,951,242 KiB, and private dirty memory 2,921,380 KiB; load-only `VmHWM` was 2,955,888 KiB and `VmPeak` 3,652,964 KiB. Host `MemAvailable` remained above 7.1 GiB. The profiler safety limits were 4 GiB process RSS and 1.5 GiB host-available memory; neither limit was approached.

A second isolated run executed seeds 300001–300003 with player lines enabled: all 3/3 were valid completed games. After loader return, RSS was 2,955,912 KiB. At the first seed boundary RSS was 2,435,620 KiB; after seeds 300001, 300002 and 300003 it was 2,424,712, 2,414,496 and 2,410,416 KiB. The process high-water mark across loading and these seeds was 3,208,496 KiB (3.06 GiB); the instrumentation did not attribute that high-water mark to a specific seed interval, so no per-seed transient peak is claimed. RSS did not grow across the three seed boundaries.

The sampler `_cells` cache went from 0 entries before seeds to 44, 50 and 53 after the three seeds; its dictionary shallow size was 2,264 bytes at 53 entries. `portable_backoff_groups` remained at 425 entries (18,512 shallow bytes); `_backoff_index` and `_source_support_lookup` remained `None`, and `_source_support_ids` stayed empty. This shows a small cache warming pattern, not multi-gigabyte seed growth. The output held only three records, each with player lines; output buffering is not a credible explanation for the pre-seed footprint.

Raw measurements and reproduction materials are preserved under `docs/research/week12-thanksgiving-blackfriday-slc-2026/artifacts/`:

| Artifact | SHA-256 |
| --- | --- |
| `v1.6-attribute-profile.jsonl` | `ad00dac1a5c34e667537293cab4faca7ff36c303cc6507a2d19aa6d3d4945570` |
| `v1.6-attribute-profile.py` | `62dc91e855e9bc61f7a286e5844a015f71d0e0f3b9c4503dfd7a716fd634f211` |
| `v1.6-profile-instrumentation.patch` | `191b4a69567d10318330a4524e94e423d1351c1a3dcdac96a659b0732de56400` |

The script records the exact package SHA, pinned model commit, snapshot path and seed IDs. `git apply --check` passed for the instrumentation patch against the recorded runtime source. No frozen model package, probability, layer or artifact was modified. The separate frozen CEG profile previously measured a 1,985,586-byte artifact and a roughly 4.55 MB shallow reachable object total, with only 258 bytes of reachable-size growth across 10 seeds; its profiling method differs and is only an architectural reference, not a direct apples-to-apples runtime comparison.

Remediation objectives are distinct. (A) Remove unused fields or rows only after proving they do not affect any inference branch; retain all seed behavior and full record equality. (B) Eliminate duplicate representations by adding reference-preserving serialization or reconstructing the alias after decode; require exact object-alias assertions and full game-record parity for the same 500 V1.6 seeds, including failures and player box scores. (C) Share immutable decoded state between workers only after measuring PSS/private memory and proving per-game mutation isolation. The measured independent targets are: discard or rebuild stale `_describe_memo` (931.4 MiB RSS increase at its deserialization boundary) and restore `source_pool is pool` (at least 128,831,904 bytes / 122.9 MiB of duplicated shallow containers and rows). These are observed memory-boundary estimates, not guaranteed RSS returned to the OS; test each independently before combining. Removing historical fields or rows still requires inference access tracing. Every model change requires exact normalized records for seeds 300001–300500, including player box scores, failures and RNG stream identities. Sharing additionally requires proof that mutable caches and simulation state remain isolated. The audit measured package and model memory only; no frozen behavior was changed, and no forecast batch was run for profiling.
