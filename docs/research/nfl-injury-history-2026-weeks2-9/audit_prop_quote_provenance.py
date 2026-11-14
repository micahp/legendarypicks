#!/usr/bin/env python3
"""Read-only provenance audit of graded 2026 NFL sportsbook quote captures.

Audits the quoted market side timestamps against the source's stored kickoff,
exports all recorded-settlement disagreements, and never silently replaces
historical prices with reconstructed prices. Some ingest jobs update rows
in place: a post-kickoff quote cannot recover a previous pregame price.
"""
import argparse
import csv
import datetime as dt
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "backend"))
import grade_nfl_prop_probabilities as grader
import player_splits


def utc_time(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def audit_status(kickoff, over, under):
    if over is None or under is None:
        return "selected_quote_side_missing"
    start = utc_time(kickoff)
    if start is None:
        return "kickoff_unverifiable"
    over_at = utc_time(over.get("odds_captured_at"))
    under_at = utc_time(under.get("odds_captured_at"))
    if over_at is None or under_at is None:
        return "odds_timestamp_unverifiable"
    if over_at >= start or under_at >= start:
        return "selected_quote_at_or_after_kickoff"
    return "selected_quote_pre_kickoff_recorded"


def selected_quotes(connection):
    markets = tuple(grader.RECEIVING) + tuple(grader.PASSING)
    query = (
        "SELECT p.game_id, p.player_id, p.market, p.source, p.line, p.side, "
        "p.odds, p.captured_at, p.odds_captured_at, r.hit, g.start_time "
        "FROM props p JOIN prop_games g ON g.id=p.game_id "
        "LEFT JOIN prop_results r ON r.prop_id=p.id "
        "WHERE g.league='nfl' AND p.market IN (%s) AND p.source IN (%s) "
        "AND p.odds IS NOT NULL" %
        (",".join("?" * len(markets)), ",".join("?" * len(grader.BOOKS)))
    )
    raw = connection.execute(query, markets + grader.BOOKS).fetchall()
    joins = player_splits.prop_game_nfl_ids(connection, {r[0] for r in raw})
    gsis_by_id = {int(pid): str(gsis) for pid, gsis in connection.execute(
        "SELECT id, nfl_gsis_id FROM players WHERE league='nfl' AND nfl_gsis_id IS NOT NULL"
    )}
    chosen = {}
    for pg, pid, market, book, line, side, odds, captured, odds_at, hit, start in raw:
        gid, gsis = joins.get(pg), gsis_by_id.get(int(pid))
        if gid is None or gsis is None:
            continue
        key = (gid, gsis, market, book, float(line), side)
        record = {
            "odds": odds, "captured_at": captured, "odds_captured_at": odds_at,
            "hit": hit, "kickoff": start, "prop_game_id": pg,
        }
        old = chosen.get(key)
        # Exactly mirror grader.collect()'s latest-captured_at row choice.
        if old is None or (captured or "") > (old["captured_at"] or ""):
            chosen[key] = record
    return chosen


def audit(connection, projections_csv, manifest_csv):
    selected = selected_quotes(connection)
    manifest = {}
    with manifest_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            manifest[row["game_id"]] = row["url"]
    counts = Counter()
    weekly = defaultdict(Counter)
    discrepancies = []
    errors = []
    audited = 0
    with projections_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["game_id"], row["stable_player_id"], row["market"],
                   row["book"], float(row["line"]))
            over = selected.get(key + ("over",))
            under = selected.get(key + ("under",))
            kickoff = (over or under or {}).get("kickoff")
            status = audit_status(kickoff, over, under)
            week = int(row["week"])
            counts[status] += 1
            weekly[week][status] += 1
            audited += 1
            if status != "selected_quote_pre_kickoff_recorded":
                errors.append({
                    "week": week, "game_id": key[0], "player": row["player_name"],
                    "stable_player_id": key[1], "market": key[2], "book": key[3],
                    "line": key[4], "status": status, "kickoff": kickoff,
                    "over_odds_captured_at": (over or {}).get("odds_captured_at"),
                    "under_odds_captured_at": (under or {}).get("odds_captured_at"),
                })
            if over is None:
                continue
            book_hit = over["hit"]
            if book_hit is not None and int(book_hit) != int(float(row["actual"]) > key[4]):
                discrepancies.append({
                    "week": week, "game_id": key[0], "player": row["player_name"],
                    "stable_player_id": key[1], "market": key[2], "book": key[3],
                    "line": key[4], "actual_stat_line": row["actual"],
                    "graded_over": int(float(row["actual"]) > key[4]),
                    "book_over_hit": int(book_hit), "quote_status": status,
                    "over_odds_captured_at": over.get("odds_captured_at"),
                    "under_odds_captured_at": (under or {}).get("odds_captured_at"),
                    "kickoff": kickoff, "official_gamebook": manifest.get(key[0]),
                })
    distinct = len({(r["game_id"], r["stable_player_id"], r["market"]) for r in discrepancies})
    return {
        "rows_scored": audited, "quote_status_counts": dict(counts),
        "quote_status_by_week": {str(k): dict(v) for k, v in sorted(weekly.items())},
        "recorded_book_settlement_disagreements": len(discrepancies),
        "distinct_game_player_market_discrepancies": distinct,
        "scope": "Existing graded lines; latest stored odds per side. Does not recover in-place overwritten odds.",
        "selected_quote_validation": "Both side odds_captured_at timezone-aware and strictly earlier than stored prop_games.start_time; statuses not certified independently against ESPN scheduled kickoff.",
    }, discrepancies, errors


def csv_export(path, rows):
    # For empty results still produce a minimal one-column audit marker.
    fields = list(rows[0]) if rows else ["no_rows"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--projections", type=Path, default=HERE / "walk-forward-prop-projections.csv")
    ap.add_argument("--manifest", type=Path, default=HERE / "official-gamebooks-source-manifest.csv")
    ap.add_argument("--out-dir", type=Path, default=HERE)
    ap.add_argument("--expected-graded-lines", type=int, default=65448)
    args = ap.parse_args()
    con = sqlite3.connect("file:{}?mode=ro".format(args.db.resolve()), uri=True)
    try:
        con.execute("BEGIN")
        report, disputes, issues = audit(con, args.projections, args.manifest)
    finally:
        con.rollback()
        con.close()
    if report["rows_scored"] != args.expected_graded_lines:
        raise ValueError("graded source population shifted: " + str(report["rows_scored"]))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "prop-quote-provenance-audit.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    csv_export(args.out_dir / "recorded-settlement-disagreements.csv", disputes)
    csv_export(args.out_dir / "prop-quote-timestamp-exceptions.csv", issues)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
