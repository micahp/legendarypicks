#!/usr/bin/env python3
"""Build strict-lag NHL goalie features and print coverage/leak audit.

Phase 1 only: reads goalie data read-only and performs no model fitting,
scoring, threshold selection, or betting simulation.
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib
import io
import math
import sys
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
NHL_RESEARCH_DIR = HERE.parent
AUDIT_DIR = NHL_RESEARCH_DIR / "newinfo-audit-2026-10-20"
sys.path.insert(0, str(AUDIT_DIR))
audit_sources = importlib.import_module("audit_nhl_sources")

CANONICAL_FILE = audit_sources.CANONICAL_FILE
GOALIE_DB = audit_sources.GOALIE_DB
OUTPUT_CSV = HERE / "goalie_features.csv"
OUTPUT_REPORT = HERE / "COVERAGE.md"
MAX_TARGET_SEASON = 2022
WINDOW = 10
SIDES = ("home", "away")
FEATURES = (
    "starter_last",
    "starter_games_trailing10",
    "starter_gsax_trailing10",
    "starter_savepct_trailing10",
    "team_goalie_gsax_trailing10",
    "starter_changed",
)
TEAM_CODE_ALIASES = {"PHX": "ARI"}


@dataclass(frozen=True)
class GoalieRow:
    game_id: int
    game_date: dt.date
    season: int
    team: str
    goalie_id: int
    icetime: float
    xgoals: float | None
    ongoal: float | None
    goals: float | None


@dataclass(frozen=True)
class TeamGame:
    game_id: int
    game_date: dt.date
    season: int
    team: str
    starter_id: int | None
    tied_starter_ids: tuple[int, ...]
    team_gsax: float | None


@dataclass
class Histories:
    by_team: dict[str, list[TeamGame]]
    goalie_starts: dict[int, list[GoalieRow]]
    goalie_ties: dict[int, list[TeamGame]]
    tied_team_games: list[TeamGame]


def source_date(value: Any) -> dt.date:
    text = str(value)
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid goalie gameDate value: {value!r}")
    return dt.datetime.strptime(text, "%Y%m%d").date()


def canonical_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid canonical game_date value: {value!r}") from exc


def finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def team_key(code: str) -> str:
    return TEAM_CODE_ALIASES.get(code, code)


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"refusing non-finite output value: {value}")
        return format(value, ".12g")
    return str(value)


def read_crosswalk() -> tuple[dict[int, dict], str]:
    captured = io.StringIO()
    with redirect_stdout(captured):
        _, linked, _ = audit_sources.load_crosswalk()
    output = captured.getvalue()
    if not linked:
        raise ValueError("SBR-to-canonical crosswalk returned no target games")
    return linked, output


def read_canonical() -> dict[int, dict[str, str]]:
    path = Path(CANONICAL_FILE)
    if not path.is_file():
        raise FileNotFoundError(f"required canonical source is missing: {path}")
    required = {"game_id", "game_date", "season", "game_type", "home_team", "away_team"}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"canonical games CSV missing columns: {sorted(required)}")
        rows: dict[int, dict[str, str]] = {}
        for row in reader:
            game_id = int(row["game_id"])
            if game_id in rows:
                raise ValueError(f"duplicate canonical game_id: {game_id}")
            rows[game_id] = row
    if not rows:
        raise ValueError("canonical games CSV is empty")
    return rows


def read_goalie_rows(
    canonical: dict[int, dict[str, str]],
) -> tuple[list[GoalieRow], dict[str, int], dict[int, Counter]]:
    path = Path(GOALIE_DB)
    if not path.is_file():
        raise FileNotFoundError(f"required read-only goalie DuckDB is missing: {path}")
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("DuckDB is required; use /root/lp-goalie-research/.venv/bin/python") from exc

    connection = duckdb.connect(
        str(path),
        read_only=True,
        config={"memory_limit": "200MB", "threads": "1"},
    )
    try:
        columns = {row[0] for row in connection.execute("DESCRIBE goalies_gamelogs").fetchall()}
        required = {
            "gameId", "gameDate", "season", "playerTeam", "playerId", "situation",
            "icetime", "xGoals", "ongoal", "goals",
        }
        if not required.issubset(columns):
            raise ValueError(f"goalies_gamelogs missing fields: {sorted(required - columns)}")
        raw_rows = connection.execute(
            "SELECT gameId, gameDate, season, playerTeam, playerId, icetime, xGoals, ongoal, goals "
            "FROM goalies_gamelogs WHERE lower(situation)='all' AND season <= ?",
            [MAX_TARGET_SEASON],
        ).fetchall()
    finally:
        connection.close()

    rows: list[GoalieRow] = []
    game_ids: set[int] = set()
    by_game_team: dict[tuple[int, str], list[GoalieRow]] = defaultdict(list)
    seen_player_rows: set[tuple[int, str, int]] = set()
    team_alias_rows = 0
    for raw in raw_rows:
        gid, date_raw, season_raw, team_raw, pid_raw, toi_raw, xg_raw, sog_raw, goals_raw = raw
        if any(value is None for value in (gid, date_raw, season_raw, team_raw, pid_raw, toi_raw)):
            raise ValueError(f"null goalie game identity or icetime: {raw!r}")
        gid, season, pid = int(gid), int(season_raw), int(pid_raw)
        team, toi = str(team_raw), finite_or_none(toi_raw)
        if toi is None:
            raise ValueError(f"non-finite goalie icetime: {raw!r}")
        row = GoalieRow(
            game_id=gid,
            game_date=source_date(date_raw),
            season=season,
            team=team,
            goalie_id=pid,
            icetime=toi,
            xgoals=finite_or_none(xg_raw),
            ongoal=finite_or_none(sog_raw),
            goals=finite_or_none(goals_raw),
        )
        if season > MAX_TARGET_SEASON:
            raise ValueError(f"future-season row passed DuckDB filter: {season}")
        team = team_key(team)
        row = GoalieRow(
            game_id=row.game_id,
            game_date=row.game_date,
            season=row.season,
            team=team,
            goalie_id=row.goalie_id,
            icetime=row.icetime,
            xgoals=row.xgoals,
            ongoal=row.ongoal,
            goals=row.goals,
        )
        key = (gid, team, pid)
        if key in seen_player_rows:
            raise ValueError(f"duplicate all-situation player/game/team row: {key}")
        seen_player_rows.add(key)
        rows.append(row)
        by_game_team[(gid, team)].append(row)
        game_ids.add(gid)

    if not rows:
        raise ValueError("no all-situation goalie game-log rows at or before target seasons")

    for gid in game_ids:
        canonical_row = canonical.get(gid)
        if canonical_row is None:
            raise ValueError(f"goalie gameId has no canonical game_id: {gid}")
        if int(canonical_row["game_type"]) != 2:
            raise ValueError(f"goalies_gamelogs unexpectedly contains non-regular game_id={gid}")

    for (gid, team), group in by_game_team.items():
        canonical_row = canonical[gid]
        if int(canonical_row["season"]) != group[0].season:
            raise ValueError(f"goalie/canonical season mismatch game_id={gid}")
        if canonical_date(canonical_row["game_date"]) != group[0].game_date:
            raise ValueError(f"goalie/canonical date mismatch game_id={gid}")
        canonical_teams = {
            team_key(canonical_row["home_team"]),
            team_key(canonical_row["away_team"]),
        }
        if team not in canonical_teams:
            raise ValueError(f"playerTeam not a canonical side game_id={gid} team={team}")
        if team not in (canonical_row["home_team"], canonical_row["away_team"]):
            team_alias_rows += len(group)
        if any((row.season, row.game_date) != (group[0].season, group[0].game_date) for row in group):
            raise ValueError(f"inconsistent goalie game date/season game_id={gid} team={team}")

    starter_counts: dict[int, Counter] = defaultdict(Counter)
    for (gid, _team), group in by_game_team.items():
        high = max(row.icetime for row in group)
        leaders = [row for row in group if row.icetime == high]
        season = int(canonical[gid]["season"])
        starter_counts[season]["unique" if len(leaders) == 1 else "tied"] += 1

    stats = {
        "rows": len(rows),
        "game_ids": len(game_ids),
        "team_games": len(by_game_team),
        "player_rows": len(seen_player_rows),
        "team_alias_rows": team_alias_rows,
    }
    print(
        "SOURCE_CANONICAL_RECONCILIATION "
        f"all_situation_rows_season_le_{MAX_TARGET_SEASON}={stats['rows']} "
        f"unique_game_ids={stats['game_ids']} "
        f"team_games={stats['team_games']} "
        f"team_alias_rows={team_alias_rows} canonical_team_alias=PHX->ARI "
        "canonical_id_date_season_team_mismatches=0 non_regular_season_source_games=0"
    )
    expected = {
        2018: (2542, 2542),
        2019: (2163, 2163),
        2020: (1736, 1736),
        2021: (2624, 2623),
        2022: (2624, 2624),
    }
    for season, (expected_games, expected_unique) in expected.items():
        observed_games = sum(
            1 for gid, _team in by_game_team
            if int(canonical[gid]["season"]) == season
        )
        observed_unique = starter_counts[season]["unique"]
        observed_tied = starter_counts[season]["tied"]
        print(
            f"SOURCE_STARTER_COVERAGE season={season} source_team_games={observed_games} "
            f"unique_starter_team_games={observed_unique} ambiguous_starter_team_games={observed_tied}"
        )
        if (observed_games, observed_unique) != (expected_games, expected_unique):
            raise ValueError(
                f"starter source coverage changed season={season}: "
                f"team_games={observed_games}/{expected_games} "
                f"unique_starters={observed_unique}/{expected_unique}"
            )
    return rows, stats, starter_counts


def build_histories(rows: list[GoalieRow]) -> Histories:
    grouped: dict[tuple[int, str], list[GoalieRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.game_id, row.team)].append(row)

    by_team: dict[str, list[TeamGame]] = defaultdict(list)
    goalie_starts: dict[int, list[GoalieRow]] = defaultdict(list)
    goalie_ties: dict[int, list[TeamGame]] = defaultdict(list)
    tied_team_games: list[TeamGame] = []

    for (gid, team), goalie_rows in grouped.items():
        goalie_rows.sort(key=lambda row: row.goalie_id)
        high = max(row.icetime for row in goalie_rows)
        leaders = [row for row in goalie_rows if row.icetime == high]
        starter_id = leaders[0].goalie_id if len(leaders) == 1 else None
        tied_ids = tuple(row.goalie_id for row in leaders) if len(leaders) > 1 else ()
        metric_pairs = [(row.xgoals, row.goals) for row in goalie_rows]
        if all(xg is not None and goals is not None for xg, goals in metric_pairs):
            team_gsax = sum(float(xg) - float(goals) for xg, goals in metric_pairs)
        else:
            team_gsax = None
        team = team_key(team)
        game = TeamGame(
            game_id=gid,
            game_date=goalie_rows[0].game_date,
            season=goalie_rows[0].season,
            team=team,
            starter_id=starter_id,
            tied_starter_ids=tied_ids,
            team_gsax=team_gsax,
        )
        by_team[team].append(game)
        if starter_id is not None:
            goalie_starts[starter_id].append(
                next(row for row in goalie_rows if row.goalie_id == starter_id)
            )
        else:
            tied_team_games.append(game)
            for candidate_id in tied_ids:
                goalie_ties[candidate_id].append(game)

    for team, games in by_team.items():
        games.sort(key=lambda game: (game.game_date, game.game_id))
        seen_dates: set[dt.date] = set()
        for game in games:
            if game.game_date in seen_dates:
                raise ValueError(f"multiple source team-games for team/date: {team}/{game.game_date}")
            seen_dates.add(game.game_date)
    for starts in goalie_starts.values():
        starts.sort(key=lambda row: (row.game_date, row.game_id))
    for games in goalie_ties.values():
        games.sort(key=lambda game: (game.game_date, game.game_id))
    tied_team_games.sort(key=lambda game: (game.game_date, game.team, game.game_id))
    return Histories(dict(by_team), dict(goalie_starts), dict(goalie_ties), tied_team_games)


def prior_team_games(
    games: list[TeamGame], target_date: dt.date, target_season: int
) -> list[TeamGame]:
    return [
        game for game in games
        if game.game_date < target_date and game.season <= target_season
    ]


def max_date(items: list[Any]) -> str | None:
    if not items:
        return None
    return max(item.game_date for item in items).isoformat()


def absent(reason: str, date: str | None = None) -> dict[str, Any]:
    return {"value": None, "n": 0, "coverage": reason, "max_date": date}


def covered(
    value: Any, n: int, date: str | None, window: int | None = WINDOW
) -> dict[str, Any]:
    if n < 1 or date is None:
        raise ValueError("covered features require at least one source row and source date")
    if window is None:
        status = "covered"
    else:
        status = f"covered_n={n}" if n == window else f"covered_partial_n={n}_of_{window}"
    return {"value": value, "n": n, "coverage": status, "max_date": date}


def empty_features(reason: str) -> dict[str, dict[str, Any]]:
    return {feature: absent(reason) for feature in FEATURES}


def relevant_tie_date(
    goalie_id: int,
    starts: list[GoalieRow],
    ties: dict[int, list[TeamGame]],
    target_date: dt.date,
    target_season: int,
) -> str | None:
    eligible_starts = [
        row for row in starts
        if row.game_date < target_date and row.season <= target_season
    ]
    selected = eligible_starts[-WINDOW:]
    eligible_ties = [
        game for game in ties.get(goalie_id, [])
        if game.game_date < target_date and game.season <= target_season
    ]
    if selected:
        floor_date = selected[0].game_date
        relevant = [game for game in eligible_ties if game.game_date >= floor_date]
    else:
        relevant = eligible_ties
    return max_date(relevant)


def features_for_team(
    team: str, target_date: dt.date, season: int, histories: Histories
) -> dict[str, dict[str, Any]]:
    prior = prior_team_games(histories.by_team.get(team, []), target_date, season)
    if not any(game.season == season for game in prior):
        return empty_features("first_team_game_of_season")
    if not prior:
        return empty_features("no_prior_team_game")

    latest = prior[-1]
    latest_day = latest.game_date.isoformat()
    starter_id = latest.starter_id
    starter_last = (
        absent("ambiguous_latest_starter_tie", latest_day)
        if starter_id is None
        else covered(starter_id, 1, latest_day, window=None)
    )

    team_window = prior[-WINDOW:]
    team_window_day = max_date(team_window)
    if starter_id is None:
        starter_games = absent("starter_last_absent", team_window_day)
        starter_gsax = absent("starter_last_absent", team_window_day)
        starter_savepct = absent("starter_last_absent", team_window_day)
    else:
        if any(game.starter_id is None for game in team_window):
            starter_games = absent(
                "ambiguous_starter_in_trailing_team_games", team_window_day
            )
        else:
            count = sum(game.starter_id == starter_id for game in team_window)
            starter_games = covered(count, len(team_window), team_window_day)

        starts = histories.goalie_starts.get(starter_id, [])
        goalie_window = [
            row for row in starts
            if row.game_date < target_date and row.season <= season
        ][-WINDOW:]
        tie_day = relevant_tie_date(
            starter_id, starts, histories.goalie_ties, target_date, season
        )
        goalie_window_day = max_date(goalie_window)
        if tie_day is not None:
            effective_day = max(day for day in (tie_day, goalie_window_day) if day is not None)
            starter_gsax = absent(
                "ambiguous_starter_tie_in_last10_start_window", effective_day
            )
            starter_savepct = absent(
                "ambiguous_starter_tie_in_last10_start_window", effective_day
            )
        elif not goalie_window:
            starter_gsax = absent("no_prior_starts", latest_day)
            starter_savepct = absent("no_prior_starts", latest_day)
        else:
            gsax_values = [
                None if row.xgoals is None or row.goals is None
                else row.xgoals - row.goals
                for row in goalie_window
            ]
            if any(value is None for value in gsax_values):
                starter_gsax = absent(
                    "missing_xGoals_or_goals_in_start_window", goalie_window_day
                )
            else:
                starter_gsax = covered(
                    sum(float(value) for value in gsax_values) / len(gsax_values),
                    len(gsax_values),
                    goalie_window_day,
                )

            savepct_values = []
            for row in goalie_window:
                if row.ongoal is None or row.goals is None or row.ongoal <= 0:
                    savepct_values = []
                    break
                savepct_values.append((row.ongoal - row.goals) / row.ongoal)
            if not savepct_values:
                starter_savepct = absent(
                    "missing_or_zero_ongoal_in_start_window", goalie_window_day
                )
            else:
                starter_savepct = covered(
                    sum(savepct_values) / len(savepct_values),
                    len(savepct_values),
                    goalie_window_day,
                )

    if any(game.team_gsax is None for game in team_window):
        team_gsax = absent(
            "missing_xGoals_or_goals_in_team_window", team_window_day
        )
    else:
        team_gsax = covered(
            sum(float(game.team_gsax) for game in team_window) / len(team_window),
            len(team_window),
            team_window_day,
        )

    if len(prior) < 2:
        starter_changed = absent("fewer_than_two_prior_team_games", latest_day)
    elif prior[-1].starter_id is None or prior[-2].starter_id is None:
        starter_changed = absent("ambiguous_starter_in_comparison_games", latest_day)
    else:
        starter_changed = covered(
            int(prior[-1].starter_id != prior[-2].starter_id),
            2,
            latest_day,
            window=None,
        )

    return {
        "starter_last": starter_last,
        "starter_games_trailing10": starter_games,
        "starter_gsax_trailing10": starter_gsax,
        "starter_savepct_trailing10": starter_savepct,
        "team_goalie_gsax_trailing10": team_gsax,
        "starter_changed": starter_changed,
    }


def feature_columns() -> list[str]:
    columns = [
        "game_id", "season", "season_label", "game_date", "game_type",
        "home_team", "away_team", "target_coverage_status",
    ]
    for side in SIDES:
        for feature in FEATURES:
            columns.extend((
                f"{side}_{feature}",
                f"{side}_{feature}_n",
                f"{side}_{feature}_coverage",
                f"{side}_{feature}_max_source_gameDate",
            ))
    return columns


def build_rows(
    linked: dict[int, dict], histories: Histories
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seasons: dict[str, Counter] = defaultdict(Counter)
    season_dates: dict[str, list[str]] = defaultdict(list)
    missing: dict[str, Counter] = defaultdict(Counter)
    partial: dict[str, Counter] = defaultdict(Counter)
    populated: Counter[str] = Counter()
    source_date_pairs: list[tuple[str, str]] = []

    ordered = sorted(
        linked.items(),
        key=lambda item: (item[1]["canonical"]["game_date"], int(item[0])),
    )
    for game_id, info in ordered:
        canonical = info["canonical"]
        season = int(canonical["season"])
        target_date = canonical_date(canonical["game_date"])
        label = info["season_label"]
        game_type = int(canonical["game_type"])
        seasons[label]["target_games"] += 1
        season_dates[label].append(target_date.isoformat())
        record: dict[str, Any] = {
            "game_id": int(game_id),
            "season": season,
            "season_label": label,
            "game_date": target_date.isoformat(),
            "game_type": game_type,
            "home_team": canonical["home_team"],
            "away_team": canonical["away_team"],
            "target_coverage_status": "regular_season_feature_population",
        }

        if game_type == 2:
            seasons[label]["regular_season_games"] += 1
            side_features = {
                "home": features_for_team(team_key(canonical["home_team"]), target_date, season, histories),
                "away": features_for_team(team_key(canonical["away_team"]), target_date, season, histories),
            }
        elif game_type == 3:
            seasons[label]["playoff_games_uncovered"] += 1
            record["target_coverage_status"] = (
                "playoff_uncovered_regular_season_goalie_logs_only"
            )
            side_features = {
                side: empty_features("playoff_target_uncovered")
                for side in SIDES
            }
        else:
            raise ValueError(f"unexpected SBR target game_type={game_type}")

        for side in SIDES:
            for feature in FEATURES:
                item = side_features[side][feature]
                value, n, status, source_day = (
                    item["value"], item["n"], item["coverage"], item["max_date"]
                )
                if value is None:
                    missing[feature][status] += 1
                else:
                    populated[feature] += 1
                    if status.startswith("covered_partial_"):
                        partial[feature][status] += 1
                if source_day is not None:
                    if source_day >= target_date.isoformat():
                        raise AssertionError(
                            f"date leakage game_id={game_id} {side}.{feature}: "
                            f"{source_day} >= {target_date.isoformat()}"
                        )
                    source_date_pairs.append((target_date.isoformat(), source_day))
                if value is not None and source_day is None:
                    raise AssertionError(
                        f"non-null {side}.{feature} lacks max_source_gameDate game_id={game_id}"
                    )
                record[f"{side}_{feature}"] = value
                record[f"{side}_{feature}_n"] = n
                record[f"{side}_{feature}_coverage"] = status
                record[f"{side}_{feature}_max_source_gameDate"] = source_day
        rows.append(record)

    regular = sum(item["regular_season_games"] for item in seasons.values())
    playoffs = sum(item["playoff_games_uncovered"] for item in seasons.values())
    if len(rows) != len(linked) or len({row["game_id"] for row in rows}) != len(linked):
        raise ValueError("output must contain exactly one row per SBR/canonical game_id")
    if (len(rows), regular, playoffs) != (5132, 4872, 260):
        raise ValueError(
            f"target population changed: rows={len(rows)} regular={regular} playoffs={playoffs}"
        )
    return rows, {
        "rows": rows,
        "season_counts": seasons,
        "season_dates": season_dates,
        "missing": missing,
        "partial": partial,
        "populated": populated,
        "source_date_pairs": source_date_pairs,
        "regular_targets": regular,
        "playoff_targets": playoffs,
        "target_rows": len(rows),
    }


def write_csv(rows: list[dict[str, Any]]) -> None:
    columns = feature_columns()
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=columns, extrasaction="raise", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: text_value(row.get(key)) for key in columns})


def coverage_text(stats: dict[str, Any]) -> str:
    lines = [
        "GOALIE FEATURE COVERAGE",
        f"target_rows={stats['target_rows']} unique_game_ids={stats['target_rows']} "
        f"regular_season_target_games={stats['regular_targets']} "
        f"playoff_target_games_uncovered={stats['playoff_targets']}",
        "coverage_unit=team_side; covered counts include partial windows tagged with actual n",
        "season_label target_games regular_feature_games playoff_uncovered_games "
        + " ".join(f"{feature}_covered_sides" for feature in FEATURES),
    ]
    for label in sorted(stats["season_counts"]):
        counts = stats["season_counts"][label]
        season_rows = [row for row in stats["rows"] if row["season_label"] == label]
        values = [
            label,
            str(counts["target_games"]),
            str(counts["regular_season_games"]),
            str(counts["playoff_games_uncovered"]),
        ]
        for feature in FEATURES:
            count = sum(
                row[f"{side}_{feature}"] is not None
                for row in season_rows
                for side in SIDES
            )
            values.append(str(count))
        lines.append(" ".join(values))

    if "2022-23" in stats["season_counts"]:
        dates = stats["season_dates"]["2022-23"]
        season_games = stats["season_counts"]["2022-23"]
        first_date, last_date = min(dates), max(dates)
        if (
            season_games["regular_season_games"] != 339
            or first_date != "2022-10-11"
            or last_date != "2022-11-27"
        ):
            raise ValueError(
                "2022-23 SBR archive slice changed: "
                f"games={season_games['regular_season_games']} dates={first_date}..{last_date}"
            )
        lines.append(
            f"PARTIAL_TARGET_SEASON season=2022-23 archive_regular_games=339 "
            f"date_span={first_date}..{last_date} full_regular_season=false"
        )

    lines.append("FIELD_ABSENCE_COUNTS (unit=team_side; denominator includes playoff sides)")
    denominator = stats["target_rows"] * len(SIDES)
    for feature in FEATURES:
        reasons = stats["missing"][feature]
        reason_text = ",".join(
            f"{reason}:{count}" for reason, count in sorted(reasons.items())
        ) or "none"
        lines.append(
            f"field={feature} total_sides={denominator} "
            f"populated={stats['populated'][feature]} absent={sum(reasons.values())} "
            f"absent_reasons={reason_text}"
        )
    for feature in FEATURES:
        if stats["partial"][feature]:
            partial_text = ",".join(
                f"{status}:{count}"
                for status, count in sorted(stats["partial"][feature].items())
            )
            lines.append(f"FIELD_PARTIAL_WINDOWS field={feature} {partial_text}")
    return "\n".join(lines)


def leak_audit_text(
    rows: list[dict[str, Any]], stats: dict[str, Any], source_stats: dict[str, int]
) -> str:
    dates = stats["source_date_pairs"]
    violations = sum(target_day <= source_day for target_day, source_day in dates)
    if violations:
        raise AssertionError(f"strict-lag assertion found {violations} violations")
    emitted_dates = sum(
        row[f"{side}_{feature}_max_source_gameDate"] is not None
        for row in rows
        for side in SIDES
        for feature in FEATURES
    )
    if emitted_dates != len(dates):
        raise AssertionError(
            f"leak audit dates={len(dates)} but emitted per-feature source dates={emitted_dates}"
        )
    return "\n".join((
        "LEAK AUDIT",
        f"feature_rows={len(rows)} unique_game_ids={len({row['game_id'] for row in rows})} "
        f"regular_season_targets={stats['regular_targets']} "
        f"playoff_rows_null_and_flagged={stats['playoff_targets']}",
        f"read_only_all_situation_rows_season_le_{MAX_TARGET_SEASON}={source_stats['rows']} "
        f"source_game_ids={source_stats['game_ids']} source_team_games={source_stats['team_games']}",
        "assertion=max_source_gameDate < target_gameDate for every non-null per-feature source date",
        f"checked_per_feature_source_dates={len(dates)} violations={violations} status=PASS",
        "same_target_date_excluded=true future_season_source_excluded=true",
    ))


def report_text(
    crosswalk: str, source_lines: list[str], coverage: str, leak_audit: str
) -> str:
    return f"""# NHL strict-lag goalie feature coverage

