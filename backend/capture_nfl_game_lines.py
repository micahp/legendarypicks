#!/usr/bin/env python3
"""capture_nfl_game_lines.py -- capture pre-game NFL spread, total and moneyline from Bovada.

Reads the Bovada NFL coupon (read-only GET via bovada_scraper.client.fetch_events), keeps the
full-game markets only (the market period named "Game", never live, quarter, half or team
props), matches each event to an unscored REG game in nfl_schedule by team name, and writes one
row per game to nfl_line_snapshots with source 'bovada' and the capture time.

Sign convention: nfl_schedule.spread_line and nfl_line_snapshots.spread_line are the HOME team's
expected margin (positive = home favoured). Bovada's home handicap is the negative of that, so
spread_line = -home_handicap.

Dry run by default. Pass --write to insert. Writes only to LP_DB_PATH.

Usage:
  LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db venv/bin/python capture_nfl_game_lines.py
  LP_DB_PATH=... venv/bin/python capture_nfl_game_lines.py --write
"""
import datetime as dt
import os
import sqlite3
import sys

import check_nfl_schedule_scores as cs
from bovada_scraper.client import fetch_events

LEAGUE = "nfl"
SOURCE = "bovada"
SEASON = 2026
DB = os.environ.get("LP_DB_PATH")


def american(price):
    """Bovada prices are American strings ('-110', '+105', 'EVEN'). Return int or None."""
    if price is None:
        return None
    if price == "EVEN":
        return 100
    try:
        return int(price)
    except ValueError:
        return None


def team_codes(con):
    rows = con.execute("SELECT team_name, team FROM nfl_teams WHERE season = ?", (SEASON,))
    return {name: code for name, code in rows}


def full_game_lines(event):
    """Return dict with spread_line, total_line, home_moneyline, away_moneyline from the
    full-game markets only, or None for any that Bovada did not post."""
    out = {"spread_line": None, "total_line": None, "home_moneyline": None, "away_moneyline": None}
    for grp in event.get("displayGroups", []):
        if grp.get("description") != "Game Lines":
            continue
        for m in grp.get("markets", []):
            if (m.get("period") or {}).get("description") != "Game":
                continue
            name = m.get("description")
            for o in m.get("outcomes", []):
                price = o.get("price") or {}
                if name == "Point Spread" and o.get("type") == "H" and price.get("handicap"):
                    out["spread_line"] = -float(price["handicap"])
                elif name == "Total" and o.get("type") == "O" and price.get("handicap"):
                    out["total_line"] = float(price["handicap"])
                elif name == "Moneyline":
                    if o.get("type") == "H":
                        out["home_moneyline"] = american(price.get("american"))
                    elif o.get("type") == "A":
                        out["away_moneyline"] = american(price.get("american"))
    return out


def main(argv):
    write = "--write" in argv
    if not DB:
        sys.exit("set LP_DB_PATH to the dev database")
    con = sqlite3.connect(DB, timeout=60)
    codes = team_codes(con)
    now_dt = dt.datetime.now(dt.timezone.utc)
    now = now_dt.isoformat()
    events = fetch_events("football", "nfl")
    print("bovada nfl events: %d" % len(events))
    to_write = []
    started = []
    unguarded = []
    for ev in events:
        comps = ev.get("competitors", [])
        home = next((c["name"] for c in comps if c.get("home")), None)
        away = next((c["name"] for c in comps if not c.get("home")), None)
        label = ev.get("description")
        if home not in codes or away not in codes:
            print("  SKIP %s: unmapped team name (%s / %s)" % (label, away, home))
            continue
        row = con.execute(
            "SELECT game_id, gameday, gametime FROM nfl_schedule "
            "WHERE season = ? AND game_type = 'REG' "
            "AND home_team = ? AND away_team = ? AND home_score IS NULL",
            (SEASON, codes[home], codes[away])).fetchall()
        if len(row) != 1:
            print("  SKIP %s: %d unscored schedule matches" % (label, len(row)))
            continue
        gid, gameday, gametime = row[0]
        if not gameday:
            print("  SKIP %s: no gameday, kickoff cannot be guarded" % label)
            unguarded.append(gid)
            continue
        kickoff = cs.kickoff_utc(gameday, gametime)
        if kickoff <= now_dt:
            print("  SKIP %s: kickoff %s has passed" % (label, kickoff.isoformat()))
            started.append(gid)
            continue
        lines = full_game_lines(ev)
        if all(v is None for v in lines.values()):
            print("  SKIP %s: no full-game lines posted" % label)
            continue
        print("  %s -> %s  spread_line=%s total=%s home_ml=%s away_ml=%s" % (
            label, gid, lines["spread_line"], lines["total_line"],
            lines["home_moneyline"], lines["away_moneyline"]))
        to_write.append((LEAGUE, gid, SOURCE, now, now, lines["spread_line"],
                         lines["total_line"], lines["home_moneyline"], lines["away_moneyline"]))
    if not write:
        print("dry run: %d rows would be inserted by --write; "
              "in-play skipped: %d; unguarded (no gameday) skipped: %d."
              % (len(to_write), len(started), len(unguarded)))
        return 0
    if started or unguarded:
        print("refusing --write: in-play skipped: %d; unguarded (no gameday) skipped: %d; "
              "no rows written." % (len(started), len(unguarded)))
        return 1
    print("writing %d rows (source=%s, captured_at=%s)" % (len(to_write), SOURCE, now))
    con.executemany(
        "INSERT INTO nfl_line_snapshots (league, game_id, source, captured_at, "
        " source_ingested_at, spread_line, total_line, home_moneyline, away_moneyline) "
        "VALUES (?,?,?,?,?,?,?,?,?)", to_write)
    con.commit()
    print("wrote %d snapshot rows (source=%s, captured_at=%s)" % (len(to_write), SOURCE, now))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
