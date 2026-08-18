#!/usr/bin/env python3
"""Fetch the board's slates on a timer, so a page view never calls a publisher.

Two modes, one script:

    ingest_scoreboards.py                 refresh today and tomorrow
    ingest_scoreboards.py --live          refresh only what is under way

## Why this exists

`/api/{league}/games` used to call ESPN on every request. One cold `/scores`
load was 22 upstream requests, and the serving process carries a per-host budget
that answers exhaustion with `time.sleep(60)` -- so the board stalled itself
about every five page loads (measured on prod 2026-08-18: 46 sixty-second pauses
in 46 minutes of uptime). Publisher spend was a function of user traffic, which
is the one thing we cannot bound.

Here it is a constant, and a small one, because **we only ask about leagues the
publisher says are playing.** `league_activity` reads `leagues[0].calendar` out
of the payloads this job already fetches. Measured 2026-08-18, board leagues,
today and tomorrow:

    22 pairs -> 14 asked
    skipped: nba and nhl (seasons ended June and July), ncaaf (opens Aug 22),
             wc (the final was Jul 19)

None of those are hand-written. Leagues Cup looks finished on the same evidence
-- its league phase ended Aug 13 -- and is asked, because ESPN publishes
quarterfinals through Sep 1. A guess would have dropped a live league.

## The live rung

Between a game's start and its final, the slate has to move. Polling all eleven
leagues for that cost 22 requests a tick. Instead `scoreboard_store.live_targets`
asks the DB which (league, date) pairs hold a game that has started and is not
final, and only those are refreshed. Nothing under way costs nothing at all.

## Spend

Printed per host on every run, always, per rung 6 of the `espn-request-budget`
skill. A job whose cost nobody can see is one nobody can size later.
"""
import argparse
import datetime as dt
import fcntl
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client as espn
import league_activity
import paced_http
import scoreboard_store

# The leagues the scoreboard fans out over, minus `cod`, which is not an ESPN
# league (breakingpoint.gg) and has its own path in the router.
BOARD_LEAGUES = ["nba", "mlb", "nhl", "nfl", "lcup", "mls", "ncaaf", "atp", "wta", "ufc", "wc"]

# Polite spacing between calls. This buys no budget -- ESPN's ceiling is a count,
# not a rate -- it is here so a timer firing every ten minutes does not arrive as
# a burst on a publisher that serves us for free.
MIN_INTERVAL = 1.0

# The job refuses at its own declared ceiling rather than discovering ESPN's.
# Never 0: that would mean "this publisher has no limit", which is the one thing
# not to declare about someone serving us for nothing.
HOST_BUDGET = 60

# How long to wait for the AI preview threads before exiting. They are daemon
# threads, so leaving without them is the same as never having kicked them. The
# live run waits less because its timer fires again in a minute.
STORY_DRAIN_SCHEDULE = 240
STORY_DRAIN_LIVE = 45


def _dates(today=None):
    """Yesterday, today, tomorrow.

    Yesterday is here because a day does not finish at midnight UTC. Late games
    are still in flight when the date rolls over, so a window of today-and-
    tomorrow captures that slate mid-game and then, by the finished-day rule,
    never looks at it again -- freezing a live score as the permanent record.
    Yesterday costs one more request per league per day and then retires itself
    the moment `needs_refresh` sees every game final.
    """
    today = today or dt.date.today()
    return [(today - dt.timedelta(days=1)).isoformat(),
            today.isoformat(),
            (today + dt.timedelta(days=1)).isoformat()]


def _past_dates(days, today=None):
    """The finished days to capture, oldest first.

    The serving path never asks a publisher about a day that is over: its result
    cannot change, so a request per page view buys a fact that is already fixed.
    That rule only works if the day was captured while it was current -- which is
    true from here on, and false for every day before this job existed. This is
    the one-time catch-up, and it is a JOB, not a page load: bounded, paced,
    declared, and run once per missing day rather than once per viewer.
    """
    today = today or dt.date.today()
    return [(today - dt.timedelta(days=offset)).isoformat()
            for offset in range(days, 0, -1)]


