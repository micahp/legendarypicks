#!/usr/bin/env python3
"""What-if run: repeat the Weeks 2-9 backtest with the two lateral-play stat
lines restored, without touching the database or the committed artifacts.

Two 2026 player-weeks publish receiving yards with zero targets because the NFL
credits the yards (and any touchdown) to the player who ends the play after a
lateral. The weekly ingester drops the whole receiving key group when targets is
zero, so the database log carries no rec_yds for those rows and the grader reads
0. This runner patches only the in-memory History rows, then calls the committed
backtest runner unchanged and writes its outputs to a separate directory.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2] / "backend"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BACKEND))

import nfl_player_projection_v2 as engine
import run_prop_projection_backtest as runner

CORRECTIONS = (
    # (season, game_id, player_id, rec_yds, rec_td) from nflverse
    # stats_player_week_2026.parquet: receiving_yards/receiving_tds with targets == 0
    (2026, "2026_03_ARI_SF", 19487, 80.0, 1.0),   # Deebo Samuel Sr., 80-yd TD after lateral
    (2026, "2026_04_DAL_HOU", 15696, 19.0, 0.0),  # David Montgomery, 19-yd gain after lateral
)

_original_load = engine.History.load


def patched_load(con, seasons):
    hist = _original_load(con, seasons)
    applied = []
    for season, game_id, pid, yards, td in CORRECTIONS:
        row = next((r for r in hist.rows
                    if r.season == season and r.game_id == game_id and r.pid == pid), None)
        if row is None:
            raise SystemExit("correction target not found: %r" % ((game_id, pid),))
        applied.append({
            "game_id": game_id, "player_id": pid,
            "db_rec_yds": row.rec_yds, "corrected_rec_yds": yards,
            "db_rec_td": row.rec_td, "corrected_rec_td": td,
        })
        row.rec_yds, row.rec_td = yards, td
    engine.History.load = _original_load  # single use, so later callers see the raw rows
    print("applied corrections: " + json.dumps(applied), flush=True)
    return hist


def main():
    engine.History.load = patched_load
    out_dir = HERE / "impact-corrected-history"
    out_dir.mkdir(exist_ok=True)
    sys.argv = [sys.argv[0], "--out-dir", str(out_dir)]
    runner.main()


if __name__ == "__main__":
    main()
