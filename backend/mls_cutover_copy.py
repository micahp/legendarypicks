"""Build an isolated, migrated copy of the MLS identity scope from a production database. Read-only on production.

Usage: python mls_cutover_copy.py PROD_DB DEST

The copy has the production table definitions for every table the MLS identity and its history touch. Per-player
tables hold only MLS players' rows (their game logs, props, prop results and settlement attempts). Identity tables and
team game results are copied whole. DEST must not exist. The production file is opened read-only and never written.
"""
import os
import sqlite3
import sys

WHOLE = ("players", "player_source_ids", "published_roster", "published_roster_name", "league_clubs",
         "team_game_results", "name_alias")
MLS_PLAYERS = "SELECT id FROM players WHERE league='mls'"
FILTERED = {
    "player_game_logs": "player_id IN (%s)" % MLS_PLAYERS,
    "props": "player_id IN (%s)" % MLS_PLAYERS,
    "prop_results": "prop_id IN (SELECT id FROM props WHERE player_id IN (%s))" % MLS_PLAYERS,
    "settlement_attempts": "prop_id IN (SELECT id FROM props WHERE player_id IN (%s))" % MLS_PLAYERS,
    "roster_snapshots": "league='mls'",
    "roster_memberships": "snapshot_id IN (SELECT id FROM roster_snapshots WHERE league='mls')",
}


def build(prod_path, dest):
    if os.path.exists(dest):
        raise SystemExit("refusing to overwrite %s" % dest)
    src = sqlite3.connect("file:%s?mode=ro" % prod_path, uri=True, timeout=120)
    out = sqlite3.connect(dest)
    counts = {}
    for table, where in [(t, "") for t in WHOLE] + list(FILTERED.items()):
        ddl = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if ddl is None:
            raise SystemExit("production has no table %s" % table)
        out.execute(ddl[0])
        cols = [row[1] for row in src.execute("PRAGMA table_info(%s)" % table)]
        clause = " WHERE %s" % where if where else ""
        cursor = src.execute("SELECT %s FROM %s%s" % (",".join(cols), table, clause))
        n = 0
        while True:
            rows = cursor.fetchmany(5000)
            if not rows:
                break
            out.executemany("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(cols), ",".join("?" * len(cols))),
                            rows)
            n += len(rows)
        counts[table] = n
    names = tuple(list(WHOLE) + list(FILTERED))
    marks = ",".join("?" * len(names))
    for (sql,) in src.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
                              "AND tbl_name IN (%s)" % marks, names):
        out.execute(sql)
    out.commit()
    out.close()
    src.close()
    return counts


if __name__ == "__main__":
    for table, n in build(sys.argv[1], sys.argv[2]).items():
        print("%-22s %d" % (table, n))
