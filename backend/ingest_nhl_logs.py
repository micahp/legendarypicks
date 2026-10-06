#!/usr/bin/env python3
"""Publish current NHL regular-season logs and team evidence atomically.

The NHL publishes a complete schedule plus one box score per game.  Fetch and
validate that whole bounded population before replacing one season.  The
default is a dry run; ``--apply`` is required to write.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sqlite3
import sys
from typing import Any

import paced_http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_nfl_logs import ensure_table  # noqa: E402
from nhl_standings_store import (  # noqa: E402
    # This module defines its own SOURCE ("nhle.com"); import the standings
    # one under its own name so the two cannot shadow each other.
    SOURCE as STANDINGS_NOW_SOURCE,
    NHLStandingsError,
    ensure_table as ensure_standings_table,
    publish_snapshot as publish_standings_snapshot,
    snapshot_from_document,
)
from season_keys import normalize_season  # noqa: E402
from team_codes import UnknownTeamCode, normalize  # noqa: E402


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
SOURCE = "nhle.com"
LOG_SOURCE = "nhle.com:gamecenter/boxscore"
RESULT_SOURCE = "nhle.com:club-schedule-season+gamecenter/boxscore"
TEAM_STAT_SOURCE = "nhle.com:gamecenter/right-rail+landing"
COVERAGE_SOURCE = (
    "nhle.com:season+club-schedule-season+gamecenter/boxscore+right-rail+landing"
)
EXPECTED_TEAMS = 32
TEAM_DIRECTORY_URL = "https://api-web.nhle.com/v1/standings/now"
# The league publishes the first and last standings date of every season it has
# ever played, so a completed season's final table is a fetch, never a rollup of
# whichever of its games we happen to hold.
SEASON_LIST_URL = "https://api-web.nhle.com/v1/standings-season"
STANDINGS_ON_URL = "https://api-web.nhle.com/v1/standings/{date}"
SEASON_URL = "https://api.nhle.com/stats/rest/en/season?cayenneExp=id={season}"
SCHEDULE_URL = "https://api-web.nhle.com/v1/club-schedule-season/{team}/{season}"
BOXSCORE_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
RIGHT_RAIL_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/right-rail"
LANDING_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/landing"
COMPLETED_STATES = frozenset(("OFF", "FINAL"))
TEAM_STAT_CATEGORIES = frozenset((
    "sog", "faceoffWinningPctg", "powerPlay", "pim", "hits",
    "blockedShots", "giveaways", "takeaways",
))

_FETCH = paced_http.Fetcher(
    min_interval=float(os.environ.get("LP_NHL_MIN_INTERVAL", "0.5")),
    retry_waits=(5.0, 20.0, 60.0),
    headers={"User-Agent": "legendarypicks/1.0"},
    timeout=30,
    host_budget=0,
)


class NHLLogIngestError(RuntimeError):
    """The current NHL population cannot be published safely."""


def _get(url: str) -> dict:
    try:
        document = _FETCH.fetch(url)
    except Exception as exc:
        raise NHLLogIngestError(f"{url} failed: {exc}") from exc
    if not isinstance(document, dict):
        raise NHLLogIngestError(
            f"{url} returned {type(document).__name__}, expected object"
        )
    return document


def _canonical_team(raw: Any) -> str:
    try:
        return normalize("nhl", str(raw or ""))
    except UnknownTeamCode as exc:
        raise NHLLogIngestError(str(exc)) from exc


def _played(toi: Any) -> bool:
    value = str(toi or "").strip()
    if not value or ":" not in value:
        return False
    try:
        minutes, seconds = value.split(":", 1)
        return int(minutes) * 60 + int(seconds) > 0
    except ValueError:
        raise NHLLogIngestError(f"invalid NHL time-on-ice value {value!r}") from None


def _made_attempted(value: Any, *, game_id: str, team: str) -> tuple[int, int]:
    try:
        made, attempted = str(value).split("/", 1)
        return int(made), int(attempted)
    except (TypeError, ValueError):
        raise NHLLogIngestError(
            f"{game_id}/{team}: invalid power-play value {value!r}"
        ) from None


def _season_document(source_season: int) -> dict:
    rows = _get(SEASON_URL.format(season=source_season)).get("data") or []
    if len(rows) != 1 or int(rows[0].get("id") or 0) != int(source_season):
        raise NHLLogIngestError(
            f"season endpoint returned {len(rows)} rows for {source_season}"
        )
    row = rows[0]
    required = (
        "numberOfGames", "totalRegularSeasonGames", "startDate",
        "regularSeasonEndDate",
    )
    missing = [key for key in required if row.get(key) in (None, "")]
    if missing:
        raise NHLLogIngestError(
            f"season {source_season} is missing {', '.join(missing)}"
        )
    return row


def fetch_schedule(source_season: int) -> dict:
    """Fetch and reconcile all 32 club schedules."""
    source_codes: dict[str, str] = {}
    source_ids: dict[str, str] = {}
    standings_document = _get(TEAM_DIRECTORY_URL)
    standings = snapshot_from_document(
        standings_document,
        source_season=source_season,
        expected_teams=EXPECTED_TEAMS,
    )
    for row in standings_document.get("standings") or []:
        raw = str(((row.get("teamAbbrev") or {}).get("default")) or "").strip()
        if not raw:
            continue
        team = _canonical_team(raw)
        source_codes[team] = raw
        # standings/now does not publish a numeric team id.  Its own stable
        # club code is the source-native inventory key; never collapse the
        # population onto an invented empty id.
        source_ids[team] = raw
    if len(source_codes) != EXPECTED_TEAMS:
        raise NHLLogIngestError(
            f"team directory published {len(source_codes)} teams; expected {EXPECTED_TEAMS}"
        )

    season = _season_document(source_season)
    games_per_team = int(season["numberOfGames"])
    expected_games = int(season["totalRegularSeasonGames"])
    events: dict[str, dict] = {}
    appearances: collections.Counter[str] = collections.Counter()
    for team in sorted(source_codes):
        raw_team = source_codes[team]
        document = _get(SCHEDULE_URL.format(team=raw_team, season=source_season))
        if int(document.get("currentSeason") or 0) != int(source_season):
            raise NHLLogIngestError(
                f"{raw_team} schedule names season {document.get('currentSeason')!r}"
            )
        regular = [g for g in document.get("games") or [] if g.get("gameType") == 2]
        if len(regular) != games_per_team:
            raise NHLLogIngestError(
                f"{raw_team} published {len(regular)} regular games; expected {games_per_team}"
            )
        for game in regular:
            game_id = str(game.get("id") or "")
            away = _canonical_team((game.get("awayTeam") or {}).get("abbrev"))
            home = _canonical_team((game.get("homeTeam") or {}).get("abbrev"))
            if not game_id or away == home or away not in source_codes or home not in source_codes:
                raise NHLLogIngestError(
                    f"{raw_team} schedule has invalid game {game_id!r} {away!r}/{home!r}"
                )
            normalized = {
                "game_id": game_id,
                "game_date": str(game.get("gameDate") or "")[:10],
                "game_state": str(game.get("gameState") or ""),
                "away": away,
                "home": home,
            }
            prior = events.setdefault(game_id, normalized)
            if prior != normalized:
                raise NHLLogIngestError(
                    f"game {game_id} disagrees across club schedules"
                )
            appearances[game_id] += 1

    if len(events) != expected_games:
        raise NHLLogIngestError(
            f"club schedules published {len(events)} unique games; expected {expected_games}"
        )
    bad = [(game_id, count) for game_id, count in appearances.items() if count != 2]
    if bad:
        raise NHLLogIngestError(
            f"{len(bad)} games do not appear on exactly two club schedules"
        )
    completed = {
        game_id: game for game_id, game in events.items()
        if game["game_state"] in COMPLETED_STATES
    }
    return {
        "source_season": int(source_season),
        "season": normalize_season(SOURCE, "nhl", source_season),
        "season_start": str(season["startDate"])[:10],
        "season_end": str(season["regularSeasonEndDate"])[:10],
        "scheduled_games": len(events),
        "games_per_team": games_per_team,
        "teams": source_codes,
        "team_ids": source_ids,
        "standings": standings,
        "completed": completed,
    }


def _player_line(player: dict, group: str) -> dict:
    if group == "goalies":
        keys = (
            "saves", "shotsAgainst", "goalsAgainst", "savePctg", "decision",
            "toi", "starter", "pim", "evenStrengthShotsAgainst",
            "powerPlayShotsAgainst", "shorthandedShotsAgainst",
        )
    else:
        keys = (
            "goals", "assists", "points", "plusMinus", "pim", "hits",
            "powerPlayGoals", "sog", "faceoffWinningPctg", "toi",
            "blockedShots", "shifts", "giveaways", "takeaways",
        )
    values = {key: player[key] for key in keys if player.get(key) is not None}
    if group != "goalies" and player.get("sog") is not None:
        values["shots"] = player["sog"]
    return values


def _team_rows(game: dict, boxscore: dict, right_rail: dict, landing: dict) -> tuple[list, list]:
    game_id = game["game_id"]
    if str(boxscore.get("id") or "") != game_id:
        raise NHLLogIngestError(f"{game_id}: boxscore returned a different id")
    if boxscore.get("gameType") != 2 or str(boxscore.get("gameState")) not in COMPLETED_STATES:
        raise NHLLogIngestError(f"{game_id}: boxscore is not completed regular season")
    if str(boxscore.get("gameDate") or "")[:10] != game["game_date"]:
        raise NHLLogIngestError(f"{game_id}: boxscore date disagrees with schedule")

    sides = {}
    for side in ("away", "home"):
        raw = boxscore.get(f"{side}Team") or {}
        team = _canonical_team(raw.get("abbrev"))
        if team != game[side] or raw.get("score") is None:
            raise NHLLogIngestError(f"{game_id}: invalid {side} team or score")
        sides[side] = {"team": team, "score": float(raw["score"])}

    categories = {
        str(row.get("category")): row
        for row in right_rail.get("teamGameStats") or []
    }
    missing = sorted(TEAM_STAT_CATEGORIES - set(categories))
    if missing:
        raise NHLLogIngestError(
            f"{game_id}: team stats missing {', '.join(missing)}"
        )
    short_handed = collections.Counter()
    for period in (landing.get("summary") or {}).get("scoring") or []:
        for goal in period.get("goals") or []:
            team = _canonical_team(((goal.get("teamAbbrev") or {}).get("default")))
            if str(goal.get("strength") or "").lower() == "sh":
                short_handed[team] += 1

    results, stats = [], []
    for side, opposite in (("away", "home"), ("home", "away")):
        mine, theirs = sides[side], sides[opposite]
        team = mine["team"]
        pp_goals, pp_opps = _made_attempted(
            categories["powerPlay"].get(f"{side}Value"), game_id=game_id, team=team
        )
        faceoff = categories["faceoffWinningPctg"].get(f"{side}Value")
        values = {
            "shots": categories["sog"].get(f"{side}Value"),
            "blocked_shots": categories["blockedShots"].get(f"{side}Value"),
            "hits": categories["hits"].get(f"{side}Value"),
            "takeaways": categories["takeaways"].get(f"{side}Value"),
            "giveaways": categories["giveaways"].get(f"{side}Value"),
            "faceoff_pct": None if faceoff is None else round(float(faceoff) * 100, 3),
            "powerplay_goals": pp_goals,
            "powerplay_opps": pp_opps,
            "shorthanded_goals": int(short_handed[team]),
            "penalty_min": categories["pim"].get(f"{side}Value"),
        }
        absent = sorted(key for key, value in values.items() if value is None)
        if absent:
            raise NHLLogIngestError(
                f"{game_id}/{team}: incomplete team stats {', '.join(absent)}"
            )
        results.append({
            "game_id": game_id, "game_date": game["game_date"], "team": team,
            "opponent": theirs["team"], "home_away": side,
            "score_for": mine["score"], "score_against": theirs["score"],
            "win": int(mine["score"] > theirs["score"]),
        })
        stats.append({
            "game_id": game_id, "team": team, "home_away": side, "values": values,
        })
    return results, stats


def _player_rows(game: dict, boxscore: dict) -> list[dict]:
    game_id = game["game_id"]
    by_game = boxscore.get("playerByGameStats") or {}
    rows, seen = [], set()
    for side, opposite in (("away", "home"), ("home", "away")):
        groups = by_game.get(f"{side}Team") or {}
        for group in ("forwards", "defense", "goalies"):
            players = groups.get(group) or []
            if group != "goalies" and not players:
                raise NHLLogIngestError(f"{game_id}/{game[side]}: empty {group} group")
            for player in players:
                if not _played(player.get("toi")):
                    if group == "goalies":
                        continue
                    raise NHLLogIngestError(
                        f"{game_id}: skater {player.get('playerId')} has no time on ice"
                    )
                source_key = str(player.get("playerId") or "")
                if not source_key or source_key in seen:
                    raise NHLLogIngestError(
                        f"{game_id}: missing or duplicate player id {source_key!r}"
                    )
                seen.add(source_key)
                rows.append({
                    "source_player_key": source_key,
                    "game_id": game_id,
                    "game_date": game["game_date"],
                    "team": game[side],
                    "opponent": game[opposite],
                    "home_away": side,
                    "stats": _player_line(player, group),
                })
    if not rows:
        raise NHLLogIngestError(f"{game_id}: no player appearances")
    return rows


def build_publication(db_path: str, *, source_season: int) -> dict:
    publication = fetch_schedule(source_season)
    player_rows, result_rows, stat_rows = [], [], []
    for game_id in sorted(publication["completed"]):
        game = publication["completed"][game_id]
        boxscore = _get(BOXSCORE_URL.format(game_id=game_id))
        results, stats = _team_rows(
            game,
            boxscore,
            _get(RIGHT_RAIL_URL.format(game_id=game_id)),
            _get(LANDING_URL.format(game_id=game_id)),
        )
        result_rows.extend(results)
        stat_rows.extend(stats)
        player_rows.extend(_player_rows(game, boxscore))

    completed_games = len(publication["completed"])
    if len(result_rows) != completed_games * 2 or len(stat_rows) != completed_games * 2:
        raise NHLLogIngestError(
            f"pair invariant failed: games={completed_games} "
            f"results={len(result_rows)} stats={len(stat_rows)}"
        )

    connection = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        owners: dict[str, list[int]] = collections.defaultdict(list)
        for row in connection.execute(
            "SELECT id,nhl_id FROM players WHERE league='nhl' AND nhl_id IS NOT NULL"
        ):
            owners[str(row["nhl_id"])].append(int(row["id"]))
    finally:
        connection.close()
    duplicate_ids = sorted(key for key, values in owners.items() if len(values) != 1)
    if duplicate_ids:
        raise NHLLogIngestError(
            f"{len(duplicate_ids)} NHL ids have duplicate canonical owners"
        )
    unresolved = sorted({
        row["source_player_key"] for row in player_rows
        if row["source_player_key"] not in owners
    })
    if unresolved:
        raise NHLLogIngestError(
            f"{len(unresolved)} participants have no nhl_id owner: "
            + ", ".join(unresolved[:10])
        )
    for row in player_rows:
        row["player_id"] = owners[row["source_player_key"]][0]

    publication.update({
        "player_rows": player_rows,
        "result_rows": result_rows,
        "stat_rows": stat_rows,
        "completed_games": completed_games,
        "checked_through": max(
            (game["game_date"] for game in publication["completed"].values()),
            default=None,
        ),
    })
    return publication


def publish(db_path: str, publication: dict, *, apply: bool) -> dict:
    summary = {
        "status": "published" if apply else "ready",
        "source_season": publication["source_season"],
        "season": publication["season"],
        "teams": len(publication["teams"]),
        "games_per_team": publication["games_per_team"],
        "scheduled_games": publication["scheduled_games"],
        "completed_games": publication["completed_games"],
        "player_logs": len(publication["player_rows"]),
        "standings_teams": len(publication["standings"]["teams"]),
        "checked_through": publication["checked_through"],
    }
    if not apply:
        return summary

    captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    run_id = "nhl-current-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    season = int(publication["season"])
    connection = sqlite3.connect(db_path, timeout=60, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=60000")
    ensure_table(connection)
    ensure_standings_table(connection)
    required_tables = {
        "team_game_results", "team_game_stats", "team_stats_coverage",
        "team_stats_team_inventory", "team_stats_ingestion_failures",
    }
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing_tables = sorted(required_tables - tables)
    if missing_tables:
        connection.close()
        raise NHLLogIngestError(
            "database is missing team-stat tables: " + ", ".join(missing_tables)
        )
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM team_game_stats WHERE league='nhl' AND game_id IN "
            "(SELECT game_id FROM team_game_results WHERE league='nhl' AND season=?)",
            (season,),
        )
        connection.execute(
            "DELETE FROM team_game_results WHERE league='nhl' AND season=?", (season,)
        )
        connection.execute(
            "DELETE FROM player_game_logs WHERE league='nhl' AND season=?", (season,)
        )
        connection.execute(
            "DELETE FROM team_stats_coverage WHERE league='nhl' AND season=?", (season,)
        )
        for row in publication["player_rows"]:
            connection.execute(
                """INSERT INTO player_game_logs(
                     player_id,league,season,game_no,game_id,game_date,team,opponent,
                     home_away,game_type,stats,source,source_player_key
                   ) VALUES(?,'nhl',?,?,?,?,?,?,?,'REG',?,?,?)""",
                (
                    row["player_id"], season, row["game_id"], row["game_id"],
                    row["game_date"], row["team"], row["opponent"],
                    row["home_away"], json.dumps(row["stats"], sort_keys=True),
                    LOG_SOURCE, row["source_player_key"],
                ),
            )
        for row in publication["result_rows"]:
            connection.execute(
                """INSERT INTO team_game_results(
                     league,game_id,team,game_date,opponent,home_away,score_for,
                     score_against,win,season,status,source,run_id
                   ) VALUES('nhl',?,?,?,?,?,?,?,?,?,'completed',?,?)""",
                (
                    row["game_id"], row["team"], row["game_date"], row["opponent"],
                    row["home_away"], row["score_for"], row["score_against"],
                    row["win"], season, RESULT_SOURCE, run_id,
                ),
            )
        for row in publication["stat_rows"]:
            values = row["values"]
            connection.execute(
                """INSERT OR REPLACE INTO team_game_stats(
                     league,game_id,captured_at,team_abbrev,home_away,run_id,source,
                     shots,blocked_shots,hits,takeaways,giveaways,faceoff_pct,
                     powerplay_goals,powerplay_opps,shorthanded_goals,penalty_min,stats
                   ) VALUES('nhl',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["game_id"], captured_at, row["team"], row["home_away"],
                    run_id, TEAM_STAT_SOURCE, values["shots"],
                    values["blocked_shots"], values["hits"], values["takeaways"],
                    values["giveaways"], values["faceoff_pct"],
                    values["powerplay_goals"], values["powerplay_opps"],
                    values["shorthanded_goals"], values["penalty_min"],
                    json.dumps(values, sort_keys=True),
                ),
            )
        for team in sorted(publication["teams"]):
            connection.execute(
                "INSERT INTO team_stats_team_inventory(run_id,team_id,team_abbrev) "
                "VALUES(?,?,?)",
                (run_id, publication["team_ids"][team], team),
            )
        manifest_status = (
            "complete"
            if publication["completed_games"] == publication["scheduled_games"]
            else "in_progress"
        )
        columns = (
            "run_id", "league", "season", "season_start", "season_end", "status",
            "expected_teams", "fetched_teams", "expected_games", "fetched_games",
            "paired_games", "paired_stat_games", "failure_count", "completed_at",
            "source", "checked_through",
        )
        values = (
            run_id, "nhl", season, publication["season_start"],
            publication["season_end"], manifest_status, EXPECTED_TEAMS,
            len(publication["teams"]), publication["completed_games"],
            publication["completed_games"], publication["completed_games"],
            publication["completed_games"], 0, captured_at, COVERAGE_SOURCE,
            publication["checked_through"],
        )
        connection.execute(
            f"INSERT INTO team_stats_coverage({','.join(columns)}) "
            f"VALUES({','.join('?' for _ in columns)})",
            values,
        )
        publish_standings_snapshot(
            connection, publication["standings"], captured_at=captured_at
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    summary["run_id"] = run_id
    summary["manifest_status"] = manifest_status
    return summary


def refresh(db_path: str, *, source_season: int, apply: bool = False) -> dict:
    return publish(
        db_path,
        build_publication(db_path, source_season=source_season),
        apply=apply,
    )


def standings_endpoint(source_season: int) -> tuple[str, str]:
    """Which standings URL publishes this season, and what to record as source.

    `standings/now` is only correct for the season the league is currently
    playing; asking it for 20252026 returns this season's table under last
    season's name. For any earlier season the league publishes that season's
    own `standingsEnd` date, so the final table is read from there.
    """
    document = _get(SEASON_LIST_URL)
    seasons = document.get("seasons") if isinstance(document, dict) else document
    if not isinstance(seasons, list) or not seasons:
        raise NHLStandingsError("nhle.com published no standings season list")
    entry = next(
        (row for row in seasons
         if isinstance(row, dict) and int(row.get("id") or 0) == int(source_season)),
        None,
    )
    if entry is None:
        raise NHLStandingsError(
            f"nhle.com does not publish standings for season {source_season}"
        )
    current = max(int(row.get("id") or 0) for row in seasons if isinstance(row, dict))
    if int(source_season) == current:
        return TEAM_DIRECTORY_URL, STANDINGS_NOW_SOURCE
    end = str(entry.get("standingsEnd") or "")[:10]
    if len(end) != 10:
        raise NHLStandingsError(
            f"season {source_season} publishes no standingsEnd date"
        )
    return STANDINGS_ON_URL.format(date=end), f"nhle.com:standings/{end}"


def refresh_standings(
    db_path: str, *, source_season: int, apply: bool = False
) -> dict:
    """Publish the official season-named standings without fetching game boxes."""
    url, source = standings_endpoint(source_season)
    snapshot = snapshot_from_document(
        _get(url),
        source_season=source_season,
        expected_teams=EXPECTED_TEAMS,
        source=source,
    )
    summary = {
        "status": "published" if apply else "ready",
        "season": snapshot["season"],
        "season_label": snapshot["season_label"],
        "standings_date": snapshot["standings_date"],
        "teams": len(snapshot["teams"]),
        "source": snapshot["source"],
    }
    if not apply:
        return summary

    captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    connection = sqlite3.connect(db_path, timeout=60, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=60000")
    ensure_standings_table(connection)
    try:
        connection.execute("BEGIN IMMEDIATE")
        publish_standings_snapshot(connection, snapshot, captured_at=captured_at)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    summary["captured_at"] = captured_at
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True,
                        help="nhle.com season key, e.g. 20262027, or 'current' for the "
                             "season the NHL publishes as current (club-schedule-season/now), "
                             "so a scheduled run never pins one year")
    parser.add_argument("--db", default=DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--standings-only", action="store_true",
        help="fetch and publish only the official 32-team standings snapshot",
    )
    args = parser.parse_args(argv)
    if args.season == "current":
        raw = _get("https://api-web.nhle.com/v1/club-schedule-season/CHI/now").get("currentSeason")
        try:
            args.season = int(raw)
        except (TypeError, ValueError):
            raise NHLLogIngestError("invalid current NHL season %r" % (raw,))
    else:
        args.season = int(args.season)
    action = refresh_standings if args.standings_only else refresh
    result = action(
        os.path.abspath(args.db), source_season=args.season, apply=args.apply
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not args.apply:
        print("DRY RUN -- nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
