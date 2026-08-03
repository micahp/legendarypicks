#!/usr/bin/env python3
"""
reconcile_totals.py — compare what we stored against what the publisher says exists.

Every ingest in this repo answers "did rows land?" Nothing answers "did *all* the rows
land?" — and a partial ingest is indistinguishable from a complete one by inspection.
The 2024 NFL game logs sat at 29% of 2025 for months looking entirely normal.

The cheap oracle: ESPN's core API returns the cardinality of any collection in the
envelope of a `limit=1` request. One HTTP call, no traversal, no key needed:

    GET .../seasons/2025/types/2/events?limit=1   ->  {"count": 272, ...}
    GET .../seasons/2025/teams?limit=1            ->  {"count": 32,  ...}
    GET .../athletes/<id>/eventlog?limit=1        ->  {"events": {"count": 17, ...}}

Usage:
    python3 reconcile_totals.py                    # all checks
    python3 reconcile_totals.py --league nfl
    python3 reconcile_totals.py --season 2024
    python3 reconcile_totals.py --sample 40        # per-player eventlog sample size

Exit code is 1 if any check MISMATCHes or its oracle is unreachable. An unreachable
oracle is a FAIL, not a skip: "evidence unavailable" must never read as green.

Environment:
    LP_DB_PATH — the sqlite database (default: backend/data/picks.db)
"""
import argparse
import calendar
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, NamedTuple, Optional, Tuple

