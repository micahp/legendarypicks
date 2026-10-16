# Tennis total-games distribution backtest

- **Run date:** 2026-10-16
- **Status:** Historical development evidence; not prospective confirmation or a production approval
- **Primary target:** Official completed-match total games, best-of-three main-tour matches
- **Primary score:** Discrete CRPS; lower is better
- **Implementation:** [`backend/tennis_total_games_backtest.py`](../backend/tennis_total_games_backtest.py)
- **Aggregate outputs:** [`research/tennis/total-games/2026-10-16/`](../research/tennis/total-games/2026-10-16/)

## Result

The current point-probability scoring simulator did not improve total-games forecasts over a direct historical
distribution. The format, surface and pre-match competitiveness direct distribution had lower CRPS, lower mean absolute
error and almost no aggregate mean bias on both tours. The simulator overpredicted total games by 1.89 on ATP and 2.42
on WTA. The direct format-only distribution had the best negative log score, while the more detailed direct distribution
had the best CRPS; no single direct variant won every metric.

The paired event-cluster bootstrap confirms a CRPS loss for the simulator against the CRPS-leading direct variant on
both tours. The result is consistent in every reported year, surface, competitiveness band and player point-history
band. Treat this as a **no-promotion for the current simulator's total-games distribution on the evaluated population**.
It does not reject the simulator for every other target, nor establish that a future simulator cannot improve.

## Evaluation design

The backtest uses prior-only chronological date blocks. Every match with the same archived event-start date is forecast
before any match from that date updates player, Elo or total-games history. It evaluates matches dated 2023-01-01 through
the latest available 2026 rows, with direct historical distributions trained from 2022 onward. The historical match
archive is research-only under its current data-use terms; these outputs are not cleared for commercial model use.

Four forecast distributions were compared on the same eligible matches:

1. **Current simulator:** Existing opponent-adjusted serve/return point estimates, with two-year player decay and
   `K=250`, passed through the exact tennis scoring distribution. Opening server is averaged 50/50.
2. **Direct format:** Empirical total-games frequencies conditioned on scoring format.
3. **Direct format + surface:** Adds court surface to the direct grouping.
4. **Direct format + surface + competitiveness:** Adds the pre-match absolute Elo gap, bucketed as `<50`, `50–149`,
   `150–299` or `300+` points. This is the CRPS-leading direct variant.

The direct histograms use a five-year half-life and hierarchical smoothing: 10 pseudo-observations for the format prior,
30 for the surface distribution and 30 for the competitiveness distribution. Each target-date block is scored before
its outcomes enter the histograms. Elo starts at 1500 with `K=32` and updates after each date block.

