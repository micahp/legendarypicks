#!/usr/bin/env python3
"""Propose ESPN game links for provider match stats, and report what could not be linked (research, CP4).

Evidence, weakest to strongest:
- a provider match is a candidate for an ESPN final in the same event when both players' surnames
  appear in the provider's URL slug (or anchor text);
- a link is PROPOSED only when exactly one ESPN final in the event matches both surnames;
- anything with zero or several candidates goes to REVIEW with the candidates listed.

Names are used only to propose. The join key that the stats depend on is the ESPN game id. Once a
provider player id has been reviewed against an ESPN athlete id, that id pair should replace names.
Nothing here is confirmed by a second source yet; `method` says what was used.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

DDL = """
CREATE TABLE IF NOT EXISTS provider_espn_links(
  provider TEXT NOT NULL,
  provider_match_id TEXT NOT NULL,
  event TEXT NOT NULL,
  espn_game_id TEXT,
  status TEXT NOT NULL,
  method TEXT NOT NULL,
  candidates TEXT,
  PRIMARY KEY(provider, provider_match_id)
);
"""

# Completed matches: a Retired match is finished and can carry partial stats; grading excludes it later.
COMPLETED_STATUS = ("Final", "Retired")
TOKEN = re.compile(r"[a-z]+")


def _normal_tokens(text: str) -> Set[str]:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    return set(TOKEN.findall(folded))


def espn_surnames(name: str) -> Set[str]:
    """The last word of a name (ESPN gives full names). Compound surnames match on their last word."""
    tokens = [t for t in TOKEN.findall(unicodedata.normalize("NFKD", name or "")
                                       .encode("ascii", "ignore").decode("ascii").lower())]
    return {tokens[-1]} if tokens else set()


def link_provider_match(provider_text: str, espn_finals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify one provider match against the event's ESPN finals.

    `provider_text` is the URL slug plus anchor text. `espn_finals` rows have game_id, home, away.
    """
    text_tokens = _normal_tokens(provider_text)
    candidates = []
    for final in espn_finals:
        home, away = espn_surnames(final["home"]), espn_surnames(final["away"])
        if home and away and home <= text_tokens and away <= text_tokens:
            candidates.append(final["game_id"])
    if len(candidates) == 1:
        return {"status": "proposed", "espn_game_id": candidates[0], "candidates": candidates,
                "method": "exact surname pair within the event"}
    if not candidates:
        return {"status": "review", "espn_game_id": None, "candidates": [],
                "method": "no ESPN final has both surnames"}
    return {"status": "review", "espn_game_id": None, "candidates": candidates,
            "method": "several ESPN finals share both surnames"}


def load_espn_finals(con: sqlite3.Connection, tournament_id: str) -> List[Dict[str, Any]]:
    """ESPN finals for one tournament id, from the scoreboard snapshots."""
    finals: Dict[str, Dict[str, Any]] = {}
    for game_id, payload in con.execute(
            "SELECT game_id, payload FROM scoreboard_snapshots WHERE league IN ('atp','wta') AND state='post'"):
        game = json.loads(payload or "{}")
        if str(game.get("status")) not in COMPLETED_STATUS or str(game.get("tournament_id")) != tournament_id:
            continue
        finals[str(game_id)] = {
            "game_id": str(game_id),
            "home": (game.get("home") or {}).get("name") or "",
            "away": (game.get("away") or {}).get("name") or "",
        }
    return list(finals.values())


def build(con: sqlite3.Connection, event: str, tournament_id: str) -> Dict[str, Any]:
    """Link every provider match stored for an event and write the result rows."""
    con.executescript(DDL)
    finals = load_espn_finals(con, tournament_id)
    rows = con.execute(
        "SELECT provider, provider_match_id, source_url, anchor_text FROM provider_match_stats WHERE event=?",
        (event,)).fetchall()
    summary: Dict[str, Any] = {"espn_finals": len(finals), "provider_matches": len(rows),
                               "proposed": 0, "review": 0, "linked_espn_games": {}}
    linked: Dict[str, Set[str]] = {}
    for provider, provider_match_id, source_url, anchor_text in rows:
        kept = con.execute("SELECT status FROM provider_espn_links WHERE provider=? AND provider_match_id=?",
                           (provider, provider_match_id)).fetchone()
        if kept and kept[0] == "stats_match":
            continue  # promoted by provider_review_resolver; a rerun must not reset it to review
        result = link_provider_match(f"{source_url} {anchor_text or ''}", finals)
        con.execute(
            "INSERT OR REPLACE INTO provider_espn_links(provider,provider_match_id,event,espn_game_id,status,method,"
            "candidates) VALUES(?,?,?,?,?,?,?)",
            (provider, provider_match_id, event, result["espn_game_id"], result["status"], result["method"],
             json.dumps(result["candidates"])))
        summary[result["status"]] += 1
        if result["espn_game_id"]:
            linked.setdefault(provider, set()).add(result["espn_game_id"])
    con.commit()
    summary["linked_espn_games"] = {p: len(g) for p, g in linked.items()}
    return summary


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: provider_espn_crosswalk.py <db> <event> <espn_tournament_id>", file=sys.stderr)
        return 2
    db, event, tournament_id = sys.argv[1], sys.argv[2], sys.argv[3]
    if db.endswith("picks.dev.db"):
        raise SystemExit("refusing to write to picks.dev.db; use a copy")
    con = sqlite3.connect(db)
    try:
        print(json.dumps(build(con, event, tournament_id), indent=1, sort_keys=True))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
