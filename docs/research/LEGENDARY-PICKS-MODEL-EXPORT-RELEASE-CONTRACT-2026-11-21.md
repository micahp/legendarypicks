# Legendary Picks: model export and application release contract

Status: **proposed, non-production policy** (2026-11-21). This document does not publish, promote, or deploy a model.

## Three independent identities

- **Application release**: the Legendary Picks application version and exact application Git commit/tag (e.g. `v10.2.0`).
- **Model release**: immutable model-family version and export build (e.g. `nfl-slc-v1@1.0.0`), with source repository commit and runtime SHA-256. Do not infer the model commit from the application release tag.
- **Simulation run**: the existing write-once run registry's `run_id`, with its seed, snapshot, source and result hashes. Run IDs are not model releases.

One application release can include several model families and versions. The same model export can be used across several app releases without rebuilding or relabeling it. A new model export should get a new immutable release ID whenever its bytes, code, rules, or required data dependencies change.

## Required immutable export manifest

Each exported model release must contain a JSON manifest, e.g.:

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
    "artifact_name": "nfl-slc-v1-1.0.0.tar.gz",
    "sha256": "<64-character SHA-256>",
    "format_version": "1",
    "entrypoint": "<relative executable path>"
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

The manifest above is a **schema illustration only**: angle-bracket values are not real hashes or releases. Production tooling must reject placeholders, absent dependencies, uncommitted producing code, mismatched artifact hashes, unverified fixtures and an export that cannot run independently. Define the archive's deterministic build procedure and hash the exact bytes distributed.

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
2. Build an exported runtime **from a pinned clean commit**, with a deterministic command. Do not create the model from a moving branch tip.
3. Run a smoke test and a pinned replay fixture on the **exported runtime**, not only on the source checkout. Validate dependency hashes and any model-specific release gates.
4. Produce the model export manifest and artifact; upload both as immutable, content-addressed release assets. Do not rewrite an existing model release or its assets.
5. Prepare the app release from its own pinned commit; generate a lockfile referencing approved model releases. Deploy both atomically or fail closed. A model release need not coincide with an app version bump, but any **production model change requires a new app deployment/release lock**.
6. Attach the app lockfile to the application release and retain all referenced model artifacts. Verify after deployment by reading the live app's model lock and running one known fixture.
7. Roll back the **app and model lock together**; preserve historical exports and manifests for reproducibility.

## Existing code to reuse

- `scripts/nfl_sequence/versions.py` stamps clean engine code and rule-file hashes. Preserve these fields, but also capture the **full source commit** and exported-runtime hash; `model_version` alone is the most recent engine-file commit, not necessarily the entire export source.
- `scripts/nfl_sequence/sim_run_registry.py` is a write-once **simulation run** registry with payload hashes; do not repurpose run IDs as model releases.
- `scripts/nfl_sequence/slc_family_runner.py` already extracts per-model Git refs into runtime trees; require pinned commit SHAs and verify their runtime/export manifests when used for released models.

## Immediate work before enabling production releases

- Locate and inventory the actual V1/V2 portable export format, required external files and runtime entrypoint. Do not assume the existing source-tree extraction is already a self-contained export.
- Implement `build-model-export`, `verify-model-export`, and `verify-app-model-lock` commands with unit tests and a fixture, using the discovered format.
- Add CI checks on candidate releases: no dirty source, no mutable ref, no missing dependency, no SHA mismatch, no unverified runtime test, no research-only model marked production.
- Add a release job to publish immutable model artifacts and attach the model lock to app releases. Use a **manual approval gate** for initial production rollout.
- Decide artifact retention/storage: GitHub Releases or an immutable object store. GitHub Releases currently list no assets; do not pretend an export has been attached.
- Backfill manifests for existing **verifiable** exports; do not fabricate missing commit or hash provenance.

**No production release or model promotion is authorized by this policy document alone.**
