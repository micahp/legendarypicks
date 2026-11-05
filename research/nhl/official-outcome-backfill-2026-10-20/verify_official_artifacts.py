#!/usr/bin/env python3
"""Independently verify stored GameCenter bodies against normalized outputs."""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ARTIFACT_ROOT = Path("/root/lp-data/nhl-official-outcome-backfill-2026-10-20")
FRAME_SHA256 = "336d8a8d055febd742dbf31ce7a613bd2e47c2cd8fbc7a8d956fc8967ba47b1c"
FRAME_COUNTS = {2018: 1271, 2019: 1082, 2020: 868, 2021: 1312, 2022: 343}
TEAM_ALIASES = {"PHX": "ARI"}


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and math.isfinite(value) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def toi_seconds(value: Any) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    pieces = value.split(":")
    if len(pieces) != 2 or not all(part.isdigit() for part in pieces):
        return None
    minutes, seconds = map(int, pieces)
    return None if seconds >= 60 else minutes * 60 + seconds


def assert_rows_equal(
    label: str, actual: list[dict[str, str]], expected: dict[str, dict[str, Any]], fields: tuple[str, ...]
) -> None:
    indexed: dict[str, dict[str, str]] = {}
    for row in actual:
        key = row["record_key"]
        if key in indexed:
            raise ValueError(f"{label}: duplicate normalized record_key={key}")
        indexed[key] = row
    if set(indexed) != set(expected):
        raise ValueError(
            f"{label}: normalized row keys differ; missing={sorted(set(expected)-set(indexed))[:5]}, "
            f"extra={sorted(set(indexed)-set(expected))[:5]}"
        )
    for key, expected_row in expected.items():
        actual_row = indexed[key]
        for field in fields:
            got, want = actual_row.get(field, ""), expected_row.get(field, "")
            if str(got) != str(want):
                raise ValueError(f"{label}: {key} {field}: actual={got!r} expected={want!r}")


