#!/usr/bin/env python3
"""Recompute the team and player statistics of the frozen seed-1 game from its play records, and compare them with the
stored `stats` block. The recomputation is written here from the definitions in the NFL sense, and it imports nothing from
the engine or from game_stats.

Definitions used: a pass attempt is any pass play that is not a sack (interceptions included); a sack is not an attempt;
a rush is a run play; yards on a touchdown are capped at the goal line; possession time is the elapsed-clock difference
between the start and end of each drive, with elapsed = (quarter - 1) * 900 + (900 - clock).

Usage: python3 seed1_stats_check.py [--out PATH]
"""
import argparse
import copy
import hashlib
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED1 = HERE.parents[2] / 'docs' / 'fixtures' / 'e2' / 'e2-game-seed1.json'
SCRIMMAGE = ('run', 'pass_complete', 'pass_incomplete', 'sack', 'interception', 'fumble_lost')


def elapsed(quarter, clock):
    return (quarter - 1) * 900 + (900 - clock)


def capped(play, yards):
    if play['outcome']['touchdown']:
        return min(yards, play['state_before']['yardline_100'])
    return yards


def team_lines(record):
    teams = defaultdict(lambda: defaultdict(int))
    for d in record['drives']:
        t = teams[d['offense_team']]
        t['drives'] += 1
        t['possession_seconds'] += elapsed(d['end_quarter'], d['end_clock']) - elapsed(d['quarter_start'], d['clock_start'])
        if d['terminal'] == 'touchdown':
            t['touchdowns'] += 1
        if d['terminal'] == 'turnover_on_downs':
            t['turnovers_on_downs'] += 1
        if d['field_goal_made'] is not None:
            t['fg_att'] += 1
            t['fg_made'] += 1 if d['field_goal_made'] else 0
        for p in d['plays']:
            ev, out, yards = p['event_type'], p['outcome'], p['outcome']['yards_gained'] or 0
            if ev in SCRIMMAGE:
                t['plays'] += 1
            if ev == 'run':
                t['rush_att'] += 1
                t['rush_yds'] += capped(p, yards)
            elif ev == 'sack':
                t['sacks_taken'] += 1
                t['sack_yds'] += yards
            elif ev in ('pass_complete', 'pass_incomplete', 'interception'):
                t['pass_att'] += 1
                if ev == 'pass_complete':
                    t['pass_comp'] += 1
                    t['pass_yds'] += capped(p, yards)
            if ev in ('interception', 'fumble_lost') and out['turnover']:
                t['turnovers'] += 1
            if out['punt']:
                t['punts'] += 1
    for name, pts in record['points'].items():
        teams[name]['points'] = pts
    return {name: dict(sorted(lines.items())) for name, lines in sorted(teams.items())}


def player_lines(record):
    lines = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for d in record['drives']:
        for p in d['plays']:
            ev, out, part = p['event_type'], p['outcome'], p['participants']
            yards = out['yards_gained'] or 0
            if ev == 'run' and part['rusher_id']:
                r = lines[part['rusher_id']]['rushing']
                r['att'] += 1
                r['yds'] += capped(p, yards)
                r['td'] += 1 if out['touchdown'] else 0
            if ev == 'sack' and part['passer_id']:
                lines[part['passer_id']]['passing']['sacked'] += 1
                lines[part['passer_id']]['passing']['sack_yds'] += yards
            elif ev in ('pass_complete', 'pass_incomplete', 'interception') and part['passer_id']:
                pa = lines[part['passer_id']]['passing']
                pa['att'] += 1
                if ev == 'interception':
                    pa['int'] += 1
                if ev == 'pass_complete':
                    pa['comp'] += 1
                    pa['yds'] += capped(p, yards)
                    pa['td'] += 1 if out['touchdown'] else 0
            if ev == 'pass_complete' and part['receiver_id']:
                c = lines[part['receiver_id']]['receiving']
                c['rec'] += 1
                c['yds'] += capped(p, yards)
                c['td'] += 1 if out['touchdown'] else 0
    result = []
    for pid in sorted(lines):
        # the label says these are the observed play's participants, not a lineup or a substitution
        entry = {'player_id': pid, 'attribution': 'sampled_observed_play'}
        for cat in ('passing', 'rushing', 'receiving'):
            if lines[pid][cat]:
                entry[cat] = dict(sorted(lines[pid][cat].items()))
        result.append(entry)
    return result


def sha256(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(HERE.parents[2] / 'docs' / 'evidence' / 'e2' / 'seed1-stats-recomputed.json'))
    args = ap.parse_args()
    raw = json.load(open(SEED1))
    record = copy.deepcopy(raw.get('record', raw))
    stored = record['stats']

    recomputed_team = team_lines(record)
    recomputed_players = player_lines(record)
    team_match = {}
    for name in sorted(set(recomputed_team) | set(stored['team'])):
        mine, theirs = recomputed_team.get(name, {}), stored['team'].get(name, {})
        team_match[name] = {'match': mine == theirs,
                            'differences': {k: [mine.get(k), theirs.get(k)] for k in set(mine) | set(theirs)
                                            if mine.get(k) != theirs.get(k)}}
    player_match = recomputed_players == stored['player']
    result = {
        'source': {'file': 'docs/fixtures/e2/e2-game-seed1.json', 'sha256': sha256(SEED1)},
        'seed': record['seed'], 'status': record['status'], 'points': record['points'],
        'team_stats_recomputed': recomputed_team, 'team_stats_stored_match': {k: v['match'] for k, v in team_match.items()},
        'team_differences': {k: v['differences'] for k, v in team_match.items() if v['differences']},
        'player_lines_recomputed': recomputed_players,
        'player_lines_match_stored': player_match,
        'player_count': len(recomputed_players),
        'all_match': all(v['match'] for v in team_match.values()) and player_match,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: result[k] for k in ('team_stats_stored_match', 'player_lines_match_stored', 'player_count',
                                              'all_match', 'team_differences')}, indent=1, sort_keys=True))
    return 0 if result['all_match'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
