"""espn_client.scoreboard -- normalized scoreboards for every league shape.

`games()` and `scoreboard_raw()` share one fetch (the raw document also carries
`leagues[0].calendar`, which the ingest reads to know when a league plays).
Tennis returns tournaments as events with matches nested in groupings;
UFC returns events with fights directly; soccer (wc/lcup/mls) carries group
context, draws, extra time and penalties; everything else is team-vs-team.

Internal calls to shared public names (`_check`, `_get`, `scoreboard_raw`)
resolve through the `espn_client` package object at call time so that
monkeypatching `espn_client._get` (as the test suite does) keeps working the
way it did when this was a single module.
"""
import datetime as _dt

import espn_client

# ---------------------------------------------------------------------------
# Major tournament filter -- only Grand Slams, Masters/WTA 1000, and year-end Finals.
# Substrings matched case-insensitively against ESPN's event shortName.
# ---------------------------------------------------------------------------
# Canonical keys -- each tuple is (canonical_name, espn_name_substrings)
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


def _iso(text):
    """ESPN timestamp -> aware datetime, or None. Never raises.

    ESPN writes `2026-11-09T04:59Z` -- a trailing `Z` and no seconds. Python 3.8
    (the dev venv; the image is 3.11) rejects the `Z`, so it is rewritten the
    same way the rest of this module already does it.
    """
    if not text:
        return None
    try:
        return _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def neighbor_dates(date_text):
    """Return an ESPN scoreboard date followed by its previous and next day.

    Book/game dates are often UTC while ESPN indexes US events by the local card
    or slate date.  UFC cards routinely cross midnight UTC, so both linking and
    later competition lookup must use this exact same window.
    """
    try:
        base = _dt.date.fromisoformat(str(date_text))
    except (TypeError, ValueError):
        return [date_text]
    return [base.isoformat(),
            (base - _dt.timedelta(days=1)).isoformat(),
            (base + _dt.timedelta(days=1)).isoformat()]


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
        event_season = event.get("season") or {}
        out.append({
            "game_id": event.get("id"),
            "date": event.get("date"),
            "state": status_type.get("state"),
            # `state == "post"` is not "this game was played": a POSTPONED game is
            # also state="post", with a score of 0 rather than null. ESPN publishes
            # the question directly; ingests must filter on this, not on state.
            "completed": bool(status_type.get("completed")),
            "status": status_type.get("description"),
            "period": status.get("period"),
            "clock": status.get("displayClock"),
            "status_detail": status_type.get("shortDetail"),
            # The phase, as the publisher files it -- see backend/game_types.py.
            # `competition_type` is carried separately because it is the only thing
            # that distinguishes an NBA All-Star exhibition from a regular-season
            # game: both are published season.type=2.
            "season_type": _int(event_season.get("type")),
            "season_slug": event_season.get("slug"),
            "competition_type": (competition.get("type") or {}).get("abbreviation"),
            "home": teams.get("home"),
            "away": teams.get("away"),
        })
    return out


def scoreboard_raw(league, date=None, ttl=20):
    """The scoreboard document as published, before normalization.

    `games()` throws away everything outside `events`, but the same response
    also carries `leagues[0].calendar` -- when this league plays. Reading that
    is how the ingest knows not to ask about the NHL in August
    (`league_activity.py`), and it must not cost a second request, so the
    normalized and raw readers share one fetch instead of each having their own.
    """
    _, path = espn_client._check(league)
    q = ("?dates=" + date.replace("-", "")) if date else ""
    return espn_client._get(espn_client._SITE.format(path=path) + "/scoreboard" + q, ttl=ttl)


def games(league, date=None):
    """Normalized scoreboard. date='YYYY-MM-DD' (or None=today). state: pre | in | post."""
    _, path = espn_client._check(league)
    return _games_from_payload(league, date, espn_client.scoreboard_raw(league, date))


