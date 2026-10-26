#!/usr/bin/env python3
"""Resumable research-only NHL GameCenter boxscore import and normalization.

Raw HTTP bodies are retained outside Git under /root/lp-data. No application
database, model fit, wager, market price, or production table is read or written.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.utils
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_ARTIFACT_ROOT = Path("/root/lp-data/nhl-official-outcome-backfill-2026-10-20")
RAW_SOURCE_COMMIT = "cc50e244"
SEED = 20261020
ANCHOR_GAME_ID = 2018020160
SAMPLE_SHA256 = "0cd5fd97f61d2e945395b7e2b8238746dc3cad5c818fae746f1629c40149222a"
FRAME_SHA256 = "336d8a8d055febd742dbf31ce7a613bd2e47c2cd8fbc7a8d956fc8967ba47b1c"
FRAME_COUNTS = {2018: 1271, 2019: 1082, 2020: 868, 2021: 1312, 2022: 343}
FRAME_TOTAL = 4876
API = "https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
USER_AGENT = "Mozilla/5.0 (compatible; LegendaryPicks-NHL-OfficialOutcomeResearch/1.0)"
MIN_REQUEST_INTERVAL = 1.0
TIMEOUT_SECONDS = 30
RETRY_DELAYS = (5.0, 20.0)
TEAM_ALIASES = {"PHX": "ARI"}
COMPLETED_STATES = {"OFF", "FINAL"}
ACCESS_REFUSAL_STATUSES = {401, 403, 407, 429, 451}


class AccessRefused(RuntimeError):
    def __init__(self, game_id: int, status: int, retry_after: str | None, detail: str):
        super().__init__(f"game_id={game_id} HTTP {status}: {detail}")
        self.game_id = game_id
        self.status = status
        self.retry_after = retry_after


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    atomic_bytes(path, (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def load_frame(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"frozen canonical frame missing: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "game_id", "season", "game_date", "home_team", "away_team",
        "in_sbr_market_archive", "canonical_home_score", "canonical_away_score",
    }
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"frozen frame missing fields: {sorted(required - set(rows[0] if rows else []))}")
    for row in rows:
        row["game_id"] = int(row["game_id"])
        row["season"] = int(row["season"])
        row["in_sbr_market_archive"] = int(row["in_sbr_market_archive"])
    rows.sort(key=lambda row: (row["season"], row["game_id"]))
    counts = Counter(row["season"] for row in rows)
    canonical_bytes = "".join(
        f"{r['season']},{r['game_id']},{r['game_date']},{r['home_team']},{r['away_team']}\n"
        for r in rows
    ).encode()
    actual = sha256_bytes(canonical_bytes)
    if len(rows) != FRAME_TOTAL or dict(counts) != FRAME_COUNTS or actual != FRAME_SHA256:
        raise ValueError(
            f"frame contract failed: rows={len(rows)} seasons={dict(counts)} sha256={actual}"
        )
    return rows


def draw_seed_ids(frame: list[dict[str, Any]]) -> list[int]:
    import random

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in frame:
        grouped[row["season"]].append(row)
    rng = random.Random(SEED)
    sample = []
    for season in sorted(grouped):
        games = sorted(grouped[season], key=lambda row: row["game_id"])
        anchor = next((row for row in games if row["game_id"] == ANCHOR_GAME_ID), None)
        take = 59 if anchor else 60
        pool = [row for row in games if row["game_id"] != ANCHOR_GAME_ID]
        sample.extend(rng.sample(pool, take))
        if anchor:
            sample.append(anchor)
    sample.sort(key=lambda row: (row["season"], row["game_id"]))
    digest = sha256_bytes("".join(f"{r['season']}:{r['game_id']}\n" for r in sample).encode())
    if len(sample) != 300 or digest != SAMPLE_SHA256:
        raise ValueError(f"seed sample changed: n={len(sample)} sha256={digest}")
    return [row["game_id"] for row in sample]


def record_path(root: Path, game_id: int) -> Path:
    return root / "records" / f"{game_id}.json"


def raw_path(root: Path, game_id: int) -> Path:
    return root / "raw" / f"{game_id}.json.gz"


def parse_nonnegative_int(value: Any, label: str, game_id: int, player_id: str) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        result = value
    elif isinstance(value, float) and value.is_integer():
        result = int(value)
    elif isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        result = int(value.strip())
    else:
        return None
    if result < 0:
        return None
    return result


def parse_toi(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d+):(\d{2})", value.strip())
    if not match:
        return None
    minutes, seconds = map(int, match.groups())
    if seconds >= 60:
        return None
    return minutes * 60 + seconds


def validate_game_payload(payload: Any, game: dict[str, Any]) -> dict[str, Any]:
    gid = game["game_id"]
    if not isinstance(payload, dict):
        raise ValueError(f"game_id={gid}: response JSON is not an object")
    try:
        response_id = int(payload.get("id", payload.get("gameId")))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"game_id={gid}: response has no numeric game id") from exc
    if response_id != gid:
        raise ValueError(f"game_id={gid}: response id={response_id}")
    if str(payload.get("gameDate", ""))[:10] != game["game_date"]:
        raise ValueError(f"game_id={gid}: response date {payload.get('gameDate')!r} != canonical {game['game_date']}")
    if payload.get("gameType") != 2:
        raise ValueError(f"game_id={gid}: response gameType={payload.get('gameType')!r}, expected regular season (2)")
    if str(payload.get("gameState") or "") not in COMPLETED_STATES:
        raise ValueError(f"game_id={gid}: response is not completed: {payload.get('gameState')!r}")
    raw_season = payload.get("season")
    try:
        api_start_year = int(str(raw_season)[:4])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"game_id={gid}: response season is invalid: {raw_season!r}") from exc
    if api_start_year != game["season"]:
        raise ValueError(f"game_id={gid}: response season starts {api_start_year}, canonical {game['season']}")
    for side in ("home", "away"):
        team = payload.get(f"{side}Team")
        if not isinstance(team, dict):
            raise ValueError(f"game_id={gid}: missing {side}Team metadata")
        official = TEAM_ALIASES.get(str(team.get("abbrev") or ""), str(team.get("abbrev") or ""))
        canonical = game[f"{side}_team"]
        if official != canonical:
            raise ValueError(f"game_id={gid}: {side} team {official!r} != canonical {canonical!r}")
        for key in ("score", "sog"):
            if parse_nonnegative_int(team.get(key), key, gid, "") is None:
                raise ValueError(f"game_id={gid}: {side}Team.{key} missing or invalid")
    groups = payload.get("playerByGameStats")
    if not isinstance(groups, dict):
        raise ValueError(f"game_id={gid}: playerByGameStats missing")
    return payload


def gzip_bytes(raw: bytes) -> bytes:
    import io

    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as handle:
        handle.write(raw)
    return output.getvalue()


def load_validated_raw(root: Path, game: dict[str, Any], allow_recover: bool = True) -> tuple[bytes, dict[str, Any]]:
    gid = game["game_id"]
    path, metadata_path = raw_path(root, gid), record_path(root, gid)
    compressed = path.read_bytes()
    try:
        raw = gzip.decompress(compressed)
        payload = json.loads(raw)
    except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"game_id={gid}: corrupt raw response {path}: {exc}") from exc
    validate_game_payload(payload, game)
    raw_hash, compressed_hash = sha256_bytes(raw), sha256_bytes(compressed)
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("status") != "OK":
            raise ValueError(f"game_id={gid}: cached response metadata status={metadata.get('status')!r}")
        if metadata.get("raw_sha256") != raw_hash or metadata.get("compressed_sha256") != compressed_hash:
            raise ValueError(f"game_id={gid}: response bytes do not match manifest sidecar")
    elif allow_recover:
        metadata = {
            "game_id": gid, "status": "OK", "http_status": 200,
            "source": "recovered_existing_artifact", "retrieved_at_utc": None,
            "url": API.format(game_id=gid), "raw_sha256": raw_hash,
            "compressed_sha256": compressed_hash, "raw_bytes": len(raw),
            "compressed_bytes": len(compressed),
        }
        atomic_json(metadata_path, metadata)
    else:
        raise ValueError(f"game_id={gid}: per-game manifest sidecar missing")
    return raw, metadata


def seed_prior_cache(frame: list[dict[str, Any]], root: Path, source_dir: Path) -> int:
    expected = set(draw_seed_ids(frame))
    files = {int(path.name.split(".", 1)[0]): path for path in source_dir.glob("*.json.gz")}
    if set(files) != expected:
        raise ValueError(
            f"prior audit cache ids differ: expected {len(expected)}, found {len(files)}, "
            f"missing={sorted(expected-set(files))[:8]}, extra={sorted(set(files)-expected)[:8]}"
        )
    frame_by_id = {row["game_id"]: row for row in frame}
    copied = 0
    for gid in sorted(expected):
        src, dest = files[gid], raw_path(root, gid)
        compressed = src.read_bytes()
        raw = gzip.decompress(compressed)
        validate_game_payload(json.loads(raw), frame_by_id[gid])
        if dest.exists():
            if sha256_bytes(dest.read_bytes()) != sha256_bytes(compressed):
                raise ValueError(f"seed game_id={gid}: destination already has different bytes")
        else:
            atomic_bytes(dest, compressed)
            copied += 1
        metadata = {
            "game_id": gid, "status": "OK", "http_status": 200,
            "source": "prior_official_audit_cache", "source_commit": RAW_SOURCE_COMMIT,
            "source_cache_file": src.name, "retrieved_at_utc": None,
            "audit_date": "2026-10-20", "sample_seed": SEED,
            "url": API.format(game_id=gid), "raw_sha256": sha256_bytes(raw),
            "compressed_sha256": sha256_bytes(compressed), "raw_bytes": len(raw),
            "compressed_bytes": len(compressed),
        }
        sidecar = record_path(root, gid)
        if sidecar.exists():
            old = json.loads(sidecar.read_text(encoding="utf-8"))
            if old.get("raw_sha256") != metadata["raw_sha256"]:
                raise ValueError(f"seed game_id={gid}: existing metadata hash conflicts")
        else:
            atomic_json(sidecar, metadata)
    return copied


def write_manifest(frame: list[dict[str, Any]], root: Path, manifest_path: Path) -> int:
    lines = []
    for game in frame:
        path = raw_path(root, game["game_id"])
        if not path.is_file():
            continue
        _, metadata = load_validated_raw(root, game)
        row = {
            "game_id": game["game_id"], "season": game["season"],
            "game_date": game["game_date"], "canonical_home_team": game["home_team"],
            "canonical_away_team": game["away_team"],
            "in_sbr_market_archive": game["in_sbr_market_archive"],
            **metadata,
        }
        lines.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
    manifest_bytes = ("\n".join(lines) + ("\n" if lines else "")).encode()
    atomic_bytes(manifest_path, manifest_bytes)
    external_manifest = root / "manifest.jsonl"
    if external_manifest.resolve() != manifest_path.resolve():
        atomic_bytes(external_manifest, manifest_bytes)
    return len(lines)


def save_failure(root: Path, event: dict[str, Any], body: bytes = b"") -> None:
    if body:
        path = root / "rejected" / f"{event['game_id']}.http-{event['http_status']}.body"
        atomic_bytes(path, body)
        event["error_body_path"] = str(path)
        event["error_body_sha256"] = sha256_bytes(body)
    append_jsonl(root / "fetch_events.jsonl", event)


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
            return max(0.0, (when - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def wait_between_requests(last_start: float | None) -> None:
    if last_start is not None:
        elapsed = time.monotonic() - last_start
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)


def fetch_one(root: Path, game: dict[str, Any], last_start: float | None) -> tuple[float, dict[str, Any]]:
    gid = game["game_id"]
    url = API.format(game_id=gid)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    latest_start = last_start
    for attempt in range(1, 4):
        wait_between_requests(latest_start)
        latest_start = time.monotonic()
        requested_at = utc_now()
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                status = response.status
                body = response.read()
                headers = response.headers
        except urllib.error.HTTPError as exc:
            body = exc.read()
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            event = {
                "game_id": gid, "attempt": attempt, "requested_at_utc": requested_at,
                "url": url, "http_status": exc.code, "reason": str(exc.reason),
                "retry_after": retry_after,
            }
            save_failure(root, event, body)
            if exc.code in ACCESS_REFUSAL_STATUSES:
                raise AccessRefused(gid, exc.code, retry_after, str(exc.reason)) from exc
            if exc.code == 408 or 500 <= exc.code <= 599:
                if attempt < 3:
                    delay = retry_after_seconds(retry_after)
                    delay = RETRY_DELAYS[attempt - 1] if delay is None else delay
                    if delay > 300:
                        raise RuntimeError(f"game_id={gid}: Retry-After {delay:.0f}s exceeds 300s; stopped") from exc
                    print(f"RETRY game_id={gid} http={exc.code} wait={delay:.1f}s attempt={attempt}/3", flush=True)
                    time.sleep(delay)
                    continue
            raise RuntimeError(f"game_id={gid}: HTTP {exc.code}; stopped") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            event = {
                "game_id": gid, "attempt": attempt, "requested_at_utc": requested_at,
                "url": url, "http_status": None, "transport_error": f"{type(exc).__name__}: {exc}",
            }
            save_failure(root, event)
            if attempt < 3:
                delay = RETRY_DELAYS[attempt - 1]
                print(f"RETRY game_id={gid} transport wait={delay:.1f}s attempt={attempt}/3", flush=True)
                time.sleep(delay)
                continue
            raise RuntimeError(f"game_id={gid}: transport failed after 3 attempts; stopped") from exc
        if status != 200:
            raise RuntimeError(f"game_id={gid}: unexpected HTTP status {status}; stopped")
        try:
            payload = json.loads(body)
            validate_game_payload(payload, game)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            compressed = gzip_bytes(body)
            atomic_bytes(raw_path(root, gid), compressed)
            metadata = {
                "game_id": gid, "status": "VALIDATION_FAILED", "http_status": status,
                "source": "official_gamecenter", "retrieved_at_utc": requested_at,
                "url": url, "raw_sha256": sha256_bytes(body),
                "compressed_sha256": sha256_bytes(compressed), "raw_bytes": len(body),
                "compressed_bytes": len(compressed), "validation_error": str(exc),
            }
            atomic_json(record_path(root, gid), metadata)
            raise RuntimeError(f"game_id={gid}: official response failed validation; raw retained: {exc}") from exc
        compressed = gzip_bytes(body)
        atomic_bytes(raw_path(root, gid), compressed)
        metadata = {
            "game_id": gid, "status": "OK", "http_status": status,
            "source": "official_gamecenter", "retrieved_at_utc": requested_at,
            "url": url, "raw_sha256": sha256_bytes(body),
            "compressed_sha256": sha256_bytes(compressed), "raw_bytes": len(body),
            "compressed_bytes": len(compressed),
            "game_date": payload["gameDate"], "game_type": payload["gameType"],
            "game_state": payload["gameState"], "season": payload["season"],
        }
        atomic_json(record_path(root, gid), metadata)
        append_jsonl(root / "fetch_events.jsonl", {
            "game_id": gid, "attempt": attempt, "requested_at_utc": requested_at,
            "url": url, "http_status": status, "result": "STORED",
            "raw_sha256": metadata["raw_sha256"],
        })
        return latest_start, metadata
    raise RuntimeError(f"game_id={gid}: exhausted request attempts")


def read_manifested_payloads(frame: list[dict[str, Any]], root: Path) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    output = []
    for game in frame:
        raw, metadata = load_validated_raw(root, game)
        payload = json.loads(raw)
        output.append((game, payload, metadata))
    return output


def player_name(player: dict[str, Any]) -> str:
    name = player.get("name")
    if isinstance(name, dict):
        return str(name.get("default") or "")
    return str(name or "")


def normalize_player_rows(
    game: dict[str, Any], payload: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    gid = game["game_id"]
    groups = payload["playerByGameStats"]
    skaters, goalies, issues, totals = [], [], [], []
    all_rows: list[dict[str, Any]] = []
    for side in ("away", "home"):
        team_code = game[f"{side}_team"]
        opponent = game["home_team"] if side == "away" else game["away_team"]
        official_team = payload[f"{side}Team"]
        stats_team = groups.get(f"{side}Team")
        if not isinstance(stats_team, dict):
            issues.append({
                "game_id": gid, "record_key": "", "side": side, "team": team_code,
                "player_id": "", "issue_type": "MISSING_TEAM_PLAYER_GROUP",
                "field": "playerByGameStats", "value": "", "detail": "side group missing",
            })
            continue
        known_sog = 0
        missing_sog = 0
        for group_name, role in (("forwards", "skater"), ("defense", "skater"), ("goalies", "goalie")):
            players = stats_team.get(group_name)
            if not isinstance(players, list):
                issues.append({
                    "game_id": gid, "record_key": "", "side": side, "team": team_code,
                    "player_id": "", "issue_type": "MISSING_PLAYER_GROUP",
                    "field": group_name, "value": "", "detail": "group is not a list",
                })
                continue
            if not players and group_name in ("forwards", "defense"):
                issues.append({
                    "game_id": gid, "record_key": "", "side": side, "team": team_code,
                    "player_id": "", "issue_type": "EMPTY_SKATER_GROUP",
                    "field": group_name, "value": "[]", "detail": "empty skater group",
                })
            for index, player in enumerate(players):
                record_key = f"{gid}:{side}:{group_name}:{index}"
                if not isinstance(player, dict):
                    issues.append({
                        "game_id": gid, "record_key": record_key, "side": side,
                        "team": team_code, "player_id": "", "issue_type": "INVALID_PLAYER_ROW",
                        "field": "player", "value": repr(player), "detail": "row is not an object",
                    })
                    continue
                raw_pid = player.get("playerId")
                pid = ""
                if isinstance(raw_pid, int) and not isinstance(raw_pid, bool) and raw_pid > 0:
                    pid = str(raw_pid)
                else:
                    issues.append({
                        "game_id": gid, "record_key": record_key, "side": side,
                        "team": team_code, "player_id": str(raw_pid or ""),
                        "issue_type": "MISSING_OR_INVALID_PLAYER_ID", "field": "playerId",
                        "value": str(raw_pid), "detail": "numeric NHL player ID required",
                    })
                toi = player.get("toi")
                toi_seconds = parse_toi(toi)
                if toi_seconds is None:
                    issues.append({
                        "game_id": gid, "record_key": record_key, "side": side,
                        "team": team_code, "player_id": pid, "issue_type": "INVALID_TOI",
                        "field": "toi", "value": str(toi), "detail": "expected M:SS publisher value",
                    })
                row = {
                    "record_key": record_key, "game_id": gid, "season": game["season"],
                    "game_date": game["game_date"], "team": team_code,
                    "opponent": opponent, "home_away": side,
                    "player_id": pid, "player_name": player_name(player),
                    "position": str(player.get("position") or ""),
                    "source_group": group_name, "toi": str(toi or ""),
                    "toi_seconds": "" if toi_seconds is None else toi_seconds,
                    "appeared": "" if toi_seconds is None else int(toi_seconds > 0),
                    "identity_status": "OK" if pid else "MISSING_OR_INVALID",
                }
                if role == "skater":
                    sog = parse_nonnegative_int(player.get("sog"), "sog", gid, pid)
                    row["sog"] = "" if sog is None else sog
                    if sog is None:
                        missing_sog += 1
                        issues.append({
                            "game_id": gid, "record_key": record_key, "side": side,
                            "team": team_code, "player_id": pid, "issue_type": "INVALID_SOG",
                            "field": "sog", "value": str(player.get("sog")),
                            "detail": "nonnegative integer required",
                        })
                    else:
                        known_sog += sog
                    skaters.append(row)
                else:
                    values = {}
                    for source_key, output_key in (
                        ("saves", "saves"), ("shotsAgainst", "shots_against"),
                        ("goalsAgainst", "goals_against"),
                    ):
                        value = parse_nonnegative_int(player.get(source_key), source_key, gid, pid)
                        values[output_key] = "" if value is None else value
                        if value is None:
                            issues.append({
                                "game_id": gid, "record_key": record_key, "side": side,
                                "team": team_code, "player_id": pid,
                                "issue_type": "INVALID_GOALIE_STAT", "field": source_key,
                                "value": str(player.get(source_key)),
                                "detail": "nonnegative integer required",
                            })
                    row.update(values)
                    row["starter"] = str(player.get("starter", ""))
                    if all(isinstance(row[key], int) for key in ("saves", "shots_against", "goals_against")):
                        if row["saves"] + row["goals_against"] != row["shots_against"]:
                            issues.append({
                                "game_id": gid, "record_key": record_key, "side": side,
                                "team": team_code, "player_id": pid,
                                "issue_type": "GOALIE_TOTAL_IDENTITY_MISMATCH",
                                "field": "saves+goals_against=shots_against",
                                "value": f"{row['saves']}+{row['goals_against']}!={row['shots_against']}",
                                "detail": "published goalie totals fail arithmetic identity",
                            })
                    goalies.append(row)
                all_rows.append(row)

        team_sog = parse_nonnegative_int(official_team.get("sog"), "team sog", gid, "")
        status = "UNKNOWN" if missing_sog else ("PASS" if known_sog == team_sog else "MISMATCH")
        diff = "" if team_sog is None else known_sog - team_sog
        totals.append({
            "game_id": gid, "season": game["season"], "game_date": game["game_date"],
            "side": side, "team": team_code, "official_team_sog": team_sog,
            "sum_player_sog": known_sog, "missing_or_invalid_player_sog_rows": missing_sog,
            "difference": diff, "validation": status,
        })
        if status != "PASS":
            issues.append({
                "game_id": gid, "record_key": "", "side": side, "team": team_code,
                "player_id": "", "issue_type": "PLAYER_SOG_SUM_VS_TEAM_TOTAL",
                "field": "sog", "value": f"players={known_sog}; team={team_sog}",
                "detail": f"official team total validation {status}",
            })

    pid_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        if row["player_id"]:
            pid_rows[row["player_id"]].append(row)
    for pid, rows in pid_rows.items():
        if len(rows) > 1:
            for row in rows:
                row["identity_status"] = "CONFLICT_DUPLICATE_ID"
            issues.append({
                "game_id": gid, "record_key": ";".join(row["record_key"] for row in rows),
                "side": ";".join(sorted({row["home_away"] for row in rows})),
                "team": ";".join(sorted({row["team"] for row in rows})),
                "player_id": pid, "issue_type": "DUPLICATE_PLAYER_ID_WITHIN_GAME",
                "field": "playerId", "value": pid,
                "detail": "same numeric ID appears in multiple official player rows",
            })
    return skaters, goalies, issues, totals


def materialize(frame: list[dict[str, Any]], root: Path, output_dir: Path) -> dict[str, Any]:
    payloads = read_manifested_payloads(frame, root)
    games_out, skaters_out, goalies_out, issues_out, totals_out = [], [], [], [], []
    for game, payload, metadata in payloads:
        for side in ("home", "away"):
            api_team = payload[f"{side}Team"]
            games_out.append({
                "game_id": game["game_id"], "season": game["season"],
                "game_date": game["game_date"], "game_type": payload["gameType"],
                "game_state": payload["gameState"], "season_api": payload["season"],
                "side": side, "team": game[f"{side}_team"],
                "score": api_team["score"], "team_sog": api_team["sog"],
                "canonical_score": game[f"canonical_{side}_score"],
                "in_sbr_market_archive": game["in_sbr_market_archive"],
                "raw_sha256": metadata["raw_sha256"],
                "compressed_sha256": metadata["compressed_sha256"],
            })
        skaters, goalies, issues, totals = normalize_player_rows(game, payload)
        skaters_out.extend(skaters)
        goalies_out.extend(goalies)
        issues_out.extend(issues)
        totals_out.extend(totals)

    response_source_counts = Counter(
        str(metadata.get("source") or "UNKNOWN") for _game, _payload, metadata in payloads
    )
    identity_conflicts = sum(row["issue_type"] in (
        "MISSING_OR_INVALID_PLAYER_ID", "DUPLICATE_PLAYER_ID_WITHIN_GAME"
    ) for row in issues_out)
    zero_toi_goalies = sum(row["appeared"] == 0 for row in goalies_out)
    appeared_goalies = sum(row["appeared"] == 1 for row in goalies_out)
    zero_toi_skaters = sum(row["appeared"] == 0 for row in skaters_out)
    appeared_skaters = sum(row["appeared"] == 1 for row in skaters_out)
    unknown_toi_skaters = sum(row["appeared"] == "" for row in skaters_out)
    team_sog_counts = Counter(row["validation"] for row in totals_out)
    quality_issue_counts = Counter(row["issue_type"] for row in issues_out)
    goalie_arithmetic_failures = sum(
        row["issue_type"] == "GOALIE_TOTAL_IDENTITY_MISMATCH" for row in issues_out
    )
    games_covered = len({row["game_id"] for row in games_out})
    season_games = Counter(game["season"] for game in frame)
    sbr_market_season_games = Counter(
        game["season"] for game in frame if game["in_sbr_market_archive"]
    )
    canonical_date_ranges = {
        str(season): [
            min(game["game_date"] for game in frame if game["season"] == season),
            max(game["game_date"] for game in frame if game["season"] == season),
        ] for season in sorted(season_games)
    }
    sbr_market_date_ranges = {}
    for season in sorted(season_games):
        market_dates = [
            game["game_date"] for game in frame
            if game["season"] == season and game["in_sbr_market_archive"]
        ]
        if market_dates:
            sbr_market_date_ranges[str(season)] = [min(market_dates), max(market_dates)]
    game_ids_by_season = {
        season: {game["game_id"] for game in frame if game["season"] == season}
        for season in season_games
    }
    season_coverage: dict[str, dict[str, Any]] = {}
    for season in sorted(season_games):
        team_status = Counter(row["validation"] for row in totals_out if row["season"] == season)
        season_issues = [row for row in issues_out if row["game_id"] in game_ids_by_season[season]]
        season_coverage[str(season)] = {
            "games": season_games[season],
            "official_team_rows": sum(row["season"] == season for row in games_out),
            "skater_rows": sum(row["season"] == season for row in skaters_out),
            "skater_appearances": sum(row["season"] == season and row["appeared"] == 1 for row in skaters_out),
            "skater_zero_toi_slots": sum(row["season"] == season and row["appeared"] == 0 for row in skaters_out),
            "skater_unknown_toi_rows": sum(row["season"] == season and row["appeared"] == "" for row in skaters_out),
            "goalie_rows_including_zero_toi": sum(row["season"] == season for row in goalies_out),
            "goalie_appearances": sum(row["season"] == season and row["appeared"] == 1 for row in goalies_out),
            "zero_toi_goalie_slots": sum(row["season"] == season and row["appeared"] == 0 for row in goalies_out),
            "team_sog_sum_validation": dict(team_status),
            "goalie_arithmetic_failures": sum(row["issue_type"] == "GOALIE_TOTAL_IDENTITY_MISMATCH" for row in season_issues),
            "identity_issue_count": sum(row["issue_type"] in (
                "MISSING_OR_INVALID_PLAYER_ID", "DUPLICATE_PLAYER_ID_WITHIN_GAME"
            ) for row in season_issues),
            "quality_issue_count": len(season_issues),
        }
    summary = {
        "frame_games": len(frame), "official_game_ids": games_covered,
        "official_team_rows": len(games_out), "skater_rows": len(skaters_out),
        "response_source_counts": dict(response_source_counts),
        "skater_appearances": appeared_skaters,
        "skater_zero_toi_slots": zero_toi_skaters,
        "skater_unknown_toi_rows": unknown_toi_skaters,
        "goalie_rows_including_zero_toi": len(goalies_out),
        "goalie_appearances": appeared_goalies, "zero_toi_goalie_slots": zero_toi_goalies,
        "team_sog_sum_validation": dict(team_sog_counts),
        "goalie_arithmetic_failures": goalie_arithmetic_failures,
        "identity_issue_count": identity_conflicts,
        "quality_issue_count": len(issues_out),
        "quality_issue_counts_by_type": dict(quality_issue_counts),
        "canonical_season_counts": {str(k): season_games[k] for k in sorted(season_games)},
        "sbr_market_season_counts": {str(k): sbr_market_season_games[k] for k in sorted(season_games)},
        "canonical_season_date_ranges": canonical_date_ranges,
        "sbr_market_season_date_ranges": sbr_market_date_ranges,
        "season_coverage": season_coverage,
        "sbr_market_games_in_frame": sum(game["in_sbr_market_archive"] for game in frame),
        "canonical_only_games": sorted(game["game_id"] for game in frame if not game["in_sbr_market_archive"]),
    }
    write_csv(output_dir / "official_game_sides.csv", list(games_out[0]), games_out)
    write_csv(output_dir / "official_skater_outcomes.csv", list(skaters_out[0]), skaters_out)
    write_csv(output_dir / "official_goalie_outcomes.csv", list(goalies_out[0]), goalies_out)
    issue_fields = [
        "game_id", "record_key", "side", "team", "player_id", "issue_type",
        "field", "value", "detail",
    ]
    write_csv(output_dir / "official_quality_issues.csv", issue_fields, issues_out)
    write_csv(output_dir / "official_team_sog_validation.csv", list(totals_out[0]), totals_out)
    atomic_json(output_dir / "official_coverage_summary.json", summary)
    return summary


def write_coverage_report(output_dir: Path, summary: dict[str, Any], root: Path) -> None:
    manifest = output_dir / "manifest.jsonl"
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else "MISSING"
    lines = [
        "# NHL official outcome backfill — coverage",
        "",
        "Research-only official outcome import. No model fitting, market evaluation, ROI, or production data replacement was performed.",
        "",
        "## Population",
        "",
        f"- Canonical regular-season frame: **{summary['frame_games']:,}** games; season counts `{summary['canonical_season_counts']}`.",
        f"- SBR market population inside that frame: **{summary['sbr_market_games_in_frame']:,}** games.",
        f"- Canonical-only games, outside the SBR market archive: `{summary['canonical_only_games']}`. The partial 2022–23 canonical frame covers {summary['canonical_season_date_ranges']['2022'][0]} to {summary['canonical_season_date_ranges']['2022'][1]} ({summary['canonical_season_counts']['2022']} games); its SBR subset covers {summary['sbr_market_season_date_ranges']['2022'][0]} to {summary['sbr_market_season_date_ranges']['2022'][1]} ({summary['sbr_market_season_counts']['2022']} games).",
        "- The goalie experiment remains a separate 4,872-game SBR target population, with 4,763 complete-case rows and 3,509 OOF evaluation rows; these denominators are unchanged.",
        "",
        "## Official response and outcome coverage",
        "",
        f"- Official GameCenter responses validated: **{summary['official_game_ids']:,}/{summary['frame_games']:,}** unique canonical game IDs.",
        f"- Response provenance: `{summary['response_source_counts']}` (the prior audit cache is retained as source data; all newly fetched responses remain individually hash-pinned).",
        f"- Team-side rows: {summary['official_team_rows']:,}; skater player-game rows: {summary['skater_rows']:,}, including {summary['skater_appearances']:,} positive-TOI appearances, {summary['skater_zero_toi_slots']:,} zero-TOI slots, and {summary['skater_unknown_toi_rows']:,} unknown-TOI rows.",
        f"- Goalie rows retained: {summary['goalie_rows_including_zero_toi']:,}, including {summary['zero_toi_goalie_slots']:,} zero-TOI slots. Played-goalie sample rows (TOI > 0): {summary['goalie_appearances']:,}.",
        f"- Player SOG sums versus the official boxscore team SOG totals: `{summary['team_sog_sum_validation']}`.",
        f"- Goalie arithmetic identity failures (`saves + goalsAgainst = shotsAgainst`): {summary['goalie_arithmetic_failures']:,}.",
        f"- Missing/invalid or duplicate player-ID issues in official rows: {summary['identity_issue_count']:,}; all reported quality issues: {summary['quality_issue_count']:,}. See `official_quality_issues.csv`.",
        f"- Quality issue counts by type: `{summary['quality_issue_counts_by_type']}`.",
    ]
    lines.extend([
        "",
        "| Start season | Games | Team rows | Skater rows | Skater appearances | Skater zero-TOI | Goalie rows | Played goalie rows | Goalie zero-TOI | Team-SOG checks | Goalie arithmetic failures | Identity issues |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|",
    ])
    for season, item in sorted(summary["season_coverage"].items()):
        team_checks = ", ".join(f"{key}={value}" for key, value in sorted(item["team_sog_sum_validation"].items()))
        lines.append(
            f"| {season} | {item['games']} | {item['official_team_rows']} | {item['skater_rows']} "
            f"| {item['skater_appearances']} | {item['skater_zero_toi_slots']} "
            f"| {item['goalie_rows_including_zero_toi']} | {item['goalie_appearances']} "
            f"| {item['zero_toi_goalie_slots']} | {team_checks} | {item['goalie_arithmetic_failures']} "
            f"| {item['identity_issue_count']} |"
        )
    lines.extend([
        "",
        "## Reproducibility and limitations",
        "",
        f"- Raw bodies are stored outside Git at `{root}`. Per-game raw and compressed SHA256 values are in `manifest.jsonl` (manifest SHA256 `{manifest_hash}`).",
        "- `official_goalie_outcomes.csv` retains zero-TOI backup slots. Exclude `appeared=0` from played-game goalie prop outcome samples; do not delete those rows from the raw official artifact.",
        "- This report validates official boxscore coverage and reconciles outcome fields against the local historical archive. It does not certify sportsbook settlement rules or stat-correction timing.",
        "- Official boxscores do not contain shift-by-shift data and do not complete the V3 simulation roadmap.",
        "",
    ])
    (output_dir / "COVERAGE.md").write_text("\n".join(lines), encoding="utf-8")


def run_fetch(args: argparse.Namespace, frame: list[dict[str, Any]]) -> int:
    root: Path = args.artifact_root
    root.mkdir(parents=True, exist_ok=True)
    prior_state_path = root / "fetch_state.json"
    prior_state = json.loads(prior_state_path.read_text()) if prior_state_path.exists() else {}
    if prior_state.get("status") == "STOPPED_ACCESS_REFUSAL" and not args.resume_after_refusal:
        print("STOP previous access refusal is recorded; pass --resume-after-refusal only after access is restored", file=sys.stderr)
        return 2

    if args.seed_cache_dir:
        copied = seed_prior_cache(frame, root, args.seed_cache_dir)
        print(f"SEEDED prior_official_audit_cache copied={copied} expected=300 source_commit={RAW_SOURCE_COMMIT}", flush=True)

    frame_by_id = {row["game_id"]: row for row in frame}
    raw_dir = root / "raw"
    if raw_dir.exists():
        known = {row["game_id"] for row in frame}
        unexpected = []
        for path in raw_dir.glob("*.json.gz"):
            try:
                gid = int(path.name[:-8])
            except ValueError:
                unexpected.append(path.name)
                continue
            if gid not in known:
                unexpected.append(path.name)
        if unexpected:
            raise ValueError(f"unexpected raw artifact paths: {unexpected[:10]}")

    # Verify every existing body before requesting anything. A partial gzip or stale sidecar
    # must stop the run rather than being silently replaced.
    cached = set()
    for game in frame:
        path = raw_path(root, game["game_id"])
        if path.exists():
            load_validated_raw(root, game)
            cached.add(game["game_id"])
    missing = [game for game in frame if game["game_id"] not in cached]
    write_manifest(frame, root, HERE / "manifest.jsonl")
    run_state = {
        "status": "RUNNING", "started_at_utc": utc_now(),
        "frame_games": len(frame), "cached_at_start": len(cached),
        "missing_at_start": len(missing), "minimum_interval_seconds": MIN_REQUEST_INTERVAL,
        "concurrency": 1, "artifact_root": str(root),
    }
    atomic_json(prior_state_path, run_state)
    print(
        f"BACKFILL_START frame={len(frame)} cached={len(cached)} missing={len(missing)} "
        f"interval={MIN_REQUEST_INTERVAL:.1f}s concurrency=1",
        flush=True,
    )
    last_start: float | None = None
    fetched_this_run = 0
    try:
        for game in missing:
            if args.max_new and fetched_this_run >= args.max_new:
                break
            last_start, _ = fetch_one(root, game, last_start)
            fetched_this_run += 1
            if fetched_this_run % 25 == 0 or fetched_this_run == len(missing):
                completed = len(cached) + fetched_this_run
                print(
                    f"PROGRESS fetched_this_run={fetched_this_run} "
                    f"complete={completed}/{FRAME_TOTAL} remaining={FRAME_TOTAL-completed}",
                    flush=True,
                )
            if fetched_this_run % 100 == 0:
                write_manifest(frame, root, HERE / "manifest.jsonl")
    except AccessRefused as exc:
        write_manifest(frame, root, HERE / "manifest.jsonl")
        run_state.update({
            "status": "STOPPED_ACCESS_REFUSAL", "stopped_at_utc": utc_now(),
            "http_status": exc.status, "game_id": exc.game_id,
            "retry_after": exc.retry_after, "detail": str(exc),
        })
        atomic_json(prior_state_path, run_state)
        print(f"STOP ACCESS_REFUSAL {exc}; no further requests issued", file=sys.stderr, flush=True)
        return 2
    except Exception as exc:
        write_manifest(frame, root, HERE / "manifest.jsonl")
        run_state.update({
            "status": "STOPPED_ERROR", "stopped_at_utc": utc_now(),
            "detail": f"{type(exc).__name__}: {exc}",
        })
        atomic_json(prior_state_path, run_state)
        raise

    completed = len({
        game["game_id"] for game in frame if raw_path(root, game["game_id"]).exists()
    })
    write_manifest(frame, root, HERE / "manifest.jsonl")
    run_state.update({
        "status": "COMPLETE" if completed == FRAME_TOTAL else "INCOMPLETE_LIMIT",
        "finished_at_utc": utc_now(), "fetched_this_run": fetched_this_run,
        "validated_responses": completed, "remaining": FRAME_TOTAL - completed,
    })
    atomic_json(prior_state_path, run_state)
    if completed != FRAME_TOTAL:
        print(f"INCOMPLETE validated={completed}/{FRAME_TOTAL} remaining={FRAME_TOTAL-completed}", flush=True)
        return 0

    summary = materialize(frame, root, HERE)
    write_coverage_report(HERE, summary, root)
    run_state.update({"response_source_counts": summary["response_source_counts"]})
    atomic_json(prior_state_path, run_state)
    print("MATERIALIZED " + json.dumps(summary, sort_keys=True), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=Path, default=HERE / "canonical_frame.csv")
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--seed-cache-dir", type=Path)
    parser.add_argument("--fetch", action="store_true", help="fetch missing boxes sequentially")
    parser.add_argument("--max-new", type=int, default=0, help="fetch at most N new boxes; 0 means all")
    parser.add_argument("--resume-after-refusal", action="store_true", help="explicitly resume after a previously recorded 403/429")
    args = parser.parse_args()
    frame = load_frame(args.frame)
    if args.max_new < 0:
        parser.error("--max-new must be nonnegative")
    if not args.fetch:
        parser.error("--fetch is required to issue requests; use --fetch only after reviewing the plan")
    return run_fetch(args, frame)


if __name__ == "__main__":
    raise SystemExit(main())
