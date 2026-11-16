#!/usr/bin/env python3
"""Lock near-start tennis forecasts and persist grades from final scoreboards."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys


def _winner(game: dict, state: str) -> str | None:
    if state != "post" or game.get("completed") is not True:
        return None
    home, away = game.get("home") or {}, game.get("away") or {}
    status = str(game.get("status") or "").lower()
    if any(token in status for token in ("cancel", "postpon", "walkover", "abandon", "default")):
        return None

    if "winner" in home or "winner" in away:
        if home.get("winner") is True and away.get("winner") is False:
            return home.get("name")
        if away.get("winner") is True and home.get("winner") is False:
            return away.get("name")
        return None
    if "retir" in status:
        return None

    home_score, away_score = home.get("score"), away.get("score")
    try:
        if home_score is not None and away_score is not None:
            if float(home_score) > float(away_score):
                return home.get("name")
            if float(away_score) > float(home_score):
                return away.get("name")
    except (TypeError, ValueError):
        pass

    return None


def _require_grade_schema(con) -> None:
    required = {
        "league", "game_id", "winner", "total_games_error", "graded_at",
        "result_source", "result_game_date", "result_fetched_at",
        "result_payload_sha256",
    }
    columns = {row[1] for row in con.execute("PRAGMA table_info(tennis_model_grades)")}
    triggers = {
        row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name IN ('tennis_model_grades_immutable_update', "
            "'tennis_model_grades_immutable_delete')"
        )
    }
    missing = sorted(required - columns)
    if not _table_exists(con, "tennis_model_grades") or missing or len(triggers) != 2:
        detail = ", ".join(missing) if missing else "immutability triggers"
        raise RuntimeError(
            "tennis grade schema is not ready (missing %s); "
            "run backend/migrate_all.py --apply before grading" % detail
        )


def _table_exists(con, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def grade_final_matches(con, now: dt.datetime) -> dict[str, int]:
    _require_grade_schema(con)
    report = {"locked_finals": 0, "graded": 0, "missing_result": 0}
    for league in ("atp", "wta"):
        rows = con.execute("""
          SELECT s.game_id,s.game_date,s.payload,s.state,s.fetched_at,s.source,l.projection
          FROM scoreboard_snapshots s
          JOIN tennis_model_locks l ON l.league=s.league AND l.game_id=s.game_id
          WHERE s.league=? AND NOT EXISTS (
            SELECT 1 FROM scoreboard_snapshots newer
            WHERE newer.league=s.league AND newer.game_id=s.game_id
              AND (newer.fetched_at>s.fetched_at OR
                   (newer.fetched_at=s.fetched_at AND newer.game_date>s.game_date))
          )
        """, (league,)).fetchall()
        for row in rows:
            if str(row["state"] or "").lower() != "post":
                continue
            try:
                game = json.loads(row["payload"])
                projection = json.loads(row["projection"])
            except (TypeError, ValueError):
                report["locked_finals"] += 1
                report["missing_result"] += 1
                continue
            report["locked_finals"] += 1
            if game.get("completed") is not True:
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
            is_retirement = "retir" in str(game.get("status") or "").lower()
            if not is_retirement and home_sets and len(home_sets) == len(away_sets):
                try:
                    set_scores = [int(value) for value in home_sets + away_sets]
                    if all(value >= 0 for value in set_scores):
                        total_games = sum(set_scores)
                except (TypeError, ValueError):
                    pass
            expected = projection.get("totalGames")
            total_error = abs(float(expected) - total_games) if expected is not None and total_games is not None else None
            winner_grade = "correct" if predicted_winner == actual_winner else "incorrect"
            cursor = con.execute("""
              INSERT OR IGNORE INTO tennis_model_grades(
                league,game_id,winner,total_games_error,graded_at,result_source,
                result_game_date,result_fetched_at,result_payload_sha256
              ) VALUES(?,?,?,?,?,?,?,?,?)
            """, (
                league, str(row["game_id"]), winner_grade, total_error, now.isoformat(),
                row["source"], row["game_date"], row["fetched_at"],
                hashlib.sha256(str(row["payload"]).encode("utf-8")).hexdigest(),
            ))
            if cursor.rowcount == 1:
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
