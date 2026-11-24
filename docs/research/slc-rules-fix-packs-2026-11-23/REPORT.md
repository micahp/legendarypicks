# SLC packs with the blocker fixes and the v1.6 geometry filter

Date: 2026-11-23. The pack registry now points v1, v1.5 and v1.6 at rebuilt packs. v2, pbv1, pbv1-off and v1.7 are
unchanged. The old packs and the old registry are kept.

## Why

In week 11 (13 games, 100 seeds each) v1 lost 56 seeds and v1.5 lost 41 to unsupported cells, and v1.6 lost 2 to an
engine error (`docs/issues/slc-v1-v15-unsupported-cells.md`, `docs/issues/slc-v16-sack-fumble-own-end-zone-error.md`).

- v1 and v1.5: the engine code at their commits has the five blocker fixes (`e2_reference.BLOCKER_FIXES`), but the
  registry built their packs with `build_args: []`, so the fixes were off. The non-pack runs (`run_week8_smoke.py`) had
  them on. The code is unchanged; only the build arguments change.
- v1.6: a `sack_fumble_lost` source row could carry the ball behind its own goal line. `cf8fd47b`
  (`fix/slc-v1.6-rules-2026-11-23`, on top of `1bb3bd50`) ports the V1.7 geometry filter behind
  `--slc-geometry-filter`, off by default, and the v1.6 build turns it on. Only v1.6 has a separate sack-fumble event,
  so the other models do not need it.

## The table

| model | code commit | pack sha256 | change |
|---|---|---|---|
| v1 | `58ef3861` (same) | `bc1c8544c919` (was `6286d341b21d`) | five blocker fixes on |
| v1.5 | `2eab8a89` (same) | `0d94303e03a2` (was `727820b921ce`) | five blocker fixes on |
| v1.6 | `cf8fd47b` (was `1bb3bd50`) | `16092cde8640` (was `6cf1e83677dc`) | geometry filter on |
| v1.7 | `1ca59e0d` | `db1d2c364332` | unchanged |
| v2 | `8a1d9842` | `97c4a01e9a60` | unchanged |
| pbv1 | `8a1d9842` | `774366599e23` | unchanged |
| pbv1-off | `8a1d9842` | `48cca8b62f36` | unchanged (research ablation, not in the weekly default) |

Full hashes: `registry.json` in this folder (a copy of the fast host's pack registry).

## Where things are on the fast host

- Current packs and registry: `/root/runs/week-11/inputs/models/portable-models-2026-11-23-rules-fix/`. Unchanged packs
  are hard links to the old files.
- Old packs and registry, untouched: `/root/runs/week-11/inputs/models/portable-models-2026-11-19/`.
- Model registry (`slc_model_registry.py` in `/root/lp-slc-portable-runtime`): v1 and v1.5 build with
  `_SHARED_BLOCKER_FIX_ARGS`; v1.6 is pinned to `cf8fd47b` and builds with `--slc-geometry-filter`. The old file is
  `slc_model_registry.py.before-rules-fix-20261124`; its pinned tests were updated the same way
  (`test_slc_model_registry.py.before-rules-fix-20261124`). Registry and pack tests: 35 pass.
- Because the registry now pins v1.6 to `cf8fd47b`, the old v1.6 pack (`1bb3bd50`) runs only with the old registry file.

## Build inputs

Built with `slc_cli.py pack build` from a copy of the runtime (`/root/runs/week-11/rules-fix-runtime`), on the week 11
inputs: snapshot `2026_11_ARI_KC.portable.json`, `/root/runs/week-11/inputs/picks.frozen.db`, the playcall artifact from
each model's source tree, `ari-kc-streaks.json`. v1.6 also used the 2026 play-by-play
`/root/lp-snapshots/nfl-backfill-2026-11-17/raw/pbp/play_by_play_2026.parquet` (sha256 `32334d4a...`, the same as the old
v1.6 pack) and a rebuilt materialized history, `slc-materialized-history-v16rules.sqlite` (1,237 games, 214,528 rows). It
had to be rebuilt because it pins the hash of `e1_drive.py`, which the fix changes.

## Checks

1. **The inputs reproduce v1.** v1 rebuilt from these inputs with no fixes gives the same scores and box scores as the
   original v1 pack on CIN at WAS seeds 300001 to 300003. So the only change in the new v1 pack is the fixes.
2. **Smoke tests.** v1 and v1.5: 26 of 26 one-seed runs over the 13 week 11 games passed the postflight.
3. **Every failed week 11 seed now finishes.** v1 56 of 56, v1.5 41 of 41, v1.6 2 of 2, all with the postflight passing
   (no excluded player with stats, every passer the resolved QB1). Seeds were run alone with a `--seed-list` option in
   the runtime copy; a seed run alone gives the same game as in a range (3 of 3 CIN at WAS seeds identical).
4. **End-to-end.** The weekly default models (v1, v1.5, v1.6, v2, pbv1) through the live runtime and the new registry,
   one seed on all 13 games: `SMOKE_TEST_PASSED 65 runs` (2026-11-24, `smoke-registry-rules-fix-2026-11-24`). This is
   also v1.6's smoke test.

A seed is not the same game in the old and the new pack: the fixes change draws before the point where the old seed
stopped. The fixed packs must be evaluated as new runs, not spliced into the old week 11 results.