Scoring rules were checked by format. Standard best-of-three uses a 7-point tiebreak at 6–6. For 2022 onward Grand Slam
best-of-three rows, the deciding set uses a 10-point tiebreak at 6–6. A bracketed deciding match tiebreak contributes no
games to the total. The Grand Slam rule change is documented by the [Australian Open scoring guide](https://ausopen.com/articles/news/guide-scoring-tennis)
and [Roland-Garros 2022 announcement](https://www.rolandgarros.com/en-us/article/roland-garros-innovations-commitments-edition-2022).

Incomplete matches and walkovers, non-best-of-three matches, unverified scoring formats and unparseable scores are not
scored. The simulator and all three direct distributions use identical scored targets within each tour.

## Aggregate scores

Bias is forecast mean minus observed mean. Coverage is the share of observed totals inside a central predictive
interval. The reported over thresholds are diagnostics, not historical sportsbook lines.

| Tour | Method | Matches | CRPS | Log score | Total-games MAE | Bias | 80% interval coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| ATP | Current simulator | 11,766 | 3.533 | 3.106 | 5.474 | +1.89 | 79.0% |
| ATP | Direct format | 11,766 | 3.363 | **3.055** | 5.058 | -0.07 | 82.7% |
| ATP | Direct format + surface | 11,766 | 3.363 | 3.062 | 5.055 | -0.09 | 84.2% |
| ATP | Direct + surface + competitiveness | 11,766 | **3.359** | 3.079 | **5.045** | -0.09 | 83.7% |
| WTA | Current simulator | 13,062 | 3.557 | 3.145 | 5.519 | +2.42 | 76.8% |
| WTA | Direct format | 13,062 | 3.246 | **3.033** | 4.891 | +0.04 | 86.4% |
| WTA | Direct format + surface | 13,062 | 3.246 | 3.041 | 4.891 | +0.02 | 85.5% |
| WTA | Direct + surface + competitiveness | 13,062 | **3.231** | 3.061 | **4.865** | +0.04 | 84.0% |

The primary CRPS difference (simulator minus direct format + surface + competitiveness) is **+0.174 ATP** (95% event-
cluster bootstrap interval +0.145 to +0.204; 223 event clusters) and **+0.326 WTA** (+0.299 to +0.354; 193 event
clusters). Positive values favor the direct distribution. For negative log score, the corresponding differences are
+0.027 ATP (+0.014 to +0.041) and +0.084 WTA (+0.070 to +0.097), also favoring the direct distribution. Intervals use
1,000 paired event-cluster bootstrap resamples.

The direct format-only distribution has the best log score in each tour. Adding surface and competitiveness improves
CRPS slightly, but does not improve log score. Keep both as references; the detailed direct variant is not a universal
winner across every scoring rule.

## Over-threshold calibration diagnostics

Each entry is mean predicted probability / observed frequency. The diagnostic thresholds are 18.5, 20.5, 22.5, 24.5
and 26.5 games. The simulator is too high at every threshold on both tours. The direct format-only forecast is close to
the observed frequency across these pooled thresholds.

| Tour | Method | Over 18.5 | Over 20.5 | Over 22.5 | Over 24.5 | Over 26.5 |
|---|---|---:|---:|---:|---:|---:|
| ATP | Simulator | .867 / .762 | .722 / .594 | .592 / .458 | .514 / .387 | .423 / .304 |
| ATP | Direct format | .756 / .762 | .590 / .594 | .456 / .458 | .384 / .387 | .303 / .304 |
| WTA | Simulator | .799 / .627 | .659 / .483 | .542 / .379 | .473 / .319 | .379 / .244 |
| WTA | Direct format | .631 / .627 | .488 / .483 | .385 / .379 | .323 / .319 | .244 / .244 |

## Where the gap appears

The table reports CRPS difference (simulator minus direct surface + competitiveness); positive favors the direct
distribution. Coverage is observed coverage of the nominal 80% central interval, shown as simulator / direct.

| Slice | ATP n | ATP ΔCRPS | ATP 80% coverage | WTA n | WTA ΔCRPS | WTA 80% coverage |
|---|---:|---:|---:|---:|---:|---:|
| 2023 | 3,448 | +0.148 | 78.7% / 83.9% | 3,781 | +0.327 | 75.8% / 82.0% |
| 2024 | 3,561 | +0.197 | 79.4% / 84.2% | 3,892 | +0.339 | 76.5% / 84.4% |
| 2025 | 3,191 | +0.177 | 79.8% / 83.6% | 3,631 | +0.306 | 77.5% / 84.6% |
| 2026 partial | 1,566 | +0.171 | 77.5% / 82.2% | 1,758 | +0.334 | 78.5% / 86.4% |
| Clay | 3,933 | +0.153 | 79.7% / 84.8% | 3,404 | +0.322 | 76.4% / 84.6% |
| Grass | 1,079 | +0.163 | 80.4% / 84.4% | 1,487 | +0.259 | 78.2% / 81.9% |
| Hard | 6,754 | +0.188 | 78.5% / 82.9% | 8,171 | +0.340 | 76.7% / 84.2% |
| Elo gap <50 | 2,913 | +0.140 | 79.2% / 84.4% | 3,016 | +0.249 | 78.0% / 83.1% |
| Elo gap 50–149 | 4,637 | +0.162 | 78.9% / 83.5% | 4,889 | +0.259 | 78.3% / 83.4% |
| Elo gap 150–299 | 3,282 | +0.196 | 78.6% / 82.5% | 3,820 | +0.365 | 76.0% / 84.9% |
| Elo gap 300+ | 934 | +0.260 | 80.8% / 86.4% | 1,337 | +0.633 | 71.1% / 85.8% |
| Min serve-history <300 points | 2,594 | +0.280 | 74.5% / 81.9% | 2,960 | +0.504 | 73.4% / 82.0% |
| Min serve-history 300–1,499 | 3,786 | +0.155 | 79.7% / 83.4% | 4,501 | +0.280 | 77.5% / 84.2% |
| Min serve-history 1,500+ | 5,386 | +0.135 | 80.8% / 84.8% | 5,601 | +0.268 | 78.1% / 85.0% |

The simulator's positive bias and CRPS loss are not isolated to one surface or one history segment. The largest WTA gap
appears for matches with an Elo gap of 300 or more and for players with thin serve history. These are diagnostics, not
causal explanations. The full archived JSONs contain all scores and thresholds for each segment.

## Decision and next work

- Keep the current simulator in Model Lab as a challenger. Do not use it as the total-games incumbent on this evaluated
  best-of-three population.
- Keep match winner, total games and player-stat projections as separate targets. The simulator's earlier loss to Elo
  on match winners did not answer this question; this total-games experiment now independently finds it behind direct
  historical distributions.
- Complete prospective grading with frozen per-target versions, full distributions, timestamps and input snapshots.
  The existing local development grader does not yet retain full distributions or Brier/CRPS grading.
- Use the archived segments to diagnose overprediction by surface, history depth and competitiveness. Change the
  simulator only after stating a hypothesis and a predeclared comparison against the direct baselines.
- Before any promotion, audit format parsing and compare on future matches. The 2023–2026 results are development
  evidence, not untouched confirmation.

## Reproduction

The development database is opened read-only by the script. Example:

```bash
PYTHONPATH=backend python3 backend/tennis_total_games_backtest.py \
  --db backend/data/picks.dev.db --tour atp \
  --out /tmp/tennis-total-games-atp.json \
  --records /tmp/tennis-total-games-atp.csv
```

Repeat with `--tour wta` and tour-specific output paths. Aggregate JSON outputs for this run are preserved in
[`research/tennis/total-games/2026-10-16/`](../research/tennis/total-games/2026-10-16/). The row-level CSVs used for
the full run were temporary files under `/tmp`; regenerate them with the command above if needed.
