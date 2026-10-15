# Tennis model card

**Scope:** Daily ATP and WTA match projections. Each forecast target carries its own method version in `modelVersions`; the legacy `modelVersion` field remains for response compatibility.

## Forecast targets and methods

| Target | Current method version | Output |
|---|---|---|
| Winner | `global-surface-elo-blend-v1` | Home-win probability and selected winner |
| Aces | ATP `p1-history-exposure-nb-v1`; WTA `p0-match-rate-nb-v1` | Expected count and full negative-binomial predictive distribution for each player |
| Double faults | ATP `p1-history-exposure-nb-v1`; WTA `p0-match-rate-nb-v1` | Expected count and full negative-binomial predictive distribution for each player |
| Total games | `serve-return-sim-unknown-server-v2` | Expected count, central interval, and full score-simulator distribution |

Winner probabilities blend global and surface Elo in logit space. Historical updates use matches dated before the forecast day, so same-day matches do not update one another. `probability` is the selected winner's probability; `homeWinProbability` is the consistently oriented probability used for Brier grading.

The ATP ace and double-fault candidate uses historical event counts, service-point exposure, player shrinkage, and an NB2 distribution. It is an approximate history-exposure implementation, not the researched E2/X-bbin specification. WTA retains the P0 match-rate estimate with an NB2 predictive distribution. These methods are research candidates and have not been validated prospectively. The method version names distinguish them but do not imply a positive evaluation.

Total-games simulation is made available only for events whose surface and format are explicitly mapped in `backend/tennis_daily_projections.py`: Shanghai, Wuhan, and the four Grand Slams. Grand Slam ATP singles use best-of-five; WTA uses best-of-three. Unknown event rules leave this target unavailable. The simulator averages over both possible first servers.

## Locked forecast grading

`backend/tennis_forecast_ledger.py` stores immutable prospective forecast locks by league, game, target, and method version. It grades winner probabilities with Brier and log loss, and count distributions with negative log score, discrete CRPS, expected-count absolute error, and total-games mean absolute error. A target is graded only when its actual outcome exists. Aces require verified match-stat overrides; double faults require verified double-fault overrides. Missing outcomes remain ungraded rather than being treated as zero.

The existing legacy grader continues to populate its original correctness and total-games fields. The versioned ledger is an additional prospective record and does not backfill forecasts that were made before a target version was locked.

## Validation status and limits

The total-games simulator has not yet established an advantage over a direct historical count baseline. Its proper-score comparison on ATP and WTA must be completed before treating the simulator as a preferred model. The count-model candidates also need prospective monitoring. No unified trajectory model is promoted by this implementation.

The underlying Sackmann-derived data has unresolved licensing restrictions documented in `docs/TENNIS-DATA-2026-10-13.md`. These changes support internal evaluation only until rights for the data and derived forecasts are cleared.

## References

- `backend/tennis_daily_projections.py` — live projection methods, version identifiers, and event rules.
- `backend/tennis_forecast_ledger.py` — versioned locks and proper-score grading.
- `backend/grade_tennis_model.py` — scheduled/CLI grading integration.
- `backend/tennis_total_games_backtest.py` — walk-forward comparison against the historical count baseline.
- `docs/TENNIS-MATCH-BACKTEST-2026-10-14.md` — separate winner-method research; it is not live-model performance evidence.
