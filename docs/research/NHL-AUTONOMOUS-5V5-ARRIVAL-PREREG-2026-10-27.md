# NHL Autonomous 5v5 Event-Arrival Experiment Preregistration

- **Date:** 2026-10-27
- **Branch:** `research/nhl-autonomous-5v5-2026-10-27`
- **Base:** `da2475f1ea70648a1aeba805006776028368e8d5`
- **Scope:** A research-only, fixed-strength 5v5 event-arrival kernel. It replaces donor clock slots for the kernel experiment; it does not replace the current v0.2b simulator.
- **Status:** Frozen before fitting the new arrival model or scoring it on 2021.

## Why this code and data are needed

The existing v0.2b B2 model samples event families at donor event slots. Its emitted provenance explicitly retains donor event count and clock slots, so it cannot test whether an independent model can generate event-arrival times. A separate, isolated research kernel is necessary to test that missing component without changing the frozen B2 baseline.

The required labels are already published in the verified NHL GameCenter PBP archive: event type, `timeInPeriod`, `sortOrder`, `situationCode`, team owner, and event details. We will copy those source fields and fit an empirical arrival process; we will not acquire another ordinary event feed or query Legendary Picks databases for historical labels. PBP clocks are whole-second values. `sortOrder` supplies within-second record order, not subsecond time.

## Frozen population and eligibility

| Role | Population | Use |
|---|---|---|
| Training | Eligible 2019 and 2020 start seasons: 1,921 games | Fit all arrival and event-mark distributions |
| Development | Eligible 2021 start season: 1,292 games | One development comparison and model selection only |
| Quarantined | 2018 start season | Excluded until the chronology/source repair is complete |
| Exposed | 2022 start season | Excluded from tuning and treated only as historical evidence |

Use the frozen v0.1 loader and its hash-verified PBP, independent box-score, and eligibility decisions. Use the corrected event-state attribution from `NHL-BEHAVIOR-EVIDENCE-EVENT-STATE-V3-2026-10-27.md`; do not refit those attribution rules on 2021. Ambiguous event-state labels and intervals crossing a manpower boundary are excluded from 5v5 fitting and reported by reason.

## Experiment question

Can a training-only, donor-independent distribution of event arrival gaps and event bundles produce better calibrated 5v5 event timelines on 2021 development games than a pooled renewal baseline, while preserving count calibration and the existing B2 donor-slot trace as a descriptive reference?

This experiment tests the event-arrival component only. Its generated 20-minute segment is explicitly **conditional on remaining 5v5 for the full segment**. Penalties, special teams, goalie pulls, substitutions, overtime, shootouts, players, player attribution, team tactics, rink geometry, and puck physics are out of scope. It is not a complete NHL period or a valid full game.

## Frozen candidate definitions

### D0 — B2 donor-slot reference

Retain the current v0.2b/B2 donor event-count and clock-slot behavior as a reference. Do not alter B2. Report only on the same eligible 2021 games/periods for which the event-level donor-slot output can be reproduced; missing event-level baseline artifacts are `NOT_AVAILABLE`, never reconstructed from summary metrics.

### A0 — pooled autonomous renewal baseline

Fit from eligible 2019/20 PBP only. Treat all ordered PBP records at one verified clock second as one event bundle, retaining bundle size and `sortOrder` order. Sample positive whole-second gaps between eligible 5v5 bundles from one pooled distribution, then sample an eligible event bundle from one pooled mark distribution. Do not sample an entire period, shift sequence, target-game timeline, or future event sequence.

### A1 — state-conditioned autonomous renewal model

Use the same training rows and output schema as A0. Condition the inter-bundle gap and event-bundle mark distributions on the pre-arrival event family, PBP possession proxy known/unknown, current score state, and five-minute period-clock bucket. These are all computed from generated history at the prediction point. PBP possession is a latent proxy derived from recorded faceoffs/turnovers, not a continuous observed puck-possession label.

Use this frozen fallback hierarchy: exact context → previous-family plus possession-known state → previous family → pooled A0. A conditional level is eligible only with at least 100 training bundles; otherwise fall back. No 2021 observations may change bins, thresholds, or fallback rules.

Eligible event marks exclude penalties and any bundle whose source-reconciled state is not 5v5 throughout. This keeps the experiment at fixed strength rather than silently applying 5v5 rates to a power play. Goals, shots on goal, missed shots, blocked shots, faceoffs, stoppages, hits, giveaways, and takeaways remain source-defined event marks where their state labels are eligible. Generated traces preserve the source-family distinctions and count a goal as one SOG.

## Evaluation protocol

- Score A0 and A1 on the same 2021 eligible game-period population. Keep 2021 wholly out of fitting.
- Generate ten 20-minute fixed-strength traces per eligible game-period and candidate. Use deterministic seeds keyed by game ID, period, replicate, and model version. Pair A0/A1 replicates with common uniforms for interval and bundle draws.
- Report per-game clustered results, with 2,000 paired bootstrap replicates and the fixed seed recorded in the output manifest.
- Primary score: mean held-out negative log predictive density of the ordered event-bundle sequence, reported per eligible at-risk 5v5 minute. For D0, report `NOT_AVAILABLE` for this score unless its exact event-level clock probabilities can be recovered; do not fabricate a likelihood for fixed donor slots.
- Secondary measures: CRPS and calibration for bundle counts, event-family counts, shot-attempt/SOG/goal counts per 5v5 exposure, inter-bundle gap distribution (including median and upper quantiles), count variance, percentage of development exposure quarantined for state ambiguity, and runtime.
- Report deterministic accounting checks: nondecreasing period clocks, all events within 0–1200 seconds, ordered same-second bundles, goals reconciled to SOG, and byte-identical output for fixed input/version/seed.

## Frozen development decision rule

A1 merits continued research only if it improves the primary held-out log score over A0 with a paired game-cluster 95% interval wholly in A1's favor and its event-count CRPS is not worse than A0. Otherwise retain A0 as the simpler research reference or retain neither if both are miscalibrated. This is a 2021 development decision only; it does not authorize adoption, production integration, a full-game-validity claim, or an NHL prediction-skill claim. A later unseen season or prospective population is required for any adoption claim.

## Reproducibility and boundaries

- Preserve the `da2475f1` queued-penalty implementation and all frozen B2 artifacts unchanged.
- Keep raw tracking/PBP data outside Git. Commit scripts, compact provenance manifests, tests, and reports only.
- Keep all output in a new `research/nhl/autonomous-5v5/` namespace. Do not alter production forecasts or databases, the B2 generator, Gridiron Physics, or Gate 1 thresholds.
- No pushes are authorized by this preregistration.
