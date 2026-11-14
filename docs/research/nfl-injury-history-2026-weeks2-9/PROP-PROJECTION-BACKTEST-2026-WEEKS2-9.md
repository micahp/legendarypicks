# NFL prop projection backtest, 2026 Weeks 2–9

## Scope

This replays the frozen Spec B v2 player projection engine in a walk-forward
evaluation over completed 2026 regular-season games in Weeks 2–9. Marcel-lite is
reported as the point-estimate benchmark. The forward Platt map is fit separately
for each target week, using only eligible sportsbook prop outcomes from earlier
weeks in 2026; a week without at least 200 earlier items stays uncalibrated.

The replay uses player-game logs only through the target game's week boundary.
Target-game injury and availability status is left empty, because there is no
verified pregame archive for each historical week. Model projections are
conditional on the target player having a recorded game log. Official GSIS
gamebooks are joined after the projection by game, team, and GSIS ID to verify
that graded players were listed active. Final roster status is not a feature or
input to the projections.

## Outputs

- `walk-forward-prop-projections.csv`: one row per eligible prop line and book,
  including the raw Spec B probability, forward-calibrated probability where a
  prior-week map exists, market probability, point projections, distribution
  quantiles, actual, and gamebook reference.
- `player-game-market-projections.csv`: deduplicated player-game-market point
  projections and errors, so alternate lines and books do not multiply MAE.
- `weekly-prop-projection-metrics.csv`: per-week sample counts, Brier scores,
  and point MAE.
- `prop-projection-backtest-summary.json`: run inputs, hashes, calibration maps,
  coverage, and limitations.
- `run_prop_projection_backtest.py`: reproducible read-only runner.

The forecast probabilities cover the model's existing receiving markets and
pregame-lead quarterback passing markets only. Rushing and joint-stat markets
do not receive probabilities unless the frozen model has a supported
distribution. The outcome set excludes inactive and did-not-play players, plus
players without a target-week game-log row; their props are not assumed to have
settled at zero. The roster CSV and this backtest therefore answer different
questions: the gamebooks establish final eligibility, while this score is
conditional on a stat-log participant. No claim of pregame forecast capture or
betting profitability follows from a retrospective reconstruction.

## Rebuild

Run from the repository root. The database is opened with SQLite `mode=ro`; the
script does not write projection, calibration, or grading rows to it.

```sh
python docs/research/nfl-injury-history-2026-weeks2-9/run_prop_projection_backtest.py \
  --db backend/data/picks.dev.db \
  --out-dir docs/research/nfl-injury-history-2026-weeks2-9
```
