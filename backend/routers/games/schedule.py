"""routers/games/schedule.py — schedule-dates and NFL schedule-week endpoints."""
import datetime as dt

from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from . import router


def _db():
    """Resolve `routers.games._db` at call time (see scoreboard.py `_db`)."""
    from routers.games import _db as _pkg_db
    return _pkg_db()


def _pkg_local_event_starts(league, anchor, direction):
    """Resolve `routers.games._local_event_starts` at call time.

    Tests patch the package attribute (`patch.object(games,
    "_local_event_starts", ...)`) before calling `get_schedule_dates`, so the
    call must read through the package namespace, not the module-local binding.
    """
    from routers.games import _local_event_starts as _pkg_les
    return _pkg_les(league, anchor, direction)


_SCHEDULE_DATES_CONTRACT = "league-schedule-dates-v1"
_NFL_SCHEDULE_WEEKS_CONTRACT = "nfl-schedule-weeks-v1"
_NFL_SCHEDULE_WEEK_CONTRACT = "nfl-schedule-week-v1"
_SCHEDULE_SEARCH_RANGES = {
    # Keep every ESPN range comfortably below its 1,000-event response cap.
    # A full NBA season in one 280-day request can otherwise truncate before
    # the games nearest the anchor (especially when searching backwards).
    "future": (
        (0, 14),
        (15, 45),
        (46, 90),
        (91, 150),
        (151, 210),
        (211, 270),
        (271, 330),
        (331, 370),
    ),
    "past": (
        (-14, -1),
        (-45, -15),
        (-90, -46),
        (-150, -91),
        (-210, -151),
        (-270, -211),
        (-330, -271),
        (-370, -331),
    ),
}
_SCHEDULE_CANDIDATE_LIMIT = 64
_MIN_VIEWER_OFFSET = dt.timezone(dt.timedelta(hours=-12))
_MAX_VIEWER_OFFSET = dt.timezone(dt.timedelta(hours=14))


def _parse_anchor_date(anchor: Optional[str]) -> dt.date:
    if anchor is None:
        return dt.date.today()
    try:
        parsed = dt.date.fromisoformat(anchor)
    except (TypeError, ValueError):
        raise HTTPException(400, "anchor must be YYYY-MM-DD")
    if parsed.isoformat() != anchor:
        raise HTTPException(400, "anchor must be YYYY-MM-DD")
    return parsed


def _default_nfl_season(anchor: dt.date) -> int:
    return anchor.year - 1 if anchor.month <= 2 else anchor.year


def _flatten_nfl_weeks(phases):
    return [week for phase in phases for week in phase.get("weeks", [])]


def _default_nfl_week(weeks, anchor: dt.date):
    if not weeks:
        return None, "none"
    anchor_text = anchor.isoformat()
    starts = [str(week.get("start_time") or "")[:10] for week in weeks]
    if anchor_text < starts[0]:
        return weeks[0], "next"
    for index, week in enumerate(weeks):
        next_start = starts[index + 1] if index + 1 < len(starts) else None
        if next_start is not None and anchor_text < next_start:
            return week, "current"
        if next_start is None:
            end_text = str(week.get("end_time") or "")[:10]
            return week, "current" if anchor_text <= end_text else "latest"
    return weeks[-1], "latest"


def _event_start(value):
    """Parse an absolute ESPN start time, returning ``None`` for junk."""
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _is_guaranteed_directional_start(value, anchor: dt.date, direction: str):
    """Whether every real viewer timezone places ``value`` past the anchor.

    The browser remains authoritative for its local calendar. This conservative
    check only tells the backend when it has searched far enough: a future start
    must still be after ``anchor`` at UTC-12, while a past start must already be
    before it at UTC+14. Boundary starts are retained for the browser but do not
    prematurely stop discovery.
    """
    parsed = _event_start(value)
    if parsed is None:
        return False
    if direction == "future":
        return parsed.astimezone(_MIN_VIEWER_OFFSET).date() > anchor
    return parsed.astimezone(_MAX_VIEWER_OFFSET).date() < anchor


def _cap_schedule_candidates(starts, anchor: dt.date, direction: str):
    ordered = sorted(set(starts))
    if len(ordered) <= _SCHEDULE_CANDIDATE_LIMIT:
        return ordered

    guaranteed = [
        value
        for value in ordered
        if _is_guaranteed_directional_start(value, anchor, direction)
    ]
    if direction == "future":
        selected = ordered[:_SCHEDULE_CANDIDATE_LIMIT]
        if guaranteed and not any(value in selected for value in guaranteed):
            selected[-1] = guaranteed[0]
    else:
        selected = ordered[-_SCHEDULE_CANDIDATE_LIMIT:]
        if guaranteed and not any(value in selected for value in guaranteed):
            selected[0] = guaranteed[-1]
    return sorted(set(selected))


