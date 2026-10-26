#!/usr/bin/env python3
"""Fetch and hash-pin NHL event evidence for the audit sample.

Two sources per game, both official:

  play-by-play  https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play
  shift charts  https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={game_id}

Raw bodies are gzipped outside Git at /root/lp-data/nhl-event-data-audit-2026-10-20/
with a per-file sidecar carrying the uncompressed and compressed SHA256, so every
audit number can be traced to bytes that can be re-verified later.

Resumable and non-destructive: an existing validated body is reused, never
overwritten. One request at a time with a pause between starts. Stops on an
access-refusal status (401/403/407/429/451) rather than hammering the source.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample_games.csv"
CACHE = Path("/root/lp-data/nhl-event-data-audit-2026-10-20")
RAW = CACHE / "raw"
MANIFEST = HERE / "event_evidence_manifest.csv"

PBP_URL = "https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play"
SHIFT_URL = "https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={gid}"
PAUSE = 1.1
UA = "legendarypicks-research-event-audit/1.0"
REFUSALS = {401, 403, 407, 429, 451}
FIELDS = ["game_id", "kind", "url", "http_status", "content_type", "bytes_raw",
          "sha256_raw", "bytes_gz", "sha256_gz", "rows", "retrieved_at_utc", "note"]


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_sample() -> list[str]:
    with SAMPLE.open(newline="", encoding="utf-8") as fh:
        return [r["game_id"] for r in csv.DictReader(fh)]


def validate(kind: str, gid: str, body: bytes) -> int:
    """Return the row count the payload should contribute to the audit."""
    payload = json.loads(body)
    if kind == "pbp":
        if str(payload.get("id")) != gid:
            raise ValueError(f"{gid}: PBP id={payload.get('id')!r}")
        if payload.get("gameType") != 2:
            raise ValueError(f"{gid}: PBP gameType={payload.get('gameType')!r} (not regular season)")
        plays = payload.get("plays")
        if not isinstance(plays, list) or not plays:
            raise ValueError(f"{gid}: PBP has no plays")
        return len(plays)
    if kind == "shifts":
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise ValueError(f"{gid}: shift chart has no rows")
        ids = {str(r.get("gameId")) for r in data}
        if ids != {gid}:
            raise ValueError(f"{gid}: shift chart gameId {sorted(ids)}")
        return len(data)
    raise ValueError(kind)


def cached(gid: str, kind: str) -> tuple[Path, Path]:
    return RAW / kind / f"{gid}.json.gz", RAW / kind / f"{gid}.meta.json"


def existing(gid: str, kind: str) -> dict | None:
    gz, meta = cached(gid, kind)
    if not (gz.exists() and meta.exists()):
        return None
    m = json.loads(meta.read_text(encoding="utf-8"))
    if sha256(gz.read_bytes()) != m["sha256_gz"]:
        raise ValueError(f"{gid}/{kind}: cached body does not match its sidecar")
    return m


def fetch(gid: str, kind: str) -> dict:
    url = (PBP_URL if kind == "pbp" else SHIFT_URL).format(gid=gid)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    t0 = dt.datetime.now(dt.timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status, ctype = resp.status, resp.headers.get("Content-Type", "")
            body = resp.read()
    except urllib.error.HTTPError as exc:
        status, ctype, body = exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", b""
        if status in REFUSALS:
            raise SystemExit(f"source refused ({status}) at {url}; stopping, resume later")
    if status != 200:
        raise ValueError(f"{gid}/{kind}: HTTP {status}")

    rows = validate(kind, gid, body)
    gz_path, meta_path = cached(gid, kind)
    gz_path.parent.mkdir(parents=True, exist_ok=True)
    blob = gzip.compress(body, 9)
    gz_path.write_bytes(blob)
    meta = {
        "game_id": gid, "kind": kind, "url": url, "http_status": status,
        "content_type": ctype, "bytes_raw": len(body), "sha256_raw": sha256(body),
        "bytes_gz": len(blob), "sha256_gz": sha256(blob), "rows": rows,
        "retrieved_at_utc": t0.isoformat(timespec="seconds"), "note": "",
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-new", type=int, default=0, help="bounded probe: stop after N new bodies")
    ap.add_argument("--kind", choices=["pbp", "shifts", "both"], default="both")
    args = ap.parse_args()

    games = load_sample()
    kinds = ["pbp", "shifts"] if args.kind == "both" else [args.kind]
    new = 0
    rows: list[dict] = []
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for i, gid in enumerate(games):
            for kind in kinds:
                m = existing(gid, kind)
                if m is None:
                    if args.max_new and new >= args.max_new:
                        rows.append(dict(game_id=gid, kind=kind, url="", http_status="",
                                         content_type="", bytes_raw="", sha256_raw="",
                                         bytes_gz="", sha256_gz="", rows="",
                                         retrieved_at_utc="", note="not fetched (max-new)"))
                        continue
                    time.sleep(PAUSE)
                    m = fetch(gid, kind)
                    new += 1
                rows.append({k: m.get(k, "") for k in FIELDS})
        for r in rows:
            w.writerow(r)
    got = sum(1 for r in rows if r["sha256_raw"])
    print(f"bodies on disk: {got}/{len(games) * len(kinds)} (new this run: {new})")
    print(f"manifest -> {MANIFEST}")


if __name__ == "__main__":
    main()
