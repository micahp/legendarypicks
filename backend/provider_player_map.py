#!/usr/bin/env python3
"""Propose provider player codes -> ESPN athlete ids from the matches a code appears in (research, CP4).

A provider code (the numbers in a 365scores match URL, or the code after a tennis24 player slug) is
assumed to name one player. For each code, the ESPN athletes in every linked match are intersected.
A code that appears in two or more matches and intersects to one athlete is PROPOSED with its evidence
count. A code in one match only is single_match; an empty intersection is conflict. Nothing here is
reviewed. The table is provider_player_map and is not the authoritative identity source.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import defaultdict

import research_evidence as rpe
from typing import Dict, List, Set

DDL = """
CREATE TABLE IF NOT EXISTS provider_player_map(
  provider TEXT NOT NULL,
  provider_player_code TEXT NOT NULL,
  event TEXT NOT NULL,
  espn_athlete_id TEXT,
  status TEXT NOT NULL,
  matches_seen INTEGER NOT NULL,
  PRIMARY KEY(provider, provider_player_code, event)
);
"""


def codes_for(provider: str, url: str) -> List[str]:
    if provider == "365scores":
        match = re.search(r"-(\d+)-(\d+)-\d+#", url)
        return [match.group(1), match.group(2)] if match else []
    match = re.search(r"/match/([^/]+)/([^/]+)/\?mid=", url)
    if not match:
        return []
    return [segment.rsplit("-", 1)[-1] for segment in match.groups()]


def build(con: sqlite3.Connection, event: str) -> Dict[str, int]:
    con.executescript(DDL)
    payloads = {str(gid): json.loads(p or "{}") for gid, p in con.execute(
        "SELECT game_id, payload FROM scoreboard_snapshots WHERE state='post' AND league IN ('atp','wta')")}
    seen: Dict[tuple, List[Set[str]]] = defaultdict(list)
    for provider, url, gid in con.execute(
            "SELECT s.provider, s.source_url, l.espn_game_id FROM provider_match_stats s "
            "JOIN provider_espn_links l ON l.provider=s.provider AND l.provider_match_id=s.provider_match_id "
            "WHERE s.event=? AND l.status IN ('proposed','stats_match') AND l.espn_game_id IS NOT NULL", (event,)):
        game = payloads.get(str(gid), {})
        athletes = {str((game.get(side) or {}).get("athlete_id") or "") for side in ("home", "away")} - {""}
        for code in codes_for(provider, url):
            seen[(provider, code)].append(athletes)
    counts = defaultdict(int)
    for (provider, code), sets in seen.items():
        inter = set.intersection(*sets) if sets else set()
        if len(sets) == 1:
            status, athlete = "single_match", None
        elif len(inter) == 1:
            status, athlete = "proposed", next(iter(inter))
        else:
            status, athlete = "conflict", None
        accepted = con.execute("SELECT espn_athlete_id FROM provider_player_map WHERE provider=? AND provider_player_code=? "
                               "AND event=?", (provider, code, event)).fetchone()
        if accepted is not None and accepted[0] and athlete and accepted[0] != athlete:
            rpe.record_conflict(con, "identity", f"{provider}|{code}|{event}", {"espn_athlete_id": accepted[0]},
                                {"espn_athlete_id": athlete})
            counts["conflict"] = counts.get("conflict", 0) + 1
            continue
        con.execute("INSERT OR REPLACE INTO provider_player_map(provider,provider_player_code,event,espn_athlete_id,"
                    "status,matches_seen) VALUES(?,?,?,?,?,?)", (provider, code, event, athlete, status, len(sets)))
        counts[f"{provider}:{status}"] += 1
    con.commit()
    return dict(counts)


def main() -> int:
    db, event = sys.argv[1], sys.argv[2]
    if db.endswith("picks.dev.db"):
        raise SystemExit("refusing to write to picks.dev.db; use a copy")
    con = sqlite3.connect(db)
    try:
        print(json.dumps(build(con, event), indent=1, sort_keys=True))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
