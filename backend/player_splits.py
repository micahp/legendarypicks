"""player_splits.py -- one player's games, split by whether named teammates played in them.

For player P, the universe is every final regular-season game of P's teams that P did not
provably miss: each game P logged, plus each scheduled game with no box-score line unless P's own
availability says he did not play. Each universe game is classified by the availability of each
teammate named in ``without`` (must be played = 0) and ``with_`` (must be played = 1), read from
player_game_availability. A game is:
  matched      every named teammate's status agrees with the filter
  not_matched  at least one teammate's known status contradicts the filter
  excluded     no known contradiction, but at least one teammate's status is unknown (NULL or no row)
not_teammate a named teammate never wore P's team this season, so the game says nothing about him
A scheduled game with no box-score line has no stats to show, so it is excluded and counted as unknown.
Excluded and not-teammate games are counted, never dropped silently, and never in either bucket.

Usage: LP_DB_PATH=... python3 player_splits.py --player-id 123 --without 456 [--with 789] [--season 2025]
"""
import argparse
import json
import os
import sqlite3
import sys

LEAGUE = "nfl"


def _player_games(con, league, player_id, season):
    sql = ("SELECT season, CAST(game_no AS INTEGER), game_id, team, stats FROM player_game_logs "
           "WHERE league=? AND player_id=? AND source='nflverse_weekly' "
           "AND (game_type='REG' OR game_type IS NULL) AND team IS NOT NULL")
    args = [league, player_id]
    if season is not None:
        sql += " AND season=?"
        args.append(season)
    return con.execute(sql + " ORDER BY season, CAST(game_no AS INTEGER)", args).fetchall()


def _shares(con, league, player_id, season):
    out = {}
    for game_id, team, metric, share in con.execute(
            "SELECT game_id, team, metric, share FROM player_game_shares "
            "WHERE league=? AND player_id=? AND season IS NOT NULL "
            "AND (? IS NULL OR season=?)", (league, player_id, season, season)):
        out.setdefault((game_id, team), {})[metric] = share
    return out


def _teams_this_season(con, league, season, player_id):
    teams = {t for (t,) in con.execute(
        "SELECT DISTINCT team FROM player_game_logs WHERE league=? AND season=? AND player_id=? "
        "AND team IS NOT NULL", (league, season, player_id))}
    teams |= {t for (t,) in con.execute(
        "SELECT DISTINCT team FROM player_game_availability WHERE league=? AND season=? "
        "AND player_id=?", (league, season, player_id))}
    return teams


def _scheduled_games(con, season, team):
    return con.execute(
        "SELECT CAST(week AS INTEGER), game_id FROM nfl_schedule WHERE season=? "
        "AND game_type='REG' AND home_score IS NOT NULL AND away_score IS NOT NULL "
        "AND (home_team=? OR away_team=?)", (season, team, team)).fetchall()


def _availability_seasons(con, league, player_id, season):
    sql = ("SELECT DISTINCT season FROM player_game_availability WHERE league=? AND player_id=?")
    args = [league, player_id]
    if season is not None:
        sql += " AND season=?"
        args.append(season)
    return {s for (s,) in con.execute(sql, args)}


def _played(con, league, season, game_id, team, teammates):
    if not teammates:
        return {}
    marks = ",".join("?" * len(teammates))
    found = {pid: played for pid, played in con.execute(
        "SELECT player_id, played FROM player_game_availability "
        "WHERE league=? AND season=? AND game_id=? AND team=? AND player_id IN (%s)" % marks,
        (league, season, game_id, team, *teammates))}
    return {pid: found.get(pid) for pid in teammates}