def _refresh(league, date, verbose=True):
    """One (league, date): fetch, store the slate, record when the league plays.

    Returns (games_written, error). An error is returned rather than raised so
    one refusing league cannot take the rest of the run with it -- but it is
    never swallowed: the caller prints it and the exit code reflects it.
    """
    try:
        games = espn.games(league, date)
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"

    written = scoreboard_store.save(league, date, games, source="espn")

    # "Write the preview whenever we find out about the game." This job is now
    # where we find out, so the kick moved here out of the request handler --
    # the page no longer fetches, so leaving it there would have quietly ended
    # preview generation.
    if league in ("nba", "nhl", "mlb", "nfl") and games:
        try:
            from core_stories import kick_game_stories
            kick_game_stories(league, games)
        except Exception as exc:
            print(f"  stories not kicked league={league}: {type(exc).__name__}: {exc}")

    # Free: the calendar rode in on the fetch above and is served from the
    # 20-second cache, so this costs no request.
    try:
        payload = espn.scoreboard_raw(league, date)
        if not league_activity.record_from_payload(league, payload):
            league_activity.touch(league)
    except Exception as exc:
        league_activity.touch(league)
        if verbose:
            print(f"  calendar unread league={league}: {type(exc).__name__}: {exc}")
    return written, None


def _drain_stories(timeout):
    """Wait for the story threads this run kicked, then return how many are left.

    `kick_game_stories` starts DAEMON threads. That was right when the caller was
    a long-lived server: the request returned immediately and generation finished
    behind it. This job exits in seconds, and a daemon thread dies with the
    process -- so moving the kick here without waiting would have quietly ended
    preview generation while every log line still said ok.
    """
    try:
        import core_stories
        inflight = core_stories._story_inflight
    except Exception:
        return 0
    deadline = time.time() + timeout
    while inflight and time.time() < deadline:
        time.sleep(1.0)
    return len(inflight)


def _spend_report():
    spend = dict(paced_http._host_spend)
    if not spend:
        return "spent 0 requests"
    return "spent " + ", ".join(f"{host}={count}" for host, count in sorted(spend.items()))


def run_schedule(leagues, dates, dry_run=False, verbose=True):
    """Two gates, in order, and both of them are the publisher's own answers.

    First `league_activity`: is this league in a window ESPN says it plays in.
    Second `scoreboard_store.needs_refresh`: given what it told us last time, is
    there anything new to learn. The first retires a league for a season; the
    second retires a day. Together they take the steady-state cost from 22
    requests a cycle to whatever is actually playing and still moving.
    """
    in_season, plan_skip = league_activity.plan(leagues, dates)
    if verbose:
        print(league_activity.report(leagues, dates))

    plan_ask = []
    for league, date in in_season:
        wanted, reason = scoreboard_store.needs_refresh(league, date)
        if wanted:
            plan_ask.append((league, date))
        else:
            plan_skip.append((league, f"{date}: {reason}"))
            if verbose:
                print(f"  skip  {league:6} {date}: {reason}")
    if dry_run:
        print(f"[scoreboards] would ask {len(plan_ask)} of {len(leagues) * len(dates)}")
        return 0

    failures = []
    total = 0
    for league, date in plan_ask:
        written, error = _refresh(league, date, verbose=verbose)
        total += written
        if error:
            failures.append((league, date, error))
            print(f"  FAIL {league:6} {date}: {error}")
        elif verbose:
            print(f"  ok   {league:6} {date}  games={written}")
    pending = _drain_stories(STORY_DRAIN_SCHEDULE)
    print(f"[scoreboards] schedule: {len(plan_ask)} asked, {len(plan_skip)} skipped, "
          f"{total} games stored, {len(failures)} failed"
          + (f", {pending} stories still generating at exit" if pending else "")
          + f"; {_spend_report()}")
    return 1 if failures else 0


