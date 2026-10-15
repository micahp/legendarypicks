#!/usr/bin/env python3
"""Lock near-start tennis forecasts and persist grades from final scoreboards."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys


def _winner(game: dict, state: str) -> str | None:
    home, away = game.get("home") or {}, game.get("away") or {}
    home_score, away_score = home.get("score"), away.get("score")
    try:
        if home_score is not None and away_score is not None:
            if float(home_score) > float(away_score):
                return home.get("name")
            if float(away_score) > float(home_score):
                return away.get("name")
    except (TypeError, ValueError):
        pass

    if state == "post" and "retir" in str(game.get("status") or "").lower():
        try:
            home_games = sum(int(value) for value in home.get("sets") or [])
            away_games = sum(int(value) for value in away.get("sets") or [])
            if home_games != away_games:
                return home.get("name") if home_games > away_games else away.get("name")
        except (TypeError, ValueError):
            pass
    return None


def grade_final_matches(con, now: dt.datetime) -> dict[str, int]:
    con.execute("""CREATE TABLE IF NOT EXISTS tennis_model_grades(
      league TEXT NOT NULL CHECK(league IN ('atp','wta')),
      game_id TEXT NOT NULL,
      winner TEXT NOT NULL CHECK(winner IN ('correct','incorrect')),
      total_games_error REAL,
      graded_at TEXT NOT NULL,
      PRIMARY KEY(league, game_id)
    )""")
    report = {"locked_finals": 0, "graded": 0, "missing_result": 0}
    for league in ("atp", "wta"):
        rows = con.execute("""
          SELECT s.game_id,s.payload,s.state,l.projection
          FROM scoreboard_snapshots s
          JOIN tennis_model_locks l ON l.league=s.league AND l.game_id=s.game_id
          WHERE s.league=? AND LOWER(s.state)='post'
        """, (league,)).fetchall()
        for row in rows:
            report["locked_finals"] += 1
            try:
                game = json.loads(row["payload"])
                projection = json.loads(row["projection"])
            except (TypeError, ValueError):
                report["missing_result"] += 1
                continue
            actual_winner = _winner(game, str(row["state"] or "").lower())
            predicted_winner = projection.get("projectedWinner")
            if not actual_winner or not predicted_winner:
                report["missing_result"] += 1
                continue
            home_sets = (game.get("home") or {}).get("sets") or []
            away_sets = (game.get("away") or {}).get("sets") or []
            total_games = None
            if home_sets and len(home_sets) == len(away_sets):
                try:
                    total_games = sum(int(value) for value in home_sets + away_sets)
                except (TypeError, ValueError):
                    pass
            expected = projection.get("totalGames")
            total_error = abs(float(expected) - total_games) if expected is not None and total_games is not None else None
            winner_grade = "correct" if predicted_winner == actual_winner else "incorrect"
            con.execute("""
              INSERT INTO tennis_model_grades(league,game_id,winner,total_games_error,graded_at)
              VALUES(?,?,?,?,?)
              ON CONFLICT(league,game_id) DO UPDATE SET
                winner=excluded.winner,
                total_games_error=excluded.total_games_error,
                graded_at=excluded.graded_at
            """, (league, str(row["game_id"]), winner_grade, total_error, now.isoformat()))
            report["graded"] += 1
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=3, help="UTC days of upcoming forecasts to refresh and lock")
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 7:
        parser.error("--days must be between 1 and 7")

    from routers.games import misc
    from tennis_model_lock import projection_job_lock

    db_path = os.environ.get("LP_DB_PATH") or misc.DB
    with projection_job_lock(db_path):
        today = dt.datetime.now(dt.timezone.utc).date()
        refreshed = 0
        for offset in range(args.days):
            day = (today + dt.timedelta(days=offset)).isoformat()
            for tour in ("atp", "wta"):
                result = misc.tennis_model(date=day, tour=tour, utc_offset_minutes=0)
                refreshed += sum(1 for match in result.get("matches", []) if match.get("lockedAt"))

        con = misc._db()
        try:
            report = grade_final_matches(con, dt.datetime.now(dt.timezone.utc))
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
    print("tennis model job: %d locks present in refreshed slates; %d final locks, %d graded, %d awaiting usable result" % (
        refreshed, report["locked_finals"], report["graded"], report["missing_result"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
