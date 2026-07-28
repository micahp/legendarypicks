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
import sys
import os
import json
import sqlite3
import warnings

import nfl_data_py as nfl

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
    return out


def ingest(year: int = 2025, dry_run: bool = False) -> dict:
    """Run both paths: game-log enrichment + snap-counts table population.

    Returns counts: {updated_logs, inserted_snaps, ...}
    """

    warnings.filterwarnings("ignore")

    print(f"Loading nflverse snap counts {year}...")
    df = nfl.import_snap_counts([year])
    if "game_type" in df.columns:
        df = df[df["game_type"] == "REG"]
    print(f"  {len(df)} snap rows (REG)")

    crosswalk = _pfr_to_gsis()
    print(f"  {len(crosswalk)} pfr->gsis id pairs")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # ── Ensure tables exist ──────────────────────────────────────────────
    ensure_snap_table(con)

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
    for r in con.execute(
        "SELECT player_id, week FROM nfl_snap_counts WHERE season=?",
        (year,),
    ):
        existing_snap_keys.add((r["player_id"], r["week"]))

    updated = 0
    snap_inserted = 0
    snap_skipped = 0
    no_pfr = no_gsis = no_log = 0
    pending = []  # game-log patches
    snap_pending = []  # snap-counts table inserts

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

        team = getattr(row, "team", None)

        # ── Path 1: Game-log enrichment (skill players only) ──────────
        log_id = log_index.get((pid, week))
        if log_id is not None:
            add = {}
            for src, key in SNAP_FIELDS.items():
                v = getattr(row, src, None)
                if v is None or v != v:  # NaN
                    continue
                fv = float(v)
                add[key] = int(fv) if fv.is_integer() else round(fv, 3)
            if add:
                pending.append((log_id, add))
        else:
            no_log += 1

        # ── Path 2: Snap-counts table (ALL positions) ─────────────────
        if (pid, week) in existing_snap_keys:
            snap_skipped += 1
            continue

        snap_add = {"player_id": pid, "season": year, "week": week, "team": team}
        for src, col in SNAP_TABLE_COLS.items():
            v = getattr(row, src, None)
            if v is None or v != v:  # NaN
                continue
            fv = float(v)
            snap_add[col] = int(fv) if fv.is_integer() else round(fv, 3)
        snap_pending.append(snap_add)

    print(
        f"  matched {len(pending)} snap rows to game logs "
        f"(skipped: {no_pfr} unmapped pfr id, {no_gsis} not in spine, "
        f"{no_log} no game log)"
    )
    print(
        f"  snap-counts table: {len(snap_pending)} new rows, "
        f"{snap_skipped} already present"
    )

    if dry_run:
        for log_id, add in pending[:5]:
            r = con.execute(
                "SELECT p.name, l.team, l.game_no FROM player_game_logs l "
                "LEFT JOIN players p ON p.id=l.player_id WHERE l.id=?",
                (log_id,),
            ).fetchone()
            print(f"    DRY log-enrich  {r['name']} {r['team']} wk{r['game_no']} += {add}")
        for s in snap_pending[:5]:
            r = con.execute(
                "SELECT name FROM players WHERE id=?", (s["player_id"],)
            ).fetchone()
            name = r["name"] if r else "?"
            print(f"    DRY snap-table  {name} wk{s['week']} {s['team']}")
        con.close()
        return {
            "updated_logs": 0,
            "inserted_snaps": 0,
            "skipped_snaps": snap_skipped,
        }

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
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in SNAP_TABLE_COLS.values())
    insert_sql = (
        f"INSERT INTO nfl_snap_counts ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(player_id, season, week) DO UPDATE SET {set_clause}"
    )
    for s in snap_pending:
        values = tuple(s.get(c) for c in cols)
        con.execute(insert_sql, values)
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
    print(f"  Snap-counts table: {snap_total} rows for {year}")
    con.close()

    return {
        "updated_logs": updated,
        "inserted_snaps": snap_inserted,
        "skipped_snaps": snap_skipped,
    }


if __name__ == "__main__":
    year = 2025
    if "--year" in sys.argv:
        year = int(sys.argv[sys.argv.index("--year") + 1])
    ingest(year, dry_run="--dry-run" in sys.argv)
