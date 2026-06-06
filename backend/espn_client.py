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
    "atp":  ("tennis/atp", 3),
    "wta":  ("tennis/wta", 3),
}

# ---------------------------------------------------------------------------
# Major tournament filter — only Grand Slams, Masters/WTA 1000, and year-end Finals.
# Substrings matched case-insensitively against ESPN's event shortName.
# ---------------------------------------------------------------------------
# Canonical keys — each tuple is (canonical_name, espn_name_substrings)
_ATP_MAJORS = [
    # Grand Slams
    ("Australian Open",        ["Australian Open"]),
    ("French Open",            ["Roland Garros", "French Open"]),
    ("Wimbledon",              ["Wimbledon"]),
    ("US Open",                ["US Open"]),
    # Masters 1000
    ("Indian Wells",           ["BNP Paribas Open"]),
    ("Miami Open",             ["Miami Open"]),
    ("Monte-Carlo Masters",    ["Monte-Carlo Masters"]),
    ("Madrid Open",            ["Mutua Madrid Open"]),
    ("Italian Open",           ["Italian Open", "Internazionali BNL d'Italia"]),
    ("Canadian Open",          ["National Bank Open", "Omnium Banque Nationale",
                                "Rogers Cup", "Canadian Open"]),
    ("Cincinnati Open",        ["Cincinnati Open", "Western & Southern Open"]),
    ("Shanghai Masters",       ["Rolex Shanghai Masters", "Shanghai Masters"]),
    ("Paris Masters",          ["Rolex Paris Masters", "Paris Masters"]),
    # Finals
    ("ATP Finals",             ["ATP Finals", "Nitto ATP Finals", "ATP World Tour Finals"]),
]

_WTA_MAJORS = [
    # Grand Slams (same as ATP)
    ("Australian Open",        ["Australian Open"]),
    ("French Open",            ["Roland Garros", "French Open"]),
    ("Wimbledon",              ["Wimbledon"]),
    ("US Open",                ["US Open"]),
    # WTA 1000
    ("Qatar Open",             ["Qatar TotalEnergies Open", "Qatar Open", "Qatar Total Open"]),
    ("Dubai",                  ["Dubai Duty Free Tennis Championships", "Dubai Tennis Championships"]),
    ("Indian Wells",           ["BNP Paribas Open"]),
    ("Miami Open",             ["Miami Open"]),
    ("Madrid Open",            ["Mutua Madrid Open"]),
    ("Italian Open",           ["Italian Open", "Internazionali BNL d'Italia"]),
    ("Canadian Open",          ["National Bank Open", "Omnium Banque Nationale", "Canadian Open"]),
    ("Cincinnati Open",        ["Cincinnati Open"]),
    ("China Open",             ["China Open"]),
    ("Wuhan Open",             ["Wuhan Open"]),
    # Finals
    ("WTA Finals",             ["WTA Finals", "WTA Championships"]),
]

def _is_major(league: str, event_short_name: str) -> bool:
    """True if this ESPN event is a Grand Slam, Masters/1000, or Finals."""
    maj = _ATP_MAJORS if league == "atp" else _WTA_MAJORS
    name_lower = (event_short_name or "").lower()
    for _, aliases in maj:
        for alias in aliases:
            if alias.lower() in name_lower:
                return True
    return False
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
    is_tennis = league in ("atp", "wta")
    q = ("?dates=" + date.replace("-", "")) if date else ""
    d = _get(_SITE.format(path=path) + "/scoreboard" + q, ttl=20)
    out = []

    if is_tennis:
        # Tennis returns tournaments as events, matches nested in groupings[].competitions[]
        # Tournaments span weeks — filter to the requested date (or today)
        import datetime as _dt
        target_date = None
        if date:
            target_date = _dt.datetime.strptime(date, "%Y-%m-%d").date()
        else:
            target_date = _dt.date.today()
        for event in d.get("events", []):
            # ATP/WTA both return full tournament — filter by gender grouping
            # Use startswith to avoid matching "mens" inside "womens"
            if league == "atp":
                gender_prefix = "mens"
            else:
                gender_prefix = "womens"
            # ----- major-tournament gate -----
            short_name = event.get("shortName") or event.get("name", "")
            if not _is_major(league, short_name):
                continue
            # ---------------------------------
            for grp in event.get("groupings", []):
                slug = grp.get("grouping", {}).get("slug", "")
                if not slug.startswith(gender_prefix):
                    continue
                # Singles only — skip doubles and mixed
                if "doubles" in slug or "mixed" in slug:
                    continue
                for comp in grp.get("competitions", []):
                    # Filter by date — tennis tournaments span weeks
                    comp_date = comp.get("date", "")
                    if comp_date:
                        try:
                            cd = _dt.datetime.fromisoformat(comp_date.replace("Z", "+00:00")).date()
                            if cd != target_date:
                                continue
                        except (ValueError, TypeError):
                            pass
                    status = comp.get("status", {})
                    st = status.get("type", {})
                    players = {}
                    for c in comp.get("competitors", []):
                        # Singles: athlete object. Doubles: team object with roster.
                        if c.get("type") == "team":
                            roster = c.get("roster", {})
                            name = roster.get("displayName") or roster.get("shortDisplayName") or "TBD"
                            abbrev = roster.get("shortDisplayName", name)[:8]
                        else:
                            ath = c.get("athlete", {})
                            name = ath.get("displayName") or ath.get("fullName") or "TBD"
                            abbrev = ath.get("shortName") or name[:3].upper()
                        players[c.get("homeAway")] = {
                            "abbrev": abbrev,
                            "name": name,
                            "score": None,
                        }
                    # Extract set scores from linescores and compute set wins
                    set_scores = []
                    away_sets = home_sets = 0
                    for c in comp.get("competitors", []):
                        ls = c.get("linescores", [])
                        scores = [str(int(v.get("value"))) for v in ls if v.get("value") is not None]
                        wins = sum(1 for v in ls if v.get("winner") is True)
                        if scores:
                            set_scores.append("-".join(scores))
                        if c.get("homeAway") == "away":
                            away_sets = wins
                        else:
                            home_sets = wins
                    score_str = " | ".join(set_scores) if set_scores else None
                    # Set numeric scores for display (sets won), 0 is valid (lost in straight sets)
                    if status.get("type", {}).get("completed") or set_scores:
                        players["away"]["score"] = away_sets
                        players["home"]["score"] = home_sets
                    out.append({
                        "game_id": comp.get("id"),
                        "date": comp.get("date") or event.get("date"),
                        "state": st.get("state"),
                        "status": st.get("description") or score_str or "",
                        "period": status.get("period"),
                        "clock": status.get("displayClock"),
                        "home": players.get("home"),
                        "away": players.get("away"),
                    })
    else:
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
                "state": st.get("state"),
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


def roster(league, team):
    """Active roster for a team (by abbreviation or id): [{player_id, name, jersey, position}]."""
    _, path = _check(league)
    d = _get(_SITE.format(path=path) + f"/teams/{team}/roster", ttl=3600)
    out = []
    for a in d.get("athletes", []):
        # NFL/NBA roster nests athletes under position groups; flatten either shape
        items = a.get("items") if isinstance(a, dict) and "items" in a else [a]
        for p in items:
            out.append({
                "player_id": str(p.get("id")),
                "name": p.get("fullName") or p.get("displayName"),
                "jersey": p.get("jersey"),
                "position": (p.get("position") or {}).get("abbreviation"),
            })
    return out


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
