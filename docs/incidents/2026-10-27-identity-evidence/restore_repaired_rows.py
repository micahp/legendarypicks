"""Restore three roster rows to the values they had before the 2026-10-27 repair.

Reviewed operation, NOT RUN ON PROD. Dry run by default: it reads the database and reports what
--apply would do. Nothing is written unless --apply is given.

The repair changed only `team` and `team_code`. updated_at and player_id were never changed, so the
guards below check them as well, to prove the rows are still in the repaired state.

Each row must match its repaired state exactly, and each change must touch exactly one row. Any
mismatch aborts the transaction and writes nothing.
"""
import json
import sqlite3
import sys

DB = "/root/legendarypicks/backend/data/picks.db"
ORIGINAL_JSON = "repair_stale_rows_old_values.json"  # next to this script

# (league, source, key) -> repaired state (what prod has now) and original state (what to restore)
ROWS = [
    {"league": "mls", "source": "fotmob", "key": "1259117",
     "repaired": {"team": "Paysandu", "team_code": None},
     "original": {"team": "Los Angeles FC", "team_code": "LAFC"}},
    {"league": "lcup", "source": "fotmob", "key": "1259117",
     "repaired": {"team": "Paysandu", "team_code": None},
     "original": {"team": "Los Angeles FC", "team_code": "LAFC"}},
    {"league": "mls", "source": "fotmob", "key": "1787871",
     "repaired": {"team": "CD FAS", "team_code": None},
     "original": {"team": "Red Bull New York", "team_code": "RBNY"}},
]


def _load_stamps():
    """updated_at and player_id from the saved original JSON, which the repair never changed."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    saved = json.load(open(os.path.join(here, ORIGINAL_JSON)))
    stamps = {}
    for item in saved:
        stamps[(item["league"], item["source"], item["key"])] = (item["updated_at"], item["player_id"])
    return stamps


def _guard_sql():
    return ("SELECT team, team_code, player_id, updated_at FROM published_roster "
            "WHERE league=? AND source=? AND source_player_key=?")


def check(con, stamps):
    """Return a list of (row, status, current) for each target row, without writing."""
    report = []
    for row in ROWS:
        key = (row["league"], row["source"], row["key"])
        found = con.execute(_guard_sql(), key).fetchall()
        updated_at, player_id = stamps[key]
        if len(found) != 1:
            report.append((row, "ROW COUNT %d (expected 1)" % len(found), None))
            continue
        team, team_code, pid, stamp = found[0]
        problems = []
        if team != row["repaired"]["team"]:
            problems.append("team is %r, expected repaired %r" % (team, row["repaired"]["team"]))
        if team_code != row["repaired"]["team_code"]:
            problems.append("team_code is %r, expected repaired %r" % (team_code, row["repaired"]["team_code"]))
        if pid != player_id:
            problems.append("player_id is %r, expected %r" % (pid, player_id))
        if stamp != updated_at:
            problems.append("updated_at is %r, expected %r" % (stamp, updated_at))
        report.append((row, "OK" if not problems else "; ".join(problems), found[0]))
    return report


def main(apply: bool):
    stamps = _load_stamps()
    if not apply:
        con = sqlite3.connect("file:{}?mode=ro".format(DB), uri=True)
        for row, status, current in check(con, stamps):
            print(row["league"], row["source"], row["key"], "->", status)
            print("   would restore team=%r team_code=%r" % (row["original"]["team"], row["original"]["team_code"]))
        con.close()
        print("DRY RUN: nothing written. Re-run with --apply only after review.")
        return 0

    con = sqlite3.connect(DB, timeout=120, isolation_level=None)
    con.execute("BEGIN IMMEDIATE")
    try:
        report = check(con, stamps)
        bad = [r for r in report if r[1] != "OK"]
        if bad:
            raise RuntimeError("guards failed: %s" % bad)
        for row, _, _ in report:
            changed = con.execute(
                "UPDATE published_roster SET team=?, team_code=? WHERE league=? AND source=? "
                "AND source_player_key=? AND team=? AND team_code IS ? AND player_id IS NULL AND updated_at=?",
                (row["original"]["team"], row["original"]["team_code"], row["league"], row["source"], row["key"],
                 row["repaired"]["team"], row["repaired"]["team_code"], stamps[(row["league"], row["source"], row["key"])][0])
            ).rowcount
            if changed != 1:
                raise RuntimeError("expected 1 row changed for %s, got %d" % (row["key"], changed))
        con.execute("COMMIT")
        print("committed: three rows restored to their original team and team_code")
        return 0
    except Exception as exc:
        con.execute("ROLLBACK")
        print("ROLLED BACK, nothing written:", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