Phase 1 only: coverage and leakage audit. No model fitting, scoring, threshold
selection, betting simulation, or promotion-rule changes.

## Population and source

The SBR archive is joined to the official canonical game table by date and
unordered team pair, then keyed by canonical game_id. It contains 5,132
crosswalk games: 4,872 regular-season target games and 260 playoff games. The
CSV retains one row per crosswalk game_id. Playoff rows have null goalie fields
and target_coverage_status
playoff_uncovered_regular_season_goalie_logs_only. They are uncovered because
goalies_gamelogs contains regular-season game logs for these target seasons.
The 2022-23 SBR archive is a partial season slice, not full-season coverage;
the exact game count and date span are printed in the coverage block below.

The source is {GOALIE_DB}, table goalies_gamelogs, filtered to
lower(situation)='all' and season <= 2022, read-only with one DuckDB thread and a 200 MB memory
limit. Source gameId, gameDate, season, and playerTeam are reconciled against
canonical game_id, game_date, season, home_team, and away_team. SBR crosswalk
logic is reused from the predecessor new-information audit. Historical
canonical PHX and goalie-source ARI codes are normalized to the Arizona franchise
key ARI; that alias is counted in the source reconciliation output.

## Feature definitions

- A starter is the unique goalie with maximum all-situation icetime in a
  completed regular-season team game. A tied maximum is absent and logged.
