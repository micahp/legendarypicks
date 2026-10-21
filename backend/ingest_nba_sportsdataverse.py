#!/usr/bin/env python3
"""Load recent NBA Stats player box scores from SportsDataverse releases.

The Python package's ``load_nba_stats_player_boxscores`` is a convenience
wrapper around these public Parquet assets. Reading the assets directly keeps
the backend on Python 3.8 and uses its existing pyarrow installation.

Usage: python3 ingest_nba_sportsdataverse.py --recent-seasons 2 --dry-run
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata
from io import BytesIO
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nba_sportsdataverse as sdv_schema
import paced_http
from league_stats import queue_unresolved_player
from team_codes import UnknownTeamCode, normalize


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
RELEASE_BASE = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
USER_AGENT = "LegendaryPicks-NBA-Stats-ingest/1.0"
ESPN_SUMMARY_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
ESPN_FETCHER = paced_http.Fetcher(
    min_interval=1.0,
    retry_waits=(5.0, 20.0),
    headers={"User-Agent": paced_http.DEFAULT_HDRS["User-Agent"], "Accept": "application/json"},
    timeout=30,
    host_budget=40,
)
MARKET_COLUMNS = {
    "PTS": "points",
    "REB": "rebounds_total",
    "AST": "assists",
    "STL": "steals",
    "BLK": "blocks",
    "TO": "turnovers",
    "3PM": "three_pointers_made",
    "FGM": "field_goals_made",
    "FTM": "free_throws_made",
}
STAT_COLUMNS = dict(MARKET_COLUMNS, FGA="field_goals_attempted", FTA="free_throws_attempted")
GAME_TYPES = {
    "1": "PRE",
    "2": "REG",
    "3": "ALLSTAR",
    "4": "POST",
    "5": "PLAYIN",
    "6": "CUP",
    "9": "INTL",
}
IDENTITY_MATCH_THRESHOLD = 8  # of 11 counting stats; minutes are excluded (ESPN rounds them).


class SportsDataverseIngestError(RuntimeError):
    """A published release or its canonical crosswalk failed validation."""


def _current_start_year(today: Optional[dt.date] = None) -> int:
    today = today or dt.date.today()
    return today.year if today.month >= 7 else today.year - 1


def _asset_url(kind: str, source_season: int) -> str:
    if kind == "boxscores":
        return (f"{RELEASE_BASE}/nba_stats_player_boxscores/"
                f"player_boxscores_{source_season}.parquet")
    return f"{RELEASE_BASE}/nba_stats_schedules/nba_schedule_{source_season}.parquet"


def _download(url: str) -> Optional[bytes]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"})
    try:
        with urlopen(request, timeout=45) as response:
            payload = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise SportsDataverseIngestError(f"SportsDataverse request failed ({exc.code}): {url}") from exc
    except (URLError, TimeoutError) as exc:
        raise SportsDataverseIngestError(f"SportsDataverse request failed: {url}: {exc}") from exc
    if not payload:
        raise SportsDataverseIngestError(f"SportsDataverse returned an empty asset: {url}")
    return payload


def _read_parquet(payload: bytes, url: str) -> List[dict]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SportsDataverseIngestError(
            "pyarrow is required to read the SportsDataverse release; use the backend venv"
        ) from exc
    try:
        return pq.read_table(BytesIO(payload)).to_pylist()
    except Exception as exc:
        raise SportsDataverseIngestError(f"invalid Parquet asset: {url}: {exc}") from exc


def fetch_release(start_year: int) -> Optional[dict]:
    """Fetch both complete published assets for the requested start-year season.

    A season is available only when both assets exist. Returning None means both
    assets are 404; a half-published release fails closed.
    """
    source_season = int(start_year) + 1
    box_url = _asset_url("boxscores", source_season)
    schedule_url = _asset_url("schedules", source_season)
    box_bytes = _download(box_url)
    schedule_bytes = _download(schedule_url)
    if box_bytes is None and schedule_bytes is None:
        return None
    if box_bytes is None or schedule_bytes is None:
        raise SportsDataverseIngestError(
            f"partial SportsDataverse release for {start_year}-{str(source_season)[-2:]}"
        )
    boxes = _read_parquet(box_bytes, box_url)
    schedules = _read_parquet(schedule_bytes, schedule_url)
    fingerprint = hashlib.sha256(box_bytes + b"\0" + schedule_bytes).hexdigest()
    return {
        "start_year": int(start_year),
        "source_season": source_season,
        "boxes": boxes,
        "schedules": schedules,
        "release_hash": fingerprint,
        "boxscore_bytes": len(box_bytes),
        "schedule_bytes": len(schedule_bytes),
    }


def _fold_name(value: object) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = ascii_value.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z]+", "", ascii_value)


def _number(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _minutes(value) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip()
    try:
        if ":" in raw:
            minutes, seconds = raw.split(":", 1)
            return round(int(minutes) + float(seconds) / 60.0, 3)
        return float(raw)
    except (TypeError, ValueError):
        return None


def _normal_team(value: object, context: str) -> str:
    try:
        return normalize("nba", str(value or ""))
    except UnknownTeamCode as exc:
        raise SportsDataverseIngestError(f"{context}: {exc}") from exc


def _game_type(row: dict) -> str:
    phase = str(row.get("season_type_id") or "").strip()
    if phase not in GAME_TYPES:
        raise SportsDataverseIngestError(
            f"unknown NBA Stats season_type_id {phase!r} in game {row.get('game_id')}"
        )
    return GAME_TYPES[phase]


def _normalize_line(row: dict) -> Tuple[dict, str, Optional[str]]:
    comment = str(row.get("comment") or "").strip()
    status = "dnp" if comment else "played"
    minutes = _minutes(row.get("minutes"))
    if comment and minutes not in (None, 0, 0.0):
        raise SportsDataverseIngestError(
            f"NBA Stats row has both a DNP comment and positive minutes: {row.get('game_id')} / {row.get('person_id')}"
        )
    if not comment and (minutes is None or minutes <= 0):
        status = "unknown"

    if status == "dnp":
        stats = {key: 0 for key in STAT_COLUMNS}
        stats.update({"PRA": 0, "MIN": 0, "DNP": True, "DNP_COMMENT": comment})
        return stats, status, comment

    stats = {}
    for key, column in STAT_COLUMNS.items():
        value = _number(row.get(column))
        if value is not None:
            stats[key] = value
    if minutes is not None:
        stats["MIN"] = minutes
    if all(stats.get(key) is not None for key in ("PTS", "REB", "AST")):
        stats["PRA"] = stats["PTS"] + stats["REB"] + stats["AST"]
    return stats, status, None


def validate_release(release: dict) -> dict:
    """Validate the release grain, phase, schedule, team sides and market fields."""
    boxes, schedules = release["boxes"], release["schedules"]
    if not boxes or not schedules:
        raise SportsDataverseIngestError("NBA Stats player boxscores and schedule must be non-empty")
    required_box = {
        "person_id", "first_name", "family_name", "team_tricode", "side", "game_id",
        "season", "season_type_id", "comment", "minutes",
    } | set(STAT_COLUMNS.values())
    required_schedule = {
        "game_id", "season", "game_date", "home_team_abbreviation", "away_team_abbreviation",
        "home_pts", "away_pts",
    }
    if not required_box.issubset(boxes[0]):
        raise SportsDataverseIngestError(
            "NBA Stats player boxscore schema is missing: " + ", ".join(sorted(required_box - set(boxes[0])))
        )
    if not required_schedule.issubset(schedules[0]):
        raise SportsDataverseIngestError(
            "NBA Stats schedule schema is missing: " + ", ".join(sorted(required_schedule - set(schedules[0])))
        )

    source_season = int(release["source_season"])
    if any(int(row.get("season") or 0) != source_season for row in boxes + schedules):
        raise SportsDataverseIngestError(f"release rows disagree with source season {source_season}")

    box_game_ids = {str(row.get("game_id") or "") for row in boxes}
    schedule_by_id = {}
    for row in schedules:
        game_id = str(row.get("game_id") or "")
        if not game_id or game_id in schedule_by_id:
            raise SportsDataverseIngestError(f"missing or duplicate schedule game id {game_id!r}")
        date = str(row.get("game_date") or "")[:10]
        try:
            dt.date.fromisoformat(date)
        except ValueError as exc:
            raise SportsDataverseIngestError(f"invalid date for NBA Stats game {game_id}: {date!r}") from exc
        row["_date"] = date
        if game_id in box_game_ids:
            row["_home"] = _normal_team(row.get("home_team_abbreviation"), game_id)
            row["_away"] = _normal_team(row.get("away_team_abbreviation"), game_id)
            if row["_home"] == row["_away"]:
                raise SportsDataverseIngestError(
                    f"NBA Stats game {game_id} has the same team on both sides"
                )
        schedule_by_id[game_id] = row

    seen = set()
    teams_by_game = collections.defaultdict(set)
    market_missing = collections.Counter()
    dnp_rows = 0
    unknown_appearance_rows = 0
    for row in boxes:
        game_id = str(row.get("game_id") or "")
        person_id = str(row.get("person_id") or "")
        key = (game_id, person_id)
        if not game_id or not person_id or key in seen:
            raise SportsDataverseIngestError(f"missing or duplicate player/game key {key!r}")
        seen.add(key)
        schedule = schedule_by_id.get(game_id)
        if schedule is None:
            raise SportsDataverseIngestError(f"boxscore game {game_id} is absent from the NBA Stats schedule")
        side = str(row.get("side") or "").lower()
        expected = schedule["_home"] if side == "home" else schedule["_away"] if side == "away" else None
        team = _normal_team(row.get("team_tricode"), f"boxscore game {game_id}")
        if expected is None or team != expected:
            raise SportsDataverseIngestError(
                f"boxscore team/side disagrees with schedule for game {game_id}: {team}/{side}"
            )
        teams_by_game[game_id].add(team)
        stats, status, _comment = _normalize_line(row)
        if status == "dnp":
            dnp_rows += 1
        elif status == "played":
            for market, column in MARKET_COLUMNS.items():
                if stats.get(market) is None:
                    market_missing[market] += 1
        else:
            unknown_appearance_rows += 1

    for game_id, teams in teams_by_game.items():
        schedule = schedule_by_id[game_id]
        if teams != {schedule["_home"], schedule["_away"]}:
            raise SportsDataverseIngestError(f"boxscore game {game_id} does not contain both scheduled teams")
        if _number(schedule.get("home_pts")) is None or _number(schedule.get("away_pts")) is None:
            raise SportsDataverseIngestError(f"completed boxscore game {game_id} has no final score")

    release["schedule_by_id"] = schedule_by_id
    release["boxscore_games"] = len(teams_by_game)
    release["dnp_rows"] = dnp_rows
    release["unknown_appearance_rows"] = unknown_appearance_rows
    release["market_missing"] = dict(market_missing)
    release["schedule_games_without_boxscore"] = len(schedule_by_id) - len(teams_by_game)
    return release


def _fixture_key(game_date: str, team_a: object, team_b: object) -> Tuple[str, str, str]:
    a = _normal_team(team_a, "fixture")
    b = _normal_team(team_b, "fixture")
    return (str(game_date)[:10],) + tuple(sorted((a, b)))


def build_game_id_map(connection: sqlite3.Connection, release: dict) -> Dict[str, Optional[str]]:
    """Join NBA Stats ids to our existing ESPN event ids by date and team pair."""
    event_by_fixture = collections.defaultdict(set)
    for row in connection.execute(
        """SELECT DISTINCT game_id,game_date,team,opponent FROM player_game_logs
             WHERE league='nba' AND game_id IS NOT NULL AND game_date IS NOT NULL
               AND team IS NOT NULL AND opponent IS NOT NULL"""
    ):
        try:
            event_by_fixture[_fixture_key(row["game_date"], row["team"], row["opponent"])].add(str(row["game_id"]))
        except SportsDataverseIngestError:
            continue

    if sdv_schema.table_exists(connection, "prop_games"):
        for row in connection.execute(
            """SELECT espn_event_id,date,home,away FROM prop_games
                 WHERE league='nba' AND espn_event_id IS NOT NULL
                   AND date IS NOT NULL AND home IS NOT NULL AND away IS NOT NULL"""
        ):
            try:
                event_by_fixture[_fixture_key(row["date"], row["home"], row["away"])].add(
                    str(row["espn_event_id"])
                )
            except SportsDataverseIngestError:
                continue

    result = {}
    for game_id in release["box_game_ids"]:
        schedule = release["schedule_by_id"][game_id]
        fixture = _fixture_key(schedule["_date"], schedule["_home"], schedule["_away"])
        matches = event_by_fixture.get(fixture, set())
        if len(matches) > 1:
            raise SportsDataverseIngestError(
                f"ambiguous ESPN game crosswalk for NBA Stats game {game_id}: {sorted(matches)}"
            )
        result[game_id] = next(iter(matches)) if matches else None

    mapped = [event for event in result.values() if event]
    if len(mapped) != len(set(mapped)):
        raise SportsDataverseIngestError("multiple NBA Stats games map to one Legendary Picks event id")
    release["game_id_map"] = result
    return result


def _read_players(connection: sqlite3.Connection) -> dict:
    players = {}
    for row in connection.execute("SELECT id,name,league FROM players WHERE league='nba'"):
        players[int(row["id"])] = {"name": row["name"], "league": row["league"]}
    return players


def _direct_person_crosswalk(connection: sqlite3.Connection, players: dict) -> Dict[str, int]:
    if not sdv_schema.table_exists(connection, "player_source_ids"):
        raise SportsDataverseIngestError("player_source_ids is required for NBA Stats identity resolution")
    result = {}
    owners = collections.defaultdict(set)
    for row in connection.execute(
        """SELECT source_player_key,player_id FROM player_source_ids
             WHERE source=? AND league='nba'""", (sdv_schema.PLAYER_ID_SOURCE,)
    ):
        person_key, player_id = str(row["source_player_key"]), int(row["player_id"])
        player = players.get(player_id)
        if player is None:
            raise SportsDataverseIngestError(
                f"NBA Stats crosswalk {person_key} points to missing/non-NBA player {player_id}"
            )
        owners[player_id].add(person_key)
        if person_key in result and result[person_key] != player_id:
            raise SportsDataverseIngestError(f"NBA Stats person id {person_key} has multiple owners")
        result[person_key] = player_id
    return result


def _stat_match_count(source_row: dict, existing_stats: dict) -> int:
    matches = 0
    for key, column in STAT_COLUMNS.items():
        source_value = _number(source_row.get(column))
        old_value = existing_stats.get(key)
        if source_value is None or old_value is None:
            continue
        try:
            if float(source_value) == float(old_value):
                matches += 1
        except (TypeError, ValueError):
            continue
    return matches


def infer_person_crosswalk(connection: sqlite3.Connection, releases: Sequence[dict],
                           players: dict, direct: Dict[str, int]) -> Tuple[Dict[str, int], dict]:
    """Find only exact-name/team candidates corroborated by same-game stat lines."""
    game_players = collections.defaultdict(list)
    for row in connection.execute(
        """SELECT l.player_id,l.game_id,l.game_date,l.team,l.stats,p.name
             FROM player_game_logs l JOIN players p ON p.id=l.player_id
            WHERE l.league='nba' AND l.source='espn' AND l.game_id IS NOT NULL
              AND l.game_date IS NOT NULL AND l.team IS NOT NULL"""
    ):
        try:
            team = normalize("nba", row["team"])
        except UnknownTeamCode:
            continue
        game_players[(str(row["game_id"]), team, _fold_name(row["name"]))].append(row)

    proposals = collections.defaultdict(set)
    for release in releases:
        for box in release["boxes"]:
            person_key = str(box["person_id"])
            if person_key in direct or str(box.get("comment") or "").strip():
                continue
            event_id = release["game_id_map"].get(str(box["game_id"]))
            if not event_id:
                continue
            team = normalize("nba", box["team_tricode"])
            full_name = _fold_name("{} {}".format(box.get("first_name"), box.get("family_name")))
            candidates = game_players.get((event_id, team, full_name), [])
            if len(candidates) != 1:
                continue
            candidate = candidates[0]
            try:
                existing_stats = json.loads(candidate["stats"] or "{}")
            except (TypeError, ValueError):
                continue
            if _stat_match_count(box, existing_stats) >= IDENTITY_MATCH_THRESHOLD:
                player_id = int(candidate["player_id"])
                if player_id in players:
                    proposals[person_key].add(player_id)

    proposed = {
        person_key: next(iter(player_ids))
        for person_key, player_ids in proposals.items()
        if len(player_ids) == 1
    }
    ambiguous = {key for key, player_ids in proposals.items() if len(player_ids) > 1}
    claimed = collections.defaultdict(set)
    for person_key, player_id in proposed.items():
        claimed[player_id].add(person_key)
    for person_key, player_id in list(proposed.items()):
        if len(claimed[player_id]) > 1:
            ambiguous.add(person_key)
            del proposed[person_key]

    already_owned = collections.defaultdict(set)
    for person_key, player_id in direct.items():
        already_owned[player_id].add(person_key)
    for person_key, player_id in list(proposed.items()):
        if already_owned[player_id] and person_key not in already_owned[player_id]:
            ambiguous.add(person_key)
            del proposed[person_key]

    combined = dict(direct)
    combined.update(proposed)
    reason = {person_key: "ambiguous_same_game_stats_crosswalk" for person_key in ambiguous}
    return combined, {"inferred": proposed, "ambiguous": ambiguous, "reason": reason}


def fetch_espn_event_summary(event_id: str) -> dict:
    """Read ESPN's published boxscore roster, including players who did not play."""
    url = ESPN_SUMMARY_BASE + "?" + urlencode({"event": str(event_id)})
    payload = ESPN_FETCHER.json(url)
    if not isinstance(payload, dict):
        raise SportsDataverseIngestError(f"ESPN event {event_id} returned a non-object summary")
    return payload


