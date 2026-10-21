#!/usr/bin/env python3
"""Cache NHL's historical Game Summary reports for the goalie cases."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
CACHE = Path("/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20/game-summaries")
MANIFEST = HERE / "game_summary_evidence_manifest.csv"
REPORTS = {
    "2022020158": {"goalie": "STOLARZ", "line": "5-44"},
    "2022020276": {"goalie": "LUUKKONEN", "line": "5-23"},
}
PAUSE_SECONDS = 1.1
USER_AGENT = "legendarypicks-research-outcome-quality/1.0"


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def report_url(game_id: str) -> str:
    return f"https://www.nhl.com/scores/htmlreports/20222023/GS{game_id[-6:]}.HTM"


def validate(game_id: str, body: bytes) -> str:
    text = html.unescape(re.sub(r"<[^>]*>", " ", body.decode("utf-8", errors="strict")))
    normalized = " ".join(text.upper().split())
    expected = REPORTS[game_id]
    if expected["goalie"] not in normalized or expected["line"] not in normalized:
        raise ValueError(f"game {game_id}: NHL Game Summary lacks expected goalie/line {expected}")
    if f"GAME {game_id[-4:]}" not in normalized:
        raise ValueError(f"game {game_id}: Game Summary has wrong game number")
    return normalized


def cache_paths(game_id: str) -> tuple[Path, Path]:
    return CACHE / f"{game_id}.html", CACHE / f"{game_id}.meta.json"


def one(game_id: str) -> dict[str, Any]:
    body_path, meta_path = cache_paths(game_id)
    if body_path.exists() or meta_path.exists():
        if not body_path.is_file() or not meta_path.is_file():
            raise ValueError(f"game {game_id}: incomplete HTML cache pair; refusing overwrite")
        body = body_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("sha256") != sha256(body) or meta.get("bytes") != len(body):
            raise ValueError(f"game {game_id}: cached Game Summary hash/length mismatch")
        normalized = validate(game_id, body)
    else:
        CACHE.mkdir(parents=True, exist_ok=True)
        url = report_url(game_id)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                body = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"game {game_id}: official Game Summary request failed: {exc}") from exc
        if status != 200:
            raise RuntimeError(f"game {game_id}: expected HTTP 200 from official Game Summary, got {status}")
        normalized = validate(game_id, body)
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
    return {
        "game_id": game_id,
        "source_url": meta["source_url"],
        "retrieved_at_utc": meta["retrieved_at_utc"],
        "http_status": meta["http_status"],
        "content_type": meta["content_type"],
        "bytes": len(body),
        "sha256": sha256(body),
        "cache_file": body_path.name,
        "confirmed_goalie": REPORTS[game_id]["goalie"],
        "confirmed_goalie_line": REPORTS[game_id]["line"],
        "normalized_report_sha256": sha256(normalized.encode("utf-8")),
    }


def main() -> int:
    columns = ["game_id", "source_url", "retrieved_at_utc", "http_status", "content_type", "bytes", "sha256", "cache_file", "confirmed_goalie", "confirmed_goalie_line", "normalized_report_sha256"]
    rows = []
    for index, game_id in enumerate(sorted(REPORTS, key=int)):
        row = one(game_id)
        rows.append(row)
        print(f"GAME_SUMMARY {index + 1}/{len(REPORTS)} game={game_id} bytes={row['bytes']} sha256={row['sha256']}", flush=True)
        if index + 1 < len(REPORTS):
            time.sleep(PAUSE_SECONDS)
    temporary = MANIFEST.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(MANIFEST)
    print(f"GAME_SUMMARY_EVIDENCE_PASS games={len(rows)} manifest={MANIFEST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