- starter_last is the starter from the team's latest source game dated before
  the target. A team's first regular-season game of each season has all features
  null. After that opening game, trailing histories may include same-season and
  earlier-season regular-season games, with a strict date lag and no later season.
- starter_games_trailing10 counts that goalie among the team's up-to-ten most
  recent prior regular-season games. Fewer than ten available games are tagged
  with the actual n.
- starter_gsax_trailing10 is the unweighted mean of per-start xGoals minus
  goals over that goalie's up-to-ten uniquely identified prior starts.
- starter_savepct_trailing10 is the unweighted mean of per-start
  (ongoal minus goals) divided by ongoal over the same up-to-ten prior starts.
  A missing or zero ongoal makes this feature absent.
- team_goalie_gsax_trailing10 is the unweighted mean of team-game goalie GSAx
  over up to ten prior team games, summing all goalies' all-situation xGoals
  minus goals within each team game first.
- starter_changed is 1/0 according to whether starters in the latest and
  second-latest prior team games differ. It is absent unless both are unique.
- Each feature has its own max_source_gameDate, n, and coverage string.
  Missing values remain null; no zero imputation, shrinkage, tuned constant,
  or fitted weight is used.

## SEASON COVERAGE and SBR crosswalk output

<pre>
{crosswalk.strip()}
</pre>

