# V3 kernel-matching close-out

**Classification: diagnostic only.** This close-out adds no kernel, makes no candidate or gate
change, does not run the simulator, and does not edit frozen Phase 2A results. It is on
`research/nhl-v3-kernel-noise-floor-2026-10-21`, after noise-floor commit `67a32441`.

## Required sigma-zero floor at σ=0.324

Define raw Δ as candidate SOG CRPS minus Phase 2A CRPS, and let `F` be the sigma-zero CRPS
floor subtracted from that raw delta. The kernel-fix run measured raw Δ **+0.10618865** with
95% game-cluster CI **[+0.08326255, +0.12945583]**. Therefore:

- To make the point estimate nonworsening, `F` must be at least **+0.10619**.
- For the adjusted 95% interval to include zero, `F` must lie in
  **[+0.08326, +0.12946]**.

The two sigma-zero floors measured along this line were +0.023651
**[+0.010267, +0.036878]** for the conditional-binomial kernel and +0.037670
**[+0.023881, +0.051245]** for the Beta–Binomial moment fit. Relative to the point-estimate
requirement, those floors are **4.49×** and **2.82×** too small. Even relative to the lower
CI edge needed for possible overlap with zero, they are **3.52×** and **2.21×** too small.
This is the load-bearing bound: neither measured floor is large enough to account for the
σ=0.324 deterioration.

## Four-row decision record

Raw A pass rates refer to the σ=0.324 arm where that kernel was tested. CRPS contrasts retain
the direction reported by each source; A is the preregistered nonworsening SOG CRPS condition.

| Line | Measured σ=0 floor, CRPS Δ [95% CI] | Raw A passes | Relevant raw SOG CRPS contrast [95% CI] |
|---|---:|---:|---:|
| Share mechanism | N/A: moment counterfactual, no scoring kernel | Not evaluated | No SOG CRPS test; share and margin moments only |
| Underdispersion | N/A: stored-prediction diagnosis, no σ kernel | Not evaluated | Phase 2A minus stored C SOG CRPS = −0.0387 [−0.0618, −0.0163]; descriptive comparison, not an A trial |
| Kernel fix, σ=0.324 | +0.023651 [+0.010267, +0.036878] | 0/100 (Wilson 95%: 0–3.70%) | Candidate minus Phase 2A = +0.115111 [+0.089913, +0.141358] |
| Beta–Binomial noise-floor fit, σ=0.324 | +0.037670 [+0.023881, +0.051245] | 0/100 (Wilson 95%: 0–3.70%) | Candidate minus Phase 2A = +0.106189 [+0.083263, +0.129456] |

The first two rows are explicitly not A evaluations: the share audit reports moment sizing, and
the underdispersion audit reports count calibration plus a stored-prediction sensitivity. Their
“not evaluated” entries are not zero pass rates.

## Bias attribution for the Beta–Binomial floor

The direct comparison uses the 1,292 SOG-eligible games, 2,584 game-side fits, and the 16
committed Phase 2A draws. For each game-side, the analytic quantity is the expected ddof=1
sample variance across its fixed, varying attempt sequence under the fitted mean rate (m) and
intra-class correlation ρ:

\[
V_{fit}=m(1-m)\bar n + m^2\frac{D}{D-1}\operatorname{Var}_0(n)
       + \rho m(1-m)\overline{n(n-1)},\quad D=16.
\]

The candidate variance is the mean of the realized ddof=1 variances over the same 100 sigma-zero
replicates and seeds as the committed run.

| Quantity | Mean variance per game-side | Ratio of aggregate means to Phase 2A sample variance | Per-side ratio distribution |
|---|---:|---:|---|
| Phase 2A 16-draw sample variance | 31.88184 | 1.00000 | Reference |
| Analytic variance implied by fitted `m`, `ρ`, and `n` | 37.18295 | 1.16627 | Analytic/sample: mean 1.25440, median 1.10625; p05–p95 1.00000–1.96507 |
| Realized Beta–Binomial sigma-zero candidate variance, averaged over 100 replicates | 37.18516 | 1.16634 | Candidate/analytic: mean 0.99979, median 0.99925; p05–p95 0.95036–1.05068 |

The analytic variance exceeds the variance it was fit to by **5.30112** on average. This gap
comes from the nonnegative-ρ fallback: **1,633/2,584 (63.2%)** of game-sides had nonpositive
excess variance and were set to Binomial. On those fallback sides the analytic variance exceeds
the fitted sample variance by **8.38830** on average. On the other 951 positive-ρ sides, the
moment equation matches the fitted sample variance to floating-point precision. Thus the
aggregate excess is attributable to truncating the noisy 16-draw moment estimates at ρ=0;
the fallback cannot represent a sample variance below its binomial-plus-attempt baseline.

The sampler does not account for the discrepancy: realized candidate variance is only 0.00221
above the analytic mean (aggregate ratio 1.00006), and the per-side candidate/analytic ratio is
centered near one. Replaying the 100 sigma-zero seeds reproduced every saved per-replicate mean
SD and CRPS exactly. The fitted ρ distribution is zero-inflated and right-tailed: median 0,
75th percentile 0.00466, 90th 0.01319, 95th 0.01843, 99th 0.02980, maximum 0.05273. That shape
describes the finite-sample fits; the direct decomposition shows the excess arises in the
zero-truncated fallback cells, not from a sampler variance mismatch.

The mean-of-SD aggregation is not the explanation: candidate/Phase 2A mean per-side SD is
1.07768, while the ratio of square roots of aggregate variances is 1.07997, a 0.00230 difference.
Both empirical variances use ddof=1, and the analytic expression includes the corresponding
varying-attempt correction. Neither ddof nor the mean-of-SD versus SD choice explains the 7.8%
dispersion gap. No refit, shrinkage, or alternative parameterization was tried.

## Recommendation and unresolved point

**A is rejected under two independent sigma-zero kernel-matching attempts at σ=0.324 in the raw
preregistered sense:** each had 0/100 nonworsening replicates and a paired CRPS interval wholly above zero. The
measured sigma-zero floors are below the required bound. The Beta–Binomial construction itself
failed the stipulated sigma-zero match, so its floor-subtracted residual is not a valid estimate
of the effect under a truly floor-free kernel. We could not determine that exact residual. B is
unidentifiable without an attempt-allocation layer; any further test needs a new preregistration,
not more kernel fitting.

Sources: [`SHARE-MECHANISM.md`](SHARE-MECHANISM.md), [`UNDERDISPERSION.md`](UNDERDISPERSION.md),
[`KERNEL-FIX.md`](KERNEL-FIX.md), and [`KERNEL-NOISE-FLOOR.md`](KERNEL-NOISE-FLOOR.md).
