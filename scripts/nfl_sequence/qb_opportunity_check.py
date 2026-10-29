"""QB-opportunity validation check: simulated plays per game against the actual 2025 regular season (validation only, not an input).

The QB-opportunity model (another branch) predicts team attempts as plays per game times pass propensity times QB share. SLC generates
its own plays, so this check compares what the simulation produces with what the season produced: dropbacks, runs and scrimmage plays
per game, both teams together, and the pass share. A gap is simulated over actual, minus one.

Usage: python3 qb_opportunity_check.py BATCH.json [BATCH.json ...] [--season 2025] [--out JSON]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB = '/root/legendarypicks/backend/data/picks.dev.db'


def compare(simulated, actual):
    """Per-quantity simulated and actual means, the gap, and the pass share on each side. None where the actual is zero."""
    out = {}
    for key in ('dropback', 'run', 'scrimmage'):
        s, a = simulated[key], actual[key]
        out[key] = {'simulated': s, 'actual': a, 'gap': (s / a - 1) if a else None}
    out['pass_share'] = {'simulated': simulated['dropback'] / simulated['scrimmage'],
                         'actual': actual['dropback'] / actual['scrimmage']}
    return out


def simulated_means(paths):
    """Mean dropbacks, runs and scrimmage plays per valid game, both teams, over the batch files."""
    totals = {'dropback': 0.0, 'run': 0.0, 'scrimmage': 0.0}
    n = 0
    for path in paths:
        for outcome in json.load(open(path))['summary']['outcomes']:
            if not outcome.get('valid_full_game'):
                continue
            pc = outcome['playcall']
            totals['dropback'] += pc['dropback']
            totals['run'] += pc['run']
            totals['scrimmage'] += pc['scrimmage']
            n += 1
    if not n:
        raise ValueError('no valid games in the batch files')
    return {k: v / n for k, v in totals.items()}


def actual_means(season, db=DB):
    """Mean dropbacks (pass plays, sacks included), runs and scrimmage plays per regular-season game, both teams, from the database."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        out = {}
        for key, sql in (('dropback', "play_type = 'pass'"), ('run', "play_type = 'run'"),
                         ('scrimmage', "play_type IN ('pass', 'run')")):
            (mean,) = con.execute(
                f"SELECT AVG(n) FROM (SELECT game_id, COUNT(*) AS n FROM nfl_pbp WHERE season = ? AND week <= 18 AND posteam IS NOT NULL "
                f"AND {sql} GROUP BY game_id)", (int(season),)).fetchone()
            out[key] = mean
        return out
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('batches', nargs='+', type=Path)
    ap.add_argument('--season', type=int, default=2025)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    result = compare(simulated_means(args.batches), actual_means(args.season))
    for key in ('dropback', 'run', 'scrimmage'):
        r = result[key]
        gap = 'n/a' if r['gap'] is None else f"{100 * r['gap']:+.1f}%"
        print(f"{key:10s} simulated {r['simulated']:7.2f}  actual {r['actual']:7.2f}  gap {gap}")
    print(f"pass share simulated {result['pass_share']['simulated']:.3f}  actual {result['pass_share']['actual']:.3f}")
    if args.out:
        args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
