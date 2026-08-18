#!/usr/bin/env python3
"""Shared HTTP, pacing, cache and published-oracle primitives for the reconcile suite.

Extracted from reconcile_totals.py 2026-08-08 (monolith split). The check suite,
gap classifier and coverage writer import these; the CLI entry re-exports the
names tests and docs reference. No behavior change.
"""
import calendar
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import paced_http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

CORE = "https://sports.core.api.espn.com/v2/sports"
# The site API answers for a whole date range at once. The core API answers one event
# per request. Both publish the same status, date and competition type; only the cost
# differs, and for a season still in progress the difference is an hour.
SITE = "https://site.api.espn.com/apis/site/v2/sports"

# league -> ESPN core API path segment. Adding one is step 5 of the add-a-league
# checklist in docs/DATA-COVERAGE-CONTRACT.md; read §6 first, because the shape of a
# competition is not the NFL's. Paths mirror espn_leagues.ESPN_LEAGUES (the registry
# the ingests read); the scope group of a group-scoped league (NCAAF FBS = '80') is
# read from that registry at check time, never hardcoded here.
ESPN_PATH = {
    "nfl": "football/leagues/nfl",
    "nba": "basketball/leagues/nba",
    "mlb": "baseball/leagues/mlb",
    "nhl": "hockey/leagues/nhl",
    "mls": "soccer/leagues/usa.1",
    "ncaaf": "football/leagues/college-football",
}

TIMEOUT = 20

class OracleUnreachable(Exception):
    """The published total could not be read. Distinct from a mismatch."""


# ESPN's core API rate-limits a burst with a bare 403 — not a 429, no Retry-After, and
# the same URL that answered a second ago starts refusing. Measured 2026-08-02: a few
# dozen unpaced requests trips it and the block outlives a short backoff. So pace every
# request, back off long, and cache — the whole point of this script is that a phantom
# gap is worse than a slow check.
_CACHE: Dict[str, dict] = {}
# Pace, overridable. A mid-season league is the expensive case: explain_gap costs one
# request per DIFFERING event, and MLB 2026 mid-season differs by ~776 (the whole rest
# of the schedule), which at 0.5s is a burst long enough to trip the 403 described
# above — measured 2026-08-03, and the block then outlived the retry ladder and turned
# the whole run into a single NO-ORACLE. Slow it down for those runs rather than
# discovering the ceiling again.
_MIN_INTERVAL = float(os.environ.get("LP_RECONCILE_MIN_INTERVAL") or 0.5)

# ESPN's core API rejects the bare `python-requests/x.y` User-Agent with a bare 403 —
# measured 2026-08-03: `requests.get(url)` -> 403 for nba/nhl/mlb while curl and a
# browser UA return 200 from the same IP. The 403 branch below would then back off
# six times and report NO-ORACLE, which reads as "publisher unreachable" when the
# publisher was reachable all along. Same UA as espn_client.py, which has worked
# against this host for months.
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

# ESPN's limit is a COUNT per host (~100, measured 2026-08-04), not a rate.
# Refuse at OUR ceiling before the publisher does: a run that stops at its
# declared budget with a clear message beats one that trips the wall at 137 and
# spends the rest of the process 403-ing. Per-hostname, so a multi-host run can
# never exhaust one host's budget against another's name.
_HOST_BUDGET = int(os.environ.get("LP_RECONCILE_HOST_BUDGET") or 100)
_HOST_SPEND: Dict[str, int] = {}

# The shared client issues each request (pacing, the per-host count and the
# spend log) but carries NO retry ladder: this module's policy decides what a
# refusal means -- a 403 is fail-fast OracleUnreachable, a 429/5xx is worth
# backing off -- and it must see every attempt to do that.
_FETCH = paced_http.Fetcher(min_interval=_MIN_INTERVAL, retry_waits=(),
                            headers=_HDRS, timeout=TIMEOUT,
                            host_budget=_HOST_BUDGET)


# Event documents are immutable once a game is final, and a mid-season league costs
# one fetch per event it differs by -- MLB 2026 differs by ~750, which is 20 minutes
# of pacing that a re-run pays again from zero because _CACHE dies with the process.
# That is what turned a rate-limit into a 40-minute retry loop on 2026-08-03. Persist
# them: the second run of the same season is nearly free, which is what makes this
# affordable to run on a schedule rather than by hand.
_DISK_CACHE = os.environ.get("LP_RECONCILE_CACHE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "reconcile-event-cache.json"
)
# Progress goes to a FILE, not just stderr. stderr belongs to whoever launched the
# process -- under nohup, a systemd unit, or a background shell it lands somewhere
# nobody is looking, and a run with no inspectable output is indistinguishable from a
# hung one. On 2026-08-03 that produced a 54-minute silence that could not be
# audited without poking /proc. A path you can tail is the fix.
_LOG_PATH = os.environ.get("LP_RECONCILE_LOG") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "reconcile.log"
)


