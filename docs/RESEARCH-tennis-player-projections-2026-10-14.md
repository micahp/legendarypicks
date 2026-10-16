# RESEARCH: Tennis player-projection engine

<<<<<<< HEAD
- **Date:** 2026-10-14
- **Status:** Research plan, not a validated model
- **Repository:** `micahp/legendarypicks`, branch `docs/tennis-prediction-brief`
- **Related:** [Tennis match prediction brief](BRIEF-tennis-prediction-model.md)
=======
**Date:** 2026-10-14  
**Status:** Research plan, not a validated model  
**Repository:** `micahp/legendarypicks`, branch `docs/tennis-prediction-brief`  
**Related:** [Tennis match prediction brief](BRIEF-tennis-prediction-model.md)
>>>>>>> 24bc9fc87425138dc00f964d4df5f09b8f9cb3c3

## Decision

**GO on player-projection research; NO-GO on the current simulator as a standalone match-winner forecaster.**

The goal is not to recover the match-winner result by asserting that a coherent simulator must be more accurate. The immediate question is whether simulating service-point **opportunities** and outcomes produces better **player-statistic count distributions** than simpler methods.

The 2023 to 2026 match-winner window has been inspected and is a development set, **not** untouched confirmation:

| Tour | Matches | Elo Brier | Point-model simulator Brier | Elo log loss | Simulator log loss |
|---|---:|---:|---:|---:|---:|
| ATP | 11,777 | 0.2280 | 0.2353 | 0.6490 | 0.6628 |
| WTA | 13,066 | 0.2160 | 0.2288 | 0.6210 | 0.6486 |

<<<<<<< HEAD
Those numbers are not prop forecasts. The simulator passed 48 arithmetic/Monte Carlo comparison cases. A separate
2023–partial-2026 total-games backtest now finds it behind direct historical distributions on ATP and WTA BO3 matches;
that is a failed predictive comparison, not an arithmetic defect. Tiebreak occurrence, service-volume and player-statistic
forecasts remain separate targets and have not all passed historical predictive validation. See
[`TENNIS-TOTAL-GAMES-BACKTEST-2026-10-16.md`](TENNIS-TOTAL-GAMES-BACKTEST-2026-10-16.md).
=======
Those numbers are not prop forecasts. The existing simulator passed 48 arithmetic/Monte Carlo comparison cases, but its total-games, tiebreak, service-volume, and player-statistic forecasts **have not passed historical predictive validation**. Keep the two conclusions separate.
>>>>>>> 24bc9fc87425138dc00f964d4df5f09b8f9cb3c3

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

<<<<<<< HEAD
## Gate A: validate service-point exposure first

**Question:** does the current simulator predict the *number of service points* each player faces well enough for a count model?

- First score expected service-point volume against a rolling player/surface exposure mean and a tour/surface mean. The exact
  simulator exposes expected service points for both players; its scoring recurrence was checked against independent
  point-by-point Monte Carlo. The expected-volume replay loses on both tours (ATP: MAE 19.227 vs 17.711 rolling-player;
  WTA: 20.250 vs 18.036) and overpredicts by 7.292 ATP and 9.226 WTA service points per player on average. It loses in
  every test year and on hard, clay and grass. The report is `docs/TENNIS-PROPS-BASELINES-2026-10-14.md`.
- Full-distribution replays (50 match trajectories per forecast) also lose on CRPS: ATP 12.842 and 12.814 versus 12.214
  direct across two seeds (sim-minus-direct +0.628 and +0.600); WTA 13.503 and 13.505 versus 12.422 (+1.081 and +1.083).
  Both tours' simulator intervals under-cover at 50%, 80% and 90%, in every year and on hard, clay and grass. Across the
  seeds, CRPS changes by at most 0.028 on ATP and 0.002 on WTA; interval coverage changes by at most 0.13 percentage
  point. Results are in `docs/TENNIS-PROPS-BASELINES-2026-10-14.md`.
- Gate A is a no-go for the current simulator as a service-point exposure forecast on the evaluated completed
  best-of-three main-tour population. Keep P0/P1 moving with direct exposure; a format/history-depth review remains before
  extending this decision beyond that population.
- Then generate full predictive distributions for A and B's service points, total games, sets and tiebreaks. Add opponent-
  adjusted direct exposure estimates if they are available without leakage.
- Score service-point distributions with held-out log score (when a discrete mass is supported), CRPS, 50/80/90% interval
  coverage, mean bias and MAE. Report the paired sample and distribution coverage.
- Segment by ATP/WTA, format, surface, Elo difference, effective serving history, retirements/completeness, and match length.
- Assert simulation invariants: each point belongs to exactly one server, completed scores obey tennis rules, probabilities sum to one, and event totals match trajectory totals.

