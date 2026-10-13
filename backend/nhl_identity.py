#!/usr/bin/env python3
"""One identity rule for NHL ingests that meet a published player with no `nhl_id` owner.

The roster publisher (`ingest_nhl_roster`) mints owners for the CURRENT rosters. The season
report and the game logs also carry players who are on no roster now (retired, in the AHL,
called up for one game), and ones who signed after the last roster run. An ingest that
refuses the whole run for them is a standing outage: `nhl_current` failed every half hour
from 2026-10-12 to 10-13 on one such participant (8484409) while its last success was 10-08.

So the ingest resolves the identity itself, by the roster publisher's own rule
(`_choose_unbound_candidate`), and writes it in the SAME transaction as its own rows:

  * one unbound same-name row with team or position evidence -> bind its nhl_id;
  * no same-name row without a different nhl_id             -> mint an inactive row;
  * anything else (ambiguous, no evidence, a spelling twin)  -> skipped and reported.
    A guess is never written.

`resolve` reads and writes nothing. `apply` writes, inside the caller's transaction.
An item is {"source_key", "name" (full name), "position" (L/R/C/D/G or None),
"teams" (NHL tricodes, any spelling)}.
"""
from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_league_stats import _identity_name_key  # noqa: E402
from ingest_nhl_roster import _choose_unbound_candidate, _normal_team  # noqa: E402

SOURCE = "nhle.com"


def resolve(connection: sqlite3.Connection, items: list) -> dict:
    by_name: dict = {}
    unbound_by_last: dict = {}
    for row in connection.execute(
            "SELECT id,name,team,position,nhl_id FROM players WHERE league='nhl'"):
        key = _identity_name_key(row["name"])
        by_name.setdefault(key, []).append(row)
        if row["nhl_id"] is None and key:
            unbound_by_last.setdefault(key.split()[-1], []).append(row)
    durable = {
        str(r["source_player_key"]): int(r["player_id"])
        for r in connection.execute(
            "SELECT source_player_key,player_id FROM player_source_ids "
            "WHERE source=? AND league='nhl'", (SOURCE,))
    }
    binds, mints, skipped = [], [], []
    for source in items:
        name = str(source.get("name") or "")
        teams = [t for t in (_normal_team(a) for a in source.get("teams") or []) if t]
        item = {"source_key": str(source["source_key"]), "name": name,
                "position": source.get("position"),
                "team": teams[0] if teams else None}
        if item["source_key"] in durable:
            skipped.append({**item, "reason": "stranded_source_crosswalk"})
            continue
        key = _identity_name_key(name)
        if not key:
            skipped.append({**item, "reason": "no_name"})
            continue
        candidates = by_name.get(key, [])
        outcomes = [_choose_unbound_candidate(
            candidates, {"team": team, "position": item["position"]})
            for team in teams or [""]]
        chosen = {int(c["id"]): c for c, _ in outcomes if c is not None}
        if len(chosen) > 1:
            skipped.append({**item, "reason": "ambiguous_team"})
        elif chosen:
            binds.append({**item, "player_id": next(iter(chosen))})
        elif any(action == "insert" for _, action in outcomes):
            # "Samuel Blais" beside an unbound "Sammy Blais" is one person under two
            # spellings. Minting would leave a second row for him, so it is held.
            twins = [r for r in unbound_by_last.get(key.split()[-1], [])
                     if _identity_name_key(r["name"])[:3] == key[:3]]
            if twins:
                skipped.append({**item, "reason": "possible_duplicate_of_"
                                + ",".join(str(r["id"]) for r in twins)})
            else:
                mints.append(item)
        else:
            skipped.append({**item, "reason": outcomes[0][1]})
    return {"binds": binds, "mints": mints, "skipped": skipped}


def apply(connection: sqlite3.Connection, plan: dict, now: str) -> dict:
    """Write the planned binds and mints; returns {source_key: players.id}."""
    owners = {}
    for item in plan["binds"]:
        connection.execute(
            "UPDATE players SET nhl_id=COALESCE(nhl_id,?),updated_at=? "
            "WHERE id=? AND league='nhl'",
            (int(item["source_key"]), now, item["player_id"]))
        owners[item["source_key"]] = item["player_id"]
    for item in plan["mints"]:
        cursor = connection.execute(
            "INSERT INTO players(name,league,team,position,nhl_id,active,updated_at) "
            "VALUES(?,'nhl',?,?,?,0,?)",
            (item["name"], item["team"], item["position"],
             int(item["source_key"]), now))
        owners[item["source_key"]] = int(cursor.lastrowid)
    for key, player_id in owners.items():
        connection.execute(
            "INSERT INTO player_source_ids(source,league,source_player_key,"
            "player_id,first_seen,last_seen) VALUES(?,'nhl',?,?,?,?)",
            (SOURCE, key, player_id, now, now))
    return owners
