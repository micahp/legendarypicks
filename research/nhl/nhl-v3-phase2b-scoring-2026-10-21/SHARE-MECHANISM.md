# Phase 2B home-away share mechanism audit

Diagnostic only. This audit reuses the pinned 2021 development snapshot and its 16 stored Phase 2A draws per game. It does not rerun the simulator, change frozen Phase 2A, select a candidate, or change a gate.

## Where the coupling comes from

The exact count-generation sites are in frozen `research/nhl/nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py`:

- `:416-426` (`_GameBuilder._shot`) recomputes each side's shot rate and assigns the next attempt to home or away by a Bernoulli mark proportional to the two rates. Attempts are counted at `:442-446`; a saved or goal outcome increments that team's SOG at `:454-456`.
- `:481-488` generates the regulation wait from the sum of the two team rates. The same sum-rate clock is used in OT at `:559-566`; a tied game enters sudden-death OT at `:551-580`.
- The side rates come from `shot_rate` and `state_key` (`:191-208`, `:229-238`): team/opponent quality buckets, side, period, manpower, score state and clock buckets all affect the rates. A goal changes the score used by subsequent rates (`:457-462`); penalties change the manpower state (`:501-535`).

At one frozen state with fixed rates, an exponential wait at the sum rate followed by a rate-proportional team mark is the competing-hazard construction for independent home and away Poisson clocks. The complete simulator path is not exogenous, however: scores and manpower respond to generated events, the clock advances, and regulation ties condition entry into sudden-death OT. Thus the complete home and away game counts are **not conditionally independent given the realized endogenous state path**. Conditional independence applies only to the fixed-rate, fixed-endpoint idealization.

For that idealized fixed exogenous path, `Cov(H,A | path)=0`. It is not an estimable conditional term for the actual endogenous path from these saved counts. The directly measurable within-game predictive covariance across the 16 draws is −7.355 (95% interval [−8.333, −6.390]); the across-game mixture of the 16-draw means contributes another −1.465. The within-game term includes both fixed-total allocation and state/path feedback, so it is not a pure causal estimate of the shared-state effect.

The compact saved trace has game-level counts, not event-level intensity/state paths. The exact finite-snapshot covariance can still be decomposed by conditioning on game and total attempts, then mixing over totals within each game, then mixing the 16-draw game means across games:

| Empirical covariance component | Estimate | 95% game-cluster interval |
|---|---:|---:|
| Mean `Cov(H,A | game,N)`; fixed game and total-attempt count | −6.206 | [−6.535, −5.864] |
| Within-game covariance of conditional means as `N` varies | −1.149 | [−2.031, −0.310] |
| Across-game covariance of the 16-draw mean pairs | −1.465 | [−2.088, −0.863] |
| Sum / direct generated mixture covariance | **−8.820** | [−9.946, −7.740] |

These three terms sum exactly for the stored game-by-draw population. The first term captures the mechanical one-side-per-attempt allocation at fixed `N`; the second captures the within-game mixture over totals and evolving paths; the third is the cross-game mixture of predicted means. The second term cannot be separated into strength-bucket, clock, penalty, score-feedback and OT effects from this trace. These are an empirical covariance decomposition, not a causal state-path attribution. All intervals resample game IDs and condition on the same realized 16 draws.

## Why the generated share is too even

For attempts, generated home-share SD is 0.0569 versus 0.0784 observed; the share overdispersion index is 1.449 versus 2.759. The generated share variance is 0.003239, below observed 0.006153 by 0.002914 (paired 95% interval [0.002444, 0.003373]).

The event mark does create mechanical negative allocation at a fixed total. But the simulator has no adjustable game-level possession budget or latent home-away share dispersion. Its total remains random over fixed regulation and OT clocks, while each side's hazard is set by the current categorical rate features and shared game state. The side-rate pair does not include an independently calibrated, game-level allocation draw. This leaves the observed cross-game split variation underrepresented.

The minimum Phase 2C code surface to investigate, without changing it in this task, is:

1. Fit and serialize a training-only allocation-dispersion parameter alongside the relevant `FittedParameters` fields.
2. Draw one game-level home-away allocation state from the existing per-game seeded RNG in `_GameBuilder.__init__`.
3. Centralize the side hazards in one helper used by the regulation clock, OT clock, and `_shot` team mark. For a share-only ablation, renormalize the two hazards to preserve their existing sum so the allocation change does not alter total pace.

## Share-only moment sizing

This is a moment counterfactual, not a simulated candidate. Keep V3's generated total attempts (`mean 112.940`, `Var(N) 130.535`, `CV 0.10116`) and independently substitute the observed empirical share moments (`mean 0.514583`, `Var(s) 0.006153`). The resulting moments are:

| Quantity | Share-only estimate | 95% game-cluster interval | Observed |
|---|---:|---:|---:|
| `Var(H)` | 113.854 | [107.686, 119.693] | 117.597 |
| `Var(A)` | 110.047 | [103.830, 116.065] | 116.503 |
| `Cov(H,A)` | −46.683 | [−52.464, −40.415] | −44.710 |
| `Var(H−A)` | **317.268** | [292.546, 340.210] | **323.520** |

The share-only covariance differs from observed by −1.973 (paired interval [−5.080, +1.094]); the margin-variance difference is −6.252 (paired interval [−13.051, +0.402]). These differences are not resolved by this sample. Matching the observed covariance exactly at the point estimates would require `Var(s)=0.006000`, slightly below the observed 0.006153; the paired interval for that variance difference is [−0.000394, +0.000085], which includes zero. Under independence, the observed mean share, share variance, and covariance are therefore not an exact simultaneous point fit, though the mismatch is not statistically established here.

Share-only sizing closes most of the home-away margin spread gap while retaining the generated pace distribution. It does not fix total pace: generated `Var(N)` remains 14.145 below observed 144.679 (paired 95% interval for the generated-minus-observed gap [−26.015, −2.380]). Share/allocation dispersion and pace dispersion are separate margins.

## Limits and decision

The stored count trace cannot identify a causal covariance contribution for the exact strength-bucket sequence, common clock, score feedback, penalties or OT. Doing that would need saved event-level paths or a new controlled replay, which this diagnostic did not perform. The share-only results are moment sizing, not goal/SOG CRPS evaluation and not evidence to adopt an allocation model. Phase 2A remains a research prototype; this report makes no candidate-selection or adoption recommendation.

## Reproduction

From the repository root:

```sh
/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2b-scoring-2026-10-21/share_mechanism.py --bootstrap-replicates 2000 --seed 20261022
```

The script validates the stored trace hash, frozen Phase 2A hashes, game and draw counts, and cross-checks the generated mean/covariance and observed share variance against the committed pace report. It ran in 2.8 seconds, reused all 16 draws for each of 1,312 games, and performed no simulator Monte Carlo. Machine-readable estimates, intervals and input hashes are in `share_mechanism.json`.
