#!/usr/bin/env python3
"""mlb_api.py — MLB Stats API: schedule, gamePk, boxscore, final."""
import json
from typing import Optional, Tuple, Dict

_MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
_MLB_BOXSCORE = "https://statsapi.mlb.com/api/v1/game/{gamePk}/boxscore"
_MLB_HDR = {"User-Agent": "Mozilla/5.0"}

_MLB_SCHEDULE_CACHE: Dict[str, dict] = {}


def _mlb_schedule(date_str: str) -> dict:
    """One schedule fetch per DATE, not per game."""
    import urllib.request as _ur
    if date_str not in _MLB_SCHEDULE_CACHE:
        url = f"{_MLB_SCHEDULE}?date={date_str}&sportId=1"
        req = _ur.Request(url, headers=_MLB_HDR)
        with _ur.urlopen(req, timeout=15) as r:
            _MLB_SCHEDULE_CACHE[date_str] = json.loads(r.read().decode())
    return _MLB_SCHEDULE_CACHE[date_str]


def _fetch_mlb_gamepk(date_str: str, home_team: str, away_team: str,
                      start_time: Optional[str] = None) -> Optional[int]:
    """Look up MLB gamePk by FIRST PITCH, falling back to the calendar day."""
    import datetime as _dt

    def _instant(text):
        if not text:
            return None
        try:
            return _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except ValueError:
            return None

    want = _instant(start_time)
    try:
        base = _dt.date.fromisoformat(date_str)
        candidates = [date_str,
                      (base - _dt.timedelta(days=1)).isoformat(),
                      (base + _dt.timedelta(days=1)).isoformat()]
    except Exception:
        candidates = [date_str]

    matches = []
    seen = set()
    for day in candidates:
        try:
            data = _mlb_schedule(day)
        except Exception:
            continue
        for dt_entry in data.get("dates", []):
            for game in dt_entry.get("games", []):
                pk = game.get("gamePk")
                if pk in seen:
                    continue
                teams = game.get("teams", {})
                away = teams.get("away", {}).get("team", {})
                home = teams.get("home", {}).get("team", {})
                if not any(home_team.lower() == (home.get(key) or "").lower()
                           and away_team.lower() == (away.get(key) or "").lower()
                           for key in ("name", "abbreviation")):
                    continue
                if (game.get("status") or {}).get("abstractGameState") != "Final":
                    continue
                seen.add(pk)
                matches.append((pk, _instant(game.get("gameDate"))))

    if want is not None:
        near = sorted((abs((gd - want).total_seconds()), pk)
                      for pk, gd in matches if gd is not None)
        near = [(d, pk) for d, pk in near if d <= 90 * 60]
        return near[0][1] if len(near) == 1 else None

    if len(matches) == 1:
        return matches[0][0]
    return None


def _fetch_mlb_final(gamePk: int) -> Optional[Tuple[int, int]]:
    """(home_score, away_score) for a gamePk the schedule reports Final, else None."""
    import urllib.request as _ur
    try:
        url = f"{_MLB_SCHEDULE}?gamePk={gamePk}&sportId=1"
        with _ur.urlopen(_ur.Request(url, headers=_MLB_HDR), timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None
    for entry in data.get("dates", []):
        for game in entry.get("games", []):
            if (game.get("status") or {}).get("abstractGameState") != "Final":
                continue
            teams = game.get("teams") or {}
            home = (teams.get("home") or {}).get("score")
            away = (teams.get("away") or {}).get("score")
            if home is not None and away is not None:
                return (home, away)
    return None


def _fetch_mlb_boxscore(gamePk: int) -> Optional[dict]:
    """Pull the MLB Stats API boxscore for a game."""
    import urllib.request as _ur
    try:
        url = _MLB_BOXSCORE.format(gamePk=gamePk)
        req = _ur.Request(url, headers=_MLB_HDR)
        with _ur.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None
