#!/usr/bin/env python3
"""Recover 2026 NFL Weeks 2-9 injury reports without inventing as-of dates.

Produces a row-level audit of the existing nflverse cumulative injury artifact,
optionally supplemented by *timestamped, independently archived* earlier copies.
A final weekly report from today's cumulative parquet is NOT a pregame capture.

Usage:
  python backend/recover_nfl_injury_weeks.py \
    --artifact /path/to/injuries_2026.parquet \
    --db /path/to/picks.dev.db \
    --out-dir /tmp/nfl-injury-history

Optional: --capture-index /path/to/captures.json supplies historically observed
copies, each {"path": "/archive/injuries_2026.parquet",
"observed_at_utc": "2026-09-18T15:30:00Z", "sha256": "<full hash>"}.
Do not provide an assumed observed_at or reuse filesystem mtime: it must come
from an independently recorded capture log, frozen snapshot or fetch manifest.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from ingest_nfl_injuries import read_artifact
from team_codes import normalize_optional

SEASON = 2026
FIRST_WEEK = 2
LAST_WEEK = 9
UTC = timezone.utc
ET = ZoneInfo("America/New_York")
FIELDS = [
    "season", "week", "game_id", "team", "gsis_id", "full_name",
    "position", "report_status", "practice_status", "primary_injury",
    "source_modified_at_utc", "kickoff_utc", "evidence_class",
    "earliest_captured_at_utc", "capture_sha256", "capture_path",
    "source_artifact_sha256", "official_weekly_reference"
]


def file_sha256(path: Path) -> str:
    h = sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def utc_timestamp(value):
    if not value:
        return None
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    # A timezone-less nflverse date_modified must not be assumed to be UTC.
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(UTC)


def string_utc(value):
    return value.isoformat().replace("+00:00", "Z") if value else ""


def get_schedule(db_path: Path):
    """One scheduled kickoff for each season/week/team; read-only DB."""
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    out = {}
    with sqlite3.connect("file:" + str(db_path.resolve()) + "?mode=ro", uri=True) as con:
        rows = con.execute("""
            SELECT game_id,week,gameday,gametime,away_team,home_team
            FROM nfl_schedule
            WHERE season=? AND game_type='REG' AND week BETWEEN ? AND ?
        """, (SEASON, FIRST_WEEK, LAST_WEEK))
        for gid, week, day, clock, away, home in rows:
            if not day or not clock:
                continue
            try:
                start = datetime.strptime(
                    str(day) + " " + str(clock), "%Y-%m-%d %H:%M"
                ).replace(tzinfo=ET).astimezone(UTC)
            except ValueError:
                continue
            for team in (away, home):
                key = (int(week), normalize_optional("nfl", str(team)))
                if key in out:
                    raise ValueError("duplicate team/week scheduled games: " + str(key))
                out[key] = {"game_id": gid, "kickoff": start}
    return out


def captures_from_index(path: Path | None):
    """Only accept separately documented observations with verified file hashes."""
    if path is None:
        return []
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError("capture index must be a list")
    captures = []
    for record in payload:
        stamp = utc_timestamp(record.get("observed_at_utc"))
        if not stamp:
            raise ValueError("capture index requires timezone-aware observed_at_utc")
        location = Path(record["path"])
        if not location.is_absolute():
            location = path.parent / location
        actual = file_sha256(location)
        if actual != record.get("sha256"):
            raise ValueError("archived injury capture SHA256 mismatch: " + str(location))
        captures.append({"path": str(location.resolve()), "sha256": actual,
                         "observed": stamp})
    return captures


def recover(current_rows, current_sha, games, archived_captures=()):
    """Return (rows, coverage) with strict cutoff-safe capture classification.

    Source data date_modified can prove row text was changed AFTER kickoff,
    but only an earlier *captured file* proves we possessed that exact row
    before kickoff. Undated rows remain available for retrospective study.
    """
    keyed = {}
    for r in current_rows:
        week = int(r["week"])
        if not FIRST_WEEK <= week <= LAST_WEEK:
            continue
        team = normalize_optional("nfl", str(r["team"]))
        key = (week, team, str(r["gsis_id"]))
        if key in keyed:
            raise ValueError("duplicate current publisher injury key: " + str(key))
        keyed[key] = r
    archives = defaultdict(list)
    for cap in archived_captures:
        for row in cap["rows"]:
            week = int(row["week"])
            if FIRST_WEEK <= week <= LAST_WEEK:
                key = (week, normalize_optional("nfl", str(row["team"])), str(row["gsis_id"]))
                archives[key].append((cap, row))
    out = []
    summary = Counter()
    for (week, team, gsis), row in sorted(keyed.items()):
        sched = games.get((week, team))
        kickoff = sched["kickoff"] if sched else None
        published = utc_timestamp(row.get("date_modified"))
        observed = None
        chosen_cap = None
        if kickoff is not None:
            for cap, archived_row in archives.get((week, team, gsis), []):
                # Pre-kickoff capture proves the historical status only when
                # the relevant report content is the same (not merely player ID).
                if cap["observed"] >= kickoff:
                    continue
                status_matches = all(
                    archived_row.get(k) == row.get(k)
                    for k in ("report_status", "practice_status",
                              "report_primary_injury"))
                if status_matches and (observed is None or cap["observed"] < observed):
                    observed, chosen_cap = cap["observed"], cap
        if kickoff is None:
            classification = "missing_schedule_kickoff"
        elif observed is not None:
            classification = "pre_kickoff_archived_capture"
        elif published is not None and published >= kickoff:
            classification = "source_modified_after_kickoff"
        elif published is not None:
            classification = "source_modified_before_kickoff_not_observed"
        else:
            classification = "historical_weekly_report_undated"
        summary[classification] += 1
        summary["week_" + str(week)] += 1
        out.append({
            "season": SEASON, "week": week, "game_id": sched["game_id"] if sched else "",
            "team": team, "gsis_id": gsis, "full_name": str(row.get("full_name") or ""),
            "position": str(row.get("position") or ""),
            "report_status": row.get("report_status") or "",
            "practice_status": row.get("practice_status") or "",
            "primary_injury": row.get("report_primary_injury") or "",
            "source_modified_at_utc": string_utc(published),
            "kickoff_utc": string_utc(kickoff),
            "evidence_class": classification,
            "earliest_captured_at_utc": string_utc(observed),
            "capture_sha256": chosen_cap["sha256"] if chosen_cap else "",
            "capture_path": chosen_cap["path"] if chosen_cap else "",
            "source_artifact_sha256": current_sha,
            "official_weekly_reference":
                f"https://www.nfl.com/injuries/league/{SEASON}/reg{week}",
        })
    summary["unique_weeks"] = len({r["week"] for r in out})
    summary["unique_teams"] = len({r["team"] for r in out})
    summary["source_artifact_rows"] = len(current_rows)
    summary["selected_weekly_rows"] = len(out)
    summary["missing_schedule_keys"] = len({
        (r["week"], r["team"]) for r in out if not r["kickoff_utc"]
    })
    return out, dict(summary)


def write_report(directory: Path, rows, summary, current_path, sha, captures):
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / "nfl-injury-weeks-2-9.csv"
    with csv_path.open("w", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "season": SEASON, "weeks": [FIRST_WEEK, LAST_WEEK],
        "historical_claim": "candidate rows only unless pre_kickoff_archived_capture",
        "current_artifact": str(current_path.resolve()),
        "current_artifact_sha256": sha,
        "original_report_modified_time": "nullable source date_modified, never set to ingest time",
        "archive_inputs": [
            {"path": c["path"], "sha256": c["sha256"],
             "observed_at_utc": string_utc(c["observed"])} for c in captures
        ],
        "summary": summary,
        "output": csv_path.name,
    }
    (directory / "nfl-injury-week-coverage.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    md = [
        "# 2026 NFL injury-report recovery, Weeks 2–9", "",
        f"Candidate historical injury rows: **{len(rows)}**.",
        "Only a separately captured, hash-verified file observed before kickoff",
        "can establish that a specific report was known at the time.",
        "The latest nflverse season file contains historic weekly rows, but",
        "its current modification time cannot backdate earlier snapshots.",
        "Missing `date_modified` stays missing; no fake timestamp is generated.",
        "", "## Evidence classes", "",
        "| Class | Report rows |", "|---|---:|"
    ]
    for name in ("pre_kickoff_archived_capture",
                 "source_modified_before_kickoff_not_observed",
                 "historical_weekly_report_undated",
                 "source_modified_after_kickoff",
                 "missing_schedule_kickoff"):
        md.append(f"| {name} | {summary.get(name, 0)} |")
    md.extend(["", "## Next evidence to recover", "",
               "Inspect pre-kickoff cached `injuries_2026.parquet` files,",
               "pinned SLC snapshots, prior ingest job artifacts, or original",
               "download manifests. Add only real observed timestamps and",
               "SHA-256 hashes to `--capture-index`; rerun this audit.",
               "Use the official weekly injury reports linked in the CSV for",
               "fact-checking, but a page viewed today is not itself",
               "proof of what the site showed before a historic kickoff.", ""])
    (directory / "README.md").write_text("\n".join(md))
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", type=Path, required=True,
                    help="The available cumulative nflverse 2026 injuries parquet")
    ap.add_argument("--db", type=Path, required=True,
                    help="SQLite schedule DB, opened read-only")
    ap.add_argument("--capture-index", type=Path,
                    help="JSON listing independently timestamped archived parquet files")
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    current_sha = file_sha256(args.artifact)
    current_rows = read_artifact(str(args.artifact), SEASON)
    captures = captures_from_index(args.capture_index)
    archives = [
        {**cap, "rows": read_artifact(cap["path"], SEASON)} for cap in captures
    ]
    rows, summary = recover(current_rows, current_sha, get_schedule(args.db), archives)
    if not rows:
        raise RuntimeError("2026 injury file has no 2026 Weeks 2-9 reports")
    manifest = write_report(args.out_dir, rows, summary, args.artifact,
                            current_sha, captures)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
