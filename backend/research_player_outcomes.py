#!/usr/bin/env python3
"""Verified player-level aces and double faults for CP4 (research). Writes only to research tables.

Each completed ESPN game with a linked tennis24 row gets one of three verification tiers, and any game
without one goes to identity_review_queue:

- official_labelled: an official Rolex Shanghai match-stat page names both players exactly, the first
  listed player is ESPN's home player, and the tennis24 left column equals that player's values.
- id_consistent: both tennis24 player codes map (from the matches each code appears in) to the two
  ESPN athlete ids of the linked game, and the tennis24 left column is the ESPN home player.
- cross_provider: 365scores has a row linked to the same ESPN game whose four values equal tennis24's
  in the same orientation.

Orientation is the left column = ESPN home player. It was checked on official pages (13 of 13 sampled
Shanghai matches, see docs/TENNIS-TOURNAMENT-STATS-2026-10-20.md) and on tennis24 header names (10 of
10 sampled pages once name order is normalised).

eligible_cp4 = 1 only for ESPN status Final with a tier and a parsed result. Retirements are stored
for audit with eligible_cp4 = 0.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import sys
import unicodedata
from typing import Any, Dict, List, Optional

import research_evidence as rpe

DDL = """
CREATE TABLE IF NOT EXISTS research_player_match_outcomes(
  tour TEXT NOT NULL,
  event TEXT NOT NULL,
  espn_game_id TEXT NOT NULL,
  espn_athlete_id TEXT NOT NULL,
  side TEXT NOT NULL,
  opponent_athlete_id TEXT,
  espn_status TEXT NOT NULL,
  aces INTEGER,
  double_faults INTEGER,
  verification_tier TEXT NOT NULL,
  provider TEXT NOT NULL,
  provider_match_id TEXT NOT NULL,
  official_url TEXT,
  raw_values TEXT NOT NULL,
  eligible_cp4 INTEGER NOT NULL,
  built_at TEXT NOT NULL,
  PRIMARY KEY(tour, espn_game_id, espn_athlete_id)
);
CREATE TABLE IF NOT EXISTS provider_player_identity(
  provider TEXT NOT NULL,
  provider_player_code TEXT NOT NULL,
  event TEXT NOT NULL,
  espn_athlete_id TEXT,
  evidence TEXT NOT NULL,
  verification_status TEXT NOT NULL,
  matches_seen INTEGER NOT NULL,
  reviewed_by TEXT,
  reviewed_at TEXT,
  PRIMARY KEY(provider, provider_player_code, event)
);
CREATE TABLE IF NOT EXISTS identity_review_queue(
  event TEXT NOT NULL,
  espn_game_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  provider_match_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  PRIMARY KEY(event, espn_game_id, provider, provider_match_id)
);
"""
COMPLETED = ("Final", "Retired")


def fold(text: str) -> str:
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower())


def same_person(a: str, b: str) -> bool:
    """Same name after folding, in any word order, or one name's words all inside the other's with the same surname.

    'Zhang Zhizhen' matches 'Zhizhen Zhang'. 'Coleman Wong' matches 'Chak Lam Coleman Wong' (same surname, and
    every word of the shorter name is in the longer one).
    """
    wa = [fold(w) for w in (a or "").split() if fold(w)]
    wb = [fold(w) for w in (b or "").split() if fold(w)]
    if not wa or not wb:
        return False
    if sorted(wa) == sorted(wb):
        return True
    shorter, longer = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return shorter[-1] == longer[-1] and set(shorter) <= set(longer)


def game_index(con: sqlite3.Connection, tournament_id: str) -> Dict[str, Dict[str, Any]]:
    games = {}
    for gid, league, payload in con.execute(
            "SELECT game_id, league, payload FROM scoreboard_snapshots WHERE state='post' AND league IN ('atp','wta')"):
        g = json.loads(payload or "{}")
        if str(g.get("tournament_id")) == tournament_id and str(g.get("status")) in COMPLETED:
            games[str(gid)] = {"league": league, "status": str(g.get("status")),
                               "home": g.get("home") or {}, "away": g.get("away") or {}}
    return games


def official_by_game(official: List[Dict[str, Any]], games: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Official pages keyed by ESPN game, only where the two names match exactly one completed game."""
    out: Dict[str, Dict[str, Any]] = {}
    for page in official:
        names = page.get("names")
        if not names or page.get("parse_status") != "ok":
            continue
        hits = []
        for gid, g in games.items():
            pair = {(g["home"].get("name") or ""), (g["away"].get("name") or "")}
            if all(any(same_person(n, p) for p in pair) for n in names) and len(pair) == 2:
                hits.append(gid)
        if len(hits) == 1:
            out[hits[0]] = page
    return out


def build_identity(con: sqlite3.Connection, event: str) -> Dict[str, int]:
    """Identity rows gain evidence only (research_evidence.upsert_identity). Single-match codes stay unverified."""
    con.executescript(DDL)
    counts: Dict[str, int] = {}
    for provider, code, athlete, status, seen in con.execute(
            "SELECT provider, provider_player_code, espn_athlete_id, status, matches_seen FROM provider_player_map WHERE event=?",
            (event,)).fetchall():
        if status == "proposed":
            verification = "id_consistent_multi_match"
            evidence = f"codes intersect across {seen} linked matches to one ESPN athlete"
        else:
            verification, athlete = "unverified_single_match", None
            evidence = "appears in one linked match; no identity evidence beyond that match"
        action = rpe.upsert_identity(con, provider, code, event, athlete, verification, evidence, seen)
        counts[action] = counts.get(action, 0) + 1
    con.commit()
    return counts


