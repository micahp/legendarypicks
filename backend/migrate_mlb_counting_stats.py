"""One-shot: give `player_stats` the MLB counting stats nobody could measure.

`docs/LEAGUE-STAT-GAPS.md` records MLB as having no PA, no hits, no RBI, no ERA,
no innings and no WHIP -- and both published qualifier rules (3.1 PA x team
games, 1.0 IP x team games) as unmeasurable, because the columns their units are
counted in did not exist. It also records ERA and AB as published nowhere we
hold.

All of that was wrong. `statsapi.mlb.com/api/v1/stats?stats=season&group=hitting`
publishes the entire batting line and `group=pitching` the entire pitching line,
in one request each, for the full player pool. MLB has been publishing its own
counting stats the whole time; we were reading only Statcast, which publishes
exit velocity and xwOBA and was never going to carry an RBI.

Why these columns and not others
--------------------------------
Statcast keeps this row. It owns `exit_velo`, `barrel_pct`, `xwoba`,
`whiff_pct` and the rest, all of which are on the props page today, and nothing
here touches them. These columns are the ones Statcast never had, so the two
publishers fill different halves of one row rather than overwriting each other.
`counting_source` records which publisher filled this half, per row -- a shared
row with no provenance is how a league ends up unable to say where a number
came from.

Two names are deliberately league-prefixed. `hits` and `saves` already exist for
the NHL, where they mean body checks and goaltender saves; a base hit and a
pitcher's save are different things that happen to share a word. `wins`,
`losses` and `shutouts` are NOT prefixed, because a pitcher's and a goaltender's
are the same idea.

Usage:
  cd backend && venv/bin/python migrate_mlb_counting_stats.py \\
      --db data/picks.dev.db [--apply]

Dry run by default. Idempotent and purely additive.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

BATTING_COLUMNS = {
    "pa": "INTEGER",          # the published qualifier's own unit
    "ab": "INTEGER",
    "mlb_hits": "INTEGER",    # `hits` is NHL body checks
    "runs": "INTEGER",
    "rbi": "INTEGER",
    "doubles": "INTEGER",
    "triples": "INTEGER",
    "bb": "INTEGER",
    "sb": "INTEGER",
    "obp": "REAL",
    "slg": "REAL",
    "ops": "REAL",
    "tb": "INTEGER",
}
PITCHING_COLUMNS = {
    "innings": "REAL",        # the published pitching qualifier's unit
    "era": "REAL",
    "whip": "REAL",
    "earned_runs": "INTEGER",
    "strikeouts": "INTEGER",
    "mlb_saves": "INTEGER",   # `saves` is an NHL goaltender's
    "wins": "INTEGER",        # shared with NHL: same idea
    "losses": "INTEGER",
    "shutouts": "INTEGER",
}
PROVENANCE_COLUMNS = {
    "counting_source": "TEXT",
}
NEW_COLUMNS = {**BATTING_COLUMNS, **PITCHING_COLUMNS, **PROVENANCE_COLUMNS}


def existing_columns(connection: sqlite3.Connection) -> set[str]:
    return {
        row[1] for row in connection.execute("PRAGMA table_info(player_stats)")
    }


def migrate(db_path: str, *, apply: bool) -> int:
    connection = sqlite3.connect(db_path)
    try:
        present = existing_columns(connection)
        missing = [name for name in NEW_COLUMNS if name not in present]
        if not missing:
            print("all columns already present -- nothing to do")
            return 0

        for stat_type in ("batting", "pitching"):
            count = connection.execute(
                "SELECT COUNT(*) FROM player_stats "
                "WHERE lower(league)='mlb' AND stat_type=?",
                (stat_type,),
            ).fetchone()[0]
            print(f"  {count} mlb {stat_type} rows waiting on these columns")
        for name in missing:
            print(f"  + {name} {NEW_COLUMNS[name]}")
        if not apply:
            print("\ndry run -- pass --apply to add them")
            return 0

        for name in missing:
            connection.execute(
                f"ALTER TABLE player_stats ADD COLUMN {name} {NEW_COLUMNS[name]}"
            )
        connection.commit()
        added = existing_columns(connection) - present
        print(f"\nadded {len(added)} columns: {', '.join(sorted(added))}")
        return 0
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=os.environ.get("LP_DB_PATH")
        or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "picks.db"),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    print(f"database: {args.db}")
    return migrate(args.db, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
