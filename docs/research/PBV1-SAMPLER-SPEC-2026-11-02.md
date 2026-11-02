# PBV1 package-level sampler: pre-registered spec, 2026-11-02

Status: pre-registration. Written before any PBV1 model is fitted or scored. Research only. No SLC default change. No 2026 result is read. The owner approved the package code on 2026-11-02 (RB+FB for cross-season comparisons, RB-only retained for SLC, 2022 fullback coding uncertainty preserved).

Data source: the validated HPV1 contract, built by `pipeline/hpv1_build.py` (`season_frame`) in the Gridiron research repository. The HPV1 contract is the data source and identifier; PBV1 is the experiment name.

## 1. Population

- Regular-season (`season_type == REG`) plays with `play_class == scrimmage`, offense team `posteam`, seasons 2022 to 2025.
- Excluded classes (HPV1 contract): two-point, fake kick, cross-side label, other, participation only. Excluded plays are counted, not dropped silently.

## 2. Target and cells

- **Target:** `package_comparable` (RB + FB). This is the cross-season code. Sensitivity target: `package` (RB-only, SLC representation), reported separately.
- **Play family:** `play_type` run or pass.
- **Cell:** (play family, down 1 to 4, distance bucket from the HPV1 buckets, red zone 0 or 1). Formation is recorded but not in the cell, because 2022 formation labels have no verified mapping to 2023 onward.
- **Parent:** (play family, down). The parent is the cell's backoff.

## 3. Sampler (primary)

For a cell c with training count n_c and training package counts n_cp:

P(p | c) = (n_cp + K * P(p | parent)) / (n_c + K), with K = 20 fixed and P(p | parent) the parent's empirical package distribution.

Support rule: the sampler gives mass only to packages observed in the training data for the cell's parent. Packages never observed in the parent get zero mass. This is the "observed joint combinations only" rule of the HPV1 contract.

Fixed before fitting: K = 20. K is not tuned.

Sensitivity (reported, does not change the verdict): K = 5 and K = 80.

## 4. Baselines

- **B0, package marginal:** the training season's package distribution, no cells.
- **B1, unshrunk cell:** n_cp / n_c on each cell. Packages unseen in the cell have zero probability. Their log loss is undefined, so B1 is scored on supported plays only and its unsupported rate is reported.

## 5. Folds

| Fit | Score | Role |
|---|---|---|
| 2022 | 2023 | development |
| 2022 to 2023 | 2024 | development |
| 2022 to 2024 | 2025 | previously exposed retrospective; scored once, no tuning |

## 6. Metrics (test season)

1. **Conditional log likelihood** per play of the observed package, mean and paired game-clustered 95% CI for the difference between the sampler and B0 and between the sampler and B1 (supported plays).
2. **Package frequency:** total variation distance between the mean predicted package distribution and the observed test share, with the per-package table.
3. **Unsupported-combination rate:** the share of test plays whose package has no training support for its parent.
4. **Zero rates:** the share of test plays for packages with zero training count overall.
5. **Team opportunities:** observed scrimmage plays per team-game, training mean against test mean. Descriptive only: PBV1 does not simulate opportunities.
6. **Workloads and named-player participation:** not evaluated. Named-player participation waits for the eligibility mechanism (owner ruling E).

## 7. Uncertainty

Paired game-clustered bootstrap over game ID. 10,000 draws, seed 20261102 (the owner's selected settings, from the M3 freeze amendment). Games, not plays, are the resampling unit.

## 8. Fullback coding uncertainty

The 2022 season has no FB token, so 2022 fullback plays are coded as RB. The package_comparable code merges RB and FB, which absorbs this for cross-season comparison. Report the 2022 package shares next to the 2023 shares, and state that the 2022 fullback coding is inferred, not labelled.

## 9. Decision rule

This spec does not promote the sampler. It reports the metrics above for the two development folds and the retrospective fold. A sampler "passes" PBV1 Milestone 2 only if: (a) its log-likelihood gain over B0 is positive with a 95% CI above zero on both development folds; (b) its unsupported-combination rate is at or below the B1 rate on the same folds; and (c) the retrospective fold agrees in sign. Failure is reported as failure.