## Source reconciliation and starter coverage

<pre>
{chr(10).join(source_lines)}
</pre>

## Feature coverage and absence reasons

Coverage counts by season use team-sides. Absence counts include both sides of
every archive row, including uncovered playoff rows. Reason strings are stored
per feature and side in the CSV.

<pre>
{coverage}
</pre>

## Leak audit output (verbatim from the builder)

<pre>
{leak_audit}
</pre>

## Reproduction

<pre>
/root/lp-goalie-research/.venv/bin/python research/nhl/goalie-features-2026-10-20/build_goalie_features.py
</pre>
"""


def main() -> None:
    linked, crosswalk_output = read_crosswalk()
    canonical = read_canonical()
    for gid, info in linked.items():
        if int(gid) not in canonical:
            raise ValueError(f"crosswalk game_id missing from canonical CSV: {gid}")
        if canonical[int(gid)]["game_date"] != info["canonical"]["game_date"]:
            raise ValueError(f"crosswalk/canonical date mismatch game_id={gid}")

    goalie_rows, source_stats, _ = read_goalie_rows(canonical)
    histories = build_histories(goalie_rows)
    print(f"AMBIGUOUS_STARTER_SOURCE_TEAM_GAMES tied_max_icetime={len(histories.tied_team_games)}")
    for game in histories.tied_team_games:
        print(
            f"AMBIGUOUS_STARTER game_id={game.game_id} team={game.team} "
            f"season={game.season} gameDate={game.game_date.isoformat()} "
            f"tied_goalie_ids={','.join(map(str, game.tied_starter_ids))}"
        )

    rows, stats = build_rows(linked, histories)
    coverage = coverage_text(stats)
    leak_audit = leak_audit_text(rows, stats, source_stats)

    source_lines = [
        f"SOURCE_CANONICAL_RECONCILIATION all_situation_rows_season_le_{MAX_TARGET_SEASON}={source_stats['rows']} "
        f"unique_game_ids={source_stats['game_ids']} team_games={source_stats['team_games']} "
        f"team_alias_rows={source_stats['team_alias_rows']} canonical_team_alias=PHX->ARI "
        "canonical_id_date_season_team_mismatches=0 non_regular_season_source_games=0"
    ]
    for season in range(2018, MAX_TARGET_SEASON + 1):
        season_games = [
            game for games in histories.by_team.values()
            for game in games if game.season == season
        ]
        unique = sum(game.starter_id is not None for game in season_games)
        tied = sum(game.starter_id is None for game in season_games)
        source_lines.append(
            f"SOURCE_STARTER_COVERAGE season={season} source_team_games={len(season_games)} "
            f"unique_starter_team_games={unique} ambiguous_starter_team_games={tied}"
        )

    rendered_report = report_text(crosswalk_output, source_lines, coverage, leak_audit)
    write_csv(rows)
    OUTPUT_REPORT.write_text(rendered_report, encoding="utf-8")

    print(crosswalk_output.rstrip())
    print("\n".join(source_lines))
    print(coverage)
    print(leak_audit)
    print(
        f"OUTPUT feature_file={OUTPUT_CSV} rows={len(rows)} "
        f"report_file={OUTPUT_REPORT}"
    )


if __name__ == "__main__":
    main()
