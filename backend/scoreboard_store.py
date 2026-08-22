#!/usr/bin/env python3
"""The scoreboard we last read from a publisher, so serving a page costs nothing.

Before this, `/api/{league}/games` called ESPN on every request. A cold `/scores`
load fanned out to 22 upstream requests (11 ESPN leagues x the viewer's today and
tomorrow), and `espn_client`'s Fetcher carries the process-wide per-host budget --
100 requests, then `time.sleep(60)`. That is a batch job's behaviour running
inside the serving process: measured 2026-08-18 on prod, 46 minutes of uptime and
almost no traffic produced **46 sixty-second pauses**, 38 of them inside a seven
second window, because the budget check is unguarded and every caller in flight
sleeps its own minute when the process crosses the ceiling. The board did not
break because ESPN refused us. It broke because we stalled ourselves, and the
cost of a page view scaled with our own traffic.

So publisher traffic is decoupled from user traffic. A timer writes here; the
serving path only reads. Page load becomes SQLite, and the upstream spend becomes
a constant nobody can push up by opening more tabs.

## What is stored, and what is not claimed

One row per game, holding the normalized shape the API already serves, plus:

  `fetched_at`  when the publisher told us this. Returned to the caller as an
                age, because a score with no age is a claim about now that we
                cannot support ([[feedback_stale_data_looks_clean]]).
  `start_time`  so the live poller can find the games that are under way
                without parsing every payload.

`scoreboard_refresh` records that a (league, date) was asked at all, separately
from what came back. "We fetched and the publisher published nothing" and "we
never asked" are different claims, and only the first is the publisher's. A read
of a day we never fetched returns None, and the caller falls through to the live
ladder rather than serving an empty board.
"""
import datetime as dt
import json
import os
import sqlite3
from contextlib import closing

from espn_client.scoreboard import _slate_day
from history_refresh_common import BUSY_TIMEOUT_SECONDS
from publisher_capture import capture_payload, require_publisher_capture_schema

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# A game still not final this long after its published start is not a live game
# any more, it is a row nobody closed out. Polling it forever would make a stuck
# state into a permanent request source.
LIVE_TAIL = dt.timedelta(hours=12)

# How long a (league, date) that published no games at all stays unasked. A day
# with no slate does not sprout one in ten minutes, but a postponement or a late
# addition is real, so this backs off rather than giving up.
EMPTY_BACKOFF = dt.timedelta(hours=3)

