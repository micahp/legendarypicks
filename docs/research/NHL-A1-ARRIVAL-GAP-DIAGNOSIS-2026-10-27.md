# NHL A1 Arrival-Gap Diagnosis

**Date:** 2026-10-27
**Branch:** `research/nhl-a1-arrival-gap-diagnosis-2026-10-27`
**Diagnostic preregistration:** `02c419d99065fe61085cb085a9eff60cb82d92fd` (SHA-256 `2f22f5b75e8317d10098878ada1eb009d75a8078dbd9cec76864007b8075ac96`)
**Base:** `3c3afb9dc15155de6d006517b2ea833038ddb260`
**Scope:** diagnostic only; A0/A1 frozen; no candidate selection, tuning, gate change, or production forecast change.

## Finding

**The largest measured cause is A1's smoothed categorical interarrival-gap distribution.** On actual 2021 pre-gap states, A1's predicted gap tail is already much too long: the context-mixture p90/p95/p99 are 375/788/1,118 seconds versus observed 33/43/66. The gap-NLL rate is +0.37777 nats per 5v5 minute worse than A0 (game-clustered 95% CI +0.36931 to +0.38667). Later observed transitions account for the excess; the first scored transition is slightly better under A1. Autonomous feedback is therefore not needed to produce the main conditional timing failure.

A1 puts a uniform pseudocount of 0.5 on every integer gap from 1 to 1,200 seconds. Its observed-context-weighted prior mass is 14.53%, versus 0.18% for pooled A0, and the smoothed A1 mean gap rises to 100.31 seconds from the context-weighted empirical 15.22 seconds. Removing only that gap pseudocount restores the rollout mean from 18.24 to 82.31 bundles per full-period trace and lowers bundle CRPS from 56.31 to 8.38. That arm gives zero probability to 951 held-out gaps, however, so its full historical-state gap NLL is infinite; it diagnoses the mechanism and is not a usable fix.

Score-aware period initialization does not explain the shortage: it reduces the A1 mean to 17.03 and worsens bundle CRPS by 1.479 (95% CI +1.403 to +1.555). Shot-on-target conversion is also not the primary shortage: A1's SOG/attempt ratio is 0.553 versus 0.552 observed, while its goal/SOG ratio is somewhat high (0.101 versus 0.084). The low absolute goal count is chiefly downstream of too few generated bundles and shot opportunities; event composition and faceoff marking remain separate defects.

## Population, clock, and censoring

- Re-extracted source population: 1,292 games and 3,876 regulation periods; 229,842 cached transitions matched raw PBP/shift reconstruction, with zero mismatches.
- Scored rollouts: 1,285 games / 3,843 periods; 33 periods had no qualifying retained transition exposure. Training used 329,667 2019–20 transitions; evaluation scored 229,842 2021 gaps.
- Regulation clock: 4,651,200 seconds. Shift-derived 5v5 / non-5v5 / ambiguous exposure: 3,718,639 / 871,987 / 60,574 seconds.
- Retained event-to-event exposure: 3,458,744 seconds; period-entry 5v5 edge 9,086, terminal edge 55,764, and other unpaired 5v5 exposure 195,045 seconds.
- Source exclusions across 2021: `{"adjacent_bundle_not_eligible": 60870, "interval_not_5v5": 249, "shift_state_ambiguous": 1936}`. The clock is validated as nondecreasing whole seconds within each source period, in `[0, 1200]`.

The observed target remains the frozen 20-minute-equivalent rate: retained destination bundles × 1,200 / retained eligible gap seconds. It is not a literal full-period event count. Rollouts use a 1,200-second horizon. Each trace records its next sampled gap at or beyond the horizon as one terminal right-censored proposal; it is not emitted as an event. There is no minutes/seconds mismatch, cache/source mismatch, or hidden addition of period-edge exposure to the denominator.

## Mode A: historical-state replay

Each observed next gap is scored using its actual pre-gap context; generated states do not feed this replay. The first scored gap per period is not the interval from period start to its first event.

