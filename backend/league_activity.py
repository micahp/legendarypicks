#!/usr/bin/env python3
"""Which leagues are actually playing on a given date, from ESPN's own calendar.

The scoreboard board fans out over twelve leagues. Eleven of them are ESPN
backed, so one cold `/scores` load cost **22 upstream requests** (11 leagues x
the viewer's today and tomorrow) no matter how many of those leagues were in
season. On 2026-08-18 that included the FIFA World Cup, whose final was played
on 2026-07-19, and the NHL, whose season ended 2026-07-01. Asking a publisher
about a league that is months out of season is a request spent to be told
nothing, and ESPN's limit is a request COUNT per host.

**Every scoreboard payload already carries the answer.** `leagues[0].calendar`
is published on every response we were already fetching, so knowing when a
league plays costs nothing extra: it arrives inside the fetch that we do anyway,
and is recorded here.

## The two shapes, and why only one of them can say "no"

ESPN publishes the calendar two ways, named by `calendarType`:

`list`  Phase windows with start and end dates: NFL, NCAAF, Leagues Cup, the
        World Cup; and for UFC, one block per event. These are precise and are
        used as the gate directly. Measured 2026-08-18:

            NFL           Preseason Week 1   2026-08-13 .. 2026-08-20   playing
            Leagues Cup   Quarterfinals      2026-08-17 .. 2026-09-01   playing
            NCAAF         Regular Season     2026-08-22 .. 2026-12-13   not yet
            World Cup     Final              2026-07-19 .. 2026-08-01   over

        Leagues Cup is the reason this is read rather than guessed: its League
        Phase ended 2026-08-13 and it looks finished, but the publisher says
        the quarterfinals run to 2026-09-01. A hand-written "soccer is done in
        August" would have dropped a live league.

`day`   A list of dates. It looks like the game-day list and **is not one**.
        MLB's has 20 entries and does not contain 2026-08-18, a day MLB played
        15 games; the long ones (NHL 226, ATP 256, WTA 272) do look like game
        days. So a `day` calendar is a positive signal we cannot verify and is
        never used to refuse: those leagues are gated on the season window
        (`season.startDate .. season.endDate`) alone, which is correct and
        coarse. It still retires NBA (ended 2026-06-27) and NHL (2026-07-01).

## Off season is read from the published encoding, not from the word

`value` on a `list` block is ESPN's season type id, and **4 is the off season**
(measured: NFL publishes `value 4, label "Off Season", entries 0`). Blocks are
excluded on that id, never on the label. Where a block carries entries, the
entries are the windows, since they are the finer published truth; where it
carries none (UFC, where the block IS the event) the block is the window.

## Refusing to ask is a claim, so it fails open

A league with no recorded calendar is treated as playing. A gap here must cost
a request, never a silently empty board: [[reference_lp_five_defect_shapes]]
shape 1. And a league we have stopped asking is re-checked once every
`RECHECK_HOURS`, because the only way a new season becomes visible is to ask.
"""
import datetime as dt
import json
import os
import sqlite3
from contextlib import closing

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# ESPN season type 4. The id, not the label -- a trust decision keyed on a name
# is one bad string away from being wrong ([[feedback_trust_lists_never_keyed_on_name_alone]]).
OFF_SEASON_TYPE = "4"

# A window is compared against a calendar date, but it is published as a UTC
# instant, and a game at 19:40 local on the 18th is the 19th in UTC. One day of
# padding on each side keeps that from retiring a league a day early. The
# windows are weeks long, so a day of slack costs at most one request.
WINDOW_PAD = dt.timedelta(days=1)

# How long a league we are not asking stays unasked. A season that starts
# tomorrow is published today, but only to whoever asks.
RECHECK_HOURS = 24

SCHEMA = """
CREATE TABLE IF NOT EXISTS league_activity(
  league        TEXT PRIMARY KEY,
  calendar_type TEXT,
  season_start  TEXT,
  season_end    TEXT,
  windows       TEXT,           -- JSON [[start_date, end_date], ...]
  fetched_at    TEXT,           -- when the payload this was parsed from arrived
  checked_at    TEXT            -- when we last asked at all, even if empty
)
"""


def _db_path():
    """Resolved per call, not bound at import.

    The suite points LP_DB_PATH at a throwaway file and `conftest.py` restores
    it between tests, so a path captured at import time is whichever module
    happened to import this one first. It is also how a dev run and a prod run
    of the same ingest stay told apart.
    """
    return os.environ.get("LP_DB_PATH") or DB


def _db():
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    return con


def init(con=None):
    if con is not None:
        con.executescript(SCHEMA)
        return
    with closing(_db()) as own:
        own.executescript(SCHEMA)
        own.commit()


