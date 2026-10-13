# Legendary Picks forecasting north star

Decision recorded 2026-10-10 from Micah's product discussion; revised 2026-10-11 to set the bar as a
benchmark ladder rather than the market. This refines the consumer prediction vision in
[the July modeling platform spec](SPEC-modeling-platform-2026-07-16.md).
[Spec A](SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md) and
[Spec B](SPEC-player-projections-availability-2026-10-09.md) are the immediate NFL implementation tracks.

## The product

Legendary Picks is a sports forecasting platform that connects player projections, game outcomes, and
season odds, then grades every locked prediction against what happened. A fan should be able to see a
projected score, understand which player and team assumptions produced it, compare each relevant market
with a fair probability, and follow the resulting playoff or championship outlook.

The forecast is the product. Market disagreement is a useful signal when the data, price, and probability
are trustworthy. Consistent betting profit is an additional result to demonstrate, not a premise for the
company.

Published team and player data + availability + game context
→ shared player opportunities and team strengths
→ simulated player stat lines and two team scores
→ win, spread, total, team-total and player-prop probabilities
→ remaining-season simulations and publicly graded forecasts.

NFL is the first complete implementation. The same concepts should extend to other sports where source
coverage and market definitions support them; they need not all expose identical markets.

## The bar is a benchmark ladder, not the market

What we measured on 2026-10-11:

- The closing market is the ceiling. Frozen v1 loses to the de-vigged moneyline on Brier in 15 of 16
  seasons; pooled 2010 to 2025 over 3,909 games, v1 0.2244 vs market 0.2105
  ([market baseline](RESULTS-market-baseline-2010-2025-2026-10-11.md)).
- No model built on our own data beats the closing spread, total or moneyline, pooled 2011 to 2023 or in
  2024 ([backfill and features](RESULTS-nfl-backfill-features-2026-10-11.md),
  [points vs lines](RESULTS-nfl-points-vs-lines-2026-10-11.md)). The one input that helps, a
  market-implied prior, is built from the market's own spreads and so is not an independent forecast
  ([features vs market](RESULTS-nfl-features-vs-market-2026-10-11.md)).
- Sam's own site states that against closing lines on 1,171 games since 2022 his model tracks the market
  rather than beating it (as published; not yet captured or checked by us).

So the near-term question is not "do we beat the close" but "where do we sit among the public models
people already trust." Every rung below is compared on identical games, with the same metric and the same
tie and postseason handling. A number from a different game set is context, not a comparison.