**Gate A:** promote simulated opportunity distributions only if they improve on the direct exposure baseline under a
predeclared proper score and show acceptable calibration. If Gate A fails, keep player-projection work moving: use or
improve direct exposure estimates for P0/P1, and do not assume the match simulator supplies better opportunity forecasts.

## Gate B: validate direct ace/DF distributions

Two P0/P1 experiment families now exist and must stay versioned separately. The earlier E2-based experiment used the
frozen simulator's expected service-point exposure and ran from 2019 through 2026. Its P1 negative binomial beat P0 on
ATP aces and double faults; P0 beat P1 on WTA for both. The later correction integrated E2 exposure uncertainty with a
beta-binomial: it improved on P0 and P1 for ATP, did not beat P0 for WTA aces, and was inconclusive against P0 for WTA
double faults. The result files are preserved at
`research/tennis/props/2026-10-14/e2-count-mixtures.json` and
`research/tennis/props/2026-10-14/e2-exposure-diagnostics.json`.

A separate 2015–partial-2026 replay uses direct historical player/surface service-point exposure and a moment-matched
P1 Gamma-Poisson distribution that includes exposure variance. It has lower CRPS and log score than its P0 Gamma-Poisson
and plug-in Poisson candidates for all four tour/target cells. The result is useful development evidence for this
direct-exposure variant, but it changes the exposure method, P0 specification, count-rate estimates, score and date
window together. It does not reverse or supersede the earlier E2-based result. Its complete table, calibration and
uncertainty notes are in `docs/TENNIS-PROPS-BASELINES-2026-10-14.md`.

Neither experiment establishes a promoted production incumbent. The direct-exposure variant's ATP ace 80/90% intervals
under-cover; DF intervals on both tours and WTA ace intervals over-cover. Remaining checks are an identical-date,
identical-target comparison of the versioned direct candidates; threshold reliability and tail calibration; randomized
PIT; interval coverage and sharpness by tour, surface, season, history depth and count band; and prospective grading.
These historical results are development evidence, not untouched confirmation.

P0 and P1 remain viable independently of Gate A; direct count models do not require the match simulator's exposure
forecast to pass.
=======
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
>>>>>>> 24bc9fc87425138dc00f964d4df5f09b8f9cb3c3

- Use ace and double-fault rates per **service point**, rather than totals divided by matches, as the core exposure-normalized measures.
- Evaluate model-specific dispersion; do not assume a Poisson fit to every player's count tails.
- Train a global/pooled prior; player, surface, opponent return profile, recent workload and sufficient history enter as candidate adjustments, **not presumed improvements**.
- Freeze features and thresholds on rolling validation, with leakage checks for latest matches and pre-match player identities.

<<<<<<< HEAD
**Gate B:** report separate ace and double-fault distributions with full count coverage and tested interval/exceedance
calibration. Compare P0 and P1 on identical eligible matches; the best valid direct model becomes the incumbent for Gate C.

## Immediate work order

1. **P0/P1 consolidation is documented.** The earlier E2 findings, corrected exposure-mixture outputs and separate
   direct-historical-exposure challenger are preserved. Do not rerun the full replay merely to restate existing results.
   Still compare frozen candidates on identical dates and finish threshold, PIT, tail and interval calibration before
   choosing one direct ace/DF incumbent per tour.
2. **Total-games comparison is complete for development.** On identical 2023–partial-2026 ATP/WTA BO3 matches, direct
   historical distributions beat the current simulator on primary CRPS, expected-games MAE and aggregate bias. The
   direct format-only distribution has the best log score, while the surface/competitiveness distribution has the best
   CRPS. The paired event-cluster CRPS difference (simulator minus CRPS-leading direct) is +0.174 ATP and +0.326 WTA,
   with 95% intervals above zero. Segment results show the loss across year, surface, competitiveness and history
   depth; they do not identify its cause. Keep the simulator out of the total-games incumbent role on this population.
   See [`TENNIS-TOTAL-GAMES-BACKTEST-2026-10-16.md`](TENNIS-TOTAL-GAMES-BACKTEST-2026-10-16.md).
3. **Finish prospective grading.** Freeze each target's model version and store full distributions, timestamps and input
   snapshots before play. Grade winner probabilities, total-games distributions and ace/DF counts when supported by
   reliable final data. Keep immutable challenger records separate.
4. **Diagnose the simulator's total-games overprediction.** Segment review by surface, serve-history depth and match
   competitiveness is complete; use it to form a specific cause hypothesis. Keep the current simulator in Model Lab as
   a challenger.