def _espn_event_players(payload: dict, event_id: str, schedule: dict) -> dict:
    """Index ESPN event athletes by normalized team and exact normalized display name."""
    header = payload.get("header") or {}
    if str(header.get("id") or "") != str(event_id):
        raise SportsDataverseIngestError(
            f"ESPN summary id mismatch: requested {event_id}, got {header.get('id')}"
        )
    competitions = [
        row for row in (header.get("competitions") or [])
        if str(row.get("id") or "") == str(event_id)
    ]
    if len(competitions) != 1:
        raise SportsDataverseIngestError(
            f"ESPN event {event_id} has {len(competitions)} matching competitions"
        )

    def team_code(team_obj: dict, context: str) -> str:
        raw = team_obj.get("abbreviation")
        try:
            return normalize("nba", raw)
        except (UnknownTeamCode, AttributeError) as exc:
            raise SportsDataverseIngestError(
                f"ESPN event {event_id} has an unrecognized {context} team {raw!r}"
            ) from exc

    competition_teams = {
        team_code(row.get("team") or {}, "competition")
        for row in competitions[0].get("competitors") or []
    }
    expected_teams = {schedule["_home"], schedule["_away"]}
    if len(competition_teams) != 2 or competition_teams != expected_teams:
        raise SportsDataverseIngestError(
            f"ESPN event {event_id} teams {sorted(competition_teams)} do not match "
            f"NBA Stats fixture {sorted(expected_teams)}"
        )

    boxscore = payload.get("boxscore") or {}
    team_rows = boxscore.get("players") or []
    box_teams = {
        team_code(row.get("team") or {}, "boxscore")
        for row in team_rows
    }
    if len(team_rows) != 2 or box_teams != expected_teams:
        raise SportsDataverseIngestError(
            f"ESPN event {event_id} boxscore teams {sorted(box_teams)} do not match "
            f"NBA Stats fixture {sorted(expected_teams)}"
        )

    by_name_team = collections.defaultdict(dict)
    athlete_identity = {}
    for team_row in team_rows:
        team = team_code(team_row.get("team") or {}, "boxscore")
        for stat_group in team_row.get("statistics") or []:
            for entry in stat_group.get("athletes") or []:
                athlete = entry.get("athlete") or {}
                athlete_id = str(athlete.get("id") or "").strip()
                name = str(athlete.get("displayName") or athlete.get("fullName") or "").strip()
                name_key = _fold_name(name)
                if not athlete_id or not name_key:
                    continue
                identity = (name, team)
                previous = athlete_identity.get(athlete_id)
                if previous is not None and previous != identity:
                    raise SportsDataverseIngestError(
                        f"ESPN athlete {athlete_id} has conflicting names or teams in event {event_id}"
                    )
                athlete_identity[athlete_id] = identity
                by_name_team[(team, name_key)][athlete_id] = {
                    "espn_id": athlete_id,
                    "name": name,
                    "team": team,
                }
    if not by_name_team:
        raise SportsDataverseIngestError(f"ESPN event {event_id} has no player roster rows")
    return by_name_team


