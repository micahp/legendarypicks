#!/usr/bin/env python3
"""Resolve blank Flashscore tournament references from each match's own public page.

The output JSONL is an append-only fetch cache. Parsed tournament metadata and source
URLs are retained in a CSV. The existing raw feed rows remain unchanged.
"""
from __future__ import annotations

import csv
import gzip
import html
import json
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DB = ROOT / "backend/data/picks.dev.db"
CACHE = HERE / "flashscore_tournament_resolution_2026-10-16.jsonl"
CSV = HERE / "flashscore_tournament_resolution_2026-10-16.csv"
WORKERS = 2
REQUEST_INTERVAL = 0.5  # Global page-start rate: at most two requests per second.
MAX_BYTES = 2_500_000

_pace_lock = threading.Lock()
_next_request_at = 0.0
_write_lock = threading.Lock()


def normalize(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def targets() -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT m.tour,m.source_match_id,m.match_date,m.player1_name,m.player2_name,m.source_match_url "
            "FROM tennis_points m WHERE m.record_kind='match_status' AND m.tour IN ('atp','wta') "
            "AND (m.tournament_name IS NULL OR m.tournament_name='') "
            "AND m.source_match_url IS NOT NULL AND EXISTS (SELECT 1 FROM tennis_points e "
            "WHERE e.tour=m.tour AND e.source_match_id=m.source_match_id AND e.record_kind='game_sequence') "
            "ORDER BY m.match_date,m.tour,m.source_match_id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def append_cache(result: dict[str, Any]) -> None:
    with _write_lock:
        with CACHE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
            f.flush()


def page_metadata(body: str) -> dict[str, Any] | None:
    # Flashscore includes unrelated string-valued `tournament` keys earlier in the
    # document; anchor on the event object that starts with a category.
    match = re.search(r'"tournament"\s*:\s*\{\s*"category"\s*:', body)
    if not match:
        return None
    value_start = body.find("{", match.start())
    try:
        event, _ = json.JSONDecoder().raw_decode(body[value_start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    return event


def extract_name(raw_name: str) -> str:
    # The page label normally appends court surface and round to the event name.
    return re.sub(r",\s*(?:clay|hard|grass|carpet)\b.*$", "", raw_name, flags=re.I).strip()


def fetch_one(match: dict[str, Any]) -> dict[str, Any]:
    global _next_request_at
    with _pace_lock:
        wait = _next_request_at - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _next_request_at = time.monotonic() + REQUEST_INTERVAL

    request = urllib.request.Request(
        match["source_match_url"],
        headers={
            "User-Agent": "LegendaryPicksResearch/1.0 (tennis source cross-reference)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError(f"page exceeded {MAX_BYTES} bytes")
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    data = gzip.decompress(data)
                body = data.decode("utf-8", "replace")
                title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
                title = html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else ""
                event = page_metadata(body)
                raw_name = str(event.get("tournament", "")).strip() if event else ""
                link = str(event.get("link", "")).strip() if event else ""
                title_norm = normalize(title)
                players_check = bool(title_norm and normalize(match["player1_name"]) in title_norm
                                     and normalize(match["player2_name"]) in title_norm)
                result = {
                    **match,
                    "http_status": response.status,
                    "page_title": title,
                    "match_title_players_check": players_check,
                    "page_category": event.get("category") if event else None,
                    "tournament_label_raw": raw_name or None,
                    "tournament_name": extract_name(raw_name) if raw_name else None,
                    "tournament_path": link or None,
                    "tournament_id": f"flashscore:{link.strip('/')}" if link else None,
                    "fetch_error": None if raw_name and link and players_check else
                    "page title/player mismatch" if not players_check else "event tournament metadata not found",
                }
                return result
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code not in (429, 500, 502, 503, 504):
                break
        except Exception as exc:  # network and parsing errors are retained for resume/review
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < 2:
            time.sleep(2 ** (attempt + 1))
    return {**match, "http_status": None, "page_title": None, "match_title_players_check": False, "page_category": None,
            "tournament_label_raw": None, "tournament_name": None, "tournament_path": None,
            "tournament_id": None, "fetch_error": last_error or "unknown fetch failure"}


def load_cache() -> dict[tuple[str, str], dict[str, Any]]:
    cached: dict[tuple[str, str], dict[str, Any]] = {}
    if not CACHE.exists():
        return cached
    with CACHE.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            cached[(row.get("tour", ""), row.get("source_match_id", ""))] = row
    return cached


def write_csv(rows: list[dict[str, Any]]) -> None:
    fields = ["tour", "source_match_id", "match_date", "player1_name", "player2_name",
              "match_title_players_check",
              "page_title", "page_category", "tournament_name", "tournament_label_raw",
              "tournament_id", "tournament_path", "source_match_url", "http_status", "fetch_error"]
    with CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fields} for row in rows)


def apply_resolved(rows: list[dict[str, Any]]) -> tuple[int, int]:
    # Only write records with both the event label and the source tournament path.
    resolved = [r for r in rows if r.get("tournament_name") and r.get("tournament_id")
                and r.get("match_title_players_check")]
    conn = sqlite3.connect(DB, timeout=600)
    updated_rows = updated_matches = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        for row in resolved:
            # Ensure the match and player identities have not changed since retrieval.
            status = conn.execute(
                "SELECT player1_name,player2_name,tournament_name FROM tennis_points "
                "WHERE tour=? AND source_match_id=? AND record_kind='match_status'",
                (row["tour"], row["source_match_id"]),
            ).fetchone()
            if not status or normalize(status[0]) != normalize(row["player1_name"]) or normalize(status[1]) != normalize(row["player2_name"]):
                continue
            if status[2]:
                continue
            cursor = conn.execute(
                "UPDATE tennis_points SET tournament_source='flashscore_match_page',tournament_id=?,tournament_name=? "
                "WHERE tour=? AND source_match_id=? AND (tournament_name IS NULL OR tournament_name='')",
                (row["tournament_id"], row["tournament_name"], row["tour"], row["source_match_id"]),
            )
            if cursor.rowcount:
                updated_matches += 1
                updated_rows += cursor.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return updated_matches, updated_rows


def main() -> None:
    pending = targets()
    cache = load_cache()
    todo = [row for row in pending
            if not cache.get((row["tour"], row["source_match_id"]), {}).get("tournament_name")
            or not cache.get((row["tour"], row["source_match_id"]), {}).get("tournament_id")
            or not cache.get((row["tour"], row["source_match_id"]), {}).get("match_title_players_check")]
    print(f"{len(pending)} blank point-history references; {len(todo)} pages to fetch", flush=True)
    completed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_one, row): row for row in todo}
        for future in as_completed(futures):
            result = future.result()
            append_cache(result)
            cache[(result["tour"], result["source_match_id"])] = result
            completed += 1
            if completed % 50 == 0 or completed == len(todo):
                resolved = sum(bool(r.get("tournament_name") and r.get("tournament_id")) for r in cache.values())
                print(f"fetched {completed}/{len(todo)} new pages; {resolved} cached tournament references", flush=True)

    rows = [cache[(row["tour"], row["source_match_id"])] for row in pending
            if (row["tour"], row["source_match_id"]) in cache]
    write_csv(rows)
    updated_matches, updated_rows = apply_resolved(rows)
    resolved = sum(bool(r.get("tournament_name") and r.get("tournament_id")) for r in rows)
    print(f"Resolved {resolved}/{len(rows)} pages; updated {updated_matches} matches / {updated_rows} DB rows.", flush=True)
    print(f"Evidence: {CSV}", flush=True)


if __name__ == "__main__":
    main()