def build(con: sqlite3.Connection, event: str, tournament_id: str, official: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Assemble verified outcomes for one event. Never deletes; every write goes through research_evidence."""
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    rpe.ensure(con)
    if official:
        rpe.store_official_pages(con, event, official)
    official_pages = rpe.load_official_pages(con, event)
    games = game_index(con, tournament_id)
    official_map = official_by_game(official_pages, games)
    pmap = {(r[0], r[1]): r[2] for r in con.execute(
        "SELECT provider, provider_player_code, espn_athlete_id FROM provider_player_map WHERE event=? AND status='proposed'", (event,))}
    provider_rows = {}
    for r in con.execute(
            "SELECT s.provider, s.provider_match_id, s.source_url, s.home_aces, s.away_aces, s.home_double_faults, "
            "s.away_double_faults, s.parse_status, s.stats_view, l.espn_game_id gid, l.status link_status "
            "FROM provider_match_stats s JOIN provider_espn_links l ON l.provider=s.provider AND l.provider_match_id=s.provider_match_id "
            "WHERE s.event=? AND l.status IN ('proposed','stats_match') AND l.espn_game_id IS NOT NULL", (event,)):
        provider_rows.setdefault(str(r["gid"]), {})[r["provider"]] = r
    from provider_player_map import codes_for
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    counts: Dict[str, int] = {}
    for gid, g in games.items():
        league = g["league"]
        home = str(g["home"].get("athlete_id") or "")
        away = str(g["away"].get("athlete_id") or "")
        rows = provider_rows.get(gid, {})
        t24 = rows.get("tennis24")
        if t24 is None:
            con.execute("INSERT OR REPLACE INTO identity_review_queue VALUES(?,?,?,?,?)",
                        (event, gid, "none", "", "no provider row linked to this completed game"))
            counts["review"] = counts.get("review", 0) + 1
            continue
        if t24["parse_status"] != "ok":
            con.execute("INSERT OR REPLACE INTO identity_review_queue VALUES(?,?,?,?,?)",
                        (event, gid, "tennis24", t24["provider_match_id"], f"parse status {t24['parse_status']}"))
            counts["review"] = counts.get("review", 0) + 1
            continue
        left = (t24["home_aces"], t24["home_double_faults"])
        right = (t24["away_aces"], t24["away_double_faults"])
        tier, official_url, reason = None, None, None
        page = official_map.get(gid)
        if page is not None:
            page_first = (page.get("names") or [""])[0]
            if not same_person(page_first, g["home"].get("name") or ""):
                reason = "official first-listed player is not ESPN home"
            elif (page.get("home_aces"), page.get("home_double_faults")) == left and \
                    (page.get("away_aces"), page.get("away_double_faults")) == right:
                tier, official_url = "official_labelled", page.get("url")
            else:
                reason = "official values differ from tennis24"
        if tier is None and reason is None and "365scores" in rows:
            s = rows["365scores"]
            if (s["home_aces"], s["home_double_faults"], s["away_aces"], s["away_double_faults"]) == \
                    (t24["home_aces"], t24["home_double_faults"], t24["away_aces"], t24["away_double_faults"]):
                tier = "cross_provider"
        if tier is None and reason is None:
            codes = codes_for("tennis24", t24["source_url"])
            ids = [pmap.get(("tennis24", c)) for c in codes]
            if len(codes) == 2 and None not in ids and set(ids) == {home, away} and home != away:
                tier = "id_consistent"
        if tier is None:
            reason = reason or "no verification tier (codes not id-consistent, no official or cross-provider row)"
            con.execute("INSERT OR REPLACE INTO identity_review_queue VALUES(?,?,?,?,?)",
                        (event, gid, "tennis24", t24["provider_match_id"], reason))
            counts["review"] = counts.get("review", 0) + 1
            continue
        confirmed = "sum to match" in (t24["stats_view"] or "")
        eligible = 1 if (g["status"] == "Final" and (tier in ("official_labelled", "cross_provider") or confirmed)) else 0
        raw = json.dumps({"tennis24": {k: t24[k] for k in ("home_aces", "away_aces", "home_double_faults", "away_double_faults")},
                          "stats_view": t24["stats_view"]}, sort_keys=True)
        for side, athlete, opponent, aces, dfs in (
                ("home", home, away, left[0], left[1]),
                ("away", away, home, right[0], right[1])):
            action = rpe.upsert_outcome(con, {
                "tour": league, "event": event, "espn_game_id": gid, "espn_athlete_id": athlete, "side": side,
                "opponent_athlete_id": opponent, "espn_status": g["status"], "aces": aces, "double_faults": dfs,
                "verification_tier": tier, "provider": "tennis24", "provider_match_id": t24["provider_match_id"],
                "official_url": official_url, "raw_values": raw, "eligible_cp4": eligible, "built_at": now})
            counts[action] = counts.get(action, 0) + 1
    con.commit()
    return counts


def main() -> int:
    db, event, tournament_id = sys.argv[1], sys.argv[2], sys.argv[3]
    official_path = sys.argv[4] if len(sys.argv) > 4 else None
    if db.endswith("picks.dev.db"):
        raise SystemExit("refusing to write to picks.dev.db; use a copy")
    official = json.load(open(official_path)) if official_path else None
    con = sqlite3.connect(db)
    try:
        print(json.dumps(build(con, event, tournament_id, official), indent=1, sort_keys=True))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
