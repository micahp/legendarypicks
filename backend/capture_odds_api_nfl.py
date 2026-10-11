#!/usr/bin/env python3
"""capture_odds_api_nfl.py -- one pre-game NFL snapshot from The Odds API (v4), into
nfl_line_snapshots with source 'theoddsapi:<bookmaker>' and the capture time.

Reads the key from the environment variable THEODDS_API_KEY and never prints it. Costs 3 credits per
run (3 markets x 1 region). Dry run by default; pass --write to insert.

Sign convention as elsewhere: spread_line = the HOME team's expected margin, so it is the negative
of the home team's point in the API. The bookmaker is the first one in the response that carries all
three markets, in the API's order.

Usage:
  set -a; . /root/.hermes/.env; set +a   # loads the key into the environment without printing it
  LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db venv/bin/python capture_odds_api_nfl.py [--write]
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request

SEASON = 2026
DB = os.environ.get("LP_DB_PATH")
URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"


def fetch(key):
    q = urllib.parse.urlencode({"apiKey": key, "regions": "us", "markets": "h2h,spreads,totals",
                                "oddsFormat": "american"})
    with urllib.request.urlopen(URL + "?" + q, timeout=30) as r:
        remaining = r.headers.get("x-requests-remaining")
        return json.loads(r.read().decode()), remaining


def price_int(p):
    try:
        return int(float(p))
    except (TypeError, ValueError):
        return None


def lines_for(event):
    """(book, lines) from the first bookmaker carrying h2h, spreads and totals."""
    home, away = event["home_team"], event["away_team"]
    for bk in event.get("bookmakers", []):
        mk = {m["key"]: m for m in bk.get("markets", [])}
        if not {"h2h", "spreads", "totals"} <= set(mk):
            continue
        out = {"spread_line": None, "total_line": None, "home_moneyline": None,
               "away_moneyline": None}
        for o in mk["spreads"]["outcomes"]:
            if o["name"] == home:
                out["spread_line"] = -float(o["point"])
        for o in mk["totals"]["outcomes"]:
            if o["name"] == "Over":
                out["total_line"] = float(o["point"])
        for o in mk["h2h"]["outcomes"]:
            if o["name"] == home:
                out["home_moneyline"] = price_int(o["price"])
            elif o["name"] == away:
                out["away_moneyline"] = price_int(o["price"])
        return bk["key"], out
    return None, None


def main(argv):
    write = "--write" in argv
    key = os.environ.get("THEODDS_API_KEY")
    if not key:
        sys.exit("THEODDS_API_KEY is not set in this environment")
    if not DB:
        sys.exit("set LP_DB_PATH to the dev database")
    con = sqlite3.connect(DB, timeout=120)
    names = {n: c for n, c in con.execute(
        "SELECT team_name, team FROM nfl_teams WHERE season = ?", (SEASON,))}
    events, remaining = fetch(key)
    print("odds api nfl events: %d   requests remaining this month: %s" % (len(events), remaining))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = []
    for ev in events:
        home, away = names.get(ev["home_team"]), names.get(ev["away_team"])
        label = "%s @ %s" % (ev["away_team"], ev["home_team"])
        if not home or not away:
            print("  SKIP %s: unmapped team name" % label)
            continue
        found = con.execute(
            "SELECT game_id FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
            "AND home_team = ? AND away_team = ? AND home_score IS NULL", (SEASON, home, away)).fetchall()
        if len(found) != 1:
            print("  SKIP %s: %d unscored schedule matches" % (label, len(found)))
            continue
        book, lines = lines_for(ev)
        if book is None:
            print("  SKIP %s: no bookmaker with all three markets" % label)
            continue
        print("  %s -> %s [%s] spread=%s total=%s home_ml=%s away_ml=%s" % (
            label, found[0][0], book, lines["spread_line"], lines["total_line"],
            lines["home_moneyline"], lines["away_moneyline"]))
        rows.append(("nfl", found[0][0], "theoddsapi:" + book, now, now, lines["spread_line"],
                     lines["total_line"], lines["home_moneyline"], lines["away_moneyline"]))
    if not write:
        print("dry run: %d rows would be written. Pass --write to insert." % len(rows))
        return
    con.executemany(
        "INSERT INTO nfl_line_snapshots (league, game_id, source, captured_at, source_ingested_at, "
        " spread_line, total_line, home_moneyline, away_moneyline) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    print("wrote %d snapshot rows at %s" % (len(rows), now))


if __name__ == "__main__":
    main(sys.argv[1:])
