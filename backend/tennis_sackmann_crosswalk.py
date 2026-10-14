#!/usr/bin/env python3
"""Build the stable tennis-spine to Sackmann identity crosswalk.

Only a one-to-one exact full-name match is eligible. Ambiguous and unmatched
source identities are emitted for review and never guessed. The crosswalk is
stored in player_source_ids as source='sackmann', keyed by Sackmann's player ID.

Dry run:
  python3 backend/tennis_sackmann_crosswalk.py --db <dev-db>
Apply to a database:
  python3 backend/tennis_sackmann_crosswalk.py --db <dev-db> --apply
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sqlite3
import unicodedata
from typing import Any


def normalize(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = value.encode("ascii", "ignore").decode("ascii").casefold()
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", value).split())


def build(con: sqlite3.Connection, tour: str) -> dict[str, Any]:
    if tour not in ("atp", "wta"):
        raise ValueError(f"unsupported tour: {tour}")
    source = f"tennis_{tour}_players"
    canonical = con.execute(
        "SELECT id,name FROM players WHERE league=? AND publisher IS NOT NULL "
        "AND publisher_id IS NOT NULL ORDER BY id", (tour,)
    ).fetchall()
    historical = con.execute(
        f"SELECT player_id,name_first,name_last FROM {source} ORDER BY player_id"
    ).fetchall()

    by_name: dict[str, list[sqlite3.Row]] = collections.defaultdict(list)
    for row in historical:
        by_name[normalize(f"{row['name_first'] or ''} {row['name_last'] or ''}")].append(row)

    canonical_by_name: dict[str, list[sqlite3.Row]] = collections.defaultdict(list)
    for row in canonical:
        canonical_by_name[normalize(row["name"])].append(row)

    matches: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for row in canonical:
        name = normalize(row["name"])
        source_rows = by_name.get(name, [])
        if len(source_rows) == 1 and len(canonical_by_name[name]) == 1:
            matches.append({"player_id": int(row["id"]), "sackmann_player_id": str(source_rows[0]["player_id"]),
                            "name": row["name"], "match_method": "unique_exact_full_name"})
        elif len(source_rows) > 1:
            ambiguous.append({"player_id": int(row["id"]), "name": row["name"],
                              "candidates": [str(item["player_id"]) for item in source_rows]})
        elif len(canonical_by_name[name]) > 1:
            ambiguous.append({"player_id": int(row["id"]), "name": row["name"],
                              "reason": "duplicate_canonical_spine_name", "candidates": []})
        else:
            unmatched.append({"player_id": int(row["id"]), "name": row["name"]})

    # A Sackmann ID may never point at more than one canonical spine identity.
    by_source_id: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in matches:
        by_source_id[row["sackmann_player_id"]].append(row)
    collisions = [rows for rows in by_source_id.values() if len(rows) != 1]
    if collisions:
        raise RuntimeError(f"cross-tour source ID collision in {tour}: {collisions[:3]}")

    existing = {
        str(row[0]): int(row[1])
        for row in con.execute(
            "SELECT source_player_key,player_id FROM player_source_ids "
            "WHERE source='sackmann' AND league=?", (tour,)
        )
    }
    conflicts = [row for row in matches if row["sackmann_player_id"] in existing
                 and existing[row["sackmann_player_id"]] != row["player_id"]]
    if conflicts:
        raise RuntimeError(f"existing Sackmann crosswalk conflicts: {conflicts[:3]}")
    for row in matches:
        if row["sackmann_player_id"] in existing:
            row["state"] = "already_bound"
        else:
            row["state"] = "to_bind"

    return {"tour": tour, "canonical_players": len(canonical), "sackmann_players": len(historical),
            "unique_exact_matches": len(matches), "ambiguous": ambiguous, "unmatched": unmatched,
            "matches": matches, "existing_bindings": len(existing)}


def apply(con: sqlite3.Connection, tour: str, matches: list[dict[str, Any]]) -> int:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    inserted = 0
    with con:
        for row in matches:
            cur = con.execute(
                "INSERT OR IGNORE INTO player_source_ids "
                "(source,league,source_player_key,player_id,first_seen,last_seen) "
                "VALUES('sackmann',?,?,?,?,?)",
                (tour, row["sackmann_player_id"], row["player_id"], now, now),
            )
            inserted += cur.rowcount
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true", help="write one-to-one unique matches to player_source_ids")
    args = parser.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode={'rw' if args.apply else 'ro'}", uri=True)
    con.row_factory = sqlite3.Row
    try:
        report = [build(con, tour) for tour in ("atp", "wta")]
        if args.apply:
            for result in report:
                result["inserted"] = apply(con, result["tour"], result["matches"])
        print(json.dumps([{key: value for key, value in result.items() if key not in ("matches", "ambiguous", "unmatched")}
                          for result in report], indent=2))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
