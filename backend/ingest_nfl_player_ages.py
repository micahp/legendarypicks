#!/usr/bin/env python3
"""ingest_nfl_player_ages.py -- birth dates for a Marcel-style aging curve.

Why this exists: an aging curve needs a player's age in the target season, and `players` has no birth date
column at all. nflverse publishes one on `players.parquet`, which `ingest_nfl_weekly_stats.py` already
downloads for identity resolution, so this reads a file already in the pipeline rather than adding a source.

Writes `nfl_player_birth_dates`, keyed on gsis_id. A side table rather than a new column on `players`:
`players` is shared with other sessions and an ALTER is a schema change they did not agree to. Promote to
`players.birth_date` when that is wanted.

Reconciles stored rows against the file's own row count, and reports how many resolved to a `players` row.
Idempotent: re-running replaces the table's rows for the source.

Usage: LP_DB_PATH=... python3 ingest_nfl_player_ages.py [--path /tmp/nflverse_players.parquet]
"""
import argparse
import datetime
import os
import sqlite3
import sys
import urllib.request

URL = ("https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet")
SOURCE = "nflverse_players_parquet"
DDL = """
CREATE TABLE IF NOT EXISTS nfl_player_birth_dates (
    gsis_id       TEXT PRIMARY KEY,
    player_id     INTEGER,
    name          TEXT,
    birth_date    TEXT,
    rookie_season INTEGER,
    draft_year    INTEGER,
    position      TEXT,
    source        TEXT NOT NULL,
    loaded_at     TEXT NOT NULL
)
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", default="/tmp/nflverse_players.parquet")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    if not os.path.exists(a.path):
        print("downloading %s" % URL)
        urllib.request.urlretrieve(URL, a.path)
    import pyarrow.parquet as pq
    cols = [f.name for f in pq.read_schema(a.path)]
    want = [c for c in ("gsis_id", "display_name", "birth_date", "rookie_season", "draft_year",
                        "position") if c in cols]
    table = pq.read_table(a.path, columns=want)
    rows = table.to_pylist()
    file_rows = len(rows)
    with_birth = [r for r in rows if r.get("birth_date")]
    print("artifact: %s (%d rows, %d with a birth date)" % (os.path.basename(a.path), file_rows,
                                                            len(with_birth)))
    if a.dry_run:
        print("dry run: nothing written")
        return
    now = datetime.datetime.utcnow().isoformat() + "+00:00"
    con = sqlite3.connect(path)
    con.execute(DDL)
    ids = {g: pid for pid, g in con.execute(
        "SELECT id, nfl_gsis_id FROM players WHERE league='nfl' AND nfl_gsis_id IS NOT NULL")}
    con.execute("DELETE FROM nfl_player_birth_dates WHERE source=?", (SOURCE,))
    payload = []
    for r in rows:
        g = r.get("gsis_id")
        if not g:
            continue
        payload.append((g, ids.get(g), r.get("display_name"), r.get("birth_date"),
                        r.get("rookie_season"), r.get("draft_year"), r.get("position"), SOURCE, now))
    con.executemany(
        "INSERT INTO nfl_player_birth_dates (gsis_id, player_id, name, birth_date, rookie_season, "
        "draft_year, position, source, loaded_at) VALUES (?,?,?,?,?,?,?,?,?)", payload)
    con.commit()
    stored = con.execute("SELECT COUNT(*) FROM nfl_player_birth_dates WHERE source=?", (SOURCE,)).fetchone()[0]
    joined = con.execute("SELECT COUNT(*) FROM nfl_player_birth_dates WHERE source=? AND player_id IS NOT NULL",
                         (SOURCE,)).fetchone()[0]
    dated = con.execute("SELECT COUNT(*) FROM nfl_player_birth_dates WHERE source=? AND birth_date IS NOT NULL",
                        (SOURCE,)).fetchone()[0]
    print("wrote %d rows (file had %d); %d dated; %d joined to a players row" % (stored, file_rows, dated, joined))
    if stored != len(payload):
        print("MISMATCH: wrote %d, expected %d" % (stored, len(payload)))
    # sanity: age of a known skill player, and the spread of ages in 2024
    row = con.execute("SELECT name, birth_date FROM nfl_player_birth_dates WHERE gsis_id=?",
                      ("00-0034857",)).fetchone()
    print("sanity (00-0034857): %s" % (row,))
    con.close()


if __name__ == "__main__":
    sys.exit(main())
