# NHL Autonomous Simulation: Mechanism and Data Gap Audit

**Date:** 2026-10-27 · **Branch:** `research/nhl-autonomous-mechanism-gap-audit-2026-10-27` · **Base:** `5449e508250f50e6228822ae5fc121026ddc4c42`

**Scope:** Diagnostic only. No parameter tuning, candidate selection, production forecast changes, or frozen A0/A1 edits.

## Executive finding

The largest measured A1 failure is its event-arrival distribution. On the same 2021 development population and eligible exposure, A1 loses **0.3181 nats per 5v5 minute** to A0 (game-clustered 95% interval **[0.3000, 0.3348]**). A1's gap component is worse by 21,776.81 nats; its bundle-mark component is better by 3,435.90 nats. Thus the net NLL loss comes from arrival gaps, not the average likelihood of the event bundles conditional on the preceding context.

The count results agree. Across 3,843 scored game-periods, observed bundle count averages 80.04 per 20-minute equivalent; A0 generates 75.05 and A1 18.24. A1's 95th percentile interarrival gap is 230 seconds, versus 43 seconds observed. The frozen A1 implementation assigns a uniform Dirichlet prior over all 1,200 integer-second gaps. At its minimum selected context size of 100 transitions, 600 prior pseudo-counts supply **85.7%** of the posterior mass. This is a direct, measurable mismatch between the smoothing support and the sparse context. Its causal contribution is strongly implicated by the implementation and output but has not been isolated in an ablation; this report does not retune it.

This is not evidence that A0 is ready to adopt. A0's aggregate bundle count is near the observed count, but it underproduces faceoffs (4.54 vs 17.00 per 20-minute equivalent) and overproduces stoppages (20.45 vs 15.37). Neither candidate enforces hockey restarts or models player deployment. Keep A0 as a frozen reference only.

**Trace limitation:** the frozen evaluation artifact preserves aggregates, candidate/source hashes, and one fixed-seed equality check, but does not preserve generated event traces or per-transition selected probabilities. The requested ten highest-error traces and first-divergence attribution therefore cannot be reproduced from the committed artifact. A fresh full evaluation was started from the pinned cache and stopped after about 2:50 when shared-host load rose above 9 and available memory fell near 1.5 GiB. A separate bounded trace exporter then scored the first 500 of 3,843 periods, but a concurrent research process drove available memory below 1 GiB; that process was stopped and produced no accepted result artifact. Both PIDs were confirmed gone. The trace-specific task item remains open pending a resource-safe bounded trace run. No cause is invented to fill that gap.

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
| GameCenter PBP manifest | `d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990` |
| Shift-chart manifest | `deba1a38d9f9c969139dc15ac57e7085988c05bcab36db43bd87fe5805f1c6f5` |
| Sequence cache | `9cfba618ded78ed92ad2cb6e15be64b493ef768fc8d094669f2a9138ec5275b2` |

Primary references: [frozen A0/A1 report](NHL-AUTONOMOUS-5V5-ARRIVAL-REPORT-2026-10-27.md), [A0/A1 kernel](../../research/nhl/autonomous-5v5/kernel.py), [transition extractor](../../research/nhl/autonomous-5v5/data.py), [frozen result](../../research/nhl/autonomous-5v5/results/nhl-autonomous-5v5-arrival-development-2026-10-27.json), [Event-State v3 report](NHL-BEHAVIOR-EVIDENCE-EVENT-STATE-V3-2026-10-27.md), and [Event-State v3 result](../../research/nhl/behavior-evidence/results/nhl-behavior-evidence-event-state-v3-2026-10-27.json).

## A0 versus A1: measured decomposition

### Held-out sequence likelihood

| Component | A0 NLL | A1 NLL | A1 − A0 |
|---|---:|---:|---:|
| Interarrival gaps | 843,973.55 | 865,750.37 | **+21,776.81** |
| Ordered event-bundle marks | 768,636.75 | 765,200.85 | **−3,435.90** |
| Total | 1,612,610.31 | 1,630,951.21 | **+18,340.91** |

