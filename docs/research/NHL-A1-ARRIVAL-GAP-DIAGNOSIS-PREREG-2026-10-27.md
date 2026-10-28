# NHL A1 Arrival-Gap Diagnosis Preregistration

**Date:** 2026-10-27  
**Branch:** `research/nhl-a1-arrival-gap-diagnosis-2026-10-27`  
**Base:** `3c3afb9dc15155de6d006517b2ea833038ddb260`  
**Scope:** Mechanism diagnosis only. No candidate selection, production change, gate change, or A0/A1 source modification.

## Question

Explain why autonomous A1 generates 18.24 event bundles per 20-minute-equivalent period when the frozen evaluation reports 80.04 observed and 75.05 from A0. Separate conditional gap-model failure on observed states from additional error caused by autonomous state evolution. Do not assume that a lower event rate is caused by smoothing, initialization, feedback, or clock handling before measuring it.

## Frozen population and controls

- Fit population: the pinned eligible 2019 and 2020 transition rows only.
- Diagnostic population: all eligible 2021 regulation 5v5 transition rows and periods in the pinned cache. The 2021 population is already exposed development data; it is not an adoption holdout.
- Controls: frozen A0 and A1 implementations and the frozen evaluation definitions. Preserve their source files and original result artifacts byte-for-byte.
- Reuse the pinned source manifests, eligible-sequence cache, A0/A1 result JSON, and existing deterministic per-game/period/replicate seeds. Refuse changed hashes or population counts.
- Do not use future events from a target period to initialize the score-aware rollout. The period-start score may use only goals from completed earlier regulation periods. Do not use the actual opening-faceoff winner.

## Definitions to verify before scoring

1. **Bundle:** all eligible event tokens recorded at one whole-second event timestamp, ordered by the existing extractor. A bundle is not an individual event.
2. **Observed modeled gap:** a positive whole-second difference between adjacent eligible bundles where the interval remains unambiguous 5v5. The transition cache excludes the interval from period start to the first eligible bundle, the terminal interval after the final eligible bundle, and intervals that cross ineligible or non-5v5 states.
3. **Observed gap exposure:** the sum of retained transition gaps, not regulation clock and not the shift chart's full 5v5 seconds. Report all three quantities separately, along with excluded intervals and their reasons.
4. **Autonomous rollout:** `sample_trace` arrivals with integer `gap >= 1`; an arrival at or beyond second 1,200 is right-censored and is not emitted. Report the sampled terminal gap separately from event arrivals.
5. **Arrival model:** a categorical PMF on integer gaps 1–1,200. Do not describe it as a continuous-time hazard. Report `P(gap > t | context)` or gap PMF summaries instead.
6. **First modeled gap:** the first retained `Transition` in a period versus later retained transitions. The first retained transition is not necessarily the period-entry interval; do not conflate those labels.

## Mode A: historical-state replay

Fit A0/A1 on 2019/20 and evaluate each 2021 transition with its actual cached pre-event context and observed gap/mark. This is conditional next-transition prediction, not an autonomous rollout and not a prospective forecast.

Report, with game-clustered uncertainty where applicable:

- Gap log loss per eligible interarrival minute overall, for the first retained gap versus later gaps, by selected-context support/fallback, previous family, possession-known flag, score state, 5-minute clock bucket, and observed gap bin.
- Observed and predicted median, p90, p95, p99, and survival probabilities at 10, 20, 30, 43, 60, 120, and 300 seconds. Predictive summaries are averaged over each observed pre-gap context; do not pool unweighted per-transition probabilities as though contexts were equally likely.
- Bundle-size, ordered family-prefix, family, and owner likelihood components. Report faceoff-token incidence and within-bundle faceoff log loss separately from next-bundle first-family performance.
- A support table showing selected training-context count, prior mass, and development gaps absent from the unsmoothed training support.

## Mode B: autonomous rollout

Run 10 frozen common seeds for each eligible 2021 game-period with a 1,200-second horizon. Keep mark sampling, fit rows, context hierarchy, state update, seed derivation, and target definition fixed except for the single named factor in each diagnostic arm.

Arms:

