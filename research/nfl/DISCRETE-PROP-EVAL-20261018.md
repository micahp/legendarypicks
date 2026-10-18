# Discrete-prop evaluation audit — 2026-10-18

Branch: `research/discrete-prop-eval-2026-10-18`, based on `origin/dev` at `7dd1b62b`.

## Finding

The central-interval coverage measure is useful as a descriptive realized-inclusion rate, but it is **unsound as a standalone acceptance criterion for zero-heavy discrete forecasts**. A central interval can contain more than its nominal probability because its endpoints include whole atoms. Its observed coverage therefore does not isolate calibration, and aggregate coverage can conceal large offsetting errors across strata.

The frozen 2025 B0 exhibit is direct evidence: observed zero share is **0.379**, while mean predicted `P(0)` is **0.173**, a **−0.206** probability gap. Yet the stored central 50% coverage is **0.543**, only 0.043 above nominal. The stored diagnostic says 24.8% of B0 forecasts have `q25 = 0`; those cover 0.848, while the remainder cover 0.442. Their weighted coverage is approximately `0.248 × 0.848 + 0.752 × 0.442 = 0.543`. The near-nominal aggregate is cancellation, not evidence that the zero event is calibrated.

This answers the gate question in general: realized interval coverage can describe how often a chosen set contains outcomes. For zero-heavy integer outcomes, comparing that rate alone to the nominal level is not a sound acceptance rule. The same issue applies to any discrete prop with atoms, including receptions, touchdowns, sacks, and interceptions.

## Frozen-artifact boundary

I copied the versioned frozen JSONs and result documents into [`discrete-prop-eval-2026-10-18/frozen-inputs/`](discrete-prop-eval-2026-10-18/frozen-inputs/). [`MANIFEST.md`](discrete-prop-eval-2026-10-18/frozen-inputs/MANIFEST.md) records source branches, commit IDs, sizes, and SHA-256 hashes. The source worktree `/root/lp-rushing-carries` was read only.

The artifacts do **not** contain the observation-level inputs required for the requested re-score:

- No frozen per-player forecast PMF or CDF for B0 or v1–v4.
- No evaluation ledger with actual count, game ID, player/prop ID, season, and week joined to each forecast.
- No per-observation `P(0)` or `P(Y ≥ k)` values.
- No row-level losses or paired game-cluster bootstrap samples for the new diagnostics.

The v1 JSON contains fitted parameters only. The v2–v4 JSONs add aggregate metric tables and parameters, but no forecast rows. Result documents preserve some aggregate values and selected paired CRPS intervals, not the distributions or keyed observations. Reconstructing item distributions from parameters and a database would regenerate forecasts and rely on non-frozen inputs, which the task forbids.

The stored reports state 2,500 observations across 240 games in 2025 and 489 across 48 games in 2026. These counts match across versions, but the exact common game/player population cannot be independently verified without identifiers. The v1 report labels 2026 as weeks 3–6; later reports record the evaluation request as weeks 3–18. Therefore **B0 and all four candidates are excluded from the requested new common-population interval, PIT, and zero-reliability comparison**. No new prediction was scored or regenerated.

## Requested interval families: not scoreable from frozen outputs

Every cell below applies separately at nominal 50%, 80%, and 90%. “Not scored” means no new observed coverage, mean width, set size, or disconnected-set share was computed.

| Forecast | Central interval | Shortest contiguous interval | HPD prediction set |
|---|---|---|---|
| B0 | Not scored | Not scored | Not scored |
| v1 | Not scored | Not scored | Not scored |
| v2 | Not scored | Not scored | Not scored |
| v3 | Not scored | Not scored | Not scored |
| v4 | Not scored | Not scored | Not scored |

The original central-interval coverage is preserved below as a reproducibility check. The frozen summaries do not contain endpoint probabilities, so the endpoint-atom excess decomposition cannot be calculated. In particular, observed coverage minus nominal is **not** an estimate of endpoint-atom excess: it mixes endpoint mass with genuine miscalibration and sampling variation.

## Original CRPS, MAE, and central-coverage checks

These are the previously reported aggregate values, transcribed from the frozen summaries; they are not a new common-population re-score. The 2025 v2–v4 values are read from their JSON summaries. v1 values are available only in its result document.

