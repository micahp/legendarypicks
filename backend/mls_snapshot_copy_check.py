"""Run the MLS snapshot against a COPY of the production database and prove what did not change.

Usage: python mls_snapshot_copy_check.py COPY_PATH REPORT_PATH

COPY_PATH must be a separate file that already holds a copy of production. The script refuses the live
production path. It checksums the tables that must not change, publishes the snapshot into the copy,
checksums them again, and writes a report. It does not touch production.
"""
import hashlib
import json
import os
import sqlite3
import sys

import mls_snapshot as ms

PROD = "/root/legendarypicks/backend/data/picks.db"
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "mls_regression_2026-10-27.json")
PROTECTED = ("players", "player_source_ids", "player_game_logs", "props", "prop_results",
             "settlement_attempts", "team_game_results", "published_roster")
CAPTURED = "2026-10-27T21:13:59+00:00"


def table_checksum(con, table):
    digest = hashlib.sha256()
    count = 0
    for row in con.execute("SELECT * FROM %s ORDER BY rowid" % table):
        digest.update(repr(tuple(row)).encode("utf-8"))
        count += 1
    return {"rows": count, "sha256": digest.hexdigest()}


def checksums(con):
    return {t: table_checksum(con, t) for t in PROTECTED}


def main(copy_path, report_path):
    if os.path.abspath(copy_path) == os.path.abspath(PROD):
        raise SystemExit("refusing to run against the production database")
    con = sqlite3.connect(copy_path, timeout=120, isolation_level=None)
    con.row_factory = sqlite3.Row
    before = checksums(con)

    fx = json.load(open(FIXTURE))
    binds = {}
    for source, key, player_id in fx["binds"]:
        binds[(source, key)] = player_id
    result = ms.build(fx["squads"], binds, prior_memberships=ms.load_prior(con), captured_at=CAPTURED)
    if result.status != "publish":
        raise SystemExit("snapshot refused: %s" % result.reasons)
    con.execute("BEGIN IMMEDIATE")
    try:
        snapshot_id = ms.publish(con, result, CAPTURED)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    after = checksums(con)

    report = {
        "copy": copy_path,
        "snapshot_id": snapshot_id,
        "memberships": len(result.memberships),
        "blockers": len(result.blockers),
        "carried": len(result.carried),
        "unchanged": {t: before[t]["sha256"] == after[t]["sha256"] for t in PROTECTED},
        "before": before,
        "after": after,
        "roster_memberships_for_snapshot": con.execute(
            "SELECT COUNT(*) FROM roster_memberships WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0],
        "published_mls_snapshots": con.execute(
            "SELECT COUNT(*) FROM roster_snapshots WHERE league='mls' AND status='published'").fetchone()[0],
    }
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps({k: report[k] for k in ("snapshot_id", "memberships", "blockers", "carried",
                                              "roster_memberships_for_snapshot")}, indent=1))
    print("unchanged:", report["unchanged"])
    return 0 if all(report["unchanged"].values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
