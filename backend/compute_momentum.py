#!/usr/bin/env python3
"""
compute_momentum.py — nightly momentum state from game logs (SPEC-momentum-engine.md).

Runs analytics/momentum.py cross_state over every (entity, stat) series and
materializes current state (momentum_state, upsert) plus the append-only cross
event log (momentum_crosses — the alert feed and the backtest record). Series
stay derivable from player_game_logs / team_game_results; only state is stored.

Stat polarity: state is always the RAW direction of the stat (hot = rising).
`improving` applies polarity (a batter whose K series is hot is NOT improving).

Windows: batters/teams 5/26 (long-season default); pitchers 3/10 (starters get
~16 starts by midseason — a 26-start slow window would mute the whole season).

Usage: python3 compute_momentum.py [--league mlb]
"""
import sys, os, json, sqlite3, argparse, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analytics.momentum import cross_state

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# (stat key in the JSON/table, polarity: +1 more is better, -1 less is better)
MLB_BATTER_STATS = [("TB", 1), ("H", 1), ("HR", 1), ("BB", 1), ("K", -1)]
MLB_PITCHER_STATS = [("K", 1), ("outs", 1), ("hits_allowed", -1)]
TEAM_STATS = [("score_for", 1), ("score_diff", 1), ("win", 1)]

BATTER_WINDOWS = (5, 26)
PITCHER_WINDOWS = (3, 10)
TEAM_WINDOWS = (5, 26)


def ensure_tables(con):
    con.execute("""CREATE TABLE IF NOT EXISTS momentum_state(
        league TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
        entity_name TEXT, stat TEXT NOT NULL, season INTEGER,
        n_games INTEGER, fast REAL, slow REAL, spread REAL, spread_pct REAL,
        state TEXT, improving INTEGER,
        crossed_at TEXT, games_since_cross INTEGER, last_cross_direction TEXT,
        last_game_date TEXT, windows TEXT, computed_at TEXT,
        PRIMARY KEY(league, entity_type, entity_id, stat))""")
    con.execute("""CREATE TABLE IF NOT EXISTS momentum_crosses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
        entity_name TEXT, stat TEXT NOT NULL, direction TEXT NOT NULL,
        cross_date TEXT, fast REAL, slow REAL,
        detected_at TEXT DEFAULT (datetime('now')),
        UNIQUE(league, entity_type, entity_id, stat, cross_date, direction))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_mc_feed ON momentum_crosses(league, cross_date)")


def _persist(con, league, etype, eid, ename, stat, polarity, season,
             dates, values, fast_n, slow_n, now):
    r = cross_state(values, fast_n, slow_n)
    if r is None:
        return 0
    improving = 1 if (r["spread"] > 0) == (polarity > 0) and r["spread"] != 0 else 0
    crossed_at = dates[r["crosses"][-1]["idx"]] if r["crosses"] else None
    con.execute("""INSERT OR REPLACE INTO momentum_state
        (league, entity_type, entity_id, entity_name, stat, season, n_games,
         fast, slow, spread, spread_pct, state, improving,
         crossed_at, games_since_cross, last_cross_direction,
         last_game_date, windows, computed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (league, etype, str(eid), ename, stat, season, r["n"],
         r["fast"], r["slow"], r["spread"], r["spread_pct"], r["state"], improving,
         crossed_at, r["games_since_cross"], r["last_cross_direction"],
         dates[-1], f"{fast_n}/{slow_n}", now))
    for c in r["crosses"]:
        con.execute("""INSERT OR IGNORE INTO momentum_crosses
            (league, entity_type, entity_id, entity_name, stat, direction, cross_date, fast, slow)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (league, etype, str(eid), ename, stat, c["direction"],
             dates[c["idx"]], c["fast"], c["slow"]))
    return 1


def compute_players(con, league: str, season: int, now: str) -> int:
    rows = con.execute("""
        SELECT l.player_id, p.name, l.game_date, l.stats
        FROM player_game_logs l JOIN players p ON p.id = l.player_id
        WHERE l.league = ? AND l.season = ? AND l.player_id IS NOT NULL
          AND l.game_date IS NOT NULL
        ORDER BY l.player_id, l.game_date""", (league, season)).fetchall()
    by_player = {}
    for pid, name, gdate, stats_json in rows:
        by_player.setdefault(pid, {"name": name, "games": []})["games"].append(
            (gdate, json.loads(stats_json)))
    written = 0
    for pid, rec in by_player.items():
        batter = [(d, s) for d, s in rec["games"] if "PA" in s]
        pitcher = [(d, s) for d, s in rec["games"] if "outs" in s]
        for games, stat_defs, (fn, sn) in (
                (batter, MLB_BATTER_STATS, BATTER_WINDOWS),
                (pitcher, MLB_PITCHER_STATS, PITCHER_WINDOWS)):
            if len(games) < sn:
                continue
            dates = [d for d, _ in games]
            for stat, pol in stat_defs:
                vals = [float(s.get(stat) or 0) for _, s in games]
                written += _persist(con, league, "player", pid, rec["name"],
                                    stat, pol, season, dates, vals, fn, sn, now)
    return written


def compute_teams(con, league: str, season: int, now: str) -> int:
    rows = con.execute("""
        SELECT team, game_date, score_for, score_against, win
        FROM team_game_results WHERE league = ?
        ORDER BY team, game_date""", (league,)).fetchall()
    by_team = {}
    for team, gdate, sf, sa, win in rows:
        by_team.setdefault(team, []).append((gdate, sf, sa, win))
    fn, sn = TEAM_WINDOWS
    written = 0
    for team, games in by_team.items():
        if len(games) < sn:
            continue
        dates = [g[0] for g in games]
        series = {
            "score_for": [g[1] for g in games],
            "score_diff": [g[1] - g[2] for g in games],
            "win": [float(g[3] or 0) for g in games],
        }
        for stat, pol in TEAM_STATS:
            written += _persist(con, league, "team", team, team,
                                stat, pol, season, dates, series[stat], fn, sn, now)
    return written


def main(league: str = "mlb"):
    season = dt.date.today().year
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = sqlite3.connect(DB)
    ensure_tables(con)
    np = compute_players(con, league, season, now)
    nt = compute_teams(con, league, season, now)
    con.commit()
    hot = con.execute("SELECT COUNT(*) FROM momentum_state WHERE league=? AND improving=1", (league,)).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM momentum_state WHERE league=?", (league,)).fetchone()[0]
    crosses = con.execute("SELECT COUNT(*) FROM momentum_crosses WHERE league=?", (league,)).fetchone()[0]
    con.close()
    print(f"{league}: {np} player states + {nt} team states written "
          f"({total} total, {hot} improving); {crosses} cross events on record")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="mlb")
    args = ap.parse_args()
    main(args.league)
