# NHL standings/points-first matchup and model-pick trading strategy

**Status: a research hypothesis for later. It has not yet been demonstrated profitable.**
This is deliberately independent of NHL v3 (team/period + shot-adjusted goalie)
and v4 (full-game simulation). The purpose is to test whether a **standings-driven
matchup strategy using our existing NHL pick rules** produces a repeatable net
trading profit with some additional selectivity.

## What defines the strategy

**Standings and points are the primary signal and the first decision layer,
not a minor additional covariate or a filter on a separate model's picks.**

For *both teams*, use standings position/percentile, points, points
percentage (points divided by 2 × games played), games played, wins,
regulation losses, overtime losses, and season stage, all **as of before the
forecast/trade**. Examine each team's absolute strength **and** the relative
strength gap. Matchups with 14 vs 13 points and 4 vs 3 points are not
equivalent. Raw points without games played can mislead; do not replace
points with just the points difference either.

Matchups, retaining stronger side and home/away orientation:

- **Strong–weak (SW)**: comparatively dominant side versus comparatively
  poor side; also record whether the model's chosen side is strong or weak.
- **Strong–strong (SS)**: two high-standing teams, even if their points
  difference is small; strength of competition may affect call market.
- **Weak–weak (WW)**: two low-standing teams, even if their points
  difference is small; do not classify as SS merely because gap is tiny.
- **Middle or mixed**: separate controls to avoid artificially forcing
  all teams into strong/weak extremes.

**The matchup regime is established before using any model-generated call
or quote.** This is not primarily a price-mispricing detector or a
standings-based fair-price model. Prices are needed to compute profits;
they do not define whether the game is SW, SS or WW.

## Layer 1 — standings strength and matchup classification

1. Reconstruct pregame standings for both teams at the exact decision
   timestamp. Never use end-of-season standings, the game's own outcome,
   or the later of the two teams' games as a feature.
2. Define strong and weak using robust **absolute** points-percentage
   bands and/or league standing percentiles; record raw points and
   games-played levels, as well as pairwise differences. Pick candidate
   definitions using historical **training** seasons only, not
   hindsight-picked profitable thresholds.
3. Test early- vs late-season thresholds separately. A 6–0 team and a
   24–8 team shouldn't receive identical certainty; impose GP floors or
   shrink early-season standings, while preserving the observed points.
4. Save the full two-dimensional matchup state: (home points%,
   away points%, home points, away points, GP, ranks, strength bands,
   gap, favorite orientation), not merely a single difference number.
5. Publish each season's SW/SS/WW/Middle counts before evaluating picks.
   Document missed or ambiguous standings snapshots; do not silently
   assign missing teams to the weak category.

## Layer 2 — match the matchup regime to OUR model-pick hierarchy

Within **each** SW, SS, WW or Middle category, run exactly one named,
versioned NHL pick policy on the locked pregame forecast.

The original `docs/NHL-MODEL-PICK-LOGIC.md` policy says:
1. If the sportsbook underdog +1.5 is the model's spread-gap side and
   displayed rounded `S > 1.0`, call underdog **+1.5 cover**.
2. Otherwise, when the sportsbook favorite agrees with the model
   favorite, call the favorite **moneyline**.
3. Otherwise, call a **game total**: 5.5 at expected game totals
   ≤6.0, else 6.5; Over/Under determined by projected total.
4. Freeze every eligible **model call**, even where no bet is taken;
   grade Win/Loss/Push without hindsight.

Important: the S-gap trigger is a known uncalibrated heuristic. The
current production selector `ev-max-2-settlement` instead selects the
highest quoted EV candidate and is **not** that original hierarchy.
Never mix the two retrospectively. Research separate policy variants:
the original version, a strictly forward-calibrated tiered version,
and the existing EV-max rule as an **independently named control**.

**Do not hard-code that SW means strong-team ML, SS means +1.5 or WW
means Under.** Those are testable hypotheses, not observed profitable
rules. For every cell, record the actual **regime × model-call market
(ML / +1.5 / totals) × called side × strong/weak side × home/away**
and then discover which combinations have consistent net returns.

