"""Freeze workload query results and player positions in one SQLite read transaction."""
import argparse
import gzip
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

import evaluate_workload_calibration as ev
import player_shares as ps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--through-season', type=int, required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    try:
        con.execute('BEGIN')
        games = {str(year): {role: ev.load_games(con, year, role)
                             for role in ev.ROLES}
                 for year in range(ps.FIRST_SEASON, args.through_season + 1)}
        rows = con.execute("SELECT nfl_gsis_id, MIN(position) FROM players WHERE lower(league)='nfl' "
                           "AND nfl_gsis_id IS NOT NULL AND position IS NOT NULL GROUP BY nfl_gsis_id").fetchall()
        positions = dict(sorted(rows))
    finally:
        con.close()
    result = {'schema': 'lp.workload.evaluation-inputs.v1', 'source_database': args.db,
              'source_is_mutable': True, 'first_season': ps.FIRST_SEASON,
              'through_season': args.through_season, 'games': games, 'positions': positions,
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'queries': {'games': 'evaluate_workload_calibration.load_games grouped player opportunities by team/game/week',
                          'positions': 'players: MIN(position) by nfl_gsis_id, nfl league'}}
    data = json.dumps(result, sort_keys=True, separators=(',', ':')).encode()
    compressed = gzip.compress(data, mtime=0)
    Path(args.out).write_bytes(compressed)
    print(json.dumps({'path': args.out, 'sha256': hashlib.sha256(compressed).hexdigest(),
                      'uncompressed_sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(compressed)}))

if __name__ == '__main__':
    main()
