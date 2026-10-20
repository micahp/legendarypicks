# NHL: standings/points-only selective trading research (deferred)

**Goal:** Identify a *selective*, executable NHL trading rule that earns positive
risk-adjusted **net profit** over time. Do not require this predictor to beat
the closing sportsbook's Brier score on every game. Do not require a trade
in every game. Do not require v3 or v4 to be built first.

This is a distinct goal from the forecasts and their proper-score benchmarks.
There is no proven profitable standings strategy in the current research.

## Hypothesis

Pregame team points, points percentage, games played and their differences
may contain **conditional** signal that the market sometimes underweights or
overweights, or that predicts an intraday repricing even when the eventual
closing probability is a stronger average predictor.

This permits opportunities in a **subset of games, prices and decision times**,
even if the standalone points model has worse full-slate Brier. Conversely,
beating a market Brier does not itself guarantee tradable profit.

Use official standings available *as of trade time*, including source snapshot
timestamp and both teams' games played. Points% = points / (2 × GP).
Do not accidentally include the game's own result, future rest-of-season
standings, or post-entry prices in selection.

## Start with simple prespecified candidates

Test independent variants rather than blending everything in one result:

1. **Simple points-gap filter:** pregame points% differential and games-played
   minimum, home/away side, season stage and quoted price band. Thresholds
   are learned on training seasons only. A game produces either a single
   qualifying signal or **no trade**.
2. **Points-only fitted fair price:** a chronological, strongly regularized
   model with points%, points difference, games played and home indicator
   provides an estimated win probability. Market quotes are NOT needed to
   train that probability, but the observed executable price is required
   to evaluate whether to trade.
3. **Points-based relative-value or opening-to-closing hypothesis:**
   predeclare entry time and target (hold to settlement vs exit before
   start), test separately, with available orderbook snapshots and
   no hindsight-selected entry or exit.

Keep the first iteration points-only; any rest, xG, shots, goalies and
advanced inputs belong to separate comparison strategies.

## Entry, execution and costs

A pregame market snapshot must include both sides when possible, market,
best executable ask/bid, quoted available size/depth, captured timestamp,
game start, fees, tick size and settlement rules. Kalshi/exchange
contracts require venue-specific fees, spread and settlement logic.

For a binary YES contract held to outcome with entry cost `q` dollars
and fees `f` per unit, net outcome is approximately
`1 - q - f` on success and `-q - f` on failure (subject to contract
rules). Estimated expected profit is `p_true - q - E[fees]`;
a sell-before-start trade requires an actual achievable *bid* at exit
and *both* entry and exit costs. Marking profit at midpoint or at the
historical closing line is **not realized P&L**.

For sports betting instead of exchange trading, apply the offered
American odds, vig, push/void rules and stake-specific profit.
Do not mix sportsbook backtests and exchange mark-to-market returns.

The selection rule must account for price: a correct underdog pick can
be an unprofitable trade, and a low winning rate can be profitable
at sufficiently favorable odds.

## Historical tests and the benchmark distinction

Existing note: on 5,627 games overlapping SBR closing moneyline,
standings logistic reports Brier **0.2431** versus closing market
**0.2393**. This shows the closing market predicts winners better on
that matched sample on average. **It neither disproves nor establishes
positive returns for a conditional points-only strategy.**

Use SBR opens/closes only for **clearly labeled historical
price-sensitivity scenarios** (no intraday T-90 timestamp, no proof
of executable liquidity at the reference price). The archived
2007-08 to 2017-18 files may be incomplete two-sided markets;
2018-19 to 2022-23 are more suitable for matched benchmark checks
but still lack intraday executable quotes.

The **promotion gate** needs *prospective* recorded signals and orderbook
snapshots at the exact intended entry/exit time. Pre-register the
trade/no-trade rule and let no-signal days count as no trade.

## Evaluate the trading strategy, not just the prediction model

Primary scorecard:
- trades, trading days, eligible games, selection rate, stake/exposure,
  average entry ask and available size;
- realized **net P&L, ROI, return per dollar at risk**, fees, slippage,
  realized exit bid when relevant and settlement results;
- drawdown, bankroll/exposure concentration, maximum losing streak,
  adverse selection and per-season or rolling-quarter results;
- uncertainty from game/day-clustered resampling, and comparison with a
  simple passive-price strategy or no-trade baseline.

Secondary diagnostics: full-slate and **trade-subset** Brier/log loss,
calibration, opening-to-closing movement, CLV, hit rate, and which
points%/price bands contributed profit. None replaces net P&L.

No threshold search or model fitting on evaluation seasons. Use
expanding-window seasons or strictly ordered development and forward
holdouts; ensure one game's correlated sides/alternate prices don't
inflate sample size. Explicitly report missing quotes and unmatched games,
and exclude impossible/unfillable orders with consistent rules.

If real orderbooks are incomplete, report **NO VERIFIED PROFITABILITY
CONCLUSION**, not simulated fills at favorable historical prices.

## Decision gate

Do not promote simply because the fitted model improves Brier.
Promote a constrained, selective strategy only if prospective
net returns after *actual* transaction costs and fill limits are
positive with credible uncertainty and no single season/outlier
driving the result. Require enough trades to make estimates meaningful.
A profitable strategy can be sparse; zero trades on a slate is valid.

This independent experiment can proceed before NHL v3 or v4.
