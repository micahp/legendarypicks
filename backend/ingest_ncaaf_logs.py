#!/usr/bin/env python3
"""Ingest NCAAF (college football) FBS player logs from ESPN.

Scope
-----
The FBS subdivision only: events are enumerated from the published group
``80`` under the season's regular-season type, and the group id is read from
``espn_leagues.ESPN_LEAGUES`` rather than hardcoded. FCS (group 81) is a
different subdivision -- an FCS row in the FBS denominator is a coverage bug --
and the postseason (a separate published type, covering bowls and the playoff)
is out of scope for this ingest. Both would need their own enumeration and
their own game-type stamp.

The regular-season type id is found by name from the season document's
published ``types[]`` (the 2025 document names id 2 "Regular Season"), never
assumed. ``game_type`` is stamped NOT NULL from that type -- ``REG`` here,
since this ingest only ever processes the regular-season type.

Player lines come from each completed game's ESPN summary boxscore, the
football shape: players grouped by team, then by stat group, with
``labels``/``keys`` describing the published columns and a parallel ``stats``
array of values. Only the published offensive columns mapped in ``_STAT_MAP``
are kept, and a line's stats JSON holds exactly the keys that appear -- a
QB who only threw has no ``rec``/``rush_yds`` keys. Athletes spanning several
stat groups (e.g. a dual-threat QB in passing, rushing and fumbles) are merged
into one line per game.

Idempotent: rows key on UNIQUE(league, source_player_key, season, game_no), so
a re-run after new players land re-links previously unresolved rows (kept with
``player_id=NULL``) without creating duplicates. The players table may hold no
ncaaf rows yet; every athlete is then retained unresolved for a later run.

Usage:
  python3 ingest_ncaaf_logs.py --season 2025
  python3 ingest_ncaaf_logs.py --season 2025 --dry-run
"""
import argparse
import json
import os
import sqlite3
import sys
import time

import paced_http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client as espn
import team_codes
from _core import _normalize_name
from espn_leagues import ESPN_LEAGUES
from ingest_nfl_logs import ensure_table  # shared player_game_logs schema


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

LEAGUE = "ncaaf"
GROUP_ID = ESPN_LEAGUES[LEAGUE]["scope_group"]        # '80' = FBS
REGULAR_TYPE_NAME = ESPN_LEAGUES[LEAGUE]["regular_type_name"]  # "Regular Season"
LEAGUE_PATH = ESPN_LEAGUES[LEAGUE]["path"]            # football/leagues/college-football
GAME_TYPE = "REG"                                     # this ingest covers only the regular season

_CORE = "https://sports.core.api.espn.com/v2/sports/{path}"
_SITE = "https://site.web.api.espn.com/apis/site/v2/sports/{path}"
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

# The shared client for the direct fetches this module still makes (season
# type $refs, and the summary fallback): same headers and timeout as the raw
# call it replaces, and no retry ladder — the callers wrap it in their own
# retry/fallback logic and must see every attempt.
_FETCH = paced_http.Fetcher(headers=_HDRS, timeout=30, retry_waits=())

# our key <- (published stat-group name, published label), measured 2026-08-06
# against a completed 2025 FBS summary: passing labels C/ATT,YDS,AVG,TD,INT,QBR;
# rushing CAR,YDS,AVG,TD,LONG; receiving REC,YDS,AVG,TD,LONG.
_STAT_MAP = {
    ("passing", "catt"): "att",
    ("passing", "yds"): "pass_yds",
    ("passing", "td"): "pass_td",
    ("passing", "int"): "intc",
    ("rushing", "yds"): "rush_yds",
    ("rushing", "td"): "rush_td",
    ("receiving", "rec"): "rec",
    ("receiving", "yds"): "rec_yds",
    ("receiving", "td"): "rec_td",
}

# Fallback keyed by ESPN's machine keys (the ``keys`` column of each stat
# group), in case a label vocabulary ever drifts. Scoped by group so that the
# defensive "interceptions" group can never feed the passing ``intc``.
_KEY_MAP = {
    ("passing", "completionspassingattempts"): "att",
    ("passing", "passingyards"): "pass_yds",
    ("passing", "passingtouchdowns"): "pass_td",
    ("passing", "interceptions"): "intc",
    ("rushing", "rushingyards"): "rush_yds",
    ("rushing", "rushingtouchdowns"): "rush_td",
    ("receiving", "receptions"): "rec",
    ("receiving", "receivingyards"): "rec_yds",
    ("receiving", "receivingtouchdowns"): "rec_td",
}


