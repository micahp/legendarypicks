#!/usr/bin/env python3
"""Refresh recent NBA player game logs from ESPN.

Fetches and validates the complete date range before opening SQLite for one short
transaction. ESPN athlete ids resolve onto the existing players spine; unresolved ids
are queued for review and never create player records.

Usage: python3 ingest_nba_logs.py --recent-days 14
       python3 ingest_nba_logs.py --start 2026-10-01 --end 2026-10-14
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn
from game_types import espn_event_phase
from ingest_nfl_logs import ensure_table
from league_stats import load_unique_source_id_map, queue_unresolved_player

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)


def _madeatt(value):
    """Parse ESPN's made-attempted strings, such as ``3-5``."""
    try:
        made, attempted = str(value).split("-", 1)
        return int(made), int(attempted)
    except (TypeError, ValueError):
        return None, None


def _minutes(value):
    try:
        if ":" in str(value):
            minutes, seconds = str(value).split(":", 1)
            return round(int(minutes) + int(seconds) / 60, 3)
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_line(names, values, did_not_play=False):
    """Return only published stats; zero values are valid only for explicit DNPs."""
    if did_not_play:
        return {
            "PTS": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0, "TO": 0,
            "MIN": 0, "3PM": 0, "FGM": 0, "FGA": 0, "FTM": 0, "FTA": 0,
            "PRA": 0,
        }

    data = dict(zip(names or (), values or ()))

    def integer(key):
        raw = data.get(key)
        try:
            return int(raw) if str(raw).lstrip("-+").isdigit() else None
        except (TypeError, ValueError):
            return None

    fg3m, _ = _madeatt(data.get("3PT"))
    fgm, fga = _madeatt(data.get("FG"))
    ftm, fta = _madeatt(data.get("FT"))
    line = {
        "PTS": integer("PTS"), "REB": integer("REB"), "AST": integer("AST"),
        "STL": integer("STL"), "BLK": integer("BLK"), "TO": integer("TO"),
        "MIN": _minutes(data.get("MIN")), "3PM": fg3m,
        "FGM": fgm, "FGA": fga, "FTM": ftm, "FTA": fta,
    }
    if all(line[key] is not None for key in ("PTS", "REB", "AST")):
        line["PRA"] = line["PTS"] + line["REB"] + line["AST"]
    return {key: value for key, value in line.items() if value is not None}


def nba_start_year(day):
    """NBA season key per DATA-COVERAGE-CONTRACT: the season's start year."""
    return day.year if day.month >= 7 else day.year - 1


def _fetch_range(start, end):
    """Fetch all final boxscores first; any source error aborts before DB access."""
    d0 = dt.datetime.strptime(start, "%Y-%m-%d").date()
    d1 = dt.datetime.strptime(end, "%Y-%m-%d").date()
    if d1 < d0:
        raise ValueError("end date precedes start date")

    fetched = []
    day = d0
    while day <= d1:
        date_string = day.isoformat()
        # A postponed game may carry state='post' and a 0-0 score. Only the
        # publisher's completed flag establishes that a game was played.
        games = [game for game in espn.games("nba", date_string)
                 if game.get("completed") is True]
        date_games = []
        for game in games:
            game_id = game.get("game_id")
            if game_id in (None, ""):
                raise ValueError("ESPN returned a completed NBA game without game_id")
            boxscore = espn.boxscore("nba", str(game_id))
            if (not isinstance(boxscore, dict)
                    or not isinstance(boxscore.get("players"), list)
                    or not boxscore["players"]):
                raise ValueError("ESPN returned a malformed boxscore for game {}".format(game_id))
            if not any(
                stats.get("athletes")
                for team in boxscore["players"]
                for stats in team.get("statistics", [])
            ):
                raise ValueError("ESPN returned no NBA player lines for game {}".format(game_id))
            date_games.append((game, boxscore, day))
            time.sleep(0.05)
        fetched.extend(date_games)
        print("  {}: {} final games fetched".format(date_string, len(date_games)))
        day += dt.timedelta(days=1)
    return fetched


