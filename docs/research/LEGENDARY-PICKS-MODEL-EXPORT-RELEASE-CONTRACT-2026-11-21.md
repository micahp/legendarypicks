# Legendary Picks: model export and application release contract

Status: **proposed, non-production policy** (2026-11-21). This document does not publish, promote, or deploy a model.

## Three independent identities

- **Application release**: the Legendary Picks application version and exact application Git commit/tag (e.g. `v10.2.0`).
- **Model release**: immutable model-family version and export build (e.g. `nfl-slc-v1@1.0.0`), with source repository commit and runtime SHA-256. Do not infer the model commit from the application release tag.
- **Simulation run**: the existing write-once run registry's `run_id`, with its seed, snapshot, source and result hashes. Run IDs are not model releases.

One application release can include several model families and versions. The same model export can be used across several app releases without rebuilding or relabeling it. A new model export should get a new immutable release ID whenever its bytes, code, rules, or required data dependencies change.

## Existing packaging (implemented on model-pack feature branches)

The export system **already exists**, but is not merged into `dev` as of the inspected `dev` commit `74579b70`. Do not reimplement it. Implementation branches:

- `feat/slc-portable-model-packs-2026-11-18` (inspected head `e0e2f861`)
- `feat/slc-v1-executable-package-2026-11-18` (inspected head `fb327c77`)

Existing source files in `scripts/nfl_sequence/`:
- `compile_portable_pack.py` builds the `.slcpack` from the model's pinned clean source, including a one-seed smoke.
- `portable_model_pack.py` defines immutable ZIP-based schema `lp-slc-portable-model-pack-1` with `manifest.json`, `reference.json`, and bundled `engine/` code. It already records `model_code_commit`, `engine_files_sha256`, `reference_sha256`, `snapshot_sha256`, `training_cutoff`, `runtime_dependencies`, and source-artifact hashes. Existing writer refuses overwrite.
- `simulate_portable_pack.py` executes the exported runtime with a new frozen snapshot and no source database, independently validating the externally provided pack hash and commit.
- `compare_portable_parity.py` performs seed-level comparison of original and exported records.
- `test_portable_model_pack.py`, `test_portable_runtime.py`, `test_portable_parity.py` cover packaging and no-DB execution.
- `slc_model_registry.py` identifies source commits and model configurations; model variant status and parity must be assessed independently.

Thus `build-model-export` and most `verify-model-export` functionality **already exist**. The release task is to **reuse, merge, orchestrate and gate** them, not create a competing implementation.

## Required application-level release binding

The existing `.slcpack` already contains an authoritative internal manifest. At release time, wrap or reference it with a **small external release index**, not a second incompatible package schema. Example:

```json
{
  "schema": "legendarypicks-model-export-v1",
  "model_id": "nfl-slc-v1",
  "model_release": "1.0.0",
  "model_status": "research",
  "source_repository": "micahp/legendarypicks",
  "source_commit": "<full 40-character commit>",
  "source_tree_clean": true,
  "rules_version": "<hash>",
  "runtime": {
    "artifact_name": "nfl-slc-v1-1.0.0.slcpack",
    "sha256": "<64-character SHA-256>",
    "format_version": "lp-slc-portable-model-pack-1",
    "entrypoint": "scripts/nfl_sequence/simulate_portable_pack.py"
  },
  "dependencies": [
    {"name": "historical-reference", "sha256": "<64-character SHA-256>", "delivery": "external-pinned"}
  ],
  "verification": {
    "command": "<replay/smoke-test command>",
    "fixture_sha256": "<64-character SHA-256>",
    "result_sha256": "<64-character SHA-256>",
    "status": "passed"
  }
}
```

The index above is an **illustration only**; the existing `.slcpack` manifest is the authoritative model payload, and angle-bracket values are placeholders. Validate the external index against the actual pack manifest. Existing build and loader already check many of these properties; do not duplicate them unnecessarily. Add only release-level checks for immutable artifact location, parity results, readiness, and application lock correctness.

