"""Compare the 2024 replay (scoring_calibration_2024.py) with the 2024 regular season, per team-game (research, not adopted).

Actuals come from the database's play-by-play and schedule scores for 2024 regular-season games. Drives are the possessions of
each team in regulation and overtime. A drive's terminal is taken from the play-by-play series result. Simulated and actual drives
are summarised the same way: drives, points, touchdowns, field goals, turnovers, punts, turnovers on downs, plays per drive
(scrimmage plays only), and points per drive. The replay covers weeks 2 to 18, because week 1 has no earlier depth chart.

Usage: python3 scoring_compare_2024.py --sim JSONL --out JSON
"""
import argparse
import collections
import json
import sqlite3
from pathlib import Path

DB = '/root/legendarypicks/backend/data/picks.dev.db'
SCRIMMAGE = ('run', 'pass')


def actual_team_games():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    games = {r[0]: r for r in con.execute(
        "SELECT game_id, home_team, away_team, home_score, away_score FROM nfl_schedule "
        "WHERE season=2024 AND game_type='REG' AND home_score IS NOT NULL AND week >= 2")}
    plays = con.execute(
        "SELECT game_id, drive, posteam, qtr, play_type, series_result, game_seconds_remaining FROM nfl_pbp "
        "WHERE season=2024 AND week BETWEEN 2 AND 18 AND posteam IS NOT NULL AND drive IS NOT NULL "
        "ORDER BY game_id, play_id")
    drives = collections.OrderedDict()
    for game_id, drive, posteam, qtr, play_type, series, secs in plays:
        if game_id not in games:
            continue
        entry = drives.setdefault((game_id, drive, posteam), {'plays': 0, 'terminal': None, 'first_secs': secs, 'last_secs': secs})
        if play_type in SCRIMMAGE:
            entry['plays'] += 1
        entry['last_secs'] = secs
        if series:
            entry['terminal'] = series
    teams = collections.defaultdict(lambda: collections.defaultdict(list))
    for (game_id, _drive, posteam), entry in drives.items():
        teams[(game_id, posteam)]['drives'].append(entry)
    rows = []
    for game_id, home, away, hs, aw in games.values():
        for team, points in ((home, hs), (away, aw)):
            if (game_id, team) in teams:
                rows.append({'game_id': game_id, 'team': team, 'points': points, 'drives': teams[(game_id, team)]['drives']})
    return rows


def summarise_actual(rows):
    out = []
    for row in rows:
        drives = row['drives']
        out.append({'points': row['points'], 'drives': len(drives),
                    'plays_per_drive': sum(d['plays'] for d in drives) / max(1, len(drives)),
                    'terminals': collections.Counter(classify_actual(d['terminal']) for d in drives)})
    return out


def classify_actual(series):
    text = (series or '').lower()
    if 'touchdown' in text:
        return 'touchdown'
    if 'field goal' in text and 'missed' not in text:
        return 'field_goal'
    if 'missed' in text:
        return 'missed_field_goal'
    if 'punt' in text:
        return 'punt'
    if 'downs' in text:
        return 'turnover_on_downs'
    if 'turnover' in text or 'interception' in text or 'fumble' in text:
        return 'turnover'
    if 'safety' in text:
        return 'safety'
    if 'end of' in text or 'half' in text or 'game' in text:
        return 'end_of_period'
    return 'other'


def summarise_sim(path):
    games = collections.defaultdict(list)
    skipped = errors = 0
    for line in Path(path).read_text().splitlines():
        row = json.loads(line)
        if 'skipped' in row:
            skipped += 1
            continue
        if 'error' in row:
            errors += 1
            continue
        games[row['game_id']].append(row)
    out = []
    for game_id, rows in games.items():
        for row in rows:
            for side in ('A', 'B'):
                drives = [d for d in row['drives'] if d['offense'] == side]
                out.append({'points': row['points'][side], 'drives': len(drives),
                            'plays_per_drive': sum(d['plays'] for d in drives) / max(1, len(drives)),
                            'terminals': collections.Counter(d['terminal'] for d in drives)})
    return out, {'games': len(games), 'skipped': skipped, 'errors': errors, 'team_games': len(out)}


def mean(values):
    return round(sum(values) / len(values), 3) if values else None


def describe(items):
    terminals = collections.Counter()
    for item in items:
        terminals.update(item['terminals'])
    n = len(items)
    per_game = {k: round(v / n, 3) for k, v in sorted(terminals.items(), key=lambda kv: -kv[1])}
    return {'team_games': n, 'points': mean([i['points'] for i in items]), 'drives': mean([i['drives'] for i in items]),
            'points_per_drive': round(sum(i['points'] for i in items) / max(1, sum(i['drives'] for i in items)), 3),
            'plays_per_drive': mean([i['plays_per_drive'] for i in items]), 'terminals_per_team_game': per_game}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sim', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    sim, meta = summarise_sim(args.sim)
    actual = summarise_actual(actual_team_games())
    result = {'sim_meta': meta, 'simulated_2024_replay': describe(sim), 'actual_2024_regular_season': describe(actual),
              'definitions': 'points include overtime; drives are possessions; plays are run and pass plays only; '
                             'actual terminals from the play-by-play series result'}
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: result[k] for k in ('sim_meta',)}))
    for key in ('simulated_2024_replay', 'actual_2024_regular_season'):
        block = result[key]
        print(key, {k: block[k] for k in ('team_games', 'points', 'drives', 'points_per_drive', 'plays_per_drive')})


if __name__ == '__main__':
    main()
