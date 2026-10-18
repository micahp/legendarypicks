#!/usr/bin/env python3
"""audit_fbs_archive.py -- turn the download manifest into the coverage matrix.

Reads research/fbs/parquet/MANIFEST.jsonl (one row per downloaded file) and each Parquet file's
metadata (row count and schema only; no column data is read), then writes:

  research/fbs/archive-releases.csv   one row per release: category, kind, seasons, files,
                                      bytes, rows, columns, first/last season, floor note
  research/fbs/archive-coverage.csv   one row per release x season: files, bytes, rows, columns

Categories are the six in the execution brief. A release that is not mapped is reported as
`unmapped`, never silently dropped.

Usage:
  /root/legendarypicks/backend/venv/bin/python backend/audit_fbs_archive.py [--dir research/fbs/parquet]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict

import pyarrow.parquet as pq

CATEGORY = {}
for tag in ("cfb_crosswalk", "cfb_groups", "cfb_team_info", "cfb_team_portal", "espn_cfb_teams",
            "ncaa_mfb_teams"):
    CATEGORY[tag] = "1 identity/reference"
for tag in ("cfb_schedules", "espn_cfb_schedules", "ncaa_mfb_schedule", "espn_cfb_betting",
            "cfb_matchup_line", "espn_cfb_linescores", "ncaa_mfb_linescore"):
    CATEGORY[tag] = "2 games/markets"
for tag in ("cfb_team_opponent_splits", "espn_cfb_team_box", "espn_cfb_team_summaries",
            "cfb_team_summaries_weekly", "espn_cfb_adv_team", "espn_cfb_adv_team_gamelog",
            "espn_cfb_adv_defensive", "espn_cfb_adv_situational", "espn_cfb_adv_turnover",
            "espn_cfb_adv_team_usage", "ncaa_mfb_team_stats", "cfb_league_averages",
            "cfb_defense_vs_position", "espn_cfb_adv_position_group_tackles",
            "espn_cfb_adv_position_group_usage", "espn_cfb_usage_teams",
            "espn_cfb_usage_position_groups", "espn_cfb_usage_position_group_tackles",
            "espn_cfb_usage_st_team", "espn_cfb_usage_st_blocks", "espn_cfb_usage_st_kickers",
            "espn_cfb_usage_st_punters", "espn_cfb_usage_st_returners", "espn_cfb_usage_tackles",
            "espn_cfb_usage_drive_scripting", "espn_cfb_qa", "ncaa_mfb_qa", "espn_cfb_percentiles",
            "cfb_matchup_features"):
    CATEGORY[tag] = "3 team performance"
for tag in ("cfbfastR_cfb_pbp", "espn_cfb_pbp", "ncaa_mfb_pbp", "ncaa_mfb_pbp_cfbfastr",
            "espn_cfb_drives", "espn_cfb_adv_drives", "espn_cfb_play_participants",
            "espn_cfb_model_pbp", "ncaa_mfb_drives"):
    CATEGORY[tag] = "4 event level"
for tag in ("espn_cfb_player_box", "espn_cfb_game_rosters", "espn_cfb_rosters", "ncaa_mfb_rosters",
            "ncaa_mfb_player_stats", "cfb_recruits", "cfb_recruiting_proj", "cfb_team_talent",
            "cfb_returning_production", "cfb_rolling_windows", "cfb_metric_curves",
            "espn_cfb_usage_players", "espn_cfb_adv_player_usage", "espn_cfb_adv_passing",
            "espn_cfb_adv_rushing", "espn_cfb_adv_receiving", "espn_cfb_adv_specialists",
            "espn_cfb_adv_tackles", "espn_cfb_adv_defensive_players", "espn_cfb_adv_st_blocks",
            "espn_cfb_adv_st_kickers", "espn_cfb_adv_st_punters", "espn_cfb_adv_st_returners",
            "espn_cfb_passing", "espn_cfb_rushing", "espn_cfb_receiving", "espn_cfb_injuries"):
    CATEGORY[tag] = "5 player/roster"
for tag in ("espn_cfb_coach_careers", "espn_cfb_coach_tendencies", "cfb_poll_analytics",
            "cfb_poll_week_summary", "cfb_ratings", "cfb_ratings_weekly", "cfb_fpi_weekly",
            "espn_cfb_power_index", "cfb_paper_index_games", "ncaa_mfb_officials"):
    CATEGORY[tag] = "6 coaching/context"
CATEGORY["espn_cfb_adv_drive_scripting"] = "6 coaching/context"
CATEGORY["espn_cfb_team_tendencies"] = "6 coaching/context"
CATEGORY["espn_cfb_adv_st_team"] = "3 team performance"

for tag in ("cfb_model_artifacts", "espn_cfb_model_artifacts"):
    CATEGORY[tag] = "7 model artifacts"


def load_manifest(path):
    rows, seen = [], {}
    with open(path) as fh:
        for line in fh:
            r = json.loads(line)
            seen[(r["release"], r["asset"])] = r
    return list(seen.values())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--out-dir", default=os.path.join("research", "fbs"))
    a = ap.parse_args(argv)
    manifest = os.path.join(a.dir, "MANIFEST.jsonl")
    rows = load_manifest(manifest)
    by_rel = defaultdict(list)
    for r in rows:
        by_rel[r["release"]].append(r)

    release_rows, coverage_rows, failures = [], [], []
    sums = defaultdict(lambda: [0, 0, 0])       # category -> [files, bytes, rows]
    for tag, files in sorted(by_rel.items()):
        seasons, total_bytes = [], 0
        total_rows = total_cols = 0
        cols_union = set()
        for f in sorted(files, key=lambda x: (x["season"] if x["season"] is not None else 9999, x["asset"])):
            path = os.path.join(a.dir, tag, f["asset"])
            nrows = ncols = None
            try:
                md = pq.ParquetFile(path).metadata
                nrows, ncols = md.num_rows, md.num_columns
                cols_union |= set(pq.ParquetFile(path).schema_arrow.names)
            except Exception as e:
                failures.append((tag, f["asset"], str(e)))
            row_bytes = f["bytes"]
            total_bytes += row_bytes
            total_rows += nrows or 0
            total_cols = max(total_cols, ncols or 0)
            if f["season"] is not None:
                seasons.append(f["season"])
            coverage_rows.append({
                "release": tag, "category": CATEGORY.get(tag, "unmapped"),
                "kind": f["kind"], "season": f["season"] if f["season"] is not None else "",
                "file": f["asset"], "bytes": row_bytes, "rows": nrows if nrows is not None else "",
                "columns": ncols if ncols is not None else "", "sha256": f["sha256"],
                "downloaded_at": f.get("downloaded_at", "")})
        cat = CATEGORY.get(tag, "unmapped")
        sums[cat][0] += len(files)
        sums[cat][1] += total_bytes
        sums[cat][2] += total_rows
        release_rows.append({
            "release": tag, "category": cat, "kind": files[0]["kind"],
            "seasons": "%s-%s" % (min(seasons), max(seasons)) if seasons else "none",
            "n_seasons": len(set(seasons)), "files": len(files), "bytes": total_bytes,
            "rows": total_rows, "max_columns": total_cols, "n_columns_union": len(cols_union)})

    os.makedirs(a.out_dir, exist_ok=True)
    for name, data in (("archive-releases.csv", release_rows), ("archive-coverage.csv", coverage_rows)):
        with open(os.path.join(a.out_dir, name), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0]) if data else ["release"], lineterminator="\n")
            w.writeheader()
            w.writerows(data)

    print("%d releases, %d parquet files, %.1f MB, %.1f M rows"
          % (len(by_rel), len(rows), sum(r["bytes"] for r in rows) / 1e6,
             sum(v[2] for v in sums.values()) / 1e6))
    print("\nby category:")
    for cat in sorted(sums):
        f, b, r = sums[cat]
        print("  %-22s %4d files %9.1f MB %11.0f rows" % (cat, f, b / 1e6, r))
    print("\nreleases with no category mapping: %s"
          % ([r["release"] for r in release_rows if r["category"] == "unmapped"] or "none"))
    if failures:
        print("\nFAILED to read metadata (file unusable): %d" % len(failures))
        for t, f, e in failures[:20]:
            print("  %s/%s: %s" % (t, f, e))
    print("\nwrote %s/archive-releases.csv and archive-coverage.csv" % a.out_dir)


if __name__ == "__main__":
    main()