def _log(message: str) -> None:
    """Append one timestamped line to the run log, and echo to stderr."""
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {message}"
    print(line, file=sys.stderr, flush=True)
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001 - logging must never break the run
        pass


_DISK: Dict[str, dict] = {}
try:
    with open(_DISK_CACHE) as _fh:
        _DISK = json.load(_fh)
except Exception:  # noqa: BLE001 - a missing or corrupt cache is not an error
    _DISK = {}
_DISK_DIRTY = False


def _disk_flush() -> None:
    """Best effort. A cache we cannot write is a slow run, never a wrong one."""
    if not _DISK_DIRTY:
        return
    try:
        os.makedirs(os.path.dirname(_DISK_CACHE), exist_ok=True)
        tmp = _DISK_CACHE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(_DISK, fh)
        os.replace(tmp, _DISK_CACHE)
    except Exception:  # noqa: BLE001
        pass


def _get_json(url: str, attempts: int = 6) -> dict:
    global _DISK_DIRTY
    if url in _CACHE:
        return _CACHE[url]
    # Only individual /events/<id> documents are cached across runs. Collection
    # envelopes carry counts that must stay live -- caching those would be caching
    # the answer this script exists to ask for.
    cacheable = re.search(r"/events/\d+$", url) is not None
    if cacheable and url in _DISK:
        return _DISK[url]
    host = urllib.parse.urlsplit(url).netloc
    # Refuse BEFORE the request: ESPN's wall is a per-host COUNT (~100), so the
    # 101st request to a host is a 403 we can see coming. A run that stops here
    # with a named number leaves the DB untouched and the budget intact for a
    # later run; a run that trips the wall spends the rest of its process
    # re-discovering it (measured 2026-08-03, 2026-08-07).
    spent = _HOST_SPEND.get(host, 0)
    if spent >= _HOST_BUDGET:
        raise OracleUnreachable(
            f"host budget spent: {spent} request(s) to {host} this run "
            f"(ceiling {_HOST_BUDGET}); refusing the {spent + 1}th — "
            f"wait for the wall to reset or raise LP_RECONCILE_HOST_BUDGET"
        )
    last = None
    for i in range(attempts):
        # The Fetcher paces (min_interval) and logs every attempt to the spend
        # log; this module's own counter still refuses before the request.
        _HOST_SPEND[host] = _HOST_SPEND.get(host, 0) + 1
        try:
            body = _FETCH.fetch(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                # A 403 from a host we already spent budget on means the wall is
                # up. Retrying is how the old ladder burned 6 requests + backoff
                # per URL and still reported NO-ORACLE. Fail the URL fast; the
                # caller's recorded-vocabulary fallback (if any) handles it.
                raise OracleUnreachable(
                    f"HTTP 403 from {host} after {_HOST_SPEND[host]} request(s)"
                ) from exc
            if exc.code in (429, 500, 502, 503):
                last = f"HTTP {exc.code}"
                time.sleep(min(60, 3 * 2 ** i))
                continue
            raise
        except OSError as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(min(60, 3 * 2 ** i))
        else:
            _CACHE[url] = body
            if cacheable:
                _DISK[url] = body
                _DISK_DIRTY = True
                if len(_DISK) % 50 == 0:
                    _disk_flush()
            return body
    raise OracleUnreachable(f"{last} after {attempts} attempts")

def season_types(league: str, season: int) -> Dict[str, dict]:
    """The season's own type list, keyed by lowercased name.

    This function exists because the first draft of this script carried
    `REGULAR, POSTSEASON = 2, 3` at module scope — a definition, inferred, which is
    exactly what published-first rung 5 forbids. It holds for the four leagues we had
    and breaks on the three we are adding: measured 2026-08-02, `soccer/leagues/eng.1`
    season 2025 publishes a *single* type, id 1, named "2025-26 English Premier League".
    A hardcoded `types/2` would have reported the entire Premier League as missing.

    `GET seasons/<year>` publishes ids, names and date ranges. Read them.
    """
    doc = _get_json(f"{CORE}/{ESPN_PATH[league]}/seasons/{season}")
    types = doc.get("types", {}).get("items", [])
    if not types:
        raise OracleUnreachable(f"no season types published for {league} {season}")
    return {str(t.get("name", "")).lower(): t for t in types}


def season_type_id(league: str, season: int, name: str) -> Optional[str]:
    """Resolve a type id by published name, or None when the league has no such phase.

    None is a real answer, not a failure: a soccer league genuinely has no postseason.
    """
    types = season_types(league, season)
    for key, value in types.items():
        if name in key:
            return str(value.get("id"))
    return None


def published_count(url: str, *, path: Optional[List[str]] = None) -> int:
    """Read a collection's cardinality from a limit=1 envelope. One request."""
    sep = "&" if "?" in url else "?"
    try:
        node = _get_json(f"{url}{sep}limit=1")
    except OracleUnreachable:
        raise
    except Exception as e:  # noqa: BLE001 - any failure is "no evidence"
        raise OracleUnreachable(f"{type(e).__name__}: {e}") from e
    for key in path or []:
        if key not in node:
            raise OracleUnreachable(f"no '{key}' in response from {url}")
        node = node[key]
    if "count" not in node:
        raise OracleUnreachable(f"no 'count' in response from {url}")
    return int(node["count"])


def published_event_ids(url: str) -> List[str]:
    """Every event id in a collection, read from the `$ref` URLs.

    Paged at limit=100 (the project's pacing ceiling — small pages + the
    0.5s+ floor between requests is the protection against ESPN's 403 wall).
    The pageCount loop is what makes this complete; an earlier version read
    the first page only and silently classified the first 100 of 1,239.
    """
    out: List[str] = []
    page = 1
    sep = "&" if "?" in url else "?"
    while True:
        doc = _get_json(f"{url}{sep}limit=100&page={page}")
        for item in doc.get("items", []):
            m = re.search(r"/events/(\d+)", item.get("$ref", ""))
            if m:
                out.append(m.group(1))
        if page >= int(doc.get("pageCount", 1) or 1):
            return out
        page += 1


def published_team_ids(url: str) -> List[str]:
    """Every team id in a teams collection, from the `$ref` URLs.

    The teams analogue of published_event_ids: the id is already in the URL
    (`.../teams/<id>`), so no per-team fetch is needed to enumerate. NCAAF's
    group-scoped teams collection publishes bare refs with no abbreviation
    inlined, so the ids are joined against the site API's id -> abbreviation
    map by the per-team check.
    """
    out: List[str] = []
    page = 1
    sep = "&" if "?" in url else "?"
    while True:
        doc = _get_json(f"{url}{sep}limit=100&page={page}")
        for item in doc.get("items", []):
            m = re.search(r"/teams/(\d+)", item.get("$ref", ""))
            if m:
                out.append(m.group(1))
        if page >= int(doc.get("pageCount", 1) or 1):
            return out
        page += 1

def bulk_event_index(url: str) -> Dict[str, dict]:
    """Every event of a season, by id, in one request per calendar month.

    The per-event fetch this replaces is the right shape for a finished season, which
    differs by a handful of events, and exactly the wrong shape for a season still
    being played: MLB 2026 differs by its entire remaining schedule — 776 events — and
    at any pace polite enough not to be blocked that is over an hour of requests. Two
    consecutive runs on 2026-08-03 died that way, the first into a 403 of its own
    making, the second to its timeout with nothing to show.

    The site API publishes the same three fields the classifier reads — `date`,
    `competitions[0].type.abbreviation`, `competitions[0].status.type.name` — for a
    whole date range at once. Measured 2026-08-03: seven requests return all 2,458
    published MLB 2026 regular-season events, exactly matching the core API's own
    `count`, and reproduce the single All-Star event hiding inside season type 2.

    Best effort by contract. Anything unindexed falls back to its own fetch, so this
    only ever changes how long a run takes, never what it concludes.
    """
    # A group-scoped league (NCAAF FBS) publishes its events under
    # `types/<id>/groups/<g>/events`; the optional group segment must not stop
    # the index from matching, or a mid-season college run pays a paced
    # per-event fetch for every remaining game.
    m = re.search(
        r"/v2/sports/(.+?)/seasons/(\d+)/types/([^/]+)(?:/groups/[^/]+)?/events", url
    )
    if not m:
        return {}
    core_path, season, type_id = m.group(1), m.group(2), m.group(3)
    try:
        window = _get_json(f"{CORE}/{core_path}/seasons/{season}/types/{type_id}")
    except OracleUnreachable:
        return {}
    start, end = str(window.get("startDate") or "")[:10], str(window.get("endDate") or "")[:10]
    if not (start and end):
        return {}

    # The site API takes `baseball/mlb` where the core API takes `baseball/leagues/mlb`.
    site_path = core_path.replace("/leagues/", "/")
    index: Dict[str, dict] = {}
    requests_made = 0
    year, month = int(start[:4]), int(start[5:7])
    last_year, last_month = int(end[:4]), int(end[5:7])
    while (year, month) <= (last_year, last_month):
        span = calendar.monthrange(year, month)[1]
        try:
            doc = _get_json(
                f"{SITE}/{site_path}/scoreboard"
                f"?dates={year}{month:02d}01-{year}{month:02d}{span:02d}&limit=1000"
            )
            requests_made += 1
        except OracleUnreachable:
            doc = {}
        for event in doc.get("events") or []:
            # A month of scoreboard carries every phase that touched those dates —
            # 321 spring-training events sit alongside the regular season in March.
            # The type we were asked about is the only one this collection claims.
            if str((event.get("season") or {}).get("type")) != str(type_id):
                continue
            if event.get("id"):
                index[str(event["id"])] = event
        month = 1 if month == 12 else month + 1
        year = year + 1 if month == 1 else year
    if index:
        _log(f"  bulk index: {len(index)} events in {requests_made} request(s)")
    return index

def db_count(conn: sqlite3.Connection, sql: str, args=()) -> int:
    return int(conn.execute(sql, args).fetchone()[0])
