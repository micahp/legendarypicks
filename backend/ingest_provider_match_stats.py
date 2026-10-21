#!/usr/bin/env python3
"""Collect per-match aces and double faults from tournament-provider match pages (research, CP4).

Two providers, one browser, one page at a time:

- 365scores: the league page's Results list (Results tab, then scroll until the link count holds),
  then each match page's Stats section.
- tennis24: the event's /results/ page ("Show more matches" until it is gone, then scroll until the
  link count holds), then each match page's STATS tab.

Rows go to `provider_match_stats` in the database given by --db. The module refuses picks.dev.db.
Run it against a copy. Stop rules: an HTTP 403 or 429, a bot-check page, or three failures in a row.

Usage:
  python3 backend/ingest_provider_match_stats.py --db /root/picks.tennis-cp4.db --event wuhan-wta-2026 \
      --provider 365scores --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

EVENTS = {
    "wuhan-wta-2026": {
        "365scores": "https://www.365scores.com/en-us/tennis/league/wuhan-6177",
        "tennis24": "https://www.tennis24.com/wta-singles/wuhan/results/",
        "espn_tournament_id": "381",
        "espn_final_count": 74,
    },
    "shanghai-atp-2026": {
        "365scores": None,  # no Shanghai league page reachable from 365scores navigation (2026-10-20)
        "tennis24": "https://www.tennis24.com/atp-singles/shanghai/results/",
        "espn_tournament_id": "315",
        "espn_final_count": 119,
    },
}
MEMORY_FLOOR_MB = 1500
KEYS = ("home_aces", "away_aces", "home_double_faults", "away_double_faults")
PACE_SECONDS = 5.0
MAX_CONSECUTIVE_FAILURES = 3
BLOCK_PATTERN = re.compile(r"attention required|access denied|are you a robot|verify you are human|"
                           r"performing security verification|just a moment", re.I)
COUNT_PATTERN = {"365scores": r"/tennis/match/", "tennis24": r"/match/"}
ID_PATTERN = {"365scores": r"[#&?]id=(\d+)", "tennis24": r"[?&]mid=([A-Za-z0-9]+)"}

DDL = """
CREATE TABLE IF NOT EXISTS provider_match_stats(
  provider TEXT NOT NULL,
  provider_match_id TEXT NOT NULL,
  event TEXT NOT NULL,
  source_url TEXT NOT NULL,
  anchor_text TEXT,
  home_aces INTEGER,
  away_aces INTEGER,
  home_double_faults INTEGER,
  away_double_faults INTEGER,
  stats_view TEXT,
  parse_status TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY(provider, provider_match_id)
);
"""


class StopRun(RuntimeError):
    """A stop rule fired; the run ends and reports what it has."""


def _pair(lines: List[str], label: str) -> Optional[tuple]:
    """(left, right) integers from a 'value / label / value' row, or None when absent or not numeric."""
    for index, line in enumerate(lines):
        if line != label or index == 0 or index + 1 >= len(lines):
            continue
        left, right = lines[index - 1], lines[index + 1]
        if re.fullmatch(r"\d+", left) and re.fullmatch(r"\d+", right):
            return int(left), int(right)
    return None


def parse_stats_text(text: str) -> Dict[str, Any]:
    """Aces and double faults from a rendered match page's text. Status says what was found."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    aces = _pair(lines, "Aces")
    double_faults = _pair(lines, "Double Faults")
    if aces is None and double_faults is None:
        return {"parse_status": "no_stats", "home_aces": None, "away_aces": None,
                "home_double_faults": None, "away_double_faults": None}
    if aces is None or double_faults is None:
        return {"parse_status": "partial", "home_aces": aces and aces[0], "away_aces": aces and aces[1],
                "home_double_faults": double_faults and double_faults[0],
                "away_double_faults": double_faults and double_faults[1]}
    return {"parse_status": "ok", "home_aces": aces[0], "away_aces": aces[1],
            "home_double_faults": double_faults[0], "away_double_faults": double_faults[1]}


