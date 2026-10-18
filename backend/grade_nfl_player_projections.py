#!/usr/bin/env python3
"""grade_nfl_player_projections.py -- grade player projections after their games are final (Spec B section 5).

Grades the 'base' scenario of every model_version in player_projections (v2, marcel-lite, espn-weekly).
For each (game, player, stat, model_version) the projection graded is the LAST run whose as_of is at or
before kickoff (nflverse gameday + gametime, America/New_York). A run written after kickoff is never
graded and is counted as 'late'. Reruns before kickoff refine; they never overwrite an earlier row.

A projection is conditional on the player playing. A player with no box-score line in the final game is
`played = 0`: stored, with no error, and left out of every error figure. Nobody is graded as a zero.
The error is actual - mean (positive = the projection was low). `in_band` is 1 when the actual lies inside
the row's p10 to p90 (v2 only; the other versions carry no band).

summary() reports, per stat, the mean absolute error and bias of each version over the SAME player-games
(those every compared version projected), so the versions are never scored on different samples.

Usage: LP_DB_PATH=... python3 grade_nfl_player_projections.py --season 2026 [--week 5] [--summary]
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

import pytz

ET = pytz.timezone("America/New_York")
LOG_KEY = {"tgt": "targets", "rec": "rec", "rec_yds": "rec_yds", "rec_td": "rec_td",
           "att": "att", "cmp": "cmp", "pass_yds": "pass_yds", "pass_td": "pass_td"}


def kickoff_utc(gameday, gametime):
    local = ET.localize(dt.datetime.strptime("%s %s" % (gameday, gametime or "13:00"), "%Y-%m-%d %H:%M"))
    return local.astimezone(pytz.utc).replace(tzinfo=None)


def _parse_as_of(text):
    value = dt.datetime.fromisoformat(text)
    if value.tzinfo is not None:
        value = value.astimezone(pytz.utc).replace(tzinfo=None)
    return value


def grade_week(con, season, week, now=None):
    now = now or dt.datetime.now(dt.timezone.utc).isoformat()
    stats = {"graded": 0, "dnp": 0, "late_only": 0, "games": 0}
    games = con.execute(
        "SELECT game_id, gameday, gametime FROM nfl_schedule WHERE season=? AND week=? AND game_type='REG' "
        "AND home_score IS NOT NULL AND away_score IS NOT NULL", (season, week)).fetchall()
    for gid, gameday, gametime in games:
        stats["games"] += 1
        kickoff = kickoff_utc(gameday, gametime)
        chosen = {}
        late = set()
        for r in con.execute(
                "SELECT run_id, player_id, stat, scenario, model_version, mean, p10, p90, as_of "
                "FROM player_projections WHERE league='nfl' AND game_id=? AND scenario='base'", (gid,)):
            key = (r[1], r[2], r[3], r[4])
            if _parse_as_of(r[8]) > kickoff:
                late.add(key)
                continue
            if key not in chosen or r[8] > chosen[key][8]:
                chosen[key] = r
        stats["late_only"] += len(late - set(chosen))
        logs = {pid: json.loads(s) for pid, s in con.execute(
            "SELECT player_id, stats FROM player_game_logs WHERE league='nfl' AND game_id=? "
            "AND source='nflverse_weekly'", (gid,))}
        now_ts = now
        for key, r in chosen.items():
            run_id, pid, stat, scenario, version, mean, p10, p90, _ = r
            line = logs.get(pid)
            if line is None:
                played, actual, error, abs_error, in_band = 0, None, None, None, None
            else:
                actual = float(line.get(LOG_KEY[stat]) or 0)
                played, error = 1, actual - mean
                abs_error = abs(error)
                in_band = None if p10 is None or p90 is None else int(p10 <= actual <= p90)
            cur = con.execute(
                "INSERT OR IGNORE INTO player_projection_grades (run_id, league, season, week, game_id, player_id, "
                "stat, scenario, model_version, mean, actual, error, abs_error, played, in_band, graded_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, "nfl", season, week, gid, pid, stat, scenario, version, mean, actual, error,
                 abs_error, played, in_band, now_ts))
            if cur.rowcount:
                stats["dnp" if not played else "graded"] += 1
    con.commit()
    return stats


def summary(con, season, week=None, versions=None):
    """{stat: {version: {n, mae, bias}}} over player-games every compared version projected and who played."""
    where = "league='nfl' AND season=? AND scenario='base' AND played=1"
    args = [season]
    if week is not None:
        where += " AND week=?"
        args.append(week)
    rows = con.execute(
        "SELECT stat, game_id, player_id, model_version, error, abs_error FROM player_projection_grades "
        "WHERE " + where, args).fetchall()
    versions = versions or sorted({r[3] for r in rows})
    by = {}
    for stat, g, p, v, err, ae in rows:
        if v in versions:
            by.setdefault(stat, {}).setdefault((g, p), {})[v] = (err, ae)
    out = {}
    for stat, cells in by.items():
        common = [c for c in cells.values() if all(v in c for v in versions)]
        out[stat] = {"n": len(common)}
        for v in versions:
            if common:
                out[stat][v] = {"mae": sum(c[v][1] for c in common) / len(common),
                                "bias": -sum(c[v][0] for c in common) / len(common)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int)
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect(path, timeout=30)
    weeks = [a.week] if a.week else [w for (w,) in con.execute(
        "SELECT DISTINCT week FROM player_projections WHERE season=? ORDER BY week", (a.season,))]
    for w in weeks:
        print("week %s: %s" % (w, grade_week(con, a.season, w)))
    if a.summary:
        for stat, res in sorted(summary(con, a.season, a.week).items()):
            print(stat, res)


if __name__ == "__main__":
    main()
