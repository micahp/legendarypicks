#!/usr/bin/env python3
"""
cdl_client.py — Call of Duty League data from the official CDL website.

The CDL schedule page (callofdutyleague.com/en-us/schedule) embeds all match
data as server-side rendered JSON in <script id="__NEXT_DATA__">. No API key,
no auth — just parse the HTML and extract.

Usage:
    matches = cdl_client.get_matches()       # all matches from the schedule
    day_matches = cdl_client.get_matches(date_str="2026-06-05")  # filtered by date
"""
import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

CDL_URL = "https://www.callofdutyleague.com/en-us/schedule"
CACHE_TTL = 300  # 5 minutes
_cache = {"data": None, "ts": 0}


def _fetch_schedule():
    """Fetch and parse the CDL schedule page, return raw matches list."""
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    try:
        req = urllib.request.Request(CDL_URL, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        print(f"[cdl_client] fetch error: {e}")
        return _cache["data"] or []

    # Extract __NEXT_DATA__ JSON blob
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.+?)</script>',
        html, re.DOTALL
    )
    if not match:
        print("[cdl_client] __NEXT_DATA__ not found in page")
        return _cache["data"] or []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"[cdl_client] JSON parse error: {e}")
        return _cache["data"] or []

    # Navigate to matches array
    blocks = data.get("props", {}).get("pageProps", {}).get("blocks", [])
    matches = []
    for block in blocks:
        score_strip = (
            block.get("cdlHeader", {})
            .get("scoreStripList", {})
            .get("scoreStrip", {})
        )
        ms = score_strip.get("matches", [])
        if ms:
            matches = ms
            break

    _cache["data"] = matches
    _cache["ts"] = now
    return matches


def get_matches(date_str=None):
    """
    Return CDL matches, optionally filtered to a date (YYYY-MM-DD).
    Each match is normalized to the format the frontend expects:
        {
            "game_id": "CDL-13069",
            "date": "2026-06-05T19:00:00Z",
            "state": "pre" | "in" | "post",
            "status": "COMPLETED" | "PENDING" | "LIVE",
            "home": {"abbrev": "CAR", "name": "Carolina Royal Ravens", "score": 3},
            "away": {"abbrev": "TOR", "name": "Toronto KOI", "score": 0}
        }
    """
    raw = _fetch_schedule()
    results = []

    for m in raw:
        ts = m.get("date", {}).get("startTime", 0)
        if not ts:
            continue

        match_date = datetime.fromtimestamp(ts, tz=timezone.utc)
        if date_str:
            target = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            # Match if within the target day (UTC)
            if match_date.date() != target.date():
                continue

        status = m.get("status", "PENDING")
        state = "post" if status == "COMPLETED" else ("in" if status == "LIVE" else "pre")

        comps = m.get("competitors", [])
        home_team = comps[0] if len(comps) > 0 else {}
        away_team = comps[1] if len(comps) > 1 else {}

        results.append({
            "game_id": f"CDL-{m.get('link', '').split('/')[-1]}",
            "date": match_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "state": state,
            "status": status,
            "home": {
                "abbrev": home_team.get("shortName", "???"),
                "name": home_team.get("longName", "???"),
                "score": float(home_team.get("score", 0)) if status == "COMPLETED" else 0.0
            },
            "away": {
                "abbrev": away_team.get("shortName", "???"),
                "name": away_team.get("longName", "???"),
                "score": float(away_team.get("score", 0)) if status == "COMPLETED" else 0.0
            }
        })

    return results


if __name__ == "__main__":
    import sys
    date_filter = sys.argv[1] if len(sys.argv) > 1 else None
    matches = get_matches(date_filter)
    print(json.dumps(matches, indent=2))
    print(f"\n{len(matches)} matches")
