#!/usr/bin/env python3
"""Capture pre-game NHL puck line, total and moneyline from the Bovada coupon.

Reads the Bovada NHL coupon (read-only GET via bovada_scraper.client.fetch_events), keeps the
full-game markets only (the "Game Lines" group, period "Game"), matches each event to a game in the
NHL research feed by team pair and start time, and appends one snapshot row per game to
nhl_game_lines in the standalone NHL model database.

Sign convention: home_puck_line is Bovada's home handicap. -1.5 means the home team is favoured
by 1.5 goals. Prices are American odds.

Dry run by default; --write appends the rows. Never writes to a Legendary Picks database.
refresh_lines() is the same capture, used by the read API when the newest snapshot is stale.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from bovada_scraper.client import fetch_events
from nhl_model_store import (DEFAULT_DB, DEFAULT_FEED, ensure_schema, iso_utc, open_db,
                             parse_time, read_feed)

SOURCE = "bovada"
MATCH_WINDOW = dt.timedelta(minutes=60)
REFRESH_AFTER = dt.timedelta(minutes=15)
TEAM_CODES = {
    "Anaheim Ducks": "ANA", "Boston Bruins": "BOS", "Buffalo Sabres": "BUF", "Calgary Flames": "CGY",
    "Carolina Hurricanes": "CAR", "Chicago Blackhawks": "CHI", "Colorado Avalanche": "COL",
    "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL", "Detroit Red Wings": "DET",
    "Edmonton Oilers": "EDM", "Florida Panthers": "FLA", "Los Angeles Kings": "LAK",
    "Minnesota Wild": "MIN", "Montreal Canadiens": "MTL", "Nashville Predators": "NSH",
    "New Jersey Devils": "NJD", "New York Islanders": "NYI", "New York Rangers": "NYR",
    "Ottawa Senators": "OTT", "Philadelphia Flyers": "PHI", "Pittsburgh Penguins": "PIT",
    "San Jose Sharks": "SJS", "Seattle Kraken": "SEA", "St. Louis Blues": "STL",
    "Tampa Bay Lightning": "TBL", "Toronto Maple Leafs": "TOR", "Utah Mammoth": "UTA",
    "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK", "Washington Capitals": "WSH",
    "Winnipeg Jets": "WPG",
}


def _assert_standalone(path: str) -> None:
    if os.path.basename(os.path.realpath(path)) in {"picks.db", "picks.dev.db"}:
        raise SystemExit("refusing Legendary Picks database path: %s" % path)


def american(price):
    """Bovada prices are American strings ('-128', '+195', 'EVEN'). Return int or None."""
    if price is None:
        return None
    if price == "EVEN":
        return 100
    try:
        return int(price)
    except ValueError:
        return None


def game_lines(event: dict) -> dict:
    """Full-game puck line, total and moneyline from the Game Lines group. None where not posted."""
    out = {"home_puck_line": None, "home_puck_price": None, "away_puck_price": None,
           "total_line": None, "over_price": None, "under_price": None,
           "home_moneyline": None, "away_moneyline": None}
    for grp in event.get("displayGroups", []):
        if grp.get("description") != "Game Lines":
            continue
        for market in grp.get("markets", []):
            if (market.get("period") or {}).get("description") != "Game":
                continue
            name = market.get("description")
            for outcome in market.get("outcomes", []):
                price = outcome.get("price") or {}
                handicap = price.get("handicap")
                kind = outcome.get("type")
                if name == "Puck Line" and handicap is not None:
                    if kind == "H":
                        out["home_puck_line"] = float(handicap)
                        out["home_puck_price"] = american(price.get("american"))
                    elif kind == "A":
                        out["away_puck_price"] = american(price.get("american"))
                elif name == "Total" and handicap is not None:
                    if kind == "O":
                        out["total_line"] = float(handicap)
                        out["over_price"] = american(price.get("american"))
                    elif kind == "U":
                        out["under_price"] = american(price.get("american"))
                elif name == "Moneyline":
                    if kind == "H":
                        out["home_moneyline"] = american(price.get("american"))
                    elif kind == "A":
                        out["away_moneyline"] = american(price.get("american"))
    return out


def event_teams(event: dict) -> tuple:
    home = next((c.get("name") for c in event.get("competitors", []) if c.get("home")), None)
    away = next((c.get("name") for c in event.get("competitors", []) if not c.get("home")), None)
    return home, away


def match_rows(events: list, feed_games: list, now_iso: str, log=print) -> list:
    """One snapshot row per Bovada event that maps to exactly one feed game and has full-game lines."""
    rows = []
    for event in events:
        label = event.get("description")
        home_name, away_name = event_teams(event)
        home, away = TEAM_CODES.get(home_name), TEAM_CODES.get(away_name)
        if home is None or away is None:
            log("  SKIP %s: unmapped team name (%s / %s)" % (label, away_name, home_name))
            continue
        starts = event.get("startTime")
        if starts is None:
            log("  SKIP %s: no start time" % label)
            continue
        start = dt.datetime.fromtimestamp(starts / 1000, dt.timezone.utc)
        matches = [g for g in feed_games if g["home_team"] == home and g["away_team"] == away
                   and abs(parse_time(g["scheduled_start_utc"]) - start) <= MATCH_WINDOW]
        if len(matches) != 1:
            log("  SKIP %s: %d feed matches" % (label, len(matches)))
            continue
        lines = game_lines(event)
        if all(value is None for value in lines.values()):
            log("  SKIP %s: no full-game lines posted" % label)
            continue
        game_id = str(matches[0]["game_id"])
        log("  %s -> %s  puck_line=%s (%s/%s) total=%s (over %s / under %s) home_ml=%s away_ml=%s" % (
            label, game_id, lines["home_puck_line"], lines["home_puck_price"], lines["away_puck_price"],
            lines["total_line"], lines["over_price"], lines["under_price"],
            lines["home_moneyline"], lines["away_moneyline"]))
        rows.append((game_id, SOURCE, now_iso, home, away, lines["home_puck_line"], lines["home_puck_price"],
                     lines["away_puck_price"], lines["total_line"], lines["over_price"], lines["under_price"],
                     lines["home_moneyline"], lines["away_moneyline"]))
    return rows


def write_rows(db_path: str, rows: list) -> None:
    con = open_db(db_path)
    try:
        ensure_schema(con)
        con.executemany(
            "INSERT INTO nhl_game_lines (game_id, source, captured_at_utc, home_team, away_team, "
            "home_puck_line, home_puck_price, away_puck_price, total_line, over_price, under_price, "
            "home_moneyline, away_moneyline) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()


def latest_capture(db_path: str):
    con = open_db(db_path)
    try:
        ensure_schema(con)
        return con.execute("SELECT MAX(captured_at_utc) FROM nhl_game_lines WHERE source=?", (SOURCE,)).fetchone()[0]
    finally:
        con.close()


def refresh_lines(db_path: str, feed_path: str, fetch, now: dt.datetime, log=print,
                  max_age: dt.timedelta | None = None) -> dict:
    """Pull the Bovada NHL coupon when the newest snapshot is older than the threshold.

    `max_age` defaults to REFRESH_AFTER for the read path. The T-90 lock passes a tighter
    window so a game is priced against a quote captured near the cutoff rather than one the
    read path happened to refresh up to fifteen minutes earlier.
    """
    threshold = REFRESH_AFTER if max_age is None else max_age
    latest = latest_capture(db_path)
    if latest is not None and now - parse_time(latest) < threshold:
        return {"refreshed": False, "reason": "fresh", "latest_captured_at_utc": latest}
    now_iso = iso_utc(now)
    try:
        events = fetch("hockey", "nhl")
    except Exception as exc:  # noqa: BLE001 - reported, so the caller can judge the fallback
        return {"refreshed": False, "reason": "fetch_failed", "error": str(exc)[:200],
                "latest_captured_at_utc": latest}
    rows = match_rows(events, read_feed(feed_path)["games"], now_iso, log=log)
    if not rows:
        return {"refreshed": False, "reason": "no_matches", "latest_captured_at_utc": latest}
    write_rows(db_path, rows)
    return {"refreshed": True, "reason": "written", "rows": len(rows), "captured_at_utc": now_iso}


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", default=DEFAULT_FEED)
    parser.add_argument("--db", default=os.environ.get("NHL_MODEL_DB_PATH", DEFAULT_DB))
    parser.add_argument("--write", action="store_true", help="append snapshot rows to the standalone database")
    args = parser.parse_args(argv)
    _assert_standalone(args.db)
    now_iso = iso_utc(dt.datetime.now(dt.timezone.utc))
    events = fetch_events("hockey", "nhl")
    print("bovada nhl events: %d" % len(events))
    rows = match_rows(events, read_feed(args.feed)["games"], now_iso)
    if not args.write:
        print("dry run: %d rows would be written. Pass --write to append." % len(rows))
        return 0
    write_rows(args.db, rows)
    print("wrote %d snapshot rows (source=%s, captured_at=%s)" % (len(rows), SOURCE, now_iso))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