import requests

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
# competition is not the NFL's.
ESPN_PATH = {
    "nfl": "football/leagues/nfl",
    "nba": "basketball/leagues/nba",
    "mlb": "baseball/leagues/mlb",
    "nhl": "hockey/leagues/nhl",
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
_last_request = 0.0

# ESPN's core API rejects the bare `python-requests/x.y` User-Agent with a bare 403 —
# measured 2026-08-03: `requests.get(url)` -> 403 for nba/nhl/mlb while curl and a
# browser UA return 200 from the same IP. The 403 branch below would then back off
# six times and report NO-ORACLE, which reads as "publisher unreachable" when the
# publisher was reachable all along. Same UA as espn_client.py, which has worked
# against this host for months.
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


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
    global _last_request, _DISK_DIRTY
    if url in _CACHE:
        return _CACHE[url]
    # Only individual /events/<id> documents are cached across runs. Collection
    # envelopes carry counts that must stay live -- caching those would be caching
    # the answer this script exists to ask for.
    cacheable = re.search(r"/events/\d+$", url) is not None
    if cacheable and url in _DISK:
        return _DISK[url]
    last = None
    for i in range(attempts):
        gap = _MIN_INTERVAL - (time.monotonic() - _last_request)
        if gap > 0:
            time.sleep(gap)
        try:
            _last_request = time.monotonic()
            r = requests.get(url, timeout=TIMEOUT, headers=_HDRS)
            if r.status_code in (403, 429, 500, 502, 503):
                last = f"HTTP {r.status_code}"
                time.sleep(min(60, 3 * 2 ** i))
                continue
            r.raise_for_status()
            body = r.json()
            _CACHE[url] = body
            if cacheable:
                _DISK[url] = body
                _DISK_DIRTY = True
                if len(_DISK) % 50 == 0:
                    _disk_flush()
            return body
        except OSError as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(min(60, 3 * 2 ** i))
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

    Three paged requests for a 1,239-event NBA season, and zero per-event fetches —
    the id is already in the URL. The previous version of this module paged at
    `limit=100` and would have silently classified the first 100 of 1,239.
    """
    out: List[str] = []
    page = 1
    sep = "&" if "?" in url else "?"
    while True:
        doc = _get_json(f"{url}{sep}limit=500&page={page}")
        for item in doc.get("items", []):
            m = re.search(r"/events/(\d+)", item.get("$ref", ""))
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
    m = re.search(r"/v2/sports/(.+?)/seasons/(\d+)/types/([^/]+)/events", url)
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


class Gap(NamedTuple):
    """What a difference between the published set and ours is actually made of."""
    published: int          # everything in the publisher's collection
    exhibition: int         # All-Star and friends: published, played, not a league game
    not_played: int         # postponed/canceled shells, superseded by a makeup event id
    expected: int           # published - exhibition - not_played - not_yet_played - beyond_horizon
    missing: List[str]      # published, real, played, and absent from our table
    extra: List[str]        # ours and not theirs — always a bug, in us or in the key
    not_yet_played: int = 0  # scheduled/in-progress: published, not finished, not a gap
    beyond_horizon: int = 0  # finished AFTER the last game we hold: outside the claim


def explain_gap(url: str, ours: set, horizon: Optional[str] = None) -> Gap:
    """Diff a published collection against ours and classify only the difference.

    The cost is one request per *differing* event, not per event, so a clean season
    costs three requests and a broken one costs as many as it is broken. That is what
    makes it affordable to run this on every league.

    It exists because a headline count difference is not a defect until it is
    classified. NBA 2025-26 published 1,239 regular-season events against our 1,227,
    and the 12 were three different things: 4 All-Star exhibitions (ESPN files NBA
    All-Star under season type **2**, unlike the NFL Pro Bowl under type 3 — which is
    why the exhibition type id is never assumed here and always read from the event),
    4 postponed shells whose makeups carry new event ids, and only 4 real misses.
    Reporting "12 missing" would have sent someone to fix a problem we did not have.
    """
    published = published_event_ids(url)
    diff = [e for e in published if e not in ours]
    exhibition = not_played = not_yet_played = beyond_horizon = 0
    missing: List[str] = []
    # Progress, to stderr, because a run with no output is indistinguishable from a
    # hung one. A finished season differs by a handful of events and prints nothing
    # worth reading; a MID-SEASON league differs by its whole remaining schedule --
    # MLB 2026 differs by ~750, which is 20 minutes of paced requests. The first
    # version of this printed only at the end, and a 54-minute silence is not
    # something anyone should be asked to take on faith.
    total = len(diff)
    index: Dict[str, dict] = {}
    if total > 50:
        _log(f"classifying {total} differing events")
        # Above this many, the per-event fetch is the wrong instrument. Below it, a
        # finished season pays three requests and the bulk index would cost more than
        # it saves.
        index = bulk_event_index(url)
        covered = sum(1 for e in diff if e in index)
        if index:
            _log(f"  index covers {covered}/{total} differing events; "
                 f"{total - covered} still need their own fetch "
                 f"(~{(total - covered) * _MIN_INTERVAL / 60:.0f} min at {_MIN_INTERVAL}s pacing)")
    started = time.monotonic()
    for n, event_id in enumerate(diff, 1):
        if total > 50 and n % 100 == 0:
            rate = (time.monotonic() - started) / n
            _log(f"  {n}/{total}  missing={len(missing)} "
                 f"not-yet-played={not_yet_played} past-horizon={beyond_horizon} "
                 f"eta={(total - n) * rate / 60:.0f}m")
        ev = index.get(event_id)
        if ev is None:
            try:
                ev = _get_json(f"{CORE}/{ESPN_PATH_BY_URL(url)}/events/{event_id}")
            except OracleUnreachable:
                missing.append(event_id)  # unclassifiable is not innocent
                continue
        comp = (ev.get("competitions") or [{}])[0]
        if (comp.get("type") or {}).get("abbreviation") == "ALLSTAR":
            exhibition += 1
            continue
        state = _event_state(comp)
        if state in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"):
            not_played += 1
            continue
        # Not-yet-played: a season in progress (MLB 2026) publishes its whole
        # schedule, so the collection holds games that have not been played yet.
        # They are not missing — they have not happened. Counting them as missing
        # would report every future MLB game as a defect and demote a season that
        # is exactly as complete as it can be today. The status type carries the
        # answer: `completed` False with no terminal name means scheduled or in
        # progress, and the game we cannot have yet is not a game we lost.
        if state in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "STATUS_PRE"):
            not_yet_played += 1
            continue
        # Finished, absent from our table, and played AFTER the last game we hold.
        #
        # This is the difference between a gap and an edge, and getting it wrong is
        # what made a live season unofferable. `not_yet_played` above handles
        # September. It does nothing for last night: those games ARE finished, so
        # without this branch they count as missing the moment they end, the verdict
        # drops to `partial`, and the league disappears from /leagues every morning
        # until the next ingest runs — availability that tracks cron timing rather
        # than data quality.
        #
        # So the coverage row claims a WINDOW, not an instant: every published game
        # up to `horizon` is present. A game past the horizon is outside the claim,
        # not a hole in it. A game missing INSIDE the window is still a real miss and
        # still fails, which is the whole point of keeping the two apart.
        if horizon and str(ev.get("date") or "")[:10] > horizon:
            beyond_horizon += 1
            continue
        missing.append(event_id)
    return Gap(
        published=len(published),
        exhibition=exhibition,
        not_played=not_played,
        expected=len(published) - exhibition - not_played - not_yet_played - beyond_horizon,
        missing=missing,
        extra=sorted(ours - set(published)),
        not_yet_played=not_yet_played,
        beyond_horizon=beyond_horizon,
    )


def _event_state(comp: dict) -> str:
    """The competition's status name, following the `$ref` when it is not inlined."""
    status = comp.get("status") or {}
    kind = status.get("type") or {}
    if not kind and status.get("$ref"):
        try:
            kind = _get_json(status["$ref"]).get("type") or {}
        except OracleUnreachable:
            return ""
    return str(kind.get("name") or "")


def ESPN_PATH_BY_URL(url: str) -> str:  # noqa: N802 - reads as a lookup at call sites
    """Recover the league path segment from a season-scoped collection URL."""
    m = re.search(r"/v2/sports/(.+?)/seasons/", url)
    if not m:
        raise OracleUnreachable(f"cannot locate league path in {url}")
    return m.group(1)


def db_count(conn: sqlite3.Connection, sql: str, args=()) -> int:
    return int(conn.execute(sql, args).fetchone()[0])


def describe_gap(gap: Gap) -> str:
    """The one-line arithmetic, so a passing check still shows what it excluded."""
    parts = [f"{gap.published} published"]
    if gap.exhibition:
        parts.append(f"-{gap.exhibition} exhibition")
    if gap.not_played:
        parts.append(f"-{gap.not_played} not played")
    if gap.not_yet_played:
        parts.append(f"-{gap.not_yet_played} not yet played")
    if gap.beyond_horizon:
        parts.append(f"-{gap.beyond_horizon} past our horizon")
    return " ".join(parts)


def report_gap(rep: "Report", name: str, gap: Gap) -> None:
    """Name the individual events on both sides of a difference.

    A count tells you something is wrong; an event id tells you what. The four NBA
    games lost on 2026-07-14 were findable in one query once someone printed them.
    """
    for event_id in gap.missing[:10]:
        rep.note("  missing event", f"{name}: {event_id} published, played, not ours")
    for event_id in gap.extra[:10]:
        rep.note("  extra event", f"{name}: {event_id} ours, not in the published set")


class Report:
    """Checks, plus a per-(league, season) verdict the coverage registry can store.

    The verdict is deliberately three-valued and deliberately not derivable from a
    count of passes. `unverified` is what an unreachable oracle produces, and it is
    NOT the same as `partial`: one says our data disagrees with the publisher, the
    other says nobody knows. Collapsing them is how "evidence unavailable" gets read
    as green.
    """

    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str, str]] = []
        self.failed = 0
        self.current: Optional[Tuple[str, int]] = None
        self.scopes: Dict[Tuple[str, int], Dict[str, int]] = {}

    def _tally(self, outcome: str) -> None:
        if self.current is None:
            return
        self.scopes.setdefault(
            self.current, {"pass": 0, "mismatch": 0, "no_oracle": 0}
        )[outcome] += 1

    def scope(self, league: str, season: int) -> None:
        self.current = (league, season)
        self.scopes.setdefault(
            self.current, {"pass": 0, "mismatch": 0, "no_oracle": 0}
        )

    def verdict(self, league: str, season: int) -> str:
        tally = self.scopes.get((league, season))
        if not tally or not any(tally.values()):
            return "unverified"           # nothing ran; never good
        if tally["no_oracle"]:
            return "unverified"           # evidence unavailable is not evidence of health
        if tally["mismatch"]:
            return "partial"
        return "complete"

    def check(self, name: str, ours: int, theirs: int, note: str = "") -> None:
        ok = ours == theirs
        if not ok:
            self.failed += 1
        self._tally("pass" if ok else "mismatch")
        delta = "" if ok else f"  ({ours - theirs:+d})"
        self.rows.append(
            ("PASS" if ok else "MISMATCH", name, f"ours={ours} published={theirs}{delta}", note)
        )

    def unreachable(self, name: str, why: str) -> None:
        self.failed += 1
        self._tally("no_oracle")
        self.rows.append(("NO-ORACLE", name, "expected total unavailable", why))

    def note(self, name: str, text: str) -> None:
        self.rows.append(("INFO", name, text, ""))

    def render(self) -> str:
        width = max((len(r[1]) for r in self.rows), default=0)
        lines = []
        for status, name, detail, note in self.rows:
            line = f"{status:<10} {name:<{width}}  {detail}"
            if note:
                line += f"   [{note}]"
            lines.append(line)
        return "\n".join(lines)