def _espn_id_owners(connection: sqlite3.Connection) -> Tuple[dict, dict]:
    """Read ESPN athlete-id owners, including legacy ids stored in nba_id."""
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(players)")}
    if not {"id", "league", "espn_id"}.issubset(columns):
        raise SportsDataverseIngestError("players must expose id, league, and espn_id for ESPN matching")
    selected = ["id", "league", "espn_id"]
    if "nba_id" in columns:
        selected.append("nba_id")
    owners = collections.defaultdict(set)
    leagues = {}
    for row in connection.execute("SELECT {} FROM players".format(",".join(selected))):
        player_id, league = int(row["id"]), str(row["league"])
        leagues[player_id] = league
        keys = [row["espn_id"]]
        if league == "nba" and "nba_id" in columns:
            keys.append(row["nba_id"])
        for raw_key in keys:
            key = str(raw_key or "").strip()
            if key:
                owners[key].add(player_id)

    if sdv_schema.table_exists(connection, "player_source_ids"):
        for row in connection.execute(
            """SELECT source_player_key,player_id FROM player_source_ids
                 WHERE source='espn'"""
        ):
            key = str(row["source_player_key"] or "").strip()
            if key:
                player_id = int(row["player_id"])
                owners[key].add(player_id)
    return owners, leagues


