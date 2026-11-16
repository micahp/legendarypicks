"""Run the MLS snapshot against a COPY of production, with identities from the copy's own binds.

Usage: python mls_snapshot_copy_check.py COPY_PATH REPORT_PATH

- Identities come from the copy's player_source_ids (binds_from_db), not from the saved fixture.
- The fixture's squads are the frozen source records. Its bindings are compared with the copy's and every
  difference is reported.
- Runs the snapshot twice: the first run publishes, the second must be unchanged.
- Checksums eight protected tables before and after, and after the repeat run.

Refuses the live production path. Writes only to COPY_PATH.
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
REPEAT = "2026-10-28T21:13:59+00:00"


def table_checksum(con, table):
    digest = hashlib.sha256()
    count = 0
    for row in con.execute("SELECT * FROM %s ORDER BY rowid" % table):
        digest.update(repr(tuple(row)).encode("utf-8"))
        count += 1
    return {"rows": count, "sha256": digest.hexdigest()}


def checksums(con):
    return {t: table_checksum(con, t) for t in PROTECTED}


def bind_discrepancies(fixture_binds, copy_binds, squad_keys):
    """Fixture bindings compared with the copy, for the keys in the squads."""
    report = {"missing_in_copy": [], "different_player": [], "not_in_fixture": 0}
    for source, key, player_id in fixture_binds:
        if (source, str(key)) not in squad_keys:
            continue
        found = copy_binds.get((source, str(key)))
        if found is None:
            report["missing_in_copy"].append([source, key, player_id])
        elif found != player_id:
            report["different_player"].append([source, key, player_id, found])
    fixture_keys = {(s, str(k)) for s, k, _ in fixture_binds}
    report["not_in_fixture"] = sum(1 for k in squad_keys if k in copy_binds and k not in fixture_keys)
    return report


def run(con, squads, binds, captured_at):
    result = ms.build(con, squads, binds, captured_at=captured_at)
    if result.status != "publish":
        return result, "refused", None
    con.execute("BEGIN IMMEDIATE")
    try:
        outcome, snapshot_id = ms.publish(con, result, captured_at)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return result, outcome, snapshot_id


def main(copy_path, report_path):
    if os.path.abspath(copy_path) == os.path.abspath(PROD):
        raise SystemExit("refusing to run against the production database")
    con = sqlite3.connect(copy_path, timeout=120, isolation_level=None)
    con.row_factory = sqlite3.Row
    before = checksums(con)

    fx = json.load(open(FIXTURE))
    squads = fx["squads"]
    squad_keys = {(s, str(m["source_player_key"])) for s in squads for m in squads[s]}
    copy_binds = ms.binds_from_db(con)
    discrepancies = bind_discrepancies(fx["binds"], copy_binds, squad_keys)

    result, outcome, snapshot_id = run(con, squads, copy_binds, CAPTURED)
    if result.status != "publish":
        raise SystemExit("snapshot refused on the copy: %s" % result.reasons)
    after_first = checksums(con)

    repeat, repeat_outcome, repeat_id = run(con, squads, copy_binds, REPEAT)
    after_repeat = checksums(con)

    report = {
        "copy": copy_path,
        "identities_from": "copy player_source_ids",
        "bind_discrepancies_vs_fixture": discrepancies,
        "first_run": {"outcome": outcome, "snapshot_id": snapshot_id, "coverage": result.coverage,
                      "memberships": len(result.memberships), "blockers": len(result.blockers),
                      "carried": len(result.carried), "departures": len(result.departures),
                      "single_source_departures": len(result.single_source_departures),
                      "transfers": len(result.transfers), "rekeys": len(result.rekeys),
                      "bind_changed": len(result.bind_changed)},
        "repeat_run": {"outcome": repeat_outcome, "snapshot_id": repeat_id, "coverage": repeat.coverage},
        "unchanged_after_first_run": {t: before[t]["sha256"] == after_first[t]["sha256"] for t in PROTECTED},
        "unchanged_after_repeat_run": {t: before[t]["sha256"] == after_repeat[t]["sha256"] for t in PROTECTED},
        "checksums_before": before,
        "checksums_after_first_run": after_first,
        "checksums_after_repeat_run": after_repeat,
        "published_mls_snapshots": con.execute(
            "SELECT COUNT(*) FROM roster_snapshots WHERE league='mls' AND status='published'").fetchone()[0],
        "health": ms.health(con),
    }
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps({"first_run": report["first_run"], "repeat_run": report["repeat_run"],
                      "bind_discrepancies": {k: (v if isinstance(v, int) else len(v))
                                             for k, v in discrepancies.items()}}, indent=1))
    ok = all(report["unchanged_after_first_run"].values()) and all(report["unchanged_after_repeat_run"].values())
    print("protected tables unchanged after both runs:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
