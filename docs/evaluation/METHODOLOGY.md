# Model evaluation methodology

[Evaluation home](README.md) · [Benchmarks](BENCHMARKS.md)

Before work: state objective, minimal control, expected mechanism, falsifiable acceptance criterion, train/tune/test cutoffs, cohort, scoring metric, uncertainty, cost budget and stop condition. Record all inspected prior experiments; avoid new complexity without improvement.

| Question | Evidence |
|---|---|
| Runtime integrity | Pinned replay, exact source/input identity, complete seed census, valid legal games, blocked reasons, no leakage |
| Realism | Same definitions/denominators versus NFL or relevant sport: plays, drives, scores, events, opportunity, player/team distributions |
| Prediction | Chronological held-out or prospective locks; Brier/log loss, score MAE, distribution calibration and proper distribution scores |
| Incremental signal | Paired market-only versus market-plus-model on the same time-eligible records, uncertainty excluding no improvement |
| Release | Explicit adoption decision, source/config/artifact identity and operations/coverage gates |

For binary outcomes Brier = mean((p-y)^2); log loss = mean(-y log p -(1-y) log(1-p)). For empirical distributions assess interval coverage and CRPS (mean absolute sample-to-observation distance minus half the mean pairwise sample distance). For point predictions use MAE. Match event definitions, quote timestamps, pushes/ties and cohort eligibility. Bootstrap the relevant independent game/date or player-game cluster; do not treat multiple prop lines or Monte Carlo seeds as independent realized games. Account for finite-simulation noise in estimated expected points. Use common RNG streams only when truly matched; seed labels alone do not prove pairing.

For storage and reproducible evidence, see the [proposed simulation artifact retention policy](../specifications/SIMULATION-ARTIFACT-RETENTION.md). Full-population metrics and compact seed facts must not be replaced by a retained replay sample.

Separately label component, full-game and live operational evidence. Freeze prospective forecasts before kickoff/tipoff. Report failed/invalid seeds instead of selecting only completed outcomes. Preserve earlier gates and failed results. See [original forecasting north star](../STRATEGY-forecasting-north-star-2026-10-10.md), [player projections methodology](../PROJECTIONS-METHODOLOGY.md) and [CEG findings](https://github.com/micahp/legendarypicks/blob/8d86d430/docs/research/slc-ceg-2026-11-24/FINDINGS-FOR-V2-AND-V1-COMPLETE.md).
