# NHL Autonomous Simulation: Mechanism and Data Gap Audit

**Date:** 2026-10-27 · **Branch:** `research/nhl-autonomous-mechanism-gap-audit-2026-10-27` · **Base:** `5449e508250f50e6228822ae5fc121026ddc4c42`

**Scope:** Diagnostic only. No parameter tuning, candidate selection, production forecast changes, or frozen A0/A1 edits.

## Executive finding

The largest measured A1 failure is its event-arrival distribution. On the same 2021 development population and eligible exposure, A1 loses **0.3181 nats per 5v5 minute** to A0 (game-clustered 95% interval **[0.3000, 0.3348]**). A1's gap component is worse by 21,776.81 nats; its bundle-mark component is better by 3,435.90 nats. A further decomposition shows that A1's bundle-size and family log losses improve, while owner log loss worsens; the net NLL loss is from arrival gaps.

The count results agree. Across 3,843 scored game-periods, observed bundle count averages 80.04 per 20-minute equivalent; A0 generates 75.05 and A1 18.24. A1's 95th percentile interarrival gap is 230 seconds, versus 43 seconds observed. The frozen A1 implementation assigns a uniform Dirichlet prior over all 1,200 integer-second gaps. At its minimum selected context size of 100 transitions, 600 prior pseudo-counts supply **85.7%** of the posterior mass. This is a direct, measurable mismatch between the smoothing support and the sparse context. Its causal contribution is strongly implicated by the implementation and output but has not been isolated in an ablation; this report does not retune it.

This is not evidence that A0 is ready to adopt. A0's aggregate bundle count is near the observed count, but it underproduces faceoffs (4.54 vs 17.00 per 20-minute equivalent) and overproduces stoppages (20.45 vs 15.37). A1 improves several next-family transition distributions, but its within-bundle faceoff-family likelihood worsens and it does not preserve faceoff winner side. Neither candidate enforces restarts or models player deployment. Keep A0 as a frozen reference only.

The frozen A0/A1 artifact did not retain event traces, so I added a diagnostic-only exporter and completed a bounded replay after the shared host cleared. It scored all **3,843 eligible periods × 10 A1 draws**, exactly reproduced the frozen A1 bundle-count CRPS (**56.311574**), reconciled both models' decomposed NLLs to the frozen totals, and emitted the ten highest-A1-period-CRPS traces. All ten generated traces matched the frozen sampler byte-for-byte; each raw PBP/shift sequence matched its cached transitions. The diagnostic took 52.64 seconds and did not change either model or frozen result. The top error cases show sampled 969-, 1,199-, and 1,034-second gaps; they also reveal that 4 of the ten traces start from a target context with a different score state or previous family than the simulator's fixed synthetic initial context. These are source-backed examples, not independent evaluation data or causal experiments.

## Evidence boundary and reproducibility

The frozen comparison uses 1,921 eligible 2019/20 games for training and 1,292 eligible 2021 games for development. It evaluates 229,842 eligible transition gaps over 57,645.7 5v5 minutes. A0 and A1 use identical source populations, transition definitions, scoring code, game-period targets, and ten seeded trace replicates per eligible development game-period. The 2021 events were not used for fitting. The comparison is development evidence, not an untouched adoption test.

The experiment covers conditional, continuous 5v5 event bundles over fixed 1,200-second horizons. Generated traces presume 5v5 and both goalies for the entire horizon. They are not complete periods or rule-valid games. The model has no penalties, exits from 5v5, overtime, shootouts, player deployment, teams, goalies, or spatial movement.

Source integrity was checked against the frozen hashes:

| Artifact | SHA-256 |
|---|---|
| A0/A1 kernel | `ea54dc59dd6df7a4372b506cc6a9105eda023abdf2de0017eece805722788773` |
| Transition extractor | `dd19648ffbb3c5b3a74b98490e62f71dfd6c990a2d4093c42b22c583ce7280bb` |
| Frozen evaluation runner | `a120a1a0b21987853faa9e145b3c4631d99347b2322e40fd5c7150eef60fa7a6` |
| A0/A1 result JSON | `6116b755505fbfeca9dabd512b3a8db328202f78d4cf0345ed8c457763da3326` |
| Event-State v3 source audit JSON | `1029c286cc3e20907338fea3f5f5bc612c6bb0bec793661f558ab57edd934f75` |
| Mechanism diagnostic script | `cfe3743f0333b03d678d0aafa83f516a5bf87f0bd6b371e7708ada979ead6733` |
| Mechanism diagnostic result JSON | `7a64d6d73cb3a2c8c23dbf53fc04ed93d4e09734fe5f29790a007f03aa3c13a6` |
| GameCenter PBP manifest | `d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990` |
| Shift-chart manifest | `deba1a38d9f9c969139dc15ac57e7085988c05bcab36db43bd87fe5805f1c6f5` |
| Sequence cache | `9cfba618ded78ed92ad2cb6e15be64b493ef768fc8d094669f2a9138ec5275b2` |

