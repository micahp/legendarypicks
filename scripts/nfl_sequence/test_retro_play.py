"""Behavior tests use authored game attributes, not real player ratings."""
import copy

import retro_play as retro


def lineup():
    players = []
    def add(pid, role, side, x, y, assignment):
        players.append({'id': pid, 'name': pid, 'role': role, 'side': side, 'x': float(x), 'y': float(y),
                        'assignment': assignment, 'state': 'ALIGN', 'ratings': dict(retro.DEFAULTS)})
    add('qb', 'QB', 'offense', -5, 0, 'QB scan')
    for y, role in zip((-2, -1, 0, 1, 2), ('LT', 'LG', 'C', 'RG', 'RT')):
        add(role, role, 'offense', 0, y, 'pass protect')
    add('rb', 'RB', 'offense', -5, -3, 'flat route')
    add('te', 'TE', 'offense', -1, 4, 'seam route')
    for pid, y, route in (('wr1', -17, 'go route'), ('wr2', -8, 'cross route'), ('wr3', 17, 'out route')):
        add(pid, 'WR', 'offense', -1 if pid == 'wr2' else 0, y, route)
    for i, y in enumerate((-2.4, -0.8, 0.8, 2.4)):
        add('rush' + str(i), 'DL', 'defense', 1.5, y, 'rush QB')
    for i, (x, y) in enumerate(((5, -5), (5, 0), (5, 5), (4, -17), (4, 17), (10, -8), (10, 8))):
        add('cover' + str(i), 'DB', 'defense', x, y, 'cover')
    return players


def throw_decision(run):
    return next((f['decision'] for f in run['frames'] if (f['decision'] or '').startswith('throw to')), None)


def test_autonomous_play_is_reproducible_and_emits_twenty_two_players():
    first = retro.simulate(lineup(), 300001, 'zone')
    assert first == retro.simulate(lineup(), 300001, 'zone')
    assert first == retro.simulate(list(reversed(lineup())), 300001, 'zone')
    assert all(len(f['players']) == 22 for f in first['frames'])
    assert len({p['id'] for p in first['frames'][0]['players']}) == 22
    assert first['event'] in ('run', 'sack', 'pass_complete', 'pass_incomplete', 'interception')
    assert first['frames'][-1]['event'] == first['event']
    assert first['input_classification'] == 'authored_gameplay_defaults'
    assert 'sampled_from' not in first['play']['outcome']


def test_man_and_zone_execute_distinct_assignments():
    man, zone = (retro.simulate(lineup(), 300001, mode) for mode in ('man', 'zone'))
    assert any(p['state'].startswith('MAN:') for p in man['frames'][0]['players'])
    assert any(p['state'] == 'ZONE' for p in zone['frames'][0]['players'])
    assert man['frames'][2]['players'] != zone['frames'][2]['players']


def test_defender_position_changes_qb_read():
    original = lineup()
    next(p for p in original if p['id'] == 'qb')['ratings']['read'] = 1.0
    shifted = copy.deepcopy(original)
    for p in shifted:
        if p['side'] == 'defense' and p['assignment'] == 'cover':
            p['y'] += 12
    before = throw_decision(retro.simulate(original, 300001, 'zone'))
    after = throw_decision(retro.simulate(shifted, 300001, 'zone'))
    assert before and after and before != after


def test_qb_read_rating_changes_timing_and_blocking_changes_pressure():
    fast = lineup()
    slow = copy.deepcopy(fast)
    next(p for p in fast if p['id'] == 'qb')['ratings']['read'] = 1.0
    next(p for p in slow if p['id'] == 'qb')['ratings']['read'] = 0.0
    assert throw_decision(retro.simulate(fast, 300001, 'zone'))
    assert retro.simulate(slow, 300001, 'zone')['event'] == 'sack'
    poor = lineup()
    good = copy.deepcopy(poor)
    for p in poor:
        if p['assignment'] == 'pass protect':
            p['ratings']['block'] = 0.0
    for p in good:
        if p['assignment'] == 'pass protect':
            p['ratings']['block'] = 1.0
    assert retro.simulate(poor, 300001, 'zone')['event'] == 'sack'
    assert retro.simulate(good, 300001, 'zone')['event'] != 'sack'


def test_catching_rating_changes_an_actual_contest():
    sure = lineup()
    next(p for p in sure if p['id'] == 'qb')['ratings']['read'] = 1.0
    for p in sure:
        if p['side'] == 'offense':
            p['ratings']['catch'] = 1.0
    dropping = copy.deepcopy(sure)
    for p in dropping:
        if p['side'] == 'offense':
            p['ratings']['catch'] = 0.0
    assert retro.simulate(sure, 0, 'zone')['event'] == 'pass_complete'
    assert retro.simulate(dropping, 0, 'zone')['event'] == 'pass_incomplete'


def test_speed_changes_route_progress():
    fast = lineup()
    slow = copy.deepcopy(fast)
    next(p for p in slow if p['id'] == 'wr1')['ratings']['speed'] = 3.0
    fast_frame = retro.simulate(fast, 300001, 'zone')['frames'][3]
    slow_frame = retro.simulate(slow, 300001, 'zone')['frames'][3]
    fast_wr = next(p for p in fast_frame['players'] if p['id'] == 'wr1')
    slow_wr = next(p for p in slow_frame['players'] if p['id'] == 'wr1')
    assert fast_wr['x'] > slow_wr['x']
