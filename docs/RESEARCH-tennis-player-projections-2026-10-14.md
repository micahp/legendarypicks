# RESEARCH: Tennis player-projection engine

**Date:** 2026-10-14  
**Status:** Research plan, not a validated model  
**Repository:** `micahp/legendarypicks`, branch `docs/tennis-prediction-brief`  
**Related:** [Tennis match prediction brief](BRIEF-tennis-prediction-model.md)

## Decision

**GO on player-projection research; NO-GO on the current simulator as a standalone match-winner forecaster.**

The goal is not to recover the match-winner result by asserting that a coherent simulator must be more accurate. The immediate question is whether simulating service-point **opportunities** and outcomes produces better **player-statistic count distributions** than simpler methods.

The 2023–2026 match-winner window has been inspected and is a development set, **not** untouched confirmation:

| Tour | Matches | Elo Brier | Point-model simulator Brier | Elo log loss | Simulator log loss |
|---|---:|---:|---:|---:|---:|
| ATP | 11,777 | 0.2280 | 0.2353 | 0.6490 | 0.6628 |
| WTA | 13,066 | 0.2160 | 0.2288 | 0.6210 | 0.6486 |

Those numbers are not prop forecasts. The existing simulator passed 48 arithmetic/Monte Carlo comparison cases, but its total-games, tiebreak, service-volume, and player-statistic forecasts **have not passed historical predictive validation**. Keep the two conclusions separate.

## Product question

For player A facing B, on this surface and in this scoring format:

1. How many service points will A likely play?
2. What is A's **full count distribution** for aces and double faults, rather than only a projected mean?
3. For any published threshold (e.g., aces over 7.5), what fraction of simulated matches exceed it?
4. Does full-match simulation improve those distributions over direct statistical forecasts, on the *same* matches?

For a player's total aces, the exposure and rate are distinct:
`E[aces] = E[service points × ace rate]`, **not necessarily** `E[service points] × E[ace rate]` when those quantities covary.

## Available data and explicit gaps

Historical ATP and WTA match files have, where reported, `svpt` (service points), `ace`, `df` (double faults), and service/return aggregates, match results, dates, surface, and format information. Verify actual column coverage, definitions, and missingness by tour, year, surface, and tournament level in local data before using a feature.

These are **match aggregates**: they are sufficient for initial ace, double-fault, and exposure estimation. They do **not** inherently label every serve as a first-serve ace versus a second-serve ace or provide shot-by-shot winners, forehands, rally length, movement, or fatigue. Do not invent those observations.

Exclude or separately model incomplete scorelines, retirements and walkovers as appropriate to the forecast target. Score rules and sportsbook grading/void rules must be explicit. Resolve the 11 held-out WTA `W` events for the main-tour denominator; do not silently mix WTA 125 with main tour.

**Data and code availability:** the model-performance report and simulator code are referenced in the companion brief on `feat/tennis-point-model`; those artifacts were not independently audited when this plan was prepared. Validate local implementations before claiming an operational capability.

## Minimal model ladder

All models use only information available before match start; use identical held-out matches and published coverage counts.

| Model | Forecast | Purpose |
|---|---|---|
| P0: empirical player rate | Player's rolling all-surface aces and DFs **per match**, shrunk to tour-wide prior; Poisson and negative-binomial count fits | Minimum direct count baselines |
| P1: exposure × rate | Separately forecast service points; apply a shrinkage-based ace-per-service-point and DF-per-service-point rate; compare Poisson, binomial, beta-binomial, and negative-binomial as appropriate | Determine whether modeling opportunity adds value |
| P2: current scoring simulator + event labels | Predict service-point outcomes and terminal match length; accumulate service points, aces, DFs per player over complete simulated matches | Test the incremental value of coherent match length and game dynamics |
| P3: calibrated joint simulator | Add opponent/surface adjustment, overall-to-surface partial pooling, and estimated shared match-level variation | Test joint distributions and tails only after P2 has a reliable baseline |

**Crucial cold-start rule:** the current surface-only point model underperforms Elo most strongly when serving history is thin. Pool overall, other-surface and same-surface evidence with explicit effective sample sizes; fall back to broader priors. Do not let a player with 60 same-surface service points look as certain as one with 3,000.

Use match-outcome Elo as contextual information or a prior **only if the resulting service-point and exposure distributions independently validate**. Calibrating the final winner probability does not uniquely determine both players' serve-point probabilities, and does not automatically calibrate totals or props.

## Coherent service-point event model

For the first version, do **not** require first-serve/second-serve ace labels if the dataset contains only aggregated ace counts. Instead, for server A vs returner B estimate:

- `p_win`: probability A wins this service point;
- `p_ace`: probability of an ace per service point;
- `p_df`: probability of a double fault per service point;
- remaining categories `p_other_win = p_win - p_ace` and `p_other_loss = 1 - p_win - p_df`.

Require `0 <= p_ace <= p_win` and `0 <= p_df <= 1 - p_win`, so ace always wins the point and double fault always loses it. Normalize or parameterize with constrained conditional probabilities; **never** clip silently after fitting.

Each sampled point increments the server's service points and exactly one outcome category; point winner updates actual game/set/tiebreak state. Aggregate per-player counts and match totals from **the same simulated trajectory**. Apply event-specific tiebreak and final-set rules, including appropriate best-of-3/best-of-5 formats.

