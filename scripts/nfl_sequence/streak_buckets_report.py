"""Win-loss record and points by streak bucket, from the regular seasons before the cutoff (research, exploratory).

Each team-game counts once, in the bucket it carried into that game, with the same buckets and the same streak rules as
streak_splits: L5+ to W5+, reset each season. Output per bucket: team-games, wins, losses, ties, win share, points scored and allowed
(totals and per game), and the mean margin. A 2026 cutoff reads the 2010 to 2025 schedule only.

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


def schedule(db, cutoff):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        return con.execute("SELECT season, week, game_id, home_team, away_team, home_score, away_score FROM nfl_schedule "
                           "WHERE game_type='REG' AND season >= ? AND season < ? AND home_score IS NOT NULL "
                           "ORDER BY season, week, game_id", (FIRST_SEASON, int(cutoff))).fetchall()
    finally:
        con.close()


def _empty():
    return {'team_games': 0, 'wins': 0, 'losses': 0, 'ties': 0, 'points_for': 0, 'points_against': 0}


def report(db, cutoff):
    rows = schedule(db, cutoff)
    results = []
    for season, week, game_id, home, away, hs, aw in rows:
        outcome = None if hs == aw else hs > aw
        results.append((season, week, game_id, home, outcome))
        results.append((season, week, game_id, away, None if outcome is None else not outcome))
    states = ss.streak_states(results)
    acc = {bucket: _empty() for bucket in ss.BUCKETS}
    total = _empty()
    for _season, _week, game_id, home, away, hs, aw in rows:
        for team, scored, allowed in ((home, hs, aw), (away, aw, hs)):
            row = acc[states[game_id][team]]
            for target in (row, total):
                target['team_games'] += 1
                target['points_for'] += scored
                target['points_against'] += allowed
                if scored > allowed:
                    target['wins'] += 1
                elif scored < allowed:
                    target['losses'] += 1
                else:
                    target['ties'] += 1
    out = {bucket: _summary(row) for bucket, row in acc.items()}
    out['ALL'] = _summary(total)
    return out


def _summary(row):
    n = row['team_games']
    out = dict(row)
    out['win_share'] = round(row['wins'] / n, 4) if n else None
    out['points_for_per_game'] = round(row['points_for'] / n, 3) if n else None
    out['points_against_per_game'] = round(row['points_against'] / n, 3) if n else None
    out['margin_per_game'] = round((row['points_for'] - row['points_against']) / n, 3) if n else None
    return out


def markdown(result):
    lines = ['| bucket | team-games | W | L | T | win share | PF total | PA total | PF/g | PA/g | margin/g |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for bucket in list(ss.BUCKETS) + ['ALL']:
        r = result[bucket]
        lines.append(f"| {bucket} | {r['team_games']} | {r['wins']} | {r['losses']} | {r['ties']} | {r['win_share']} | "
                     f"{r['points_for']} | {r['points_against']} | {r['points_for_per_game']} | "
                     f"{r['points_against_per_game']} | {r['margin_per_game']} |")
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', default=DB)
    ap.add_argument('--cutoff', type=int, default=2026)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    result = report(args.db, args.cutoff)
    args.out.write_text(json.dumps({'cutoff': args.cutoff, 'first_season': FIRST_SEASON, 'buckets': result}, indent=1) + '\n')
    print(markdown(result))


if __name__ == '__main__':
    main()
