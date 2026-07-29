#!/usr/bin/env python3
"""
ingest_nfl_snap_counts.py — nflverse snap counts → two targets.

1. **game-log enrichment** (existing): patches `off_snaps`/`off_pct` etc. into the
   `stats` JSON of rows that already exist in `player_game_logs`.  Only skill-position
   players have game logs, so this path skips linemen, defenders, and kickers
   (intentionally — this is a usage-metric merge, not a roster import).

2. **nfl_snap_counts table** (M2): writes EVERY snap row — all positions, all weeks —
   into its own table so availability (games played / weeks present) can answer "did
   this player dress" instead of "did this player touch the ball."

Usage:
    python3 ingest_nfl_snap_counts.py [--year 2025] [--dry-run]

Environment:
    LP_DB_PATH — the sqlite database (default: backend/data/picks.db)
"""
import argparse
import hashlib
import sys
import os
import json
import sqlite3
import warnings
from typing import Optional

import nfl_data_py as nfl

from team_codes import normalize_optional

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

# nflverse snap column -> key written into the stats JSON blob
SNAP_FIELDS = {
    "offense_snaps": "off_snaps",
    "offense_pct": "off_pct",
    "defense_snaps": "def_snaps",
    "defense_pct": "def_pct",
    "st_snaps": "st_snaps",
    "st_pct": "st_pct",
}

# nflverse snap column -> column in nfl_snap_counts table
SNAP_TABLE_COLS = {
    "offense_snaps": "off_snaps",
    "offense_pct": "off_pct",
    "defense_snaps": "def_snaps",
    "defense_pct": "def_pct",
    "st_snaps": "st_snaps",
    "st_pct": "st_pct",
}

# dynastyprocess currently assigns the offensive lineman's PFR id to the
# defensive Jonah Williams.  PFR's own player pages identify WillJo10 as the
# Arizona OL and WillJo16 as the New Orleans DE; nflverse rosters publish their
# GSIS ids.  Keep the reviewed stable-id correction at the ingest boundary so
# the wrong player's availability is never silently patched.
_PFR_TO_GSIS_OVERRIDES = {
    "WillJo10": "00-0035629",
    "WillJo16": "00-0035944",
}


def ensure_snap_table(con: sqlite3.Connection) -> None:
    """Create nfl_snap_counts (M2 — availability from presence, not stats)."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS nfl_snap_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            week INTEGER NOT NULL,
            team TEXT,
            off_snaps INTEGER,
            off_pct REAL,
            def_snaps INTEGER,
            def_pct REAL,
            st_snaps INTEGER,
            st_pct REAL,
            UNIQUE(player_id, season, week)
        )""")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_nsc_player_season "
        "ON nfl_snap_counts(player_id, season)"
    )


def _pfr_to_gsis():
    """Crosswalk PFR player ids -> GSIS ids. nflverse ships both in one id table."""

    ids = nfl.import_ids()
    out = {}
    for pfr, gsis in zip(ids.get("pfr_id"), ids.get("gsis_id")):
        if isinstance(pfr, str) and pfr and isinstance(gsis, str) and gsis:
            out[pfr] = gsis
    out.update(_PFR_TO_GSIS_OVERRIDES)
    return out


