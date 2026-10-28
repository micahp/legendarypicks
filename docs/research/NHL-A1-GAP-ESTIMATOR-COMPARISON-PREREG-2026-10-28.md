# NHL A1 Gap Estimator Comparison Preregistration

**Date:** 2026-10-28  
**Branch:** `research/nhl-a1-gap-estimator-comparison-2026-10-28`  
**Base:** `38e181418500be26df61a8b12fe42c78750d9292`  
**Scope:** Frozen-control comparison of timing estimators. Research only; no candidate adoption, production changes, shot-conversion tuning, or gate changes.

## Questions

1. How much probability does A1's uniform gap pseudocount place at each duration and in the long tail, and how does that compare with the raw empirical gaps and A0?
2. Does the failure differ between the synthetic first arrival, the first retained observed transition, and later transitions?
3. Are period-ending and 5v5-interrupted intervals excluded, mislabeled, or available as right-censored observations?
4. Can a pooled-distribution shrinkage estimator or a censor-aware time-to-event estimator improve historical-state prediction without losing support?
5. After completing the historical-state comparison, what happens to autonomous counts, variance, and event-family composition under the same seeds?

The new code is needed because the frozen A0/A1 harness has neither pooled-distribution shrinkage nor right-censored risk spells. These model-derived quantities have no publisher-defined values. The existing verified GameCenter PBP and shift archive is the source; this task does not acquire another source.

## Frozen inputs and controls

- Parent diagnostic: commit `38e181418500be26df61a8b12fe42c78750d9292`.
- Frozen A0/A1 timing kernel SHA-256: `ea54dc59dd6df7a4372b506cc6a9105eda023abdf2de0017eece805722788773`.
- Frozen sequence extractor SHA-256: `dd19648ffbb3c5b3a74b98490e62f71dfd6c990a2d4093c42b22c583ce7280bb`.
- Frozen eligible-sequence cache SHA-256: `9cfba618ded78ed92ad2cb6e15be64b493ef768fc8d094669f2a9138ec5275b2`.
- Parent diagnostic JSON SHA-256: `23edf72783ae694062051ec5adac53509eff22e3772bc28b5ebfd1e2ab6280a9`.
- Training: eligible 2019 and 2020 source games only. Development: the identical eligible 2021 population and transition definitions in the parent diagnostic. The 2021 season is exposed development data, never a fresh holdout.
- A0 and A1 source, metrics, marks, seeds, and previous results remain byte-for-byte unchanged.
- Source manifests and raw PBP/shift files are hash-checked and read-only. Any hash, population, transition, or exposure mismatch fails the run.

## Data and censor definitions

Reconstruct the verified PBP bundle sequence and second-by-second shift state from the pinned source. Reconcile every event-observed spell back to the frozen transition cache.

- A complete spell starts immediately after an eligible 5v5 bundle and ends at the next eligible bundle while the intervening exposure remains unambiguous 5v5. Its duration is the positive integer-second event gap.
- A spell is right-censored at the first ineligible PBP bundle, 5v5 exit, ambiguous state, or period end, whichever occurs first. Count each reason separately. An interrupted or terminal spell is never recorded as a long event gap.
- Do not bridge across an interruption. Spell duration is known 5v5 exposure from its origin to the censor boundary. Zero-exposure boundary ties are reported and excluded from duration likelihoods.
- Period-entry-to-first-event observations are a separate initialization stratum. Report their coverage and first-event distributions; do not silently pool them with post-event gaps or use a target game's opening-faceoff winner as a prospective rollout input.
- Primary historical-state replay remains on the frozen set of complete 2021 transitions so A0, A1, and candidates share identical scored event gaps. Also report a censor-aware joint likelihood over event and censored spells. Report first retained transition per period separately from later transitions.

## Estimators

All candidates retain A1's selected-context hierarchy and its `MIN_CONTEXT_BUNDLES=100` selection rule unless the model definition below says otherwise. Fit only with training sources.