def check_nfl(conn: sqlite3.Connection, rep: Report, season: int, sample: int) -> None:
    base = f"{CORE}/{ESPN_PATH['nfl']}/seasons/{season}"

    # --- games: schedule table vs ESPN's event count, per season type.
    # Type ids come from the season document, not from a constant — see season_types().
    try:
        regular_id = season_type_id("nfl", season, "regular")
        postseason_id = season_type_id("nfl", season, "post")
    except OracleUnreachable as e:
        rep.unreachable(f"nfl {season} season types", str(e))
        return

    for type_id, game_type, label in (
        (regular_id, "REG", "regular"),
        (postseason_id, "POST", "post"),
    ):
        name = f"nfl {season} {label}-season games"
        if type_id is None:
            rep.unreachable(name, f"no '{label}' type published for nfl {season}")
            continue
        # Diff on the ESPN event id, not on `game_id` — nfl_schedule is keyed
        # nflverse-style (`2025_01_DAL_PHI`) and carries ESPN's id in `espn`.
        # Comparing the wrong vocabulary would report all 272 games as missing and
        # all 272 as extra, which is the LAR/LA join-key failure with more zeros.
        our_ids = {
            str(r[0])
            for r in conn.execute(
                "SELECT espn FROM nfl_schedule WHERE season=? AND espn IS NOT NULL"
                " AND espn != '' AND game_type "
                + ("= 'REG'" if game_type == "REG" else "!= 'REG'"),
                (season,),
            )
        }
        ours = len(our_ids)
        try:
            gap = explain_gap(f"{base}/types/{type_id}/events", our_ids)
        except OracleUnreachable as e:
            rep.unreachable(name, str(e))
            continue
        theirs = gap.expected
        rep.check(name, ours, theirs, describe_gap(gap))
        report_gap(rep, name, gap)

        # --- coverage: every one of those games should appear in the derived tables
        for table, col in (("player_game_logs", "game_id"), ("nfl_pbp", "game_id")):
            if game_type == "POST" and table == "nfl_pbp":
                continue  # nfl_pbp has no game_type column; it is checked once, vs REG
            covered = db_count(
                conn,
                f"SELECT COUNT(DISTINCT {col}) FROM {table} WHERE season=?"
                + (" AND league='nfl'" if table == "player_game_logs" else "")
                + (" AND game_type='REG'" if table == "player_game_logs" and game_type == "REG" else "")
                + (" AND game_type!='REG'" if table == "player_game_logs" and game_type == "POST" else ""),
                (season,),
            )
            rep.check(f"{name} in {table}", covered, theirs, "distinct game_id")

    # --- teams
    name = f"nfl {season} teams"
    try:
        theirs = published_count(f"{base}/teams")
    except OracleUnreachable as e:
        rep.unreachable(name, str(e))
    else:
        ours = db_count(
            conn,
            "SELECT COUNT(DISTINCT home_team) FROM nfl_schedule WHERE season=?",
            (season,),
        )
        rep.check(name, ours, theirs, "nfl_schedule.home_team")

    # --- per-player game counts: the check that catches a partial ingest
    # A season total can look right while individual players are short.
    # `eventlog` for a season is REGULAR SEASON ONLY (measured: Drake Maye 2025 returns
    # 17 events, Sep 7 -> Jan 4, though he played four playoff games). So compare REG to
    # REG — the first draft of this check compared our 21 to their 17 and reported seven
    # healthy Patriots as short.
    players = conn.execute(
        """
        SELECT p.id, p.name, p.espn_id, COUNT(l.id)
          FROM players p
          JOIN player_game_logs l
            ON l.player_id = p.id AND l.season = ? AND l.game_type = 'REG'
         WHERE p.league = 'nfl' AND p.espn_id IS NOT NULL AND p.espn_id != ''
         GROUP BY p.id
         ORDER BY COUNT(l.id) DESC
         LIMIT ?
        """,
        (season, sample),
    ).fetchall()
    if not players:
        rep.unreachable(f"nfl {season} per-player game counts", "no joinable players with espn_id")
        return

    short = []
    unreachable = 0
    for pid, pname, espn_id, ours in players:
        try:
            theirs = published_count(
                f"{base}/athletes/{espn_id}/eventlog", path=["events"]
            )
        except OracleUnreachable:
            unreachable += 1
            continue
        if ours != theirs:
            short.append(f"{pname} ours={ours} published={theirs}")
    checked = len(players) - unreachable
    name = f"nfl {season} per-player game counts"
    if checked == 0:
        rep.unreachable(name, "every eventlog request failed")
    else:
        if unreachable:
            # Never let a dead oracle quietly shrink the denominator into a pass.
            rep.unreachable(f"{name} (partial)", f"{unreachable} of {len(players)} eventlogs unreadable")
        rep.check(name, checked - len(short), checked, f"sampled {checked} players")
        for s in short[:10]:
            rep.note("  short player", s)


