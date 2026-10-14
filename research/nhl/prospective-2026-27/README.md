# NHL prospective evaluation, 2026–27

This folder starts a prospective evaluation of three frozen candidates. It does not revise or
replace the retrospective reports. A game is in the prospective sample only when its immutable
forecast was recorded after `prospective_session.json` was created and before the official NHL
`startTimeUTC`.

## Frozen candidates

| Candidate | Moneyline | Score distribution |
| --- | --- | --- |
| `B3_elo` | Selected Elo v1: K=10, home ice=35 | Elo-feature Poisson score model |
| `B5_xg_poisson` | Derived from its independent score distribution | Rolling 10-game 5-on-5 score-venue-adjusted xGF/xGA Poisson model |
| `B7_elo_xg_poisson` | Derived from its independent score distribution | B5 plus pregame Elo rating difference |

Poisson regularization is fixed at alpha 0.01, the value selected in the earlier preregistered
baseline work. Coefficients are refit once through 2025–26 before prospective session start. The
2025–26 season is training history for this forward test, not a fresh holdout. No market price is
used as a statistical feature. The probability calibration challenger is not included in these
three candidates.
Elo+xG remains an experimental challenger, not a validated replacement for Elo.

## Frozen targets and settlement limits

The historical target is regulation plus overtime goals with the shootout deciding goal removed.
The official winner target includes overtime and shootouts. Goal-score probabilities are independent
Poisson probabilities; tied model-score mass is resolved with the historical home shootout win rate.
That supports a full-game winner estimate, but not a separate regulation-win probability. V1 records
that field as unavailable rather than infer regulation outcomes from the final score.

Totals and puck-line outputs use the model's regulation-plus-overtime, shootout-goal-excluded score
target. They are statistical probabilities, not a claim that every sportsbook or exchange settles
the market that way. The current Kalshi NHL series is a game-winner market. Its captured prices are
reported separately and are never joined into model features. Contract-specific settlement rules
must be versioned before comparing total or spread prices.

## Commands

Run with Python 3.9+ and the `numpy` and `scikit-learn` packages (the frozen training code uses the
same estimator family as the historical baseline). From the repository root:

```bash
python3 research/nhl/prospective-2026-27/run_pipeline.py freeze
python3 research/nhl/prospective-2026-27/run_pipeline.py init
python3 research/nhl/prospective-2026-27/run_pipeline.py forecast --horizon-hours 24
python3 research/nhl/prospective-2026-27/run_pipeline.py capture-markets
python3 research/nhl/prospective-2026-27/run_pipeline.py collect-results
python3 research/nhl/prospective-2026-27/run_pipeline.py complete-score-distributions
python3 research/nhl/prospective-2026-27/run_pipeline.py report
```

`freeze` and `init` are write-once. Forecasts, Kalshi snapshots, and official results are append-only
JSONL ledgers. A second forecast for the same game and model version is refused; any later model
change needs a new version. Concurrent forecast writers are serialized and duplicate game/model
rows are refused. The first `forecast` command initializes the prospective clock if `init`
was not run separately. A forecast after puck drop is rejected.

The initial two game forecasts record the pipeline run-start time from before source acquisition;
later pipeline runs record the forecast time after schedule and feature retrieval. The first records
remain immutable, with their feature/game IDs and source hashes preserved.

The session pins the frozen model file hash. A later specification must use a new versioned folder
and session; the active session refuses a changed artifact.

`forecast` reads the NHL schedule, reconstructs Elo from canonical NHL game outcomes plus published
current-season NHL schedule results, and reads MoneyPuck team game-by-game 5-on-5 xG. Team source
files are cached under `.cache/` and reused for 30 minutes. Each forecast stores its full feature
snapshot, source dates and game IDs, model-artifact hash, schedule response hash, and source-file
hashes. The market command calls Kalshi's public market and orderbook endpoints and records both
sides, price levels, capture time, and response hashes. It does not backfill gaps from a bookmaker.