Standings classification can ultimately **inform which pick types the
strategy permits**, and how selective it is. Do not let a generic
"highest estimated value" recommendation erase the standings-based
structure. But don't promote a regime-specific adjustment without a
forward performance check.

## Stage A — first measure the full regime × call grid

Generate the model's call for every game even without prices, then
produce the following independent views:

| Matchup | Moneyline calls | +1.5 calls | Total calls |
| --- | --- | --- | --- |
| Strong–weak | Track strong/weak side, orientation | Track cover side vs strength | Track projected total and side |
| Strong–strong | Track model side and orientation | Track underdog identity and margin | Track Over/Under and line |
| Weak–weak | Track model side and orientation | Track underdog identity and margin | Track Over/Under and line |
| Middle/mixed | Control | Control | Control |

For every cell show **eligible games, calls, hit rate, pushes, valid
quotes, units staked, actual or explicitly simulated net units,
fees/returns, ROI, drawdown, year-by-year stability**. Report
unpriced-game coverage. A high hit rate alone is not profit, but the
closing market's overall Brier is not the primary target either.

Compare against simple rules that select favorite ML, underdog +1.5,
or totals within the same regime, using equivalent rules for timing
and available prices. Compare *policy with standings regimes* against
*identical pick policy without regimes* to isolate what the standings
classification actually adds.

## Stage B — add selectivity after measuring the unfiltered grid

Pre-specify only a small number of selective dimensions using
training seasons. Examples:
- more extreme or moderate standings-strength separation within SW;
- high-high vs modest-high teams in SS and low-low vs middling-low in WW;
- direction of call relative to higher-ranked team and to bookmaker
  favorite;
- minimum GP, league-relative strength threshold and home/away;
- limit to certain model-call types **conditional on matchup regime**.

Separately, test execution constraints such as acceptable quoted odds,
minimum liquidity, or maximum fees. These are downstream feasibility
conditions, not substitutes for the standings signal. **No trade** is a
valid output, even if a model call exists for every game.

Use expanding-window evaluation. Tune regime thresholds and selectivity
on prior seasons; preserve later seasons and prospective observations
untouched. Avoid selecting hundreds of cells then reporting only the
winners. Show all attempted variants and confidence intervals, including
game/day-clustered uncertainty.

## Net trading profit is the north star

A selective standings-based strategy could make money even if its
full-slate winner probabilities score worse than the bookmaker's
closing odds. It can also lose money despite a high hit rate.
The historical points% logistic Brier 0.2431 vs matched closing
market 0.2393 over 5,627 games is **not a verdict on this strategy**.

A return requires an actual selected side, stake, and price:
- Sportsbook moneylines, +1.5 and totals use captured offered odds
  and official Win/Loss/Push/void rules.
- Exchange positions held to settlement use executable ask and fees;
  entries/exits before settlement need the actually available
  executable bid/ask, time, liquidity, spread, fees, slippage and
  exposure. Do not treat midpoints or hindsight closes as fills.
- Historic SBR opening and closing prices can support explicitly
  *hypothetical* historical bets, not a verified T−90 or live-fill
  claim. Before 2018–19, two-sided price coverage is incomplete,
  and 2022–23 is partial.

Primary criteria: **out-of-sample net P&L, net ROI, units at risk,
selection rate, turnover, maximum drawdown and consistency by season
and matchup×market cell**, after trading costs. Brier, CLV and model
calibration can help explain performance but should never replace
measured trading returns.

Until forward quotes, strategy timestamps and actual fills are
available, label results historical price scenarios / prospective
paper trades, not realized profitable trading.

## Implementation boundary and next research output

No immediate model or betting changes. When picked up, first create
a pregame standings join and a **regime × original-pick-policy**
historical audit; compare with a policy-without-standings control.
Then test a small selective subset with prior-season training
and forward evaluation. Preserve immutable model ledgers and clearly
version the strategy separate from the model's forecast and
a sportsbook wager.

**The central question:** do strong–weak, strong–strong and weak–weak
games behave differently **under our actual model-pick rules**, and
can selecting among those regime-specific combinations yield
repeatable positive net returns?