Normalized total delta is +0.318134 nats per eligible 5v5 minute, 95% game-cluster bootstrap interval [0.300034, 0.334830] (2,000 replicates, seed 20261027). A1's gap loss is only partly offset by a better average mark score. The frozen output does not break mark NLL down by event family, gap NLL by interval/context, or NLL by game state. Those requested sub-decompositions are not recoverable from its aggregate JSON.

The underlying archive supports the missing cuts: event clocks, period, pre-event score, reconciled strength and event family are in the Event-State v3 audit. But the saved A0/A1 output has only overall gap/mark NLL, and the `Transition` cache does not retain absolute event seconds or PBP IDs. The reported A1 gap percentiles and family count CRPS are diagnostics, not the requested NLL breakdown by time bin/state or first-divergence sequence analysis.

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

A1's lower event volume affects nearly every family. A0's near-correct total volume masks a family-composition error: faceoffs are strongly low and stoppages high. The current saved result does not provide the family-specific NLL or sequence traces needed to attribute that A0 discrepancy to extraction, mark probabilities, or the bundle definition.

### Event-arrival timing

| Interarrival gap quantile | Observed | A0 generated | A1 generated |
|---|---:|---:|---:|
| p50 | 11 sec | 11 sec | 12 sec |
| p90 | 33 sec | 33 sec | 46 sec |
| p95 | 43 sec | 43 sec | 230 sec |

The gap domain is integer seconds, 1–1,200; both the model and input use seconds. The source PBP and shift clocks are whole-second resolution, and transition gaps are computed as positive differences between eligible event-bundle clock seconds. This rules out a seconds-versus-minutes mismatch in the inspected code. The upper-tail mismatch is real in the frozen generated output.

One evaluation input also deserves a controlled audit before attributing the entire CRPS difference to model fit: `sample_trace` initializes every generated period with `Context("faceoff", True, 0, 0)`. This is a tied, 0–0 start for every regulation period, while periods 2 and 3 can begin with a pre-existing score. Both candidates share this initialization, so it does not explain the raw comparison by itself; however, the context-specific A1 gap model may be more sensitive to that mismatch. The observed score at period start is present in PBP and can be reconstructed without future leakage. No period-start-state sensitivity result is saved.

The A1 smoothing setting is `alpha=0.5` on each of 1,200 possible gap values. At the minimum 100-row selected context, its prior contributes 600/(100+600)=85.7% of posterior mass. A0 has the same prior but pools 329,667 training transitions, so its prior share is negligible. This is the strongest specific implementation-level explanation available for the gap tail and under-count. Its effect size has not been separated from context partitioning and other A1 choices.

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
| PBP event ID/type, `sortOrder`, period, `timeInPeriod`, `timeRemaining` | 4,876-game verified GameCenter PBP manifest; 1,921 training and 1,292 development games eligible | Type mapped to a coarse family; same-second records are bundled in source order; adjacent clock differences train gap distribution | Absolute target event times and IDs are dropped from `Transition`; saved model result has no event trace |
| PBP event owner/team IDs; faceoff winner ID | Team ownership is resolved to home/away; faceoff winner ID can supply the owner side | Owner is retained on each token; the context discards side after updating `possession_known` | No team identity/strength, no winner-conditioned next possession or ownership |
| PBP score before/after | Reconstructed from goal sequence | A1 uses only tied/home-leading/away-leading category for context selection | No score margin, empty-net urgency, tactical state, or target outcome context beyond this coarse category |
| PBP `situationCode`; shift roster intervals | PBP and shifts each have 4,876-game manifests; event/shift reconciliation excludes ambiguous states | Used to select 5v5 events and exposure; special teams excluded | No personnel enters A0/A1 candidate context; 1.340% of 2021 regulation clock is state-ambiguous; shift-derived non-5v5 time is 871,987 seconds |
| Shift player/team IDs, period, start/end/duration, type and description | Historical shift charts; the Event-State audit reconciles player intervals and situation | Exposure eligibility only | No player participation, substitution, line policy, fatigue, or player-specific event rates in A0/A1 |
| PBP shooting player, shot type, zone, x/y, goalie ID, event result | Event-State v3 reports outcome-specific coverage; independent box scores check team score/SOG | Only goal/SOG/missed/blocked coarse family | No shot-quality, shooter, goalie, location, save, or rebound model; shot type is absent for all blocked-shot rows |
| PBP faceoff winner/loser, zone/location, next event | Faceoff outcomes and sequence are available; 2021 5v5 follow-up proxy above | Faceoff token family and owner only | No puck location or possession side carried into subsequent hazard/mark model |
| PBP stoppage reason and following faceoff | Recorded stoppage and restart records are available | `stoppage` token only | No rule-driven restart transition; unrecorded whistles and geometric adjudication are unavailable |
| Independent box scores | 4,876 manifest rows; audited scores and team SOG were cross-checked by the frozen v0.1 loader | Eligibility/reconciliation support, not model targets beyond event tokens | Boxscore totals do not reveal unrecorded event opportunities or puck sequence |
| Legendary Picks NHL DB | Prior read-only audit of `picks.dev.db`: 1,833 NHL `player_stats` rows and 54,727 `player_game_logs` rows are from 2025–26/2026–27; 2,812 team result/stat rows are from those seasons; 816 roster snapshots are 2027 | Not used to fit 2019/20 or 2021 | DB is not the historical behavior source. The needed old behavior exists in the verified GameCenter/shift archive, but historical as-of roster/deployment snapshots are not represented by these DB seasons. |

