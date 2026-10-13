# RESULTS: benchmark ladder on identical games, 2010 to 2020 (2026-10-13)

Fills the two empty rungs of the ladder in
[STRATEGY-forecasting-north-star-2026-10-10.md](STRATEGY-forecasting-north-star-2026-10-10.md): home field only
and 538 Elo. Script: `backend/benchmark_ladder_2010_2020.py` (read-only, `mode=ro`). Definitions were written in
its docstring before the run. Run on the dev DB, 2026-10-13.

## Game set

Regular-season games 2010 to 2020, weeks 2 on, that `nfl_backtest.backtest_season` grades, kept only when every
rung has a probability and the game has a winner. n = 2,633. Ties are excluded for every rung. Postseason games
are not in the set. Every rung below is scored on exactly these games.

## Result (Brier, lower is better)

| Rung | Brier 2010 to 2020 | Note |
|---|---|---|
| Coin flip | 0.2500 | arithmetic |
| Home field only | 0.2467 | walk-forward home win rate with a Laplace prior, neutral sites 0.5; rate reached 0.571 |
| 538 Elo | 0.2193 | `elo_prob1`; 538 fit its constants on this history, so this is a flattering bar |
| Our v1 (frozen) | 0.2217 | |
| Closing market | 0.2104 | de-vigged moneyline |

Paired difference, v1 minus rung, 95% bootstrap interval (negative means v1 is better):

| Against | Difference | Interval |
|---|---|---|
| Coin flip | -0.0283 | [-0.0340, -0.0226] |
| Home field only | -0.0250 | [-0.0310, -0.0191] |
| 538 Elo | +0.0024 | [-0.0012, +0.0060] |
| Closing market | +0.0113 | [+0.0075, +0.0150] |

By season, v1 is better than 538 Elo in 4 of 11 seasons (2011, 2012, 2013, 2019).

## What it says

- Stage 1 of the north star is "beat home field and 538 Elo on identical games, across seasons, not in one."
  v1 clearly beats home field. It does **not** beat 538 Elo: the pooled difference is +0.0024 with an interval that
  includes zero, and the per-season count is 4 of 11. Stage 1 is not met.
- The market is still the ceiling. v1 trails it by 0.0113 on these games, interval entirely above zero.

## What this does not show

- Different game set from the earlier market baseline (3,909 games, 2010 to 2025, v1 0.2244, market 0.2105).
  Do not mix the two sets on one ladder; the swcrockett figure (their reported 2025 number, their set) stays
  separate context.
- The 538 rung is not an independent forecast of ours and was fit on this history. A tie or a gap to it says
  nothing about 2026.
- Nine games listed 538's two teams in the other order (neutral-site and relocated games); they were matched on
  the reversed pair with probability 1 minus `elo_prob1`: 2010_08_DEN_SF, 2010_14_NYG_MIN, 2011_07_CHI_TB,
  2012_08_NE_STL, 2013_04_PIT_MIN, 2013_08_SF_JAX, 2014_04_MIA_OAK, 2014_08_DET_ATL, 2014_10_DAL_JAX. A game with
  no Elo row either way would have failed the run; none did.
- The home-field rung is one definition (walk-forward rate, Laplace prior). A different prior moves it in the
  fourth decimal, not tested here.
