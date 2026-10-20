#!/usr/bin/env python3
"""Read-only inventory and SBR-archive coverage audit for NHL research inputs.

This script does not fit, score, or tune a model. It reads local source tables and
reports their schemas, date/season ranges, and joins to the archived SBR games.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import itertools
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SBR_FILE = ROOT / "research/nhl/sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz"
CANONICAL_FILE = Path(
    "/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26/"
    "canonical_games_v1_7cd2fc9a6e84470c.csv"
)
PREGAME_FILE = Path(
    "/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26/"
    "pregame_rolling_features_v1_62dcceb77085bc59.csv"
)
MONEYPUCK_DIR = Path(
    "/root/legendarypicks/research/nhl/prospective-2026-27/.cache"
)
SPECIAL_TEAMS_DIR = Path(
    "/root/lp-nhl-special-teams/research/nhl/special-teams-2026-10-19"
)
GOALIE_DB = Path("/root/nhl_database_2025-26-playoffs.duckdb")
PICKS_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
STARTER_AUDIT = Path(
    "/root/lp-nhl-starter-feed/research/nhl/starter-feed-feasibility-2026-10-19.md"
)
GOALIE_AUDIT = Path(
    "/root/lp-goalie-research/research/nhl/goalie-data-audit-2026-10-18.md"
)


# SBR uses sportsbook display names; canonical NHL rows use three-letter codes.
# Arizona deliberately allows both historical NHL abbreviations. The date and
# unordered team pair must still resolve to exactly one canonical game.
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


def require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"required read-only source is missing: {path}")
    return path


def csv_dicts(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    require(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader), list(reader.fieldnames)


def team_date_from_sbr(row: dict) -> str:
    season_start = int(row["season"].split("-")[0])
    month, day = divmod(int(row["date"]), 100)
    year = season_start if month >= 10 else season_start + 1
    return dt.date(year, month, day).isoformat()


def load_crosswalk() -> tuple[list[dict], dict[int, dict], dict[str, int]]:
    sbr = []
    with gzip.open(require(SBR_FILE), "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid SBR JSON at line {line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"SBR line {line_number} is not an object")
            sbr.append(row)

    canonical, canonical_columns = csv_dicts(CANONICAL_FILE)
    required_columns = {"game_id", "game_date", "home_team", "away_team", "season"}
    if not required_columns.issubset(canonical_columns):
        raise ValueError(f"canonical table missing columns: {required_columns - set(canonical_columns)}")

    by_date_pair: dict[tuple[str, tuple[str, str]], list[dict]] = defaultdict(list)
    canonical_by_id = {}
    for row in canonical:
        game_id = int(row["game_id"])
        if game_id in canonical_by_id:
            raise ValueError(f"duplicate canonical game_id: {game_id}")
        canonical_by_id[game_id] = row
        pair = tuple(sorted((row["home_team"], row["away_team"])))
        by_date_pair[(row["game_date"], pair)].append(row)

    linked: dict[int, dict] = {}
    orientation_mismatches = 0
    orientation_details = []
    unmatched = []
    for row in sbr:
        home_name = row["home"]["team"]
        away_name = row["away"]["team"]
        if home_name not in SBR_TEAM_CODES or away_name not in SBR_TEAM_CODES:
            unmatched.append((row.get("season"), row.get("date"), home_name, away_name, "unmapped SBR team"))
            continue
        date = team_date_from_sbr(row)
        candidates = {}
        for home_code, away_code in itertools.product(
            SBR_TEAM_CODES[home_name], SBR_TEAM_CODES[away_name]
        ):
            pair = tuple(sorted((home_code, away_code)))
            for canonical_row in by_date_pair.get((date, pair), []):
                candidates[int(canonical_row["game_id"])] = canonical_row
        if len(candidates) != 1:
            unmatched.append((row.get("season"), date, home_name, away_name, tuple(candidates)))
            continue
        game_id, canonical_row = next(iter(candidates.items()))
        if game_id in linked:
            raise ValueError(f"multiple SBR rows resolve to canonical game_id {game_id}")
        if (
            canonical_row["home_team"] not in SBR_TEAM_CODES[home_name]
            or canonical_row["away_team"] not in SBR_TEAM_CODES[away_name]
        ):
            orientation_mismatches += 1
            orientation_details.append(
                (row["season"], date, home_name, away_name, canonical_row["home_team"], canonical_row["away_team"])
            )
        linked[game_id] = {
            "sbr": row,
            "canonical": canonical_row,
            "date": date,
            "season_label": row["season"],
        }

    print("SBR / CANONICAL CROSSWALK")
    print(
        f"target_rows={len(sbr)} unique_canonical_games={len(linked)} "
        f"unmatched_or_ambiguous={len(unmatched)} venue_order_mismatches={orientation_mismatches}"
    )
    if unmatched:
        for item in unmatched:
            print(f"UNMATCHED {item}")
    if len(linked) != len(sbr) or unmatched:
        raise ValueError("SBR-to-canonical reconciliation is incomplete; see unmatched rows above")
    for season, date, sbr_home, sbr_away, canonical_home, canonical_away in orientation_details:
        print(
            f"VENUE_ORDER_MISMATCH season={season} date={date} "
            f"sbr_home={sbr_home} sbr_away={sbr_away} "
            f"canonical_home={canonical_home} canonical_away={canonical_away}"
        )

    coverage = Counter(info["season_label"] for info in linked.values())
    date_bounds: dict[str, list[str]] = defaultdict(list)
    game_type_totals: Counter[int] = Counter()
    for info in linked.values():
        date_bounds[info["season_label"]].append(info["date"])
        game_type_totals[int(info["canonical"]["game_type"])] += 1
    print("SEASON COVERAGE")
    print(
        f"archive_rows={len(sbr)} canonical_game_ids={len(linked)} "
        f"regular_season_games={game_type_totals[2]} playoff_games={game_type_totals[3]}"
    )
    for season in sorted(coverage):
        game_types = Counter(
            int(info["canonical"]["game_type"])
            for info in linked.values()
            if info["season_label"] == season
        )
        print(
            f"season={season} sbr_games={coverage[season]} canonical_matches={coverage[season]} "
            f"regular_season_games={game_types.get(2, 0)} playoff_games={game_types.get(3, 0)} "
            f"date_span={min(date_bounds[season])}..{max(date_bounds[season])}"
        )
    return sbr, linked, {"target_games": len(sbr), "orientation_mismatches": orientation_mismatches}


def summarize_csv_table(label: str, path: Path, key_candidates: tuple[str, ...]) -> list[dict[str, str]]:
    rows, columns = csv_dicts(path)
    key_columns = [column for column in key_candidates if column in columns]
    seasons = sorted({int(row["season"]) for row in rows if row.get("season", "").isdigit()})
    dates = [row.get("game_date", "") or row.get("gameDate", "") for row in rows]
    dates = [value for value in dates if value]
    season_text = f"{seasons[0]}..{seasons[-1]} ({len(seasons)} labels)" if seasons else "none"
    date_text = f"{min(dates)}..{max(dates)}" if dates else "none"
    print(
        f"FILE_TABLE name={label} rows={len(rows)} seasons={season_text} "
        f"dates={date_text} key_columns={','.join(key_columns)} columns={len(columns)}"
    )
    return rows


def print_primary_file_inventory() -> tuple[list[dict], list[dict], list[dict]]:
    print("FILE INVENTORY")
    canonical_rows, canonical_columns = csv_dicts(CANONICAL_FILE)
    canonical_seasons = sorted({int(row["season"]) for row in canonical_rows})
    print(
        f"FILE_TABLE name=official_canonical_games rows={len(canonical_rows)} "
        f"seasons={canonical_seasons[0]}..{canonical_seasons[-1]} "
        f"({len(canonical_seasons)} labels) dates={min(r['game_date'] for r in canonical_rows)}.."
        f"{max(r['game_date'] for r in canonical_rows)} "
        "key_columns=game_id,game_date,home_team,away_team join_key=game_id"
    )
    features = summarize_csv_table(
        "pregame_rolling_features",
        PREGAME_FILE,
        ("game_id", "season", "game_date", "home_team", "away_team", "home_rolling10_5v5_xgf", "away_rolling10_5v5_xgf", "home_max_feature_source_date", "away_max_feature_source_date", "required_features_complete"),
    )
    special = summarize_csv_table(
        "special_teams_merged_features",
        SPECIAL_TEAMS_DIR / "special_teams_merged_features.csv",
        ("game_id", "season", "game_date", "home_team", "away_team", "hpp", "hpk", "app", "apk"),
    )
    summarize_csv_table(
        "special_teams_all_arms_features",
        SPECIAL_TEAMS_DIR / "features_all_arms.csv",
        ("game_id", "season", "home_team", "away_team", "hpp", "hpk", "app", "apk", "hdrawn", "htaken"),
    )

    team_files = sorted(MONEYPUCK_DIR.glob("moneypuck_team_*.csv"))
    if not team_files:
        raise FileNotFoundError(f"no MoneyPuck team-game CSVs found under {MONEYPUCK_DIR}")
    team_rows = []
    team_columns = None
    for path in team_files:
        rows, columns = csv_dicts(path)
        if team_columns is None:
            team_columns = columns
        elif columns != team_columns:
            raise ValueError(f"MoneyPuck schema differs in {path}")
        team_rows.extend(rows)
    all_seasons = sorted({int(row["season"]) for row in team_rows if row["season"].isdigit()})
    all_dates = [row["gameDate"] for row in team_rows if row.get("gameDate")]
    selected_keys = [
        key for key in ("team", "season", "gameId", "playerTeam", "opposingTeam", "gameDate", "situation", "xGoalsFor", "xGoalsAgainst", "x", "y")
        if key in (team_columns or [])
    ]
    print(
        f"FILE_TABLE name=moneypuck_team_game_csvs files={len(team_files)} rows={len(team_rows)} "
        f"seasons={all_seasons[0]}..{all_seasons[-1]} ({len(all_seasons)} labels) "
        f"dates={min(all_dates)}..{max(all_dates)} key_columns={','.join(selected_keys)} "
        "join_key=gameId+playerTeam+situation"
    )
    sbr_file_seasons = Counter(row["season"] for row in jsonl_sbr_rows())
    raw_dir = Path("/root/lp-data/nhl-sbr")
    raw_workbooks = sorted([*raw_dir.glob("*.xlsx"), *raw_dir.glob("*.xls")])
    print(
        f"SBR_RAW_SOURCE workbooks={len(raw_workbooks)} "
        f"normalized_archive_seasons={','.join(sorted(sbr_file_seasons))} "
        "normalized_join_key=date+unordered_team_pair->canonical_game_id"
    )
    special_script = require(SPECIAL_TEAMS_DIR / "run_special_teams.py").read_text(encoding="utf-8")
    penalty_script = require(SPECIAL_TEAMS_DIR / "run_penalty_volume.py").read_text(encoding="utf-8")
    special_prior_filter = 'if x["date"] < day' in special_script
    penalty_prior_filter = 'if x["date"] < d["date"]' in penalty_script
    print(
        "SOURCE_TIME_SEMANTICS special_teams_prior_date_filter="
        f"{'present' if special_prior_filter else 'missing'} "
        "penalty_prior_date_filter="
        f"{'present' if penalty_prior_filter else 'missing'}"
    )
    return features, special, team_rows


def jsonl_sbr_rows() -> list[dict]:
    with gzip.open(require(SBR_FILE), "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def coverage_for_csv_rows(
    label: str,
    rows: list[dict[str, str]],
    linked: dict[int, dict],
    game_column: str,
    strict_feature_check: bool = False,
) -> dict[str, set[int]]:
    by_game = {}
    for row in rows:
        game_id = int(row[game_column])
        if game_id in by_game:
            raise ValueError(f"duplicate {label} row for game_id {game_id}")
        by_game[game_id] = row
    targets = set(linked)
    found = targets.intersection(by_game)
    if strict_feature_check:
        complete = {
            game_id
            for game_id in found
            if by_game[game_id].get("required_features_complete", "").lower() == "true"
        }
        strict = set()
        for game_id in complete:
            row = by_game[game_id]
            game_date = row.get("game_date", "")
            source_dates = (
                row.get("home_max_feature_source_date", ""),
                row.get("away_max_feature_source_date", ""),
            )
            if game_date and all(source_date and source_date < game_date for source_date in source_dates):
                strict.add(game_id)
        print(
            f"COVERAGE source={label} rows={len(rows)} target_rows={len(targets)} "
            f"game_id_matches={len(found)} complete_feature_games={len(complete)} "
            f"strictly_pregame_source_date_games={len(strict)} "
            f"incomplete_or_not_strictly_pregame_games={len(targets - strict)}"
        )
        per_season_coverage("pregame_rolling_features", linked, found, complete, strict)
        return {"matched": found, "complete": complete, "strict": strict}
    print(f"COVERAGE source={label} rows={len(rows)} target_games={len(targets)} game_id_matches={len(found)}")
    return {"matched": found}


def per_season_coverage(
    label: str,
    linked: dict[int, dict],
    *sets: set[int],
) -> None:
    season_ids: dict[str, set[int]] = defaultdict(set)
    for game_id, info in linked.items():
        season_ids[info["season_label"]].add(game_id)
    names = ("target", "row", "complete", "strict_pregame")
    for season in sorted(season_ids):
        counts = [len(season_ids[season])]
        counts.extend(len(season_ids[season].intersection(values)) for values in sets)
        fields = " ".join(f"{name}={count}" for name, count in zip(names, counts))
        print(f"SEASON_FEATURE_COVERAGE source={label} season={season} {fields}")


def print_moneypuck_coverage(team_rows: list[dict[str, str]], linked: dict[int, dict]) -> None:
    by_game: dict[int, set[str]] = defaultdict(set)
    duplicate_rows = 0
    seen = set()
    for row in team_rows:
        if row.get("situation", "").strip().lower() != "all":
            continue
        game_id = int(row["gameId"])
        identity = (game_id, row.get("playerTeam", ""))
        if identity in seen:
            duplicate_rows += 1
        seen.add(identity)
        if game_id in linked:
            by_game[game_id].add(row["playerTeam"])
    target = set(linked)
    any_team = {game_id for game_id, teams in by_game.items() if teams}
    paired = set()
    for game_id, teams in by_game.items():
        game = linked[game_id]["canonical"]
        if {game["home_team"], game["away_team"]}.issubset(teams):
            paired.add(game_id)
    print(
        f"COVERAGE source=moneypuck_postgame_all_situation target_games={len(target)} "
        f"any_team_row={len(any_team)} both_team_rows={len(paired)} "
        f"duplicate_game_team_rows={duplicate_rows}"
    )
    by_season: dict[str, set[int]] = defaultdict(set)
    for game_id, info in linked.items():
        by_season[info["season_label"]].add(game_id)
    for season in sorted(by_season):
        season_target = by_season[season]
        print(
            f"SEASON_COVERAGE source=moneypuck_postgame season={season} target={len(season_target)} "
            f"any_team_row={len(season_target & any_team)} both_team_rows={len(season_target & paired)}"
        )


def load_duckdb_module():
    try:
        import duckdb  # type: ignore
        return duckdb
    except ImportError:
        for site_packages in Path("/root/lp-goalie-research/.venv/lib").glob("python*/site-packages"):
            if str(site_packages) not in sys.path:
                sys.path.insert(0, str(site_packages))
        try:
            import duckdb  # type: ignore
            return duckdb
        except ImportError as exc:
            raise RuntimeError(
                "duckdb Python package is required; use the NHL goalie research venv"
            ) from exc


def print_duckdb_inventory(linked: dict[int, dict]) -> dict[str, set[int]]:
    duckdb = load_duckdb_module()
    require(GOALIE_DB)
    conn = duckdb.connect(
        str(GOALIE_DB),
        read_only=True,
        config={"memory_limit": "700MB", "threads": "1"},
    )
    target_ids = set(linked)
    target_coverage: dict[str, set[int]] = {}
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    print(f"DUCKDB_INVENTORY file={GOALIE_DB} tables={len(tables)} mode=read_only")
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        schema = conn.execute(f"DESCRIBE {quoted}").fetchall()
        columns = [row[0] for row in schema]
        count = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        if "season" in columns:
            season_min, season_max, season_count = conn.execute(
                f"SELECT MIN(season), MAX(season), COUNT(DISTINCT season) FROM {quoted}"
            ).fetchone()
            season_text = f"{season_min}..{season_max} ({season_count} labels)"
        else:
            season_text = "none"
        date_column = next((name for name in ("gameDate", "game_date") if name in columns), None)
        if date_column:
            date_min, date_max = conn.execute(
                f"SELECT MIN(\"{date_column}\"), MAX(\"{date_column}\") FROM {quoted}"
            ).fetchone()
            date_text = f"{date_min}..{date_max}"
        else:
            date_text = "none"
        game_column = next((name for name in ("gameId", "game_id") if name in columns), None)
        key_priority = (
            "gameId", "game_id", "lineId", "playerId", "goalieId", "goalieIdForShot",
            "team", "playerTeam", "homeTeamCode", "awayTeamCode", "season", "gameDate",
            "situation", "starter", "icetime", "iceTimeRank", "xGoals", "xGoalsFor",
            "xGoalsAgainst", "xGoal", "shotAngle", "shotDistance", "location", "savePctg",
            "saves", "ongoal", "goals", "x", "y",
        )
        keys = [name for name in key_priority if name in columns]
        coverage_text = ""
        if game_column:
            game_ids = {
                int(row[0])
                for row in conn.execute(
                    f'SELECT DISTINCT "{game_column}" FROM {quoted} WHERE "{game_column}" IS NOT NULL'
                ).fetchall()
            }
            coverage = game_ids.intersection(target_ids)
            target_coverage[table] = coverage
            coverage_text = f" canonical_game_id_direct_matches={len(coverage)}"
            if table == "shots":
                join_key = "season+game_id(source_local)"
            else:
                join_key = game_column
        elif "playerId" in columns and "season" in columns:
            join_key = "playerId+season+team" if "team" in columns else "playerId+season"
        elif "playerId" in columns:
            join_key = "playerId"
        elif "season" in columns and "team" in columns:
            join_key = "season+team"
        else:
            join_key = "table-specific/non-game"
        print(
            f"DUCKDB_TABLE name={table} rows={count} seasons={season_text} dates={date_text} "
            f"key_columns={','.join(keys)} join_key={join_key}{coverage_text}"
        )
        if table == "shots":
            lower_columns = {column.lower(): column for column in columns}
            coordinate_columns = [
                column for column in columns
                if "coord" in column.lower() or column.lower() in ("x", "y", "xcoord", "ycoord", "xcoordinate", "ycoordinate")
            ]
            location_fields = [
                name for name in ("location", "shotAngle", "shotDistance", "xGoal", "teamCode", "goalieIdForShot")
                if name in columns
            ]
            print(
                f"SHOT_SCHEMA date_field_present={any('date' in column.lower() for column in columns)} "
                f"coordinate_columns={','.join(coordinate_columns) or 'none'} "
                f"location_quality_fields={','.join(location_fields)} "
                f"source_local_game_key={lower_columns.get('game_id', 'missing')}"
            )
    for table, game_ids in sorted(target_coverage.items()):
        regular_target = {
            game_id
            for game_id, info in linked.items()
            if int(info["canonical"]["game_type"]) == 2
        }
        playoff_target = set(linked) - regular_target
        print(
            f"DUCKDB_TARGET_SUMMARY table={table} regular_target_games={len(regular_target)} "
            f"regular_matches={len(regular_target & game_ids)} playoff_target_games={len(playoff_target)} "
            f"playoff_matches={len(playoff_target & game_ids)}"
        )
        for season_label in sorted({info["season_label"] for info in linked.values()}):
            season_ids = {
                game_id
                for game_id, info in linked.items()
                if info["season_label"] == season_label
            }
            regular_ids = {
                game_id
                for game_id in season_ids
                if int(linked[game_id]["canonical"]["game_type"]) == 2
            }
            playoff_ids = season_ids - regular_ids
            print(
                f"DUCKDB_SEASON_COVERAGE table={table} season={season_label} "
                f"target_games={len(season_ids)} direct_game_id_matches={len(season_ids & game_ids)} "
                f"regular_matches={len(regular_ids & game_ids)} playoff_matches={len(playoff_ids & game_ids)}"
            )
    shot_coverage = shot_event_canonical_bridge(conn, linked)
    target_coverage["shots"] = shot_coverage
    conn.close()
    return target_coverage


def shot_event_canonical_bridge(conn, linked: dict[int, dict]) -> set[int]:
    """Count only one-to-one, outcome-anchored matches for the noncanonical shot key.

    shots.game_id is a MoneyPuck-local key and has no date. This bridge uses
    season, home/away teams, final score, and game type strictly to inventory
    historical coverage. Those postgame fields are never features.
    """
    aliases = {"L.A": "LAK", "N.J": "NJD", "S.J": "SJS", "T.B": "TBL"}
    canonical_rows, _ = csv_dicts(CANONICAL_FILE)
    target_ids = set(linked)
    canonical_index: dict[tuple, list[int]] = defaultdict(list)
    for row in canonical_rows:
        game_id = int(row["game_id"])
        game_type = int(row["game_type"]) == 3
        key = (
            int(row["season"]),
            row["home_team"],
            row["away_team"],
            int(row["official_home_score"]),
            int(row["official_away_score"]),
            game_type,
        )
        canonical_index[key].append(game_id)

    shot_groups = conn.execute(
        "SELECT season, game_id, homeTeamCode, awayTeamCode, isPlayoffGame, "
        "MAX(homeTeamGoals), MAX(awayTeamGoals) FROM shots "
        "GROUP BY season, game_id, homeTeamCode, awayTeamCode, isPlayoffGame"
    ).fetchall()
    source_candidates: dict[tuple, list[int]] = {}
    inverse: dict[int, list[tuple]] = defaultdict(list)
    candidate_source_count = 0
    for season, source_game_id, home, away, playoff, home_score, away_score in shot_groups:
        key = (
            int(season),
            aliases.get(str(home), str(home)),
            aliases.get(str(away), str(away)),
            int(home_score),
            int(away_score),
            bool(playoff),
        )
        candidates = canonical_index.get(key, [])
        if not candidates:
            continue
        source_key = (int(season), int(source_game_id), str(home), str(away), int(home_score), int(away_score), bool(playoff))
        source_candidates[source_key] = candidates
        candidate_source_count += bool(set(candidates).intersection(target_ids))
        for game_id in candidates:
            inverse[game_id].append(source_key)

    unambiguous = {
        game_id
        for game_id, source_keys in inverse.items()
        if len(source_keys) == 1 and len(source_candidates[source_keys[0]]) == 1
    }
    possible = set(inverse).intersection(target_ids)
    unambiguous_target = unambiguous.intersection(target_ids)
    print(
        f"SHOT_TABLE_CROSSWALK source_groups_with_target_candidates={candidate_source_count} "
        f"target_games_with_candidate={len(possible)} one_to_one_outcome_anchored_games={len(unambiguous_target)} "
        f"ambiguous_target_games={len(possible - unambiguous_target)} "
        f"target_games_without_candidate={len(target_ids - possible)} no_date_field=true "
        "key=season+home/away+final_score+game_type audit_only_postgame=true"
    )
    per_season: dict[str, set[int]] = defaultdict(set)
    for game_id in unambiguous_target:
        per_season[linked[game_id]["season_label"]].add(game_id)
    for season_label in sorted({info["season_label"] for info in linked.values()}):
        targets = {
            game_id
            for game_id, info in linked.items()
            if info["season_label"] == season_label
        }
        print(
            f"SHOT_TABLE_SEASON_COVERAGE season={season_label} target_games={len(targets)} "
            f"one_to_one_outcome_anchored_games={len(targets & unambiguous_target)}"
        )
    return unambiguous_target


def print_goalie_prior_season_coverage(linked: dict[int, dict]) -> None:
    duckdb = load_duckdb_module()
    conn = duckdb.connect(
        str(GOALIE_DB),
        read_only=True,
        config={"memory_limit": "700MB", "threads": "1"},
    )
    rows = conn.execute(
        "SELECT season, team, playerId, xGoals, goals, ongoal "
        "FROM goalies_seasons WHERE lower(situation)='all'"
    ).fetchall()
    conn.close()
    aliases = {"L.A": "LAK", "N.J": "NJD", "S.J": "SJS", "T.B": "TBL"}
    metric_by_team_season: dict[tuple[int, str], set[int]] = defaultdict(set)
    complete_by_team_season: set[tuple[int, str]] = set()
    for season, team, player_id, xgoals, goals, ongoal in rows:
        if team is None:
            continue
        normalized_team = aliases.get(str(team), str(team))
        metric_by_team_season[(int(season), normalized_team)].add(int(player_id))
        if xgoals is not None and goals is not None and ongoal is not None:
            complete_by_team_season.add((int(season), normalized_team))
    covered_games = set()
    covered_sides = 0
    missing_team_sides: Counter[str] = Counter()
    target_sides = len(linked) * 2
    for game_id, info in linked.items():
        canonical = info["canonical"]
        prior_season = int(canonical["season"]) - 1
        teams = (canonical["home_team"], canonical["away_team"])
        side_hits = 0
        for team in teams:
            if (prior_season, team) in complete_by_team_season:
                side_hits += 1
            else:
                missing_team_sides[team] += 1
        covered_sides += side_hits
        if side_hits == 2:
            covered_games.add(game_id)
    seasons = sorted({season for season, _ in metric_by_team_season})
    print(
        f"GOALIE_PRIOR_SEASON_METRIC source=goalies_seasons metric_fields=xGoals,goals,ongoal "
        f"season_span={seasons[0]}..{seasons[-1]} season_labels={len(seasons)} "
        f"target_team_sides={target_sides} sides_with_prior_season_team_metric={covered_sides} "
        f"games_with_both_team_prior_season_metrics={len(covered_games)} "
        f"missing_team_sides_by_code={dict(sorted(missing_team_sides.items()))} "
        "unit=team_has_at_least_one_goalie_row; starter_identity_not_joined"
    )
    for season_label in sorted({info["season_label"] for info in linked.values()}):
        ids = [gid for gid, info in linked.items() if info["season_label"] == season_label]
        prior_season = int(linked[ids[0]]["canonical"]["season"]) - 1
        side_count = 0
        game_count = 0
        for gid in ids:
            canonical = linked[gid]["canonical"]
            prior_season = int(canonical["season"]) - 1
            hit = sum(
                (prior_season, team) in complete_by_team_season
                for team in (canonical["home_team"], canonical["away_team"])
            )
            side_count += hit
            game_count += hit == 2
        print(
            f"SEASON_COVERAGE source=goalie_prior_season season={season_label} "
            f"prior_goalie_season={prior_season} target_games={len(ids)} "
            f"team_sides={len(ids)*2} metric_sides={side_count} "
            f"games_both_teams={game_count}"
        )


def print_sqlite_inventory(linked: dict[int, dict]) -> dict:
    require(PICKS_DB)
    conn = sqlite3.connect(f"file:{PICKS_DB}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    print(f"SQLITE_INVENTORY file={PICKS_DB} mode=read_only")
    target_ids = set(linked)

    def columns(table: str) -> list[str]:
        return [row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')]

    def grouped(query: str) -> list[tuple]:
        return [tuple(row) for row in conn.execute(query).fetchall()]

    nhl_log = grouped(
        "SELECT season, COUNT(*), COUNT(DISTINCT game_id), MIN(game_date), MAX(game_date) "
        "FROM player_game_logs WHERE lower(league)='nhl' GROUP BY season ORDER BY season"
    )
    log_count = sum(row[1] for row in nhl_log)
    log_ids = {
        int(row[0])
        for row in conn.execute(
            "SELECT DISTINCT game_id FROM player_game_logs WHERE lower(league)='nhl' "
            "AND game_id GLOB '[0-9]*'"
        )
    }
    log_id_matches = log_ids.intersection(target_ids)
    log_games = conn.execute(
        "SELECT COUNT(DISTINCT game_id) FROM player_game_logs WHERE lower(league)='nhl'"
    ).fetchone()[0]
    goalie_log_count = conn.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE lower(league)='nhl' "
        "AND json_valid(stats) AND (json_extract(stats,'$.saves') IS NOT NULL "
        "OR json_extract(stats,'$.shotsAgainst') IS NOT NULL)"
    ).fetchone()[0]
    starter_log_count = conn.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE lower(league)='nhl' "
        "AND json_valid(stats) AND json_extract(stats,'$.starter') IS NOT NULL"
    ).fetchone()[0]
    print(
        f"SQLITE_TABLE name=player_game_logs league=nhl rows={log_count} distinct_games={log_games} "
        f"seasons={nhl_log[0][0]}..{nhl_log[-1][0]} ({len(nhl_log)} labels) "
        f"dates={nhl_log[0][3]}..{nhl_log[-1][4]} goalie_stat_rows={goalie_log_count} "
        f"starter_flag_rows={starter_log_count} key_columns=game_id,player_id,game_date,team,stats "
        "join_key=game_id+player_id"
    )
    print(
        f"SQLITE_COVERAGE source=player_game_logs target_games={len(target_ids)} "
        f"direct_game_id_matches={len(log_id_matches)} current_log_games={len(log_ids)}"
    )
    for season, rows, games, date_min, date_max in nhl_log:
        print(
            f"SQLITE_SEASON_TABLE name=player_game_logs season={season} rows={rows} "
            f"games={games} dates={date_min}..{date_max}"
        )

    stats = grouped(
        "SELECT season, COUNT(*), SUM(CASE WHEN nhl_position='G' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN nhl_position='G' AND save_pct IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM player_stats WHERE lower(league)='nhl' GROUP BY season ORDER BY season"
    )
    if stats:
        print(
            f"SQLITE_TABLE name=player_stats league=nhl rows={sum(row[1] for row in stats)} "
            f"seasons={stats[0][0]}..{stats[-1][0]} ({len(stats)} labels) "
            "key_columns=player_id,season,nhl_position,save_pct,saves,shots_against,goals_against "
            "join_key=player_id+season"
        )
        for season, rows, goalies, save_pct_rows in stats:
            print(
                f"SQLITE_SEASON_TABLE name=player_stats season={season} rows={rows} "
                f"goalie_rows={goalies} goalie_save_pct_rows={save_pct_rows}"
            )

    shares = grouped(
        "SELECT season, COUNT(*), COUNT(DISTINCT metric) FROM player_team_shares "
        "WHERE lower(league)='nhl' GROUP BY season ORDER BY season"
    )
    if shares:
        print(
            f"SQLITE_TABLE name=player_team_shares league=nhl rows={sum(row[1] for row in shares)} "
            f"seasons={shares[0][0]}..{shares[-1][0]} ({len(shares)} labels) "
            "key_columns=season,team,player_id,metric,player_value,team_value,share,through "
            "join_key=player_id+team+season+metric"
        )
        for season, rows, metrics in shares:
            print(f"SQLITE_SEASON_TABLE name=player_team_shares season={season} rows={rows} metrics={metrics}")

    player = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN active THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN nhl_id IS NOT NULL THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN lower(position) IN ('g','goalie') THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN injury_status IS NOT NULL AND trim(injury_status)<>'' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN last_news_date IS NOT NULL AND trim(last_news_date)<>'' THEN 1 ELSE 0 END) "
        "FROM players WHERE lower(league)='nhl'"
    ).fetchone()
    print(
        f"SQLITE_TABLE name=players league=nhl rows={player[0]} active={player[1]} "
        f"with_nhl_id={player[2]} goalie_position={player[3]} injury_status_filled={player[4]} "
        f"last_news_date_filled={player[5]} key_columns=id,nhl_id,team,position,injury_status,last_news_date "
        "join_key=nhl_id"
    )

    injury = grouped("SELECT lower(league), COUNT(*) FROM injury_reports GROUP BY lower(league)")
    print(f"SQLITE_TABLE name=injury_reports league_counts={injury} key_columns=league,season,team,player_id,report_status,practice_status,date_modified join_key=player_id+season")
    nhl_injury = sum(count for league, count in injury if league == "nhl")
    print(f"SQLITE_COVERAGE source=injury_reports target_games={len(linked)} nhl_rows={nhl_injury}")

    news = conn.execute(
        "SELECT COUNT(*), MIN(NULLIF(published,'')), MAX(NULLIF(published,'')), "
        "SUM(CASE WHEN NULLIF(published,'') IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM news_items WHERE lower(league)='nhl'"
    ).fetchone()
    print(
        f"SQLITE_TABLE name=news_items league=nhl rows={news[0]} "
        f"published_nonblank={news[3]} published_range={news[1]}..{news[2]} "
        "key_columns=league,published,first_seen,key_player,headline,body join_key=key_player+published (unstructured)"
    )

    snapshots = grouped(
        "SELECT season, COUNT(*), MIN(captured_at), MAX(captured_at), SUM(player_count) "
        "FROM roster_snapshots WHERE lower(league)='nhl' GROUP BY season ORDER BY season"
    )
    if snapshots:
        snapshot_seasons = {int(row[0]) for row in snapshots}
        target_seasons = {int(info["canonical"]["season"]) for info in linked.values()}
        roster_season_overlap = snapshot_seasons.intersection(target_seasons)
        print(
            f"SQLITE_TABLE name=roster_snapshots league=nhl rows={sum(row[1] for row in snapshots)} "
            f"seasons={snapshots[0][0]}..{snapshots[-1][0]} ({len(snapshots)} labels) "
            "key_columns=id,season,captured_at,published_at,source_checksum,player_count "
            "join_key=snapshot_id"
        )
        for season, rows, date_min, date_max, members in snapshots:
            print(
                f"SQLITE_SEASON_TABLE name=roster_snapshots season={season} snapshots={rows} "
                f"capture_range={date_min}..{date_max} summed_player_count={members}"
            )
    else:
        snapshot_seasons = set()
        roster_season_overlap = set()
    memberships = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT rm.snapshot_id), COUNT(DISTINCT rm.player_id), "
        "MIN(rm.roster_status), MAX(rm.roster_status) FROM roster_memberships rm "
        "JOIN roster_snapshots rs ON rs.id=rm.snapshot_id WHERE lower(rs.league)='nhl'"
    ).fetchone()
    print(
        f"SQLITE_TABLE name=roster_memberships league=nhl rows={memberships[0]} "
        f"snapshots={memberships[1]} distinct_players={memberships[2]} "
        f"roster_status_values={memberships[3]}..{memberships[4]} "
        "key_columns=snapshot_id,player_id,team,position,roster_status join_key=snapshot_id+player_id"
    )
    print(
        f"SQLITE_COVERAGE source=roster_snapshots target_seasons={min(target_seasons)}..{max(target_seasons)} "
        f"snapshot_seasons={','.join(map(str, sorted(snapshot_seasons)))} "
        f"season_overlap={len(roster_season_overlap)} historical_sbr_game_status_coverage=0"
    )

    for table in ("published_roster", "player_game_availability"):
        cols = columns(table)
        if "league" in cols:
            rows_by_league = grouped(
                f'SELECT lower(league), COUNT(*) FROM "{table}" GROUP BY lower(league)'
            )
            nhl_rows = sum(count for league, count in rows_by_league if league == "nhl")
            keys = [name for name in cols if name in ("league", "season", "game_id", "player_id", "team", "status", "played", "report_status")]
            print(
                f"SQLITE_TABLE name={table} rows_by_league={rows_by_league} nhl_rows={nhl_rows} "
                f"key_columns={','.join(keys)} join_key=league+player_id"
            )
    conn.close()
    return {
        "player_game_log_game_id_matches": log_id_matches,
        "starter_flag_rows": starter_log_count,
        "injury_report_nhl_rows": nhl_injury,
        "roster_snapshot_seasons": snapshot_seasons,
        "roster_season_overlap": roster_season_overlap,
        "roster_membership_rows": memberships[0],
    }


def print_availability_evidence(linked: dict[int, dict], file_coverage: dict[str, set[int]], duck_coverage: dict[str, set[int]], sqlite_coverage: dict) -> None:
    target_count = len(linked)
    print("NEW_INFORMATION_FAMILY_COVERAGE")
    print(
        f"family=announced_starting_goalie status=ABSENT target_games={target_count} "
        f"archived_pregame_announcements=0 postgame_starter_flags_in_sbr_target={len(duck_coverage.get('goalies_playoff_boxscores', set()))}"
    )
    print(
        f"family=goalie_quality status=PARTIAL target_games={target_count} "
        "historical_prior_season_team_metric_count_reported_by=GOALIE_PRIOR_SEASON_METRIC "
        f"current_actual_starter_flag_rows_postgame={sqlite_coverage['starter_flag_rows']} "
        "starter_specific_pregame_coverage=0"
    )
    print(
        f"family=shot_quality status=PARTIAL target_games={target_count} "
        f"postgame_shot_event_games_one_to_one={len(duck_coverage.get('shots', set()))} "
        f"pregame_rolling_xg_games={len(file_coverage.get('pregame_strict', set()))}"
    )
    print(
        f"family=deployment status=PARTIAL target_games={target_count} "
        f"postgame_line_gamelog_games={len(duck_coverage.get('lines_gamelogs', set()))} "
        f"postgame_skater_gamelog_games={len(duck_coverage.get('skaters_gamelogs', set()))} "
        f"pregame_special_teams_feature_games={len(file_coverage.get('special_teams', set()))} "
        "announced_line_or_scratch_coverage=0"
    )
    print(
        f"family=injuries_roster_status status=PARTIAL target_games={target_count} "
        f"structured_historical_nhl_injury_reports={sqlite_coverage['injury_report_nhl_rows']} "
        f"current_roster_snapshot_seasons={len(sqlite_coverage['roster_snapshot_seasons'])} "
        f"historical_sbr_game_status_coverage={len(sqlite_coverage['roster_season_overlap'])}"
    )


def main() -> None:
    print("NHL NEW-INFORMATION AVAILABILITY AUDIT audit_date=2026-10-20")
    _, linked, _ = load_crosswalk()
    features, special_features, money_rows = print_primary_file_inventory()

    file_coverage = {}
    feature_coverage = coverage_for_csv_rows(
        "pregame_rolling_features", features, linked, "game_id", strict_feature_check=True
    )
    file_coverage["pregame_strict"] = feature_coverage["strict"]
    special = coverage_for_csv_rows(
        "special_teams_merged_features", special_features, linked, "game_id"
    )
    file_coverage["special_teams"] = special["matched"]
    special_by_id = {int(row["game_id"]): row for row in special_features}
    special_complete = {
        game_id
        for game_id in special["matched"]
        if all(special_by_id[game_id].get(column, "").strip() for column in ("hpp", "hpk", "app", "apk"))
    }
    print(
        f"COVERAGE source=special_teams_merged_features target_games={len(linked)} "
        f"all_four_pp_pk_values={len(special_complete)}"
    )
    print_moneypuck_coverage(money_rows, linked)

    duck_coverage = print_duckdb_inventory(linked)
    print_goalie_prior_season_coverage(linked)
    sqlite_coverage = print_sqlite_inventory(linked)
    print_availability_evidence(linked, file_coverage, duck_coverage, sqlite_coverage)

    for evidence_file in (STARTER_AUDIT, GOALIE_AUDIT):
        require(evidence_file)
    print(f"LOCAL_SOURCE_NOTES starter_feed_audit={STARTER_AUDIT} goalie_data_audit={GOALIE_AUDIT}")
    print("END_AUDIT read_only=true model_fitting=false")


if __name__ == "__main__":
    main()