The database inventory comes from the committed Event-State v3 read-only audit, not a new broad DB scan. That report used SQLite `mode=ro` and `query_only=ON`. No database writes or new broad row-count queries were performed for this audit.

## Mechanism-level gap ledger

| Mechanism | Observed discrepancy | Root-cause evidence and classification | Data coverage / missing information | Proposed correction to investigate (not implemented) | Acceptance test / falsification |
|---|---|---|---|---|---|
| A1 interarrival gaps | A1 gap NLL +21,776.81 vs A0; p95 230s vs 43s; per-20m count 18.24 vs 80.04 | **Measured model-estimation/smoothing defect candidate.** `RenewalModel.gap_probability/sample_gap` puts alpha 0.5 on 1,200 values; at n=100, 85.7% prior mass. Context partition and prior are entangled; no causal ablation yet. Not a clock-unit bug. | Whole-second observed transition gaps; 57,645.7 eligible 2021 minutes. No subsecond timing. | First report held-out gap calibration by selected context and gap bins, with training n, empirical support, prior share, censoring, and game-cluster intervals. Only then preregister a pooled-centered or hierarchical shrinkage comparison. | On identical game-periods, gap NLL and p50/p90/p95 improve without worsening count CRPS; false if tail/count mismatch persists in well-supported contexts or is explained by extraction/censoring instead. |
| Bundle arrival/count variance | A1 mean trace variance below observed for bundles, attempts, SOG and goals; A1 80% count coverage 0% | **Measured underdispersion**, consistent with too few arrivals. The variance loss is not independently decomposed from the gap mechanism. | Same 3,843 periods and ten draws; no persisted individual traces. | Decompose conditional count mean/variance and count calibration by game, period, state, and A1 selected-context depth. | The corrected mechanism must improve mean and variance/coverage jointly; matching only the mean fails. |
| Bundle/event-family composition | A0 faceoffs 4.54 vs 17.00; stoppages 20.45 vs 15.37. A1 is low for all listed families. | **Root cause unresolved.** Counts establish the discrepancy; no family-specific mark NLL or generated sequence trace is frozen. Do not blame family transition probabilities before that breakdown. | PBP family counts and ordered marks exist; 5v5 source transition destination counts: faceoff 48,717, stoppage 44,059, SOG 55,593, hit 52,746 (2021). | Score mark size, family, owner, and within-bundle prefix contributions separately; compare family count means and event time exposure on identical targets. | Improvement must reduce family-level CRPS and preserve joint bundle composition; falsified if gains are only aggregate total-count gains. |
| Faceoff winner → subsequent play | Model cannot represent winner-controlled next possession; historical 5v5 winner-team shot proxy is 35.7% within 30s before next faceoff. | **Missing state representation in code.** `Context` has only `possession_known: bool`; winner side is not carried. Statistical dependence is available to estimate, but continuous possession is latent. | Faceoff winner/loser/team, clock, zone, strength, and following shot events available; puck control and unrecorded passes absent. | Preserve possession side as an explicit observed-proxy/latent state and compare faceoff-conditioned next-event and shot-within-30s forecasts, with uncertainty and fallback. | Altering the faceoff winner must alter the modeled distribution of subsequent owner/shot events; on held-out games calibration should improve over parent. No claim of observed possession truth. |
| Goal and stoppage restarts | A1 may sample an arbitrary family after a goal/stoppage; no forced restart transition. | **Deterministic transition/rule gap.** Kernel updates score and sets possession unknown after goal, but does not force faceoff. Source example `2019020001` P1 00:25 contains goal→faceoff. | PBP `sortOrder`, goal, next faceoff, zone; explicit full restart sequences. Offside/icing geometry and unrecorded whistles remain unavailable. | Separate deterministic goal→whistle/restart state logic from empirical non-rule event choice; also audit stoppage→faceoff by reason and season. | Every simulated goal in the applicable scope must produce the correct restart before open-play events; source-backed sequences and illegal counterexamples; fail on silent correction. |
| Shot creation, SOG, goal conversion | A1 attempt→SOG marginal ratio close to observed, but absolute attempts/SOG/goals are 25%/25%/31% of observed; goal/SOG ratio is high (0.101 vs 0.0835). | **Main measured error is opportunity volume; smaller conversion concern remains.** The current tokens do not represent individual shot outcomes or shooter/goalie. Ratio comparison is aggregate, not conditional per-shot calibration. | PBP has attempts, outcomes, coordinates, shot type, shooter and goalie with outcome-dependent missingness; box scores independently provide goals/SOG. | After arrival/count diagnosis, score a conditional shot-event ledger: attempts→miss/block/SOG→goal; use only fields available before each outcome and retain missingness cohorts. | Team-period attempt/SOG/goal joint distribution improves, while arithmetic reconciliation and calibration by independently available features hold. Falsified if only goal totals improve by distorting attempts or SOG. |
| Team and player effects | A0/A1 treat team labels as home/away event owners; no player participates in generated marks. | **Model capability absent, not data absent for historical behavior.** Team/player IDs, shifts, and event participation are in the archive. A1's “interaction” label does not mean player interactions: it is a context-conditioned renewal model. | 4,876-game PBP/shift archive supports retrospective team/player rates. LP DB current NHL rows do not contain 2019/20 or 2021 logs/snapshots. Cross-game as-of lineup availability, line identity, and coaching decision are not fully observed. | First quantify training support by player/team and on-ice seconds; estimate only cutoff-safe, shrunk rates with source and lineup uncertainty. | Player/team-conditioned rates beat pooled equivalents on later chronological games while preserving eligibility and calibration; no in-sample target-game roster features. |
| Line deployment and fatigue | Generated sequence has no personnel state or substitutions. | **Model omitted; behavior partially inferable from shift intervals.** No line labels, bench intent, or physiological fatigue. | Shift player/team/period/start/end/duration and PBP roster spots; no verified line/pair identity or fatigue. | Reconstruct on-ice groups from overlaps as an explicitly inferred label, then measure shift duration/substitution distributions before modeling policy. | Reconcile all inferred on-ice intervals to source shift charts and report ambiguity; falsify any claimed line/fatigue model that uses unsupported labels. |
| Manpower transitions | A0/A1 are conditional fixed 5v5 only and cannot generate penalties or special teams. | **Scope exclusion**, not demonstrated cause of the 5v5 comparison failure. | Penalty and shift evidence exists in the archive, but state ambiguity and penalty service semantics require their own validated engine. | Keep out of 5v5 arrival diagnosis; add only after Gate 1 state ledger and special-team exposure are independently validated. | No 5v5 candidate may silently cross non-5v5 or ambiguous intervals; full game claims require separate rule-state acceptance. |
| Period-start state in count simulation | Every simulated period starts tied 0–0 with `faceoff`, known possession; actual later periods often start with nonzero score. | **Evaluation-input mismatch present in code; effect on A0/A1 delta unmeasured.** A1 conditions gaps on score/clock/context and could be more sensitive than pooled A0. | PBP score at period boundary is available; cache currently retains period transitions but not a separate start-state record. | Reconstruct cutoff-valid period-start score/context and report sensitivity with identical targets and seeds; do not use within-period future observations to initialize. | If supplying period-start state changes the A1−A0 count/CRPS ranking materially, qualify the original count comparison; if not, falsify this as a meaningful confound. |
| Sequence trace/provenance | No saved high-error examples or per-step probabilities in the frozen result. | **Evaluation instrumentation gap.** Aggregate score is reproducible in principle; no exact sequence divergence can be reviewed from saved outputs. | Cache is hash-pinned and retains identity-free transitions; model code can calculate categorical gap/mark probabilities. The target artifact stores only a replay-equality boolean. | Bounded, deterministic trace export: observed events, generated event, selected A1 context key, training support, categorical gap probabilities, sampled uniform, bundle-size/family/owner probabilities, state before/after, and source references. | At least ten preregistered representative/error-selected traces can be rerun byte-identically and independently joined to source windows; no trace may use target future state as input. |

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

