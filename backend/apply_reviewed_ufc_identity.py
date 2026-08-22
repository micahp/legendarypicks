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


REVIEWS = (
    {
        "source_player_key": "7c2bea83-5af4-44e3-952a-6b2bcd6f94e9",
        "source_name": "Kaue Fernandes",
        "existing_name": "Kaua Fernandes",
        "canonical_name": "Kauê Fernandes",
        "evidence": "ESPN site scoreboard UFC event 600059185, 2026-08-15",
    },
    {
        "source_player_key": "d3a5c9af-217f-4f3c-a59a-21e5a2f74553",
        "source_name": "Reinier de Ridder",
        "existing_name": "Reinier De Ridder",
        "canonical_name": "Reinier de Ridder",
        "evidence": "ESPN site scoreboard UFC event 600060493, 2026-08-22",
    },
    {
        "source_player_key": "db38a62b-a1aa-477c-866a-e601ada906d0",
        "source_name": "Serghei Spivac",
        "existing_name": "Sergey Spivak",
        "canonical_name": "Serghei Spivac",
        "evidence": "ESPN site scoreboard UFC event 600060493, 2026-08-22",
    },
    {
        "source_player_key": "525edb4d-4ba7-466f-b300-c186a629bfab",
        "source_name": "Wesley Schultz",
        "existing_name": "Wes Schultz",
        "canonical_name": "Wes Schultz",
        "evidence": "ESPN site scoreboard UFC event 600060493, 2026-08-22",
    },
    {
        "source_player_key": "aa9cab99-ad93-451c-bb29-d881802a26a0",
        "source_name": "Christopher Padilla",
        "existing_name": "Chris Padilla",
        "canonical_name": "Chris Padilla",
        "evidence": "ESPN site scoreboard UFC event 600060493, 2026-08-22",
    },
)

# Kept for the original focused regression test and callers that import one review.
REVIEW = REVIEWS[0]


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


def apply_review(con, review=REVIEW):
    """Apply one independently reviewed source-id binding atomically."""
    con.row_factory = sqlite3.Row
    ensure_source_identity_schema(con)
    source_key = review["source_player_key"]
    existing_binding = con.execute(
        "SELECT player_id FROM player_source_ids WHERE source=? AND league=? AND source_player_key=?",
        (SOURCE, LEAGUE, source_key),
    ).fetchall()
    if len(existing_binding) > 1:
        raise SourceIdentityConflict("reviewed native id has multiple existing bindings")

    candidates = con.execute(
        "SELECT id,name FROM players WHERE league=? AND name IN (?,?) ORDER BY id",
        (LEAGUE, review["existing_name"], review["canonical_name"]),
    ).fetchall()
    player = _one(candidates, "reviewed UFC fighter")
    if existing_binding and existing_binding[0]["player_id"] != player["id"]:
        raise SourceIdentityConflict("reviewed native id already points at another player")

    if player["name"] != review["canonical_name"]:
        con.execute(
            "UPDATE players SET name=? WHERE id=?",
            (review["canonical_name"], player["id"]),
        )
    game_ids = [
        row["game_id"]
        for row in con.execute("SELECT DISTINCT game_id FROM props WHERE player_id=?", (player["id"],))
    ]
    for game_id in game_ids:
        con.execute(
            "UPDATE prop_games SET home=? WHERE id=? AND home=?",
            (review["canonical_name"], game_id, review["existing_name"]),
        )
        con.execute(
            "UPDATE prop_games SET away=? WHERE id=? AND away=?",
            (review["canonical_name"], game_id, review["existing_name"]),
        )
    _insert_alias(con, player["id"], normalize_name(review["existing_name"]))
    _insert_alias(con, player["id"], normalize_name(review["source_name"]))
    bind_player_source_key(con, source_key, player["id"], "2026-08-15T00:00:00+00:00")
    return player["id"]


def apply_reviews(con, reviews=REVIEWS):
    """Apply the complete, independently-reviewed UFC mapping set."""
    return [apply_review(con, review) for review in reviews]


def main():
    if "--apply" not in sys.argv:
        print(__doc__)
        return 1
    db_path = os.environ.get("LP_DB_PATH") or DB
    con = sqlite3.connect(db_path)
    try:
        player_ids = apply_reviews(con)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    for review, player_id in zip(REVIEWS, player_ids):
        print(
            "Applied reviewed UFC identity: Underdog {} -> player {} ({}) [{}]".format(
                review["source_player_key"], player_id, review["canonical_name"], review["evidence"]
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
