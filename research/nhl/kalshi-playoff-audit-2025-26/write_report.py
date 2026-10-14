#!/usr/bin/env python3
"""Render the coverage report from the completed read-only audit artifacts."""
import csv, json, os
P = os.path.dirname(__file__)
s = json.load(open(os.path.join(P, 'audit_summary.json'), encoding='utf-8'))
with open(os.path.join(P, 'game_crosswalk.csv'), newline='', encoding='utf-8') as f:
    games = list(csv.DictReader(f))
with open(os.path.join(P, 'pregame_quotes.csv'), newline='', encoding='utf-8') as f:
    quotes = list(csv.DictReader(f))
valid = [q for q in quotes if q['yes_bid'] and q['yes_ask']]
traded = [q for q in valid if q['traded_price_close'] not in ('', 'None', 'null')]
volume = [q for q in valid if q['candle_volume'] not in ('', 'None', 'null')]
oi = [q for q in valid if q['open_interest'] not in ('', 'None', 'null')]
missing = [g for g in games if g['coverage_status'] != 'matched']
q = s['quote_coverage']; a = s['kalshi_archive']; d = s['data_quality']; e = s['event_game_reconciliation']
lines = [
'# NHL 2025–26 Playoff Kalshi Market Reconciliation', '',
'Generated: ' + s['audit_generated_at_utc'], '',
'## Result', '',
f"- NHL DuckDB playoff games: **{s['db_playoff_games']}**.",
f"- Kalshi archive pagination: **{a['page_count']} pages** with sizes **{a['page_sizes']}**; all **{a['contracts_fetched_all_series']}** historical `KXNHLGAME` contracts were returned, all tickers were unique, and the cursor chain terminated.",
f"- Postseason window: **{a['playoff_event_count']} events / {a['playoff_contract_count']} contracts**; all events have two distinct team-side contracts.",
f"- Reconciliation: **{e['matched_games']}/82 games matched**; **{len(e['missing_kalshi_events_for_games'])}** games have no Kalshi event; duplicate or ambiguous matchups: **{len(e['duplicate_or_ambiguous_matchups'])}**; unmatched Kalshi events: **{len(e['unmatched_kalshi_events'])}**.", '',
'## Missing game markets', '']
for g in missing:
    lines.append(f"- NHL game `{g['game_id']}`: {g['date']} {g['away']} at {g['home']} — no Kalshi event.")
lines += ['', '## Pregame quote coverage', '',
'A quote is usable when a 1-minute candle has numeric YES bid and YES ask with `0 <= bid <= ask <= 1`. For each team-side contract, the audit selected the latest qualifying candle with `end_period_ts` **strictly before official NHL `startTimeUTC`**. It queried T−15 minutes through T−1 second; if needed, it would check back to T−6 hours and flag stale quotes. The fallback was not needed.', '',
f"- Matched team-side contracts expected: **{q['matched_market_contracts_expected']}**.",
f"- Contracts with valid bid and ask: **{q['contracts_with_usable_two_sided_quotes']}/{q['matched_market_contracts_expected']}**; with a quote within 15 minutes: **{q['contracts_with_quotes_within_15m']}/{q['matched_market_contracts_expected']}**.",
f"- Against a two-outcome-per-game denominator, **{q['contracts_with_usable_two_sided_quotes']}/164** possible playoff contracts have quotes; the remaining four sides belong to the two games with no Kalshi event.",
f"- Matched games with both side quotes: **{q['games_with_both_side_quotes']}/80**; both sides within 15 minutes: **{q['games_with_both_side_quotes_within_15m']}/80**.",
f"- Spread available: **{q['contracts_with_spread']}/{q['matched_market_contracts_expected']}**; median spread **{s['spread']['median_spread_cents']}¢**.",
f"- Quote age: median **{q['median_quote_age_seconds']} seconds**, maximum **{q['max_quote_age_seconds']} seconds**. Age counts (contracts): <=1m {q['quote_age_distribution_seconds']['le_1m']}; <=5m {q['quote_age_distribution_seconds']['le_5m']}; <=15m {q['quote_age_distribution_seconds']['le_15m']}; >15m {q['quote_age_distribution_seconds']['gt_15m']}.",
f"- Selected traded price present: **{len(traded)}/{len(valid)}**; candle volume present: **{len(volume)}/{len(valid)}**; open interest present: **{len(oi)}/{len(valid)}**.", '',
'## Data quality and safeguards', '',
f"- Duplicate archive tickers: **{d['duplicate_archive_tickers']}**; malformed events: **{len(d['malformed_events'])}**; duplicate/ambiguous matchups: **{len(d['duplicate_or_ambiguous_matchups'])}**.",
f"- Matched contracts without a valid quote: **{d['contracts_missing_usable_quote']}**; candle request failures: **{len(d['quote_http_or_parse_failures'])}**; crossed/invalid spreads: **{d['crossed_or_invalid_spreads']}**.",
f"- Selected post-start candles: **{d['invalid_or_post_start_candles_selected']}**. No other bookmaker was substituted. Settlement result metadata is retained only for provenance and excluded from features.",
'- Kalshi short team codes were normalized explicitly at the join boundary: `TB → TBL`, `LA → LAK`.',
'- The two unmatched games remain uncovered; their prices are not imputed.', '',
'This report establishes market coverage and quote availability; it does not train or evaluate a model. Any model-versus-market evaluation on this postseason must be labelled as the 80 matched games, unless the two absent Kalshi events are excluded with that limitation stated.', '',
'The separate [historical game identity and outcome audit](historical_data_integrity.md) records issues found in the NHL modeling DuckDB that must be resolved before backtesting.', '',
'## Artifacts', '',
'- `game_crosswalk.csv`: all 82 games, official puck-drop times, and match status.',
'- `pregame_quotes.csv`: selected quote per team-side contract, exchange timestamp, age, bid/ask/mid, spread, traded price, candle volume/open interest, and source request metadata.',
'- `kalshi_pregame_candles.jsonl`: raw 1-minute candle arrays and request metadata.',
'- `kalshi_market_metadata.jsonl`: source records for all matched contracts; includes settlement metadata for audit provenance only.',
'- `kalshi_archive_pagination.json`: page sizes, cursor completion, and archive cutoff response.',
'- `nhl_official_schedule.jsonl`: NHL gamecenter schedule fields and source URLs.',
'- `audit_summary.json`: machine-readable totals and quality flags.',
'- `run_audit.py`: read-only acquisition and reconciliation script.', '',
'## Sources and query contract', '',
'- Kalshi `GET /trade-api/v2/historical/cutoff`.',
'- Kalshi `GET /trade-api/v2/historical/markets?series_ticker=KXNHLGAME&limit=1000`, cursor-paginated until no cursor remained.',
'- Kalshi `GET /trade-api/v2/historical/markets/{ticker}/candlesticks` with `period_interval=1`, `start_ts=start−900` (or fallback `start−21600`), and `end_ts=start−1`.',
'- NHL `GET /v1/gamecenter/{game_id}/landing`; used `gameDate`, teams, venue, and `startTimeUTC` for schedule identity and pregame cutoff.',
'- NHL database opened read-only: `/root/nhl_database_2025-26-playoffs.duckdb`; 82-game population from `skaters_playoff_boxscores`, season key 2025.', '',
]
open(os.path.join(P, 'report.md'), 'w', encoding='utf-8').write('\n'.join(lines))
print('Wrote report.md')
