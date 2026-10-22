# NHL V3 kernel noise-floor diagnostic

**Classification:** diagnostic only. No candidate was selected, no rule or gate changed, and
Phase 2A predictions and frozen files were left untouched.

## Finding

The requested per-game-side Beta–Binomial moment fit did **not** remove its own sigma-zero
noise floor. On the 1,292 SOG-eligible games, its mean within-game per-side ensemble SD was
5.9769 versus 5.5461 for Phase 2A (ratio 1.0777; replicate 2.5th–97.5th percentiles
1.0712–1.0844). Its sigma-zero SOG CRPS was 3.950245 versus the Phase 2A baseline 3.912575,
for a paired delta of **+0.037670 [ +0.023881, +0.051245 ]** on a 2,000-resample game-cluster
bootstrap. The interval excludes zero and the dispersion ratio is outside the required
[0.98, 1.02] band. The floor criteria therefore fail.

The sigma-zero delta above is the measured floor for this tested moment-fit construction,
not a claim that every possible Beta–Binomial parameterization has this minimum. No alternate
shrinkage or calibration was selected. In particular, the results below that subtract this
floor are exploratory sensitivities, not a valid floor-free test of condition A.

## Sigma grid

Each row repeats the sigma-zero floor, as requested. CRPS intervals are paired 95% game-cluster
bootstrap intervals. “A raw” is the per-replicate nonworsening rate against Phase 2A; its 0/100
Wilson 95% interval is 0–3.70% in every row. “Adjusted” subtracts the same replicate's sigma-zero
CRPS and is shown only as a diagnostic because the floor failed. The sigma-zero adjusted result
is zero by definition.

| Sigma | Mean side SD (ratio to Phase 2A) | Sigma-zero floor Δ [95% CI] | Raw CRPS Δ [95% CI] | Δ minus own sigma-zero floor [95% CI] | A raw passes | Adjusted nonworsening† |
|---:|---:|---:|---:|---:|---:|---:|
| 0.000 | 5.9769 (1.0777) | +0.03767 [+0.02388, +0.05124] | +0.03767 [+0.02388, +0.05124] | 0.00000 [0.00000, 0.00000] | 0/100 | 100/100† |
| 0.100 | 6.1313 (1.1055) | +0.03767 [+0.02388, +0.05124] | +0.04131 [+0.02655, +0.05550] | +0.00364 [+0.00168, +0.00564] | 0/100 | 27/100† |
| 0.160 | 6.3623 (1.1472) | +0.03767 [+0.02388, +0.05124] | +0.04827 [+0.03235, +0.06375] | +0.01060 [+0.00646, +0.01492] | 0/100 | 17/100† |
| 0.240 | 6.8021 (1.2265) | +0.03767 [+0.02388, +0.05124] | +0.06765 [+0.04902, +0.08608] | +0.02998 [+0.02159, +0.03857] | 0/100 | 1/100† |
| 0.324 | 7.3865 (1.3318) | +0.03767 [+0.02388, +0.05124] | +0.10619 [+0.08326, +0.12946] | +0.06852 [+0.05466, +0.08277] | 0/100 | 0/100† |
| 0.450 | 8.4034 (1.5152) | +0.03767 [+0.02388, +0.05124] | +0.20280 [+0.17163, +0.23394] | +0.16513 [+0.14293, +0.18793] | 0/100 | 0/100† |

† The adjusted rate is not a condition-A pass rate while the sigma-zero floor criteria fail.
The bootstrap intervals quantify game-sampling uncertainty; they do not repair that failed
kernel-matching criterion.

## Fit and protocol

For each eligible game-side, the conversion mean is total SOG divided by total attempts over the
16 committed Phase 2A draws. The variance fit uses the ddof=1 sample variance and removes both
binomial variance and the expected-count variation from the fixed, varying attempt counts before
estimating Beta probability variance. Nonpositive excess variance falls back to Binomial. This
affected 1,633 of 2,584 game-side fits (63.2%); no fit hit the upper rho cap.

The grid used 100 replicates per sigma, seeds `20261023 + replicate_index`, common Gaussian
latents and inverse-CDF uniforms across sigma values, and 2,000 paired game-cluster bootstrap
resamples (seed `20261022`). A vectorized Beta–Binomial PMF recurrence replaced SciPy's scalar
quantile loop; its quantiles were tested against SciPy, and vectorized CRPS was checked against
the existing reference helper. Runtime was 32.0 seconds with BLAS/OpenMP limited to one thread.
Every generated SOG count was within its fixed attempt count.

The committed Phase 2A frozen hashes matched before and after the run:

- `EVALUATION.json`: `24d5a55754a6b072f66203096a1936036a8d209df870ef6f8787bd0a22fc3930`
- `FITTED-MODEL.json`: `8e0304b9dbe4230f9deb17abda0ebe79cd89653289d2661a1612d79f8914addb`
- `REPORT.md`: `b0867d3cf1ef64a30469d087a03bda9ed156bbbbe020458b3efbb562473036f0`

## Scope and direct answer

Condition A passed raw in 0/100 replicates at every sigma. After subtracting the measured
sigma-zero floor, the exploratory residual at sigma 0.324 is +0.06852 [ +0.05466, +0.08277 ]
and 0/100 replicates are nonworsening. **This does not establish whether A survives a truly
floor-free kernel:** the sigma-zero kernel failed both required matching criteria, so the
floor-free question remains unresolved. The measured floor for this tested moment-fit is
+0.03767 [ +0.02388, +0.05124 ].

Condition B is untestable in this kernel. It holds the Phase 2A attempt counts and side split
fixed and contains no attempt-allocation layer, so the prior B 0/100 result carries no information
about the rule. No joint pass rate is reported.

The diagnostic used only committed Phase 2A count traces and official SOG labels for scoring; it
did not run the simulator, use future shot locations or shooter identities, or use starting-goalie
information. It does not tune on 2022, change a gate, or recommend adoption.