def main() -> int:
    frame = read_csv(HERE / "canonical_frame.csv")
    if len(frame) != 4876:
        raise ValueError(f"canonical frame rows={len(frame)}; expected 4876")
    frame.sort(key=lambda row: (int(row["season"]), int(row["game_id"])))
    digest_input = "".join(
        f"{r['season']},{r['game_id']},{r['game_date']},{r['home_team']},{r['away_team']}\n"
        for r in frame
    ).encode()
    frame_hash = sha256(digest_input)
    counts = Counter(int(row["season"]) for row in frame)
    if frame_hash != FRAME_SHA256 or dict(counts) != FRAME_COUNTS:
        raise ValueError(f"frame contract failed: sha256={frame_hash}, seasons={dict(counts)}")
    frame_by_id = {int(row["game_id"]): row for row in frame}

    manifest_path = HERE / "manifest.jsonl"
    manifest_rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line]
    manifest_by_id = {int(row["game_id"]): row for row in manifest_rows}
    if len(manifest_by_id) != len(manifest_rows) or set(manifest_by_id) != set(frame_by_id):
        raise ValueError(f"manifest frame mismatch: {len(manifest_by_id)} unique rows")

    expected_skaters: dict[str, dict[str, Any]] = {}
    expected_goalies: dict[str, dict[str, Any]] = {}
    expected_games: dict[tuple[int, str], tuple[str, int, int, str, str]] = {}
    expected_team_totals: dict[tuple[int, str], tuple[int, int, int, str]] = {}
    expected_quality_counts: Counter[str] = Counter()
    quality_by_game: dict[int, Counter[str]] = defaultdict(Counter)

    def note_issue(game_id: int, issue_type: str) -> None:
        expected_quality_counts[issue_type] += 1
        quality_by_game[game_id][issue_type] += 1

    response_count = 0
    response_source_counts: Counter[str] = Counter()
    raw_bytes_total = compressed_bytes_total = 0
    official_only_score_conflicts = []

    for game_id in sorted(frame_by_id):
        game = frame_by_id[game_id]
        entry = manifest_by_id[game_id]
        raw_path = ARTIFACT_ROOT / "raw" / f"{game_id}.json.gz"
        sidecar_path = ARTIFACT_ROOT / "records" / f"{game_id}.json"
        compressed = raw_path.read_bytes()
        body = gzip.decompress(compressed)
        payload = json.loads(body)
        raw_hash, compressed_hash = sha256(body), sha256(compressed)
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        for label, value in (("raw", raw_hash), ("compressed", compressed_hash)):
            if entry.get(f"{label}_sha256") != value or sidecar.get(f"{label}_sha256") != value:
                raise ValueError(f"game_id={game_id}: {label} hash mismatch")
        if entry.get("status") != "OK" or sidecar.get("status") != "OK":
            raise ValueError(f"game_id={game_id}: non-OK response manifest status")
        if int(payload.get("id", payload.get("gameId", -1))) != game_id:
            raise ValueError(f"game_id={game_id}: response ID mismatch")
        if str(payload.get("gameDate", ""))[:10] != game["game_date"]:
            raise ValueError(f"game_id={game_id}: response date mismatch")
        if payload.get("gameType") != 2 or str(payload.get("gameState")) not in {"OFF", "FINAL"}:
            raise ValueError(f"game_id={game_id}: not a completed regular-season response")
        if int(str(payload.get("season", "0"))[:4]) != int(game["season"]):
            raise ValueError(f"game_id={game_id}: response season mismatch")
        response_count += 1
        response_source_counts[str(entry.get("source") or "UNKNOWN")] += 1
        raw_bytes_total += len(body)
        compressed_bytes_total += len(compressed)

        for side in ("home", "away"):
            team = payload[f"{side}Team"]
            team_code = TEAM_ALIASES.get(str(team.get("abbrev", "")), str(team.get("abbrev", "")))
            if team_code != game[f"{side}_team"]:
                raise ValueError(f"game_id={game_id}: {side} team identity mismatch")
            expected_games[(game_id, side)] = (
                team_code, int(team["score"]), int(team["sog"]), raw_hash, compressed_hash
            )
            if int(team["score"]) != int(game[f"canonical_{side}_score"]):
                official_only_score_conflicts.append((game_id, side))

        all_records = []
        groups = payload["playerByGameStats"]
        for side in ("away", "home"):
            team_code = game[f"{side}_team"]
            opponent = game["home_team"] if side == "away" else game["away_team"]
            team_group = groups.get(f"{side}Team")
            if not isinstance(team_group, dict):
                raise ValueError(f"game_id={game_id}: missing {side} player group")
            team_known_sog = 0
            team_missing_sog = 0
            for group_name, market in (("forwards", "skater"), ("defense", "skater"), ("goalies", "goalie")):
                players = team_group.get(group_name)
                if not isinstance(players, list):
                    raise ValueError(f"game_id={game_id}: {side}/{group_name} is not a list")
                if not players and group_name in ("forwards", "defense"):
                    note_issue(game_id, "EMPTY_SKATER_GROUP")
                for index, player in enumerate(players):
                    key = f"{game_id}:{side}:{group_name}:{index}"
                    raw_pid = player.get("playerId")
                    pid = str(raw_pid) if isinstance(raw_pid, int) and not isinstance(raw_pid, bool) and raw_pid > 0 else ""
                    if not pid:
                        note_issue(game_id, "MISSING_OR_INVALID_PLAYER_ID")
                    raw_toi = player.get("toi")
                    seconds = toi_seconds(raw_toi)
                    if seconds is None:
                        note_issue(game_id, "INVALID_TOI")
                    player_name = player.get("name")
                    if isinstance(player_name, dict):
                        player_name = player_name.get("default") or ""
                    base = {
                        "record_key": key, "game_id": game_id, "season": int(game["season"]),
                        "game_date": game["game_date"], "team": team_code, "opponent": opponent,
                        "home_away": side, "player_id": pid, "player_name": str(player_name or ""),
                        "position": str(player.get("position") or ""), "source_group": group_name,
                        "toi": str(raw_toi or ""), "toi_seconds": "" if seconds is None else seconds,
                        "appeared": "" if seconds is None else int(seconds > 0),
                        "identity_status": "OK" if pid else "MISSING_OR_INVALID",
                    }
                    if market == "skater":
                        sog = parse_int(player.get("sog"))
                        base["sog"] = "" if sog is None else sog
                        if sog is None:
                            team_missing_sog += 1
                            note_issue(game_id, "INVALID_SOG")
                        else:
                            team_known_sog += sog
                        expected_skaters[key] = base
                    else:
                        for source, output in (("saves", "saves"), ("shotsAgainst", "shots_against"), ("goalsAgainst", "goals_against")):
                            value = parse_int(player.get(source))
                            base[output] = "" if value is None else value
                            if value is None:
                                note_issue(game_id, "INVALID_GOALIE_STAT")
                        if all(isinstance(base[field], int) for field in ("saves", "shots_against", "goals_against")):
                            if base["saves"] + base["goals_against"] != base["shots_against"]:
                                note_issue(game_id, "GOALIE_TOTAL_IDENTITY_MISMATCH")
                        base["starter"] = str(player.get("starter", ""))
                        expected_goalies[key] = base
                    all_records.append((pid, base))
            team_sog = int(payload[f"{side}Team"]["sog"])
            validation = "UNKNOWN" if team_missing_sog else ("PASS" if team_known_sog == team_sog else "MISMATCH")
            if validation != "PASS":
                note_issue(game_id, "PLAYER_SOG_SUM_VS_TEAM_TOTAL")
            expected_team_totals[(game_id, side)] = (team_sog, team_known_sog, team_missing_sog, validation)

        duplicates = Counter(pid for pid, _row in all_records if pid)
        for pid, count in duplicates.items():
            if count > 1:
                note_issue(game_id, "DUPLICATE_PLAYER_ID_WITHIN_GAME")
                for row_pid, row in all_records:
                    if row_pid == pid:
                        row["identity_status"] = "CONFLICT_DUPLICATE_ID"

    games = read_csv(HERE / "official_game_sides.csv")
    if len(games) != 2 * len(frame):
        raise ValueError(f"official game side rows={len(games)}; expected {2*len(frame)}")
    seen_game_sides = set()
    score_conflicts_from_file = []
    for row in games:
        key = (int(row["game_id"]), row["side"])
        if key in seen_game_sides or key not in expected_games:
            raise ValueError(f"duplicate or extra official game-side row {key}")
        seen_game_sides.add(key)
        team, score, sog, raw_hash, compressed_hash = expected_games[key]
        observed = (row["team"], int(row["score"]), int(row["team_sog"]), row["raw_sha256"], row["compressed_sha256"])
        if observed != (team, score, sog, raw_hash, compressed_hash):
            raise ValueError(f"official game-side normalized row mismatch {key}")
        game = frame_by_id[key[0]]
        if score != int(game[f"canonical_{key[1]}_score"]):
            score_conflicts_from_file.append(key)

    skater_fields = ("season", "game_id", "game_date", "team", "opponent", "home_away", "player_id", "player_name", "position", "source_group", "toi", "toi_seconds", "appeared", "identity_status", "sog")
    goalie_fields = ("season", "game_id", "game_date", "team", "opponent", "home_away", "player_id", "player_name", "position", "source_group", "toi", "toi_seconds", "appeared", "identity_status", "saves", "shots_against", "goals_against", "starter")
    skaters = read_csv(HERE / "official_skater_outcomes.csv")
    goalies = read_csv(HERE / "official_goalie_outcomes.csv")
    assert_rows_equal("skater outcomes", skaters, expected_skaters, skater_fields)
    assert_rows_equal("goalie outcomes", goalies, expected_goalies, goalie_fields)

    totals = read_csv(HERE / "official_team_sog_validation.csv")
    if len(totals) != 2 * len(frame):
        raise ValueError("official team SOG validation does not contain two sides per game")
    seen_totals = set()
    for row in totals:
        key = (int(row["game_id"]), row["side"])
        if key in seen_totals or key not in expected_team_totals:
            raise ValueError(f"duplicate or extra team SOG row {key}")
        seen_totals.add(key)
        expected = expected_team_totals[key]
        observed = (int(row["official_team_sog"]), int(row["sum_player_sog"]), int(row["missing_or_invalid_player_sog_rows"]), row["validation"])
        if observed != expected:
            raise ValueError(f"team SOG sum mismatch {key}: {observed} != {expected}")

    quality = read_csv(HERE / "official_quality_issues.csv")
    actual_quality_counts = Counter(row["issue_type"] for row in quality)
    if actual_quality_counts != expected_quality_counts:
        raise ValueError(
            f"quality issue counts differ: normalized={dict(actual_quality_counts)}, "
            f"raw_recomputed={dict(expected_quality_counts)}"
        )

    coverage = json.loads((HERE / "official_coverage_summary.json").read_text(encoding="utf-8"))
    canonical_season_counts = Counter(int(row["season"]) for row in frame)
    sbr_season_counts = Counter(
        int(row["season"]) for row in frame if row["in_sbr_market_archive"] == "1"
    )
    canonical_date_ranges = {
        str(season): [
            min(row["game_date"] for row in frame if int(row["season"]) == season),
            max(row["game_date"] for row in frame if int(row["season"]) == season),
        ] for season in sorted(canonical_season_counts)
    }
    sbr_date_ranges = {
        str(season): [
            min(row["game_date"] for row in frame if int(row["season"]) == season and row["in_sbr_market_archive"] == "1"),
            max(row["game_date"] for row in frame if int(row["season"]) == season and row["in_sbr_market_archive"] == "1"),
        ] for season in sorted(sbr_season_counts)
    }
    expected_coverage = {
        "frame_games": len(frame), "official_game_ids": response_count,
        "official_team_rows": len(games), "skater_rows": len(skaters),
        "skater_appearances": sum(row["appeared"] == "1" for row in skaters),
        "skater_zero_toi_slots": sum(row["appeared"] == "0" for row in skaters),
        "skater_unknown_toi_rows": sum(row["appeared"] == "" for row in skaters),
        "goalie_rows_including_zero_toi": len(goalies),
        "zero_toi_goalie_slots": sum(row["appeared"] == "0" for row in goalies),
        "quality_issue_count": len(quality),
        "identity_issue_count": expected_quality_counts["MISSING_OR_INVALID_PLAYER_ID"] + expected_quality_counts["DUPLICATE_PLAYER_ID_WITHIN_GAME"],
        "goalie_arithmetic_failures": expected_quality_counts["GOALIE_TOTAL_IDENTITY_MISMATCH"],
        "response_source_counts": dict(response_source_counts),
        "canonical_season_counts": {str(k): canonical_season_counts[k] for k in sorted(canonical_season_counts)},
        "sbr_market_season_counts": {str(k): sbr_season_counts[k] for k in sorted(canonical_season_counts)},
        "canonical_season_date_ranges": canonical_date_ranges,
        "sbr_market_season_date_ranges": sbr_date_ranges,
    }
    for field, value in expected_coverage.items():
        if coverage.get(field) != value:
            raise ValueError(f"coverage summary {field}={coverage.get(field)!r}; expected {value!r}")
    if coverage.get("team_sog_sum_validation") != dict(Counter(row["validation"] for row in totals)):
        raise ValueError("coverage team SOG summary differs from validated side rows")
    if coverage.get("quality_issue_counts_by_type") != dict(actual_quality_counts):
        raise ValueError("coverage quality-issue type counts differ from the issue table")

    season_coverage = coverage.get("season_coverage")
    if not isinstance(season_coverage, dict):
        raise ValueError("coverage report lacks per-season coverage rows")
    for season in sorted({int(row["season"]) for row in frame}):
        season_games = {int(row["game_id"]) for row in frame if int(row["season"]) == season}
        season_skaters = [row for row in skaters if int(row["season"]) == season]
        season_goalies = [row for row in goalies if int(row["season"]) == season]
        season_game_rows = [row for row in games if int(row["season"]) == season]
        season_totals = [row for row in totals if int(row["game_id"]) in season_games]
        season_quality_counts = Counter()
        for gid in season_games:
            season_quality_counts.update(quality_by_game[gid])
        expected_season = {
            "games": len(season_games),
            "official_team_rows": len(season_game_rows),
            "skater_rows": len(season_skaters),
            "skater_appearances": sum(row["appeared"] == "1" for row in season_skaters),
            "skater_zero_toi_slots": sum(row["appeared"] == "0" for row in season_skaters),
            "skater_unknown_toi_rows": sum(row["appeared"] == "" for row in season_skaters),
            "goalie_rows_including_zero_toi": len(season_goalies),
            "goalie_appearances": sum(row["appeared"] == "1" for row in season_goalies),
            "zero_toi_goalie_slots": sum(row["appeared"] == "0" for row in season_goalies),
            "team_sog_sum_validation": dict(Counter(row["validation"] for row in season_totals)),
            "goalie_arithmetic_failures": season_quality_counts["GOALIE_TOTAL_IDENTITY_MISMATCH"],
            "identity_issue_count": season_quality_counts["MISSING_OR_INVALID_PLAYER_ID"] + season_quality_counts["DUPLICATE_PLAYER_ID_WITHIN_GAME"],
            "quality_issue_count": sum(season_quality_counts.values()),
        }
        if season_coverage.get(str(season)) != expected_season:
            raise ValueError(f"season {season} coverage differs: {season_coverage.get(str(season))} != {expected_season}")

    manifest_hash = sha256(manifest_path.read_bytes())
    result = {
        "verified_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "frame_games": len(frame), "manifest_entries": len(manifest_rows),
        "raw_responses_verified": response_count,
        "raw_bytes_total": raw_bytes_total, "compressed_bytes_total": compressed_bytes_total,
        "response_source_counts": dict(response_source_counts),
        "manifest_sha256": manifest_hash,
        "skater_rows_verified": len(skaters), "goalie_rows_verified_including_zero_toi": len(goalies),
        "official_team_sog_rows_verified": len(totals),
        "quality_issue_rows_verified": len(quality),
        "canonical_score_conflict_team_sides": len(score_conflicts_from_file),
        "canonical_score_conflict_ids": sorted({gid for gid, _side in score_conflicts_from_file}),
        "result": "PASS",
    }
    (HERE / "artifact_verification.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("ARTIFACT_VERIFY_PASS " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
