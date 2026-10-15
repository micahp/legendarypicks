# NHL model card

**Scope:** The NHL research forecast pipeline under `research/nhl/prospective-2026-27/` and its separate lock, grading, and read API. The current evaluation version is `nhl-prospective-2026-27-v1`. This is a research system, not a validated betting model or commercial production service.

## Forecast targets and candidates

The frozen pipeline generates three per-game candidates:

| Candidate | Features and scoring model | Role |
|---|---|---|
| `B3_elo` | Elo difference with K=10 and home-ice value 35, passed through an Elo-feature Poisson score model | Moneyline incumbent and score baseline |
| `B5_xg_poisson` | Rolling last-ten 5-on-5, score- and venue-adjusted expected goals for and against, passed through Poisson regression | xG score baseline |
| `B7_elo_xg_poisson` | B5 features plus pregame Elo difference, passed through Poisson regression | Combined challenger and current UI default |

Poisson regularization is fixed at alpha 0.01. Coefficients were fit through the 2025–26 season before the prospective session began. The B5 and B7 xG inputs are based on MoneyPuck team game-by-game data. Historical training features do not identify their exact xG source release; live data records the current publisher release and file hashes. MoneyPuck states its xG model was rebuilt for 2026–27, so the historical/live feature-version mismatch is unresolved.

For each model, the pipeline stores expected home and away goals, total, home goal differential, home-win probability, over-5.5 and over-6.5 probabilities, and a full joint score probability matrix with goal marginals. The score distributions are independent Poisson marginals. The official winner target includes overtime and shootouts; tied model score mass is resolved with the historical home shootout win rate. The model does not estimate regulation-win probability.

The statistical score target is regulation plus overtime goals with the shootout-deciding goal excluded. Total and puck-line probabilities use that target. They may not match the settlement rules of every sportsbook or exchange contract; contract-specific rules must be checked before comparing those prices.

## Forecast locks and grades

The prospective session started at `2026-10-14T08:06:00Z`. Forecasts include feature as-of time, source dates and game IDs, model and input hashes, and are rejected if they use post-start information. Per-model forecast locks are immutable and recorded near T-90; missed lock windows are stored explicitly. Official scores and winner are kept separately from the shootout-adjusted statistical score target. Grading waits four hours after scheduled start and stores immutable grades from NHL gamecenter results.

The cumulative reporting pipeline is designed to report monthly and cumulative winner Brier, log loss, calibration, team-goal MAE, joint goal negative log likelihood, totals and puck-line Brier, market coverage, and paired game-level bootstrap intervals. A prospective run is useful only when it has enough completed, locked forecasts; a forecast count alone is not predictive validation.

For the binary full-game winner target, Brier is the mean squared difference between predicted home-win probability and the observed result (1 for a home win, 0 for an away win). Zero is perfect and lower is better. A 50/50 forecast has Brier 0.25 on a balanced sample. The primary benchmark will be the contemporaneous, de-vigged market probability on the same games; 0.25 is the simple reference point.

| Candidate | Prospective winner Brier | Benchmark and status |
|---|---:|---|
| `B3_elo` | Not yet measurable (0 graded results) | Compare with 0.2500 50/50 reference and same-game Kalshi market Brier once results are collected |
| `B5_xg_poisson` | Not yet measurable (0 graded results) | Same benchmark |
| `B7_elo_xg_poisson` | Not yet measurable (0 graded results) | Same benchmark; current display default, not a validated winner |

At this repository snapshot, the ledger contains 39 model rows across 13 games and 12 market-capture rows. No official results are recorded, so there is no observed Brier score to report yet. No candidate has prospective performance evidence sufficient for adoption.

## Market comparison and product pick

The forecast model does not use market prices as features. Kalshi quotes are recorded in a separate append-only ledger and compared only when both sides have usable, non-crossed quotes, positive top-level size, and a spread no wider than 20 cents. Incomplete or stale coverage is reported as a data-quality outcome, not filled from another bookmaker.

The current UI pick selection is a separate heuristic described in `docs/NHL-MODEL-PICK-LOGIC.md`. It always emits a pick and uses spread-edge thresholds and a 6.0 projected-total cutoff. That rule has not been calibrated as a decision policy and should not be read as evidence of positive expected value.

## Intended use and limits

Use outputs for internal, prospective model comparison. The data rights for commercial use of MoneyPuck-derived features remain unresolved, so the pipeline is research-only pending permission. Shot-level xG is a provider estimate, not ground truth. The model does not yet include a confirmed starting-goalie adjustment, lineups, player ice time, or separate power-play and penalty-kill scoring. Independent Poisson score assumptions may understate dependence and score dispersion. The shootout adjustment is historical and does not create a regulation-win forecast.

There are only three frozen candidates in this prospective session. Do not promote a combined model or infer a market edge until comparable locked results accumulate and proper scores, calibration, quote coverage, settlement rules, and uncertainty have been reviewed.

## References

- `research/nhl/prospective-2026-27/README.md` — frozen protocol, data lineage, reporting, and licensing limits.
- `research/nhl/prospective-2026-27/frozen_models_2026-27_v1.json` — coefficients, fitted sample counts, and model definitions.
- `research/nhl/prospective-2026-27/run_pipeline.py` — forecast and prospective-report implementation.
- `backend/nhl_model_store.py`, `backend/grade_nhl_models.py` — immutable locks, results, grades, and exports.
- `backend/routers/nhl_model.py` — read API and selected display default.
- `docs/NHL-MODEL-PICK-LOGIC.md` — product pick heuristic, distinct from model validation.
- [MoneyPuck data and terms](https://www.moneypuck.com/data.htm) — xG data and usage terms.
