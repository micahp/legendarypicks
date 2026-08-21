#!/usr/bin/env python3
"""Shared per-match soccer player logs from ESPN. MLS first; EPL inherits.

The props chart and the game log read ``player_game_logs``. This script
enumerates a soccer season's *published* phases (``seasons/<year>/types[]``)
from the core API, fetches each completed match's summary, extracts each
participant's goals, assists, shots and shots on target, and links the ESPN
athlete to an existing player by normalized name. Unresolved athletes are
retained with ``player_id=NULL`` so they can be re-resolved on a later
idempotent run without creating duplicates.

Modeled on ``ingest_wc_logs.py``, which already handles ESPN's soccer summary
shape and stat mapping. Three things there are deliberately NOT carried over
(see TASK-league-mls.md and docs/DATA-COVERAGE-CONTRACT.md §6):

1. ``season = int(game_date[:4])`` — a season key inferred from a date string.
   It happens to work for the World Cup and for MLS, and it is wrong for EPL,
   where a match played in January 2026 belongs to season 2025. The season key
   here comes from the CLI argument and is verified against the published
   type's ``startDate``/``endDate`` window, with a warning on disagreement.
2. No ``game_type`` written (all 3,222 wc rows are NULL). Every row written
   here carries ``game_type`` NOT NULL, mapped from the published type's own
   name: ``REG`` for the regular season, ``ALLSTAR`` for the All-Star Game,
   ``POST`` for everything else (MLS files its postseason as per-conference
   wild cards, rounds, semis, finals and the MLS Cup).
3. Enumerated by date window. Here the set of matches ingested is the set the
   publisher says exists: each published type's own ``events`` collection is
   paged and ingested. An empty published collection (e.g. MLS type 0
   "Combined", 0 events) is a fact, not a failure — it is skipped, not raised.

Usage:
  python3 ingest_soccer_logs.py --league mls --season 2025
  python3 ingest_soccer_logs.py --league mls --season 2025 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from typing import Dict, List, Optional, Tuple

import paced_http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client as espn  # noqa: E402
import team_codes  # noqa: E402
from _core import _normalize_name  # noqa: E402
from espn_leagues import ESPN_LEAGUES  # noqa: E402
from game_types import ALLSTAR, POST, REG  # noqa: E402
from ingest_nfl_logs import ensure_table  # noqa: E402
from publisher_capture import capture_payload, require_publisher_capture_schema  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

# sports.core.api answers collections per request and 403s a burst with no
# Retry-After (measured 2026-08-02 in reconcile_totals.py). Pace every core
# request and cache in memory; the season and type documents are immutable
# within a run, so re-fetching them per type is wasted work.
CORE = "https://sports.core.api.espn.com/v2/sports"
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
_MIN_INTERVAL = float(os.environ.get("LP_INGEST_MIN_INTERVAL") or 0.5)

# The shared client replaces this module's hand-rolled _throttle/_last_request
# and its _CACHE dict: pacing is _MIN_INTERVAL (same env knob), the memory
# cache is the Fetcher's (same "immutable within a run" guarantee, 12h ttl),
# and the retry ladder stays in the module so the 403 fail-fast posture is
# decided here, not inherited.
_FETCH = paced_http.Fetcher(min_interval=_MIN_INTERVAL, retry_waits=(),
                            headers=_HDRS, timeout=30)

# Everything ESPN publishes per player on a soccer summary, not the four we happened to
# need first. Measured on the MLS summary for event 727308 (2026-08-16): all 40 players in
# the match carried 15 named stats, and this table read 4 of them. The other 11 were not
# missing data -- they were data we never asked for, which is the shape described in
# published-first §3: a gap is a statement about which endpoint we asked.
#
# The cost of the omission was concrete. Bovada prices "To be Shown a Card" on this league;
# with no card column that prop cannot be settled, so it could not be ingested, so the
# board was missing a market the publisher already gave us the answer for.
#
# Keys are the folded form (_key strips non-alphanumerics and lowercases), so "goalAssists"
# and "Goal Assists" and "GA" all land on the same target.
_TARGET_STATS = {
    "goals": {"g", "goal", "goals", "totalgoals"},
    "assists": {"a", "assist", "assists", "goalassists"},
    "shots": {"sh", "shot", "shots", "totalshots"},
    "sot": {"sog", "sot", "shotsongoal", "shotsontarget"},
    "yellow_cards": {"yc", "yellowcards", "yellowcard"},
    "red_cards": {"rc", "redcards", "redcard"},
    "fouls_committed": {"fc", "foulscommitted"},
    "fouls_suffered": {"fa", "foulssuffered"},
    "offsides": {"of", "offsides", "offside"},
    "own_goals": {"og", "owngoals", "owngoal"},
    "saves": {"sv", "saves", "save"},
    "shots_faced": {"shf", "shotsfaced"},
    "goals_conceded": {"ga", "goalsconceded"},
    "appearances": {"app", "appearances"},
    "sub_ins": {"subins", "subin", "sub"},
}

# Written in this order so a stored row reads the way a box score does.
_STAT_ORDER = ("goals", "assists", "shots", "sot", "yellow_cards", "red_cards",
               "fouls_committed", "fouls_suffered", "offsides", "own_goals",
               "saves", "shots_faced", "goals_conceded", "appearances", "sub_ins")


def _key(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _number(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _target_line(raw_stats) -> dict:
    """Normalize either ESPN stat objects or a name->value mapping."""
    values = {}
    if isinstance(raw_stats, dict):
        items = raw_stats.items()
    else:
        items = (
            (stat.get("name") or stat.get("abbreviation"), stat)
            for stat in (raw_stats or [])
            if isinstance(stat, dict)
        )
    for raw_name, raw_value in items:
        name = _key(raw_name)
        for target, aliases in _TARGET_STATS.items():
            if name in aliases:
                value = _number(raw_value)
                if value is not None:
                    values[target] = value
                break
    if not values:
        return {}
    return {name: values.get(name, 0) for name in _STAT_ORDER}


def _appeared(raw_stats) -> bool:
    """Exclude unused reserves when ESPN exposes an appearances=0 marker."""
    for stat in raw_stats or []:
        if not isinstance(stat, dict) or _key(stat.get("name")) != "appearances":
            continue
        value = _number(stat)
        return value is None or value > 0
    return True


def _boxscore_players(summary: dict):
    """Yield player lines from ESPN's generic boxscore.players contract."""
    for block in (summary.get("boxscore") or {}).get("players", []):
        team = (block.get("team") or {}).get("abbreviation") or ""
        home_away = block.get("homeAway")
        for stat_group in block.get("statistics", []):
            names = stat_group.get("names") or stat_group.get("labels") or []
            for row in stat_group.get("athletes", []):
                if row.get("didNotPlay"):
                    continue
                athlete = row.get("athlete") or {}
                athlete_id = athlete.get("id") or row.get("id")
                name = athlete.get("displayName") or athlete.get("fullName")
                raw = dict(zip(names, row.get("stats") or []))
                stats = _target_line(raw)
                if athlete_id and name and stats:
                    yield str(athlete_id), name, team, home_away, stats