1. **A1 gap calibration and support audit.** Decompose NLL and generated counts by gap bins, selected context, training support, score/time/previous-family state, and game. Report censored/entry gaps separately. Success: explain where the long tail and event-count deficit originate. Falsification: the A1 tail remains even in high-support contexts or comes from target/exposure mismatch rather than smoothing.
2. **Categorical mark/sequence scoring.** Split mark NLL into bundle size, family, owner, and within-bundle prefix; report family-specific observed/generated counts and transition matrices. Success: identify whether A0's faceoff/stoppage composition comes from extraction, mark size, or conditional family probability. Falsification: no family or sequence component explains its large family-level CRPS despite the aggregate fit.
3. **Faceoff winner dependence.** Fit/evaluate a training-only, source-backed winner-team follow-up event/shot proxy using next-faceoff censoring and 5v5/strength/zone strata. Hold out by game. Success: improved held-out calibration over the unconditional/strength parent and a candidate whose possession side can actually affect later event ownership. Falsification: no improvement or unstable strata after shrinkage. Do not call the label continuous possession.
4. **Deterministic restart audit.** Measure goal→faceoff, stoppage reason→next faceoff, and event ordering by season; test deterministic restart rules separately from fitted event probabilities. Success: all supported goal/restart transitions comply while empirical intervals remain plausible. Falsification: source ambiguity prevents a deterministic inference for a named transition; quarantine that case.
5. **Shot opportunity/conversion decomposition.** Use a consistent attempt denominator and source-availability cohorts. Separately score attempt rate, miss/block/SOG outcome, and goal given SOG; never use target-dependent missing shotType as a predictor. Success: locate whether goal error remains after event volume is calibrated. Falsification: per-shot conversion is near-calibrated and the entire goal loss follows opportunity count.
6. **Team/player/goalie/shift coverage audit.** Quantify historical support by on-ice seconds and pregame cutoff evidence; compare pooled, team, player, and goalie estimates only in chronological folds. Success: measurable stable improvement without oracle lineup/starter use. Falsification: coverage is too sparse or pregame availability cannot be reconstructed for the claimed use.
7. **Independent later-season evaluation.** Freeze specification and thresholds before accessing a genuinely later, eligible season. Success: gains persist with game-cluster uncertainty and all source/clock checks. Falsification: development improvements do not replicate.

## Decision

This audit explains the dominant measured A1 loss at the component level: arrival-gap likelihood and under-counting fail; average mark likelihood improves. It identifies a strong, directly inspectable smoothing/context mechanism, but does not claim a controlled causal effect size or produce the requested ten generated high-error traces. It also shows that A0's total count match hides a substantial event-family error and that current model inputs omit several behaviors already measurable from the archive.

The existing `A0_SIMPLER_REFERENCE_OR_NEITHER` decision remains unchanged. No model is promoted, no rule/data gate is changed, and no production forecast is touched. A follow-up bounded trace audit should precede any parameter change or new event-generation candidate.
