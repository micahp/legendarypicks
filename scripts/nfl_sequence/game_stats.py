"""Team and player lines for one generated game, computed from its plays.

Pregame games assign the frozen QB1 and sample eligible backs and receivers from the frozen depth chart. Other research
modes retain observed-play participants. Pregame player totals reconcile to the generated team totals, but they are role
allocations rather than player-specific performance projections or a complete lineup. Every line carries `attribution`.

Yards credited on a touchdown are capped at the distance to the goal line in the simulation. The observed yards describe
the observed play, not the simulated spot, and a line that said otherwise would contradict the field.
"""
from collections import defaultdict

QUARTER_LENGTH = 900
OVERTIME_LENGTH = 600  # the same value as game_state.OVERTIME_LENGTH: one 10-minute period in the regular season
ATTRIBUTION = 'sampled_observed_play'
SCRIMMAGE_EVENTS = ('run', 'pass_complete', 'pass_incomplete', 'sack', 'interception', 'fumble_lost')
TEAM_COUNT_FIELDS = (
    'first_downs', 'first_downs_run', 'first_downs_pass', 'first_downs_penalty', 'first_downs_other',
    'down_1_plays', 'down_1_successful_plays', 'down_2_plays', 'down_2_successful_plays',
    'down_3_plays', 'down_3_successful_plays', 'down_4_plays', 'down_4_successful_plays',
    'down_3_attempts', 'down_3_conversions', 'down_4_attempts', 'down_4_conversions',
    'drives_without_first_down', 'drives_with_first_down', 'three_and_outs',
    'turnover_drives', 'scoring_drives', 'offense_points',
)


def _elapsed(quarter, clock):
    """Game seconds elapsed at (quarter, clock). Overtime is a 600-second period that starts after 3,600 seconds."""
    if quarter > 4:
        return 4 * QUARTER_LENGTH + (quarter - 5) * OVERTIME_LENGTH + (OVERTIME_LENGTH - clock)
    return (quarter - 1) * QUARTER_LENGTH + (QUARTER_LENGTH - clock)


def first_down_result(play):
    """Return the earned first-down source from the play's recorded transition, or None.

    A first down requires the same offense to retain possession and the next state to
    begin at down one. Touchdowns do not count as first downs. This intentionally uses
    state_after rather than the next play, so the result remains available at drive ends.
    """
    before = play.get('state_before') or {}
    after = play.get('state_after') or {}
    outcome = play.get('outcome') or {}
    if (before.get('offense_team') not in ('A', 'B')
            or before.get('offense_team') != after.get('offense_team')
            or after.get('down') != 1 or outcome.get('touchdown') or outcome.get('safety')):
        return None
    penalty = outcome.get('penalty')
    if penalty:
        return 'penalty'
    event = play.get('event_type')
    participants = play.get('participants') or {}
    if event == 'run' or (event == 'fumble_lost' and participants.get('rusher_id')):
        return 'run'
    if event in ('pass_complete', 'pass_incomplete', 'interception', 'sack'):
        return 'pass'
    return 'other'


def _is_successful_play(play):
    """Conventional down-based success: 40% on first, 60% on second, chains on 3rd/4th.

    A touchdown is successful on any down. Penalty-only events are excluded until
    penalty enforcement is modeled as an explicit state transition.
    """
    before = play.get('state_before') or {}
    outcome = play.get('outcome') or {}
    if outcome.get('penalty'):
        return False
    if outcome.get('touchdown'):
        return True
    try:
        down = int(before.get('down'))
        to_go = max(0, int(before.get('yards_to_go')))
        yards = int(outcome.get('yards_gained') or 0)
    except (TypeError, ValueError):
        return False
    if down == 1:
        return yards >= 0.4 * to_go
    if down == 2:
        return yards >= 0.6 * to_go
    if down in (3, 4):
        return first_down_result(play) is not None
    return False


