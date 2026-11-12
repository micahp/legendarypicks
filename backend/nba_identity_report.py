#!/usr/bin/env python3
"""Read-only NBA identity report.

Opens the database read-only and writes:
  - a markdown summary (counts and problem lists)
  - players_nba.csv: every NBA row in `players`, with its IDs
  - unresolved_nba.csv: every NBA row in `unresolved_players`, and whether its
    ESPN ID now exists in `players`. `times_seen` is the queue's `count`: how
    often resolution failed. It is NOT a count of missing games.

Usage:
  python3 nba_identity_report.py --db /abs/path/picks.dev.db --out /abs/out/dir
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sqlite3
import sys


def connect_ro(path: str) -> sqlite3.Connection:
    if not os.path.isabs(path) or not os.path.isfile(path):
        raise SystemExit("database must be an existing absolute file: " + path)
    return sqlite3.connect("file:{}?mode=ro".format(path), uri=True, timeout=30)


def scalar(con: sqlite3.Connection, sql: str, args=()) -> int:
    return con.execute(sql, args).fetchone()[0]


def write_csv(path: str, header, rows) -> int:
    count = 0
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    con = connect_ro(args.db)

    players_cols = {r[1] for r in con.execute("PRAGMA table_info(players)")}
    if not {"id", "name", "espn_id", "nba_id", "league"} <= players_cols:
        raise SystemExit("players table is missing expected columns")
    has_active = "active" in players_cols
    has_team = "team" in players_cols
    has_pos = "position" in players_cols
    select = "id, name, {}, {}, {}, {}, {}".format(
        "team" if has_team else "NULL",
        "position" if has_pos else "NULL",
        "active" if has_active else "NULL",
        "espn_id", "nba_id")
    nba_rows = con.execute(
        "SELECT {} FROM players WHERE league = 'nba' ORDER BY id".format(select)
    ).fetchall()

    total = len(nba_rows)
    with_espn = sum(1 for r in nba_rows if r[5] not in (None, ""))
    with_nba = sum(1 for r in nba_rows if r[6] not in (None, ""))
    with_both = sum(1 for r in nba_rows if r[5] not in (None, "") and r[6] not in (None, ""))
    with_neither = sum(1 for r in nba_rows if r[5] in (None, "") and r[6] in (None, ""))
    active = sum(1 for r in nba_rows if has_active and r[4] == 1)

    espn_counts = {}
    nba_counts = {}
    for r in nba_rows:
        if r[5] not in (None, ""):
            espn_counts[str(r[5])] = espn_counts.get(str(r[5]), 0) + 1
        if r[6] not in (None, ""):
            nba_counts[str(r[6])] = nba_counts.get(str(r[6]), 0) + 1
    dup_espn = {k: v for k, v in espn_counts.items() if v > 1}
    dup_nba = {k: v for k, v in nba_counts.items() if v > 1}

    players_csv = os.path.join(args.out, "players_nba.csv")
    write_csv(players_csv,
              ["players_id", "name", "team", "position", "active", "espn_id", "nba_id"],
              nba_rows)

    unresolved = con.execute(
        "SELECT source_player_key, raw_name, team, count, reason, first_seen "
        "FROM unresolved_players WHERE league = 'nba' "
        "ORDER BY count DESC, source_player_key").fetchall()
    espn_in_players = {str(r[0]) for r in con.execute(
        "SELECT espn_id FROM players WHERE league = 'nba' AND espn_id IS NOT NULL")}
    unresolved_rows = []
    for key, raw_name, team, count, reason, first_seen in unresolved:
        unresolved_rows.append((
            key, raw_name, team, count, reason, first_seen,
            "yes" if str(key) in espn_in_players else "no"))
    unresolved_csv = os.path.join(args.out, "unresolved_nba.csv")
    write_csv(unresolved_csv,
              ["source_player_key", "raw_name", "team", "times_seen", "reason",
               "first_seen", "espn_id_now_in_players"],
              unresolved_rows)

    still_missing = sum(1 for r in unresolved_rows if r[6] == "no")
    now_resolved = len(unresolved_rows) - still_missing

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = [
        "# NBA identity report",
        "",
        "Generated {} from `{}`. Read-only. No rows were changed.".format(
            stamp, os.path.basename(args.db)),
        "",
        "## players, league = nba",
        "",
        "| Measure | Count |",
        "|---|---|",
        "| Rows | {} |".format(total),
        "| Active | {} |".format(active),
        "| With ESPN ID | {} |".format(with_espn),
        "| With NBA ID (hoopR) | {} |".format(with_nba),
        "| With both IDs | {} |".format(with_both),
        "| With neither ID | {} |".format(with_neither),
        "| Duplicate ESPN IDs (more than one row) | {} |".format(len(dup_espn)),
        "| Duplicate NBA IDs (more than one row) | {} |".format(len(dup_nba)),
        "",
        "## unresolved_players, league = nba",
        "",
        "| Measure | Count |",
        "|---|---|",
        "| Parked rows | {} |".format(len(unresolved_rows)),
        "| ESPN ID now in players | {} |".format(now_resolved),
        "| ESPN ID still missing from players | {} |".format(still_missing),
        "",
        "## Files",
        "",
        "- `players_nba.csv`: every NBA row, with its IDs.",
        "- `unresolved_nba.csv`: every parked row, with `espn_id_now_in_players`.",
        "  `times_seen` counts repeated failed resolution attempts. It is not a",
        "  count of missing games. The queue stores no game ID, date, or stats.",
        "",
    ]
    if dup_espn:
        md += ["## Duplicate ESPN IDs", "", "| espn_id | rows |", "|---|---|"]
        md += ["| {} | {} |".format(k, v) for k, v in sorted(dup_espn.items())]
        md.append("")
    if dup_nba:
        md += ["## Duplicate NBA IDs", "", "| nba_id | rows |", "|---|---|"]
        md += ["| {} | {} |".format(k, v) for k, v in sorted(dup_nba.items())]
        md.append("")
    summary = os.path.join(args.out, "NBA-IDENTITY-REPORT.md")
    with open(summary, "w", encoding="utf-8") as handle:
        handle.write("\n".join(md))
    con.close()
    print("summary:", summary)
    print("players rows:", total, "| parked rows:", len(unresolved_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