Primary references: [frozen A0/A1 report](NHL-AUTONOMOUS-5V5-ARRIVAL-REPORT-2026-10-27.md), [A0/A1 kernel](../../research/nhl/autonomous-5v5/kernel.py), [transition extractor](../../research/nhl/autonomous-5v5/data.py), [mechanism diagnostic script](../../research/nhl/autonomous-5v5/mechanism_diagnostics.py), [frozen result](../../research/nhl/autonomous-5v5/results/nhl-autonomous-5v5-arrival-development-2026-10-27.json), [trace and decomposition result](../../research/nhl/autonomous-5v5/results/nhl-autonomous-mechanism-diagnostics-2026-10-27.json), [Event-State v3 report](NHL-BEHAVIOR-EVIDENCE-EVENT-STATE-V3-2026-10-27.md), and [Event-State v3 result](../../research/nhl/behavior-evidence/results/nhl-behavior-evidence-event-state-v3-2026-10-27.json).

Reproduce the bounded diagnostic with `python3 research/nhl/autonomous-5v5/mechanism_diagnostics.py`. Its defaults pin the verified cache and raw-data root; the script also refuses changed cache or frozen-result hashes. It writes the trace JSON listed above. The stored `elapsed_seconds` field means a rerun's whole JSON hash will differ even when the seeded traces and metrics match.

## A0 versus A1: measured decomposition

### Held-out sequence likelihood

| Component | A0 NLL | A1 NLL | A1 − A0 |
|---|---:|---:|---:|
| Interarrival gaps | 843,973.55 | 865,750.37 | **+21,776.81** |
| Ordered event-bundle marks | 768,636.75 | 765,200.85 | **−3,435.90** |
| Total | 1,612,610.31 | 1,630,951.21 | **+18,340.91** |

Normalized total delta is +0.318134 nats per eligible 5v5 minute, 95% game-cluster bootstrap interval [0.300034, 0.334830] (2,000 replicates, seed 20261027). The independent decomposition exactly reproduces the frozen overall losses:

| NLL component | A0 | A1 | A1 − A0 |
|---|---:|---:|---:|
| Interarrival gap | 843,973.55 | 865,750.37 | **+21,776.81** |
| Bundle size | 145,896.16 | 142,323.20 | −3,572.97 |
| Event-family tokens | 452,756.58 | 451,778.85 | −977.73 |
| Event-owner tokens | 169,984.01 | 171,098.80 | +1,114.79 |
| Mark total (size + family + owner) | 768,636.75 | 765,200.85 | **−3,435.90** |
| Full total | 1,612,610.31 | 1,630,951.21 | **+18,340.91** |

The event-family component is not uniformly better. Faceoff-token loss increases by **2,724.6 nats** (48,715 tokens), while stoppage-token loss decreases by **2,517.2 nats** (43,826 tokens); the other families make smaller contributions. These are conditional family-token log losses within the ordered bundle model, not marginal event counts. This pinpoints a faceoff bundle-composition weakness that aggregate mark NLL concealed.

The decomposition groups held-out NLL by common gap interval, preceding family, score state, and five-minute elapsed-clock bucket. These are point estimates normalized within each grouping; the bootstrap confidence interval above remains for the overall game-clustered comparison.

| Observed gap interval | Gaps | A0 gap NLL/min | A1 gap NLL/min | A1 − A0 |
|---|---:|---:|---:|---:|
| 1–5 sec | 60,505 | 63.549 | 62.910 | −0.639 |
| 6–10 sec | 52,258 | 23.670 | 24.831 | +1.161 |
| 11–20 sec | 59,502 | 14.593 | 15.158 | +0.565 |
| 21–30 sec | 29,279 | 10.409 | 10.743 | +0.334 |
| 31–60 sec | 24,934 | 8.049 | 8.264 | +0.215 |
| 61–120 sec | 3,295 | 6.320 | 6.270 | −0.051 |
| 121–300 sec | 69 | 5.121 | 3.925 | −1.196 |
| 301–1,200 sec | 0 | — | — | — |

A1 is worse over the common 6–60 second intervals, but better at some short and rare long observed gaps. No eligible observed transition exceeds 300 seconds. A1 nevertheless generates a 230-second p95 because its discrete gap distribution reserves mass for unobserved long gaps.

Gap NLL is also worse for A1 in each leading/tied score state and each five-minute elapsed-clock bucket. For tied, home-leading, and away-leading contexts, A1−A0 gap NLL is respectively +0.342, +0.372, and +0.427 nats/min. By elapsed buckets 0–4:59, 5–9:59, 10–14:59, and 15–19:59, deltas are +0.292, +0.375, +0.386, and +0.488 nats/min. This broad pattern argues against one score-state or late-clock cell accounting for the aggregate failure.

### Event counts and forecast spread per 20-minute equivalent

The observed target is a fractionally scaled count over each period's eligible interarrival exposure. Forecasts are the mean of ten trace draws per period.

| Quantity | Observed | A0 | A1 | A0 CRPS | A1 CRPS |
|---|---:|---:|---:|---:|---:|
| Event bundles | 80.043 | 75.052 | 18.244 | 8.621 | 56.312 |
| Shot attempts | 38.315 | 39.781 | 9.628 | 4.876 | 25.611 |
| SOG | 21.166 | 21.852 | 5.325 | 3.475 | 13.994 |
| Goals | 1.768 | 1.889 | 0.539 | 0.950 | 1.259 |

The paired game-cluster CRPS difference A1−A0 is significantly worse for bundles (+47.697; 95% CI [47.209, 48.179]), attempts (+20.735; [20.422, 21.052]), SOG (+10.517; [10.312, 10.716]), and goals (+0.309; [0.279, 0.340]).

