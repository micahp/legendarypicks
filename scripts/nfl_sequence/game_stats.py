"""Team and player lines for one generated game, computed from its plays.

Pregame games assign the frozen QB1 and sample eligible backs and receivers from the frozen depth chart. Other research
modes retain observed-play participants. Pregame player totals reconcile to the generated team totals, but they are role
allocations rather than player-specific performance projections or a complete lineup. Every line carries `attribution`.

Yards credited on a touchdown are capped at the distance to the goal line in the simulation. The observed yards describe
the observed play, not the simulated spot, and a line that said otherwise would contradict the field.
"""
from collections import defaultdict

QUARTER_LENGTH = 900
ATTRIBUTION = 'sampled_observed_play'
SCRIMMAGE_EVENTS = ('run', 'pass_complete', 'pass_incomplete', 'sack', 'interception', 'fumble_lost')


def _elapsed(quarter, clock):
    """Game seconds elapsed at (quarter, clock)."""
    return (quarter - 1) * QUARTER_LENGTH + (QUARTER_LENGTH - clock)


def team_stats(drives, points):
    """Per-team lines: plays, rushing, passing, turnovers, punts, field goals, possession time and points."""
    teams = {}

    def team(name):
        return teams.setdefault(name, defaultdict(int))

    for d in drives:
        t = team(d['offense_team'])
        fg_attempt_recorded = False
        fg_result_recorded = False
        t['drives'] += 1
        end = _elapsed(d['end_quarter'], d['end_clock'])
        t['possession_seconds'] += end - _elapsed(d['quarter_start'], d['clock_start'])
        for play in d['plays']:
            ev, out, part = play['event_type'], play['outcome'], play['participants']
            if ev in SCRIMMAGE_EVENTS:
                t['plays'] += 1
            if ev in ('pass_complete', 'pass_incomplete', 'interception') and part.get('receiver_id'):
                t['pass_tgt'] += 1
            yards = out['yards_gained'] or 0
            if ev == 'run':
                t['rush_att'] += 1
                t['rush_yds'] += _credited(play, yards)
            elif ev in ('pass_complete', 'pass_incomplete', 'interception', 'sack'):
                if ev == 'sack':
                    t['sacks_taken'] += 1
                    t['sack_yds'] += yards
                else:
                    t['pass_att'] += 1
                    if ev == 'pass_complete':
                        t['pass_comp'] += 1
                        t['pass_yds'] += _credited(play, yards)
            if out['turnover'] and ev in ('interception', 'fumble_lost'):
                t['turnovers'] += 1
            if ev == 'interception':
                t['interceptions'] += 1
            if ev == 'fumble_lost':
                t['fumbles_lost'] += 1
            if out.get('punt_attempt', out['punt']):
                t['punts'] += 1
            if out.get('field_goal_attempt'):
                t['fg_att'] += 1
                fg_attempt_recorded = True
                if out.get('field_goal_result') in ('made', 'missed', 'blocked'):
                    t['fg_made'] += int(out['field_goal_result'] == 'made')
                    fg_result_recorded = True
            blocked = out.get('blocked_kick')
            if blocked:
                t['blocked_field_goals' if blocked.get('kick_type') == 'field_goal' else 'blocked_punts'] += 1
                role = blocked.get('recovery_role')
                if role in ('kicking_team', 'receiving_team') and blocked.get('return_yards') is not None:
                    returning_side = d['offense_team'] if role == 'kicking_team' else ('B' if d['offense_team'] == 'A' else 'A')
                    returned = team(returning_side)
                    returned['blocked_kick_returns'] += 1
                    returned['blocked_kick_return_yards'] += blocked['return_yards']
        if d['terminal'] == 'turnover_on_downs':
            t['turnovers_on_downs'] += 1
        if d['field_goal_made'] is not None:
            if not fg_attempt_recorded:
                # Compatibility with records that keep the kick result only on the drive.
                t['fg_att'] += 1
            if not fg_result_recorded:
                t['fg_made'] += int(d['field_goal_made'])
        if d['terminal'] == 'touchdown':
            scorer = d.get('touchdown_scored_by') or d['offense_team']
            scored = team(scorer)
            scored['touchdowns'] += 1
            if not (d['plays'] and d['plays'][-1]['outcome'].get('blocked_kick')):  # an observed overtime drive has no plays
                scored['offensive_touchdowns'] += 1
            if d.get('observed_overtime_drive'):
                scored['observed_overtime_touchdowns'] += 1  # counted on the team line, with no play to attribute it to
    for name, pts in points.items():
        team(name)['points'] = pts
    return {name: dict(sorted(t.items())) for name, t in sorted(teams.items())}


def _credited(play, yards):
    """Yards credited to a play: the observed yards, capped at the goal line when the play is a touchdown."""
    if play['outcome']['touchdown']:
        return min(yards, play['state_before']['yardline_100'])
    return yards


