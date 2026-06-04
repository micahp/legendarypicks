#!/usr/bin/env python3
"""espn_client.py — dependency-free ESPN data client for all major leagues.

Replaces the dead `sportsipy` scraper and the NBA-only `nba_api` path with ESPN's hidden
site API: free, reliable, multi-league, and the SAME source the prediction-market trading
repo already uses (espn_pbp.py / espn_resolve.py). Pure stdlib (urllib), TTL-cached.

Provides the three things both Legendary Picks and the trading strategy need:
  - games(league, date)        scoreboard (pre / in-progress / final)
  - team_strength(league)      win%, point/run differential, streak, last-10  = the QUALITY prior
  - boxscore / game_result     per-game detail + a clean winner/state for grading predictions
"""
import json, time, urllib.request

LEAGUES = {  # our key -> (espn "sport/league" path, regulation periods)
    "nba":  ("basketball/nba", 4),
    "wnba": ("basketball/wnba", 4),
    "nhl":  ("hockey/nhl", 3),
    "mlb":  ("baseball/mlb", 9),
    "nfl":  ("football/nfl", 4),
}
_SITE = "https://site.api.espn.com/apis/site/v2/sports/{path}"
_CORE = "https://site.api.espn.com/apis/v2/sports/{path}"
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

_CACHE = {}  # url -> (expires_at, data); ESPN is fine but we cache to be polite + fast


def _get(url, ttl=30):
    now = time.time()
    hit = _CACHE.get(url)
    if hit and hit[0] > now:
        return hit[1]
    with urllib.request.urlopen(urllib.request.Request(url, headers=_HDRS), timeout=20) as r:
        data = json.loads(r.read().decode())
    _CACHE[url] = (now + ttl, data)
    return data


def _check(league):
    league = (league or "").lower()
    if league not in LEAGUES:
        raise ValueError(f"unsupported league {league!r}; supported: {sorted(LEAGUES)}")
    return league, LEAGUES[league][0]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def games(league, date=None):
    """Normalized scoreboard. date='YYYY-MM-DD' (or None=today). state: pre | in | post."""
    _, path = _check(league)
    q = ("?dates=" + date.replace("-", "")) if date else ""
    d = _get(_SITE.format(path=path) + "/scoreboard" + q, ttl=20)
    out = []
    for e in d.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        status = comp.get("status", {})
        st = status.get("type", {})
        teams = {}
        for c in comp.get("competitors", []):
            teams[c.get("homeAway")] = {
                "abbrev": c.get("team", {}).get("abbreviation"),
                "name": c.get("team", {}).get("displayName"),
                "score": _num(c.get("score")),
            }
        out.append({
            "game_id": e.get("id"),
            "date": e.get("date"),
            "state": st.get("state"),                # pre | in | post
            "status": st.get("description"),
            "period": status.get("period"),
            "clock": status.get("displayClock"),
            "home": teams.get("home"),
            "away": teams.get("away"),
        })
    return out


def team_strength(league):
    """Every team ranked by quality — win%, differential, streak, last-10. The selection prior.

    `differential` is run differential (MLB), goal diff (NHL), point diff (NBA/NFL) per game.
    """
    _, path = _check(league)
    d = _get(_CORE.format(path=path) + "/standings", ttl=900)
    rows = []
    for child in d.get("children", []):                  # divisions / conferences
        for ent in child.get("standings", {}).get("entries", []):
            s = {x.get("name"): x.get("value") for x in ent.get("stats", [])}
            disp = {x.get("name"): x.get("displayValue") for x in ent.get("stats", [])}
            t = ent.get("team", {})
            wp = s.get("winPercent")
            rows.append({
                "abbrev": t.get("abbreviation"),
                "name": t.get("displayName"),
                "wins": _int(s.get("wins")),
                "losses": _int(s.get("losses")),
                "win_pct": round(wp, 4) if wp is not None else None,
                "differential": s.get("pointDifferential", s.get("differential")),
                "streak": disp.get("streak"),
                "last10": disp.get("Last Ten Games"),
                "games_played": _int(s.get("gamesPlayed")),
            })
    rows.sort(key=lambda r: (r["win_pct"] if r["win_pct"] is not None else -1), reverse=True)
    return rows


def team_strength_map(league):
    """{abbrev: strength_row} for O(1) lookup / joining to a market."""
    return {r["abbrev"]: r for r in team_strength(league) if r["abbrev"]}


def boxscore(league, game_id):
    """Full per-game box score (team + player stat lines)."""
    _, path = _check(league)
    d = _get(_SITE.format(path=path) + f"/summary?event={game_id}", ttl=20)
    return d.get("boxscore", {})


def game_result(league, game_id):
    """Clean grading info for one game: {state, scores{abbrev:score}, winner|None}.

    Robust to date (queries the game directly), so it grades predictions regardless of when
    the game was played. winner is None until the game is final.
    """
    _, path = _check(league)
    d = _get(_SITE.format(path=path) + f"/summary?event={game_id}", ttl=20)
    comp = (d.get("header", {}).get("competitions") or [{}])[0]
    st = comp.get("status", {}).get("type", {})
    scores = {}
    for c in comp.get("competitors", []):
        scores[c.get("team", {}).get("abbreviation")] = _num(c.get("score"))
    winner = None
    if st.get("state") == "post" and len(scores) == 2 and all(v is not None for v in scores.values()):
        winner = max(scores, key=scores.get)
    return {"state": st.get("state"), "scores": scores, "winner": winner}


if __name__ == "__main__":
    import sys
    lg = sys.argv[1] if len(sys.argv) > 1 else "mlb"
    print(f"== {lg} top-5 by quality ==")
    for r in team_strength(lg)[:5]:
        print(f"  {r['abbrev']:4} {str(r['wins'])+'-'+str(r['losses']):8} "
              f"win%={r['win_pct']} diff={r['differential']} {r['streak']} L10={r['last10']}")
    print(f"== {lg} games today ==")
    for g in games(lg):
        h, a = g["home"], g["away"]
        print(f"  {a['abbrev']}@{h['abbrev']} {g['state']:4} {a['score']}-{h['score']} ({g['status']})")
