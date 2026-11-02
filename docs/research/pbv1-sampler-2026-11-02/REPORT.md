# PBV1 package-level sampler: results (SLC v2 Milestone 2), 2026-11-02

Status: research result under the pre-registered spec (`docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md`). No SLC default change. No simulator run. No 2026 result read. Named-player participation and workloads are not evaluated, because the eligibility mechanism has not passed (owner ruling E).

## Data

- Source: the validated HPV1 frame (`pipeline/hpv1_build.py`, `season_frame`), regular-season scrimmage plays, 2022 to 2025.
- Plays: 133,262 regular-season scrimmage plays. Excluded before scoring: 6,536 non-regular-season rows (counted, not silently dropped). No play had an unknown down, distance or red-zone field.
- Target: `package_comparable` (RB+FB). Sensitivity: the RB-only SLC code.
- Games: 272 per season. Test seasons: 33,761 plays (2023), 33,252 (2024), 32,657 (2025).

## Results, primary (K = 20, package_comparable)

Mean log likelihood per play, on plays that all three arms can score (sampler, B0 marginal, B1 unshrunk cell):

| Fold | Role | Sampler | B0 marginal | B1 unshrunk | Sampler minus B0 (95% CI) | Sampler minus B1 (95% CI) | Unsupported: sampler / B1 | Package TV |
|---|---|---:|---:|---:|---|---|---|---:|
| Fit 2022, score 2023 | development | -1.06172 | -1.12112 | -1.06140 | +0.0594 (+0.0536 to +0.0652) | -0.00033 (-0.00065 to -0.00001) | 8 (0.02%) / 181 (0.54%) | 0.027 |
| Fit 2022 to 2023, score 2024 | development | -1.04405 | -1.11072 | -1.04368 | +0.0667 (+0.0614 to +0.0721) | -0.00037 (-0.00058 to -0.00017) | 4 (0.01%) / 71 (0.21%) | 0.032 |
| Fit 2022 to 2024, score 2025 | previously exposed, retrospective | -1.14114 | -1.21019 | -1.14122 | +0.0691 (+0.0627 to +0.0752) | +0.00007 (-0.00015 to +0.00032) | 8 (0.02%) / 49 (0.15%) | 0.049 |

Intervals are paired, game-clustered, 10,000 draws, seed 20261102.

## Sensitivity

| Setting | Fold | Sampler minus B0 | Sampler minus B1 | Package TV |
|---|---|---|---|---:|
| K = 5 | 2023 | +0.0595 | -0.00019 | 0.027 |
| K = 5 | 2024 | +0.0669 | -0.00014 | 0.032 |
| K = 80 | 2023 | +0.0588 | -0.00089 | 0.027 |
| K = 80 | 2024 | +0.0661 | -0.00099 | 0.031 |
| RB-only code (SLC), K = 20 | 2023 | +0.0370 | -0.00025 | 0.098 |
| RB-only code (SLC), K = 20 | 2024 | +0.0510 | -0.00036 | 0.054 |

## Reading

1. **The sampler beats the marginal package distribution on every fold.** The gain is about 0.06 nats per play, with intervals well above zero, on both development folds and on the retrospective fold.
2. **The sampler is slightly less likely than the unshrunk cell on the plays the unshrunk cell can score.** The gap is about 0.0003 nats per play on the development folds, with intervals that exclude zero. On the retrospective fold the gap is zero within its interval. The unshrunk cell cannot be used as a sampler: it has no probability for about 0.2 to 0.5% of plays. The shrinkage cost is small, and it is the price of full coverage.
3. **Supported combinations.** The sampler leaves 4 to 8 test plays unsupported per fold (0.01 to 0.03%). The unshrunk cell leaves 49 to 181 (0.15 to 0.54%).
4. **Package frequency and drift.** Total variation is 0.027 and 0.032 on the development folds, and 0.049 on 2025. The 2025 gap is the largest. Predicted 11 personnel is 0.631, observed 0.588, and 12 and 13 personnel are higher than predicted. This is a mix shift the 2022 to 2024 prior does not anticipate, and it is reported as drift, not hidden.
5. **Zero rates.** No test package lacked training support (zero training rate 0.0 on all folds).

## The spec's decision rule, applied

The spec's rule asks for (a) a positive gain over B0 with an interval above zero on both development folds, (b) an unsupported rate at or below B1's, and (c) the retrospective fold agreeing in sign.

- (a) Met: +0.0594 and +0.0667, intervals above zero.
- (b) Met: 0.02% and 0.01% against B1's 0.54% and 0.21%.
- (c) Met under the reading below: the retrospective gain over B0 is +0.0691, same sign.

**Reading of (c).** The spec does not name the comparison that (c) refers to. I read it as the B0 comparison, because criterion (a) uses it. If the owner reads it as the B1 comparison, the retrospective fold agrees in sign on that comparison as well (+0.00007, not significant), so the verdict does not change. The owner should confirm the reading. This is recorded here, not changed in the spec.

PBV1 passes Milestone 2's package-level criteria. The result is package-level only. It does not establish that named players, workloads or team opportunities are realistic.

## What is not evaluated

- **Named-player participation and workloads:** not evaluated, because the eligibility mechanism has not passed (owner ruling E).
- **Team opportunities:** the table reports observed scrimmage plays per team-game by season (61.98, 62.06, 61.12, 60.03 for 2022 to 2025). These are descriptive. The sampler does not generate plays, so nothing here is a model test.
- **Formation:** not in the cell, because 2022 formation labels have no verified mapping to 2023 onward.

## 2022 fullback coding uncertainty

The package_comparable shares for 2022 are 11 at 0.629, 12 at 0.201, 21 at 0.082, 13 at 0.041, and 22 at 0.028. The 2023 shares are 0.642, 0.204, 0.074, 0.034 and 0.015. The 2022 fullback coding remains inferred, not labelled (see the HPV1 contract). The RB-only sensitivity moves the TV distance up to 0.098 (2023), because the RB-only code splits FB plays from RB plays.

## Outputs

- `outputs/pbv1_results.json`: every fold and sensitivity, including per-package predicted and observed shares.
- `outputs/pbv1_package_shares.csv`: package shares by season.
- `pbv1_sampler.py`, `pbv1_eval.py`, `test_pbv1_sampler.py` (16 tests passing, including the 139,798 HPV1 scrimmage total).

## Open items

1. Owner: confirm the reading of spec criterion (c).
2. The 2025 mix shift toward 12 and 13 personnel: decide whether a drift term or a fresh prior is in scope for later milestones.
3. Named-player participation and workloads: wait for the eligibility mechanism.