| Arm | Single change from frozen A1 | Interpretation |
|---|---|---|
| B0 | None: alpha 0.5 on all 1,200 gap values; default `Context(faceoff, known, 0-0, bucket 0)` | Frozen reproduction control |
| B-smooth-off | Gap PMF uses empirical counts on the same selected context only, with no gap pseudocounts; mark smoothing remains 0.5 | Mechanism ablation, not a candidate. Report the development gap-support failure rate; do not treat its zero probability for unseen gaps as acceptable prediction. |
| B-start-score | Keep all frozen smoothing and sampling; change only initial score difference to the score at that regulation-period boundary, holding previous family=`faceoff`, possession-known=`true`, and clock bucket=0 | Cutoff-valid score-initialization diagnostic. The opening faceoff winner is not read. |

For each arm report bundle-count mean/variance/CRPS and game-clustered paired intervals, family counts, p50/p90/p95/p99 gaps, terminal censored gaps, selected-context support/fallback occupancy, and context occupancy by simulated elapsed-time bucket. Compare generated state occupancy with the observed distribution of pre-gap contexts. The smoothing-off arm is a deliberately extreme diagnostic; it cannot be selected as a model.

## Clock, censoring, and exposure reconciliation

Before interpreting any model contrast, require:

- PBP `timeInPeriod` parses as whole seconds in 0–1,200 and the cache's transition gap equals the difference between source bundle seconds.
- Exact agreement between the eligible cached transitions and source-reconstructed transitions for the source-reconciliation subset; any mismatch fails the diagnostic rather than being silently dropped.
- Per-period reconciliation of regulation seconds, shift-derived 5v5/non-5v5/ambiguous seconds, retained interarrival exposure, excluded intervals, period-entry exposure, and terminal exposure.
- Clear distinction among a full-period 1,200-second simulated horizon, source-derived 5v5 exposure, and the retained event-to-event exposure used by the frozen rate target.
- Count target retains the frozen definition `retained destination bundles * 1,200 / retained interarrival seconds`; also report raw retained destination count and do not relabel the rate-scaled target as an observed literal period count.

## First-divergence and feedback analysis

For the ten largest B0 per-period count errors, retain the original seeds and emit complete event traces with time, prior context, selected context key/support, categorical gap probability and uniform, mark factors, post-event context, terminal censored gap, and first index mismatch against the observed sequence. Reconcile source events to event IDs, sort order, and clocks. After the first mismatch, label subsequent state comparisons as trajectory divergence, not counterfactual causal effects.

Summarize which event families disappear in autonomous output versus observed destination marks, separating arrival count from conditional mark composition. Report state occupancy/support before each sampled gap and whether long waits arise in the first gap, later gaps, or both.

## One-factor interpretation rules

- A bad Mode A gap score establishes that A1's conditional gap distribution is already miscalibrated on observed contexts; autonomous feedback is not required to explain that component.
- A good Mode A score with poor Mode B output would implicate initialization, feedback, restart/state updates, or finite-horizon aggregation, subject to the diagnostics above.
- If both modes fail, report their measured contributions separately; do not attribute the full rollout deficit to one arm's response.
- Smoothing-off count recovery is evidence that the frozen smoothing support contributes to rollout counts, not evidence that zero smoothing is a valid fix. Unseen development gaps and proper-score failure remain explicit.
- A score-aware initialization effect is confined to periods whose score differs from 0–0 at the cutoff. Do not generalize it to other state components.
- No broad parameter sweep, global event-rate multiplier, model promotion, candidate selection, or holdout claim is authorized.

## Diagnostic pipeline regression tests

Add automated tests for the new diagnostic helpers covering: first-versus-subsequent retained-gap labeling; observed exposure as the exact sum of eligible gaps rather than full clock; right-censoring at the horizon; gap-PMF normalization and the analytically expected uniform-prior mass; gap-only smoothing ablation leaving mark probabilities unchanged; score-only initialization leaving family/possession/clock fixed; common-seed determinism; and fail-closed behavior on non-monotone source times, inconsistent transition counts, missing period-start score, or a changed frozen artifact hash.

Run these focused tests and the existing autonomous 5v5 tests. Also run the bounded real-data diagnostic, verify frozen A0/A1 aggregate reproduction and source/cache reconciliation, record commands and runtime, and inspect the final diff against this base before committing.

## Decision boundary

Deliver a mechanism-level explanation and ranked next experiments. If no one-factor diagnostic isolates a cause, say so and propose the next smallest falsifiable analysis. Do not implement or recommend a model correction until its measured cause and falsification condition are stated. Preserve `A0_SIMPLER_REFERENCE_OR_NEITHER`; do not alter any gate or production forecast.
