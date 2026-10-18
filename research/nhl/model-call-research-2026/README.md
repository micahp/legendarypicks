# NHL model-call research prototype, 2026

Prototype-only research. This directory does not modify the frozen prospective
models (`research/nhl/prospective-2026-27/`), the locked ledgers, the grading
provenance, or any production code. Nothing here is a statistical model
replacement; it is evidence for the tiered model-call policy decision.

## What it does

`run_backtest.py` performs a chronological walk-forward evaluation:

1. **Faithful model replay.** B5 xG Poisson and B7 Elo+xG Poisson are refit per
   evaluation season on all prior seasons only (alpha 0.01, the frozen value;
   identical feature construction to `run_pipeline.py`). B3 Elo is replayed
   chronologically (k=10, home ice 35, batch update by date) recording pregame
   ratings. Tie mass is resolved with the training-window home shootout rate.
2. **Analytical score distributions.** Independent Poisson joint matrices
   (21x21) produce ML, ±1.5 cover, totals at 5.5/6.5 and whole lines, goal MAE,
   and score log-likelihood. Settlement mapping: official total = statistical
   total + 1{statistical tie} in the regular season; identical in the playoffs;
   puck line ±1.5 is invariant under both targets.
3. **Monte Carlo control.** Draws from the *same* Poisson model verify the
   analytical engine; sampling error is quantified at 10k/25k/50k/100k/200k
   trials. This is a control, not a competing model.
4. **Simulation candidates.** (a) Gamma-Poisson (negative binomial) marginals
   with dispersion fit on training residuals; (b) Dixon-Coles-style low-score
   adjustment with rho fit on training likelihood; (c) common-shock bivariate
   Poisson when training covariance is positive; (d) period-level simulator
   with score-state rate effects and an explicit OT/SO stage.
5. **Tiered policy backtest.** The cascade ML → puck-line cover → total →
   fallback is evaluated per season with thresholds tuned only on prior seasons
   (expanding window, fit/tune/evaluation separation). All games are graded,
   not just selected calls. Baselines: always-ML, argmax-probability, and the
   model-only variant of the goal-diff-1 card rule.

## Inputs (read-only)

- `../kalshi-playoff-audit-2025-26/canonical_games_v1_7cd2fc9a6e84470c.csv`
- `../kalshi-playoff-audit-2025-26/pregame_rolling_features_v1_62dcceb77085bc59.csv`

No market prices enter any statistical feature. Historical sportsbook odds are
not present in this checkout, so betting ROI is evaluated only on the
prospective 2026-27 window (see the report).

## Outputs

`results/` JSON artifacts: per-season metric tables, MC convergence, threshold
tuning traces, dispersion diagnostics. The research report in `docs/` cites
these numbers; re-run to reproduce.