5. **Only then test an improved simulator** against the strongest direct baselines using a predeclared primary score,
   sample, calibration criteria and promotion rule. Test joint outputs separately; do not assume gains transfer across
   targets.

## Later conditional phase: assess the value of event-labeled simulation

Once the immediate work order is complete, fit P2 on the same pre-match inputs and compare it against the best *direct*
P0/P1 baseline, not against a weak straw man.
=======
**Gate B:** report separate ace and double-fault distributions with full count coverage and tested interval/exceedance calibration.

## Phase C: assess the value of simulation

Fit P2 on the same pre-match inputs and compare it against the best *direct* P0/P1 baseline, not against a weak straw man.
>>>>>>> 24bc9fc87425138dc00f964d4df5f09b8f9cb3c3

Score:

1. Count-distribution log score, CRPS, and calibration/coverage of prediction intervals.
2. Over/under Brier or log loss for **every applicable historical threshold**, grouped by threshold and player, with samples per bin. If sportsbook lines are unavailable, use preregistered integer/half-point thresholds; do not imply those are actual market opportunities.
3. Paired differences with uncertainty intervals, by tour, year, surface, format, history depth and count size.
4. Correlation and conditional distributions (e.g., aces versus number of sets), because the simulator's potential benefit is a coherent *joint* forecast, not just an improved marginal mean.
5. Monte Carlo convergence; test simulation seed stability and ensure simulation noise is much smaller than between-model differences.

Only after P2 passes should P3 add match-level latent serve-day effects and opponent/conditions coupling. Estimate the variance and correlation from historical data; independent fixed-probability point draws may understate tails.

**Gate C:** GO only if the simulator improves a predeclared primary proper scoring rule over the strongest direct baseline without unacceptable miscalibration. If it does not, use the direct distribution model for props and keep the simulator for separately validated match markets.

<<<<<<< HEAD
## Validation in parallel: historical replay and prospective grading

Historical research is the immediate development path; prospective records are an independent, continuing check. Neither
waits for the other.

### Historical walk-forward

- Replay chronological folds using only earlier match records, ratings, player histories, format data and features that
  would have been available before the forecast date. The archived `tourney_date` is an event start date, so group all
  matches with that date and update histories only after the group; document that this is conservative and not exact
  between-round chronology.
- Report each test season separately and aggregate paired scores only over identical target rows. Publish row coverage by
  tour, year, surface, format, completion status and history depth.
- The 2023-2026 **match-winner** results have been inspected and are development evidence, not an untouched holdout.
  Player-count targets are different outcomes, so they can be researched now; however, call a player-stat period
  “untouched” only after auditing that its outcomes and modeling choices were not used in prior selection.
- Keep an untouched historical holdout only if the audit finds one that has not influenced feature or model choices.
  Rolling-origin tests on earlier seasons are useful development evidence even when no untouched holdout remains.

### Daily prospective cycle

For every eligible upcoming ATP/WTA match, not a hand-picked subset:

1. Resolve players, tour, event, round, surface, format and published start time; record data source and missing fields.
2. Before start, freeze an immutable forecast record with forecast timestamp, model version for each target, method version,
   input snapshot/hash, and full probability distributions (winner, games, service points, aces and double faults as each
   becomes available). Never backfill a forecast after play begins.
3. After an official result, grade only targets supported by reliable source data. Mark walkovers, retirements, missing
   box scores and unsettled targets with explicit eligibility reasons; do not silently count them as misses or wins.
4. Publish daily and cumulative records: matches forecast/graded, coverage, winner Brier/log loss and skill vs Elo, service-
   point MAE/CRPS, ace/DF distribution scores, calibration and paired differences versus the incumbent.
5. Report cumulative windows of 100, 250, 500 and 1,000 matches, separated by ATP/WTA when sample size permits. Daily
   calibration bins are descriptive only; wait for adequate samples before interpreting them.

Freeze at least one official challenger/version before prospective scoring. Each experimental version gets a separate,
immutable history. Promotion requires a predeclared improvement on suitable validation; do not splice changing versions
into one cumulative record.

### Current local development status (snapshot 2026-10-16)

`backend/data/picks.dev.db` contains 12 locks since 2026-10-14, with the first on 2026-10-15; there are no Oct 14 locks.
Eleven locks have grades, and all use `tennis-free-daily-v1`. Existing capture is one lock per `(tour, game_id)`, forecast
locks occur within the hour before start, and the stored JSON lacks an input snapshot and full probability distributions.
The grader records winner correctness and total-games absolute error only; it does not calculate Brier, log loss, count
distribution scores or calibration. The current job runs every 30 minutes, but there is no cumulative daily report or
rolling-window view. These figures describe local dev only, not production. The Oct 14 prospective start was proposed but
not achieved in this snapshot; use the first actual lock date and do not backdate missing forecasts.

