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


def team_stats(drives, points, kickoff_events=()):
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
            enforcement = out.get('penalty_enforcement')
            if enforcement and enforcement.get('accepted'):
                offender = enforcement.get('offender_team')
                penalized_team = (play['state_before']['offense_team'] if offender == 'offense' else
                                  play['state_before']['defense_team'] if offender == 'defense' else None)
                if penalized_team is None:
                    raise ValueError(f"unsupported autonomous penalty team role: {offender!r}")
                charged = team(penalized_team)
                charged['penalties'] += 1
                charged['penalty_yards'] += int(round(enforcement['yards']))
            if enforcement is not None and not enforcement.get('play_counts', False):
                continue
            if ev in SCRIMMAGE_EVENTS:
                t['plays'] += 1
            if ev in ('pass_complete', 'pass_incomplete', 'interception') and part.get('receiver_id'):
                t['pass_tgt'] += 1
            yards = out['yards_gained'] or 0
            if ev == 'run' or (ev == 'fumble_lost' and part.get('rusher_id')):
                t['rush_att'] += 1
                t['rush_yds'] += _credited(play, _player_yards(play, 'rushing_yards', yards))
            elif ev in ('pass_complete', 'pass_incomplete', 'interception', 'sack'):
                if ev == 'sack':
                    t['sacks_taken'] += 1
                    t['sack_yds'] += yards
                else:
                    t['pass_att'] += 1
                    if ev == 'pass_complete':
                        t['pass_comp'] += 1
                        t['pass_yds'] += _credited(play, _player_yards(play, 'passing_yards', yards))
                        # Player receiving lines use this same fallback for ordinary
                        # completions. Do not omit them just because one fumble play
                        # carries explicit receiving yardage.
                        t['receiving_yds'] += _credited(play, _player_yards(play, 'receiving_yards', yards))
            if out['turnover'] and (ev in ('interception', 'fumble_lost') or out.get('fumble')):
                t['turnovers'] += 1
            if ev == 'interception':
                t['interceptions'] += 1
            if ev == 'fumble_lost':
                t['fumbles_lost'] += 1
            if out.get('fumble'):
                fumbler_side = part.get('fumbler_side')
                fumbler_team = fumbler_side if fumbler_side in points else play['state_before']['offense_team']
                team(fumbler_team)['fumbles'] += 1
                lost_team = out.get('fumble_lost_team')
                if lost_team is None and out.get('turnover'):
                    lost_team = fumbler_team
                if lost_team is not None:
                    if ev != 'fumble_lost':
                        team(lost_team)['fumbles_lost'] += 1
                    if lost_team != play['state_before']['offense_team']:
                        team(lost_team)['turnovers'] += 1
                recovery_team = out.get('fumble_recovery_team')
                if recovery_team not in points:
                    recovery_team = (play['state_before']['defense_team'] if out.get('turnover')
                                     else play['state_before']['offense_team'])
                recovered = team(recovery_team)
                recovered['fumble_recoveries'] += 1
                fumble_return_yards = out.get('fumble_return_yards')
                if fumble_return_yards is None and out.get('turnover'):
                    fumble_return_yards = out.get('return_yards')
                if fumble_return_yards is not None:
                    recovered['fumble_return_yards'] += int(fumble_return_yards)
            # Regular punts set `punt`; `punt_attempt` is only present on some
            # special-team outcomes (notably blocked kicks). Count either flag
            # once so ordinary punts are not omitted from the team boxscore.
            if out.get('punt') or out.get('punt_attempt'):
                t['punts'] += 1
                execution = out.get('special_teams_execution') or {}
                punt_distance = execution.get('distance_yards', execution.get('generated_punt_distance_yards'))
                if punt_distance is not None:
                    t['punt_yds'] += int(punt_distance)
            if out.get('punt_return'):
                return_team = play['state_before']['defense_team']
                returned = team(return_team)
                returned['punt_returns'] += 1
                returned['punt_return_yards'] += int(out.get('return_yards') or 0)
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
            last_play = d['plays'][-1] if d['plays'] else None
            offensive_scoring_play = (last_play and last_play['event_type'] in ('run', 'pass_complete')
                                      and last_play['outcome'].get('touchdown'))
            unassigned_overtime_offensive_td = (d.get('observed_overtime_drive') and not d['plays']
                                                and scorer == d['offense_team'])
            if scorer == d['offense_team'] and (offensive_scoring_play or unassigned_overtime_offensive_td):
                # Scrimmage touchdowns and observed no-play OT touchdowns are offensive; returns are not.
                scored['offensive_touchdowns'] += 1
            if last_play and last_play['outcome'].get('return_touchdown'):
                scored['return_touchdowns'] += 1
            if unassigned_overtime_offensive_td:
                # No player row exists for this observed OT score, so exclude it from player reconciliation.
                scored['observed_overtime_touchdowns'] += 1
        elif d['terminal'] == 'safety':
            scorer = (d['plays'][-1]['outcome'].get('scoring_team') if d['plays'] else None)
            if scorer is not None:
                team(scorer)['safeties'] += 1
        scoring = d.get('points_scored_on_drive') or {}
        try_result = scoring.get('try')
        if isinstance(try_result, dict):
            scoring_team = team(scoring.get('team', d['offense_team']))
            if try_result.get('kind') == 'extra_point':
                scoring_team['extra_point_att'] += 1
                scoring_team['extra_point_made'] += int(bool(try_result.get('made')))
            elif try_result.get('kind') == 'two_point':
                scoring_team['two_point_att'] += 1
                scoring_team['two_point_made'] += int(bool(try_result.get('made')))
    for event in kickoff_events:
        team(event['kicking_team'])['kickoffs'] += 1
        if event.get('result') == 'return' and event.get('returner_id') and not event.get('fair_catch'):
            returned = team(event['receiving_team'])
            returned['kickoff_returns'] += 1
            returned['kickoff_return_yards'] += int(event.get('return_yards') or 0)
        if event.get('terminal') == 'touchdown':
            scorer = event.get('scoring_team')
            if scorer is None:
                raise ValueError('kickoff touchdown is missing its scoring team')
            team(scorer)['touchdowns'] += 1
            team(scorer)['return_touchdowns'] += 1
        if event.get('terminal') == 'safety':
            scorer = event.get('scoring_team')
            if scorer is None:
                raise ValueError('kickoff safety is missing its scoring team')
            team(scorer)['safeties'] += 1
        flags = event.get('flags') or {}
        if flags.get('fumble'):
            fumbler_team = (event.get('participants') or {}).get('fumbler_side')
            fumbler_team = fumbler_team if fumbler_team in points else event['receiving_team']
            team(fumbler_team)['fumbles'] += 1
            lost_team = flags.get('fumble_lost_team')
            if lost_team is not None:
                team(lost_team)['fumbles_lost'] += 1
                team(lost_team)['turnovers'] += 1
            recovery_team = flags.get('fumble_recovery_team')
            if recovery_team in points:
                recovered = team(recovery_team)
                recovered['fumble_recoveries'] += 1
                if flags.get('fumble_return_yards') is not None:
                    recovered['fumble_return_yards'] += int(flags['fumble_return_yards'])
    for name, pts in points.items():
        team(name)['points'] = pts
    return {name: dict(sorted(t.items())) for name, t in sorted(teams.items())}


