# NHL and NBA prop source evidence, 2026-10-04

## Source checked

The local RotoWire relay archive
`backend/data/rotowire-archive/rotowire-2026-10-04.json.gz` is a real payload
fetched at 2026-10-04 00:06:50 America/Chicago. Its SHA-256 is
`1b409e9aedc3541c9abecb050c17b6dcb16d4851de0ec56f1c77a39eb052fe17`.
It contains 3,662 props, 46 events, 1,292 entities, and 87 markets.

A read-only request to `https://api.prizepicks.com/leagues` returned HTTP 403.
There is no current direct PrizePicks payload in `data/prizepicks_drop/`; its
README records 2026-08-25 as the last successful residential pull. Therefore
the current direct PrizePicks board cannot be inspected from this host.

## NHL game props found

RotoWire publishes all requested skater markets as `category: Game`. Counts are
publisher prop objects; one object may carry lines from several books.

| Market ID | Publisher market | Props | Books present | Example line |
|---:|---|---:|---|---|
| 80 | Goals | 36 | sleeper | Gabriel Vilardi 0.5 |
| 81 | Assists | 53 | underdog, prizepicks, sleeper, hardrock-sb | Clayton Keller 0.5 |
| 82 | Points | 52 | underdog, prizepicks, sleeper, hardrock-sb | Logan Cooley 0.5 |
| 83 | Shots on Goal | 50 | underdog, hardrock-sb, prizepicks, sleeper, fanduel-sb | Clayton Keller 2.5 |
| 87 | Hits | 6 | underdog, prizepicks | Andrew Copp 0.5 |
| 88 | Faceoffs Won | 6 | prizepicks | Mika Zibanejad 8.5 |
| 89 | Blocked Shots | 2 | underdog, prizepicks, sleeper | Jackson LaCombe 1.5 |
| 90 | Time on Ice | 10 | prizepicks | Josh Morrissey 24.5 |

The relay also has Power Play Points, which is outside the decided market set.
It has no NHL saves market. Existing Bovada saves remain necessary.

One real relay row is market 83 for Mikhail Sergachev, Utah at New York Rangers,
2026-10-04T22:00:00Z. It carries an Underdog 1.5 line and a Hard Rock 1.5 line.
The row includes RotoWire player identity, fixture identity, line, side prices,
and line timestamp.

## NBA evidence

The relay contains 94 NBA objects, but every one is a season market with no
current fixture: 37 Points AVG, 19 Rebounds AVG, 18 3PT Made AVG, 16 Assists AVG,
and 4 Triple-Doubles. All 94 lines are labeled PrizePicks. They are season
futures and cannot be represented truthfully as game props.

No NBA `category: Game` player props are present in the 2026-10-04 relay payload.
There is therefore no current NBA game line to ingest from the checked sources.
The game settlement vocabulary can still be prepared for points, rebounds,
assists, and made threes so it is ready when a fixture-backed publisher line
appears.
