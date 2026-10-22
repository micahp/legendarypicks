# Phase 2C feasibility kernel fix

**Classification: diagnostic only.** No candidate was selected, no gate changed, no simulator was run, and no frozen Phase 2A artifact was edited. The run uses the committed Phase 2A 2021 count trace and the preregistered SOG eligibility mask.

## Result

The corrected kernel produces no impossible side counts: across 25,190,400 candidate team-draw cells, **SOG exceeded attempts 0 times (0.000%)**. At σ=0.324, the mean paired team-SOG CRPS change is **+0.115111** (candidate minus Phase 2A), with a 2,000-replicate paired game-cluster 95% interval of **[+0.089913, +0.141358]**. Condition A passed **0/100** replicates at that σ; its non-worsening requirement still binds, and the positive interval supports a real deterioration on this evaluation population.

The prior independent-resplit result at σ=0.324 was +0.154630. The new mean is lower by 0.039520 (25.6%), but that difference is **not an estimate of how much the impossible events caused**. The old condition-A CRPS is computed from each team's SOG marginal ensemble and observed SOG labels; the separately resplit attempt counts do not enter that score. The new kernel changes the SOG predictive distribution itself. Thus the impossible SOG/attempt pairing invalidated the event interpretation, while the CRPS comparison alone cannot assign any share of its old penalty to that pairing artifact.

## Kernel and continuity

For every committed game-draw and side, the baseline conversion rate is (p_0=SOG_{2A}/Attempts_{2A}); zero attempts map to (p_0=0). A shared standard-normal latent (U) shifts the home and away conversion logits by (+σU) and (-σU). A deterministic 32-point Gauss-Hermite offset centers each side's probability so its marginal conversion rate remains (p_0). The outcome is then sampled as `Binomial(committed side attempts, adjusted side probability)`. The same uniforms and latent values are reused across σ for each replicate.

This construction keeps each Phase 2A attempt count and home/away split fixed. Binomial support proves `0 <= SOG_side <= attempts_side` for every draw. Total SOG is allowed to vary as the sum of the two conditional binomial outcomes.

There is no exact-identity branch at σ=0. That would be a different kernel from a conditional-binomial draw. The tested family includes its conditional-binomial limit at σ=0, the smallest tested value. At that point, (Attempts_{2A}\times p_0=SOG_{2A}) for every stored team-draw to maximum absolute arithmetic error **7.11e-15**; the realized binomial counts are not the stored Phase 2A SOG trace. Across all tested σ values, the 32-point quadrature's maximum side-rate mean error was **2.22e-16**. For fixed latent values, the probability map converges to (p_0) as σ tends to zero. This treats σ=0 as the continuous probability-law limit, not as exact Phase 2A sample identity.

## Results by σ

The baseline Phase 2A team-SOG CRPS is 3.912575. Intervals below are paired game-cluster bootstrap intervals for the Monte-Carlo-averaged per-game delta; each uses 2,000 game-ID resamples. A/B/joint counts use 100 fixed-seed replicates. Pass-rate intervals are Wilson 95% intervals in the JSON artifact.

| σ | A: SOG CRPS non-worse | B: attempt rule as written | Joint | Mean SOG CRPS Δ | Paired game-cluster 95% CI | SOG > attempts fraction |
|---:|---:|---:|---:|---:|---:|---:|
| 0.000 | 4/100 | 0/100 | 0/100 | +0.023651 | [+0.010267, +0.036878] | 0.000% |
| 0.100 | 2/100 | 0/100 | 0/100 | +0.029689 | [+0.014927, +0.044716] | 0.000% |
| 0.160 | 1/100 | 0/100 | 0/100 | +0.041505 | [+0.024895, +0.058837] | 0.000% |
| 0.240 | 0/100 | 0/100 | 0/100 | +0.068940 | [+0.048638, +0.090590] | 0.000% |
| 0.324 | 0/100 | 0/100 | 0/100 | +0.115111 | [+0.089913, +0.141358] | 0.000% |
| 0.450 | 0/100 | 0/100 | 0/100 | +0.220925 | [+0.187978, +0.254638] | 0.000% |

The pass-rate counts are Monte Carlo diagnostics, not independent game-level trials. At σ=0.324, all 100 replicate mean deltas are positive. At σ=0, the 4/100 A passes reflect finite replicate variation; its game-cluster interval is also wholly above zero.

## Condition B and the degenerate interval

Before the run, a zero-width paired interval was designated **undefined for the interval-only subcriterion and never a pass**. Since the required attempt split is fixed, the candidate attempt-margin variance is exactly the Phase 2A value, **165.813**, below the preregistered point target **244.667**. The paired variance interval is exactly **[0, 0]** at every σ.

Therefore B as written fails **0/100** at every σ, and the joint rule also fails **0/100**. Under the degenerate-interval sensitivity, the interval-only component is undefined in **100/100** replicates; the full B condition still fails because its point-variance target is not met. Treating the interval component as undefined does not turn B or the joint rule into a pass. The preregistration and gate text were not changed.

## Population, reproducibility, and limits

- 1,312 trace games; 16 committed draws per game. SOG CRPS uses the identical 1,292 accepted official-SOG games for predictions and labels. Attempt calibration uses all 1,312 games.
- 100 replicates at each of the six preregistered σ values; replicate seeds 20261023–20261122. The same seeded normal and binomial uniforms are reused across σ within replicate.
- 2,000 game-cluster bootstrap resamples, seed 20261022. The SOG interval resamples the 1,292 eligible games; the attempt interval resamples all 1,312 attempt games.
- Runtime: **111.23 seconds** with BLAS/OpenMP limited to one thread. The output records seeds, hashes, per-replicate results, Wilson intervals, runtime, and accounting in [`kernel_fix.json`](kernel_fix.json).
- Five focused kernel tests pass. They cover rate centering, the σ-to-zero probability limit, reproducible common-random-number draws, physical SOG/attempt bounds, and the degenerate paired interval.
- Frozen Phase 2A hashes matched before and after: `EVALUATION.json` `24d5a55754a6b072f66203096a1936036a8d209df870ef6f8787bd0a22fc3930`; `FITTED-MODEL.json` `8e0304b9dbe4230f9deb17abda0ebe79cd89653289d2661a1612d79f8914addb`; `REPORT.md` `b0867d3cf1ef64a30469d087a03bda9ed156bbbbe020458b3efbb562473036f0`.

This remains a count-level diagnostic, not an event-stream replay. The conversion rates come from the committed Phase 2A model-output draws; they are not separately estimated pregame probabilities. It reconstructs no shot locations, shooters, goals, special teams, game clocks, regulation, overtime, or shootouts. The bootstrap intervals condition on these fixed game labels and model protocol; replicate percentiles in the JSON separately show simulation variability.

## Reproduction

From this directory:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python3 kernel_fix.py --replicates 100 --output kernel_fix.json
python3 -m unittest -v test_kernel_fix.py
```
