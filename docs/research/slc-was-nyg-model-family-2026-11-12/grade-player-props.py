#!/usr/bin/env python3
"""Grade the saved model distributions against pre-kickoff API lines and final stats."""
import argparse
import csv
import json
import re
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--db", type=Path, required=True, help="read-only picks.dev.db")
parser.add_argument("--game-id", type=int, default=30217)
parser.add_argument("--kickoff", default="2026-11-13T01:15:00+00:00")
parser.add_argument("--forecasts", type=Path, required=True)
parser.add_argument("--actuals", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--quotes-out", type=Path, required=True)
parser.add_argument("--summary-out", type=Path, required=True)
args = parser.parse_args()

# Database market key -> saved per-game simulated stat distribution.
MARKETS = {
    "passing_yards": "pass_yards", "pass_attempts": "pass_attempts",
    "pass_completions": "pass_completions", "passing_touchdowns": "pass_tds",
    "interceptions_thrown": "interceptions", "rushing_yards": "rush_yards",
    "rush_attempts": "carries", "receiving_yards": "receiving_yards",
    "receptions": "receptions", "targets": "targets",
    "rushing_receiving_yards": "rushing_receiving_yards",
    "passing_rushing_yards": "passing_rushing_yards", "total_touchdowns": "total_touchdowns",
}
ACTUAL_KEYS = {
    "passing_yards": ("passing", "yds"), "pass_attempts": ("passing", "att"),
    "pass_completions": ("passing", "comp"), "passing_touchdowns": ("passing", "td"),
    "interceptions_thrown": ("passing", "int"), "rushing_yards": ("rushing", "yds"),
    "rush_attempts": ("rushing", "att"), "receiving_yards": ("receiving", "yds"),
    "receptions": ("receiving", "rec"), "targets": ("receiving", "tar"),
}

forecasts = {}
for r in csv.DictReader(args.forecasts.open()):
    forecasts[(r["model"], r["stable_player_id"], r["metric"])] = json.loads(r["histogram_json"])
actual_json = json.loads(args.actuals.read_text())
db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
players = {str(r["id"]): r for r in db.execute("select id,nfl_gsis_id,espn_id,name,team from players where league='nfl'")}
def name_key(name, team):
    # CBS labels use initial + surname; the app DB uses full roster names.
    pieces = re.sub(r"\s+\d+\s+[A-Z]+$", "", name).replace(".", "").split()
    if len(pieces) < 2:
        return None
    first, last = pieces[0].lower(), pieces[-1].lower()
    return (first[:1], last)
cbs_by_key = defaultdict(list)
for cbs_id, player in actual_json.items():
    key = name_key(player["name"], player["team"])
    if key:
        cbs_by_key[key].append(player)
actual_by_gsis = {}
for player in players.values():
    gsis = player["nfl_gsis_id"]
    key = name_key(player["name"], player["team"])
    matches = cbs_by_key.get(key, []) if key else []
    if gsis and len(matches) == 1:
        actual_by_gsis[gsis] = matches[0]
raw = defaultdict(dict)
sql = """select p.player_id,p.market,p.line,p.side,p.source,p.captured_at,p.odds,pl.nfl_gsis_id,pl.espn_id
         from props p join players pl on pl.id=p.player_id
         where p.game_id=? and p.captured_at<? order by p.captured_at"""
for r in db.execute(sql, (args.game_id, args.kickoff)):
    key = (r["nfl_gsis_id"], r["market"], float(r["line"]), r["source"])
    raw[key][r["side"].lower()] = {"odds": r["odds"], "captured_at": r["captured_at"], "gsis_id": r["nfl_gsis_id"]}

def american_prob(odds):
    odds = int(odds)
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)

def actual_value(gsis_id, market):
    player = actual_by_gsis.get(gsis_id)
    if player is None:
        return None
    if market in ACTUAL_KEYS:
        group, key = ACTUAL_KEYS[market]
        val = player.get(group, {}).get(key)
        if val is None or val in ("", "-"):
            return None
        try:
            return float(val)
        except ValueError:
            return None
    if market == "rushing_receiving_yards":
        a, b = actual_value(gsis_id, "rushing_yards"), actual_value(gsis_id, "receiving_yards")
        return a + b if a is not None and b is not None else None
    if market == "passing_rushing_yards":
        a, b = actual_value(gsis_id, "passing_yards"), actual_value(gsis_id, "rushing_yards")
        return a + b if a is not None and b is not None else None
    if market == "total_touchdowns":
        rush = player.get("rushing", {}).get("td")
        rec = player.get("receiving", {}).get("td")
        try:
            return float(rush) + float(rec)
        except (TypeError, ValueError):
            return None
    return None

