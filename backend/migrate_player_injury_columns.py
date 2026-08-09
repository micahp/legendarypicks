"""One-shot: give `players` the two columns the NFL draft board reads.

`ingest_nfl_adp.py:278` guards its write on these columns existing:

    _has_injury_cols = {"injury_status", "last_news_date"} <= {...}

which means a database without them is not an error. The ingest runs, reports
success, writes everything else, and skips these two in silence. That is
exactly what happened: on 2026-08-05 the production draft pool served **4,508
players with injury_status set on 0 of them**, against 2,616 on dev. The API
returned the keys, always null -- no error, no empty state, just a draft board
on which nobody is injured, in the week before draft season.

The guard is not wrong; a missing column should not crash an ingest. The
missing piece is that nothing ever added the columns to prod, because they were
added to dev by hand and no migration existed to carry them across. That is the
same shape as the other six divergences found that day (see
`backend/diff_databases.py`), and this file exists so this one cannot recur.

Columns:
  injury_status   TEXT  ESPN's `injuryStatus` verbatim -- the publisher's word,
                        not a normalised one. Absent means "not reported",
                        which is different from "healthy" and must stay
                        distinguishable.
  last_news_date  TEXT  ESPN's `lastNewsDate` verbatim: **epoch milliseconds
                        as a string**, not an ISO date, despite the name.
                        Measured range 2026-08-05: 1535827792000 (2018-09-01)
                        to 1785892683000 (2026-08-05). It is a recency signal
                        -- when anyone last wrote about this player -- and it
                        is the thing that distinguishes a genuinely active
                        player from one ESPN still lists. Artavis Scott reads
                        `injury_status='ACTIVE'` with no news since 2018:
                        ESPN's ACTIVE means "carries no designation", not
                        "playing", so neither column means much without the
                        other. Convert at the read site, not here -- storing
                        the publisher's value verbatim is what makes it
                        diffable against the source.

Usage:
  cd backend && venv/bin/python migrate_player_injury_columns.py \\
      --db /abs/path/picks.db [--apply]

Dry run by default. Idempotent -- ADD COLUMN is skipped for any column already
present, so a second --apply run reports zero additions. Purely additive: no
existing column is read, written or dropped, so it cannot disturb a row.

After applying, re-run `ingest_nfl_adp.py` against the same database; the
columns alone are empty until something fills them.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("LP_DB_PATH") or os.path.join(HERE, "data", "picks.db")

COLUMNS = (
    ("injury_status", "TEXT"),
    ("last_news_date", "TEXT"),
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--apply", action="store_true",
                    help="commit the change; default is a dry run")
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"migrate_player_injury_columns: no such database: {args.db}",
              file=sys.stderr)
        return 2

    con = sqlite3.connect(args.db)
    try:
        present = {r[1] for r in con.execute("PRAGMA table_info(players)")}
        missing = [(name, kind) for name, kind in COLUMNS if name not in present]

        print(f"database: {args.db}")
        for name, kind in COLUMNS:
            state = "already present" if name in present else f"+ {name} {kind}"
            print(f"  {state}")

        if not missing:
            print("nothing to do: both columns already exist")
            return 0
        if not args.apply:
            print(f"\ndry run -- would add {len(missing)} column(s). "
                  "re-run with --apply")
            return 0

        for name, kind in missing:
            con.execute(f"ALTER TABLE players ADD COLUMN {name} {kind}")
        con.commit()
        print(f"\nadded {len(missing)} column(s): "
              f"{', '.join(n for n, _ in missing)}")
        print("columns are EMPTY until an ingest fills them -- "
              "run ingest_nfl_adp.py against this database next")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