`collect-results` reads final NHL gamecenter records. It preserves the official score and winner
separately from period-by-period regulation goals, overtime goals, and shootout events. When the final
period is a shootout, it removes the deciding goal from the statistical target and validates that the
official period totals reconcile. `report` creates a new timestamped cumulative JSON report
with monthly and cumulative Brier, log loss, calibration bins, team-goal MAE, joint goal NLL, totals
and puck-line Brier scores, Kalshi coverage and same-game comparison, and paired game-level 95%
bootstrap intervals, including model-versus-market differences on usable matched quotes. A report is
a derived snapshot and can be regenerated; the source ledgers are never rewritten. Paired intervals
report model A minus model B loss, so positive values mean model A performed worse.

Each new forecast stores the full 0–20 by 0–20 joint home-away score probability matrix and both goal
marginals. The support is normalized over 0–20 goals per team; its omitted Poisson tail is negligible
for the fitted means, and the support is recorded on each row. The first six forecasts were archived
before that output field was added; `complete-score-distributions` appends companion rows derived
only from their immutable expected-goal means and frozen model parameters. Those supplement records
retain the original forecast timestamp and hash, plus their own later derivation timestamp. They do
not alter the forecast rows or use market/game outcomes.

## Data status and limits

- Canonical games and rolling features are pinned by SHA-256 in the frozen model artifact.
- MoneyPuck's published data page describes current xG data and notes that the xG model was rebuilt
  for 2026–27. The archived training feature table does not identify its exact source-model release.
  Live forecasts preserve the source file hash, publisher `Last-Modified`/ETag, and the current
  release label, so this is visible as a version-compatibility limitation.
- MoneyPuck describes free downloads as available for non-commercial use; commercial permission
  for Legendary Picks remains unresolved. This pipeline is research-only until the data rights are
  settled. See [MoneyPuck data and terms](https://www.moneypuck.com/data.htm).
- Kalshi market discovery uses the public [`Get Markets`](https://docs.kalshi.com/api-reference/market/get-markets)
  endpoint and quote depth uses [`Get Market Orderbook`](https://docs.kalshi.com/api-reference/market/get-market-orderbook).
  The exchange orderbook endpoint returns bid levels; the YES ask is derived as one minus the best
  NO bid. Each response receipt timestamp and the batch identifier are preserved because REST
  orderbook responses are not a historical tick tape. Market comparisons require both team sides to have a non-crossed two-sided
  book, positive top-level size, and a spread no wider than 20¢. Wider and incomplete quotes remain
  in the raw ledger and are reported as coverage/data-quality outcomes, not benchmark prices.
- The research CLI itself does not install or enable services. Legendary Picks supplies separate
  dev timer definitions under `ops/systemd/`: the forecast job runs every five minutes with a
  96-minute horizon, the per-model lock checker runs every minute inside the one-minute T-90
  window, and official-result grading runs daily after a four-hour finality grace period. These
  jobs store records in a standalone NHL model database; they do not write either LP picks database.
  The forecast runner refuses post-start forecasts and remains research-only while MoneyPuck
  commercial rights are unresolved.

## Output files

- `frozen_models_2026-27_v1.json`: fixed model definitions, fitted coefficients, source hashes,
  training sample counts, and known version limitations.
- `training_environment.json`: interpreter and numerical-library versions plus the frozen model
  and input hashes.
- `prospective_session.json`: one-time start timestamp and model hash.
- `forecasts.jsonl`: immutable forecasts and embedded feature snapshots.
- `market_quotes.jsonl`: separate append-only Kalshi captures or explicit coverage failures.
- `official_results.jsonl`: official result and distinct scoring target records.
- `score_distributions.jsonl`: deterministic full-PMF supplements for early forecasts that predate
  the inline matrix field.
- `cumulative_results_2026-27_<timestamp>.json`: monthly and cumulative scoring snapshots.