This is a deliberately coarse starting model, not a physical description of every serve. First/second-serve splits, return quality, and shot-level attributes can be added when reliably labeled data exists.

## Phase A: validate exposure first

**Question:** does the current simulator predict the *number of service points* each player faces well enough for a count model?

- Generate full distributions of A service points, B service points, total games, number of sets, and tiebreaks.
- Baseline against rolling service-points-per-match, opponent-adjusted exposure estimates, and a direct distribution model.
- Score service-point distribution with held-out log score (when a suitable discrete probability mass is supported), CRPS, 50/80/90% interval coverage, mean bias, and MAE as secondary diagnostics.
- Segment by ATP/WTA, format, surface, Elo difference, effective serving history, retirements/completeness, and match length.
- Assert simulation invariants: each point belongs to exactly one server, completed scores obey tennis rules, probabilities sum to one, and event totals match trajectory totals.

**Gate A:** a simulator that loses convincingly on exposure is not promoted to prop prediction just because it produces realistic-looking counts.

## Phase B: validate direct ace/DF distributions

Fit P0 and P1 before adding event simulation.

- Use ace and double-fault rates per **service point**, rather than totals divided by matches, as the core exposure-normalized measures.
- Evaluate model-specific dispersion; do not assume a Poisson fit to every player's count tails.
- Train a global/pooled prior; player, surface, opponent return profile, recent workload and sufficient history enter as candidate adjustments, **not presumed improvements**.
- Freeze features and thresholds on rolling validation, with leakage checks for latest matches and pre-match player identities.

**Gate B:** report separate ace and double-fault distributions with full count coverage and tested interval/exceedance calibration.

## Phase C: assess the value of simulation

Fit P2 on the same pre-match inputs and compare it against the best *direct* P0/P1 baseline, not against a weak straw man.

Score:

1. Count-distribution log score, CRPS, and calibration/coverage of prediction intervals.
2. Over/under Brier or log loss for **every applicable historical threshold**, grouped by threshold and player, with samples per bin. If sportsbook lines are unavailable, use preregistered integer/half-point thresholds; do not imply those are actual market opportunities.
3. Paired differences with uncertainty intervals, by tour, year, surface, format, history depth and count size.
4. Correlation and conditional distributions (e.g., aces versus number of sets), because the simulator's potential benefit is a coherent *joint* forecast, not just an improved marginal mean.
5. Monte Carlo convergence; test simulation seed stability and ensure simulation noise is much smaller than between-model differences.

Only after P2 passes should P3 add match-level latent serve-day effects and opponent/conditions coupling. Estimate the variance and correlation from historical data; independent fixed-probability point draws may understate tails.

**Gate C:** GO only if the simulator improves a predeclared primary proper scoring rule over the strongest direct baseline without unacceptable miscalibration. If it does not, use the direct distribution model for props and keep the simulator for separately validated match markets.

## Backtest protocol

- Chronological walk-forward; no future data in ratings, opponent histories, player match stats, event rules or expected lineup.
- Treat 2023–2026 as explored **development** for model selection. Use older chronological folds for tuning where viable; true confirmation requires future, previously unseen matches after the 2026-10-14 freeze.
- Compare only on matched samples and provide a second coverage report for all eligible matches.
- Declare one primary proper scoring metric per stage; report Brier skill score for exceedance predictions against the *best direct prop baseline*, not match-winner Elo.
- Bootstrap at an appropriate match or tournament cluster level and report intervals, not only the point estimate.
- Separately evaluate observed full matches and any retirement-adjusted forecasts to avoid changing targets mid-test.
- Public sportsbook odds/prices, if available, are an **evaluation benchmark**, not mandatory inputs. Preserve quote timestamp, line, side, venue, and grading rule; no claim of ROI/edge without calibrated out-of-sample probabilities and executable price assumptions.

## Deliverables

Write results under `docs/`:

- `TENNIS-PROPS-DATA-AUDIT-2026-10-14.md`: column inventory, sample counts, definitions, missingness, retirements, scoring rules, and licensing.
- `TENNIS-PROPS-BASELINES-2026-10-14.md`: P0/P1 rolling results, metrics, calibration, and segment tables.
- `TENNIS-PROPS-SIM-BACKTEST-2026-10-14.md`: P2/P3 only after prior gates; comparisons on identical matches, uncertainty intervals, examples of failures.
- `TENNIS-PROPS-DECISION-2026-10-14.md`: separate GO/NO-GO calls for exposure modeling, ace and DF distributions, and simulation incremental value.

These are **planned filenames**, not claims that the reports already exist. The first implementation milestone is the **data audit and P0/P1**, not adding a complex multi-event simulator.

## Licensing and product boundary

Jeff Sackmann match data and the cited mirror are CC BY-NC-SA 4.0. **Research use only** pending licensing decision D1; no training or publishing a commercial Legendary Picks projection feature from this dataset without an authorized licensing path. Store source provenance and reproduce no proprietary market quotes without rights.

The long-term extension to footwork, shot selection, shot quality, power, forehand, backhand and winners/unforced errors requires independently licensed tracking/video/shot-chart data, and each feature must prove incremental held-out predictive value.
