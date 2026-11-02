# Year-by-year PBV1 comparison

Primary target is `package_comparable` at K=20. RB-only SLC is the sensitivity, also at K=20. Intervals use paired game-clustered bootstrap resampling with 10,000 draws and seed 20261102. Mean log likelihood uses plays supported by all three arms. Unsupported counts are listed as sampler / B0 / B1.

Only seasons 2022 to 2025 were loaded. No 2026 data was used. The 2023 and 2024 rows were calculated with the existing `pbv1_eval.fold_metrics` function. The previously exposed 2025 rows were carried forward from the existing scored outputs and were not rescored or tuned.

| Target | Fold | Test plays | Comparable plays | Mean log likelihood sampler / B0 / B1 | Sampler minus B0 (95% CI) | Sampler minus B1 (95% CI) | Unsupported sampler / B0 / B1 | Package TV |
|---|---|---:|---:|---|---|---|---|---:|
| package_comparable, K=20 | Fit 2022, score 2023 | 33761 | 33580 | -1.06172 / -1.12112 / -1.06140 | +0.05940 (+0.05356 to +0.06515) | -0.00033 (-0.00065 to -0.00001) | 8 / 0 / 181 | 0.02705 |
| RB-only SLC, K=20 | Fit 2022, score 2023 | 33761 | 33571 | -0.97757 / -1.01455 / -0.97732 | +0.03698 (+0.03094 to +0.04281) | -0.00025 (-0.00056 to +0.00005) | 10 / 0 / 190 | 0.09817 |
| package_comparable, K=20 | Fit 2022 to 2023, score 2024 | 33252 | 33181 | -1.04405 / -1.11072 / -1.04368 | +0.06668 (+0.06141 to +0.07205) | -0.00037 (-0.00058 to -0.00017) | 4 / 0 / 71 | 0.03153 |
| RB-only SLC, K=20 | Fit 2022 to 2023, score 2024 | 33252 | 33171 | -0.94066 / -0.99167 / -0.94030 | +0.05102 (+0.04573 to +0.05640) | -0.00036 (-0.00054 to -0.00019) | 3 / 0 / 81 | 0.05430 |
| package_comparable, K=20 | Fit 2022 to 2024, score 2025 | 32657 | 32608 | -1.14114 / -1.21019 / -1.14122 | +0.06905 (+0.06273 to +0.07520) | +0.00007 (-0.00015 to +0.00032) | 8 / 0 / 49 | 0.04940 |
| RB-only SLC, K=20 | Fit 2022 to 2024, score 2025 | 32657 | 32620 | -0.99531 / -1.04414 / -0.99545 | +0.04882 (+0.04279 to +0.05453) | +0.00014 (-0.00008 to +0.00038) | 6 / 0 / 37 | 0.05842 |

## Comparison with REPORT.md

Checked 52 reported numeric fields at the precision shown in `REPORT.md`, using decimal ROUND_HALF_UP. Mismatches: 0.
- No mismatches.
- `REPORT.md` does not include RB-only 2025 mean log likelihoods, unsupported counts, or package TV. Those fields are included above from the existing retrospective output.

The primary 2025 fold is previously exposed and retrospective only. Its saved result is reported without a new scoring pass.
