#!/usr/bin/env python3
"""
ingest_nfl_ngs_receiving.py — merge NFL Next Gen Stats receiving into NFL game logs.

Why this exists: routes run is the denominator the fantasy usage genre wants, and it is
PFF/paid. Estimating it (snap share x team pass plays) is unreliable for RB/TE because
blocking assignments mean on-field != running a route. NGS sidesteps the problem entirely
by shipping **air yards share** for free, which -- combined with the target share already
derivable from `targets` -- gives WOPR (1.5 x target share + 0.7 x air yards share), the
actual standard usage metric. No routes needed.

Unlike snap counts, NGS keys players by `player_gsis_id`, which `players.nfl_gsis_id`
already stores, so no PFR crosswalk is required.

Week 0 rows are season aggregates in the NGS feed and are skipped -- this table is
per-game.

Adds to each matched row's stats blob:
    air_yds_share, adot, separation, cushion, yac_above_exp

Usage: python3 ingest_nfl_ngs_receiving.py [--year 2025] [--dry-run]
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from typing import Optional

import nfl_data_py as nfl

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# NGS column -> key written into the stats JSON blob
NGS_FIELDS = {
    "percent_share_of_intended_air_yards": "air_yds_share",
    "avg_intended_air_yards": "adot",
    "avg_separation": "separation",
    "avg_cushion": "cushion",
    "avg_yac_above_expectation": "yac_above_exp",
}


def _load_ngs(year: int, artifact_path: Optional[str] = None):
    if artifact_path is None:
        print("  source: nfl_data_py import_ngs_data")
        return nfl.import_ngs_data("receiving", [year])

    artifact_path = os.path.abspath(artifact_path)
    if not os.path.isfile(artifact_path):
        raise RuntimeError(
            f"NGS artifact does not exist: {artifact_path}"
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


def _num(value):
    if value is None or value != value:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _replace_owned_values(
    con: sqlite3.Connection, year: int, pending: list
) -> None:
    paths = ", ".join(
        "'$.{}'".format(key) for key in NGS_FIELDS.values()
    )
    con.execute(
        "UPDATE player_game_logs SET stats=json_remove(stats, {}) "
        "WHERE league='nfl' AND season=?".format(paths),
        (year,),
    )
    for log_id, add in pending:
        con.execute(
            "UPDATE player_game_logs "
            "SET stats=json_patch(stats, ?) WHERE id=?",
            (json.dumps(add), log_id),
        )
    con.commit()


def ingest(
    year: int = 2025,
    dry_run: bool = False,
    artifact_path: Optional[str] = None,
) -> int:
    import warnings; warnings.filterwarnings("ignore")

    print(f"Loading NGS receiving {year}...")
    df = _load_ngs(year, artifact_path)
    needed = {"player_gsis_id", "week"} | set(NGS_FIELDS)
    missing = sorted(needed - set(df.columns))
    if missing:
        raise RuntimeError(
            f"NGS artifact is missing expected columns: {missing}"
        )
    if "season_type" in df.columns:
        df = df[df["season_type"] == "REG"]
    df = df[df["week"] > 0]  # week 0 = season aggregate, not a game
    print(f"  {len(df)} weekly NGS rows (REG)")

    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    gsis_to_player = {
        r["nfl_gsis_id"]: r["id"]
        for r in con.execute(
            "SELECT id, nfl_gsis_id FROM players "
            "WHERE league='nfl' AND nfl_gsis_id IS NOT NULL AND nfl_gsis_id != ''")
    }

    log_index = {}
    for r in con.execute(
            "SELECT id, player_id, game_no FROM player_game_logs "
            "WHERE league='nfl' AND season=? AND player_id IS NOT NULL", (year,)):
        try:
            log_index[(r["player_id"], int(r["game_no"]))] = r["id"]
        except (TypeError, ValueError):
            continue
    print(f"  {len(log_index)} existing {year} game logs to match against")

    pending = []
    no_gsis = no_log = 0
    seen = set()
    for row in df.itertuples(index=False):
        gsis = getattr(row, "player_gsis_id", None)
        pid = gsis_to_player.get(gsis) if isinstance(gsis, str) else None
        if pid is None:
            no_gsis += 1; continue
        try:
            week = int(getattr(row, "week"))
        except (TypeError, ValueError):
            continue
        natural_key = (gsis, week)
        if natural_key in seen:
            raise RuntimeError(
                f"NGS artifact has duplicate player/week {natural_key}"
            )
        seen.add(natural_key)
        log_id = log_index.get((pid, week))
        if log_id is None:
            no_log += 1; continue

        add = {}
        for src, key in NGS_FIELDS.items():
            v = getattr(row, src, None)
            value = _num(v)
            if value is not None:
                add[key] = value
        if add:
            pending.append((log_id, add))

    print(f"  matched {len(pending)} NGS rows "
          f"(skipped: {no_gsis} gsis not in spine, {no_log} no game log)")

    if dry_run:
        for log_id, add in pending[:5]:
            r = con.execute(
                "SELECT p.name, l.team, l.game_no FROM player_game_logs l "
                "LEFT JOIN players p ON p.id=l.player_id WHERE l.id=?", (log_id,)).fetchone()
            print(f"    DRY {r['name']} {r['team']} wk{r['game_no']} += {add}")
        con.close()
        return 0

    _replace_owned_values(con, year, pending)
    updated = len(pending)

    have = con.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE league='nfl' AND season=? "
        "AND json_extract(stats,'$.air_yds_share') IS NOT NULL", (year,)).fetchone()[0]
    print(f"  Updated {updated} rows; {have} {year} logs now carry air_yds_share")
    con.close()
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--artifact")
    arguments = parser.parse_args()
    ingest(
        arguments.year,
        dry_run=arguments.dry_run,
        artifact_path=arguments.artifact,
    )