def run_live(verbose=True):
    targets = scoreboard_store.live_targets()
    if not targets:
        print(f"[scoreboards] live: nothing under way; {_spend_report()}")
        return 0

    failures = []
    total = 0
    for league, date in targets:
        written, error = _refresh(league, date, verbose=verbose)
        total += written
        if error:
            failures.append((league, date, error))
            print(f"  FAIL {league:6} {date}: {error}")
        elif verbose:
            print(f"  ok   {league:6} {date}  games={written}")
    pending = _drain_stories(STORY_DRAIN_LIVE)
    print(f"[scoreboards] live: {len(targets)} in flight, {total} games stored, "
          f"{len(failures)} failed"
          + (f", {pending} stories still generating at exit" if pending else "")
          + f"; {_spend_report()}")
    return 1 if failures else 0


_LOCK_PATH = os.environ.get("LP_SCOREBOARD_LOCK", "/tmp/lp-scoreboards.lock")


def _only_one_run(path=_LOCK_PATH, wait_seconds=0.0):
    """Hold an exclusive lock, or refuse to start. Returns the open file or None.

    THE BUDGET IS PER HOST, BUT THE COUNTER IS PER PROCESS. Two copies of this
    job each think they have spent 20 requests when between them they have
    spent 40, so the declared ceiling stops meaning anything. Measured
    2026-08-18: a backfill still running plus a second one started on top of it
    walked ESPN's per-host count until all three ESPN hosts refused this box --
    site.web.api, site.api and sports.core.api, none of which had been refusing
    an hour earlier. Two timers plus a hand-run catch-up is exactly how that
    happens, so the second one now declines instead of overlapping.
    """
    handle = open(path, "w")
    deadline = time.time() + wait_seconds
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= deadline:
                handle.close()
                return None
            time.sleep(0.5)
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true",
                        help="refresh only leagues holding a game that has started")
    parser.add_argument("--leagues", default=",".join(BOARD_LEAGUES))
    parser.add_argument("--date", help="anchor day (default today); tomorrow is added")
    parser.add_argument("--backfill", type=int, metavar="DAYS",
                        help="capture the last DAYS finished days, then stop. "
                             "One-time catch-up for days that passed before this "
                             "job existed; the serving path never asks about them.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be asked, request nothing")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    # Batch settings, opted into here rather than in the client, because the
    # serving path must never inherit them: a page load must not pause.
    # The live run WAITS briefly rather than declining outright. Its whole value
    # is timeliness and it costs two requests; a schedule run takes 7-13s, so a
    # short wait gets it in almost every time. Measured 2026-08-18, an instant
    # decline froze three live polls in one hour for no benefit. A backfill runs
    # for minutes and will still push it out, which is the correct outcome --
    # the point is to protect the shared budget, not to be first.
    lock = _only_one_run(wait_seconds=20.0 if args.live else 0.0)
    if lock is None:
        print("[scoreboards] another scoreboard run holds the lock; "
              "declining rather than doubling the per-host spend")
        return 0

    espn.set_min_interval(MIN_INTERVAL)
    espn.set_host_budget(HOST_BUDGET)
    # This job has nobody waiting on it, so it is allowed to wait out a spent
    # budget. The module default is "refuse" for the request handlers.
    espn.set_on_exhausted("sleep")

    scoreboard_store.init()
    league_activity.init()

    started = time.time()
    if args.backfill:
        anchor = dt.date.fromisoformat(args.date) if args.date else None
        leagues = [l.strip().lower() for l in args.leagues.split(",") if l.strip()]
        dates = _past_dates(args.backfill, anchor)
        print(f"[scoreboards] backfill {dates[0]} to {dates[-1]} "
              f"({len(dates)} days x {len(leagues)} leagues, before gating)")
        status = run_schedule(leagues, dates, dry_run=args.dry_run,
                              verbose=not args.quiet)
    elif args.live:
        status = run_live(verbose=not args.quiet)
    else:
        anchor = dt.date.fromisoformat(args.date) if args.date else None
        leagues = [l.strip().lower() for l in args.leagues.split(",") if l.strip()]
        status = run_schedule(leagues, _dates(anchor), dry_run=args.dry_run,
                              verbose=not args.quiet)
    print(f"[scoreboards] {time.time() - started:.1f}s")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
