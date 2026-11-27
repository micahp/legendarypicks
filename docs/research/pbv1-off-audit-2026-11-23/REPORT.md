# Why pbv1 and pbv1-off give identical results

Date: 2026-11-23. A one-time audit. pbv1 itself is not changed, and no batch was rerun.

## Result

**The switch works, but it has no effect on the game.** pbv1 is a label-only integration: it replaces the play's
personnel label, and nothing that decides the play reads that label. It is not bypassed and it is not compiled
incorrectly.

## Evidence

1. **The outputs are identical, seed for seed.** All 13 week 11 games: pbv1 and pbv1-off have byte-identical outcomes and
   player box scores for every seed (`docs/research/week11-rerun-preflight-2026-11-23/`, 1,300 seeds each).
2. **The pack is compiled correctly.** Each week 11 pack was loaded on the fast host:
   - pbv1 (`774366599e23...`): `contextual_sampler.pbv1_model` is a `pbv1_package.Model`, and its recorded build arguments
     include `--playcall-pbv1-package`.
   - pbv1-off (`48cca8b62f36...`): no `pbv1_model`, and no pbv1 build argument.
3. **The switch fires at runtime.** One seed of CIN at WAS (seed 300001, the week 11 rerun snapshot), with the decision log
   on:
   - 136 plays each. The personnel label differs on 49 plays (pbv1: 92 `11`, 28 `12`, 3 `21`, 3 `10`, 2 `13`;
     pbv1-off: 88, 28, 4, 1, 6).
   - Every other decision field is identical. So are the box score and the final score.
4. **Nothing reads the label.** Code commit `8a1d9842`, shared by pbv1, pbv1-off and v2:
   - `pre_event.choose` draws the PBV1 package after the formation draw and writes only `chosen['personnel']`.
     It draws from its own named stream (`{base}:pbv1`), so it never moves another draw.
   - The runner, receiver and passer are chosen before that line.
   - The only readers of `personnel` are the decision log (`slc_playcall.py:797`) and the per-game trace
     (`slc_engine.py:486`). Outcome sampling uses `formation`, not `personnel`.
   - The registry names the flag this way: `"pbv1_integration": "label_only"`.

## Side finding: the reference hash does not see pbv1

The two packs have the same `reference_sha256` (`8e1171dc...`), but one carries the pbv1 model and one does not. The
reference fingerprint leaves out `pbv1_model`, so the registry cannot tell the two references apart by that hash. The
pack sha256 does differ. Use the pack hash, not the reference hash, to tell variants apart.

## What changed

- pbv1-off is no longer in the default weekly batch: `run_portable_batch.py` now defaults `--models` to
  `v1,v1.5,v1.6,v2,pbv1` (`74830f9d`). The pbv1-off pack, its registry entry and its earlier results are kept. It runs
  only when named in `--models`.

## What this does not decide

- Whether pbv1 should drive outcomes. That needs a reader of the label (for example the formation and personnel outcome
  layer keyed on personnel), which is a new model, not a fix.
- Until then, pbv1 and pbv1-off are the same model for every number we report.
