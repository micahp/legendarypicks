#!/usr/bin/env python3
"""Recompute the team and player statistics of the frozen seed-1 game from its play records, and compare them with the
stored `stats` block. The recomputation is written here from the definitions in the NFL sense, and it imports nothing from
the engine or from game_stats.

Definitions used: a pass attempt is any pass play that is not a sack (interceptions included); a sack is not an attempt;
a rush is a run play; yards on a touchdown are capped at the goal line; possession time is the elapsed-clock difference
between the start and end of each drive, with elapsed = (quarter - 1) * 900 + (900 - clock).

Usage: python3 seed1_stats_check.py [--record PATH] [--out PATH]
The default record is the frozen seed-1 game; pass the successor record with --record.
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


def pregame_team_lines(record):
    """Independently recompute the richer team totals in the pregame snapshot contract."""
    teams = defaultdict(lambda: defaultdict(int))
    for drive in record['drives']:
        team = teams[drive['offense_team']]
        team['drives'] += 1
        team['possession_seconds'] += (elapsed(drive['end_quarter'], drive['end_clock'])
                                       - elapsed(drive['quarter_start'], drive['clock_start']))
        if drive['terminal'] == 'touchdown':
            team['touchdowns'] += 1
        if drive['terminal'] == 'turnover_on_downs':
            team['turnovers_on_downs'] += 1
        if drive['field_goal_made'] is not None:
            team['fg_att'] += 1
            team['fg_made'] += int(drive['field_goal_made'])
        for play in drive['plays']:
            event, outcome, participants = play['event_type'], play['outcome'], play['participants']
            yards = outcome['yards_gained'] or 0
            if event in SCRIMMAGE:
                team['plays'] += 1
            if event in ('pass_complete', 'pass_incomplete', 'interception') and participants.get('receiver_id'):
                team['pass_tgt'] += 1
            if event == 'run':
                team['rush_att'] += 1
                team['rush_yds'] += capped(play, yards)
            elif event in ('pass_complete', 'pass_incomplete', 'interception', 'sack'):
                if event == 'sack':
                    team['sacks_taken'] += 1
                    team['sack_yds'] += yards
                else:
                    team['pass_att'] += 1
                    if event == 'pass_complete':
                        team['pass_comp'] += 1
                        team['pass_yds'] += capped(play, yards)
            if outcome['turnover'] and event in ('interception', 'fumble_lost'):
                team['turnovers'] += 1
            if event == 'interception':
                team['interceptions'] += 1
            if event == 'fumble_lost':
                team['fumbles_lost'] += 1
            if outcome['punt']:
                team['punts'] += 1
    for name, points in record['points'].items():
        teams[name]['points'] = points
    return {name: dict(sorted(values.items())) for name, values in sorted(teams.items())}


def pregame_player_lines(record):
    """Independently recompute role-assigned lines and preserve the attribution metadata."""
    lines = {}

    def line(player_id, participants, role):
        result = lines.setdefault(player_id, {'passing': defaultdict(int), 'rushing': defaultdict(int),
                                               'receiving': defaultdict(int), 'miscellaneous': defaultdict(int),
                                               'attribution': participants.get('attribution')})
        for field in ('name', 'position', 'team', 'side'):
            value = participants.get(f'{role}_{field}')
            if value is not None:
                result[f'player_{field}'] = value
        return result

    for drive in record['drives']:
        for play in drive['plays']:
            event, outcome, participants = play['event_type'], play['outcome'], play['participants']
            yards, touchdown = outcome['yards_gained'] or 0, bool(outcome['touchdown'])
            if event == 'run' and participants.get('rusher_id'):
                rushing = line(participants['rusher_id'], participants, 'rusher')['rushing']
                rushing['att'] += 1
                rushing['yds'] += capped(play, yards)
                rushing['td'] += int(touchdown)
            if event == 'fumble_lost':
                role = 'rusher' if participants.get('rusher_id') else 'passer'
                fumbler = participants.get(f'{role}_id')
                if fumbler:
                    line(fumbler, participants, role)['miscellaneous']['fumbles_lost'] += 1
            if event in ('pass_complete', 'pass_incomplete', 'interception', 'sack') and participants.get('passer_id'):
                passing = line(participants['passer_id'], participants, 'passer')['passing']
                if event == 'sack':
                    passing['sacked'] += 1
                    passing['sack_yds'] += yards
                else:
                    passing['att'] += 1
                    if event == 'interception':
                        passing['int'] += 1
                    if event == 'pass_complete':
                        passing['comp'] += 1
                        passing['yds'] += capped(play, yards)
                        passing['td'] += int(touchdown)
            if event in ('pass_complete', 'pass_incomplete', 'interception') and participants.get('receiver_id'):
                receiving = line(participants['receiver_id'], participants, 'receiver')['receiving']
                receiving['tgt'] += 1
                if event == 'pass_complete':
                    receiving['rec'] += 1
                    receiving['yds'] += capped(play, yards)
                    receiving['td'] += int(touchdown)
    result = []
    for player_id in sorted(lines):
        source = lines[player_id]
        entry = {'player_id': player_id, 'attribution': source['attribution']}
        for field in ('player_name', 'player_position', 'player_team', 'player_side'):
            if field in source:
                entry[field] = source[field]
        for category in ('passing', 'rushing', 'receiving', 'miscellaneous'):
            if source[category]:
                entry[category] = dict(sorted(source[category].items()))
        result.append(entry)
    return result


def pregame_roster_check(payload, player_lines):
    snapshot = payload.get('pregame_snapshot') or {}
    rosters = snapshot.get('rosters') or {}
    roster = {}
    qb1 = {}
    for side, group in rosters.items():
        for player in group.get('players', []):
            roster[player.get('gsis_id')] = (side, player)
            if player.get('pos_abb') == 'QB' and player.get('pos_rank') == 1:
                qb1[side] = player.get('gsis_id')
    record_side = {'A': 'home', 'B': 'away'}
    ids_present = all(row['player_id'] in roster for row in player_lines)
    metadata_matches = all(
        roster.get(row['player_id'], (None, {}))[0] == record_side.get(row.get('player_side'))
        and roster.get(row['player_id'], (None, {}))[1].get('player_name') == row.get('player_name')
        and roster.get(row['player_id'], (None, {}))[1].get('pos_abb') == row.get('player_position')
        for row in player_lines)
    quarterbacks = {play['participants'].get('passer_side'): play['participants'].get('passer_id')
                    for drive in payload['record']['drives'] for play in drive['plays']
                    if play['participants'].get('passer_id')}
    qb1_only = bool(quarterbacks) and all(qb1.get(record_side.get(side)) == player_id
                                            for side, player_id in quarterbacks.items())
    return {'all_players_in_frozen_roster': ids_present, 'player_metadata_matches_roster': metadata_matches,
            'passers_are_frozen_qb1': qb1_only}


def sha256(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--record', default=str(SEED1))
    ap.add_argument('--out', default=str(HERE.parents[2] / 'docs' / 'evidence' / 'e2' / 'seed1-stats-recomputed.json'))
    args = ap.parse_args()
    source = Path(args.record)
    raw = json.load(open(source))
    record = copy.deepcopy(raw.get('record', raw))
    stored = record['stats']

    is_pregame = stored.get('player_attribution') == 'pregame_depth_chart_role_sample'
    recomputed_team = pregame_team_lines(record) if is_pregame else team_lines(record)
    recomputed_players = pregame_player_lines(record) if is_pregame else player_lines(record)
    team_match = {}
    for name in sorted(set(recomputed_team) | set(stored['team'])):
        mine, theirs = recomputed_team.get(name, {}), stored['team'].get(name, {})
        team_match[name] = {'match': mine == theirs,
                            'differences': {k: [mine.get(k), theirs.get(k)] for k in set(mine) | set(theirs)
                                            if mine.get(k) != theirs.get(k)}}
    player_match = recomputed_players == stored['player']
    try:
        source_label = str(source.resolve().relative_to(HERE.parents[2]))
    except ValueError:
        source_label = str(source.resolve())
    roster_checks = pregame_roster_check(raw, recomputed_players) if is_pregame else {}
    result = {
        'source': {'file': source_label, 'sha256': sha256(source)},
        'seed': record['seed'], 'status': record['status'], 'points': record['points'],
        'team_stats_recomputed': recomputed_team, 'team_stats_stored_match': {k: v['match'] for k, v in team_match.items()},
        'team_differences': {k: v['differences'] for k, v in team_match.items() if v['differences']},
        'player_lines_recomputed': recomputed_players,
        'player_lines_match_stored': player_match,
        'player_count': len(recomputed_players),
        'roster_checks': roster_checks,
        'all_match': (all(v['match'] for v in team_match.values()) and player_match
                      and all(roster_checks.values())),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: result[k] for k in ('team_stats_stored_match', 'player_lines_match_stored', 'player_count',
                                              'all_match', 'team_differences')}, indent=1, sort_keys=True))
    return 0 if result['all_match'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