| Season | Model | n reported | CRPS | MAE | Central coverage 50 / 80 / 90 |
|---|---|---:|---:|---:|---|
| 2025 | B0 (v2–v4 summaries) | 2,500 | 2.0605 | 2.9401 | 0.543 / 0.818 / 0.909 |
| 2025 | v1 B2 hurdle | 2,500 | 1.9093 | 2.7868 | 0.713 / 0.914 / 0.955 |
| 2025 | v2 Zf | 2,500 | 1.8785 | 2.9399 | 0.738 / 0.910 / 0.960 |
| 2025 | v3 tiered dispersion | 2,500 | 1.8524 | 2.9400 | 0.750 / 0.919 / 0.965 |
| 2025 | v4 quantile map | 2,500 | 1.7710 | 2.7104 | 0.744 / 0.938 / 0.970 |
| 2026 | B0 (v2–v4 summaries) | 489 | 2.0889 | 2.9972 | 0.491 / 0.812 / 0.896 |
| 2026 | v1 B2 hurdle | 489 | 1.9764 | 2.9330 | 0.685 / 0.912 / 0.963 |
| 2026 | v2 Zf | 489 | 1.8668 | 2.9959 | 0.740 / 0.926 / 0.965 |
| 2026 | v3 tiered dispersion | 489 | 1.8368 | 2.9967 | 0.748 / 0.930 / 0.973 |
| 2026 | v4 quantile map | 489 | 1.8015 | 2.7965 | 0.718 / 0.928 / 0.978 |

**Source discrepancy:** v1’s own B0 summary reports 2025 CRPS 2.0604 and coverage 0.546 / 0.819 / 0.910; the later v2–v4 summaries report 2.0605 and 0.543 / 0.818 / 0.909. For 2026, v1 reports B0 CRPS 2.0887 and coverage 0.491 / 0.816 / 0.896; v2–v4 report 2.0889 and 0.491 / 0.812 / 0.896. The frozen artifacts do not explain these differences, so they remain unresolved rather than being silently harmonized.

The previous reports contain candidate-versus-B0 paired, game-clustered CRPS intervals. They are retained only as source reproducibility checks, not recalculated comparisons:

| Candidate | 2025 paired CRPS difference vs B0 (reported 95% interval) | 2026 paired CRPS difference vs B0 (reported 95% interval) |
|---|---:|---:|
| v1 B2 hurdle | −0.1511 ± 0.0381 | −0.1123 ± 0.0714 |
| v2 Zf | −0.1820 ± 0.0282 | −0.2221 ± 0.0668 |
| v3 tiered dispersion | −0.2080 ± 0.0281 | −0.2521 ± 0.0684 |
| v4 quantile map | −0.2895 ± 0.0433 | −0.2874 ± 0.1206 |

The `±` values are the source reports’ game-clustered 95% interval half-widths. No full candidate-by-candidate paired matrix is frozen. The 2025 v3 report also stores one adjacent paired comparison, v3−v2 CRPS −0.0261 ± 0.0041; it does not provide the paired raw losses needed for the new metrics.

## Zero-event evidence available in the frozen reports

The following are stored aggregate values, not new calculations. Brier for `Y ≥ 1` equals Brier for the zero indicator when the event probability is complemented (`P(0)=1−P(Y≥1)`). It does not supply game-clustered paired uncertainty.

| Season/source | Model | Observed zero share | Mean predicted P(0) | Stored Brier for zero indicator |
|---|---|---:|---:|---:|
| 2025 v4 report | B0 | 0.379 | **0.173** | 0.2380 in v2–v4 JSON (0.2376 in v1 report) |
| 2025 v4 report | v2 Zf | 0.379 | 0.333 | 0.1410 |
| 2025 v4 report | v3 | 0.379 | Not stored | 0.1375 |
| 2025 v4 report | v4 | 0.379 | 0.301 | 0.1485 |
| 2025 v1 report | v1 B2 | 0.379 | Not stored | 0.1700 |
| 2026 reports | B0 | Not stored as a zero share | Not stored | 0.2498 in v2–v4 JSON (0.2495 in v1 report) |
| 2026 reports | v1 B2 / v2 Zf / v3 / v4 | Not stored as a zero share | Not stored | 0.1898 / 0.1461 / 0.1432 / 0.1625 |

Only B0, v2, and v4 have a reported 2025 mean `P(0)` in the frozen result documents. No model has frozen reliability-bin rows or per-game `P(0)` values, so the requested game-clustered intervals and reliability bins cannot be produced. The zero-indicator Brier checks above are individual stored scores; paired Brier differences and intervals are unavailable. For `k = 2, 5, 10, 20`, no per-observation tail probabilities or Brier summaries were frozen. The 2025 B0 zero gap is quantified as a point difference only: `0.173 − 0.379 = −0.206`; no uncertainty interval is available.

