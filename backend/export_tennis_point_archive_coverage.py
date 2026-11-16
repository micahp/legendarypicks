#!/usr/bin/env python3
"""Export exact year/tournament coverage for the standalone point-event databases."""

import csv
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path


DB_DIR = Path(__file__).resolve().parent / "data" / "tennis_point_archives"
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "TENNIS-POINT-ARCHIVE-COVERAGE-2026-10-16.csv"
DATABASES = ("grand_slam_archive", "match_charting_project", "usopen", "kalshi")


def export():
    coverage = defaultdict(lambda: {"matches": 0, "metadata_only": 0, "rows": 0, "points": 0})
    for name in DATABASES:
        path = DB_DIR / f"{name}.db"
        if not path.is_file():
            raise RuntimeError(f"missing point database: {path}")
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            source, dataset, expected_rows, expected_points, expected_matches = con.execute(
                "SELECT source,source_dataset,source_event_rows,played_point_rows,source_match_rows "
                "FROM tennis_point_sources"
            ).fetchone()
            events = {}
            for match_id, event_rows, point_rows in con.execute(
                "SELECT source_match_id,COUNT(*),SUM(is_point) "
                "FROM tennis_point_events INDEXED BY ix_tennis_point_events_match_point "
                "WHERE source=? AND source_dataset=? GROUP BY source_match_id",
                (source, dataset),
            ):
                events[match_id] = (event_rows, point_rows or 0)
            actual_rows = sum(row_count for row_count, _ in events.values())
            actual_points = sum(point_count for _, point_count in events.values())
            if (actual_rows, actual_points) != (expected_rows, expected_points):
                raise RuntimeError(
                    f"coverage totals disagree for {name}: {(actual_rows, actual_points)} "
                    f"!= {(expected_rows, expected_points)}"
                )
            match_count = 0
            for match_id, year, tournament, category in con.execute(
                "SELECT source_match_id,match_year,tournament_name,event_category "
                "FROM tennis_point_matches"
            ):
                key = (
                    source, dataset, str(year) if year is not None else "Unknown",
                    tournament or "Unspecified in source", category or "Unspecified in source",
                )
                target = coverage[key]
                if match_id in events:
                    target["matches"] += 1
                    target["rows"] += events[match_id][0]
                    target["points"] += events[match_id][1]
                    match_count += 1
                else:
                    target["metadata_only"] += 1
            if match_count != len(events) or len(events) > expected_matches:
                raise RuntimeError(
                    f"match coverage disagrees for {name}: event matches={len(events)}, "
                    f"metadata-linked={match_count}, metadata total={expected_matches}"
                )
        finally:
            con.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow((
            "source", "source_dataset", "year", "tournament", "event_category",
            "matches_with_points", "metadata_only_matches", "source_event_rows", "point_outcomes",
        ))
        for key in sorted(coverage, key=lambda row: (row[0], row[2], row[3].casefold(), row[4].casefold())):
            writer.writerow((*key, *(
                coverage[key][field] for field in ("matches", "metadata_only", "rows", "points")
            )))
    print(f"wrote {OUTPUT} ({len(coverage):,} year/tournament/category rows)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(export())
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        print(f"export_tennis_point_archive_coverage: {exc}", file=sys.stderr)
        sys.exit(1)
