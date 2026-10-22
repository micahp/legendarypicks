# Phase 2C preregistered rule feasibility

**Status: synthetic diagnostic only.** No candidate was selected, no simulator or gate was changed, and no frozen Phase 2A artifact was modified. This run answers whether the preregistered conjunction can pass under its specified count-resplitting approximation.

Run date: 2026-10-21. Base commit: `7cd37e0c8562dcfd4e75d8485dc09b92461f9b14`.

## Result

The rule passed in **0 of 100 synthetic datasets at every tested σ**. At σ=0.324, the diagnostic scale cited by the earlier share analysis, SOG CRPS condition A passed **0/100** times; margin condition B passed **100/100** times. Condition A is the binding part of this rule on this synthetic kernel.

The rule's 50% and 80% joint-pass thresholds were **not reached** anywhere on the tested grid from 0 through 0.45. The grid does not support extrapolating a crossing.

| σ | Mean paired SOG CRPS Δ (synthetic − Phase 2A), with R-dataset 2.5–97.5 percentiles | A passes / 100 (Wilson 95%) | Mean attempt Var(H−A), with R-dataset 2.5–97.5 percentiles | B passes / 100 (Wilson 95%) | Joint passes / 100 (Wilson 95%) |
|---:|---:|---:|---:|---:|---:|
| 0 | 0.0000 [0.0000, 0.0000] | 100 (96.3–100%) | 165.813 [165.813, 165.813] | 0 (0–3.7%) | 0 (0–3.7%) |
| 0.10 | +0.0398 [+0.0109, +0.0682] | 0 (0–3.7%) | 308.142 [304.384, 312.166] | 100 (96.3–100%) | 0 (0–3.7%) |
| 0.16 | +0.0531 [+0.0232, +0.0754] | 0 (0–3.7%) | 355.693 [350.361, 361.092] | 100 (96.3–100%) | 0 (0–3.7%) |
| 0.24 | +0.0900 [+0.0579, +0.1329] | 0 (0–3.7%) | 450.788 [444.492, 458.355] | 100 (96.3–100%) | 0 (0–3.7%) |
| 0.324 | +0.1546 [+0.1146, +0.1972] | 0 (0–3.7%) | 587.469 [578.754, 595.981] | 100 (96.3–100%) | 0 (0–3.7%) |
| 0.45 | +0.2955 [+0.2404, +0.3355] | 0 (0–3.7%) | 851.373 [839.165, 863.950] | 100 (96.3–100%) | 0 (0–3.7%) |

The Phase 2A baseline SOG CRPS was 3.912575. At σ=0.324 the synthetic mean was 4.067205, a deterioration of 0.154630. The entire 2.5–97.5 percentile range of replicate mean deltas was positive. The bootstrap interval for attempt margin-variance change was above zero in all 100 replicates; its median interval was **[411.55, 432.16] attempts²**. The synthetic attempt margin variance averaged 587.47, versus 323.52 observed. Thus B's one-sided minimum of 244.667 is met while allowing a substantial overshoot of the observed variance.

At R=100, Wilson intervals for 0/100 and 100/100 rates are respectively 0–3.7% and 96.3–100%. These quantify pass-rate Monte Carlo precision across the synthetic datasets, not future-season uncertainty. The CRPS percentile ranges in the table describe replicate-to-replicate synthetic variability; they are not game-cluster confidence intervals.

## Baseline and protocol checks

The baseline harness reproduced committed Phase 2A team SOG CRPS and the generated attempt and SOG moments with zero measured discrepancy. The SOG calculation used the same 1,292 accepted official-SOG games for predictions and labels. A separate calculation using Phase 2A's `_crps_discrete` implementation also returned 3.9125749806501546.

The attempt moments reproduced were generated Var(H)=75.658, Var(A)=72.516, Cov(H,A)=−8.820, and Var(H−A)=165.813. Observed values were 117.597, 116.503, −44.710, and 323.520. For accepted-SOG games, generated values were 34.845, 33.876, −0.655, and 70.031; observed values were 47.233, 47.518, −11.460, and 117.671.

