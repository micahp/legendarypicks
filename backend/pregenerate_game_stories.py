#!/usr/bin/env python3
"""Manual one-shot backfill: warm the AI-story cache for upcoming games across leagues.

The AUTOMATIC path is the `/api/{league}/games` hook (`_core.kick_game_stories`): loading
a scoreboard fires background generation for that league's games, so previews are warm by
click-time without any cron. This script is just a convenience to warm the whole slate at
once (e.g. after a fresh DB or a code change). Idempotent — skips already-cached games.

Usage:
  LP_DB_PATH=data/picks.dev.db python3 pregenerate_game_stories.py [league ...] [--days N]
  (default leagues: nba nhl mlb nfl; default --days 2 = today + tomorrow)
"""
import sys, datetime as dt
import espn_client as espn
from _core import generate_game_story

DEFAULT_LEAGUES = ["nba", "nhl", "mlb", "nfl"]


def discover(lg: str, days: int):
    """Return [(game_id, home_abbrev, away_abbrev)] for the next `days` days of games."""
    out, seen = [], set()
    today = dt.date.today()
    for i in range(days):
        d = (today + dt.timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            for g in espn.games(lg, d):
                gid = g.get("game_id")
                if not gid or str(gid) in seen:
                    continue
                seen.add(str(gid))
                home = (g.get("home") or {}).get("abbrev")
                away = (g.get("away") or {}).get("abbrev")
                out.append((str(gid), home, away))
        except Exception as e:
            print(f"[{lg}] games({d}) failed: {e}")
    return out


def main():
    args = [a for a in sys.argv[1:] if a != "--days"]
    days = 2
    if "--days" in sys.argv:
        i = sys.argv.index("--days")
        try:
            days = int(sys.argv[i + 1]); args = [a for a in args if a != sys.argv[i + 1]]
        except (IndexError, ValueError):
            pass
    leagues = args or DEFAULT_LEAGUES

    total_new, total_seen = 0, 0
    for lg in leagues:
        games = discover(lg, days)
        new = 0
        for gid, home, away in games:
            res = generate_game_story(lg, gid, home=home, away=away)
            if res.get("story") and not res.get("cached"):
                new += 1
        total_new += new; total_seen += len(games)
        print(f"[{lg}] {len(games)} games discovered, {new} new stories generated")
    print(f"DONE: {total_seen} games seen, {total_new} new stories cached")


if __name__ == "__main__":
    main()