def _key(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _number(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _fetch_json(url):
    return _FETCH.fetch(url)


def _core_get(suffix):
    # Route sports.core fetches through the shared paced_http fetcher
    # (espn_client._get), NOT raw urllib: the raw path has no pacing, no
    # per-host budget, and no disk cache, so a paginated enumeration trips
    # ESPN's 403 wall (measured 2026-08-07: offset pagination + raw fetches
    # died at 403 after ~10 core requests) and re-runs cost full budget.
    # The shared fetcher enforces host_budget + cooldown + disk cache, so a
    # re-run after the wall resets is free (cache hits don't charge).
    return espn._get(_CORE.format(path=LEAGUE_PATH) + suffix, ttl=43200)


def _summary(event_id):
    """One game summary via espn_client when its registry has ncaaf (added in
    parallel), else the same site-API URL fetched directly. Retries with
    backoff: espn_client's shared fetcher has empty retry_waits (page loads
    must not wait), but a season ingest is a batch job and a transient 403
    from the low-trust bucket is worth waiting out. Measured 2026-08-06."""
    attempts = 4
    last = None
    for i in range(attempts):
        try:
            if "ncaaf" in espn.LEAGUES:
                return espn.summary(LEAGUE, event_id)
            url = _SITE.format(path=LEAGUE_PATH) + "/summary?event={0}".format(event_id)
            return _fetch_json(url)
        except Exception as e:  # noqa: BLE001 - any failure is retried
            last = e
            time.sleep(min(60, 2.0 * (i + 1)))
    raise RuntimeError("summary {0} failed after {1} attempts: {2}".format(
        event_id, attempts, last))


def _season_doc(season):
    doc = _core_get("/seasons/{0}".format(season))
    if int(doc.get("year") or 0) != season:
        raise ValueError(
            "ESPN publishes no NCAAF season document for {0}".format(season)
        )
    return doc


def _regular_type(season_doc):
    """The published season type named by REGULAR_TYPE_NAME, found from the
    season document's types[] -- never assumed to be id 2."""
    items = ((season_doc.get("types") or {}).get("items")) or []
    for item in items:
        if _key(item.get("name")) != _key(REGULAR_TYPE_NAME):
            continue
        if item.get("id") and item.get("startDate") and item.get("endDate"):
            return item
        if item.get("$ref"):
            return _fetch_json(item["$ref"])
    # The season doc only carried refs: fetch each type and match by name.
    for item in items:
        ref = item.get("$ref")
        if not ref:
            continue
        type_doc = _fetch_json(ref)
        if _key(type_doc.get("name")) == _key(REGULAR_TYPE_NAME):
            return type_doc
    raise ValueError(
        "season publishes no {0!r} type; published: {1}".format(
            REGULAR_TYPE_NAME, [i.get("name") for i in items]
        )
    )


def _group_events(season, type_id):
    """(published_count, [event ids]) for one type's FBS group, paginated.

    The count comes from the limit=1 envelope first -- the same published
    number reconcile_totals asserts against (888 for 2025), not a value we
    derive from our own pages. Pagination is by ``page``, not ``offset``:
    sports.core.api.espn.com ignores ``offset`` and re-serves page 1 (the
    soccer ingest's ``_type_events`` uses the same page+pageCount pattern).
    ``pageCount`` is read from the envelope so the loop stops at the
    publisher's own page count instead of guessing.
    """
    url = (
        "/seasons/{0}/types/{1}/groups/{2}/events".format(season, type_id, GROUP_ID)
    )
    probe = _core_get(url + "?limit=1")
    total = int(probe.get("count") or 0)
    ids = []
    seen = set()
    page = 1
    while True:
        env = _core_get(url + "?limit=100&page={0}".format(page))
        items = env.get("items") or []
        if not items:
            break
        for item in items:
            tail = ((item.get("$ref") or "").split("?", 1)[0])
            tail = tail.rstrip("/").rsplit("/", 1)[-1]
            if tail.isdigit() and tail not in seen:
                seen.add(tail)
                ids.append(tail)
        if page >= int(env.get("pageCount", 1) or 1):
            break
        page += 1
        time.sleep(0.05)
    return total, ids


def _line_stats(group_name, labels, keys, raw_stats):
    """Our stat keys from one published stat-group row.

    ``att`` is passing attempts: the C/ATT column publishes "14/28" as one
    string, and the attempt count is its second component (matching the NFL
    vocabulary where att means passing attempts). Only keys whose published
    value parses are set -- no zero-filling of columns that did not appear.
    """
    values = {}
    group = _key(group_name)
    for idx in range(len(raw_stats)):
        label = _key(labels[idx]) if idx < len(labels) else ""
        mkey = _key(keys[idx]) if idx < len(keys) else ""
        target = _STAT_MAP.get((group, label))
        if target is None:
            target = _KEY_MAP.get((group, mkey))
        if target is None:
            continue
        value = raw_stats[idx]
        if target == "att" and isinstance(value, str) and "/" in value:
            parts = value.split("/")
            num = _number(parts[-1]) if parts[-1].strip() else None
        else:
            num = _number(value)
        if num is not None:
            values[target] = num
    return values


def _boxscore_players(summary, ha_by_team):
    """Yield merged per-athlete lines from ESPN's football boxscore contract.

    Football groups players by team, then by stat group; one athlete spans
    several groups, so lines are merged per athlete id before yielding.
    """
    merged = {}
    for block in (summary.get("boxscore") or {}).get("players", []):
        team = (block.get("team") or {}).get("abbreviation") or ""
        home_away = ha_by_team.get(team.upper()) if team else None
        for stat_group in block.get("statistics", []):
            labels = stat_group.get("labels") or stat_group.get("names") or []
            keys = stat_group.get("keys") or []
            for row in stat_group.get("athletes", []):
                if row.get("didNotPlay"):
                    continue
                athlete = row.get("athlete") or {}
                athlete_id = athlete.get("id") or row.get("id")
                name = (athlete.get("displayName") or athlete.get("fullName") or "").strip()
                if not athlete_id or not name:
                    continue
                # ESPN publishes placeholder team rows (negative id, " Team");
                # they are not players.
                if not str(athlete_id).lstrip("-").isdigit() or int(athlete_id) < 0:
                    continue
                if name.lower() in ("team", "tm"):
                    continue
                stats = _line_stats(
                    stat_group.get("name") or "", labels, keys, row.get("stats") or []
                )
                if not stats:
                    continue
                entry = merged.setdefault(str(athlete_id), [name, team, home_away, {}])
                entry[3].update(stats)
    for athlete_id, (name, team, home_away, stats) in merged.items():
        yield athlete_id, name, team, home_away, stats


def _header_competition(summary):
    """(completed, game_date, {abbrev: homeAway}) from the summary header."""
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    status_type = (comp.get("status") or {}).get("type") or {}
    completed = bool(status_type.get("completed"))
    game_date = (comp.get("date") or "")[:10]
    ha = {}
    for competitor in comp.get("competitors") or []:
        abbrev = ((competitor.get("team") or {}).get("abbreviation") or "").upper()
        if abbrev:
            ha[abbrev] = competitor.get("homeAway")
    return completed, game_date, ha


class PlayerResolver:
    """Resolve ESPN athlete names to existing players for one league.

    The same multi-pass matcher as the WC ingest's WCPlayerResolver, with the
    league taken from a parameter instead of hardcoded to 'wc'. Never
    fabricates a player row: an athlete no existing player matches is left
    unresolved and retained with player_id=NULL.
    """

    def __init__(self, con, league=LEAGUE, allowed_player_ids=None):
        self.rows = []
        if con is not None:
            try:
                self.rows = [dict(row) for row in con.execute(
                    "SELECT id, name, team FROM players WHERE league=?", (league,)
                )]
            except sqlite3.Error:
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

    def resolve(self, name, team):
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


def _team_code(abbrev):
    """Canonical NCAAF team code, or the raw abbreviation while the ncaaf
    team_codes vocabulary has not landed yet (added in parallel)."""
    raw = (abbrev or "").strip().upper()
    if not raw:
        return None
    try:
        return team_codes.normalize(LEAGUE, raw)
    except Exception:
        return raw


def _opponent(team, home_away, home, away):
    if home_away == "home":
        return away
    if home_away == "away":
        return home
    if team and home and team.upper() == home.upper():
        return away
    if team and away and team.upper() == away.upper():
        return home
    return None


def ingest(season, dry_run=False):
    season = int(season)
    # Batch job: pace the shared espn_client fetcher so 888 unpaced summary
    # fetches do not trip ESPN's 403 wall (measured 2026-08-06; the wall
    # outlives short backoffs and takes the live standings tab down with it).
    espn.set_min_interval(float(os.environ.get("LP_INGEST_MIN_INTERVAL") or 0.5))
    # Batch job: opt into the shared fetcher's retry ladder so a transient
    # 403 from a spent host is waited out instead of killing the run (the
    # soccer ingest's _summary_retry pattern; espn_client's default retry
    # waits are empty because page loads must not sit through a ladder).
    espn.set_retry_waits((5.0, 30.0, 120.0))
    print("NCAAF FBS (group {0}) {1} log ingest{2}".format(
        GROUP_ID, season, " (dry run)" if dry_run else ""))

    season_doc = _season_doc(season)
    type_doc = _regular_type(season_doc)
    type_id = str(type_doc.get("id") or "")
    type_name = type_doc.get("name") or REGULAR_TYPE_NAME
    print("  season {0} ({1}): type {2} {3!r} published {4} .. {5}".format(
        season, season_doc.get("displayName") or "?",
        type_id, type_name,
        (type_doc.get("startDate") or "")[:10],
        (type_doc.get("endDate") or "")[:10]))

    # The CLI season is the ESPN start-year key; verify it against the
    # published type window and warn -- never silently relabel.
    start_year = int((type_doc.get("startDate") or "")[:4] or 0)
    end_year = int((type_doc.get("endDate") or "")[:4] or 0)
    if season not in (start_year, end_year):
        print("  WARNING: season {0} outside the published {1} window {2}..{3}".format(
            season, type_name,
            (type_doc.get("startDate") or "")[:10],
            (type_doc.get("endDate") or "")[:10]))

    con = None
    if dry_run and not os.path.exists(DB):
        print("  dry run: no DB at {0}; resolving against an empty player set".format(DB))
    else:
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        if not dry_run:
            ensure_table(con)
    resolver = PlayerResolver(con, league=LEAGUE)

    if "ncaaf" not in espn.LEAGUES:
        print("  note: espn_client.LEAGUES lacks 'ncaaf' yet; fetching summaries directly")

    total, event_ids = _group_events(season, type_id)
    print("  group {0}: {1} published {2} events".format(GROUP_ID, total, type_name))
    if total == 0:
        raise ValueError(
            "group {0} publishes no {1} events; refusing to ingest nothing".format(
                GROUP_ID, type_name))

    ingested = resolved = unresolved = completed = 0
    skipped = failed = phase_mismatch = 0
    for idx, event_id in enumerate(event_ids, 1):
        try:
            summary = _summary(event_id)
        except Exception as exc:
            failed += 1
            print("  event {0}: summary failed ({1})".format(event_id, exc))
            continue

        is_completed, game_date, ha_by_team = _header_competition(summary)
        if not is_completed:
            skipped += 1
            continue

        # The stamp is read back from the published envelope, never assumed:
        # the event was enumerated from a type-scoped collection, so a
        # disagreement with the summary's own phase is a publisher surprise.
        hdr_season = (summary.get("header") or {}).get("season") or {}
        if hdr_season.get("type") is not None and str(hdr_season.get("type")) != str(type_id):
            phase_mismatch += 1
            print("  event {0}: published phase {1} != enumerated type {2}".format(
                event_id, hdr_season.get("type"), type_id))

        if not ha_by_team:
            # boxscore.teams[] carries homeAway when the header is absent.
            for t in (summary.get("boxscore") or {}).get("teams", []):
                abbrev = ((t.get("team") or {}).get("abbreviation") or "").upper()
                if abbrev:
                    ha_by_team[abbrev] = t.get("homeAway")
        home = away = None
        for abbrev, ha in ha_by_team.items():
            if ha == "home":
                home = abbrev
            elif ha == "away":
                away = abbrev
        home, away = _team_code(home), _team_code(away)

        completed += 1
        for athlete_id, name, raw_team, home_away, stats in _boxscore_players(summary, ha_by_team):
            team = _team_code(raw_team)
            player_id = resolver.resolve(name, team)
            if player_id is None:
                unresolved += 1
            else:
                resolved += 1
            ingested += 1
            if dry_run:
                continue
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
                    player_id, LEAGUE, season, event_id, event_id, game_date,
                    team, _opponent(team, home_away, home, away), home_away,
                    GAME_TYPE, json.dumps(stats, separators=(",", ":")),
                    "espn", athlete_id,
                ),
            )

        if not dry_run and (idx % 200 == 0 or idx == total):
            con.commit()
        if idx % 100 == 0 or idx == total:
            print("  type {0} ({1}): {2}/{3} events, {4} completed, {5} logs".format(
                type_id, type_name, idx, total, completed, ingested))
        time.sleep(0.05)

    total_logs = linked = None
    if con is not None:
        if not dry_run:
            total_logs, linked = con.execute(
                "SELECT COUNT(*), COUNT(player_id) FROM player_game_logs WHERE league=?",
                (LEAGUE,),
            ).fetchone()
        con.close()

    print("Done. {0} NCAAF FBS logs from {1} completed games "
          "({2} resolved rows, {3} unresolved rows).".format(
              ingested, completed, resolved, unresolved))
    print("  {0} events skipped (not completed), {1} summaries failed, "
          "{2} phase mismatches.".format(skipped, failed, phase_mismatch))
    if total_logs is not None:
        print("  ncaaf table now has {0} logs, {1} linked to players.".format(
            total_logs, linked))
    return ingested


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest NCAAF FBS regular-season player logs from ESPN")
    parser.add_argument("--season", type=int, required=True,
                        help="season year (ESPN start-year key, e.g. 2025)")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and resolve but write nothing")
    args = parser.parse_args()
    ingest(args.season, dry_run=args.dry_run)
