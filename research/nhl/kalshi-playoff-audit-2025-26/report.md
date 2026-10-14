# NHL 2025–26 Playoff Kalshi Market Reconciliation

Generated: 2026-10-14T05:16:17.842607+00:00

## Result

- NHL DuckDB playoff games: **82**.
- Kalshi archive pagination: **4 pages** with sizes **[1000, 1000, 1000, 76]**; all **3076** historical `KXNHLGAME` contracts were returned, all tickers were unique, and the cursor chain terminated.
- Postseason window: **80 events / 160 contracts**; all events have two distinct team-side contracts.
- Reconciliation: **80/82 games matched**; **2** games have no Kalshi event; duplicate or ambiguous matchups: **0**; unmatched Kalshi events: **0**.

## Missing game markets

- NHL game `2025030127`: 2026-05-03 MTL at TBL — no Kalshi event.
- NHL game `2025030217`: 2026-05-18 MTL at BUF — no Kalshi event.

## Pregame quote coverage

A quote is usable when a 1-minute candle has numeric YES bid and YES ask with `0 <= bid <= ask <= 1`. For each team-side contract, the audit selected the latest qualifying candle with `end_period_ts` **strictly before official NHL `startTimeUTC`**. It queried T−15 minutes through T−1 second; if needed, it would check back to T−6 hours and flag stale quotes. The fallback was not needed.

- Matched team-side contracts expected: **160**.
- Contracts with valid bid and ask: **160/160**; with a quote within 15 minutes: **160/160**.
- Against a two-outcome-per-game denominator, **160/164** possible playoff contracts have quotes; the remaining four sides belong to the two games with no Kalshi event.
- Matched games with both side quotes: **80/80**; both sides within 15 minutes: **80/80**.
- Spread available: **160/160**; median spread **1.0¢**.
- Quote age: median **60 seconds**, maximum **60 seconds**. Age counts (contracts): <=1m 160; <=5m 160; <=15m 160; >15m 0.
- Selected traded price present: **160/160**; candle volume present: **160/160**; open interest present: **160/160**.

## Data quality and safeguards

- Duplicate archive tickers: **0**; malformed events: **0**; duplicate/ambiguous matchups: **0**.
- Matched contracts without a valid quote: **0**; candle request failures: **0**; crossed/invalid spreads: **0**.
- Selected post-start candles: **0**. No other bookmaker was substituted. Settlement result metadata is retained only for provenance and excluded from features.
- Kalshi short team codes were normalized explicitly at the join boundary: `TB → TBL`, `LA → LAK`.
- The two unmatched games remain uncovered; their prices are not imputed.

This report establishes market coverage and quote availability; it does not train or evaluate a model. Any model-versus-market evaluation on this postseason must be labelled as the 80 matched games, unless the two absent Kalshi events are excluded with that limitation stated.

The separate [historical game identity and outcome audit](historical_data_integrity.md) records issues found in the NHL modeling DuckDB that must be resolved before backtesting.

## Artifacts

- `game_crosswalk.csv`: all 82 games, official puck-drop times, and match status.
- `pregame_quotes.csv`: selected quote per team-side contract, exchange timestamp, age, bid/ask/mid, spread, traded price, candle volume/open interest, and source request metadata.
- `kalshi_pregame_candles.jsonl`: raw 1-minute candle arrays and request metadata.
- `kalshi_market_metadata.jsonl`: source records for all matched contracts; includes settlement metadata for audit provenance only.
- `kalshi_archive_pagination.json`: page sizes, cursor completion, and archive cutoff response.
- `nhl_official_schedule.jsonl`: NHL gamecenter schedule fields and source URLs.
- `audit_summary.json`: machine-readable totals and quality flags.
- `run_audit.py`: read-only acquisition and reconciliation script.

## Sources and query contract

- Kalshi `GET /trade-api/v2/historical/cutoff`.
- Kalshi `GET /trade-api/v2/historical/markets?series_ticker=KXNHLGAME&limit=1000`, cursor-paginated until no cursor remained.
- Kalshi `GET /trade-api/v2/historical/markets/{ticker}/candlesticks` with `period_interval=1`, `start_ts=start−900` (or fallback `start−21600`), and `end_ts=start−1`.
- NHL `GET /v1/gamecenter/{game_id}/landing`; used `gameDate`, teams, venue, and `startTimeUTC` for schedule identity and pregame cutoff.
- NHL database opened read-only: `/root/nhl_database_2025-26-playoffs.duckdb`; 82-game population from `skaters_playoff_boxscores`, season key 2025.
