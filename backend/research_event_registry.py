#!/usr/bin/env python3
"""Event discovery and the supported-tournament registry for the tennis research collector (research only).

ESPN is the discovery source. Each ESPN tournament with games in the active window gets a registry row. A
tournament is SUPPORTED only when a tennis24 results page loads and its title names the tournament. The
tennis24 slug is a candidate built from the ESPN name, so an unsupported tournament shows the candidates tried.
Verified mappings are never removed. Unsupported ones are retried on later runs.

Seeds: Wuhan and Shanghai were verified by hand in the 2026-10-20 work and are recorded as seeds.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from typing import Any, Dict, List, Optional

DDL = """
CREATE TABLE IF NOT EXISTS tournament_registry(
  espn_tournament_id TEXT NOT NULL,
  league TEXT NOT NULL,
  espn_event_name TEXT,
  event_key TEXT,
  tennis24_results_url TEXT,
  mapping_status TEXT NOT NULL,
  mapping_evidence TEXT,
  candidates_tried TEXT,
  checked_at TEXT,
  PRIMARY KEY(espn_tournament_id, league)
);
"""
GENERIC = {"open", "masters", "presented", "by", "international", "championship", "championships", "tour", "atp",
           "wta", "singles", "doubles", "men", "women", "tennis", "the", "of", "and", "in", "at", "cup", "classic",
           "trophy", "finals", "final", "group", "bnb", "chn", "jpn", "usa"}
SEEDS = [
    ("381", "wta", "Dongfeng Voyah Wuhan Open", "wuhan-wta-2026", "https://www.tennis24.com/wta-singles/wuhan/results/",
     "seeded: verified by hand 2026-10-20 (tennis24 title 'WTA Wuhan')"),
    ("315", "atp", "Rolex Shanghai Masters", "shanghai-atp-2026", "https://www.tennis24.com/atp-singles/shanghai/results/",
     "seeded: verified by hand 2026-10-20 (tennis24 title 'ATP Shanghai')"),
]


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(DDL)
    for tid, league, name, key, url, evidence in SEEDS:
        con.execute("INSERT OR IGNORE INTO tournament_registry(espn_tournament_id,league,espn_event_name,event_key,"
                    "tennis24_results_url,mapping_status,mapping_evidence,checked_at) VALUES(?,?,?,?,?,'supported',?,?)",
                    (tid, league, name, key, url, evidence, dt.datetime.now(dt.timezone.utc).isoformat()))
    con.commit()


def espn_tournaments(con: sqlite3.Connection, today: dt.date, window_days: int = 14) -> Dict[tuple, Dict[str, Any]]:
    """ESPN tournaments with any game dated within window_days of today, keyed by (id, league)."""
    lo, hi = (today - dt.timedelta(days=window_days)).isoformat(), (today + dt.timedelta(days=window_days)).isoformat()
    out: Dict[tuple, Dict[str, Any]] = {}
    for league, game_date, payload, state in con.execute(
            "SELECT league, game_date, payload, state FROM scoreboard_snapshots WHERE league IN ('atp','wta')"):
        g = json.loads(payload or "{}")
        tid = str(g.get("tournament_id") or "")
        if not tid or tid == "None" or not (lo <= str(game_date) <= hi):
            continue
        t = out.setdefault((tid, league), {"name": str(g.get("event") or ""), "dates": [], "completed": 0, "upcoming": 0})
        t["dates"].append(str(game_date))
        if str(g.get("status")) in ("Final", "Retired"):
            t["completed"] += 1
        elif state == "pre":
            t["upcoming"] += 1
    for t in out.values():
        t["first"], t["last"] = min(t["dates"]), max(t["dates"])
        del t["dates"]
    return out


def distinctive_words(name: str) -> List[str]:
    """Non-generic words of the ESPN name, in order, de-duplicated. Sponsor words are tried and then rejected by the page check."""
    out: List[str] = []
    for w in re.findall(r"[a-z]+", name.lower()):
        if w not in GENERIC and len(w) > 2 and w not in out:
            out.append(w)
    return out


def candidate_slugs(name: str) -> List[str]:
    """At most four candidate tennis24 slugs. The city usually appears among the words."""
    return distinctive_words(name)[:4]


def title_names(title: str, word: str) -> bool:
    """True when the page title contains the candidate word, as a whole word."""
    return bool(re.search(rf"\b{re.escape(word)}\b", (title or "").lower()))


def results_url(league: str, slug: str) -> str:
    return f"https://www.tennis24.com/{league}-singles/{slug}/results/"


def event_key(slug: str, league: str, year: int) -> str:
    return f"{slug}-{league}-{year}"


def supported(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    ensure(con)
    rows = con.execute("SELECT espn_tournament_id, league, event_key, tennis24_results_url FROM tournament_registry "
                       "WHERE mapping_status='supported'").fetchall()
    return [{"tournament_id": t, "league": l, "event": e, "list_url": u} for t, l, e, u in rows]


def discover(con: sqlite3.Connection, browser, today: dt.date, window_days: int = 14, pace_s: float = 5.0) -> Dict[str, Any]:
    """Map every ESPN tournament in the window to a tennis24 results page, or record why it cannot be mapped."""
    import time
    ensure(con)
    report = {"checked": 0, "newly_supported": 0, "unsupported": []}
    known = {(t, l): s for t, l, s in con.execute("SELECT espn_tournament_id, league, mapping_status FROM tournament_registry")}
    for (tid, league), info in sorted(espn_tournaments(con, today, window_days).items()):
        if known.get((tid, league)) == "supported":
            continue
        tried, found = [], None
        for slug in candidate_slugs(info["name"]):
            url = results_url(league, slug)
            tried.append(slug)
            page = browser.new_page()
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                title = page.title()
                if response is not None and response.status == 200 and title_names(title, slug):
                    found = (slug, url, title)
            except Exception:
                pass
            finally:
                page.close()
            time.sleep(pace_s)
            report["checked"] += 1
            if found:
                break
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if found:
            slug, url, title = found
            year = int(info["last"][:4]) if info.get("last") else today.year
            con.execute("INSERT OR REPLACE INTO tournament_registry(espn_tournament_id,league,espn_event_name,event_key,"
                        "tennis24_results_url,mapping_status,mapping_evidence,candidates_tried,checked_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (tid, league, info["name"], event_key(slug, league, year), url, "supported",
                         f"tennis24 title '{title}' names the tournament", json.dumps(tried), now))
            report["newly_supported"] += 1
        else:
            con.execute("INSERT OR REPLACE INTO tournament_registry(espn_tournament_id,league,espn_event_name,event_key,"
                        "tennis24_results_url,mapping_status,mapping_evidence,candidates_tried,checked_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (tid, league, info["name"], None, None, "unsupported", "no candidate page named the tournament",
                         json.dumps(tried), now))
            report["unsupported"].append({"tournament_id": tid, "league": league, "espn_event_name": info["name"],
                                          "candidates_tried": tried})
        con.commit()
    return report


def coverage(con: sqlite3.Connection, today: dt.date, window_days: int = 14) -> List[Dict[str, Any]]:
    """One row per ESPN tournament in the window: completed matches and where each one stands."""
    ensure(con)
    registry = {(t, l): dict(zip(("status", "event", "candidates"), (s, e, c))) for t, l, s, e, c in con.execute(
        "SELECT espn_tournament_id, league, mapping_status, event_key, candidates_tried FROM tournament_registry")}
    out = []
    for (tid, league), info in sorted(espn_tournaments(con, today, window_days).items()):
        reg = registry.get((tid, league), {"status": "not_checked", "event": None, "candidates": None})
        row = {"tournament_id": tid, "league": league, "espn_event_name": info["name"], "dates": [info["first"], info["last"]],
               "completed_espn": info["completed"], "upcoming_espn": info["upcoming"], "mapping": reg["status"],
               "event": reg["event"]}
        if reg["status"] == "unsupported":
            row["candidates_tried"] = json.loads(reg["candidates"] or "[]")
        out.append(row)
    return out
