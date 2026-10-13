#!/usr/bin/env python3
"""Remove only empty, unattributed MLB ``team_game_stats`` residue.

MLB aggregates intentionally use ``team_game_results`` and do not consume this
table. Dry-run is the default. ``--apply`` refuses the whole operation if even
one MLB row contains a stat, JSON payload, run id, source, or unknown column.
"""
import os
import sqlite3
import sys


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

_IDENTITY_COLUMNS = {
    "league", "game_id", "captured_at", "team_abbrev", "home_away",
}
_PROVENANCE_COLUMNS = {"run_id", "source"}


def cleanup(con: sqlite3.Connection, apply: bool = False) -> dict:
    con.row_factory = sqlite3.Row
    columns = [row[1] for row in con.execute("PRAGMA table_info(team_game_stats)")]
    protected = _IDENTITY_COLUMNS | _PROVENANCE_COLUMNS
    value_columns = [column for column in columns if column not in protected]
    rows = con.execute(
        "SELECT rowid AS _rowid, * FROM team_game_stats WHERE league='mlb'"
    ).fetchall()

    empty = []
    nonempty = []
    for row in rows:
        meaningful = []
        for column in value_columns + [c for c in _PROVENANCE_COLUMNS if c in columns]:
            value = row[column]
            if value is None:
                continue
            if isinstance(value, str) and value.strip() in ("", "{}"):
                continue
            meaningful.append(column)
        (nonempty if meaningful else empty).append((row["_rowid"], meaningful))

    result = {
        "mlb_rows": len(rows),
        "empty_rows": len(empty),
        "nonempty_rows": len(nonempty),
        "deleted": 0,
    }
    if apply:
        if nonempty:
            raise ValueError(
                "refusing MLB team_game_stats cleanup: nonempty rows exist: "
                + repr(nonempty[:5]))
        if empty:
            rowids = [rowid for rowid, _columns in empty]
            placeholders = ",".join("?" for _ in rowids)
            result["deleted"] = con.execute(
                f"DELETE FROM team_game_stats WHERE rowid IN ({placeholders})",
                rowids,
            ).rowcount
            con.commit()
    return result


def main() -> int:
    apply = "--apply" in sys.argv
    con = sqlite3.connect(DB)
    try:
        result = cleanup(con, apply=apply)
    except (sqlite3.Error, ValueError) as exc:
        con.rollback()
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    finally:
        con.close()
    print("Empty MLB team_game_stats cleanup" + (" [APPLY]" if apply else " [DRY RUN]"))
    for key, value in result.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
