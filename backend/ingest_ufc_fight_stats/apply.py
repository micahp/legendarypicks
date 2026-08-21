"""Apply a completed UFC ingest plan to the database."""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from .schema import ensure_table
from publisher_capture import capture_payload, require_publisher_capture_schema

if TYPE_CHECKING:  # the annotation is the only use; importing it at runtime
    from .plan import IngestPlan  # would be a cycle (plan imports nothing here)

def apply_plan(db_path: str, plan: "IngestPlan") -> dict:
    """Apply a completed plan in one short transaction with no source calls."""
    if plan.source_errors:
        raise RuntimeError("refusing write: source errors are present")
    if plan.conflicts:
        raise RuntimeError("refusing write: identity/data conflicts are present")
    con = sqlite3.connect(db_path, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN IMMEDIATE")
        ensure_table(con)
        if plan.source_payloads:
            # Status bodies were obtained while making this immutable plan. A
            # successful apply must retain them before using their result/method
            # fields to write a log; without the explicit migration, fail closed.
            require_publisher_capture_schema(con)
            for source in plan.source_payloads:
                capture_payload(
                    con, source="espn", league="ufc",
                    endpoint=source.endpoint, payload=source.payload,
                )
        identity_updates = 0
        for player_id, athlete_id in sorted(plan.identity_updates.items()):
            owner = con.execute(
                "SELECT id FROM players WHERE league='ufc' AND espn_id=?",
                (athlete_id,),
            ).fetchone()
            if owner is not None and int(owner["id"]) != player_id:
                raise RuntimeError(
                    "ESPN {} became owned by player {}".format(
                        athlete_id, owner["id"]
                    )
                )
            cursor = con.execute(
                """
                UPDATE players SET espn_id=?
                WHERE id=? AND league='ufc' AND NULLIF(espn_id, '') IS NULL
                """,
                (athlete_id, player_id),
            )
            identity_updates += max(cursor.rowcount, 0)
        game_links = 0
        for prop_game_id, fight_id in sorted(plan.game_links.items()):
            row = con.execute(
                "SELECT espn_event_id FROM prop_games WHERE id=? AND league='ufc'",
                (prop_game_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("UFC prop_game {} disappeared".format(prop_game_id))
            current = str(row["espn_event_id"] or "")
            if current and current != fight_id:
                raise RuntimeError(
                    "UFC prop_game {} is already linked to {}".format(
                        prop_game_id, current
                    )
                )
            if not current:
                cursor = con.execute(
                    "UPDATE prop_games SET espn_event_id=? WHERE id=?",
                    (fight_id, prop_game_id),
                )
                game_links += max(cursor.rowcount, 0)
        before_logs = con.total_changes
        con.executemany(
            """
            INSERT OR IGNORE INTO player_game_logs
              (player_id, league, season, game_no, game_id, game_date,
               team, opponent, home_away, stats, source, source_player_key)
            VALUES (?, 'ufc', ?, ?, ?, ?, NULL, ?, NULL, ?, 'espn_mma_stats', ?)
            """,
            [
                (
                    row.player_id,
                    row.season,
                    row.game_no,
                    row.game_id,
                    row.game_date,
                    row.opponent,
                    row.stats_json,
                    row.source_player_key,
                )
                for row in plan.logs
            ],
        )
        inserted_logs = con.total_changes - before_logs
        con.commit()
        return {
            "identity_updates": identity_updates,
            "game_links": game_links,
            "inserted_logs": inserted_logs,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
