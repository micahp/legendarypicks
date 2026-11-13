#!/usr/bin/env python3
"""Reconstruct *as-of depth and injury context*, not a falsely finalized roster.

nflverse 2025+ depth charts append dated records (dt). For each scheduled game,
select that team's last source snapshot before the requested pre-kickoff cutoff
and join known WEEKLY injury statuses from the recover_nfl_injury_weeks audit.
The published weekly roster is deliberately not used as proof of active status.

Official game-day inactive lists must be attached independently. Without them
the output is a depth/injury reconstruction, NOT a finalized 53/48-man roster.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import timedelta
import json
from pathlib import Path

from recover_nfl_injury_weeks import (
    SEASON, FIRST_WEEK, LAST_WEEK, file_sha256, get_schedule_csv,
    string_utc, utc_timestamp
)
from team_codes import normalize_optional

OUTPUT_FIELDS = [
    "game_id", "week", "team", "kickoff_utc", "cutoff_utc",
    "depth_snapshot_utc", "depth_source_sha256",
    "gsis_id", "player_name", "pos_grp", "pos_abb", "pos_rank",
    "injury_report_status", "injury_practice_status",
    "injury_evidence_class", "pregame_inactive",
    "inactive_evidence_class", "reconstruction_status",
]


def load_depth(path):
    import pyarrow.parquet as pq
    fields = ["dt", "team", "gsis_id", "player_name", "pos_grp", "pos_abb", "pos_rank"]
    have = set(pq.ParquetFile(path).schema.names)
    if not set(fields).issubset(have):
        raise RuntimeError("depth chart missing: " + ", ".join(sorted(set(fields) - have)))
    raw = pq.read_table(path, columns=fields).to_pylist()
    by_team_date = defaultdict(list)
    for item in raw:
        dt = utc_timestamp(item["dt"])
        if dt is None:
            raise RuntimeError("depth chart has unparseable/naive dt")
        if not item["team"] or not item["gsis_id"]:
            continue
        team = normalize_optional("nfl", str(item["team"]))
        by_team_date[(team, dt)].append(item)
    return by_team_date


def load_injury_audit(path):
    data = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            if int(row["season"]) != SEASON or not FIRST_WEEK <= int(row["week"]) <= LAST_WEEK:
                continue
            key = (int(row["week"]), row["team"], row["gsis_id"])
            if key in data:
                raise ValueError("duplicate GSIS injury report key: " + str(key))
            data[key] = row
    return data


def inactive_index(path):
    """Curated official source evidence, not inferred from game participation.

    Each entry requires game_id/team, unique GSIS IDs and official source URL.
    An after-kickoff source is useful *retrospectively* but is not a pregame lock.
    """
    if path is None:
        return {}
    entries = json.loads(path.read_text())
    if not isinstance(entries, list):
        raise ValueError("inactives index must contain an array")
    out = {}
    for r in entries:
        if not r.get("source_url") or not str(r["source_url"]).startswith("https://"):
            raise ValueError("official inactives source URL required")
        if not r.get("source_sha256") or len(r["source_sha256"]) != 64:
            raise ValueError("inactives source SHA-256 required")
        ids = r.get("gsis_ids")
        if not isinstance(ids, list) or len(ids) != len(set(ids)):
            raise ValueError("inactives require distinct GSIS identifiers")
        key = (r["game_id"], normalize_optional("nfl", r["team"]))
        if key in out:
            raise ValueError("duplicate inactives game/team " + str(key))
        out[key] = r
    return out


def build(schedule, depth, injury, depth_sha, cutoff_before_kickoff_minutes=30,
          inactive_sources=None):
    if cutoff_before_kickoff_minutes < 1:
        raise ValueError("must cut off before kickoff")
    inactive_sources = inactive_sources or {}
    games = {}
    for (week, team), info in schedule.items():
        if FIRST_WEEK <= week <= LAST_WEEK:
            game = games.setdefault(info["game_id"], {
                "week": week, "teams": set(), "kickoff": info["kickoff"]})
            if game["week"] != week or game["kickoff"] != info["kickoff"]:
                raise ValueError("inconsistent schedule " + info["game_id"])
            game["teams"].add(team)
    rows, coverage = [], Counter()
    for gid, game in sorted(games.items()):
        week = game["week"]
        kickoff = game["kickoff"]
        cutoff = kickoff - timedelta(minutes=cutoff_before_kickoff_minutes)
        for team in sorted(game["teams"]):
            times = [stamp for candidate_team, stamp in depth if candidate_team == team and stamp <= cutoff]
            if not times:
                coverage["missing_before_cutoff_depth_team_games"] += 1
                continue
            snapshot = max(times)
            depth_rows = depth[(team, snapshot)]
            if not depth_rows:
                raise ValueError("selected empty depth snapshot")
            inactive = inactive_sources.get((gid, team))
            inactive_ids = set(inactive["gsis_ids"]) if inactive else set()
            status_class = "depth_and_injury_only_not_finalized"
            inactive_class = "none"
            if inactive:
                source_time = utc_timestamp(inactive.get("source_last_updated_at_utc"))
                if source_time is None:
                    source_time = utc_timestamp(inactive.get("source_published_at_utc"))
                # Pages continually updated after kickoff are *retrospective*
                # even if their original publication time precedes kickoff.
                if source_time is not None and source_time <= cutoff:
                    status_class = "reconstructed_with_pregame_dated_inactives"
                    inactive_class = "dated_official_before_cutoff"
                else:
                    status_class = "reconstructed_with_retrospective_inactives"
                    inactive_class = "official_not_pregame_verified"
            coverage[status_class + "_team_games"] += 1
            coverage["depth_team_games"] += 1
            coverage["injury_week_rows_matched"] += sum(
                (week, team, r["gsis_id"]) in injury for r in depth_rows)
            seen = set()
            for d in depth_rows:
                role = (d["gsis_id"], d["pos_grp"], d["pos_abb"], d["pos_rank"])
                if role in seen:
                    raise ValueError("duplicated depth role " + str(role))
                seen.add(role)
                report = injury.get((week, team, d["gsis_id"]), {})
                rows.append({
                    "game_id": gid, "week": week, "team": team,
                    "kickoff_utc": string_utc(kickoff),
                    "cutoff_utc": string_utc(cutoff),
                    "depth_snapshot_utc": string_utc(snapshot),
                    "depth_source_sha256": depth_sha,
                    "gsis_id": d["gsis_id"], "player_name": d.get("player_name") or "",
                    "pos_grp": d.get("pos_grp") or "", "pos_abb": d.get("pos_abb") or "",
                    "pos_rank": d.get("pos_rank"),
                    "injury_report_status": report.get("report_status") or "",
                    "injury_practice_status": report.get("practice_status") or "",
                    "injury_evidence_class": report.get("evidence_class") or "none",
                    "pregame_inactive": (True if d["gsis_id"] in inactive_ids else
                                         False if inactive is not None else ""),
                    "inactive_evidence_class": inactive_class,
                    "reconstruction_status": status_class,
                })
            # An inactive may be missing from today's historical depth table:
            # never drop him silently or infer active from nonmembership.
            missing = inactive_ids - {x["gsis_id"] for x in depth_rows}
            coverage["official_inactives_not_in_depth_chart"] += len(missing)
    coverage["game_count"] = len(games)
    coverage["depth_player_role_rows"] = len(rows)
    coverage["expected_team_games"] = sum(len(x["teams"]) for x in games.values())
    coverage["official_inactive_sources"] = len(inactive_sources)
    return rows, dict(coverage)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--depth-parquet", type=Path, required=True)
    ap.add_argument("--schedule-csv", type=Path, required=True)
    ap.add_argument("--injury-csv", type=Path, required=True)
    ap.add_argument("--inactives-index", type=Path, default=None)
    ap.add_argument("--cutoff-minutes", type=int, default=30)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    sha = file_sha256(args.depth_parquet)
    records, counts = build(
        get_schedule_csv(args.schedule_csv), load_depth(args.depth_parquet),
        load_injury_audit(args.injury_csv), sha,
        cutoff_before_kickoff_minutes=args.cutoff_minutes,
        inactive_sources=inactive_index(args.inactives_index))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "asof-depth-injury-rosters.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(records)
    info = {
        "season": SEASON, "weeks": [FIRST_WEEK, LAST_WEEK],
        "depth_sha256": sha, "injury_csv_sha256": file_sha256(args.injury_csv),
        "schedule_csv_sha256": file_sha256(args.schedule_csv),
        "cutoff_before_kickoff_minutes": args.cutoff_minutes,
        "finalized_roster_claim": False if not args.inactives_index else
            "only games with individually sourced game-day inactives",
        "warning": "Depth is not official game-day active roster; injury date_modified missing for most 2026 reports. Weekly roster generated after games is not pregame proof.",
        "coverage": counts,
        "output": "asof-depth-injury-rosters.csv",
    }
    (args.out_dir / "asof-depth-injury-coverage.json").write_text(
        json.dumps(info, indent=2, sort_keys=True) + "\n")
    print(json.dumps(info, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
