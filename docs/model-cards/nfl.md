# NFL model card

**Scope:** NFL regular-season game forecasts and team playoff-odds simulations implemented in this repository. The game forecasts are locked as separate model versions. This card describes the code and validation evidence available on 2026-10-15; it is not a claim of betting advantage.

## Game forecasts

| Model | Method | Operational status |
|---|---|---|
| `nfl-v1` points model | Recency-weighted team offense/defense points ratings with a prior carried from the previous season; fitted expected points and a Normal margin-to-win-probability link | Current adopted/legacy baseline |
| `nfl-v2` EPA | Pass and rush EPA offense/defense ratings, converted to points and calibrated on a prior season | Trial only; not adopted |
| `nfl-v1+elo stack` | Frozen v1 margin plus a 538-style Elo gap in a fitted linear stack | Research challenger; the lock code labels it trial |

The v1 lock version records the frozen settings: half-life 6 weeks, margin cap 14, prior strength 4 games, prior shrinkage one third, and win-probability scale `sigma=13.295`. It fits only on scored regular-season games before the target week. The preseason prior comes from the previous season and is shrunk toward the league mean. Neutral-site status affects home advantage. A lock is created from 90 minutes before kickoff up to kickoff; later runs cannot replace it. The shared ledger retains later unlocked runs for audit, while grading uses the first lock for each model version.

The v2 implementation models pass and rush EPA separately for offense and defense, weights recent play-by-play more heavily, carries shrunken previous-season ratings forward, and calibrates expected points and margin scale from prior-season walk-forward predictions. It requires complete earlier game results and play-by-play. Its historical holdout did not establish an improvement, so it remains a challenger.

The Elo stack combines the frozen v1 margin with an Elo difference and home-field term, fits its coefficients and residual scale on earlier seasons, and preserves v1's projected total. Its retrospective test improved Brier over v1 in the reported pooled seasons, but the API still treats it as experimental. The prospective evaluation should complete before changing the operational default.

## Targets, grades, and validation

The game model outputs projected home and away points, margin, total, and home-win probability. The grader records winner-probability Brier and log loss, margin and total absolute errors, and ATS result against the market line captured with the lock. Ties are handled separately from decisive win/loss outcomes. Market comparisons use the captured line, not a subsequently updated schedule value.

For a binary winner target, Brier is the mean squared difference between predicted home-win probability and the observed outcome (1 for a home win, 0 for an away win). Zero is perfect; lower is better. A 50/50 forecast scores 0.25 on a balanced outcome set. The captured, de-vigged market probability is the stronger practical benchmark.

| Model and evaluation | Brier (n) | Reference Brier | Readout |
|---|---:|---:|---|
| `nfl-v1`, 2025 holdout | 0.2288 (255) | 0.2500 50/50; 0.2497 constant 57% home; 0.2137 closing market | Beats naive references; worse than market |
| `nfl-v2` EPA, 2025 second look | 0.2291 (255) | 0.2288 `nfl-v1` on the same games | No improvement; paired difference +0.0003, 95% CI [−0.0083, +0.0087] |
| v1 + Elo research stack, 2011–2023 | 0.2197 (3,158) | 0.2229 recalibrated v1; 0.2104 closing market | Retrospective improvement over v1; still worse than market |

The frozen v1 configuration was selected on 2024 and evaluated once on the 2025 holdout. Its mean absolute margin error was 10.67 points versus 9.97 for the spread, and total error was 10.61 versus 10.17 for the closing total. The sample is one season and roughly 255 games, so differences are uncertain. The Elo comparison is retrospective, not prospective confirmation, and does not change the operational default. The EPA challenger failed its adoption gate.

## Playoff odds

The separate team playoff-odds job fits regular-season offense and defense ratings, then simulates remaining games and applies NFL seeding and tiebreaking rules. It reports playoff, division, bye, seed, and wins probabilities. The current default score method is `placeholder-split-40` (`nfl-playoff-odds-v1.2`). A historical-score sampling option (`nfl-playoff-odds-v1.3`) passed most distribution checks but failed the pre-registered across-team scoring-spread gate, so it is not the default. Reported playoff and division probabilities were close between methods and within simulation noise; the season-scoring spread failure remains material.

The playoff-probability Brier benchmark is 0.246 for the naive 14-of-32 team playoff-rate forecast. In the 2020–2025 historical comparison (384 team forecasts), the results were:

| Simulation method and seed | Playoff Brier | Division Brier |
|---|---:|---:|
| Placeholder A | 0.13262 | 0.12121 |
| Placeholder B | 0.13319 | 0.12072 |
| Historical scores A | 0.13277 | 0.12135 |
| Historical scores B | 0.13190 | 0.12142 |

The seed-level differences were within simulation noise. This result evaluates playoff odds, not weekly game-winner forecasts.

## Intended use and limits

Use forecasts as uncertain estimates, not as betting recommendations. The game model is not market-leading on the reported 2025 holdout. Early-season team ratings have less current-season evidence. The Elo challenger has retrospective results but needs prospective scoring. The EPA model is not adopted. The playoff simulation's history-score option failed a season-level distribution check. Injury, quarterback availability, and other late roster information are not comprehensively modeled in these game forecasts. The lock-time market quote is a benchmark and is not a feature in the game model.

The backend uses nflverse schedules, scores, and play-by-play. Data-source terms and permitted redistribution or commercial use should be checked before external use of derived outputs.

## References

- `backend/nfl_ratings.py`, `backend/nfl_ratings_data.py`, `backend/lock_nfl_week.py` — v1 ratings and locks.
- `backend/nfl_epa_model.py`, `backend/lock_nfl_epa.py` — EPA challenger.
- `backend/lock_nfl_elo.py`, `backend/nfl_elo_replica.py` — Elo stack.
- `backend/grade_nfl_locks.py` — locked-game scoring.
- `backend/nfl_sim.py`, `backend/jobs/nfl_playoff_odds.py` — playoff simulation.
- `docs/RESULTS-A3-nfl-backtest-2026-10-09.md` — v1 holdout and baselines.
- `docs/RESULTS-A9-nfl-epa-v2-backtest-2026-10-11.md` — EPA adoption-gate results.
- `docs/RESULTS-nfl-elo-and-era-2026-10-13.md` — Elo and feature research.
- `docs/RESULTS-nfl-sim-scores-2026-10-13.md` — playoff score-simulation validation.
