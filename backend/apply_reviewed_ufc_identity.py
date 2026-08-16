#!/usr/bin/env python3
"""Apply the reviewed current-card UFC identity correction.

This is deliberately a narrow, explicit data migration rather than a fuzzy
matcher. ESPN's published UFC 330 event 600059185 (2026-08-15) names the
fighter ``Kauê Fernandes``. The existing Bovada-created canonical row says
``Kaua Fernandes``; Underdog's native player key publishes ``Kaue Fernandes``.

The command corrects the canonical display name and its existing fight labels,
preserves the Bovada spelling as an alias, and binds only the reviewed Underdog
native id. It refuses to choose if the database contains multiple candidates or
a conflicting source id.
"""
import os
import sqlite3
import sys

from ingest_underdog_props import (
    DB,
    LEAGUE,
    SOURCE,
    SourceIdentityConflict,
    bind_player_source_key,
    ensure_source_identity_schema,
    normalize_name,
)


REVIEW = {
    "source_player_key": "7c2bea83-5af4-44e3-952a-6b2bcd6f94e9",
    "source_name": "Kaue Fernandes",
    "existing_name": "Kaua Fernandes",
    "canonical_name": "Kauê Fernandes",
    "evidence": "ESPN site scoreboard UFC event 600059185, 2026-08-15",
}


def _one(rows, description):
    if len(rows) != 1:
        raise SourceIdentityConflict("{}: expected one row, found {}".format(description, len(rows)))
    return rows[0]


def _insert_alias(con, player_id, alias_norm):
    present = con.execute(
        "SELECT 1 FROM name_alias WHERE player_id=? AND alias_norm=?",
        (player_id, alias_norm),
    ).fetchone()
    if not present:
        con.execute(
            "INSERT INTO name_alias(player_id,alias_norm) VALUES(?,?)",
            (player_id, alias_norm),
        )


def apply_review(con):
    """Apply the one independently reviewed source-id binding atomically."""
    con.row_factory = sqlite3.Row
    ensure_source_identity_schema(con)
    source_key = REVIEW["source_player_key"]
    existing_binding = con.execute(
        "SELECT player_id FROM player_source_ids WHERE source=? AND league=? AND source_player_key=?",
        (SOURCE, LEAGUE, source_key),
    ).fetchall()
    if len(existing_binding) > 1:
        raise SourceIdentityConflict("reviewed native id has multiple existing bindings")

    candidates = con.execute(
        "SELECT id,name FROM players WHERE league=? AND name IN (?,?) ORDER BY id",
        (LEAGUE, REVIEW["existing_name"], REVIEW["canonical_name"]),
    ).fetchall()
    player = _one(candidates, "reviewed UFC fighter")
    if existing_binding and existing_binding[0]["player_id"] != player["id"]:
        raise SourceIdentityConflict("reviewed native id already points at another player")

    if player["name"] != REVIEW["canonical_name"]:
        con.execute(
            "UPDATE players SET name=? WHERE id=?",
            (REVIEW["canonical_name"], player["id"]),
        )
    game_ids = [
        row["game_id"]
        for row in con.execute("SELECT DISTINCT game_id FROM props WHERE player_id=?", (player["id"],))
    ]
    for game_id in game_ids:
        con.execute(
            "UPDATE prop_games SET home=? WHERE id=? AND home=?",
            (REVIEW["canonical_name"], game_id, REVIEW["existing_name"]),
        )
        con.execute(
            "UPDATE prop_games SET away=? WHERE id=? AND away=?",
            (REVIEW["canonical_name"], game_id, REVIEW["existing_name"]),
        )
    _insert_alias(con, player["id"], normalize_name(REVIEW["existing_name"]))
    _insert_alias(con, player["id"], normalize_name(REVIEW["source_name"]))
    bind_player_source_key(con, source_key, player["id"], "2026-08-15T00:00:00+00:00")
    return player["id"]


def main():
    if "--apply" not in sys.argv:
        print(__doc__)
        return 1
    db_path = os.environ.get("LP_DB_PATH") or DB
    con = sqlite3.connect(db_path)
    try:
        player_id = apply_review(con)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(
        "Applied reviewed UFC identity: Underdog {} -> player {} ({}) [{}]".format(
            REVIEW["source_player_key"], player_id, REVIEW["canonical_name"], REVIEW["evidence"]
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
