#!/usr/bin/env python3
"""Resolve review cases using ESPN games and cross-provider stats (research, CP4). Writes nothing to the crosswalk.

For each provider match in review (no ESPN final with both surnames):
1. Take each named player's surname from the provider slug (tennis24 is surname-first; 365scores is
   first-last, so the surname is the last word of its name part).
2. Candidate ESPN games: completed games in the event containing an athlete with that surname, not already
   linked by the same provider.
3. For each candidate, compare the review match's four stats (both players' aces and double faults, in
   either orientation) with the rows the other provider linked to that same ESPN game.

Result rows go to provider_review_resolution with a status:
- stats_match: the candidate game's other-provider row has the same values in one of the two
  orientations. This is cross-provider agreement at player level, which is a provisional link.
- candidate: a candidate exists but no other-provider row can confirm it.
- no_candidate: no ESPN completed game contains either surname.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unicodedata

import research_evidence as rpe
from typing import Any, Dict, List

DDL = """
CREATE TABLE IF NOT EXISTS provider_review_resolution(
  provider TEXT NOT NULL,
  provider_match_id TEXT NOT NULL,
  event TEXT NOT NULL,
  candidate_espn_game_id TEXT,
  status TEXT NOT NULL,
  evidence TEXT NOT NULL,
  PRIMARY KEY(provider, provider_match_id, candidate_espn_game_id)
);
"""
COMPLETED = ("Final", "Retired")


def fold(text: str) -> str:
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower())


def slug_surnames(provider: str, url: str) -> List[str]:
    """Surname per side, read from the slug. tennis24: surname first; 365scores: first-last."""
    if provider == "tennis24":
        match = re.search(r"/match/([^/]+)/([^/]+)/\?mid=", url)
        if not match:
            return []
        return [fold(segment.rsplit("-", 1)[0].split("-")[0]) for segment in match.groups()]
    match = re.search(r"/match/[^/]+/([^/]+)#", url)
    if not match:
        return []
    names = re.sub(r"-\d+(-\d+)*-\d+$", "", match.group(1))
    tokens = [t for t in names.split("-") if t]
    half = len(tokens) // 2
    return [fold(tokens[half - 1]), fold(tokens[-1])] if len(tokens) >= 2 else []


def stats_of(row) -> tuple:
    return (row["home_aces"], row["away_aces"], row["home_double_faults"], row["away_double_faults"])


def build(con: sqlite3.Connection, event: str, tournament_id: str) -> Dict[str, int]:
    con.executescript(DDL)
    games = {}
    for gid, payload in con.execute("SELECT game_id, payload FROM scoreboard_snapshots WHERE state='post' AND league IN ('atp','wta')"):
        g = json.loads(payload or "{}")
        if str(g.get("tournament_id")) == tournament_id and str(g.get("status")) in COMPLETED:
            games[str(gid)] = g
    linked_by = {}
    for provider, gid, status in con.execute("SELECT provider, espn_game_id, status FROM provider_espn_links WHERE event=?", (event,)):
        if status == "proposed" and gid:
            linked_by.setdefault((provider, str(gid)), None)
    stats_rows = {}
    for r in con.execute("SELECT s.provider, s.provider_match_id, s.home_aces, s.away_aces, s.home_double_faults, s.away_double_faults, l.espn_game_id gid "
                         "FROM provider_match_stats s JOIN provider_espn_links l ON l.provider=s.provider AND l.provider_match_id=s.provider_match_id "
                         "WHERE l.status='proposed' AND s.event=?", (event,)):
        stats_rows.setdefault(str(r["gid"]), []).append(r)
    counts: Dict[str, int] = {}
    con.execute("DELETE FROM provider_review_resolution WHERE event=?", (event,))
    reviews = con.execute("SELECT s.* FROM provider_match_stats s JOIN provider_espn_links l ON l.provider=s.provider AND l.provider_match_id=s.provider_match_id "
                          "WHERE l.status='review' AND s.event=?", (event,)).fetchall()
    for row in reviews:
        surnames = slug_surnames(row["provider"], row["source_url"])
        own = {r["provider"] for r in stats_rows.get("", [])}  # placeholder for clarity
        results = []
        for gid, g in games.items():
            names = [(g.get(side) or {}).get("name") or "" for side in ("home", "away")]
            # ESPN order varies (e.g. 'Guo Hanyu' has the surname first), so every name word is a candidate surname.
            game_surnames = {fold(word) for n in names for word in n.split() if fold(word)}
            hits = [s for s in surnames if s and s in game_surnames]
            if not hits:
                continue
            if any(r["provider"] == row["provider"] for r in stats_rows.get(gid, [])):
                continue  # this provider already has this game
            others = [r for r in stats_rows.get(gid, []) if r["provider"] != row["provider"]]
            mine = (row["home_aces"], row["away_aces"], row["home_double_faults"], row["away_double_faults"])
            match_stats = [o["provider"] for o in others if stats_of(o) == mine or
                           stats_of(o) == (mine[1], mine[0], mine[3], mine[2])]
            results.append((gid, names, len(hits), match_stats))
        if not results:
            status, evidence = "no_candidate", json.dumps({"surnames": surnames})
            con.execute("INSERT OR REPLACE INTO provider_review_resolution VALUES(?,?,?,?,?,?)",
                        (row["provider"], row["provider_match_id"], event, None, status, evidence))
            counts[status] = counts.get(status, 0) + 1
            continue
        for gid, names, nhits, match_stats in results:
            status = "stats_match" if match_stats else "candidate"
            evidence = json.dumps({"espn_names": names, "surnames_hit": nhits, "agreeing_providers": match_stats})
            con.execute("INSERT OR REPLACE INTO provider_review_resolution VALUES(?,?,?,?,?,?)",
                        (row["provider"], row["provider_match_id"], event, gid, status, evidence))
            counts[status] = counts.get(status, 0) + 1
    # Promote review cases with exactly one stats-confirmed ESPN game to provisional links.
    promoted = con.execute(
        "SELECT provider, provider_match_id, candidate_espn_game_id FROM provider_review_resolution "
        "WHERE event=? AND status='stats_match' GROUP BY provider, provider_match_id HAVING COUNT(*)=1", (event,)).fetchall()
    for provider, match_id, gid in promoted:
        rpe.upsert_link(con, provider, match_id, event, gid, "stats_match",
                        "stats equal to the other provider's row for this ESPN game", "[]")
    counts["promoted_to_stats_match"] = len(promoted)
    con.commit()
    return counts


def main() -> int:
    db, event, tournament_id = sys.argv[1], sys.argv[2], sys.argv[3]
    if db.endswith("picks.dev.db"):
        raise SystemExit("refusing to write to picks.dev.db; use a copy")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        print(json.dumps(build(con, event, tournament_id), indent=1, sort_keys=True))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