Observed bundle-count variance is 179.41. Mean within-period trace variance is 175.14 for A0 and 111.75 for A1. Observed central-80% interval coverage from the ten draws is 55.6% for A0 and 0.0% for A1. A1 is underdispersed on this count measure; the data do not support the earlier speculation that excessive A1 variance is the cause.

### Event-family composition

| Event family | Observed | A0 | A1 | A0 CRPS | A1 CRPS |
|---|---:|---:|---:|---:|---:|
| Faceoff | 16.997 | 4.537 | 1.199 | 11.334 | 15.195 |
| Stoppage | 15.370 | 20.448 | 4.821 | 4.509 | 8.961 |
| Hit | 18.373 | 17.571 | 4.309 | 4.565 | 12.662 |
| Shot on goal | 19.398 | 19.963 | 4.786 | 3.341 | 12.929 |
| Missed shot | 7.812 | 8.208 | 1.999 | 2.163 | 5.142 |
| Blocked shot | 9.337 | 9.721 | 2.304 | 2.339 | 6.223 |
| Giveaway | 6.353 | 6.860 | 1.735 | 2.429 | 4.225 |
| Takeaway | 5.007 | 4.817 | 1.226 | 1.880 | 3.463 |

A1's lower event volume affects nearly every family. A0's near-correct total volume masks a family-composition error: faceoffs are strongly low and stoppages high. The added likelihood decomposition shows a specific within-bundle faceoff-token penalty for A1; the ordered transition comparison below shows its first-family probabilities often improve. So the evidence points to a distinction between predicting the next bundle's first family and composing multiple same-second events inside one bundle. It does not yet identify the exact bundle-size/prefix mechanism that creates the faceoff count deficit.

### Event-arrival timing

| Interarrival gap quantile | Observed | A0 generated | A1 generated |
|---|---:|---:|---:|
| p50 | 11 sec | 11 sec | 12 sec |
| p90 | 33 sec | 33 sec | 46 sec |
| p95 | 43 sec | 43 sec | 230 sec |

The gap domain is integer seconds, 1–1,200; both the model and input use seconds. The source PBP and shift clocks are whole-second resolution, and transition gaps are computed as positive differences between eligible event-bundle clock seconds. This rules out a seconds-versus-minutes mismatch in the inspected code. The upper-tail mismatch is real in the frozen generated output.

The count simulation calls `sample_trace` with its default `Context("faceoff", True, 0, 0)` for every regulation period. In four of the ten top-error periods, the first observed transition context differs from this synthetic start: three have a non-tied score and one has a different previous event family and score. Both candidates share the initialization, so its effect on the A1−A0 gap is not established; A1 may be more sensitive because it selects context-specific gap PMFs. The prior score and event context can be reconstructed from information available at a real period cutoff. This evaluation-input mismatch needs an isolated sensitivity comparison before attributing every count error to smoothing.

The A1 smoothing setting is `alpha=0.5` on each of 1,200 possible gap values. At the minimum 100-row selected context, its prior contributes 600/(100+600)=85.7% of posterior mass; in the high-support tied/faceoff context used by most of the top traces (10,837 training bundles), the share is 5.2%. A0 has the same prior but pools 329,667 training transitions, so its prior share is negligible. The smoothing support is therefore a strong, directly measurable explanation for how long unseen gaps can be sampled, including from high-support contexts. Its contribution to aggregate under-count has not been isolated from context partitioning and initial-state mismatch.

### Highest-error generated sequence traces

The ten periods below are ranked by A1 per-period bundle-count CRPS, using the original ten seeds. For each period the shown generated draw is the replicate with the largest absolute bundle-count error among those ten; the A0 count uses the same numeric seed. Actual event IDs/order and clocks were recovered from raw GameCenter PBP and reconciled to the frozen transition cache. Generated clocks are relative seconds from the simulated period start. `P(gap)` is the categorical PMF probability of the observed or sampled gap under that row's context; these are not continuous-time hazards.

| Rank | Game / period | A1 CRPS; observed target | A1 / A0 bundles | First observed transition (elapsed; gap; source event ID/sortOrder and family) | First A1 draw (elapsed; gap; family) | P(gap), observed context / simulated context |
|---:|---|---:|---:|---|---|---:|
| 1 | `2021020624` P1 | 133.301; 155.61 | 3 / 76 | 00:09; 9s; `151/12` SOG(home) | 00:27; 27s; giveaway(home) | .04472 / .01290 |
| 2 | `2021020233` P1 | 112.492; 134.37 | 1 / 9 | 00:15; 15s; `8/11` stoppage + `53/12` faceoff(away) | 00:08; 8s; SOG(away) | .03388 / .04805 |
| 3 | `2021020800` P2 | 111.255; 140.67 | 8 / 73 | 00:28; 28s; `362/236` SOG(away) | 00:22; 22s; hit(home) | .01412 / .02147 |
| 4 | `2021021260` P2 | 111.089; 133.68 | 2 / 41 | 00:10; 10s; `303/288` giveaway(away) | 00:05; 5s; SOG(away) | .03765 / .04114 |
| 5 | `2021020543` P1 | 108.454; 123.90 | 5 / 89 | 00:06; 6s; `53/12` hit(home) | 00:07; 7s; missed-shot(away) | .04944 / .04971 |
| 6 | `2021021116` P2 | 107.079; 129.14 | 2 / 70 | 00:50; 1s; `401/322` missed-shot(away) | 00:16; 16s; missed-shot(away) | .02034 / .03117 |
| 7 | `2021020589` P1 | 101.755; 116.98 | 3 / 75 | 00:37; 37s; `9/12` hit(home) | 16:09; 969s; missed-shot(away) | .00616 / .0000437 |
| 8 | `2021020672` P2 | 101.473; 117.49 | 1 / 3 | 00:24; 24s; `313/243` SOG(away) | 19:59; 1,199s; hit(home) | .01718 / .0000437 |
| 9 | `2021021057` P2 | 99.392; 117.51 | 2 / 81 | 00:20; 20s; `305/285` hit(home) | 17:14; 1,034s; stoppage(unknown) | .02328 / .0000437 |
| 10 | `2021020940` P2 | 98.826; 121.59 | 8 / 75 | 03:55; 4s; `456/344` SOG(away) | 00:30; 30s; missed-shot(away) | .02642 / .01167 |

