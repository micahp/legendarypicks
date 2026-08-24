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
    # ESPN event 600060620, UFC Fight Night: Nurmagomedov vs. Song, 2026-08-29.
    # These rows publish the current card's canonical athlete ids before binding the
    # independently-published Underdog ids. Name-only creation remains forbidden.
    {"source_player_key": "899b87e7-e1a4-4195-a86a-42bc05a2694d", "source_name": "Alex Perez", "existing_name": "Alex Perez", "canonical_name": "Alex Perez", "espn_id": "3155425", "evidence": "ESPN event 600060620 fight 401887536"},
    {"source_player_key": "13de3286-2ad8-479a-8cfb-da7d862b6988", "source_name": "Andre (Bra) Lima", "existing_name": "Andre Lima", "canonical_name": "Andre Lima", "espn_id": "5157669", "evidence": "ESPN event 600060620 fight 401905190"},
    {"source_player_key": "0ded92d6-857b-449d-9f6a-f12eb25fdf8d", "source_name": "Bilal Hasan", "existing_name": "Bilal Hasan", "canonical_name": "Bilal Hasan", "espn_id": "5264405", "evidence": "ESPN event 600060620 fight 401913129"},
    {"source_player_key": "2e0f61da-d21c-4c85-8c81-1c1f0166bb17", "source_name": "Denise Gomes", "existing_name": "Denise Gomes", "canonical_name": "Denise Gomes", "espn_id": "4963343", "evidence": "ESPN event 600060620 fight 401887535"},
    {"source_player_key": "e0288f8e-7fac-4f0b-9366-9d75086850f0", "source_name": "Ding Meng", "existing_name": "Ding Meng", "canonical_name": "Ding Meng", "espn_id": "4813565", "evidence": "ESPN event 600060620 fight 401913545"},
    {"source_player_key": "a179b4fb-d9ce-438b-b970-389217404ef6", "source_name": "Jack Jenkins", "existing_name": "Jack Jenkins", "canonical_name": "Jack Jenkins", "espn_id": "5088885", "evidence": "ESPN event 600060620 fight 401898005"},
    {"source_player_key": "99b6dc31-c634-4aac-9b14-80eaad9f9458", "source_name": "Kai Asakura", "existing_name": "Kai Asakura", "canonical_name": "Kai Asakura", "espn_id": "4336757", "evidence": "ESPN event 600060620 fight 401891333"},
    {"source_player_key": "220ce315-c4cc-4683-acb9-dfa24db79c6c", "source_name": "Kevin Borjas", "existing_name": "Kevin Borjas", "canonical_name": "Kevin Borjas", "espn_id": "5144066", "evidence": "ESPN event 600060620 fight 401887537"},
    {"source_player_key": "8ff9b98d-1624-4832-a684-ee7d5edee374", "source_name": "Lawrence Lui", "existing_name": "Lawrence Lui", "canonical_name": "Lawrence Lui", "espn_id": "5220183", "evidence": "ESPN event 600060620 fight 401913544"},
    {"source_player_key": "8a808945-9085-4e1e-9eac-5fe57a3039ce", "source_name": "Namsrai Batbayar", "existing_name": "Namsrai Batbayar", "canonical_name": "Namsrai Batbayar", "espn_id": "5145018", "evidence": "ESPN event 600060620 fight 401905190"},
    {"source_player_key": "cbeb1a0b-34c8-43d9-8765-607d7563e853", "source_name": "Qileng Aori", "existing_name": "Aoriqileng", "canonical_name": "Aoriqileng", "espn_id": "4389085", "evidence": "ESPN event 600060620 fight 401891333"},
    {"source_player_key": "fb264cb7-4ac7-4501-ae3c-64bc3c798c11", "source_name": "Rei Tsuruya", "existing_name": "Rei Tsuruya", "canonical_name": "Rei Tsuruya", "espn_id": "5137012", "evidence": "ESPN event 600060620 fight 401887537"},
    {"source_player_key": "5880d8fa-4f19-4cf3-aec9-1e88c26072b5", "source_name": "Sean Woodson", "existing_name": "Sean Woodson", "canonical_name": "Sean Woodson", "espn_id": "4566991", "evidence": "ESPN event 600060620 fight 401898005"},
    {"source_player_key": "b6efc6be-396f-424c-badd-3717c0a890b3", "source_name": "Su Mudaerji", "existing_name": "Sumudaerji", "canonical_name": "Sumudaerji", "espn_id": "4405109", "evidence": "ESPN event 600060620 fight 401887536"},
    {"source_player_key": "23d630fb-0694-4343-b9aa-8c2f8ca8ba37", "source_name": "Umar Nurmagomedov", "existing_name": "Umar Nurmagomedov", "canonical_name": "Umar Nurmagomedov", "espn_id": "4569549", "evidence": "ESPN event 600060620 fight 401887532"},
    {"source_player_key": "8ef267bc-eb82-423a-99f3-146543bb5a77", "source_name": "Xiao Long", "existing_name": "Xiao Long", "canonical_name": "Xiao Long", "espn_id": "4894864", "evidence": "ESPN event 600060620 fight 401913543"},
    {"source_player_key": "e808cf50-e593-4ce4-9ea2-8efdb6e1886b", "source_name": "Xiaonan Yan", "existing_name": "Yan Xiaonan", "canonical_name": "Yan Xiaonan", "espn_id": "4275487", "evidence": "ESPN event 600060620 fight 401887535"},
    {"source_player_key": "891c5f88-6ce0-4e2d-9f33-bd2c2fb880f5", "source_name": "Xiong Jing Nan", "existing_name": "Jingnan Xiong", "canonical_name": "Jingnan Xiong", "espn_id": "3956295", "evidence": "ESPN event 600060620 fight 401905191"},
    {"source_player_key": "ae0bbc49-1ca7-48b3-a459-d91f8c6a009e", "source_name": "Yadong Song", "existing_name": "Song Yadong", "canonical_name": "Song Yadong", "espn_id": "3151289", "evidence": "ESPN event 600060620 fight 401887532"},
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


