#!/usr/bin/env python3
"""Daily prospective collection of provider match stats, in an isolated research database (research only).

What one run does:
1. Copies the ESPN scoreboard snapshots for the registered tournaments from the live database, opened
   read-only, into the research database. The live database is never written.
2. For each registered event, enumerates the provider's results page and fetches only matches that are not
   already stored with status ok (ingest_provider_match_stats, 5 s pacing, 1.5 GB memory floor, stop rules).
3. Rebuilds the provisional links, the identity table, and the verified outcome table, all inside the
   research database.
4. Writes a JSON report with coverage and failures. Nothing is published, and nothing unresolved is graded.

Tournaments not in REGISTRY are reported as unsupported, not fetched.

  python3 backend/research_daily_collect.py --live-db <picks.dev.db> --research-db <research.db> [--limit N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ingest_provider_match_stats as ing  # noqa: E402
import provider_espn_crosswalk as cw  # noqa: E402
import provider_player_map as ppm  # noqa: E402
import provider_review_resolver as prr  # noqa: E402
import research_player_outcomes as rpo  # noqa: E402
import scoreboard_store  # noqa: E402

# Official labelled pages exist only for the Shanghai event, so only it is checked against them.
OFFICIAL_EVENT = "shanghai-atp-2026"
REGISTRY = {
    "381": {"event": "wuhan-wta-2026", "tour": "wta"},
    "315": {"event": "shanghai-atp-2026", "tour": "atp"},
}


def sync_snapshots(live_path: str, research: sqlite3.Connection) -> int:
    live = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True, timeout=30)
    try:
        rows = live.execute("SELECT league, game_date, game_id, payload, state, start_time, fetched_at, source "
                            "FROM scoreboard_snapshots WHERE league IN ('atp','wta')").fetchall()
    finally:
        live.close()
    copied = 0
    for league, game_date, game_id, payload, state, start_time, fetched_at, source in rows:
        tid = str((json.loads(payload or "{}")).get("tournament_id"))
        if tid not in REGISTRY:
            continue
        research.execute("INSERT OR REPLACE INTO scoreboard_snapshots(league,game_date,game_id,payload,state,start_time,"
                         "fetched_at,source) VALUES(?,?,?,?,?,?,?,?)",
                         (league, game_date, game_id, payload, state, start_time, fetched_at, source))
        copied += 1
    research.commit()
    return copied


def completed_counts(research: sqlite3.Connection) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    seen = set()
    for game_id, payload in research.execute("SELECT game_id, payload FROM scoreboard_snapshots WHERE state='post'"):
        g = json.loads(payload or "{}")
        tid = str(g.get("tournament_id"))
        if tid not in REGISTRY or (game_id, tid) in seen:
            continue
        seen.add((game_id, tid))
        counts = out.setdefault(REGISTRY[tid]["event"], {"Final": 0, "Retired": 0, "other": 0})
        status = str(g.get("status"))
        counts[status if status in ("Final", "Retired") else "other"] += 1
    return out


def run(live_path: str, research_path: str, limit: int, official_path: Optional[str] = None) -> Dict[str, Any]:
    if research_path.endswith("picks.dev.db"):
        raise SystemExit("the research database must not be the live database")
    if os.path.abspath(research_path) == os.path.abspath(live_path):
        raise SystemExit("the research database must not be the live database")
    Path(research_path).parent.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {"started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "events": {},
                              "unsupported_tournaments": []}
    research = sqlite3.connect(research_path, timeout=30)
    research.executescript(scoreboard_store.SCHEMA)
    report["snapshots_copied"] = sync_snapshots(live_path, research)
    research.close()

    research = sqlite3.connect(research_path, timeout=30)
    report["completed_by_event"] = completed_counts(research)
    research.close()

    live = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True, timeout=30)
    seen_unsupported = set()
    for (payload,) in live.execute("SELECT payload FROM scoreboard_snapshots WHERE state='post' AND league IN ('atp','wta')"):
        g = json.loads(payload or "{}")
        tid = str(g.get("tournament_id"))
        if tid in REGISTRY or str(g.get("status")) not in ("Final", "Retired"):
            continue
        seen_unsupported.add((tid, str(g.get("event"))))
    live.close()
    report["unsupported_tournaments"] = [{"tournament_id": t, "event": e} for t, e in sorted(seen_unsupported)]

    for tid, info in REGISTRY.items():
        event = info["event"]
        fetch = ing.run(research_path, event, "tennis24", dry_run=False, limit=limit)
        research = sqlite3.connect(research_path, timeout=30)
        research.row_factory = sqlite3.Row
        link = cw.build(research, event, tid)
        resolved = prr.build(research, event, tid)
        ppm_counts = ppm.build(research, event)
        identity = rpo.build_identity(research, event)
        official = json.loads(Path(official_path).read_text()) if (official_path and event == OFFICIAL_EVENT) else None
        outcomes = rpo.build(research, event, tid, official)
        tiers = [tuple(r) for r in research.execute(
            "SELECT verification_tier, eligible_cp4, COUNT(*) FROM research_player_match_outcomes WHERE event=? "
            "GROUP BY 1,2", (event,))]
        research.close()
        report["events"][event] = {"fetch": {k: fetch.get(k) for k in ("enumerated", "skipped_already_ok", "parsed",
                                                                      "failures", "stopped", "memory_waits_s",
                                                                      "limit_reached")},
                                   "crosswalk": link, "identity": identity, "outcomes": outcomes,
                                   "outcome_rows_tier_eligible": tiers}
    report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--live-db", required=True)
    parser.add_argument("--research-db", required=True)
    parser.add_argument("--limit", type=int, default=0, help="fetch at most N new matches per event this run")
    parser.add_argument("--report", help="also write the JSON report here")
    parser.add_argument("--official-json", help="official Shanghai match-stat pages, from the official fetch")
    args = parser.parse_args()
    report = run(args.live_db, args.research_db, args.limit, args.official_json)
    text = json.dumps(report, indent=1, sort_keys=True, default=str)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