# Keep only supported markets with matching model records and usable actuals.
quotes = defaultdict(list)
for (gsis, market, line, source), sides in raw.items():
    if market not in MARKETS or gsis is None or not {"over", "under"} <= sides.keys():
        continue
    y = actual_value(gsis, market)
    if y is None or y == line:  # push: no binary over/under outcome
        continue
    model_ps = {}
    for model in ("v1", "v1.5", "v1.6", "v2"):
        hist = forecasts.get((model, gsis, MARKETS[market]))
        if not hist:
            model_ps = {}
            break
        n = sum(int(v) for v in hist.values())
        over_n = sum(int(count) for value, count in hist.items() if float(value) > line)
        model_ps[model] = over_n / n
    if not model_ps:
        continue
    over_odds, under_odds = sides["over"]["odds"], sides["under"]["odds"]
    market_p = None
    if over_odds is not None and under_odds is not None:
        io, iu = american_prob(over_odds), american_prob(under_odds)
        market_p = io / (io + iu)
    quotes[(gsis, market, line)].append({
        "source": source, "actual": y, "line": line,
        "captured_at": max(sides["over"]["captured_at"], sides["under"]["captured_at"]),
        "over_odds_american": over_odds, "under_odds_american": under_odds,
        "p_over_market": market_p, "p_over_by_model": model_ps,
    })

graded = []
for (gsis, market, line), offers in sorted(quotes.items()):
    market_probs = [q["p_over_market"] for q in offers if q["p_over_market"] is not None]
    actual = offers[0]["actual"]
    row = {"stable_player_id": gsis, "market": market, "model_metric": MARKETS[market],
           "line": line, "actual": actual, "over_hit": int(actual > line),
           "books": len(offers), "books_with_two_sided_odds": len(market_probs),
           "mean_devig_market_p_over": statistics.mean(market_probs) if market_probs else None,
           "sources": ";".join(sorted(q["source"] for q in offers))}
    for model in ("v1", "v1.5", "v1.6", "v2"):
        row[f"{model}_p_over"] = statistics.mean(q["p_over_by_model"][model] for q in offers)
        row[f"{model}_brier"] = (row[f"{model}_p_over"] - row["over_hit"]) ** 2
    if row["mean_devig_market_p_over"] is not None:
        row["market_brier"] = (row["mean_devig_market_p_over"] - row["over_hit"]) ** 2
    else:
        row["market_brier"] = None
    graded.append(row)

if not graded:
    raise SystemExit("no matched settled player-prop line items")
args.out.parent.mkdir(parents=True, exist_ok=True)
with args.out.open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=graded[0].keys())
    writer.writeheader()
    writer.writerows(graded)
quote_rows = []
for (gsis, market, line), offers in sorted(quotes.items()):
    for q in offers:
        quote_rows.append({
            "stable_player_id": gsis, "market": market, "line": line, "source": q["source"],
            "captured_at": q["captured_at"], "over_odds_american": q["over_odds_american"],
            "under_odds_american": q["under_odds_american"], "actual": q["actual"],
            "over_hit": int(q["actual"] > line), "devigged_market_p_over": q["p_over_market"],
            **{f"{m}_p_over": q["p_over_by_model"][m] for m in ("v1", "v1.5", "v1.6", "v2")},
        })
args.quotes_out.parent.mkdir(parents=True, exist_ok=True)
with args.quotes_out.open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=quote_rows[0].keys())
    writer.writeheader()
    writer.writerows(quote_rows)
common = [r for r in graded if r["market_brier"] is not None]
summary = {
    "source_game_id": args.game_id, "pregame_cutoff": args.kickoff,
    "matched_player_market_lines": len(graded),
    "matched_source_quotes": len(quote_rows),
    "unique_players": len({r["stable_player_id"] for r in graded}),
    "markets": dict(sorted((m, sum(r["market"] == m for r in graded)) for m in {r["market"] for r in graded})),
    "two_sided_market_comparison_items": len(common),
    "brier_all_matched_lines": {m: statistics.mean(r[f"{m}_brier"] for r in graded) for m in ("v1", "v1.5", "v1.6", "v2")},
    "brier_same_lines_with_two_sided_market_odds": {
        **{m: statistics.mean(r[f"{m}_brier"] for r in common) for m in ("v1", "v1.5", "v1.6", "v2")},
        "devigged_market": statistics.mean(r["market_brier"] for r in common),
    },
    "brier_by_market_same_market_lines": {},
    "limitations": ["One game only; repeated prop thresholds for the same player are correlated.",
                    "Forecasts use simulation frequencies and are not calibrated market probabilities.",
                    "Market benchmark averages de-vigged over prices across captured books for each exact player-market-line."]
}
for market in sorted({r["market"] for r in common}):
    rows = [r for r in common if r["market"] == market]
    summary["brier_by_market_same_market_lines"][market] = {
        "n": len(rows), **{m: statistics.mean(r[f"{m}_brier"] for r in rows) for m in ("v1", "v1.5", "v1.6", "v2")},
        "devigged_market": statistics.mean(r["market_brier"] for r in rows),
    }
args.summary_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(json.dumps(summary, indent=2, sort_keys=True))
