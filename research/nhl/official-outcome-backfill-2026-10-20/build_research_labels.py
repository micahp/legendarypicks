#!/usr/bin/env python3
"""Build field-level NHL research-label quality outputs from pinned evidence.

Only the new adjudication outputs are writable. Original backfill artifacts and
all source response bodies are treated as immutable inputs.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import gzip
import hashlib
import html
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from nhl_research_data import iter_nhl_research_labels
from nhl_sog_validation import parse_pbp_sog_events


DEFAULT_EVIDENCE_ROOT = Path("/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20")
DEFAULT_BACKFILL_ROOT = Path("/root/lp-data/nhl-official-outcome-backfill-2026-10-20")
DEFAULT_LABEL_OUTPUT = Path("/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20/research_label_quality.csv")
PIN_FILE = "research_label_source_pins.json"
PIN_FILE_SHA256 = "0f64e178942471ed9003082c4ba914861bf0a8d4eef693ba639b898db61bc230"
BASE_COMMIT = "c91ae36c39b57f86c7c839a2e424eec3ee9330a0"
TEAM_ALIASES = {"PHX": "ARI"}
STAT_FIELDS = {
    "SOG": "sog",
    "SAVES": "saves",
    "SHOTS_AGAINST": "shots_against",
    "GOALS_AGAINST": "goals_against",
}
OUTPUT_NAMES = (
    "sog_event_reconciliation.csv",
    "goalie_event_reconciliation.csv",
    "adjudication_ledger.csv",
    "research_label_quality.csv",
    "research_label_summary.json",
)


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_blob(body: bytes, expected: str, label: str) -> None:
    actual = sha256_bytes(body)
    if actual != expected:
        raise ValueError(f"SOURCE_HASH_MISMATCH {label}: expected={expected} actual={actual}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def canonical_player_id(value: Any, label: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"INVALID_NUMERIC_NHL_PLAYER_ID {label}: {value!r}")
    value = str(value or "")
    if not value.isdigit() or int(value) <= 0:
        raise ValueError(f"INVALID_NUMERIC_NHL_PLAYER_ID {label}: {value!r}")
    return value


def verify_source_pins(artifact_dir: Path, evidence_root: Path) -> dict[str, Any]:
    pin_path = artifact_dir / PIN_FILE
    pin_bytes = pin_path.read_bytes()
    verify_blob(pin_bytes, PIN_FILE_SHA256, PIN_FILE)
    pins = json.loads(pin_bytes)
    if pins.get("base_commit") != BASE_COMMIT:
        raise ValueError(f"PINNED_BASE_MISMATCH {pins.get('base_commit')!r}")
    for name, expected in pins["source_files"].items():
        path = artifact_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"PINNED_SOURCE_MISSING {path}")
        verify_blob(path.read_bytes(), expected, name)
    for relative, expected in pins["external_evidence"].items():
        path = evidence_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"PINNED_EVIDENCE_MISSING {path}")
        verify_blob(path.read_bytes(), expected, relative)
    return pins


def read_manifest(path: Path, key: str = "game_id") -> dict[str, dict[str, str]]:
    rows = read_csv(path)
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        ident = str(row[key])
        if ident in result:
            raise ValueError(f"DUPLICATE_MANIFEST_KEY {path.name} {ident}")
        result[ident] = row
    return result


def verify_json_evidence(
    manifest: dict[str, dict[str, str]],
    game_id: str,
    evidence_root: Path,
    category: str,
    expected_url_prefix: str,
) -> tuple[dict[str, str], bytes, Any]:
    if game_id not in manifest:
        raise ValueError(f"EVIDENCE_MANIFEST_MISSING {category} game={game_id}")
    row = manifest[game_id]
    source_url = row.get("source_url", "")
    if row.get("http_status") != "200" or not source_url.startswith(expected_url_prefix):
        raise ValueError(f"EVIDENCE_SOURCE_INVALID {category} game={game_id}: {row}")
    if category == "play-by-play" and source_url != f"{expected_url_prefix}{game_id}/play-by-play":
        raise ValueError(f"EVIDENCE_URL_GAME_MISMATCH {category} game={game_id}: {source_url}")
    if category == "goalie-stats":
        parsed_url = urlsplit(source_url)
        query = parse_qs(parsed_url.query)
        if (
            parsed_url.path != "/stats/rest/en/goalie/summary"
            or query.get("cayenneExp") != [f"gameId={game_id}"]
            or query.get("isAggregate") != ["false"]
            or query.get("isGame") != ["true"]
        ):
            raise ValueError(f"EVIDENCE_URL_GAME_MISMATCH {category} game={game_id}: {source_url}")
    path = evidence_root / category / row["cache_file"]
    body = path.read_bytes()
    verify_blob(body, row["sha256"], f"{category}/{path.name}")
    if int(row["bytes"]) != len(body):
        raise ValueError(f"EVIDENCE_LENGTH_MISMATCH {category} game={game_id}")
    return row, body, json.loads(body)


def verify_html_evidence(
    manifest: dict[str, dict[str, str]], game_id: str, evidence_root: Path
) -> tuple[dict[str, str], str]:
    if game_id not in manifest:
        raise ValueError(f"EVIDENCE_MANIFEST_MISSING game_summary game={game_id}")
    row = manifest[game_id]
    expected_url = f"https://www.nhl.com/scores/htmlreports/20222023/GS{game_id[-6:]}.HTM"
    if row.get("http_status") != "200" or row.get("source_url") != expected_url:
        raise ValueError(f"EVIDENCE_SOURCE_INVALID game_summary game={game_id}")
    body = (evidence_root / "game-summaries" / row["cache_file"]).read_bytes()
    verify_blob(body, row["sha256"], f"game-summaries/{row['cache_file']}")
    if int(row["bytes"]) != len(body):
        raise ValueError(f"EVIDENCE_LENGTH_MISMATCH game_summary game={game_id}")
    text = html.unescape(re.sub(r"<[^>]*>", " ", body.decode("utf-8")))
    normalized = " ".join(text.upper().split())
    if row["confirmed_goalie"] not in normalized or row["confirmed_goalie_line"] not in normalized:
        raise ValueError(f"GAME_SUMMARY_CONTENT_MISMATCH game={game_id}")
    return row, normalized


def manifest_by_game(path: Path) -> dict[int, dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    result = {int(row["game_id"]): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("ORIGINAL_GAMECENTER_MANIFEST_DUPLICATE_GAME_ID")
    return result


def verify_original_game(
    game_id: str,
    original_manifest: dict[int, dict[str, Any]],
    backfill_root: Path,
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    gid = int(game_id)
    if gid not in original_manifest:
        raise ValueError(f"ORIGINAL_MANIFEST_GAME_MISSING {game_id}")
    entry = original_manifest[gid]
    compressed_path = backfill_root / "raw" / f"{game_id}.json.gz"
    compressed = compressed_path.read_bytes()
    verify_blob(compressed, entry["compressed_sha256"], f"original-compressed/{game_id}")
    body = gzip.decompress(compressed)
    verify_blob(body, entry["raw_sha256"], f"original-raw/{game_id}")
    payload = json.loads(body)
    if int(payload.get("id", -1)) != gid:
        raise ValueError(f"ORIGINAL_GAME_ID_MISMATCH {game_id}")
    return entry, body, payload


def verify_original_corpus_hashes(
    original_manifest: dict[int, dict[str, Any]],
    frame_game_ids: set[str],
    backfill_root: Path,
) -> None:
    if {str(game_id) for game_id in original_manifest} != frame_game_ids:
        raise ValueError("ORIGINAL_MANIFEST_CANONICAL_FRAME_MISMATCH")
    for game_id in sorted(original_manifest):
        entry = original_manifest[game_id]
        compressed = (backfill_root / "raw" / f"{game_id}.json.gz").read_bytes()
        verify_blob(compressed, entry["compressed_sha256"], f"original-compressed/{game_id}")
        body = gzip.decompress(compressed)
        verify_blob(body, entry["raw_sha256"], f"original-raw/{game_id}")
        payload = json.loads(body)
        if int(payload.get("id", -1)) != game_id:
            raise ValueError(f"ORIGINAL_GAME_ID_MISMATCH {game_id}")


def integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"INVALID_INTEGER {label}={value!r}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"INVALID_INTEGER {label}={value!r}") from exc
    if str(parsed) != str(value).strip() and not isinstance(value, int):
        raise ValueError(f"NON_CANONICAL_INTEGER {label}={value!r}")
    return parsed


def usable_status(status: str) -> bool:
    return status in {"VERIFIED", "ADJUDICATED"}


def build_outputs(
    artifact_dir: Path = HERE,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    backfill_root: Path = DEFAULT_BACKFILL_ROOT,
    label_output_path: Path = DEFAULT_LABEL_OUTPUT,
) -> dict[str, bytes]:
    pins = verify_source_pins(artifact_dir, evidence_root)
    frame = read_csv(artifact_dir / "canonical_frame.csv")
    if len(frame) != 4876:
        raise ValueError(f"CANONICAL_FRAME_COUNT {len(frame)} != 4876")
    sbr_games = sum(row["in_sbr_market_archive"] == "1" for row in frame)
    if sbr_games != 4872:
        raise ValueError(f"SBR_FRAME_COUNT {sbr_games} != 4872")
    frame_by_id = {row["game_id"]: row for row in frame}
    if len(frame_by_id) != len(frame):
        raise ValueError("CANONICAL_FRAME_DUPLICATE_GAME_ID")

    issues = read_csv(artifact_dir / "official_quality_issues.csv")
    sog_issues = [row for row in issues if row["issue_type"] == "PLAYER_SOG_SUM_VS_TEAM_TOTAL"]
    goalie_issues = [row for row in issues if row["issue_type"] == "GOALIE_TOTAL_IDENTITY_MISMATCH"]
    if len(issues) != 22 or len(sog_issues) != 20 or len(goalie_issues) != 2:
        raise ValueError(f"ORIGINAL_ISSUE_FRAME_MISMATCH total={len(issues)} sog={len(sog_issues)} goalie={len(goalie_issues)}")
    issue_sides = {(row["game_id"], row["team"]): row for row in sog_issues}
    goalie_issue_by_key = {(row["game_id"], row["player_id"]): row for row in goalie_issues}
    target_games = {row["game_id"] for row in issues}

    official_sides_rows = read_csv(artifact_dir / "official_game_sides.csv")
    official_sides = {(row["game_id"], row["side"]): row for row in official_sides_rows}
    if len(official_sides) != 9752:
        raise ValueError(f"OFFICIAL_GAME_SIDE_COUNT {len(official_sides)} != 9752")
    team_validation_rows = read_csv(artifact_dir / "official_team_sog_validation.csv")
    team_validation = {(row["game_id"], row["team"]): row for row in team_validation_rows}
    if len(team_validation) != 9752:
        raise ValueError(f"TEAM_SOG_VALIDATION_COUNT {len(team_validation)} != 9752")

    skater_rows = read_csv(artifact_dir / "official_skater_outcomes.csv")
    goalie_rows = read_csv(artifact_dir / "official_goalie_outcomes.csv")
    skaters_by_game_team: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    skater_by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in skater_rows:
        key = (row["game_id"], row["team"], row["player_id"])
        if key in skater_by_key:
            raise ValueError(f"DUPLICATE_SKATER_GAME_PLAYER_ID {key}")
        skater_by_key[key] = row
        skaters_by_game_team[(row["game_id"], row["team"])].append(row)
    goalie_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in goalie_rows:
        key = (row["game_id"], row["player_id"])
        if key in goalie_by_key:
            raise ValueError(f"DUPLICATE_GOALIE_GAME_PLAYER_ID {key}")
        goalie_by_key[key] = row
    if len(skater_rows) != 175490 or len(goalie_rows) != 19506:
        raise ValueError(f"PLAYER_OUTCOME_ROW_COUNTS skater={len(skater_rows)} goalie={len(goalie_rows)}")

    original_manifest = manifest_by_game(artifact_dir / "manifest.jsonl")
    verify_original_corpus_hashes(original_manifest, set(frame_by_id), backfill_root)
    original_entries = {str(game_id): entry for game_id, entry in original_manifest.items()}
    pbp_manifest = read_manifest(artifact_dir / "play_by_play_evidence_manifest.csv")
    stats_manifest = read_manifest(artifact_dir / "goalie_stats_evidence_manifest.csv")
    summary_manifest = read_manifest(artifact_dir / "game_summary_evidence_manifest.csv")
    if set(pbp_manifest) != target_games or set(stats_manifest) != {row["game_id"] for row in goalie_issues} or set(summary_manifest) != {row["game_id"] for row in goalie_issues}:
        raise ValueError("EVIDENCE_MANIFEST_POPULATION_MISMATCH")

    pbp_by_game: dict[str, dict[str, Any]] = {}
    pbp_meta_by_game: dict[str, dict[str, str]] = {}
    pbp_body_by_game: dict[str, bytes] = {}
    original_payloads: dict[str, dict[str, Any]] = {}
    sog_events_by_game: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = {}
    no_shot_goals_by_game: dict[str, list[dict[str, Any]]] = {}

    for game_id in sorted(target_games, key=int):
        original_entry, _original_body, original = verify_original_game(game_id, original_manifest, backfill_root)
        original_entries[game_id] = original_entry
        original_payloads[game_id] = original
        pbp_meta, pbp_body, pbp = verify_json_evidence(
            pbp_manifest, game_id, evidence_root, "play-by-play", "https://api-web.nhle.com/v1/gamecenter/"
        )
        if int(pbp.get("id", -1)) != int(game_id) or pbp.get("gameType") != 2 or pbp.get("gameState") not in {"OFF", "FINAL"}:
            raise ValueError(f"PBP_GAME_IDENTITY_OR_STATE {game_id}")
        if pbp.get("gameDate", "")[:10] != frame_by_id[game_id]["game_date"]:
            raise ValueError(f"PBP_GAME_DATE_MISMATCH {game_id}")
        pbp_by_game[game_id] = pbp
        pbp_meta_by_game[game_id] = pbp_meta
        pbp_body_by_game[game_id] = pbp_body

        parsed_pbp = parse_pbp_sog_events(game_id, pbp, TEAM_ALIASES)
        team_ids = parsed_pbp.team_ids
        for side in ("home", "away"):
            pbp_team = pbp[f"{side}Team"]
            team_code = TEAM_ALIASES.get(str(pbp_team.get("abbrev", "")), str(pbp_team.get("abbrev", "")))
            source_team = original[f"{side}Team"]
            if team_code != frame_by_id[game_id][f"{side}_team"] or team_code != TEAM_ALIASES.get(str(source_team.get("abbrev", "")), str(source_team.get("abbrev", ""))):
                raise ValueError(f"PBP_TEAM_IDENTITY_MISMATCH {game_id}/{side}/{team_code}")
        roster_by_id = parsed_pbp.roster_by_id
        by_player: dict[tuple[str, str], list[dict[str, Any]]] = {
            key: list(events) for key, events in parsed_pbp.events_by_team_side.items()
        }
        no_shot_goals = list(parsed_pbp.no_shot_goals)
        sog_events_by_game[game_id] = by_player
        no_shot_goals_by_game[game_id] = no_shot_goals

        for side in ("home", "away"):
            official_side = official_sides[(game_id, side)]
            team = official_side["team"]
            events = [event for (event_team, event_side), values in by_player.items() if event_team == team and event_side == side for event in values]
            event_total = len(events)
            official_team_sog = integer(official_side["team_sog"], f"official team SOG {game_id}/{side}")
            pbp_reported_sog = integer(pbp[f"{side}Team"]["sog"], f"PBP team SOG {game_id}/{side}")
            if event_total != official_team_sog or pbp_reported_sog != official_team_sog:
                raise ValueError(
                    f"PBP_TEAM_SOG_RECONCILIATION_FAILED {game_id}/{side}: events={event_total} "
                    f"official={official_team_sog} PBP_summary={pbp_reported_sog}"
                )

        # The pinned original GameCenter payload independently reconstructs each
        # originally flagged skater/team sum. No name join participates.
        original_groups = original.get("playerByGameStats", {})
        for (issue_game, team), issue in issue_sides.items():
            if issue_game != game_id:
                continue
            side = issue["side"]
            raw_side = original_groups.get(f"{side}Team", {})
            raw_team = original[f"{side}Team"]
            raw_skater_counts: dict[str, int] = {}
            for group_name in ("forwards", "defense"):
                group = raw_side.get(group_name)
                if not isinstance(group, list):
                    raise ValueError(f"ORIGINAL_SKATER_GROUP_MISSING {game_id}/{side}/{group_name}")
                for player in group:
                    pid = canonical_player_id(player.get("playerId"), f"original skater {game_id}/{side}")
                    if pid in raw_skater_counts:
                        raise ValueError(f"ORIGINAL_SKATER_DUPLICATE_ID {game_id}/{pid}")
                    raw_skater_counts[pid] = integer(player.get("sog"), f"original SOG {game_id}/{pid}")
            normalized_players = skaters_by_game_team[(game_id, team)]
            normalized_by_id = {canonical_player_id(row["player_id"], f"normalized skater {game_id}"): integer(row["sog"], f"normalized SOG {game_id}") for row in normalized_players}
            if normalized_by_id != raw_skater_counts:
                raise ValueError(f"NORMALIZED_VS_RAW_SKATER_ROWS_DIFFER {game_id}/{side}")
            event_by_id: Counter[str] = Counter(event["player_id"] for event in by_player[(team, side)])
            mismatches = {pid: (value, event_by_id[pid]) for pid, value in raw_skater_counts.items() if value != event_by_id[pid]}
            extra_ids = {pid: n for pid, n in event_by_id.items() if pid not in raw_skater_counts}
            raw_sum = sum(raw_skater_counts.values())
            team_sog = integer(raw_team["sog"], f"raw team SOG {game_id}/{side}")
            if mismatches or len(extra_ids) != 1 or list(extra_ids.values()) != [1] or team_sog - raw_sum != 1:
                raise ValueError(f"SOG_ISSUE_NOT_EXPLAINED_BY_ONE_EVENT {game_id}/{side}: {mismatches} {extra_ids}")
            extra_id = next(iter(extra_ids))
            goalie_events = [e for e in by_player[(team, side)] if e["player_id"] == extra_id]
            roster_item = roster_by_id.get(extra_id)
            goalie_outcome = goalie_by_key.get((game_id, extra_id))
            expected_nhl_team_id = original[f"{side}Team"].get("id")
            if (
                len(goalie_events) != 1
                or not (
                    goalie_events[0]["event_type"] == "shot-on-goal"
                    or (
                        goalie_events[0]["event_type"] == "goal"
                        and goalie_events[0]["details"].get("shotType")
                    )
                )
                or not roster_item
                or roster_item.get("positionCode") != "G"
                or roster_item.get("teamId") != expected_nhl_team_id
                or not goalie_outcome
                or goalie_outcome["team"] != team
                or goalie_outcome["appeared"] != "1"
                or int(goalie_outcome["toi_seconds"]) <= 0
            ):
                raise ValueError(f"EXTRA_SOG_NOT_CONFIRMED_AS_PLAYED_TEAM_GOALIE {game_id}/{side}/{extra_id}")

    sog_event_rows, sog_event_index = build_sog_event_rows(
        sog_issues, skaters_by_game_team, sog_events_by_game, pbp_meta_by_game, goalie_by_key,
        pbp_by_game, official_sides, frame_by_id,
    )
    goalie_event_rows, goalie_evidence = build_goalie_event_rows(
        goalie_issues, goalie_by_key, pbp_by_game, pbp_meta_by_game, sog_events_by_game,
        no_shot_goals_by_game, stats_manifest, summary_manifest, evidence_root, official_sides,
    )
    ledger_rows = build_ledger_rows(
        sog_issues, goalie_issues, goalie_evidence, sog_event_index, frame_by_id,
        official_sides, pbp_meta_by_game, stats_manifest, summary_manifest, original_entries,
    )
    quality_rows = build_quality_rows(
        skater_rows, goalie_rows, issue_sides, sog_event_index, goalie_evidence,
        original_entries, pbp_meta_by_game,
    )
    summary = build_summary(quality_rows, issues, frame, pins, sog_event_rows, goalie_event_rows)

    outputs = {
        "sog_event_reconciliation.csv": write_csv(sog_event_rows, SOG_EVENT_COLUMNS),
        "goalie_event_reconciliation.csv": write_csv(goalie_event_rows, GOALIE_EVENT_COLUMNS),
        "adjudication_ledger.csv": write_csv(ledger_rows, LEDGER_COLUMNS),
        "research_label_quality.csv": write_csv(quality_rows, QUALITY_COLUMNS),
    }
    summary["derived_output_sha256"] = {name: sha256_bytes(outputs[name]) for name in sorted(outputs)}
    summary["label_artifact"] = {
        "filename": "research_label_quality.csv",
        "bytes": len(outputs["research_label_quality.csv"]),
        "sha256": summary["derived_output_sha256"]["research_label_quality.csv"],
        "storage_path": str(label_output_path),
        "git_tracked": False,
    }
    outputs["research_label_summary.json"] = (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return outputs


SOG_EVENT_COLUMNS = (
    "adjudication_id", "game_id", "season", "game_date", "side", "team", "player_id",
    "player_class", "player_name", "official_sog", "pbp_sog_event_count", "pbp_event_ids_json",
    "pbp_event_types_json", "player_count_match", "team_sum_before", "team_sog_official",
    "goalie_sog_addition", "quality_status", "reason_code", "source_url", "retrieved_at_utc",
    "source_sha256",
)

GOALIE_EVENT_COLUMNS = (
    "adjudication_id", "game_id", "season", "game_date", "team", "opponent", "player_id",
    "player_name", "toi_seconds", "game_outcome_last_period", "official_saves", "official_shots_against",
    "official_goals_against", "stats_rest_saves", "stats_rest_shots_against", "stats_rest_goals_against",
    "pbp_non_goal_shot_events", "pbp_goal_events", "pbp_goal_events_with_shot_type",
    "pbp_goal_events_without_shot_type", "pbp_counted_shots_against", "pbp_team_sog",
    "game_summary_goalie_line", "accepted_saves", "accepted_shots_against", "accepted_goals_against",
    "quality_status", "reason_code", "pbp_source_url", "pbp_retrieved_at_utc", "pbp_sha256",
    "stats_rest_source_url", "stats_rest_retrieved_at_utc", "stats_rest_sha256",
    "game_summary_source_url", "game_summary_retrieved_at_utc", "game_summary_sha256",
)

LEDGER_COLUMNS = (
    "ledger_id", "row_type", "source_issue_id", "game_id", "game_date", "season", "team", "side",
    "player_id", "statistic", "original_official_value", "independent_evidence_value", "corrected_value",
    "quality_status", "reason_code", "reason", "source_url", "retrieved_at_utc", "source_sha256",
    "corroborating_source_url", "corroborating_retrieved_at_utc", "corroborating_sha256",
    "eligible_training", "eligible_evaluation", "eligible_grading",
)

QUALITY_COLUMNS = (
    "label_id", "record_key", "game_id", "season", "game_date", "team", "opponent", "home_away",
    "player_id", "statistic", "official_value", "accepted_value", "corrected_value", "quality_status",
    "reason_code", "reason", "adjudication_id", "source_issue_id", "original_gamecenter_raw_sha256",
    "independent_evidence_url", "independent_evidence_sha256", "eligible_training",
    "eligible_evaluation", "eligible_grading",
)


def index_player_events(events: dict[tuple[str, str], list[dict[str, Any]]], game_id: str, team: str, side: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events[(team, side)]:
        grouped[event["player_id"]].append(event)
    for values in grouped.values():
        values.sort(key=lambda item: (item["sort_order"], item["event_id"]))
    return grouped


def build_sog_event_rows(
    issues: list[dict[str, str]],
    skaters_by_game_team: dict[tuple[str, str], list[dict[str, str]]],
    events_by_game: dict[str, dict[tuple[str, str], list[dict[str, Any]]]],
    pbp_meta: dict[str, dict[str, str]],
    goalie_by_key: dict[tuple[str, str], dict[str, str]],
    pbp_by_game: dict[str, dict[str, Any]],
    official_sides: dict[tuple[str, str], dict[str, str]],
    frame_by_id: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    output: list[dict[str, Any]] = []
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for issue in sorted(issues, key=lambda row: (int(row["game_id"]), row["side"])):
        game_id, team, side = issue["game_id"], issue["team"], issue["side"]
        grouped = index_player_events(events_by_game[game_id], game_id, team, side)
        skaters = skaters_by_game_team[(game_id, team)]
        raw_team_sum = sum(integer(row["sog"], f"skater SOG {game_id}/{row['player_id']}") for row in skaters)
        official_total = integer(official_sides[(game_id, side)]["team_sog"], f"team SOG {game_id}/{side}")
        goalie_id = next(pid for pid in grouped if pid not in {row["player_id"] for row in skaters})
        goalie = goalie_by_key[(game_id, goalie_id)]
        extra_event = grouped[goalie_id][0]
        base = {
            "adjudication_id": f"SOG-{game_id}-{side}",
            "game_id": game_id,
            "season": frame_by_id[game_id]["season"],
            "game_date": frame_by_id[game_id]["game_date"],
            "side": side,
            "team": team,
        }
        source_issue_id = f"{game_id}:{side}:{team}:PLAYER_SOG_SUM_VS_TEAM_TOTAL"
        for row in sorted(skaters, key=lambda item: int(item["player_id"])):
            pid = canonical_player_id(row["player_id"], f"SOG output {game_id}")
            player_events = grouped.get(pid, [])
            count = len(player_events)
            if count != integer(row["sog"], f"boxscore SOG {game_id}/{pid}"):
                raise ValueError(f"SOG_PER_PLAYER_PBP_MISMATCH {game_id}/{pid}")
            event_ids = [event["event_id"] for event in player_events]
            output.append({
                **base,
                "player_id": pid,
                "player_class": "SKATER",
                "player_name": row["player_name"],
                "official_sog": row["sog"],
                "pbp_sog_event_count": count,
                "pbp_event_ids_json": json.dumps(event_ids, separators=(",", ":")),
                "pbp_event_types_json": json.dumps([event["event_type"] for event in player_events], separators=(",", ":")),
                "player_count_match": "true",
                "team_sum_before": raw_team_sum,
                "team_sog_official": official_total,
                "goalie_sog_addition": "",
                "quality_status": "ADJUDICATED",
                "reason_code": "SKATER_EVENT_COUNT_CONFIRMED",
                "source_url": pbp_meta[game_id]["source_url"],
                "retrieved_at_utc": pbp_meta[game_id]["retrieved_at_utc"],
                "source_sha256": pbp_meta[game_id]["sha256"],
            })
            index[(game_id, team, pid)] = {
                "status": "ADJUDICATED",
                "reason_code": "SKATER_EVENT_COUNT_CONFIRMED",
                "reason": "NHL PBP shot events for this numeric player ID exactly match the original official SOG value.",
                "adjudication_id": base["adjudication_id"],
                "source_issue_id": source_issue_id,
                "source_url": pbp_meta[game_id]["source_url"],
                "retrieved_at_utc": pbp_meta[game_id]["retrieved_at_utc"],
                "source_sha256": pbp_meta[game_id]["sha256"],
            }
        if len(grouped[goalie_id]) != 1 or not (
            extra_event["event_type"] == "shot-on-goal"
            or (extra_event["event_type"] == "goal" and extra_event["details"].get("shotType"))
        ):
            raise ValueError(f"EXPECTED_ONE_GOALIE_SOG_EVENT {game_id}/{goalie_id}")
        output.append({
            **base,
            "player_id": goalie_id,
            "player_class": "GOALIE",
            "player_name": goalie["player_name"],
            "official_sog": "",
            "pbp_sog_event_count": 1,
            "pbp_event_ids_json": json.dumps([extra_event["event_id"]], separators=(",", ":")),
            "pbp_event_types_json": json.dumps([extra_event["event_type"]], separators=(",", ":")),
            "player_count_match": "N/A_SKATER_STAT_NOT_PUBLISHED",
            "team_sum_before": raw_team_sum,
            "team_sog_official": official_total,
            "goalie_sog_addition": 1,
            "quality_status": "ADJUDICATED",
            "reason_code": "TEAM_TOTAL_INCLUDES_GOALIE_SOG",
            "source_url": pbp_meta[game_id]["source_url"],
            "retrieved_at_utc": pbp_meta[game_id]["retrieved_at_utc"],
            "source_sha256": pbp_meta[game_id]["sha256"],
        })
        index[(game_id, team, goalie_id)] = {
            "status": "ADJUDICATED",
            "reason_code": "TEAM_TOTAL_INCLUDES_GOALIE_SOG",
            "reason": "One official PBP SOG event belongs to a played goalie and is included in team SOG but not the skater outcome group.",
            "adjudication_id": base["adjudication_id"],
            "source_issue_id": source_issue_id,
            "player_id": goalie_id,
            "event_ids": [extra_event["event_id"]],
            "source_url": pbp_meta[game_id]["source_url"],
            "retrieved_at_utc": pbp_meta[game_id]["retrieved_at_utc"],
            "source_sha256": pbp_meta[game_id]["sha256"],
        }
    return output, index


def build_goalie_event_rows(
    issues: list[dict[str, str]],
    goalie_by_key: dict[tuple[str, str], dict[str, str]],
    pbp_by_game: dict[str, dict[str, Any]],
    pbp_meta: dict[str, dict[str, str]],
    sog_events_by_game: dict[str, dict[tuple[str, str], list[dict[str, Any]]]],
    no_shot_goals_by_game: dict[str, list[dict[str, Any]]],
    stats_manifest: dict[str, dict[str, str]],
    summary_manifest: dict[str, dict[str, str]],
    evidence_root: Path,
    official_sides: dict[tuple[str, str], dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    output: list[dict[str, Any]] = []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for issue in sorted(issues, key=lambda row: (int(row["game_id"]), int(row["player_id"]))):
        game_id, player_id = issue["game_id"], canonical_player_id(issue["player_id"], "goalie issue")
        goalie = goalie_by_key[(game_id, player_id)]
        side = goalie["home_away"]
        opponent_side = "away" if side == "home" else "home"
        opponent_sog = integer(official_sides[(game_id, opponent_side)]["team_sog"], f"opponent SOG {game_id}")
        pbp = pbp_by_game[game_id]
        target_events = [
            event
            for (team, event_side), events in sog_events_by_game[game_id].items()
            if team == goalie["opponent"] and event_side == opponent_side
            for event in events
            if event["details"].get("goalieInNetId") == int(player_id)
        ]
        # SOG events are explicit saves; a goal counts as a shot against only
        # when its PBP record includes shotType. A goal without shotType stays
        # a goal against but has no separate published SOG event.
        saves_events = [event for event in target_events if event["event_type"] == "shot-on-goal"]
        typed_goal_events = [
            event for event in target_events if event["event_type"] == "goal" and event["details"].get("shotType")
        ]
        goalie_goals = [
            play
            for play in pbp["plays"]
            if play.get("periodDescriptor", {}).get("periodType") in {"REG", "OT"}
            and play.get("typeDescKey") == "goal"
            and (play.get("details") or {}).get("goalieInNetId") == int(player_id)
        ]
        untyped_goals = [play for play in goalie_goals if not (play.get("details") or {}).get("shotType")]
        stat_meta, stat_body, stat_payload = verify_json_evidence(
            stats_manifest, game_id, evidence_root, "goalie-stats", "https://api.nhle.com/stats/rest/en/goalie/summary?"
        )
        stats_rows = [row for row in stat_payload.get("data", []) if str(row.get("playerId")) == player_id and int(row.get("gameId", -1)) == int(game_id)]
        if len(stats_rows) != 1:
            raise ValueError(f"STATS_REST_GOALIE_ROW_CARDINALITY {game_id}/{player_id}={len(stats_rows)}")
        stats_row = stats_rows[0]
        expected_home_road = "H" if goalie["home_away"] == "home" else "R"
        if (
            stats_row.get("teamAbbrev") != goalie["team"]
            or stats_row.get("opponentTeamAbbrev") != goalie["opponent"]
            or stats_row.get("gameDate") != goalie["game_date"]
            or stats_row.get("homeRoad") != expected_home_road
        ):
            raise ValueError(f"STATS_REST_GOALIE_IDENTITY_MISMATCH {game_id}/{player_id}")
        game_meta, _game_text = verify_html_evidence(summary_manifest, game_id, evidence_root)
        if integer(stats_row["timeOnIce"], f"Stats REST TOI {game_id}/{player_id}") != int(goalie["toi_seconds"]):
            raise ValueError(f"STATS_REST_TOI_MISMATCH {game_id}/{player_id}")
        stats_values = {
            "saves": integer(stats_row["saves"], f"Stats REST saves {game_id}"),
            "shots_against": integer(stats_row["shotsAgainst"], f"Stats REST SA {game_id}"),
            "goals_against": integer(stats_row["goalsAgainst"], f"Stats REST GA {game_id}"),
        }
        original_values = {
            "saves": integer(goalie["saves"], f"official saves {game_id}"),
            "shots_against": integer(goalie["shots_against"], f"official SA {game_id}"),
            "goals_against": integer(goalie["goals_against"], f"official GA {game_id}"),
        }
        if stats_values != original_values:
            raise ValueError(f"STATS_REST_VS_GAMECENTER_MISMATCH {game_id}/{player_id}: {stats_values} != {original_values}")
        pbp_counts = {
            "saves": len(saves_events),
            "shots_against": len(saves_events) + len(typed_goal_events),
            "goals_against": len(goalie_goals),
        }
        if pbp_counts != original_values:
            raise ValueError(f"PBP_GOALIE_FIELDS_NOT_RECONCILED {game_id}/{player_id}: {pbp_counts} != {original_values}")
        pbp_sog_summary = integer(pbp[f"{opponent_side}Team"]["sog"], f"PBP reported opponent SOG {game_id}")
        if pbp_sog_summary != opponent_sog or pbp_counts["shots_against"] != opponent_sog:
            raise ValueError(f"PBP_OFFICIAL_SA_SUMMARY_MISMATCH {game_id}/{player_id}")
        if len(untyped_goals) != 1 or pbp_counts["goals_against"] - len(untyped_goals) != len(typed_goal_events):
            raise ValueError(f"GOAL_WITHOUT_SHOTTYPE_NOT_EXPLAINING_IDENTITY {game_id}/{player_id}")
        game_summary_line = summary_manifest[game_id]["confirmed_goalie_line"]
        expected_line = f"{original_values['goals_against']}-{original_values['shots_against']}"
        if game_summary_line != expected_line:
            raise ValueError(f"GAME_SUMMARY_GOALIE_LINE_MISMATCH {game_id}: {game_summary_line} != {expected_line}")
        if original_values["saves"] + original_values["goals_against"] == original_values["shots_against"]:
            raise ValueError(f"GOALIE_CASE_NO_LONGER_FAILS_REGISTERED_IDENTITY {game_id}/{player_id}")

        row = {
            "adjudication_id": f"GOALIE-{game_id}-{player_id}",
            "game_id": game_id,
            "season": goalie["season"],
            "game_date": goalie["game_date"],
            "team": goalie["team"],
            "opponent": goalie["opponent"],
            "player_id": player_id,
            "player_name": goalie["player_name"],
            "toi_seconds": goalie["toi_seconds"],
            "game_outcome_last_period": pbp.get("gameOutcome", {}).get("lastPeriodType", ""),
            "official_saves": original_values["saves"],
            "official_shots_against": original_values["shots_against"],
            "official_goals_against": original_values["goals_against"],
            "stats_rest_saves": stats_values["saves"],
            "stats_rest_shots_against": stats_values["shots_against"],
            "stats_rest_goals_against": stats_values["goals_against"],
            "pbp_non_goal_shot_events": len(saves_events),
            "pbp_goal_events": len(goalie_goals),
            "pbp_goal_events_with_shot_type": len(typed_goal_events),
            "pbp_goal_events_without_shot_type": len(untyped_goals),
            "pbp_counted_shots_against": pbp_counts["shots_against"],
            "pbp_team_sog": pbp_sog_summary,
            "game_summary_goalie_line": game_summary_line,
            "accepted_saves": "",
            "accepted_shots_against": "",
            "accepted_goals_against": "",
            "quality_status": "QUARANTINED",
            "reason_code": "GOALIE_ARITHMETIC_CONFLICT_UNRESOLVED",
            "pbp_source_url": pbp_meta[game_id]["source_url"],
            "pbp_retrieved_at_utc": pbp_meta[game_id]["retrieved_at_utc"],
            "pbp_sha256": pbp_meta[game_id]["sha256"],
            "stats_rest_source_url": stat_meta["source_url"],
            "stats_rest_retrieved_at_utc": stat_meta["retrieved_at_utc"],
            "stats_rest_sha256": stat_meta["sha256"],
            "game_summary_source_url": game_meta["source_url"],
            "game_summary_retrieved_at_utc": game_meta["retrieved_at_utc"],
            "game_summary_sha256": game_meta["sha256"],
        }
        output.append(row)
        index[(game_id, player_id)] = {
            "status": "QUARANTINED",
            "adjudication_id": row["adjudication_id"],
            "source_issue_id": f"{game_id}:{player_id}:GOALIE_TOTAL_IDENTITY_MISMATCH",
            "reason_code": "GOALIE_ARITHMETIC_CONFLICT_UNRESOLVED",
            "reason": (
                "NHL Stats REST and the historical Game Summary repeat the original goalie values. PBP has "
                f"{len(saves_events)} explicit non-goal shot-on-goal events, {len(typed_goal_events)} goal events "
                f"with shotType, and {len(untyped_goals)} goal event without shotType; the published SA is "
                "the opposing team's official SOG total. The sources do not establish whether the untyped goal "
                "belongs in shots against, so the internal conflict cannot be assigned to one field. Preserve all "
                "published values, quarantine all three targets, and do not correct by subtraction."
            ),
            "original_values": original_values,
            "accepted_values": {field: "" for field in original_values},
            "corrected_values": {field: "" for field in original_values},
            "pbp_counts": pbp_counts,
            "pbp_untyped_goal_event_ids": [integer(play.get("eventId"), "untyped goal event") for play in untyped_goals],
            "pbp_url": pbp_meta[game_id]["source_url"],
            "pbp_retrieved_at_utc": pbp_meta[game_id]["retrieved_at_utc"],
            "pbp_sha256": pbp_meta[game_id]["sha256"],
            "stats_url": stat_meta["source_url"],
            "stats_retrieved_at_utc": stat_meta["retrieved_at_utc"],
            "stats_sha256": stat_meta["sha256"],
            "summary_url": game_meta["source_url"],
            "summary_retrieved_at_utc": game_meta["retrieved_at_utc"],
            "summary_sha256": game_meta["sha256"],
            "summary_line": game_summary_line,
        }
    return output, index


def build_ledger_rows(
    sog_issues: list[dict[str, str]],
    goalie_issues: list[dict[str, str]],
    goalie_evidence: dict[tuple[str, str], dict[str, Any]],
    sog_index: dict[tuple[str, str, str], dict[str, Any]],
    frame: dict[str, dict[str, str]],
    official_sides: dict[tuple[str, str], dict[str, str]],
    pbp_meta: dict[str, dict[str, str]],
    stats_manifest: dict[str, dict[str, str]],
    summary_manifest: dict[str, dict[str, str]],
    original_entries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for issue in sorted(sog_issues, key=lambda row: (int(row["game_id"]), row["side"])):
        gid, side, team = issue["game_id"], issue["side"], issue["team"]
        evidence_rows = [row for key, row in sog_index.items() if key[0] == gid and key[1] == team]
        if not evidence_rows or any(row["status"] != "ADJUDICATED" for row in evidence_rows):
            raise ValueError(f"SOG_ISSUE_MISSING_PLAYER_EVIDENCE {gid}/{team}")
        proof = next(row for row in evidence_rows if row.get("reason_code") == "TEAM_TOTAL_INCLUDES_GOALIE_SOG")
        player_id = proof["player_id"]
        team_row = official_sides[(gid, side)]
        rows.append({
            "ledger_id": f"ISSUE-SOG-{gid}-{side}",
            "row_type": "SOURCE_ISSUE",
            "source_issue_id": f"{gid}:{side}:{team}:PLAYER_SOG_SUM_VS_TEAM_TOTAL",
            "game_id": gid,
            "game_date": frame[gid]["game_date"],
            "season": frame[gid]["season"],
            "team": team,
            "side": side,
            "player_id": player_id,
            "statistic": "SKATER_SOG_TEAM_SUM_VALIDATION",
            "original_official_value": issue["value"],
            "independent_evidence_value": (
                f"published_team_sog={team_row['team_sog']}; all {len(evidence_rows)-1} skater IDs match PBP; "
                f"goalie {player_id} has 1 SOG event {proof['event_ids']}"
            ),
            "corrected_value": "",
            "quality_status": "ADJUDICATED",
            "reason_code": "TEAM_TOTAL_INCLUDES_GOALIE_SOG",
            "reason": (
                "The validator summed only forward/defense rows. Official team SOG includes one same-team goalie SOG; "
                "PBP independently matches every skater count by numeric NHL player ID. No skater value is changed."
            ),
            "source_url": pbp_meta[gid]["source_url"],
            "retrieved_at_utc": pbp_meta[gid]["retrieved_at_utc"],
            "source_sha256": pbp_meta[gid]["sha256"],
            "corroborating_source_url": original_entries[gid]["url"],
            "corroborating_retrieved_at_utc": original_entries[gid].get("retrieved_at_utc") or f"prior-cache audit_date={original_entries[gid].get('audit_date', '')}",
            "corroborating_sha256": original_entries[gid]["raw_sha256"],
            "eligible_training": "N/A_TEAM_AGGREGATE",
            "eligible_evaluation": "N/A_TEAM_AGGREGATE",
            "eligible_grading": "N/A_TEAM_AGGREGATE",
        })
    for issue in sorted(goalie_issues, key=lambda row: (int(row["game_id"]), int(row["player_id"]))):
        gid, pid = issue["game_id"], issue["player_id"]
        evidence = goalie_evidence[(gid, pid)]
        original = evidence["original_values"]
        rows.append({
            "ledger_id": f"ISSUE-GOALIE-{gid}-{pid}",
            "row_type": "SOURCE_ISSUE",
            "source_issue_id": f"{gid}:{pid}:GOALIE_TOTAL_IDENTITY_MISMATCH",
            "game_id": gid,
            "game_date": frame[gid]["game_date"],
            "season": frame[gid]["season"],
            "team": next(row["team"] for row in goalie_issues if row["game_id"] == gid and row["player_id"] == pid),
            "side": next(row["side"] for row in goalie_issues if row["game_id"] == gid and row["player_id"] == pid),
            "player_id": pid,
            "statistic": "SAVES_PLUS_GOALS_AGAINST_EQUALS_SHOTS_AGAINST",
            "original_official_value": f"saves={original['saves']}; goals_against={original['goals_against']}; shots_against={original['shots_against']}",
            "independent_evidence_value": (
                f"PBP saves_events={evidence['pbp_counts']['saves']}; PBP counted_shots_against="
                f"{evidence['pbp_counts']['shots_against']}; PBP goals={evidence['pbp_counts']['goals_against']}; "
                f"official_game_summary={evidence['summary_line']}; untyped_goal_event_ids={evidence['pbp_untyped_goal_event_ids']}"
            ),
            "corrected_value": "",
            "quality_status": "QUARANTINED",
            "reason_code": evidence["reason_code"],
            "reason": evidence["reason"],
            "source_url": evidence["pbp_url"],
            "retrieved_at_utc": evidence["pbp_retrieved_at_utc"],
            "source_sha256": evidence["pbp_sha256"],
            "corroborating_source_url": f"{evidence['summary_url']} ; {evidence['stats_url']} ; {original_entries[gid]['url']}",
            "corroborating_retrieved_at_utc": f"{evidence['summary_retrieved_at_utc']} ; {evidence['stats_retrieved_at_utc']} ; {original_entries[gid].get('retrieved_at_utc', '')}",
            "corroborating_sha256": f"{evidence['summary_sha256']} ; {evidence['stats_sha256']} ; {original_entries[gid]['raw_sha256']}",
            "eligible_training": "N/A_COMPOSITE_CHECK",
            "eligible_evaluation": "N/A_COMPOSITE_CHECK",
            "eligible_grading": "N/A_COMPOSITE_CHECK",
        })
        for field in ("saves", "shots_against", "goals_against"):
            rows.append({
                "ledger_id": f"FIELD-GOALIE-{gid}-{pid}-{field.upper()}",
                "row_type": "PLAYER_STAT_FIELD",
                "source_issue_id": f"{gid}:{pid}:GOALIE_TOTAL_IDENTITY_MISMATCH",
                "game_id": gid,
                "game_date": frame[gid]["game_date"],
                "season": frame[gid]["season"],
                "team": next(row["team"] for row in goalie_issues if row["game_id"] == gid and row["player_id"] == pid),
                "side": next(row["side"] for row in goalie_issues if row["game_id"] == gid and row["player_id"] == pid),
                "player_id": pid,
                "statistic": field.upper(),
                "original_official_value": original[field],
                "independent_evidence_value": evidence["pbp_counts"][field],
                "corrected_value": evidence["corrected_values"][field],
                "quality_status": "QUARANTINED",
                "reason_code": evidence["reason_code"],
                "reason": evidence["reason"],
                "source_url": evidence["pbp_url"],
                "retrieved_at_utc": evidence["pbp_retrieved_at_utc"],
                "source_sha256": evidence["pbp_sha256"],
                "corroborating_source_url": f"{evidence['summary_url']} ; {evidence['stats_url']} ; {original_entries[gid]['url']}",
                "corroborating_retrieved_at_utc": f"{evidence['summary_retrieved_at_utc']} ; {evidence['stats_retrieved_at_utc']} ; {original_entries[gid].get('retrieved_at_utc', '')}",
                "corroborating_sha256": f"{evidence['summary_sha256']} ; {evidence['stats_sha256']} ; {original_entries[gid]['raw_sha256']}",
                "eligible_training": "false",
                "eligible_evaluation": "false",
                "eligible_grading": "false",
            })
    rows.sort(key=lambda row: (int(row["game_id"]), row["row_type"], row["statistic"], int(row["player_id"] or 0)))
    if sum(row["row_type"] == "SOURCE_ISSUE" for row in rows) != 22:
        raise ValueError("LEDGER_DOES_NOT_COVER_22_SOURCE_ISSUES")
    return rows


def build_quality_rows(
    skater_rows: list[dict[str, str]],
    goalie_rows: list[dict[str, str]],
    issue_sides: dict[tuple[str, str], dict[str, str]],
    sog_event_index: dict[tuple[str, str, str], dict[str, Any]],
    goalie_evidence: dict[tuple[str, str], dict[str, Any]],
    original_entries: dict[str, dict[str, Any]],
    pbp_meta: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    def eligibility(status: str, appeared: bool) -> tuple[str, str, str]:
        value = "true" if appeared and usable_status(status) else "false"
        return value, value, value

    for row in skater_rows:
        game_id = row["game_id"]
        player_id = row["player_id"]
        stat = "SOG"
        original = row["sog"]
        try:
            pid = canonical_player_id(player_id, f"skater label {game_id}")
            source_value = integer(original, f"skater SOG {game_id}/{pid}")
            appearance = row["appeared"] == "1"
        except ValueError:
            pid = player_id
            source_value = ""
            appearance = False
            status = "QUARANTINED"
            reason_code = "INVALID_ID_OR_SOG"
            reason = "Player ID or SOG is missing or invalid; no value is imputed."
            evidence = None
        else:
            if row["appeared"] == "0":
                status = "NOT_APPLICABLE"
                reason_code = "NO_SKATER_APPEARANCE_ZERO_TOI"
                reason = "Official TOI is zero; a played-game SOG outcome does not apply."
                evidence = None
            elif row["appeared"] != "1" or int(row["toi_seconds"] or 0) <= 0 or row["identity_status"] != "OK":
                status = "QUARANTINED"
                reason_code = "APPEARANCE_OR_IDENTITY_NOT_VERIFIED"
                reason = "Positive appearance, numeric NHL ID, and identity status must all be present."
                evidence = None
            elif (game_id, row["team"]) in issue_sides:
                evidence = sog_event_index.get((game_id, row["team"], pid))
                if not evidence:
                    raise ValueError(f"ADJUDICATED_SOG_LABEL_HAS_NO_PBP_EVIDENCE {game_id}/{pid}")
                status = evidence["status"]
                reason_code = evidence["reason_code"]
                reason = evidence["reason"]
            else:
                status = "VERIFIED"
                reason_code = "OFFICIAL_SOG_TEAM_SUM_PASS"
                reason = "Hash-pinned official row has numeric ID and positive TOI; its full team-side player SOG sum equals the official team total."
                evidence = None
        original_hash = original_entries[game_id]["raw_sha256"]
        eligible = eligibility(status, appearance)
        output.append({
            "label_id": f"{row['record_key']}:{stat}",
            "record_key": row["record_key"],
            "game_id": game_id,
            "season": row["season"],
            "game_date": row["game_date"],
            "team": row["team"],
            "opponent": row["opponent"],
            "home_away": row["home_away"],
            "player_id": pid,
            "statistic": stat,
            "official_value": source_value,
            "accepted_value": source_value if usable_status(status) and appearance else "",
            "corrected_value": "",
            "quality_status": status,
            "reason_code": reason_code,
            "reason": reason,
            "adjudication_id": evidence["adjudication_id"] if evidence else "",
            "source_issue_id": evidence["source_issue_id"] if evidence else "",
            "original_gamecenter_raw_sha256": original_hash,
            "independent_evidence_url": evidence["source_url"] if evidence else "",
            "independent_evidence_sha256": evidence["source_sha256"] if evidence else "",
            "eligible_training": eligible[0],
            "eligible_evaluation": eligible[1],
            "eligible_grading": eligible[2],
        })

    for row in goalie_rows:
        game_id, player_id = row["game_id"], row["player_id"]
        try:
            pid = canonical_player_id(player_id, f"goalie label {game_id}")
            appearance = row["appeared"] == "1"
        except ValueError:
            pid = player_id
            appearance = False
        original_hash = original_entries[game_id]["raw_sha256"]
        for stat, field in (("SAVES", "saves"), ("SHOTS_AGAINST", "shots_against"), ("GOALS_AGAINST", "goals_against")):
            original = row[field]
            if not appearance and row["appeared"] == "0":
                status = "NOT_APPLICABLE"
                reason_code = "NO_GOALIE_APPEARANCE_ZERO_TOI"
                reason = "Official goalie TOI is zero; this is a retained roster slot, not a played-game prop outcome."
                value = integer(original, f"zero-TOI goalie {game_id}/{pid}/{field}")
                accepted = ""
                evidence = None
            elif not pid.isdigit() or row["appeared"] != "1" or int(row["toi_seconds"] or 0) <= 0 or row["identity_status"] != "OK" or not original.isdigit():
                status = "QUARANTINED"
                reason_code = "GOALIE_ID_APPEARANCE_OR_VALUE_INVALID"
                reason = "Played goalie identity, positive TOI, or published statistic is missing/invalid; no value is imputed."
                value = original
                accepted = ""
                evidence = None
            elif (game_id, pid) in goalie_evidence:
                evidence = goalie_evidence[(game_id, pid)]
                status = evidence["status"]
                reason_code = evidence["reason_code"]
                reason = evidence["reason"]
                value = integer(original, f"goalie field {game_id}/{pid}/{field}")
                accepted = evidence["accepted_values"][field]
            else:
                value = integer(original, f"goalie field {game_id}/{pid}/{field}")
                if integer(row["saves"], f"goalie saves identity {game_id}") + integer(row["goals_against"], f"goalie GA identity {game_id}") != integer(row["shots_against"], f"goalie SA identity {game_id}"):
                    raise ValueError(f"UNREGISTERED_GOALIE_ARITHMETIC_FAILURE {game_id}/{pid}")
                status = "VERIFIED"
                reason_code = "OFFICIAL_GOALIE_ARITHMETIC_PASS"
                reason = "Hash-pinned official goalie record has numeric NHL ID, positive TOI, and saves + goals against equals shots against."
                accepted = value
                evidence = None
            eligible = eligibility(status, appearance)
            output.append({
                "label_id": f"{row['record_key']}:{stat}",
                "record_key": row["record_key"],
                "game_id": game_id,
                "season": row["season"],
                "game_date": row["game_date"],
                "team": row["team"],
                "opponent": row["opponent"],
                "home_away": row["home_away"],
                "player_id": pid,
                "statistic": stat,
                "official_value": value,
                "accepted_value": accepted,
                "corrected_value": "",
                "quality_status": status,
                "reason_code": reason_code,
                "reason": reason,
                "adjudication_id": evidence["adjudication_id"] if evidence else "",
                "source_issue_id": evidence["source_issue_id"] if evidence else "",
                "original_gamecenter_raw_sha256": original_hash,
                "independent_evidence_url": evidence["pbp_url"] if evidence else "",
                "independent_evidence_sha256": evidence["pbp_sha256"] if evidence else "",
                "eligible_training": eligible[0],
                "eligible_evaluation": eligible[1],
                "eligible_grading": eligible[2],
            })

    output.sort(key=lambda row: (int(row["game_id"]), row["team"], row["statistic"], int(row["player_id"] or 0), row["record_key"]))
    if len(output) != len(skater_rows) + 3 * len(goalie_rows):
        raise ValueError("RESEARCH_LABEL_ROW_COUNT_MISMATCH")
    if len({row["label_id"] for row in output}) != len(output):
        raise ValueError("RESEARCH_LABEL_DUPLICATE_LABEL_ID")
    return output


def build_summary(
    labels: list[dict[str, Any]],
    issues: list[dict[str, str]],
    frame: list[dict[str, str]],
    pins: dict[str, Any],
    sog_event_rows: list[dict[str, Any]],
    goalie_event_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_stat: dict[str, Counter[str]] = defaultdict(Counter)
    by_season: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in labels:
        stat = row["statistic"]
        season = str(row["season"])
        status = row["quality_status"]
        by_stat[stat][status] += 1
        by_season[(season, stat)][status] += 1
        if row["eligible_training"] == "true":
            by_stat[stat]["ELIGIBLE_TRAINING"] += 1
            by_season[(season, stat)]["ELIGIBLE_TRAINING"] += 1
        if row["eligible_evaluation"] == "true":
            by_stat[stat]["ELIGIBLE_EVALUATION"] += 1
            by_season[(season, stat)]["ELIGIBLE_EVALUATION"] += 1
        if row["eligible_grading"] == "true":
            by_stat[stat]["ELIGIBLE_GRADING"] += 1
            by_season[(season, stat)]["ELIGIBLE_GRADING"] += 1
    issue_counts = Counter(row["issue_type"] for row in issues)
    issue_seasons: dict[str, Counter[str]] = defaultdict(Counter)
    frame_season_by_game = {row["game_id"]: row["season"] for row in frame}
    for row in issues:
        issue_seasons[frame_season_by_game[row["game_id"]]][row["issue_type"]] += 1
    frame_by_season = Counter(row["season"] for row in frame)
    sbr = sum(row["in_sbr_market_archive"] == "1" for row in frame)
    return {
        "schema_version": 1,
        "base_commit": BASE_COMMIT,
        "scope": "NHL official SOG, goalie saves, shots against, goals against; no fitting, ROI, or model promotion.",
        "populations": {
            "canonical_official_frame_games": len(frame),
            "sbr_market_subset_games": sbr,
            "goalie_prereg_complete_case_rows": 4763,
            "goalie_prereg_out_of_fold_evaluation_games": 3509,
            "canonical_games_by_start_season": dict(sorted(frame_by_season.items(), key=lambda item: int(item[0]))),
            "denominators_are_independent": True,
            "existing_goalie_preregistration_unchanged": True,
        },
        "quality_vocabulary": ["VERIFIED", "ADJUDICATED", "QUARANTINED", "NOT_APPLICABLE"],
        "labels": {
            "total_rows": len(labels),
            "by_statistic": {key: dict(sorted(value.items())) for key, value in sorted(by_stat.items())},
            "by_season_and_statistic": {
                f"{season}:{stat}": dict(sorted(counts.items()))
                for (season, stat), counts in sorted(by_season.items(), key=lambda item: (int(item[0][0]), item[0][1]))
            },
            "quarantined_total": sum(row["quality_status"] == "QUARANTINED" for row in labels),
            "not_applicable_total": sum(row["quality_status"] == "NOT_APPLICABLE" for row in labels),
            "eligible_counts_are_field_rows_not_games": True,
        },
        "adjudication": {
            "original_issue_count": len(issues),
            "issues_by_type": {
                issue_type: {
                    "found": count,
                    "adjudicated": count if issue_type == "PLAYER_SOG_SUM_VS_TEAM_TOTAL" else 0,
                    "quarantined": count if issue_type == "GOALIE_TOTAL_IDENTITY_MISMATCH" else 0,
                }
                for issue_type, count in sorted(issue_counts.items())
            },
            "issues_by_season": {season: dict(sorted(counts.items())) for season, counts in sorted(issue_seasons.items(), key=lambda item: int(item[0]))},
            "sog_player_event_rows": len(sog_event_rows),
            "goalie_case_rows": len(goalie_event_rows),
            "corrected_official_values": 0,
            "source_value_mutations": 0,
            "goalie_arithmetic_explanation": (
                "Stats REST and historical Game Summary repeat each original goalie line. PBP independently counts "
                "the saves and goals and the opponent's team SOG matches published shots against, but one goal event "
                "per game has no shotType. The evidence does not establish whether that goal belongs in shots "
                "against or which published field causes the failed identity. Preserve and expose every original "
                "value, quarantine saves/SA/GA for both goalies, and do not derive saves by subtraction."
            ),
            "unresolved_goalie_arithmetic_records": 2,
            "quarantined_goalie_stat_fields": 6,
        },
        "source_integrity": {
            "input_hashes": dict(sorted(pins["source_files"].items())),
            "external_evidence_hashes": dict(sorted(pins["external_evidence"].items())),
            "raw_external_evidence_kept_outside_git": True,
        },
        "research_limitations": [
            "The 2022-23 canonical frame is a 343-game partial-season slice; SBR market coverage is 339 games.",
            "The 4,763 complete-case goalie preregistration and 3,509 OOF denominator remain separate and unchanged.",
            "Outcome labels do not certify historical sportsbook settlement, grading-rule versions, or stat-correction timing.",
            "A quality-approved label is not evidence of player-prop price availability or profitable market evaluation.",
        ],
    }


def verify_outputs(outputs: dict[str, bytes], output_dir: Path) -> None:
    for name, expected in outputs.items():
        if name == "research_label_quality.csv":
            continue
        path = output_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"DERIVED_OUTPUT_MISSING {path}")
        actual = path.read_bytes()
        if actual != expected:
            raise ValueError(f"DERIVED_OUTPUT_HASH_MISMATCH {name}: expected={sha256_bytes(expected)} actual={sha256_bytes(actual)}")


def read_research_labels(
    *,
    purpose: str,
    path: Path = DEFAULT_LABEL_OUTPUT,
    statistic: str | None = None,
    before_game_date: str | dt.date | None = None,
) -> Iterator[dict[str, Any]]:
    """Compatibility wrapper for the shared purpose-aware research reader."""
    for label in iter_nhl_research_labels(
        purpose=purpose,  # type: ignore[arg-type]
        statistic=statistic,
        before_game_date=before_game_date,
        path=path,
    ):
        yield dataclasses.asdict(label)


def verify_label_output(expected: bytes, path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"LABEL_ARTIFACT_MISSING {path}")
    expected_hash = sha256_bytes(expected)
    actual_hash = file_sha256(path)
    if path.stat().st_size != len(expected) or actual_hash != expected_hash:
        raise ValueError(
            f"LABEL_ARTIFACT_HASH_MISMATCH expected={expected_hash}/{len(expected)} "
            f"actual={actual_hash}/{path.stat().st_size} path={path}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write adjudication outputs, keeping the large label CSV external")
    parser.add_argument("--artifact-dir", type=Path, default=HERE)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--backfill-root", type=Path, default=DEFAULT_BACKFILL_ROOT)
    parser.add_argument("--output-dir", type=Path, default=HERE, help="directory for small versioned outputs")
    parser.add_argument("--label-output", type=Path, default=DEFAULT_LABEL_OUTPUT, help="external path for the large reproducible CSV")
    parser.add_argument("--replace-label-output", action="store_true", help="replace an existing external CSV only after explicit review")
    args = parser.parse_args()
    repo_root = HERE.parents[2].resolve()
    try:
        args.label_output.resolve().relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise ValueError(f"LABEL_ARTIFACT_MUST_STAY_OUTSIDE_GIT {args.label_output}")
    outputs = build_outputs(args.artifact_dir, args.evidence_root, args.backfill_root, args.label_output)
    label_name = "research_label_quality.csv"
    small_outputs = {name: body for name, body in outputs.items() if name != label_name}
    if args.write:
        write_label = not args.label_output.exists()
        if args.label_output.exists():
            try:
                verify_label_output(outputs[label_name], args.label_output)
            except ValueError:
                if not args.replace_label_output:
                    raise
                write_label = True
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, body in small_outputs.items():
            (args.output_dir / name).write_bytes(body)
        args.label_output.parent.mkdir(parents=True, exist_ok=True)
        if write_label:
            args.label_output.write_bytes(outputs[label_name])
        print(
            f"RESEARCH_LABELS_WRITTEN small_files={len(small_outputs)} "
            f"labels={outputs[label_name].count(bytes([10])) - 1} "
            f"label_sha256={sha256_bytes(outputs[label_name])} path={args.label_output}"
        )
    else:
        verify_outputs(small_outputs, args.output_dir)
        verify_label_output(outputs[label_name], args.label_output)
        print(
            "RESEARCH_LABELS_VERIFY_PASS deterministic small outputs and external label artifact "
            f"match pinned sources and evidence sha256={sha256_bytes(outputs[label_name])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