| Model | Gap NLL (nats) | NLL / 5v5 min | First scored / min | Later / min |
|---|---:|---:|---:|---:|
| A0 | 843973.55 | 14.64069 | 11.75150 | 14.70823 |
| A1 | 865750.37 | 15.01846 | 11.49098 | 15.10092 |
| A1 − A0 difference | +21,776.81 | +0.37777 [+0.36931, +0.38667] | -0.26052 [-0.28491, -0.23709] | +0.39269 [+0.38415, +0.40160] |

The first-transition gap-rate difference favors A1 (95% CI entirely below zero); the later-gap difference favors A0 (95% CI entirely above zero). Thus a poor synthetic period start is not required to create the A1 loss. Later gaps contribute +22,119.86 nats of the net +21,776.81 excess, partly offset by A1's −343.05 first-gap advantage.

### Gap quantiles and survival calibration

| Population / model | N | Observed p50 / p90 / p95 / p99 (s) | Predicted p50 / p90 / p95 / p99 (s) |
|---|---:|---|---|
| A0 all | 229,842 | 11 / 33 / 43 / 66 | 11 / 34 / 44 / 69 |
| A0 first_scored_transition | 3,843 | 16 / 40 / 51 / 76 | 11 / 34 / 44 / 69 |
| A0 later_scored_transitions | 225,999 | 11 / 33 / 43 / 66 | 11 / 34 / 44 / 69 |
| A1 all | 229,842 | 11 / 33 / 43 / 66 | 14 / 375 / 788 / 1118 |
| A1 first_scored_transition | 3,843 | 16 / 40 / 51 / 76 | 15 / 57 / 455 / 1051 |
| A1 later_scored_transitions | 225,999 | 11 / 33 / 43 / 66 | 14 / 381 / 791 / 1119 |

| Threshold t | Observed P(gap > t) | A0 predicted | A1 predicted |
|---:|---:|---:|---:|
| 10 s | 0.5094 | 0.5181 | 0.5870 |
| 20 s | 0.2505 | 0.2566 | 0.3616 |
| 30 s | 0.1231 | 0.1268 | 0.2490 |
| 43 s | 0.0490 | 0.0517 | 0.1830 |
| 60 s | 0.0146 | 0.0169 | 0.1511 |
| 120 s | 0.0003 | 0.0019 | 0.1310 |
| 300 s | 0.0000 | 0.0014 | 0.1090 |

A1's 95th percentile is 788 seconds versus 43 observed. On real contexts, A1 predicts P(gap > 60 s)=0.1511 versus 0.0146 observed; at 120 s it predicts 0.1310 versus 0.0003 observed. These are categorical PMF survival probabilities, not continuous-time hazards.

### Where the conditional gap NLL excess occurs

| Observed gap bin | Transitions | A1 − A0 gap NLL (nats) |
|---|---:|---:|
| 1-5s | 60,505 | -1789.42 |
| 6-10s | 52,258 | +7942.16 |
| 11-20s | 59,502 | +8336.36 |
| 21-30s | 29,279 | +4060.88 |
| 31-60s | 24,934 | +3624.06 |
| 61-120s | 3,295 | -205.28 |
| 121-300s | 69 | -191.94 |

A1's proper-score penalty is not dominated by a few observed extreme waits: its excess is concentrated in the common 6–60 second bins (+23,963.46 nats combined). The uniform prior's long tail is instead exposed most clearly by the conditional survival calibration and autonomous count collapse. State/clock/score breakdowns, complete survival Brier tables, and all support levels are preserved in the JSON.

### Smoothing support

A1 selected 98 contexts; their training-support median was 3,746.0. The context-weighted uniform prior mass was 14.534%; A0's pooled prior mass was 0.182%. A1's weighted empirical mean gap was 15.22 seconds, versus 100.31 after smoothing.

A1 assigned zero raw training support to 951/229,842 observed 2021 gaps (0.414%). Removing the prior repairs counts but creates infinite held-out gap NLL; it is not an acceptable calibrated model.