A model that still fails its own realism or validation gate (such as V1-Pure's intra-play execution gate) must remain `research`, not `production`.

## Application release manifest

Every production application release should publish `model-lock.json` next to its deployment artifact:

```json
{
  "schema": "legendarypicks-app-model-lock-v1",
  "app_version": "10.2.0",
  "app_commit": "<full 40-character commit>",
  "models": [
    {
      "model_id": "nfl-slc-v1",
      "model_release": "1.0.0",
      "model_source_commit": "<full 40-character commit>",
      "runtime_sha256": "<64-character SHA-256>",
      "export_manifest_sha256": "<64-character SHA-256>",
      "deployment_role": "shadow"
    }
  ]
}
```

Illustration only; **not** an assertion that these versions are deployed. Roles: `production`, `shadow`, `research`, `disabled`. Only `production` may serve public forecasts. A release must resolve every model artifact and verify every hash before deploy. Production boot must verify the lockfile against the installed runtime and refuse to silently substitute another model.

The deployed forecast output should record `app_version`, `app_commit`, `model_id`, `model_release`, `model_source_commit`, `runtime_sha256`, `rules_version`, and `run_id` (when available). Store the lockfile's own hash on the deployment.

## Release flow

1. Finish and test the model on its research branch. Merge approved changes to the canonical **V1 branch** via review, preserving the original commit history and the full commit SHA.
2. Use the **existing** `compile_portable_pack.py` on a clean pinned model commit, with a deterministic command. Do not create the model from a moving branch tip.
3. Reuse the compiler's one-seed smoke, then run `simulate_portable_pack.py` and `compare_portable_parity.py` for the mandatory independent no-DB parity gate before production. Validate dependency hashes and model-specific release gates.
4. Produce the model export manifest and artifact; upload both as immutable, content-addressed release assets. Do not rewrite an existing model release or its assets.
5. Prepare the app release from its own pinned commit; generate a lockfile referencing approved model releases. Deploy both atomically or fail closed. A model release need not coincide with an app version bump, but any **production model change requires a new app deployment/release lock**.
6. Attach the app lockfile to the application release and retain all referenced model artifacts. Verify after deployment by reading the live app's model lock and running one known fixture.
7. Roll back the **app and model lock together**; preserve historical exports and manifests for reproducibility.

## Existing code to reuse

- `scripts/nfl_sequence/versions.py` stamps clean engine code and rule-file hashes. Preserve these fields, but also capture the **full source commit** and exported-runtime hash; `model_version` alone is the most recent engine-file commit, not necessarily the entire export source.
- `scripts/nfl_sequence/sim_run_registry.py` is a write-once **simulation run** registry with payload hashes; do not repurpose run IDs as model releases.
- `scripts/nfl_sequence/slc_family_runner.py` already extracts per-model Git refs into runtime trees; require pinned commit SHAs and verify their runtime/export manifests when used for released models.

## Immediate work: automation and integration, not packaging

1. Review and merge the **existing** model-pack feature branches into the appropriate integration branch. Do not silently promote incomplete variants; only ready models can be made available in a production lock.
2. Add a release orchestration wrapper around `compile_portable_pack.py`, `simulate_portable_pack.py` and `compare_portable_parity.py` and capture their exact commands, pins, outputs and pass/fail status.
3. Add CI preflight that checks clean source, full commit pin, externally verified pack hash, successful exported-runtime smoke, no-DB parity, correct model identity and unchanged release artifacts. A clean packaging result alone is not proof of model accuracy or realistic intra-play football.
4. Integrate with existing `scripts/release.sh`, which performs the app version bump, commit, tag and push, and currently creates a GitHub Release on major/minor versions but not patches. Every app tag should receive an immutable model-lock association; decide whether patch tags need their own published asset or a pinned off-repo lock record.
5. Publish an immutable `.slcpack` and its independent SHA-256 in the chosen release artifact store; bind it to the app release lock. Verify installed pack hashes and identities at deploy and boot; rollback app and model lock together.
6. Backfill provenance only for exports whose actual commits and hashes can be verified. Never fabricate provenance or declare an unfinished research model production-ready.

**No application release, model export promotion, branch merge or deployment was executed by this document change.**
