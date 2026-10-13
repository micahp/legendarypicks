# The product is the joined tape

Written 2026-10-05, from Micah's step back after six trading competitions. Companion to
`docs/VALUE-PROP-simulating-plays-2026-10-04.md` (the second value prop).

## The decision

The AI traders are not getting better. Six competitions in (09-07 to 10-04), every model loses
most days, and they repeat reasoning their own reflections rejected the night before. Tuning
them is not where the time goes.

What the competitions did prove is the data and the grading. Every one of them found a
measurement error before it found anything about the traders (`/root/prediction-market-trading/
docs/LEARNINGS-competitions.md`). Getting that right is the hard part, and it is what we have.

**The product is the joined tape: every market price, timestamped, joined to what happened at
that moment, graded honestly.** The arena keeps running on autopilot as the demo, the data
collector and the daily content.

## Why prices alone are not the product

Someone already gives away historical bar charts for every Polymarket market. Prices are a
commodity. A backtest needs more than the price:

- **What happened.** The point, the play, the score change, the injury, the lineup.
- **What else the market knew.** The pregame line, the sportsbook props, the player's form.
- **An honest fill.** The quote that existed at that instant, net of fees, not a backdated or
  free fill. Our first scorer handed out free maker fills and crowned the wrong winner.

That join is slow to build: it takes recorders running every day, publishers matched by
identity rather than by name, and a grader proven against the tape. A competitor can download
prices in an afternoon. They cannot download two months of joined, verified history.

## What we already have (2026-10-05)

| layer | what | coverage |
| --- | --- | --- |
| order book | Kalshi tennis, every 3 s | June 3 to Sept 8, 2,204 match-winner events (`_tennis_compact.tsv`, 2.5 GB) |
| order book | Kalshi all sports, every 3 s on recorded games | Sept 15 on (`BROADTAPE_shared_*`, about 17 GB) |
| order book | MLB | `_mlb_compact.tsv`, 1.3 GB |
| quotes | every market on the daily board, 20 s, plus NFL props (10 series) | Oct 3 on |
| points | tennis point by point | US Open (416 matches), Kalshi's own feed from Oct 3 |
| plays | Kalshi team-sport plays, bound to the market | from Oct 5 (`kalshi_live_games.py`) |
| plays | ESPN play-by-play | MLB 5,530 game files, WNBA 228, NHL 110, NFL 78, NBA 69 |
| props | sportsbook player props, line and odds by book, opening and consensus | LP: about 12 sources per NFL game |
| results | prop outcomes and settlement from stored box scores | LP `prop_results`, DB-only settlement |
| form | every match at every level, with opponent rank | Tennis Abstract, cached daily |
| commentary | broadcast audio transcribed, tagged to the game | RedZone, NBC, FS1, Tennis Channel 2 |
| decisions | every AI and human trade with its stated reason and its graded result | six competitions |

## What makes it worth paying for

1. **Alignment.** Each price row can be joined to the event that moved it, on one clock. The
   10-04 audit showed how much this matters: runner and grader read opposite sides of the same
   timestamp and moved fills by up to 23c.
2. **Honesty.** The grader is proven: fills at the quote that existed, fees measured, partial
   exits graded partially, gaps treated as unknown rather than as the old price.
3. **Resolution.** Micah's insight: a price moves as a shape (area under the curve, slope,
   turning point) at every resolution: point, game, set, match, tournament. Only a joined tape
   can show those shapes at every resolution at once, and turning points are where prices
   reprice.
4. **Breadth.** The same structure across tennis, MLB, NFL, NCAAF, NHL, NBA, WNBA and UFC, so
   one backtest runs everywhere.

## Who would use it

- People backtesting on Kalshi and Polymarket who have prices and nothing to join them to.
- Sharp bettors who want props history with outcomes, by book.
- Builders of AI trading agents: the arena is a ready benchmark with an honest grader.
- Researchers on in-play markets (how fast prices absorb a break, a touchdown, an injury).

## Forms it could take

1. Daily files per sport: price rows, events and outcomes, already joined.
2. An API for the same, by game and by time window.
3. The arena as a public benchmark: submit an agent, get graded on the same tape.

## Gaps to close first

- **Hygiene.** The tape repeats the previous row 78% of the time in the old tennis file and 20 to
  53% since: change-only rows with a liveness sidecar (`/root/prediction-market-trading/docs/
  TASK-tape-change-only.md`). Point feeds repeat rows and have gaps.
- **Soccer.** No order book recorded at all.
- **Proof of the shape.** The coil and explosion test (`TASK-shape-coil-test.md`) came back with
  look-ahead bias; it needs a real-time redo before any claim.
- **Kalshi plays vs price.** Whether Kalshi's play feed leads ESPN or the price is not measured
  yet (`measure_kalshi_live.py`, after the first live window).
- **NBA and NHL props.** Settlement and props coverage are behind NFL and MLB.

## What this changes about where time goes

- Arena: keep it running, fix only what breaks the grading. No more prompt tuning.
- Data: hygiene first (duplicate rows), then coverage (NBA and NHL props, soccer), then the
  joins (plays bound to markets, points bound to prices).
- Content: the daily learnings posts are the marketing, and every post is evidence for the data.
