# SLC portable model packs: table-free runtime contract (2026-11-18)

Status: implementation and initial V1 parity evidence; branch `feat/slc-portable-model-packs-2026-11-18`. One frozen WAS–NYG seed now has exact portable-versus-legacy parity. V1 has not passed the multi-seed acceptance gate.
Owner decision: model loading is a one-time build concern, not a per-simulation requirement. Every supported full-game model must include overtime. No change to `dev` or production until validated.

## Current implementation status (updated 2026-11-19)

**Executable V1 package implementation; not yet parity-certified.** The pushed branch contains:
- `portable_model_pack.py`: SHA-256 checked archive containing bundled Python engine code and schema-defined JSON model state, with full-game dependency preflight.
- `slc_model_registry.py` and `slc_cli.py`: central pinned model policies and build/run commands. V1 is the only enabled builder. `slc pack build --all` now fails before writing anything while any family remains unsupported.
- `compile_portable_pack.py`: captures the initialized reference from the pinned legacy loader and strips memoized and current-game streak context from reusable reference state.
- `simulate_portable_pack.py`: loads executable code from the package and blocks database and external research-table reads. For models with the streak layer, it requires a snapshot envelope containing the hash-pinned pregame snapshot and checksummed `runtime_model_inputs` with the full frozen streak table.
- `capture_legacy_parity.py` and `compare_portable_parity.py`: full-record legacy capture and per-seed comparison tooling.

**Acceptance status:** An earlier V1 artifact was compared against legacy V1 for 10 matching seeds on two frozen games; both comparisons failed exact full-record parity (WAS–NYG: 50 field mismatches; JAX–BAL: 70). After matching RNG v2 and the complete frozen model inputs, a separate WAS–NYG run using seed `300001` matched the legacy full record exactly. This is one-seed evidence, not completion of the multi-seed acceptance gate. V1 is not parity-certified. V1.5, V1.6, V1.7, V2, and PBV1 remain disabled. Do not merge to `dev` until every variant passes parity and isolation gates.

See the [V1 portable runtime/model card](SLC-V1-PORTABLE-RUNTIME-MODEL-CARD-2026-11-19.md) for artifact hashes, size, dependencies, and validation evidence.

The executable CLI requires model-specific build inputs on the data host. `slc simulate --model ...` uses the installed package plus a new game's snapshot. When the selected package enables the current-streak layer, the snapshot envelope must include a cutoff-matched `model_reference.current_streak_context` and its checksummed `runtime_model_inputs` table. See the [project context note](SLC-PORTABLE-MODEL-PACKS-CONTEXT-2026-11-19.md) for the envelope format and latest parity evidence.

## Goal

The slow/data host has SQLite tables and the pinned research fixtures. Use them **once** to build a self-contained, immutable model artifact; thereafter a simulation runner needs only the model artifact, an immutable pregame snapshot (possibly embedded), the code/runtime matching the artifact, seed range and output path. It must never open the source SQLite database, refit historical features, read a loose fixture, or silently omit a model layer. Retain the legacy table-loading path for reproducibility and validation, but make portable execution the normal deployment path.

A pack may contain *materialized data structures*: "no tables" means no external table/database/CSV lookup at inference, not that a predictive model can run without trained distributions.

## Scope: no omissions

Supported model identities: S0 control as needed for calibration, SLC V1, V1.5, V1.6, V1.7 (including the real penalty-policy path), V2 (including 2026 PBP release), PBV1 off/on and subsequent PBV1-participation-field coupling. Preserve their distinct code commits and configuration. Never silently substitute a V1 profile on V2 code for V1.5, V1.6, V1.7 or V2.