def player_lines(drives):
    """Per-player passing, rushing, receiving and miscellaneous lines with attribution metadata."""
    lines = {}

    def line(pid, part, role):
        entry = lines.setdefault(pid, {'passing': defaultdict(int), 'rushing': defaultdict(int),
                                       'receiving': defaultdict(int), 'miscellaneous': defaultdict(int),
                                       'attribution': part.get('attribution', ATTRIBUTION)})
        for field in ('name', 'position', 'team', 'side'):
            value = part.get(f'{role}_{field}')
            if value is not None:
                entry[f'player_{field}'] = value
        return entry

    for d in drives:
        for play in d['plays']:
            ev, out, part = play['event_type'], play['outcome'], play['participants']
            yards = out['yards_gained'] or 0
            td = bool(out['touchdown'])
            if ev == 'run' and part['rusher_id']:
                r = line(part['rusher_id'], part, 'rusher')['rushing']
                r['att'] += 1
                r['yds'] += _credited(play, yards)
                r['td'] += int(td)
            if ev == 'fumble_lost':
                role = 'rusher' if part.get('rusher_id') else 'passer'
                fumbler = part.get(f'{role}_id')
                if fumbler:
                    line(fumbler, part, role)['miscellaneous']['fumbles_lost'] += 1
            if ev in ('pass_complete', 'pass_incomplete', 'interception', 'sack') and part['passer_id']:
                p = line(part['passer_id'], part, 'passer')['passing']
                if ev == 'sack':
                    p['sacked'] += 1
                    p['sack_yds'] += yards
                    continue
                p['att'] += 1
                if ev == 'interception':
                    p['int'] += 1
                if ev == 'pass_complete':
                    p['comp'] += 1
                    p['yds'] += _credited(play, yards)
                    p['td'] += int(td)
            if ev in ('pass_complete', 'pass_incomplete', 'interception') and part['receiver_id']:
                c = line(part['receiver_id'], part, 'receiver')['receiving']
                c['tgt'] += 1
                if ev == 'pass_complete':
                    c['rec'] += 1
                    c['yds'] += _credited(play, yards)
                    c['td'] += int(td)
    out = []
    for pid in sorted(lines):
        entry = {'player_id': pid, 'attribution': lines[pid]['attribution']}
        for field in ('player_name', 'player_position', 'player_team', 'player_side'):
            if field in lines[pid]:
                entry[field] = lines[pid][field]
        for cat in ('passing', 'rushing', 'receiving', 'miscellaneous'):
            if lines[pid][cat]:
                entry[cat] = dict(sorted(lines[pid][cat].items()))
        out.append(entry)
    return out


def compute(drives, points):
    """The game's stat block: team lines, player lines, and the label that says what the player lines are."""
    players = player_lines(drives)
    attributions = {row['attribution'] for row in players}
    attribution = next(iter(attributions)) if len(attributions) == 1 else ATTRIBUTION
    if attribution == 'pregame_depth_chart_role_sample':
        _verify_pregame_reconciliation(team_stats(drives, points), players)
    note = ('Team play outcomes come from historical E1 samples. The passer is the frozen QB1; eligible receiver and '
            'ball-carrier positions follow historical shares, then players are sampled by depth rank. Individual lines are '
            'allocations, not player-specific projections.'
            if attribution == 'pregame_depth_chart_role_sample' else
            'Players are the participants of the observed plays each simulated play was sampled from. They are not this '
            'game\'s roster or lineup, and these lines are not evidence about those players.')
    return {
        'team': team_stats(drives, points),
        'player': players,
        'player_attribution': attribution,
        'player_note': note,
    }


def _verify_pregame_reconciliation(teams, players):
    """Player box-score lines must sum to their offense's corresponding team totals."""
    for side, team in teams.items():
        rows = [player for player in players if player.get('player_side') == side]
        checks = {
            'rush_att': sum(player.get('rushing', {}).get('att', 0) for player in rows),
            'rush_yds': sum(player.get('rushing', {}).get('yds', 0) for player in rows),
            'pass_att': sum(player.get('passing', {}).get('att', 0) for player in rows),
            'pass_comp': sum(player.get('passing', {}).get('comp', 0) for player in rows),
            'pass_yds': sum(player.get('passing', {}).get('yds', 0) for player in rows),
            'pass_int': sum(player.get('passing', {}).get('int', 0) for player in rows),
            'offensive_td': (sum(player.get('rushing', {}).get('td', 0) for player in rows)
                             + sum(player.get('passing', {}).get('td', 0) for player in rows)),
            'sacks_taken': sum(player.get('passing', {}).get('sacked', 0) for player in rows),
            'sack_yds': sum(player.get('passing', {}).get('sack_yds', 0) for player in rows),
            'fumbles_lost': sum(player.get('miscellaneous', {}).get('fumbles_lost', 0) for player in rows),
            'pass_tgt': sum(player.get('receiving', {}).get('tgt', 0) for player in rows),
            'pass_comp_receiving': sum(player.get('receiving', {}).get('rec', 0) for player in rows),
            'pass_yds_receiving': sum(player.get('receiving', {}).get('yds', 0) for player in rows),
            'offensive_turnovers': (sum(player.get('passing', {}).get('int', 0) for player in rows)
                                    + sum(player.get('miscellaneous', {}).get('fumbles_lost', 0) for player in rows)),
        }
        expected = {
            'rush_att': team.get('rush_att', 0), 'rush_yds': team.get('rush_yds', 0),
            'pass_att': team.get('pass_att', 0), 'pass_comp': team.get('pass_comp', 0),
            'pass_yds': team.get('pass_yds', 0), 'sacks_taken': team.get('sacks_taken', 0),
            'pass_int': team.get('interceptions', 0), 'fumbles_lost': team.get('fumbles_lost', 0),
            # The team line has no offensive_touchdowns key when every touchdown was a blocked-kick return: that means zero.
            'offensive_td': team.get('offensive_touchdowns', 0) - team.get('observed_overtime_touchdowns', 0),
            'offensive_turnovers': team.get('turnovers', 0),
            'sack_yds': team.get('sack_yds', 0), 'pass_tgt': team.get('pass_tgt', 0),
            'pass_comp_receiving': team.get('pass_comp', 0),
            'pass_yds_receiving': team.get('pass_yds', 0),
        }
        mismatches = {key: (checks[key], expected[key]) for key in checks if checks[key] != expected[key]}
        if mismatches:
            raise AssertionError(f'pregame player/team stats do not reconcile for {side}: {mismatches}')
