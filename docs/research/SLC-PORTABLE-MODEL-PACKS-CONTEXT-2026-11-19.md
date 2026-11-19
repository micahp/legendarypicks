# SLC Portable Model Packs — Project Context

Updated 2026-11-19

## Goal

Export each SLC model family as a versioned, self-contained runtime package. The intended coverage is V1, V1.5, V1.6, V1.7, V2, and PBV1. A portable run should use a selected model, frozen pregame inputs, and explicit seeds without a database, loose research fixtures, or retraining.

Every standard package must support full games, including overtime. Preserve each model's original rules policy, code version, and experimental switches. Do not promote or merge until each supported variant passes portable-versus-legacy parity.

## Current implementation

The portable runtime bundles pinned engine code and JSON-serialized model state in a checksum-protected package. Its runner blocks database connections and research-table or fixture reads.

**V1 is the only enabled package builder so far.** V1.5, V1.6, V1.7, V2, and PBV1 remain gated pending their exact loaders, policies, artifacts, and parity work. Full-family export is not complete.

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

For WAS–NYG, seed `300001`:

- Pack SHA-256: `9403c9f63e764720799c8a4bd43a67f3fd3554716abc7692a1c4f39bd2078514`; reference SHA-256: `168b59885d1cc5cbe6a60e4560a8017942afad8e26bf4057d2ea1ab7b58019b5`.
- RNG v2 stream root matched legacy: `6d1979d6404e6cbc9cfd383fd02a041710c6790173a194c50b11e4c5e8fddc0f`.
- Portable execution passed preflight and completed the game.
- The complete portable game record matched the legacy record exactly, including transitions, score, and statistics.
- Portable source-read guards were active during execution.

Focused verification passed: 5 tests, Python compilation, and `git diff --check`. This establishes one-seed WAS–NYG parity. It does **not** complete the two-game, 10-seed, 100-seed, or full-family parity gates.

## Branch and working tree

Commit `6eb4a49ded7d270bdc43f26de0ae97d320fe5357` is pushed to `feat/slc-portable-model-packs-2026-11-18`. The local branch is `feat/slc-v1-executable-package-2026-11-18`. The remote branch was verified at the same commit. `dev` remains unchanged.

The V1 model card records an earlier package and its failed 10-seed comparisons. Its addendum describes the separate one-seed exact-parity run above; the two artifacts and results should not be conflated.
