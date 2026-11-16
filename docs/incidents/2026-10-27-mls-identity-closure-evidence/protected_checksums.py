"""Row checksums of the identity and history tables, read-only. Usage: protected_checksums.py DB_PATH

Prints JSON: row count and SHA-256 over every row (in rowid order) for each table that exists. Opens the database
read-only, so it can be pointed at a copy before and after a cycle.
"""
import hashlib
import json
import sqlite3
import sys

TABLES = ("players", "player_source_ids", "roster_snapshots", "roster_memberships", "identity_evidence",
          "identity_onboarding_queue", "player_game_logs", "props", "prop_results", "settlement_attempts",
          "team_game_results", "prop_games")


def table_digest(con, table):
    h = hashlib.sha256()
    count = 0
    for row in con.execute("SELECT * FROM %s ORDER BY rowid" % table):
        h.update(repr(tuple(row)).encode())
        count += 1
    return {"rows": count, "sha256": h.hexdigest()}


def main(argv):
    path = argv[1]
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    present = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    out = {"db": path}
    for table in TABLES:
        out[table] = table_digest(con, table) if table in present else "absent"
    con.close()
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv)
