#!/usr/bin/env python3
"""Read-only full-frame reconciliation against the historical NHL log archive.

The archive is opened read-only. Matching uses canonical numeric game_id and
numeric playerId; player names are never fallback join keys.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_DUCKDB = Path("/root/nhl_database_2025-26-playoffs.duckdb")
TEAM_ALIASES = {"PHX": "ARI"}
SOG_LINES = (0.5, 1.5, 2.5, 3.5)
SAVE_LINES = (20.5, 24.5, 28.5)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def numeric_seconds(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def canonical_team(value: str) -> str:
    return TEAM_ALIASES.get(value, value)


def name_tokens(value: Any) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    tokens, current = [], []
    for char in text.casefold():
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def names_consistent(official_name: Any, archive_name: Any) -> bool:
    official, archive = name_tokens(official_name), name_tokens(archive_name)
    if not official or not archive:
        return False
    if official == archive:
        return True
    # GameCenter commonly publishes a first initial while the log archive
    # publishes the full given name. Names are only cross-checked here; they
    # are never used to match rows.
    return (
        len(official) >= 2 and len(archive) >= 2
        and official[0][0] == archive[0][0]
        and official[-1] == archive[-1]
    )


def name_crosschecks(
    official_sog: list[dict[str, Any]], archive_sog: list[dict[str, Any]],
    official_goalies: list[dict[str, Any]], archive_goalies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_player: dict[int, dict[str, Any]] = {}
    for market, official_rows, archive_rows in (
        ("SOG", official_sog, archive_sog),
        ("SAVES", official_goalies, archive_goalies),
    ):
        official, official_dupes = grouped(official_rows)
        archive, archive_dupes = grouped(archive_rows)
        for key in sorted(set(official) & set(archive)):
            if key in official_dupes or key in archive_dupes:
                continue
            off, arc = official[key][0], archive[key][0]
            if off.get("identity_status", "OK") != "OK" or arc.get("identity_status", "OK") != "OK":
                continue
            official_name, archive_name = str(off.get("player_name") or ""), str(arc.get("archive_name") or "")
            if names_consistent(official_name, archive_name):
                continue
            pid = int(key[1])
            item = by_player.setdefault(pid, {
                "player_id": pid, "official_names": set(), "archive_names": set(),
                "seasons": set(), "SOG_shared_rows": 0, "SAVES_shared_rows": 0,
                "missing_name_rows": 0,
            })
            if official_name:
                item["official_names"].add(official_name)
            if archive_name:
                item["archive_names"].add(archive_name)
            item["seasons"].add(int(off["season"]))
            item[f"{market}_shared_rows"] += 1
            item["missing_name_rows"] += int(not official_name or not archive_name)
    output = []
    for item in by_player.values():
        output.append({
            "player_id": item["player_id"],
            "official_names": "; ".join(sorted(item["official_names"])),
            "archive_names": "; ".join(sorted(item["archive_names"])),
            "seasons": ";".join(str(value) for value in sorted(item["seasons"])),
            "SOG_shared_rows": item["SOG_shared_rows"],
            "SAVES_shared_rows": item["SAVES_shared_rows"],
            "affected_shared_rows": item["SOG_shared_rows"] + item["SAVES_shared_rows"],
            "missing_name_rows": item["missing_name_rows"],
            "review_status": "POTENTIAL_NAME_ALIAS_OR_ID_CONFLICT",
        })
    return sorted(output, key=lambda row: row["player_id"])


def load_archive(
    duckdb_path: Path, frame: list[dict[str, str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not duckdb_path.is_file():
        raise FileNotFoundError(f"historical archive missing: {duckdb_path}")
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("DuckDB unavailable; run with /root/lp-goalie-research/.venv/bin/python") from exc
    game_ids = sorted(int(row["game_id"]) for row in frame)
    if len(game_ids) != len(set(game_ids)):
        raise ValueError("duplicate canonical game IDs")
    id_sql = ",".join(str(gid) for gid in game_ids)
    connection = duckdb.connect(
        str(duckdb_path), read_only=True,
        config={"memory_limit": "256MB", "threads": "1"},
    )
    try:
        connection.execute("SET enable_progress_bar=false")
        skater_columns = {r[0] for r in connection.execute("DESCRIBE SELECT * FROM skaters_gamelogs").fetchall()}
        goalie_columns = {r[0] for r in connection.execute("DESCRIBE SELECT * FROM goalies_gamelogs").fetchall()}
        required_skater = {"season", "gameId", "gameDate", "playerId", "name", "playerTeam", "situation", "I_F_shotsOnGoal"}
        required_goalie = {"season", "gameId", "gameDate", "playerId", "name", "playerTeam", "situation", "ongoal", "goals", "icetime"}
        if not required_skater.issubset(skater_columns):
            raise ValueError(f"skater archive schema missing {sorted(required_skater-skater_columns)}")
        if not required_goalie.issubset(goalie_columns):
            raise ValueError(f"goalie archive schema missing {sorted(required_goalie-goalie_columns)}")
        skater_rows = connection.execute(
            "SELECT season, gameId, gameDate, playerId, name, playerTeam, I_F_shotsOnGoal "
            f"FROM skaters_gamelogs WHERE lower(situation)='all' AND gameId IN ({id_sql})"
        ).fetchall()
        goalie_rows = connection.execute(
            "SELECT season, gameId, gameDate, playerId, name, playerTeam, ongoal, goals, icetime "
            f"FROM goalies_gamelogs WHERE lower(situation)='all' AND gameId IN ({id_sql})"
        ).fetchall()
    finally:
        connection.close()

    by_id = {int(row["game_id"]): row for row in frame}
    skaters: list[dict[str, Any]] = []
    goalies: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    nonappearing_goalies: list[dict[str, Any]] = []

    for season, raw_gid, game_date, raw_pid, archive_name, team, raw_sog in skater_rows:
        gid = integer(raw_gid)
        pid = integer(raw_pid)
        if gid is None or gid not in by_id:
            issues.append({"game_id": gid or "", "season": season, "player_id": pid or "", "source": "archive_skater", "issue": "INVALID_OR_OUTSIDE_FRAME_GAME_ID", "detail": str(raw_gid)})
            continue
        if pid is None or pid <= 0:
            issues.append({"game_id": gid, "season": season, "player_id": "", "source": "archive_skater", "issue": "MISSING_OR_INVALID_PLAYER_ID", "detail": str(raw_pid)})
            continue
        game = by_id[gid]
        identity_status = "OK"
        date_text = str(integer(game_date) or "")
        if int(season) != int(game["season"]) or date_text != game["game_date"].replace("-", ""):
            identity_status = "CONFLICT"
            issues.append({"game_id": gid, "season": season, "player_id": pid, "source": "archive_skater", "issue": "SEASON_OR_DATE_CONFLICT", "detail": f"source={season}/{date_text} canonical={game['season']}/{game['game_date']}"})
        team = canonical_team(str(team))
        if team not in (game["home_team"], game["away_team"]):
            identity_status = "CONFLICT"
            issues.append({"game_id": gid, "season": season, "player_id": pid, "source": "archive_skater", "issue": "TEAM_OUTSIDE_GAME", "detail": f"source={team} canonical={game['home_team']}/{game['away_team']}"})
        sog = integer(raw_sog)
        if sog is None or sog < 0:
            identity_status = "CONFLICT"
            issues.append({"game_id": gid, "season": season, "player_id": pid, "source": "archive_skater", "issue": "INVALID_SOG", "detail": str(raw_sog)})
        skaters.append({"game_id": gid, "season": int(season), "player_id": pid, "team": team, "sog": sog, "archive_name": str(archive_name or ""), "identity_status": identity_status})

    for season, raw_gid, game_date, raw_pid, archive_name, team, raw_sa, raw_ga, raw_icetime in goalie_rows:
        gid = integer(raw_gid)
        pid = integer(raw_pid)
        if gid is None or gid not in by_id:
            issues.append({"game_id": gid or "", "season": season, "player_id": pid or "", "source": "archive_goalie", "issue": "INVALID_OR_OUTSIDE_FRAME_GAME_ID", "detail": str(raw_gid)})
            continue
        if pid is None or pid <= 0:
            issues.append({"game_id": gid, "season": season, "player_id": "", "source": "archive_goalie", "issue": "MISSING_OR_INVALID_PLAYER_ID", "detail": str(raw_pid)})
            continue
        game = by_id[gid]
        identity_status = "OK"
        date_text = str(integer(game_date) or "")
        if int(season) != int(game["season"]) or date_text != game["game_date"].replace("-", ""):
            identity_status = "CONFLICT"
            issues.append({"game_id": gid, "season": season, "player_id": pid, "source": "archive_goalie", "issue": "SEASON_OR_DATE_CONFLICT", "detail": f"source={season}/{date_text} canonical={game['season']}/{game['game_date']}"})
        team = canonical_team(str(team))
        if team not in (game["home_team"], game["away_team"]):
            identity_status = "CONFLICT"
            issues.append({"game_id": gid, "season": season, "player_id": pid, "source": "archive_goalie", "issue": "TEAM_OUTSIDE_GAME", "detail": f"source={team} canonical={game['home_team']}/{game['away_team']}"})
        icetime = numeric_seconds(raw_icetime)
        if icetime is None:
            identity_status = "CONFLICT"
            issues.append({"game_id": gid, "season": season, "player_id": pid, "source": "archive_goalie", "issue": "INVALID_GOALIE_ICETIME", "detail": str(raw_icetime)})
        elif icetime == 0:
            nonappearing_goalies.append({
                "game_id": gid, "season": int(season), "player_id": pid,
                "team": team, "archive_name": str(archive_name or ""),
                "icetime": raw_icetime, "status": "ZERO_ICE_TIME",
            })
            continue
        sa, ga = integer(raw_sa), integer(raw_ga)
        saves = None if sa is None or ga is None else sa - ga
        if sa is None or ga is None or sa < 0 or ga < 0 or saves is None or saves < 0:
            identity_status = "CONFLICT"
            issues.append({"game_id": gid, "season": season, "player_id": pid, "source": "archive_goalie", "issue": "INVALID_RECONSTRUCTED_SAVES", "detail": f"shots_against={raw_sa}; goals_against={raw_ga}"})
        goalies.append({
            "game_id": gid, "season": int(season), "player_id": pid, "team": team,
            "archive_name": str(archive_name or ""), "icetime": raw_icetime,
            "saves": saves, "shots_against": sa, "goals_against": ga,
            "identity_status": identity_status,
        })
    return skaters, goalies, issues, nonappearing_goalies


def grouped(rows: list[dict[str, Any]]) -> tuple[dict[tuple[int, int], list[dict[str, Any]]], set[tuple[int, int]]]:
    output: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        output[(int(row["game_id"]), int(row["player_id"]))].append(row)
    return output, {key for key, values in output.items() if len(values) > 1}


def compare_market(
    frame: list[dict[str, str]], official_rows: list[dict[str, Any]],
    archive_rows: list[dict[str, Any]], fields: tuple[str, ...], label: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, dict[str, Any]], set[tuple[int, int]]]:
    official, official_dupes = grouped(official_rows)
    archive, archive_dupes = grouped(archive_rows)
    duplicate_keys = official_dupes | archive_dupes
    union = set(official) | set(archive)
    frame_by_id = {int(row["game_id"]): row for row in frame}
    per_season: dict[int, dict[str, Any]] = {
        int(row["season"]): {
            "canonical_games": 0, "sbr_market_games": 0,
            f"{label}_official_rows": 0, f"{label}_archive_rows": 0,
            f"{label}_union_player_games": 0, f"{label}_shared_player_games": 0,
            f"{label}_exact_matches": 0, f"{label}_value_mismatches": 0,
            f"{label}_official_only": 0, f"{label}_archive_only": 0,
            f"{label}_identity_conflicts": 0, f"{label}_games_with_mismatch": 0,
            f"{label}_games_with_2plus_mismatches": 0,
        } for row in frame
    }
    for row in frame:
        season = int(row["season"])
        per_season[season]["canonical_games"] += 1
        per_season[season]["sbr_market_games"] += int(row["in_sbr_market_archive"])
    for row in official_rows:
        per_season[int(row["season"])][f"{label}_official_rows"] += 1
    for row in archive_rows:
        per_season[int(row["season"])][f"{label}_archive_rows"] += 1

    details = []
    mismatch_counts_by_game: Counter[tuple[int, int]] = Counter()
    counts_by_season: Counter[tuple[int, str]] = Counter()
    shared_rows_for_flips = []
    for key in sorted(union):
        gid, pid = key
        game = frame_by_id[gid]
        season = int(game["season"])
        off_rows, arc_rows = official.get(key, []), archive.get(key, [])
        off = off_rows[0] if len(off_rows) == 1 else None
        arc = arc_rows[0] if len(arc_rows) == 1 else None
        if key in duplicate_keys:
            status = "IDENTITY_CONFLICT_DUPLICATE_ID"
        elif off is None:
            status = "ARCHIVE_ONLY"
        elif arc is None:
            status = "OFFICIAL_ONLY"
        elif off.get("identity_status", "OK") != "OK" or arc.get("identity_status", "OK") != "OK":
            status = "IDENTITY_CONFLICT_SOURCE_ROW"
        elif canonical_team(str(off["team"])) != canonical_team(str(arc["team"])):
            status = "IDENTITY_CONFLICT_TEAM"
        elif any(off.get(field) in (None, "") or arc.get(field) in (None, "") for field in fields):
            status = "MISSING_OUTCOME_FIELD"
        elif any(int(off[field]) != int(arc[field]) for field in fields):
            status = "VALUE_MISMATCH"
        else:
            status = "EXACT_MATCH"
        counts_by_season[(season, status)] += 1
        per_season[season][f"{label}_union_player_games"] += 1
        if (
            off is not None and arc is not None and key not in duplicate_keys
            and off.get("identity_status", "OK") == "OK"
            and arc.get("identity_status", "OK") == "OK"
            and canonical_team(str(off["team"])) == canonical_team(str(arc["team"]))
        ):
            per_season[season][f"{label}_shared_player_games"] += 1
            shared_rows_for_flips.append((season, off, arc))
        if status != "EXACT_MATCH":
            mismatch_counts_by_game[(season, gid)] += 1
            details.append({
                "market": label, "game_id": gid, "season": season,
                "in_sbr_market_archive": int(game["in_sbr_market_archive"]),
                "player_id": pid, "status": status,
                **{f"official_{field}": "" if off is None else off.get(field, "") for field in fields},
                **{f"archive_{field}": "" if arc is None else arc.get(field, "") for field in fields},
            })
    for season, row in per_season.items():
        row[f"{label}_exact_matches"] = counts_by_season[(season, "EXACT_MATCH")]
        row[f"{label}_value_mismatches"] = counts_by_season[(season, "VALUE_MISMATCH")]
        row[f"{label}_official_only"] = counts_by_season[(season, "OFFICIAL_ONLY")]
        row[f"{label}_archive_only"] = counts_by_season[(season, "ARCHIVE_ONLY")]
        row[f"{label}_identity_conflicts"] = sum(
            value for (s, status), value in counts_by_season.items()
            if s == season and status.startswith("IDENTITY_CONFLICT")
        ) + counts_by_season[(season, "MISSING_OUTCOME_FIELD")]
        game_counts = [count for (s, _gid), count in mismatch_counts_by_game.items() if s == season]
        row[f"{label}_games_with_mismatch"] = len(game_counts)
        row[f"{label}_games_with_2plus_mismatches"] = sum(count >= 2 for count in game_counts)
    return details, shared_rows_for_flips, per_season, duplicate_keys


def calculate_line_flips(
    shared_rows: list[tuple[int, dict[str, Any], dict[str, Any]]],
    stat: str, lines: tuple[float, ...], market: str,
) -> list[dict[str, Any]]:
    by_line_season: dict[tuple[float, int], list[int]] = defaultdict(lambda: [0, 0, 0])
    for season, official, archive in shared_rows:
        a, b = official.get(stat), archive.get(stat)
        for line in lines:
            counts = by_line_season[(line, season)]
            counts[0] += 1
            if a in (None, "") or b in (None, ""):
                counts[2] += 1
            elif (int(a) > line) != (int(b) > line):
                counts[1] += 1
    output = []
    for (line, season), (shared, flips, unscorable) in sorted(by_line_season.items()):
        scorable = shared - unscorable
        output.append({
            "market": market, "season": season, "line": line,
            "shared_player_games": shared, "scorable_player_games": scorable,
            "unscorable_player_games": unscorable, "side_flips": flips,
            "side_flip_share": "" if not scorable else flips / scorable,
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=Path, default=HERE / "canonical_frame.csv")
    parser.add_argument("--games", type=Path, default=HERE / "official_game_sides.csv")
    parser.add_argument("--skaters", type=Path, default=HERE / "official_skater_outcomes.csv")
    parser.add_argument("--goalies", type=Path, default=HERE / "official_goalie_outcomes.csv")
    parser.add_argument("--team-sog", type=Path, default=HERE / "official_team_sog_validation.csv")
    parser.add_argument("--quality-issues", type=Path, default=HERE / "official_quality_issues.csv")
    parser.add_argument("--duckdb", type=Path, default=DEFAULT_DUCKDB)
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()

    frame, official_games = read_csv(args.frame), read_csv(args.games)
    official_skaters, official_goalies_all = read_csv(args.skaters), read_csv(args.goalies)
    team_sog = read_csv(args.team_sog)
    if len(official_games) != len(frame) * 2:
        raise ValueError(f"official team-side count {len(official_games)} != {len(frame)*2}")
    official_game_ids = {int(row["game_id"]) for row in official_games}
    frame_ids = {int(row["game_id"]) for row in frame}
    if official_game_ids != frame_ids:
        raise ValueError("official game-side IDs do not equal the frozen canonical frame")

    archive_skaters, archive_goalies, archive_issues, archive_nonappearing_goalies = load_archive(args.duckdb, frame)
    identity_issues = list(archive_issues)
    quality = read_csv(args.quality_issues)
    for row in quality:
        if row["issue_type"] in ("MISSING_OR_INVALID_PLAYER_ID", "DUPLICATE_PLAYER_ID_WITHIN_GAME"):
            identity_issues.append({
                "game_id": row["game_id"], "season": "", "player_id": row["player_id"],
                "source": "official", "issue": row["issue_type"],
                "detail": f"{row['record_key']} {row['detail']}",
            })

    frame_by_id = {int(row["game_id"]): row for row in frame}
    official_sog_rows = []
    for row in official_skaters:
        pid = integer(row["player_id"])
        if pid is None:
            continue
        official_sog_rows.append({
            "game_id": int(row["game_id"]), "season": int(row["season"]),
            "player_id": pid, "team": row["team"], "player_name": row["player_name"],
            "sog": integer(row["sog"]),
            "identity_status": row.get("identity_status", "OK"),
        })
    archive_sog_rows = archive_skaters

    # Zero-TOI goalies stay in the official outcome file and are not treated as
    # played-game prop outcomes. Unknown-TOI rows are also withheld and reported.
    official_goalie_rows = []
    for row in official_goalies_all:
        if row["appeared"] != "1":
            continue
        pid = integer(row["player_id"])
        if pid is None:
            continue
        official_goalie_rows.append({
            "game_id": int(row["game_id"]), "season": int(row["season"]),
            "player_id": pid, "team": row["team"], "player_name": row["player_name"],
            "toi": row["toi"], "appeared": row["appeared"],
            "saves": integer(row["saves"]),
            "shots_against": integer(row["shots_against"]),
            "goals_against": integer(row["goals_against"]),
            "identity_status": row.get("identity_status", "OK"),
        })

    name_reviews = name_crosschecks(
        official_sog_rows, archive_skaters, official_goalie_rows, archive_goalies
    )
    for row in name_reviews:
        identity_issues.append({
            "game_id": "", "season": row["seasons"], "player_id": row["player_id"],
            "source": "official_vs_archive_display_name",
            "issue": row["review_status"],
            "detail": (
                f"official={row['official_names']}; archive={row['archive_names']}; "
                f"SOG_shared_rows={row['SOG_shared_rows']}; "
                f"SAVES_shared_rows={row['SAVES_shared_rows']}"
            ),
        })

    sog_details, sog_shared, sog_by_season, sog_dupes = compare_market(
        frame, official_sog_rows, archive_sog_rows, ("sog",), "SOG"
    )
    goalie_details, goalie_shared, goalie_by_season, goalie_dupes = compare_market(
        frame, official_goalie_rows, archive_goalies,
        ("saves", "shots_against", "goals_against"), "SAVES"
    )
    for label, duplicates in (("archive_sog", sog_dupes), ("archive_goalie", goalie_dupes)):
        for gid, pid in sorted(duplicates):
            identity_issues.append({
                "game_id": gid, "season": frame_by_id[gid]["season"],
                "player_id": pid, "source": label,
                "issue": "DUPLICATE_GAME_PLAYER_ID",
                "detail": "multiple rows share numeric game_id/player_id",
            })

    summary_rows = []
    for season in sorted(sog_by_season):
        row = {"season": season, **sog_by_season[season]}
        row.update({f"goalie_{key}": value for key, value in goalie_by_season[season].items() if key not in ("canonical_games", "sbr_market_games")})
        row["official_zero_toi_goalie_slots"] = sum(
            int(item["season"]) == season and item["appeared"] == "0"
            for item in official_goalies_all
        )
        row["archive_zero_icetime_goalie_rows"] = sum(
            int(item["season"]) == season for item in archive_nonappearing_goalies
        )
        row["official_unknown_toi_goalie_rows"] = sum(
            int(item["season"]) == season and item["appeared"] == ""
            for item in official_goalies_all
        )
        row["official_team_sog_sum_mismatches"] = sum(
            int(item["season"]) == season and item["validation"] != "PASS"
            for item in team_sog
        )
        row["official_canonical_score_mismatches"] = sum(
            int(item["season"]) == season and integer(item["score"]) != integer(item["canonical_score"])
            for item in official_games
        )
        season_name_reviews = [
            item for item in name_reviews if str(season) in item["seasons"].split(";")
        ]
        row["potential_name_crosscheck_ids"] = len(season_name_reviews)
        row["potential_name_crosscheck_sog_rows"] = sum(int(item["SOG_shared_rows"]) for item in season_name_reviews)
        row["potential_name_crosscheck_goalie_rows"] = sum(int(item["SAVES_shared_rows"]) for item in season_name_reviews)
        summary_rows.append(row)

    flips = calculate_line_flips(sog_shared, "sog", SOG_LINES, "SOG")
    flips.extend(calculate_line_flips(goalie_shared, "saves", SAVE_LINES, "SAVES"))
    max_flip_row = max(
        (row for row in flips if row["side_flip_share"] != ""),
        key=lambda row: float(row["side_flip_share"]), default=None,
    )
    def aggregate(values: dict[int, dict[str, Any]], prefix: str) -> dict[str, int]:
        names = (
            f"{prefix}_official_rows", f"{prefix}_archive_rows",
            f"{prefix}_union_player_games", f"{prefix}_shared_player_games",
            f"{prefix}_exact_matches", f"{prefix}_value_mismatches",
            f"{prefix}_official_only", f"{prefix}_archive_only",
        )
        return {name: sum(row[name] for row in values.values()) for name in names}
    sog_aggregate = aggregate(sog_by_season, "SOG")
    goalie_aggregate = aggregate(goalie_by_season, "SAVES")
    zero_toi = [row for row in official_goalies_all if row["appeared"] == "0"]
    canonical_score_conflicts = [
        row for row in official_games
        if integer(row["score"]) != integer(row["canonical_score"])
    ]

    write_csv(args.out / "archive_sog_discrepancies.csv", [
        "market", "game_id", "season", "in_sbr_market_archive", "player_id", "status",
        "official_sog", "archive_sog",
    ], sog_details)
    write_csv(args.out / "archive_goalie_discrepancies.csv", [
        "market", "game_id", "season", "in_sbr_market_archive", "player_id", "status",
        "official_saves", "archive_saves", "official_shots_against", "archive_shots_against",
        "official_goals_against", "archive_goals_against",
    ], goalie_details)
    official_goalies_by_key = {
        (int(row["game_id"]), int(row["player_id"])): row for row in official_goalie_rows
    }
    archive_goalies_by_key = {
        (int(row["game_id"]), int(row["player_id"])): row for row in archive_goalies
    }
    one_sided_goalies = []
    for detail in goalie_details:
        if detail["status"] not in ("OFFICIAL_ONLY", "ARCHIVE_ONLY"):
            continue
        key = (int(detail["game_id"]), int(detail["player_id"]))
        official = official_goalies_by_key.get(key, {})
        archive = archive_goalies_by_key.get(key, {})
        one_sided_goalies.append({
            "game_id": key[0], "season": detail["season"], "player_id": key[1],
            "status": detail["status"],
            "official_name": official.get("player_name", ""),
            "official_team": official.get("team", ""),
            "official_toi": official.get("toi", ""),
            "official_saves": detail["official_saves"],
            "official_shots_against": detail["official_shots_against"],
            "official_goals_against": detail["official_goals_against"],
            "archive_name": archive.get("archive_name", ""),
            "archive_team": archive.get("team", ""),
            "archive_icetime": archive.get("icetime", ""),
            "archive_saves": detail["archive_saves"],
            "archive_shots_against": detail["archive_shots_against"],
            "archive_goals_against": detail["archive_goals_against"],
        })
    write_csv(args.out / "played_goalie_one_sided_rows.csv", [
        "game_id", "season", "player_id", "status", "official_name", "official_team",
        "official_toi", "official_saves", "official_shots_against", "official_goals_against",
        "archive_name", "archive_team", "archive_icetime", "archive_saves",
        "archive_shots_against", "archive_goals_against",
    ], one_sided_goalies)
    write_csv(args.out / "prop_side_flip_by_season.csv", [
        "market", "season", "line", "shared_player_games", "scorable_player_games",
        "unscorable_player_games", "side_flips", "side_flip_share",
    ], flips)
    write_csv(args.out / "zero_toi_goalie_slots.csv", list(zero_toi[0]) if zero_toi else [
        "record_key", "game_id", "season", "game_date", "team", "opponent", "home_away",
        "player_id", "player_name", "position", "source_group", "toi", "toi_seconds",
        "appeared", "identity_status", "saves", "shots_against", "goals_against", "starter",
    ], zero_toi)
    issue_fields = ["game_id", "season", "player_id", "source", "issue", "detail"]
    write_csv(args.out / "archive_identity_issues.csv", issue_fields, identity_issues)
    write_csv(args.out / "archive_name_crosscheck.csv", [
        "player_id", "official_names", "archive_names", "seasons",
        "SOG_shared_rows", "SAVES_shared_rows", "affected_shared_rows",
        "missing_name_rows", "review_status",
    ], name_reviews)
    write_csv(args.out / "archive_nonappearing_goalie_slots.csv", [
        "game_id", "season", "player_id", "team", "archive_name", "icetime", "status",
    ], archive_nonappearing_goalies)
    write_csv(args.out / "official_canonical_score_conflicts.csv", list(canonical_score_conflicts[0]) if canonical_score_conflicts else [
        "game_id", "season", "game_date", "side", "team", "score", "canonical_score",
        "team_sog", "in_sbr_market_archive", "raw_sha256", "compressed_sha256",
    ], canonical_score_conflicts)
    fields = list(dict.fromkeys(key for row in summary_rows for key in row))
    write_csv(args.out / "reconciliation_by_season.csv", fields, summary_rows)

    status_counts = lambda rows: dict(Counter(row["status"] for row in rows))
    max_flip = max((float(row["side_flip_share"]) for row in flips if row["side_flip_share"] != ""), default=0.0)
    result = {
        "canonical_frame_games": len(frame),
        "sbr_market_games": sum(int(row["in_sbr_market_archive"]) for row in frame),
        "canonical_only_game_ids": sorted(gid for gid, row in frame_by_id.items() if row["in_sbr_market_archive"] == "0"),
        "official_skater_rows": len(official_sog_rows), "archive_skater_rows": len(archive_sog_rows),
        "official_goalie_rows_including_zero_toi": len(official_goalies_all),
        "official_played_goalie_rows": len(official_goalie_rows),
        "official_zero_toi_goalie_slots": len(zero_toi),
        "archive_goalie_rows": len(archive_goalies),
        "archive_zero_icetime_goalie_rows": len(archive_nonappearing_goalies),
        "sog_reconciliation_status_counts": status_counts(sog_details),
        "goalie_reconciliation_status_counts": status_counts(goalie_details),
        "sog_reconciliation_aggregate": sog_aggregate,
        "goalie_reconciliation_aggregate": goalie_aggregate,
        "archive_or_official_identity_issues": len(identity_issues),
        "potential_name_crosscheck_ids": len(name_reviews),
        "potential_name_crosscheck_sog_rows": sum(int(row["SOG_shared_rows"]) for row in name_reviews),
        "potential_name_crosscheck_goalie_rows": sum(int(row["SAVES_shared_rows"]) for row in name_reviews),
        "official_canonical_score_conflicts": len(canonical_score_conflicts),
        "max_prop_side_flip_share": max_flip,
        "max_prop_side_flip": max_flip_row,
        "model_fitting_performed": False,
        "market_evaluation_performed": False,
        "production_data_written": False,
    }
    (args.out / "reconciliation_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    partial_frame_dates = sorted(row["game_date"] for row in frame if int(row["season"]) == 2022)
    partial_market_dates = sorted(
        row["game_date"] for row in frame
        if int(row["season"]) == 2022 and row["in_sbr_market_archive"] == "1"
    )
    report = [
        "# NHL official outcomes: archive reconciliation", "",
        "Outcome-quality audit only. No fitting, forecast, ROI, sportsbook price test, or production data replacement.",
        "", "## Population", "",
        f"- Canonical official boxscore frame: {len(frame):,} regular-season games.",
        f"- SBR regular-season market population: {result['sbr_market_games']:,} games.",
        f"- The final partial 2022–23 canonical block is {sum(int(row['season']) == 2022 for row in frame):,} games, {partial_frame_dates[0]} to {partial_frame_dates[-1]}; its SBR subset is {sum(int(row['season']) == 2022 and row['in_sbr_market_archive'] == '1' for row in frame):,} games, {partial_market_dates[0]} to {partial_market_dates[-1]}.",
        f"- Four canonical-only games in that block: `{result['canonical_only_game_ids']}`.",
        "- The goalie experiment population remains 4,872 SBR games; its 4,763 eligible rows and 3,509 OOF rows remain separate and unchanged.",
        "", "## Reconciliation by season", "",
        "See `reconciliation_by_season.csv` for row and game counts, exact matches, value discrepancies, missing rows, identity conflicts, official and archive zero-TOI goalie rows, official team-SOG totals, canonical-score checks, and potential cross-source name reviews.",
        "", "| Season | Canonical games | SBR games | SOG exact / shared | SOG value mismatches | SOG official only | SOG archive only | Goalie appearances | Goalie exact / shared | Goalie value mismatches | Goalie official only | Goalie archive only | Official zero-TOI slots | Archive zero-TOI rows | Potential name-review IDs |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        report.append(
            f"| {row['season']} | {row['canonical_games']} | {row['sbr_market_games']} "
            f"| {row['SOG_exact_matches']} / {row['SOG_shared_player_games']} "
            f"| {row['SOG_value_mismatches']} | {row['SOG_official_only']} | {row['SOG_archive_only']} "
            f"| {row['goalie_SAVES_official_rows']} | {row['goalie_SAVES_exact_matches']} / {row['goalie_SAVES_shared_player_games']} "
            f"| {row['goalie_SAVES_value_mismatches']} | {row['goalie_SAVES_official_only']} "
            f"| {row['goalie_SAVES_archive_only']} | {row['official_zero_toi_goalie_slots']} | {row['archive_zero_icetime_goalie_rows']} | {row['potential_name_crosscheck_ids']} |"
        )
    report.extend([
        "",
        "Aggregate row reconciliation:",
        f"- SOG: {sog_aggregate['SOG_official_rows']:,} official rows; {sog_aggregate['SOG_archive_rows']:,} archive rows; {sog_aggregate['SOG_shared_player_games']:,} shared game/player IDs; {sog_aggregate['SOG_exact_matches']:,} exact ({sog_aggregate['SOG_exact_matches']/sog_aggregate['SOG_shared_player_games']:.6%} of shared rows); {sog_aggregate['SOG_value_mismatches']:,} value mismatches; {sog_aggregate['SOG_official_only']:,} official-only; {sog_aggregate['SOG_archive_only']:,} archive-only.",
        f"- Played goalie outcomes: {goalie_aggregate['SAVES_official_rows']:,} official rows; {goalie_aggregate['SAVES_archive_rows']:,} archive rows; {goalie_aggregate['SAVES_shared_player_games']:,} shared game/player IDs; {goalie_aggregate['SAVES_exact_matches']:,} exact across saves, shots against, and goals against ({goalie_aggregate['SAVES_exact_matches']/goalie_aggregate['SAVES_shared_player_games']:.6%} of shared rows); {goalie_aggregate['SAVES_value_mismatches']:,} value mismatches; {goalie_aggregate['SAVES_official_only']:,} official-only; {goalie_aggregate['SAVES_archive_only']:,} archive-only.",
        f"- Maximum side-flip share: {max_flip:.6%} at {max_flip_row['market']} line {max_flip_row['line']} in start season {max_flip_row['season']} ({max_flip_row['side_flips']}/{max_flip_row['scorable_player_games']:,}).",
    ])
    report.extend([
        "", "## Data-quality checks", "",
        f"- Official boxscore game-side rows equal the frozen frame: {len(official_games):,} rows for {len(frame):,} game IDs.",
        f"- Official team SOG sum mismatches: {sum(int(r['official_team_sog_sum_mismatches']) for r in summary_rows)} team-sides. Per-side detail: `official_team_sog_validation.csv`.",
        f"- Official boxscore score conflicts with the frozen canonical table: {len(canonical_score_conflicts)} team-sides. Detail: `official_canonical_score_conflicts.csv`.",
        f"- Official goalie rows retained in `official_goalie_outcomes.csv`: {len(official_goalies_all):,}; zero-TOI rows: {len(zero_toi):,}. Only TOI>0 official rows and archive `icetime>0` rows enter the played-game comparison. Official zero-TOI records remain available in `zero_toi_goalie_slots.csv` and raw payloads; archive zero-ice-time rows are in `archive_nonappearing_goalie_slots.csv`.",
        f"- Played-goalie one-sided rows: {goalie_aggregate['SAVES_official_only']} official-only and {goalie_aggregate['SAVES_archive_only']} archive-only. Detail with names, TOI, and all three outcomes: `played_goalie_one_sided_rows.csv`.",
        f"- Identity/source issues: {len(identity_issues):,}. Detail: `archive_identity_issues.csv`.",
        f"- Cross-source display-name review: {len(name_reviews)} player IDs, {sum(int(row['SOG_shared_rows']) for row in name_reviews)} shared SOG rows, and {sum(int(row['SAVES_shared_rows']) for row in name_reviews)} shared goalie rows. These are potential alias/spelling/ID conflicts, not automatic corrections; details are in `archive_name_crosscheck.csv`.",
        f"- Maximum SOG/Saves side-flip share over the preregistered audit lines: {max_flip:.6%}. Per line and season: `prop_side_flip_by_season.csv`.",
        "- Full discrepancy rows: `archive_sog_discrepancies.csv` and `archive_goalie_discrepancies.csv`.",
        "- Player joins use numeric NHL player IDs and canonical game IDs. No name-based fallback or silent team substitution is used.",
        "", "## Limitations", "",
        "This audit compares the historical archive with the official GameCenter boxscore snapshots retrieved for this task. It does not certify sportsbook settlement rules, stat-correction timing, or historical player-prop prices. Official boxscores alone do not provide shifts or event order for V3 simulation.",
        "",
    ])
    (args.out / "RECONCILIATION.md").write_text("\n".join(report), encoding="utf-8")
    print("RECONCILIATION_COMPLETE " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