def _local_event_starts(league: str, anchor: dt.date, direction: str):
    """Event start instants we already hold, for the day arrows.

    The board's ``‹`` and ``›`` asked ESPN on every click, so when the host
    refused, the arrow silently did nothing and the board simply would not move
    past a certain day. Measured 2026-08-18: `schedule-dates` returned
    `source: unavailable` with a 403 for every league, and going back before
    Sunday was impossible -- with UFC 330 sitting in our own database the whole
    time.

    Only sources carrying a real INSTANT are read. `team_game_results` is day
    precision on purpose, and turning `2026-08-16` into midnight UTC would move
    the event onto the previous local day throughout the Americas, which is the
    same mistake `_games_from_db` refuses to make. The contract promises
    instants and the browser converts them, so a fabricated one is worse than a
    missing one.
    """
    horizon = dt.timedelta(days=370)
    if direction == "past":
        low, high = anchor - horizon, anchor + dt.timedelta(days=1)
    else:
        low, high = anchor - dt.timedelta(days=1), anchor + horizon
    try:
        with closing(_db()) as con:
            rows = con.execute(
                "SELECT start_time FROM scoreboard_snapshots"
                "  WHERE league=? AND start_time IS NOT NULL"
                "        AND substr(start_time,1,10) BETWEEN ? AND ?"
                " UNION"
                " SELECT start_time FROM prop_games"
                "  WHERE league=? AND start_time IS NOT NULL"
                "        AND substr(start_time,1,10) BETWEEN ? AND ?",
                (league, low.isoformat(), high.isoformat(),
                 league, low.isoformat(), high.isoformat()),
            ).fetchall()
    except sqlite3.Error as exc:
        print(f"[schedule-dates] local starts unavailable league={league}: "
              f"{type(exc).__name__}: {exc}")
        return []
    return sorted({str(row[0]) for row in rows if row[0]})


def _schedule_candidates(league: str, anchor: dt.date, direction: str):
    attempts = []
    candidates = []
    for start_delta, end_delta in _SCHEDULE_SEARCH_RANGES[direction]:
        start_date = anchor + dt.timedelta(days=start_delta)
        end_date = anchor + dt.timedelta(days=end_delta)
        starts = espn.schedule_event_starts(league, start_date, end_date)
        candidates.extend(starts)
        attempts.append({
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "event_starts_found": len(starts),
        })
        if any(
            _is_guaranteed_directional_start(value, anchor, direction)
            for value in starts
        ):
            break
    return _cap_schedule_candidates(candidates, anchor, direction), attempts