All ten traces first differ at event index 0, which is expected when comparing a stochastic draw with one observed realization and is not itself a causal diagnosis. The strongest trace evidence is the count and gap tail: ranks 7–9 sample 969–1,199-second gaps with probability 0.0000437, and produce 1–3 bundles while their observed 20-minute-equivalent targets are 116.98–117.51. Ranks 4, 6, 9 and 10 also start from a different observed score/previous-family context than the fixed synthetic context. After the first mismatch, the generated and actual states diverge; later event-by-event differences must not be read as paired counterfactual outcomes.

The first A1 step in all ten traces selects the same exact training context (`faceoff`, possession known, tied, clock bucket 0; support 10,837). In ranks 7–9, gap uniforms .989866, .999937 and .992716 select gaps of 969, 1,199 and 1,034 seconds, each with PMF probability .00004372. The first selected mark probabilities are .0424, .1054 and .0983 respectively. These traces expose how tail draws can starve the rest of a finite period. They do not prove the tail alone explains the aggregate under-count.

A1 has no continuous-time hazard function: it samples an integer-second gap from a categorical PMF conditioned on the current context. The trace records that PMF probability and uniform, the factorized bundle-size/family/owner probabilities, support, and state before/after. It therefore identifies the actual stochastic decisions available in the implementation, rather than inventing a hazard calculation. The machine-readable result is [the diagnostic trace JSON](../../research/nhl/autonomous-5v5/results/nhl-autonomous-mechanism-diagnostics-2026-10-27.json); it contains all ten first-step comparisons and complete generated traces.

## Shot creation → SOG → goal

The frozen traces count event families, not individual generated shot attempts with an independent shooter, goalie, shot type, or outcome record. Ratios of marginal forecast means are therefore aggregate diagnostics, not fitted per-shot calibration scores.

| Stage ratio | Observed | A0 | A1 |
|---|---:|---:|---:|
| SOG / attempts | 0.552 | 0.549 | 0.553 |
| Goals / SOG | 0.0835 | 0.0864 | 0.1013 |

The attempt-to-SOG ratio is close across all three. A1's goal-per-SOG ratio is high, but its event volume is much too low: attempts, SOG, and goals are forecast at 25%, 25%, and 31% of their respective observed means. The largest goal-count loss is consequently associated with too few generated opportunities; a smaller conversion discrepancy remains. This does not establish the cause of the conversion difference because no actual shot-level candidate outcomes are generated or retained.

The source archive supports richer retrospective analysis: 2021 has 146,319 eligible attempt events, 81,660 SOG events, and 8,213 goal events before the stricter A0/A1 transition-destination eligibility filter. Shot type, zone, x/y, shooter, and goalie fields are available in the Event-State v3 audit, but shot-type availability is outcome-dependent: blocked shots have no `shotType` or goalie ID recorded in the audited source. Shot type cannot be used prospectively by filling its missingness as a feature. A1 uses only the coarse event family and home/away/unknown owner.

## Conditional sequence and game-state evidence

The 2019/20 and 2021 archive includes ordered PBP events, `sortOrder`, whole-second clock, event owner, score progression, faceoff winner/loser, stoppage reason, shot families, and reconciled strength state. These support conditional event sequences; they do not reveal continuous possession or passes.

An existing source-backed faceoff proxy finds that, among **55,797 eligible 2021 5v5 faceoffs**, the faceoff winner's team recorded a shot before the next faceoff and within 30 game-clock seconds in **19,917 cases (35.7%)**. In the 2019/20 training 5v5 group this was 28,587 of 82,142 (34.8%). This is an event-sequence label, not continuous possession truth.

The trace diagnostic also compares the first event family in the next eligible timestamp bundle, conditioned on the preceding bundle's final family. Values below are observed held-out frequencies and mean model probabilities for the four most common outcomes in each row. This is a conditional mark comparison, not possession truth or a full sequence score.