| Name | Frozen definition | Purpose |
|---|---|---|
| A0 | Existing pooled categorical PMF with alpha 0.5 per integer second, 1–1,200. | Simpler reference. |
| A1 | Existing context-selected categorical PMF with alpha 0.5 per second, 1–1,200. | Reproduction of the failure. |
| B1 | For selected context `c`, `P(d|c) = [N_c(d) + 600 P_pool(d)] / [N_c + 600]`. `P_pool` is the training-only A0 pooled PMF, including its 0.5-per-second support prior. The 600 pseudo-count total matches A1's existing `1,200 × 0.5` prior mass; only its base distribution changes from uniform to observed pooled timing. | Isolate prior shape while preserving A1 context selection and full positive support. B1's gap PMF is fit to complete gaps; interrupted/terminal spells are censored in evaluation and are not added as long gaps. |
| B2-E | Context-conditioned discrete exponential/geometric event hazard fit from complete and right-censored 5v5 risk spells by maximum likelihood. | Test whether a constant conditional arrival hazard explains timing. |
| B2-W | Context-conditioned discrete Weibull survival model fit to the same right-censored spells by maximum likelihood; event probabilities are integer-second survival differences. | Test whether duration-dependent hazard improves fit. |

For B2-E/W, selected contexts with no finite, positive training event rate or a failed optimizer are a hard failure; do not silently fall back or replace the model. Record fit convergence and context support. B1 has fixed shrinkage strength 600; no tuning on 2021. No global arrival-rate multiplier is tested.

## Evaluation sequence

### Stage 1: audit before fitting candidates

Report the exact pseudocount mass allocation for A1: selected-context support distribution, prior-mass share, prior-only probability by duration, and smoothed versus raw empirical histogram/survival by fixed duration bins. Recompute A0 and A1 from the pinned source/cache and reconcile to parent values. Compare first synthetic gap, first retained transition, later transitions, and period-entry observations separately. Reconcile censored counts and seconds to source 5v5 exposure.

Fixed reporting bins are 1–5, 6–10, 11–20, 21–30, 31–60, 61–120, 121–300, 301–600, 601–900, and 901–1,200 seconds. These are summaries only; they do not tune candidate parameters.

### Stage 2: historical-state replay

Evaluate A0, A1, B1, B2-E, and B2-W on identical complete 2021 gaps and contexts. Separately score every right-censored spell with its survival probability. Report:

- Event-gap NLL and joint event/censor NLL per at-risk 5v5 minute.
- Paired game-clustered 95% confidence intervals for each candidate minus A0 and A1; 2,000 bootstrap replicates, seed `20261028`.
- Empirical and predicted p50/p90/p95/p99; survival at 10, 20, 30, 43, 60, 120, 300, and 600 seconds; observed Kaplan–Meier estimates and model calibration by first/later transition and selected-context support.
- Event versus censor counts, censor duration, and censor reason; verify that no censored duration is scored as an event.
- Conditional mark/family likelihood from the frozen A1 mark model. It must be identical across timing-only historical-state candidates.
- Context support and fallback rates; candidate optimizer/convergence diagnostics; finite probability for every observed event gap and positive survival for every censored spell.

### Stage 3: autonomous rollout

Only after Stage 2 metrics and censor reconciliation are complete, run A0, A1, B1, B2-E, and B2-W on identical 2021 game-periods, original common seeds, 1,200-second horizons, A1 mark sampler, and unchanged state update. Do not use observed future events or actual opening-faceoff winners. Report bundle mean/variance/CRPS and p50/p90/p95/p99 counts, generated gap quantiles and tails, terminal right-censor proposals, event-family counts/shares, SOG, attempts, and goals, with paired game-clustered intervals and runtime. This is a development comparison, not independent validation or adoption evidence.

If a candidate fails positive-support, finite-likelihood, source reconciliation, or reproducibility checks in Stage 2, do not run that candidate autonomously; report the specific failure.

## Acceptance and decision boundaries

- A model is not declared better because it matches the mean. It must have finite support and likelihood, be calibrated across the fixed survival thresholds, and be compared with A0 using game-clustered uncertainty.
- A historical-state improvement does not establish realistic autonomous gameplay. Rollout metrics are a separate required layer.
- Shot creation, SOG conversion, goal conversion, event marks, and scoring rules are frozen. Report their unchanged conditional likelihood and rollout outcomes, but do not tune them.
- No candidate is adopted and no gate changes in this task. If all candidates remain inferior or underdispersed, retain A0/A1 as research controls and specify what evidence would falsify the next proposed estimator.
- Add focused tests for prior mass normalization/support, B1 mixture math, right-censored spell boundaries, exact event/censor reconciliation, discrete survival probabilities, positive support, first/later labels, fixed-seed reproducibility, and fail-closed source/hash mismatch.

## Resource and execution protocol

Before any archive-wide extraction or rollout, inspect the called code for concurrency, then check `uptime`, `free -h`, and active CPU jobs. Run one real game first, verify its spell ledger against source PBP and shifts, and monitor load/headroom before the sequential full population. Do not use parallel workers. Report actual runtime and resource conditions.
