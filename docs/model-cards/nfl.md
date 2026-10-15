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

The frozen v1 configuration was selected on 2024 and evaluated once on the 2025 holdout: 255 games, with one tie excluded from the win Brier. The 2025 v1 Brier was 0.2288; the closing market Brier was 0.2137. V1 beat constant-probability references in that holdout but did not match the market. Its mean absolute margin error was 10.67 points versus 9.97 for the spread, and total error was 10.61 versus 10.17 for the closing total. The sample is one season and roughly 255 games, so differences are uncertain.

The separate Elo research report found Brier 0.2197 for v1+Elo versus 0.2229 for recalibrated v1 over 3,158 games from 2011–2023. The 2024 and 2025 point differences were also favorable to Elo in that report. This is retrospective evidence from a selected historical comparison, not prospective confirmation, and does not change the operational default by itself. The EPA challenger failed its adoption gate: on the 2025 holdout its Brier was 0.2291 versus 0.2288 for v1, with a paired interval spanning zero.

## Playoff odds

The separate team playoff-odds job fits regular-season offense and defense ratings, then simulates remaining games and applies NFL seeding and tiebreaking rules. It reports playoff, division, bye, seed, and wins probabilities. The current default score method is `placeholder-split-40` (`nfl-playoff-odds-v1.2`). A historical-score sampling option (`nfl-playoff-odds-v1.3`) passed most distribution checks but failed the pre-registered across-team scoring-spread gate, so it is not the default. Reported playoff and division probabilities were close between methods and within simulation noise; the season-scoring spread failure remains material.

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
