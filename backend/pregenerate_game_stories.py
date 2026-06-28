#!/usr/bin/env python3
"""Pre-generate AI matchup stories for discovered games, so the preview cache is warm
BEFORE the first user view — instead of generating lazily when someone opens the game
detail (which makes that first viewer wait on a DeepSeek call).

"Write the preview whenever we find out about the game." Run on a cron (e.g. hourly).
Idempotent: _core.generate_game_story skips games already in the game_story cache.

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