def _settle(page, rounds_unchanged: int, pattern: str, label: str, presses: int = 4,
            wait_ms: int = 2000, max_rounds: int = 40) -> List[Dict[str, str]]:
    """Scroll to the bottom in steps until the match-link count holds for `rounds_unchanged` rounds.

    Rows load lazily on scroll. Buttons are not clicked: on 365scores a 'Show More' click emptied the
    list. Each round presses End `presses` times with a pause between presses.
    """
    seen_count, unchanged = -1, 0
    matches: Dict[str, str] = {}
    page.mouse.move(640, 400)
    page.mouse.wheel(0, 500)
    page.wait_for_timeout(wait_ms)
    for _ in range(max_rounds):
        for _ in range(presses):
            page.keyboard.press("End")
            page.wait_for_timeout(wait_ms)
        links = page.eval_on_selector_all("a[href]", "els => els.map(e => [e.href, e.innerText.trim()])")
        matches = {}
        for href, anchor in links:
            if re.search(pattern, href):
                matches.setdefault(href, anchor)
        unchanged = unchanged + 1 if len(matches) == seen_count else 0
        seen_count = len(matches)
        if unchanged >= rounds_unchanged:
            break
    return [{"url": href, "anchor_text": anchor} for href, anchor in matches.items()]


def enumerate_matches(browser, provider: str, list_url: str) -> List[Dict[str, str]]:
    page = browser.new_page()
    try:
        page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        if provider == "365scores":
            page.locator("text=Results").first.click(timeout=8000)
            page.wait_for_timeout(3000)
        return _settle(page, rounds_unchanged=4, pattern=COUNT_PATTERN[provider], label=provider)
    finally:
        page.close()


def available_mb() -> int:
    with open("/proc/meminfo") as handle:
        for line in handle:
            if line.startswith("MemAvailable"):
                return int(line.split()[1]) // 1024
    raise RuntimeError("MemAvailable not found")


def wait_for_memory(report: Dict[str, Any], max_wait_s: int = 3600) -> None:
    """Hold until available memory is back above the floor; stop if it does not recover."""
    waited = 0
    while available_mb() < MEMORY_FLOOR_MB:
        if waited >= max_wait_s:
            raise StopRun(f"available memory below {MEMORY_FLOOR_MB} MB for {max_wait_s} s")
        time.sleep(30)
        waited += 30
        report["memory_waits_s"] = report.get("memory_waits_s", 0) + 30


def _click_tab(page, label: str) -> Optional[bool]:
    """Click a stats tab (MATCH, SET 1..3) by its exact label. Returns None if no tab has that label.

    Otherwise returns whether the tab was already selected before the click. On tennis24 the stats tabs
    carry classes like 'wcl-tab_...' and the selected one 'wcl-tabSelected_...'.
    """
    return page.evaluate(
        """(label) => {
            const tabs = [...document.querySelectorAll('[class*="wcl-tab_"]')]
                .filter(e => e.innerText && e.innerText.trim() === label);
            if (!tabs.length) return null;
            const wasSelected = /wcl-tabSelected/.test(tabs[0].className || '');
            if (!wasSelected) tabs[0].click();
            return wasSelected;
        }""", label)


def _check_block(text: str) -> None:
    if BLOCK_PATTERN.search(text):
        raise StopRun("bot-check or block page returned")


def collect_match(browser, provider: str, url: str) -> Dict[str, Any]:
    page = browser.new_page()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        status = response.status if response else None
        if status in (403, 429):
            raise StopRun(f"HTTP {status}")
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        if provider == "tennis24":
            stats_tab = page.locator("text=STATS")
            try:
                if stats_tab.count() == 0:
                    raise LookupError("no STATS tab")
                stats_tab.first.click(timeout=8000)
            except Exception:
                # Walkovers and suspended matches have no stats tab. That is a finding, not a failure.
                return {"parse_status": "no_stats_tab", "stats_view": "no STATS tab on page",
                        "home_aces": None, "away_aces": None, "home_double_faults": None,
                        "away_double_faults": None}
            page.wait_for_timeout(3000)
            match_tab = _click_tab(page, "MATCH")
            confirmed = match_tab is not None
            page.wait_for_timeout(1500)
            text = page.inner_text("body")
            _check_block(text)
            parsed = parse_stats_text(text)
            set_parses = []
            for label in ("SET 1", "SET 2", "SET 3"):
                if _click_tab(page, label) is not None:
                    page.wait_for_timeout(1500)
                    set_parses.append(parse_stats_text(page.inner_text("body")))
            if not confirmed:
                parsed["stats_view"] = "MATCH tab not found; default block read"
                return parsed
            if match_tab is False:
                parsed["stats_view"] = "MATCH tab selected by click; default was a set"
            if parsed["parse_status"] != "ok" or not set_parses:
                parsed["stats_view"] = "MATCH tab confirmed; set tabs not checked"
                return parsed
            if any(s["parse_status"] != "ok" for s in set_parses):
                parsed["stats_view"] = "MATCH tab confirmed; a set tab did not parse"
                return parsed
            sums_ok = all(parsed[k] == sum(s[k] for s in set_parses) for k in KEYS)
            if sums_ok:
                parsed["stats_view"] = "MATCH tab confirmed; set tabs sum to match"
            else:
                parsed["stats_view"] = "MATCH tab confirmed; set tabs DO NOT sum to match"
                parsed["parse_status"] = "set_mismatch"
            return parsed
        text = page.inner_text("body")
        _check_block(text)
        parsed = parse_stats_text(text)
        parsed["stats_view"] = "page (Stats section)"
        return parsed
    finally:
        page.close()


