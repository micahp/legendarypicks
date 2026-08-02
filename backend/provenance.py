"""Where each row in this database actually came from — measured, not declared.

Written 2026-08-02, the day the NHL season-key split cost a league its
enablement. That bug is usually filed as a vocabulary mismatch. It is more
precisely a **provenance** bug: `team_game_results` is ESPN and
`player_game_logs` is nhle.com, the two publishers key seasons differently, and
nothing anywhere said so. Every surface treated the two tables as one corpus
because nothing recorded that they were not.

`team_stats_coverage.source` reads `reconcile_totals+espn_core_api`. That is the
provenance of the **verdict**, not of the data the verdict is about — which is
the specific confusion this module exists to end.

Measured 2026-08-02, `player_game_logs` alone carries seven publishers:

    mlb  statcast, statcast_pitcher      nfl  nflverse_weekly, nflverse_snap_counts
    nba  espn                            nhl  nhle.com
    ufc  espn_mma_stats                  wc   espn

and every one of them is reconciled against ESPN's published totals. Each is a
season-key, team-code and game-id vocabulary that has to be translated at its
own boundary (see `season_keys.py`, `team_codes.py`). A publisher this file does
not name is a boundary nobody has checked.

Two rules this module holds to
------------------------------
1. **A table with no source column reports `unrecorded`, never a guess.** It is
   tempting to write "team_game_results is obviously ESPN" — it is, today,
   because one script writes it. The moment a second one does, the guess is
   wrong and nothing says so. Presence of a plausible answer is not integrity.
2. **`derived` is not a publisher.** `player_stats` holds 580 NBA and 841 NHL
   rows sourced `derived` — values we computed. They are legitimate, and they
   must never be counted as published corroboration of themselves. Anything
   reconciling our numbers against an oracle has to exclude them or it is
   grading its own work.
"""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

# Sources that are OURS — computed here, not published anywhere. Reconciliation
# must never treat these as independent confirmation.
DERIVED_SOURCES = frozenset({"derived", "computed", "projection"})

# (table, league column, candidate timestamp columns in preference order).
#
# The season and source columns are deliberately NOT listed. The first draft of
# this file declared them — and said `team_game_results` had no source column,
# which was true for about forty minutes, until the column was added and this
# module went on reporting UNRECORDED over correctly-stamped rows. A hardcoded
# claim about a schema is a claim, and it decays exactly like the coverage rows
# this whole contract exists to distrust. Read the schema instead: PRAGMA
# table_info is one call and cannot go stale.
TRACKED = (
    ("player_game_logs", "league", ("ingested_at",)),
    ("player_stats", "league", ()),
    ("team_game_results", "league", ("ingested_at",)),
    ("team_game_stats", "league", ("captured_at",)),
)


def _columns(conn: sqlite3.Connection, table: str) -> set:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def sources_for(
    conn: sqlite3.Connection,
    league: Optional[str] = None,
    season=None,
) -> List[Dict]:
    """Row counts by (table, league, season, source). One row per distinct source.

    `source` is `None` for tables that do not record it — rendered as
    `unrecorded` by `format_provenance`, and that is a defect to fix, not a
    cosmetic gap.
    """
    out: List[Dict] = []
    for table, league_col, ts_candidates in TRACKED:
        cols = _columns(conn, table)
        if league_col not in cols:
            continue
        season_col = "season" if "season" in cols else None
        source_col = "source" if "source" in cols else None
        ts_col = next((c for c in ts_candidates if c in cols), None)

        select = [f"{league_col} AS lg"]
        group = [league_col]
        select.append(f"{season_col} AS sn" if season_col else "NULL AS sn")
        if season_col:
            group.append(season_col)
        select.append(f"{source_col} AS src" if source_col else "NULL AS src")
        if source_col:
            group.append(source_col)
        select.append("COUNT(*) AS n")
        if ts_col:
            select.append(f"MIN({ts_col}) AS first_seen")
            select.append(f"MAX({ts_col}) AS last_seen")
        else:
            select.append("NULL AS first_seen")
            select.append("NULL AS last_seen")

        where, args = [], []
        if league:
            where.append(f"{league_col}=?")
            args.append(league)
        if season is not None and season_col:
            where.append(f"{season_col}=?")
            args.append(season)
        clause = (" WHERE " + " AND ".join(where)) if where else ""

        sql = (
            f"SELECT {', '.join(select)} FROM {table}{clause}"
            f" GROUP BY {', '.join(group)}"
        )
        try:
            rows = conn.execute(sql, args).fetchall()
        except sqlite3.Error:
            continue
        for r in rows:
            out.append({
                "table": table,
                "league": r[0],
                "season": r[1],
                "source": r[2],
                "rows": r[3],
                "first_seen": r[4],
                "last_seen": r[5],
                "records_source": source_col is not None,
                "derived": str(r[2] or "").lower() in DERIVED_SOURCES,
            })
    return out


def publishers_for(conn: sqlite3.Connection, league: str, season=None) -> List[str]:
    """The distinct external publishers behind one league's rows.

    Excludes `derived`. More than one entry here is not a problem — it is the
    signal that more than one vocabulary is in play for this league, and that
    every join across those tables crosses a boundary.
    """
    seen = set()
    for row in sources_for(conn, league, season):
        if row["source"] and not row["derived"]:
            seen.add(row["source"])
    return sorted(seen)


def format_provenance(rows: List[Dict], indent: str = "  ") -> List[str]:
    """Human-readable lines, ordered so the unrecorded tables cannot be skimmed past."""
    lines: List[str] = []
    by_table: Dict[str, List[Dict]] = {}
    for r in rows:
        by_table.setdefault(r["table"], []).append(r)

    for table in sorted(by_table):
        entries = sorted(
            by_table[table],
            key=lambda r: (str(r["league"]), str(r["season"]), str(r["source"])),
        )
        lines.append(f"{indent}{table}")
        for e in entries:
            season = "-" if e["season"] in (None, "") else e["season"]
            if not e["records_source"]:
                src = "UNRECORDED — this table has no source column"
            elif e["source"] is None:
                src = "NULL — rows written without a source"
            else:
                src = e["source"] + ("  (ours, not published)" if e["derived"] else "")
            span = ""
            if e["first_seen"] and e["last_seen"]:
                span = f"  [{str(e['first_seen'])[:10]}..{str(e['last_seen'])[:10]}]"
            lines.append(
                f"{indent}  {str(e['league']):<5} {str(season):<9} "
                f"{e['rows']:>7} rows  {src}{span}"
            )
    return lines
