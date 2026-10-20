#!/usr/bin/env python3
"""Read-only audit of NHL per-player outcome and quote coverage.

No model fitting, score calculation, ROI, or database writes. The source DuckDB is
opened read-only. SQLite uses mode=ro&immutable=1 and query_only.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import itertools
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_SBR = ROOT / "research/nhl/sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz"
DEFAULT_CANONICAL = Path(
    "/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26/"
    "canonical_games_v1_7cd2fc9a6e84470c.csv"
)
DEFAULT_DUCKDB = Path("/root/nhl_database_2025-26-playoffs.duckdb")
DEFAULT_PICKS_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
TARGET_LABELS = ("2018-19", "2019-20", "2020-21", "2021-22", "2022-23")
EXPECTED_GAMES = {
    "2018-19": 1271,
    "2019-20": 1082,
    "2020-21": 868,
    "2021-22": 1312,
    "2022-23": 339,
}
EXPECTED_OUTCOMES = {
    "2018-19": (45756, 906, 45756, 2720, 93, 2720),
    "2019-20": (38931, 883, 38931, 2305, 85, 2305),
    "2020-21": (31196, 913, 31196, 1852, 98, 1852),
    "2021-22": (47206, 1003, 47206, 2818, 119, 2818),
    "2022-23": (12200, 761, 12200, 715, 74, 715),
}
EXPECTED_MARKET_ROWS = {
    "assists": 24226,
    "blocked_shots": 950,
    "faceoffs_won": 760,
    "goals": 2060,
    "goals_allowed": 294,
    "hits": 1090,
    "plus_minus": 166,
    "points": 21740,
    "saves": 3360,
    "shots": 28020,
    "time_on_ice": 1054,
}
EXPECTED_MARKET_PREGAME = {
    "assists": 24226,
    "blocked_shots": 950,
    "faceoffs_won": 760,
    "goals": 2060,
    "goals_allowed": 294,
    "hits": 1090,
    "plus_minus": 166,
    "points": 21740,
    "saves": 3296,
    "shots": 27658,
    "time_on_ice": 1054,
}
EXPECTED_PRICE_TOTALS = {
    "rows": 83720,
    "players": 678,
    "games": 149,
    "with_line_and_capture": 83720,
    "with_odds_and_odds_timestamp": 83720,
    "pregame": 83294,
    "at_or_after_start": 426,
    "start_time_unknown": 0,
    "target_window_rows": 0,
    "snapshot_rows": 0,
    "requested_market_rows": 55180,
    "distinct_markets": 11,
    "research_player_price_rows": 0,
}
TEAM_ALIASES = {"PHX": "ARI"}
SBR_TEAM_CODES = {
    "Anaheim": ("ANA",),
    "Arizona": ("ARI", "PHX"),
    "Arizonas": ("ARI", "PHX"),
    "Boston": ("BOS",),
    "Buffalo": ("BUF",),
    "Calgary": ("CGY",),
    "Carolina": ("CAR",),
    "Chicago": ("CHI",),
    "Colorado": ("COL",),
    "Columbus": ("CBJ",),
    "Dallas": ("DAL",),
    "Detroit": ("DET",),
    "Edmonton": ("EDM",),
    "Florida": ("FLA",),
    "Los Angeles": ("LAK",),
    "LosAngeles": ("LAK",),
    "Minnesota": ("MIN",),
    "Montreal": ("MTL",),
    "NY Islanders": ("NYI",),
    "NYIslanders": ("NYI",),
    "NY Rangers": ("NYR",),
    "NYRangers": ("NYR",),
    "Nashville": ("NSH",),
    "New Jersey": ("NJD",),
    "NewJersey": ("NJD",),
    "Ottawa": ("OTT",),
    "Philadelphia": ("PHI",),
    "Pittsburgh": ("PIT",),
    "San Jose": ("SJS",),
    "SanJose": ("SJS",),
    "Seattle": ("SEA",),
    "Seattle Kraken": ("SEA",),
    "SeattleKraken": ("SEA",),
    "St. Louis": ("STL",),
    "St.Louis": ("STL",),
    "Tampa Bay": ("TBL",),
    "TampaBay": ("TBL",),
    "Toronto": ("TOR",),
    "Vancouver": ("VAN",),
    "Vegas": ("VGK",),
    "Washington": ("WSH",),
    "Winnipeg": ("WPG",),
}
PLAYER_KEYS = {
    "player",
    "playerid",
    "player_id",
    "playername",
    "player_name",
    "athleteid",
    "athlete_id",
}
LINE_KEYS = {"line", "marketline", "market_line", "linevalue", "line_value"}
CAPTURE_KEYS = {
    "capturedat",
    "captured_at",
    "capturedatutc",
    "captured_at_utc",
    "capturetimestamp",
    "capture_timestamp",
    "capturetime",
    "capture_time",
}
PROP_MARKET_TERMS = (
    "shot",
    "sog",
    "save",
    "goal",
    "point",
)


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def norm_team(value: str) -> str:
    return TEAM_ALIASES.get(value, value)


def parse_sbr_date(season_label: str, mmdd: Any) -> str:
    pieces = season_label.split("-")
    if len(pieces) != 2:
        raise ValueError(f"unexpected SBR season label: {season_label!r}")
    start_year = int(pieces[0])
    month, day = divmod(int(mmdd), 100)
    year = start_year if month >= 10 else start_year + 1
    return dt.date(year, month, day).isoformat()


def load_canonical(path: Path) -> tuple[dict[int, dict[str, str]], dict]:
    require_file(path, "canonical game table")
    required = {"game_id", "game_date", "season", "game_type", "home_team", "away_team"}
    by_id: dict[int, dict[str, str]] = {}
    by_date_pair: dict[tuple[str, tuple[str, str]], list[dict[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            missing = required - set(reader.fieldnames or ())
            raise ValueError(f"canonical game table missing columns: {sorted(missing)}")
        for row in reader:
            game_id = int(row["game_id"])
            if game_id in by_id:
                raise ValueError(f"duplicate canonical game_id {game_id}")
            by_id[game_id] = row
            pair = tuple(sorted((row["home_team"], row["away_team"])))
            by_date_pair[(row["game_date"], pair)].append(row)
    if not by_id:
        raise ValueError("canonical game table is empty")
    return by_id, {"by_date_pair": by_date_pair}


def load_sbr_crosswalk(
    sbr_path: Path, canonical_path: Path
) -> tuple[dict[int, dict], dict[str, dict]]:
    require_file(sbr_path, "SBR game archive")
    canonical, lookup = load_canonical(canonical_path)
    by_date_pair = lookup["by_date_pair"]
    linked: dict[int, dict] = {}
    sbr_by_id: dict[int, dict] = {}
    unmatched: list[tuple[int, str, str, str, int]] = []
    venue_mismatches: list[tuple[int, str, str, str, str, str]] = []

    with gzip.open(sbr_path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid SBR JSON at line {line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"SBR line {line_number} is not an object")
            home_name = row["home"]["team"]
            away_name = row["away"]["team"]
            if home_name not in SBR_TEAM_CODES or away_name not in SBR_TEAM_CODES:
                raise ValueError(
                    f"unmapped SBR team at line {line_number}: {home_name!r}/{away_name!r}"
                )
            date = parse_sbr_date(row["season"], row["date"])
            candidates: dict[int, dict[str, str]] = {}
            for home_code, away_code in itertools.product(
                SBR_TEAM_CODES[home_name], SBR_TEAM_CODES[away_name]
            ):
                pair = tuple(sorted((home_code, away_code)))
                for candidate in by_date_pair.get((date, pair), []):
                    candidates[int(candidate["game_id"])] = candidate
            if len(candidates) != 1:
                unmatched.append(
                    (line_number, date, home_name, away_name, len(candidates))
                )
                continue
            game_id, canonical_row = next(iter(candidates.items()))
            if game_id in linked:
                raise ValueError(f"multiple SBR rows resolve to canonical game_id {game_id}")
            linked[game_id] = {
                "sbr": row,
                "canonical": canonical_row,
                "date": date,
                "season_label": row["season"],
            }
            sbr_by_id[game_id] = row
            if (
                canonical_row["home_team"] not in SBR_TEAM_CODES[home_name]
                or canonical_row["away_team"] not in SBR_TEAM_CODES[away_name]
            ):
                venue_mismatches.append(
                    (
                        game_id,
                        date,
                        home_name,
                        away_name,
                        canonical_row["home_team"],
                        canonical_row["away_team"],
                    )
                )

    if unmatched:
        print(f"SBR_UNMATCHED_OR_AMBIGUOUS rows={len(unmatched)}")
        for item in unmatched[:20]:
            print("SBR_UNMATCHED", item)
        raise ValueError("SBR-to-canonical crosswalk is incomplete")
    if len(linked) != 5132:
        raise ValueError(f"SBR archive/crosswalk row count changed: {len(linked)} != 5132")
    if len(linked) != len(sbr_by_id):
        raise ValueError("SBR crosswalk is not one-to-one")

    target = {
        game_id: info
        for game_id, info in linked.items()
        if int(info["canonical"]["game_type"]) == 2
    }
    if len(target) != 4872:
        raise ValueError(f"regular-season target games changed: {len(target)} != 4872")
    playoff_games = len(linked) - len(target)
    if playoff_games != 260:
        raise ValueError(f"crosswalk playoff game count changed: {playoff_games} != 260")

    games_by_season = Counter(info["season_label"] for info in target.values())
    if dict(games_by_season) != EXPECTED_GAMES:
        raise ValueError(
            f"target game counts changed: {dict(games_by_season)} != {EXPECTED_GAMES}"
        )
    if len(venue_mismatches) != 1:
        raise ValueError(
            f"venue-order mismatch count changed: {len(venue_mismatches)} != 1"
        )

    print(
        "SBR_CANONICAL_CROSSWALK "
        f"archive_rows={len(linked)} unique_canonical_gameIds={len(linked)} "
        f"regular_season_games={len(target)} playoff_games={playoff_games} "
        f"unmatched_or_ambiguous=0 venue_order_mismatches={len(venue_mismatches)}"
    )
    for mismatch in venue_mismatches:
        print(
            "VENUE_ORDER_MISMATCH "
            f"gameId={mismatch[0]} date={mismatch[1]} "
            f"sbr_home={mismatch[2]} sbr_away={mismatch[3]} "
            f"canonical_home={mismatch[4]} canonical_away={mismatch[5]}"
        )
    for label in TARGET_LABELS:
        dates = sorted(info["date"] for info in target.values() if info["season_label"] == label)
        print(
            f"TARGET_SEASON season={label} regular_games={games_by_season[label]} "
            f"date_span={dates[0]}..{dates[-1]}"
        )
    return target, linked


def source_date(value: Any) -> str:
    text = str(value)
    if text.endswith(".0"):
        text = text[:-2]
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid source gameDate: {value!r}")
    return dt.datetime.strptime(text, "%Y%m%d").date().isoformat()


def validate_source_identity(
    label: str,
    season: Any,
    game_id: Any,
    game_date: Any,
    team: Any,
    info: dict,
) -> int:
    if any(value is None for value in (season, game_id, game_date, team)):
        raise ValueError(f"{label} row has null identity: {season, game_id, game_date, team}")
    season = int(season)
    game_id = int(game_id)
    canonical = info["canonical"]
    if season != int(canonical["season"]):
        raise ValueError(
            f"{label} season mismatch at gameId={game_id}: {season} != {canonical['season']}"
        )
    canonical_date = canonical["game_date"]
    if source_date(game_date) != canonical_date:
        raise ValueError(
            f"{label} date mismatch at gameId={game_id}: "
            f"{source_date(game_date)} != {canonical_date}"
        )
    sides = {norm_team(canonical["home_team"]), norm_team(canonical["away_team"])}
    if norm_team(str(team)) not in sides:
        raise ValueError(
            f"{label} team mismatch at gameId={game_id}: {team!r} not in {sorted(sides)}"
        )
    return season


def audit_outcomes(target: dict[int, dict], duckdb_path: Path) -> dict[str, dict]:
    require_file(duckdb_path, "NHL DuckDB source")
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "DuckDB reader missing; use /root/lp-goalie-research/.venv/bin/python"
        ) from exc

    connection = duckdb.connect(
        str(duckdb_path),
        read_only=True,
        config={"memory_limit": "256MB", "threads": "1"},
    )
    try:
        skater_columns = {
            row[0] for row in connection.execute("DESCRIBE SELECT * FROM skaters_gamelogs").fetchall()
        }
        goalie_columns = {
            row[0] for row in connection.execute("DESCRIBE SELECT * FROM goalies_gamelogs").fetchall()
        }
        required_skater = {
            "season", "gameId", "gameDate", "playerId", "playerTeam",
            "situation", "I_F_shotsOnGoal",
        }
        required_goalie = {
            "season", "gameId", "gameDate", "playerId", "playerTeam",
            "situation", "ongoal", "goals",
        }
        if not required_skater.issubset(skater_columns):
            raise ValueError(
                f"skaters_gamelogs missing columns: {sorted(required_skater - skater_columns)}"
            )
        if not required_goalie.issubset(goalie_columns):
            raise ValueError(
                f"goalies_gamelogs missing columns: {sorted(required_goalie - goalie_columns)}"
            )
        skater_rows = connection.execute(
            "SELECT season, gameId, gameDate, playerId, playerTeam, I_F_shotsOnGoal "
            "FROM skaters_gamelogs WHERE lower(situation)='all' AND season BETWEEN 2018 AND 2022"
        ).fetchall()
        goalie_rows = connection.execute(
            "SELECT season, gameId, gameDate, playerId, playerTeam, ongoal, goals "
            "FROM goalies_gamelogs WHERE lower(situation)='all' AND season BETWEEN 2018 AND 2022"
        ).fetchall()
    finally:
        connection.close()

    print(
        "SOG_SOURCE table=skaters_gamelogs situation=all "
        "column=I_F_shotsOnGoal key=season+gameId+playerId gameId=canonical"
    )
    print(
        "SAVES_SOURCE table=goalies_gamelogs situation=all "
        "formula=ongoal-goals key=season+gameId+playerId"
    )
    stats = {
        label: {
            "games": EXPECTED_GAMES[label],
            "skater_player_games": 0,
            "distinct_skaters": set(),
            "sog_values": 0,
            "sog_zero": 0,
            "goalie_player_games": 0,
            "distinct_goalies": set(),
            "nonnegative_saves": 0,
            "source_skater_game_ids": set(),
            "source_goalie_game_ids": set(),
        }
        for label in TARGET_LABELS
    }
    skater_keys: set[tuple[int, int, int]] = set()
    goalie_keys: set[tuple[int, int, int]] = set()
    skater_invalid: list[tuple] = []
    goalie_anomalies: list[tuple] = []
    skater_alias_rows = 0
    goalie_alias_rows = 0

    for season, game_id, game_date, player_id, team, sog in skater_rows:
        game_id = int(game_id)
        if game_id not in target:
            continue
        info = target[game_id]
        season = validate_source_identity(
            "skaters_gamelogs", season, game_id, game_date, team, info
        )
        label = info["season_label"]
        player_id = int(player_id)
        key = (season, game_id, player_id)
        if key in skater_keys:
            raise ValueError(f"duplicate all-situation skater player-game: {key}")
        skater_keys.add(key)
        row = stats[label]
        row["skater_player_games"] += 1
        row["distinct_skaters"].add(player_id)
        row["source_skater_game_ids"].add(game_id)
        if norm_team(str(team)) != str(team):
            skater_alias_rows += 1
        if sog is None:
            skater_invalid.append((label, game_id, player_id, team, "missing"))
            continue
        value = float(sog)
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            skater_invalid.append((label, game_id, player_id, team, sog))
            continue
        row["sog_values"] += 1
        if value == 0:
            row["sog_zero"] += 1

    for season, game_id, game_date, player_id, team, ongoal, goals in goalie_rows:
        game_id = int(game_id)
        if game_id not in target:
            continue
        info = target[game_id]
        season = validate_source_identity(
            "goalies_gamelogs", season, game_id, game_date, team, info
        )
        label = info["season_label"]
        player_id = int(player_id)
        key = (season, game_id, player_id)
        if key in goalie_keys:
            raise ValueError(f"duplicate all-situation goalie player-game: {key}")
        goalie_keys.add(key)
        row = stats[label]
        row["goalie_player_games"] += 1
        row["distinct_goalies"].add(player_id)
        row["source_goalie_game_ids"].add(game_id)
        if norm_team(str(team)) != str(team):
            goalie_alias_rows += 1
        if ongoal is None or goals is None:
            goalie_anomalies.append(
                (label, game_id, player_id, team, ongoal, goals, None, "missing")
            )
            continue
        ongoal_value, goals_value = float(ongoal), float(goals)
        saves = ongoal_value - goals_value
        if (
            not math.isfinite(ongoal_value)
            or not math.isfinite(goals_value)
            or not saves.is_integer()
        ):
            goalie_anomalies.append(
                (label, game_id, player_id, team, ongoal, goals, saves, "noninteger_or_nonfinite")
            )
        elif saves < 0:
            goalie_anomalies.append(
                (label, game_id, player_id, team, ongoal, goals, saves, "negative")
            )
        else:
            row["nonnegative_saves"] += 1

    skater_game_ids = set().union(*(stats[label]["source_skater_game_ids"] for label in TARGET_LABELS))
    goalie_game_ids = set().union(*(stats[label]["source_goalie_game_ids"] for label in TARGET_LABELS))
    target_game_ids = set(target)
    if skater_game_ids != target_game_ids:
        missing = sorted(target_game_ids - skater_game_ids)
        extra = sorted(skater_game_ids - target_game_ids)
        raise ValueError(f"skater game coverage mismatch: missing={missing[:10]} extra={extra[:10]}")
    if goalie_game_ids != target_game_ids:
        missing = sorted(target_game_ids - goalie_game_ids)
        extra = sorted(goalie_game_ids - target_game_ids)
        raise ValueError(f"goalie game coverage mismatch: missing={missing[:10]} extra={extra[:10]}")
    if skater_invalid:
        print(f"SOG_INVALID_ROWS count={len(skater_invalid)}")
        for case in skater_invalid:
            print("SOG_INVALID", case)
        raise ValueError("SOG field has missing, negative, noninteger, or nonfinite values")
    if goalie_anomalies:
        print(f"SAVES_ANOMALIES count={len(goalie_anomalies)}")
        for case in goalie_anomalies:
            print("SAVES_ANOMALY", case)
        raise ValueError("goalie saves contain missing, negative, noninteger, or nonfinite cases")

    for label in TARGET_LABELS:
        row = stats[label]
        row["distinct_skaters_count"] = len(row["distinct_skaters"])
        row["distinct_goalies_count"] = len(row["distinct_goalies"])
        observed = (
            row["skater_player_games"],
            row["distinct_skaters_count"],
            row["sog_values"],
            row["goalie_player_games"],
            row["distinct_goalies_count"],
            row["nonnegative_saves"],
        )
        if observed != EXPECTED_OUTCOMES[label]:
            raise ValueError(
                f"outcome counts changed for {label}: {observed} != {EXPECTED_OUTCOMES[label]}"
            )
        if row["sog_values"] != row["skater_player_games"]:
            raise ValueError(f"SOG coverage is incomplete for {label}")
        if row["nonnegative_saves"] != row["goalie_player_games"]:
            raise ValueError(f"goalie saves coverage is incomplete for {label}")
        print(
            f"OUTCOME_SEASON season={label} target_games={row['games']} "
            f"skater_player_games={row['skater_player_games']} "
            f"distinct_skaters={row['distinct_skaters_count']} "
            f"sog_values={row['sog_values']} sog_zero={row['sog_zero']} "
            f"goalie_player_games={row['goalie_player_games']} "
            f"distinct_goalies={row['distinct_goalies_count']} "
            f"nonnegative_saves={row['nonnegative_saves']}"
        )

    totals = {
        key: sum(stats[label][key] for label in TARGET_LABELS)
        for key in (
            "skater_player_games",
            "sog_values",
            "sog_zero",
            "goalie_player_games",
            "nonnegative_saves",
        )
    }
    print(
        "OUTCOME_TOTALS "
        f"target_games={len(target)} source_skater_game_ids={len(skater_game_ids)} "
        f"skater_player_games={totals['skater_player_games']} "
        f"sog_values={totals['sog_values']} sog_zero={totals['sog_zero']} "
        f"source_goalie_game_ids={len(goalie_game_ids)} "
        f"goalie_player_games={totals['goalie_player_games']} "
        f"nonnegative_saves={totals['nonnegative_saves']} "
        f"identity_rows_checked={totals['skater_player_games'] + totals['goalie_player_games']} "
        "identity_mismatches=0 sog_missing_or_invalid=0 saves_missing_or_negative_or_invalid=0 "
        f"skater_team_alias_rows={skater_alias_rows} goalie_team_alias_rows={goalie_alias_rows}"
    )
    return stats



def audit_official_spotcheck(duckdb_path: Path) -> dict[str, int]:
    """Compare one targeted local SOG inconsistency to NHL GameCenter."""
    game_id = 2018020160
    url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
    request = Request(url, headers={"User-Agent": "nhl-prop-feasibility-audit/1.0"})
    with urlopen(request, timeout=20) as response:
        official = json.load(response)
    if int(official.get("id", -1)) != game_id or int(official.get("gameType", -1)) != 2:
        raise ValueError(f"official NHL GameCenter returned wrong game identity: {url}")

    box = official.get("playerByGameStats")
    if not isinstance(box, dict):
        raise ValueError("official NHL GameCenter response has no playerByGameStats")
    official_skaters: dict[int, int] = {}
    official_goalies: dict[int, tuple[float, float, float]] = {}
    for side in ("homeTeam", "awayTeam"):
        team_data = box.get(side)
        if not isinstance(team_data, dict):
            raise ValueError(f"official GameCenter response missing {side}")
        for group in ("forwards", "defense"):
            for player in team_data.get(group, []):
                if player.get("playerId") is None or player.get("sog") is None:
                    continue
                official_skaters[int(player["playerId"])] = int(player["sog"])
        for goalie in team_data.get("goalies", []):
            if goalie.get("playerId") is None:
                continue
            if any(goalie.get(field) is None for field in ("saves", "shotsAgainst", "goalsAgainst")):
                continue
            official_goalies[int(goalie["playerId"])] = (
                float(goalie["saves"]),
                float(goalie["shotsAgainst"]),
                float(goalie["goalsAgainst"]),
            )

    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("DuckDB is required for the official sample comparison") from exc
    connection = duckdb.connect(
        str(duckdb_path),
        read_only=True,
        config={"memory_limit": "128MB", "threads": "1"},
    )
    try:
        local_skaters = connection.execute(
            "SELECT playerId, I_F_shotsOnGoal FROM skaters_gamelogs "
            "WHERE gameId=? AND lower(situation)='all'",
            [game_id],
        ).fetchall()
        local_goalies = connection.execute(
            "SELECT playerId, ongoal, goals FROM goalies_gamelogs "
            "WHERE gameId=? AND lower(situation)='all'",
            [game_id],
        ).fetchall()
    finally:
        connection.close()

    source_skaters: dict[int, int] = {}
    for player_id, sog in local_skaters:
        if player_id is None or sog is None:
            raise ValueError(f"local SOG sample has missing identity/value: {player_id, sog}")
        player_id = int(player_id)
        if player_id in source_skaters:
            raise ValueError(f"duplicate local SOG sample playerId={player_id}")
        source_skaters[player_id] = int(float(sog))
    source_goalies: dict[int, tuple[float, float]] = {}
    for player_id, ongoal, goals in local_goalies:
        if player_id is None or ongoal is None or goals is None:
            raise ValueError(f"local goalie sample has missing identity/value: {player_id, ongoal, goals}")
        player_id = int(player_id)
        if player_id in source_goalies:
            raise ValueError(f"duplicate local goalie sample playerId={player_id}")
        source_goalies[player_id] = (float(ongoal), float(goals))

    matched_skaters = set(official_skaters) & set(source_skaters)
    sog_mismatches = [
        (player_id, official_skaters[player_id], source_skaters[player_id])
        for player_id in sorted(matched_skaters)
        if official_skaters[player_id] != source_skaters[player_id]
    ]
    matched_goalies = set(official_goalies) & set(source_goalies)
    goalie_mismatches = []
    for player_id in sorted(matched_goalies):
        official_saves, official_shots_against, official_goals_against = official_goalies[player_id]
        local_ongoal, local_goals = source_goalies[player_id]
        local_saves = local_ongoal - local_goals
        if (
            official_saves != local_saves
            or official_shots_against != local_ongoal
            or official_goals_against != local_goals
        ):
            goalie_mismatches.append(
                (
                    player_id,
                    official_saves,
                    official_shots_against,
                    official_goals_against,
                    local_saves,
                    local_ongoal,
                    local_goals,
                )
            )

    unmatched_official_goalies = set(official_goalies) - set(source_goalies)
    zero_stat_unmatched_goalies = sum(
        official_goalies[player_id] == (0.0, 0.0, 0.0)
        for player_id in unmatched_official_goalies
    )
    actual = {
        "skaters_matched": len(matched_skaters),
        "skaters_unmatched": len(set(official_skaters) ^ set(source_skaters)),
        "sog_mismatch_rows": len(sog_mismatches),
        "goalies_matched": len(matched_goalies),
        "goalies_unmatched": len(set(official_goalies) ^ set(source_goalies)),
        "zero_stat_unmatched_goalies": zero_stat_unmatched_goalies,
        "saves_mismatch_rows": len(goalie_mismatches),
    }
    expected = {
        "skaters_matched": 36,
        "skaters_unmatched": 0,
        "sog_mismatch_rows": 2,
        "goalies_matched": 2,
        "goalies_unmatched": 2,
        "zero_stat_unmatched_goalies": 2,
        "saves_mismatch_rows": 0,
    }
    if actual != expected:
        raise ValueError(f"official NHL sample changed: {actual} != {expected}")
    print(
        "OFFICIAL_NHL_SPOTCHECK "
        f"source={url} game_date={official.get('gameDate')} game_type={official.get('gameType')} "
        f"skaters_matched={actual['skaters_matched']} "
        f"skaters_unmatched={actual['skaters_unmatched']} "
        f"sog_mismatch_rows={actual['sog_mismatch_rows']} "
        f"goalies_matched={actual['goalies_matched']} "
        f"goalies_unmatched={actual['goalies_unmatched']} "
        f"zero_stat_unmatched_goalies={actual['zero_stat_unmatched_goalies']} "
        f"saves_mismatch_rows={actual['saves_mismatch_rows']}"
    )
    for player_id, official_value, archive_value in sog_mismatches:
        print(
            f"OFFICIAL_SOG_MISMATCH gameId={game_id} playerId={player_id} "
            f"official={official_value} archive={archive_value}"
        )
    return actual

def parse_capture(value: Any) -> dt.datetime | None:
    if value is None or not str(value).strip():
        return None
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def season_start_year(game_date: str) -> int:
    parsed = dt.date.fromisoformat(game_date)
    return parsed.year if parsed.month >= 7 else parsed.year - 1


def audit_prices(picks_db: Path, research_root: Path) -> dict:
    require_file(picks_db, "picks.dev.db")
    if picks_db.name != "picks.dev.db":
        raise ValueError(f"refusing non-dev SQLite input: {picks_db}")
    uri = "file:" + quote(str(picks_db), safe="/") + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA cache_size=-32768")
        required_tables = {"props", "prop_games", "players", "prop_odds_snapshots"}
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if not required_tables.issubset(tables):
            raise ValueError(
                f"picks.dev.db missing tables: {sorted(required_tables - tables)}"
            )
        required_columns = {
            "props": {"id", "game_id", "player_id", "market", "line", "source", "captured_at", "odds", "odds_captured_at"},
            "prop_games": {"id", "league", "date", "start_time"},
            "players": {"id", "league"},
            "prop_odds_snapshots": {"id", "prop_id", "captured_at", "odds"},
        }
        for table, expected in required_columns.items():
            actual = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not expected.issubset(actual):
                raise ValueError(
                    f"{table} missing columns: {sorted(expected - actual)}"
                )

        nhl_game_rows = connection.execute(
            "SELECT count(*) FROM prop_games WHERE lower(league)='nhl'"
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT p.id, p.game_id, p.player_id, pl.league AS player_league, p.market, p.line, "
            "p.side, p.source, p.captured_at, p.odds, p.odds_captured_at, "
            "g.league AS game_league, g.date AS game_date, g.start_time "
            "FROM props p JOIN players pl ON pl.id=p.player_id "
            "LEFT JOIN prop_games g ON g.id=p.game_id "
            "WHERE lower(pl.league)='nhl' AND p.player_id IS NOT NULL "
            "AND p.line IS NOT NULL AND p.captured_at IS NOT NULL"
        ).fetchall()
        snapshot_rows = connection.execute(
            "SELECT count(*) FROM prop_odds_snapshots s "
            "JOIN props p ON p.id=s.prop_id "
            "JOIN players pl ON pl.id=p.player_id "
            "WHERE lower(pl.league)='nhl'"
        ).fetchone()[0]
    finally:
        connection.close()

    market_rows: Counter[str] = Counter()
    market_pregame: Counter[str] = Counter()
    market_after: Counter[str] = Counter()
    market_unknown: Counter[str] = Counter()
    market_players: dict[str, set[int]] = defaultdict(set)
    market_games: dict[str, set[int]] = defaultdict(set)
    market_lines: dict[str, set[float]] = defaultdict(set)
    season_rows: Counter[int] = Counter()
    all_players: set[int] = set()
    all_games: set[int] = set()
    pregame = after = unknown = with_price = 0
    target_window_rows = 0
    linked_nhl_rows = 0
    source_labels: set[str] = set()
    capture_dates: list[str] = []
    game_dates: list[str] = []
    for row in rows:
        market = str(row["market"])
        market_rows[market] += 1
        player_id = int(row["player_id"])
        all_players.add(player_id)
        market_players[market].add(player_id)
        if row["source"]:
            source_labels.add(str(row["source"]))
        if row["odds"] is not None and row["odds_captured_at"] is not None:
            with_price += 1
        if row["game_league"] is not None and str(row["game_league"]).lower() == "nhl":
            linked_nhl_rows += 1
        if row["game_date"]:
            game_date = str(row["game_date"])[:10]
            game_dates.append(game_date)
            year = season_start_year(game_date)
            season_rows[year] += 1
            if row["game_id"] is not None:
                game_id = int(row["game_id"])
                all_games.add(game_id)
                market_games[market].add(game_id)
            if "2018-10-01" <= game_date < "2023-07-01":
                target_window_rows += 1
        if row["line"] is not None:
            market_lines[market].add(float(row["line"]))
        if row["captured_at"]:
            capture_dates.append(str(row["captured_at"]))
        captured = parse_capture(row["captured_at"])
        start = parse_capture(row["start_time"])
        if captured is None or start is None:
            unknown += 1
            market_unknown[market] += 1
        elif captured < start:
            pregame += 1
            market_pregame[market] += 1
        else:
            after += 1
            market_after[market] += 1

    market_names = set(market_rows)
    actual_expected_markets = {market: market_rows[market] for market in sorted(market_names)}
    if actual_expected_markets != EXPECTED_MARKET_ROWS:
        raise ValueError(
            f"NHL prop market row counts changed: {actual_expected_markets} != {EXPECTED_MARKET_ROWS}"
        )
    actual_pregame_markets = {
        market: market_pregame[market] for market in sorted(market_names)
    }
    if actual_pregame_markets != EXPECTED_MARKET_PREGAME:
        raise ValueError(
            f"NHL prop pregame row counts changed: "
            f"{actual_pregame_markets} != {EXPECTED_MARKET_PREGAME}"
        )
    research_summary = scan_research(research_root)
    totals = {
        "rows": len(rows),
        "players": len(all_players),
        "games": len(all_games),
        "with_line_and_capture": len(rows),
        "with_odds_and_odds_timestamp": with_price,
        "pregame": pregame,
        "at_or_after_start": after,
        "start_time_unknown": unknown,
        "target_window_rows": target_window_rows,
        "snapshot_rows": int(snapshot_rows),
        "requested_market_rows": sum(
            market_rows[market] for market in ("shots", "saves", "goals", "points")
        ),
        "distinct_markets": len(market_names),
    }
    if linked_nhl_rows != len(rows):
        raise ValueError(f"NHL player props not linked to NHL games: {len(rows) - linked_nhl_rows}")
    if season_rows != Counter({2026: len(rows)}):
        raise ValueError(f"unexpected NHL player prop seasons: {dict(season_rows)}")
    for key, expected in EXPECTED_PRICE_TOTALS.items():
        actual = (
            research_summary["player_price_rows"]
            if key == "research_player_price_rows"
            else totals.get(key, 0)
        )
        if actual != expected:
            raise ValueError(f"NHL price count changed for {key}: {actual} != {expected}")
    if nhl_game_rows != 149:
        raise ValueError(f"NHL prop game count changed: {nhl_game_rows} != 149")
    if set(market_lines["goals"]) != {0.5}:
        raise ValueError(f"unexpected NHL goals line values: {sorted(market_lines['goals'])}")

    print(
        "NHL_PRICE_ARCHIVE "
        f"prop_games={nhl_game_rows} quote_rows={totals['rows']} "
        f"player_ids={totals['players']} game_ids={totals['games']} "
        f"rows_with_line_and_capture={totals['with_line_and_capture']} "
        f"rows_with_odds_and_odds_timestamp={totals['with_odds_and_odds_timestamp']} "
        f"capture_date_span={min(capture_dates)[:10]}..{max(capture_dates)[:10]} "
        f"game_date_span={min(game_dates)}..{max(game_dates)} "
        f"season_start_years={','.join(str(y) for y in sorted(season_rows))} "
        f"pregame={pregame} at_or_after_start={after} start_time_unknown={unknown} "
        f"target_2018_19_to_2022_23_rows={target_window_rows} "
        f"requested_market_quote_rows={totals['requested_market_rows']} "
        f"distinct_market_keys={totals['distinct_markets']} "
        f"prop_odds_snapshots_rows={snapshot_rows} distinct_quote_sources={len(source_labels)}"
    )
    for market in sorted(market_rows):
        lines = ",".join(format(value, "g") for value in sorted(market_lines[market]))
        print(
            f"PRICE_MARKET market={market} rows={market_rows[market]} "
            f"players={len(market_players[market])} games={len(market_games[market])} "
            f"pregame={market_pregame[market]} at_or_after_start={market_after[market]} "
            f"start_time_unknown={market_unknown[market]} line_values={lines}"
        )
    return {
        "totals": totals,
        "market_rows": dict(market_rows),
        "market_pregame": dict(market_pregame),
        "market_after": dict(market_after),
        "market_unknown": dict(market_unknown),
        "market_players": {key: len(value) for key, value in market_players.items()},
        "market_games": {key: len(value) for key, value in market_games.items()},
        "market_lines": {key: sorted(value) for key, value in market_lines.items()},
    }


def normalize_key(key: Any) -> str:
    return "".join(character.lower() for character in str(key) if character.isalnum())


def nested_key_values(record: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(record, dict):
        for key, value in record.items():
            yield normalize_key(key), value
            yield from nested_key_values(value)
    elif isinstance(record, list):
        for value in record:
            yield from nested_key_values(value)


def iter_records(path: Path) -> Iterable[Any]:
    opener = gzip.open if path.suffix == ".gz" else open
    if path.suffix in (".jsonl", ".gz"):
        with opener(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON in {path}:{line_number}") from exc
        return
    if path.suffix == ".json":
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        if isinstance(value, list):
            yield from value
        else:
            yield value
        return
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            yield from csv.DictReader(handle)


def is_nhl_record(path: Path, record: Any) -> bool:
    rel = str(path).lower()
    if "/nhl/" in rel or rel.endswith("/nhl"):
        return True
    for key, value in nested_key_values(record):
        if key in {"league", "sport", "sportid", "leagueid"}:
            text = str(value).lower()
            if text in {"nhl", "hockey", "ice hockey"}:
                return True
        if isinstance(value, str) and value.upper().startswith("KXNHL"):
            return True
    return False


def is_player_price_record(record: Any) -> bool:
    values = list(nested_key_values(record))
    player = any(key in PLAYER_KEYS and value not in (None, "") for key, value in values)
    line = any(key in LINE_KEYS and value not in (None, "") for key, value in values)
    captured = any(key in CAPTURE_KEYS and value not in (None, "") for key, value in values)
    text = " ".join(str(value).lower() for _, value in values if isinstance(value, str))
    market = any(term in text for term in PROP_MARKET_TERMS)
    return player and line and captured and market


def scan_research(research_root: Path) -> dict:
    require_file(research_root / "nhl/sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz", "SBR research archive")
    data_suffixes = {".jsonl", ".json", ".csv", ".gz"}
    files = sorted(
        path
        for path in research_root.rglob("*")
        if path.is_file() and path.suffix.lower() in data_suffixes and path.stat().st_size <= 25_000_000
    )
    total_records = 0
    nhl_records = 0
    qualified_nhl_player_prices = 0
    candidate_details: list[tuple[str, int, int]] = []
    for path in files:
        file_records = 0
        file_nhl_records = 0
        file_prices = 0
        for record in iter_records(path):
            file_records += 1
            total_records += 1
            if is_nhl_record(path, record):
                file_nhl_records += 1
                nhl_records += 1
                if is_player_price_record(record):
                    file_prices += 1
                    qualified_nhl_player_prices += 1
        rel = path.relative_to(ROOT).as_posix()
        if file_nhl_records and any(token in rel.lower() for token in ("odds", "price", "quote", "market")):
            candidate_details.append((rel, file_records, file_prices))
    print(
        "RESEARCH_STRUCTURED_SCAN "
        f"files={len(files)} records={total_records} nhl_records={nhl_records} "
        f"nhl_player_line_capture_price_rows={qualified_nhl_player_prices}"
    )
    for path, records, prices in candidate_details:
        print(
            f"RESEARCH_CANDIDATE path={path} records={records} "
            f"player_line_capture_price_rows={prices}"
        )
    if qualified_nhl_player_prices != EXPECTED_PRICE_TOTALS["research_player_price_rows"]:
        raise ValueError(
            "NHL research player-level line/capture rows changed: "
            f"{qualified_nhl_player_prices} != "
            f"{EXPECTED_PRICE_TOTALS['research_player_price_rows']}"
        )
    return {
        "files": len(files),
        "records": total_records,
        "nhl_records": nhl_records,
        "player_price_rows": qualified_nhl_player_prices,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbr", type=Path, default=DEFAULT_SBR)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--duckdb", type=Path, default=DEFAULT_DUCKDB)
    parser.add_argument("--picks-db", type=Path, default=DEFAULT_PICKS_DB)
    parser.add_argument("--research", type=Path, default=ROOT / "research")
    args = parser.parse_args()

    print("READ_ONLY=true duckdb_read_only=true sqlite_uri=mode=ro&immutable=1")
    print(f"INPUT sbr={args.sbr}")
    print(f"INPUT canonical={args.canonical}")
    print(f"INPUT duckdb={args.duckdb}")
    print(f"INPUT picks_dev_db={args.picks_db}")

    target, _all_games = load_sbr_crosswalk(args.sbr, args.canonical)
    audit_outcomes(target, args.duckdb)
    audit_official_spotcheck(args.duckdb)
    audit_prices(args.picks_db, args.research)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
