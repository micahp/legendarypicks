#!/usr/bin/env python3
"""
ingest_nhl_logs.py — per-GAME NHL logs from api-web.nhle.com game-log endpoint.

The season-aggregate ingest (ingest_nhl.py) uses the /landing seasonTotals
endpoint. This uses /v1/player/{id}/game-log/{season}/{gameType} which returns
one row per game — goals, assists, points, shots, PP points, TOI, opponent.

Usage: python3 ingest_nhl_logs.py [--season 20252026] [--game-types 2,3] [--limit N]
"""
import sys, os, json, sqlite3, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_nfl_logs import ensure_table
from team_codes import normalize
from season_keys import normalize_season
from game_types import normalize_game_type, verify_nhl_phase

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
HDR = {"User-Agent": "Mozilla/5.0 (legendarypicks ingest)"}
STAT_KEYS = ["goals", "assists", "points", "shots", "plusMinus", "powerPlayGoals",
             "powerPlayPoints", "shorthandedPoints", "pim", "toi"]

# Every key above describes a skater, so a goaltender's game read
# {"goals": 0, "assists": 0, "pim": 0, "toi": "60:00"} -- 60 minutes of doing
# nothing. These are the goalie keys the same endpoint publishes alongside
# them, and they cost no extra request.
GOALIE_STAT_KEYS = ["shotsAgainst", "goalsAgainst", "savePctg", "decision",
                    "shutouts", "gamesStarted"]


def fetch_game_log(nhl_id: int, season: str, game_type: int):
    """(published gameTypeId, rows). The id is READ BACK, never assumed.

    It is tempting to stamp `game_type` from the `game_type` argument, since it
    is a path segment in the URL below and therefore "obviously" what came back.
    That is the ingest describing its own request, not its data — the same
    mistake as `team_stats_coverage.source` recording the provenance of the
    verdict instead of the provenance of the rows. The envelope publishes
    `gameTypeId`; use it, and a publisher that ever answers a different phase
    than the one asked for becomes visible instead of mislabelled.
    """
    url = f"https://api-web.nhle.com/v1/player/{nhl_id}/game-log/{season}/{game_type}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=12) as r:
            doc = json.loads(r.read())
            return doc.get("gameTypeId"), doc.get("gameLog", [])
    except Exception:
        return None, []


def ingest(season: str = "20252026", limit: int = 0, game_types=(2, 3),
           positions=None) -> int:
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    ensure_table(con)

    # `positions` narrows the pull to one player type -- one request per player
    # per game type, so refreshing only the 90 goalies is 180 requests instead
    # of 1,748. Upstream is a courtesy, not a resource.
    query = ("SELECT id, name, nhl_id FROM players "
             "WHERE league='nhl' AND nhl_id IS NOT NULL")
    params = []
    if positions:
        wanted = [str(p).strip().upper() for p in positions]
        query += (" AND upper(COALESCE(position,'')) IN "
                  f"({','.join('?' for _ in wanted)})")
        params = wanted
    players = con.execute(query + " ORDER BY id", params).fetchall()
    if limit:
        players = players[:limit]
    print(f"NHL game-logs {season} types={list(game_types)}"
          f"{' positions=' + ','.join(positions) if positions else ''}: "
          f"{len(players)} players to pull")

    # `season` stays in nhle's vocabulary — it is a path segment in their URL
    # above. What we STORE is ESPN's key, translated once, here at the boundary.
    # It was `int(season)`, which put "20252026" in a column where every other
    # league holds a plain year, and made `WHERE season=2026` return nothing for
    # a season we had complete.
    season_int = normalize_season("nhle.com", "nhl", season)
    ingested = 0
    dates_by_phase = {}
    for game_type in game_types:
        for i, p in enumerate(players):
            published_type, log = fetch_game_log(p["nhl_id"], season, game_type)
            phase = normalize_game_type("nhle.com", "nhl", published_type) if log else None
            for g in log:
                stats = {}
                for k in STAT_KEYS + GOALIE_STAT_KEYS:
                    v = g.get(k)
                    if v is not None:
                        stats[k] = v
                # INTERIM, and marked as such. `saves` is published per game --
                # gamecenter/{gameId}/boxscore carries it directly, along with
                # blockedShots, hits, takeaways and giveaways for every skater.
                # This endpoint publishes none of those, so the value below is
                # arithmetic over two published numbers, not a read of the
                # published one. It agrees with the publisher where checked
                # (game 2025021269: boxscore saves 26, shotsAgainst 27, goals
                # against 1) -- but "agrees where checked" is not "is the
                # published value", and a game can have more than one goalie,
                # which is exactly where a derivation earns its mistakes.
                #
                # `saves_derived` marks every such row so the boxscore ingest
                # can find and replace them. Do not widen this pattern.
                if stats.get("shotsAgainst") is not None and \
                        stats.get("goalsAgainst") is not None:
                    stats["saves"] = int(stats["shotsAgainst"]) - int(stats["goalsAgainst"])
                    stats["saves_derived"] = True
                con.execute(
                    """INSERT OR REPLACE INTO player_game_logs
                       (player_id, league, season, game_no, game_id, game_date, team,
                        opponent, home_away, game_type, stats, source, source_player_key)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (p["id"], "nhl", season_int, str(g.get("gameId")), str(g.get("gameId")),
                     g.get("gameDate"),
                     normalize("nhl", g.get("teamAbbrev")) if g.get("teamAbbrev") else None,
                     normalize("nhl", g.get("opponentAbbrev")) if g.get("opponentAbbrev") else None,
                     "home" if g.get("homeRoadFlag") == "H" else "away",
                     phase,
                     json.dumps(stats), "nhle.com", str(p["nhl_id"])))
                dates_by_phase.setdefault(phase, set()).add(g.get("gameDate"))
                ingested += 1
            if (i + 1) % 50 == 0:
                con.commit(); print(f"  type {game_type}: {i+1}/{len(players)} players, {ingested} logs")
            time.sleep(0.05)

    con.commit()
    print(f"  Ingested {ingested} NHL game-logs")

    # The stamp is a claim; check it against the NHL's own calendar before anyone
    # builds a denominator on it. One request, at the end of a run that already
    # made a thousand.
    for phase, dates in sorted(dates_by_phase.items()):
        try:
            problem = verify_nhl_phase(season, phase, dates)
        except Exception as e:
            print(f"  PHASE {phase}: unverified ({e})")
            continue
        print(f"  PHASE {phase}: {len(dates)} distinct dates — "
              + (problem or "all inside the published window"))

    con.close()
    return ingested


if __name__ == "__main__":
    season = "20252026"
    if "--season" in sys.argv:
        season = sys.argv[sys.argv.index("--season") + 1]
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    # Both phases by default. It was 2 alone, hardcoded in the URL, and that is how
    # a full postseason went missing without a single count looking wrong: the phase
    # column was uniformly REG, which is indistinguishable from complete.
    types = (2, 3)
    if "--game-types" in sys.argv:
        types = tuple(int(x) for x in sys.argv[sys.argv.index("--game-types") + 1].split(","))
    positions = None
    if "--positions" in sys.argv:
        positions = [p for p in
                     sys.argv[sys.argv.index("--positions") + 1].split(",") if p]
    ingest(season, limit, types, positions)
