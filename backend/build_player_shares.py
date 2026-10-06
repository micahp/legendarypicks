"""build_player_shares.py -- each player's share of his team's opportunity, per season.

One table for every league: (league, season, team, player_id, metric) -> the player's total,
the team's total, and the share. A team sport's version of "who gets the ball": NFL targets,
air yards, carries and touchdowns now; NBA usage, NHL ice time and MLB plate appearances slot
into the same rows later. Information for whoever reads it (the trading agents' game context,
a future LP fantasy view), never a rule.

NFL source: player_game_logs rows from nflverse's weekly box score (ingest_nfl_weekly_stats.py),
regular season only. A share here is the player's season SUM over the team's season SUM of the
same published count, by the team he played for in each game (a traded player gets one row per
team). nflverse publishes target_share per GAME, not per season; the season figure is this sum
ratio, not an average of weekly shares.

Usage: python3 build_player_shares.py --league nfl|nhl --season 2026 [--dry-run]
       (NHL season = LP's key, the season's end year: 2027 for 2026-27)
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# metric -> how to read it from one NFL log row's stats JSON
NFL_METRICS = {
    "targets": lambda s: s.get("targets"),
    "air_yards": lambda s: s.get("rec_air_yds"),
    "carries": lambda s: s.get("carries"),
    "rec_td": lambda s: s.get("rec_td"),
    "rush_td": lambda s: s.get("rush_td"),
    # Scrimmage touchdowns: the receiving and rushing TDs the team's skill players scored.
    "scrimmage_td": lambda s: (None if s.get("rec_td") is None and s.get("rush_td") is None
                               else (s.get("rec_td") or 0) + (s.get("rush_td") or 0)),
}


def _toi_seconds(value):
    try:
        m, sec = str(value).split(":")
        return int(m) * 60 + int(sec)
    except (TypeError, ValueError):
        return None


def nhl_shares(con, season):
    """NHL rows from nhle.com box-score logs (LP season key = the season's end year, regular
    season). Skaters: shots on goal, goals, points as shares of the team's totals, and ice time
    as a share of the team's GAME time (its goalies' summed ice time, overtime included), so
    0.41 reads "on the ice for 41% of the game". Goalies: starts out of the team's games."""
    player, team, games, team_games, through = {}, {}, {}, {}, {}
    for player_id, team_code, game_no, game_id, stats in con.execute(
            "SELECT player_id, team, game_no, game_id, stats FROM player_game_logs "
            "WHERE league='nhl' AND season=? AND (game_type='REG' OR game_type IS NULL) "
            "AND team IS NOT NULL", (season,)):
        s = json.loads(stats)
        team_games.setdefault(team_code, set()).add(game_id)
        through[team_code] = max(through.get(team_code, ""), str(game_no))
        toi = _toi_seconds(s.get("toi"))
        goalie = "savePctg" in s or "saves" in s
        values = ({"goalie_starts": 1 if s.get("starter") else 0} if goalie else
                  {"toi": toi, "sog": s.get("sog", s.get("shots")), "goals": s.get("goals"),
                   "points": s.get("points")})
        if goalie and toi is not None:
            team[(team_code, "toi")] = team.get((team_code, "toi"), 0) + toi
        for metric, v in values.items():
            if v is None:
                continue
            if metric not in ("toi", "goalie_starts"):
                team[(team_code, metric)] = team.get((team_code, metric), 0) + v
            if player_id is not None:
                key = (team_code, player_id, metric)
                player[key] = player.get(key, 0) + v
        if player_id is not None:
            games.setdefault((team_code, player_id), set()).add(game_id)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    out = []
    for (team_code, player_id, metric), value in player.items():
        if not value:
            continue
        total = (len(team_games[team_code]) if metric == "goalie_starts"
                 else team.get((team_code, metric), 0))
        out.append(("nhl", season, team_code, player_id, metric, value, total,
                    value / total if total else None,
                    len(games[(team_code, player_id)]), len(team_games[team_code]),
                    through[team_code], "nhle.com", now))
    return out


def ensure_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS player_team_shares (
            league       TEXT NOT NULL,
            season       INTEGER NOT NULL,
            team         TEXT NOT NULL,
            player_id    INTEGER NOT NULL,
            metric       TEXT NOT NULL,
            player_value REAL NOT NULL,
            team_value   REAL NOT NULL,
            share        REAL,              -- NULL when the team total is 0
            games        INTEGER NOT NULL,  -- games this player logged for this team
            team_games   INTEGER NOT NULL,  -- games the team has logged
            through      TEXT,              -- last game_no included
            source       TEXT NOT NULL,
            computed_at  TEXT NOT NULL,
            PRIMARY KEY (league, season, team, player_id, metric)
        )""")


def nfl_shares(con, season):
    """Rows for player_team_shares from the season's regular-season NFL logs."""
    player, team, games, team_games, through = {}, {}, {}, {}, {}
    for player_id, team_code, game_no, game_id, stats in con.execute(
            "SELECT player_id, team, game_no, game_id, stats FROM player_game_logs "
            "WHERE league='nfl' AND season=? AND source='nflverse_weekly' "
            "AND (game_type='REG' OR game_type IS NULL) AND team IS NOT NULL", (season,)):
        s = json.loads(stats)
        team_games.setdefault(team_code, set()).add(game_id)
        through[team_code] = max(through.get(team_code, 0), int(game_no))
        for metric, read in NFL_METRICS.items():
            v = read(s)
            if v is None:
                continue
            team[(team_code, metric)] = team.get((team_code, metric), 0) + v
            if player_id is not None:
                key = (team_code, player_id, metric)
                player[key] = player.get(key, 0) + v
        if player_id is not None:
            games.setdefault((team_code, player_id), set()).add(game_id)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    out = []
    for (team_code, player_id, metric), value in player.items():
        if not value:               # a defender's zero targets is not a share worth a row
            continue
        total = team[(team_code, metric)]
        out.append(("nfl", season, team_code, player_id, metric, value, total,
                    value / total if total else None,
                    len(games[(team_code, player_id)]), len(team_games[team_code]),
                    str(through[team_code]), "nflverse_weekly", now))
    return out


def write(con, league, season, rows):
    """Replace one league-season: a player who left the logs leaves the table."""
    ensure_table(con)
    con.execute("DELETE FROM player_team_shares WHERE league=? AND season=?", (league, season))
    con.executemany("INSERT INTO player_team_shares VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="nfl", choices=["nfl", "nhl"])
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    con = sqlite3.connect(DB, timeout=60)
    rows = (nhl_shares if args.league == "nhl" else nfl_shares)(con, args.season)
    teams = {r[2] for r in rows}
    print("player_team_shares %s %d: %d rows, %d teams, %d players" % (
        args.league, args.season, len(rows), len(teams), len({(r[2], r[3]) for r in rows})))
    if not rows:
        print("  no logs for this season; nothing written")
        return 1
    if args.dry_run:
        print("  dry run: nothing written")
        return 0
    write(con, args.league, args.season, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