def clock_reconciliation(record):
    """Reconcile play-clock possession, drive windows, and kickoff time with elapsed game time."""
    drives = record.get('drives') or []
    if not drives:
        return {'status': 'unavailable', 'reason': 'record has no drives'}
    needed = ('quarter_start', 'clock_start', 'end_quarter', 'end_clock', 'offense_team')
    missing = sorted({key for d in drives for key in needed if key not in d})
    if missing:
        return {'status': 'unavailable', 'reason': 'drive records lack ' + ', '.join(missing)}
    drive_windows = sum(_elapsed(d['end_quarter'], d['end_clock']) -
                        _elapsed(d['quarter_start'], d['clock_start']) for d in drives)
    possession = 0
    missing_play_clock = False
    for drive in drives:
        plays = drive.get('plays') or []
        if not plays and _elapsed(drive['end_quarter'], drive['end_clock']) > _elapsed(
                drive['quarter_start'], drive['clock_start']):
            missing_play_clock = True
        for play in plays:
            before, after = play.get('state_before') or {}, play.get('state_after') or {}
            if not all(key in before for key in ('quarter', 'clock_seconds')) or not all(
                    key in after for key in ('quarter', 'clock_seconds')):
                missing_play_clock = True
                continue
            seconds = _elapsed(after['quarter'], after['clock_seconds']) - _elapsed(
                before['quarter'], before['clock_seconds'])
            if seconds < 0:
                missing_play_clock = True
                continue
            possession += seconds
    kickoffs = record.get('kickoffs') or []
    kickoff = sum(int(k['clock_before']) - int(k['clock_after']) for k in kickoffs)  # the clock the kickoff actually used
    sampled = sum(int(k.get('runoff_seconds') or 0) for k in kickoffs)
    overrun = sum(int(k.get('runoff_overrun_seconds') or 0) for k in kickoffs)
    last = drives[-1]
    # the game ends at the later of the last drive's end and the last kickoff's end: a final kickoff can run the clock to zero
    ends = [_elapsed(last['end_quarter'], last['end_clock'])] + [_elapsed(k['quarter'], k['clock_after']) for k in kickoffs]
    elapsed = max(ends)
    gap = elapsed - possession - kickoff
    drive_gap = elapsed - drive_windows - kickoff
    regulation = elapsed <= 4 * QUARTER_LENGTH
    reconciled = gap == 0 and drive_gap == 0 and not missing_play_clock
    return {'status': 'reconciled' if reconciled else 'unreconciled', 'regulation_only': regulation,
            'possession_seconds_total': possession, 'kickoff_seconds_total': kickoff,
            'drive_window_seconds_total': drive_windows,
            'kickoff_sampled_runoff_seconds': sampled, 'kickoff_overrun_seconds': overrun,
            'elapsed_game_clock_seconds': elapsed, 'unassigned_seconds': gap,
            'drive_window_unassigned_seconds': drive_gap,
            'possession_matches_drive_windows': possession == drive_windows,
            'play_clock_complete': not missing_play_clock}


def play_metric_coverage(drives):
    """Check that every scrimmage play has the state and gain fields needed for down metrics."""
    scrimmage_plays = 0
    missing = []
    for drive in drives or []:
        for index, play in enumerate(drive.get('plays') or [], 1):
            if play.get('event_type') not in SCRIMMAGE_EVENTS:
                continue
            scrimmage_plays += 1
            before = play.get('state_before') or {}
            after = play.get('state_after') or {}
            outcome = play.get('outcome') or {}
            absent = ([f'state_before.{key}' for key in ('offense_team', 'down', 'yards_to_go') if key not in before]
                      + [f'state_after.{key}' for key in ('offense_team', 'down') if key not in after]
                      + (['outcome.yards_gained'] if 'yards_gained' not in outcome else []))
            if absent:
                missing.append({'drive': drive.get('index'), 'play': play.get('sequence', index),
                                'fields': absent})
    return {'status': 'complete' if not missing else 'incomplete',
            'scrimmage_plays': scrimmage_plays, 'plays_with_missing_metric_fields': len(missing),
            'examples': missing[:10]}