The build dependency closure must include, as applicable:
- Play-by-play outcome pools, clock/runoff and kickoff pools by season/rule regime, per-play participant lookup, position usage, fitted pass-call parameters, special teams and kick/try probabilities.
- Overtime drives, overtime choice/coin-toss policy, overtime try fallback; safety free kicks, blocked punts and kicks, missed FG transitions, geometry, penalty rules/transitions and their support.
- Score/clock model, team offense/defense strengths, transition strengths, formation and personnel, coverage, decisions A–N, playbook priors, score/streak layers, QB tendencies, scramble/turnover/sack models, player shares, player outcomes, snap/participation field, kicker-specific outcomes.
- PBV1 model coefficients/distribution/support/fallbacks plus integration mode `label_only` or `coupled_lineup`. A PBV1 label-only pack must **not** masquerade as a predictive improvement.
- Any fixture/data dependency touched later by `slc_engine.play`, `game_state.play_game`, validation, box-score export or prop aggregation; the pack builder owns the complete closure.

Do not rely solely on `--overtime-table` or caller flags to make the pack complete. Mandatory features belong to its manifest and validated loaded reference.

## Artifact levels

1. **Model/core pack**: immutable trained reference distributions, all play/transition and rule support, policy flags, code fingerprint, source digests, fit seasons and permitted cutoff. Hash-addressed, reusable *where mathematically valid*.
2. **Game overlay**: schedule/venue and roster, canonical player identities, injuries, elevations, kicker, formation/role projections, current-season snap/streak inputs, availability as-of UTC, provenance and confidence. Frozen separately so roster updates don't rewrite model evidence.
3. **Execution pack**: resolved model/core pack + game overlay + final per-game/season fitted layers, if needed. This is the unit sent to the fast host. A pack is never re-used across a different week/cutoff if its training or dynamic inputs would change.

For a first safe release it is acceptable to compile one execution pack **per game x model x cutoff** to avoid accidental reuse across teams/seasons. Optimize shared core storage only after parity passes.

## Archive contract

- Format: `lp-slc-model-pack-1`, immutable single-file archive (e.g. `.slcpack`) with `manifest.json`, `snapshot.json`, and fully materialized reference payload(s).
- Pack SHA-256 is written to an external lock/index and required by the consumer. Individual payload SHA-256s and uncompressed-size limits are in the manifest. Never deserialize untrusted Python pickle files; initial trusted internal compiler may use pickle only with externally pinned digest and exactly pinned code/runtime, then migrate to a safe, schema-defined binary serializer.
- Keys: `game_id`, `as_of_utc`, `model_id`, `model_variant`, `model_source_commit`, `rules_policy`, `rng_protocol`, `seed_protocol`, `schema`, `reference_sha256`, `snapshot_sha256`, `source_cutoff`, `artifact_hashes`, `enabled_layers`, `disabled_layers`, `experimental_flags`, and per-component row/support counts.
- Record `full_game_capable`, `overtime_pool_samples`, `overtime_choice_present`, `overtime_try_fallback_present`, and `missing_required_components`.
- `full_game_capable=true` is forbidden if the overtime pool is absent/empty or an applicable rules dependency is missing. Reject a failed pack at *build time*, not after processing seeds.
- Distinguish `forecast_evidence_status` (verified/provisional/exploratory input) from `valid_full_game` (simulation state and legal completion). Never turn successfully completed games into invalid football simply because historical evidence was not verified.

## CLI target

Build on slow host (source DB and fixtures available, **one time**):
```sh
python3 scripts/nfl_sequence/compile_model_packs.py \
  --game-snapshot /path/frozen-2026_11_IND_HOU.json \
  --models v1,v1.5,v1.6,v1.7,v2,pbv1-label-only \
  --out-dir /path/packs
```

Run on fast host (only code + trusted pack, no DB or fixtures):
```sh
python3 scripts/nfl_sequence/simulate_portable_pack.py \
  --pack /path/packs/2026_11_IND_HOU/v1.7-<sha>.slcpack \
  --pack-sha256 <64-character-SHA> --games 1000 --seed-start 300001 \
  --out /path/results/v1.7.json
```

