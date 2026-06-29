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
    "ufc":  ("mma/ufc", 3),
    "wc":   ("soccer/fifa.world", 2),
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
    is_ufc = league == "ufc"
    q = ("?dates=" + date.replace("-", "")) if date else ""
    d = _get(_SITE.format(path=path) + "/scoreboard" + q, ttl=20)
    import datetime as _dt
    out = []

    if is_tennis:
        # Tennis returns tournaments as events, matches nested in groupings[].competitions[]
        # Tournaments span weeks — filter to the requested date (or today)
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
                    # Extract per-set game scores from linescores for each competitor
                    for c in comp.get("competitors", []):
                        ls = c.get("linescores", [])
                        per_set = [int(v.get("value")) for v in ls if v.get("value") is not None]
                        wins = sum(1 for v in ls if v.get("winner") is True)
                        ha = c.get("homeAway")
                        if ha in players:
                            players[ha]["sets"] = per_set
                            if per_set:
                                players[ha]["score"] = wins
                    # Build status string from paired set scores (home[i] - away[i])
                    home_sets = players.get("home", {}).get("sets", [])
                    away_sets = players.get("away", {}).get("sets", [])
                    n_sets = max(len(home_sets), len(away_sets))
                    set_strs = []
                    for i in range(n_sets):
                        h = str(home_sets[i]) if i < len(home_sets) else "-"
                        a = str(away_sets[i]) if i < len(away_sets) else "-"
                        set_strs.append(f"{h}-{a}")
                    score_str = " | ".join(set_strs) if set_strs else None
                    out.append({
                        "game_id": comp.get("id"),
                        "date": comp.get("date") or event.get("date"),
                        "state": st.get("state"),
                        "status": st.get("description") or score_str or "",
                        "period": status.get("period"),
                        "clock": status.get("displayClock"),
                        "status_detail": st.get("shortDetail"),
                        "home": players.get("home"),
                        "away": players.get("away"),
                        "event": event.get("shortName") or event.get("name", ""),
                    })
    elif is_ufc:
        # UFC — events contain fights (competitions) directly, athlete-based competitors.
        # No homeAway field; competitors have order=1 and order=2.
        # Detect card segments by time grouping (Main Card / Prelims / Early Prelims).
        for event in d.get("events", []):
            event_name = event.get("shortName") or event.get("name", "")
            event_date = event.get("date", "")
            comps = event.get("competitions", [])
            if not comps:
                continue
            # Group fights by distinct start hour to detect card segments
            distinct_times = []  # list of (sortable_datetime, hour_key)
            for comp in comps:
                t = (comp.get("startDate") or comp.get("date", "")).replace("Z", "+00:00")
                try:
                    dt_obj = _dt.datetime.fromisoformat(t)
                    hour_key = dt_obj.strftime("%H")
                    if not any(hk == hour_key for _, hk in distinct_times):
                        distinct_times.append((dt_obj, hour_key))
                except (ValueError, TypeError):
                    pass
            # Sort by actual datetime (handles overnight events where UTC hour wraps)
            distinct_times.sort(key=lambda x: x[0])
            # Extract ordered hour keys
            ordered_hours = [hk for _, hk in distinct_times]
            # Map time group → card-segment label
            segment_map = {}
            if len(ordered_hours) == 1:
                segment_map = {ordered_hours[0]: "Main Card"}
            elif len(ordered_hours) == 2:
                segment_map = {ordered_hours[0]: "Prelims", ordered_hours[1]: "Main Card"}
            else:
                segment_map = {ordered_hours[0]: "Early Prelims", ordered_hours[1]: "Prelims",
                               ordered_hours[-1]: "Main Card"}
                # Any extra middle times also map to Prelims
                for t in ordered_hours[2:-1]:
                    segment_map[t] = "Prelims"
            # Build fights
            for comp in comps:
                # Determine card segment
                t = (comp.get("startDate") or comp.get("date", "")).replace("Z", "+00:00")
                card_segment = ""
                try:
                    dt_obj = _dt.datetime.fromisoformat(t)
                    hour_key = dt_obj.strftime("%H")
                    card_segment = segment_map.get(hour_key, "")
                except (ValueError, TypeError):
                    pass
                status = comp.get("status", {})
                st = status.get("type", {})
                weight_class = (comp.get("type") or {}).get("abbreviation", "")
                fighters = {}
                for c in comp.get("competitors", []):
                    ath = c.get("athlete", {})
                    name = ath.get("displayName") or ath.get("fullName") or "TBD"
                    abbrev = ath.get("shortName") or name[:3].upper()
                    record = ""
                    for rec in c.get("records", []):
                        if rec.get("type") == "total":
                            record = rec.get("summary", "")
                            break
                    slot = "home" if c.get("order") == 1 else "away"
                    fighters[slot] = {
                        "abbrev": abbrev,
                        "name": name,
                        "score": None,
                        "record": record,
                        "winner": c.get("winner"),
                    }
                out.append({
                    "game_id": comp.get("id"),
                    "date": comp.get("date") or event_date,
                    "state": st.get("state"),
                    "status": st.get("description") or weight_class or "",
                    "period": status.get("period"),
                    "clock": status.get("displayClock"),
                    "status_detail": st.get("shortDetail"),
                    "home": fighters.get("home"),
                    "away": fighters.get("away"),
                    "event": event_name,
                    "card_segment": card_segment,
                })
    elif league == "wc":
        # Soccer (World Cup) - events with group/round context, draws, ET, penalties
        for e in d.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            status = comp.get("status", {})
            st = status.get("type", {})

            teams = {}
            winner_abbrev = None
            for c in comp.get("competitors", []):
                t = c.get("team", {})
                teams[c.get("homeAway")] = {
                    "abbrev": t.get("abbreviation"),
                    "name": t.get("displayName"),
                    "nickname": t.get("name"),
                    "score": _num(c.get("score")),
                    "winner": c.get("winner"),
                }
                if c.get("winner") is True:
                    winner_abbrev = t.get("abbreviation")

            state = st.get("state")
            is_post = state == "post"
            hs = teams.get("home", {}).get("score")
            away_s = teams.get("away", {}).get("score")
            is_draw = is_post and hs is not None and away_s is not None and hs == away_s

            status_name = st.get("name", "")
            stage = "regular"
            if "EXTRA" in status_name:
                stage = "et"
            if "SHOOTOUT" in status_name:
                stage = "pens"

            status_display = st.get("description") or ""
            if is_post:
                if is_draw and winner_abbrev:
                    status_display = "FT (Pens)"
                elif stage == "et":
                    status_display = "FT (AET)"
                else:
                    status_display = "FT"

            notes = comp.get("notes", [])
            subtitle = ""
            for n in notes:
                headline = n.get("headline", "") or ""
                if "Group" in headline:
                    subtitle = headline
                    break

            out.append({
                "game_id": e.get("id"),
                "date": e.get("date"),
                "state": state,
                "status": status_display,
                "period": status.get("period"),
                "clock": status.get("displayClock"),
                "status_detail": st.get("shortDetail"),
                "home": teams.get("home"),
                "away": teams.get("away"),
                "subtitle": subtitle,
                "is_draw": is_draw,
                "winner_abbrev": winner_abbrev,
                "stage": stage,
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
                    "nickname": c.get("team", {}).get("name"),
                    "score": _num(c.get("score")),
                }
            out.append({
                "game_id": e.get("id"),
                "date": e.get("date"),
                "state": st.get("state"),
                "status": st.get("description"),
                "period": status.get("period"),
                "clock": status.get("displayClock"),
                "status_detail": st.get("shortDetail"),
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



def group_standings(league):
    """World Cup group tables — per-group standings with draws.
    Returns [{group: "Group A", rows: [{rank, abbrev, name, played, wins, draws, losses, gf, ga, gd, points}]}]
    """
    _, path = _check(league)
    d = _get(_CORE.format(path=path) + "/standings", ttl=900)
    groups = []
    for child in d.get("children", []):
        gname = child.get("name", "")
        rows = []
        for ent in child.get("standings", {}).get("entries", []):
            s = {x.get("name"): x.get("value") for x in ent.get("stats", [])}
            t = ent.get("team", {})
            rows.append({
                "rank": int(s.get("rank", 0)),
                "abbrev": t.get("abbreviation"),
                "name": t.get("displayName"),
                "played": int(s.get("gamesPlayed", 0)),
                "wins": int(s.get("wins", 0)),
                "draws": int(s.get("ties", 0)),
                "losses": int(s.get("losses", 0)),
                "gf": int(s.get("pointsFor", 0)),
                "ga": int(s.get("pointsAgainst", 0)),
                "gd": int(s.get("pointDifferential", 0)),
                "points": int(s.get("points", 0)),
            })
        rows.sort(key=lambda r: r["rank"])
        groups.append({"group": gname, "rows": rows})
    return groups



def summary(league, game_id):
    """Cached raw ESPN /summary JSON for one game. TTL 20s.
    Shared by boxscore, play-by-play, lineups, match_events, and game_result.
    One fetch serves all callers — the second and subsequent hits come from the in-memory
    _CACHE without an extra HTTP round-trip."""
    _, path = _check(league)
    return _get(_SITE.format(path=path) + f"/summary?event={game_id}", ttl=20)


def game_result_soccer(league, game_id):
    """Soccer-specific game result — uses competitor.winner flag (penalty/AET aware)."""
    d = summary(league, game_id)
    comp = (d.get("header", {}).get("competitions") or [{}])[0]
    st = comp.get("status", {}).get("type", {})
    scores = {}
    winner = None
    for c in comp.get("competitors", []):
        abbr = c.get("team", {}).get("abbreviation")
        scores[abbr] = _num(c.get("score"))
        if c.get("winner") is True:
            winner = abbr
    return {"state": st.get("state"), "scores": scores, "winner": winner}


def lineups(league, game_id):
    """Starting XI + formation for a soccer match. [{side: 'home'|'away', formation, players: [{jersey, name, position}]}]"""
    d = summary(league, game_id)
    result = []
    for roster in d.get("rosters", []):
        side = "home" if roster.get("homeAway") == "home" else "away"
        formation = roster.get("formation", "")
        players = []
        for p in roster.get("roster", []):
            ath = p.get("athlete", {})
            players.append({
                "jersey": p.get("jersey"),
                "name": ath.get("displayName") or ath.get("fullName"),
                "position": p.get("position", ""),
                "starter": p.get("starter", False),
            })
        result.append({"side": side, "formation": formation, "players": players})
    return result


def wc_knockout_standings():
    """World Cup knockout bracket/results from the scoreboard.

    When group_standings() returns empty (group stage is over), read the
    scoreboard for knockout events. ESPN /standings returns {children: []}
    once groups finish, but /scoreboard carries the bracket events with
    results, scores, and winner flags.

    Returns {rounds: [{name, matches: [{home, away, homeScore, awayScore,
                                         winner, status, game_id}]}]}

    §10: ESPN fields are OBJECTS — extract .abbreviation from team,
         .displayValue from scores before returning.
    """
    _, path = _check("wc")
    d = _get(_SITE.format(path=path) + "/scoreboard", ttl=60)

    # Try to read the current phase from the season envelope
    season = d.get("season") or {}
    if not isinstance(season, dict):
        season = {}
    season_type = season.get("type") or {}
    if not isinstance(season_type, dict):
        season_type = {}
    default_phase = season_type.get("name") or "Knockout Stage"

    # Collect matches, then group by round
    matches = []
    for e in d.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        status = comp.get("status", {}) or {}
        st = status.get("type", {}) or {}

        # ── Round / stage ──
        round_info = e.get("round", {}) or {}
        round_name = (
            round_info.get("displayName")
            or round_info.get("name")
            or round_info.get("shortDisplayName")
            or default_phase
        )

        # ── Competitor data (extract strings, never ship raw ESPN objects) ──
        home_team = None
        away_team = None
        home_score = None
        away_score = None
        winner = None

        for c in comp.get("competitors", []):
            t = c.get("team", {}) or {}
            # §10: team is an object — extract .abbreviation
            abbrev = t.get("abbreviation")

            # Score may be a raw number or an object {value, displayValue}
            score_raw = c.get("score")
            if isinstance(score_raw, dict):
                score_val = score_raw.get("displayValue")
                if score_val is None:
                    score_val = score_raw.get("value")
            else:
                score_val = score_raw

            ha = c.get("homeAway")
            if ha == "home":
                home_team = abbrev
                home_score = score_val
            else:
                away_team = abbrev
                away_score = score_val

            if c.get("winner") is True:
                winner = abbrev

        matches.append({
            "home": home_team,
            "away": away_team,
            "homeScore": home_score,
            "awayScore": away_score,
            "winner": winner,
            "status": st.get("name") or st.get("description") or "",
            "round": round_name,
            "game_id": e.get("id"),
        })

    # Group by round
    rounds_map = {}
    for m in matches:
        rname = m.pop("round", default_phase)
        if rname not in rounds_map:
            rounds_map[rname] = []
        rounds_map[rname].append(m)

    # Stable order (canonical knockout sequence)
    ROUND_ORDER = [
        "Round of 32", "Round of 16", "Quarterfinals",
        "Semifinals", "Third Place", "Final",
    ]
    rounds = []
    for rname in ROUND_ORDER:
        if rname in rounds_map:
            rounds.append({"name": rname, "matches": rounds_map.pop(rname)})
    # Anything left (unusual round names)
    for rname, match_list in rounds_map.items():
        rounds.append({"name": rname, "matches": match_list})

    return {"rounds": rounds}


def match_events(league, game_id):
    """Key events + commentary for a soccer match."""
    d = summary(league, game_id)
    return {
        "key_events": d.get("keyEvents", []),
        "commentary": d.get("commentary", []),
    }

def boxscore(league, game_id):
    """Full per-game box score (team + player stat lines)."""
    d = summary(league, game_id)
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
    the game was played. winner is None until the game is final. Soccer uses competitor.winner flag.
    """
    if league == "wc":
        return game_result_soccer(league, game_id)
    d = summary(league, game_id)
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
