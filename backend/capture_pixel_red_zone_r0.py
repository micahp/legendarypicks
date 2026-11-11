#!/usr/bin/env python3
"""Capture a bounded live ESPN NFL slate sample for the Pixel Red Zone R0 audit.

The job calls the existing ESPN client directly, polls no faster than once a
minute, and writes append-only research observations. It does not run in a
request handler or update application databases.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import pathlib
import time
import uuid

import espn_client as espn


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs/research/fixtures/pixel-red-zone-live-2026-11-01"
MIN_INTERVAL_SECONDS = 60
MAX_DURATION_MINUTES = 360


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(value: dt.datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed.astimezone(dt.timezone.utc)


def plays_from_summary(summary: dict) -> list[dict]:
    """Flatten ESPN's published play arrays without changing their records."""
    flat = summary.get("plays")
    if isinstance(flat, list):
        return [play for play in flat if isinstance(play, dict)]

    result = []
    drives = summary.get("drives") or {}
    if not isinstance(drives, dict):
        return result
    for key in ("previous", "current"):
        drives_for_key = drives.get(key)
        if isinstance(drives_for_key, dict):
            drives_for_key = [drives_for_key]
        if not isinstance(drives_for_key, list):
            continue
        for drive in drives_for_key:
            if not isinstance(drive, dict):
                continue
            drive_plays = drive.get("plays") or []
            if isinstance(drive_plays, list):
                result.extend(play for play in drive_plays if isinstance(play, dict))
    return result


def canonical_hash(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _append_jsonl(path: pathlib.Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) + "\n")
        output.flush()


def _read_existing_versions(events_path: pathlib.Path) -> dict[str, set[str]]:
    versions: dict[str, set[str]] = collections.defaultdict(set)
    if not events_path.exists():
        return versions
    with events_path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                record = json.loads(line)
                versions[str(record["event_id"])].add(str(record["revision_hash"]))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(f"invalid existing event log line {line_number}: {exc}") from exc
    return versions


def _scoreboard_events(payload: dict) -> list[dict]:
    result = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        competition = (event.get("competitions") or [{}])[0]
        if not isinstance(competition, dict):
            competition = {}
        status_type = ((competition.get("status") or {}).get("type") or {})
        sides = {row.get("homeAway"): row for row in competition.get("competitors") or []
                 if isinstance(row, dict)}
        scores = {
            side: (sides.get(side) or {}).get("score")
            for side in ("home", "away")
        }
        result.append({
            "event_id": str(event.get("id") or ""),
            "date": event.get("date"),
            "state": status_type.get("state"),
            "period": (competition.get("status") or {}).get("period"),
            "clock": (competition.get("status") or {}).get("displayClock"),
            "scores": scores,
            "situation": competition.get("situation"),
        })
    return result


def _capture_play_versions(event_id: str, plays: list[dict], observed_at: str,
                           versions: dict[str, set[str]], events_path: pathlib.Path) -> dict:
    play_ids = [str(play["id"]) for play in plays if play.get("id") not in (None, "")]
    id_counts = collections.Counter(play_ids)
    missing_ids = sum(play.get("id") in (None, "") for play in plays)
    duplicate_ids = sum(count - 1 for count in id_counts.values() if count > 1)
    added = revisions = 0

    for play in plays:
        raw_id = play.get("id")
        if raw_id in (None, ""):
            continue
        play_id = str(raw_id)
        event_key = f"{event_id}:ESPN:{play_id}"
        digest = canonical_hash(play)
        known = versions[event_key]
        if digest in known:
            continue
        record = {
            "event_id": event_key,
            "game_id": event_id,
            "publisher": "ESPN",
            "play_id": play_id,
            "revision_hash": digest,
            "revision_basis": "canonical_raw_play_sha256",
            "observed_at_utc": observed_at,
            "occurred_at_utc": play.get("wallclock"),
            "source_modified_at": play.get("modified"),
            "sequence_number": play.get("sequenceNumber"),
            "period": (play.get("period") or {}).get("number"),
            "clock": (play.get("clock") or {}).get("displayValue"),
            "raw_play": play,
        }
        _append_jsonl(events_path, record)
        revisions += bool(known)
        added += not known
        known.add(digest)

    return {
        "play_count": len(plays),
        "unique_play_ids": len(id_counts),
        "missing_play_ids": missing_ids,
        "duplicate_ids_in_snapshot": duplicate_ids,
        "new_play_versions": added,
        "changed_play_versions": revisions,
    }