def resolve_person_crosswalk_from_espn(connection: sqlite3.Connection,
                                       releases: Sequence[dict], players: dict,
                                       crosswalk: Dict[str, int], plan: dict) -> Tuple[dict, dict]:
    """Resolve remaining NBA Stats ids through exact ESPN event roster identities.

    The game must already crosswalk to one ESPN event. ESPN must publish the exact
    normalized name on the same team in every source appearance. Existing canonical
    players bind by ESPN athlete id; a missing canonical row is staged as an inactive
    ESPN identity and only inserted during the ingest transaction.
    """
    boxes_by_person = collections.defaultdict(list)
    for release in releases:
        for box in release["boxes"]:
            person_key = str(box["person_id"])
            if person_key not in crosswalk:
                boxes_by_person[person_key].append((release, box))
    if not boxes_by_person:
        plan["espn_inferred"] = {}
        plan["espn_ids"] = {}
        plan["new_players"] = {}
        plan["espn_events_checked"] = 0
        plan["espn_events_failed"] = 0
        return crosswalk, plan

    schedules_by_event = {}
    needed_events = set()
    for rows in boxes_by_person.values():
        for release, box in rows:
            event_id = release["game_id_map"].get(str(box["game_id"]))
            if event_id:
                needed_events.add(str(event_id))
                schedules_by_event[str(event_id)] = release["schedule_by_id"][str(box["game_id"])]

    event_players = {}
    event_errors = {}
    for event_id in sorted(needed_events):
        try:
            event_players[event_id] = _espn_event_players(
                fetch_espn_event_summary(event_id), event_id, schedules_by_event[event_id]
            )
        except Exception as exc:
            # Identity remains null and queryable; the run reports this event failure
            # and never falls back to an unverified name-only player match.
            event_errors[event_id] = str(exc)

    proposals = {}
    reason = dict(plan.get("reason") or {})
    for person_key, rows in boxes_by_person.items():
        observed_ids = set()
        failed = False
        for release, box in rows:
            event_id = release["game_id_map"].get(str(box["game_id"]))
            if not event_id:
                reason[person_key] = "espn_event_has_no_legendary_picks_crosswalk"
                failed = True
                break
            event_id = str(event_id)
            if event_id in event_errors:
                reason[person_key] = "espn_event_lookup_failed"
                failed = True
                break
            try:
                team = normalize("nba", box["team_tricode"])
            except UnknownTeamCode:
                reason[person_key] = "nba_stats_team_not_normalized_for_espn_identity"
                failed = True
                break
            name_key = _fold_name("{} {}".format(box.get("first_name"), box.get("family_name")))
            matches = event_players[event_id].get((team, name_key), {})
            if len(matches) != 1:
                reason[person_key] = (
                    "ambiguous_espn_event_name_team_match" if len(matches) > 1
                    else "espn_event_name_team_match_missing"
                )
                failed = True
                break
            observed_ids.update(matches)
        if failed:
            continue
        if len(observed_ids) != 1:
            reason[person_key] = "conflicting_espn_athlete_ids_across_games"
            continue
        proposals[person_key] = next(iter(observed_ids))

    claimed = collections.defaultdict(set)
    for person_key, espn_id in proposals.items():
        claimed[espn_id].add(person_key)
    ambiguous_ids = {espn_id for espn_id, keys in claimed.items() if len(keys) > 1}
    for person_key, espn_id in list(proposals.items()):
        if espn_id in ambiguous_ids:
            reason[person_key] = "multiple_nba_stats_ids_match_one_espn_athlete"
            del proposals[person_key]

    id_owners, owner_leagues = _espn_id_owners(connection)
    existing_player_claims = collections.defaultdict(set)
    for person_key, player_id in crosswalk.items():
        existing_player_claims[int(player_id)].add(person_key)

    espn_inferred = {}
    new_players = {}
    next_temp_id = -1
    for person_key, espn_id in proposals.items():
        owners = id_owners.get(espn_id, set())
        if len(owners) > 1:
            reason[person_key] = "espn_athlete_id_has_multiple_player_owners"
            continue
        if owners:
            player_id = next(iter(owners))
            if owner_leagues.get(player_id) != "nba" or player_id not in players:
                reason[person_key] = "espn_athlete_id_owned_outside_nba_player_spine"
                continue
            if existing_player_claims.get(player_id, set()) - {person_key}:
                reason[person_key] = "multiple_nba_stats_ids_claim_one_canonical_player"
                continue
        else:
            evidence = None
            for event_id, roster in event_players.items():
                found = [
                    item
                    for key, athletes in roster.items() for athlete_id, item in athletes.items()
                    if athlete_id == espn_id
                ]
                if found:
                    evidence = found[0]
                    break
            if evidence is None:
                reason[person_key] = "espn_athlete_evidence_missing"
                continue
            player_id = next_temp_id
            next_temp_id -= 1
            new_players[player_id] = {
                "espn_id": espn_id,
                "name": evidence["name"],
                "team": evidence["team"],
            }
            players[player_id] = {"name": evidence["name"], "league": "nba"}
            existing_player_claims[player_id].add(person_key)
        espn_inferred[person_key] = int(player_id)
        reason.pop(person_key, None)

    result = dict(crosswalk)
    result.update(espn_inferred)
    plan.update({
        "espn_inferred": espn_inferred,
        "espn_ids": {person_key: proposals[person_key]
                     for person_key in espn_inferred},
        "new_players": new_players,
        "reason": reason,
        "espn_events_checked": len(event_players),
        "espn_events_failed": len(event_errors),
        "espn_event_errors": event_errors,
    })
    return result, plan