def _day(value):
    """The calendar day of an ISO instant, or None. Never raises on junk."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def windows_from_payload(payload):
    """Parse `leagues[0]` into (calendar_type, season_start, season_end, windows).

    `windows` is a list of (start_date, end_date) day pairs the league publishes
    itself as playing. It is empty for a `day` calendar, where the season window
    is the only usable gate -- see the module docstring on MLB.
    """
    leagues = (payload or {}).get("leagues") or []
    if not leagues:
        return None
    league = leagues[0] or {}
    season = league.get("season") or {}
    cal_type = league.get("calendarType") or ""
    season_start = _day(season.get("startDate"))
    season_end = _day(season.get("endDate"))

    windows = []
    if cal_type == "list":
        for block in league.get("calendar") or []:
            if not isinstance(block, dict):
                continue
            if str(block.get("value") or "") == OFF_SEASON_TYPE:
                continue
            entries = [e for e in (block.get("entries") or []) if isinstance(e, dict)]
            # Entries are the finer published truth; a block with none is itself
            # the window (UFC publishes one block per event).
            for source in (entries or [block]):
                start = _day(source.get("startDate"))
                end = _day(source.get("endDate")) or start
                if start:
                    windows.append((start, end or start))
    return cal_type, season_start, season_end, windows


def record_from_payload(league, payload, con=None):
    """Store what a scoreboard payload says about when this league plays.

    Called from the ingest with a payload it fetched anyway, so this costs no
    request of its own. Returns True when something was recorded.
    """
    parsed = windows_from_payload(payload)
    if not parsed:
        return False
    cal_type, season_start, season_end, windows = parsed
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    row = (
        league.lower(), cal_type,
        season_start.isoformat() if season_start else None,
        season_end.isoformat() if season_end else None,
        json.dumps([[s.isoformat(), e.isoformat()] for s, e in windows]),
        now, now,
    )
    own = con is None
    con = con or _db()
    try:
        init(con)
        con.execute(
            "INSERT INTO league_activity"
            " (league, calendar_type, season_start, season_end, windows, fetched_at, checked_at)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(league) DO UPDATE SET"
            "   calendar_type=excluded.calendar_type,"
            "   season_start=excluded.season_start,"
            "   season_end=excluded.season_end,"
            "   windows=excluded.windows,"
            "   fetched_at=excluded.fetched_at,"
            "   checked_at=excluded.checked_at",
            row,
        )
        if own:
            con.commit()
    finally:
        if own:
            con.close()
    return True


def touch(league, con=None):
    """Record that we asked, whatever the answer.

    A league whose payload carried no calendar still must not be re-asked every
    cycle, or an unparseable response becomes an unbounded request source.
    """
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    own = con is None
    con = con or _db()
    try:
        init(con)
        con.execute(
            "INSERT INTO league_activity (league, checked_at) VALUES (?,?)"
            " ON CONFLICT(league) DO UPDATE SET checked_at=excluded.checked_at",
            (league.lower(), now),
        )
        if own:
            con.commit()
    finally:
        if own:
            con.close()


def _read(league, con=None):
    own = con is None
    con = con or _db()
    try:
        init(con)
        return con.execute(
            "SELECT * FROM league_activity WHERE league=?", (league.lower(),)
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        if own:
            con.close()


def plays_on(league, date, con=None):
    """True / False / None for "does `league` publish play on `date`".

    None means we have never recorded a calendar for it. That is not a no:
    the caller must ask the publisher rather than serve an empty board.
    """
    row = _read(league, con)
    if row is None or row["calendar_type"] is None:
        return None
    if isinstance(date, str):
        date = dt.date.fromisoformat(date)

    windows = []
    try:
        windows = [(dt.date.fromisoformat(s), dt.date.fromisoformat(e))
                   for s, e in json.loads(row["windows"] or "[]")]
    except (ValueError, TypeError):
        windows = []

    if windows:
        return any(start - WINDOW_PAD <= date <= end + WINDOW_PAD
                   for start, end in windows)

    # `day` calendar, or a `list` one that published no usable block: the season
    # envelope is the only gate we can trust. See the module docstring.
    start = _day(row["season_start"])
    end = _day(row["season_end"])
    if not start or not end:
        return None
    return start - WINDOW_PAD <= date <= end + WINDOW_PAD


def stale(league, hours=RECHECK_HOURS, con=None):
    """Has it been long enough to ask a dormant league again?"""
    row = _read(league, con)
    if row is None or not row["checked_at"]:
        return True
    try:
        checked = dt.datetime.fromisoformat(row["checked_at"])
    except ValueError:
        return True
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - checked) >= dt.timedelta(hours=hours)


def plan(leagues, dates, con=None):
    """Split `leagues` into what to ask about `dates` and what to skip, with reasons.

    Returns (ask, skip) where `ask` is a list of (league, date) and `skip` is a
    list of (league, reason). Every skip carries the published reason it was
    skipped, because "we did not ask" and "there were no games" are different
    claims and only one of them is the publisher's.
    """
    own = con is None
    con = con or _db()
    try:
        init(con)
        ask, skip = [], []
        for league in leagues:
            verdicts = {d: plays_on(league, d, con) for d in dates}
            if any(v is None for v in verdicts.values()):
                ask.extend((league, d) for d in dates)
                continue
            playing = [d for d, v in verdicts.items() if v]
            if playing:
                ask.extend((league, d) for d in playing)
                for d in dates:
                    if d not in playing:
                        skip.append((league, f"{d}: outside a published window"))
                continue
            if stale(league, con=con):
                # Dormant, but not asked in RECHECK_HOURS. One request is what a
                # newly published season costs.
                ask.append((league, dates[0]))
                skip.extend((league, f"{d}: dormant, re-checking") for d in dates[1:])
            else:
                skip.extend((league, f"{d}: out of season") for d in dates)
        return ask, skip
    finally:
        if own:
            con.close()


def report(leagues, dates, con=None):
    """Human readable plan. Used by --dry-run and by the ingest's own log line."""
    ask, skip = plan(leagues, dates, con)
    lines = [f"asking {len(ask)} of {len(leagues) * len(dates)} (league, date) pairs"]
    for league, date in ask:
        lines.append(f"  ASK   {league:6} {date}")
    for league, reason in skip:
        lines.append(f"  skip  {league:6} {reason}")
    return "\n".join(lines)