# A stat that only the widened extractor writes. A row missing it was written by the
# 4-stat version and must be re-fetched; a row carrying it is current.
_FRESHNESS_KEY = "yellow_cards"


def _already_ingested(con, league: str, season: int, game_id: str) -> bool:
    """True when this match is already stored at the current stat shape."""
    row = con.execute(
        "SELECT stats FROM player_game_logs "
        "WHERE league=? AND season=? AND game_id=? AND stats IS NOT NULL LIMIT 1",
        (league, season, game_id)).fetchone()
    if not row:
        return False
    try:
        return _FRESHNESS_KEY in json.loads(row[0])
    except (TypeError, ValueError):
        return False


def _first_goal_scorer(summary: dict):
    """(athlete_id of the match's first goal, whether ESPN published its events).

    Bovada prices "First Goal Scorer" -- 332 outcomes on the MLS board, the third biggest
    player market it publishes -- and a box score cannot settle it, because a box score has
    no order. ESPN's summary does: `keyEvents` carries each Goal with the scorer in
    `participants[0].athlete.id` and a clock, so the question is answerable from a document
    we were already fetching for the stat lines.

    The second return value is what keeps this honest. If ESPN published no events for a
    match, every player would otherwise be written `first_goal: 0` and settlement would
    grade the whole market as losing -- a fabricated answer, indistinguishable from a real
    one. Absent events mean the key is omitted entirely so the prop VOIDS instead, which is
    the rule fb0927b established for an absent stat.

    A match ESPN did cover in which nobody scored is a different fact: events published,
    first scorer None, everyone correctly 0.
    """
    events = summary.get("keyEvents")
    if not isinstance(events, list) or not events:
        return None, False
    goals = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if (event.get("type") or {}).get("text") != "Goal":
            continue
        # A shootout goal does not count toward the match's goalscorer markets, and an
        # unattributed goal (own goal) has no scorer to credit.
        if not event.get("scoringPlay") or event.get("shootout"):
            continue
        participants = event.get("participants") or []
        athlete = None
        if participants and isinstance(participants[0], dict):
            athlete = (participants[0].get("athlete") or {}).get("id")
        if not athlete:
            continue
        period = (event.get("period") or {}).get("number") or 0
        clock = (event.get("clock") or {}).get("value")
        goals.append(((period, clock if clock is not None else 0.0), str(athlete)))
    if not goals:
        return None, True
    goals.sort(key=lambda g: g[0])
    return goals[0][1], True


