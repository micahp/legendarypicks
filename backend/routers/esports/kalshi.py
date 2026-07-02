"""kalshi.py — Kalshi settled esports markets as a RESULT fallback for the slate.

Some pro matches (e.g. minor BetBoom-league CS2) aren't carried by PandaScore's past feed OR GRID's
Open Access window, so once they end no source flips them to `finished` and they rot in the Scheduled
bucket. Kalshi trades a game-winner market per matchup and FINALIZES it to yes/no when the match ends,
so a settled market gives us the winner (Kalshi is winner-only — no map score). That's enough to move
a match we can't otherwise source out of limbo and into Results.

Market data is PUBLIC (no auth/RSA key), so this needs no credentials. Cached ~5min and fails open to
an empty map, so a Kalshi hiccup never blocks the slate.
"""

import json
import time
import urllib.request as _u

from .common import _canon_team

_KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
# Per-matchup (game-winner) series -> our title label. Tournament-winner series (KXCS2/KXLOL/...) are
# per-team, not per-matchup, so they carry no fixture-level result.
_KALSHI_SERIES = {
    "KXCS2GAME": "CS2",
    "KXVALORANTGAME": "Valorant",
    "KXDOTA2GAME": "Dota 2",
    "KXLOLGAME": "LoL",
    "KXOWGAME": "Overwatch",
    "KXCODGAME": "CoD",  # harmless until CoD is a covered title
}
_res_cache = {"t": 0.0, "data": None}
_TTL = 300


def _get(path, query):
    try:
        req = _u.Request(f"{_KALSHI_BASE}{path}?{query}", headers={"Accept": "application/json"})
        with _u.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}


def _iso_ms(s):
    if not s:
        return None
    try:
        from datetime import datetime, timezone
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)
    except Exception:
        return None


def _kalshi_results():
    """(title, frozenset({canonA, canonB})) -> list of (winner_canon, close_ms) from SETTLED markets.

    A finalized game-winner event has two markets (one per team); the market that resolved `result ==
    'yes'` names the winner. We key on the two canonical team names + title, and keep close_time so the
    slate can pick the settlement nearest the fixture (a rematch of the same pair never grabs the wrong
    result). List-valued because a pairing can meet more than once."""
    now = time.time()
    if _res_cache["data"] is not None and now - _res_cache["t"] < _TTL:
        return _res_cache["data"]
    out = {}
    for ticker, title in _KALSHI_SERIES.items():
        d = _get("/markets", f"series_ticker={ticker}&status=settled&limit=1000")
        by_event = {}
        for m in (d.get("markets") or []):
            et = m.get("event_ticker")
            name = m.get("yes_sub_title") or m.get("no_sub_title")
            if not (et and name):
                continue
            by_event.setdefault(et, {"teams": {}, "close": None})
            by_event[et]["teams"][_canon_team(name)] = (m.get("result") or "").lower()
            by_event[et]["close"] = by_event[et]["close"] or _iso_ms(m.get("close_time"))
        for et, ev in by_event.items():
            teams = ev["teams"]
            if len(teams) != 2:
                continue
            winner = next((c for c, res in teams.items() if res == "yes"), None)
            if winner:
                out.setdefault((title, frozenset(teams)), []).append((winner, ev["close"]))
    if out or _res_cache["data"] is None:
        _res_cache.update(t=now, data=out)
    return _res_cache["data"] or {}


def _kalshi_winner_for(title, team_a, team_b, near_ms=None, tol_ms=12 * 3600 * 1000):
    """Winner side ('a'/'b') for a fixture if Kalshi settled it, else None. `near_ms` (the fixture's
    start) disambiguates same-pair rematches: pick the settlement whose close_time is closest and
    within `tol_ms`."""
    ca, cb = _canon_team(team_a), _canon_team(team_b)
    cands = _kalshi_results().get((title, frozenset({ca, cb})))
    if not cands:
        return None
    if near_ms:
        cands = [c for c in cands if c[1] is None or abs(c[1] - near_ms) <= tol_ms]
        if not cands:
            return None
        cands = sorted(cands, key=lambda c: abs((c[1] or near_ms) - near_ms))
    winner = cands[0][0]
    if winner == ca:
        return "a"
    if winner == cb:
        return "b"
    return None
