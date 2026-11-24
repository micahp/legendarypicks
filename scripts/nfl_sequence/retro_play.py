"""Authored retro 11-on-11 pass play. Not an NFL forecasting model.

Coordinates are yards from the offense's line of scrimmage; +x attacks the
opponent's goal, y is lateral. Movement and gameplay attributes are authored
shared defaults, not individual NFL measurements. No historical result is read.
"""
import copy
import json
import math
import random

import game_stats
import live_participation
import participation_field
import pregame_snapshot
import reducer
import roster_preflight
import v1_complete_roster

DT = 0.2
WIDTH = 26.65
DEFAULTS = {'speed': 6.0, 'read': 0.6, 'throw_accuracy': 0.65, 'catch': 0.7,
            'coverage': 0.6, 'block': 0.6, 'rush': 0.6}
DEFENSE_ROLES = ['LDE', 'LDT', 'RDT', 'RDE', 'WLB', 'MLB', 'SLB', 'LCB', 'RCB', 'SS', 'FS']


def _move(p, target, dt, factor=1.0):
    dx, dy = target[0] - p['x'], target[1] - p['y']
    dist = math.hypot(dx, dy)
    amount = min(dist, max(0.0, p['ratings']['speed'] * dt * factor))
    if dist:
        p['x'] += dx / dist * amount
        p['y'] = max(-WIDTH, min(WIDTH, p['y'] + dy / dist * amount))


def _distance(a, b):
    return math.hypot(a['x'] - b['x'], a['y'] - b['y'])


def make_lineups(snapshot, resolved, field, seed, ratings=None):
    """Choose MIN 11 personnel using the existing field; SF uses supplied 4-3 roles."""
    ratings = ratings or {}
    offense, defense = snapshot['rosters']['away'], snapshot['rosters']['home']
    if offense['team'] != 'MIN' or defense['team'] != 'SF':
        raise ValueError('retro_demo_requires_MIN_SF')
    picked = live_participation.advance(field, team='MIN', season=2026, resolved=resolved['away'],
                                        roster=offense['players'], group='11', seed=seed)
    allowed = v1_complete_roster.eligible_ids(resolved['away'])
    roles = {picked['qb1']: 'QB', **picked['slots']}
    for role in ('LT', 'LG', 'C', 'RG', 'RT'):
        candidates = [p for p in offense['players'] if p['gsis_id'] in allowed and p['gsis_id'] not in roles
                      and p['pos_abb'] == role and type(p['pos_rank']) is int and p['pos_rank'] > 0]
        if not candidates:
            raise ValueError('retro_missing_offensive_line:' + role)
        rank = min(p['pos_rank'] for p in candidates)
        best = {p['gsis_id'] for p in candidates if p['pos_rank'] == rank}
        if len(best) != 1:
            raise ValueError('retro_ambiguous_offensive_line:' + role)
        roles[best.pop()] = role
    defenders = live_participation.defense_lineup(resolved=resolved['home'], roster=defense['players'],
                                                   positions=DEFENSE_ROLES)['players']
    names = {p['gsis_id']: p['player_name'] for side in (offense, defense) for p in side['players']}
    def player(pid, role, side, x, y, assignment):
        attrs = dict(DEFAULTS)
        for key, value in ratings.get(pid, {}).items():
            if key not in attrs or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('retro_invalid_rating:' + str(key))
            if not (2 <= value <= 10 if key == 'speed' else 0 <= value <= 1):
                raise ValueError('retro_rating_out_of_range:' + str(key))
            attrs[key] = float(value)
        return {'id': pid, 'name': names[pid], 'role': role, 'side': side, 'x': float(x), 'y': float(y),
                'assignment': assignment, 'state': 'ALIGN', 'ratings': attrs}
    out = []
    qb = next(pid for pid, role in roles.items() if role == 'QB')
    out.append(player(qb, 'QB', 'offense', -5, 0, 'QB scan'))
    for y, role in zip((-2, -1, 0, 1, 2), ('LT', 'LG', 'C', 'RG', 'RT')):
        out.append(player(next(pid for pid, r in roles.items() if r == role), role, 'offense', 0, y, 'pass protect'))
    skill = {role: sorted(pid for pid, r in roles.items() if r == role) for role in ('RB', 'TE', 'WR')}
    out.append(player(skill['RB'][0], 'RB', 'offense', -5, -3, 'flat route'))
    out.append(player(skill['TE'][0], 'TE', 'offense', -1, 4, 'seam route'))
    for pid, y, route in zip(skill['WR'], (-17, -8, 17), ('go route', 'cross route', 'out route')):
        out.append(player(pid, 'WR', 'offense', -1 if route == 'cross route' else 0, y, route))
    for idx, (pid, role) in enumerate(defenders.items()):
        if idx < 4:
            x, y, task = 1.5, (-2.4, -0.8, 0.8, 2.4)[idx], 'rush QB'
        elif idx < 7:
            x, y, task = 5, (-5, 0, 5)[idx - 4], 'cover'
        elif idx < 9:
            x, y, task = 4, (-17, 17)[idx - 7], 'cover'
        else:
            x, y, task = 10, (-8, 8)[idx - 9], 'cover'
        out.append(player(pid, role, 'defense', x, y, task))
    if len(out) != 22 or len({p['id'] for p in out}) != 22:
        raise ValueError('retro_lineup_not_22_distinct_players')
    return out, picked