def check_generic(conn: sqlite3.Connection, rep: Report, league: str, season: int) -> None:
    """Games-played coverage for the non-NFL leagues, which share player_game_logs.

    Caveat before you trust a MISMATCH here: **check which season the key names.** ESPN
    has no league-wide convention — measured 2026-08-02 from `types[].startDate/endDate`,
    `nba/seasons/2026` and `nhl/seasons/2026` are the *2025-26* seasons (keyed by the year
    they end) while `nfl/seasons/2026` starts in Sep 2026 and `eng.1/seasons/2025` is
    "2025-26". So NBA's `2026` in our tables already agrees with ESPN's `2026`; an earlier
    version of this docstring claimed the opposite and would have had you dismiss a real
    mismatch as a vocabulary artefact.

    What is genuinely inconsistent is ours: the NHL 2025-26 season is `20252026` in
    `player_game_logs` and `2026` in `team_game_results` — two keys, one season, same
    database. Same class of bug as the LAR/LA join key.
    """
    base = f"{CORE}/{ESPN_PATH[league]}/seasons/{season}"
    name = f"{league} {season} regular-season games in player_game_logs"
    try:
        # A competition with a single published type (soccer) has no "regular season"
        # phase to name; its one type *is* the season.
        type_id = season_type_id(league, season, "regular")
        if type_id is None:
            published = list(season_types(league, season).values())
            if len(published) != 1:
                rep.unreachable(name, "no regular-season type and more than one published")
                return
            type_id = str(published[0].get("id"))
        # team_game_results is keyed by ESPN's event id for nba/nhl/mlb, so the gap
        # can be classified event by event. player_game_logs is not: NHL rows carry
        # NHL-API ids (`2025020001`) and MLB rows carry MLB ids, so that table gets a
        # count comparison and nothing more. Diffing across two vocabularies would
        # report every game as both missing and extra.
        our_ids = {
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT game_id FROM team_game_results"
                " WHERE league=? AND season=?",
                (league, season),
            )
        }
        # The horizon is the last game we hold, and it is what turns this from an
        # instant into a window. Read from the table rather than from the clock: a
        # season is as current as its data, not as current as the moment you asked.
        horizon_row = conn.execute(
            "SELECT MAX(game_date) FROM team_game_results WHERE league=? AND season=?",
            (league, season),
        ).fetchone()
        horizon = (horizon_row[0] or None) if horizon_row else None
        gap = explain_gap(f"{base}/types/{type_id}/events", our_ids, horizon=horizon)
    except OracleUnreachable as e:
        rep.unreachable(name, str(e))
        return

    rep.check(
        f"{league} {season} games in team_game_results",
        len(our_ids), gap.expected, describe_gap(gap),
    )
    report_gap(rep, f"{league} {season}", gap)

    # `name` says REGULAR-SEASON games, and `gap.expected` is the regular-season type's
    # count, so the query has to name the phase too — otherwise the moment a league's
    # playoff logs land, this reports the postseason as a surplus of regular-season
    # games and demotes a season that just got MORE complete.
    #
    # Where no row carries a phase we count everything and say so. That is not the
    # column-presence mistake: this asks what the VALUES hold, and when they hold
    # nothing it labels the answer phase-blind rather than passing a laxer question
    # off as the strict one.
    phased = db_count(
        conn,
        "SELECT COUNT(*) FROM player_game_logs WHERE league=? AND season=?"
        " AND game_type IS NOT NULL",
        (league, season),
    )
    ours = db_count(
        conn,
        "SELECT COUNT(DISTINCT game_id) FROM player_game_logs WHERE league=? AND season=?"
        + (" AND game_type='REG'" if phased else ""),
        (league, season),
    )
    rep.check(name, ours, gap.expected,
              "distinct game_id" if phased else "distinct game_id, PHASE-BLIND (no row carries game_type)")
    if ours < gap.expected:
        _blame_the_key_before_the_data(conn, rep, league, season)


