"""Restore three roster rows to the values they had before the 2026-10-27 repair.

Reviewed operation. NOT RUN ON PROD. Usage:

    python restore_repaired_rows.py --db PATH            dry run: reads only, prints the plan
    python restore_repaired_rows.py --db PATH --apply    takes a fresh backup, then writes

Rules:
- --db is required. There is no default database.
- Dry run and apply both exit 1 if any guard fails. Exit 0 means every guard passed.
- Apply takes a fresh backup to a new file next to the database before it writes. It refuses to run if
  the backup already exists or does not match the source row counts.
- The repair changed only team and team_code. The guards also check player_id and updated_at, so a row
  that has changed since the repair is not touched.
- All guards and every UPDATE run in one transaction. Any mismatch rolls back.
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ORIGINAL_JSON = os.path.join(HERE, "repair_stale_rows_old_values.json")

# repaired is what production holds now. original is what the rows held before the repair.
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

COUNT_TABLES = ("players", "player_source_ids", "published_roster")


def load_stamps():
    """updated_at and player_id from the saved original JSON, which the repair never changed."""
    saved = json.load(open(ORIGINAL_JSON))
    return {(s["league"], s["source"], s["key"]): (s["updated_at"], s["player_id"]) for s in saved}


def check(con, stamps):
    """Return (rows, ok). Each row is (target, status). Reads only."""
    report, ok = [], True
    for target in ROWS:
        key = (target["league"], target["source"], target["key"])
        found = con.execute(
            "SELECT team, team_code, player_id, updated_at FROM published_roster "
            "WHERE league=? AND source=? AND source_player_key=?", key).fetchall()
        updated_at, player_id = stamps[key]
        if len(found) != 1:
            report.append((target, "ROW COUNT %d, expected 1" % len(found)))
            ok = False
            continue
        team, team_code, pid, stamp = found[0]
        problems = []
        if team != target["repaired"]["team"]:
            problems.append("team is %r, expected %r" % (team, target["repaired"]["team"]))
        if team_code != target["repaired"]["team_code"]:
            problems.append("team_code is %r, expected %r" % (team_code, target["repaired"]["team_code"]))
        if pid != player_id:
            problems.append("player_id is %r, expected %r" % (pid, player_id))
        if stamp != updated_at:
            problems.append("updated_at is %r, expected %r" % (stamp, updated_at))
        if problems:
            ok = False
        report.append((target, "OK" if not problems else "; ".join(problems)))
    return report, ok


def counts(con):
    return {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in COUNT_TABLES}


def fresh_backup(db_path):
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = "%s.bak-pre-restore-%s" % (db_path, stamp)
    if os.path.exists(backup_path):
        raise SystemExit("backup path exists, refusing to overwrite: %s" % backup_path)
    src = sqlite3.connect("file:{}?mode=ro".format(db_path), uri=True)
    dst = sqlite3.connect(backup_path)
    src.backup(dst)
    dst.close()
    src_counts = counts(src)
    src.close()
    check_con = sqlite3.connect("file:{}?mode=ro".format(backup_path), uri=True)
    backup_counts = counts(check_con)
    check_con.close()
    if backup_counts != src_counts:
        raise SystemExit("backup row counts differ from source, stopping: %s vs %s" % (backup_counts, src_counts))
    return backup_path, src_counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="path to the SQLite database to restore")
    parser.add_argument("--apply", action="store_true", help="write the restoration (after a fresh backup)")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print("no database at", args.db)
        return 2
    stamps = load_stamps()

    if not args.apply:
        con = sqlite3.connect("file:{}?mode=ro".format(args.db), uri=True)
        report, ok = check(con, stamps)
        con.close()
        for target, status in report:
            print("%s %s %s -> %s" % (target["league"], target["source"], target["key"], status))
            if status == "OK":
                print("   would restore team=%r team_code=%r" % (target["original"]["team"],
                                                                 target["original"]["team_code"]))
        print("DRY RUN, nothing written. %s" % ("all guards passed" if ok else "GUARDS FAILED"))
        return 0 if ok else 1

    backup_path, before = fresh_backup(args.db)
    print("fresh backup written:", backup_path, before)
    con = sqlite3.connect(args.db, timeout=120, isolation_level=None)
    con.execute("BEGIN IMMEDIATE")
    try:
        report, ok = check(con, stamps)
        if not ok:
            raise RuntimeError("guards failed: " + "; ".join(s for t, s in report if s != "OK"))
        for target, _ in report:
            key = (target["league"], target["source"], target["key"])
            changed = con.execute(
                "UPDATE published_roster SET team=?, team_code=? WHERE league=? AND source=? "
                "AND source_player_key=? AND team=? AND team_code IS ? AND player_id IS NULL AND updated_at=?",
                (target["original"]["team"], target["original"]["team_code"], key[0], key[1], key[2],
                 target["repaired"]["team"], target["repaired"]["team_code"], stamps[key][0])).rowcount
            if changed != 1:
                raise RuntimeError("expected 1 row changed for %s, got %d" % (key, changed))
        con.execute("COMMIT")
        print("committed: %d rows restored to their original team and team_code" % len(report))
        return 0
    except Exception as exc:
        con.execute("ROLLBACK")
        print("ROLLED BACK, nothing written:", exc)
        return 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