def _roster_players(summary: dict):
    """Yield player lines from ESPN soccer summaries (the current WC shape)."""
    for block in summary.get("rosters", []):
        team = (block.get("team") or {}).get("abbreviation") or ""
        home_away = block.get("homeAway")
        for row in block.get("roster", []):
            raw_stats = row.get("stats") or []
            if not raw_stats or not _appeared(raw_stats):
                continue
            athlete = row.get("athlete") or {}
            athlete_id = athlete.get("id") or row.get("id")
            name = athlete.get("displayName") or athlete.get("fullName")
            stats = _target_line(raw_stats)
            if athlete_id and name and stats:
                yield str(athlete_id), name, team, home_away, stats


def _get_core(url: str, attempts: int = 4, capture=None) -> dict:
    """Paced, cached fetch of one sports.core.api document.

    The request goes through the shared Fetcher (pacing + per-host count +
    spend log); the retry ladder stays here so a refusal is waited out only
    as many times as this module decides.
    """
    last = None
    for i in range(attempts):
        try:
            payload = _FETCH.json(url)
            if capture is not None:
                capture(url, payload)
            return payload
        except Exception as e:  # noqa: BLE001 - any failure is retried
            last = e
            time.sleep(min(60, 1.5 * (i + 1)))
    raise RuntimeError(f"{url} failed after {attempts} attempts: {last}")


def _summary_retry(league: str, game_id: str, attempts: int = 4) -> dict:
    """espn.summary with retry/backoff.

    espn_client's shared fetcher deliberately has empty retry_waits (a page
    load must not sit through a ladder), but a season ingest is a batch job:
    a single 403 from the low-trust bucket is worth waiting out, not worth
    skipping the game. Measured 2026-08-06: the wall tripped mid-run and the
    ingest burned the rest of the season printing 403s per event.
    """
    last = None
    for i in range(attempts):
        try:
            return espn.summary(league, game_id)
        except Exception as e:  # noqa: BLE001 - any failure is retried
            last = e
            time.sleep(min(60, 2.0 * (i + 1)))
    raise RuntimeError(f"summary {game_id} failed after {attempts} attempts: {last}")


