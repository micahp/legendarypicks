"""Classify each game of a season and weeks by the pregame evaluation it can support (research, not adopted).

For every regular-season game, two snapshot builds are attempted, read-only and with no outcome read:
- backtest: the strict build. It is eligible only if every input has a verified availability time.
- exploratory_replay: the labelled build, which records the unverified inputs.

A game is 'backtest' when the strict build succeeds, 'exploratory_replay' when only the labelled build succeeds, and
'ineligible' when neither does. The refusal reason is kept for each build.

Usage: python3 slc_eligibility_inventory.py --season 2026 --weeks 1-8 --db DB --out JSON
"""
import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import pregame_snapshot as ps  # noqa: E402


def attempt(db, game_id, as_of, evaluation):
    try:
        ps.build(db, game_id, as_of, allow_unverified_current_schedule_exploratory=(evaluation == 'exploratory_replay'),
                 evaluation=evaluation)
        return {'built': True, 'reason': None}
    except ValueError as exc:
        return {'built': False, 'reason': str(exc).split(': ', 1)[-1][:240]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--weeks', required=True, help='e.g. 1-8 or 1,2,7')
    ap.add_argument('--db', default=e1.DEFAULT_DB)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if '-' in args.weeks:
        low, high = (int(v) for v in args.weeks.split('-'))
        weeks = list(range(low, high + 1))
    else:
        weeks = [int(v) for v in args.weeks.split(',')]
    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    games = con.execute("SELECT game_id, week, gameday FROM nfl_schedule WHERE season=? AND game_type='REG' AND week IN (%s) "
                        "ORDER BY week, gameday, game_id" % ','.join('?' * len(weeks)), (args.season, *weeks)).fetchall()
    rows, counts = [], {'backtest': 0, 'exploratory_replay': 0, 'ineligible': 0}
    for game_id, week, gameday in games:
        as_of = (date.fromisoformat(gameday) - timedelta(days=1)).isoformat() + 'T12:00:00Z'
        strict = attempt(args.db, game_id, as_of, 'backtest')
        labelled = strict if strict['built'] else attempt(args.db, game_id, as_of, 'exploratory_replay')
        category = 'backtest' if strict['built'] else ('exploratory_replay' if labelled['built'] else 'ineligible')
        counts[category] += 1
        rows.append({'game_id': game_id, 'week': week, 'gameday': gameday, 'as_of': as_of, 'category': category,
                     'backtest_refusal': None if strict['built'] else strict['reason'],
                     'exploratory_refusal': None if labelled['built'] else labelled['reason']})
    out = {'season': args.season, 'weeks': weeks, 'as_of_rule': 'the day before the scheduled game day, 12:00Z',
           'counts': counts, 'games': rows,
           'note': 'no outcome column is read; the categories describe input availability only'}
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
