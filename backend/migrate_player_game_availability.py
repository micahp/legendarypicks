#!/usr/bin/env python3
"""Create and build the NFL player game availability fact table.

The row universe comes only from canonical player ids in ``nfl_snap_counts``
and ``injury_reports``. ``nfl_schedule`` supplies the published game id and
final score state; it never supplies player presence.
"""

import argparse
from datetime import datetime, timezone
import os
import sqlite3


TABLE = "player_game_availability"
SOURCE_SNAPS = "nflverse_snap_counts"
SOURCE_INJURIES = "nflverse_injuries"

REQUIRED_INPUT_COLUMNS = {
    "nfl_snap_counts": {
        "player_id", "season", "week", "team", "off_snaps", "off_pct",
        "def_snaps", "def_pct", "st_snaps",
    },
    "injury_reports": {
        "league", "season", "week", "team", "player_id", "report_status",
    },
    "nfl_schedule": {
        "game_id", "season", "week", "home_team", "away_team",
        "home_score", "away_score",
    },
}


def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _require_inputs(connection):
    for table, required in REQUIRED_INPUT_COLUMNS.items():
        actual = _columns(connection, table)
        missing = sorted(required - actual)
        if missing:
            raise RuntimeError(
                f"{table} is missing required columns: {', '.join(missing)}"
            )


def migrate(connection):
    """Create the availability table and indexes. Safe to run repeatedly."""
    connection.execute(
        f"""CREATE TABLE IF NOT EXISTS {TABLE} (
            league TEXT NOT NULL,
            season INTEGER NOT NULL,
            week INTEGER NOT NULL,
            game_id TEXT NOT NULL,
            team TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            played INTEGER CHECK (played IN (0, 1) OR played IS NULL),
            off_snaps INTEGER,
            off_pct REAL,
            def_snaps INTEGER,
            def_pct REAL,
            st_snaps INTEGER,
            report_status TEXT,
            reason TEXT NOT NULL CHECK (
                reason IN ('injury_out', 'inactive_no_report', 'played', 'unknown')
            ),
            source TEXT NOT NULL,
            built_at TEXT NOT NULL,
            PRIMARY KEY (league, game_id, team, player_id)
        )"""
    )
    expected = {
        "league", "season", "week", "game_id", "team", "player_id",
        "played", "off_snaps", "off_pct", "def_snaps", "def_pct",
        "st_snaps", "report_status", "reason", "source", "built_at",
    }
    actual = _columns(connection, TABLE)
    if actual != expected:
        raise RuntimeError(
            f"{TABLE} schema mismatch: expected {sorted(expected)}, got {sorted(actual)}"
        )
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_pga_player_season "
        f"ON {TABLE}(league, player_id, season, week)"
    )
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_pga_team_game "
        f"ON {TABLE}(league, team, season, week)"
    )


def _where_season(alias, season):
    if season is None:
        return "", ()
    return f" WHERE {alias}.season=?", (season,)


