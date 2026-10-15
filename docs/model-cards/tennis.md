# Tennis model card

**Scope:** Daily ATP and WTA match projections (`tennis-global-surface-elo-blend-v1`). The version name describes the winner forecast; aces and total-games projections use separate methods described below.

**Human-readable description:** Daily tennis forecasts use a global and surface Elo blend for match winners, historical player averages shrunk toward the tour/format mean for aces, and a serve/return point model with a match simulator for total games on mapped surfaces.

## What it predicts

### Winner

The live winner forecast combines global Elo and surface-specific Elo probabilities in logit space. It uses historical results dated before the forecast day; same-day matches do not update one another. When the event surface is not mapped, the winner forecast falls back to global Elo. The stored `probability` is the probability assigned to the selected `projectedWinner`, not a home-team probability.

### Aces

Each player's projected aces use that player's historical average, shrunk toward the tour/format mean with a 10-match prior. The available grade table does not currently score aces projections.

### Total games

Where the event surface is mapped, a serve/return point model feeds an exact match-score simulator to produce expected total games and an interval. If the surface is not mapped, the live projection leaves total games unavailable. The product event surface map is explicit in `backend/tennis_daily_projections.py` and currently covers Shanghai and Wuhan as hard court.

## What Brier means for tennis

For a named binary event, Brier is the mean squared probability error:

`mean((p - y)^2)`

For tennis winner forecasts, the event must be stated as **which player wins the match**; the probability and binary outcome must refer to that same player on every row. This is not a Brier score for aces, total games, or a predicted scoreline. A lower score is better; 0 is perfect, and a 50% forecast scores 0.25 on every match.

### Live product grading

The live tennis grader currently records whether `projectedWinner` was correct and the absolute error in total games when both the forecast and final score are available. It does **not** calculate or store a live Brier score, does not store the live winner probability in its grade row, and does not grade aces. Therefore there is no production Brier number for `tennis-global-surface-elo-blend-v1` in this grader today. Winner hit rate alone does not measure probability calibration.

### Separate research backtest (not the live product Brier)

The frozen research report [Tennis match backtest (2026-10-14)](../TENNIS-MATCH-BACKTEST-2026-10-14.md) compares a point-model-plus-simulator forecast with a chronological Elo baseline on scored best-of-three matches from 2023–2026. Its Brier target is **match winner probability**, not aces or total games:

| Tour | Scored matches | Point model + simulator Brier | Elo Brier |
|---|---:|---:|---:|
| ATP | 11,777 | 0.23530 | 0.22802 |
| WTA | 13,066 | 0.22884 | 0.21596 |

This system is research-only and failed the pre-registered predictive-value gate against Elo on both tours. It is not the live product winner model, which uses a global/surface Elo blend. Do not cite these research Brier scores as live product performance.

## Intended use and limits

Treat winner probabilities and game/ace projections as uncertain estimates. Player identity must resolve through the tennis spine for a projection to be available. Surface-dependent totals can be unavailable for unmapped events. Current live grading is incomplete for probability quality because it stores winner correctness rather than the forecast probability and has no ace grade.

## Implementation references

- `backend/tennis_daily_projections.py` — live version, historical cutoff, winner probability, aces shrinkage, and total-games projection.
- `backend/grade_tennis_model.py` — live winner-correctness and total-games-error grader.
- `backend/tennis_match_backtest.py` — separate research comparison.
- `docs/TENNIS-MATCH-BACKTEST-2026-10-14.md` — research sample, Brier targets, results, and decision.