## Mode B: autonomous rollouts

A0 and A1 are distinct frozen fitted models. Within the three A1 arms, fit rows, hierarchy, state update, mark sampler, horizon, and common seeds are fixed; only the named gap smoothing or initial score changes.

| Arm | Generated bundles / 1,200 s | Observed target | Bundle CRPS | Emitted gap p50 / p90 / p95 / p99 (s) | First attempted gap p50 / p90 / p95 / p99 (s) |
|---|---:|---:|---:|---|---|
| A0_frozen | 75.05 | 80.04 | 8.62109 | 11 / 33 / 43 / 67 | 11 / 34 / 44 / 69 |
| A1_frozen | 18.24 | 80.04 | 56.31157 | 12 / 46 / 230 / 859 | 15 / 46 / 94 / 966 |
| A1_gap_prior_off | 82.31 | 80.04 | 8.38192 | 10 / 33 / 42 / 64 | 15 / 36 / 46 / 70 |
| A1_period_score_start | 17.03 | 80.04 | 57.78951 | 12 / 50 / 292 / 891 | 16 / 52 / 319 / 1023 |

The smoothing-off arm's bundle CRPS change versus A1 is −47.939 (95% paired game-cluster CI −48.564 to −47.315). Score-aware initialization changes CRPS by +1.479 (+1.403 to +1.555), a supported deterioration. A1 versus A0 is +47.697 (+47.209 to +48.179), also worse. Intervals use 2,000 paired game-cluster bootstrap replicates with seed 20261027; full intervals for all metrics and contrasts are in the JSON.

### Bundle-count variance

| Arm | Observed between-period variance | Mean generated within-period variance |
|---|---:|---:|
| A0_frozen | 179.41 | 175.14 |
| A1_frozen | 179.41 | 111.75 |
| A1_gap_prior_off | 179.41 | 69.70 |
| A1_period_score_start | 179.41 | 102.25 |

A1's within-period bundle variance is below the observed between-period variance (111.75 vs 179.41). The alpha-zero arm is more underdispersed (69.70), despite matching the mean. Count recovery alone is insufficient.

### Event-family counts per 20-minute equivalent

| Family | Observed target | A0 | A1 | A1 gap prior off |
|---|---:|---:|---:|---:|
| faceoff | 17.00 | 4.54 | 1.20 | 5.54 |
| hit | 18.37 | 17.57 | 4.31 | 19.23 |
| giveaway | 6.35 | 6.86 | 1.74 | 7.65 |
| takeaway | 5.01 | 4.82 | 1.23 | 5.54 |
| shot-on-goal | 19.40 | 19.96 | 4.79 | 21.60 |
| missed-shot | 7.81 | 8.21 | 2.00 | 9.09 |
| blocked-shot | 9.34 | 9.72 | 2.30 | 10.53 |
| goal | 1.77 | 1.89 | 0.54 | 2.56 |
| stoppage | 15.37 | 20.45 | 4.82 | 21.83 |
| other | 0.47 | 0.68 | 0.23 | 1.17 |

Aggregate SOG/attempt and goal/SOG ratios are 0.5524 and 0.0835 observed. A0 produces 0.5493 and 0.0864; A1 produces 0.5531 and 0.1013. These aggregate ratios show that attempt-to-SOG conversion is close, while goal conversion is somewhat high in A1; they do not replace per-shot calibration. The large absolute SOG and goal shortfall tracks the event-volume deficit.

### Faceoff mark likelihood is a separate problem

All 48,717 observed faceoff tokens occur after the first token within their event bundle; there are zero first-token faceoffs. A1's within-bundle faceoff NLL is 3245.06 nats (0.0666 per faceoff token), versus A0's 520.51 (0.0107). A1's next-bundle first-family NLL improves by 4601.57 nats, but that score contains no faceoffs. In rollout, faceoffs are 1.20 for A1 and only 5.54 with gap smoothing off, versus 17.00 observed. This is an independent mark/within-bundle sequencing gap, not evidence against the arrival diagnosis.

