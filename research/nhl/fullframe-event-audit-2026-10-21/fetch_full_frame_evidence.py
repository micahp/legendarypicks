#!/usr/bin/env python3
"""Resumable, source-pinned NHL PBP or shift-chart importer.

Every path is supplied on the command line. A body is reusable only after both
hashes, byte counts, source URL, game identity, and payload shape are verified.
Raw gzip bodies and sidecars belong in external durable storage, not Git.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Callable, Iterable

PBP_URL = "https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play"
SHIFT_URL = "https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={gid}"
USER_AGENT = "legendarypicks-research-event-audit/1.1 (+full-frame import)"
ACCESS_REFUSALS = {401, 403, 407, 429, 451}
MANIFEST_FIELDS = [
    "game_id", "kind", "url", "http_status", "content_type", "bytes_raw",
    "sha256_raw", "bytes_gz", "sha256_gz", "rows", "attempts",
    "retrieved_at_utc", "request_duration_seconds", "request_elapsed_with_pacing_seconds",
    "evidence_origin", "sample_event_manifest_sha256", "sample_source_commit",
    "source_identity_basis", "note",
]


class AccessRefused(RuntimeError):
    """The publisher refused access or rate-limited this request."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def source_url(kind: str, game_id: str) -> str:
    if kind == "pbp":
        return PBP_URL.format(gid=game_id)
    if kind == "shifts":
        return SHIFT_URL.format(gid=game_id)
    raise ValueError(f"UNKNOWN_SOURCE_KIND {kind!r}")


