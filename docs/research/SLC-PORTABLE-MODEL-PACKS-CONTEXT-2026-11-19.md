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

The portable loader streams JSON into objects, but constructs separate Python objects and copies decoded NumPy arrays. The runner deep-copies the game snapshot per seed. Its `rows` and player-box-score `details` lists grow with attempted seeds; optional full records and decision traces also accumulate until output. These are output buffers, not evidence of a leaking cache. The inspected V2 play-call sampler builds `_cells`, grouped outcome counters, sorted row lists, `_team_transition_groups`, and, when enabled, a backoff index lazily. They can grow as previously unseen cells are visited across seeds; retained sizes, ceilings, and behavior in every other pinned engine remain unmeasured. Group lists may contain references to existing rows rather than independent copies: object identity profiling is needed to distinguish the two.

Read-only, immutable fitted tables and historical rows are candidates for sharing across workers. Mutable per-game state, RNG streams, snapshot copies, decision traces and mutable caches need isolation or a verified shared read-only representation. A fork or memory map is not automatically safe or effective: copy-on-write behavior, object mutation, platform, provenance and parity must be measured. CEG currently unpickles its artifact in each worker initializer and collects results in the parent.

Counts and weighted aggregates can replace individual historical rows only when they retain every value used by eligibility, conditional filtering, transition and participant weighting, attribution, downstream state, and any required row identity. The inspected V2 sampler selects historical rows after formation, coverage, streak and label conditioning, player weights and transition grouping; a single unconditional count or mean cannot preserve that joint distribution. Exact grouped representations may be possible for rows proven equivalent across all relevant fields, with multiplicity and ordering retained where seed parity requires it. This has not been demonstrated.

Still required for a complete census: profile every pinned V1, V1.5, V1.6, V1.7, V2, PBV1 and CEG artifact independently; enumerate retained object graphs with shared-reference accounting and native allocations; measure load peaks and growth over seeds; trace field access across representative games and all conditional paths; compare dataset identities and cached indexes; and validate any compression or sharing proposal against full seeded records. No field is declared unused on the basis of this source inspection alone.