| Previous bundle family | N | Four largest observed next-family rates | A0 probabilities | A1 probabilities |
|---|---:|---|---|---|
| Faceoff | 51,386 | SOG .243; hit .235; blocked .129; stoppage .116 | .236; .220; .116; .158 | .237; .228; .128; .124 |
| SOG | 47,852 | stoppage .289; SOG .213; hit .184; blocked .092 | .158; .236; .220; .116 | .294; .208; .181; .090 |
| Giveaway | 18,172 | SOG .281; hit .201; blocked .131; missed .115 | .236; .220; .116; .098 | .284; .191; .137; .116 |
| Hit | 51,302 | hit .265; SOG .238; blocked .117; stoppage .112 | .220; .236; .116; .158 | .255; .241; .118; .117 |

A1's first-family distribution tracks these conditional frequencies more closely than A0's pooled distribution in these large groups. In contrast, A1's gap NLL per minute is worse after blocked shots (+0.714), giveaways (+0.842), hits (+0.594), missed shots (+0.765), and takeaways (+1.131); it is slightly better after faceoffs (−0.049) and SOG (−0.159). The miss is therefore concentrated in the arrival-time distribution across many contexts, while some event-family transition dependence is already learnable from the archive and improves the held-out mark probabilities.

The prior Event-State v3 audit also fit rates on 2019/20 and measured 2021 outcomes under observed shift exposure. These are event-row diagnostics, **not A0/A1 forecasts**:

| Outcome | Observed training context | Training rate per 60 team-min | 2021 observed / training-expected |
|---|---|---:|---:|
| Attempt | 5v5 | 53.279 | 1.037 |
| Attempt | 5v4 | 87.848 | 1.087 |
| Attempt | 4v5 | 14.318 | 1.101 |
| Attempt | score tied | 53.501 | 1.046 |
| SOG | 5v5 | 29.205 | 1.044 |
| SOG | 5v4 | 48.718 | 1.100 |
| SOG | 4v5 | 10.529 | 1.101 |
| Goal | 5v5 | 2.408 | 1.056 |
| Goal | 5v4 | 6.352 | 1.107 |
| Goal | 4v5 | 0.883 | 1.127 |

The audit also reports attempt rates of 70.970 per 60 team-minute in the final minute and 52.635 with more than ten minutes remaining (2021 observed/expected 1.025 and 1.044). This confirms that the archive supports strength, score, period and time conditional estimates. A0/A1's evaluation artifact does not report loss or count calibration by these contexts; the autonomous comparison itself is 5v5-only, so special-team rates do not explain its failure.

A1's context stores `previous_family`, a boolean `possession_known`, tied/leading score state, and a five-minute clock bucket. Faceoff owner is stored in the sampled token, but the next context retains only whether possession is known, not which side won it. Consequently the model cannot condition the next event owner or shot chance on the winning team. Nor does a goal force a post-goal faceoff. A real source example is GameCenter game `2019020001`, period 1 at 00:25: goal event 10 (`sortOrder` 11) is followed by faceoff event 11 (`sortOrder` 14) at the same recorded second, both at reconciled 5v5. This demonstrates that the source can supply a concrete restart sequence. It does not quantify the frequency of generated restart violations.

## Pipeline and field-use inventory

| Source / field group | Evidence available in archive or DB | A0/A1 use | Gap exposed by inspection |
|---|---|---|---|
| PBP event ID/type, `sortOrder`, period, `timeInPeriod`, `timeRemaining` | 4,876-game verified GameCenter PBP manifest; 1,921 training and 1,292 development games eligible | Type mapped to a coarse family; same-second records are bundled in source order; adjacent clock differences train gap distribution | Absolute target event times and IDs are dropped from `Transition` and absent from the frozen result; the separate diagnostic now joins raw PBP IDs/order/clocks for ten traces |
| PBP event owner/team IDs; faceoff winner ID | Team ownership is resolved to home/away; faceoff winner ID can supply the owner side | Owner is retained on each token; the context discards side after updating `possession_known` | No team identity/strength, no winner-conditioned next possession or ownership |
| PBP score before/after | Reconstructed from goal sequence | A1 uses only tied/home-leading/away-leading category for context selection | No score margin, empty-net urgency, tactical state, or target outcome context beyond this coarse category |
| PBP `situationCode`; shift roster intervals | PBP and shifts each have 4,876-game manifests; event/shift reconciliation excludes ambiguous states | Used to select 5v5 events and exposure; special teams excluded | No personnel enters A0/A1 candidate context; 1.340% of 2021 regulation clock is state-ambiguous; shift-derived non-5v5 time is 871,987 seconds |
| Shift player/team IDs, period, start/end/duration, type and description | Historical shift charts; the Event-State audit reconciles player intervals and situation | Exposure eligibility only | No player participation, substitution, line policy, fatigue, or player-specific event rates in A0/A1 |
| PBP shooting player, shot type, zone, x/y, goalie ID, event result | Event-State v3 reports outcome-specific coverage; independent box scores check team score/SOG | Only goal/SOG/missed/blocked coarse family | No shot-quality, shooter, goalie, location, save, or rebound model; shot type is absent for all blocked-shot rows |
| PBP faceoff winner/loser, zone/location, next event | Faceoff outcomes and sequence are available; 2021 5v5 follow-up proxy above | Faceoff token family and owner only | No puck location or possession side carried into the subsequent gap/mark process |
| PBP stoppage reason and following faceoff | Recorded stoppage and restart records are available | `stoppage` token only | No rule-driven restart transition; unrecorded whistles and geometric adjudication are unavailable |
| Independent box scores | 4,876 manifest rows; audited scores and team SOG were cross-checked by the frozen v0.1 loader | Eligibility/reconciliation support, not model targets beyond event tokens | Boxscore totals do not reveal unrecorded event opportunities or puck sequence |
| Legendary Picks NHL DB | Prior read-only audit of `picks.dev.db`: 1,833 NHL `player_stats` rows and 54,727 `player_game_logs` rows are from 2025–26/2026–27; 2,812 team result/stat rows are from those seasons; 816 roster snapshots are 2027 | Not used to fit 2019/20 or 2021 | DB is not the historical behavior source. The needed old behavior exists in the verified GameCenter/shift archive, but historical as-of roster/deployment snapshots are not represented by these DB seasons. |

