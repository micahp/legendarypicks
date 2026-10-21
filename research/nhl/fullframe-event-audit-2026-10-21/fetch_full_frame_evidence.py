#!/usr/bin/env python3
"""Fetch, verify and manifest NHL event evidence for an explicit game list.

Two official sources per game:

  play-by-play  https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play
  shift charts  https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={game_id}

Contract (from the audit brief):

* the game list, the raw store, and the manifest are all command-line arguments --
  no module-level constants have to be edited to run a different scope;
* an existing body whose sidecar hash verifies is reused, never re-downloaded and
  never overwritten, so an interrupted run resumes without repeating valid work;
* a body counts only if the payload passes shape validation (game id, regular
  season, non-empty plays / shift rows);
* the manifest is written atomically (temp file + os.replace), so a crash or a
  failed request can never truncate the previous manifest;
* an access refusal (401/403/407/429/451) stops the run instead of hammering the
  source; a stopped run is resumable and says so;
* raw bodies live outside Git, one gzipped file per game per source, each with a
  sidecar carrying uncompressed and compressed SHA256 and byte counts.

Usage:
    python fetch_full_frame_evidence.py --kind pbp \
        --games full_frame_games.csv --raw-dir /root/lp-data/.../raw \
        --manifest /root/lp-data/.../pbp_evidence_manifest.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import os
import signal
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PBP_URL = "https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play"
SHIFT_URL = "https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={gid}"
UA = "legendarypicks-research-event-audit/1.0 (+full-frame import)"
REFUSALS = {401, 403, 407, 429, 451}
FIELDS = ["game_id", "kind", "url", "http_status", "content_type", "bytes_raw",
          "sha256_raw", "bytes_gz", "sha256_gz", "rows", "retrieved_at_utc", "note"]

EXIT_REFUSED = 3
EXIT_BUDGET = 4


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_games(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        game_ids = [r["game_id"].strip() for r in csv.DictReader(handle)]
    if not game_ids:
        raise SystemExit(f"no games in {path}")
    if len(game_ids) != len(set(game_ids)):
        raise SystemExit(f"duplicate game ids in {path}")
    return game_ids


def validate(kind: str, gid: str, body: bytes) -> int:
    """Return the number of rows the payload contributes; raise if the shape is wrong."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{gid}/{kind}: response is not JSON ({exc})") from exc
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


def paths_for(raw_dir: Path, gid: str, kind: str) -> tuple[Path, Path]:
    return raw_dir / kind / f"{gid}.json.gz", raw_dir / kind / f"{gid}.meta.json"


def existing(raw_dir: Path, gid: str, kind: str) -> dict | None:
    gz, meta = paths_for(raw_dir, gid, kind)
    if not (gz.exists() and meta.exists()):
        return None
    m = json.loads(meta.read_text(encoding="utf-8"))
    if sha256(gz.read_bytes()) != m.get("sha256_gz"):
        # A body that does not match its sidecar is not evidence; say so instead of
        # silently reusing or overwriting it.
        raise ValueError(f"{gid}/{kind}: cached body does not match its sidecar")
    return m


def store(raw_dir: Path, gid: str, kind: str, url: str, status: int, ctype: str,
          body: bytes, rows: int, retrieved_at: dt.datetime) -> dict:
    gz_path, meta_path = paths_for(raw_dir, gid, kind)
    gz_path.parent.mkdir(parents=True, exist_ok=True)
    blob = gzip.compress(body, 9)
    tmp_gz = gz_path.with_suffix(".json.gz.tmp")
    tmp_gz.write_bytes(blob)
    os.replace(tmp_gz, gz_path)
    meta = {
        "game_id": gid, "kind": kind, "url": url, "http_status": status,
        "content_type": ctype, "bytes_raw": len(body), "sha256_raw": sha256(body),
        "bytes_gz": len(blob), "sha256_gz": sha256(blob), "rows": rows,
        "retrieved_at_utc": retrieved_at.isoformat(timespec="seconds"), "note": "",
    }
    tmp_meta = meta_path.with_suffix(".json.tmp")
    tmp_meta.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_meta, meta_path)
    return meta