def _prepare_rows(releases: Sequence[dict], person_map: Dict[str, int]) -> Tuple[list, list]:
    logs, games = [], []
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for release in releases:
        start_year = release["start_year"]
        schedule_by_id = release["schedule_by_id"]
        game_id_map = release["game_id_map"]
        grouped = collections.defaultdict(list)
        for box in release["boxes"]:
            grouped[str(box["game_id"])].append(box)
        for source_game_id, box_rows in grouped.items():
            schedule = schedule_by_id[source_game_id]
            game_type = _game_type(box_rows[0])
            home, away = schedule["_home"], schedule["_away"]
            home_score, away_score = _number(schedule["home_pts"]), _number(schedule["away_pts"])
            event_id = game_id_map.get(source_game_id)
            games.append((source_game_id, start_year, release["source_season"], event_id,
                          schedule["_date"], home, away, home_score, away_score, game_type,
                          release["release_hash"], now))
            for box in box_rows:
                source_team = _normal_team(box["team_tricode"], source_game_id)
                is_home = str(box["side"]).lower() == "home"
                opponent = away if is_home else home
                stats, appearance_status, dnp_comment = _normalize_line(box)
                player_key = str(box["person_id"])
                logs.append((person_map.get(player_key), "nba", start_year,
                             source_game_id, event_id, source_game_id, schedule["_date"],
                             source_team, opponent, "home" if is_home else "away",
                             json.dumps(stats, sort_keys=True, separators=(",", ":")),
                             sdv_schema.SOURCE, player_key, appearance_status, dnp_comment,
                             release["release_hash"], now, game_type))
    return logs, games


