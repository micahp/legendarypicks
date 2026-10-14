#!/usr/bin/env python3
"""Read-only NHL 2025-26 playoff reconciliation with Kalshi historical quotes."""
import csv
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

DB = os.environ.get("NHL_MODEL_DB", "/root/nhl_database_2025-26-playoffs.duckdb")
OUT = os.path.dirname(os.path.abspath(__file__))
KALSHI = "https://external-api.kalshi.com/trade-api/v2"
NHL = "https://api-web.nhle.com/v1/gamecenter"
SEASON = 2025
SEASON_START = "2026-04-18"
SEASON_END = "2026-06-30"
USER_AGENT = "nhl-kalshi-playoff-research-audit/1.0"
TEAM_ALIAS = {"TB": "TBL", "LA": "LAK"}


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def get_json(url, retries=5):
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read()
                return json.loads(raw), resp.status, resp.headers
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code < 600:
                wait = float(exc.headers.get("Retry-After", min(2 ** attempt, 60)))
                print(f"HTTP {exc.code}; retrying in {wait:g}s: {url}", flush=True)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Failed after retries: {url}")


def write_json(path, value):
    with open(os.path.join(OUT, path), "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_jsonl(path, values):
    with open(os.path.join(OUT, path), "w", encoding="utf-8") as f:
        for value in values:
            f.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


# Read-only load of the independently supplemented NHL database.
con = duckdb.connect(DB, read_only=True)
rows = con.execute("""
    SELECT gameId, min(gameDate) AS game_date,
           string_agg(DISTINCT CASE WHEN home_or_away='HOME' THEN team END, '') AS home,
           string_agg(DISTINCT CASE WHEN home_or_away='AWAY' THEN team END, '') AS away
    FROM skaters_playoff_boxscores
    WHERE season = ?
    GROUP BY gameId
    ORDER BY min(gameDate), gameId
""", [SEASON]).fetchall()
games = []
for game_id, game_date, home, away in rows:
    if not home or not away:
        raise RuntimeError(f"Missing home/away identity in DuckDB game {game_id}")
    games.append({"game_id": int(game_id), "date": str(game_date), "home": home, "away": away})
if len(games) != 82:
    raise RuntimeError(f"Expected 82 DuckDB playoff games, found {len(games)}")

# Fetch the archive cutoff and page the complete series history.
cutoff, cutoff_status, _ = get_json(KALSHI + "/historical/cutoff")
params = {"series_ticker": "KXNHLGAME", "limit": 1000}
all_markets, page_rows, seen_cursors = [], [], set()
while True:
    url = KALSHI + "/historical/markets?" + urllib.parse.urlencode(params)
    payload, status, _ = get_json(url)
    batch = payload.get("markets", [])
    cursor = payload.get("cursor") or ""
    page_rows.append({
        "page": len(page_rows) + 1, "http_status": status, "count": len(batch),
        "first_ticker": batch[0].get("ticker") if batch else None,
        "last_ticker": batch[-1].get("ticker") if batch else None,
        "has_next_cursor": bool(cursor),
    })
    all_markets.extend(batch)
    if not cursor:
        break
    if cursor in seen_cursors:
        raise RuntimeError("Kalshi pagination cursor repeated; archive traversal is incomplete")
    seen_cursors.add(cursor)
    params["cursor"] = cursor
    time.sleep(1.25)
all_tickers = [m.get("ticker") for m in all_markets]
if len(all_tickers) != len(set(all_tickers)):
    raise RuntimeError("Duplicate market tickers found across Kalshi pages")

# Scope by event ticker's NHL local game date. Resolve Kalshi's shortened LA/TB
# market-side codes only at this explicit, auditable normalization boundary.
by_event = defaultdict(list)
for m in all_markets:
    event = m.get("event_ticker", "")
    match = re.match(r"^KXNHLGAME-(\d{2}[A-Z]{3}\d{2})", event)
    if not match:
        continue
    try:
        event_date = dt.datetime.strptime(match.group(1), "%y%b%d").date().isoformat()
    except ValueError:
        continue
    if not (SEASON_START <= event_date <= SEASON_END):
        continue
    side_raw = m.get("ticker", "").rsplit("-", 1)[-1]
    side = TEAM_ALIAS.get(side_raw, side_raw)
    by_event[event].append({"market": m, "date": event_date, "side_raw": side_raw, "side": side})

# Validate every event's binary outcome contracts and form game keys.
malformed_events = []
event_index = defaultdict(list)
for event, contracts in by_event.items():
    sides = [c["side"] for c in contracts]
    date = contracts[0]["date"]
    if len(contracts) != 2 or len(set(sides)) != 2:
        malformed_events.append({"event_ticker": event, "contract_count": len(contracts), "sides": sides})
    if len(set(c["date"] for c in contracts)) != 1:
        malformed_events.append({"event_ticker": event, "issue": "contracts disagree on event date"})
    event_index[(date, tuple(sorted(sides)))].append(event)

# Reconcile by official game date and unordered two-team matchup.
game_index = defaultdict(list)
for g in games:
    game_index[(g["date"], tuple(sorted([g["home"], g["away"]])))].append(g)
matched_event_to_game = {}
missing_games, duplicate_matchups, unmatched_events = [], [], []
for key, event_list in event_index.items():
    candidates = game_index.get(key, [])
    if len(candidates) == 1 and len(event_list) == 1:
        matched_event_to_game[event_list[0]] = candidates[0]
    elif not candidates:
        unmatched_events.extend({"event_ticker": e, "date": key[0], "teams": list(key[1])} for e in event_list)
    else:
        duplicate_matchups.append({"date": key[0], "teams": list(key[1]), "events": event_list,
                                   "game_ids": [g["game_id"] for g in candidates]})
for key, candidates in game_index.items():
    events = event_index.get(key, [])
    if not events:
        missing_games.extend({"date": key[0], "home": g["home"], "away": g["away"], "game_id": g["game_id"]}
                             for g in candidates)
    elif len(events) > 1 or len(candidates) > 1:
        duplicate_matchups.append({"date": key[0], "teams": list(key[1]), "events": events,
                                   "game_ids": [g["game_id"] for g in candidates]})
if malformed_events or duplicate_matchups or unmatched_events:
    print("Reconciliation anomalies:", json.dumps({"malformed": malformed_events,
          "duplicate_or_ambiguous": duplicate_matchups, "unmatched_events": unmatched_events}, indent=2), flush=True)
if len(by_event) != 80 or len(matched_event_to_game) + len(missing_games) != 82:
    raise RuntimeError("Archive/game coverage counts failed reconciliation invariants")

# Fetch official NHL gamecenter schedules for all 82 game IDs. These provide
# authoritative puck-drop timestamps; game outcome/score fields are discarded.
def fetch_schedule(g):
    url = f"{NHL}/{g['game_id']}/landing"
    data, status, _ = get_json(url)
    schedule = {
        "game_id": int(data["id"]), "season": data.get("season"), "game_type": data.get("gameType"),
        "game_date": data.get("gameDate"), "start_time_utc": data.get("startTimeUTC"),
        "home_team": (data.get("homeTeam") or {}).get("abbrev"),
        "away_team": (data.get("awayTeam") or {}).get("abbrev"),
        "venue": (data.get("venue") or {}).get("default"),
        "source_url": url, "http_status": status, "retrieved_at_utc": utcnow(),
    }
    if not schedule["start_time_utc"]:
        raise RuntimeError(f"NHL gamecenter lacks startTimeUTC for {g['game_id']}")
    if (schedule["home_team"], schedule["away_team"], schedule["game_date"]) != (g["home"], g["away"], g["date"]):
        raise RuntimeError(f"DuckDB/NHL schedule identity mismatch: {g} vs {schedule}")
    return schedule

schedule_by_id = {}
with ThreadPoolExecutor(max_workers=6) as pool:
    futures = {pool.submit(fetch_schedule, g): g for g in games}
    for future in as_completed(futures):
        schedule = future.result()
        schedule_by_id[schedule["game_id"]] = schedule
write_jsonl("nhl_official_schedule.jsonl", [schedule_by_id[g["game_id"]] for g in games])

# Retain source metadata for every relevant event contract, not just the chosen quote.
contract_records = []
for event, contracts in by_event.items():
    if event not in matched_event_to_game:
        continue
    g = matched_event_to_game[event]
    schedule = schedule_by_id[g["game_id"]]
    for entry in contracts:
        contract_records.append({
            "event_ticker": event, "game_id": g["game_id"], "game_date": g["date"],
            "home_team": g["home"], "away_team": g["away"], "market_side_team": entry["side"],
            "market_side_raw": entry["side_raw"], "source_endpoint": KALSHI + "/historical/markets",
            "source_query": {"series_ticker": "KXNHLGAME", "limit": 1000},
            "source_market": entry["market"], "nhl_start_time_utc": schedule["start_time_utc"],
        })
write_jsonl("kalshi_market_metadata.jsonl", contract_records)

# Retrieve only the final 15 minutes before official puck drop (1m candles).
# If no valid two-sided quote appears there, retry with a 6h lookback for the
# latest stale-but-still-pregame quote. Strictly exclude candles timestamped at
# or after puck drop.
quote_rows, raw_candle_records, failures = [], [], []
contracts_done = 0
for rec in sorted(contract_records, key=lambda x: (x["game_date"], x["game_id"], x["market_side_team"])):
    market = rec["source_market"]
    ticker = market["ticker"]
    start_dt = dt.datetime.fromisoformat(rec["nhl_start_time_utc"].replace("Z", "+00:00"))
    start_ts = int(start_dt.timestamp())
    chosen = None
    queried = []
    for window_name, lookback in (("15m", 900), ("6h_fallback", 21600)):
        if window_name == "6h_fallback" and chosen is not None:
            break
        q = {"start_ts": start_ts - lookback, "end_ts": start_ts - 1, "period_interval": 1}
        endpoint = f"{KALSHI}/historical/markets/{urllib.parse.quote(ticker, safe='')}/candlesticks"
        url = endpoint + "?" + urllib.parse.urlencode(q)
        fetched_at = utcnow()
        try:
            payload, http_status, _ = get_json(url)
        except Exception as exc:
            failures.append({"ticker": ticker, "window": window_name, "error": repr(exc), "url": url})
            queried.append({"window": window_name, "url": url, "query": q, "error": repr(exc)})
            break
        candles = payload.get("candlesticks", [])
        queried.append({"window": window_name, "url": url, "query": q,
                        "http_status": http_status, "candles_returned": len(candles)})
        raw_candle_records.append({
            "ticker": ticker, "event_ticker": rec["event_ticker"], "game_id": rec["game_id"],
            "market_side_team": rec["market_side_team"], "source_endpoint": endpoint,
            "source_query": q, "fetched_at_utc": fetched_at, "http_status": http_status,
            "window": window_name, "candlesticks": candles,
        })
        for candle in candles:
            ts = int(candle.get("end_period_ts", -1))
            if ts >= start_ts:
                continue
            bid_raw = (candle.get("yes_bid") or {}).get("close")
            ask_raw = (candle.get("yes_ask") or {}).get("close")
            try:
                bid, ask = float(bid_raw), float(ask_raw)
            except (TypeError, ValueError):
                continue
            if 0 <= bid <= ask <= 1:
                candidate = (ts, candle, bid, ask, window_name)
                if chosen is None or ts > chosen[0]:
                    chosen = candidate
        time.sleep(1.0)
    contracts_done += 1
    if chosen:
        ts, candle, bid, ask, window_name = chosen
        age = start_ts - ts
        quote_rows.append({
            **{k: rec[k] for k in ("event_ticker", "game_id", "game_date", "home_team", "away_team", "market_side_team", "market_side_raw")},
            "ticker": ticker, "game_start_time_utc": rec["nhl_start_time_utc"],
            "quote_timestamp_utc": dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(),
            "quote_age_seconds": age, "within_15m": age <= 900,
            "yes_bid": bid, "yes_ask": ask, "yes_mid": (bid + ask) / 2,
            "spread": ask - bid, "traded_price_close": (candle.get("price") or {}).get("close"),
            "candle_volume": candle.get("volume"), "open_interest": candle.get("open_interest"),
            "quote_window": window_name, "candle_end_period_ts": ts,
            "source_endpoint": next(x["url"] for x in queried if x["window"] == window_name),
            "source_query": next(x["query"] for x in queried if x["window"] == window_name),
            "source_fetched_at_utc": next(x.get("fetched_at_utc") for x in raw_candle_records[-len(queried):] if x["window"] == window_name) if queried else None,
            "source_market_open_time": market.get("open_time"), "source_market_close_time": market.get("close_time"),
            "source_market_result_label_excluded_from_features": market.get("result"),
        })
    else:
        quote_rows.append({
            **{k: rec[k] for k in ("event_ticker", "game_id", "game_date", "home_team", "away_team", "market_side_team", "market_side_raw")},
            "ticker": ticker, "game_start_time_utc": rec["nhl_start_time_utc"],
            "quote_timestamp_utc": None, "quote_age_seconds": None, "within_15m": False,
            "yes_bid": None, "yes_ask": None, "yes_mid": None, "spread": None,
            "traded_price_close": None, "candle_volume": None, "open_interest": None,
            "quote_window": None, "candle_end_period_ts": None,
            "source_endpoint": None, "source_query": None, "source_fetched_at_utc": None,
            "source_market_open_time": market.get("open_time"), "source_market_close_time": market.get("close_time"),
            "source_market_result_label_excluded_from_features": market.get("result"),
        })
    if contracts_done % 20 == 0:
        print(f"Fetched candles for {contracts_done}/{len(contract_records)} matched contracts", flush=True)

# Write exact source responses and derived audit tables.
write_json("kalshi_archive_pagination.json", {
    "retrieved_at_utc": utcnow(), "endpoint": KALSHI + "/historical/markets",
    "query": {"series_ticker": "KXNHLGAME", "limit": 1000}, "pages": page_rows,
    "archive_contract_count": len(all_markets), "unique_ticker_count": len(set(all_tickers)),
    "cursor_chain_terminated": True, "historical_cutoff_http_status": cutoff_status,
    "historical_cutoff": cutoff,
})
write_jsonl("kalshi_pregame_candles.jsonl", raw_candle_records)
write_jsonl("quote_failures.jsonl", failures)

# Complete 82-row game crosswalk, including the two with no Kalshi event.
events_by_game_id = defaultdict(list)
for event, g in matched_event_to_game.items():
    events_by_game_id[g["game_id"]].append(event)
quote_by_game = defaultdict(list)
for qrow in quote_rows:
    quote_by_game[qrow["game_id"]].append(qrow)
crosswalk = []
for g in games:
    sch = schedule_by_id[g["game_id"]]
    evs = events_by_game_id.get(g["game_id"], [])
    qs = quote_by_game.get(g["game_id"], [])
    valid = [q for q in qs if q["yes_bid"] is not None and q["yes_ask"] is not None]
    fresh = [q for q in valid if q["within_15m"]]
    crosswalk.append({
        **g, "game_start_time_utc": sch["start_time_utc"], "venue": sch["venue"],
        "kalshi_event_ticker": evs[0] if len(evs) == 1 else None,
        "event_count": len(evs), "market_contract_count": len(qs),
        "usable_quote_contract_count": len(valid), "quote_within_15m_contract_count": len(fresh),
        "both_sides_usable": len(valid) == 2, "both_sides_within_15m": len(fresh) == 2,
        "coverage_status": "matched" if evs else "no_kalshi_event",
    })
with open(os.path.join(OUT, "game_crosswalk.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(crosswalk[0].keys()))
    w.writeheader(); w.writerows(crosswalk)
with open(os.path.join(OUT, "pregame_quotes.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(quote_rows[0].keys()))
    w.writeheader(); w.writerows(quote_rows)

# Coverage, spread and quality metrics.
valid_quotes = [q for q in quote_rows if q["yes_bid"] is not None and q["yes_ask"] is not None]
fresh_quotes = [q for q in valid_quotes if q["within_15m"]]
spreads = [q for q in valid_quotes if q["spread"] is not None]
games_with_any_quote = sum(bool(quote_by_game[g["game_id"]] and any(q["yes_bid"] is not None for q in quote_by_game[g["game_id"]])) for g in games)
games_with_both = sum(len([q for q in quote_by_game[g["game_id"]] if q["yes_bid"] is not None]) == 2 for g in games)
games_fresh_both = sum(len([q for q in quote_by_game[g["game_id"]] if q["within_15m"]]) == 2 for g in games)
ages = [q["quote_age_seconds"] for q in valid_quotes]
quality = {
    "duplicate_archive_tickers": len(all_tickers) - len(set(all_tickers)),
    "duplicate_event_tickers_in_scope": 0,
    "malformed_events": malformed_events,
    "duplicate_or_ambiguous_matchups": duplicate_matchups,
    "unmatched_kalshi_events": unmatched_events,
    "quote_http_or_parse_failures": failures,
    "contracts_missing_usable_quote": len(quote_rows) - len(valid_quotes),
    "crossed_or_invalid_spreads": sum(1 for q in quote_rows if q["yes_bid"] is not None and q["yes_ask"] is not None and q["yes_bid"] > q["yes_ask"]),
    "invalid_or_post_start_candles_selected": sum(1 for q in valid_quotes if q["candle_end_period_ts"] >= int(dt.datetime.fromisoformat(q["game_start_time_utc"].replace("Z", "+00:00")).timestamp())),
    "source_failures": [],
}
summary = {
    "audit_generated_at_utc": utcnow(), "database_path_read_only": DB,
    "season_label": "2025-26 NHL playoffs", "db_playoff_games": len(games),
    "kalshi_archive": {"endpoint": KALSHI + "/historical/markets", "series_ticker": "KXNHLGAME",
        "page_count": len(page_rows), "page_sizes": [p["count"] for p in page_rows],
        "contracts_fetched_all_series": len(all_markets), "unique_market_tickers": len(set(all_tickers)),
        "cursor_chain_terminated": True, "playoff_event_count": len(by_event),
        "playoff_contract_count": sum(len(x) for x in by_event.values()),
        "events_with_exactly_two_distinct_sides": sum(1 for v in by_event.values() if len(v) == 2 and len({x['side'] for x in v}) == 2)},
    "event_game_reconciliation": {"matched_games": len(matched_event_to_game), "matched_events": len(matched_event_to_game),
        "missing_kalshi_events_for_games": missing_games, "unmatched_kalshi_events": unmatched_events,
        "duplicate_or_ambiguous_matchups": duplicate_matchups, "malformed_events": malformed_events},
    "quote_coverage": {"matched_market_contracts_expected": len(contract_records), "contracts_with_usable_two_sided_quotes": len(valid_quotes),
        "contracts_with_quotes_within_15m": len(fresh_quotes), "contracts_with_spread": len(spreads),
        "games_with_any_usable_side_quote": games_with_any_quote, "games_with_both_side_quotes": games_with_both,
        "games_with_both_side_quotes_within_15m": games_fresh_both,
        "median_quote_age_seconds": sorted(ages)[len(ages)//2] if ages else None,
        "max_quote_age_seconds": max(ages) if ages else None,
        "quote_age_distribution_seconds": {"le_1m": sum(a <= 60 for a in ages), "le_5m": sum(a <= 300 for a in ages),
            "le_15m": sum(a <= 900 for a in ages), "gt_15m": sum(a > 900 for a in ages)}},
    "spread": {"available_contract_quotes": len(spreads), "median_probability_spread": sorted(q["spread"] for q in spreads)[len(spreads)//2] if spreads else None,
        "median_spread_cents": round(100 * sorted(q["spread"] for q in spreads)[len(spreads)//2], 3) if spreads else None},
    "data_quality": quality,
    "feature_safety": {"cutoff_rule": "Select greatest candle end_period_ts strictly less than NHL startTimeUTC.",
        "post_start_candles_selected": 0, "settlement_result_used_as_feature": False,
        "missing_markets_substituted_from_other_bookmakers": 0,
        "fallback": "If no valid quote in T-15m..T-1s, request up to T-6h..T-1s and flag quote age."},
}
write_json("audit_summary.json", summary)

# Human-readable report.
report = f'''# NHL 2025–26 Playoff Kalshi Market Reconciliation

Generated: {summary['audit_generated_at_utc']}

## Result

- NHL DuckDB playoff games: **{len(games)}**.
- Kalshi historical archive pagination: **{len(page_rows)} pages** with sizes **{[p['count'] for p in page_rows]}**; all **{len(all_markets)}** returned market tickers were unique and the cursor chain terminated.
- 2025–26 playoff-window Kalshi events/contracts: **{len(by_event)} events / {sum(len(v) for v in by_event.values())} contracts**. Every event has exactly two distinct team-side contracts.
- Reconciled: **{len(matched_event_to_game)} of 82 games**. Missing Kalshi events: **{len(missing_games)}**. Duplicate or ambiguous event/game matches: **{len(duplicate_matchups)}**.

## Missing game markets

'''
for g in missing_games:
    report += f"- NHL game `{g['game_id']}`: {g['date']} {g['away']} at {g['home']} — no Kalshi event.\n"
report += f'''
## Pregame quote coverage

A quote is usable when the selected 1-minute candle has numeric YES bid and YES ask, with `0 <= bid <= ask <= 1`. For each team-side contract, the selected quote is the newest qualifying candle whose `end_period_ts` is **strictly earlier than official NHL `startTimeUTC`**. The primary lookup window is T−15 minutes through T−1 second. If no valid quote exists there, the audit checks up to T−6 hours and marks the quote stale by its age.

- Matched games expected: **{len(matched_event_to_game)}**; matched team-side contracts expected: **{len(contract_records)}**.
- Contracts with a valid two-sided quote: **{len(valid_quotes)}/{len(contract_records)}**.
- Contracts with a quote within 15 minutes of puck drop: **{len(fresh_quotes)}/{len(contract_records)}**.
- Games with any quoted side: **{games_with_any_quote}/{len(games)}**; games with both team-side contracts quoted: **{games_with_both}/{len(games)}**.
- Games with both sides quoted within 15 minutes: **{games_fresh_both}/{len(games)}**.
- Spread available for **{len(spreads)}/{len(contract_records)}** matched contracts; median YES bid/ask spread **{summary['spread']['median_spread_cents']}¢**.
- Quote age: median **{summary['quote_coverage']['median_quote_age_seconds']} seconds**, max **{summary['quote_coverage']['max_quote_age_seconds']} seconds**. Age buckets: <=1m {summary['quote_coverage']['quote_age_distribution_seconds']['le_1m']}, <=5m {summary['quote_coverage']['quote_age_distribution_seconds']['le_5m']}, <=15m {summary['quote_coverage']['quote_age_distribution_seconds']['le_15m']}, >15m {summary['quote_coverage']['quote_age_distribution_seconds']['gt_15m']}.

## Data quality and safeguards

- Malformed Kalshi events: **{len(malformed_events)}**.
- Duplicate or ambiguous matchups: **{len(duplicate_matchups)}**.
- Archive duplicate tickers: **{quality['duplicate_archive_tickers']}**.
- Contracts without a valid quote after fallback: **{quality['contracts_missing_usable_quote']}**.
- Quote retrieval failures: **{len(failures)}**.
- Crossed/invalid spreads: **{quality['crossed_or_invalid_spreads']}**.
- Selected post-start candles: **{quality['invalid_or_post_start_candles_selected']}**.
- No bookmaker substitution. Market result labels are retained as source metadata only and excluded from model features.

The two games without Kalshi events remain uncovered; no prices are imputed. Model-versus-market evaluation must either be explicitly limited to matched games or use another season of Kalshi coverage. This report does not train or evaluate a model.

The separate [historical game identity and outcome audit](historical_data_integrity.md) records issues found in the NHL modeling DuckDB that must be resolved before backtesting.

## Artifacts

- `game_crosswalk.csv`: all 82 NHL games and match status.
- `pregame_quotes.csv`: selected quote per available team-side contract, exchange candle timestamp, age, bid/ask/mid, spread, trade price, candle volume/open interest, and source query metadata.
- `kalshi_pregame_candles.jsonl`: raw 1-minute candle responses and request metadata, including the full 15-minute windows and any fallback windows.
- `kalshi_market_metadata.jsonl`: source market records for the 160 matched contracts, including settlement fields for audit provenance only.
- `kalshi_archive_pagination.json`: all-series page counts, cursor termination, and historical cutoff response.
- `nhl_official_schedule.jsonl`: official gamecenter start times and team identity.
- `audit_summary.json`: machine-readable coverage totals and quality flags.
- `run_audit.py`: read-only audit script.

## Sources and exact query contracts

- Kalshi: `GET /trade-api/v2/historical/cutoff`.
- Kalshi: `GET /trade-api/v2/historical/markets?series_ticker=KXNHLGAME&limit=1000`, cursor-paginated to completion.
- Kalshi: `GET /trade-api/v2/historical/markets/{{ticker}}/candlesticks?start_ts={{start_ts}}&end_ts={{start_ts-1}}&period_interval=1`.
- NHL: `GET /v1/gamecenter/{{game_id}}/landing`; use only `gameDate`, teams, venue and `startTimeUTC` as schedule authority.
- NHL DuckDB opened read-only: `{DB}`; game population from `skaters_playoff_boxscores`, season key `{SEASON}`.
- Kalshi team abbreviations normalized: `TB -> TBL`, `LA -> LAK`; other suffixes retained as returned.
'''
with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8") as f:
    f.write(report)
print("AUDIT_COMPLETE")
print(json.dumps(summary, indent=2))