def _credited(play, yards):
    """Credit only the distance the ball can legally travel before becoming dead at either goal line."""
    if play['outcome']['touchdown']:
        return min(yards, play['state_before']['yardline_100'])
    if play['outcome'].get('safety'):
        return max(yards, play['state_before']['yardline_100'] - 100)
    return yards


def _player_yards(play, field, fallback):
    """Use the source's role-specific box-score field when supplied; otherwise retain transition yardage."""
    context = play.get('participants', {}).get('sampled_play_context') or {}
    value = context.get(field)
    if value is None:
        value = play.get('participants', {}).get(field)
    return fallback if value is None else int(value)


def player_lines(drives, kickoff_events=()):
    """Per-player passing, rushing, receiving and miscellaneous lines with attribution metadata."""
    lines = {}

    def line(pid, part, role):
        attribution = part.get('attribution', ATTRIBUTION)
        existing = lines.get(pid)
        if existing is not None and existing['attribution'] != attribution:
            raise ValueError(f'player {pid} has mixed attribution sources: '
                             f'{existing["attribution"]!r} and {attribution!r}')
        entry = lines.setdefault(pid, {'passing': defaultdict(int), 'rushing': defaultdict(int),
                                       'receiving': defaultdict(int), 'kicking': defaultdict(int),
                                       'returning': defaultdict(int), 'miscellaneous': defaultdict(int),
                                       'attribution': attribution})
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
            enforcement = out.get('penalty_enforcement')
            offender_id = enforcement.get('offender_id') if enforcement and enforcement.get('accepted') else None
            if offender_id:
                p = line(offender_id, part, 'penalty_offender')['miscellaneous']
                p['penalties'] += 1
                p['penalty_yards'] += int(round(enforcement['yards']))
            if enforcement is not None and not enforcement.get('play_counts', False):
                continue
            if (ev == 'run' or (ev == 'fumble_lost' and part.get('rusher_id'))) and part['rusher_id']:
                r = line(part['rusher_id'], part, 'rusher')['rushing']
                r['att'] += 1
                r['yds'] += _credited(play, _player_yards(play, 'rushing_yards', yards))
                r['td'] += int(ev == 'run' and td and not out.get('return_touchdown'))
            if ev == 'fumble_lost':
                role = 'rusher' if part.get('rusher_id') else 'passer'
                fumbler = part.get(f'{role}_id')
                if fumbler:
                    line(fumbler, part, role)['miscellaneous']['fumbles_lost'] += 1
            if out.get('fumble'):
                fumbler = part.get('fumbler_id') or part.get('rusher_id') or part.get('receiver_id') or part.get('passer_id')
                if fumbler:
                    fumble_stats = line(fumbler, part, 'fumbler')['miscellaneous']
                    fumble_stats['fumbles'] += 1
                    fumbler_side = part.get('fumbler_side')
                    lost_team = out.get('fumble_lost_team')
                    if ev != 'fumble_lost' and (lost_team == fumbler_side
                                                   or (lost_team is None and out.get('turnover'))):
                        fumble_stats['fumbles_lost'] += 1
                recoverer = part.get('recoverer_id') or out.get('recoverer_id')
                if recoverer:
                    recovery_stats = line(recoverer, part, 'recoverer')['miscellaneous']
                    recovery_stats['fumble_recoveries'] += 1
                    fumble_return_yards = out.get('fumble_return_yards')
                    if fumble_return_yards is not None:
                        recovery_stats['fumble_return_yards'] += int(fumble_return_yards)
                        chain = out.get('turnover_chain') or {}
                        returner = (part.get('post_recovery_returner_id')
                                    or chain.get('returner_id')
                                    or part.get('returner_id') or recoverer)
                        role = 'returner' if part.get('returner_id') == returner else 'recoverer'
                        recovery = line(returner, part, role)['returning']
                        recovery['fumble_returns'] += 1
                        recovery['fumble_return_yds'] += int(fumble_return_yards)
                        recovery['td'] += int(bool(out.get('return_touchdown')))
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
                    p['yds'] += _credited(play, _player_yards(play, 'passing_yards', yards))
                    p['td'] += int(td and not out.get('return_touchdown'))
            if ev in ('pass_complete', 'pass_incomplete', 'interception') and part['receiver_id']:
                c = line(part['receiver_id'], part, 'receiver')['receiving']
                c['tgt'] += 1
                if ev == 'pass_complete':
                    c['rec'] += 1
                    c['yds'] += _credited(play, _player_yards(play, 'receiving_yards', yards))
                    c['td'] += int(td and not out.get('return_touchdown'))
            if ev == 'punt' and part.get('punter_id'):
                k = line(part['punter_id'], part, 'punter')['kicking']
                k['punt_att'] += 1
                execution = out.get('special_teams_execution') or {}
                punt_distance = execution.get('distance_yards', execution.get('generated_punt_distance_yards'))
                if punt_distance is not None:
                    k['punt_yds'] += int(punt_distance)
            if ev == 'field_goal_attempt' and part.get('kicker_id'):
                k = line(part['kicker_id'], part, 'kicker')['kicking']
                k['fg_att'] += 1
                k['fg_made'] += int(out.get('field_goal_result') == 'made')
            blocked = out.get('blocked_kick')
            if blocked and blocked.get('returner_id'):
                r = line(blocked['returner_id'], part, 'returner')['returning']
                r['blocked_kick_returns'] += 1
                r['blocked_kick_return_yds'] += int(blocked.get('return_yards') or 0)
                r['td'] += int(bool(out.get('return_touchdown')))
            if ev == 'punt' and out.get('punt_return') and part.get('returner_id'):
                r = line(part['returner_id'], part, 'returner')['returning']
                r['punt_returns'] += 1
                r['punt_return_yds'] += int(out.get('return_yards') or 0)
                r['td'] += int(bool(out.get('return_touchdown')))
    for event in kickoff_events:
        part = event.get('participants') or {}
        kicker_id = part.get('kicker_id')
        if kicker_id:
            line(kicker_id, part, 'kicker')['kicking']['kickoffs'] += 1
        flags = event.get('flags') or {}
        if flags.get('fumble'):
            fumbler = part.get('fumbler_id') or part.get('muffing_returner_id')
            if fumbler:
                fumble_stats = line(fumbler, part, 'fumbler')['miscellaneous']
                fumble_stats['fumbles'] += 1
                if flags.get('fumble_lost_team') == part.get('fumbler_side'):
                    fumble_stats['fumbles_lost'] += 1
            recoverer = part.get('recoverer_id') or flags.get('recoverer_id')
            if recoverer:
                recovery_stats = line(recoverer, part, 'recoverer')['miscellaneous']
                recovery_stats['fumble_recoveries'] += 1
                yards = flags.get('fumble_return_yards')
                if yards is not None:
                    recovery_stats['fumble_return_yards'] += int(yards)
                    returner = (part.get('post_recovery_returner_id')
                                or part.get('returner_id') or recoverer)
                    role = 'returner' if part.get('returner_id') == returner else 'recoverer'
                    returning = line(returner, part, role)['returning']
                    returning['fumble_returns'] += 1
                    returning['fumble_return_yds'] += int(yards)
                    returning['td'] += int(bool(flags.get('return_touchdown')))
        pid = event.get('returner_id')
        if event.get('result') == 'return' and pid and not event.get('fair_catch'):
            entry = lines.setdefault(pid, {'passing': defaultdict(int), 'rushing': defaultdict(int),
                                           'receiving': defaultdict(int), 'kicking': defaultdict(int),
                                           'returning': defaultdict(int), 'miscellaneous': defaultdict(int),
                                           'attribution': 'autonomous_execution'})
            for field in ('name', 'position', 'team', 'side'):
                value = part.get('returner_' + field)
                if value is not None:
                    entry['player_' + field] = value
            r = entry['returning']
            r['kickoff_returns'] += 1
            r['kickoff_return_yds'] += int(event.get('return_yards') or 0)
            r['td'] += int(event.get('terminal') == 'touchdown')
    for drive in drives:
        scoring = drive.get('points_scored_on_drive') or {}
        try_result = scoring.get('try')
        if not isinstance(try_result, dict):
            continue
        part = {'attribution': 'autonomous_execution'}
        if try_result.get('kind') == 'extra_point' and try_result.get('kicker_id'):
            details = try_result.get('kicker_details') or {}
            part.update({f'try_kicker_{field}': details.get(field)
                         for field in ('name', 'position', 'team', 'side')})
            k = line(try_result['kicker_id'], part, 'try_kicker')['kicking']
            k['extra_point_att'] += 1
            k['extra_point_made'] += int(bool(try_result.get('made')))
        elif try_result.get('kind') == 'two_point':
            for pid in try_result.get('try_actor_ids', ()):
                if pid:
                    details = try_result.get('try_player_details') or {}
                    prefix = next((name for name in ('rusher', 'receiver', 'passer')
                                   if details.get(name + '_id') == pid), None)
                    actor_part = dict(part)
                    if prefix:
                        actor_part.update({f'try_actor_{field}': details.get(prefix + '_' + field)
                                           for field in ('name', 'position', 'team', 'side')})
                    misc = line(pid, actor_part, 'try_actor')['miscellaneous']
                    misc['two_point_att'] += 1
                    misc['two_point_made'] += int(bool(try_result.get('made')))
    out = []
    for pid in sorted(lines):
        entry = {'player_id': pid, 'attribution': lines[pid]['attribution']}
        for field in ('player_name', 'player_position', 'player_team', 'player_side'):
            if field in lines[pid]:
                entry[field] = lines[pid][field]
        for cat in ('passing', 'rushing', 'receiving', 'kicking', 'returning', 'miscellaneous'):
            if lines[pid][cat]:
                entry[cat] = dict(sorted(lines[pid][cat].items()))
        out.append(entry)
    return out