def _reviewed_player(con, review):
    """Find or publish one ESPN-keyed canonical fighter from reviewed evidence."""
    espn_id = review.get("espn_id")
    if espn_id:
        by_id = con.execute(
            "SELECT id,name FROM players WHERE league=? AND espn_id=? ORDER BY id",
            (LEAGUE, espn_id),
        ).fetchall()
        if len(by_id) > 1:
            raise SourceIdentityConflict("reviewed ESPN id has multiple canonical owners")
        if by_id:
            return by_id[0]

    candidates = con.execute(
        "SELECT id,name FROM players WHERE league=? AND name IN (?,?) ORDER BY id",
        (LEAGUE, review["existing_name"], review["canonical_name"]),
    ).fetchall()
    if len(candidates) > 1:
        raise SourceIdentityConflict("reviewed UFC fighter: expected at most one row")
    if candidates:
        player = candidates[0]
        if espn_id:
            con.execute(
                "UPDATE players SET espn_id=? WHERE id=? AND NULLIF(espn_id,'') IS NULL",
                (espn_id, player["id"]),
            )
            owner = con.execute(
                "SELECT espn_id FROM players WHERE id=?", (player["id"],)
            ).fetchone()["espn_id"]
            if owner != espn_id:
                raise SourceIdentityConflict("reviewed fighter already owns another ESPN id")
        return player

    if not espn_id:
        return _one(candidates, "reviewed UFC fighter")
    now = "2026-08-24T00:00:00+00:00"
    columns = {row[1] for row in con.execute("PRAGMA table_info(players)")}
    names = ["name", "league", "espn_id"]
    values = [review["canonical_name"], LEAGUE, espn_id]
    if "active" in columns:
        names.append("active")
        values.append(1)
    if "updated_at" in columns:
        names.append("updated_at")
        values.append(now)
    placeholders = ",".join("?" for _ in names)
    player_id = con.execute(
        "INSERT INTO players({}) VALUES({})".format(",".join(names), placeholders),
        values,
    ).lastrowid
    return con.execute("SELECT id,name FROM players WHERE id=?", (player_id,)).fetchone()


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

    player = _reviewed_player(con, review)
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
