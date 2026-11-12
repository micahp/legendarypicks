"""Decide whether an NBA athlete already has a canonical players row.

Created after 2026-11-12, when 'William Kyle III' (ESPN 5107258) was inserted as a
new player although row 63170 'William Kyle' already carried his nba.com id
1643759. A name check that ignored the suffix missed it. This module is the one
place that answers "reuse, attach, hold or create" BEFORE any insert.

It never creates when any existing identity could be the same person:

  reuse        the ESPN id or hoopR id already belongs to a row
  attach_espn  the nba.com id belongs to a row that has no ESPN id yet
  hold         conflicting ids, or a same-name candidate with no id evidence
  create       nothing matches by id, alias or name key

A name key alone never binds a row (a name is a candidate, not proof): it only
turns "create" into "hold".
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from typing import Optional, Tuple

import name_aliases

SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def name_key(name: Optional[str]) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = SUFFIX.sub("", text.replace(".", "").replace("-", " ").replace("'", ""))
    return " ".join(text.split())


def _first_last(key: str) -> Tuple[str, str]:
    parts = key.split()
    return (parts[0], parts[-1]) if parts else ("", "")


REVIEWED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "nba-identity-reviewed.json")


def _reviewed_pairs(path: str = REVIEWED_PATH) -> dict:
    """{espn_id: {nba.com ids}} from the reviewed file (birth-date or box-score evidence)."""
    try:
        with open(path, encoding="utf-8") as handle:
            entries = json.load(handle).get("nba", {})
    except (OSError, ValueError):
        return {}
    pairs: dict = {}
    for nba_id, entry in entries.items():
        if isinstance(entry, dict) and entry.get("espn_id"):
            pairs.setdefault(str(entry["espn_id"]), set()).add(str(nba_id))
    return pairs


def crosswalk_nba_com_id(con: sqlite3.Connection, espn_id) -> Tuple[Optional[str], bool]:
    """Verified nba.com id for an ESPN id, from evidence we already hold.

    Sources: the reviewed file, and a player_source_ids row that carries the ESPN
    id (source 'espn') next to an nba.com id for the same player. Returns
    (nba_com_id or None, conflict). Two different ids is a conflict, never a pick.
    """
    espn_id = str(espn_id) if espn_id not in (None, "") else None
    if not espn_id:
        return None, False
    found = set(_reviewed_pairs().get(espn_id, set()))
    for (pid,) in con.execute("SELECT DISTINCT player_id FROM player_source_ids "
                              "WHERE league='nba' AND source='espn' AND source_player_key=?",
                              (espn_id,)).fetchall():
        for (key,) in con.execute("SELECT source_player_key FROM player_source_ids "
                                  "WHERE league='nba' AND source='nba.com' AND player_id=?",
                                  (pid,)).fetchall():
            found.add(str(key))
    if len(found) > 1:
        return None, True
    return (next(iter(found)) if found else None), False


def resolve(con: sqlite3.Connection, espn_id, name: str, nba_com_id=None
            ) -> Tuple[str, Optional[int], str]:
    """Return (action, players.id or None, reason)."""
    espn_id = str(espn_id) if espn_id not in (None, "") else None
    cols = {r[1] for r in con.execute("PRAGMA table_info(players)")}
    if espn_id:
        row = con.execute("SELECT id FROM players WHERE league='nba' AND espn_id=?",
                          (espn_id,)).fetchall()
        if len(row) == 1:
            return "reuse", row[0][0], "espn_id owner"
        if len(row) > 1:
            return "hold", None, "more than one row owns the ESPN id"
        if "hoopr_id" in cols:
            row = con.execute("SELECT id FROM players WHERE league='nba' AND CAST(hoopr_id AS TEXT)=?",
                              (espn_id,)).fetchall()
            if len(row) == 1:
                return "reuse", row[0][0], "hoopr_id owner"
            if len(row) > 1:
                return "hold", None, "more than one row owns the hoopR id"
    if nba_com_id:
        row = con.execute("SELECT DISTINCT player_id FROM player_source_ids "
                          "WHERE league='nba' AND source='nba.com' AND source_player_key=?",
                          (str(nba_com_id),)).fetchall()
        if len(row) > 1:
            return "hold", None, "more than one row owns the nba.com id"
        if len(row) == 1:
            pid = row[0][0]
            have = con.execute("SELECT espn_id FROM players WHERE id=?", (pid,)).fetchone()[0]
            if have in (None, ""):
                return "attach_espn", pid, "nba.com id owner has no ESPN id"
            if str(have) == espn_id:
                return "reuse", pid, "nba.com id owner"
            return "hold", pid, "nba.com id owner carries a different ESPN id"
    key = name_key(name)
    listed = set()
    if espn_id:
        listed = {name_key(a) for a in name_aliases.aliases_for("nba", espn_id)}
    first, last = _first_last(key)
    cands = []
    for pid, other in con.execute("SELECT id, name FROM players WHERE league='nba'"):
        k = name_key(other)
        if k == key or k in listed or (first and _first_last(k) == (first, last)):
            cands.append(pid)
    if cands:
        return "hold", cands[0], "same-name candidate without id evidence: %s" % cands[:5]
    return "create", None, "no id, alias or name match"
