"""Game lifecycle for the NCAAF forecasting operation: pure rules, no I/O.

Three separate statuses are tracked for every game, and none is inferred from another:

  game status     what ESPN's own status fields say the event is (lifecycle below)
  grading status  pending | graded | void | quarantined | unresolved (see store.fbs_game_status)
  lock status     whether a verified pregame lock exists for each model (fbs_forecasts)

Lifecycle classes come only from ESPN's status type name and its own completion flag. A missing,
unmapped or contradictory status is `unknown`. An absent event is never read as cancelled or as
completed, and a play-by-play row is never read as a final score.
"""
from __future__ import annotations

import datetime as dt

LIFECYCLES = ("scheduled", "in_progress", "delayed", "suspended", "postponed", "completed",
              "cancelled", "abandoned", "forfeit", "no_contest", "unknown")

# ESPN status type names mapped to a lifecycle class. Any other name is unknown.
_ESPN_STATUS = {
    "STATUS_SCHEDULED": "scheduled",
    "STATUS_IN_PROGRESS": "in_progress",
    "STATUS_HALFTIME": "in_progress",
    "STATUS_END_PERIOD": "in_progress",
    "STATUS_DELAYED": "delayed",
    "STATUS_SUSPENDED": "suspended",
    "STATUS_POSTPONED": "postponed",
    "STATUS_FINAL": "completed",
    "STATUS_CANCELED": "cancelled",
    "STATUS_CANCELLED": "cancelled",
    "STATUS_ABANDONED": "abandoned",
    "STATUS_FORFEIT": "forfeit",
    "STATUS_NO_CONTEST": "no_contest",
}

# Terminal classes where no ordinary final result exists. They are voids, never win or loss.
VOID_LIFECYCLES = frozenset({"cancelled", "abandoned", "forfeit", "no_contest"})
# Classes that suspend new locks and grades while the schedule is unresolved.
HOLD_LIFECYCLES = frozenset({"delayed", "suspended", "postponed"})
# Classes that do not count as a missed T-90 window: there was no eligible window to miss.
NO_WINDOW_LIFECYCLES = HOLD_LIFECYCLES | VOID_LIFECYCLES

RETRY_BASE = dt.timedelta(minutes=15)
RETRY_CAP = dt.timedelta(hours=6)
ALERT_AFTER = dt.timedelta(hours=24)


def classify_status(status_name: str | None, completed: bool | None) -> str:
    """Lifecycle class for one ESPN event, from its status type name and completion flag only."""
    if not status_name:
        return "unknown"
    lifecycle = _ESPN_STATUS.get(str(status_name).upper(), "unknown")
    if lifecycle == "completed" and completed is not True:
        return "unknown"           # ESPN contradicts itself: name says final, flag says not
    if lifecycle == "scheduled" and completed is True:
        return "unknown"
    return lifecycle


def is_gradeable(lifecycle: str, home_score, away_score) -> bool:
    """A result may be graded only when ESPN reports completed with both final scores."""
    return lifecycle == "completed" and home_score is not None and away_score is not None


def is_lockable(lifecycle: str, kickoff: dt.datetime, now: dt.datetime) -> bool:
    """Only a scheduled game that has not started can take a lock. Started events never lock."""
    return lifecycle == "scheduled" and now < kickoff


def next_attempt(attempts: int, now: dt.datetime) -> dt.datetime:
    """Bounded exponential backoff for an unresolved game. Attempts beyond the cap stay at the cap."""
    delay = RETRY_BASE * (2 ** min(max(attempts, 0), 16))
    return now + min(delay, RETRY_CAP)


def alert_due(kickoff: dt.datetime, now: dt.datetime) -> bool:
    return now >= kickoff + ALERT_AFTER


def eastern_dates(kickoff: dt.datetime) -> list[str]:
    """Scoreboard dates to try for one game: its Eastern date, then the day before and after.

    ESPN files a game under its Eastern date. A kickoff just after midnight UTC belongs to the
    previous Eastern date, so a reschedule must not lose it. Duplicates are removed, order kept.
    """
    import pytz
    eastern = pytz.timezone("America/New_York")
    local = kickoff.astimezone(eastern).date()
    dates = [local, local - dt.timedelta(days=1), local + dt.timedelta(days=1)]
    seen, out = set(), []
    for day in dates:
        text = day.strftime("%Y%m%d")
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out
