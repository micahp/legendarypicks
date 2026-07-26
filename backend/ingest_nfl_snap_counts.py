#!/usr/bin/env python3
"""
ingest_nfl_snap_counts.py — merge nflverse snap counts into existing NFL game logs.

Snap counts are the missing half of usage analysis: `player_game_logs` already carries
`targets`/`carries` (opportunity taken) but not snaps (opportunity available). Without
snaps you cannot compute snap share, and target-per-snap rates are the metrics the weekly
fantasy usage-report genre is built on.

Two identity frictions this script resolves:
  * nflverse snap counts key players by `pfr_player_id`; `players` stores `nfl_gsis_id`.
    `nfl.import_ids()` carries both, so it is used as the crosswalk.
  * 2024 rows (source `nflverse`) have no `game_id`, only `game_no`. 2025 rows have both.
    So the join is on (player_id, season, week) which is uniform across both seasons.

This UPDATEs the `stats` JSON of rows that already exist; it never inserts. Offensive
linemen and most defenders have snap rows but no game log (no targets/carries/attempts),
and they are intentionally skipped -- this is a usage-metric merge, not a roster import.

Adds to each matched row's stats blob:
    off_snaps, off_pct, def_snaps, def_pct, st_snaps, st_pct

Usage: python3 ingest_nfl_snap_counts.py [--year 2025] [--dry-run]
"""
import sys, os, json, sqlite3

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# nflverse snap column -> key written into the stats JSON blob
SNAP_FIELDS = {
    "offense_snaps": "off_snaps", "offense_pct": "off_pct",
    "defense_snaps": "def_snaps", "defense_pct": "def_pct",
    "st_snaps": "st_snaps", "st_pct": "st_pct",
}


def _pfr_to_gsis() -> dict:
    """Crosswalk PFR player ids -> GSIS ids. nflverse ships both in one id table."""
    import nfl_data_py as nfl
    ids = nfl.import_ids()
    out = {}
    for pfr, gsis in zip(ids.get("pfr_id"), ids.get("gsis_id")):
        if isinstance(pfr, str) and pfr and isinstance(gsis, str) and gsis:
            out[pfr] = gsis
    return out


def ingest(year: int = 2025, dry_run: bool = False) -> int:
    import warnings; warnings.filterwarnings("ignore")
    import nfl_data_py as nfl

    print(f"Loading nflverse snap counts {year}...")
    df = nfl.import_snap_counts([year])
    if "game_type" in df.columns:
        df = df[df["game_type"] == "REG"]
    print(f"  {len(df)} snap rows (REG)")

    crosswalk = _pfr_to_gsis()
    print(f"  {len(crosswalk)} pfr->gsis id pairs")

    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    gsis_to_player = {
        r["nfl_gsis_id"]: r["id"]
        for r in con.execute(
            "SELECT id, nfl_gsis_id FROM players "
            "WHERE league='nfl' AND nfl_gsis_id IS NOT NULL AND nfl_gsis_id != ''")
    }
    print(f"  {len(gsis_to_player)} gsis-resolved players in spine")

    # (player_id, week) -> game log id, so a snap row can find the row it belongs to.
    # 2024 logs have no game_id, so week is the only shared game key across seasons.
    log_index = {}
    for r in con.execute(
            "SELECT id, player_id, game_no FROM player_game_logs "
            "WHERE league='nfl' AND season=? AND player_id IS NOT NULL", (year,)):
        try:
            log_index[(r["player_id"], int(r["game_no"]))] = r["id"]
        except (TypeError, ValueError):
            continue
    print(f"  {len(log_index)} existing {year} game logs to match against")

    updated = no_pfr = no_gsis = no_log = 0
    pending = []
    for row in df.itertuples(index=False):
        pfr = getattr(row, "pfr_player_id", None)
        if not isinstance(pfr, str) or not pfr:
            no_pfr += 1; continue
        gsis = crosswalk.get(pfr)
        if not gsis:
            no_pfr += 1; continue
        pid = gsis_to_player.get(gsis)
        if pid is None:
            no_gsis += 1; continue
        try:
            week = int(getattr(row, "week"))
        except (TypeError, ValueError):
            continue
        log_id = log_index.get((pid, week))
        if log_id is None:
            # OL/DL and inactive skill players: snap row exists, no game log. Expected.
            no_log += 1; continue

        add = {}
        for src, key in SNAP_FIELDS.items():
            v = getattr(row, src, None)
            if v is None or v != v:  # NaN
                continue
            fv = float(v)
            add[key] = int(fv) if fv.is_integer() else round(fv, 3)
        if not add:
            continue
        pending.append((log_id, add))

    print(f"  matched {len(pending)} snap rows to game logs "
          f"(skipped: {no_pfr} unmapped pfr id, {no_gsis} not in spine, {no_log} no game log)")

    if dry_run:
        for log_id, add in pending[:5]:
            r = con.execute(
                "SELECT p.name, l.team, l.game_no FROM player_game_logs l "
                "LEFT JOIN players p ON p.id=l.player_id WHERE l.id=?", (log_id,)).fetchone()
            print(f"    DRY {r['name']} {r['team']} wk{r['game_no']} += {add}")
        con.close()
        return 0

    # json_patch merges the new keys without disturbing existing ones, so this is
    # safe to re-run and never clobbers targets/carries/yards already present.
    for log_id, add in pending:
        con.execute(
            "UPDATE player_game_logs SET stats = json_patch(stats, ?) WHERE id=?",
            (json.dumps(add), log_id))
        updated += 1
    con.commit()

    have = con.execute(
        "SELECT COUNT(*) FROM player_game_logs "
        "WHERE league='nfl' AND season=? AND json_extract(stats,'$.off_snaps') IS NOT NULL",
        (year,)).fetchone()[0]
    print(f"  Updated {updated} rows; {have} {year} logs now carry off_snaps")
    con.close()
    return updated


if __name__ == "__main__":
    year = 2025
    if "--year" in sys.argv:
        year = int(sys.argv[sys.argv.index("--year") + 1])
    ingest(year, dry_run="--dry-run" in sys.argv)
