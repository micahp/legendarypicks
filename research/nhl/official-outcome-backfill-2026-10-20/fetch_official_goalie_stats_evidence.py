#!/usr/bin/env python3
"""Cache the NHL Stats REST goalie-summary rows for the two arithmetic cases."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ISSUES = HERE / "official_quality_issues.csv"
CACHE = Path("/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20/goalie-stats")
MANIFEST = HERE / "goalie_stats_evidence_manifest.csv"
ENDPOINT = "https://api.nhle.com/stats/rest/en/goalie/summary"
PAUSE_SECONDS = 1.1
USER_AGENT = "legendarypicks-research-outcome-quality/1.0"


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def targets() -> dict[str, set[str]]:
    with ISSUES.open(newline="", encoding="utf-8") as handle:
        issues = list(csv.DictReader(handle))
    result: dict[str, set[str]] = {}
    for row in issues:
        if row["issue_type"] == "GOALIE_TOTAL_IDENTITY_MISMATCH":
            result.setdefault(row["game_id"], set()).add(row["player_id"])
    if len(result) != 2:
        raise ValueError(f"expected the two specified goalie issue games, found {sorted(result)}")
    return result


def build_url(game_id: str) -> str:
    query = urllib.parse.urlencode({
        "isAggregate": "false",
        "isGame": "true",
        "cayenneExp": f"gameId={game_id}",
        "limit": "100",
    })
    return f"{ENDPOINT}?{query}"


def validate_payload(game_id: str, player_ids: set[str], body: bytes) -> dict[str, Any]:
    payload = json.loads(body)
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"game {game_id}: stats response lacks data list")
    if not all(int(row.get("gameId", -1)) == int(game_id) for row in rows):
        raise ValueError(f"game {game_id}: stats response contains another game")
    matching = {str(row.get("playerId")): row for row in rows if str(row.get("playerId")) in player_ids}
    if set(matching) != player_ids:
        raise ValueError(f"game {game_id}: requested goalie rows {sorted(player_ids)}; returned {sorted(matching)}")
    for player_id, row in matching.items():
        if any(not isinstance(row.get(field), (int, float)) for field in ("saves", "shotsAgainst", "goalsAgainst", "timeOnIce")):
            raise ValueError(f"game {game_id} player {player_id}: missing numeric goalie field")
    return payload


def paths(game_id: str) -> tuple[Path, Path]:
    return CACHE / f"{game_id}.json", CACHE / f"{game_id}.meta.json"


def one(game_id: str, player_ids: set[str]) -> dict[str, Any]:
    body_path, meta_path = paths(game_id)
    if body_path.exists() or meta_path.exists():
        if not body_path.is_file() or not meta_path.is_file():
            raise ValueError(f"game {game_id}: incomplete stats cache pair; refusing overwrite")
        body = body_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        digest = sha256(body)
        if meta.get("sha256") != digest or meta.get("bytes") != len(body):
            raise ValueError(f"game {game_id}: cached stats response hash/length mismatch")
        payload = validate_payload(game_id, player_ids, body)
    else:
        CACHE.mkdir(parents=True, exist_ok=True)
        url = build_url(game_id)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                body = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"game {game_id}: official stats REST request failed: {exc}") from exc
        if status != 200:
            raise RuntimeError(f"game {game_id}: expected HTTP 200 from official Stats REST, got {status}")
        payload = validate_payload(game_id, player_ids, body)
        meta = {
            "game_id": game_id,
            "source_url": url,
            "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "http_status": status,
            "content_type": content_type,
            "bytes": len(body),
            "sha256": sha256(body),
        }
        with body_path.open("xb") as handle:
            handle.write(body)
        with meta_path.open("x", encoding="utf-8") as handle:
            json.dump(meta, handle, sort_keys=True, indent=2)
            handle.write("\n")
    rows = payload["data"]
    data_by_id = {str(row["playerId"]): row for row in rows if str(row.get("playerId")) in player_ids}
    selected = []
    for player_id in sorted(player_ids, key=int):
        row = data_by_id[player_id]
        selected.append({
            "player_id": player_id,
            "saves": row["saves"],
            "shots_against": row["shotsAgainst"],
            "goals_against": row["goalsAgainst"],
            "toi_seconds": row["timeOnIce"],
        })
    return {
        "game_id": game_id,
        "source_url": meta["source_url"],
        "retrieved_at_utc": meta["retrieved_at_utc"],
        "http_status": meta["http_status"],
        "content_type": meta["content_type"],
        "bytes": len(body),
        "sha256": sha256(body),
        "cache_file": body_path.name,
        "selected_goalie_rows_json": json.dumps(selected, sort_keys=True, separators=(",", ":")),
    }


def main() -> int:
    grouped = targets()
    columns = ["game_id", "source_url", "retrieved_at_utc", "http_status", "content_type", "bytes", "sha256", "cache_file", "selected_goalie_rows_json"]
    rows = []
    for index, (game_id, player_ids) in enumerate(sorted(grouped.items(), key=lambda item: int(item[0]))):
        result = one(game_id, player_ids)
        rows.append(result)
        print(f"GOALIE_STATS {index + 1}/{len(grouped)} game={game_id} bytes={result['bytes']} sha256={result['sha256']}", flush=True)
        if index + 1 < len(grouped):
            time.sleep(PAUSE_SECONDS)
    temporary = MANIFEST.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(MANIFEST)
    print(f"GOALIE_STATS_EVIDENCE_PASS games={len(rows)} manifest={MANIFEST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