def ingest(start: str, end: str, season=None, dry_run=False) -> int:
    fetched = _fetch_range(start, end)
    if dry_run:
        candidates = 0
        for _game, boxscore, _day in fetched:
            for block in boxscore["players"]:
                for stats_block in block.get("statistics", []):
                    for athlete_row in stats_block.get("athletes", []):
                        if _parse_line(
                            stats_block.get("names", []), athlete_row.get("stats", []),
                            did_not_play=athlete_row.get("didNotPlay") is True,
                        ):
                            candidates += 1
        print("Dry run: fetched {} final games and {} candidate player lines; DB untouched".format(
            len(fetched), candidates
        ))
        return candidates

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        ensure_table(con)
        espn_to_player, ambiguous_ids = load_unique_source_id_map(
            con, league="nba", id_column="espn_id"
        )
        con.execute("BEGIN IMMEDIATE")
        ingested = resolved = queued = 0
        queued_ids = set()
        for game, boxscore, day in fetched:
            game_id = str(game["game_id"])
            date_string = day.isoformat()
            phase = espn_event_phase("nba", game)
            home_abbrev = (game.get("home") or {}).get("abbrev", "")
            away_abbrev = (game.get("away") or {}).get("abbrev", "")
            for block in boxscore["players"]:
                team = (block.get("team") or {}).get("abbreviation")
                if team and home_abbrev and away_abbrev:
                    if team.upper() == home_abbrev.upper():
                        opponent, home_away = away_abbrev, "home"
                    elif team.upper() == away_abbrev.upper():
                        opponent, home_away = home_abbrev, "away"
                    else:
                        opponent, home_away = None, None
                else:
                    opponent, home_away = None, None

                for stats_block in block.get("statistics", []):
                    names = stats_block.get("names", [])
                    for athlete_row in stats_block.get("athletes", []):
                        athlete = athlete_row.get("athlete") or {}
                        raw_id = athlete.get("id")
                        if raw_id is None:
                            continue
                        source_id = str(raw_id)
                        explicit_dnp = athlete_row.get("didNotPlay") is True
                        stats = _parse_line(
                            names, athlete_row.get("stats", []),
                            did_not_play=explicit_dnp,
                        )
                        # Empty/malformed stat lines without explicit DNP evidence
                        # remain unknown and are not turned into zeros.
                        if not stats:
                            continue
                        player_id = espn_to_player.get(source_id)
                        if player_id is None:
                            if source_id in queued_ids:
                                continue
                            queued_ids.add(source_id)
                            queue_unresolved_player(
                                con,
                                source="espn_boxscore",
                                raw_name=athlete.get("displayName") or "espn_{}".format(source_id),
                                league="nba",
                                team=team,
                                source_player_key=source_id,
                                reason=("duplicate_spine_espn_id" if source_id in ambiguous_ids
                                        else "espn_id_not_in_spine"),
                            )
                            queued += 1
                            continue

                        row_season = season if season is not None else nba_start_year(day)
                        con.execute(
                            """INSERT INTO player_game_logs
                               (player_id, league, season, game_no, game_id, game_date, team,
                                opponent, home_away, stats, source, source_player_key, game_type)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                               ON CONFLICT(league, source_player_key, season, game_no)
                               DO UPDATE SET player_id=excluded.player_id,
                                 game_id=excluded.game_id, game_date=excluded.game_date,
                                 team=excluded.team, opponent=excluded.opponent,
                                 home_away=excluded.home_away, stats=excluded.stats,
                                 source=excluded.source, game_type=excluded.game_type""",
                            (player_id, "nba", row_season, date_string, game_id,
                             date_string, team, opponent, home_away, json.dumps(stats),
                             "espn", source_id, phase),
                        )
                        resolved += 1
                        ingested += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    print("Done. {} NBA player-game rows ({}, {} unresolved queued)".format(
        ingested, resolved, queued
    ))
    return ingested


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--recent-days", type=int)
    parser.add_argument("--season", type=int,
                        help="override the start-year season key for every fetched date")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and parse, but do not open or write the database")
    args = parser.parse_args(argv)

    today = dt.date.today()
    if args.recent_days is not None:
        if args.recent_days < 1 or args.start or args.end:
            parser.error("--recent-days must be positive and cannot be combined with --start/--end")
        end = today.isoformat()
        start = (today - dt.timedelta(days=args.recent_days - 1)).isoformat()
    elif args.start or args.end:
        if not args.start or not args.end:
            parser.error("--start and --end must be supplied together")
        start, end = args.start, args.end
    else:
        parser.error("supply --recent-days or both --start and --end")

    ingest(start, end, season=args.season, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