The above are **target interfaces**, not claims that they already exist or work. The standard family runner should resolve a model ID to a locked pack automatically and reject missing packs; no `--db`, `--playcall-artifact`, `--overtime-drives`, `--playcall-pbv1-package`, `--streak-file` or ad hoc path arguments at run time.

## Build algorithm

1. Freeze verified, as-of-consistent input sources on the data host. Build the full-depth roster and availability overlay independently; never use a later event in an earlier cutoff.
2. Use each model's *real* code commit, flags, penalties and enabled layers; call existing reference loader once. Load all optional artifacts and model tables; resolve source fallback policies explicitly.
3. Compute/retain the current reference fingerprint; enumerate all downstream read dependencies. A missing required file or model-layer mismatch is a **build failure**.
4. Validate full-game capability (overtime drive pool and required rules). Assert nonzero support where appropriate, reject missing/None rather than silently disabling components.
5. Serialize frozen in-memory reference and finalized snapshot; include full provenance, exact code version, Python/runtime compatibility, per-component hashes and model policy. Sign/lock the pack SHA outside the archive.
6. Verify the pack via cold-load in a second isolated process *without* the DB or research-fixtures directory.

## Runtime invariants

- A `--pack` invocation must not call `sqlite3.connect`, load a CSV/parquet from `docs/fixtures` or consult `nfl_pbp`/training data. CI must monkeypatch/block these operations and run with the source directories absent.
- No automatic "try without the unavailable layer" behavior. All enabled layers and their hashes must match the manifest. Frozen V1.6 must remain frozen; the rules-fix arm is a separate model variant.
- Full-game is default. Regulation-end outputs are diagnostic; ties enter supported overtime. If the overtime pool is missing the pack fails its preflight rather than counting tie seeds as completed or downgrading the request.
- RNG streams and reference hashes are pinned so a given model and game inputs reproduce per-seed event and player results exactly.
- An updated injury report or kicker elevation creates a new game overlay and new execution pack, never changes the old one.
- No refitting or model training on the fast host.
- Keep comparable Brier and props outputs but compare like-for-like game sets and prop lines.

## Deployment acceptance gate

A. Inventory every source read in the models' runtime paths; compile with DB/fixtures present and then run with them removed. No source read may occur.

B. For all models (V1, V1.5, V1.6, V1.7, V2, PBV1 off/on), replay at least 100 fixed seeds on at least one valid game. **Portable vs legacy per-seed scores, events, and boxscores must match** for the same code commit/model policy. Preserve PBV1 label-only zero-effect behavior until a separate coupled-lineup experiment is intentionally enabled.

C. Force a regulation tie; confirm the overtime branch is played to a supported terminal state. Force a missing/empty overtime pool; pack building must fail with `MISSING_REQUIRED_OVERTIME_POOL` before a single seed.

D. Confirm 0 DB connections, 0 external model/table/fixture opens, and no fallback to regulation-only.

E. Confirm model variants are not incorrectly aliased: V1.7 must load its true penalty rules; V2 its intended transition/PBP profile; V1.6 frozen and rules-fix variants have distinct hashes; no variant is relabeled to make a pass.

F. Compare 2026 Week 10 and TNF reference results using the same roster, model revisions and common seeds. Report valid full-game coverage separately from input evidence.

G. Only after A–F pass, change the production runner to **require packs**. Archive original fixture-dependent runs and keep legacy path available for research rebuilds.

## Immediate blocker confirmed in code

On `feat/slc-v2-pbp-release-2026-11-17`, `e2_reference.py` constructs the reference by loading source SQLite and multiple `docs/fixtures/e2` files, including `overtime_drives_2022_2025.csv`. In `game_state.py`, a regulation tie enters overtime only if `ref.overtime_pool` is not None. Otherwise the record becomes `overtime_not_modelled`. This is why a ready-to-run model must have the compiled overtime reference rather than depend on per-run loader flags.

Current code's `regulation_only=True` refers to historical pool *filtering*, not disabling game overtime. Preserve that separation.
