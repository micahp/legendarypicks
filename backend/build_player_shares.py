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

Usage: python3 build_player_shares.py --league nfl --season 2026 [--dry-run]
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
    ap.add_argument("--league", default="nfl", choices=["nfl"])
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    con = sqlite3.connect(DB, timeout=60)
    rows = nfl_shares(con, args.season)
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
