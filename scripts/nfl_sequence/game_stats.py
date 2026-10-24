"""Team and player lines for one generated game, computed from its plays.

Player lines use the participants each play carries. Those are the passer, rusher and receiver of the observed play the
simulated play was sampled from. They are not this game's roster or lineup, and the lines are not evidence about those
players. Every line says so with `attribution`.

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
        t['drives'] += 1
        end = _elapsed(d['end_quarter'], d['end_clock'])
        t['possession_seconds'] += end - _elapsed(d['quarter_start'], d['clock_start'])
        for play in d['plays']:
            ev, out = play['event_type'], play['outcome']
            if ev in SCRIMMAGE_EVENTS:
                t['plays'] += 1
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
            if out['punt']:
                t['punts'] += 1
        if d['terminal'] == 'turnover_on_downs':
            t['turnovers_on_downs'] += 1
        if d['field_goal_made'] is not None:
            t['fg_att'] += 1
            t['fg_made'] += int(d['field_goal_made'])
        if d['terminal'] == 'touchdown':
            t['touchdowns'] += 1
    for name, pts in points.items():
        team(name)['points'] = pts
    return {name: dict(sorted(t.items())) for name, t in sorted(teams.items())}


def _credited(play, yards):
    """Yards credited to a play: the observed yards, capped at the goal line when the play is a touchdown."""
    if play['outcome']['touchdown']:
        return min(yards, play['state_before']['yardline_100'])
    return yards


def player_lines(drives):
    """Per-player passing, rushing and receiving lines, each marked with the attribution label."""
    lines = {}

    def line(pid):
        return lines.setdefault(pid, {'passing': defaultdict(int), 'rushing': defaultdict(int),
                                      'receiving': defaultdict(int)})

    for d in drives:
        for play in d['plays']:
            ev, out, part = play['event_type'], play['outcome'], play['participants']
            yards = out['yards_gained'] or 0
            td = bool(out['touchdown'])
            if ev == 'run' and part['rusher_id']:
                r = line(part['rusher_id'])['rushing']
                r['att'] += 1
                r['yds'] += _credited(play, yards)
                r['td'] += int(td)
            if ev in ('pass_complete', 'pass_incomplete', 'interception', 'sack') and part['passer_id']:
                p = line(part['passer_id'])['passing']
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
            if ev == 'pass_complete' and part['receiver_id']:
                c = line(part['receiver_id'])['receiving']
                c['rec'] += 1
                c['yds'] += _credited(play, yards)
                c['td'] += int(td)
    out = []
    for pid in sorted(lines):
        entry = {'player_id': pid, 'attribution': ATTRIBUTION}
        for cat in ('passing', 'rushing', 'receiving'):
            if lines[pid][cat]:
                entry[cat] = dict(sorted(lines[pid][cat].items()))
        out.append(entry)
    return out


def compute(drives, points):
    """The game's stat block: team lines, player lines, and the label that says what the player lines are."""
    return {
        'team': team_stats(drives, points),
        'player': player_lines(drives),
        'player_attribution': ATTRIBUTION,
        'player_note': ('Players are the participants of the observed plays each simulated play was sampled from. '
                        'They are '
                        'not this game\'s roster or lineup, and these lines are not evidence about those players.'),
    }