## First divergence: source-linked examples

The ten highest A1 count-error traces, their full generated paths, seeds, sampled gap probabilities/uniforms, context transitions, terminal censor proposals, and first observed source event IDs are in the JSON. Two long-wait examples:

- `2021020589` period 1: observed first eligible bundle after 37s (event 9 sortOrder 12 at 37s (hit)); A1 sampled a 969s first wait with probability 0.00004372 at uniform 0.98986614, then emitted 3 bundles against a 117.0 target. Selected context `["exact", "faceoff", true, "tied", 0]` had support 10,837.
- `2021020672` period 2: observed first eligible bundle after 24s (event 313 sortOrder 243 at 24s (shot-on-goal)); A1 sampled a 1199s first wait with probability 0.00004372 at uniform 0.99993731, then emitted 1 bundle against a 117.5 target. Selected context `["exact", "faceoff", true, "tied", 0]` had support 10,837.

These are realization traces, not paired counterfactuals. The first mismatch may be stochastic or an initialization-context mismatch; after it, trajectories diverge. The JSON records that distinction and does not attribute downstream differences causally to the first sampled event.

## Ranked next experiments and decision

1. **Supported gap-tail calibration.** Keep the integer-gap model and positive probability for unseen development gaps, but test one preregistered sparse-context pooling/shrinkage mechanism on a new development split. Measure Mode A tail calibration and NLL, autonomous count CRPS, mean, and variance. Falsify if tail calibration improves only by worsening held-out NLL or if the rollout remains underdispersed.
2. **Within-bundle faceoff process.** Separately diagnose the observed ordered bundle structure and conditional faceoff token probability. Evaluate faceoff incidence and likelihood without changing gap arrival probabilities. Falsify if faceoff counts do not improve on identical sequences or if other bundle-family calibration degrades.
3. **Initialization/context support.** Do not prioritize score-only initialization: its paired interval shows worse CRPS, and tied starts are unchanged. A later test can address the mismatch between the synthetic opening context and the first retained transition, without using the target-period future faceoff winner.

No correction is adopted and no candidate is selected. The A1 gap-prior-off arm is not adoptable because its full historical-state NLL is infinite and its trace variance is low. Keep the frozen A0/A1 controls and current gate unchanged. The 2021 population is exposed development data, not an independent adoption test.

## Data boundary and reproduction

No new source was needed to identify this timing failure: verified GameCenter PBP clocks/events and shift-derived 5v5 exposure were sufficient. PBP still does not observe every pass, continuous possession, or spatial puck/player state; those remain limits for future tactical and causal behavior, not blockers to this diagnosis. Source manifests and bodies were hash-checked read-only. No production forecast, gate, A0/A1 source, or frozen Phase 2A artifact changed.

- Preregistration: [protocol](NHL-A1-ARRIVAL-GAP-DIAGNOSIS-PREREG-2026-10-27.md).
- Diagnostic implementation and tests: [script](../../research/nhl/autonomous-5v5/arrival_gap_diagnostics.py), [tests](../../research/nhl/autonomous-5v5/tests/test_arrival_gap_diagnostics.py).
- Complete machine-readable decomposition: [result JSON](../../research/nhl/autonomous-5v5/results/nhl-a1-arrival-gap-diagnosis-2026-10-27.json).
- Frozen controls: [A1 report](NHL-AUTONOMOUS-5V5-ARRIVAL-REPORT-2026-10-27.md), [mechanism audit](NHL-AUTONOMOUS-MECHANISM-DATA-GAP-AUDIT-2026-10-27.md).

Full raw-source and rollout run: 379.74s; Mode A NLL interval postprocess: 72.50s; combined reported runtime: 452.24s. Result JSON SHA-256: `23edf72783ae694062051ec5adac53509eff22e3772bc28b5ebfd1e2ab6280a9`.