def team_stats(drives, points):
    """Per-team counts and rates derived from recorded play states and drive outcomes."""
    teams = {}
    possession_clock_complete = {}

    def team(name):
        return teams.setdefault(name, defaultdict(int))

    for d in drives:
        t = team(d['offense_team'])
        possession_clock_complete.setdefault(d['offense_team'], True)
        fg_attempt_recorded = False
        fg_result_recorded = False
        t['drives'] += 1
        t['drive_terminal_' + str(d.get('terminal') or 'unknown')] += 1
        end = _elapsed(d['end_quarter'], d['end_clock'])
        t['drive_window_seconds'] += end - _elapsed(d['quarter_start'], d['clock_start'])
        drive_first_downs = 0
        drive_scrimmage_plays = 0
        drive_turnovers = 0
        for play in d['plays']:
            ev, out, part = play['event_type'], play['outcome'], play['participants']
            before = play.get('state_before') or {}
            after = play.get('state_after') or {}
            play_seconds = None
            if (all(key in before for key in ('quarter', 'clock_seconds'))
                    and all(key in after for key in ('quarter', 'clock_seconds'))):
                try:
                    play_seconds = _elapsed(after['quarter'], after['clock_seconds']) - _elapsed(
                        before['quarter'], before['clock_seconds'])
                except (TypeError, ValueError):
                    pass
            if play_seconds is not None and play_seconds >= 0:
                t['possession_seconds'] += play_seconds
            else:
                possession_clock_complete[d['offense_team']] = False
            if ev in SCRIMMAGE_EVENTS:
                drive_scrimmage_plays += 1
                try:
                    down = int(before.get('down'))
                except (TypeError, ValueError):
                    down = None
                if down in (1, 2, 3, 4):
                    t[f'down_{down}_plays'] += 1
                    t[f'down_{down}_successful_plays'] += int(_is_successful_play(play))
                if down in (3, 4):
                    t[f'down_{down}_attempts'] += 1
                    t[f'down_{down}_conversions'] += int(first_down_result(play) is not None)
            first_down = first_down_result(play)
            if first_down:
                drive_first_downs += 1
                t['first_downs'] += 1
                t[f'first_downs_{first_down}'] += 1
            if ev in SCRIMMAGE_EVENTS:
                t['plays'] += 1
            if ev == 'fumble_lost' and not part.get('rusher_id'):
                t['other_fumble_scrimmage_plays'] += 1
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
                        if 'receiving_yards' in (part.get('sampled_play_context') or {}):
                            t['receiving_yds'] += _credited(play, _player_yards(play, 'receiving_yards', yards))
            if out['turnover'] and ev in ('interception', 'fumble_lost'):
                t['turnovers'] += 1
                drive_turnovers += 1
            if ev == 'interception':
                t['interceptions'] += 1
            if ev == 'fumble_lost':
                t['fumbles_lost'] += 1
            # Regular punts set `punt`; `punt_attempt` is only present on some
            # special-team outcomes (notably blocked kicks). Count either flag
            # once so ordinary punts are not omitted from the team boxscore.
            if out.get('punt') or out.get('punt_attempt'):
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
        if drive_turnovers:
            t['turnover_drives'] += 1
        if drive_first_downs == 0:
            t['drives_without_first_down'] += 1
        else:
            t['drives_with_first_down'] += 1
        if d.get('terminal') == 'punt' and drive_scrimmage_plays == 3 and drive_first_downs == 0:
            t['three_and_outs'] += 1
        scoring = d.get('points_scored_on_drive') or {}
        if scoring.get('team') == d['offense_team'] and int(scoring.get('points') or 0) > 0:
            t['scoring_drives'] += 1
        if scoring.get('team') == d['offense_team']:
            t['offense_points'] += int(scoring.get('points') or 0)
        if d['field_goal_made'] is not None:
            if not fg_attempt_recorded:
                # Compatibility with records that keep the kick result only on the drive.
                t['fg_att'] += 1
            if not fg_result_recorded:
                t['fg_made'] += int(d['field_goal_made'])
        if d['terminal'] == 'touchdown':
            scorer = d.get('touchdown_scored_by')
            if scorer not in ('A', 'B'):
                raise ValueError('touchdown drive missing valid touchdown_scored_by')
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
            if unassigned_overtime_offensive_td:
                # No player row exists for this observed OT score, so exclude it from player reconciliation.
                scored['observed_overtime_touchdowns'] += 1
        if scoring.get('team') in ('A', 'B'):
            scored = team(scoring['team'])
            scored['score_ledger_points'] += int(scoring.get('points') or 0)
            if d.get('terminal') == 'touchdown':
                scored['touchdown_points'] += 6
                scored['try_points'] += int(scoring.get('points') or 0) - 6
            elif d.get('terminal') == 'safety':
                scored['safety_points'] += int(scoring.get('points') or 0)
            else:
                scored['other_score_points'] += int(scoring.get('points') or 0)
    for name, pts in points.items():
        team(name)['points'] = pts
    for name, complete in possession_clock_complete.items():
        if not complete:
            teams[name]['possession_seconds'] = None
    for stats in teams.values():
        for field in TEAM_COUNT_FIELDS:
            stats.setdefault(field, 0)
    return {name: derive_team_rates(dict(sorted(t.items()))) for name, t in sorted(teams.items())}


def derive_team_rates(stats):
    """Add explicitly defined per-game rates to a team count line."""
    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None

    drives = stats.get('drives', 0)
    pass_attempts = stats.get('pass_att', 0)
    dropbacks = pass_attempts + stats.get('sacks_taken', 0)
    stats['plays_per_drive'] = ratio(stats.get('plays', 0), drives)
    stats['drive_window_seconds_per_drive'] = ratio(stats.get('drive_window_seconds', 0), drives)
    stats['points_per_drive'] = ratio(stats.get('offense_points', 0), drives)
    stats['scoring_drive_rate'] = ratio(stats.get('scoring_drives', 0), drives)
    stats['completion_percentage'] = ratio(stats.get('pass_comp', 0), pass_attempts)
    stats['yards_per_attempt'] = ratio(stats.get('pass_yds', 0), pass_attempts)
    stats['sack_rate'] = ratio(stats.get('sacks_taken', 0), dropbacks)
    stats['turnovers_per_drive'] = ratio(stats.get('turnovers', 0), drives)
    stats['turnover_drive_rate'] = ratio(stats.get('turnover_drives', 0), drives)
    stats['turnovers_per_dropback'] = ratio(stats.get('turnovers', 0), dropbacks)
    stats['third_down_conversion_rate'] = ratio(
        stats.get('down_3_conversions', stats.get('third_down_conversions', 0)),
        stats.get('down_3_attempts', stats.get('third_down_attempts', 0)))
    stats['fourth_down_conversion_rate'] = ratio(
        stats.get('down_4_conversions', stats.get('fourth_down_conversions', 0)),
        stats.get('down_4_attempts', stats.get('fourth_down_attempts', 0)))
    successful = sum(stats.get(f'down_{down}_successful_plays', 0) for down in (1, 2, 3, 4))
    stats['offensive_success_rate'] = ratio(successful, stats.get('plays', 0))
    for down in (1, 2, 3, 4):
        stats[f'down_{down}_success_rate'] = ratio(stats.get(f'down_{down}_successful_plays', 0),
                                                   stats.get(f'down_{down}_plays', 0))
    return stats


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
    return fallback if value is None else int(value)


