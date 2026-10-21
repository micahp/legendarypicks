# NHL V3 Phase 2B unseen evaluation protocol

## Current data status

The hash-pinned Phase 1 NHL frame available for this run contains 4,876 regular-season games from start seasons 2018–2022; 2022 ends on November 27. The local `research/nhl/prospective-2026-27` archive has forecasts and score distributions, but no settled game outcomes. It cannot serve as a scored evaluation yet.

## Holdout rule

Use the first later complete regular season with accepted official scores, accepted team SOG targets, and reconciled event evidence. Keep the entire season sealed until the candidate definition and fitted artifact are frozen. Do not select between A, B, C, D, or their settings using the new season.

The Phase 2B candidate settings are fixed as follows:

- A: the 0.5 shrinkage factor for the training-only population conversion intercept.
- B rolling: ten prior team games, ten league-prior games, and the defined goal-for / opponent-goals-allowed log offset.
- B v2: attack(team) minus defense(opponent) from the 2018–2020 same-window v2 fit; no second-stage model.
- C: log of the same-window v2 expected team goals divided by Phase 2A's pregame simulated expected goals; generated shot outcomes remain the only source of goals.
- D: training-only location/type reservoirs with the committed 150/200 support floors, keyed by generated period, score state, time bucket, strength, and pregame attack category, with the specified fallback pools.

## Evaluation steps

1. Acquire and pin the later season's official score and team SOG targets, event feed bodies, dispositions, and stable game/team identity joins. Reconcile every accepted score/SOG count to the publisher. Fail closed on missing games, target disagreements, or identity misses.
2. Fit all model parameters using only information available before each evaluation game. Team histories update forward-only; same-date historical games do not update one another without published puck-drop timestamps.
3. Save and hash the frozen Phase 2A reference, every Phase 2B candidate, the same-window v2 refit, fit inputs, and candidate settings before scoring any holdout outcome.
4. Run identical eligible game IDs with common random seeds and full event accounting for Phase 2A, simple historical-rate, A, B rolling, B v2, C, D, and v2 score-only. Report all exclusions by component.
5. Report paired game-bootstrap intervals for goal CRPS, final-score energy, winner Brier, and team SOG CRPS; also report count means/variances/50–90% coverage, event-level SOG and goal calibration, shot-quality composition, OT/shootout and strength splits, and runtime.

## Adoption gate

Adoption requires a later untouched evaluation with paired 95% intervals showing improvement over both matched Phase 2A and same-window v2 on team-goal CRPS and final-score energy. Winner Brier must not show a supported deterioration. Team SOG CRPS must remain competitive with the Phase 2A advantage, and all component reconciliation and simulation invariants must pass. If any condition fails or the intervals span zero, keep Phase 2A as the research prototype and retain the new model only as a research candidate.

Do not use the already exposed 2022 holdout to choose a candidate or tune any setting. Its existing measurements remain historical diagnostic evidence.
