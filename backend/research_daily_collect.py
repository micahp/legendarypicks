#!/usr/bin/env python3
"""Daily tennis stats collection in an isolated research database (research only). Never writes the live DB.

One run:
1. Copies every ATP/WTA scoreboard snapshot from the live database, opened read-only, into the research database.
2. Stores any official match-stat pages passed in. They stay stored, so later runs do not need them again.
3. Discovers which ESPN tournaments in the active window have a tennis24 results page (research_event_registry).
   Unsupported tournaments are listed with the candidates tried, and they are not fetched.
4. For each supported tournament with games in the window, fetches only matches not already stored as ok or
   no_stats_tab (5 s pacing, 1.5 GB memory floor, stop rules), then rebuilds links, the review resolver, the
   identity table and the verified outcomes. Those writes never delete or overwrite accepted evidence.
5. Writes a JSON report: discovery, coverage per tournament, fetch counts, failures, tiers and open conflicts.

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
import research_evidence as rpe  # noqa: E402
import research_event_registry as ereg  # noqa: E402
import research_player_outcomes as rpo  # noqa: E402
import scoreboard_store  # noqa: E402


def sync_all_snapshots(live_path: str, research: sqlite3.Connection) -> int:
    live = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True, timeout=30)
    try:
        rows = live.execute("SELECT league, game_date, game_id, payload, state, start_time, fetched_at, source "
                            "FROM scoreboard_snapshots WHERE league IN ('atp','wta')").fetchall()
    finally:
        live.close()
    research.executemany("INSERT OR REPLACE INTO scoreboard_snapshots(league,game_date,game_id,payload,state,start_time,"
                         "fetched_at,source) VALUES(?,?,?,?,?,?,?,?)", rows)
    research.commit()
    return len(rows)


def run(live_path: str, research_path: str, limit: int, official_path: Optional[str] = None,
        today: Optional[dt.date] = None, window_days: int = 14) -> Dict[str, Any]:
    if os.path.abspath(research_path) == os.path.abspath(live_path) or research_path.endswith("picks.dev.db"):
        raise SystemExit("the research database must not be the live database")
    today = today or dt.datetime.now(dt.timezone.utc).date()
    Path(research_path).parent.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {"started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "today": today.isoformat()}
    research = sqlite3.connect(research_path, timeout=30)
    research.row_factory = sqlite3.Row
    research.executescript(scoreboard_store.SCHEMA)
    research.executescript(ing.DDL)
    rpe.ensure(research)
    ereg.ensure(research)
    report["snapshots_copied"] = sync_all_snapshots(live_path, research)
    if official_path:
        pages = json.loads(Path(official_path).read_text())
        report["official_pages"] = rpe.store_official_pages(research, "shanghai-atp-2026", pages)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        report["discovery"] = ereg.discover(research, browser, today, window_days)
        browser.close()

    in_window = ereg.espn_tournaments(research, today, window_days)
    report["events"] = {}
    for entry in ereg.supported(research):
        if (entry["tournament_id"], entry["league"]) not in in_window:
            continue
        event = entry["event"]
        fetch = ing.run(research_path, event, "tennis24", dry_run=False, limit=limit, list_url_override=entry["list_url"])
        link = cw.build(research, event, entry["tournament_id"])
        resolved = prr.build(research, event, entry["tournament_id"])
        ppm_counts = ppm.build(research, event)
        identity = rpo.build_identity(research, event)
        outcomes = rpo.build(research, event, entry["tournament_id"])
        tiers = [tuple(r) for r in research.execute(
            "SELECT verification_tier, eligible_cp4, COUNT(*) FROM research_player_match_outcomes WHERE event=? "
            "GROUP BY 1,2", (event,))]
        report["events"][event] = {
            "fetch": {k: fetch.get(k) for k in ("enumerated", "skipped_already_ok", "parsed", "failures", "stopped",
                                              "memory_waits_s", "limit_reached")},
            "crosswalk": link, "resolver": resolved, "identity_map": ppm_counts, "identity": identity,
            "outcomes": outcomes, "tiers_eligible": tiers}
    report["coverage"] = ereg.coverage(research, today, window_days)
    report["unsupported"] = [c for c in report["coverage"] if c["mapping"] != "supported"]
    report["conflicts_open"] = [tuple(r) for r in research.execute(
        "SELECT kind, COUNT(*) FROM evidence_conflicts WHERE status='open' GROUP BY 1")]
    research.close()
    report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--live-db", required=True)
    parser.add_argument("--research-db", required=True)
    parser.add_argument("--limit", type=int, default=0, help="fetch at most N new matches per event this run")
    parser.add_argument("--report", help="also write the JSON report here")
    parser.add_argument("--official-json", help="official match-stat pages to store (kept for later runs)")
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