def _snapshot(players, ball, tick, event, decision):
    return {'tick': tick, 'time': round(tick * DT, 2), 'players': [
        {k: p[k] for k in ('id', 'name', 'role', 'side', 'x', 'y', 'assignment', 'state')} for p in players],
        'ball': dict(ball), 'event': event, 'decision': decision}


def simulate(lineup, seed, coverage='man', state=None):
    """Autonomous shotgun pass against a 4-3 man or zone defense."""
    if coverage not in ('man', 'zone'):
        raise ValueError('retro_coverage_must_be_man_or_zone')
    state = state or {'quarter': 1, 'clock': 600, 'offense': 'MIN', 'defense': 'SF', 'down': 1, 'togo': 10, 'yl': 50}
    players = sorted(copy.deepcopy(lineup), key=lambda p: p['id'])
    offense = [p for p in players if p['side'] == 'offense']
    defense = [p for p in players if p['side'] == 'defense']
    if len({p['id'] for p in players}) != 22:
        raise ValueError('retro_lineup_not_22_distinct_players')
    if (sum(p['role'] == 'QB' for p in offense) != 1
            or sum(p['assignment'] == 'pass protect' for p in offense) != 5
            or sum('route' in p['assignment'] for p in offense) != 5
            or sum(abs(p['x']) < 1e-9 for p in offense) < 7
            or any(p['x'] <= 0 for p in defense)):
        raise ValueError('retro_formation_alignment_invalid')
    qb = next(p for p in offense if p['role'] == 'QB')
    blockers = [p for p in offense if p['assignment'] == 'pass protect']
    receivers = [p for p in offense if 'route' in p['assignment']]
    rushers = [p for p in defense if p['assignment'] == 'rush QB']
    coverage_players = [p for p in defense if p['assignment'] == 'cover']
    if len(offense) != 11 or len(defense) != 11 or len(rushers) != 4 or len(coverage_players) != 7:
        raise ValueError('retro_formation_assignments_invalid')
    # Assign coverage by initial alignment, never by the QB's future target.
    assigned = {d['id']: min(receivers, key=lambda r: (abs(r['y'] - d['y']), r['id']))['id'] for d in coverage_players}
    zones = {d['id']: (d['x'] + 3, d['y']) for d in coverage_players}
    for d in coverage_players:
        d['assignment'] = ('man:' + assigned[d['id']]) if coverage == 'man' else ('zone:' + str(zones[d['id']]))
    route_end = {'go route': [(20, -17)], 'cross route': [(7, -8), (12, 4)], 'out route': [(7, 17), (12, 23)],
                 'flat route': [(0, -7), (5, -16)], 'seam route': [(15, 4)]}
    route_step = {p['id']: 0 for p in receivers}
    rng = random.Random(seed)
    ball = {'x': qb['x'], 'y': qb['y'], 'height': 1.8, 'phase': 'held'}
    frames, decision, event, carrier, target_id = [], None, None, None, None
    flight = None
    for tick in range(101):
        now = tick * DT
        world = copy.deepcopy(players)
        old = {p['id']: p for p in world}
        qb_old = old[qb['id']]
        if ball['phase'] == 'held':
            # A QB sees current receiver/defender positions only. Higher read delays less and notices tighter windows.
            if now >= 0.8 + (1.0 - qb['ratings']['read']) * 1.5:
                choices = []
                for r in receivers:
                    rr = old[r['id']]
                    separation = min(_distance(rr, old[d['id']]) for d in defense)
                    if rr['x'] >= 0:
                        choices.append((separation + 0.03 * rr['x'], r['id'], separation))
                best = max(choices, default=None)
                pressure = min(_distance(qb_old, old[d['id']]) for d in rushers)
                if best and best[2] >= 1.3 + (1 - qb['ratings']['read']) * 1.5:
                    target_id = best[1]
                    receiver = old[target_id]
                    # Inaccuracy is an authored seeded gameplay parameter, not a fitted NFL rating.
                    spread = (1 - qb['ratings']['throw_accuracy']) * 2.0
                    destination = route_end[receiver['assignment']][route_step[target_id]]
                    dx, dy = destination[0] - receiver['x'], destination[1] - receiver['y']
                    length = math.hypot(dx, dy)
                    route_speed = receiver['ratings']['speed'] * 0.8
                    lead = min(length, _distance(qb_old, receiver) / max(1.0, 18.0 - route_speed) * route_speed)
                    tx = receiver['x'] + (lead * dx / length if length else 0) + rng.uniform(-spread, spread)
                    ty = receiver['y'] + (lead * dy / length if length else 0) + rng.uniform(-spread, spread)
                    distance = math.hypot(tx - qb_old['x'], ty - qb_old['y'])
                    flight = {'start': (qb_old['x'], qb_old['y']), 'end': (tx, ty), 'start_time': now,
                              'duration': max(DT, distance / 18.0)}
                    ball['phase'] = 'flight'
                    decision = 'throw to ' + next(r['name'] for r in receivers if r['id'] == target_id)
                elif pressure < 2.0:
                    ball['phase'], carrier, decision = 'carry', qb['id'], 'QB scrambles under pressure'
                elif now >= 4.0:
                    decision, event = 'throw away', 'pass_incomplete'
        for p in players:
            before = old[p['id']]
            if p['id'] == carrier:
                p['state'] = 'CARRY'
                _move(p, (state['yl'] if p['side'] == 'offense' else state['yl'] - 100, before['y']), DT)
            elif carrier and old[carrier]['side'] != p['side']:
                runner = old[carrier]
                p['state'] = 'PURSUE'
                _move(p, (runner['x'], runner['y']), DT)
            elif p['side'] == 'offense':
                if p['role'] == 'QB':
                    p['state'] = 'SCAN' if ball['phase'] == 'held' else 'THROW'
                    if ball['phase'] == 'held':
                        _move(p, (-7, 0), DT, 0.35)
                elif p in blockers:
                    threat = min((old[d['id']] for d in rushers), key=lambda d: (_distance(before, d), d['id']))
                    p['state'] = 'BLOCK:' + threat['id']
                    _move(p, (threat['x'] - 0.4, threat['y']), DT, 0.6)
                else:
                    waypoints = route_end[p['assignment']]
                    step = route_step[p['id']]
                    x, y = waypoints[step]
                    if math.hypot(before['x'] - x, before['y'] - y) < 0.5 and step + 1 < len(waypoints):
                        route_step[p['id']] += 1
                        x, y = waypoints[step + 1]
                    p['state'] = 'ROUTE' if ball['phase'] == 'held' else 'TRACK_BALL'
                    _move(p, (x, before['y'] if y is None else y), DT, 0.8)
            elif p in rushers and ball['phase'] == 'held':
                nearest = min(((_distance(before, old[b['id']]), b) for b in blockers), key=lambda pair: (pair[0], pair[1]['id']))
                block = nearest[1]['ratings']['block'] if nearest[0] < 1.1 else 0.0
                p['state'] = 'BLOCKED' if block else 'RUSH'
                _move(p, (qb_old['x'], qb_old['y']), DT, max(0.12, 1 - block * (1.0 - 0.4 * p['ratings']['rush'])))
            elif ball['phase'] == 'carry' and carrier:
                runner = old[carrier]
                p['state'] = 'PURSUE'
                _move(p, (runner['x'], runner['y']), DT)
            elif p in coverage_players:
                if ball['phase'] == 'flight':
                    p['state'] = 'BREAK_BALL'
                    _move(p, (ball['x'], ball['y']), DT, p['ratings']['coverage'])
                elif coverage == 'man':
                    mark = old[assigned[p['id']]]
                    p['state'] = 'MAN:' + mark['id']
                    _move(p, (mark['x'] + 0.8, mark['y']), DT, 0.65 + 0.35 * p['ratings']['coverage'])
                else:
                    zone = zones[p['id']]
                    threats = [old[r['id']] for r in receivers if _distance(old[r['id']], {'x': zone[0], 'y': zone[1]}) < 8]
                    mark = min(threats, key=lambda r: (_distance(r, before), r['id'])) if threats else None
                    p['state'] = 'ZONE'
                    _move(p, (max(zone[0], mark['x'] + 3), mark['y']) if mark else zone, DT, 0.7)
        if ball['phase'] == 'held':
            ball.update(x=qb['x'], y=qb['y'])
            if any(_distance(qb, d) <= 0.7 for d in rushers):
                event = 'sack'
        elif ball['phase'] == 'flight':
            t = min(1.0, max(0.0, (now - flight['start_time']) / flight['duration']))
            ball.update(x=flight['start'][0] + t * (flight['end'][0] - flight['start'][0]),
                        y=flight['start'][1] + t * (flight['end'][1] - flight['start'][1]),
                        height=1.8 + 3.0 * 4 * t * (1 - t))
            if abs(ball['y']) > WIDTH:
                event, decision = 'pass_incomplete', 'ball out of bounds'
            elif t >= 0.5 and ball['height'] <= 3.0:
                reach = [p for p in receivers + defense if _distance(p, ball) <= 1.5]
                if reach:
                    p = min(reach, key=lambda p: (_distance(p, ball), p['id']))
                    chance = p['ratings']['catch'] if p['side'] == 'offense' else 0.35 * p['ratings']['coverage']
                    if rng.random() < chance:
                        carrier = p['id']
                        ball['phase'], decision = 'carry', ('catch' if p['side'] == 'offense' else 'interception') + ': ' + p['name']
                    else:
                        event, decision = 'pass_incomplete', 'drop or deflection: ' + p['name']
            if t >= 1 and ball['phase'] == 'flight' and event is None:
                event, decision = 'pass_incomplete', 'ball incomplete'
        elif ball['phase'] == 'carry' and carrier:
            holder = next(p for p in players if p['id'] == carrier)
            ball.update(x=holder['x'], y=holder['y'], height=1.0)
            opponents = defense if holder['side'] == 'offense' else offense
            if holder['side'] == 'defense' and holder['x'] <= state['yl'] - 100:
                raise ValueError('retro_interception_return_touchdown_unsupported')
            if any(_distance(holder, p) <= 0.75 for p in opponents) or holder['x'] >= state['yl'] or abs(holder['y']) >= WIDTH:
                event = 'interception' if holder['side'] == 'defense' else ('run' if holder['role'] == 'QB' else 'pass_complete')
        frames.append(_snapshot(players, ball, tick, event, decision))
        if event:
            break
    if not event:
        raise ValueError('retro_live_play_unresolved')
    if math.ceil(frames[-1]['time']) >= state['clock']:
        raise ValueError('retro_period_expiry_unsupported')
    x = qb['x'] if event == 'sack' else ball['x']
    yards = max(state['yl'] - 100, min(state['yl'], math.floor(x))) if event in ('run', 'sack', 'pass_complete') else 0
    if event == 'sack':
        yards = min(0, yards)
    spot = 100 - state['yl'] + math.floor(x) if event == 'interception' else None
    if spot is not None and not 1 <= spot <= 99:
        raise ValueError('retro_interception_boundary_unsupported')
    after, terminal, flags = reducer.apply_play(state, event, yards, spot)
    holder = next((p for p in players if p['id'] == carrier), None)
    record = {'event_type': event, 'state_before': {'yardline_100': state['yl']},
              'participants': {'passer_id': None if event == 'run' else qb['id'],
                               'receiver_id': (holder['id'] if event == 'pass_complete' else target_id),
                               'rusher_id': qb['id'] if event == 'run' else None, 'attribution': 'retro_authored'},
              'outcome': {'yards_gained': yards, **flags}}
    return {'seed': seed, 'coverage': coverage, 'input_classification': 'authored_gameplay_defaults',
            'frames': frames, 'decision': decision, 'event': event, 'yards': yards, 'terminal': terminal,
            'state_after': after, 'clock_at_whistle': state['clock'] - math.ceil(frames[-1]['time']),
            'player_statistics': game_stats.player_lines([{'plays': [record]}]), 'play': record}


def load_rosters(snapshot_path, field_path, field_sha256, seed):
    snapshot = pregame_snapshot.load_frozen_snapshot(snapshot_path)
    checks, resolved = roster_preflight.check(snapshot)
    if roster_preflight.failed(checks):
        raise ValueError('retro_roster_preflight_failed:' + repr(roster_preflight.failed(checks)))
    field = participation_field.Field.load(field_path, field_sha256)
    lineup, selection = make_lineups(snapshot, resolved, field, seed)
    return snapshot, lineup, selection
