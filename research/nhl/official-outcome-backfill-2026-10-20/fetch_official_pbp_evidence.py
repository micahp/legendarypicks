#!/usr/bin/env python3
"""Fetch and hash-pin NHL GameCenter play-by-play for the 22 adjudication cases.

The source payload cache stays outside Git. This script never overwrites an
existing body; reruns verify and reuse the bytes already collected.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ISSUES = HERE / "official_quality_issues.csv"
CACHE = Path("/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20/play-by-play")
MANIFEST = HERE / "play_by_play_evidence_manifest.csv"
BASE_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
PAUSE_SECONDS = 1.1
USER_AGENT = "legendarypicks-research-outcome-quality/1.0"


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def required_games() -> list[str]:
    with ISSUES.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    relevant = {"PLAYER_SOG_SUM_VS_TEAM_TOTAL", "GOALIE_TOTAL_IDENTITY_MISMATCH"}
    unknown = sorted({row["issue_type"] for row in rows} - relevant)
    if unknown:
        raise ValueError(f"unexpected quality issue types: {unknown}")
    return sorted({row["game_id"] for row in rows if row["issue_type"] in relevant}, key=int)


def validate_payload(game_id: str, body: bytes) -> dict[str, Any]:
    payload = json.loads(body)
    if str(payload.get("id")) != game_id:
        raise ValueError(f"requested game {game_id}; PBP payload id={payload.get('id')!r}")
    if payload.get("gameType") != 2 or payload.get("gameState") not in {"OFF", "FINAL"}:
        raise ValueError(f"game {game_id}: unexpected state/type {payload.get('gameState')}/{payload.get('gameType')}")
    if not isinstance(payload.get("plays"), list) or not payload["plays"]:
        raise ValueError(f"game {game_id}: PBP has no plays")
    if not isinstance(payload.get("homeTeam", {}).get("id"), int):
        raise ValueError(f"game {game_id}: missing numeric home team id")
    if not isinstance(payload.get("awayTeam", {}).get("id"), int):
        raise ValueError(f"game {game_id}: missing numeric away team id")
    return payload


def cache_paths(game_id: str) -> tuple[Path, Path]:
    return CACHE / f"{game_id}.json", CACHE / f"{game_id}.meta.json"


def read_cached(game_id: str) -> dict[str, Any] | None:
    body_path, meta_path = cache_paths(game_id)
    if not body_path.exists() and not meta_path.exists():
        return None
    if not body_path.is_file() or not meta_path.is_file():
        raise ValueError(f"game {game_id}: incomplete cache pair; refusing overwrite")
    body = body_path.read_bytes()
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    digest = sha256(body)
    if metadata.get("sha256") != digest or metadata.get("bytes") != len(body):
        raise ValueError(f"game {game_id}: cached PBP body hash/length mismatch")
    payload = validate_payload(game_id, body)
    return {
        "game_id": game_id,
        "source_url": metadata["source_url"],
        "retrieved_at_utc": metadata["retrieved_at_utc"],
        "http_status": metadata["http_status"],
        "content_type": metadata["content_type"],
        "bytes": len(body),
        "sha256": digest,
        "cache_file": body_path.name,
        "event_count": len(payload["plays"]),
    }


def fetch_one(game_id: str) -> dict[str, Any]:
    cached = read_cached(game_id)
    if cached is not None:
        return cached
    CACHE.mkdir(parents=True, exist_ok=True)
    url = BASE_URL.format(game_id=game_id)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            body = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"game {game_id}: official PBP request failed: {exc}") from exc
    if status != 200:
        raise RuntimeError(f"game {game_id}: expected HTTP 200 from official PBP, got {status}")
    payload = validate_payload(game_id, body)
    body_path, meta_path = cache_paths(game_id)
    metadata = {
        "game_id": game_id,
        "source_url": url,
        "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "http_status": status,
        "content_type": content_type,
        "bytes": len(body),
        "sha256": sha256(body),
    }
    try:
        with body_path.open("xb") as handle:
            handle.write(body)
        with meta_path.open("x", encoding="utf-8") as handle:
            json.dump(metadata, handle, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise RuntimeError(f"game {game_id}: cache appeared during fetch; refusing overwrite") from exc
    return {
        **metadata,
        "cache_file": body_path.name,
        "event_count": len(payload["plays"]),
    }


def write_manifest(rows: list[dict[str, Any]]) -> None:
    columns = ["game_id", "source_url", "retrieved_at_utc", "http_status", "content_type", "bytes", "sha256", "cache_file", "event_count"]
    temporary = MANIFEST.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    temporary.replace(MANIFEST)


def main() -> int:
    games = required_games()
    if len(games) != 22:
        raise ValueError(f"expected 22 distinct issue games, got {len(games)}: {games}")
    rows = []
    for index, game_id in enumerate(games):
        row = fetch_one(game_id)
        rows.append(row)
        print(f"PBP {index + 1}/{len(games)} game={game_id} bytes={row['bytes']} sha256={row['sha256']}", flush=True)
        if index + 1 < len(games) and not cache_paths(games[index + 1])[0].exists():
            time.sleep(PAUSE_SECONDS)
    write_manifest(rows)
    print(f"PBP_EVIDENCE_PASS games={len(rows)} bytes={sum(row['bytes'] for row in rows)} manifest={MANIFEST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
