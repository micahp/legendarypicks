"""Win-loss record and points by streak bucket, by era, from the regular seasons before the cutoff (research, exploratory).

Each team-game counts once, in the bucket it carried into that game, with the same buckets and the same streak rules as
streak_splits: L5+ to W5+, reset each season. Output per bucket: team-games, wins, losses, ties, win share, points scored and allowed
(totals and per game), and the mean margin. The table is split by era (ERAS) and also given for all seasons. A 2026 cutoff reads the
2010 to 2025 schedule only; an era that the cutoff cuts short is truncated, not dropped.

Usage: python3 streak_buckets_report.py --cutoff 2026 --out JSON
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import streak_splits as ss  # noqa: E402

DB = '/root/legendarypicks/backend/data/picks.dev.db'
FIRST_SEASON = 2010  # the same first season the streak frame uses
# 2016 is the first participation season; 2021 is the first 17-game schedule
ERAS = (('2010-2015', 2010, 2015), ('2016-2020', 2016, 2020), ('2021-2025', 2021, 2025))


def schedule(db, cutoff):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        return con.execute("SELECT season, week, game_id, home_team, away_team, home_score, away_score FROM nfl_schedule "
                           "WHERE game_type='REG' AND season >= ? AND season < ? AND home_score IS NOT NULL "
                           "ORDER BY season, week, game_id", (FIRST_SEASON, int(cutoff))).fetchall()
    finally:
        con.close()


def era_of(season):
    for label, first, last in ERAS:
        if first <= season <= last:
            return label
    return None


def _empty():
    return {'team_games': 0, 'wins': 0, 'losses': 0, 'ties': 0, 'points_for': 0, 'points_against': 0}


def _add(row, scored, allowed):
    row['team_games'] += 1
    row['points_for'] += scored
    row['points_against'] += allowed
    if scored > allowed:
        row['wins'] += 1
    elif scored < allowed:
        row['losses'] += 1
    else:
        row['ties'] += 1


def _summary(row):
    n = row['team_games']
    out = dict(row)
    out['win_share'] = round(row['wins'] / n, 4) if n else None
    out['points_for_per_game'] = round(row['points_for'] / n, 3) if n else None
    out['points_against_per_game'] = round(row['points_against'] / n, 3) if n else None
    out['margin_per_game'] = round((row['points_for'] - row['points_against']) / n, 3) if n else None
    return out


def _table(acc):
    out = {bucket: _summary(row) for bucket, row in acc.items()}
    total = _empty()
    for row in acc.values():
        for key in total:
            total[key] += row[key]
    out['ALL'] = _summary(total)
    return out


def report(db, cutoff):
    rows = schedule(db, cutoff)
    results = []
    for season, week, game_id, home, away, hs, aw in rows:
        outcome = None if hs == aw else hs > aw
        results.append((season, week, game_id, home, outcome))
        results.append((season, week, game_id, away, None if outcome is None else not outcome))
    states = ss.streak_states(results)
    by_era = {label: {bucket: _empty() for bucket in ss.BUCKETS} for label, _first, _last in ERAS}
    overall = {bucket: _empty() for bucket in ss.BUCKETS}
    for season, _week, game_id, home, away, hs, aw in rows:
        for team, scored, allowed in ((home, hs, aw), (away, aw, hs)):
            bucket = states[game_id][team]
            _add(overall[bucket], scored, allowed)
            era = era_of(season)
            if era is not None:
                _add(by_era[era][bucket], scored, allowed)
    return {'eras': {label: _table(by_era[label]) for label, _first, _last in ERAS}, 'all': _table(overall)}


def markdown(result):
    header = ['| bucket | team-games | W | L | T | win share | PF total | PA total | PF/g | PA/g | margin/g |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    blocks = []
    for label, table in list(result['eras'].items()) + [('all seasons', result['all'])]:
        lines = [f'### {label}', ''] + header
        for bucket in list(ss.BUCKETS) + ['ALL']:
            r = table[bucket]
            lines.append(f"| {bucket} | {r['team_games']} | {r['wins']} | {r['losses']} | {r['ties']} | {r['win_share']} | "
                         f"{r['points_for']} | {r['points_against']} | {r['points_for_per_game']} | "
                         f"{r['points_against_per_game']} | {r['margin_per_game']} |")
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', default=DB)
    ap.add_argument('--cutoff', type=int, default=2026)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    result = report(args.db, args.cutoff)
    payload = {'cutoff': args.cutoff, 'first_season': FIRST_SEASON, 'eras': {label: [first, last] for label, first, last in ERAS}}
    payload.update(result)
    args.out.write_text(json.dumps(payload, indent=1) + '\n')
    print(markdown(result))


if __name__ == '__main__':
    main()
