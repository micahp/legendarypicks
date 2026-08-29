"""espn_client.nfl -- week-based football schedule/calendar reads.

Week catalog (`nfl_schedule_weeks`) is read from the league-season calendar on
the scoreboard document; week games (`nfl_schedule_week_games`) are filtered
defensively to the requested season/type/week identity; `schedule_event_starts`
returns absolute event start instants from a bounded date range.

All shared calls (`_check`, `_get`, `_int`, `_normalize_team_events`) resolve
through the `espn_client` package at call time so monkeypatching
`espn_client._get` (as test_nfl_schedule_api does) keeps working.
"""
import espn_client
from .scoreboard import _normalize_team_events


_WEEK_LEAGUES = ("nfl", "ncaaf")


def football_schedule_weeks(league, season):
    """Return ESPN's ordered phase/week catalog for NFL or NCAAF."""
    league = str(league or "").lower()
    if league not in _WEEK_LEAGUES:
        raise ValueError("week schedule league must be nfl or ncaaf")
    season = int(season)
    _, path = espn_client._check(league)
    url = espn_client._SITE.format(path=path) + f"/scoreboard?dates={season}&limit=1"
    data = espn_client._get(url, ttl=900)
    league_data = (data.get("leagues") or [{}])[0]
    league_season = league_data.get("season") or {}
    if espn_client._int(league_season.get("year")) != season:
        raise ValueError(f"ESPN {league.upper()} calendar unavailable for season {season}")

    phases = []
    for phase in league_data.get("calendar") or []:
        season_type = espn_client._int(phase.get("value"))
        entries = []
        # ESPN type 4 is explicitly off-season. NCAAF currently puts an
        # All-Star entry there; it is not part of the league week schedule.
        if season_type is None or season_type == 4:
            continue
        for entry in phase.get("entries") or []:
            week = espn_client._int(entry.get("value"))
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
        raise ValueError(f"ESPN {league.upper()} calendar has no weeks for season {season}")
    return phases


def nfl_schedule_weeks(season):
    """Backward-compatible NFL catalog wrapper."""
    return football_schedule_weeks("nfl", season)


def football_schedule_week_games(league, season, season_type, week,
                                 start_time=None, end_time=None):
    """Return one football week, filtered to its published identity.

    ESPN's NCAAF ``week=`` response caps at 25 games even with ``limit=1000``.
    Its published calendar window returns the complete slate, so NCAAF uses
    that bounded date range plus ``groups=80`` and then applies the same strict
    season/type/week filter. NFL never exceeds the cap and keeps its existing
    one-week request.
    """
    league = str(league or "").lower()
    if league not in _WEEK_LEAGUES:
        raise ValueError("week schedule league must be nfl or ncaaf")
    season = int(season)
    season_type = int(season_type)
    week = int(week)
    _, path = espn_client._check(league)
    if league == "ncaaf":
        if not start_time or not end_time:
            raise ValueError("NCAAF week games require published start/end times")
        start = str(start_time)[:10].replace("-", "")
        end = str(end_time)[:10].replace("-", "")
        url = (espn_client._SITE.format(path=path)
               + f"/scoreboard?dates={start}-{end}&limit=1000&groups=80")
    else:
        url = (espn_client._SITE.format(path=path)
               + f"/scoreboard?dates={season}&seasontype={season_type}"
                 f"&week={week}&limit=100")
    data = espn_client._get(url, ttl=20)
    events = []
    for event in data.get("events") or []:
        event_season = event.get("season") or {}
        event_week = event.get("week") or {}
        if espn_client._int(event_season.get("year")) != season:
            continue
        if espn_client._int(event_season.get("type")) != season_type:
            continue
        if espn_client._int(event_week.get("number")) != week:
            continue
        events.append(event)
    return _normalize_team_events(events)


def nfl_schedule_week_games(season, season_type, week):
    """Backward-compatible NFL week wrapper."""
    return football_schedule_week_games("nfl", season, season_type, week)


def schedule_event_starts(league, start_date, end_date, limit=1000):
    """Return absolute event start instants from one bounded scoreboard range.

    This is intentionally lower-level than :func:`games`: callers that need to
    choose a viewer-local schedule date must convert the returned ISO instants
    in the browser's timezone. ESPN date buckets are US-sports calendar dates,
    while an evening game often starts on the following UTC date.
    """
    _, path = espn_client._check(league)
    start = start_date.strftime("%Y%m%d")
    end = end_date.strftime("%Y%m%d")
    bounded_limit = max(1, min(int(limit), 1000))
    url = (
        espn_client._SITE.format(path=path)
        + f"/scoreboard?dates={start}-{end}&limit={bounded_limit}"
    )
    data = espn_client._get(url, ttl=900)
    starts = {
        str(event.get("date"))
        for event in data.get("events", [])
        if event.get("date")
    }
    return sorted(starts)
