# SPEC — "Cheap Quality, Live" widget (the trading strategy as a surface)

**Date:** 2026-07-04. **Where:** top of the scores page, in/above the existing `LiveNow` rail
(`pages/scores.tsx:24` — slot verified). **Focus per Micah: this is THE build. Not game-line
screeners, not prop history (blocked on the prop-loop repair anyway,
`SPEC-prop-loop-mlb.md`).**

## The idea in one line
Surface, in real time, the exact setups the prediction-market trading strategy buys: **a
quality team going down early (reversible dip = discount), or a close game entering its
witching hour** — "cheap quality picks, live." These windows don't last long; the widget's
whole value is showing them while they're open.

This is the BUY-ONLY value-discount doctrine made visible: fade overreactions on quality,
never chase, skip value traps (cheap-but-correct). Same primitive as PHILOSOPHY.md — the
moment that matters, while it's still happening.

## Why this is buildable TODAY (all verified 2026-07-04)
- **Quality prior:** `/api/{league}/strength` + `/strength/{team}` exist
  (`backend/routers/games.py:128,170`) — the v3 selection edge.
- **Live prices:** Kalshi public API, no auth — `KXMLBGAME` series confirmed live via curl
  (per-team Winner markets, yes_bid/yes_ask, ticker encodes date+teams). Existing client
  `backend/routers/esports/kalshi.py` already wraps this host; extend, don't rewrite.
- **Live game state:** the scores page already renders live MLB games from the ESPN backend
  (score, inning). No new ingest.
- **No prop history required.** This runs entirely on data LP has now.

## Signal classes (v0, MLB — it's July, games every day)

**A. QUALITY DIP ("discount")** — all three required:
1. *Quality:* pregame favorite by model (strength prior) AND pregame Kalshi price ≥ ~55¢.
2. *Dip:* live price meaningfully below pregame (v0 threshold: −15¢ or more).
3. *Reversible:* deficit small relative to time left (v0 heuristic: trailing by ≤3 runs
   before the 7th; tighten with a win-expectancy table later). This is the value-trap guard —
   down 6 in the 8th is CORRECT pricing, not a discount. Never show cheap-and-correct.

**B. WITCHING HOUR** — close game, late: score within 1–2 runs from the 7th on (or extras).
High-leverage window where every event swings the price; valuable to watch AND to trade.

**Knife indicator (port of the Jun-8 entry-timing finding):** each card shows whether the
price is *still falling* vs *stabilizing* (last 3 snapshots monotonic-down or not). We know
90% of naive entries catch the knife mid-fall — the widget should show the difference, not
repeat the mistake.

## The card
Team + opponent, live score/inning, **pregame → now price** (number + tiny sparkline from
our own snapshots), model prior %, badge (`DISCOUNT` / `WITCHING HOUR`), knife state
(`falling` / `stabilizing`), freshness timestamp. Click → game detail page. Cards appear and
expire on their own; an empty state is honest ("no live discounts right now — next games
7:05 pm").

## Mechanics
- Backend: `/api/live/discounts` — polls Kalshi markets for today's games (30–60s cadence,
  cached server-side; one poller, not per-visitor), joins to live ESPN state + strength
  prior, evaluates A/B, keeps an in-memory price history per market for sparkline + knife.
- Price snapshots appended to a small table (reuse the `prop_odds_snapshots` pattern) — this
  becomes backtest fodder: every surfaced discount is a logged, timestamped, checkable call.
  **The widget generates receipts** — the geoppls distribution asset — automatically.
- Frontend: widget component above `LiveNow` in `scores.tsx`. The scores page stops being
  "matches you can't even watch" (Micah's gripe) — the widget is the reason to be there even
  with no stream; stream/audio links stay secondary anchors where they exist.
- Later rungs (not v0): Telegram alert via Hermes when a card fires (the witching-hour
  notification rung already planned), esports adapter (Bovada live odds where Kalshi is
  thin), NBA/NFL in season, Kalshi builder-code link-out on each card (volume-based revenue
  rail, zero payment infra).

## Explicitly NOT in this build
- Auto-trading or bet placement. Surface + receipts only.
- Prop-based signals (blocked on the prop-loop repair; when clean they slot into the same
  widget as a third class: "about to hit").
- Uncalibrated win-probability displays (standing rule: don't show fake precision — we show
  model prior vs market price, both of which are real).

## Backlogged (Micah, 2026-07-04 — park, don't build now)
**"Game Edges" tab on `/props`:** pregame game-winner edges — model strength vs de-vigged
market price, plus expected point/run differential as the display metric. Feels "less pure"
than props/live (his read); revisit after the live widget ships and the prop loop is clean.

## Evolution (keep — the lessons are the spec)

**v0 (Jul 4, `c4ca767`) — shipped, and its first live card was a value trap.** WITCHING_HOUR
fired on SD @ LAD "0–2 in the 8th" (run-diff rule) anchoring the cheapest side: SD at 3¢ —
while our own game story read "Padres stumble in on a seven-game losing streak" vs Dodgers
"winners of eight of their last ten." Cheap-AND-correct, surfaced as if it were a pick.
Receipt resolved: SD lost. Two failures: run diff is not closeness (the market's 3¢/97¢ was),
and form was displayed but never used.

**v0.1 (Jul 5) — gates.** (1) Witching hour requires the anchored side inside the
market-contested band (25–75¢) and not cold; (2) cold gate everywhere: last-10 wins ≤ 3 or
losing streak ≥ 4 disqualifies a team from ANY card class — quality includes current form.

**v0.2 (Jul 5) — the no-knife-catching rule (Micah).** A quality dip with no live evidence of
the turn is a knife, not a discount — "are we just yoloing, praying they get one?" DISCOUNT
now additionally requires **rally evidence** from the live base/out situation (ESPN scoreboard
`situation`, same cached call): the trailing quality team must be *at bat right now with
runners on and outs to work with*. The card states it ("2 on, 1 out, at bat"). No evidence,
no card. We buy the visible turn, never the fall — same doctrine as the Jun-8 trading
entry-timing finding. Other leagues define their own evidence when they activate (NFL:
possession / red zone).

**v0.3 (Jul 5) — edge, not price level (Micah).** The v0.1 contested-price band (25–75¢) was
wrong doctrine: "a quality team's price dropping IS a signal — just not by itself. If they
have a 50% chance of coming back at 3 cents to make 100, you take that every time." The
missing input was the comeback probability, and ESPN publishes one live (`winprobability`,
summary endpoint). Witching hour now anchors on the side where **live Kalshi price sits under
ESPN's live WP** — edge ≥ 5 points, or ≥ 1.75× ratio for sub-10¢ prices; no WP available → no
value claim → no card. DISCOUNT suppresses when WP says the market is already fair. Cards show
"live WP N%" next to the price. Backtested against the trap: SD at 3.5¢ vs ~5% WP = no edge,
correctly dead; a 3¢/10% case correctly fires; a fair 45¢/47% coin flip stays silent.

## Acceptance
1. During any live MLB slate, the widget shows only games meeting A or B, each with a live
   Kalshi price ≤60s stale, and never shows a cheap-but-correct trap (spot-check vs win
   expectancy).
2. Every surfaced card is logged with its full lifecycle (fire → resolution) so we can
   report the widget's own record in R terms — the widget must be able to prove itself.
3. Scores page renders it above the fold with zero regression to existing LiveNow/cards.