## Historical backtest protocol

- Chronological walk-forward; no future data in ratings, opponent histories, player match stats, event rules or expected lineup.
- Treat 2023 to 2026 match-winner results as explored **development** for winner-model selection. For player-stat targets,
  audit prior exposure before calling any period untouched. Use rolling-origin folds across prior seasons now; future
  prospective matches remain independent confirmation.
=======
## Backtest protocol

- Chronological walk-forward; no future data in ratings, opponent histories, player match stats, event rules or expected lineup.
- Treat 2023 to 2026 as explored **development** for model selection. Use older chronological folds for tuning where viable; true confirmation requires future, previously unseen matches after the 2026-10-14 freeze.
>>>>>>> 24bc9fc87425138dc00f964d4df5f09b8f9cb3c3
- Compare only on matched samples and provide a second coverage report for all eligible matches.
- Declare one primary proper scoring metric per stage; report Brier skill score for exceedance predictions against the *best direct prop baseline*, not match-winner Elo.
- Bootstrap at an appropriate match or tournament cluster level and report intervals, not only the point estimate.
- Separately evaluate observed full matches and any retirement-adjusted forecasts to avoid changing targets mid-test.
- Public sportsbook odds/prices, if available, are an **evaluation benchmark**, not mandatory inputs. Preserve quote timestamp, line, side, venue, and grading rule; no claim of ROI/edge without calibrated out-of-sample probabilities and executable price assumptions.

## Deliverables

Write results under `docs/`:

<<<<<<< HEAD
- `TENNIS-PROPS-DATA-AUDIT-2026-10-14.md`: column inventory, sample counts, definitions, missingness, retirements, scoring rules and current prospective-system audit. **Written 2026-10-16.**
- `TENNIS-PROPS-BASELINES-2026-10-14.md`: Gate A expected-volume and distribution results, followed by P0/P1 rolling results, metrics, calibration and segment tables.
- `TENNIS-PROPS-SIM-BACKTEST-2026-10-14.md`: P2/P3 only after prior gates; comparisons on identical matches, uncertainty intervals, examples of failures.
- `TENNIS-PROPS-DECISION-2026-10-14.md`: separate GO/NO-GO calls for exposure modeling, ace and DF distributions, and simulation incremental value.

The data audit and primary Gate A service-point exposure comparison are complete. On the evaluated completed
best-of-three population, the current simulator loses on expected-volume error and full-distribution CRPS on both tours;
the result is stable across two simulation seeds. Gate B's earlier E2-based P0/P1 and corrected exposure-mixture results
are archived alongside a separately defined direct-historical-exposure challenger. The total-games historical comparison
is also complete: direct distributions beat the simulator on CRPS, expected-games MAE and bias on both tours, with the
gap present in all reported segments. Remaining work is prospective grading, calibration and a causal diagnosis of the
simulator's length bias. Keep it in Model Lab; defer a richer simulator until a predeclared comparison against direct
baselines is ready. A Gate A failure does not stop player-projection work.

The long-term extension to footwork, shot selection, shot quality, power, forehand, backhand and winners/unforced errors requires independently sourced tracking/video/shot-chart data, and each feature must prove incremental held-out predictive value.
=======
- `TENNIS-PROPS-DATA-AUDIT-2026-10-14.md`: column inventory, sample counts, definitions, missingness, retirements, scoring rules, and licensing.
- `TENNIS-PROPS-BASELINES-2026-10-14.md`: P0/P1 rolling results, metrics, calibration, and segment tables.
- `TENNIS-PROPS-SIM-BACKTEST-2026-10-14.md`: P2/P3 only after prior gates; comparisons on identical matches, uncertainty intervals, examples of failures.
- `TENNIS-PROPS-DECISION-2026-10-14.md`: separate GO/NO-GO calls for exposure modeling, ace and DF distributions, and simulation incremental value.

These are **planned filenames**, not claims that the reports already exist. The first implementation milestone is the **data audit and P0/P1**, not adding a complex multi-event simulator.

## Licensing and product boundary

Jeff Sackmann match data and the cited mirror are CC BY-NC-SA 4.0. **Research use only** pending licensing decision D1; no training or publishing a commercial Legendary Picks projection feature from this dataset without an authorized licensing path. Store source provenance and reproduce no proprietary market quotes without rights.

The long-term extension to footwork, shot selection, shot quality, power, forehand, backhand and winners/unforced errors requires independently licensed tracking/video/shot-chart data, and each feature must prove incremental held-out predictive value.
>>>>>>> 24bc9fc87425138dc00f964d4df5f09b8f9cb3c3