def run(db_path: str, event: str, provider: str, dry_run: bool, sample: int = 0, limit: int = 0) -> Dict[str, Any]:
    if db_path.endswith("picks.dev.db"):
        raise SystemExit("refusing to write to picks.dev.db; use a copy")
    from playwright.sync_api import sync_playwright

    config = EVENTS[event]
    list_url = config.get(provider)
    if list_url is None:
        raise SystemExit(f"no list URL configured for {provider} in {event}")
    report: Dict[str, Any] = {"event": event, "provider": provider, "list_url": list_url,
                              "espn_final_count": config["espn_final_count"], "enumerated": 0,
                              "parsed": {}, "failures": 0, "stopped": None}
    con = None
    if not dry_run:
        con = sqlite3.connect(db_path)
        con.executescript(DDL)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            wait_for_memory(report)
            matches = enumerate_matches(browser, provider, list_url)
            report["enumerated"] = len(matches)
            report["sample_urls"] = [m["url"] for m in matches[:3]]
            if dry_run:
                browser.close()
                return report
            consecutive = 0
            done = set()
            if con is not None:
                done = {r[0] for r in con.execute(
                    "SELECT provider_match_id FROM provider_match_stats WHERE provider=? AND event=? "
                    "AND parse_status IN ('ok','no_stats_tab')", (provider, event))}
            report["skipped_already_ok"] = 0
            taken = 0
            for match in matches:
                url = match["url"]
                ids = re.search(ID_PATTERN[provider], url)
                provider_id = ids.group(1) if ids else url
                if provider_id in done:
                    report["skipped_already_ok"] += 1
                    continue
                if sample and taken >= sample:
                    break
                if limit and taken >= limit:
                    report["limit_reached"] = limit
                    break
                taken += 1
                wait_for_memory(report)
                try:
                    row = collect_match(browser, provider, url)
                    consecutive = 0
                except StopRun as exc:
                    report["stopped"] = str(exc)
                    break
                except Exception as exc:
                    consecutive += 1
                    report["failures"] += 1
                    row = {"parse_status": f"error:{type(exc).__name__}", "stats_view": None,
                           "home_aces": None, "away_aces": None, "home_double_faults": None,
                           "away_double_faults": None}
                    if consecutive >= MAX_CONSECUTIVE_FAILURES:
                        report["stopped"] = f"{consecutive} failures in a row"
                        break
                report["parsed"][row["parse_status"]] = report["parsed"].get(row["parse_status"], 0) + 1
                if sample:
                    report.setdefault("sample_rows", []).append({"provider_match_id": provider_id, "url": url, **row})
                if con is not None and not sample:
                    con.execute(
                        "INSERT OR REPLACE INTO provider_match_stats(provider,provider_match_id,event,source_url,"
                        "anchor_text,home_aces,away_aces,home_double_faults,away_double_faults,stats_view,"
                        "parse_status,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (provider, provider_id, event, url, match["anchor_text"], row["home_aces"],
                         row["away_aces"], row["home_double_faults"], row["away_double_faults"],
                         row["stats_view"], row["parse_status"], dt.datetime.now(dt.timezone.utc).isoformat()))
                    con.commit()
                time.sleep(PACE_SECONDS)
            browser.close()
    finally:
        if con is not None:
            con.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--db", required=True)
    parser.add_argument("--event", required=True, choices=sorted(EVENTS))
    parser.add_argument("--provider", required=True, choices=sorted(COUNT_PATTERN))
    parser.add_argument("--dry-run", action="store_true", help="enumerate only; write nothing")
    parser.add_argument("--sample", type=int, default=0, help="collect the first N matches and print them; write nothing")
    args = parser.parse_args()
    report = run(args.db, args.event, args.provider, args.dry_run, args.sample)
    import json
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
