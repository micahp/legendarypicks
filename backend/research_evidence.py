#!/usr/bin/env python3
"""Monotonic evidence rules for the research tennis tables (research only).

Routine collection must never downgrade, delete or silently overwrite accepted evidence. Each write goes
through one of these helpers:

- an accepted outcome may be refreshed, or upgraded to a stronger tier when the values are unchanged;
- an accepted outcome is never removed, and never replaced by different values;
- different values, or a different athlete for the same provider identity or link, are recorded in an
  evidence_conflicts row with both sides, and the accepted record stays as it was.

Official match-stat pages are stored here too, so later runs do not need them passed in again.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Any, Dict, Optional

TIER_RANK = {"official_labelled": 3, "cross_provider": 2, "id_consistent": 1}
IDENTITY_RANK = {"id_consistent_multi_match": 2, "unverified_single_match": 1}

DDL = """
CREATE TABLE IF NOT EXISTS evidence_conflicts(
  conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  scope_key TEXT NOT NULL,
  accepted TEXT NOT NULL,
  incoming TEXT NOT NULL,
  detected_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS official_match_pages(
  event TEXT NOT NULL,
  url TEXT NOT NULL,
  names TEXT,
  home_aces INTEGER,
  away_aces INTEGER,
  home_double_faults INTEGER,
  away_double_faults INTEGER,
  parse_status TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY(event, url)
);
"""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(DDL)


def record_conflict(con: sqlite3.Connection, kind: str, scope_key: str, accepted: Any, incoming: Any) -> None:
    con.execute("INSERT INTO evidence_conflicts(kind,scope_key,accepted,incoming,detected_at) VALUES(?,?,?,?,?)",
                (kind, scope_key, json.dumps(accepted, sort_keys=True), json.dumps(incoming, sort_keys=True), now_iso()))


def store_official_pages(con: sqlite3.Connection, event: str, pages: list) -> Dict[str, int]:
    """Upsert official pages. A page whose values change is a conflict, and the stored page is kept."""
    ensure(con)
    counts = {"stored": 0, "unchanged": 0, "conflict": 0}
    for page in pages:
        url = page.get("url")
        if not url:
            continue
        values = (json.dumps(page.get("names")), page.get("home_aces"), page.get("away_aces"),
                  page.get("home_double_faults"), page.get("away_double_faults"), page.get("parse_status") or "error")
        existing = con.execute("SELECT names, home_aces, away_aces, home_double_faults, away_double_faults, parse_status "
                               "FROM official_match_pages WHERE event=? AND url=?", (event, url)).fetchone()
        if existing is None:
            con.execute("INSERT INTO official_match_pages VALUES(?,?,?,?,?,?,?,?,?)", (event, url, *values, now_iso()))
            counts["stored"] += 1
        elif tuple(existing) == values:
            counts["unchanged"] += 1
        else:
            record_conflict(con, "official_page", f"{event}|{url}", tuple(existing), values)
            counts["conflict"] += 1
    con.commit()
    return counts


def load_official_pages(con: sqlite3.Connection, event: str) -> list:
    ensure(con)
    rows = con.execute("SELECT url, names, home_aces, away_aces, home_double_faults, away_double_faults, parse_status "
                       "FROM official_match_pages WHERE event=?", (event,)).fetchall()
    return [{"url": u, "names": json.loads(n) if n else None, "home_aces": a, "away_aces": b,
             "home_double_faults": c, "away_double_faults": d, "parse_status": s} for u, n, a, b, c, d, s in rows]


def upsert_outcome(con: sqlite3.Connection, row: Dict[str, Any]) -> str:
    """Write one player outcome under the monotonic rules. Returns the action taken."""
    key = (row["tour"], row["espn_game_id"], row["espn_athlete_id"])
    accepted = con.execute(
        "SELECT aces, double_faults, verification_tier, eligible_cp4 FROM research_player_match_outcomes "
        "WHERE tour=? AND espn_game_id=? AND espn_athlete_id=?", key).fetchone()
    columns = ("tour", "event", "espn_game_id", "espn_athlete_id", "side", "opponent_athlete_id", "espn_status",
               "aces", "double_faults", "verification_tier", "provider", "provider_match_id", "official_url",
               "raw_values", "eligible_cp4", "built_at")
    if accepted is None:
        con.execute(f"INSERT INTO research_player_match_outcomes({','.join(columns)}) VALUES({','.join('?' * len(columns))})",
                    tuple(row[c] for c in columns))
        return "inserted"
    same_values = (accepted["aces"], accepted["double_faults"]) == (row["aces"], row["double_faults"])
    if not same_values:
        record_conflict(con, "outcome", "|".join(key),
                        {"aces": accepted["aces"], "double_faults": accepted["double_faults"],
                         "tier": accepted["verification_tier"]},
                        {"aces": row["aces"], "double_faults": row["double_faults"], "tier": row["verification_tier"]})
        return "conflict"
    new_rank = TIER_RANK.get(row["verification_tier"], 0)
    old_rank = TIER_RANK.get(accepted["verification_tier"], 0)
    if new_rank > old_rank:
        con.execute("UPDATE research_player_match_outcomes SET verification_tier=?, provider=?, provider_match_id=?, "
                    "official_url=?, raw_values=?, built_at=? WHERE tour=? AND espn_game_id=? AND espn_athlete_id=?",
                    (row["verification_tier"], row["provider"], row["provider_match_id"], row["official_url"],
                     row["raw_values"], row["built_at"], *key))
        if row["eligible_cp4"] and not accepted["eligible_cp4"]:
            con.execute("UPDATE research_player_match_outcomes SET eligible_cp4=1 WHERE tour=? AND espn_game_id=? "
                        "AND espn_athlete_id=?", key)
        return "upgraded"
    if row["eligible_cp4"] and not accepted["eligible_cp4"]:
        con.execute("UPDATE research_player_match_outcomes SET eligible_cp4=1, built_at=? WHERE tour=? AND "
                    "espn_game_id=? AND espn_athlete_id=?", (row["built_at"], *key))
        return "eligibility_upgraded"
    con.execute("UPDATE research_player_match_outcomes SET built_at=? WHERE tour=? AND espn_game_id=? AND espn_athlete_id=?",
                (row["built_at"], *key))
    return "refreshed"


def upsert_identity(con: sqlite3.Connection, provider: str, code: str, event: str, athlete: Optional[str],
                    status: str, evidence: str, seen: int) -> str:
    """Identity rows only ever gain evidence. A different athlete for an accepted code is a conflict."""
    accepted = con.execute("SELECT espn_athlete_id, verification_status FROM provider_player_identity "
                           "WHERE provider=? AND provider_player_code=? AND event=?", (provider, code, event)).fetchone()
    if accepted is None:
        con.execute("INSERT INTO provider_player_identity(provider,provider_player_code,event,espn_athlete_id,evidence,"
                    "verification_status,matches_seen) VALUES(?,?,?,?,?,?,?)",
                    (provider, code, event, athlete, evidence, status, seen))
        return "inserted"
    if accepted["espn_athlete_id"] and athlete and accepted["espn_athlete_id"] != athlete:
        record_conflict(con, "identity", f"{provider}|{code}|{event}",
                        {"espn_athlete_id": accepted["espn_athlete_id"]}, {"espn_athlete_id": athlete})
        return "conflict"
    if IDENTITY_RANK.get(status, 0) > IDENTITY_RANK.get(accepted["verification_status"], 0):
        con.execute("UPDATE provider_player_identity SET espn_athlete_id=?, evidence=?, verification_status=?, "
                    "matches_seen=? WHERE provider=? AND provider_player_code=? AND event=? AND reviewed_by IS NULL",
                    (athlete or accepted["espn_athlete_id"], evidence, status, seen, provider, code, event))
        return "upgraded"
    return "kept"


def upsert_link(con: sqlite3.Connection, provider: str, match_id: str, event: str, game_id: Optional[str],
                status: str, method: str, candidates: str) -> str:
    """Provider-to-ESPN links only gain evidence. A different accepted game is a conflict, not an overwrite."""
    accepted = con.execute("SELECT espn_game_id, status FROM provider_espn_links WHERE provider=? AND provider_match_id=?",
                           (provider, match_id)).fetchone()
    if accepted is None:
        con.execute("INSERT INTO provider_espn_links(provider,provider_match_id,event,espn_game_id,status,method,candidates) "
                    "VALUES(?,?,?,?,?,?,?)", (provider, match_id, event, game_id, status, method, candidates))
        return "inserted"
    if accepted["status"] in ("proposed", "stats_match") and game_id and accepted["espn_game_id"] != game_id:
        record_conflict(con, "link", f"{provider}|{match_id}",
                        {"espn_game_id": accepted["espn_game_id"], "status": accepted["status"]},
                        {"espn_game_id": game_id, "status": status})
        return "conflict"
    if accepted["status"] in ("proposed", "stats_match"):
        return "kept"
    if status in ("proposed", "stats_match") or accepted["status"] == "review" and status == "review":
        con.execute("UPDATE provider_espn_links SET espn_game_id=?, status=?, method=?, candidates=? "
                    "WHERE provider=? AND provider_match_id=?", (game_id, status, method, candidates, provider, match_id))
        return "upgraded" if status != "review" else "refreshed"
    return "kept"
