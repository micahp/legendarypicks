"""A bounded, caller-timed sequence of autonomous scrimmage plays.

The caller supplies each next snap clock; this module never fabricates dead-ball
runoff. This is not a full game, kickoff, scoring, or overtime implementation.
"""
import copy

import game_stats
import gridiron_bridge


def execute_drive(session, base_call, start_state, plan):
    """Execute calls until a terminal or the explicit call plan is exhausted.

    Each plan item supplies a seed, an absolute quarter clock for the snap,
    an authored example concept, and a defense. A nonterminal return is an
    incomplete drive, not a completed game or implied next snap.
    """
    if not plan:
        raise ValueError('gridiron_drive_empty_plan')
    state = copy.deepcopy(start_state)
    plays = []
    terminal = None
    for index, item in enumerate(plan):
        clock = item['snap_clock']
        if type(clock) is not int or not 0 < clock <= state['clock']:
            raise ValueError('gridiron_drive_invalid_snap_clock')
        if state['quarter'] in (2, 4) and state['clock'] > 120 >= clock:
            raise ValueError('gridiron_drive_two_minute_boundary_unsupported')
        state['clock'] = clock
        call = copy.deepcopy(base_call)
        call['play_id'] = f"{base_call['play_id']}:drive:{index + 1}"
        call['seed'] = str(item['seed'])
        call['situation'].update(quarter=state['quarter'], clock_seconds=clock, down=state['down'],
                                 yards_to_go=state['togo'], yardline_100=100 - state['yl'])
        call['offense']['call'].update(family='pass', concept='assigned', snap_type='shotgun')
        coverage = item['coverage']
        if coverage not in ('man', 'zone'):
            raise ValueError('gridiron_drive_invalid_coverage')
        call['defense']['call']['coverage'] = 'cover_1' if coverage == 'man' else 'cover_3'
        call['assignments'] = session.request('example_assignments', concept=item['concept'], coverage=coverage)['value']
        call['behavior_mode'] = 'retro'
        call['output_mode'] = 'result_only'
        result, timing = session.play(call)
        reduced = gridiron_bridge.reduce_result(call, result, state)
        plays.append({'index': index + 1, 'seed': call['seed'], 'snap_clock': clock,
                      'concept': item['concept'], 'coverage': coverage, 'call': call,
                      'result': result, 'reduction': reduced, 'timing': timing})
        terminal = reduced['terminal']
        if terminal:
            break
        state = {**reduced['state_at_whistle'], 'quarter': state['quarter'], 'clock': reduced['clock_at_whistle']}
    statistics = game_stats.player_lines([{'plays': [entry['reduction']['play'] for entry in plays]}])
    return {'schema_version': 'slc.gridiron-bounded-drive.v1', 'start_state': copy.deepcopy(start_state),
            'status': 'terminal' if terminal else 'incomplete_call_plan', 'terminal': terminal,
            'end_state': plays[-1]['reduction']['state_at_whistle'],
            'clock_at_whistle': plays[-1]['reduction']['clock_at_whistle'], 'plays': plays,
            'player_statistics': statistics, 'timing_source': 'caller_supplied_snap_clocks',
            'valid_full_game': False}
