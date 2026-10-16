# Research note: DraftKings sports simulation and tennis projections

- **Reviewed:** 2026-10-16
- **Scope:** Architecture reference for tennis match and player-stat simulation. This note is not a model-performance result.

## Main takeaway

A match simulator can be useful even when its standalone match-winner probability loses to Elo. The tennis backtest
rejected the point-model simulator as a winner forecaster on the evaluated sample; it did not evaluate its service-point,
ace, double-fault, break or total-game distributions against their own baselines. Those are separate targets and need
separate validation.

On the ATP 2023–2026 sample of 11,777 complete-score, best-of-three matches, winner log loss was 0.64896 for Elo and
0.66277 for the point simulator (Brier 0.22802 versus 0.23530). These scores assess match-winner probabilities only;
they do not grade player-count or match-length distributions. See the [frozen backtest](TENNIS-MATCH-BACKTEST-2026-10-14.md).

The product objective is a distribution over match trajectories. The winner is one output from those trajectories,
alongside set scores, games, tiebreaks and player statistics. Simulating the shared trajectory can preserve relationships
between those outputs, but it only earns that role if its distributions beat simpler direct baselines.

## DraftKings references

[Building a Tennis Simulation](https://medium.com/draftkings-engineering/building-a-tennis-simulation-d6afdaa97d19) was
published by DraftKings Engineering on August 17, 2023. Its tutorial samples point outcomes, updates point/game/set/match
state and simulation records, and aggregates records across many Monte Carlo matches into probabilities for match
winner, correct score, total games and other markets. It also discusses format-specific scoring and updating serve
estimates as match evidence arrives. The article says its production system is more advanced than the tutorial.

[Modeling Football: Combining ML Models and Monte Carlo Simulations](https://medium.com/draftkings-engineering/modeling-football-combining-ml-models-and-monte-carlo-simulations-170fd58cbe11)
followed on February 7, 2024. It describes a play-by-play simulation with state updates, simulation records and machine
learning decision points, including how event outcomes create correlated markets.

The tennis article is a useful architecture reference for trajectory simulation and related market probabilities. It is
not evidence that our current simulator predicts player props accurately, nor does its public tutorial establish that
it models ace and double-fault events. Our player-projection engine still needs event labels, direct baselines and
held-out distributional validation.

## What the existing match data supports

The current research inventory identifies these match-level fields for both players: service points, first serves in,
first-serve points won, second-serve points won, aces, double faults, service games, break points saved and break points
faced. They support direct count baselines and several exposure rates without tracking hardware or computer vision.
Definitions, missingness and coverage still need to be audited before each field is adopted.

| Target | Available foundation | Important limit |
|---|---|---|
| Service-point volume | Match scores, format and serve-point totals | The simulator's volume distribution must be compared with a direct historical baseline. |
| Aces | Aggregate ace and service-point counts | The source does not label whether each ace came on a first or second serve. Do not invent those event labels. |
| Double faults | Aggregate double-fault counts and serve-point / first-serve fields | Validate the second-serve exposure definition and the count distribution by tour and surface. |
| Breaks of serve | Break-point faced/saved counts, serve/return rates and match score | Distinguish breaks converted from break points won; validate derived counts against source definitions. |
| Games and set outcomes | Match scores and a scoring simulator | Keep distributions and evaluate total games, spreads, set scores and tiebreaks separately from match-winner accuracy. |
| Winners and unforced errors | Not present in the current match-level counts | Requires licensed or otherwise approved shot-charting data. |

The current source can support ace and double-fault research without shot tracking. Shot-level winners, unforced errors,
and forehand/backhand classifications are a separate future data requirement.

## Research sequence

Keep the match-winner and player-projection tracks separate. The current tennis brief's gates remain the release
criteria; this note clarifies why the simulator's player-stat outputs deserve their own experiments.

1. Finish the data and licensing audit, including field definitions, tour/year/surface/format coverage and pre-forecast
   availability.
2. Establish direct P0/P1 ace and double-fault count baselines and validate their full distributions.
3. Validate simulated service-point volume against the service-point exposure baseline. Validate total-game, set-score
   and tiebreak distributions against direct historical baselines in parallel; do not infer their quality from winner
   Brier or log loss.
4. Extend simulation records to ace, double-fault and break events only to the level supported by historical labels.
   Compare those simulated distributions against the strongest direct baselines using predeclared proper scores,
   calibration and interval coverage.
5. Measure between-match variation before adding shared match-level effects. A fixed point probability at every point
   may make count distributions too narrow; any random effect or within-match update must be fitted from historical data
   and tested on held-out matches.
6. Test Elo-informed pooling for thin-history players only as an incremental feature. The goal is to improve player
   count distributions without degrading them, not to make the simulator the winner source by default.
7. Evaluate historical sportsbook lines only after probability calibration and data licensing are established.
   Preserve line, side, odds, timestamp and settlement rules; prices are an evaluation benchmark, not an initial feature.

This sequence is consistent with the existing Track B gates: direct baselines first, then the service-point exposure
gate, then event-level simulation, then joint distributions. Track A continues to use Elo as the match-winner reference
and validates the simulator's set/game/tiebreak outputs separately.

## Public implementation reference

[DanielTomaro13/Tennis-Modelling](https://github.com/DanielTomaro13/Tennis-Modelling) is a verified public repository
describing surface-adjusted serve/return profiles, Elo, point-to-match simulation, and projections for totals,
handicaps, breaks, aces and double faults. It is useful to inspect as an implementation reference, not as independent
evidence of accuracy. Its README reports that scheduled refreshes and deploys were paused as of September 2026. Review
its data and code licenses independently before reuse; it does not change the existing commercial-licensing gate for
our own source data.

The 55.4% win rate and 9.6% ROI across 296 selections mentioned in the source thread are self-reported results, not
independent evidence of a durable betting edge.

## Sources and related work

- [DraftKings, Building a Tennis Simulation (2023-08-17)](https://medium.com/draftkings-engineering/building-a-tennis-simulation-d6afdaa97d19)
- [DraftKings, Modeling Football: Combining ML Models and Monte Carlo Simulations (2024-02-07)](https://medium.com/draftkings-engineering/modeling-football-combining-ml-models-and-monte-carlo-simulations-170fd58cbe11)
- [DanielTomaro13/Tennis-Modelling](https://github.com/DanielTomaro13/Tennis-Modelling)
- [Tennis prediction brief](BRIEF-tennis-prediction-model.md)
- [Tennis player-projection research plan](RESEARCH-tennis-player-projections-2026-10-14.md)
- [Tennis match backtest results](TENNIS-MATCH-BACKTEST-2026-10-14.md)
- [Tennis match simulator research](TENNIS-MATCH-SIM-2026-10-14.md)
