"""Keep the tennis spine in step with the tournaments the scoreboard tracks.

The spine (`players`) was the top 150 per tour, so a tracked tournament's field
(qualifiers, wildcards, lucky losers) was never in it and the model could not
project those matches ("One or both player IDs are not mapped through the tennis
spine"). The scoreboard ingest already holds every athlete on the slate, with the
publisher's athlete id, so this runs in the same pass and costs no request.

For each athlete on a stored slate:
  1. already in the spine by ESPN id -> keep it;
  2. exactly one same-name row with no ESPN id -> bind the id to that row (the
     publisher roster ingest creates such rows); never steal a row that holds a
     different id, and never pick between two;
  3. otherwise insert one.
Then any of those athletes without a Sackmann binding gets one by the same rule
as `tennis_sackmann_crosswalk`: a unique exact full-name match, never a guess. A
two-word name that matches nothing is tried once with the words swapped.

Whatever cannot be resolved is written to `tennis_spine_unresolved` with its
reason instead of failing silently. An athlete is never created from a TBD slot.
"""
from __future__ import annotations

import collections
import datetime as dt
import sqlite3

from tennis_sackmann_crosswalk import normalize

SCHEMA = """
CREATE TABLE IF NOT EXISTS tennis_spine_unresolved(
  league     TEXT NOT NULL,
  espn_id    TEXT NOT NULL,
  name       TEXT NOT NULL,
  reason     TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen  TEXT NOT NULL,
  PRIMARY KEY(league, espn_id)
);
"""


def event_athletes(games):
    """{espn athlete id: name} for the real players on a slate."""
    found = {}
    for game in games or []:
        for side in ("home", "away"):
            player = game.get(side) or {}
            name = str(player.get("name") or "").strip()
            athlete_id = str(player.get("athlete_id") or "").strip()
            if not name or not athlete_id or name.upper() == "TBD":
                continue
            found[athlete_id] = name
    return found


def _sackmann_by_name(con, tour):
    index = collections.defaultdict(list)
    for row in con.execute(f"SELECT player_id,name_first,name_last FROM tennis_{tour}_players"):
        index[normalize(f"{row[1] or ''} {row[2] or ''}")].append(str(row[0]))
    return index


def sync_event_players(tour, games, con):
    """Bring the spine up to the slate. Returns counts; the caller commits."""
    tour = str(tour or "").lower()
    if tour not in ("atp", "wta"):
        raise ValueError("tennis event spine tour must be atp or wta")
    athletes = event_athletes(games)
    if not athletes:
        return {"athletes": 0, "inserted": 0, "adopted": 0, "bound": 0, "unresolved": 0}

    con.executescript(SCHEMA)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows = con.execute("SELECT id,name,espn_id FROM players WHERE league=?", (tour,)).fetchall()
    by_espn = {str(r[2]): r[0] for r in rows if r[2]}
    by_name = collections.defaultdict(list)
    for r in rows:
        by_name[normalize(r[1])].append(r)

    name_count = collections.Counter(normalize(r[1]) for r in rows)
    unresolved = {}
    inserted = adopted = 0
    for espn_id, name in athletes.items():
        if espn_id in by_espn:
            continue
        same_name = by_name.get(normalize(name), [])
        free = [r for r in same_name if not r[2]]
        if len(same_name) == 1 and len(free) == 1:
            con.execute("UPDATE players SET espn_id=?,updated_at=? WHERE id=?",
                        (espn_id, now, free[0][0]))
            by_espn[espn_id] = free[0][0]
            adopted += 1
        elif same_name:
            unresolved[espn_id] = (name, "same-name spine row holds another id or is ambiguous")
        else:
            cur = con.execute(
                "INSERT INTO players(name,team,league,espn_id,active,updated_at)"
                " VALUES(?,NULL,?,?,0,?)", (name, tour, espn_id, now))
            by_espn[espn_id] = cur.lastrowid
            name_count[normalize(name)] += 1
            inserted += 1

    bound = 0
    sackmann = _sackmann_by_name(con, tour)
    bound_players = {r[0] for r in con.execute(
        "SELECT player_id FROM player_source_ids WHERE source='sackmann' AND league=?", (tour,))}
    bound_keys = {str(r[0]) for r in con.execute(
        "SELECT source_player_key FROM player_source_ids WHERE source='sackmann' AND league=?",
        (tour,))}
    for espn_id, name in athletes.items():
        player_id = by_espn.get(espn_id)
        if player_id is None or player_id in bound_players:
            continue
        candidates = sackmann.get(normalize(name), [])
        if not candidates:
            # ESPN lists many Chinese players family name first ("Wang Xinyu"); Sackmann
            # does the opposite. Same unique-match rule, only for two-word names.
            words = normalize(name).split()
            if len(words) == 2:
                candidates = sackmann.get(f"{words[1]} {words[0]}", [])
        spine_same_name = name_count[normalize(name)]
        if len(candidates) != 1:
            unresolved[espn_id] = (name, "no Sackmann match" if not candidates
                                   else "ambiguous Sackmann name")
        elif spine_same_name > 1:
            unresolved[espn_id] = (name, "duplicate spine name")
        elif candidates[0] in bound_keys:
            unresolved[espn_id] = (name, "Sackmann id already bound to another player")
        else:
            con.execute(
                "INSERT OR IGNORE INTO player_source_ids"
                "(source,league,source_player_key,player_id,first_seen,last_seen)"
                " VALUES('sackmann',?,?,?,?,?)", (tour, candidates[0], player_id, now, now))
            bound_players.add(player_id)
            bound_keys.add(candidates[0])
            bound += 1

    # What is resolved now no longer belongs in the list.
    for espn_id in athletes:
        if espn_id not in unresolved:
            con.execute("DELETE FROM tennis_spine_unresolved WHERE league=? AND espn_id=?",
                        (tour, espn_id))
    for espn_id, (name, reason) in unresolved.items():
        con.execute(
            "INSERT INTO tennis_spine_unresolved(league,espn_id,name,reason,first_seen,last_seen)"
            " VALUES(?,?,?,?,?,?) ON CONFLICT(league,espn_id) DO UPDATE SET"
            " name=excluded.name,reason=excluded.reason,last_seen=excluded.last_seen",
            (tour, espn_id, name, reason, now, now))
    return {"athletes": len(athletes), "inserted": inserted, "adopted": adopted,
            "bound": bound, "unresolved": len(unresolved)}
