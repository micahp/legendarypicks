#!/usr/bin/env python3
"""
breakingpoint_client.py — Call of Duty League data from breakingpoint.gg.

breakingpoint.gg keeps full CDL match history (unlike the official CDL site which
rolls completed matches off its score strip). Data is pulled from the Next.js
trpcState queries embedded in /_next/data/<buildId>/matches.json.

Returns the same normalized shape as cdl_client.get_matches() so it's a drop-in
replacement in sports_service.py.

Usage:
    matches = breakingpoint_client.get_cod_matches()           # all matches
    day_matches = breakingpoint_client.get_cod_matches("2026-06-26")  # date-filtered
"""
import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

BP_HOME = "https://breakingpoint.gg"
BP_MATCHES = "/_next/data/{buildId}/matches.json"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "Chrome/124.0.0.0 Safari/537.36")
CACHE_TTL = 300  # 5 minutes

_cache = {"buildId": None, "data": None, "ts": 0}


def _http_get(url, timeout=15):
    """GET with browser UA. Returns decoded text or raises."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _get_build_id():
    """Extract the current Next.js buildId from the homepage __NEXT_DATA__."""
    if _cache["buildId"] and (time.time() - _cache["ts"]) < CACHE_TTL:
        return _cache["buildId"]

    html = _http_get(BP_HOME)
    m = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.+?)</script>',
        html, re.DOTALL,
    )
    if not m:
        raise RuntimeError("breakingpoint: __NEXT_DATA__ not found on homepage")
    data = json.loads(m.group(1))
    _cache["buildId"] = data["buildId"]
    return _cache["buildId"]


def _fetch_all():
    """Fetch and cache all match/team/event data from breakingpoint."""
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    build_id = _get_build_id()
    url = BP_HOME + BP_MATCHES.format(buildId=build_id)
    raw = json.loads(_http_get(url))
    pp = raw.get("pageProps", {})

    # Team lookup: id → {name, logo_*}
    teams = {}
    for t in pp.get("allTeams", []):
        teams[t["id"]] = t

    # Event lookup: id → name. allEvents ids arrive as strings while match.event_id is an
    # int; normalize so the match lookup resolves (previously every event name came back empty).
    events = {}
    for ev in pp.get("allEvents", []):
        try:
            events[int(ev["id"])] = ev.get("name", "")
        except (KeyError, TypeError, ValueError):
            events[ev["id"]] = ev.get("name", "")

    # Collect all matches from trpcState queries
    trpc = pp.get("trpcState", {})
    queries = trpc.get("json", {}).get("queries", [])
    matches = []
    seen = set()
    for q in queries:
        qk = q.get("queryKey", [])
        if len(qk) < 2:
            continue
        # qk[0] is the function path: ['cached', 'matches', 'fetchUpcomingMatches']
        # qk[1] is the input dict: {'input': {'seeOnlyCDL': True}, 'type': 'query'}
        path = qk[0] if isinstance(qk[0], list) else []
        if len(path) < 3 or path[1] != "matches":
            continue
        fn = path[2]
        if fn not in ("fetchLiveMatches", "fetchUpcomingMatches", "fetchCompletedMatches"):
            continue
        inp = qk[1].get("input", {}) if isinstance(qk[1], dict) else {}
        if not inp.get("seeOnlyCDL", False):
            continue

        sd = q.get("state", {}).get("data")
        if isinstance(sd, str):
            sd = json.loads(sd)
        if not isinstance(sd, list):
            continue
        for m in sd:
            mid = m.get("id")
            if mid and mid not in seen:
                seen.add(mid)
                matches.append(m)

    result = {"matches": matches, "teams": teams, "events": events}
    _cache["data"] = result
    _cache["ts"] = now
    return result


def get_cod_matches(date_str=None):
    """
    Return COD matches from breakingpoint.gg, normalized to cdl_client shape.

    Returns list of:
        {
            "game_id": "BP-215002",
            "date": "2026-06-26T12:00:00Z",
            "state": "pre" | "in" | "post",
            "status": "upcoming" | "live" | "completed",
            "home": {"abbrev": "OpTic", "name": "OpTic Texas", "score": 3},
            "away": {"abbrev": "Breach", "name": "Boston Breach", "score": 0}
        }
    """
    try:
        data = _fetch_all()
    except Exception as e:
        print(f"[breakingpoint_client] fetch failed: {e}")
        return []

    teams = data["teams"]
    events = data["events"]
    results = []

    for m in data["matches"]:
        # Parse datetime
        dt_str = m.get("datetime", "")
        try:
            match_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        # Date filter (UTC date comparison)
        if date_str:
            try:
                target = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if match_dt.date() != target.date():
                    continue
            except ValueError:
                continue

        status = m.get("status", "upcoming")
        # Map status → state (our internal format)
        if status in ("completed", "complete"):
            state = "post"
        elif status in ("live", "in_progress"):
            state = "in"
        else:
            state = "pre"

        # EWC club ids are not always present in the page-level ``allTeams`` dictionary, but
        # Breaking Point includes the authoritative team objects directly on each match.  Prefer
        # the shared dictionary when available and fall back to those embedded objects before
        # degrading a genuinely unknown side to TBD.
        t1 = teams.get(m.get("team_1_id")) or m.get("team1") or {}
        t2 = teams.get(m.get("team_2_id")) or m.get("team2") or {}

        t1_name = t1.get("name", "TBD")
        t2_name = t2.get("name", "TBD")

        # Derive abbrev: first word/segment of team name (e.g. "OpTic Texas" → "OpTic")
        t1_abbrev = t1_name.split()[0] if t1_name else "???"
        t2_abbrev = t2_name.split()[0] if t2_name else "???"

        # Scores from breakingpoint (int, may be None for upcoming)
        s1 = m.get("team_1_score")
        s2 = m.get("team_2_score")

        # Build status display
        round_name = m.get("round", {}).get("name", "") if isinstance(m.get("round"), dict) else ""
        if state == "post":
            status_display = "Final"
        elif state == "in":
            status_display = "Live"
        else:
            status_display = round_name or "Upcoming"

        # COD score = maps won; derive current map/game number for live matches
        result = {
            "game_id": f"BP-{m['id']}",
            "date": match_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "state": state,
            "status": status_display,
            "event": events.get(m.get("event_id")) or "",
            "round": round_name,
            "home": {
                "abbrev": t1_abbrev,
                "name": t1_name,
                "score": int(s1) if s1 is not None else None,
            },
            "away": {
                "abbrev": t2_abbrev,
                "name": t2_name,
                "score": int(s2) if s2 is not None else None,
            },
        }
        if state == "in" and s1 is not None and s2 is not None:
            maps_played = int(s1) + int(s2) + 1
            result["period"] = maps_played
        results.append(result)

    # Sort: live first, then upcoming, then completed
    state_order = {"in": 0, "pre": 1, "post": 2}
    results.sort(key=lambda r: (state_order.get(r["state"], 9), r["date"]))
    return results


if __name__ == "__main__":
    import sys
    date_filter = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        matches = get_cod_matches(date_filter)
    except Exception as e:
        print(f"Error: {e}")
        matches = []
    print(json.dumps(matches, indent=2))
    print(f"\n{len(matches)} matches")