For each positive σ, the harness kept each stored draw's attempt and SOG totals fixed, computed the calibrated 32-point Gauss–Hermite logit offset, and used one normal draw for both attempt and SOG shares. It generated 100 datasets per σ using seeds 20261023 through 20261122; the same replicate seed across σ values supplied common normal draws. Each dataset used 2,000 paired game-ID cluster bootstrap resamples with seed 20261022. Bootstrap statistics were processed in batches of 32. The full run took 111.64 seconds. The first 50 σ=0.324 replicate records matched an earlier R=50 timing run exactly.

All 1,200 per-dataset attempt/SOG pair-total assertions passed. σ=0 reproduced the attempt and eligible-SOG trace bytes exactly, and its recomputed moments matched Phase 2A exactly. The three requested unit tests passed.

## Feasibility issues exposed

1. **The stated σ=0 false-positive expectation conflicts with exact identity.** Under the required identity branch, every paired game-level candidate-minus-baseline margin-variance difference is exactly zero. The paired bootstrap interval is therefore [0, 0], and its interval-only false-positive rate is 0/100, not about 2.5%. This does not indicate a mis-specified paired bootstrap; the null distribution here is degenerate. A nondegenerate null calibration would need a separately specified null generator and could not also be this exact identity comparison.
2. **The resplit is discontinuous at zero.** For every σ>0, the harness redraws H′ from Binomial(N,pH), adding fresh conditional-binomial allocation noise on top of the already realized Phase 2A split. At σ=0 it returns the original counts exactly. Consequently, the positive-σ results do not approach the σ=0 identity as σ decreases; the change includes the redraw itself as well as the latent share effect.
3. **Separate attempt and SOG resplits do not always make physically consistent side counts.** At σ=0.324, 100/100 datasets had at least one game/draw where a team's synthetic SOG exceeded that team's synthetic attempts: a mean of 66.41 team/draw cells out of 41,984 per dataset. This approximation preserves each pair's total but does not preserve event-level nesting. It cannot be treated as a valid generated game or event stream.
4. **Condition B is a lower bound only.** At the diagnostic σ the margin variance is well above both the 244.667 criterion and the observed 323.520. The current condition can pass severe overdispersion.

The result is therefore specific to this feasibility kernel. It does not establish that a future simulator implementation would have the same CRPS effect. The kernel ignores event-level dependence, holds each draw's attempt total at its Phase 2A value, has no per-period redraw, and contains no event paths, shot locations, goals, special-teams outcomes, clocks, regulation, overtime, or shootout process.

## Recommendation for review (text only)

Keep the preregistration and gate unchanged. Before any implementation is considered, clarify the read criterion in a new reviewed preregistration: use σ=0 as an identity check rather than a false-positive calibration point; define a nondegenerate null if a type-I operating rate is required; and resolve the positive-σ redraw discontinuity and side-level SOG/attempt consistency. For model selection, replace the point rule “mean SOG CRPS Δ ≤ 0” with a one-sided paired-game noninferiority test whose tolerated CRPS margin is fixed before outcomes are examined. Also require attempt margin variance to fall within a prespecified calibration band around observation, rather than merely exceed a lower bound. This diagnostic does not supply defensible tolerances for either margin, so they must be set before a new evaluation.

## Provenance

The machine-readable results, seeds, input SHA-256 values, runtime, all per-replicate scores, bootstrap intervals, and accounting counts are in [`rule_feasibility.json`](rule_feasibility.json). The executable harness and requested tests are [`rule_feasibility.py`](rule_feasibility.py) and [`test_rule_feasibility.py`](test_rule_feasibility.py).

Frozen Phase 2A hashes matched before and after the run:

| Artifact | SHA-256 |
|---|---|
| `EVALUATION.json` | `24d5a55754a6b072f66203096a1936036a8d209df870ef6f8787bd0a22fc3930` |
| `FITTED-MODEL.json` | `8e0304b9dbe4230f9deb17abda0ebe79cd89653289d2661a1612d79f8914addb` |
| `REPORT.md` | `b0867d3cf1ef64a30469d087a03bda9ed156bbbbe020458b3efbb562473036f0` |