def player_lines(drives):
    """Per-player passing, rushing, receiving and miscellaneous lines with attribution metadata."""
    lines = {}

    def line(pid, part, role):
        attribution = part.get('attribution', ATTRIBUTION)
        existing = lines.get(pid)
        if existing is not None and existing['attribution'] != attribution:
            raise ValueError(f'player {pid} has mixed attribution sources: '
                             f'{existing["attribution"]!r} and {attribution!r}')
        entry = lines.setdefault(pid, {'passing': defaultdict(int), 'rushing': defaultdict(int),
                                       'receiving': defaultdict(int), 'miscellaneous': defaultdict(int),
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
            if (ev == 'run' or (ev == 'fumble_lost' and part.get('rusher_id'))) and part['rusher_id']:
                r = line(part['rusher_id'], part, 'rusher')['rushing']
                r['att'] += 1
                r['yds'] += _credited(play, _player_yards(play, 'rushing_yards', yards))
                r['td'] += int(ev == 'run' and td)
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
                    p['yds'] += _credited(play, _player_yards(play, 'passing_yards', yards))
                    p['td'] += int(td)
            if ev in ('pass_complete', 'pass_incomplete', 'interception') and part['receiver_id']:
                c = line(part['receiver_id'], part, 'receiver')['receiving']
                c['tgt'] += 1
                if ev == 'pass_complete':
                    c['rec'] += 1
                    c['yds'] += _credited(play, _player_yards(play, 'receiving_yards', yards))
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
    if len(attributions) > 1:
        raise ValueError(f'game mixes player attribution sources: {sorted(attributions)}')
    attribution = next(iter(attributions)) if attributions else ATTRIBUTION
    if attribution in ('pregame_depth_chart_role_sample', 'pre_event_selection'):
        _verify_pregame_reconciliation(team_stats(drives, points), players)
    note = ('Team play outcomes come from historical E1 samples. Participants were selected before the outcome from the '
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
        'team': team_stats(drives, points),
        'player': players,
        'player_attribution': attribution,
        'player_note': note,
        'team_stat_semantics': {
            'possession_seconds': 'Sum of per-play game-clock intervals for this offense; separately reconciled against drive windows, kickoffs, and elapsed game time.',
            'drive_window_seconds': 'Sum of elapsed clock intervals from each drive start state to its end state.',
            'first_downs': 'Earned when the post-play state begins a new first down for the same offense; touchdowns are excluded. Penalty first downs are classified separately when modeled.',
            'first_downs_run/pass/penalty/other': 'Source breakdowns of earned first downs; the components sum to first_downs.',
            'third_down_conversions': 'Third-down scrimmage plays followed by a new first down for the same offense; touchdowns are not counted as first downs.',
            'fourth_down_conversions': 'Fourth-down go-for-it scrimmage plays followed by a new first down for the same offense; punts and field goals are excluded.',
            'offensive_success_rate': 'A successful play gains at least 40% of yards-to-go on first down, 60% on second down, or earns a new first down on third/fourth; touchdowns count as successful plays.',
            'try_points': 'Touchdown drive ledger points above six; not a try-attempt count.',
            'other_score_points': 'Non-touchdown, non-safety score-ledger points, including field goals.',
        },
        'player_yardage_fallbacks': {field: sum(1 for d in drives for play in d['plays']
            if ((field == 'rushing_yards' and (play['event_type'] == 'run' or (play['event_type'] == 'fumble_lost' and play['participants'].get('rusher_id'))))
                or (field in ('passing_yards', 'receiving_yards') and play['event_type'] == 'pass_complete'))
            and (play['participants'].get('sampled_play_context') or {}).get(field) is None)
            for field in ('rushing_yards', 'passing_yards', 'receiving_yards')},
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
