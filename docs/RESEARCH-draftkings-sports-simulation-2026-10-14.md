# Research note: DraftKings sports simulation and tennis projections

- **Reviewed:** 2026-10-16
- **Scope:** Architecture reference for tennis match and player-stat simulation. This note is not a model-performance result.

## Main takeaway

A match simulator can be useful even when its standalone match-winner probability loses to Elo, but each distribution
must win its own validation. The tennis backtest rejected the point-model simulator as a winner forecaster and, in a
separate Oct. 16 evaluation, found that it loses to direct historical distributions for total games on ATP and WTA.
Service-point exposure, aces, double faults and breaks still require their own target-specific comparisons.

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
| Games and set outcomes | Match scores and a scoring simulator | The total-games backtest favors direct historical distributions over the current simulator. Spreads, set scores and tiebreaks still need their own validation, separate from match-winner accuracy. |
| Winners and unforced errors | Not present in the current match-level counts | Requires otherwise approved shot-charting data. |

The current source can support ace and double-fault research without shot tracking. Shot-level winners, unforced errors,
and forehand/backhand classifications are a separate future data requirement.

## Research sequence

Keep the match-winner and player-projection tracks separate. Historical walk-forward research and prospective grading
run at the same time.

1. Finish the data audit, including field definitions, tour/year/surface/format coverage, completion rules
   and pre-forecast availability. The local development snapshot is audited in
   [TENNIS-PROPS-DATA-AUDIT-2026-10-14.md](TENNIS-PROPS-DATA-AUDIT-2026-10-14.md).
2. Gate A: test expected service-point volume from the exact scoring model against a rolling player/surface exposure mean
   and the tour/surface mean. The expected-volume screen is complete on both tours: ATP (35,099 matches), simulator MAE
   19.227 vs 17.711 for rolling-player and 17.655 for tour/surface; WTA (38,635), 20.250 vs 18.036 and 17.957.
   Mean overprediction is 7.292 points per ATP player and 9.226 per WTA player. The simulator loses every test year on
   both tours. Full-distribution CRPS also favors the direct empirical baseline: ATP 12.214 vs simulator 12.842/12.814
   across two seeds; WTA 12.422 vs 13.503/13.505. Simulated 50/80/90% intervals under-cover on both tours, and the
   comparison is seed-stable. Reject the current simulator for service-point exposure on the evaluated completed
   best-of-three population; format/history-depth review remains before extending that decision. Results and
   year/surface breakdowns are in
   [TENNIS-PROPS-BASELINES-2026-10-14.md](TENNIS-PROPS-BASELINES-2026-10-14.md).
3. Gate B: keep the two direct-count experiment families separate. The earlier E2-based P1 negative binomial beat P0 on
   ATP aces and double faults, while WTA P0 beat P1 on both targets. The corrected E2-integrated beta-binomial improved
   the ATP results; on WTA it did not beat P0 for aces and was inconclusive for double faults. A different direct-
   historical-exposure P1 Gamma-Poisson replay leads its expanded 2015–2026 development sample in all four cells, but
   does not reverse the earlier result because model definitions and evaluation windows differ. The full summaries are
   in `research/tennis/props/2026-10-14/` and `docs/TENNIS-PROPS-BASELINES-2026-10-14.md`.
4. Total-games validation is complete for 11,766 ATP and 13,062 WTA BO3 matches from 2023 through the available part of
   2026. Direct distributions beat the current simulator on CRPS, with the detailed format/surface/competitiveness
   baseline scoring 3.359 vs 3.533 for ATP and 3.231 vs 3.557 for WTA. The direct format-only baseline has the best log
   score. The simulator overpredicts total games by 1.89 and 2.42 on average, and its CRPS loss appears across year,
   surface, competitiveness and serve-history-depth segments. Keep it out of the total-games incumbent role on this
   evaluated population; these are development results, not prospective confirmation. Details:
   [TENNIS-TOTAL-GAMES-BACKTEST-2026-10-16.md](TENNIS-TOTAL-GAMES-BACKTEST-2026-10-16.md).
5. Finish prospective grading with frozen, timestamped per-target distributions and immutable model versions. Grade only
   outcomes supported by reliable result data.
6. Diagnose the cause of the simulator's total-games overprediction using the completed segment analysis. Keep the
   current simulator in Model Lab while this work proceeds.
7. Test event-labeled or richer simulation only after a predeclared comparison against the direct baselines. Estimate
   between-match variation from history; do not add it because a fixed-probability simulation merely looks too narrow.
8. Test Elo-informed pooling for thin-history players only as an incremental feature, and evaluate sportsbook lines only
   after calibration is established.
   Preserve line, side, odds, timestamp and settlement rules; prices are an evaluation benchmark, not an initial feature.

The 2023-2026 winner results already inspected are development evidence for that target. Player-count outcomes are
separate targets and may be studied, but their periods are called untouched only after prior-use auditing. Track A
continues to use Elo as the match-winner reference and validates the simulator's set/game/tiebreak outputs separately.

The current local development grading stream has 12 forecast locks since Oct 14 (first lock Oct 15), 11 grades, and one
version. It does not save input snapshots or full probability distributions, uses one lock per match, and grades winner
correctness and total-games error without Brier/log loss or ace/DF count scores. Prospective reporting and challenger-version
separation remain implementation gaps; these counts are not production status.

## Public implementation reference

[DanielTomaro13/Tennis-Modelling](https://github.com/DanielTomaro13/Tennis-Modelling) is a verified public repository
describing surface-adjusted serve/return profiles, Elo, point-to-match simulation, and projections for totals,
handicaps, breaks, aces and double faults. It is useful to inspect as an implementation reference, not as independent
evidence of accuracy. Its README reports that scheduled refreshes and deploys were paused as of September 2026. Review
its data and code provenance independently before reuse.

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
