"""Observed reference data for E2 games, loaded once from the dev nfl_pbp table. Read-only.

The window is E1's: 2022-2025, weeks 1-18. The pool, the kickoff pool, the kick table and the participant lookup all
come from that window, so every draw in a game is from the same observed seasons.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
import game_state as gs  # noqa: E402
import measure_kick_outcomes as mk  # noqa: E402


def load_participants(db=e1.DEFAULT_DB):
    """{(game_id, play_id): (passer_player_id, rusher_player_id, receiver_player_id)} for the window's plays."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(f"""SELECT game_id, play_id, passer_player_id, rusher_player_id, receiver_player_id
FROM nfl_pbp WHERE {mk.WINDOW}""").fetchall()
    finally:
        con.close()
    return {(g, int(p)): (pa, ru, re_) for g, p, pa, ru, re_ in rows}


def load(db=e1.DEFAULT_DB):
    """Returns (Reference, excluded_kickoffs). Refuses a kick table whose buckets do not match the engine's."""
    rows = e1.load(db)
    pool, _ = e1.build_pool(rows)
    kpool, kex = gs.build_kickoff_pool(rows)
    kicks = mk.load_kick_table(db)
    if set(kicks['field_goal']) != set(gs.FG_BUCKETS):
        raise SystemExit(f"kick table buckets {sorted(kicks['field_goal'])} do not match {list(gs.FG_BUCKETS)}")
    return gs.Reference(pool, kpool, kicks, load_participants(db)), kex
