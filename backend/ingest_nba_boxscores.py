#!/usr/bin/env python3
"""Player box scores for finished NBA games, read from the nba.com game page.

SportsDataverse publishes the NBA box score a season at a time, and the 2026-27 file is not out yet. nba.com serves the
same official box score on each game page (pageProps.game), so for every final regular-season game in nba_schedule this
stores one row per listed player. A box is refused unless each club's players add up to that club's final score, and a
game whose page cannot be read is reported, not skipped.

Usage: python3 ingest_nba_boxscores.py --db data/picks.dev.db --season 2027          (dry run)
       python3 ingest_nba_boxscores.py --db data/picks.dev.db --season 2027 --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ingest_nba_schedule  # noqa: E402

SOURCE = "nba.com"
FINAL = 3
TABLE = "nba_player_boxes_nbacom"
# nba.com statistic name -> column. Minutes is kept as the page's own "mm:ss" string.
STAT_COLUMNS = {
    "points": "points", "reboundsTotal": "rebounds", "assists": "assists", "steals": "steals",
    "blocks": "blocks", "turnovers": "turnovers", "fieldGoalsMade": "fgm", "fieldGoalsAttempted": "fga",
    "threePointersMade": "fg3m", "threePointersAttempted": "fg3a", "freeThrowsMade": "ftm",
    "freeThrowsAttempted": "fta", "plusMinusPoints": "plus_minus",
}
COLUMNS = ["game_id", "person_id", "season", "team", "opponent", "home_away", "player_name", "position", "played",
           "minutes", "comment", *STAT_COLUMNS.values(), "source", "ingested_at"]
SCHEMA = f"""CREATE TABLE IF NOT EXISTS {TABLE} (
  game_id TEXT NOT NULL, person_id INTEGER NOT NULL, season INTEGER NOT NULL,
  team TEXT NOT NULL, opponent TEXT NOT NULL, home_away TEXT NOT NULL, player_name TEXT, position TEXT,
  played INTEGER NOT NULL, minutes TEXT, comment TEXT,
  points INTEGER, rebounds INTEGER, assists INTEGER, steals INTEGER, blocks INTEGER, turnovers INTEGER,
  fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER, plus_minus REAL,
  source TEXT NOT NULL, ingested_at TEXT NOT NULL,
  PRIMARY KEY (game_id, person_id))"""


class BoxScoreError(RuntimeError):
    """A box score that cannot be stored as the official record."""


def rows_for_game(game_id, season, game, home, away):
    """One row per player listed on either club's page. Refuses a box whose points do not add up to the final score."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = []
    for side, team, opponent, label in (("homeTeam", home, away, "home"), ("awayTeam", away, home, "away")):
        block = game.get(side) or {}
        players = block.get("players") or []
        if not players:
            raise BoxScoreError(f"{game_id}: {side} lists no players")
        total = sum(int((p.get("statistics") or {}).get("points") or 0) for p in players)
        if total != block.get("score"):
            raise BoxScoreError(f"{game_id}: {team} players total {total} points, the final is {block.get('score')}")
        for p in players:
            stats = p.get("statistics") or {}
            minutes = stats.get("minutes") or ""
            row = {
                "game_id": game_id, "person_id": int(p["personId"]), "season": season,
                "team": team, "opponent": opponent, "home_away": label,
                "player_name": f"{p.get('firstName') or ''} {p.get('familyName') or ''}".strip(),
                "position": p.get("position") or None, "played": 1 if minutes else 0,
                "minutes": minutes or None, "comment": p.get("comment") or None,
                "source": SOURCE, "ingested_at": now,
            }
            for statistic, column in STAT_COLUMNS.items():
                row[column] = stats.get(statistic)
            rows.append(row)
    return rows


def store_game(connection, game_id, rows):
    """Replace this game's rows, so a re-read is idempotent."""
    connection.execute(f"DELETE FROM {TABLE} WHERE game_id=?", (game_id,))
    connection.executemany(
        f"INSERT INTO {TABLE} ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
        [tuple(row[c] for c in COLUMNS) for row in rows])


def finals(connection, season):
    return connection.execute(
        "SELECT game_id, home_team, away_team FROM nba_schedule WHERE season=? AND status=? "
        "AND season_type='REG' ORDER BY game_date, game_id", (season, FINAL)).fetchall()


def refresh(db_path, season, *, apply, fetch_game=ingest_nba_schedule._game_page, log=print):
    connection = sqlite3.connect(db_path, timeout=30)
    try:
        if apply:
            connection.execute(SCHEMA)
        has_table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                       (TABLE,)).fetchone()
        stored = set()
        if has_table:
            stored = {r[0] for r in connection.execute(f"SELECT DISTINCT game_id FROM {TABLE} WHERE season=?", (season,))}
        games = finals(connection, season)
        todo = [g for g in games if g[0] not in stored]
        log(f"{season}: {len(games)} final regular-season games, {len(stored)} with a box stored, {len(todo)} to read")
        failures, players = [], 0
        for game_id, home, away in todo:
            try:
                game = fetch_game(game_id)
                if game is None:
                    raise BoxScoreError(f"{game_id}: nba.com has no game page")
                rows = rows_for_game(game_id, season, game, home, away)
            except BoxScoreError as exc:
                failures.append(str(exc))
                continue
            players += len(rows)
            if apply:
                store_game(connection, game_id, rows)
                connection.commit()
        log(f"read {len(todo) - len(failures)} games, {players} player rows; "
            f"{'stored' if apply else 'dry run, nothing written'}")
        for failure in failures:
            log(f"REFUSED {failure}")
        return {"games": len(todo), "failures": failures, "players": players}
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--season", type=int, required=True, help="ESPN end year: 2027 is 2026-27")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = refresh(args.db, args.season, apply=args.apply)
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