The database inventory comes from the committed Event-State v3 read-only audit, not a new broad DB scan. That report used SQLite `mode=ro` and `query_only=ON`. No database writes or new broad row-count queries were performed for this audit.

## Mechanism-level gap ledger

| Mechanism | Observed discrepancy | Root-cause evidence and classification | Data coverage / missing information | Proposed correction to investigate (not implemented) | Acceptance test / falsification |
|---|---|---|---|---|---|
| A1 interarrival gaps | A1 gap NLL +21,776.81 vs A0; p95 230s vs 43s; per-20m count 18.24 vs 80.04. Gap NLL is worse in common 6–60s intervals and all score/clock buckets. | **Measured smoothing mechanism; aggregate causal share not isolated.** A0/A1 both use alpha .5 over 1,200 values; A1 partitions contexts. Prior mass is 85.7% at selected context n=100 and 5.2% at n=10,837. Top-error traces sample 969–1,199s from probabilities 0.0000437. No unit mismatch. | Whole-second observed gaps; 57,645.7 eligible 2021 minutes. No observed gap >300s; no subsecond timing. | Preregister a controlled comparison separating initial-state conditioning from the gap prior/context hierarchy. Report conditional gap PMFs, supports, censoring, count effects, and game-cluster uncertainty before any selection. | A candidate must improve held-out gap NLL, tails, count CRPS and variance on identical periods. Falsify smoothing as main driver if a period-start-state correction alone removes the deficit or the mismatch remains in well-supported contexts. |
| Bundle arrival/count variance | A1 mean trace variance below observed for bundles, attempts, SOG and goals; A1 80% bundle-count coverage 0% | **Measured underdispersion**, consistent with too few arrivals. The top A1 periods have 1–8 bundles in the selected worst-error draws versus observed equivalent counts 117–156. | Same 3,843 periods and ten draws; top ten traces now persisted in the diagnostic JSON. | Decompose variance by context and compare period-start-state and gap-PMF effects without tuning. | Improve mean and variance/coverage jointly; matching only the mean fails. |
| Bundle/event-family composition | A0 faceoffs 4.54 vs 17.00; stoppages 20.45 vs 15.37. A1 is low for all listed families. A1 faceoff-token NLL is +2,724.6 nats vs A0; stoppage-token NLL is −2,517.2. | **Partially localized.** A1's next-bundle first-family probabilities improve in large prior-family groups, but its within-bundle faceoff-token likelihood worsens. The exact bundle-size/prefix sequence producing the faceoff deficit is not isolated. | 2021 5v5 destination counts include faceoff 48,717, stoppage 44,059, SOG 55,593, hit 52,746; source PBP preserves same-second `sortOrder` bundles. | Compare exact ordered mark patterns and bundle-size/family-prefix calibration; separate deterministic goal/restart pairs from empirical mark probabilities. | Improve family CRPS and joint bundle composition without losing the first-family conditional gains; falsified if the deficit is solely event-arrival volume. |
| Faceoff winner → subsequent play | Model cannot represent winner-controlled next possession; historical 5v5 winner-team shot proxy is 35.7% within 30s before next faceoff. | **Missing state representation in code.** `Context` has only `possession_known: bool`; winner side is not carried. Statistical dependence is available to estimate, but continuous possession is latent. | Faceoff winner/loser/team, clock, zone, strength, and following shot events available; puck control and unrecorded passes absent. | Preserve possession side as an explicit observed-proxy/latent state and compare faceoff-conditioned next-event and shot-within-30s forecasts, with uncertainty and fallback. | Altering the faceoff winner must alter the modeled distribution of subsequent owner/shot events; on held-out games calibration should improve over parent. No claim of observed possession truth. |
| Goal and stoppage restarts | A1 may sample an arbitrary family after a goal/stoppage; no forced restart transition. | **Deterministic transition/rule gap.** Kernel updates score and sets possession unknown after goal, but does not force faceoff. Source example `2019020001` P1 00:25 contains goal→faceoff. | PBP `sortOrder`, goal, next faceoff, zone; explicit full restart sequences. Offside/icing geometry and unrecorded whistles remain unavailable. | Separate deterministic goal→whistle/restart state logic from empirical non-rule event choice; also audit stoppage→faceoff by reason and season. | Every simulated goal in the applicable scope must produce the correct restart before open-play events; source-backed sequences and illegal counterexamples; fail on silent correction. |
| Shot creation, SOG, goal conversion | A1 attempt→SOG marginal ratio close to observed, but absolute attempts/SOG/goals are 25%/25%/31% of observed; goal/SOG ratio is high (0.101 vs 0.0835). | **Main measured error is opportunity volume; smaller conversion concern remains.** The current tokens do not represent individual shot outcomes or shooter/goalie. Ratio comparison is aggregate, not conditional per-shot calibration. | PBP has attempts, outcomes, coordinates, shot type, shooter and goalie with outcome-dependent missingness; box scores independently provide goals/SOG. | After arrival/count diagnosis, score a conditional shot-event ledger: attempts→miss/block/SOG→goal; use only fields available before each outcome and retain missingness cohorts. | Team-period attempt/SOG/goal joint distribution improves, while arithmetic reconciliation and calibration by independently available features hold. Falsified if only goal totals improve by distorting attempts or SOG. |
| Team and player effects | A0/A1 treat team labels as home/away event owners; no player participates in generated marks. | **Model capability absent, not data absent for historical behavior.** Team/player IDs, shifts, and event participation are in the archive. A1's “interaction” label does not mean player interactions: it is a context-conditioned renewal model. | 4,876-game PBP/shift archive supports retrospective team/player rates. LP DB current NHL rows do not contain 2019/20 or 2021 logs/snapshots. Cross-game as-of lineup availability, line identity, and coaching decision are not fully observed. | First quantify training support by player/team and on-ice seconds; estimate only cutoff-safe, shrunk rates with source and lineup uncertainty. | Player/team-conditioned rates beat pooled equivalents on later chronological games while preserving eligibility and calibration; no in-sample target-game roster features. |
| Line deployment and fatigue | Generated sequence has no personnel state or substitutions. | **Model omitted; behavior partially inferable from shift intervals.** No line labels, bench intent, or physiological fatigue. | Shift player/team/period/start/end/duration and PBP roster spots; no verified line/pair identity or fatigue. | Reconstruct on-ice groups from overlaps as an explicitly inferred label, then measure shift duration/substitution distributions before modeling policy. | Reconcile all inferred on-ice intervals to source shift charts and report ambiguity; falsify any claimed line/fatigue model that uses unsupported labels. |
| Manpower transitions | A0/A1 are conditional fixed 5v5 only and cannot generate penalties or special teams. | **Scope exclusion**, not demonstrated cause of the 5v5 comparison failure. | Penalty and shift evidence exists in the archive, but state ambiguity and penalty service semantics require their own validated engine. | Keep out of 5v5 arrival diagnosis; add only after Gate 1 state ledger and special-team exposure are independently validated. | No 5v5 candidate may silently cross non-5v5 or ambiguous intervals; full game claims require separate rule-state acceptance. |
| Period-start state in count simulation | Every simulated period starts tied 0–0 with `faceoff`, known possession; the observed first-transition context differs in 4/10 top-error periods (three non-tied, one also has previous family `hit`). | **Evaluation-input mismatch confirmed; aggregate effect unmeasured.** Both candidates share the default, but A1 conditions on this context and may be more sensitive. | PBP score and pre-event family are reconstructible at the period cutoff; frozen transition rows retain actual context, while `sample_trace` uses a fixed default. | Re-run the same seeds with only cutoff-valid period-start context changed; keep fitting, targets, and model parameters fixed. | If the A1−A0 count/CRPS gap materially shrinks, correct the evaluation interpretation; otherwise rule out this mismatch as a major contributor. |
| Sequence trace/provenance | Frozen A0/A1 result omitted traces; ten highest-A1-CRPS period traces are now emitted in a separate artifact. | **Instrumentation gap closed for this audit.** Trace exporter reproduces frozen A1 CRPS and NLL totals, verifies each sampled trace against the frozen sampler, and raw-source joins all ten cases to cached transitions. | New trace JSON contains source event IDs/sortOrder/clocks, actual/generated contexts, selected context keys/support, gap PMF probabilities/uniforms, mark factors, and state transitions. | Keep this trace schema/versioned for future preregistered diagnostics; preserve observed/generated labels and post-first-divergence caveat. | Artifact replays byte-identically, all ten raw/cache joins reconcile, and no future target state is fed into generated paths. |