def _blame_the_key_before_the_data(
    conn: sqlite3.Connection, rep: Report, league: str, season: int
) -> None:
    """A short count has two causes. Say which one before anyone acts on it.

    `nhl 2026 ... ours=0 published=1312` was printed for a season whose 1,312
    games were all present — under `season=20252026`, because `ingest_nhl_logs`
    stored nhle.com's key verbatim. Read literally, that line said "we have no
    NHL data"; it meant "we asked in the wrong vocabulary". Anyone acting on the
    first reading would have re-run a 48,000-row ingest to fix a WHERE clause.

    So: before a shortfall is attributed to missing rows, check whether the rows
    are sitting under a season key we did not ask for. This costs one indexed
    GROUP BY and it is the difference between a diagnosis and a guess.
    """
    other = [
        (k, n) for k, n in conn.execute(
            "SELECT season, COUNT(DISTINCT game_id) FROM player_game_logs"
            " WHERE league=? AND season IS NOT NULL AND season != ? GROUP BY season",
            (league, season),
        )
    ]
    if not other:
        return
    detail = ", ".join(f"season={k!r} holds {n} games" for k, n in sorted(other))
    rep.note(
        "  KEY SPLIT",
        f"{league} also has player_game_logs rows under other season keys — "
        f"{detail}. A short count here may be a vocabulary mismatch, not missing "
        f"data. See backend/season_keys.py.",
    )


