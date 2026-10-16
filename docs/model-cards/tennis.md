# Tennis model card

**Scope:** Daily ATP and WTA match projections. Each forecast target carries its own method version in `modelVersions`; the legacy `modelVersion` field remains for response compatibility.

## Forecast targets and methods

| Target | Current method version | Output |
|---|---|---|
| Winner, incumbent | `global-surface-elo-blend-v1` | Home-win probability and selected winner |
| Winner, challenger | `serve-return-point-simulator-v1` | Independent home-win probability from serve/return rates and exact match simulation |
| Aces | ATP `p1-history-exposure-nb-v1`; WTA `p0-match-rate-nb-v1` | Expected count and full negative-binomial predictive distribution for each player |
| Double faults | ATP `p1-history-exposure-nb-v1`; WTA `p0-match-rate-nb-v1` | Expected count and full negative-binomial predictive distribution for each player |
| Total games | `historical-format-surface-empirical-v1` | Expected count, central interval, and smoothed empirical distribution |

The screen displays both winner probabilities independently. The incumbent blends global and surface Elo in logit space. The challenger converts pre-match serve/return estimates into point probabilities and integrates tournament rules with the exact match simulator, averaging over either first server. Historical updates use matches dated before the forecast day, so same-day matches do not update one another. Both probabilities are locked and graded separately under the `winner` target, keyed by method version; `probability` remains the incumbent's selected-winner probability for compatibility.

### What the winner Brier score measures

For every locked match, the Brier contribution is `(p_home − y_home)²`, where `p_home` is that model's probability that the listed home player wins, and `y_home` is 1 for a home-player win and 0 for an away-player win. The model is built to forecast the match winner as a probability; the reported Brier is the average contribution across eligible completed matches. It scores confidence as well as which player won, so a correct pick alone is not a sufficient grade. For this binary target the score ranges from 0 to 1: zero is perfect, lower is better, and a 50/50 forecast always scores 0.25. It is not a score for aces, total games, betting profit, or merely the share of picks that were correct.

Each method's locked probability is scored separately on the same eligible completed matches. The incumbent's home-oriented value is `homeWinProbability`; the challenger uses `homeWinProbabilityPointSim`. The product also reports the historical walk-forward Brier benchmark below. Those archived figures compare a point-model simulator against a standard Elo comparator; they are research evidence, not prospective grades for the live global/surface Elo blend.

No prospective Brier score has yet been recorded for either current live method version. Once there are locked, completed matches, the live comparison will report each method's Brier on the same matches, alongside the 0.25 reference and the paired difference between methods.

| Historical walk-forward winner benchmark, best-of-three 2023–2026 | ATP (n=11,777) | WTA (n=13,066) |
|---|---:|---:|
| 50/50 reference | 0.25000 | 0.25000 |
| Standard Elo comparator | 0.22802 | 0.21596 |
| Serve/return point-model simulator | 0.23530 | 0.22884 |

The point-model simulator is for prospective monitoring, not a promoted replacement. It scores worse than standard Elo on both tours in this backtest. The [frozen match backtest](../TENNIS-MATCH-BACKTEST-2026-10-14.md) reports the log-loss comparison, calibration and limitations. Prospective scores will be accumulated from locked forecasts by tour and method version; they will not be mixed with this historical benchmark.

The ATP ace and double-fault candidate uses historical event counts, service-point exposure, player shrinkage, and an NB2 distribution. It is an approximate history-exposure implementation, not the researched E2/X-bbin specification. WTA retains the P0 match-rate estimate with an NB2 predictive distribution. These methods are research candidates and have not been validated prospectively. The method version names distinguish them but do not imply a positive evaluation.

Total-games projections use complete historical match counts grouped by best-of and surface, with a tour-format fallback when a surface group has fewer than 100 observations. The distribution is smoothed over 0 to 120 games. It is made available only for events whose surface and format are explicitly mapped in `backend/tennis_daily_projections.py`: Shanghai, Wuhan, and the four Grand Slams. Grand Slam ATP singles use best-of-five; WTA uses best-of-three. Unknown event rules leave this target unavailable.

## Locked forecast grading

`backend/tennis_forecast_ledger.py` stores immutable prospective forecast locks by league, game, target, and method version. It grades winner probabilities with Brier and log loss, and count distributions with negative log score, discrete CRPS, expected-count absolute error, and total-games mean absolute error. A target is graded only when its actual outcome exists. Aces require verified match-stat overrides; double faults require verified double-fault overrides. Missing outcomes remain ungraded rather than being treated as zero.

The existing legacy grader continues to populate its original correctness and total-games fields. The versioned ledger is an additional prospective record and does not backfill forecasts that were made before a target version was locked.

## Validation status and limits

The exact point-model simulator was compared walk-forward with the direct historical format-and-surface distribution on 2023 through the latest stored date, 2026-05-25. The simulator lost on both negative log score and discrete CRPS for ATP (n=13,551) and WTA (n=13,066); paired 95% intervals for simulator-minus-baseline loss were entirely positive. It also overpredicted mean total games by 2.22 on ATP and 2.42 on WTA, and undercovered nominal central intervals. The live total-games output therefore uses the historical baseline; the simulator remains a research challenger. Results and protocol are in [the total-games backtest report](../TENNIS-TOTAL-GAMES-BACKTEST-2026-10-15.md). The ace and double-fault candidates still need prospective monitoring. No unified trajectory model is promoted by this implementation.

The underlying Sackmann-derived data has unresolved licensing restrictions documented in `docs/TENNIS-DATA-2026-10-13.md`. These changes support internal evaluation only until rights for the data and derived forecasts are cleared.

## References

- `backend/tennis_daily_projections.py` — live projection methods, version identifiers, and event rules.
- `backend/tennis_forecast_ledger.py` — versioned locks and proper-score grading.
- `backend/grade_tennis_model.py` — scheduled/CLI grading integration.
- `backend/tennis_total_games_backtest.py` — walk-forward comparison against the historical count baseline.
- `docs/TENNIS-MATCH-BACKTEST-2026-10-14.md` — separate winner-method research; it is not live-model performance evidence.