def _verify_score_preservation(connection: sqlite3.Connection, games: Sequence[tuple]) -> None:
    for row in games:
        event_id, source_home, source_away = row[3], row[7], row[8]
        if not event_id:
            continue
        held = connection.execute(
            """SELECT final_home,final_away FROM prop_games
                 WHERE league='nba' AND espn_event_id=?""", (event_id,)
        ).fetchall() if sdv_schema.table_exists(connection, "prop_games") else []
        for current in held:
            if current[0] is not None and int(current[0]) != source_home:
                raise SportsDataverseIngestError(
                    f"final home score conflict for ESPN event {event_id}: {current[0]} vs {source_home}"
                )
            if current[1] is not None and int(current[1]) != source_away:
                raise SportsDataverseIngestError(
                    f"final away score conflict for ESPN event {event_id}: {current[1]} vs {source_away}"
                )


def _write(connection: sqlite3.Connection, releases: Sequence[dict], logs: Sequence[tuple],
           games: Sequence[tuple], crosswalk: dict, crosswalk_plan: dict) -> None:
    sdv_schema.ensure_schema(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        temporary_to_published = {}
        espn_owner_by_id, _owner_leagues = _espn_id_owners(connection)
        player_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(players)")
        }
        for temporary_id, identity in crosswalk_plan.get("new_players", {}).items():
            espn_id = str(identity["espn_id"])
            owners = espn_owner_by_id.get(espn_id, set())
            if len(owners) > 1:
                raise SportsDataverseIngestError(
                    f"ESPN athlete {espn_id} acquired multiple player owners before publication"
                )
            if owners:
                target_id = next(iter(owners))
                row = connection.execute(
                    "SELECT league FROM players WHERE id=?", (target_id,)
                ).fetchone()
                if not row or row[0] != "nba":
                    raise SportsDataverseIngestError(
                        f"ESPN athlete {espn_id} is now owned outside the NBA player spine"
                    )
            else:
                required = {"name", "team", "league", "espn_id", "active"}
                if not required.issubset(player_columns):
                    raise SportsDataverseIngestError(
                        "players is missing columns required to publish an ESPN-only NBA identity: "
                        + ", ".join(sorted(required - player_columns))
                    )
                cursor = connection.execute(
                    """INSERT INTO players(name,team,league,espn_id,active)
                       VALUES(?,NULL,'nba',?,0)""",
                    (identity["name"], espn_id),
                )
                target_id = int(cursor.lastrowid)
            temporary_to_published[int(temporary_id)] = int(target_id)

        def ensure_source_owner(source: str, source_key: str, player_id: int) -> None:
            held = connection.execute(
                """SELECT player_id FROM player_source_ids
                     WHERE source=? AND league='nba' AND source_player_key=?""",
                (source, str(source_key)),
            ).fetchone()
            if held and int(held[0]) != int(player_id):
                raise SportsDataverseIngestError(
                    f"{source} player id {source_key} changed owner from {held[0]} to {player_id}"
                )
            if not held:
                connection.execute(
                    """INSERT INTO player_source_ids
                         (source,league,source_player_key,player_id,first_seen,last_seen)
                       VALUES(?,'nba',?,?,?,?)""",
                    (source, str(source_key), int(player_id), now, now),
                )

        new_crosswalk_ids = dict(crosswalk_plan.get("inferred", {}))
        new_crosswalk_ids.update(crosswalk_plan.get("espn_inferred", {}))
        for person_key, player_id in new_crosswalk_ids.items():
            actual_id = temporary_to_published.get(int(player_id), int(player_id))
            ensure_source_owner(sdv_schema.PLAYER_ID_SOURCE, person_key, actual_id)
        for person_key, player_id in crosswalk_plan.get("espn_inferred", {}).items():
            actual_id = temporary_to_published.get(int(player_id), int(player_id))
            ensure_source_owner("espn", str(crosswalk_plan["espn_ids"][person_key]), actual_id)

        if temporary_to_published:
            logs = [
                (temporary_to_published.get(int(row[0]), int(row[0])),) + tuple(row[1:])
                if row[0] is not None and int(row[0]) in temporary_to_published else tuple(row)
                for row in logs
            ]

        for release in releases:
            connection.execute(
                """INSERT INTO nba_sportsdataverse_releases
                     (season,source_season,release_hash,boxscore_rows,boxscore_games,
                      schedule_rows,current_release_available,checked_at,imported_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(season) DO UPDATE SET
                     source_season=excluded.source_season,
                     release_hash=excluded.release_hash,
                     boxscore_rows=excluded.boxscore_rows,
                     boxscore_games=excluded.boxscore_games,
                     schedule_rows=excluded.schedule_rows,
                     current_release_available=excluded.current_release_available,
                     checked_at=excluded.checked_at,
                     imported_at=excluded.imported_at""",
                (release["start_year"], release["source_season"], release["release_hash"],
                 len(release["boxes"]), release["boxscore_games"], len(release["schedules"]),
                 int(release.get("current_release_available", False)), now, now),
            )

        connection.executemany(
            """INSERT INTO nba_sportsdataverse_games
                 (source_game_id,season,source_season,espn_event_id,game_date,home,away,
                  home_score,away_score,game_type,release_hash,ingested_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_game_id) DO UPDATE SET
                 season=excluded.season,source_season=excluded.source_season,
                 espn_event_id=COALESCE(excluded.espn_event_id,nba_sportsdataverse_games.espn_event_id),
                 game_date=excluded.game_date,home=excluded.home,away=excluded.away,
                 home_score=excluded.home_score,away_score=excluded.away_score,
                 game_type=excluded.game_type,release_hash=excluded.release_hash,
                 ingested_at=excluded.ingested_at""",
            games,
        )
        connection.executemany(
            """INSERT INTO player_game_logs_sportsdataverse
                 (player_id,league,season,game_no,game_id,source_game_id,game_date,team,
                  opponent,home_away,stats,source,source_player_key,appearance_status,
                  dnp_comment,release_hash,ingested_at,game_type)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(league,source_player_key,season,game_no) DO UPDATE SET
                 player_id=COALESCE(excluded.player_id,player_game_logs_sportsdataverse.player_id),
                 game_id=COALESCE(excluded.game_id,player_game_logs_sportsdataverse.game_id),
                 source_game_id=excluded.source_game_id,game_date=excluded.game_date,
                 team=excluded.team,opponent=excluded.opponent,home_away=excluded.home_away,
                 stats=excluded.stats,source=excluded.source,
                 appearance_status=excluded.appearance_status,dnp_comment=excluded.dnp_comment,
                 release_hash=excluded.release_hash,ingested_at=excluded.ingested_at,
                 game_type=excluded.game_type""",
            logs,
        )
        if sdv_schema.table_exists(connection, "prop_games"):
            connection.executemany(
                """UPDATE prop_games SET final_home=COALESCE(final_home,?),
                           final_away=COALESCE(final_away,?)
                     WHERE league='nba' AND espn_event_id=?""",
                ((row[7], row[8], row[3]) for row in games if row[3]),
            )

        first_by_person = {}
        for release in releases:
            for box in release["boxes"]:
                first_by_person.setdefault(str(box["person_id"]), box)
        already_queued = set()
        if sdv_schema.table_exists(connection, "unresolved_players"):
            already_queued = {
                str(row[0]) for row in connection.execute(
                    """SELECT source_player_key FROM unresolved_players
                         WHERE source='nba.com' AND league='nba'"""
                ) if row[0] is not None
            }
        for person_key, box in first_by_person.items():
            if person_key in crosswalk or person_key in already_queued:
                continue
            queue_unresolved_player(
                connection,
                source=sdv_schema.PLAYER_ID_SOURCE,
                raw_name="{} {}".format(box.get("first_name") or "", box.get("family_name") or "").strip(),
                league="nba",
                team=_normal_team(box.get("team_tricode"), "unresolved player"),
                source_player_key=person_key,
                reason=crosswalk_plan["reason"].get(person_key, "nba_stats_id_not_crosswalked"),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def ingest(db_path: str = DB, *, recent_seasons: int = 2, dry_run: bool = False,
           season_start_years: Optional[Sequence[int]] = None) -> dict:
    if recent_seasons < 1:
        raise ValueError("recent_seasons must be positive")
    current_year = _current_start_year()
    requested = list(season_start_years or range(current_year, current_year - recent_seasons, -1))
    if len(set(requested)) != len(requested):
        raise ValueError("season start years must be unique")

    releases = []
    missing = []
    for start_year in requested:
        release = fetch_release(int(start_year))
        if release is None:
            missing.append(int(start_year))
            if int(start_year) != current_year:
                raise SportsDataverseIngestError(
                    f"expected recent NBA Stats release for {start_year}-{str(start_year + 1)[-2:]}, but both assets returned 404"
                )
            continue
        release["current_release_available"] = int(start_year) == current_year
        releases.append(validate_release(release))
    if not releases:
        raise SportsDataverseIngestError("no requested SportsDataverse NBA Stats release is available")

    db_uri = "file:{}?mode=ro".format(os.path.abspath(db_path)) if dry_run else os.path.abspath(db_path)
    connection = sqlite3.connect(db_uri, uri=dry_run, timeout=60)
    connection.row_factory = sqlite3.Row
    try:
        players = _read_players(connection)
        direct = _direct_person_crosswalk(connection, players)
        for release in releases:
            release["box_game_ids"] = sorted({str(row["game_id"]) for row in release["boxes"]})
            build_game_id_map(connection, release)
        crosswalk, crosswalk_plan = infer_person_crosswalk(connection, releases, players, direct)
        crosswalk, crosswalk_plan = resolve_person_crosswalk_from_espn(
            connection, releases, players, crosswalk, crosswalk_plan
        )
        logs, games = _prepare_rows(releases, crosswalk)
        _verify_score_preservation(connection, games)

        by_player_date = set()
        for row in logs:
            if row[0] is None:
                continue
            key = (row[0], row[6])
            if key in by_player_date:
                raise SportsDataverseIngestError(
                    "multiple NBA Stats appearances resolve to one player/date: {} / {}".format(*key)
                )
            by_player_date.add(key)

        source_people = {str(row["person_id"]) for release in releases for row in release["boxes"]}
        mapped_rows = sum(
            1 for release in releases for row in release["boxes"]
            if str(row["person_id"]) in crosswalk
        )
        result = {
            "seasons_loaded": [release["start_year"] for release in releases],
            "current_season_release_missing": current_year in missing,
            "boxscore_rows": sum(len(release["boxes"]) for release in releases),
            "source_games": sum(release["boxscore_games"] for release in releases),
            "mapped_games": sum(sum(bool(v) for v in release["game_id_map"].values()) for release in releases),
            "mapped_players": len(source_people.intersection(crosswalk)),
            "mapped_boxscore_rows": mapped_rows,
            "unresolved_boxscore_rows": sum(len(release["boxes"]) for release in releases) - mapped_rows,
            "inferred_player_ids": len(source_people.intersection(crosswalk_plan["inferred"])),
            "espn_resolved_player_ids": len(crosswalk_plan.get("espn_inferred", {})),
            "espn_identity_mappings": [
                {
                    "nba_stats_player_id": person_key,
                    "espn_athlete_id": crosswalk_plan["espn_ids"][person_key],
                    "legendarypicks_player_id": (
                        None if int(player_id) < 0 else int(player_id)
                    ),
                    "create_inactive_player": int(player_id) < 0,
                }
                for person_key, player_id in sorted(
                    crosswalk_plan.get("espn_inferred", {}).items()
                )
            ],
            "new_espn_player_identities": [
                {
                    "espn_id": identity["espn_id"],
                    "name": identity["name"],
                    "player_id_created_in_apply": True,
                }
                for identity in crosswalk_plan.get("new_players", {}).values()
            ],
            "espn_events_checked": crosswalk_plan.get("espn_events_checked", 0),
            "espn_events_failed": crosswalk_plan.get("espn_events_failed", 0),
            "espn_event_errors": crosswalk_plan.get("espn_event_errors", {}),
            "unresolved_player_ids": len(source_people - set(crosswalk)),
            "dnp_rows": sum(release["dnp_rows"] for release in releases),
            "unknown_appearance_rows": sum(
                release["unknown_appearance_rows"] for release in releases
            ),
            "market_missing_on_played_rows": {
                key: sum(release["market_missing"].get(key, 0) for release in releases)
                for key in MARKET_COLUMNS
            },
            "schedule_games_without_boxscore": sum(
                release["schedule_games_without_boxscore"] for release in releases
            ),
            "dry_run": dry_run,
        }
        if dry_run:
            return result
        _write(connection, releases, logs, games, crosswalk, crosswalk_plan)
        result["written_player_rows"] = len(logs)
        result["written_game_rows"] = len(games)
        return result
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DB)
    parser.add_argument("--recent-seasons", type=int, default=2,
                        help="current start-year season plus the preceding seasons")
    parser.add_argument("--season-start-years", nargs="+", type=int,
                        help="explicit seasons, keyed by NBA season start year")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch, validate and report; open the database read-only")
    args = parser.parse_args(argv)
    if args.season_start_years and args.recent_seasons != 2:
        parser.error("--season-start-years cannot be combined with a non-default --recent-seasons")
    result = ingest(args.db, recent_seasons=args.recent_seasons,
                    dry_run=args.dry_run, season_start_years=args.season_start_years)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["current_season_release_missing"]:
        current = _current_start_year()
        print("Current {}-{} SportsDataverse boxscore release is not published yet.".format(
            current, str(current + 1)[-2:]
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
