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
import json, re, time, unicodedata, urllib.request

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
_COMMON = "https://site.web.api.espn.com/apis/common/v3/sports/{path}"
_SPORTS_CORE = "https://sports.core.api.espn.com/v2/sports/{sport}"
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


def _normalize_team_events(events):
    """Normalize team-vs-team scoreboard events into the shared game shape."""
    out = []
    for event in events or []:
        competition = (event.get("competitions") or [{}])[0]
        status = competition.get("status", {})
        status_type = status.get("type", {})
        teams = {}
        for competitor in competition.get("competitors", []):
            team = competitor.get("team", {})
            teams[competitor.get("homeAway")] = {
                "abbrev": team.get("abbreviation"),
                "name": team.get("displayName"),
                "nickname": team.get("name"),
                "score": _num(competitor.get("score")),
            }
        out.append({
            "game_id": event.get("id"),
            "date": event.get("date"),
            "state": status_type.get("state"),
            "status": status_type.get("description"),
            "period": status.get("period"),
            "clock": status.get("displayClock"),
            "status_detail": status_type.get("shortDetail"),
            "home": teams.get("home"),
            "away": teams.get("away"),
        })
    return out


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
                        "id": str(c.get("id") or ath.get("id") or ""),
                        "abbrev": abbrev,
                        "name": name,
                        "score": None,
                        "record": record,
                        "winner": c.get("winner"),
                    }
                out.append({
                    "game_id": comp.get("id"),
                    "event_id": str(event.get("id") or ""),
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
        out.extend(_normalize_team_events(d.get("events", [])))
    return out


def nfl_schedule_weeks(season):
    """Return ESPN's ordered NFL phase/week catalog for one league season."""
    season = int(season)
    _, path = _check("nfl")
    url = _SITE.format(path=path) + f"/scoreboard?dates={season}&limit=1"
    data = _get(url, ttl=900)
    league = (data.get("leagues") or [{}])[0]
    league_season = league.get("season") or {}
    if _int(league_season.get("year")) != season:
        raise ValueError(f"ESPN NFL calendar unavailable for season {season}")

    phases = []
    for phase in league.get("calendar") or []:
        season_type = _int(phase.get("value"))
        entries = []
        if season_type is None:
            continue
        for entry in phase.get("entries") or []:
            week = _int(entry.get("value"))
            if week is None or not entry.get("startDate") or not entry.get("endDate"):
                continue
            entries.append({
                "key": f"{season_type}:{week}",
                "season_type": season_type,
                "week": week,
                "label": entry.get("label") or entry.get("alternateLabel") or f"Week {week}",
                "alternate_label": entry.get("alternateLabel"),
                "detail": entry.get("detail"),
                "start_time": entry.get("startDate"),
                "end_time": entry.get("endDate"),
            })
        if entries:
            phases.append({
                "season_type": season_type,
                "label": phase.get("label") or f"Season type {season_type}",
                "start_time": phase.get("startDate"),
                "end_time": phase.get("endDate"),
                "weeks": entries,
            })
    if not phases:
        raise ValueError(f"ESPN NFL calendar has no weeks for season {season}")
    return phases


def nfl_schedule_week_games(season, season_type, week):
    """Return one ESPN NFL week, filtered defensively to the requested identity."""
    season = int(season)
    season_type = int(season_type)
    week = int(week)
    _, path = _check("nfl")
    url = (
        _SITE.format(path=path)
        + f"/scoreboard?dates={season}&seasontype={season_type}&week={week}&limit=100"
    )
    data = _get(url, ttl=20)
    events = []
    for event in data.get("events") or []:
        event_season = event.get("season") or {}
        event_week = event.get("week") or {}
        if _int(event_season.get("year")) != season:
            continue
        if _int(event_season.get("type")) != season_type:
            continue
        if _int(event_week.get("number")) != week:
            continue
        events.append(event)
    return _normalize_team_events(events)


def schedule_event_starts(league, start_date, end_date, limit=1000):
    """Return absolute event start instants from one bounded scoreboard range.

    This is intentionally lower-level than :func:`games`: callers that need to
    choose a viewer-local schedule date must convert the returned ISO instants
    in the browser's timezone. ESPN date buckets are US-sports calendar dates,
    while an evening game often starts on the following UTC date.
    """
    _, path = _check(league)
    start = start_date.strftime("%Y%m%d")
    end = end_date.strftime("%Y%m%d")
    bounded_limit = max(1, min(int(limit), 1000))
    url = (
        _SITE.format(path=path)
        + f"/scoreboard?dates={start}-{end}&limit={bounded_limit}"
    )
    data = _get(url, ttl=900)
    starts = {
        str(event.get("date"))
        for event in data.get("events", [])
        if event.get("date")
    }
    return sorted(starts)


def _athlete_name_key(name):
    value = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _athlete_name_parts(name):
    value = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    return re.findall(r"[a-z0-9]+", value.lower())


def ufc_athlete(name, date=None):
    """Resolve a fighter name to ESPN's athlete id from a nearby UFC card.

    Prop-ingested UFC names are occasionally clipped at the end, so resolution
    prefers an exact normalized match and permits a unique 7+ character prefix.
    The date neighborhood handles cards whose early prelims and main card cross
    midnight UTC.
    """
    candidates = []
    if date:
        import datetime as _dt
        try:
            base = _dt.datetime.strptime(str(date)[:10], "%Y-%m-%d").date()
            candidates.extend((base, base - _dt.timedelta(days=1), base + _dt.timedelta(days=1)))
        except (TypeError, ValueError):
            pass
    candidates.append(None)

    fighters = {}
    seen_dates = set()
    for candidate in candidates:
        date_text = candidate.isoformat() if candidate is not None else None
        if date_text in seen_dates:
            continue
        seen_dates.add(date_text)
        try:
            card = games("ufc", date_text)
        except Exception:
            continue
        for fight in card:
            for side in ("home", "away"):
                fighter = fight.get(side) or {}
                athlete_id = str(fighter.get("id") or "")
                fighter_name = fighter.get("name") or ""
                if athlete_id and fighter_name:
                    fighters[athlete_id] = {"id": athlete_id, "name": fighter_name}

    target = _athlete_name_key(name)
    exact = [fighter for fighter in fighters.values() if _athlete_name_key(fighter["name"]) == target]
    if len(exact) == 1:
        return exact[0]
    if len(target) < 7:
        return None
    prefix = [
        fighter for fighter in fighters.values()
        if target.startswith(_athlete_name_key(fighter["name"]))
        or _athlete_name_key(fighter["name"]).startswith(target)
    ]
    if len(prefix) == 1:
        return prefix[0]

    # A source may include a middle name omitted by the prop feed ("Jose
    # Delgado" vs "Jose Miguel Delgado"). First + last must both match and the
    # candidate must be unique on the nearby card.
    target_parts = _athlete_name_parts(name)
    if len(target_parts) < 2:
        return None
    first_last = []
    for fighter in fighters.values():
        parts = _athlete_name_parts(fighter["name"])
        if len(parts) >= 2 and parts[0] == target_parts[0] and parts[-1] == target_parts[-1]:
            first_last.append(fighter)
    return first_last[0] if len(first_last) == 1 else None


def _ufc_method(result):
    raw = " ".join(str((result or {}).get(key) or "") for key in (
        "name", "displayName", "shortDisplayName"
    )).lower()
    if "submission" in raw or re.search(r"\bsub\b", raw):
        return "SUB"
    if "knockout" in raw or "tko" in raw or re.search(r"\bko\b", raw):
        return "KO/TKO"
    if "decision" in raw or re.search(r"\bdec\b", raw):
        return "DEC"
    if "disqualification" in raw or re.search(r"\bdq\b", raw):
        return "DQ"
    if "no contest" in raw:
        return "NC"
    return (result or {}).get("shortDisplayName") or "—"


def ufc_fight_history(athlete_id, limit=5):
    """Return a fighter's most-recent completed UFC results from ESPN.

    ESPN's athlete overview returns five compact fight references. Resolve the
    referenced competition, status/result method, and opponent in parallel;
    each upstream object is cached for six hours by the shared client cache.
    """
    from concurrent.futures import ThreadPoolExecutor

    athlete_id = str(athlete_id)
    overview = _get(
        _COMMON.format(path="mma/ufc") + f"/athletes/{athlete_id}/overview",
        ttl=21600,
    )
    references = []
    for item in overview.get("fightHistory", []):
        uid = item if isinstance(item, str) else (item or {}).get("uid", "")
        match = re.search(r"~e:(\d+)~c:(\d+)", uid or "")
        if match:
            references.append((match.group(1), match.group(2)))
        if len(references) >= max(1, min(int(limit), 5)):
            break

    def safe_get(url):
        try:
            return _get(url, ttl=21600)
        except Exception:
            return {}

    objects = {}
    jobs = []
    for event_id, fight_id in references:
        base = (
            _SPORTS_CORE.format(sport="mma")
            + f"/leagues/ufc/events/{event_id}/competitions/{fight_id}"
        )
        jobs.append(((fight_id, "competition"), base + "?lang=en&region=us"))
        jobs.append(((fight_id, "status"), base + "/status?lang=en&region=us"))
    with ThreadPoolExecutor(max_workers=min(10, max(1, len(jobs)))) as pool:
        futures = [(key, pool.submit(safe_get, url)) for key, url in jobs]
        for key, future in futures:
            objects[key] = future.result()

    opponent_ids = set()
    for _, fight_id in references:
        competition = objects.get((fight_id, "competition"), {})
        opponent_ids.update(
            str(row.get("id")) for row in competition.get("competitors", [])
            if row.get("id") is not None and str(row.get("id")) != athlete_id
        )

    opponent_names = {}
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(opponent_ids)))) as pool:
        futures = {
            opponent_id: pool.submit(
                safe_get,
                _SPORTS_CORE.format(sport="mma")
                + f"/athletes/{opponent_id}?lang=en&region=us",
            )
            for opponent_id in opponent_ids
        }
        for opponent_id, future in futures.items():
            athlete = future.result()
            opponent_names[opponent_id] = (
                athlete.get("displayName") or athlete.get("fullName") or "Opponent"
            )

    fights = []
    for event_id, fight_id in references:
        competition = objects.get((fight_id, "competition"), {})
        status = objects.get((fight_id, "status"), {})
        if (status.get("type") or {}).get("state") != "post":
            continue
        competitors = competition.get("competitors", [])
        fighter = next((row for row in competitors if str(row.get("id")) == athlete_id), None)
        opponent = next((row for row in competitors if str(row.get("id")) != athlete_id), None)
        if not fighter or not opponent:
            continue
        if fighter.get("winner") is True:
            outcome = "W"
        elif opponent.get("winner") is True:
            outcome = "L"
        else:
            result_text = str((status.get("result") or {}).get("displayName") or "").lower()
            outcome = "D" if "draw" in result_text else "NC"
        opponent_id = str(opponent.get("id") or "")
        # round/clock: ESPN's status object for a "post" (final) competition reports the
        # round the fight ended in (period) and elapsed time within that round (clock,
        # seconds; displayClock, "M:SS") -- already being fetched here for method/result,
        # just never read. UFC rounds are a fixed 5 minutes, so total fight time =
        # (round - 1) * 300 + clock_seconds.
        round_num = status.get("period")
        clock_seconds = status.get("clock")
        fight_time_seconds = (
            (round_num - 1) * 300 + clock_seconds
            if isinstance(round_num, int) and isinstance(clock_seconds, (int, float))
            else None
        )
        fights.append({
            "result": outcome,
            "method": _ufc_method(status.get("result") or {}),
            "opponent": opponent_names.get(opponent_id, "Opponent"),
            "date": str(competition.get("date") or "")[:10],
            "event_id": event_id,
            "fight_id": fight_id,
            "round": round_num,
            "clock_display": status.get("displayClock"),
            "fight_time_seconds": fight_time_seconds,
        })
    fights.sort(key=lambda row: row["date"], reverse=True)
    return fights[:limit]


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
            w, l = _int(s.get("wins")), _int(s.get("losses"))
            if wp is None and w is not None:
                # NHL (and any league) exposes no winPercent stat — derive it.
                # Prefer games played (includes OT losses) so it isn't overstated.
                denom = _int(s.get("gamesPlayed")) or ((w or 0) + (l or 0))
                wp = (w / denom) if denom else None
            # ESPN's NHL "Last Ten Games" displayValue is e.g. "7-2-1, 0 PTS";
            # keep just the record and drop the stray points suffix.
            last10 = disp.get("Last Ten Games")
            if isinstance(last10, str) and "," in last10:
                last10 = last10.split(",")[0].strip()
            rows.append({
                "abbrev": t.get("abbreviation"),
                "name": t.get("displayName"),
                "wins": w,
                "losses": l,
                "win_pct": round(wp, 4) if wp is not None else None,
                "differential": s.get("pointDifferential", s.get("differential")),
                "streak": disp.get("streak"),
                "last10": last10,
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


# ── Canonical World Cup knockout contract ─────────────────────────────────
# One shape, used by BOTH /api/wc/standings (during knockouts) and
# /api/wc/knockout. Each round: {round, matches:[M]}. Each match M:
#   {game_id, date, home:{abbrev,name}, away:{abbrev,name},
#    homeScore, awayScore, winner, status, state}
# §10: ESPN team/score fields are OBJECTS — extract .abbreviation/.displayName
#      and .displayValue before returning. Never ship raw ESPN objects.
_WC_ROUND_MAP = {
    "round-of-32": "Round of 32",
    "round-of-16": "Round of 16",
    "quarterfinals": "Quarterfinals",
    "semifinals": "Semifinals",
    "3rd-place-match": "Third Place",
    "final": "Final",
}
_WC_ROUND_ORDER = [
    "Round of 32", "Round of 16", "Quarterfinals",
    "Semifinals", "Third Place", "Final",
]


def _wc_round_from_event(e):
    """Determine the knockout round name from event.season.slug (canonical),
    falling back to competition.altGameNote text parsing."""
    slug = ((e.get("season") or {}).get("slug") or "").lower()
    if slug in _WC_ROUND_MAP:
        return _WC_ROUND_MAP[slug]
    # Fallback: altGameNote like "FIFA World Cup, Round of 32"
    note = ((e.get("competitions") or [{}])[0].get("altGameNote") or "")
    for key, label in _WC_ROUND_MAP.items():
        if label.lower() in note.lower():
            return label
    return "Knockout"


def _wc_competitor(c):
    """Extract {abbrev, name} + numeric score + winner flag from one ESPN
    competitor entry (objects → strings/ints per §10)."""
    t = c.get("team", {}) or {}
    abbrev = t.get("abbreviation")
    name = t.get("displayName") or t.get("name") or abbrev or ""
    score_raw = c.get("score")
    if isinstance(score_raw, dict):
        score_val = score_raw.get("displayValue")
        if score_val is None:
            score_val = score_raw.get("value")
    else:
        score_val = score_raw
    try:
        score = int(score_val) if score_val not in (None, "") else None
    except (TypeError, ValueError):
        score = None
    return {
        "abbrev": abbrev,
        "name": name,
        "score": score,
        "winner": bool(c.get("winner") is True),
    }


def wc_knockout_standings():
    """World Cup knockout bracket/results — the COMPLETE current bracket.

    Future-proof: read leagues[0].calendar[0].entries from the default
    scoreboard, exclude the 'Group' phase, derive the first knockout start
    date and last knockout end date, then issue ONE cached range request
    (?dates=START-END&limit=100). Group matches by event.season.slug into
    the canonical six rounds, dedupe by event id.

    Returns {rounds:[{round, matches:[{game_id, date, home:{abbrev,name},
    away:{abbrev,name}, homeScore, awayScore, winner, status, state}]}]}.

    During the group stage the bracket is empty — callers fall back to
    group tables. See wc_is_knockout() for the gate.
    """
    _, path = _check("wc")

    # ── 1. Derive the knockout date window from the calendar ──
    d = _get(_SITE.format(path=path) + "/scoreboard", ttl=300)
    league_blob = (d.get("leagues") or [{}])[0]
    calendar = league_blob.get("calendar") or [{}]
    entries = (calendar[0].get("entries") if calendar else []) or []
    ko_start = None
    ko_end = None
    for ent in entries:
        if (ent.get("label") or "").lower().startswith("group"):
            continue
        sd = ent.get("startDate")
        ed = ent.get("endDate")
        if sd and (ko_start is None or sd < ko_start):
            ko_start = sd
        if ed and (ko_end is None or ed > ko_end):
            ko_end = ed

    if not ko_start or not ko_end:
        # No knockout window published yet (pre-tournament) — nothing to show.
        return {"rounds": []}

    # ESPN date range format: YYYYMMDD-YYYYMMDD
    def _ymd(iso):
        return iso[:10].replace("-", "")
    rng = f"{_ymd(ko_start)}-{_ymd(ko_end)}"

    # ── 2. One cached range request for the whole bracket ──
    rd = _get(
        _SITE.format(path=path) + f"/scoreboard?dates={rng}&limit=100",
        ttl=120,
    )

    # ── 3. Build canonical rounds, dedupe by event id ──
    rounds_map = {}
    seen = set()
    for e in rd.get("events", []):
        eid = e.get("id")
        if eid in seen:
            continue
        seen.add(eid)
        comp = (e.get("competitions") or [{}])[0]
        comp_status = comp.get("status", {}) or {}
        st = comp_status.get("type", {}) or {}
        state = st.get("state") or ""

        home = away = None
        for c in comp.get("competitors", []):
            ci = _wc_competitor(c)
            if c.get("homeAway") == "home":
                home = ci
            else:
                away = ci
        if not home or not away:
            continue

        winner = home["abbrev"] if home["winner"] else (
            away["abbrev"] if away["winner"] else None)

        match = {
            "game_id": eid,
            "date": e.get("date"),
            "home": {"abbrev": home["abbrev"], "name": home["name"]},
            "away": {"abbrev": away["abbrev"], "name": away["name"]},
            "homeScore": home["score"],
            "awayScore": away["score"],
            "winner": winner,
            "status": st.get("name") or st.get("description") or "",
            "state": state,
        }
        rname = _wc_round_from_event(e)
        rounds_map.setdefault(rname, []).append(match)

    # Stable canonical order
    rounds = []
    for rname in _WC_ROUND_ORDER:
        if rname in rounds_map:
            rounds.append({"round": rname, "matches": rounds_map.pop(rname)})
    for rname, match_list in rounds_map.items():  # unknown round names last
        rounds.append({"round": rname, "matches": match_list})

    return {"rounds": rounds}


def wc_is_knockout():
    """True once the current WC league-season phase is NOT 'Group'.

    Reads league.season.type.name from the default scoreboard. While it is
    'Group' (or missing) the group stage is live and the bracket must not be
    served. Used by /api/wc/standings to pick bracket vs group tables.
    """
    _, path = _check("wc")
    d = _get(_SITE.format(path=path) + "/scoreboard", ttl=300)
    league_blob = (d.get("leagues") or [{}])[0]
    stype = (league_blob.get("season") or {}).get("type") or {}
    phase = (stype.get("name") or "") if isinstance(stype, dict) else ""
    return bool(phase) and phase.lower() != "group"


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
