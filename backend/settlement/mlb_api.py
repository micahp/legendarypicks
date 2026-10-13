#!/usr/bin/env python3
"""mlb_api.py — MLB Stats API: schedule, gamePk, boxscore, final."""
import os
from typing import Optional, Tuple, Dict

import paced_http

_MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
_MLB_BOXSCORE = "https://statsapi.mlb.com/api/v1/game/{gamePk}/boxscore"
_MLB_HDR = {"User-Agent": "Mozilla/5.0"}

# A full settlement replay touches hundreds of games.  The old bare urlopen
# path had no pacing and no durable cache, so every retry repaid for every
# schedule and boxscore.  Keep MLB on its own publisher-aware client: serial,
# rate-budgeted, and optionally replayable from an explicit archive directory.
_MLB_FETCH = paced_http.Fetcher(
    min_interval=float(os.environ.get("LP_MLB_SETTLEMENT_MIN_INTERVAL", "0.25")),
    retry_waits=(5.0, 20.0, 60.0),
    headers=_MLB_HDR,
    timeout=30,
    cache_dir=os.environ.get("LP_MLB_SETTLEMENT_CACHE_DIR") or "",
    cache_ttl=float(os.environ.get("LP_MLB_SETTLEMENT_CACHE_TTL", "31536000")),
    on_exhausted="sleep",
)

_MLB_SCHEDULE_CACHE: Dict[str, dict] = {}


def _mlb_schedule(date_str: str) -> dict:
    """One schedule fetch per DATE, not per game."""
    if date_str not in _MLB_SCHEDULE_CACHE:
        url = f"{_MLB_SCHEDULE}?date={date_str}&sportId=1"
        _MLB_SCHEDULE_CACHE[date_str] = _MLB_FETCH.json(url)
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
        # Adjacent dates are needed only when an exact first-pitch instant can
        # disambiguate them.  Without that instant, expanding a calendar-date
        # lookup makes an ordinary three-game series look ambiguous: the exact
        # day's one final plus the same clubs on the next day produced 1,036
        # falsely unresolved props in the worktree audit.
        candidates = ([date_str,
                       (base - _dt.timedelta(days=1)).isoformat(),
                       (base + _dt.timedelta(days=1)).isoformat()]
                      if want is not None else [date_str])
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
    try:
        url = f"{_MLB_SCHEDULE}?gamePk={gamePk}&sportId=1"
        data = _MLB_FETCH.json(url)
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
    try:
        url = _MLB_BOXSCORE.format(gamePk=gamePk)
        return _MLB_FETCH.json(url)
    except Exception:
        return None