def _games_from_payload(league, date, d):
    """Normalize a raw scoreboard payload into the shared game shape.

    This is the body of `games()` after its fetch. Split out so a date-range
    payload (see `games_by_day`) can be normalized once and bucketed by day
    instead of fetching per day. `date` is consulted only by tennis, which
    filters a week-long tournament to the requested day; every other league
    shape normalizes all events in the payload.
    """
    is_tennis = league in ("atp", "wta")
    is_ufc = league == "ufc"
    out = []

    if is_tennis:
        # Tennis returns tournaments as events, matches nested in groupings[].competitions[]
        # Tournaments span weeks -- filter to the requested date (or today)
        target_date = None
        if date:
            target_date = _dt.datetime.strptime(date, "%Y-%m-%d").date()
        else:
            target_date = _dt.date.today()
        for event in d.get("events", []):
            # ATP/WTA both return full tournament -- filter by gender grouping
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
                # Singles only -- skip doubles and mixed
                if "doubles" in slug or "mixed" in slug:
                    continue
                for comp in grp.get("competitions", []):
                    # Filter by date -- tennis tournaments span weeks
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
                        ath = {}
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
                            # Tennis competitors are athletes rather than teams.
                            # Preserve ESPN's native athlete ID so a prop game
                            # can be linked by its already-resolved players,
                            # not a lossy display-name comparison.
                            "athlete_id": str(c.get("id") or ath.get("id") or "") or None,
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
        # UFC -- events contain fights (competitions) directly, athlete-based competitors.
        # No homeAway field; competitors have order=1 and order=2.
        # Detect card segments by time grouping (Main Card / Prelims / Early Prelims).
        # Lazy import: ufc.py imports the package, so this must not run at module load.
        import espn_client.ufc as _ufc
        for event in d.get("events", []):
            # `name` over `shortName`: ESPN publishes the week on the long name
            # and drops it from the short one. Measured 2026-08-18:
            #   name      "Dana White's Contender Series: Season 10, Week 2"
            #   shortName "Dana White's Contender Series"
            # The board names a UFC event the way it names a tennis tournament,
            # and "Contender Series" with no week is three different cards a
            # month sharing one heading.
            event_name = event.get("name") or event.get("shortName") or ""
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
                # The finish method, round and clock: ESPN publishes them in
                # details[] and the raw path used to throw them away — see
                # espn_client.ufc.ufc_outcome. A final with no score shows the
                # method, so a card can read "SUB · R3 1:24".
                outcome_method, outcome_round, outcome_clock = _ufc.ufc_outcome(comp)
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
                    "outcome_method": outcome_method,
                    "outcome_round": outcome_round,
                    "outcome_clock": outcome_clock,
                })
    elif league in ("wc", "lcup", "mls"):
        # Soccer (World Cup / Leagues Cup / MLS) - events with group/round context, draws, ET, penalties
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
            suspended = "SUSPEND" in status_name

            status_display = st.get("description") or ""
            if is_post:
                if suspended:
                    # Weather/other suspension: ESPN closes the event (state=post)
                    # but the match is NOT over -- never label it "FT".
                    status_display = "Suspended"
                elif is_draw and winner_abbrev:
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


def _ny_date(instant):
    """America/New_York calendar date of a UTC instant, DST-aware.

    Python 3.8 (the dev venv; the image is 3.11) has no `zoneinfo`, so the
    rule is computed: EDT from the second Sunday of March 07:00Z until the
    first Sunday of November 06:00Z, EST otherwise. This is the bucket key
    for US leagues, because ESPN files an event under the local day the
    venue plays it -- a 01:00Z fight is the evening of the previous day in
    the US, and the store's `game_date` matches the New York day, not the
    UTC day (measured 374/374 rows, 2026-08-18).
    """
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=_dt.timezone.utc)
    instant = instant.astimezone(_dt.timezone.utc)
    year = instant.year

    def _nth_sunday(month, n):
        first = _dt.date(year, month, 1)
        return first + _dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))

    dst_start = _dt.datetime.combine(_nth_sunday(3, 2), _dt.time(7, 0), tzinfo=_dt.timezone.utc)
    dst_end = _dt.datetime.combine(_nth_sunday(11, 1), _dt.time(6, 0), tzinfo=_dt.timezone.utc)
    offset = _dt.timedelta(hours=-4) if dst_start <= instant < dst_end else _dt.timedelta(hours=-5)
    return (instant + offset).date()


def _slate_day(league, event_date_text):
    """The local day ESPN files an event under, from its UTC instant.

    US leagues are bucketed by the America/New_York date (see `_ny_date`);
    tennis is bucketed by the UTC date, because its normalization already
    filters competitions by UTC day. Returns 'YYYY-MM-DD' or None.
    """
    if not event_date_text:
        return None
    try:
        moment = _dt.datetime.fromisoformat(str(event_date_text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    if league in ("atp", "wta"):
        return moment.astimezone(_dt.timezone.utc).date().isoformat()
    return _ny_date(moment).isoformat()


def scoreboard_raw_range(league, start, end, ttl=20):
    """The scoreboard document for a date RANGE, in one request.

    ESPN's scoreboard endpoint also takes `?dates=YYYYMMDD-YYYYMMDD`.
    Measured 2026-08-18 (clean, after the 08-18 block): it answers 200 for
    team, combat and soccer leagues, but tennis (atp/wta) returns
    `events: []`, and the response is capped around 100 events (a 30-day
    request came back with exactly 100, cut mid-day). Callers chunk the
    window and split when the cap is hit; tennis stays per-day.
    """
    _, path = espn_client._check(league)
    q = f"?dates={str(start).replace('-', '')}-{str(end).replace('-', '')}"
    return espn_client._get(espn_client._SITE.format(path=path) + "/scoreboard" + q, ttl=ttl)


def games_by_day(league, start, end):
    """Normalized games for a date range, keyed by the local slate day.

    One request for the whole range (`scoreboard_raw_range`), then the
    normalized games are bucketed under the day ESPN files them (`_slate_day`).
    Returns `(by_day, raw_event_count)`: the bucketed games and how many raw
    events the payload held. The ~100-event ceiling applies to RAW events --
    for UFC one event is a card of many fights, so those are different units,
    and comparing against normalized games would split too eagerly. Callers
    check the raw count against the ceiling.

    Tennis is not supported here: the range form returns no events for
    atp/wta, so callers keep tennis per-day -- and `_games_from_payload`
    would otherwise filter tennis to "today".
    """
    if league in ("atp", "wta"):
        return {}, 0
    payload = scoreboard_raw_range(league, start, end)
    events = payload.get("events") or []
    if not events:
        return {}, 0
    by_day = {}
    for game in _games_from_payload(league, None, payload):
        day = _slate_day(league, game.get("date"))
        if day:
            by_day.setdefault(day, []).append(game)
    return by_day, len(events)