def _write_manifest(path: pathlib.Path, manifest: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def capture_live_slate(*, game_date: str, output_dir: pathlib.Path,
                       duration_minutes: int, interval_seconds: int,
                       start_at: dt.datetime | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "play_versions.jsonl"
    scoreboard_path = output_dir / "scoreboard_observations.jsonl"
    summaries_path = output_dir / "summary_observations.jsonl"
    errors_path = output_dir / "capture_errors.jsonl"
    manifest_path = output_dir / "capture_manifest.json"

    versions = _read_existing_versions(events_path)
    run_id = str(uuid.uuid4())
    requested_start = start_at or utc_now()
    deadline = requested_start + dt.timedelta(minutes=duration_minutes)
    counters = collections.Counter()
    by_game: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

    while utc_now() < requested_start:
        time.sleep(min(30.0, max(0.1, (requested_start - utc_now()).total_seconds())))

    actual_start = utc_now()
    print(f"[pixel-red-zone-r0] start={iso_utc(actual_start)} date={game_date} "
          f"duration_min={duration_minutes} interval_s={interval_seconds} output={output_dir}",
          flush=True)

    situation_games = set()
    pbp_games = set()
    while utc_now() < deadline:
        cycle_started = time.monotonic()
        observed_at = iso_utc()
        cycle = {"run_id": run_id, "cycle_started_at_utc": observed_at,
                 "pre": 0, "in": 0, "post": 0, "unknown": 0,
                 "summaries_attempted": 0,
                 "summaries_succeeded": 0, "new_play_versions": 0,
                 "changed_play_versions": 0}
        games = []
        try:
            with espn.batch_pacing(min_interval=1.5):
                # Retry refusals on the next scheduled cycle, not in a blocking
                # 5/20/60-second ladder inside this bounded observation window.
                espn.set_retry_waits(())
                board = espn.scoreboard_raw("nfl", game_date)
                board_captured_at = iso_utc()
                games = _scoreboard_events(board)
                for game in games:
                    state = game.get("state")
                    cycle[state if state in ("pre", "in", "post") else "unknown"] = (
                        cycle.get(state if state in ("pre", "in", "post") else "unknown", 0) + 1
                    )
                    _append_jsonl(scoreboard_path, {
                        "run_id": run_id,
                        "observed_at_utc": board_captured_at,
                        **game,
                    })
                live_games = [game for game in games
                              if game.get("state") == "in" and game.get("event_id")]
                for game in live_games:
                    event_id = game["event_id"]
                    cycle["summaries_attempted"] += 1
                    counters["summaries_attempted"] += 1
                    try:
                        summary = espn.summary("nfl", event_id)
                        summary_observed_at = iso_utc()
                        plays = plays_from_summary(summary)
                        counts = _capture_play_versions(
                            event_id, plays, summary_observed_at, versions, events_path)
                        meta = summary.get("meta") or {}
                        header_id = (summary.get("header") or {}).get("id")
                        response = {
                            "run_id": run_id,
                            "observed_at_utc": summary_observed_at,
                            "requested_event_id": event_id,
                            "publisher_event_id": str(header_id) if header_id is not None else None,
                            "available": bool(plays),
                            "publisher_updated_at": meta.get("lastUpdatedAt"),
                            "first_play_wallclock": meta.get("firstPlayWallClock"),
                            "last_play_wallclock": meta.get("lastPlayWallClock"),
                            "game_state": meta.get("gameState"),
                            "scoreboard_state": game.get("state"),
                            "scoreboard_scores": game.get("scores"),
                            **counts,
                        }
                        _append_jsonl(summaries_path, response)
                        cycle["summaries_succeeded"] += 1
                        cycle["new_play_versions"] += counts["new_play_versions"]
                        cycle["changed_play_versions"] += counts["changed_play_versions"]
                        counters["summaries_succeeded"] += 1
                        by_game[event_id]["summary_responses"] += 1
                        by_game[event_id]["available_pbp_responses"] += bool(plays)
                        if plays:
                            pbp_games.add(event_id)
                        for key, value in counts.items():
                            by_game[event_id][key] += value
                        counters["new_play_versions"] += counts["new_play_versions"]
                        counters["changed_play_versions"] += counts["changed_play_versions"]
                        counters["missing_play_ids"] += counts["missing_play_ids"]
                        counters["duplicate_ids_in_snapshot"] += counts["duplicate_ids_in_snapshot"]
                    except Exception as exc:
                        error = {"run_id": run_id, "observed_at_utc": iso_utc(),
                                 "event_id": event_id, "stage": "summary",
                                 "error_type": type(exc).__name__, "error": str(exc)[:300]}
                        _append_jsonl(errors_path, error)
                        counters["summary_errors"] += 1
        except Exception as exc:
            error = {"run_id": run_id, "observed_at_utc": iso_utc(),
                     "event_id": None, "stage": "scoreboard",
                     "error_type": type(exc).__name__, "error": str(exc)[:300]}
            _append_jsonl(errors_path, error)
            counters["scoreboard_errors"] += 1

        counters["cycles"] += 1
        counters["scoreboard_games_observed"] += sum(
            cycle.get(state, 0) for state in ("pre", "in", "post", "unknown")
        )
        counters["live_game_observations"] += cycle.get("in", 0)
        counters["scoreboard_observations_with_situation"] += sum(
            bool(row.get("situation")) for row in games
        )
        situation_games.update(row["event_id"] for row in games
                               if row.get("situation") and row.get("event_id"))
        _write_manifest(manifest_path, {
            "run_id": run_id,
            "source": "existing espn_client; ESPN NFL scoreboard and summary endpoints",
            "game_date": game_date,
            "requested_start_at_utc": iso_utc(requested_start),
            "actual_start_at_utc": iso_utc(actual_start),
            "duration_minutes": duration_minutes,
            "interval_seconds": interval_seconds,
            "last_cycle_at_utc": iso_utc(),
            "totals": dict(counters),
            "games_with_situation": len(situation_games),
            "games_with_pbp": len(pbp_games),
            "games": {game_id: dict(stats) for game_id, stats in sorted(by_game.items())},
            "artifacts": {
                "play_versions": events_path.name,
                "scoreboard_observations": scoreboard_path.name,
                "summary_observations": summaries_path.name,
                "capture_errors": errors_path.name,
            },
            "limitations": [
                "wallclock is recorded as source event time, not publisher-reported delivery time",
                "source_modified_at is retained verbatim; its revision semantics are not assumed",
                "identical payloads are deduplicated by canonical raw-play SHA-256; changed hashes are retained",
            ],
        })
        print(json.dumps({"run_id": run_id, **cycle}, separators=(",", ":")), flush=True)

        remaining = interval_seconds - (time.monotonic() - cycle_started)
        if remaining > 0 and utc_now() < deadline:
            time.sleep(remaining)

    return {"run_id": run_id, "totals": dict(counters),
            "games": {game_id: dict(stats) for game_id, stats in sorted(by_game.items())}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", required=True, help="ESPN NFL scoreboard date YYYY-MM-DD")
    parser.add_argument("--output-dir", type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--duration-minutes", type=int, default=20)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--start-at-utc", help="optional ISO-8601 UTC start time")
    args = parser.parse_args(argv)
    try:
        dt.date.fromisoformat(args.date)
        if not 1 <= args.duration_minutes <= MAX_DURATION_MINUTES:
            raise ValueError(f"duration must be 1..{MAX_DURATION_MINUTES} minutes")
        if args.interval_seconds < MIN_INTERVAL_SECONDS:
            raise ValueError(f"interval must be at least {MIN_INTERVAL_SECONDS} seconds")
        start_at = parse_utc(args.start_at_utc) if args.start_at_utc else None
        capture_live_slate(game_date=args.date, output_dir=args.output_dir,
                           duration_minutes=args.duration_minutes,
                           interval_seconds=args.interval_seconds, start_at=start_at)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