## Stratification and the v3 sign/cancellation check

The stored 2025 v3 result gives the following central-50% coverages by usage tier. The last two columns recompute absolute distance from the nominal 0.50 directly from the printed values.

| Group | B0 coverage | v3 coverage | B0 absolute error | v3 absolute error |
|---|---:|---:|---:|---:|
| Aggregate | 0.543 | 0.750 | 0.043 | 0.250 |
| m < 3 | 0.612 | 0.829 | 0.112 | 0.329 |
| 3 ≤ m < 8 | 0.436 | 0.703 | 0.064 | 0.203 |
| m ≥ 8 | 0.562 | 0.652 | 0.062 | 0.152 |

B0 over-covers the low- and high-usage strata and under-covers the middle stratum; the opposite-signed errors offset in aggregate. That explains why aggregate coverage can look close to nominal while stratum coverage is not. It does **not** show v3 closer to nominal within the tiers: the values printed in the v3 report show a larger absolute error for v3 in each tier. Its prose says the reverse (“better calibrated than B0” within every tier), so the report’s prose and table are inconsistent. This audit uses the displayed numbers and does not edit the source result.

The v4 frozen JSON adds 2025 central coverage for B0, v2 Zf, and v4 by the same usage tiers and at all three central levels; these remain central intervals, not new shortest or HPD calculations:

| Tier | B0 50 / 80 / 90 | v2 Zf 50 / 80 / 90 | v4 50 / 80 / 90 |
|---|---|---|---|
| m < 3 | 0.612 / 0.915 / 0.946 | 0.805 / 0.923 / 0.954 | 0.820 / 0.961 / 0.972 |
| 3 ≤ m < 8 | 0.436 / 0.681 / 0.872 | 0.681 / 0.883 / 0.953 | 0.685 / 0.924 / 0.970 |
| m ≥ 8 | 0.562 / 0.824 / 0.889 | 0.681 / 0.924 / 0.985 | 0.673 / 0.912 / 0.966 |

This stratification is only available for part of the requested model set in frozen artifacts. It is reported as a diagnostic and cannot replace the requested common-population re-score.

## Randomized PIT and endpoint-atom decomposition

No randomized PIT histogram, KS statistic, bin deviation, or bootstrap interval is reported. Those require the per-case CDF values at each observed count and the discrete mass at that count. Those values are absent from the frozen snapshots; no jitter draws or seed were fabricated.

The requested exact endpoint-atom decomposition also remains uncomputed. With interval-specific forecast mass available, it can be written exactly as:

```text
observed coverage
= nominal level
  + mean(forecast probability mass inside the reported set − nominal level)
  + (observed coverage − mean forecast probability mass inside the reported set)
```

The second term is endpoint-atom excess; the third is the empirical calibration residual for that set. Neither term can be recovered from observed coverage alone. The stored summaries do not include the forecast probability mass inside each per-item set.

## Threshold-free replacement proposal for Micah

**Proposal for Micah to accept or reject before any adoption decision:** for zero-heavy discrete props generally, retain central-interval coverage as a descriptive result, but do not use nominal central coverage alone as the acceptance criterion. Pre-register a measurement bundle that reports, on the identical frozen observations and with game-clustered paired uncertainty:

- CRPS and MAE as score checks;
- central and shortest-contiguous intervals separately, plus HPD prediction sets as sets, with observed coverage, forecast mass, mean width, HPD set size, disconnected share, and endpoint-atom excess;
- randomized PIT with seed, repeated draws, histogram, KS, and bin-deviation uncertainty;
- zero-event calibration and Brier, plus reliability and Brier for supported `Y ≥ k` events;
- aggregate and relevant market-specific strata side by side.

The method applies to discrete count props generally. The event definitions and useful strata are market-specific; the PMF-based interval, randomized-PIT, proper-score, calibration, and paired-game measurement methods are universal. This proposal contains **no numeric acceptance threshold** and adopts or rejects no model.

## Integrity statement

No model was refit, no frozen artifact was changed, no forecast was regenerated, no acceptance threshold was selected or applied, and no candidate was given an adoption decision. The requested new interval-family, PIT, and paired zero-calibration results remain blocked until the frozen artifact set includes per-observation distributions and a keyed outcome ledger. The original CRPS, MAE, and central-coverage checks and the B0 zero-calibration exhibit are preserved above without pretending that they are the requested re-score.