def _load_snap_counts(
    year: int, artifact_path: Optional[str] = None
):
    if artifact_path is None:
        print("  source: nfl_data_py import_snap_counts")
        return nfl.import_snap_counts([year])

    artifact_path = os.path.abspath(artifact_path)
    if not os.path.isfile(artifact_path):
        raise RuntimeError(
            f"snap-count artifact does not exist: {artifact_path}"
        )
    with open(artifact_path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    print(
        f"  artifact: {artifact_path} "
        f"({os.path.getsize(artifact_path)} bytes)"
    )
    print(f"  sha256  : {digest}")
    import pandas as pd

    frame = pd.read_parquet(artifact_path)
    if "season" in frame.columns:
        frame = frame[frame["season"] == year]
    return frame


def ingest(
    year: int = 2025,
    dry_run: bool = False,
    artifact_path: Optional[str] = None,
) -> dict:
    """Run both paths: game-log enrichment + snap-counts table population.

    Returns counts: {updated_logs, inserted_snaps, ...}
    """

    warnings.filterwarnings("ignore")

    print(f"Loading nflverse snap counts {year}...")
    df = _load_snap_counts(year, artifact_path)
    if "game_type" in df.columns:
        df = df[df["game_type"] == "REG"]
    print(f"  {len(df)} snap rows (REG)")

    crosswalk = _pfr_to_gsis()
    print(f"  {len(crosswalk)} pfr->gsis id pairs")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # A dry run is read-only, including on a legacy database where this table
    # does not exist yet. Creating the table/index merely to report a plan
    # violates the command's contract and dirties the production candidate.
    snap_table_exists = con.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='nfl_snap_counts'"
    ).fetchone() is not None
    if not dry_run:
        ensure_snap_table(con)
        snap_table_exists = True

    gsis_to_player = {
        r["nfl_gsis_id"]: r["id"]
        for r in con.execute(
            "SELECT id, nfl_gsis_id FROM players "
            "WHERE league='nfl' AND nfl_gsis_id IS NOT NULL AND nfl_gsis_id != ''"
        )
    }
    print(f"  {len(gsis_to_player)} gsis-resolved players in spine")

    # (player_id, week) -> game log id
    log_index = {}
    for r in con.execute(
        "SELECT id, player_id, game_no FROM player_game_logs "
        "WHERE league='nfl' AND season=? AND player_id IS NOT NULL",
        (year,),
    ):
        try:
            log_index[(r["player_id"], int(r["game_no"]))] = r["id"]
        except (TypeError, ValueError):
            continue
    print(f"  {len(log_index)} existing {year} game logs to match against")

    # ── Count existing snap rows so we can report new-vs-skipped ─────────
    existing_snap_keys = set()
    if snap_table_exists:
        for r in con.execute(
            "SELECT player_id, week FROM nfl_snap_counts WHERE season=?",
            (year,),
        ):
            existing_snap_keys.add((r["player_id"], r["week"]))

    updated = 0
    snap_inserted = 0
    snap_updated = 0
    no_pfr = no_gsis = no_log = 0
    pending = []  # game-log patches
    snap_pending = []  # (snap-count record, existing key)

    for row in df.itertuples(index=False):
        pfr = getattr(row, "pfr_player_id", None)
        if not isinstance(pfr, str) or not pfr:
            no_pfr += 1
            continue
        gsis = crosswalk.get(pfr)
        if not gsis:
            no_pfr += 1
            continue
        pid = gsis_to_player.get(gsis)
        if pid is None:
            no_gsis += 1
            continue
        try:
            week = int(getattr(row, "week"))
        except (TypeError, ValueError):
            continue

        raw_team = getattr(row, "team", None)
        if raw_team is not None and raw_team == raw_team:
            team = normalize_optional("nfl", str(raw_team))
        else:
            team = None

        # ── Path 1: Game-log enrichment (skill players only) ──────────
        log_id = log_index.get((pid, week))
        if log_id is not None:
            add = {}
            for src, key in SNAP_FIELDS.items():
                v = getattr(row, src, None)
                if v is None or v != v:  # NaN
                    continue
                fv = float(v)
                add[key] = int(fv) if fv.is_integer() else fv
            if add:
                pending.append((log_id, add))
        else:
            no_log += 1

        # ── Path 2: Snap-counts table (ALL positions) ─────────────────
        snap_add = {"player_id": pid, "season": year, "week": week, "team": team}
        for src, col in SNAP_TABLE_COLS.items():
            v = getattr(row, src, None)
            if v is None or v != v:  # NaN
                continue
            fv = float(v)
            snap_add[col] = int(fv) if fv.is_integer() else fv
        snap_pending.append((snap_add, (pid, week) in existing_snap_keys))

    print(
        f"  matched {len(pending)} snap rows to game logs "
        f"(skipped: {no_pfr} unmapped pfr id, {no_gsis} not in spine, "
        f"{no_log} no game log)"
    )
    print(
        f"  snap-counts table: "
        f"{sum(not exists for _, exists in snap_pending)} new rows, "
        f"{sum(exists for _, exists in snap_pending)} existing rows to refresh"
    )

    if dry_run:
        for log_id, add in pending[:5]:
            r = con.execute(
                "SELECT p.name, l.team, l.game_no FROM player_game_logs l "
                "LEFT JOIN players p ON p.id=l.player_id WHERE l.id=?",
                (log_id,),
            ).fetchone()
            print(f"    DRY log-enrich  {r['name']} {r['team']} wk{r['game_no']} += {add}")
        for s, exists in snap_pending[:5]:
            r = con.execute(
                "SELECT name FROM players WHERE id=?", (s["player_id"],)
            ).fetchone()
            name = r["name"] if r else "?"
            action = "refresh" if exists else "insert"
            print(
                f"    DRY snap-table  {action} {name} "
                f"wk{s['week']} {s['team']}"
            )
        con.close()
        return {
            "updated_logs": 0,
            "inserted_snaps": 0,
            "updated_snaps": 0,
            "deleted_stale_snaps": 0,
        }

    # ── Synchronize the published snapshot ───────────────────────────────
    # Upsert alone leaves facts that disappeared or were previously attached
    # through a bad identity crosswalk. Remove only this ingest's owned fields,
    # then repopulate them from the current artifact; NGS and box-score keys
    # remain untouched.
    con.execute(
        """UPDATE player_game_logs
           SET stats=json_remove(
               stats,
               '$.off_snaps', '$.off_pct',
               '$.def_snaps', '$.def_pct',
               '$.st_snaps', '$.st_pct'
           )
           WHERE league='nfl' AND season=?""",
        (year,),
    )

    resolved_snap_keys = {
        (snap["player_id"], snap["week"]) for snap, _ in snap_pending
    }
    stale_snap_keys = existing_snap_keys - resolved_snap_keys
    con.executemany(
        "DELETE FROM nfl_snap_counts "
        "WHERE player_id=? AND season=? AND week=?",
        [(player_id, year, week) for player_id, week in stale_snap_keys],
    )

    # ── Apply game-log patches ───────────────────────────────────────────
    for log_id, add in pending:
        con.execute(
            "UPDATE player_game_logs SET stats = json_patch(stats, ?) WHERE id=?",
            (json.dumps(add), log_id),
        )
        updated += 1

    # ── Insert snap-count rows ───────────────────────────────────────────
    cols = ["player_id", "season", "week", "team"] + list(SNAP_TABLE_COLS.values())
    placeholders = ", ".join("?" for _ in cols)
    update_cols = ["team"] + list(SNAP_TABLE_COLS.values())
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
    insert_sql = (
        f"INSERT INTO nfl_snap_counts ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(player_id, season, week) DO UPDATE SET {set_clause}"
    )
    for s, exists in snap_pending:
        values = tuple(s.get(c) for c in cols)
        con.execute(insert_sql, values)
        if exists:
            snap_updated += 1
        else:
            snap_inserted += 1

    con.commit()

    have = con.execute(
        "SELECT COUNT(*) FROM player_game_logs "
        "WHERE league='nfl' AND season=? AND json_extract(stats,'$.off_snaps') IS NOT NULL",
        (year,),
    ).fetchone()[0]
    snap_total = con.execute(
        "SELECT COUNT(*) FROM nfl_snap_counts WHERE season=?", (year,)
    ).fetchone()[0]

    print(f"  Updated {updated} game logs; {have} {year} logs now carry off_snaps")
    print(
        f"  Snap-counts table: {snap_total} rows for {year} "
        f"({snap_inserted} inserted, {snap_updated} refreshed, "
        f"{len(stale_snap_keys)} stale removed)"
    )
    con.close()

    return {
        "updated_logs": updated,
        "inserted_snaps": snap_inserted,
        "updated_snaps": snap_updated,
        "deleted_stale_snaps": len(stale_snap_keys),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--artifact",
        help=(
            "local nflverse snap-count parquet; prints sha256 and "
            "avoids a moving network fetch"
        ),
    )
    arguments = parser.parse_args()
    ingest(
        arguments.year,
        dry_run=arguments.dry_run,
        artifact_path=arguments.artifact,
    )