def write_coverage(conn: sqlite3.Connection, rep: Report, league: str, season: int) -> str:
    """Write this (league, season)'s verdict into the enablement registry.

    This is the only writer of team_stats_coverage. It lives here, and not in the
    ingest, for one reason: the ingest's expectation of itself is its own output.
    `backfill_team_parity.run_league()` wrote
    `expected_games = fetched_games = paired_games = games_written` and a hardcoded
    `failure_count=0`, and so reported `complete` over a season missing four games —
    while the reasons those four failed sat in team_stats_ingestion_failures.

    Every number below comes from somewhere the run does not control: the publisher,
    or a separate SELECT over what actually landed.
    """
    status = rep.verdict(league, season)

    # The coverage row names the INGEST run it is judging, not this reconcile. That is
    # what makes `failure_count` checkable by anyone else:
    #   SELECT COUNT(*) FROM team_stats_ingestion_failures WHERE run_id = coverage.run_id
    # must equal it. Point the row at a run_id nothing was recorded under and the
    # column becomes unfalsifiable again, which is the whole defect.
    ingest_run = conn.execute(
        "SELECT run_id FROM team_game_stats WHERE league=?"
        " ORDER BY captured_at DESC LIMIT 1", (league,)
    ).fetchone()
    run_id = ingest_run[0] if ingest_run else (
        f"{league}-reconcile-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )

    def count(sql: str, args=()) -> int:
        try:
            return db_count(conn, sql, args)
        except sqlite3.Error:
            return 0

    fetched_games = count(
        "SELECT COUNT(DISTINCT game_id) FROM team_game_results WHERE league=? AND season=?",
        (league, season),
    )
    paired_games = count(
        "SELECT COUNT(*) FROM (SELECT game_id FROM team_game_results"
        " WHERE league=? AND season=? GROUP BY game_id HAVING COUNT(DISTINCT team)=2)",
        (league, season),
    )
    paired_stat_games = count(
        "SELECT COUNT(*) FROM (SELECT game_id FROM team_game_stats"
        " WHERE league=? GROUP BY game_id HAVING COUNT(DISTINCT team_abbrev)=2)",
        (league,),
    )
    fetched_teams = count(
        "SELECT COUNT(DISTINCT team) FROM team_game_results WHERE league=? AND season=?",
        (league, season),
    )
    fetched_players = count(
        "SELECT COUNT(DISTINCT player_id) FROM player_game_logs"
        " WHERE league=? AND season=? AND player_id IS NOT NULL",
        (league, season),
    )
    # The integrity count the column-presence guard in routers/nfl_offseason.py missed:
    # a column can exist, be filtered on, and hold nothing but NULLs.
    null_key_rows = count(
        "SELECT COUNT(*) FROM player_game_logs WHERE league=? AND season=?"
        " AND (game_type IS NULL OR team IS NULL OR game_id IS NULL)",
        (league, season),
    )
    if null_key_rows:
        status = "partial" if status == "complete" else status

    expected_games = _expected_games_from_report(rep, league, season, fetched_games)
    window_start, window_end = _published_season_window(league, season)

    # `checked_through` is what the row actually claims: every published game from
    # season_start up to this date is present and paired. Not "as of now" — as of the
    # last game we hold.
    checked_row = conn.execute(
        "SELECT MAX(game_date) FROM team_game_results WHERE league=? AND season=?",
        (league, season),
    ).fetchone()
    checked_through = (checked_row[0] or None) if checked_row else None

    # A season that passes every check but has not ended yet is `in_progress`, not
    # `complete`. Keeping them apart is the point: `complete` means the season is over
    # AND fully checked, and a caller that offers only `complete` would otherwise be
    # told a September-ending season was finished in August. It also stops the row
    # from having to lie in order to be offerable.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if status == "complete" and window_end and today <= window_end:
        status = "in_progress"

    # READ, never asserted. The previous writer passed a literal 0 here while the
    # same function was inserting rows into this exact table.
    failure_count = count(
        "SELECT COUNT(*) FROM team_stats_ingestion_failures WHERE run_id=?", (run_id,)
    )
    if failure_count and status == "complete":
        status = "partial"

    conn.execute("DELETE FROM team_stats_coverage WHERE league=? AND season=?",
                 (league, season))
    cov_columns = {r[1] for r in conn.execute("PRAGMA table_info(team_stats_coverage)")}
    cols = ("run_id,league,season,season_start,season_end,status,expected_teams,"
            "fetched_teams,expected_games,fetched_games,paired_games,paired_stat_games,"
            "failure_count,completed_at,source")
    vals = [run_id, league, season, window_start, window_end, status,
            fetched_teams, fetched_teams,
            expected_games, fetched_games, paired_games, paired_stat_games,
            failure_count,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reconcile_totals+espn_core_api"]
    # Tolerate a database that predates the column rather than refusing to write the
    # row: an older prod schema should degrade to the previous behaviour, not fail.
    if "checked_through" in cov_columns:
        cols += ",checked_through"
        vals.append(checked_through)
    conn.execute(
        f"INSERT INTO team_stats_coverage({cols}) "
        f"VALUES({','.join('?' * len(vals))})",
        vals,
    )
    conn.commit()
    return status


def _published_season_window(league: str, season: int) -> Tuple[str, str]:
    """The season's date window, read from `seasons/<year>` — never from our own rows.

    `season_start`/`season_end` are NOT NULL, and the first draft of this writer passed
    `None, None` for both, which raised on the very first row it tried to write. The
    tempting repair is `MIN(game_date)/MAX(game_date)` over `team_game_results` — but
    that answers "when did the games we happen to hold start", which is the ingest
    describing its own output again, the exact defect this function exists to prevent.
    A season missing its first week would silently redefine when the season began.

    The regular-season type publishes `startDate`/`endDate`; a single-type competition
    (soccer) publishes them on its one type. Both are already in the document
    `season_types()` fetched, so this costs no extra request.
    """
    types = season_types(league, season)
    chosen = None
    for key, value in types.items():
        if "regular" in key:
            chosen = value
            break
    if chosen is None:
        # No phase named "regular": either one type IS the season, or the league names
        # its phases differently. Take the widest published window over real types —
        # an empty type (MLS "Combined", 0 events) publishes no useful dates.
        dated = [v for v in types.values() if v.get("startDate") and v.get("endDate")]
        if not dated:
            raise OracleUnreachable(
                f"{league} {season} publishes no season type with dates"
            )
        starts = min(str(v["startDate"]) for v in dated)
        ends = max(str(v["endDate"]) for v in dated)
        return starts[:10], ends[:10]
    start, end = chosen.get("startDate"), chosen.get("endDate")
    if not start or not end:
        raise OracleUnreachable(
            f"{league} {season} regular-season type publishes no date range"
        )
    return str(start)[:10], str(end)[:10]


def _expected_games_from_report(rep: Report, league: str, season: int, fallback: int) -> int:
    """The publisher's expected total, recovered from the check that read it.

    Falls back to what landed only when no games check ran — and in that case the
    verdict is already `unverified`, so the number is never load-bearing.
    """
    needle = f"{league} {season} games in team_game_results"
    for _status, name, detail, _note in rep.rows:
        if name == needle:
            m = re.search(r"published=(\d+)", detail)
            if m:
                return int(m.group(1))
    return fallback


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", choices=sorted(ESPN_PATH), action="append")
    ap.add_argument("--season", type=int, action="append")
    ap.add_argument("--sample", type=int, default=25, help="players to spot-check per season")
    ap.add_argument(
        "--write-coverage",
        action="store_true",
        help="write the verdict into team_stats_coverage (opens the db read-write)",
    )
    args = ap.parse_args()

    if not os.path.exists(DB):
        print(f"no database at {DB}", file=sys.stderr)
        return 1

    _log(f"run start: db={DB} leagues={args.league or 'all'} "
         f"seasons={args.season or 'all'} write_coverage={args.write_coverage} "
         f"pace={_MIN_INTERVAL}s cache={len(_DISK)} events")
    if args.write_coverage:
        conn = sqlite3.connect(DB, timeout=60)
    else:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rep = Report()

    leagues = args.league or ["nfl"]
    checked: List[Tuple[str, int]] = []
    for league in leagues:
        seasons = args.season or [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT season FROM player_game_logs WHERE league=? ORDER BY season",
                (league,),
            )
        ]
        for season in seasons:
            rep.scope(league, season)
            checked.append((league, season))
            if league == "nfl":
                check_nfl(conn, rep, season, args.sample)
            else:
                check_generic(conn, rep, league, season)

    print(f"reconcile_totals — db={DB}\n")
    print(rep.render())
    print()

    if args.write_coverage:
        print("coverage:")
        for league, season in checked:
            status = write_coverage(conn, rep, league, season)
            print(f"  {league} {season} -> {status}")
            _log(f"coverage written: {league} {season} -> {status}")
        print()

    if rep.failed:
        verdict = f"FAIL — {rep.failed} check(s) disagree with the published total or had no oracle"
        print(verdict)
        _log(verdict)
        return 1
    print("PASS — every stored total matches the publisher")
    _log("PASS — every stored total matches the publisher")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # Flush what this run learned even when it failed or was interrupted --
        # a killed run that discards 40 minutes of fetches is how the same slow
        # loop repeats.
        _disk_flush()
