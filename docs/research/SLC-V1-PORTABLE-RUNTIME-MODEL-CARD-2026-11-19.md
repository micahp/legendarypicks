# SLC V1 portable runtime/model card

**Status:** Historical V1 package measurement; execution isolation passed, but the 10-seed comparisons recorded here failed. Not parity-certified and not approved for promotion.

## Model identity

| Field | Value |
| --- | --- |
| Model | SLC V1 (`v1`) |
| Engine source commit | `947cb2b836e16fd206e19133fa3d54df510cbb86` |
| Rules policy | `nfl-2026-e2-successor` |
| Training cutoff | Eligible data before season 2026, week 1 |
| Experimental switches | None |
| Reference play pool | `nfl_pbp`, seasons 2022–2025, weeks 1–18; 2026 outcomes excluded |
| Reference hash | `f09a5c6c27c4a25feaaec1cf1195dbb990f74d819a12f0bb7accb6c8c1206fdb` |

The package materializes score and clock play calling, team outcome distributions, formation/personnel and coverage outcomes, player shares and outcomes, QB decisions, target role priors, decision labels and filters, playbook priors, point splits, exact-yardline outcomes, team and league streak splits, and current streak context. The original V1 policy and enabled layers are preserved.

## Portable artifact

The measured artifact is the game execution pack for `2026_10_WAS_NYG`, built at `2026-11-11T23:31:47Z`.

| Measurement | Value |
| --- | --- |
| `.slcpack` compressed size | 19,730,463 bytes (18.81 MiB) |
| Uncompressed payload | 371,256,050 bytes (354.1 MiB) |
| Bundled engine files | 1,152 |
| Pack SHA-256 | `19d80a94ad2d8ecaf6a0bbde0de9198f98737f1181be29418f475c45a6e54904` |
| Pack reference SHA-256 | `f09a5c6c27c4a25feaaec1cf1195dbb990f74d819a12f0bb7accb6c8c1206fdb` |
| Game snapshot SHA-256 | `fd3fab4ced7cba5f8a1cfce17bc25efa1003f5da4c13edcfff07807fafa44cf2` |
| Python ABI | 3.8 |
| Runtime distributions | NumPy 1.24.4; SciPy 1.10.1 |

The archive is compact because the JSON payload compresses well. Deployment storage and load-time memory should be sized against the **354.1 MiB uncompressed payload**, not only the 18.81 MiB archive. The 1,152 bundled files also indicate that engine-code collection is broader than a minimal runtime and should be narrowed as a packaging optimization after correctness is established.

The build host's `picks.dev.db` was 4,247,347,200 bytes (about 3.95 GiB). That database contains data beyond V1's source closure; the exact minimum source-table/fixture footprint has not been measured. The portable runner uses the package plus a game-specific pregame snapshot and does not require that database or loose research fixtures at execution time.

## Full-game support

The pack manifest declares `full_game_capable: true`. Its build checks record 140 overtime-drive samples, 9,963 kickoff samples, 46 safety-kick samples, and 75 play cells. Missing overtime dependencies are a package-build/load failure; regulation-only remains a reference-pool filter and is not a runtime profile.

## Validation and limitations

- The real V1 package was built using the pinned legacy loader and its reference inputs.
- Portable execution completed with the source database and loose research-table access disabled.
- Legacy-versus-portable comparison used identical 10-seed sets for two frozen games and compared full records.
- `2026_10_WAS_NYG`: **failed**, 10 seeds, 50 field mismatches.
- `2026_09_JAX_BAL`: **failed**, 10 seeds, 70 field mismatches.
- Final scores alone are insufficient for promotion; exact transitions and player outputs must also match. These runs did not establish zero-discrepancy parity.
- This artifact demonstrates V1 packaging and isolation, not production readiness. V1.5, V1.6, V1.7, V2, and PBV1 have no certified portable packages yet.

### Subsequent controlled parity check

A separate package was built from a frozen database/reference and tested with RNG v2 after correcting the portable input envelope to carry the complete frozen streak table. For WAS–NYG, seed `300001`, the portable and legacy runs had matching pregame, model-input, and stream-root hashes, and their complete game records were identical. The pack SHA-256 was `9403c9f63e764720799c8a4bd43a67f3fd3554716abc7692a1c4f39bd2078514`; its reference SHA-256 was `168b59885d1cc5cbe6a60e4560a8017942afad8e26bf4057d2ea1ab7b58019b5`.

This later result is a one-seed parity check on a different artifact and frozen reference. It does not revise the measurements above or satisfy the multi-seed promotion gate. See the [portable model-pack context note](SLC-PORTABLE-MODEL-PACKS-CONTEXT-2026-11-19.md) for the current status.

The artifact and parity records were produced in the local work area `/tmp/slc-v1-week10-parity-20261119`; they are not committed as release artifacts. Rebuild from the pinned source and verify the recorded hashes before relying on them.
