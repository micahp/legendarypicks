# Legendary Picks forecasting north star

Decision recorded 2026-10-10 from Micah's product discussion. This refines the consumer prediction vision in [the July modeling platform spec](SPEC-modeling-platform-2026-07-16.md). [Spec A](SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md) and [Spec B](SPEC-player-projections-availability-2026-10-09.md) are the immediate NFL implementation tracks.

## The product

Legendary Picks is a sports forecasting platform that connects player projections, game outcomes, and season odds, then grades every locked prediction against what happened. A fan should be able to see a projected score, understand which player and team assumptions produced it, compare each relevant market with a fair probability, and follow the resulting playoff or championship outlook.

The forecast is the product. Market disagreement is a useful signal when the data, price, and probability are trustworthy. Consistent betting profit is an additional result to demonstrate, not a premise for the company.

Published team and player data + availability + game context
→ shared player opportunities and team strengths
→ simulated player stat lines and two team scores
→ win, spread, total, team-total and player-prop probabilities
→ remaining-season simulations and publicly graded forecasts.

NFL is the first complete implementation. The same concepts should extend to other sports where source coverage and market definitions support them; they need not all expose identical markets.

## Why the projected score is the center

A predicted winner and a spread side answer different questions. In the Sam example Micah supplied, the projected score is Tampa Bay 23.9, Dallas 27.8: Dallas wins by 3.9 in the model. A cited sportsbook line of Dallas -9.5 would point to Tampa Bay against the spread. The 5.6-point gap is a difference in expected margins, not a probability or an expected return.

That example illustrates the presentation we want: projected score first, visible assumptions behind it, then the market comparison. It does not establish that the model has an edge. Micah's supplied notes also report a small early NFL ATS record alongside a much larger historical comparison in which Sam's model tracked closing lines. Those third-party figures and the game example were not independently checked for this decision memo; verify sources and dates before using them externally.

Two expected scores do not determine fair prices for all markets. The model needs a calibrated joint distribution of the teams' scores. Each simulated game must yield a winner, margin, total, and team scores; linked player outcomes should reflect the same plays, opportunities, and game script. First-half and other period markets require their own period behavior rather than a simple fraction of the full-game mean.

The game forecast should show, for each supported market: our fair probability, the available line and price with capture time and source, the implied probability after accounting for price, the estimated difference, and the sample or uncertainty behind it. A large point gap alone is not a bet recommendation. Missing or thin markets should remain unavailable.

## Model and data principles

- Use published schedules, scores, lines, team assignments, injuries, snaps, and player stats where available. Reconcile source and stored populations before fitting or publishing.
- Build team offense and defense separately, including passing and rushing efficiency, pace, pass rate, opponent strength, home field, and rest. Test added EPA, coaching/play-calling, pressure, and defensive availability against simpler baselines before promoting them.
- Project player opportunities within team volume. An injury reallocates opportunities; it cannot create production twice. A starting-quarterback change is the expected starter's effect relative to the QB production already in the team baseline, not subtraction of his full standalone value.
- Couple player and game forecasts through shared assumptions and simulation draws. Measure differences between player totals and team outcomes; reconcile the model rather than forcing a tidy but unsupported equality.
- Store versions and pre-kickoff snapshots for forecasts and market lines. Changes in starters or injury status create a new forecast with a new as-of time; they do not rewrite the earlier locked forecast used for grading.

The proposed NFL history target is 2010–2025 for model building and historical walk-forward tests, subject to checking each publisher's season, phase, field, and identity coverage. Older seasons may help with robustness if their definitions hold. Recent seasons should drive current team and player strength more than distant seasons. Any season used for model choice is disclosed as development data. For 2026, only forecasts actually locked before a game's kickoff count as prospective; earlier games reconstructed later remain retrospective.

## Public accountability

Publish score error, margin and total error, Brier/log loss and calibration for win and cover probabilities, market-specific calibration for totals and props, and results at recorded obtainable odds. Track closing-line value where a trustworthy time-stamped closing line exists. Show all games, pushes, losses, model versions, and the size of each edge bucket. Compare with simple score/Elo baselines, ESPN player projections where captured, and the market; do not claim market outperformance from a small run.

The user-facing game page starts with projected scores, spread and total, the market's view, and the main reasons for the difference. It should let a fan see how a starter being out changes other players, the score distribution, and the team's season odds. Playoff odds, weekly movers, and a permanent model record give people a reason to return and a way to judge the system.

## Near-term work and the company story

1. Finish the full [Spec A](SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md) track: trustworthy schedule/team inputs, a baseline score model, then the efficiency and availability-aware version, calibrated score distributions, market probabilities, playoff simulations, and public grading. Its current scores-only v1 is an interim benchmark, not the final game-forecast product.
2. Finish [Spec B](SPEC-player-projections-availability-2026-10-09.md): correct the availability/share/splits foundation, ship the with/without prop research feature, replace borrowed or Marcel-lite player projections with our own, handle injury scenarios, and grade them beside ESPN. The B1–B3 candidate has open review findings and remains off dev as of this note.
3. Join the tracks with shared game assumptions and a single auditable forecast run. Demonstrate that the player, game-market, and season outputs are coherent on real games before expanding the approach to another league.

Investor one-liner: **Legendary Picks connects what individual players are likely to do with game scores and season outcomes, and publishes the record of every forecast.**

The possible advantage is the integrated model, normalized cross-league identity and results data, an accumulating locked forecast record, and a consumer experience that explains changing probabilities. Public historical data alone is not a moat. The next proof is a reproducible NFL forecast and backtest, a live explanatory game page, and evidence that people use the forecasts repeatedly. Betting profitability, if demonstrated over a meaningful sample at obtainable prices, is an additional claim with its own evidence.