def splits(con, player_id, without=(), with_=(), season=None, league=LEAGUE):
    without, with_ = list(without), list(with_)
    teammates = without + with_
    shares = _shares(con, league, player_id, season)
    result = {"player_id": player_id, "league": league, "season": season,
              "without": without, "with": with_,
              "matched": [], "not_matched": [], "excluded_unknown": 0, "excluded_not_teammate": 0,
              "excluded_unknown_games": [], "excluded_not_teammate_games": []}
    logged = _player_games(con, league, player_id, season)
    logged_keys = {(s, game_id, team) for s, _week, game_id, team, _stats in logged}
    universe = [(s, week, game_id, team, stats) for s, week, game_id, team, stats in logged]
    for season_ in sorted({s for s, *_ in logged} | _availability_seasons(con, league, player_id, season)):
        for team in sorted(_teams_this_season(con, league, season_, player_id)):
            for week, game_id in _scheduled_games(con, season_, team):
                if (season_, game_id, team) in logged_keys:
                    continue
                if _played(con, league, season_, game_id, team, [player_id])[player_id] == 0:
                    continue
                universe.append((season_, week, game_id, team, None))
    teams = {}
    for season_, week, game_id, team, stats in sorted(universe, key=lambda r: (r[0], r[1])):
        for x in teammates:
            if (season_, x) not in teams:
                teams[(season_, x)] = _teams_this_season(con, league, season_, x)
        if any(teams[(season_, x)] and team not in teams[(season_, x)] for x in teammates):
            result["excluded_not_teammate"] += 1
            result["excluded_not_teammate_games"].append(game_id)
            continue
        if stats is None:
            result["excluded_unknown"] += 1
            result["excluded_unknown_games"].append(game_id)
            continue
        status = _played(con, league, season_, game_id, team, teammates)
        row = {"season": season_, "week": week, "game_id": game_id, "team": team,
               "stats": json.loads(stats), "shares": shares.get((game_id, team), {}),
               "teammates": status}
        contradicted = (any(status[x] == 1 for x in without) or
                        any(status[x] == 0 for x in with_))
        unknown = any(status[x] is None for x in teammates)
        if contradicted:
            result["not_matched"].append(row)
        elif unknown:
            result["excluded_unknown"] += 1
            result["excluded_unknown_games"].append(game_id)
        else:
            result["matched"].append(row)
    return result


def game_status(con, player_id, without=(), with_=(), season=None, league=LEAGUE):
    """game_id -> 'matched' | 'not_matched' | 'unknown' | 'not_teammate' for one player's games.

    One reading of ``splits()`` so a caller that filters its own rows (the props history
    routes) never re-implements "did X play". A game_id absent from the map is outside the
    player's universe (a game he provably missed, or not a final regular-season game).
    """
    res = splits(con, player_id, without=without, with_=with_, season=season, league=league)
    out = {}
    for key, rows in (("matched", res["matched"]), ("not_matched", res["not_matched"])):
        for row in rows:
            out[row["game_id"]] = key
    for gid in res["excluded_unknown_games"]:
        out[gid] = "unknown"
    for gid in res["excluded_not_teammate_games"]:
        out[gid] = "not_teammate"
    return out


def prop_game_nfl_ids(con, prop_game_ids):
    """prop_games.id -> nflverse game_id, joined on (date, home, away) to nfl_schedule.

    A prop game with no regular-season schedule row (preseason) is absent from the map.
    """
    ids = list(prop_game_ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {pg: gid for pg, gid in con.execute(
        "SELECT g.id, s.game_id FROM prop_games g JOIN nfl_schedule s "
        "ON s.gameday=g.date AND s.home_team=g.home AND s.away_team=g.away "
        "WHERE g.league='nfl' AND g.id IN (%s)" % marks, ids)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--player-id", type=int, required=True)
    ap.add_argument("--without", default="", help="comma-separated teammate ids who must be out")
    ap.add_argument("--with", dest="with_", default="", help="comma-separated teammate ids who must play")
    ap.add_argument("--season", type=int)
    args = ap.parse_args(argv)
    db_path = os.environ.get("LP_DB_PATH")
    if not db_path:
        raise SystemExit("LP_DB_PATH is required")
    ids = lambda s: [int(x) for x in s.split(",") if x.strip()]
    con = sqlite3.connect(db_path)
    res = splits(con, args.player_id, ids(args.without), ids(args.with_), args.season)
    print("player %d, without %s, with %s, season %s" % (
        args.player_id, res["without"], res["with"], args.season or "all"))
    print("matched %d, not matched %d, excluded unknown %d, excluded not-teammate %d" % (
        len(res["matched"]), len(res["not_matched"]), res["excluded_unknown"],
        res["excluded_not_teammate"]))
    for bucket in ("matched", "not_matched"):
        for r in res[bucket]:
            print("  %-11s %s w%02d %s %s %s" % (bucket, r["season"], r["week"], r["game_id"],
                                              r["team"], json.dumps(r["stats"], sort_keys=True)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
