# NHL game-line accuracy, independent of pick selection

This experimental extension to the NHL Model tab grades **every official, locked, completed game forecast**, including games where no sportsbook quote existed or no positive-EV bet qualified. It does not modify the frozen forecasts, recommendation decisions, historical backtests, or existing official results.

## Fixed reference benchmarks (always available)

For each frozen model, use the stored pregame probability and subsequent official result to calculate single-event Brier loss: `(p - y) ** 2`. The exported `line_grades.reference` includes:

- Home to cover -1.5
- Away to cover -1.5
- Over 5.5 statistical goals
- Over 6.5 statistical goals

The ±1.5 markets grade official final goal margins. The fixed totals grade regulation-plus-overtime statistical goals with the shootout-deciding goal excluded; that is the *research model target*, not necessarily the settlement basis of a sportsbook contract. Use all graded games regardless of whether a wager was selected. The UI displays separate sample sizes for each metric and each model.

## Frozen sportsbook comparisons (only when valid)

Where a frozen Bovada quote was captured at or before lock and meets the freshness threshold, grade the frozen home puck line and exact posted game total. Compare model Brier with the no-vig book probability on the **same** games. Never substitute a current quote for the price captured at lock.

The full-game total derives from the immutable 21 × 21 joint goal distribution. For NHL **regular season only**, surviving tied statistical scores correspond to shootouts and contribute a deciding goal to the official final total; the frozen statistical total forecasts continue to use their original target. There is no fabricated playoff shootout adjustment, so playoff market-total grading with this approach is unavailable. On whole-goal lines, pushes are recorded and excluded from binary Brier averages; decisive outcomes condition model probability on no push.

Market comparisons are absent if the frozen quote, applicable distribution, or usable market evidence is unavailable. This must not suppress the fixed reference scores. Differences across markets with unequal sample sizes are not an apples-to-apples model comparison; use matched games, per-market base rates, and uncertainty before promoting any claims.

The per-game grades are derived by `grade_game_lines()` in `backend/nhl_model_store.py`, versioned as `line-brier-v1` and exported under each locked model's `line_grades` field. The existing immutable grade and forecast tables are unchanged. The **Model accuracy** tooltip includes fixed-market and frozen-quote Brier summaries for all three NHL models, with game counts.

## Known limitations

- A low Brier score alone does not establish profitable betting or prove a model is better than a suitably calibrated market baseline.
- The live grade API recomputes versioned derived metrics from immutable snapshots; it does not yet persist a separate immutable line-grading table.
- Odds comparison is a *probability accuracy* comparison, not executable returns or ROI.
- The research score distribution is an independent Poisson approximation; market-specific overtime and shootout settlement mappings must be audited before interpreting live market comparisons.