def compute(drives, points, kickoff_events=()):
    """The game's stat block: team lines, player lines, and the label that says what the player lines are."""
    players = player_lines(drives, kickoff_events)
    attributions = {row['attribution'] for row in players}
    if len(attributions) > 1:
        raise ValueError(f'game mixes player attribution sources: {sorted(attributions)}')
    attribution = next(iter(attributions)) if attributions else ATTRIBUTION
    team_lines = team_stats(drives, points, kickoff_events)
    if attribution in ('pregame_depth_chart_role_sample', 'pre_event_selection', 'autonomous_execution'):
        _verify_pregame_reconciliation(team_lines, players)
    note = ('Team and player lines are reconciled from the actors and outcomes generated by the autonomous executor.'
            if attribution == 'autonomous_execution' else
            'Team play outcomes come from historical E1 samples. Participants were selected before the outcome from the '
            'frozen pregame roster, using the enabled target-role and share priors; these lines are allocations, not '
            'player-conditioned outcome projections.'
            if attribution == 'pre_event_selection' else
            'Team play outcomes come from historical E1 samples. The passer is the frozen QB1; eligible receiver and '
            'ball-carrier positions follow historical shares, then players are sampled by depth rank. Individual lines are '
            'allocations, not player-specific projections.'
            if attribution == 'pregame_depth_chart_role_sample' else
            'Players are the participants of the observed plays each simulated play was sampled from. They are not this '
            'game\'s roster or lineup, and these lines are not evidence about those players.')
    return {
        'team': team_lines,
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
        }
        if 'receiving_yds' in team:
            checks['receiving_yds'] = sum(player.get('receiving', {}).get('yds', 0) for player in rows)
            expected['receiving_yds'] = team['receiving_yds']
        else:
            checks['pass_yds_receiving'] = sum(player.get('receiving', {}).get('yds', 0) for player in rows)
            expected['pass_yds_receiving'] = team.get('pass_yds', 0)
        mismatches = {key: (checks[key], expected[key]) for key in checks if checks[key] != expected[key]}
        if mismatches:
            raise AssertionError(f'pregame player/team stats do not reconcile for {side}: {mismatches}')