## What data is genuinely missing versus merely unused

### Already available but not used by A0/A1

- Historical team IDs, event owner, faceoff winner/loser, score chronology, stoppage reason, and ordered PBP event families.
- Historical player IDs, positions, shot participation, shooter/goalie IDs where recorded, and shift intervals.
- Shot type, zone and x/y for most recorded attempts, with important outcome-dependent missingness; blocked-shot coordinates must not be treated as verified release points.
- Independent team box-score goals and SOG for reconciliation.
- Training-only conditional behavior tables from the Event-State v3 audit, including team faceoff rates and faceoff-winner follow-up shot proxies.

The model cache intentionally strips most of these features from `Token` and `Transition`. A1 does not use team strength, player rates, goalie ability, shift deployment, shot location/type, actual manpower as a predictor, or follow-up sequence labels.

### Not present in the current Legendary Picks DB historical window

The committed DB audit covers current NHL seasons (2025–26 and 2026–27) for player/team logs and 2026–27 roster snapshots, not 2019/20 or 2021 historical as-of snapshots. The GameCenter PBP and shift archive supplies the historical behavior evidence; don't re-ingest it merely because it is absent from the current DB.

### Genuinely unobserved or not independently validated in these sources

- Continuous puck possession and all passes between recorded PBP events.
- Shot opportunities that never become a recorded PBP event.
- Continuous player/puck coordinates, defensive coverage and passing lanes for the full 4,876-game archive.
- Actual shot release location on many blocked attempts; PBP's recorded block x/y is not validated as the release point.
- Coach intent, verified line/pair labels, bench policy, and physiological fatigue.
- Subsecond timing/reaction delay from these PBP and shift records.
- Geometric evidence to independently adjudicate all icing/offside calls and other spatial whistle decisions.