def _summary_endpoint(league: str, game_id: str) -> str:
    """The exact publisher URL that supplied a summary body."""
    _, path = espn._check(league)
    return espn._SITE.format(path=path) + f"/summary?event={game_id}"


def _capture_espn_payload(connection: sqlite3.Connection, league: str,
                           endpoint: str, payload: dict) -> tuple[int, bool]:
    """Record one complete ESPN source body before extracting product fields.

    The caller has already verified the explicit capture migration.  Keeping
    this in the same transaction as the derived log makes it impossible for a
    successful ingest to retain a product row while discarding the document
    that supplied it.
    """
    return capture_payload(
        connection,
        source="espn",
        league=league,
        endpoint=endpoint,
        payload=payload,
    )


def _capture_summary(connection: sqlite3.Connection, league: str,
                     game_id: str, payload: dict) -> tuple[int, bool]:
    return _capture_espn_payload(
        connection, league, _summary_endpoint(league, game_id), payload
    )


def _core_path(league: str) -> str:
    """The league's core API path from the espn_leagues registry."""
    entry = ESPN_LEAGUES.get(league)
    if not entry:
        raise ValueError(
            f"no espn_leagues registry entry for {league!r}; add "
            f"'path' to backend/espn_leagues.py before ingesting it"
        )
    return entry["path"]


def _team_code(league: str, abbrev: Optional[str]) -> str:
    """Canonical team code via team_codes when the league's vocabulary exists.

    The mls vocabulary is landing in the same wave as this ingest, so an
    unrecognised league or code must not block a run: fall back to the ESPN
    abbreviation passed through unchanged. The All-Star Game's opponent is
    sometimes not an MLS club at all, so even a populated vocabulary can
    legitimately fail to recognise a competitor.
    """
    if not abbrev:
        return ""
    try:
        return team_codes.normalize(league, abbrev)
    except Exception:  # noqa: BLE001 - boundary must not block the ingest
        return str(abbrev).upper()


def _published_types(league: str, season: int, capture=None) -> Tuple[str, List[dict]]:
    """(displayName, [type, ...]) straight from the publisher.

    Reads the season document's ``types[]`` — the published list, never a
    range of ids — and each type's own document for its ``startDate``/
    ``endDate`` window when the season document does not inline it.
    """
    doc = _get_core(f"{CORE}/{_core_path(league)}/seasons/{season}", capture=capture)
    display_name = doc.get("displayName") or ""
    items = ((doc.get("types") or {}).get("items")) or []
    if not items:
        raise RuntimeError(f"{league} {season} publishes no season types")
    types = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ref = item.get("$ref") or ""
        m = re.search(r"/types/([^/]+)", ref)
        type_id = str(item.get("id") or (m.group(1) if m else "")).strip()
        name = str(item.get("name") or "")
        start = str(item.get("startDate") or "")
        end = str(item.get("endDate") or "")
        if ref and not (name and start and end):
            type_doc = _get_core(ref, capture=capture)
            name = name or str(type_doc.get("name") or "")
            start = start or str(type_doc.get("startDate") or "")
            end = end or str(type_doc.get("endDate") or "")
        types.append({
            "id": type_id,
            "name": name,
            "startDate": start[:10],
            "endDate": end[:10],
        })
    return display_name, types


def _game_type_for_type(type_doc: dict) -> str:
    """Our phase for one published soccer season type, from its own name.

    The vocabulary is game_types.py's ``REG | POST | ALLSTAR``. Mapping is by
    name, not id: MLS publishes a *different* id layout than EPL and than any
    measured basketball/baseball league, and DATA-COVERAGE-CONTRACT §6 forbids
    hardcoding ids. MLS files its All-Star Game as its own type (id 2), so
    every remaining non-regular-season type is a knockout phase — POST.
    """
    name = str(type_doc.get("name") or "").lower()
    if "all-star" in name or "allstar" in name:
        return ALLSTAR
    if "regular season" in name:
        return REG
    return POST


