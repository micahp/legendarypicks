"""Team win-loss record and current streak as of each Week 8 cutoff, from the captured schedule (research, display only).

The scores come from the raw games file acquired before the Week 8 cutoff (verified by hash through pregame_capture.read_manifest),
so only games that were final before that acquisition count. A streak is the current run of wins (W) or losses (L), and ties are
neither. This is a record shown next to each game; it is not a model input, and it does not change the locked forecast.

Usage: python3 wl_streak.py --capture DIR --out JSON
"""
import argparse
import json
from pathlib import Path

import pandas as pd

import pregame_capture as pc


def streak(results):
    """results in game order, each 'W', 'L' or 'T'. Returns e.g. 'W3', 'L1', or '' when none."""
    decided = [r for r in results if r in ('W', 'L')]
    if not decided:
        return ''
    last = decided[-1]
    count = 0
    for r in reversed(decided):
        if r != last:
            break
        count += 1
    return f'{last}{count}'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--capture', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    manifest = pc.read_manifest(args.capture)
    games_file = args.capture / next(f['name'] for f in manifest['files'] if f['name'] == 'games.parquet')
    games = pd.read_parquet(games_file)
    season = games[(games.season == 2026) & (games.game_type == 'REG') & (games.week < 8)].sort_values(['week', 'gameday', 'game_id'])
    final = season[season.home_score.notna() & season.away_score.notna()]
    teams = {}
    for _, g in final.iterrows():
        for team, mine, theirs in ((g.home_team, g.home_score, g.away_score), (g.away_team, g.away_score, g.home_score)):
            outcome = 'W' if mine > theirs else 'L' if mine < theirs else 'T'
            teams.setdefault(team, []).append((int(g.week), g.game_id, outcome))
    summary = {}
    for team, rows in teams.items():
        results = [r[2] for r in rows]
        summary[team] = {'wins': results.count('W'), 'losses': results.count('L'), 'ties': results.count('T'),
                         'streak': streak(results), 'games': len(rows)}
    week8 = games[(games.season == 2026) & (games.week == 8)].sort_values(['gameday', 'gametime', 'game_id'])
    per_game = []
    for _, g in week8.iterrows():
        per_game.append({'game_id': g.game_id, 'away': {'team': g.away_team, **summary.get(g.away_team, {'wins': 0, 'losses': 0, 'ties': 0, 'streak': '', 'games': 0})},
                         'home': {'team': g.home_team, **summary.get(g.home_team, {'wins': 0, 'losses': 0, 'ties': 0, 'streak': '', 'games': 0})}})
    out = {'source': 'captured games file (sha256 in capture manifest), final games before the Week 8 acquisition',
           'as_of_utc': next(f['acquired_at_utc'] for f in manifest['files'] if f['name'] == 'games.parquet'),
           'note': 'display only; not a model input', 'teams': summary, 'week8_games': per_game}
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'teams': len(summary), 'week8_games': len(per_game)}))


if __name__ == '__main__':
    main()
