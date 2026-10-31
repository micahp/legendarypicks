# Position-conditioned player-share holdout

## Result

Three chronological one-season fits (2022→2023, 2023→2024, and 2024→2025) score the role and position groups used by SLC. Each held-out game is conditioned on players observed in nflverse offensive participation, and the fitted base shares are renormalized over those eligible players for that game, matching the simulator's share-draw operation.

The Dirichlet-multinomial improves held-out log-likelihood over fixed season shares in each pooled role and all three folds. It also repeatedly produces too much game-to-game share variation for RB carries and WR targets. QB carry likelihood gains are negligible and their confidence intervals include zero in all three folds. This supports testing higher concentration values for RB carries and WR targets, and a fixed-share QB-carry control; it does not establish a calibrated workload correction or justify changing SLC defaults.

A multi-season concentration candidate fitted on 2022–2024 and evaluated on untouched 2025 preserves the RB-carry and WR-target likelihood gains, but still overpredicts their dispersion. The candidate is a research diagnostic only; SLC defaults remain unchanged. Its complete machine-readable output is `pooled-concentration-2022-2024-holdout-2025.json`.

## Evaluation design

- Each fold fits the share base and concentration on one regular season, then evaluates on the immediately following regular season. No test-season data are used in fitting.
- Reuse SLC's `POSITION_GROUPS` and exact position mapping exported from `players` with `MIN(position)` per NFL GSIS ID. The map contains 24,180 IDs and is pinned in `position-map.csv`.
- Use each held-out season's participation file joined to regular-season scrimmage PBP rows as the game eligibility set. This records at least one offensive snap, not the official pregame active/inactive list.
- Score only players who both have prior-season same-team role support and appear in the held-out game's participation set. Omit a team-game when that supported eligible cohort records zero opportunities. The denominators below are therefore team-games with at least one opportunity in the scored cohort.
- Compare per-team-game log-likelihood; the 95% interval resamples game IDs and keeps both teams in each game together. The zero-rate and variance diagnostics compare observed player-game counts with model-predicted counts under each team's held-out opportunity total.
- All source CSVs match the hashes in the committed player-workload-reference v3 manifest. Each `fold-*.json` records source and code hashes and every group-level metric; `cross-fold-summary.csv` and `.json` contain the complete 24-row comparison.

Participation coverage was 544 team-games per season: 2023 (46,168 rows read; 34,454 scrimmage rows joined; 10,270 player-team-game records), 2024 (45,919; 33,951; 10,239), and 2025 (45,184; 33,458; 10,183).

## Held-out results

`Δ log-likelihood` is Dirichlet-multinomial minus fixed-share per team-game; positive favors the Dirichlet-multinomial. Log-likelihood intervals are game-clustered 95% bootstrap intervals. Zero rates and variances are observed / Dirichlet-multinomial predicted.

| Role group | Fit team-games | Holdout team-games | Player-team units | Fitted φ | Δ log-likelihood [95% interval] | Zero rate obs / DM | Variance obs / DM |
|---|---:|---:|---:|---:|---:|---:|---:|
| Carries, all | 544 | 526 | 193 | 7.542 | +0.8947 [0.6409, 1.1715] | 0.4308 / 0.4800 | 7.2878 / 10.6041 |
| Carries, QB | 485 | 307 | 35 | 1.000 | −0.0205 [−0.0466, 0.0025] | 0.0364 / 0.0595 | 3.3057 / 3.4094 |
| Carries, RB | 544 | 473 | 77 | 2.676 | +0.5378 [0.3148, 0.7815] | 0.0820 / 0.1624 | 16.5647 / 28.7799 |
| Carries, WR/TE | 282 | 161 | 64 | 7.943 | +0.0345 [0.0124, 0.0631] | 0.5377 / 0.5234 | 0.5096 / 0.5478 |
| Targets, all | 544 | 543 | 299 | 24.406 | +0.9234 [0.7297, 1.1193] | 0.2498 / 0.3093 | 3.9570 / 5.5013 |
| Targets, RB | 534 | 462 | 75 | 3.913 | +0.0984 [0.0313, 0.1694] | 0.2015 / 0.2544 | 2.5160 / 2.9324 |
| Targets, TE | 542 | 501 | 78 | 6.237 | +0.0340 [−0.0114, 0.0804] | 0.2016 / 0.2359 | 3.4022 / 4.1942 |
| Targets, WR | 544 | 524 | 126 | 8.810 | +0.4722 [0.3098, 0.6501] | 0.1527 / 0.2169 | 5.8658 / 8.5751 |

## Cross-fold replication

