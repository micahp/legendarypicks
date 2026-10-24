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


PLAY_EXTRAS = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'play_extras_2022_2025.csv'


def load_participants(db=e1.DEFAULT_DB, extras=PLAY_EXTRAS):
    """Observed play facts keyed by (game_id, play_id), for the window.

    From the dev table: passer, rusher and receiver ids, the posting team, air yards, and receiving yards. Yards after
    catch are derived as receiving yards minus air yards (labelled `derived` in the record; the curated table has no
    yards_after_catch). From the rebuilt play_extras CSV: timeout called (and by which team) and out_of_bounds. A play
    with no entry in the CSV has timeout 0 and out_of_bounds 0.
    """
    import csv
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(f"""SELECT game_id, play_id, passer_player_id, rusher_player_id, receiver_player_id,
posteam, air_yards, receiving_yards FROM nfl_pbp WHERE {mk.WINDOW}""").fetchall()
    finally:
        con.close()
    flags = {}
    with open(extras, newline='') as f:
        for r in csv.DictReader(f):
            flags[(r['game_id'], int(float(r['play_id'])))] = (int(r['timeout']), r['timeout_team'],
                                                                int(r['out_of_bounds']))
    out = {}
    for g, p, pa, ru, re_, posteam, air, rec_yds in rows:
        t, t_team, oob = flags.get((g, int(p)), (0, '', 0))
        yac = (rec_yds - air) if (rec_yds is not None and air is not None and re_) else None
        out[(g, int(p))] = {'passer_id': pa, 'rusher_id': ru, 'receiver_id': re_, 'posteam': posteam,
                            'air_yards': air, 'yards_after_catch': yac, 'timeout': t, 'timeout_team': t_team,
                            'out_of_bounds': oob}
    return out


def load(db=e1.DEFAULT_DB):
    """Returns (Reference, excluded_kickoffs). Refuses a kick table whose buckets do not match the engine's."""
    rows = e1.load(db)
    pool, _ = e1.build_pool(rows)
    kpool, kex = gs.build_kickoff_pool(rows)
    kicks = mk.load_kick_table(db)
    if set(kicks['field_goal']) != set(gs.FG_BUCKETS):
        raise SystemExit(f"kick table buckets {sorted(kicks['field_goal'])} do not match {list(gs.FG_BUCKETS)}")
    return gs.Reference(pool, kpool, kicks, load_participants(db)), kex