def fetch_one(gid: str, kind: str, raw_dir: Path, retries: int) -> dict:
    url = (PBP_URL if kind == "pbp" else SHIFT_URL).format(gid=gid)
    last_error: str | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        t0 = dt.datetime.now(dt.timezone.utc)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status = resp.status
                ctype = resp.headers.get("Content-Type", "")
                body = resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
            body = b""
            if status in REFUSALS:
                raise SystemExit(
                    f"source refused ({status}) at {url}; manifest preserved, resume later"
                ) from None
            if status in (500, 502, 503, 504) and attempt < retries:
                last_error = f"HTTP {status}"
                time.sleep(2 ** attempt)
                continue
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            if attempt < retries:
                last_error = f"network: {exc}"
                time.sleep(2 ** attempt)
                continue
            raise ValueError(f"{gid}/{kind}: network failure after {retries} retries: {exc}") from exc
        if status != 200:
            raise ValueError(f"{gid}/{kind}: HTTP {status}{' ' + ctype if ctype else ''}")
        rows = validate(kind, gid, body)
        return store(raw_dir, gid, kind, url, status, ctype, body, rows, t0)
    raise ValueError(f"{gid}/{kind}: gave up ({last_error})")


def write_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch and manifest NHL event evidence for an explicit game list")
    ap.add_argument("--kind", choices=["pbp", "shifts"], required=True,
                    help="one source per run; the two hosts are paced independently")
    ap.add_argument("--games", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--pause", type=float, default=0.9, help="seconds between request starts")
    ap.add_argument("--max-new", type=int, default=0, help="stop after N new bodies (0 = no limit)")
    ap.add_argument("--budget-seconds", type=int, default=0,
                    help="stop gracefully after N seconds (0 = no limit)")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--flush-every", type=int, default=10,
                    help="rewrite the manifest atomically every N new bodies")
    args = ap.parse_args()

    game_ids = load_games(args.games)
    started = time.monotonic()
    rows: list[dict] = []
    new = reused = 0
    unfetched: list[dict] = []
    stop_reason = "complete"
    last_write = 0

    def flush() -> None:
        write_manifest(args.manifest, rows + unfetched)

    try:
        for gid in game_ids:
            m = existing(args.raw_dir, gid, args.kind)
            if m is None:
                if args.max_new and new >= args.max_new:
                    stop_reason = "max-new"
                    break
                if args.budget_seconds and time.monotonic() - started >= args.budget_seconds:
                    stop_reason = "budget"
                    break
                time.sleep(args.pause)
                try:
                    m = fetch_one(gid, args.kind, args.raw_dir, args.retries)
                except ValueError as exc:
                    rows.append(dict(game_id=gid, kind=args.kind, note=str(exc)))
                    continue
                new += 1
                if new - last_write >= args.flush_every:
                    last_write = new
                    flush()
            else:
                reused += 1
            rows.append({k: m.get(k, "") for k in FIELDS})
    except KeyboardInterrupt:
        stop_reason = "interrupted"
    finally:
        fetched = {r["game_id"] for r in rows if r.get("sha256_raw")}
        for gid in game_ids:
            if gid not in fetched and not any(r["game_id"] == gid for r in rows):
                unfetched.append(dict(game_id=gid, kind=args.kind, note="not fetched"))
        flush()

    elapsed = time.monotonic() - started
    verified = sum(1 for r in rows if r.get("sha256_gz"))
    print(json.dumps({
        "kind": args.kind,
        "games_listed": len(game_ids),
        "bodies_verified": verified,
        "new_this_run": new,
        "reused": reused,
        "failed": len([r for r in rows if r.get("note") and not r.get("sha256_gz")]),
        "elapsed_seconds": round(elapsed, 1),
        "requests_per_minute": round(new / (elapsed / 60), 1) if elapsed > 0 and new else 0.0,
        "stop_reason": stop_reason,
        "manifest": str(args.manifest),
    }, indent=2, sort_keys=True))
    if stop_reason in ("budget", "max-new", "interrupted"):
        sys.exit(EXIT_BUDGET)


if __name__ == "__main__":
    main()