def _type_events(league: str, season: int, type_id: str, capture=None) -> List[str]:
    """Every event id in one published type's collection, from the $refs.

    One request per page at limit=100 (the project's pacing ceiling — smaller
    pages keep each response light and the 0.5s+ floor between requests is the
    real protection against ESPN's 403 wall); the id is already in the URL, so no
    per-event fetch is needed to enumerate (same pattern as
    reconcile_totals.published_event_ids).
    """
    url = f"{CORE}/{_core_path(league)}/seasons/{season}/types/{type_id}/events"
    out: List[str] = []
    page = 1
    while True:
        doc = _get_core(f"{url}?limit=100&page={page}", capture=capture)
        for item in doc.get("items", []):
            m = re.search(r"/events/(\d+)", item.get("$ref", ""))
            if m:
                out.append(m.group(1))
        if page >= int(doc.get("pageCount", 1) or 1):
            return out
        page += 1


def _verify_season(season: int, type_doc: dict) -> None:
    """Warn, never raise, when the CLI season contradicts the published window.

    MLS is a calendar-year season, so its key is the year the season starts;
    EPL spans two calendar years and ESPN keys it by the year it starts too.
    The key is written from the CLI argument — the caller's explicit choice —
    and the published ``startDate`` exists to catch a wrong one out loud.
    """
    start = str(type_doc.get("startDate") or "")[:4]
    if not start.isdigit():
        return
    if int(start) != int(season):
        print(
            f"  WARNING: {type_doc.get('name') or type_doc.get('id')} window starts "
            f"{start}, CLI season is {season} — the season key may be wrong"
        )


class SoccerPlayerResolver:
    """Resolve ESPN names to existing players without fabricating rows.

    The same tiers as WCPlayerResolver, scoped to the league being ingested
    (``players WHERE league=?``) so a shared soccer ingest never resolves an
    MLS athlete against a WC roster or vice versa.
    """

    def __init__(self, con: sqlite3.Connection, league: str, allowed_player_ids=None):
        try:
            self.rows = [dict(row) for row in con.execute(
                "SELECT id, name, team FROM players WHERE league=?", (league,)
            )]
        except sqlite3.OperationalError:
            # No players table (e.g. a bare dry-run DB): resolve nothing,
            # retain every athlete unresolved rather than inventing ids.
            print(f"  note: no players table — every {league} athlete stays unresolved")
            self.rows = []
        if allowed_player_ids is not None:
            allowed = {int(player_id) for player_id in allowed_player_ids}
            self.rows = [
                row for row in self.rows if int(row["id"]) in allowed
            ]
        for row in self.rows:
            row["name_norm"] = _normalize_name(row["name"])
            row["team_norm"] = (row.get("team") or "").upper()

    @staticmethod
    def _unique(rows, team):
        if team:
            team_rows = [row for row in rows if row["team_norm"] == team.upper()]
            if len(team_rows) == 1:
                return team_rows[0]["id"]
            if team_rows:
                rows = team_rows
        return rows[0]["id"] if len(rows) == 1 else None

    def resolve(self, name: str, team: str):
        normalized = _normalize_name(name)
        exact = [row for row in self.rows if row["name_norm"] == normalized]
        resolved = self._unique(exact, team)
        if resolved is not None:
            return resolved

        # Some prop-ingested names are clipped by one or more trailing letters
        # (e.g. "Alexis Mac Alliste"). Accept only a unique, team-scoped prefix.
        if len(normalized) < 7:
            return None
        prefix = [
            row for row in self.rows
            if len(row["name_norm"]) >= 7
            and (normalized.startswith(row["name_norm"]) or row["name_norm"].startswith(normalized))
        ]
        resolved = self._unique(prefix, team)
        if resolved is not None:
            return resolved

        # ESPN sometimes uses a short first name while the prop feed uses the
        # formal form ("Nico Gonzalez" vs "Nicolas Gonzalez"). Require the
        # same team, exact surname, and a first-name prefix so this cannot join
        # unrelated players who merely share a surname.
        parts = normalized.split()
        if not team or len(parts) < 2 or len(parts[0]) < 3:
            return None
        nickname = [
            row for row in self.rows
            if row["team_norm"] == team.upper()
            and len(row["name_norm"].split()) >= 2
            and row["name_norm"].split()[-1] == parts[-1]
            and (
                row["name_norm"].split()[0].startswith(parts[0])
                or parts[0].startswith(row["name_norm"].split()[0])
            )
        ]
        if len(nickname) == 1:
            return nickname[0]["id"]

        # Feed names can combine a nickname with a clipped surname while ESPN
        # uses the formal first name ("Alex Grimald" vs
        # "Alejandro Grimaldo"). Allow that only when the team, first initial,
        # and a surname prefix of at least five characters identify one row.
        initial_surname = []
        for row in self.rows:
            row_parts = row["name_norm"].split()
            if (
                row["team_norm"] != team.upper()
                or len(row_parts) < 2
                or row_parts[0][:1] != parts[0][:1]
            ):
                continue
            source_surname = parts[-1]
            row_surname = row_parts[-1]
            if (
                min(len(source_surname), len(row_surname)) >= 5
                and (
                    source_surname.startswith(row_surname)
                    or row_surname.startswith(source_surname)
                )
            ):
                initial_surname.append(row)
        return (
            initial_surname[0]["id"]
            if len(initial_surname) == 1
            else None
        )