| Rung | Brier | Source and status |
|---|---|---|
| Coin flip | 0.250 | Arithmetic |
| Home field only | to compute | Our harness |
| 538 Elo | to compute | `nfl_elo_538.elo_prob1`, 2010 to 2020 in our dev DB. Flattering bar: 538 fit its constants on this history and backfilled it with its later method. Our table has no QB-Elo columns. |
| swcrockett win-probability model | 0.2244 (2025), 0.2213 to 0.2233 (2020 to 2024 fold means), 0.2336 (2026 wk 1 to 4, 64 games) | Their reported numbers, their game sets, ties excluded ([repo](https://github.com/swcrockett/nfl-win-probability-model), commit `5d8d047`, MIT) |
| Our v1 | 0.2244 | Pooled 2010 to 2025, 3,909 games |
| Closing market | 0.2105 | Same 3,909 games |

A note on the swcrockett figures: numbers circulated in chat for this project (Elo 0.222, model 0.216,
Vegas 0.211, 3,816 games) are not what the repo reports. It publishes no standalone Elo, no market and no
ATS result; 0.2111 and 0.2168 are single-season 2024 results for two of its candidate models. Cite the
repo, not the chat. It does commit weekly per-game 2026 predictions keyed by nflverse `game_id`
(`outputs/predictions/2026_week_NN.csv`), which makes a prospective head-to-head possible; the commit time
of each file is the only evidence of when it was locked.

### Spread benchmark: Sam, prospective only

Sam's model is the against-the-spread benchmark. Its fitting equations are not published, so it cannot be
backtested; the only honest comparison is forward. Each week we record his projected scores and the line
he locked, with our capture time. He grades against the first line he saw, so we grade both models against
lines we captured at the same time, not against a later close. The bar is 52.4% at -110, reported by edge
bucket with pushes and every game shown. His published record is cited only with the date we checked it;
a record of a few dozen games is noise. (The notes Micah supplied put his NFL ATS record at 25-6-1 and his
college football record, from the same kind of model, at 59-53-2; neither checked by us yet.)

### Stages

1. Beat home field and 538 Elo on identical 2010 to 2020 games, across seasons, not in one.
2. Match swcrockett on identical games: 2026 prospectively from their committed weekly files; 2020 to 2025
   only by rerunning their MIT code, otherwise labeled as their reported numbers.
3. Hold our own against Sam ATS on 2026 lines we captured before kickoff.
4. Track the market throughout. Claim nothing against it from a small run.

## Why the projected score is the center

A predicted winner and a spread side answer different questions. In the Sam example Micah supplied, the
projected score is Tampa Bay 23.9, Dallas 27.8: Dallas wins by 3.9 in the model. A sportsbook line of
Dallas -9.5 points to Tampa Bay against the spread. The 5.6-point gap is a difference in expected margins,
not a probability or an expected return. The example illustrates the presentation we want (projected score
first, visible assumptions, then the market) and nothing about edge.

Two expected scores do not determine fair prices for all markets. The model needs a calibrated joint
distribution of the teams' scores. Each simulated game must yield a winner, margin, total, and team
scores; linked player outcomes should reflect the same plays, opportunities, and game script. First-half
and other period markets require their own period behavior rather than a fraction of the full-game mean.

The game forecast shows, for each supported market: our fair probability, the available line and price
with capture time and source, the implied probability after accounting for price, the estimated
difference, and the sample or uncertainty behind it. A large point gap alone is not a bet recommendation.
Missing or thin markets stay unavailable.

## Model and data principles

- Use published schedules, scores, lines, team assignments, injuries, snaps, and player stats where
  available. Reconcile source and stored populations before fitting or publishing.
- Build team offense and defense separately, including passing and rushing efficiency per play, pace,
  pass rate, opponent strength, home field, and rest. A new input is promoted only when it moves us up
  the ladder on identical games.
- Project player opportunities within team volume. An injury reallocates opportunities; it cannot create
  production twice. A starting-quarterback change is the expected starter's effect relative to the QB
  production already in the team baseline, not subtraction of his full standalone value.
- Couple player and game forecasts through shared assumptions and simulation draws. Measure differences
  between player totals and team outcomes; reconcile the model rather than forcing a tidy but unsupported
  equality.
- Store versions and pre-kickoff snapshots for forecasts and market lines. Changes in starters or injury
  status create a new forecast with a new as-of time; they do not rewrite the earlier locked forecast
  used for grading.

History: 2010 to 2025 is in the dev DB for model building and walk-forward tests. Recent seasons should
drive current strength more than distant ones; how much history helps is measured (a history-window
ablation on fixed test games), not assumed. Any season used for model choice is disclosed as development
data. For 2026, only forecasts locked before kickoff count as prospective.

## Public accountability

Publish score error, margin and total error, Brier/log loss and calibration for win and cover
probabilities, market-specific calibration for totals and props, and results at recorded obtainable odds.
Track closing-line value where a trustworthy time-stamped closing line exists. Show all games, pushes,
losses, model versions, and the size of each edge bucket. Show where we sit on the benchmark ladder on
identical games, beside Sam's ATS record on the same captured lines.

The user-facing game page starts with projected scores, spread and total, the market's view, and the main
reasons for the difference. It should let a fan see how a starter being out changes other players, the
score distribution, and the team's season odds. Playoff odds, weekly movers, and a permanent model record
give people a reason to return and a way to judge the system.

## Near-term work

1. Benchmark harness: home field, 538 Elo, v1 and market on identical 2010 to 2020 games, read-only on the
   dev DB.
2. Recurring line capture (approved 2026-10-11), so 2026 is graded against lines captured before kickoff.
3. Sam board recorder (approved 2026-10-11): projected scores and locked line per game, with capture time.
4. swcrockett weekly import: their per-game 2026 predictions beside ours.
5. History-window ablation on fixed test games.
6. Model inputs research: untested levers and matchup stats
   ([research agenda](RESEARCH-nfl-model-inputs-2026-10-11.md)).
7. Then [Spec A](SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md) and
   [Spec B](SPEC-player-projections-availability-2026-10-09.md) continue, each change graded against the
   ladder before it ships. The scores-only v1 is the interim rung, not the game-forecast product.

Investor one-liner: **Legendary Picks connects what individual players are likely to do with game scores
and season outcomes, and publishes the record of every forecast.**

The possible advantage is the integrated model, normalized cross-league identity and results data, an
accumulating locked forecast record, and a consumer experience that explains changing probabilities.
Public historical data alone is not a moat. The next proof is a reproducible NFL forecast placed honestly
on the benchmark ladder, a live explanatory game page, and evidence that people use the forecasts
repeatedly. Betting profitability, if demonstrated over a meaningful sample at obtainable prices, is an
additional claim with its own evidence.
