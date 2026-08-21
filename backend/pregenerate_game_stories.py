#!/usr/bin/env python3
"""Warm the AI-story cache: previews for upcoming games, recaps for finished ones.

The AUTOMATIC path is the `/api/{league}/games` hook (`_core.kick_game_stories`): loading
a scoreboard fires background generation for that league's games, so previews are warm by
click-time. That hook now also re-fires for a game that has ENDED while its cached story is
still a preview, so the recap arrives the same way.

What the hook cannot do is cover a game nobody looked at. The timer sweep is that
guarantee, in both directions: the forward run (no --finals) writes the PREVIEW for a game
nobody opened yet, so one exists by kickoff; `--finals` sweeps back over the last day or
two and writes the recap for anything final whose story still previews it. Idempotent — a
game whose story was written after the final whistle is skipped, so re-running costs
nothing.

Usage:
  LP_DB_PATH=data/picks.dev.db python3 pregenerate_game_stories.py [league ...] [--days N]
  LP_DB_PATH=data/picks.dev.db python3 pregenerate_game_stories.py --finals [league ...]
  (default leagues: league_offering.offered_leagues minus historical-only World Cup;
   default --days 2 = today + tomorrow, and --days 2 with --finals =
   today + yesterday)
"""
import sys, datetime as dt
import espn_client as espn
from _core import generate_game_story
from league_offering import offered_leagues

SCHEDULED_EXCLUDED_LEAGUES = {"wc"}


def default_leagues(con=None):
    """The leagues this database offers, read from the enablement registry.

    This used to be a literal list (`nba nhl mlb nfl`), and it went stale exactly
    the way league_offering's docstring predicts: mls, ncaaf and ufc were offered
    on the hub and silently never got a timer sweep. One question, one answer —
    `offered_leagues` reads team_stats_coverage's vouched statuses plus the
    always-offered shape set, so a league turns on the moment its
    coverage row is promoted. There is deliberately no fallback list here: if
    the registry is unreadable the job fails loudly instead of quietly sweeping
    a stale subset.
    """
    if con is None:
        from _core import _db
        con = _db()
    return sorted(set(offered_leagues(con)) - SCHEDULED_EXCLUDED_LEAGUES)


def discover(lg: str, days: int, backwards: bool = False):
    """[(game_id, home, away, state, start_time)] over a window of days.

    Forwards for previews, backwards for recaps — a finished game is behind us."""
    out, seen = [], set()
    today = dt.date.today()
    for i in range(days):
        delta = dt.timedelta(days=-i if backwards else i)
        d = (today + delta).strftime("%Y-%m-%d")
        try:
            for g in espn.games(lg, d):
                gid = g.get("game_id")
                if not gid or str(gid) in seen:
                    continue
                seen.add(str(gid))
                out.append((str(gid), (g.get("home") or {}).get("abbrev"),
                            (g.get("away") or {}).get("abbrev"),
                            g.get("state"), g.get("date")))
        except Exception as e:
            print(f"[{lg}] games({d}) failed: {e}")
    return out


def main():
    finals = "--finals" in sys.argv
    args = [a for a in sys.argv[1:] if a not in ("--days", "--finals")]
    days = 2
    if "--days" in sys.argv:
        i = sys.argv.index("--days")
        try:
            days = int(sys.argv[i + 1]); args = [a for a in args if a != sys.argv[i + 1]]
        except (IndexError, ValueError):
            pass
    leagues = args or default_leagues()

    total_new, total_seen = 0, 0
    for lg in leagues:
        games = discover(lg, days, backwards=finals)
        if finals:
            games = [g for g in games if (g[3] or "").lower() == "post"]
        new = 0
        for gid, home, away, state, start_time in games:
            res = generate_game_story(lg, gid, home=home, away=away,
                                      state=state, start_time=start_time)
            if res.get("story") and not res.get("cached"):
                new += 1
        total_new += new; total_seen += len(games)
        kind = "finals" if finals else "games"
        print(f"[{lg}] {len(games)} {kind} discovered, {new} stories written")
    label = "recaps" if finals else "stories"
    print(f"DONE: {total_seen} games seen, {total_new} {label} cached")


if __name__ == "__main__":
    main()
