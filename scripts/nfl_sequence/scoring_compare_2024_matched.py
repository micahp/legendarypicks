"""The 2024 scoring comparison on one matched cohort (research). Replaces scoring_compare_2024.py for calibration claims.

The cohort is the set of 2024 regular-season games (weeks 2 to 18) in which at least one simulated seed completed. Both sides use that
cohort only. Possessions exclude clock terminals on both sides, plays per possession count run and pass plays, and terminals use the
same names. Points are final points on both sides, including overtime. Also reported: points the defense or special teams scored on
returns, from the play-by-play, to show how much of the team total the offensive-possession comparison does not cover.

Usage: python3 scoring_compare_2024_matched.py --sim JSONL [--sim JSONL ...] --out JSON
"""
import argparse
import collections
import json
import sqlite3
from pathlib import Path

import scoring_cohort as sc
import scoring_compare_2024 as legacy

DB = '/root/legendarypicks/backend/data/picks.dev.db'


def load_seeds(paths):
    lines = []
    for path in paths:
        for raw in Path(path).read_text().splitlines():
            row = json.loads(raw)
            if 'drives' in row:
                lines.append(row)
    return lines


def actual_team_games(con, cohort):
    """Actual team-games in the cohort, drives as possessions (clock terminals kept apart), plays from scrimmage."""
    games = {r[0]: r for r in con.execute(
        "SELECT game_id, home_team, away_team, home_score, away_score FROM nfl_schedule "
        "WHERE season = 2024 AND game_type = 'REG' AND home_score IS NOT NULL AND week >= 2") if r[0] in cohort}
    plays = con.execute(
        "SELECT game_id, drive, posteam, play_type, series_result, play_id FROM nfl_pbp "
        "WHERE season = 2024 AND week BETWEEN 2 AND 18 AND posteam IS NOT NULL AND drive IS NOT NULL "
        "ORDER BY game_id, play_id").fetchall()
    drives = collections.OrderedDict()
    for game_id, drive, posteam, play_type, series, _play_id in plays:
        if game_id not in games:
            continue
        entry = drives.setdefault((game_id, drive, posteam), {'plays': 0, 'terminal': None})
        if play_type in ('run', 'pass'):
            entry['plays'] += 1
        if series:
            entry['terminal'] = series
    by_team = collections.defaultdict(list)
    for (game_id, _drive, posteam), entry in drives.items():
        by_team[(game_id, posteam)].append(entry)
    rows = []
    for game_id, home, away, hs, aw in games.values():
        for team, points in ((home, hs), (away, aw)):
            if (game_id, team) in by_team:
                drives_ = by_team[(game_id, team)]
                possessions = [d for d in drives_ if legacy.classify_actual(d['terminal']) != 'end_of_period']
                rows.append({'game_id': game_id, 'team': team, 'points': points, 'possessions': len(possessions),
                             'plays_per_possession': sum(d['plays'] for d in possessions) / max(1, len(possessions)),
                             'terminals': collections.Counter(legacy.classify_actual(d['terminal']) for d in possessions)})
    return rows


def defensive_points(con, cohort):
    """Touchdowns scored by the defense or on special teams, per cohort team-game (6 points each, extra points not counted).

    The database has no scoring-team column, so the scoring side is taken from the play: an interception, a lost fumble, a punt or a
    kickoff that is a touchdown was scored by the defensive team (defteam) on that play."""
    rows = con.execute(
        "SELECT game_id, defteam FROM nfl_pbp WHERE season = 2024 AND week BETWEEN 2 AND 18 AND touchdown = 1 "
        "AND defteam IS NOT NULL AND (interception = 1 OR fumble_lost = 1 OR play_type IN ('punt', 'kickoff'))").fetchall()
    per_team = collections.Counter()
    for game_id, defteam in rows:
        if game_id in cohort:
            per_team[(game_id, defteam)] += 6
    return per_team


def describe_sim(rows):
    n = len(rows)
    terminals = collections.Counter()
    for r in rows:
        terminals.update(r['terminals'])
    possessions = sum(r['possessions'] for r in rows)
    return {'team_games': n, 'points': round(sum(r['points'] for r in rows) / n, 3),
            'possessions': round(possessions / n, 3),
            'points_per_possession': round(sum(r['points'] for r in rows) / max(1, possessions), 4),
            'plays_per_possession': round(sum(r['plays_per_possession'] for r in rows) / n, 3),
            'terminals_per_team_game': {k: round(v / n, 3) for k, v in sorted(terminals.items(), key=lambda kv: -kv[1])}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sim', type=Path, action='append', required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    lines = load_seeds(args.sim)
    cohort = sc.cohort_games(lines)
    seeds = sc.complete_seeds(lines, cohort)
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    actual = actual_team_games(con, cohort)
    defense = defensive_points(con, cohort)
    con.close()
    sim = sc.sim_team_games(seeds)
    all_games = {r['game_id'] for r in sim}
    result = {
        'cohort': {'games': len(cohort), 'simulated_seeds_used': len(seeds),
                   'seeds_excluded_blocked': sum(1 for line in lines if line.get('status') == 'blocked'),
                   'actual_team_games': len(actual), 'simulated_team_games': len(sim)},
        'simulated': describe_sim(sim), 'actual': describe_sim(actual),
        'defensive_and_special_teams_points_per_team_game': round(sum(defense.values()) / max(1, len(actual)), 3),
        'definitions': ('cohort: 2024 regular season weeks 2 to 18, games with a completed simulated seed; points are final, '
                        'including overtime; possessions exclude clock terminals on both sides; plays per possession are run and '
                        'pass plays; simulated terminals are mapped to the actual names'),
    }
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result['cohort'], sort_keys=True))
    for side in ('simulated', 'actual'):
        block = result[side]
        print(side, {k: block[k] for k in ('team_games', 'points', 'possessions', 'points_per_possession', 'plays_per_possession')})
    print('defense/special-teams points per team-game (actual):', result['defensive_and_special_teams_points_per_team_game'])


if __name__ == '__main__':
    main()
