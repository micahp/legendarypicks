"""Offline, source-pinned cfbfastR game-coverage manifest for the NCAAF FBS model.

Reads the pinned archival cfbfastR play-by-play files and the schedule files the forecaster
loads, and writes one row per schedule game with a three-valued coverage status. A JSON manifest
pins every source file by SHA-256 and carries the CSV's own hash. Production loads the CSV and
verifies that hash before use. Play-by-play rows are not exported: only the per-game coverage
fact and its identity checks leave this script.

Statuses (per schedule game, per season)
  has_plays                     completed, plays present, date and both team names match the schedule
  no_plays_in_complete_snapshot scheduled result, no play rows, in a complete source file set
  unknown_source_or_identity    play rows present but identity fails, or a play-by-play game ID
                                is absent from the schedule, or no play has a team; halts certification
  not_completed                 no source rows and no scheduled result; outside eligibility by definition

A missing season file is not a status at all: the generator raises, writes nothing, and production
then halts. A missing row is never read as zero coverage.

usage:
  python fbs_cfbfastr_coverage.py --pbp-dir ARCHIVE/research/fbs/parquet \
      --schedule-dir DATA_DIR --seasons 2022,2023,2024,2025,2026 --out-dir backend/fbs_coverage
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

import pandas as pd
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fbs_game_winner_baseline import season_schedule_path  # noqa: E402  (same path rule as the forecaster)

GENERATOR_VERSION = 1
PBP_SUBDIR = "cfbfastR_cfb_pbp"
CSV_NAME = "cfbfastr_pbp_coverage.csv"
MANIFEST_NAME = "cfbfastr_pbp_coverage.manifest.json"
STATUSES = ("has_plays", "no_plays_in_complete_snapshot", "unknown_source_or_identity", "not_completed")
COLUMNS = ["season", "game_id", "home_team", "away_team", "start_date_utc", "schedule_completed",
           "coverage_status", "play_count", "identity_check", "source_season_sha256"]


class CoverageError(RuntimeError):
    pass


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def normalise_name(value) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", str(value).lower())
    return " ".join(text.split())


def read_schedule(path: str, season: int) -> pd.DataFrame:
    frame = pq.read_table(path, columns=["game_id", "start_date", "home_team", "away_team", "completed"]).to_pandas()
    frame["game_id"] = frame["game_id"].astype(str)
    if frame["game_id"].duplicated().any():
        raise CoverageError("duplicate game_id in schedule %s" % path)
    frame["start_date_utc"] = pd.to_datetime(frame["start_date"], utc=True)
    frame["completed"] = frame["completed"].astype(bool)
    return frame


def read_pbp(path: str) -> pd.DataFrame:
    frame = pq.read_table(path, columns=["game_id", "start_date", "pos_team", "home_team", "away_team"]).to_pandas()
    frame["game_id"] = frame["game_id"].astype(str)
    frame["start_date_utc"] = pd.to_datetime(frame["start_date"], utc=True)
    return frame


def identity_check(rec, grp: pd.DataFrame) -> str:
    """Verify that the source rows belong to this scheduled game.

    The team check is an exact match of the normalised play-by-play team set with the two scheduled
    names, the same basis the research join uses. The date check compares the schedule's UTC date
    with the source dates. Source dates can be null for whole games; then the date cannot be
    cross-checked, and the row says so rather than passing silently.
    """
    teams = {normalise_name(x) for x in grp["pos_team"].dropna().unique()}
    if teams != {normalise_name(rec.home_team), normalise_name(rec.away_team)}:
        return "failed_teams"
    source_dates = set(grp["start_date_utc"].dropna().dt.date)
    if not source_dates:
        return "teams_only_source_date_missing"
    return "teams_and_date" if rec.start_date_utc.date() in source_dates else "failed_date"


def coverage_rows(season: int, schedule: pd.DataFrame, pbp: pd.DataFrame, source_sha: str) -> list[dict]:
    """Pure function: one coverage row per schedule game, plus one per orphan play-by-play game."""
    rows = []
    grouped = {gid: grp for gid, grp in pbp.groupby("game_id", sort=False)}
    scheduled = set(schedule["game_id"])
    for rec in schedule.itertuples(index=False):
        base = dict(season=season, game_id=rec.game_id, home_team=rec.home_team, away_team=rec.away_team,
                    start_date_utc=rec.start_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    schedule_completed=bool(rec.completed), source_season_sha256=source_sha)
        grp = grouped.get(rec.game_id)
        if grp is None:
            # No source rows. Only a scheduled result makes this a claim about the archive: an
            # upcoming game has no plays yet and is outside eligibility by definition.
            if rec.completed:
                rows.append(dict(base, coverage_status="no_plays_in_complete_snapshot", play_count=0,
                                 identity_check="no_source_rows"))
            else:
                rows.append(dict(base, coverage_status="not_completed", play_count=0, identity_check=""))
            continue
        # Source rows are the evidence. The schedule snapshot's completed flag can predate results
        # that the archive already contains (the 2026 snapshot is dated 2026-10-17), so it is recorded
        # but does not override rows that exist.
        plays = int(grp["pos_team"].notna().sum())
        identity = identity_check(rec, grp)
        if plays > 0 and identity in ("teams_and_date", "teams_only_source_date_missing"):
            status = "has_plays"
        else:
            status = "unknown_source_or_identity"
        rows.append(dict(base, coverage_status=status, play_count=plays, identity_check=identity))
    for gid, grp in grouped.items():
        if gid not in scheduled:
            rows.append(dict(season=season, game_id=gid, home_team=str(grp["home_team"].iloc[0]),
                             away_team=str(grp["away_team"].iloc[0]),
                             start_date_utc=str(grp["start_date_utc"].min()), schedule_completed=False,
                             coverage_status="unknown_source_or_identity",
                             play_count=int(grp["pos_team"].notna().sum()),
                             identity_check="orphan_play_by_play_id",
                             source_season_sha256=source_sha))
    return rows


def build(pbp_dir: str, schedule_dir: str, seasons: list[int], out_dir: str) -> dict:
    sources = []
    all_rows = []
    counts: dict[str, dict[str, int]] = {}
    orphans: dict[str, int] = {}
    for season in seasons:
        pbp_path = os.path.join(pbp_dir, PBP_SUBDIR, "play_by_play_%d.parquet" % season)
        sched_path = season_schedule_path(schedule_dir, season)
        for path in (pbp_path, sched_path):
            if not os.path.exists(path):
                raise CoverageError("required source missing for %d: %s (nothing written)" % (season, path))
        pbp_sha, sched_sha = sha256_file(pbp_path), sha256_file(sched_path)
        schedule = read_schedule(sched_path, season)
        pbp = read_pbp(pbp_path)
        rows = coverage_rows(season, schedule, pbp, pbp_sha)
        all_rows.extend(rows)
        counts[str(season)] = {s: sum(1 for r in rows if r["coverage_status"] == s) for s in STATUSES}
        orphans[str(season)] = sum(1 for r in rows if r["coverage_status"] == "unknown_source_or_identity"
                                   and not r["schedule_completed"] and r["play_count"] > 0)
        sources.append({"role": "pbp", "season": season, "file": os.path.relpath(pbp_path, pbp_dir),
                        "sha256": pbp_sha, "bytes": os.path.getsize(pbp_path), "rows": int(len(pbp))})
        sources.append({"role": "schedule", "season": season, "file": os.path.basename(sched_path),
                        "sha256": sched_sha, "bytes": os.path.getsize(sched_path), "rows": int(len(schedule))})
    table = pd.DataFrame(all_rows, columns=COLUMNS).sort_values(["season", "game_id"]).reset_index(drop=True)
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, CSV_NAME)
    table.to_csv(csv_path, index=False, lineterminator="\n")
    snapshot_src = "".join(s["sha256"] for s in sources)
    manifest = {
        "manifest_version": GENERATOR_VERSION,
        "source_dataset": PBP_SUBDIR,
        "snapshot_id": "cfbfastR-" + hashlib.sha256(snapshot_src.encode()).hexdigest()[:12],
        "seasons": seasons,
        "csv": CSV_NAME,
        "csv_sha256": sha256_file(csv_path),
        "csv_rows": int(len(table)),
        "sources": sources,
        "counts_by_season": counts,
        "orphan_play_by_play_games_by_season": orphans,
        "generator": "backend/fbs_cfbfastr_coverage.py",
        "generator_sha256": sha256_file(os.path.abspath(__file__)),
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "definitions": {
            "play_count": "rows whose pos_team is not null, for the game",
            "has_plays": "play_count > 0 and identity_check is teams_and_date, or teams_only_source_date_missing",
            "identity_check": "teams: exact match of the normalised play-by-play team set with the two scheduled names; "
                              "date: schedule UTC date must equal a source date when the source has one, "
                              "otherwise the row records teams_only_source_date_missing",
            "no_plays_in_complete_snapshot": "scheduled result, no play rows, season source set present and hashed",
            "unknown_source_or_identity": "source rows exist and the identity check fails (failed_teams or failed_date), "
                                          "or a play-by-play game ID is absent from the schedule",
            "not_completed": "no source rows and no scheduled result; excluded from historical eligibility by definition",
        },
    }
    with open(os.path.join(out_dir, MANIFEST_NAME), "w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pbp-dir", required=True)
    parser.add_argument("--schedule-dir", required=True)
    parser.add_argument("--seasons", default="2022,2023,2024,2025,2026")
    parser.add_argument("--out-dir", default=os.path.join(HERE, "fbs_coverage"))
    args = parser.parse_args(argv)
    seasons = [int(s) for s in args.seasons.split(",")]
    manifest = build(args.pbp_dir, args.schedule_dir, seasons, args.out_dir)
    print(json.dumps({"snapshot_id": manifest["snapshot_id"], "csv_rows": manifest["csv_rows"],
                      "counts_by_season": manifest["counts_by_season"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
