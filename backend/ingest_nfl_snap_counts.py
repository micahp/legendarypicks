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
from datetime import datetime, timezone
import hashlib
import sys
import os
import json
import sqlite3
import time
import urllib.request
import warnings
from typing import Optional

import nfl_data_py as nfl

from team_codes import normalize_optional

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
SOURCE = "nflverse_snap_counts"
PLAYERS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "players/players.parquet"
)
CACHE_MAX_AGE_S = 6 * 60 * 60

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


def ensure_unresolved_table(con: sqlite3.Connection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS unresolved_players(
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             source TEXT NOT NULL, raw_name TEXT NOT NULL,
             league TEXT NOT NULL, team TEXT, first_seen TEXT NOT NULL,
             count INTEGER DEFAULT 1, source_player_key TEXT, reason TEXT
           )"""
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_unresolved_players_source_key "
        "ON unresolved_players(source,league,source_player_key)"
    )


def _pfr_to_gsis(ids):
    """Crosswalk PFR player ids -> GSIS ids. nflverse ships both in one id table."""

    out = {}
    for pfr, gsis in zip(ids.get("pfr_id"), ids.get("gsis_id")):
        if isinstance(pfr, str) and pfr and isinstance(gsis, str) and gsis:
            out[pfr] = gsis
    out.update(_PFR_TO_GSIS_OVERRIDES)
    return out


def _gsis_to_espn(ids):
    """Crosswalk GSIS ids to ESPN ids without using a player name."""
    out = {}
    for gsis, espn in zip(ids.get("gsis_id"), ids.get("espn_id")):
        if not isinstance(gsis, str) or not gsis or espn is None or espn != espn:
            continue
        value = str(espn).strip()
        if value:
            out[gsis] = str(int(float(value))) if value.replace(".", "", 1).isdigit() else value
    return out


def _load_identity_ids(
    cache_dir: str = "/tmp",
    artifact_path: Optional[str] = None,
    refresh: bool = False,
):
    """Load nflverse's current player file, which owns PFR/GSIS/ESPN ids.

    The prior dynastyprocess crosswalk omitted 1,110 of 5,970 current-season
    snap rows. The publisher's current players artifact misses only identities
    it genuinely has not crosswalked, and its checksum makes the run auditable.
    """
    path = os.path.abspath(
        artifact_path or os.path.join(cache_dir, "nflverse_players.parquet")
    )
    if artifact_path is None and (
        refresh
        or not os.path.exists(path)
        or time.time() - os.path.getmtime(path) > CACHE_MAX_AGE_S
    ):
        urllib.request.urlretrieve(PLAYERS_URL, path)
    if not os.path.isfile(path):
        raise RuntimeError(f"identity artifact does not exist: {path}")
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    print(f"  identity artifact: {path} ({os.path.getsize(path)} bytes)")
    print(f"  identity sha256  : {digest}")
    import pandas as pd

    return pd.read_parquet(path, columns=["pfr_id", "gsis_id", "espn_id"])


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
    identity_artifact_path: Optional[str] = None,
    cache_dir: str = "/tmp",
    refresh: bool = False,
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

    source_ids = _load_identity_ids(
        cache_dir=cache_dir,
        artifact_path=identity_artifact_path,
        refresh=refresh,
    )
    crosswalk = _pfr_to_gsis(source_ids)
    gsis_to_espn = _gsis_to_espn(source_ids)
    print(
        f"  {len(crosswalk)} pfr->gsis and "
        f"{len(gsis_to_espn)} gsis->espn id pairs"
    )

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
        ensure_unresolved_table(con)
        snap_table_exists = True

    gsis_to_player = {
        r["nfl_gsis_id"]: r["id"]
        for r in con.execute(
            "SELECT id, nfl_gsis_id FROM players "
            "WHERE league='nfl' AND nfl_gsis_id IS NOT NULL AND nfl_gsis_id != ''"
        )
    }
    espn_owners = {}
    for r in con.execute(
        "SELECT id, espn_id FROM players "
        "WHERE league='nfl' AND espn_id IS NOT NULL AND espn_id != ''"
    ):
        espn_owners.setdefault(str(r["espn_id"]), set()).add(r["id"])
    espn_to_player = {
        key: next(iter(owners))
        for key, owners in espn_owners.items()
        if len(owners) == 1
    }
    print(
        f"  {len(gsis_to_player)} direct GSIS and "
        f"{len(espn_to_player)} unique ESPN owners in spine"
    )

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
    no_pfr = no_gsis = bad_week = no_log = via_espn = 0
    pending = []  # game-log patches
    snap_pending = []  # (snap-count record, existing key)
    unresolved = {}
    resolved_source_keys = set()

    def note_unresolved(source_key, row, reason):
        key = str(source_key) if source_key else str(getattr(row, "player", "unknown"))
        raw_team = getattr(row, "team", None)
        team = (
            normalize_optional("nfl", str(raw_team))
            if raw_team is not None and raw_team == raw_team
            else None
        )
        item = unresolved.setdefault(key, {
            "name": str(getattr(row, "player", "") or key),
            "team": team,
            "reason": reason,
            "count": 0,
        })
        item["count"] += 1

    for row in df.itertuples(index=False):
        pfr = getattr(row, "pfr_player_id", None)
        if not isinstance(pfr, str) or not pfr:
            no_pfr += 1
            note_unresolved(pfr, row, "snap row has no stable PFR id")
            continue
        gsis = crosswalk.get(pfr)
        if not gsis:
            no_pfr += 1
            note_unresolved(
                pfr, row, "PFR id absent from nflverse player crosswalk"
            )
            continue
        pid = gsis_to_player.get(gsis)
        if pid is None:
            pid = espn_to_player.get(gsis_to_espn.get(gsis))
            if pid is not None:
                via_espn += 1
        if pid is None:
            no_gsis += 1
            note_unresolved(
                gsis, row, "no canonical owner for published GSIS id"
            )
            continue
        try:
            week = int(getattr(row, "week"))
        except (TypeError, ValueError):
            bad_week += 1
            note_unresolved(gsis, row, "snap row has no valid published week")
            continue
        resolved_source_keys.update((pfr, gsis))

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

    accounted = len(snap_pending) + no_pfr + no_gsis + bad_week
    if accounted != len(df):
        raise RuntimeError(
            f"snap source reconciliation failed: {len(df)} source rows != "
            f"{len(snap_pending)} resolved + {no_pfr + no_gsis + bad_week} unresolved"
        )
    resolved_keys = [(snap["player_id"], snap["week"]) for snap, _ in snap_pending]
    if len(resolved_keys) != len(set(resolved_keys)):
        raise RuntimeError("multiple snap source rows resolved to one player/week key")

    print(
        f"  matched {len(pending)} snap rows to game logs "
        f"(skipped: {no_pfr} unmapped pfr id, {no_gsis} not in spine, "
        f"{bad_week} invalid week, {no_log} no game log; "
        f"{via_espn} resolved through GSIS->ESPN)"
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
            "source_rows": len(df),
            "resolved_snap_rows": len(snap_pending),
            "unresolved_snap_rows": no_pfr + no_gsis + bad_week,
            "unresolved_snap_ids": len(unresolved),
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
    if resolved_source_keys:
        placeholders = ",".join("?" for _ in resolved_source_keys)
        con.execute(
            "DELETE FROM unresolved_players WHERE source=? AND league='nfl' "
            f"AND source_player_key IN ({placeholders})",
            [SOURCE] + sorted(resolved_source_keys),
        )
    now = datetime.now(timezone.utc).isoformat()
    for source_key, item in unresolved.items():
        existing = con.execute(
            """SELECT id FROM unresolved_players
               WHERE source=? AND league='nfl' AND source_player_key=?""",
            (SOURCE, source_key),
        ).fetchone()
        values = (
            item["name"], item["team"], item["count"], item["reason"]
        )
        if existing:
            con.execute(
                """UPDATE unresolved_players
                   SET raw_name=?,team=?,count=?,reason=? WHERE id=?""",
                values + (existing[0],),
            )
        else:
            con.execute(
                """INSERT INTO unresolved_players(
                     source,raw_name,league,team,first_seen,count,
                     source_player_key,reason
                   ) VALUES(?,?,'nfl',?,?,?,?,?)""",
                (SOURCE, item["name"], item["team"], now, item["count"],
                 source_key, item["reason"]),
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

    have = con.execute(
        "SELECT COUNT(*) FROM player_game_logs "
        "WHERE league='nfl' AND season=? AND json_extract(stats,'$.off_snaps') IS NOT NULL",
        (year,),
    ).fetchone()[0]
    snap_total = con.execute(
        "SELECT COUNT(*) FROM nfl_snap_counts WHERE season=?", (year,)
    ).fetchone()[0]
    if snap_total != len(resolved_snap_keys):
        con.rollback()
        con.close()
        raise RuntimeError(
            f"snap target reconciliation failed: {snap_total} stored rows != "
            f"{len(resolved_snap_keys)} resolved publisher rows"
        )
    con.commit()

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
        "source_rows": len(df),
        "resolved_snap_rows": len(snap_pending),
        "unresolved_snap_rows": no_pfr + no_gsis + bad_week,
        "unresolved_snap_ids": len(unresolved),
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
    parser.add_argument("--identity-artifact", help="pinned nflverse players parquet")
    parser.add_argument("--cache-dir", default="/tmp")
    parser.add_argument("--refresh", action="store_true")
    arguments = parser.parse_args()
    ingest(
        arguments.year,
        dry_run=arguments.dry_run,
        artifact_path=arguments.artifact,
        identity_artifact_path=arguments.identity_artifact,
        cache_dir=arguments.cache_dir,
        refresh=arguments.refresh,
    )