def build(connection, season=None):
    """Exact-refresh NFL availability rows and return reconciliation counts."""
    _require_inputs(connection)
    migrate(connection)

    where, params = _where_season("s", season)
    snaps = {}
    for row in connection.execute(
        "SELECT s.player_id,s.season,s.week,s.team,s.off_snaps,s.off_pct,"
        "s.def_snaps,s.def_pct,s.st_snaps FROM nfl_snap_counts s" + where,
        params,
    ):
        player_id, row_season, week, team = row[:4]
        if player_id is None or not team:
            raise RuntimeError("snap row is missing canonical player_id or team")
        key = (int(row_season), int(week), str(team), int(player_id))
        if key in snaps:
            raise RuntimeError(f"duplicate snap availability key: {key}")
        snaps[key] = row[4:]

    injury_where = " WHERE i.league='nfl'"
    injury_params = ()
    if season is not None:
        injury_where += " AND i.season=?"
        injury_params = (season,)
    injuries = {}
    unresolved_injury_rows = 0
    for row in connection.execute(
        "SELECT i.player_id,i.season,i.week,i.team,i.report_status "
        "FROM injury_reports i" + injury_where,
        injury_params,
    ):
        player_id, row_season, week, team, report_status = row
        if player_id is None:
            unresolved_injury_rows += 1
            continue
        if not team:
            raise RuntimeError("injury row is missing team")
        key = (int(row_season), int(week), str(team), int(player_id))
        if key in injuries:
            raise RuntimeError(f"duplicate injury availability key: {key}")
        injuries[key] = report_status

    # Preserve publisher team assignments as separate game facts. A cross-source
    # team disagreement must not attach an injury report to a different game.
    player_weeks = {}
    for key in set(snaps) | set(injuries):
        player_week = (key[0], key[1], key[3])
        player_weeks.setdefault(player_week, set()).add(key[2])
    team_conflicts = sum(len(teams) > 1 for teams in player_weeks.values())

    schedule_where = ""
    schedule_params = ()
    if season is not None:
        schedule_where = " WHERE season=?"
        schedule_params = (season,)
    games = {}
    team_games = {}
    for row in connection.execute(
        "SELECT game_id,season,week,home_team,away_team,home_score,away_score "
        "FROM nfl_schedule" + schedule_where,
        schedule_params,
    ):
        game_id, row_season, week, home, away, home_score, away_score = row
        if not game_id or not home or not away:
            raise RuntimeError("schedule row is missing game_id or team")
        game = {
            "game_id": str(game_id),
            "season": int(row_season),
            "week": int(week),
            "home": str(home),
            "away": str(away),
            "final": home_score is not None and away_score is not None,
        }
        games[game["game_id"]] = game
        for team in (game["home"], game["away"]):
            key = (game["season"], game["week"], team)
            if key in team_games:
                raise RuntimeError(f"ambiguous schedule team-week: {key}")
            team_games[key] = game

    candidates = sorted(set(snaps) | set(injuries))
    missing_games = sorted(
        {key[:3] for key in candidates if key[:3] not in team_games}
    )
    if missing_games:
        sample = ", ".join(map(str, missing_games[:5]))
        raise RuntimeError(
            f"{len(missing_games)} candidate team-weeks lack one schedule game: {sample}"
        )

    snap_teams_by_game = {}
    for row_season, week, team, _player_id in snaps:
        game = team_games[(row_season, week, team)]
        snap_teams_by_game.setdefault(game["game_id"], set()).add(team)
    complete_games = {
        game_id for game_id, game in games.items()
        if snap_teams_by_game.get(game_id) == {game["home"], game["away"]}
    }

    built_at = datetime.now(timezone.utc).isoformat()
    output = []
    for key in candidates:
        row_season, week, team, player_id = key
        game = team_games[(row_season, week, team)]
        snap = snaps.get(key)
        status = injuries.get(key)
        any_snap = snap is not None and any(
            value is not None and value > 0 for value in (snap[0], snap[2], snap[4])
        )
        complete_final = game["final"] and game["game_id"] in complete_games
        if any_snap:
            played, reason = 1, "played"
        elif complete_final:
            played = 0
            reason = (
                "injury_out"
                if status and status.strip().lower() in {"out", "doubtful"}
                else "inactive_no_report"
            )
        else:
            played, reason = None, "unknown"

        if snap is not None and key in injuries:
            source = f"{SOURCE_SNAPS}+{SOURCE_INJURIES}"
        elif snap is not None:
            source = SOURCE_SNAPS
        else:
            source = SOURCE_INJURIES
        values = snap if snap is not None else (None, None, None, None, None)
        output.append((
            "nfl", row_season, week, game["game_id"], team, player_id,
            played, values[0], values[1], values[2], values[3], values[4],
            status, reason, source, built_at,
        ))

    with connection:
        if season is None:
            connection.execute(f"DELETE FROM {TABLE} WHERE league='nfl'")
        else:
            connection.execute(
                f"DELETE FROM {TABLE} WHERE league='nfl' AND season=?", (season,)
            )
        connection.executemany(
            f"""INSERT INTO {TABLE}(
                league,season,week,game_id,team,player_id,played,
                off_snaps,off_pct,def_snaps,def_pct,st_snaps,
                report_status,reason,source,built_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            output,
        )
        stored = connection.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE league='nfl'"
            + (" AND season=?" if season is not None else ""),
            ((season,) if season is not None else ()),
        ).fetchone()[0]
        if stored != len(output):
            raise RuntimeError(
                f"availability reconciliation failed: {stored} stored != "
                f"{len(output)} candidates"
            )

    return {
        "candidates": len(output),
        "stored": stored,
        "unresolved_injury_rows": unresolved_injury_rows,
        "complete_games": len(complete_games),
        "team_conflicts": team_conflicts,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--season", type=int)
    args = parser.parse_args()
    db_path = os.environ.get("LP_DB_PATH")
    if not db_path:
        raise SystemExit("LP_DB_PATH is required")
    connection = sqlite3.connect(db_path)
    try:
        with connection:
            migrate(connection)
        print(f"OK migrated {TABLE}")
        if args.build:
            result = build(connection, season=args.season)
            print(
                f"OK built {result['stored']} rows from {result['candidates']} "
                f"candidates; {result['complete_games']} games have both snap teams; "
                f"excluded {result['unresolved_injury_rows']} unresolved injury rows; "
                f"kept {result['team_conflicts']} cross-source player-week team "
                f"conflicts separate"
            )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