@router.get("/api/{league}/schedule-dates")
def get_schedule_dates(
    league: str,
    anchor: Optional[str] = Query(None, description="Viewer-local YYYY-MM-DD"),
):
    """Bounded event-start candidates for resolving an empty schedule day.

    Event starts stay as absolute ISO instants. The browser converts them to
    its own local calendar before choosing the nearest future date or, when no
    future event exists in the verified horizon, the most recent past date.
    """
    lg = league.lower()
    if lg not in espn.LEAGUES:
        raise HTTPException(404, f"unsupported league {lg!r}")
    anchor_date = _parse_anchor_date(anchor)

    # Answer from what we hold before asking the publisher. Each arrow click used
    # to cost an ESPN request per league, so the navigation had exactly the
    # disease the board just had: a cost that scales with user traffic, and a
    # dead end the moment the host refuses. A direction we can already answer is
    # answered for free; one we cannot still asks.
    local_future = _pkg_local_event_starts(lg, anchor_date, "future")
    local_past = _pkg_local_event_starts(lg, anchor_date, "past")

    # A finished day never needs a SECOND request -- but "we already hold it"
    # and "we never captured it" are different states, and treating them alike
    # is what killed the arrow. This previously took past candidates from the
    # local store ONLY, so a league whose history we had never stored (every
    # league before this store existed, and every out-of-season one) had no
    # past dates at all and the arrow was permanently dead in that direction.
    # We hold it: free. We do not: ask once, and the schedule window for a day
    # that is over is immutable, so `paced_http`'s disk cache answers every
    # later click for nothing.
    past_starts = _cap_schedule_candidates(local_past, anchor_date, "past")

    if local_future and past_starts:
        return JSONResponse(
            content={
                "contract": _SCHEDULE_DATES_CONTRACT,
                "league": lg,
                "anchor_date": anchor_date.isoformat(),
                "event_start_timezone": "UTC",
                "available": True,
                "source": "local",
                "future_event_starts": _cap_schedule_candidates(
                    local_future, anchor_date, "future"),
                "past_event_starts": past_starts,
                "search": {"future": [], "past": [], "max_horizon_days": 370},
            },
            headers={"Cache-Control": "public, max-age=60"},
        )

    try:
        if local_future:
            future_starts, future_search = _cap_schedule_candidates(
                local_future, anchor_date, "future"), []
        else:
            future_starts, future_search = _schedule_candidates(
                lg, anchor_date, "future")
        past_search = []
        if not past_starts:
            past_starts, past_search = _schedule_candidates(lg, anchor_date, "past")
    except Exception as exc:
        print(
            f"[schedule-dates] publisher unavailable league={lg} "
            f"anchor={anchor_date.isoformat()} error={type(exc).__name__}: {exc}"
        )
        # A refusal is not a reason to answer with nothing when we hold half the
        # answer. Whatever direction we can serve locally is served, and the
        # response still says the publisher was unavailable so a caller can tell
        # a partial answer from a complete one.
        have_local = bool(past_starts)
        return JSONResponse(
            content={
                "contract": _SCHEDULE_DATES_CONTRACT,
                "league": lg,
                "anchor_date": anchor_date.isoformat(),
                "event_start_timezone": "UTC",
                "available": have_local,
                "source": "local" if have_local else "unavailable",
                "error": "publisher_unavailable",
                "future_event_starts": [],
                "past_event_starts": past_starts,
                "search": {
                    "future": [],
                    "past": [],
                    "max_horizon_days": 370,
                },
            },
            headers={"Cache-Control": "public, max-age=15"},
        )

    return JSONResponse(
        content={
            "contract": _SCHEDULE_DATES_CONTRACT,
            "league": lg,
            "anchor_date": anchor_date.isoformat(),
            "event_start_timezone": "UTC",
            "available": True,
            # Whichever rung answered. "local" only when BOTH directions came
            # from the store, because a payload that names one source while
            # half of it came from another is a claim we cannot support.
            "source": "local" if (local_future and not past_search) else "espn",
            "future_event_starts": future_starts,
            "past_event_starts": past_starts,
            "search": {
                "future": future_search,
                "past": past_search,
                "max_horizon_days": 370,
            },
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/api/nfl/schedule-weeks")
def get_nfl_schedule_weeks(
    season: Optional[int] = Query(None, ge=2000, le=2100),
    anchor: Optional[str] = Query(None, description="Viewer-local YYYY-MM-DD"),
):
    """ESPN's ordered NFL phase/week catalog and the default week for an anchor date."""
    anchor_date = _parse_anchor_date(anchor)
    selected_season = season if season is not None else _default_nfl_season(anchor_date)
    if selected_season < 2000 or selected_season > 2100:
        raise HTTPException(400, "season must be between 2000 and 2100")
    try:
        phases = espn.nfl_schedule_weeks(selected_season)
    except (TypeError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "NFL schedule week catalog unavailable") from exc

    weeks = _flatten_nfl_weeks(phases)
    default_week, default_reason = _default_nfl_week(weeks, anchor_date)
    if default_week is None:
        raise HTTPException(502, "NFL schedule week catalog is empty")
    return JSONResponse(
        content={
            "contract": _NFL_SCHEDULE_WEEKS_CONTRACT,
            "league": "nfl",
            "season": selected_season,
            "anchor_date": anchor_date.isoformat(),
            "navigation": "week",
            "phases": phases,
            "weeks": weeks,
            "default_week_key": default_week["key"],
            "default_reason": default_reason,
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/api/nfl/schedule-week")
def get_nfl_schedule_week(
    season: int = Query(..., ge=2000, le=2100),
    season_type: int = Query(..., ge=1, le=3),
    week: int = Query(..., ge=1, le=25),
):
    """One NFL week of games, keyed by ESPN season type and week number."""
    if season < 2000 or season > 2100:
        raise HTTPException(400, "season must be between 2000 and 2100")
    if season_type not in (1, 2, 3):
        raise HTTPException(400, "season_type must be 1, 2, or 3")
    if week < 1 or week > 25:
        raise HTTPException(400, "week must be between 1 and 25")
    try:
        phases = espn.nfl_schedule_weeks(season)
    except (TypeError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "NFL schedule week catalog unavailable") from exc

    selected = next(
        (
            candidate
            for candidate in _flatten_nfl_weeks(phases)
            if candidate["season_type"] == season_type and candidate["week"] == week
        ),
        None,
    )
    if selected is None:
        raise HTTPException(404, "NFL schedule week not found")
    try:
        week_games = espn.nfl_schedule_week_games(season, season_type, week)
    except Exception as exc:
        raise HTTPException(502, "NFL schedule week games unavailable") from exc

    return JSONResponse(
        content={
            "contract": _NFL_SCHEDULE_WEEK_CONTRACT,
            "league": "nfl",
            "season": season,
            "navigation": "week",
            "selected_week": selected,
            "games": week_games,
        },
        headers={"Cache-Control": "public, max-age=20"},
    )