| Training → holdout | Group | Fitted φ | Δ log-likelihood [95% interval] | Zero rate obs / DM | Variance ratio DM / obs |
|---|---|---:|---:|---:|---:|
| 2022→2023 | Carries, RB | 2.291 | +1.0553 [0.7196, 1.4329] | 0.0732 / 0.1717 | 1.53× |
| 2023→2024 | Carries, RB | 2.770 | +0.8561 [0.6072, 1.1435] | 0.0903 / 0.1314 | 1.51× |
| 2024→2025 | Carries, RB | 2.676 | +0.5378 [0.3148, 0.7815] | 0.0820 / 0.1624 | 1.74× |
| 2022→2023 | Targets, WR | 9.441 | +0.3621 [0.2584, 0.4713] | 0.1423 / 0.1933 | 1.43× |
| 2023→2024 | Targets, WR | 12.023 | +0.5252 [0.3820, 0.6846] | 0.1552 / 0.1873 | 1.37× |
| 2024→2025 | Targets, WR | 8.810 | +0.4722 [0.3098, 0.6501] | 0.1527 / 0.2169 | 1.46× |
| 2022→2023 | Carries, QB | 1.000 | +0.0083 [−0.0154, 0.0325] | 0.0422 / 0.0500 | 1.05× |
| 2023→2024 | Carries, QB | 1.000 | −0.0057 [−0.0284, 0.0190] | 0.0427 / 0.0541 | 1.04× |
| 2024→2025 | Carries, QB | 1.000 | −0.0205 [−0.0466, 0.0025] | 0.0364 / 0.0595 | 1.03× |

The RB-carry variance excess and WR-target variance excess repeat in every fold, while QB carry likelihood differences remain small and uncertain. This is evidence for mechanism-specific calibration, not a global dispersion adjustment.

## Multi-season concentration candidate

The concentration parameter is fitted jointly on 2022–2024 team-games, using season-specific base shares. The 2025 holdout uses 2024 base shares and 2025 on-field participation eligibility. This tests whether pooling concentration evidence stabilizes the estimate; it does not use 2025 outcomes in the fit.

| Role group | Fit team-games | Holdout team-games | Pooled φ | Δ log-likelihood [95% interval] | Zero rate obs / DM | Variance obs / DM |
|---|---:|---:|---:|---:|---:|---:|
| Carries, QB | 1,433 | 307 | 1.000 | −0.0205 [−0.0466, 0.0025] | 0.0364 / 0.0595 | 3.3057 / 3.4094 |
| Carries, RB | 1,630 | 473 | 2.541 | +0.5271 [0.3039, 0.7722] | 0.0820 / 0.1660 | 16.5647 / 29.3053 |
| Carries, WR/TE | 863 | 161 | 8.660 | +0.0328 [0.0118, 0.0600] | 0.5377 / 0.5228 | 0.5096 / 0.5461 |
| Targets, RB | 1,609 | 462 | 4.121 | +0.0998 [0.0341, 0.1698] | 0.2015 / 0.2525 | 2.5160 / 2.9080 |
| Targets, TE | 1,621 | 501 | 5.623 | +0.0285 [−0.0189, 0.0772] | 0.2016 / 0.2400 | 3.4022 / 4.2698 |
| Targets, WR | 1,630 | 524 | 9.943 | +0.4808 [0.3234, 0.6532] | 0.1527 / 0.2118 | 5.8658 / 8.2398 |

The pooled RB-carry concentration (φ=2.541) is close to the 2024-only estimate (2.676), and the pooled WR-target concentration (φ=9.943) is close to the 2024-only estimate (8.810). Both retain clear held-out likelihood gains, but the predicted RB-carry variance remains 1.77× observed and WR-target variance 1.40× observed. Pooling years therefore does not resolve the excess share dispersion. QB carries still show no reliable gain over fixed shares. Do not ship these concentrations as a workload fix; the remaining discrepancy likely requires role and game-state mechanisms beyond one global concentration per group.

## Diagnosis and next calibration step

- Pooled game-level shares improve predictive likelihood, but pool-level gains conceal position-group calibration differences.
- RB carries have substantial excess share variation: predicted variance is 74% above held-out variance and the predicted zero rate is 8.0 percentage points too high. Their fitted concentration is low (φ=2.676), so player shares move too far from their season means between games.
- WR targets also show excess variation: predicted variance is 46% above held-out variance and the zero rate is 6.4 points too high. The TE target likelihood interval includes zero, so this holdout does not establish a benefit for that subgroup.
- QB carries have a fitted φ at the current grid's lower bound (1.0). The Dirichlet-multinomial scores slightly worse than fixed shares, with the interval including zero. Treat the boundary estimate as a support warning, not evidence to increase QB-run tails.
- The predicted means match the observed mean over the scored player cohort by construction after renormalizing shares over eligible players. This check therefore supports assessment of dispersion and likelihood, not the team's total opportunity volume or each individual player's mean role.
- Next, test any supported candidate in the full paired ARI–DAL matrix and evaluate role/game-state-conditioned shares against an independent holdout. The pooled fit does not fix RB-carry or WR-target dispersion. Do not cap carries, targets, or yards.

## Reproduction

```sh
PYTHONPATH=scripts/nfl_sequence python3 \
  scripts/nfl_sequence/validate_share_distributions.py \
  --fit-season 2024 --test-season 2025 \
  --concentration-fit-seasons 2022,2023,2024 \
  --data-dir /root/gridiron-playbooks-research/data/raw \
  --position-map docs/research/share-distribution-holdout-2026-10-31/position-map.csv \
  --out docs/research/share-distribution-holdout-2026-10-31/pooled-concentration-2022-2024-holdout-2025.json
```

Focused verification: 113 tests across the share-validation, distribution, SLC playcall, football-invariant, and engine-manifest modules passed; Python compilation and `git diff --check` passed.
