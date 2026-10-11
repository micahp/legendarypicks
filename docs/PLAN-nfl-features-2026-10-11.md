# Plan: NFL model features against the market, 2026-10-11

## The bar

Frozen v1 vs the de-vigged moneyline, 2010-2025: Brier 0.2244 vs 0.2105, gap +0.0138 (interval
+0.0107 to +0.0169). Margin MAE 10.642 vs the spread's 10.111. A feature is judged by how much of
that gap it closes. Matching the market means a gap whose interval includes zero.

Where the gap sits (v1 walk-forward, 2010-2023, games with a moneyline; scratch diagnosis, this
session): weeks 2-4 +0.0236, weeks 5-8 +0.0091, weeks 9-12 +0.0098, weeks 13-18 +0.0125. Early
weeks carry about twice the gap of the rest, so the preseason prior is the first lever; the late
gap says the prior alone cannot close it.

## Method (shared by every feature)

`backend/nfl_feature_backtest.py`, read-only on the dev DB.

- Base: frozen v1 walk-forward rows (half_life 6, cap 14, no points cap), 2010-2025.
- Stack: for target season S, an OLS of actual home margin on an intercept, the v1 projected margin
  and the feature columns, fitted on all graded games of seasons 2010 to S-1 only. Sigma is the sd
  of that fit's residuals. p = Phi(margin / sigma). The baseline B is the same stack with no feature
  columns, so recalibration alone is never credited to a feature.
- Graded seasons: 2011-2023 (development; 2010 is training only), 2024 (confirmation, nothing tuned
  on it), 2025 (second look only: it was v1's holdout).
- Decision: paired Brier (feature minus B) with a 5,000-resample bootstrap interval. A feature is
  kept only if the pooled 2011-2023 interval lies entirely below zero AND the 2024 and 2025 point
  differences are not above zero. Margin MAE (feature minus B) is reported the same way. Each
  feature's gap to the market (feature minus market) is reported with its interval.
- No new data was needed (see weather below), so nothing is ingested.

## Candidates, ordered by expected value per effort

| # | Feature | Data in the dev DB | What changes | Decides it |
|---|---|---|---|---|
| 1 | Preseason prior from the opening market | `nfl_schedule.spread_line`, all seasons, every REG game | stack column: a team rating fitted from closing spreads of weeks before the game (ridge toward zero). It is market-derived, so it measures how much of the gap is information we lack, not our own forecasting | Brier, MAE |
| 2 | Opponent-adjusted EPA by unit | `nfl_pbp` epa, posteam, defteam, pass/rush flags, 2010-2025 (about 44k plays a season with defteam) | already built as v2 (`nfl_epa_model`, pass and rush offense and defense, previous-season prior). Stack column: v2's raw EPA-points margin, frozen 12 / 450 | Brier, MAE |
| 3 | Rating uncertainty | the v1 rows themselves | sigma by week bucket (2-4, 5-8, 9+) from training residuals instead of one sigma. Changes probabilities only, so MAE is unchanged by construction | Brier |
| 4 | Special teams | `nfl_pbp` play_type kickoff, punt, field_goal, extra_point, all with epa | stack column: each team's recency-weighted net special-teams EPA per game from earlier weeks | Brier, MAE |
| 5 | Venue and conditions | `home_rest`, `away_rest`, `div_game` complete; `roof`, `wind`, `temp` complete for domes and closed roofs (null by design) and for outdoor games except 2021 (11), 2022 (91), 2023 (41) missing, the same gaps as nflverse's raw games file | stack columns: rest difference, and v1 margin times a high-wind flag (wind 15+ mph, recorded games only) | Brier, MAE |

Rating uncertainty in the season simulation (playoff odds) has no market to compare with: no
futures prices are stored. It is not tested here; the game-level sigma in row 3 is the part that
the bar can judge.

Dropped or deferred: none for missing data. Weather is partial (above) and is used only where it was
recorded; a game with no recorded wind gets no wind term, never a guessed value. QB availability
(`home_qb_id`) exists but is Spec B's availability layer, not part of this plan.