def _opponent(team: str, home_away: str, home: str, away: str):
    if home_away == "home":
        return away
    if home_away == "away":
        return home
    if team and home and team.upper() == home.upper():
        return away
    if team and away and team.upper() == away.upper():
        return home
    return None


def ingest(league: str, season: int, dry_run: bool = False,
           request_budget: int = 80, force_refetch: bool = False) -> int:
    # The summary fetches below go through espn_client's shared fetcher, which
    # defaults to NO pacing (page loads must not pause). A 510-game season is
    # a batch job, and an unpaced burst is exactly what trips ESPN's 403 wall
    # with no Retry-After (measured 2026-08-06; the wall outlives short
    # backoffs). Pace the shared fetcher for the duration of the run.
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if not dry_run:
        # Check before the first publisher request. A run without the ledger
        # must not obtain season/type/event/summary bodies then throw them away.
        require_publisher_capture_schema(con)
        ensure_table(con)
    resolver = SoccerPlayerResolver(con, league=league)

    capture = None if dry_run else (
        lambda endpoint, payload: _capture_espn_payload(con, league, endpoint, payload)
    )
    espn.set_min_interval(float(os.environ.get("LP_INGEST_MIN_INTERVAL") or 0.5))
    display_name, types = _published_types(league, season, capture=capture)
    print(f"{league} {season} ({display_name or 'no published label'}): "
          f"{len(types)} published types")

    ingested = 0
    resolved = 0
    unresolved = 0
    completed_games = 0
    incomplete_events = 0
    phase_mismatches = 0
    matches_without_events = 0
    skipped_already_held = 0
    requests_spent = 0
    budget_exhausted = False
    for type_doc in types:
        type_id = type_doc.get("id") or ""
        name = type_doc.get("name") or f"type {type_id}"
        try:
            event_ids = _type_events(league, season, type_id, capture=capture)
        except Exception as exc:  # noqa: BLE001 - one type must not kill the run
            print(f"  [{type_id}] {name}: events fetch failed ({exc})")
            continue
        if not event_ids:
            # An empty published collection is a fact, not a failure: MLS
            # type 0 "Combined" publishes 0 events every season.
            print(f"  [{type_id}] {name}: 0 events — published empty, nothing to ingest")
            continue
        _verify_season(season, type_doc)
        game_type = _game_type_for_type(type_doc)
        type_logs = 0
        type_games = 0
        type_resolved = 0
        type_unresolved = 0
        for event_id in event_ids:
            game_id = str(event_id)

            # Already held at the current stat shape? Then this match costs nothing.
            #
            # Every run used to re-fetch every completed match's summary whether or not we
            # already had it, so re-running a season was always full price -- 511 requests
            # for MLS 2026. ESPN's limit is a COUNT per host (~100 measured), so a full
            # season could not complete in one run and a resumed run started from zero
            # again. Skipping what is already stored makes the backfill chunkable: each run
            # spends its budget on matches nobody has fetched yet.
            #
            # The freshness key is a stat introduced with the widened set. A row written by
            # the old 4-stat version does not carry it, so widening re-fetches exactly the
            # matches that need it and nothing else.
            if not force_refetch and _already_ingested(con, league, season, game_id):
                skipped_already_held += 1
                continue

            if requests_spent >= request_budget:
                budget_exhausted = True
                break

            try:
                requests_spent += 1
                summary = _summary_retry(league, game_id)
            except Exception as exc:  # noqa: BLE001
                print(f"    {league} {season} [{type_id}] event {game_id}: "
                      f"summary failed ({exc})")
                continue

            if not dry_run:
                # This is intentionally before finality and stat extraction:
                # a scheduled/cancelled summary is still publisher evidence,
                # and every field outside our current mapping remains useful.
                _capture_summary(con, league, game_id, summary)

            header = summary.get("header") or {}
            comp = (header.get("competitions") or [{}])[0]
            status_type = ((comp.get("status") or {}).get("type")) or {}
            if not status_type.get("completed"):
                incomplete_events += 1
                continue

            # Read the phase the envelope publishes and say so when it
            # disagrees with the collection we enumerated it from — the same
            # "stamp the data, not the URL" discipline as game_types.py.
            envelope_season = header.get("season") or comp.get("season") or {}
            envelope_type = str(envelope_season.get("type") or "")
            if envelope_type and envelope_type != str(type_id):
                phase_mismatches += 1
                print(f"    event {game_id}: envelope files season.type={envelope_type}, "
                      f"enumerated from type {type_id} — written as {game_type}")

            # Support both the generic contract and ESPN's current soccer
            # roster contract. Roster rows win if both exist.
            player_lines = {}
            for line in _boxscore_players(summary):
                player_lines[line[0]] = line
            for line in _roster_players(summary):
                player_lines[line[0]] = line

            first_scorer, goal_events_published = _first_goal_scorer(summary)
            if goal_events_published:
                for athlete_id, line in player_lines.items():
                    line[4]["first_goal"] = 1 if athlete_id == first_scorer else 0
            else:
                matches_without_events += 1

            competitors = {}
            for competitor in comp.get("competitors", []):
                team = (competitor.get("team") or {})
                competitors[competitor.get("homeAway")] = _team_code(
                    league, team.get("abbreviation")
                )
            home = competitors.get("home") or ""
            away = competitors.get("away") or ""
            game_date = str(comp.get("date") or "")[:10] or None

            for athlete_id, name, team, home_away, stats in player_lines.values():
                team = _team_code(league, team)
                if not home_away:
                    if team and home and team.upper() == home.upper():
                        home_away = "home"
                    elif team and away and team.upper() == away.upper():
                        home_away = "away"
                player_id = resolver.resolve(name, team)
                if player_id is None:
                    unresolved += 1
                    type_unresolved += 1
                else:
                    resolved += 1
                    type_resolved += 1
                if not dry_run:
                    con.execute(
                        """INSERT INTO player_game_logs
                           (player_id, league, season, game_no, game_id, game_date, team,
                            opponent, home_away, game_type, stats, source, source_player_key)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(league, source_player_key, season, game_no) DO UPDATE SET
                             player_id=excluded.player_id,
                             game_id=excluded.game_id,
                             game_date=excluded.game_date,
                             team=excluded.team,
                             opponent=excluded.opponent,
                             home_away=excluded.home_away,
                             game_type=excluded.game_type,
                             stats=excluded.stats,
                             source=excluded.source,
                             ingested_at=datetime('now')""",
                        (
                            player_id, league, season, game_id, game_id, game_date, team,
                            _opponent(team, home_away, home, away), home_away, game_type,
                            json.dumps(stats, separators=(",", ":")), "espn", athlete_id,
                        ),
                    )
                ingested += 1
                type_logs += 1
            completed_games += 1
            type_games += 1
            # Commit periodically, not just at the end: a 510-game season
            # takes 10-20 min at paced fetch rates, and ESPN's 403 wall can
            # kill the process mid-run. The INSERT is idempotent (ON
            # CONFLICT DO UPDATE), so a re-run resumes rather than duplicating
            # — but only if completed rows are already durable. Measured
            # 2026-08-06: two wall hits lost the whole run because the single
            # commit lived at the end.
            if not dry_run and (type_games % 25 == 0):
                con.commit()
            time.sleep(0.05)

        print(
            f"  [{type_id}] {name}: {len(event_ids)} published events, "
            f"{type_games} completed games, "
            f"{type_logs} player logs ({type_resolved} resolved, "
            f"{type_unresolved} unresolved)  game_type={game_type}"
        )

    if not dry_run:
        con.commit()
    try:
        total, linked = con.execute(
            "SELECT COUNT(*), COUNT(player_id) FROM player_game_logs "
            "WHERE league=? AND season=?", (league, season)
        ).fetchone()
    except sqlite3.OperationalError:
        # No player_game_logs table (dry-run against a fresh DB): the run's
        # own counters are the report; there is nothing to count yet.
        total, linked = "n/a", "n/a"
    con.close()

    print(
        f"Done. {ingested} {league} logs from {completed_games} games "
        f"({resolved} resolved rows, {unresolved} unresolved rows)"
        f"{'  [dry-run: nothing written]' if dry_run else ''}."
    )
    if incomplete_events:
        print(f"  {incomplete_events} published events not completed — not written")
    if phase_mismatches:
        print(f"  {phase_mismatches} events whose envelope phase disagreed with "
              f"their enumerated type (written under the enumerated type)")
    # Printed even at zero: a first_goal that is absent because ESPN published no events
    # and a first_goal that is absent because nobody looked are the same silence otherwise.
    print(f"  {matches_without_events} of {completed_games} matches published no keyEvents"
          f" — first_goal omitted so those props void rather than grade as losses")
    print(f"  {requests_spent} summary requests spent on site.web.api"
          f" (budget {request_budget}); {skipped_already_held} matches already held")
    if budget_exhausted:
        print(f"  BUDGET EXHAUSTED — stopped at {request_budget} requests with matches "
              f"still unfetched. ESPN's limit is a COUNT per host, so this run stopped on "
              f"purpose rather than discovering the wall. Re-run to continue; matches "
              f"already stored are skipped and cost nothing.")
    print(f"{league} {season} table now has {total} logs, {linked} linked.")
    return ingested


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Ingest per-match soccer player logs from ESPN by season type."
    )
    ap.add_argument("--league", default="mls",
                    help="ESPN soccer league key (mls today, epl later)")
    ap.add_argument("--season", type=int, required=True,
                    help="Season key to ingest (e.g. 2025 for MLS)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch, resolve and report without writing any rows")
    ap.add_argument("--request-budget", type=int, default=80,
                    help="Stop after this many summary requests to site.web.api. ESPN's "
                         "limit is a COUNT per host (~100 measured), so a season is "
                         "ingested over several runs; already-stored matches are free.")
    ap.add_argument("--force-refetch", action="store_true",
                    help="Re-fetch matches already stored (use after changing what is "
                         "extracted from the summary)")
    args = ap.parse_args()
    raise SystemExit(ingest(args.league, args.season, args.dry_run,
                            args.request_budget, args.force_refetch))
