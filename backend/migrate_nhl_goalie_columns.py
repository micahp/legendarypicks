"""One-shot: give `player_stats` the columns hockey's other two player types need.

Hockey has three player types and this table only ever had columns for one of
them. `goals`, `assists`, `points_nhl`, `shots`, `shooting_pct`, `faceoff_pct`
describe a forward. A defenceman's actual job -- blocked shots and hits -- had
nowhere to live, and a goaltender had nowhere at all: every goalie row in the
database reads 0 goals, 0 assists, 0 shots, which is a goalie described
entirely by things goalies do not do.

That is the whole of the "no goalie has ever recorded a save" gap in
`docs/LEAGUE-STAT-GAPS.md`. It was never a missing publisher. nhle.com
publishes all of it, league-wide, and has the entire time:

  goalie/summary    saves, shotsAgainst, goalsAgainst, savePct,
                    goalsAgainstAverage, shutouts, wins, losses, otLosses,
                    gamesStarted        -- 98 goalies in one request
  skater/realtime   blockedShots, hits, takeaways, giveaways
                    -- 940 skaters in one request

`saves` is published directly, so nothing here is derived from
shotsAgainst - goalsAgainst.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db \\
      venv/bin/python migrate_nhl_goalie_columns.py [--apply]

Dry run by default. Idempotent -- ADD COLUMN is skipped for any column already
present, so a second --apply run reports zero additions. Purely additive: no
existing column is read, written, or dropped, so it cannot disturb a row.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

# Column -> why it exists, so the next person does not have to guess which
# player type each one serves.
GOALIE_COLUMNS = {
    "saves": "INTEGER",
    "shots_against": "INTEGER",
    "goals_against": "INTEGER",
    "save_pct": "REAL",
    "gaa": "REAL",
    "shutouts": "INTEGER",
    "wins": "INTEGER",
    "losses": "INTEGER",
    "ot_losses": "INTEGER",
    "games_started": "INTEGER",
}
DEFENCE_COLUMNS = {
    "blocked_shots": "INTEGER",
    "hits": "INTEGER",
    "takeaways": "INTEGER",
    "giveaways": "INTEGER",
}
NEW_COLUMNS = {**DEFENCE_COLUMNS, **GOALIE_COLUMNS}


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

        goalies = connection.execute(
            """SELECT COUNT(*) FROM player_stats
               WHERE lower(league)='nhl' AND upper(COALESCE(nhl_position,''))='G'"""
        ).fetchone()[0]
        defence = connection.execute(
            """SELECT COUNT(*) FROM player_stats
               WHERE lower(league)='nhl' AND upper(COALESCE(nhl_position,''))='D'"""
        ).fetchone()[0]
        print(f"player_stats rows waiting on these columns: "
              f"{goalies} goalies, {defence} defencemen")
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
