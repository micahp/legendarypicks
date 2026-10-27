# E3 possession-duration comparison: week-5 starts, weeks 1–4 training

## Result

This is the next E3 realism check from the delivery plan: possession duration. It compares observed 2022 week-5 PBP drives with the pinned E1 empirical drive generator, whose donor pool is restricted to weeks 1–4. The initial state for each generated drive comes from an observed week-5 drive start; the simulated outcomes do not.

The metric is same-quarter **game-clock seconds**, from the first scrimmage snap through the PBP row immediately following the final E1-vocabulary play. It does not measure wall-clock time between possessions.

| Measure | Observed week-5 drives | E1 generated from those starts |
| --- | ---: | ---: |
| Drive count | 61 paired starts | 198 successful generated drives |
| Mean game-clock duration | 161.639 s | 139.899 s |
| P10 / median / P90 | 50 / 121 / 335 s | 52 / 124.5 / 258.9 s |
| Mean scrimmage plays | 6.770 | 5.859 |
| Median scrimmage plays | 6 | 5 |

Mean per-start expected absolute duration error is 106.203 seconds, averaged across available E1 draws for each paired start. E1 attempted five draws for each of 66 starts with supported training cells (330 attempts); 198 draws remained after incomplete simulations and quarter-crossing or clock-clamped simulations were excluded. The original observed PBP cohort contains 73 same-quarter drives; 7 more lacked E1 start-cell support, and five supported starts yielded no retained simulation.

This points to a duration-distribution difference worth tracking: generated drives have a similar median, but lower mean and a shorter upper tail, and they use fewer plays at the median. This is descriptive development evidence, not a promotion result.

## Scope and limitations

- The database query is fixed to season 2022, weeks 1–5. The E1 donor pool uses weeks 1–4 only; week 5 supplies observed starts and comparison targets.
- Starts are conditioned on observed week-5 quarter, clock, offense, defense, down, distance, and yardline. Field direction is the E1 authored `dir=+1` convention.
- PBP terminal events and subsequent states are not supplied to the generator. The observed terminal family is used only to stratify the report; generated outcomes are sampled normally from the training pool.
- Drives crossing a quarter boundary or with unresolved clock stamps are excluded. Generated drives with quarter changes, clock clamps, or incomplete runs are excluded and counted.
- The metric captures game-clock runoff only. PBP does not provide whistle times or stoppage durations, so this is not elapsed real-world possession duration.
- Weeks 6–9 were already examined in prior E3 work. **This comparison is not holdout-validated.**

## Reproduction and pins

```bash
python scripts/bdb/e3_possession_duration_comparison.py \
  --output docs/evidence/e3/possession-duration-comparison-weeks1-5-2026-10-24.json
```

- PBP slice SHA-256: `4e39e51ab30931ff1f5cda0ee44052a2edad59d3ced7e7cfcd73b4dece21dc13`.
- E1 commit: `2248f7e1f9710daa3092104526ab6003a0fc3b18`.
- E1, E0 bucket, and reducer source hashes are verified by the builder and recorded in the JSON.
- Comparison script SHA-256: `cb9ee6c2b44e750dd93a80e5e9a4d6068785d53a3b8f9ecabb3fe280ab73da71`.
- Machine-readable result SHA-256: `0bc744713f10af22658ba26e42b6a327ed7909695132e08d0bf541b1ca1052a3`.
