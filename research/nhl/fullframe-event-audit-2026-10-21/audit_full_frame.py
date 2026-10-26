#!/usr/bin/env python3
"""Verify and audit all NHL full-frame PBP and shift evidence.

All inputs and generated data locations are explicit. Raw bodies and derived
tables are expected outside Git. The audit fails closed for source integrity;
``--allow-incomplete`` is only for producing a coverage report while imports
are still running.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import statistics
import sys
import zlib
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SAMPLE_AUDIT = REPO / "research/nhl/event-data-audit-2026-10-20"
LABEL_DIR = REPO / "research/nhl/official-outcome-backfill-2026-10-20"
sys.path.insert(0, str(SAMPLE_AUDIT))
sys.path.insert(0, str(LABEL_DIR))

import audit_event_detail as detail  # noqa: E402
import audit_event_coverage as base  # noqa: E402
from nhl_research_data import iter_nhl_research_labels  # noqa: E402

FRAME_SHA256 = detail.EXPECTED["canonical_frame_sha256"]
FULL_FRAME_GAMES_SHA256 = "ef02d94ff0ff5e494b8cdcb7eeca2f3e466e1fac1d30682c3e25cf4065ae55a8"
SOURCE_URLS = {
    "pbp": "https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play",
    "shifts": "https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={gid}",
}
SHOT_TYPES = {"shot-on-goal", "goal", "missed-shot", "blocked-shot"}
SOG_TYPES = {"shot-on-goal", "goal"}
PBP_PERIOD_TYPES = {"REG", "OT", "SO"}
TOI_TOLERANCE_SECONDS = 30


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_keyed_rows(path: Path, key_fields: tuple[str, ...]) -> dict:
    keyed = {}
    for row in load_csv(path):
        key = tuple(row[field] for field in key_fields)
        if key in keyed:
            raise ValueError(f"DUPLICATE_OFFICIAL_ROW {path.name} key={key}")
        keyed[key] = row
    return keyed


def numeric_id(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def nonnegative_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def clock_seconds(value) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        minutes, seconds = (int(part) for part in value.split(":", 1))
    except ValueError:
        return None
    if minutes < 0 or seconds < 0 or seconds >= 60:
        return None
    return minutes * 60 + seconds


def period_parts(play: dict) -> tuple[int | None, str | None]:
    descriptor = play.get("periodDescriptor") or {}
    number = numeric_id(descriptor.get("number"))
    period_type = descriptor.get("periodType")
    if number is None or period_type not in PBP_PERIOD_TYPES:
        return None, period_type
    return number, period_type


def timeline_sequence_quality(plays: list[dict]) -> dict[str, int]:
    previous_sort_order = None
    previous_period = None
    sort_order_issue_count = 0
    period_number_regressions = 0
    for play in plays:
        sort_order = play.get("sortOrder")
        if (isinstance(sort_order, bool) or not isinstance(sort_order, int) or sort_order < 0
                or (previous_sort_order is not None and sort_order <= previous_sort_order)):
            sort_order_issue_count += 1
        if isinstance(sort_order, int) and not isinstance(sort_order, bool) and sort_order >= 0:
            previous_sort_order = sort_order
        period, _period_type = period_parts(play)
        if period is not None:
            if previous_period is not None and period < previous_period:
                period_number_regressions += 1
            previous_period = period
    return {"sort_order_issue_count": sort_order_issue_count,
            "period_number_regressions": period_number_regressions}


def apply_shootout_score_convention(period_goals: dict, official_score: dict,
                                    shootout: bool) -> dict[str, int]:
    adjusted = {side: int(period_goals.get(side, 0)) for side in ("home", "away")}
    if shootout and len(official_score) == 2 and official_score["home"] != official_score["away"]:
        winner = "home" if official_score["home"] > official_score["away"] else "away"
        adjusted[winner] += 1
    return adjusted


def finite_xy(details: dict) -> bool:
    x, y = details.get("xCoord"), details.get("yCoord")
    return (isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
            and isinstance(y, (int, float)) and not isinstance(y, bool) and math.isfinite(y))


def season_counts(rows: Iterable[dict], season_key: str = "season") -> dict[str, int]:
    counts = collections.Counter(str(row[season_key]) for row in rows)
    return {key: counts[key] for key in sorted(counts)}


def aggregate_season_metric(field: str, values: list[int | float]) -> int | float:
    if field in {"goalie_toi_max_delta_seconds", "skater_toi_max_delta_seconds"}:
        return max(values, default=0)
    if field == "median_shift_to_official_toi_ratio":
        return round(statistics.median(values), 3) if values else 0
    return sum(values)


def expected_url(kind: str, gid: str) -> str:
    return SOURCE_URLS[kind].format(gid=gid)


def validate_payload(kind: str, gid: str, raw: bytes) -> tuple[dict, int]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"PAYLOAD_NOT_JSON {gid}/{kind}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"PAYLOAD_ROOT_NOT_OBJECT {gid}/{kind}")
    if kind == "pbp":
        if str(payload.get("id")) != gid:
            raise ValueError(f"PBP_GAME_ID_MISMATCH expected={gid} actual={payload.get('id')!r}")
        if payload.get("gameType") != 2:
            raise ValueError(f"PBP_NOT_REGULAR_SEASON {gid} gameType={payload.get('gameType')!r}")
        for side in ("homeTeam", "awayTeam"):
            team = payload.get(side)
            if not isinstance(team, dict) or numeric_id(team.get("id")) is None:
                raise ValueError(f"PBP_TEAM_ID_MISSING {gid}/{side}")
        plays = payload.get("plays")
        if not isinstance(plays, list) or not plays or any(not isinstance(play, dict) for play in plays):
            raise ValueError(f"PBP_PLAYS_MISSING_OR_INVALID {gid}")
        return payload, len(plays)
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"SHIFT_ROWS_MISSING_OR_INVALID {gid}")
    if {str(row.get("gameId")) for row in rows} != {gid}:
        raise ValueError(f"SHIFT_GAME_ID_MISMATCH {gid}")
    total = payload.get("total")
    if total is not None and (isinstance(total, bool) or int(total) != len(rows)):
        raise ValueError(f"SHIFT_TOTAL_COUNT_MISMATCH {gid}: total={total!r} rows={len(rows)}")
    return payload, len(rows)


def verify_source(kind: str, game_ids: list[str], manifest_path: Path,
                  raw_root: Path, season_by_id: dict[str, str] | None = None) -> tuple[dict[str, dict], list[dict], dict]:
    if not manifest_path.is_file():
        raise ValueError(f"MANIFEST_MISSING {manifest_path}")
    rows = load_csv(manifest_path)
    manifest_by_id: dict[str, dict] = {}
    issues = []
    duplicate_ids = collections.Counter(row.get("game_id", "") for row in rows)
    duplicate_manifest_ids = {gid for gid, count in duplicate_ids.items() if count > 1}
    for gid, count in duplicate_ids.items():
        if count > 1:
            issues.append({"game_id": gid, "kind": kind, "reason_code": "DUPLICATE_MANIFEST_ROW",
                           "detail": f"rows={count}"})
    for row in rows:
        gid = row.get("game_id", "")
        if gid in manifest_by_id:
            continue
        manifest_by_id[gid] = row
    extra = sorted(set(manifest_by_id) - set(game_ids))
    for gid in extra:
        issues.append({"game_id": gid, "kind": kind, "reason_code": "MANIFEST_GAME_OUTSIDE_FRAME",
                       "detail": "manifest id not in pinned frame"})
    verified: dict[str, dict] = {}
    body_bytes_gz = body_bytes_raw = 0
    for gid in game_ids:
        row = manifest_by_id.get(gid)
        if row is None:
            issues.append({"game_id": gid, "kind": kind, "reason_code": "MANIFEST_ROW_MISSING",
                           "detail": "no manifest row"})
            continue
        if gid in duplicate_manifest_ids:
            continue
        url = expected_url(kind, gid)
        if row.get("kind") != kind or row.get("url") != url:
            issues.append({"game_id": gid, "kind": kind, "reason_code": "MANIFEST_SOURCE_IDENTITY_MISMATCH",
                           "detail": f"kind={row.get('kind')!r} url={row.get('url')!r} expected={url}"})
            continue
        if row.get("http_status") != "200" or row.get("note"):
            issues.append({"game_id": gid, "kind": kind, "reason_code": "SOURCE_REQUEST_NOT_SUCCESSFUL",
                           "detail": f"status={row.get('http_status')!r} note={row.get('note')!r}"})
            continue
        body_path = raw_root / kind / f"{gid}.json.gz"
        meta_path = raw_root / kind / f"{gid}.meta.json"
        try:
            if not body_path.is_file() or not meta_path.is_file():
                raise ValueError("RAW_BODY_OR_SIDECAR_MISSING")
            compressed = body_path.read_bytes()
            if len(compressed) != int(row["bytes_gz"]):
                raise ValueError("COMPRESSED_BYTE_COUNT_MISMATCH")
            compressed_hash = hashlib.sha256(compressed).hexdigest()
            if compressed_hash != row.get("sha256_gz"):
                raise ValueError("COMPRESSED_HASH_MISMATCH")
            raw = gzip.decompress(compressed)
            if len(raw) != int(row["bytes_raw"]):
                raise ValueError("DECOMPRESSED_BYTE_COUNT_MISMATCH")
            raw_hash = hashlib.sha256(raw).hexdigest()
            if raw_hash != row.get("sha256_raw"):
                raise ValueError("DECOMPRESSED_HASH_MISMATCH")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for field in ("game_id", "kind", "url", "http_status", "content_type", "bytes_raw", "sha256_raw",
                          "bytes_gz", "sha256_gz", "rows"):
                if str(meta.get(field, "")) != str(row.get(field, "")):
                    raise ValueError(f"SIDECAR_MANIFEST_MISMATCH_{field.upper()}")
            for field in ("retrieved_at_utc", "attempts", "request_duration_seconds",
                          "request_elapsed_with_pacing_seconds", "evidence_origin",
                          "sample_event_manifest_sha256", "sample_source_commit",
                          "source_identity_basis"):
                sidecar_value, manifest_value = meta.get(field), row.get(field)
                if sidecar_value not in (None, "") and manifest_value not in (None, ""):
                    if str(sidecar_value) != str(manifest_value):
                        raise ValueError(f"SIDECAR_MANIFEST_MISMATCH_{field.upper()}")
            if "json" not in str(row.get("content_type", "")).lower():
                raise ValueError("CONTENT_TYPE_NOT_JSON")
            payload, row_count = validate_payload(kind, gid, raw)
            if row_count != int(row["rows"]):
                raise ValueError("PAYLOAD_ROW_COUNT_MISMATCH")
            del payload
            verified[gid] = {"manifest": row, "body_path": body_path, "meta_path": meta_path,
                             "sha256_raw": raw_hash,
                             "sha256_gz": compressed_hash, "bytes_raw": len(raw),
                             "bytes_gz": len(compressed)}
            body_bytes_gz += len(compressed)
            body_bytes_raw += len(raw)
        except (OSError, EOFError, gzip.BadGzipFile, zlib.error, json.JSONDecodeError, KeyError,
                TypeError, ValueError, OverflowError) as exc:
            issues.append({"game_id": gid, "kind": kind, "reason_code": "BODY_VERIFICATION_FAILED",
                           "detail": str(exc)})
    per_season_verified = collections.Counter(
        str(season_by_id[gid]) for gid in verified if season_by_id and gid in season_by_id
    )
    return verified, issues, {
        "manifest_rows": len(rows), "unique_manifest_ids": len(manifest_by_id),
        "verified_bodies": len(verified), "missing_or_unverified": len(game_ids) - len(verified),
        "extra_manifest_ids": extra, "duplicate_manifest_ids": sorted(g for g, n in duplicate_ids.items() if n > 1),
        "verified_games_by_season": {key: per_season_verified[key] for key in sorted(per_season_verified)},
        "compressed_bytes_verified": body_bytes_gz, "decompressed_bytes_verified": body_bytes_raw,
        "manifest_sha256": sha256_file(manifest_path),
    }


def compare_prior_manifest(kind: str, game_ids: list[str], current_manifest_path: Path,
                           prior_manifest_path: Path | None) -> tuple[dict, list[dict]]:
    """Reconcile a prior full-frame manifest against the hardened manifest row by row."""
    if prior_manifest_path is None:
        return {"provided": False, "rows_checked": 0, "matched_rows": 0,
                "mismatch_rows": 0, "manifest_sha256": None}, []
    prior_rows = load_csv(prior_manifest_path)
    current_rows = load_csv(current_manifest_path)
    prior_counts = collections.Counter(row.get("game_id", "") for row in prior_rows)
    current_counts = collections.Counter(row.get("game_id", "") for row in current_rows)
    prior_by_id = {row.get("game_id", ""): row for row in prior_rows
                   if row.get("game_id", "") and prior_counts[row.get("game_id", "")] == 1}
    current_by_id = {row.get("game_id", ""): row for row in current_rows
                     if row.get("game_id", "") and current_counts[row.get("game_id", "")] == 1}
    issues = []
    fields = ("kind", "url", "http_status", "content_type", "bytes_raw", "sha256_raw",
              "bytes_gz", "sha256_gz", "rows", "retrieved_at_utc")
    for gid, count in prior_counts.items():
        if count != 1:
            issues.append({"game_id": gid, "kind": kind, "reason_code": "PRIOR_MANIFEST_DUPLICATE_GAME",
                           "detail": f"prior_manifest_rows={count}"})
    for gid, count in current_counts.items():
        if count != 1:
            issues.append({"game_id": gid, "kind": kind, "reason_code": "HARDENED_MANIFEST_DUPLICATE_GAME",
                           "detail": f"hardened_manifest_rows={count}"})
    expected_ids = set(game_ids)
    for gid in sorted(expected_ids):
        prior = prior_by_id.get(gid)
        current = current_by_id.get(gid)
        if prior is None:
            issues.append({"game_id": gid, "kind": kind, "reason_code": "PRIOR_MANIFEST_ROW_MISSING",
                           "detail": "prior source manifest has no unique game row"})
            continue
        if current is None:
            issues.append({"game_id": gid, "kind": kind, "reason_code": "HARDENED_MANIFEST_ROW_MISSING",
                           "detail": "hardened source manifest has no unique game row"})
            continue
        if prior.get("http_status") != "200" or prior.get("note") or not prior.get("sha256_raw"):
            issues.append({"game_id": gid, "kind": kind, "reason_code": "PRIOR_MANIFEST_ROW_NOT_VERIFIED",
                           "detail": f"status={prior.get('http_status')!r} note={prior.get('note')!r}"})
            continue
        mismatches = [(field, prior.get(field, ""), current.get(field, ""))
                      for field in fields if str(prior.get(field, "")) != str(current.get(field, ""))]
        for field, prior_value, current_value in mismatches:
            issues.append({"game_id": gid, "kind": kind, "reason_code": "PRIOR_MANIFEST_SOURCE_MISMATCH",
                           "detail": f"field={field} prior={prior_value!r} hardened={current_value!r}"})
    extra_ids = sorted((set(prior_by_id) | set(current_by_id)) - expected_ids)
    for gid in extra_ids:
        issues.append({"game_id": gid, "kind": kind, "reason_code": "PRIOR_MANIFEST_GAME_OUTSIDE_FRAME",
                       "detail": "prior/hardened manifest id is outside the pinned frame"})
    issue_ids_in_frame = {issue["game_id"] for issue in issues if issue["game_id"] in expected_ids}
    matched = len(expected_ids - issue_ids_in_frame)
    summary = {"provided": True, "path": str(prior_manifest_path.resolve()),
               "manifest_sha256": sha256_file(prior_manifest_path),
               "rows": len(prior_rows), "unique_game_ids": len(prior_by_id),
               "rows_checked": len(game_ids), "matched_rows": matched,
               "mismatch_rows": len(issue_ids_in_frame),
               "issue_rows": len(issues)}
    return summary, issues


def load_verified_payload(kind: str, game_id: str, source_record: dict | None) -> dict | None:
    """Reload one body for analysis and fail if it changed after preflight."""
    if source_record is None:
        return None
    row = source_record["manifest"]
    compressed = Path(source_record["body_path"]).read_bytes()
    if len(compressed) != source_record["bytes_gz"] or hashlib.sha256(compressed).hexdigest() != source_record["sha256_gz"]:
        raise ValueError(f"SOURCE_CHANGED_AFTER_PREFLIGHT_COMPRESSED {game_id}/{kind}")
    raw = gzip.decompress(compressed)
    if len(raw) != source_record["bytes_raw"] or hashlib.sha256(raw).hexdigest() != source_record["sha256_raw"]:
        raise ValueError(f"SOURCE_CHANGED_AFTER_PREFLIGHT_RAW {game_id}/{kind}")
    payload, row_count = validate_payload(kind, game_id, raw)
    if row_count != int(row["rows"]):
        raise ValueError(f"SOURCE_CHANGED_AFTER_PREFLIGHT_ROW_COUNT {game_id}/{kind}")
    return {"payload": payload, "manifest": row,
            "sha256_raw": source_record["sha256_raw"],
            "sha256_gz": source_record["sha256_gz"],
            "bytes_raw": source_record["bytes_raw"],
            "bytes_gz": source_record["bytes_gz"]}


def status_label(label, purpose: str) -> bool:
    return (label.quality_status in {"VERIFIED", "ADJUDICATED"}
            and label.accepted_value is not None
            and bool(getattr(label, f"eligible_{purpose}")))


class CsvGzipWriter:
    """Stream CSV to a gzip temp file and atomically publish on close."""
    def __init__(self, path: Path, fields: list[str]):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.temp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
        self.raw_handle = self.temp.open("wb")
        compressed = gzip.GzipFile(filename="", mode="wb", fileobj=self.raw_handle,
                                   compresslevel=6, mtime=0)
        self.handle = io.TextIOWrapper(compressed, encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        self.writer.writeheader()

    def row(self, value: dict) -> None:
        self.writer.writerow(value)

    def close(self) -> None:
        self.handle.close()
        self.raw_handle.flush()
        os.fsync(self.raw_handle.fileno())
        self.raw_handle.close()
        os.replace(self.temp, self.path)

    def abort(self) -> None:
        try:
            self.handle.close()
        finally:
            if not self.raw_handle.closed:
                self.raw_handle.close()
            try:
                self.temp.unlink()
            except FileNotFoundError:
                pass


def csv_gzip_sha(path: Path) -> str:
    return sha256_file(path)


def load_official(frame_ids: set[str]) -> tuple[dict, dict, dict, dict]:
    paths = {
        "sides": LABEL_DIR / "official_game_sides.csv",
        "skaters": LABEL_DIR / "official_skater_outcomes.csv",
        "goalies": LABEL_DIR / "official_goalie_outcomes.csv",
    }
    for key, pin in (("sides", "official_game_sides_sha256"),
                     ("skaters", "official_skater_outcomes_sha256"),
                     ("goalies", "official_goalie_outcomes_sha256")):
        actual = sha256_file(paths[key])
        if actual != detail.EXPECTED[pin]:
            raise ValueError(f"SOURCE_HASH_MISMATCH {pin}: expected={detail.EXPECTED[pin]} actual={actual}")
    sides_rows = load_keyed_rows(paths["sides"], ("game_id", "side"))
    skater_rows = load_keyed_rows(paths["skaters"], ("game_id", "player_id"))
    goalie_rows = load_keyed_rows(paths["goalies"], ("game_id", "player_id"))
    sides: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    skaters: dict[str, dict[int, dict]] = collections.defaultdict(dict)
    goalies: dict[str, dict[int, dict]] = collections.defaultdict(dict)
    for (gid, side), row in sides_rows.items():
        if gid in frame_ids:
            sides[gid][side] = row
    for (gid, pid), row in skater_rows.items():
        if gid in frame_ids and pid.isdigit():
            skaters[gid][int(pid)] = row
    for (gid, pid), row in goalie_rows.items():
        if gid in frame_ids and pid.isdigit():
            goalies[gid][int(pid)] = row
    return dict(sides), dict(skaters), dict(goalies), {k: sha256_file(v) for k, v in paths.items()}


def load_research_labels(label_path: Path, summary_path: Path, frame_ids: set[str]) -> tuple[dict, dict]:
    expected_hash = detail.EXPECTED["research_label_quality_sha256"]
    actual_hash = sha256_file(label_path)
    if actual_hash != expected_hash:
        raise ValueError(f"SOURCE_HASH_MISMATCH research_label_quality: expected={expected_hash} actual={actual_hash}")
    if sha256_file(summary_path) != detail.EXPECTED["research_label_summary_sha256"]:
        raise ValueError("SOURCE_HASH_MISMATCH research_label_summary")
    labels: dict[str, list] = collections.defaultdict(list)
    label_stats = collections.Counter()
    seen = set()
    for label in iter_nhl_research_labels(purpose="audit", path=label_path, summary_path=summary_path):
        if label.game_id not in frame_ids:
            continue
        key = (label.game_id, label.player_id, label.statistic)
        if key in seen:
            raise ValueError(f"DUPLICATE_APPROVED_LABEL {key}")
        seen.add(key)
        labels[label.game_id].append(label)
        label_stats[(label.statistic, label.quality_status)] += 1
    return dict(labels), {f"{statistic}/{status}": count
                          for (statistic, status), count in sorted(label_stats.items())}


def make_issue(issue_writer: CsvGzipWriter, reason_counts: collections.Counter,
               issue_games: dict[str, set[str]], season: str, gid: str, component: str,
               reason_code: str, subject_type: str, subject_id: str, detail_text: str,
               disposition: str) -> None:
    issue_writer.row({"game_id": gid, "season": season, "component": component,
                      "reason_code": reason_code, "subject_type": subject_type,
                      "subject_id": subject_id, "detail": detail_text,
                      "disposition": disposition})
    reason_counts[(season, reason_code)] += 1
    issue_games[reason_code].add(gid)


def team_abbrev(payload: dict, side: str) -> str:
    team = payload.get(f"{side}Team") or {}
    return str(team.get("abbrev") or team.get("triCode") or "")


def parse_shift_rows(payload: dict, season: str, gid: str, shift_writer: CsvGzipWriter,
                     issue_writer: CsvGzipWriter, reason_counts: collections.Counter,
                     issue_games: dict[str, set[str]],
                     official_skater_rows: dict[int, dict], official_goalie_rows: dict[int, dict],
                     roster_ids: set[int], team_to_id: dict[str, int]) -> tuple[list[dict], dict]:
    raw_rows = payload.get("data") or []
    parsed = []
    row_fingerprint_counts = collections.Counter()
    malformed = 0
    for index, row in enumerate(raw_rows):
        if numeric_id(row.get("typeCode")) != 517:
            continue
        pid, period = numeric_id(row.get("playerId")), numeric_id(row.get("period"))
        start, end = clock_seconds(row.get("startTime")), clock_seconds(row.get("endTime"))
        duration = clock_seconds(row.get("duration"))
        team_id = numeric_id(row.get("teamId"))
        fingerprint = (pid, period, start, end, team_id, duration)
        row_fingerprint_counts[fingerprint] += 1
        valid = pid is not None and period is not None and start is not None and end is not None and end > start
        if not valid:
            malformed += 1
            make_issue(issue_writer, reason_counts, issue_games, season, gid, "deployment",
                       "SHIFT_INTERVAL_INVALID", "shift_row", str(row.get("id") or index),
                       f"player={pid} period={period} start={row.get('startTime')!r} end={row.get('endTime')!r}",
                       "REJECT")
            continue
        duration_valid = duration is not None and duration == end - start
        if not duration_valid:
            make_issue(issue_writer, reason_counts, issue_games, season, gid, "deployment",
                       "SHIFT_DURATION_DISAGREES_WITH_INTERVAL", "shift_row", str(row.get("id") or index),
                       f"duration={row.get('duration')!r} interval_seconds={end-start}", "QUARANTINE")
        parsed.append({"row_id": str(row.get("id") or index), "player_id": pid, "period": period,
                       "start": start, "end": end, "duration": duration,
                       "duration_valid": duration_valid, "team_id": team_id,
                       "team_abbrev": str(row.get("teamAbbrev") or "")})
    exact_duplicates = sum(count - 1 for count in row_fingerprint_counts.values() if count > 1)
    if exact_duplicates:
        for fingerprint, count in row_fingerprint_counts.items():
            if count > 1:
                make_issue(issue_writer, reason_counts, issue_games, season, gid, "deployment",
                           "DUPLICATE_SHIFT_INTERVAL", "shift_interval", ":".join(map(str, fingerprint)),
                           f"duplicate_rows={count}", "REJECT")
    by_player_period: dict[tuple[int, int], list[dict]] = collections.defaultdict(list)
    for row in parsed:
        by_player_period[(row["player_id"], row["period"])].append(row)
    overlapping_players = set()
    overlapping_rows = set()
    for (pid, period), intervals in by_player_period.items():
        intervals.sort(key=lambda item: (item["start"], item["end"], item["row_id"]))
        furthest_end, furthest = -1, None
        for interval in intervals:
            if interval["start"] < furthest_end:
                overlapping_players.add(pid)
                overlapping_rows.add(interval["row_id"])
                overlapping_rows.add(furthest["row_id"])
                make_issue(issue_writer, reason_counts, issue_games, season, gid, "deployment",
                           "PLAYER_SHIFT_OVERLAP", "player_period", f"{pid}/{period}",
                           f"overlap={furthest['start']}-{furthest['end']} & {interval['start']}-{interval['end']}",
                           "REJECT")
            if interval["end"] > furthest_end:
                furthest_end, furthest = interval["end"], interval
    totals = collections.Counter()
    player_status = {}
    skater_deltas, goalie_deltas = [], []
    players = {row["player_id"] for row in parsed}
    all_official = {**official_skater_rows, **official_goalie_rows}
    shift_toi_by_player = collections.Counter()
    for row in parsed:
        shift_toi_by_player[row["player_id"]] += row["duration"] or 0
    duplicate_ratios = []
    for pid, shifted_seconds in shift_toi_by_player.items():
        official = all_official.get(pid)
        try:
            official_seconds = int(official.get("toi_seconds") or "") if official else 0
        except (TypeError, ValueError):
            continue
        if official_seconds > 300:
            duplicate_ratios.append(shifted_seconds / official_seconds)
    median_shift_ratio = statistics.median(duplicate_ratios) if duplicate_ratios else 0.0
    ratio_duplicate_chart = bool(duplicate_ratios and abs(median_shift_ratio - 2.0) < 0.15)
    chart_duplicate = exact_duplicates > 0 or ratio_duplicate_chart
    if ratio_duplicate_chart:
        make_issue(issue_writer, reason_counts, issue_games, season, gid, "deployment",
                   "DUPLICATE_SHIFT_CHART", "game", gid,
                   f"median_shift_to_official_toi_ratio={median_shift_ratio:.3f}; all chart intervals rejected",
                   "REJECT")
    appeared_skater_ids = {pid for pid, row in official_skater_rows.items() if row.get("appeared") == "1"}
    appeared_goalie_ids = {pid for pid, row in official_goalie_rows.items() if row.get("appeared") == "1"}
    team_mismatch_players = set()
    team_identity_missing_players = set()
    known_team_ids = {team_id for team_id in team_to_id.values() if team_id is not None}
    for interval in parsed:
        official = all_official.get(interval["player_id"])
        expected_abbrev = official.get("team") if official else None
        expected_team_id = team_to_id.get(expected_abbrev or "")
        if not interval["team_abbrev"] or interval["team_id"] is None:
            team_identity_missing_players.add(interval["player_id"])
        elif (interval["team_abbrev"] not in team_to_id
              or interval["team_id"] != team_to_id.get(interval["team_abbrev"])
              or (known_team_ids and interval["team_id"] not in known_team_ids)):
            team_mismatch_players.add(interval["player_id"])
        if expected_abbrev and ((interval["team_abbrev"] and interval["team_abbrev"] != expected_abbrev)
                                or (interval["team_id"] is not None and expected_team_id is not None
                                    and interval["team_id"] != expected_team_id)):
            team_mismatch_players.add(interval["player_id"])
    for pid in sorted(players | appeared_skater_ids | appeared_goalie_ids):
        player_intervals = [row for row in parsed if row["player_id"] == pid]
        is_goalie = pid in official_goalie_rows
        official = all_official.get(pid)
        shift_toi = sum(row["duration"] or 0 for row in player_intervals)
        off_toi = None
        if official and official.get("toi_seconds", "").isdigit():
            off_toi = int(official["toi_seconds"])
        player_reasons = []
        if pid not in roster_ids:
            player_reasons.append("SHIFT_PLAYER_NOT_IN_PBP_ROSTER")
        if official is None:
            player_reasons.append("SHIFT_PLAYER_NOT_IN_OFFICIAL_APPEARANCE_FILE")
        elif official.get("identity_status") != "OK":
            player_reasons.append("SHIFT_PLAYER_OFFICIAL_IDENTITY_UNRESOLVED")
        elif official.get("appeared") != "1" and player_intervals:
            player_reasons.append("SHIFT_PLAYER_OFFICIAL_NONAPPEARANCE")
        if pid in overlapping_players:
            player_reasons.append("PLAYER_SHIFT_OVERLAP")
        if pid in team_mismatch_players:
            player_reasons.append("SHIFT_TEAM_IDENTITY_MISMATCH")
        if pid in team_identity_missing_players:
            player_reasons.append("SHIFT_TEAM_IDENTITY_MISSING")
        if any(not row["duration_valid"] for row in player_intervals):
            player_reasons.append("SHIFT_DURATION_DISAGREES_WITH_INTERVAL")
        if exact_duplicates:
            player_reasons.append("DUPLICATE_SHIFT_INTERVAL")
        if ratio_duplicate_chart:
            player_reasons.append("DUPLICATE_SHIFT_CHART")
        if off_toi is None:
            player_reasons.append("OFFICIAL_TOI_UNAVAILABLE")
        elif abs(shift_toi - off_toi) > TOI_TOLERANCE_SECONDS:
            player_reasons.append("SHIFT_TOI_OUTSIDE_30S")
        if off_toi is not None:
            (goalie_deltas if is_goalie else skater_deltas).append(abs(shift_toi - off_toi))
        if not player_intervals and official and official.get("appeared") == "1":
            player_reasons.append("APPEARED_PLAYER_WITHOUT_SHIFTS")
        status = "ACCEPT" if not player_reasons and player_intervals else (
            "NOT_APPLICABLE" if not player_intervals and not (official and official.get("appeared") == "1")
            else "QUARANTINE")
        player_status[pid] = status
        totals["player_games_eligible"] += status == "ACCEPT"
        totals["goalie_player_games_eligible"] += status == "ACCEPT" and is_goalie
        totals["skater_player_games_eligible"] += status == "ACCEPT" and not is_goalie
        toi_delta = "" if off_toi is None else shift_toi - off_toi
        for code in sorted(set(player_reasons)):
            make_issue(issue_writer, reason_counts, issue_games, season, gid, "deployment", code,
                       "player", str(pid), f"shift_toi_seconds={shift_toi} official_toi_seconds={off_toi}",
                       "QUARANTINE")
        for interval in player_intervals:
            interval_status = "REJECT" if interval["row_id"] in overlapping_rows or chart_duplicate else status
            interval_team_expected = None
            if official:
                interval_team_expected = official.get("team")
            expected_team_id = team_to_id.get(interval_team_expected or "")
            team_mismatch = bool(
                interval_team_expected
                and ((interval["team_abbrev"] and interval["team_abbrev"] != interval_team_expected)
                     or (interval["team_id"] is not None and expected_team_id is not None
                         and interval["team_id"] != expected_team_id))
            )
            if team_mismatch:
                interval_status = "REJECT"
                make_issue(issue_writer, reason_counts, issue_games, season, gid, "deployment",
                           "SHIFT_TEAM_IDENTITY_MISMATCH", "shift_row", interval["row_id"],
                           f"shift_team={interval['team_abbrev']}/{interval['team_id']} official_team={interval_team_expected}/{expected_team_id}", "REJECT")
            interval["disposition"] = interval_status
            interval["reason_codes"] = ";".join(sorted(set(player_reasons)))
            shift_writer.row({"game_id": gid, "season": season, "player_id": pid,
                              "player_type": "goalie" if is_goalie else "skater",
                              "interval_id": interval["row_id"], "period": interval["period"],
                              "start_seconds": interval["start"], "end_seconds": interval["end"],
                              "duration_seconds": interval["duration"] if interval["duration"] is not None else "",
                              "official_toi_seconds": off_toi if off_toi is not None else "",
                              "shift_toi_seconds_player_game": shift_toi, "toi_delta_seconds": toi_delta,
                              "disposition": interval_status,
                              "reason_codes": interval["reason_codes"]})
    totals.update({"shift_rows": len(parsed), "malformed_shift_rows": malformed,
                   "exact_duplicate_intervals": exact_duplicates,
                   "duplicate_shift_chart": int(ratio_duplicate_chart),
                   "shift_toi_ratio_median": round(median_shift_ratio, 3),
                   "overlapping_players": len(overlapping_players),
                   "shift_players": len(players), "appeared_skaters": len(appeared_skater_ids),
                   "appeared_goalies": len(appeared_goalie_ids)})
    totals["appeared_skaters_missing_shift"] = len(appeared_skater_ids - players)
    totals["appeared_goalies_missing_shift"] = len(appeared_goalie_ids - players)
    totals["goalie_shift_toi_conflicts"] = sum(
        1 for pid in appeared_goalie_ids if player_status.get(pid) != "ACCEPT"
    )
    totals["skater_shift_toi_conflicts"] = sum(
        1 for pid in appeared_skater_ids if player_status.get(pid) != "ACCEPT"
    )
    totals.update({
        "skater_toi_compared": len(skater_deltas),
        "skater_toi_within_30s": sum(delta <= TOI_TOLERANCE_SECONDS for delta in skater_deltas),
        "skater_toi_over_60s": sum(delta > 60 for delta in skater_deltas),
        "skater_toi_max_delta_seconds": max(skater_deltas, default=0),
        "goalie_toi_compared": len(goalie_deltas),
        "goalie_toi_within_30s": sum(delta <= TOI_TOLERANCE_SECONDS for delta in goalie_deltas),
        "goalie_toi_over_60s": sum(delta > 60 for delta in goalie_deltas),
        "goalie_toi_max_delta_seconds": max(goalie_deltas, default=0),
    })
    shift_goalies_by_team: dict[str, set[int]] = collections.defaultdict(set)
    for interval in parsed:
        if interval["player_id"] in appeared_goalie_ids and interval["team_abbrev"]:
            shift_goalies_by_team[interval["team_abbrev"]].add(interval["player_id"])
    totals["shift_goalie_teams_with_substitution"] = sum(
        len(goalie_ids) > 1 for goalie_ids in shift_goalies_by_team.values()
    )
    totals["shift_goalie_substitution_teams_json"] = json.dumps(
        {team: sorted(goalie_ids) for team, goalie_ids in sorted(shift_goalies_by_team.items())
         if len(goalie_ids) > 1}, sort_keys=True)
    totals["shift_intervals_eligible"] = 0
    totals["shift_intervals_quarantined"] = 0
    totals["shift_intervals_rejected"] = 0
    for row in parsed:
        pid = row["player_id"]
        disposition = player_status.get(pid, "QUARANTINE")
        if row["row_id"] in overlapping_rows or chart_duplicate or pid in team_mismatch_players:
            disposition = "REJECT"
        key = {"ACCEPT": "shift_intervals_eligible", "QUARANTINE": "shift_intervals_quarantined",
               "REJECT": "shift_intervals_rejected"}.get(disposition)
        if key:
            totals[key] += 1
    return parsed, dict(totals)


def player_shift_at_event(intervals: list[dict], player_id: int, period: int, second: int,
                          chart_verified: bool) -> str:
    if not chart_verified:
        return "NO_VERIFIED_SHIFT_CHART"
    relevant = [row for row in intervals
                if row["player_id"] == player_id and row["period"] == period]
    active = [row for row in relevant if row["start"] <= second < row["end"]]
    if any(row.get("disposition") == "ACCEPT" for row in active):
        return "ON_ACCEPTED_SHIFT"
    if active:
        return "ON_UNTRUSTED_SHIFT"
    if any(min(abs(second - row["start"]), abs(second - row["end"])) <= 1 for row in relevant):
        return "BOUNDARY_AMBIGUOUS"
    return "OFF_SHIFT"


def goalie_shift_at_event(intervals: list[dict], goalie_id: int | None, period: int, second: int,
                          owner_side: str | None, frame_home: str, frame_away: str,
                          official_goalies: dict[int, dict], chart_verified: bool) -> str:
    if goalie_id is None:
        return "NO_DIRECT_GOALIE_ID"
    if not chart_verified:
        return "NO_VERIFIED_SHIFT_CHART"
    defending_team = frame_away if owner_side == "home" else frame_home if owner_side == "away" else ""
    active = [row for row in intervals if row["period"] == period
              and row["start"] <= second < row["end"]
              and row["team_abbrev"] == defending_team
              and row["player_id"] in official_goalies]
    direct = [row for row in active if row["player_id"] == goalie_id]
    if any(row.get("disposition") == "ACCEPT" for row in direct):
        return "DIRECT_ID_MATCHES_ACCEPTED_SHIFT"
    if any(row.get("disposition") != "ACCEPT" for row in direct):
        return "DIRECT_ID_ON_UNTRUSTED_SHIFT"
    if any(row.get("disposition") == "ACCEPT" for row in active):
        return "DIRECT_ID_DIFFERS_FROM_ACCEPTED_GOALIE_SHIFT"
    relevant = [row for row in intervals if row["period"] == period
                and row["team_abbrev"] == defending_team and row["player_id"] == goalie_id]
    if any(min(abs(second - row["start"]), abs(second - row["end"])) <= 1 for row in relevant):
        return "BOUNDARY_AMBIGUOUS"
    return "NO_GOALIE_SHIFT_AT_EVENT"


def situation_shift_at_event(intervals: list[dict], period: int, second: int, code: str,
                             home_id: int, away_id: int, frame_home: str, frame_away: str,
                             official_goalies: dict[int, dict], chart_verified: bool) -> str:
    if not chart_verified:
        return "NO_VERIFIED_SHIFT_CHART"
    if not isinstance(code, str) or len(code) != 4 or not code.isdigit():
        return "NO_VALID_SITUATION_CODE"
    active = [row for row in intervals if row["period"] == period
              and row["start"] <= second < row["end"]]
    if any(row.get("disposition") != "ACCEPT" for row in active):
        return "DEPLOYMENT_UNTRUSTED"
    if not active:
        return "NO_SHIFT_COVERAGE"
    by_team = {frame_home: set(), frame_away: set()}
    for row in active:
        if row["team_abbrev"] in by_team:
            by_team[row["team_abbrev"]].add(row["player_id"])
    home_players, away_players = by_team[frame_home], by_team[frame_away]
    home_goalies = sum(pid in official_goalies for pid in home_players)
    away_goalies = sum(pid in official_goalies for pid in away_players)
    observed = (away_goalies, len(away_players) - away_goalies,
                len(home_players) - home_goalies, home_goalies)
    expected = tuple(int(ch) for ch in code)
    if observed == expected:
        return "MATCH"
    if any(row["period"] == period
           and min(abs(second - row["start"]), abs(second - row["end"])) <= 1
           for row in intervals):
        return "BOUNDARY_AMBIGUOUS"
    return "MISMATCH"


def analyze_game(frame_row: dict, pbp_record: dict, shift_record: dict,
                 official_sides: dict[str, dict], official_skaters: dict[int, dict],
                 official_goalies: dict[int, dict], approved_labels: list,
                 event_writer: CsvGzipWriter, shift_writer: CsvGzipWriter,
                 target_writer: CsvGzipWriter, issue_writer: CsvGzipWriter,
                 reason_counts: collections.Counter, issue_games: dict[str, set[str]]) -> dict:
    gid, season = frame_row["game_id"], str(frame_row["season"])
    pbp = pbp_record["payload"] if pbp_record else None
    shift_payload = shift_record["payload"] if shift_record else None
    metric = {"game_id": gid, "season": int(season), "pbp_verified": bool(pbp),
              "shifts_verified": bool(shift_payload)}
    if not pbp:
        make_issue(issue_writer, reason_counts, issue_games, season, gid, "pbp", "PBP_NOT_VERIFIED",
                   "game", gid, "play-by-play body did not pass full source verification", "REJECT")
        return metric
    official_sides = official_sides or {}
    home, away = pbp.get("homeTeam") or {}, pbp.get("awayTeam") or {}
    home_id, away_id = numeric_id(home.get("id")), numeric_id(away.get("id"))
    home_abbrev, away_abbrev = team_abbrev(pbp, "home"), team_abbrev(pbp, "away")
    frame_home, frame_away = frame_row["home_team"], frame_row["away_team"]
    official_home, official_away = official_sides.get("home"), official_sides.get("away")
    identity_issues = []
    if home_id is None or away_id is None or home_id == away_id:
        identity_issues.append("PBP_TEAM_ID_INVALID")
    if home_abbrev != frame_home or away_abbrev != frame_away:
        identity_issues.append("PBP_FRAME_TEAM_IDENTITY_MISMATCH")
    if pbp.get("gameDate") != frame_row["game_date"]:
        identity_issues.append("PBP_GAME_DATE_MISMATCH")
    expected_season_api = f"{int(season)}{int(season) + 1}"
    if str(pbp.get("season")) != expected_season_api:
        identity_issues.append("PBP_SEASON_IDENTITY_MISMATCH")
    if not official_home or not official_away:
        identity_issues.append("OFFICIAL_TEAM_SIDE_MISSING")
    elif (official_home["team"] != frame_home or official_away["team"] != frame_away):
        identity_issues.append("OFFICIAL_FRAME_TEAM_IDENTITY_MISMATCH")
    if official_home and official_away:
        if (official_home.get("game_type") != "2" or official_away.get("game_type") != "2"
                or official_home.get("game_state") != "OFF" or official_away.get("game_state") != "OFF"):
            identity_issues.append("OFFICIAL_GAME_NOT_FINAL_REGULAR_SEASON")
        if (official_home.get("game_date") != frame_row["game_date"]
                or official_away.get("game_date") != frame_row["game_date"]):
            identity_issues.append("OFFICIAL_GAME_DATE_MISMATCH")
        if (official_home.get("canonical_score") != frame_row["canonical_home_score"]
                or official_away.get("canonical_score") != frame_row["canonical_away_score"]):
            identity_issues.append("OFFICIAL_SCORE_VS_CANONICAL_FRAME_MISMATCH")
    for code in identity_issues:
        make_issue(issue_writer, reason_counts, issue_games, season, gid, "identity", code,
                   "game", gid, f"pbp={home_abbrev}/{away_abbrev} frame={frame_home}/{frame_away}",
                   "QUARANTINE")
    team_identity_valid = not identity_issues
    embedded_score_issues = 0
    embedded_sog_issues = 0
    for side, pbp_team, side_row, frame_score in (
        ("home", home, official_home, frame_row["canonical_home_score"]),
        ("away", away, official_away, frame_row["canonical_away_score"]),
    ):
        if side_row is None:
            continue
        official_score_value = nonnegative_int(side_row.get("canonical_score") or side_row.get("score"))
        embedded_score = nonnegative_int(pbp_team.get("score"))
        expected_frame_score = nonnegative_int(frame_score)
        if (embedded_score is not None and official_score_value is not None
                and embedded_score != official_score_value):
            embedded_score_issues += 1
            make_issue(issue_writer, reason_counts, issue_games, season, gid, "score",
                       "PBP_EMBEDDED_SCORE_VS_OFFICIAL", "team", side,
                       f"pbp={embedded_score} official={official_score_value}", "QUARANTINE")
        if (official_score_value is not None and expected_frame_score is not None
                and official_score_value != expected_frame_score):
            embedded_score_issues += 1
        official_sog_value = nonnegative_int(side_row.get("team_sog"))
        embedded_sog = nonnegative_int(pbp_team.get("sog"))
        if (embedded_sog is not None and official_sog_value is not None
                and embedded_sog != official_sog_value):
            embedded_sog_issues += 1
            make_issue(issue_writer, reason_counts, issue_games, season, gid, "sog",
                       "PBP_EMBEDDED_SOG_VS_OFFICIAL", "team", side,
                       f"pbp={embedded_sog} official={official_sog_value}", "QUARANTINE")
    roster = pbp.get("rosterSpots") or []
    roster_by_player = {}
    for row in roster:
        pid = numeric_id(row.get("playerId"))
        if pid is not None:
            roster_by_player.setdefault(pid, row)
    roster_ids = set(roster_by_player)
    shift_stats = {}
    parsed_shifts = []
    if shift_payload:
        team_to_id = {home_abbrev: home_id, away_abbrev: away_id}
        parsed_shifts, shift_stats = parse_shift_rows(
            shift_payload, season, gid, shift_writer, issue_writer, reason_counts, issue_games,
            official_skaters, official_goalies, roster_ids, team_to_id)
    else:
        make_issue(issue_writer, reason_counts, issue_games, season, gid, "deployment",
                   "SHIFT_CHART_NOT_VERIFIED", "game", gid,
                   "shift body did not pass full source verification", "QUARANTINE")
    owner_side = {team_id: side for team_id, side in ((home_id, "home"), (away_id, "away"))
                  if team_id is not None}
    plays = pbp.get("plays") or []
    timeline_quality = timeline_sequence_quality(plays)
    period_join_trusted = (timeline_quality["sort_order_issue_count"] == 0
                           and timeline_quality["period_number_regressions"] == 0)
    metric["sort_order_issue_count"] = timeline_quality["sort_order_issue_count"]
    metric["period_number_sequence_regressions"] = timeline_quality["period_number_regressions"]
    if timeline_quality["sort_order_issue_count"]:
        make_issue(issue_writer, reason_counts, issue_games, season, gid, "timeline",
                   "PBP_SORT_ORDER_SEQUENCE_INVALID", "game", gid,
                   f"invalid_or_nonincreasing_sort_order_events={timeline_quality['sort_order_issue_count']}; event order quarantined",
                   "QUARANTINE")
    if timeline_quality["period_number_regressions"]:
        make_issue(issue_writer, reason_counts, issue_games, season, gid, "timeline",
                   "PBP_PERIOD_NUMBER_SEQUENCE_REGRESSION", "game", gid,
                   f"regressions={timeline_quality['period_number_regressions']}; preserve sortOrder, quarantine period-number joins",
                   "QUARANTINE")
    event_ids = collections.Counter(str(play.get("eventId")) for play in plays if play.get("eventId") is not None)
    counts = collections.Counter()
    period_goal_counts = collections.Counter()
    period_sog_counts = collections.Counter()
    player_sog = collections.Counter()
    goalie_events = collections.defaultdict(collections.Counter)
    direct_goalie_shot_events = []
    shooter_shift_alignment = collections.Counter()
    goalie_shift_alignment = collections.Counter()
    situation_shift_alignment = collections.Counter()
    shooter_on_ice_dispositions = collections.Counter()
    goalie_shift_comparison_dispositions = collections.Counter()
    situation_deployment_dispositions = collections.Counter()
    event_owner_issues = 0
    shooter_identity_issues = 0
    goalie_identity_issues = 0
    timeline_invalid = 0
    score_event_integrity_issues = 0
    sog_event_integrity_issues = 0
    penalty_identity_issues = 0
    period_types = collections.Counter()
    strength_states = collections.Counter()
    empty_net_events = 0
    event_rows_count = 0
    for index, play in enumerate(plays):
        kind = str(play.get("typeDescKey") or "")
        details = play.get("details") or {}
        period, period_type = period_parts(play)
        ordinary_period = period_type in {"REG", "OT"}
        clock = clock_seconds(play.get("timeInPeriod"))
        owner = numeric_id(details.get("eventOwnerTeamId"))
        owner_valid = owner in owner_side
        source_event_id = str(play.get("eventId") if play.get("eventId") is not None else f"missing-{index}")
        reasons = []
        core_reasons = []
        if timeline_quality["sort_order_issue_count"]:
            reasons.append("PBP_SORT_ORDER_SEQUENCE_INVALID")
        if timeline_quality["period_number_regressions"]:
            reasons.append("PBP_PERIOD_NUMBER_SEQUENCE_REGRESSION")
        if period is None or clock is None:
            reasons.append("EVENT_TIMELINE_INVALID")
            core_reasons.append("EVENT_TIMELINE_INVALID")
            timeline_invalid += 1
        if play.get("eventId") is None:
            reasons.append("EVENT_ID_MISSING")
            core_reasons.append("EVENT_ID_MISSING")
        elif event_ids[source_event_id] > 1:
            reasons.append("DUPLICATE_EVENT_ID")
            core_reasons.append("DUPLICATE_EVENT_ID")
        if not kind:
            reasons.append("EVENT_TYPE_MISSING")
            core_reasons.append("EVENT_TYPE_MISSING")
        if kind in SHOT_TYPES or kind == "penalty":
            if not owner_valid:
                reasons.append("EVENT_OWNER_TEAM_UNKNOWN")
                event_owner_issues += 1
        owner_team = ""
        if owner_valid:
            owner_team = "home" if owner == home_id else "away"
        shooter = numeric_id(details.get("shootingPlayerId"))
        scorer = numeric_id(details.get("scoringPlayerId"))
        credited_shooter = shooter if shooter is not None else (scorer if kind == "goal" else None)
        actor_identity = "NOT_APPLICABLE"
        if kind in SHOT_TYPES:
            counts["shots_direct_shooter_id"] += shooter is not None
            counts["shots_goal_scorer_fallback"] += shooter is None and kind == "goal" and scorer is not None
            counts["shots_shooter_missing"] += credited_shooter is None
            if credited_shooter is None:
                actor_identity = "MISSING"
                reasons.append("SHOT_SHOOTER_ID_MISSING")
                shooter_identity_issues += 1
            elif credited_shooter not in roster_ids:
                actor_identity = "NOT_IN_PBP_ROSTER"
                reasons.append("SHOT_SHOOTER_ID_NOT_IN_ROSTER")
                shooter_identity_issues += 1
            elif (credited_shooter not in official_skaters
                  or official_skaters[credited_shooter].get("appeared") != "1"
                  or official_skaters[credited_shooter].get("identity_status") != "OK"):
                actor_identity = "NOT_IN_OFFICIAL_SKATER_APPEARANCES"
                reasons.append("SHOT_SHOOTER_ID_NOT_IN_OFFICIAL_SKATERS")
                shooter_identity_issues += 1
            else:
                official_actor = official_skaters[credited_shooter]
                event_owner_abbrev = frame_home if owner_side.get(owner) == "home" else frame_away
                if owner_valid and official_actor.get("team") != event_owner_abbrev:
                    actor_identity = "TEAM_MISMATCH"
                    reasons.append("SHOT_SHOOTER_EVENT_OWNER_TEAM_MISMATCH")
                    shooter_identity_issues += 1
                else:
                    actor_identity = "ACCEPT_GOAL_SCORER_FALLBACK" if shooter is None else "ACCEPT_DIRECT"
        goalie_id = numeric_id(details.get("goalieInNetId"))
        duration_minutes = None
        penalty_committed_id = numeric_id(details.get("committedByPlayerId"))
        penalty_drawn_id = numeric_id(details.get("drawnByPlayerId"))
        penalty_served_id = numeric_id(details.get("servedByPlayerId"))
        penalty_identity_status = "NOT_APPLICABLE"
        penalty_identity_disposition = "NOT_APPLICABLE"
        goalie_identity = "NOT_APPLICABLE"
        situation = play.get("situationCode")
        state = base.strength_class(situation)
        if state:
            digits = str(situation)
            if period_type == "SO":
                counts["strength_state_shootout_events_excluded"] += 1
            elif ordinary_period:
                strength_states[state] += 1
            else:
                counts["strength_state_unknown_period_events_excluded"] += 1
            if ordinary_period and len(digits) == 4 and (digits[0] == "0" or digits[3] == "0"):
                empty_net_events += 1
        if period_type in PBP_PERIOD_TYPES:
            period_types[period_type] += 1
        if kind in SHOT_TYPES and goalie_id is not None:
            official_goalie = official_goalies.get(goalie_id)
            if (goalie_id not in roster_ids or official_goalie is None
                    or official_goalie.get("appeared") != "1"
                    or official_goalie.get("identity_status") != "OK"):
                goalie_identity = "NOT_IN_OFFICIAL_GOALIES"
                reasons.append("SHOT_EVENT_GOALIE_ID_NOT_IN_OFFICIAL_APPEARANCES")
                goalie_identity_issues += 1
            elif not owner_valid:
                goalie_identity = "EVENT_OWNER_UNVERIFIABLE"
                reasons.append("SHOT_EVENT_GOALIE_OWNER_UNVERIFIABLE")
                goalie_identity_issues += 1
            elif official_goalie.get("team") == (frame_home if owner_side[owner] == "home" else frame_away):
                goalie_identity = "TEAM_MISMATCH"
                reasons.append("SHOT_EVENT_GOALIE_TEAM_EQUALS_SHOOTER_TEAM")
                goalie_identity_issues += 1
            else:
                goalie_identity = "ACCEPT_DIRECT_EVENT_ID"
                if (team_identity_valid and ordinary_period and play.get("eventId") is not None
                        and event_ids[source_event_id] == 1 and period is not None and clock is not None):
                    defending_side = "away" if owner_side[owner] == "home" else "home"
                    direct_goalie_shot_events.append((period, clock, index, goalie_id, defending_side))
        if kind in SOG_TYPES and ordinary_period:
            if goalie_id is None:
                expected_empty = detail.expected_goalie_presence(play, home_id or -1, away_id or -1) is False
                goalie_identity = "EXPECTED_EMPTY_NET" if expected_empty else "MISSING_UNEXPLAINED"
                if not expected_empty:
                    reasons.append("ON_TARGET_GOALIE_ID_MISSING_UNEXPLAINED")
                    goalie_identity_issues += 1
        shooter_shift_status = "NOT_APPLICABLE"
        goalie_shift_status = "NOT_APPLICABLE"
        situation_shift_status = "NOT_APPLICABLE"
        if kind in SHOT_TYPES and period_type == "SO":
            shooter_shift_status = "NOT_APPLICABLE_SHOOTOUT"
            goalie_shift_status = "NOT_APPLICABLE_SHOOTOUT"
            situation_shift_status = "NOT_APPLICABLE_SHOOTOUT"
        elif kind in SHOT_TYPES and period is not None and clock is not None:
            if not period_join_trusted:
                if credited_shooter is not None:
                    shooter_shift_status = "PBP_PERIOD_NUMBER_UNTRUSTED"
                    shooter_shift_alignment[shooter_shift_status] += 1
                if goalie_id is not None:
                    goalie_shift_status = "PBP_PERIOD_NUMBER_UNTRUSTED"
                    goalie_shift_alignment[goalie_shift_status] += 1
            elif credited_shooter is not None:
                shooter_shift_status = player_shift_at_event(
                    parsed_shifts, credited_shooter, period, clock, bool(shift_payload))
                shooter_shift_alignment[shooter_shift_status] += 1
                if shooter_shift_status == "OFF_SHIFT" and actor_identity.startswith("ACCEPT"):
                    reasons.append("SHOOTER_REPORTED_OFF_ACCEPTED_SHIFT")
                elif shooter_shift_status == "ON_UNTRUSTED_SHIFT":
                    reasons.append("SHOOTER_EVENT_SHIFT_DEPLOYMENT_UNTRUSTED")
            if period_join_trusted and goalie_id is not None:
                goalie_shift_status = goalie_shift_at_event(
                    parsed_shifts, goalie_id, period, clock, owner_side.get(owner),
                    frame_home, frame_away, official_goalies, bool(shift_payload))
                goalie_shift_alignment[goalie_shift_status] += 1
                if goalie_shift_status == "DIRECT_ID_DIFFERS_FROM_ACCEPTED_GOALIE_SHIFT":
                    reasons.append("DIRECT_GOALIE_VS_SHIFT_CHART_MISMATCH")
                elif goalie_shift_status == "DIRECT_ID_ON_UNTRUSTED_SHIFT":
                    reasons.append("DIRECT_GOALIE_SHIFT_DEPLOYMENT_UNTRUSTED")
        if period is not None and clock is not None and ordinary_period:
            if not period_join_trusted:
                situation_shift_status = "PBP_PERIOD_NUMBER_UNTRUSTED"
            elif (base.strength_class(situation) is not None
                    and home_id is not None and away_id is not None):
                situation_shift_status = situation_shift_at_event(
                    parsed_shifts, period, clock, situation, home_id, away_id,
                    frame_home, frame_away, official_goalies, bool(shift_payload))
            else:
                situation_shift_status = "NO_VALID_SITUATION_CODE"
            situation_shift_alignment[situation_shift_status] += 1
            if situation_shift_status == "MISMATCH":
                reasons.append("SITUATION_CODE_VS_SHIFT_CHART_MISMATCH")
        shooter_on_ice_disposition = "NOT_APPLICABLE"
        goalie_shift_comparison_disposition = "NOT_APPLICABLE"
        situation_deployment_disposition = "NOT_APPLICABLE"
        if kind in SHOT_TYPES:
            if period_type == "SO":
                shooter_on_ice_disposition = "NOT_APPLICABLE_SHOOTOUT"
                goalie_shift_comparison_disposition = "NOT_APPLICABLE_SHOOTOUT"
            else:
                shooter_on_ice_disposition = (
                    "ACCEPT" if actor_identity.startswith("ACCEPT")
                    and shooter_shift_status == "ON_ACCEPTED_SHIFT" else "QUARANTINE")
                shooter_on_ice_dispositions[shooter_on_ice_disposition] += 1
                if goalie_id is not None:
                    goalie_shift_comparison_disposition = (
                        "ACCEPT" if goalie_shift_status == "DIRECT_ID_MATCHES_ACCEPTED_SHIFT"
                        else "QUARANTINE")
                    goalie_shift_comparison_dispositions[goalie_shift_comparison_disposition] += 1
        if period_type == "SO":
            situation_deployment_disposition = "NOT_APPLICABLE_SHOOTOUT"
        elif period is not None and clock is not None:
            situation_deployment_disposition = (
                "ACCEPT" if situation_shift_status == "MATCH" else "QUARANTINE")
            situation_deployment_dispositions[situation_deployment_disposition] += 1
        if kind in SHOT_TYPES:
            counts[kind] += 1
            if ordinary_period:
                counts["shot_events_ordinary"] += 1
            elif period_type == "SO":
                counts["shootout_shot_events"] += 1
            else:
                counts["shot_events_unknown_period_type"] += 1
            if finite_xy(details):
                counts["shots_with_xy"] += 1
                x, y = details.get("xCoord"), details.get("yCoord")
                if abs(x) > 100 or abs(y) > 42.5:
                    counts["shots_outside_rink_bounds"] += 1
                    reasons.append("SHOT_COORDINATES_OUTSIDE_RINK_BOUNDS")
            else:
                reasons.append("SHOT_COORDINATES_MISSING_OR_INVALID")
                counts["shots_without_xy"] += 1
            shot_type = details.get("shotType")
            if isinstance(shot_type, str) and shot_type:
                counts["shots_with_type"] += 1
                counts[f"shot_type:{shot_type}"] += 1
            elif kind == "blocked-shot":
                counts["blocked_shots_without_type"] += 1
            else:
                counts["unblocked_shots_without_type"] += 1
                reasons.append("UNBLOCKED_SHOT_TYPE_MISSING")
            if kind == "blocked-shot":
                counts["blocked_shots"] += 1
            else:
                counts["unblocked_shots"] += 1
            if kind in SOG_TYPES and ordinary_period:
                counts["on_target_ordinary"] += 1
                event_count_integrity_ok = (owner_valid and play.get("eventId") is not None
                                            and event_ids[source_event_id] == 1
                                            and period is not None and clock is not None)
                if not event_count_integrity_ok:
                    sog_event_integrity_issues += 1
                if event_count_integrity_ok:
                    period_sog_counts[owner_side[owner]] += 1
                if (credited_shooter is not None and actor_identity.startswith("ACCEPT")
                        and event_count_integrity_ok and team_identity_valid):
                    player_sog[credited_shooter] += 1
                if (goalie_id is not None and goalie_identity == "ACCEPT_DIRECT_EVENT_ID"
                        and event_count_integrity_ok and team_identity_valid):
                    key = "SAVES" if kind == "shot-on-goal" else "GOALS_AGAINST"
                    goalie_events[goalie_id][key] += 1
                    goalie_events[goalie_id]["SHOTS_AGAINST"] += 1
            if ordinary_period and credited_shooter is not None and actor_identity.startswith("ACCEPT"):
                counts["identified_ordinary_shot_events"] += 1
        if kind == "goal":
            counts["goals"] += 1
            if period_type == "REG":
                counts["regulation_goals"] += 1
            elif period_type == "OT":
                counts["overtime_goals"] += 1
            elif period_type == "SO":
                counts["shootout_goal_events"] += 1
            else:
                counts["goals_unknown_period_type"] += 1
            if (period_type != "SO" and owner_valid and play.get("eventId") is not None
                    and event_ids[source_event_id] == 1 and period is not None and clock is not None):
                period_goal_counts[owner_side[owner]] += 1
            elif period_type != "SO":
                score_event_integrity_issues += 1
        if kind == "penalty":
            counts["penalties"] += 1
            penalty_code = str(details.get("typeCode") or "")
            penalty_identity_status = "ACCEPT"
            if penalty_committed_id is None and penalty_code == "BEN":
                penalty_identity_status = "NOT_APPLICABLE_BENCH_PENALTY"
            elif penalty_committed_id is None:
                penalty_identity_status = "MISSING_COMMITTED_PLAYER"
                reasons.append("PENALTY_COMMITTED_PLAYER_MISSING")
                penalty_identity_issues += 1
            else:
                committed_row = official_skaters.get(penalty_committed_id)
                if (penalty_committed_id not in roster_ids or committed_row is None
                        or committed_row.get("appeared") != "1"
                        or committed_row.get("identity_status") != "OK"):
                    penalty_identity_status = "COMMITTED_PLAYER_ID_UNRESOLVED"
                    reasons.append("PENALTY_COMMITTED_PLAYER_ID_UNRESOLVED")
                    penalty_identity_issues += 1
                elif not owner_valid:
                    penalty_identity_status = "COMMITTED_PLAYER_OWNER_UNVERIFIABLE"
                    reasons.append("PENALTY_COMMITTED_PLAYER_OWNER_UNVERIFIABLE")
                    penalty_identity_issues += 1
                elif owner_valid and committed_row.get("team") != (frame_home if owner_side[owner] == "home" else frame_away):
                    penalty_identity_status = "COMMITTED_PLAYER_OWNER_TEAM_MISMATCH"
                    reasons.append("PENALTY_COMMITTED_PLAYER_OWNER_TEAM_MISMATCH")
                    penalty_identity_issues += 1
            if penalty_drawn_id is not None:
                drawn_row = official_skaters.get(penalty_drawn_id)
                expected_drawn_team = frame_away if owner_side.get(owner) == "home" else frame_home
                if (penalty_drawn_id not in roster_ids or drawn_row is None
                        or drawn_row.get("appeared") != "1"
                        or drawn_row.get("identity_status") != "OK"):
                    penalty_identity_status = "QUARANTINE"
                    reasons.append("PENALTY_DRAWN_PLAYER_ID_UNRESOLVED")
                    penalty_identity_issues += 1
                elif not owner_valid:
                    penalty_identity_status = "QUARANTINE"
                    reasons.append("PENALTY_DRAWN_PLAYER_OWNER_UNVERIFIABLE")
                    penalty_identity_issues += 1
                elif owner_valid and drawn_row.get("team") != expected_drawn_team:
                    penalty_identity_status = "QUARANTINE"
                    reasons.append("PENALTY_DRAWN_PLAYER_OWNER_TEAM_MISMATCH")
                    penalty_identity_issues += 1
            if penalty_served_id is not None:
                served_row = official_skaters.get(penalty_served_id)
                expected_serving_team = frame_home if owner_side.get(owner) == "home" else frame_away
                if (penalty_served_id not in roster_ids or served_row is None
                        or served_row.get("appeared") != "1"
                        or served_row.get("identity_status") != "OK"):
                    penalty_identity_status = "QUARANTINE"
                    reasons.append("PENALTY_SERVED_PLAYER_ID_UNRESOLVED")
                    penalty_identity_issues += 1
                elif not owner_valid:
                    penalty_identity_status = "QUARANTINE"
                    reasons.append("PENALTY_SERVED_PLAYER_OWNER_UNVERIFIABLE")
                    penalty_identity_issues += 1
                elif owner_valid and served_row.get("team") != expected_serving_team:
                    penalty_identity_status = "QUARANTINE"
                    reasons.append("PENALTY_SERVED_PLAYER_OWNER_TEAM_MISMATCH")
                    penalty_identity_issues += 1
            penalty_identity_disposition = (
                "NOT_APPLICABLE" if penalty_identity_status == "NOT_APPLICABLE_BENCH_PENALTY"
                else "ACCEPT" if penalty_identity_status == "ACCEPT" else "QUARANTINE")
            duration_value = details.get("duration")
            if isinstance(duration_value, (int, float)) and not isinstance(duration_value, bool):
                if math.isfinite(duration_value) and duration_value >= 0:
                    duration_minutes = float(duration_value)
            elif isinstance(duration_value, str):
                try:
                    parsed_duration = float(duration_value)
                    if math.isfinite(parsed_duration) and parsed_duration >= 0:
                        duration_minutes = parsed_duration
                except ValueError:
                    pass
            if duration_minutes is None:
                reasons.append("PENALTY_DURATION_MISSING_OR_INVALID")
                counts["penalties_duration_missing_invalid"] += 1
            else:
                counts["penalty_duration_minutes_sum"] += duration_minutes
                counts["penalties_with_duration"] += 1
            if period is None or clock is None:
                counts["penalties_timing_missing"] += 1
            if numeric_id(details.get("committedByPlayerId")) is None:
                counts["penalties_missing_committed_player"] += 1
        event_status = "ACCEPT" if not core_reasons else "QUARANTINE"
        if "DUPLICATE_EVENT_ID" in core_reasons:
            event_status = "REJECT"
        if kind in SHOT_TYPES:
            team_count_status = ("NOT_APPLICABLE_SHOOTOUT" if period_type == "SO" else
                                 "ACCEPT" if owner_valid and not core_reasons else "QUARANTINE")
            player_identity_status = ("ACCEPT" if actor_identity.startswith("ACCEPT") and owner_valid
                                      and not core_reasons else "QUARANTINE")
            in_bounds = (finite_xy(details) and abs(details["xCoord"]) <= 100
                         and abs(details["yCoord"]) <= 42.5)
            spatial_status = "ACCEPT" if in_bounds else "QUARANTINE"
            shot_type_value = details.get("shotType")
            shot_type_status = ("ACCEPT" if kind == "blocked-shot" and isinstance(shot_type_value, str) and shot_type_value else
                                "NOT_APPLICABLE_BLOCKED_SHOT_TYPE_ABSENT" if kind == "blocked-shot" else
                                "ACCEPT" if isinstance(shot_type_value, str) and shot_type_value else "QUARANTINE")
        else:
            team_count_status = player_identity_status = spatial_status = shot_type_status = "NOT_APPLICABLE"
        if kind in SOG_TYPES and ordinary_period:
            goalie_status = ("ACCEPT" if goalie_identity == "ACCEPT_DIRECT_EVENT_ID" else
                             goalie_identity if goalie_identity == "EXPECTED_EMPTY_NET" else "QUARANTINE")
        else:
            goalie_status = goalie_identity
        penalty_timing_status = ("ACCEPT" if period is not None and clock is not None else "QUARANTINE") if kind == "penalty" else "NOT_APPLICABLE"
        penalty_duration_status = ("ACCEPT" if duration_minutes is not None else "QUARANTINE") if kind == "penalty" else "NOT_APPLICABLE"
        event_writer.row({"game_id": gid, "season": season, "source_play_index": index,
                          "publisher_sort_order": play.get("sortOrder", ""),
                          "source_order_disposition": (
                              "ACCEPT" if timeline_quality["sort_order_issue_count"] == 0 else "QUARANTINE"),
                          "period_number_disposition": (
                              "ACCEPT" if period_join_trusted and period is not None else "QUARANTINE"),
                          "period_number_reason_code": (
                              "PBP_SORT_ORDER_SEQUENCE_INVALID"
                              if timeline_quality["sort_order_issue_count"] else
                              "PBP_PERIOD_NUMBER_SEQUENCE_REGRESSION"
                              if timeline_quality["period_number_regressions"] else
                              "EVENT_TIMELINE_INVALID" if period is None else ""),
                          "source_event_id": source_event_id,
                          "event_type": kind, "period_number": period or "", "period_type": period_type or "",
                          "time_in_period": play.get("timeInPeriod", ""), "event_owner_team_id": owner or "",
                          "event_owner_side": owner_team, "credited_shooter_id": credited_shooter or "",
                          "shooter_id_source": "shootingPlayerId" if shooter is not None else "scoringPlayerId_fallback" if scorer else "",
                          "shooter_identity_status": actor_identity, "goalie_in_net_id": goalie_id or "",
                          "goalie_identity_status": goalie_identity,
                          "shot_x": details.get("xCoord", "") if details.get("xCoord") is not None else "",
                          "shot_y": details.get("yCoord", "") if details.get("yCoord") is not None else "",
                          "shot_type": details.get("shotType", ""),
                          "zone_code": details.get("zoneCode", ""),
                          "miss_reason": details.get("reason", ""),
                          "situation_code": situation or "",
                          "strength_state": ("NOT_APPLICABLE_SHOOTOUT" if period_type == "SO"
                                             else state if ordinary_period else ""),
                          "ordinary_shot_eligible": (int(ordinary_period) if kind in SHOT_TYPES
                                                      and period_type in PBP_PERIOD_TYPES else ""),
                          "penalty_type_code": details.get("typeCode", ""),
                          "penalty_reason": details.get("descKey", ""),
                          "penalty_duration_minutes": duration_minutes if duration_minutes is not None else "",
                          "penalty_committed_by_player_id": penalty_committed_id or "",
                          "penalty_drawn_by_player_id": penalty_drawn_id or "",
                          "penalty_served_by_player_id": penalty_served_id or "",
                          "penalty_identity_status": penalty_identity_status,
                          "penalty_identity_disposition": penalty_identity_disposition,
                          "shooter_shift_status": shooter_shift_status,
                          "shooter_on_ice_disposition": shooter_on_ice_disposition,
                          "goalie_shift_status": goalie_shift_status,
                          "goalie_shift_comparison_disposition": goalie_shift_comparison_disposition,
                          "situation_shift_status": (situation_shift_status if period is not None and clock is not None
                                                      else "NO_TIMELINE"),
                          "situation_deployment_disposition": situation_deployment_disposition,
                          "event_disposition": event_status,
                          "team_count_disposition": team_count_status,
                          "player_identity_disposition": player_identity_status,
                          "spatial_model_disposition": spatial_status,
                          "shot_type_disposition": shot_type_status,
                          "goalie_event_disposition": goalie_status,
                          "penalty_timing_disposition": penalty_timing_status,
                          "penalty_duration_disposition": penalty_duration_status,
                          "reason_codes": ";".join(sorted(set(reasons)))})
        event_rows_count += 1
        for code in sorted(set(reasons)):
            make_issue(issue_writer, reason_counts, issue_games, season, gid, "event", code,
                       "event", source_event_id, f"type={kind} period={period} clock={play.get('timeInPeriod')}",
                       "REJECT" if code == "DUPLICATE_EVENT_ID" else "QUARANTINE")
    # Shot/SOG/goal official reconciliation uses ordinary events only. Shootout
    # events never contribute; the official shootout winner receives one goal.
    shootout = any(period_parts(play)[1] == "SO" for play in plays)
    official_score = {}
    official_sog = {}
    for side, side_row in (("home", official_sides.get("home")), ("away", official_sides.get("away"))):
        if side_row:
            official_score[side] = int(side_row["canonical_score"] or side_row["score"])
            official_sog[side] = int(side_row["team_sog"])
    pbp_adjusted_goals = apply_shootout_score_convention(
        period_goal_counts, official_score, shootout)
    if shootout and len(official_score) == 2:
        if official_score["home"] == official_score["away"]:
            score_event_integrity_issues += 1
            make_issue(issue_writer, reason_counts, issue_games, season, gid, "score",
                       "SHOOTOUT_WINNER_UNRESOLVED", "game", gid,
                       "official final score is tied despite a shootout period", "QUARANTINE")
    score_match = (len(official_score) == 2 and all(
        pbp_adjusted_goals.get(side, 0) == official_score[side] for side in ("home", "away")))
    sog_match = (len(official_sog) == 2 and all(
        period_sog_counts.get(side, 0) == official_sog[side] for side in ("home", "away")))
    if len(official_score) == 2:
        for side in ("home", "away"):
            if pbp_adjusted_goals.get(side, 0) != official_score[side]:
                make_issue(issue_writer, reason_counts, issue_games, season, gid, "score",
                           "PBP_GOALS_VS_OFFICIAL_SCORE", "team", side,
                           f"pbp_adjusted={pbp_adjusted_goals.get(side, 0)} official={official_score[side]}",
                           "QUARANTINE")
    if len(official_sog) == 2:
        for side in ("home", "away"):
            if period_sog_counts.get(side, 0) != official_sog[side]:
                make_issue(issue_writer, reason_counts, issue_games, season, gid, "sog",
                           "PBP_SOG_VS_OFFICIAL", "team", side,
                           f"pbp={period_sog_counts.get(side, 0)} official={official_sog[side]}",
                           "QUARANTINE")
    # Player event counts and direct event goalie attribution reconcile only to
    # label rows whose explicit approved purpose flags permit the comparison.
    label_by_player_stat = {(int(label.player_id), label.statistic): label for label in approved_labels}
    target_metrics = collections.Counter()
    for label in approved_labels:
        pid, stat = int(label.player_id), label.statistic
        if stat == "SOG":
            observed = player_sog.get(pid, 0)
        elif stat in {"SAVES", "SHOTS_AGAINST", "GOALS_AGAINST"}:
            observed = goalie_events.get(pid, {}).get(stat, 0)
        else:
            continue
        match = label.accepted_value is not None and observed == label.accepted_value
        purpose_eligibility = {purpose: status_label(label, purpose)
                               for purpose in ("training", "evaluation", "grading")}
        if label.quality_status in {"VERIFIED", "ADJUDICATED"} and label.accepted_value is not None and not match:
            make_issue(issue_writer, reason_counts, issue_games, season, gid, "target_reconciliation",
                       f"PBP_{stat}_VS_APPROVED_LABEL", "player_stat", f"{pid}/{stat}",
                       f"pbp_direct_event_count={observed} accepted_label={label.accepted_value} status={label.quality_status}",
                       "QUARANTINE")
        if any(purpose_eligibility.values()) and not match:
            target_disposition = "QUARANTINE"
        elif label.quality_status == "QUARANTINED":
            target_disposition = "REJECT"
        elif label.quality_status == "NOT_APPLICABLE":
            target_disposition = "NOT_APPLICABLE"
        elif match:
            target_disposition = "ACCEPT"
        else:
            target_disposition = "QUARANTINE"
        for purpose in ("training", "evaluation", "grading"):
            target_metrics[f"{stat}_{purpose}_label_rows"] += purpose_eligibility[purpose]
            target_metrics[f"{stat}_{purpose}_event_match_rows"] += purpose_eligibility[purpose] and match
            target_metrics[f"{stat}_{purpose}_event_eligible_rows"] += purpose_eligibility[purpose] and match
        target_writer.row({"game_id": gid, "season": season, "player_id": pid, "statistic": stat,
                           "official_value": label.official_value if label.official_value is not None else "",
                           "accepted_value": label.accepted_value if label.accepted_value is not None else "",
                           "quality_status": label.quality_status, "reason_code": label.reason_code,
                           "source_issue_id": label.source_issue_id,
                           "pbp_event_count": observed if pbp else "",
                           "event_count_match": int(match), "event_disposition": target_disposition,
                           "eligible_training": int(purpose_eligibility["training"] and match),
                           "eligible_evaluation": int(purpose_eligibility["evaluation"] and match),
                           "eligible_grading": int(purpose_eligibility["grading"] and match),
                           "official_boxscore_toi_seconds": (
                               official_goalies.get(pid, {}).get("toi_seconds", "") if stat != "SOG"
                               else official_skaters.get(pid, {}).get("toi_seconds", ""))})
    goalie_event_counts = collections.Counter()
    goalie_missing_expected_empty = goalie_missing_unexplained = 0
    for play in plays:
        if play.get("typeDescKey") not in SOG_TYPES or period_parts(play)[1] not in {"REG", "OT"}:
            continue
        details = play.get("details") or {}
        goalie_id = numeric_id(details.get("goalieInNetId"))
        if goalie_id is not None:
            goalie_event_counts["direct_goalie_attribution"] += 1
        elif detail.expected_goalie_presence(play, home_id or -1, away_id or -1) is False:
            goalie_missing_expected_empty += 1
        else:
            goalie_missing_unexplained += 1
    goalie_sequence_by_team: dict[str, list[tuple[int, int, int, int]]] = collections.defaultdict(list)
    for period, clock, event_index, goalie_id, defending_side in direct_goalie_shot_events:
        goalie_sequence_by_team[defending_side].append((period, clock, event_index, goalie_id))
    goalie_substitution_counts = {}
    for side, sequence in goalie_sequence_by_team.items():
        sequence.sort()
        goalie_substitution_counts[side] = sum(
            sequence[index][3] != sequence[index - 1][3]
            for index in range(1, len(sequence)))
    goalie_substitution_teams = {
        side: sorted({event[3] for event in sequence})
        for side, sequence in goalie_sequence_by_team.items()
        if len({event[3] for event in sequence}) > 1
    }
    metric.update({
        "pbp_team_identity_valid": team_identity_valid,
        "pbp_home_team_id": home_id or "", "pbp_away_team_id": away_id or "",
        "pbp_home_abbrev": home_abbrev, "pbp_away_abbrev": away_abbrev,
        "event_rows": event_rows_count,
        "shot_events": sum(counts[kind] for kind in SHOT_TYPES),
        "ordinary_shot_events": counts["shot_events_ordinary"],
        "shootout_shot_events": counts["shootout_shot_events"],
        "shot_events_unknown_period_type": counts["shot_events_unknown_period_type"],
        "goals_total_including_shootout": counts["goals"],
        "goals_regulation": counts["regulation_goals"], "goals_overtime": counts["overtime_goals"],
        "goals_shootout_events_excluded": counts["shootout_goal_events"],
        "goals_unknown_period_type": counts["goals_unknown_period_type"],
        "misses": counts["missed-shot"], "blocks": counts["blocked-shot"],
        "on_target_ordinary": counts["on_target_ordinary"],
        "shots_with_xy": counts["shots_with_xy"], "shots_without_xy": counts["shots_without_xy"],
        "shots_outside_rink_bounds": counts["shots_outside_rink_bounds"],
        "shots_with_type": counts["shots_with_type"],
        "shots_missing_type": counts["blocked_shots_without_type"] + counts["unblocked_shots_without_type"],
        "shots_direct_shooter_id": counts["shots_direct_shooter_id"],
        "shots_goal_scorer_fallback": counts["shots_goal_scorer_fallback"],
        "shots_shooter_missing": counts["shots_shooter_missing"],
        "blocked_shots": counts["blocked_shots"], "blocked_shots_without_type": counts["blocked_shots_without_type"],
        "unblocked_shots": counts["unblocked_shots"], "unblocked_shots_without_type": counts["unblocked_shots_without_type"],
        "shot_types_json": json.dumps({k.split(":", 1)[1]: v for k, v in sorted(counts.items()) if k.startswith("shot_type:")}, sort_keys=True),
        "shooter_event_shift_alignment_json": json.dumps(dict(sorted(shooter_shift_alignment.items())), sort_keys=True),
        "goalie_event_shift_alignment_json": json.dumps(dict(sorted(goalie_shift_alignment.items())), sort_keys=True),
        "situation_event_shift_alignment_json": json.dumps(dict(sorted(situation_shift_alignment.items())), sort_keys=True),
        "shooter_on_ice_dispositions_json": json.dumps(dict(sorted(shooter_on_ice_dispositions.items())), sort_keys=True),
        "goalie_shift_comparison_dispositions_json": json.dumps(dict(sorted(goalie_shift_comparison_dispositions.items())), sort_keys=True),
        "situation_deployment_dispositions_json": json.dumps(dict(sorted(situation_deployment_dispositions.items())), sort_keys=True),
        "shot_events_player_on_ice_eligible": shooter_on_ice_dispositions["ACCEPT"],
        "shot_events_player_on_ice_quarantined": shooter_on_ice_dispositions["QUARANTINE"],
        "shot_events_goalie_shift_match": goalie_shift_comparison_dispositions["ACCEPT"],
        "shot_events_goalie_shift_comparison_quarantined": goalie_shift_comparison_dispositions["QUARANTINE"],
        "events_situation_deployment_eligible": situation_deployment_dispositions["ACCEPT"],
        "events_situation_deployment_quarantined": situation_deployment_dispositions["QUARANTINE"],
        "shot_owner_identity_issues": event_owner_issues, "shot_player_identity_issues": shooter_identity_issues,
        "event_goalie_identity_issues": goalie_identity_issues,
        "on_target_goalie_direct_ids": goalie_event_counts["direct_goalie_attribution"],
        "shot_events_with_direct_goalie_id": sum(
            numeric_id((play.get("details") or {}).get("goalieInNetId")) is not None
            for play in plays if play.get("typeDescKey") in SHOT_TYPES),
        "shot_events_with_verified_direct_goalie_id": len(direct_goalie_shot_events),
        "goalie_substitution_changes_from_pbp_events": sum(goalie_substitution_counts.values()),
        "goalie_substitution_teams_from_pbp_events": len(goalie_substitution_teams),
        "goalie_substitution_ids_by_team_from_pbp_json": json.dumps(goalie_substitution_teams, sort_keys=True),
        "on_target_goalie_missing_expected_empty_net": goalie_missing_expected_empty,
        "on_target_goalie_missing_unexplained": goalie_missing_unexplained,
        "penalty_events": counts["penalties"], "penalties_with_duration": counts["penalties_with_duration"],
        "penalties_duration_missing_invalid": counts["penalties_duration_missing_invalid"],
        "penalties_timing_missing": counts["penalties_timing_missing"],
        "penalties_missing_committed_player": counts["penalties_missing_committed_player"],
        "penalties_identity_issues": penalty_identity_issues,
        "penalty_duration_minutes_sum": counts["penalty_duration_minutes_sum"],
        "strength_state_shootout_events_excluded": counts["strength_state_shootout_events_excluded"],
        "strength_state_unknown_period_events_excluded": counts["strength_state_unknown_period_events_excluded"],
        "strength_state_counts_json": json.dumps(dict(sorted(strength_states.items())), sort_keys=True),
        "empty_net_state_events": empty_net_events,
        "period_type_event_counts_json": json.dumps(dict(sorted(period_types.items())), sort_keys=True),
        "score_match_after_shootout_convention": int(score_match),
        "sog_match_excluding_shootout": int(sog_match),
        "team_score_target_disposition": "ACCEPT" if score_match and team_identity_valid and score_event_integrity_issues == 0 and embedded_score_issues == 0 else "QUARANTINE",
        "team_sog_target_disposition": "ACCEPT" if sog_match and team_identity_valid and sog_event_integrity_issues == 0 and embedded_sog_issues == 0 else "QUARANTINE",
        "score_event_integrity_issues": score_event_integrity_issues,
        "sog_event_integrity_issues": sog_event_integrity_issues,
        "pbp_embedded_score_issues": embedded_score_issues,
        "pbp_embedded_sog_issues": embedded_sog_issues,
        "official_home_score": official_score.get("home", ""), "pbp_home_score_adjusted": pbp_adjusted_goals.get("home", 0),
        "official_away_score": official_score.get("away", ""), "pbp_away_score_adjusted": pbp_adjusted_goals.get("away", 0),
        "official_home_sog": official_sog.get("home", ""), "pbp_home_sog": period_sog_counts.get("home", 0),
        "official_away_sog": official_sog.get("away", ""), "pbp_away_sog": period_sog_counts.get("away", 0),
        "shift_rows": shift_stats.get("shift_rows", 0), "shift_players": shift_stats.get("shift_players", 0),
        "skater_player_games_eligible": shift_stats.get("skater_player_games_eligible", 0),
        "goalie_player_games_eligible": shift_stats.get("goalie_player_games_eligible", 0),
        "skater_shift_toi_conflicts": shift_stats.get("skater_shift_toi_conflicts", 0),
        "goalie_shift_toi_conflicts": shift_stats.get("goalie_shift_toi_conflicts", 0),
        "shift_goalie_teams_with_substitution": shift_stats.get("shift_goalie_teams_with_substitution", 0),
        "shift_goalie_substitution_teams_json": shift_stats.get("shift_goalie_substitution_teams_json", "{}"),
        "skater_toi_compared": shift_stats.get("skater_toi_compared", 0),
        "skater_toi_within_30s": shift_stats.get("skater_toi_within_30s", 0),
        "skater_toi_over_60s": shift_stats.get("skater_toi_over_60s", 0),
        "skater_toi_max_delta_seconds": shift_stats.get("skater_toi_max_delta_seconds", 0),
        "goalie_toi_compared": shift_stats.get("goalie_toi_compared", 0),
        "goalie_toi_within_30s": shift_stats.get("goalie_toi_within_30s", 0),
        "goalie_toi_over_60s": shift_stats.get("goalie_toi_over_60s", 0),
        "goalie_toi_max_delta_seconds": shift_stats.get("goalie_toi_max_delta_seconds", 0),
        "duplicate_shift_intervals": shift_stats.get("exact_duplicate_intervals", 0),
        "duplicate_shift_charts": shift_stats.get("duplicate_shift_chart", 0),
        "median_shift_to_official_toi_ratio": shift_stats.get("shift_toi_ratio_median", 0),
        "overlapping_shift_players": shift_stats.get("overlapping_players", 0),
        "shift_intervals_eligible": shift_stats.get("shift_intervals_eligible", 0),
        "shift_intervals_quarantined": shift_stats.get("shift_intervals_quarantined", 0),
        "shift_intervals_rejected": shift_stats.get("shift_intervals_rejected", 0),
        "appeared_skaters_missing_shift": shift_stats.get("appeared_skaters_missing_shift", 0),
        "appeared_goalies_missing_shift": shift_stats.get("appeared_goalies_missing_shift", 0),
        "label_rows": len(approved_labels),
        **dict(target_metrics),
    })
    return metric


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def run(args) -> dict:
    frame_path = args.frame
    frame_hash = sha256_file(frame_path)
    if frame_hash != FRAME_SHA256:
        raise ValueError(f"CANONICAL_FRAME_HASH_MISMATCH expected={FRAME_SHA256} actual={frame_hash}")
    full_games_hash = sha256_file(args.full_frame_games)
    if full_games_hash != FULL_FRAME_GAMES_SHA256:
        raise ValueError(f"FULL_FRAME_GAMES_HASH_MISMATCH expected={FULL_FRAME_GAMES_SHA256} actual={full_games_hash}")
    frame = load_csv(frame_path)
    games = load_csv(args.full_frame_games)
    if len(frame) != 4876 or len(games) != 4876:
        raise ValueError(f"FULL_FRAME_ROW_COUNT_MISMATCH canonical={len(frame)} game_list={len(games)}")
    if len({row["game_id"] for row in frame}) != 4876 or len({row["game_id"] for row in games}) != 4876:
        raise ValueError("DUPLICATE_GAME_ID_IN_CANONICAL_OR_DERIVED_FRAME")
    frame_by_id = {row["game_id"]: row for row in frame}
    game_ids = [row["game_id"] for row in games]
    if set(game_ids) != set(frame_by_id):
        raise ValueError("DERIVED_FRAME_ID_SET_MISMATCH")
    for row in games:
        source = frame_by_id[row["game_id"]]
        if row["season"] != source["season"] or row["game_date"] != source["game_date"]:
            raise ValueError(f"DERIVED_FRAME_IDENTITY_MISMATCH {row['game_id']}")
    seasons = collections.Counter(int(row["season"]) for row in frame)
    expected_seasons = {2018: 1271, 2019: 1082, 2020: 868, 2021: 1312, 2022: 343}
    if dict(seasons) != expected_seasons:
        raise ValueError(f"CANONICAL_SEASON_COUNTS_MISMATCH {dict(sorted(seasons.items()))}")
    pbp_ids = [row["game_id"] for row in load_csv(args.pbp_games)]
    shift_ids = [row["game_id"] for row in load_csv(args.shift_games)]
    if pbp_ids != game_ids or shift_ids != game_ids:
        raise ValueError("SOURCE_SPECIFIC_GAME_LISTS_DO_NOT_MATCH_PINNED_FULL_FRAME")
    season_by_id = {row["game_id"]: row["season"] for row in frame}
    pbp_verified, pbp_issues, pbp_summary = verify_source(
        "pbp", game_ids, args.pbp_manifest, args.raw_root, season_by_id)
    shift_verified, shift_issues, shift_summary = verify_source(
        "shifts", game_ids, args.shift_manifest, args.raw_root, season_by_id)
    pbp_prior_summary, pbp_prior_issues = compare_prior_manifest(
        "pbp", game_ids, args.pbp_manifest, args.prior_pbp_manifest)
    shift_prior_summary, shift_prior_issues = compare_prior_manifest(
        "shifts", game_ids, args.shift_manifest, args.prior_shift_manifest)
    integrity_issues = pbp_issues + shift_issues + pbp_prior_issues + shift_prior_issues
    if integrity_issues and not args.allow_incomplete:
        raise ValueError(f"SOURCE_INTEGRITY_FAILURE issue_count={len(integrity_issues)}; see --allow-incomplete report")
    source_issues_by_key: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for issue in integrity_issues:
        source_issues_by_key[(issue["kind"], issue["game_id"])].append(issue["reason_code"])
    prior_issues_by_key: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for issue in pbp_prior_issues + shift_prior_issues:
        prior_issues_by_key[(issue["kind"], issue["game_id"])].append(issue["reason_code"])
    source_manifests = {
        "pbp": {row.get("game_id", ""): row for row in load_csv(args.pbp_manifest)},
        "shifts": {row.get("game_id", ""): row for row in load_csv(args.shift_manifest)},
    }
    prior_summaries = {"pbp": pbp_prior_summary, "shifts": shift_prior_summary}
    official_sides, official_skaters, official_goalies, official_hashes = load_official(set(game_ids))
    labels, label_statuses = load_research_labels(args.label_csv, args.label_summary, set(game_ids))
    for gid, game_labels in labels.items():
        source_game = frame_by_id[gid]
        for label in game_labels:
            if label.season != int(source_game["season"]) or label.game_date.isoformat() != source_game["game_date"]:
                raise ValueError(f"APPROVED_LABEL_FRAME_IDENTITY_MISMATCH {gid}/{label.player_id}/{label.statistic}")
    args.derived_out.mkdir(parents=True, exist_ok=True)
    source_writer = CsvGzipWriter(args.derived_out / "game_source_provenance.csv.gz", [
        "game_id", "season", "source_kind", "source_url", "http_status", "content_type",
        "payload_rows", "bytes_raw", "sha256_raw", "bytes_gz", "sha256_gz",
        "retrieved_at_utc", "attempts", "request_duration_seconds",
        "request_elapsed_with_pacing_seconds", "evidence_origin",
        "sample_event_manifest_sha256", "sample_source_commit", "source_identity_basis",
        "prior_manifest_sha256", "prior_manifest_disposition",
        "verification_disposition",
        "reason_codes", "canonical_frame_sha256", "full_frame_games_sha256", "audit_version"])
    for game in games:
        gid = game["game_id"]
        season = game["season"]
        for kind, verified_map in (("pbp", pbp_verified), ("shifts", shift_verified)):
            record = verified_map.get(gid)
            manifest_row = record["manifest"] if record else source_manifests[kind].get(gid, {})
            issue_codes = sorted(set(source_issues_by_key.get((kind, gid), [])))
            source_writer.row({
                "game_id": gid, "season": season, "source_kind": kind,
                "source_url": manifest_row.get("url", expected_url(kind, gid)),
                "http_status": manifest_row.get("http_status", ""),
                "content_type": manifest_row.get("content_type", ""),
                "payload_rows": manifest_row.get("rows", ""),
                "bytes_raw": manifest_row.get("bytes_raw", ""),
                "sha256_raw": manifest_row.get("sha256_raw", ""),
                "bytes_gz": manifest_row.get("bytes_gz", ""),
                "sha256_gz": manifest_row.get("sha256_gz", ""),
                "retrieved_at_utc": manifest_row.get("retrieved_at_utc", ""),
                "attempts": manifest_row.get("attempts", ""),
                "request_duration_seconds": manifest_row.get("request_duration_seconds", ""),
                "request_elapsed_with_pacing_seconds": manifest_row.get("request_elapsed_with_pacing_seconds", ""),
                "evidence_origin": manifest_row.get("evidence_origin", ""),
                "sample_event_manifest_sha256": manifest_row.get("sample_event_manifest_sha256", ""),
                "sample_source_commit": manifest_row.get("sample_source_commit", ""),
                "source_identity_basis": manifest_row.get("source_identity_basis", ""),
                "prior_manifest_sha256": prior_summaries[kind].get("manifest_sha256") or "",
                "prior_manifest_disposition": (
                    "NOT_PROVIDED" if not prior_summaries[kind].get("provided") else
                    "QUARANTINE" if prior_issues_by_key.get((kind, gid)) else "ACCEPT"
                ),
                "verification_disposition": ("REJECT" if not record else
                                             "QUARANTINE" if issue_codes else "ACCEPT"),
                "reason_codes": ";".join(issue_codes),
                "canonical_frame_sha256": frame_hash,
                "full_frame_games_sha256": full_games_hash,
                "audit_version": "nhl-fullframe-event-audit-2026-10-21-v1",
            })
    event_writer = CsvGzipWriter(args.derived_out / "event_dispositions.csv.gz", [
        "game_id", "season", "source_play_index", "publisher_sort_order", "source_order_disposition",
        "period_number_disposition", "period_number_reason_code", "source_event_id", "event_type",
        "period_number", "period_type",
        "time_in_period", "event_owner_team_id", "event_owner_side", "credited_shooter_id",
        "shooter_id_source", "shooter_identity_status", "goalie_in_net_id", "goalie_identity_status",
        "shooter_shift_status", "shooter_on_ice_disposition", "goalie_shift_status",
        "goalie_shift_comparison_disposition", "situation_shift_status", "situation_deployment_disposition",
        "shot_x", "shot_y", "shot_type", "zone_code", "miss_reason", "situation_code",
        "strength_state", "ordinary_shot_eligible", "penalty_type_code", "penalty_reason",
        "penalty_duration_minutes", "penalty_committed_by_player_id", "penalty_drawn_by_player_id",
        "penalty_served_by_player_id", "penalty_identity_status", "penalty_identity_disposition",
        "event_disposition",
        "team_count_disposition", "player_identity_disposition", "spatial_model_disposition",
        "shot_type_disposition", "goalie_event_disposition", "penalty_timing_disposition",
        "penalty_duration_disposition", "reason_codes"])
    shift_writer = CsvGzipWriter(args.derived_out / "player_shift_dispositions.csv.gz", [
        "game_id", "season", "player_id", "player_type", "interval_id", "period", "start_seconds",
        "end_seconds", "duration_seconds", "official_toi_seconds", "shift_toi_seconds_player_game",
        "toi_delta_seconds", "disposition", "reason_codes"])
    target_writer = CsvGzipWriter(args.derived_out / "target_reconciliation.csv.gz", [
        "game_id", "season", "player_id", "statistic", "official_value", "accepted_value",
        "quality_status", "reason_code", "source_issue_id", "pbp_event_count", "event_count_match",
        "event_disposition", "eligible_training", "eligible_evaluation", "eligible_grading",
        "official_boxscore_toi_seconds"])
    issue_writer = CsvGzipWriter(args.derived_out / "unresolved_issues.csv.gz", [
        "game_id", "season", "component", "reason_code", "subject_type", "subject_id", "detail",
        "disposition"])
    issue_counts = collections.Counter()
    issue_games: dict[str, set[str]] = collections.defaultdict(set)
    game_metrics = []
    for source_issue in integrity_issues:
        gid = source_issue["game_id"]
        season = frame_by_id.get(gid, {}).get("season", "")
        make_issue(issue_writer, issue_counts, issue_games, str(season), gid,
                   "pbp_source" if source_issue["kind"] == "pbp" else "shift_source",
                   source_issue["reason_code"], "game", gid, source_issue["detail"], "REJECT")
    try:
        for index, game in enumerate(games, 1):
            gid = game["game_id"]
            official_for_game = labels.get(gid, [])
            pbp_record = load_verified_payload("pbp", gid, pbp_verified.get(gid))
            shift_record = load_verified_payload("shifts", gid, shift_verified.get(gid))
            metric = analyze_game(
                frame_by_id[gid], pbp_record, shift_record,
                official_sides.get(gid, {}), official_skaters.get(gid, {}),
                official_goalies.get(gid, {}), official_for_game, event_writer, shift_writer,
                target_writer, issue_writer, issue_counts, issue_games)
            game_metrics.append(metric)
            if index % 500 == 0:
                print(f"audited {index}/{len(games)} games", flush=True)
    except BaseException:
        for writer in (source_writer, event_writer, shift_writer, target_writer, issue_writer):
            try:
                writer.abort()
            except Exception:
                pass
        raise
    for writer in (source_writer, event_writer, shift_writer, target_writer, issue_writer):
        writer.close()
    metric_fields = sorted({key for row in game_metrics for key in row})
    metrics_path = args.derived_out / "game_metrics.csv"
    temp = metrics_path.with_name(f".{metrics_path.name}.tmp.{os.getpid()}")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=metric_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(game_metrics)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, metrics_path)
    per_season = {}
    numeric_metrics = [key for key in metric_fields if key not in {
        "game_id", "season", "pbp_home_abbrev", "pbp_away_abbrev", "shot_types_json",
        "strength_state_counts_json", "period_type_event_counts_json",
        "shooter_event_shift_alignment_json", "goalie_event_shift_alignment_json",
        "situation_event_shift_alignment_json", "shooter_on_ice_dispositions_json",
        "goalie_shift_comparison_dispositions_json", "situation_deployment_dispositions_json"}]
    for season in sorted(seasons):
        rows = [row for row in game_metrics if row["season"] == season]
        item = {"games": len(rows)}
        for field in numeric_metrics:
            values = [row.get(field) for row in rows if isinstance(row.get(field), (int, float))]
            if values:
                item[field] = aggregate_season_metric(field, values)
        item["games_score_reconciled"] = sum(row.get("score_match_after_shootout_convention") == 1 for row in rows)
        item["games_sog_reconciled"] = sum(row.get("sog_match_excluding_shootout") == 1 for row in rows)
        item["pbp_verified_games"] = sum(row.get("pbp_verified") is True for row in rows)
        item["shift_verified_games"] = sum(row.get("shifts_verified") is True for row in rows)
        type_counts = collections.Counter()
        strength_counts = collections.Counter()
        period_counts = collections.Counter()
        shooter_alignment = collections.Counter()
        goalie_alignment = collections.Counter()
        situation_alignment = collections.Counter()
        shooter_on_ice_dispositions = collections.Counter()
        goalie_shift_comparison_dispositions = collections.Counter()
        situation_deployment_dispositions = collections.Counter()
        for row in rows:
            for key, value in json.loads(row.get("shot_types_json") or "{}").items():
                type_counts[key] += value
            for key, value in json.loads(row.get("strength_state_counts_json") or "{}").items():
                strength_counts[key] += value
            for key, value in json.loads(row.get("period_type_event_counts_json") or "{}").items():
                period_counts[key] += value
            for key, value in json.loads(row.get("shooter_event_shift_alignment_json") or "{}").items():
                shooter_alignment[key] += value
            for key, value in json.loads(row.get("goalie_event_shift_alignment_json") or "{}").items():
                goalie_alignment[key] += value
            for key, value in json.loads(row.get("situation_event_shift_alignment_json") or "{}").items():
                situation_alignment[key] += value
            for key, value in json.loads(row.get("shooter_on_ice_dispositions_json") or "{}").items():
                shooter_on_ice_dispositions[key] += value
            for key, value in json.loads(row.get("goalie_shift_comparison_dispositions_json") or "{}").items():
                goalie_shift_comparison_dispositions[key] += value
            for key, value in json.loads(row.get("situation_deployment_dispositions_json") or "{}").items():
                situation_deployment_dispositions[key] += value
        item["shot_type_counts"] = dict(sorted(type_counts.items()))
        item["strength_state_event_counts"] = dict(sorted(strength_counts.items()))
        item["period_type_event_counts"] = dict(sorted(period_counts.items()))
        item["shooter_event_shift_alignment_counts"] = dict(sorted(shooter_alignment.items()))
        item["goalie_event_shift_alignment_counts"] = dict(sorted(goalie_alignment.items()))
        item["situation_event_shift_alignment_counts"] = dict(sorted(situation_alignment.items()))
        item["shooter_on_ice_disposition_counts"] = dict(sorted(shooter_on_ice_dispositions.items()))
        item["goalie_shift_comparison_disposition_counts"] = dict(sorted(goalie_shift_comparison_dispositions.items()))
        item["situation_deployment_disposition_counts"] = dict(sorted(situation_deployment_dispositions.items()))
        shot_denominator = item.get("shot_events", 0)
        item["shot_field_coverage"] = {
            "coordinates_present": item.get("shots_with_xy", 0),
            "coordinates_missing": item.get("shots_without_xy", 0),
            "coordinates_pct": round(100 * item.get("shots_with_xy", 0) / shot_denominator, 6) if shot_denominator else None,
            "shot_type_present": item.get("shots_with_type", 0),
            "shot_type_missing": item.get("shots_missing_type", 0),
            "shot_type_pct": round(100 * item.get("shots_with_type", 0) / shot_denominator, 6) if shot_denominator else None,
        }
        item["eligible_model_populations"] = {
            "team_scoring_games": {
                "candidate_games": sum(bool(row.get("pbp_verified")) for row in rows),
                "eligible_games": sum(row.get("team_score_target_disposition") == "ACCEPT" for row in rows),
                "quarantined_games": sum(row.get("team_score_target_disposition") == "QUARANTINE" for row in rows),
            },
            "team_sog_games": {
                "candidate_games": sum(bool(row.get("pbp_verified")) for row in rows),
                "eligible_games": sum(row.get("team_sog_target_disposition") == "ACCEPT" for row in rows),
                "quarantined_games": sum(row.get("team_sog_target_disposition") == "QUARANTINE" for row in rows),
            },
            "player_shift_intervals": {
                key: sum(row.get(key, 0) for row in rows)
                for key in ("shift_intervals_eligible", "shift_intervals_quarantined",
                            "shift_intervals_rejected", "skater_player_games_eligible",
                            "goalie_player_games_eligible")
            },
            "shot_event_player_on_ice_attribution": {
                "eligible": sum(row.get("shot_events_player_on_ice_eligible", 0) for row in rows),
                "quarantined": sum(row.get("shot_events_player_on_ice_quarantined", 0) for row in rows),
                "shift_alignment_status_counts": {
                    status: sum(json.loads(row.get("shooter_event_shift_alignment_json") or "{}").get(status, 0)
                                for row in rows)
                    for status in ("ON_ACCEPTED_SHIFT", "OFF_SHIFT", "BOUNDARY_AMBIGUOUS",
                                   "ON_UNTRUSTED_SHIFT", "NO_VERIFIED_SHIFT_CHART")
                },
            },
            "direct_goalie_event_vs_shift_alignment": {
                "accepted_direct_id_and_accepted_shift_match": sum(
                    row.get("shot_events_goalie_shift_match", 0) for row in rows),
                "quarantined_comparison": sum(
                    row.get("shot_events_goalie_shift_comparison_quarantined", 0) for row in rows),
                "alignment_status_counts": {
                    status: sum(json.loads(row.get("goalie_event_shift_alignment_json") or "{}").get(status, 0)
                                for row in rows)
                    for status in ("DIRECT_ID_MATCHES_ACCEPTED_SHIFT",
                                   "DIRECT_ID_DIFFERS_FROM_ACCEPTED_GOALIE_SHIFT",
                                   "DIRECT_ID_ON_UNTRUSTED_SHIFT", "NO_GOALIE_SHIFT_AT_EVENT",
                                   "BOUNDARY_AMBIGUOUS", "NO_VERIFIED_SHIFT_CHART")
                },
            },
            "situation_code_vs_shift_alignment": {
                "eligible_state_matches": sum(row.get("events_situation_deployment_eligible", 0) for row in rows),
                "quarantined_state_events": sum(row.get("events_situation_deployment_quarantined", 0) for row in rows),
                "alignment_status_counts": {
                    status: sum(json.loads(row.get("situation_event_shift_alignment_json") or "{}").get(status, 0)
                                for row in rows)
                    for status in ("MATCH", "MISMATCH", "BOUNDARY_AMBIGUOUS", "DEPLOYMENT_UNTRUSTED",
                                   "NO_SHIFT_COVERAGE", "NO_VERIFIED_SHIFT_CHART",
                                   "NO_VALID_SITUATION_CODE")
                },
            },
            "approved_player_targets": {
                statistic: {
                    purpose: {
                        "approved_eligible_label_rows": sum(
                            row.get(f"{statistic}_{purpose}_label_rows", 0) for row in rows),
                        "event_count_matches": sum(
                            row.get(f"{statistic}_{purpose}_event_match_rows", 0) for row in rows),
                        "model_eligible_rows": sum(
                            row.get(f"{statistic}_{purpose}_event_eligible_rows", 0) for row in rows),
                    }
                    for purpose in ("training", "evaluation", "grading")
                }
                for statistic in ("SOG", "SAVES", "SHOTS_AGAINST", "GOALS_AGAINST")
            },
        }
        per_season[str(season)] = item
    artifact_paths = [args.derived_out / name for name in (
        "game_source_provenance.csv.gz", "event_dispositions.csv.gz", "player_shift_dispositions.csv.gz",
        "target_reconciliation.csv.gz", "unresolved_issues.csv.gz", "game_metrics.csv")]
    artifact_hashes = {path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
                       for path in artifact_paths}
    total_shots = sum(row.get("shot_events", 0) for row in game_metrics)
    total_location_missing = sum(row.get("shots_without_xy", 0) for row in game_metrics)
    total_unblocked_missing_type = sum(row.get("unblocked_shots_without_type", 0) for row in game_metrics)
    blocked_shots = sum(row.get("blocked_shots", 0) for row in game_metrics)
    blocked_missing_type = sum(row.get("blocked_shots_without_type", 0) for row in game_metrics)
    unblocked_shots = sum(row.get("unblocked_shots", 0) for row in game_metrics)
    unblocked_missing_type = total_unblocked_missing_type
    all_shot_type_counts = collections.Counter()
    all_strength_state_counts = collections.Counter()
    all_period_type_counts = collections.Counter()
    for row in game_metrics:
        for key, value in json.loads(row.get("shot_types_json") or "{}").items():
            all_shot_type_counts[key] += value
        for key, value in json.loads(row.get("strength_state_counts_json") or "{}").items():
            all_strength_state_counts[key] += value
        for key, value in json.loads(row.get("period_type_event_counts_json") or "{}").items():
            all_period_type_counts[key] += value
    season_issue_counts = {}
    for (season, reason), count in sorted(issue_counts.items()):
        season_issue_counts.setdefault(season, {})[reason] = count
    target_populations = {
        "team_scoring_games": {
            "candidate_games": sum(bool(row.get("pbp_verified")) for row in game_metrics),
            "eligible_games": sum(row.get("team_score_target_disposition") == "ACCEPT" for row in game_metrics),
            "quarantined_games": sum(row.get("team_score_target_disposition") == "QUARANTINE" for row in game_metrics),
        },
        "team_sog_games": {
            "candidate_games": sum(bool(row.get("pbp_verified")) for row in game_metrics),
            "eligible_games": sum(row.get("team_sog_target_disposition") == "ACCEPT" for row in game_metrics),
            "quarantined_games": sum(row.get("team_sog_target_disposition") == "QUARANTINE" for row in game_metrics),
        },
        "player_shift_intervals": {
            "eligible": sum(row.get("shift_intervals_eligible", 0) for row in game_metrics),
            "quarantined": sum(row.get("shift_intervals_quarantined", 0) for row in game_metrics),
            "rejected": sum(row.get("shift_intervals_rejected", 0) for row in game_metrics),
            "eligible_skater_player_games": sum(row.get("skater_player_games_eligible", 0) for row in game_metrics),
            "eligible_goalie_player_games": sum(row.get("goalie_player_games_eligible", 0) for row in game_metrics),
        },
        "shot_event_player_on_ice_attribution": {
            "eligible": sum(row.get("shot_events_player_on_ice_eligible", 0) for row in game_metrics),
            "quarantined": sum(row.get("shot_events_player_on_ice_quarantined", 0) for row in game_metrics),
            "shift_alignment_status_counts": {
                status: sum(json.loads(row.get("shooter_event_shift_alignment_json") or "{}").get(status, 0)
                            for row in game_metrics)
                for status in ("ON_ACCEPTED_SHIFT", "OFF_SHIFT", "BOUNDARY_AMBIGUOUS",
                               "ON_UNTRUSTED_SHIFT", "NO_VERIFIED_SHIFT_CHART",
                               "PBP_PERIOD_NUMBER_UNTRUSTED")
            },
        },
        "direct_goalie_event_vs_shift_alignment": {
            "accepted_direct_id_and_accepted_shift_match": sum(
                row.get("shot_events_goalie_shift_match", 0) for row in game_metrics),
            "quarantined_comparison": sum(
                row.get("shot_events_goalie_shift_comparison_quarantined", 0) for row in game_metrics),
            "alignment_status_counts": {
                status: sum(json.loads(row.get("goalie_event_shift_alignment_json") or "{}").get(status, 0)
                            for row in game_metrics)
                for status in ("DIRECT_ID_MATCHES_ACCEPTED_SHIFT", "DIRECT_ID_DIFFERS_FROM_ACCEPTED_GOALIE_SHIFT",
                               "DIRECT_ID_ON_UNTRUSTED_SHIFT", "NO_GOALIE_SHIFT_AT_EVENT", "BOUNDARY_AMBIGUOUS",
                               "NO_VERIFIED_SHIFT_CHART", "PBP_PERIOD_NUMBER_UNTRUSTED")
            },
        },
        "situation_code_vs_shift_alignment": {
            "eligible_state_matches": sum(row.get("events_situation_deployment_eligible", 0) for row in game_metrics),
            "quarantined_state_events": sum(row.get("events_situation_deployment_quarantined", 0) for row in game_metrics),
            "alignment_status_counts": {
                status: sum(json.loads(row.get("situation_event_shift_alignment_json") or "{}").get(status, 0)
                            for row in game_metrics)
                for status in ("MATCH", "MISMATCH", "BOUNDARY_AMBIGUOUS", "DEPLOYMENT_UNTRUSTED",
                               "NO_SHIFT_COVERAGE", "NO_VERIFIED_SHIFT_CHART", "NO_VALID_SITUATION_CODE",
                               "PBP_PERIOD_NUMBER_UNTRUSTED")
            },
        },
    }
    label_population_by_season: dict[str, dict[str, int]] = collections.defaultdict(collections.Counter)
    for gid, game_labels in labels.items():
        season_key = str(frame_by_id[gid]["season"])
        for label in game_labels:
            label_population_by_season[season_key][f"{label.statistic}/{label.quality_status}"] += 1
            for purpose in ("training", "evaluation", "grading"):
                if status_label(label, purpose):
                    label_population_by_season[season_key][f"{label.statistic}/eligible_{purpose}"] += 1
    for statistic in ("SOG", "SAVES", "SHOTS_AGAINST", "GOALS_AGAINST"):
        target_populations[statistic] = {}
        for purpose in ("training", "evaluation", "grading"):
            target_populations[statistic][purpose] = {
                "approved_eligible_label_rows": sum(row.get(f"{statistic}_{purpose}_label_rows", 0) for row in game_metrics),
                "event_count_matches": sum(row.get(f"{statistic}_{purpose}_event_match_rows", 0) for row in game_metrics),
                "model_eligible_rows": sum(row.get(f"{statistic}_{purpose}_event_eligible_rows", 0) for row in game_metrics),
            }
    report = {
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "frame": {"games": len(frame), "sha256": frame_hash,
                  "games_list_sha256": full_games_hash, "games_by_season": season_counts(frame)},
        "source_lists": {"pbp_sha256": sha256_file(args.pbp_games),
                         "shifts_sha256": sha256_file(args.shift_games)},
        "sources": {"pbp": pbp_summary, "shifts": shift_summary,
                    "prior_manifest_comparison": {"pbp": pbp_prior_summary,
                                                   "shifts": shift_prior_summary},
                    "complete_pairs": len(set(pbp_verified) & set(shift_verified)),
                    "source_integrity_issue_rows": len(integrity_issues)},
        "official_sources": official_hashes,
        "approved_label_source": {"path": str(args.label_csv.resolve()),
                                  "sha256": sha256_file(args.label_csv),
                                  "label_status_counts": label_statuses},
        "audited_games": len(game_metrics), "games_with_verified_pbp_analyzed": sum(r["pbp_verified"] for r in game_metrics),
        "event_metrics": {"tracked_shot_events": total_shots,
                          "timeline_sequence": {
                              "event_rows": sum(row.get("event_rows", 0) for row in game_metrics),
                              "sort_order_anomaly_games": sum(row.get("sort_order_issue_count", 0) > 0
                                                               for row in game_metrics),
                              "sort_order_anomaly_values": sum(row.get("sort_order_issue_count", 0)
                                                                for row in game_metrics),
                              "period_number_regression_games": sum(
                                  row.get("period_number_sequence_regressions", 0) > 0
                                  for row in game_metrics),
                              "period_number_regressions": sum(
                                  row.get("period_number_sequence_regressions", 0)
                                  for row in game_metrics),
                              "period_number_join_quarantined_games": sum(
                                  row.get("period_number_sequence_regressions", 0) > 0
                                  or row.get("sort_order_issue_count", 0) > 0
                                  for row in game_metrics),
                          },
                          "event_counts": {
                              key: sum(row.get(key, 0) for row in game_metrics)
                              for key in ("ordinary_shot_events", "goals_total_including_shootout",
                                          "goals_regulation", "goals_overtime", "goals_shootout_events_excluded",
                                          "goals_unknown_period_type", "shootout_shot_events",
                                          "shot_events_unknown_period_type", "misses", "blocks",
                                          "on_target_ordinary", "penalty_events",
                                          "penalties_with_duration", "penalties_duration_missing_invalid",
                                          "penalties_timing_missing", "penalties_missing_committed_player",
                                          "penalty_duration_minutes_sum",
                                          "empty_net_state_events", "strength_state_shootout_events_excluded",
                                          "strength_state_unknown_period_events_excluded")},
                          "shot_type_counts": dict(sorted(all_shot_type_counts.items())),
                          "strength_state_event_counts": dict(sorted(all_strength_state_counts.items())),
                          "period_type_event_counts": dict(sorted(all_period_type_counts.items())),
                          "shot_event_identity": {
                              "direct_shooter_ids": sum(row.get("shots_direct_shooter_id", 0) for row in game_metrics),
                              "goal_scorer_fallbacks": sum(row.get("shots_goal_scorer_fallback", 0) for row in game_metrics),
                              "missing_shooter_ids": sum(row.get("shots_shooter_missing", 0) for row in game_metrics),
                              "shooter_identity_issues": sum(row.get("shot_player_identity_issues", 0) for row in game_metrics),
                              "event_owner_identity_issues": sum(row.get("shot_owner_identity_issues", 0) for row in game_metrics),
                              "direct_goalie_ids": sum(row.get("shot_events_with_direct_goalie_id", 0) for row in game_metrics),
                              "verified_direct_goalie_ids": sum(row.get("shot_events_with_verified_direct_goalie_id", 0) for row in game_metrics),
                              "goalie_identity_issues": sum(row.get("event_goalie_identity_issues", 0) for row in game_metrics),
                              "expected_empty_net_on_target_events": sum(row.get("on_target_goalie_missing_expected_empty_net", 0) for row in game_metrics),
                              "unexplained_missing_goalie_on_target_events": sum(row.get("on_target_goalie_missing_unexplained", 0) for row in game_metrics),
                              "goalie_substitution_changes": sum(row.get("goalie_substitution_changes_from_pbp_events", 0) for row in game_metrics),
                              "goalie_substitution_teams": sum(row.get("goalie_substitution_teams_from_pbp_events", 0) for row in game_metrics),
                          },
                          "shot_events_missing_coordinates": total_location_missing,
                          "shot_events_missing_coordinates_pct": round(100 * total_location_missing / total_shots, 6) if total_shots else None,
                          "unblocked_shots_missing_shot_type": total_unblocked_missing_type,
                          "total_shots_missing_type": sum(row.get("blocked_shots_without_type", 0) + row.get("unblocked_shots_without_type", 0) for row in game_metrics),
                          "shot_type_coverage": {
                              "blocked_shots": blocked_shots,
                              "blocked_shots_with_type": blocked_shots - blocked_missing_type,
                              "blocked_shots_missing_type": blocked_missing_type,
                              "blocked_shot_type_pct": round(100 * (blocked_shots - blocked_missing_type) / blocked_shots, 6) if blocked_shots else None,
                              "unblocked_shots": unblocked_shots,
                              "unblocked_shots_with_type": unblocked_shots - unblocked_missing_type,
                              "unblocked_shots_missing_type": unblocked_missing_type,
                              "unblocked_shot_type_pct": round(100 * (unblocked_shots - unblocked_missing_type) / unblocked_shots, 6) if unblocked_shots else None,
                          }},
        "reconciliation": {
            "score_games_matching": sum(row.get("score_match_after_shootout_convention") == 1 for row in game_metrics),
            "sog_games_matching": sum(row.get("sog_match_excluding_shootout") == 1 for row in game_metrics),
        },
        "eligible_model_populations": target_populations,
        "approved_label_populations_by_season": {
            season: dict(sorted(values.items()))
            for season, values in sorted(label_population_by_season.items())
        },
        "issues": {"row_count": sum(issue_counts.values()),
                   "counts_by_season_and_reason": season_issue_counts,
                   "game_ids_by_reason_code": {code: sorted(ids) for code, ids in sorted(issue_games.items())}},
        "season_results": per_season,
        "derived_artifacts": {"directory": str(args.derived_out.resolve()), "files": artifact_hashes},
        "run_complete": len(pbp_verified) == len(frame) and len(shift_verified) == len(frame) and not integrity_issues,
    }
    write_json_atomic(args.report_out, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--full-frame-games", type=Path, required=True)
    parser.add_argument("--pbp-games", type=Path, required=True)
    parser.add_argument("--shift-games", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True, help="directory containing pbp/ and shifts/")
    parser.add_argument("--pbp-manifest", type=Path, required=True)
    parser.add_argument("--shift-manifest", type=Path, required=True)
    parser.add_argument("--prior-pbp-manifest", type=Path,
                        help="optional earlier PBP manifest to reconcile against the hardened source manifest")
    parser.add_argument("--prior-shift-manifest", type=Path,
                        help="optional earlier shift manifest to reconcile against the hardened source manifest")
    parser.add_argument("--label-csv", type=Path, required=True)
    parser.add_argument("--label-summary", type=Path, default=LABEL_DIR / "research_label_summary.json")
    parser.add_argument("--derived-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    try:
        report = run(args)
    except Exception as exc:
        print(f"AUDIT_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"run_complete": report["run_complete"], "audited_games": report["audited_games"],
                      "sources": report["sources"], "issues": report["issues"]["row_count"],
                      "report_out": str(args.report_out)}, indent=2))
    return 0 if report["run_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