def load_game_ids(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "game_id" not in reader.fieldnames:
            raise ValueError(f"GAME_LIST_MISSING_GAME_ID_COLUMN {path}")
        ids = [str(row.get("game_id", "")).strip() for row in reader]
    if not ids:
        raise ValueError(f"EMPTY_GAME_LIST {path}")
    invalid = [gid for gid in ids if len(gid) != 10 or not gid.isdigit()]
    if invalid:
        raise ValueError(f"INVALID_NHL_GAME_ID {invalid[:5]}")
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_GAME_ID_IN_LIST")
    return ids


def validate_payload(kind: str, game_id: str, body: bytes) -> int:
    """Validate publisher identity and non-empty payload shape; return row count."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"PAYLOAD_NOT_JSON {game_id}/{kind}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"PAYLOAD_ROOT_NOT_OBJECT {game_id}/{kind}")
    if kind == "pbp":
        if str(payload.get("id")) != game_id:
            raise ValueError(f"PBP_GAME_ID_MISMATCH expected={game_id} actual={payload.get('id')!r}")
        if payload.get("gameType") != 2:
            raise ValueError(f"PBP_NOT_REGULAR_SEASON {game_id}: gameType={payload.get('gameType')!r}")
        for side in ("homeTeam", "awayTeam"):
            team = payload.get(side)
            if not isinstance(team, dict) or not isinstance(team.get("id"), int):
                raise ValueError(f"PBP_TEAM_ID_MISSING {game_id}/{side}")
        plays = payload.get("plays")
        if not isinstance(plays, list) or not plays or any(not isinstance(row, dict) for row in plays):
            raise ValueError(f"PBP_PLAYS_MISSING_OR_INVALID {game_id}")
        return len(plays)
    if kind == "shifts":
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"SHIFT_ROWS_MISSING_OR_INVALID {game_id}")
        identities = {str(row.get("gameId")) for row in rows}
        if identities != {game_id}:
            raise ValueError(f"SHIFT_GAME_ID_MISMATCH expected={game_id} actual={sorted(identities)}")
        total = payload.get("total")
        if total is not None and (isinstance(total, bool) or int(total) != len(rows)):
            raise ValueError(f"SHIFT_TOTAL_COUNT_MISMATCH {game_id}: total={total!r} rows={len(rows)}")
        return len(rows)
    raise ValueError(f"UNKNOWN_SOURCE_KIND {kind!r}")


def body_paths(raw_dir: Path, game_id: str, kind: str) -> tuple[Path, Path]:
    return raw_dir / kind / f"{game_id}.json.gz", raw_dir / kind / f"{game_id}.meta.json"


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _read_cached(raw_dir: Path, game_id: str, kind: str) -> tuple[dict, bytes] | None:
    gz_path, meta_path = body_paths(raw_dir, game_id, kind)
    if not gz_path.exists() and not meta_path.exists():
        return None
    if gz_path.is_file() and not meta_path.exists():
        try:
            compressed = gz_path.read_bytes()
            raw = gzip.decompress(compressed)
        except (OSError, EOFError, gzip.BadGzipFile, zlib.error) as exc:
            raise ValueError(f"CACHE_ORPHAN_BODY_UNREADABLE {game_id}/{kind}: {exc}") from exc
        row_count = validate_payload(kind, game_id, raw)
        recovered = {
            "game_id": game_id, "kind": kind, "url": source_url(kind, game_id),
            "http_status": 200,
            "content_type": "application/json (recovered; response header unavailable)",
            "bytes_raw": len(raw), "sha256_raw": sha256(raw),
            "bytes_gz": len(compressed), "sha256_gz": sha256(compressed),
            "rows": row_count, "attempts": "unknown", "retrieved_at_utc": "",
            "request_duration_seconds": "", "request_elapsed_with_pacing_seconds": "",
            "evidence_origin": "recovered_valid_orphan_body_after_interruption",
            "source_identity_basis": "expected_source_url_and_payload_game_id",
        }
        _atomic_bytes(meta_path, (json.dumps(recovered, indent=2, sort_keys=True) + "\n").encode())
        return recovered, compressed
    if not gz_path.is_file() or not meta_path.is_file():
        raise ValueError(f"CACHE_PAIR_INCOMPLETE {game_id}/{kind}: {gz_path}, {meta_path}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        compressed = gz_path.read_bytes()
        raw = gzip.decompress(compressed)
    except (OSError, json.JSONDecodeError, EOFError, gzip.BadGzipFile, zlib.error) as exc:
        raise ValueError(f"CACHE_UNREADABLE {game_id}/{kind}: {exc}") from exc
    expected_url = source_url(kind, game_id)
    if meta.get("game_id") != game_id or meta.get("kind") != kind:
        raise ValueError(f"CACHE_SOURCE_IDENTITY_MISMATCH {game_id}/{kind}")
    if meta.get("url") != expected_url or meta.get("http_status") != 200:
        raise ValueError(f"CACHE_SOURCE_URL_OR_STATUS_MISMATCH {game_id}/{kind}")
    if "json" not in str(meta.get("content_type", "")).lower():
        raise ValueError(f"CACHE_CONTENT_TYPE_NOT_JSON {game_id}/{kind}")
    checks = (
        (len(compressed), meta.get("bytes_gz"), "CACHE_COMPRESSED_BYTE_COUNT_MISMATCH"),
        (sha256(compressed), meta.get("sha256_gz"), "CACHE_COMPRESSED_HASH_MISMATCH"),
        (len(raw), meta.get("bytes_raw"), "CACHE_RAW_BYTE_COUNT_MISMATCH"),
        (sha256(raw), meta.get("sha256_raw"), "CACHE_RAW_HASH_MISMATCH"),
    )
    for actual, expected, reason in checks:
        if str(actual) != str(expected):
            raise ValueError(f"{reason} {game_id}/{kind}: expected={expected} actual={actual}")
    row_count = validate_payload(kind, game_id, raw)
    if row_count != meta.get("rows"):
        raise ValueError(f"CACHE_PAYLOAD_ROW_COUNT_MISMATCH {game_id}/{kind}: {row_count}!={meta.get('rows')}")
    meta.setdefault("evidence_origin", "preexisting_cache_origin_unrecorded")
    return meta, compressed


def verified_existing(raw_dir: Path, game_id: str, kind: str) -> dict | None:
    found = _read_cached(raw_dir, game_id, kind)
    return found[0] if found else None


def _adopt_cache(source_dir: Path, raw_dir: Path, game_id: str, kind: str,
                 meta: dict, compressed: bytes) -> dict:
    gz_path, meta_path = body_paths(raw_dir, game_id, kind)
    if gz_path.exists() or meta_path.exists():
        raise ValueError(f"REFUSE_CACHE_OVERWRITE {game_id}/{kind}")
    origin = f"cache:{source_dir.resolve()}"
    adopted = dict(meta)
    adopted["evidence_origin"] = origin
    _atomic_bytes(gz_path, compressed)
    _atomic_bytes(meta_path, (json.dumps(adopted, indent=2, sort_keys=True) + "\n").encode())
    return adopted


def _find_reusable(game_id: str, kind: str, reuse_dirs: Iterable[Path]) -> tuple[Path, dict, bytes] | None:
    candidates = []
    for directory in reuse_dirs:
        cached = _read_cached(directory, game_id, kind)
        if cached is not None:
            candidates.append((directory, cached[0], cached[1]))
    if not candidates:
        return None
    hashes = {meta["sha256_raw"] for _, meta, _ in candidates}
    if len(hashes) != 1:
        raise ValueError(f"CACHE_SOURCE_CONFLICT {game_id}/{kind}: {sorted(hashes)}")
    return candidates[0]


def _store_network_body(raw_dir: Path, game_id: str, kind: str, body: bytes,
                        content_type: str, retrieved_at: dt.datetime, attempts: int,
                        request_duration_seconds: float) -> dict:
    row_count = validate_payload(kind, game_id, body)
    gz_path, meta_path = body_paths(raw_dir, game_id, kind)
    if gz_path.exists() or meta_path.exists():
        raise ValueError(f"REFUSE_BODY_OVERWRITE {game_id}/{kind}")
    compressed = gzip.compress(body, compresslevel=9, mtime=0)
    meta = {
        "game_id": game_id, "kind": kind, "url": source_url(kind, game_id),
        "http_status": 200, "content_type": content_type,
        "bytes_raw": len(body), "sha256_raw": sha256(body),
        "bytes_gz": len(compressed), "sha256_gz": sha256(compressed),
        "rows": row_count, "attempts": attempts,
        "retrieved_at_utc": retrieved_at.isoformat(timespec="milliseconds"),
        "request_duration_seconds": round(request_duration_seconds, 4),
        "evidence_origin": "network",
    }
    _atomic_bytes(gz_path, compressed)
    _atomic_bytes(meta_path, (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode())
    return meta


def fetch_one(game_id: str, kind: str, raw_dir: Path, retries: int = 2) -> dict:
    url = source_url(kind, game_id)
    last_error = "unknown request failure"
    started = time.monotonic()
    for attempt in range(retries + 1):
        request_started = dt.datetime.now(dt.timezone.utc)
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP_STATUS_NOT_200 {game_id}/{kind}: {response.status}")
                content_type = response.headers.get("Content-Type", "")
                body = response.read()
            if "json" not in content_type.lower():
                raise ValueError(f"UNEXPECTED_CONTENT_TYPE {game_id}/{kind}: {content_type!r}")
            return _store_network_body(raw_dir, game_id, kind, body, content_type,
                                       request_started, attempt + 1,
                                       time.monotonic() - started)
        except urllib.error.HTTPError as exc:
            if exc.code in ACCESS_REFUSALS:
                raise AccessRefused(f"SOURCE_REFUSED_{exc.code} {url}; stopping this source") from None
            last_error = f"HTTP_{exc.code}"
            if exc.code not in {500, 502, 503, 504} or attempt == retries:
                break
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            last_error = f"NETWORK_ERROR {exc}"
            if attempt == retries:
                break
        if attempt < retries:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"REQUEST_FAILED {game_id}/{kind} after {retries + 1} attempts: {last_error}")


def write_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def write_json_atomic(path: Path, value: dict) -> None:
    _atomic_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def run_import(*, kind: str, games_file: Path, raw_dir: Path, manifest: Path,
               report_out: Path, reuse_dirs: Iterable[Path] = (), pause: float = 0.9,
               max_new: int = 0, budget_seconds: int = 0, retries: int = 2,
               flush_every: int = 10, fetcher: Callable = fetch_one,
               sleeper: Callable[[float], None] = time.sleep,
               resume_after_refusal: bool = False) -> dict:
    if kind not in {"pbp", "shifts"}:
        raise ValueError(f"INVALID_KIND {kind}")
    if pause < 0 or retries < 0 or flush_every < 1:
        raise ValueError("INVALID_IMPORT_PACING_OR_RETRY_OPTION")
    game_ids = load_game_ids(games_file)
    progress_manifest = manifest.with_name(f"{manifest.stem}.progress{manifest.suffix}")
    if report_out.is_file() and not resume_after_refusal:
        try:
            previous_report = json.loads(report_out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_report = {}
        if previous_report.get("stop_reason") == "access_refused":
            raise AccessRefused(
                f"PREVIOUS_ACCESS_REFUSAL_IN_REPORT {report_out}; pass --resume-after-refusal only after access is restored"
            )
    if manifest.is_file() and not resume_after_refusal:
        with manifest.open(newline="", encoding="utf-8") as handle:
            for previous in csv.DictReader(handle):
                note = previous.get("note", "")
                status = previous.get("http_status", "")
                if "SOURCE_REFUSED_" in note or status in {str(code) for code in ACCESS_REFUSALS}:
                    raise AccessRefused(
                        f"PREVIOUS_ACCESS_REFUSAL_IN_MANIFEST {manifest}; pass --resume-after-refusal only after access is restored"
                    )
    started_utc = dt.datetime.now(dt.timezone.utc)
    started = time.monotonic()
    rows: list[dict] = []
    new = reused_local = reused_external = failed = 0
    request_wall_seconds = 0.0
    request_duration_seconds = 0.0
    network_attempts = 0
    stop_reason = "complete"
    next_index = 0
    failed_game_id = ""
    failure_note = ""

    def flush() -> None:
        write_manifest(progress_manifest, rows)

    try:
        for index, game_id in enumerate(game_ids):
            next_index = index
            try:
                meta = verified_existing(raw_dir, game_id, kind)
            except Exception as exc:
                failed += 1
                failed_game_id = game_id
                failure_note = f"CACHE_VERIFICATION_FAILED: {type(exc).__name__}: {exc}"
                rows.append({"game_id": game_id, "kind": kind, "url": source_url(kind, game_id),
                             "note": failure_note, "evidence_origin": "cache_rejected"})
                stop_reason = "cache_verification_failed"
                next_index = index + 1
                break
            if meta is not None:
                reused_local += 1
                rows.append({field: meta.get(field, "") for field in MANIFEST_FIELDS})
                next_index = index + 1
                continue

            try:
                reusable = _find_reusable(game_id, kind, reuse_dirs)
            except Exception as exc:
                failed += 1
                failed_game_id = game_id
                failure_note = f"SECONDARY_CACHE_VERIFICATION_FAILED: {type(exc).__name__}: {exc}"
                rows.append({"game_id": game_id, "kind": kind, "url": source_url(kind, game_id),
                             "note": failure_note, "evidence_origin": "cache_rejected"})
                stop_reason = "cache_verification_failed"
                next_index = index + 1
                break
            if reusable is not None:
                source_dir, source_meta, compressed = reusable
                # _find_reusable verified compressed and decompressed bytes plus source identity.
                raw_meta = _adopt_cache(source_dir, raw_dir, game_id, kind, source_meta, compressed)
                reused_external += 1
                rows.append({field: raw_meta.get(field, "") for field in MANIFEST_FIELDS})
                next_index = index + 1
                continue

            if max_new and new >= max_new:
                stop_reason = "max_new"
                next_index = index
                break
            if budget_seconds and time.monotonic() - started >= budget_seconds:
                stop_reason = "budget"
                next_index = index
                break
            request_start = time.monotonic()
            sleeper(pause)
            fetch_start = time.monotonic()
            try:
                meta = fetcher(game_id, kind, raw_dir, retries)
            except AccessRefused as exc:
                duration = time.monotonic() - fetch_start
                elapsed_with_pacing = time.monotonic() - request_start
                request_duration_seconds += duration
                request_wall_seconds += elapsed_with_pacing
                network_attempts += 1
                failed += 1
                failed_game_id = game_id
                failure_note = str(exc)
                rows.append({"game_id": game_id, "kind": kind, "url": source_url(kind, game_id),
                             "request_duration_seconds": round(duration, 4),
                             "request_elapsed_with_pacing_seconds": round(elapsed_with_pacing, 4),
                             "note": str(exc), "evidence_origin": "request_failed"})
                stop_reason = "access_refused"
                next_index = index + 1
                break
            except Exception as exc:
                duration = time.monotonic() - fetch_start
                elapsed_with_pacing = time.monotonic() - request_start
                request_duration_seconds += duration
                request_wall_seconds += elapsed_with_pacing
                network_attempts += 1
                failed += 1
                failed_game_id = game_id
                failure_note = f"{type(exc).__name__}: {exc}"
                rows.append({"game_id": game_id, "kind": kind, "url": source_url(kind, game_id),
                             "request_duration_seconds": round(duration, 4),
                             "request_elapsed_with_pacing_seconds": round(elapsed_with_pacing, 4),
                             "note": failure_note, "evidence_origin": "request_failed"})
                stop_reason = "request_failed"
                next_index = index + 1
                break
            duration = time.monotonic() - fetch_start
            elapsed_with_pacing = time.monotonic() - request_start
            request_duration_seconds += duration
            request_wall_seconds += elapsed_with_pacing
            network_attempts += int(meta.get("attempts") or 1)
            meta["request_duration_seconds"] = round(duration, 4)
            meta["request_elapsed_with_pacing_seconds"] = round(elapsed_with_pacing, 4)
            new += 1
            rows.append({field: meta.get(field, "") for field in MANIFEST_FIELDS})
            next_index = index + 1
            if new % flush_every == 0:
                flush()
    except KeyboardInterrupt:
        stop_reason = "interrupted"
    finally:
        if next_index < len(game_ids):
            for game_id in game_ids[next_index:]:
                rows.append({"game_id": game_id, "kind": kind, "url": source_url(kind, game_id),
                             "note": f"not_attempted_after_{stop_reason}",
                             "evidence_origin": "not_fetched"})
        flush()

    elapsed = time.monotonic() - started
    verified = sum(bool(row.get("sha256_raw")) for row in rows)
    manifest_published = (stop_reason == "complete" and failed == 0
                          and len(rows) == len(game_ids) and verified == len(game_ids))
    if manifest_published:
        write_manifest(manifest, rows)
        try:
            progress_manifest.unlink()
        except FileNotFoundError:
            pass
    remaining_uncached = len(game_ids) - verified
    observed_mean = request_wall_seconds / new if new else None
    report = {
        "kind": kind,
        "games_file": str(games_file.resolve()),
        "games_file_sha256": file_sha256(games_file),
        "games_listed": len(game_ids),
        "verified_bodies": verified,
        "network_bodies_new": new,
        "reused_from_primary_cache": reused_local,
        "reused_from_secondary_cache": reused_external,
        "failed_requests": failed,
        "network_attempts": network_attempts,
        "missing_or_unverified": len(game_ids) - verified,
        "request_pause_seconds": pause,
        "network_wall_seconds_including_pause": round(request_wall_seconds, 3),
        "network_call_seconds_excluding_pause": round(request_duration_seconds, 3),
        "observed_seconds_per_new_body_including_pause": round(observed_mean, 4) if observed_mean is not None else None,
        "remaining_uncached_bodies": remaining_uncached,
        "minimum_remaining_seconds_at_configured_pause": round(remaining_uncached * pause, 3),
        "projected_remaining_seconds_at_observed_mean": round(remaining_uncached * observed_mean, 3) if observed_mean is not None else None,
        "elapsed_seconds": round(elapsed, 3),
        "started_at_utc": started_utc.isoformat(timespec="seconds"),
        "finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "stop_reason": stop_reason,
        "failed_game_id": failed_game_id,
        "failure_note": failure_note,
        "manifest": str(manifest.resolve()),
        "manifest_published": manifest_published,
        "manifest_sha256": file_sha256(manifest) if manifest.is_file() else None,
        "progress_manifest": str(progress_manifest.resolve()) if not manifest_published else None,
        "progress_manifest_sha256": file_sha256(progress_manifest) if progress_manifest.is_file() else None,
    }
    write_json_atomic(report_out, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("pbp", "shifts"), required=True)
    parser.add_argument("--games", type=Path, required=True, help="source-specific game list CSV")
    parser.add_argument("--raw-dir", type=Path, required=True, help="external raw cache root")
    parser.add_argument("--manifest", type=Path, required=True, help="source-specific manifest CSV")
    parser.add_argument("--report-out", type=Path, required=True, help="source-specific run report JSON")
    parser.add_argument("--reuse-raw-dir", type=Path, action="append", default=[],
                        help="validated secondary cache; may be supplied more than once")
    parser.add_argument("--pause", type=float, default=0.9,
                        help="minimum delay before each request; response time adds to this")
    parser.add_argument("--max-new", type=int, default=0, help="stop after N new bodies (0=unlimited)")
    parser.add_argument("--budget-seconds", type=int, default=0, help="wall-clock budget (0=unlimited)")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--flush-every", type=int, default=10,
                        help="write an atomic progress checkpoint every N new bodies")
    parser.add_argument("--resume-after-refusal", action="store_true",
                        help="resume only after access has been restored and a prior refusal is cleared")
    args = parser.parse_args()
    try:
        report = run_import(
            kind=args.kind, games_file=args.games, raw_dir=args.raw_dir,
            manifest=args.manifest, report_out=args.report_out,
            reuse_dirs=args.reuse_raw_dir, pause=args.pause, max_new=args.max_new,
            budget_seconds=args.budget_seconds, retries=args.retries,
            flush_every=args.flush_every, resume_after_refusal=args.resume_after_refusal,
        )
    except AccessRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["stop_reason"] == "complete" and not report["failed_requests"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