SCHEMA = """
CREATE TABLE IF NOT EXISTS scoreboard_snapshots(
  league     TEXT NOT NULL,
  game_date  TEXT NOT NULL,
  game_id    TEXT NOT NULL,
  payload    TEXT NOT NULL,
  state      TEXT,
  start_time TEXT,
  fetched_at TEXT NOT NULL,
  source     TEXT,
  PRIMARY KEY(league, game_date, game_id)
);
CREATE INDEX IF NOT EXISTS idx_scoreboard_live
  ON scoreboard_snapshots(state, start_time);
CREATE TABLE IF NOT EXISTS scoreboard_refresh(
  league     TEXT NOT NULL,
  game_date  TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  game_count INTEGER NOT NULL,
  source     TEXT,
  PRIMARY KEY(league, game_date)
);
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
    # This store writes `scoreboard_snapshots` every minute, so it is one half of the
    # contention that made prod's props ingest 500 with `database is locked`. See the
    # note in `_core._db`: the 5s SQLite default is what gave up.
    con = sqlite3.connect(_db_path(), timeout=BUSY_TIMEOUT_SECONDS)
    con.row_factory = sqlite3.Row
    return con


def init(con=None):
    if con is not None:
        con.executescript(SCHEMA)
        return
    with closing(_db()) as own:
        own.executescript(SCHEMA)
        own.commit()


def require_capture_schema():
    """Fail before an ingest request when the raw ledger is unavailable."""
    with closing(_db()) as con:
        require_publisher_capture_schema(con)


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(moment):
    return moment.isoformat(timespec="seconds")


def _today_for(league):
    """Today, on the same clock `game_date` is keyed by.

    This used to be `_now().date()`, the UTC date, compared against a
    `game_date` that is the America/New_York slate day for every league except
    tennis. The UTC date rolls over at 20:00 ET, so for the four hours from
    8pm to midnight Eastern -- prime time -- tonight's slate compared as
    STRICTLY LESS THAN today and the store answered "day is over and published
    no games". An empty slate that gained a late addition in that window could
    never pick it up, because the backoff that exists for exactly that case was
    skipped.

    `_slate_day` is the same function that decides `game_date`, so this asks the
    question on one ruler. It is league-aware on purpose: tennis buckets by UTC
    and must keep doing so.
    """
    now = _now()
    return _slate_day(league, _iso(now)) or now.date().isoformat()


def _normalize_start(value):
    """A stored start time must be comparable to `_iso(now)` as a string.

    Publishers hand us `2026-08-18T22:35Z`; `datetime.isoformat` writes
    `2026-08-18T22:35:00+00:00`. Those sort correctly against each other only as
    far as the minute, and the live query is a string range -- so the value is
    normalized once here rather than trusted to compare. A date-only value (the
    DB result path publishes day precision deliberately) has no instant and is
    stored as None, so it can never be mistaken for a game that has started.
    """
    if not value:
        return None
    text = str(value)
    if len(text) <= 10:
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return _iso(moment.astimezone(dt.timezone.utc))


def save(league, game_date, games, source="espn", con=None, source_payload=None):
    """Replace the stored slate for one (league, date). Returns rows written.

    `source_payload`, when supplied, is ``(endpoint, native_body)`` and is
    retained before any normalized rows in this same transaction. The day is
    replaced, not merged: a game the publisher has dropped (a
    postponement, a schedule correction) must disappear from our board too, and
    an upsert alone would leave it there forever.
    """
    league = league.lower()
    fetched_at = _iso(_now())
    own = con is None
    con = con or _db()
    try:
        init(con)
        if source_payload is not None:
            endpoint, payload = source_payload
            require_publisher_capture_schema(con)
            capture_payload(
                con, source=source, league=league, endpoint=endpoint,
                payload=payload, captured_at=fetched_at,
            )
        keep = []
        for game in games or []:
            game_id = str(game.get("game_id") or "")
            if not game_id:
                # Without an id there is nothing to key on, and inventing one
                # would make the same game arrive twice on the next refresh.
                continue
            keep.append(game_id)
            con.execute(
                "INSERT INTO scoreboard_snapshots"
                " (league, game_date, game_id, payload, state, start_time, fetched_at, source)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(league, game_date, game_id) DO UPDATE SET"
                "   payload=excluded.payload, state=excluded.state,"
                "   start_time=excluded.start_time, fetched_at=excluded.fetched_at,"
                "   source=excluded.source",
                (league, game_date, game_id, json.dumps(game),
                 game.get("state"), _normalize_start(game.get("date")),
                 fetched_at, source),
            )
        if keep:
            marks = ",".join("?" * len(keep))
            con.execute(
                f"DELETE FROM scoreboard_snapshots WHERE league=? AND game_date=?"
                f" AND game_id NOT IN ({marks})",
                [league, game_date] + keep,
            )
        else:
            con.execute(
                "DELETE FROM scoreboard_snapshots WHERE league=? AND game_date=?",
                (league, game_date),
            )
        con.execute(
            "INSERT INTO scoreboard_refresh (league, game_date, fetched_at, game_count, source)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(league, game_date) DO UPDATE SET"
            "   fetched_at=excluded.fetched_at, game_count=excluded.game_count,"
            "   source=excluded.source",
            (league, game_date, fetched_at, len(keep), source),
        )
        if own:
            con.commit()
        return len(keep)
    finally:
        if own:
            con.close()


def read(league, game_date, con=None):
    """The stored slate, or None if this (league, date) was never fetched.

    None is not an empty slate. A caller that cannot tell the difference will
    serve a blank board for a day nobody ever asked about.
    """
    league = league.lower()
    own = con is None
    con = con or _db()
    try:
        init(con)
        refresh = con.execute(
            "SELECT fetched_at, game_count, source FROM scoreboard_refresh"
            " WHERE league=? AND game_date=?",
            (league, game_date),
        ).fetchone()
        if refresh is None:
            return None
        rows = con.execute(
            "SELECT payload, fetched_at FROM scoreboard_snapshots"
            " WHERE league=? AND game_date=? ORDER BY start_time, game_id",
            (league, game_date),
        ).fetchall()
        games = []
        for row in rows:
            try:
                games.append(json.loads(row["payload"]))
            except (ValueError, TypeError):
                continue
        fetched_at = refresh["fetched_at"]
        try:
            moment = dt.datetime.fromisoformat(fetched_at)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=dt.timezone.utc)
            age = int((_now() - moment).total_seconds())
        except (ValueError, TypeError):
            age = None
        return {
            "games": games,
            "fetched_at": fetched_at,
            "age_seconds": age,
            "source": refresh["source"],
        }
    except sqlite3.Error as exc:
        print(f"[scoreboard_store] read failed league={league} date={game_date}: "
              f"{type(exc).__name__}: {exc}")
        return None
    finally:
        if own:
            con.close()


def live_targets(now=None, con=None):
    """(league, game_date) pairs holding a game that has started and is not final.

    This is what the live poller refreshes, and it is the whole reason polling
    is cheap: on a quiet morning it returns nothing and the poller spends zero
    requests, while during a slate it returns the one or two leagues actually
    playing rather than all eleven.
    """
    now = now or _now()
    floor = _iso(now - LIVE_TAIL)
    ceiling = _iso(now)
    own = con is None
    con = con or _db()
    try:
        init(con)
        rows = con.execute(
            "SELECT DISTINCT league, game_date FROM scoreboard_snapshots"
            " WHERE (state IS NULL OR state != 'post')"
            "   AND league != 'wc'"
            "   AND start_time IS NOT NULL"
            "   AND start_time <= ? AND start_time >= ?"
            " ORDER BY league, game_date",
            (ceiling, floor),
        ).fetchall()
        return [(row["league"], row["game_date"]) for row in rows]
    except sqlite3.Error as exc:
        print(f"[scoreboard_store] live_targets failed: {type(exc).__name__}: {exc}")
        return []
    finally:
        if own:
            con.close()


def needs_refresh(league, game_date, empty_backoff=EMPTY_BACKOFF, con=None):
    """Should the schedule run spend a request on this (league, date)?

    Being in season is not the same as having something new to say. Three cases
    the publisher has already answered, so re-asking buys nothing:

      never fetched      ask, always. A gap must cost a request, not a blank board.
      published nothing  a slate that came back empty is not going to fill in
                         within minutes. Backed off, but not abandoned -- a
                         postponement or a late addition still lands within
                         `empty_backoff`.
      every game final   nothing about a finished day can change. Yesterday's
                         board is fetched once and then never again.

    Returns (True/False, reason). The reason is printed, because a skipped
    request is a decision and an unexplained one is indistinguishable from a bug.
    """
    league = league.lower()
    own = con is None
    con = con or _db()
    try:
        init(con)
        refresh = con.execute(
            "SELECT fetched_at, game_count FROM scoreboard_refresh"
            " WHERE league=? AND game_date=?",
            (league, game_date),
        ).fetchone()
        if refresh is None:
            return True, "never fetched"
        try:
            moment = dt.datetime.fromisoformat(refresh["fetched_at"])
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=dt.timezone.utc)
            age = _now() - moment
        except (ValueError, TypeError):
            return True, "unreadable fetched_at"

        if not refresh["game_count"]:
            if game_date < _today_for(league):
                # An empty day that is OVER stays empty. The backoff exists for
                # a postponement or a late addition, and a finished day can
                # have neither -- so re-asking is a request per viewer for an
                # answer that is already fixed, which is the whole thing this
                # store exists to stop.
                return False, "day is over and published no games"
            if age >= empty_backoff:
                return True, f"empty, last asked {int(age.total_seconds() // 60)}m ago"
            return False, f"published no games {int(age.total_seconds() // 60)}m ago"

        unfinished = con.execute(
            "SELECT COUNT(*) FROM scoreboard_snapshots"
            " WHERE league=? AND game_date=? AND (state IS NULL OR state != 'post')",
            (league, game_date),
        ).fetchone()[0]
        if unfinished:
            return True, f"{unfinished} not final"
        return False, "every game final"
    except sqlite3.Error as exc:
        # A store that cannot answer must not be read as "nothing to do".
        return True, f"store unreadable: {type(exc).__name__}: {exc}"
    finally:
        if own:
            con.close()


def coverage(con=None):
    """One row per stored (league, date): count, age, source. For the audit."""
    own = con is None
    con = con or _db()
    try:
        init(con)
        return con.execute(
            "SELECT league, game_date, game_count, fetched_at, source"
            " FROM scoreboard_refresh ORDER BY game_date DESC, league"
        ).fetchall()
    finally:
        if own:
            con.close()