These gaps limit physical or causal claims. They do not prevent statistical estimation of recorded event sequences, team/player event rates, shifts, or observed stoppage/restart frequencies.

## Ranked, isolated next investigations

These are diagnostic experiments, not permission to tune A1 or select a candidate.

1. **Explain the interarrival-gap likelihood loss.** This is the largest NLL contribution (+21,776.81) and appears across common gap bins, score states and elapsed-clock buckets. The completed audit should be extended with gap calibration stratified by selected-context training support and a precise treatment of right-censored terminal exposure versus observed gaps. Then preregister one-factor diagnostic comparisons of context pooling and the 1,200-value smoothing support, holding training rows, targets, exposure and seeds fixed. Success: identify a mechanism that explains the held-out gap loss and finite-horizon count deficit together. Evidence against sparse-context smoothing as the principal explanation would be a similar gap failure in high-support contexts or a large count correction from forecast-origin handling alone. Since 2021 is exposed, it may diagnose mechanisms but cannot select an adoption candidate.
2. **Audit the forecast origin for count evaluation.** Regenerate identical seeds after constructing only the state genuinely known at each declared simulation start (including score and restart state where applicable); do not initialize from later target events. Compare count CRPS/variance, retaining identical fitted parameters and target exposure. Success: quantify how much of the count gap is due to the current synthetic 0–0/faceoff start. Falsification: the A1−A0 count gap is unchanged. The current 4/10 finding is from selected high-error periods and is not a population effect estimate. This is distinct from gap NLL, which was scored on observed transition contexts and cannot be explained by generated period initialization.
3. **Localize bundle composition and faceoffs.** Score bundle-size, family-prefix and owner factors, then compare same-second ordered bundle patterns and family counts. Preserve the first-family conditional result separately from within-bundle faceoff-token loss. Success: identify the exact prefix or bundle-size term behind faceoff underproduction. Falsification: composition is calibrated once arrival exposure is accounted for. Do not add a faceoff policy until this decomposition is clear.
4. **Test restart transitions independently.** Use real goal→whistle→faceoff and stoppage-reason→restart sequences to separate deterministic NHL rules from empirical event choice. Success: supported goals force a legal restart and source-conditioned restart frequencies remain calibrated. Falsification: event/clock evidence cannot distinguish required ordering; quarantine the ambiguous class.
5. **Decompose generated shot opportunities and conversion.** On source-availability cohorts, estimate attempt arrival, miss/block/SOG, and goal conditional on SOG with pre-outcome features only. Current evidence says volume is the larger measured discrepancy; the high aggregate goal/SOG ratio still needs a shot-level audit. Success: locate residual conversion loss after opportunity calibration. Falsification: conversion is calibrated and goal error tracks only opportunity volume.
6. **Measure the value and coverage of faceoff, team, player, goalie and shift information.** Start from the existing archive and as-of eligible features; use grouped chronological folds and explicit fallback rates. Success: stable held-out calibration improvement over pooled rates without target-game lineup/starter leakage. Falsification: support or cutoff-valid lineup evidence is insufficient. Keep continuous possession, coaching intent and physiological fatigue labeled latent/unobserved.
7. **Freeze and evaluate only on later unseen data.** Preregister the mechanism, cutoff, metrics and gates before accessing an eligible later season or prospective games. Success: improvements replicate with game-cluster uncertainty, source reconciliation and full accounting. Falsification: development-only gains do not replicate.

## Decision

This audit explains the dominant measured A1 loss at the component level: arrival-gap likelihood and finite-period under-counting fail, while aggregate mark likelihood improves. Gap loss is +21,776.81 nats and selected-context smoothing assigns substantial mass to gaps never observed in the eligible development transitions; representative traces show how rare long-gap draws consume most of a period. This is strong mechanism evidence, but the smoothing and forecast-origin effects have not been causally separated. Mark decomposition also exposes a faceoff-token weakness that the aggregate mark NLL hid, even as A1's next-bundle first-family distributions improve over A0 in several large groups.

The ten requested high-error traces and their categorical gap/mark probabilities are now archived and reproducible. Their event-index-0 mismatches are expected from independent stochastic paths; subsequent event-by-event differences cannot be interpreted as counterfactual causal effects. A0's near-correct total count masks a substantial family-composition error, while recorded team/player/shift and event-sequence evidence remains unused by these two candidates.

The existing `A0_SIMPLER_REFERENCE_OR_NEITHER` decision remains unchanged. No model is promoted, no rule/data gate is changed, and no production forecast is touched. The immediate next work is a preregistered mechanism separation of the gap process and forecast origin, followed by bundle composition; it is not another broad parameter sweep or a new event-generation candidate.
