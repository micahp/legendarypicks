"""Authoritative possession-level reducer for the NFL sequence generator, shared by E0 and E1.

Pure functions only: no data access and no sampling. A caller samples an event and its outcome, then calls
`apply_play`. The state is offense-relative: `yl` is yardline_100 for the offense on the play.

Decisions:
- A run or completion that gains at least the state's own `yl` is a touchdown. The sampled row's touchdown flag
  refers to its own yardline and is not an input.
- Turnovers (interception, fumble lost) and punts start the next offense at `spot`, the published position of that
  offense's next snap. `yards_gained` does not encode the spot for these events.
- A field-goal attempt is a terminal with no result. Made or missed is not in the published columns.
"""

TURNOVER_EVENTS = ('interception', 'fumble_lost')
DOWN_EVENTS = ('run', 'pass_complete', 'pass_incomplete', 'sack')
EVENT_VOCABULARY = DOWN_EVENTS + TURNOVER_EVENTS + ('punt', 'field_goal_attempt')
TERMINALS = ('touchdown', 'safety', 'turnover', 'turnover_on_downs', 'punt', 'field_goal_attempt', 'end_of_period')
FLAGS = ('touchdown', 'safety', 'turnover', 'turnover_on_downs', 'punt', 'field_goal_attempt')


def _no_flags():
    return {flag: False for flag in FLAGS}


def apply_play(st, event, yards, spot=None):
    """Apply one sampled play. Returns (after, terminal, flags).

    `after` is the state at the next snap, or None when the drive ends with no next snap (touchdown, safety,
    field-goal attempt). `terminal` is None when the drive goes on, otherwise one of TERMINALS except end_of_period,
    which the drive loop decides from the clock.
    """
    if event not in EVENT_VOCABULARY:
        raise ValueError(f'unknown event {event!r}; the reducer refuses to guess')
    flags = _no_flags()
    if event == 'field_goal_attempt':
        flags['field_goal_attempt'] = True
        return None, 'field_goal_attempt', flags
    if event == 'punt':
        if spot is None or not 1 <= spot <= 99:
            raise ValueError('punt needs the receiving team\'s published spot')
        flags['punt'] = True
        return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                'togo': min(10, spot), 'yl': spot}, 'punt', flags
    if event in TURNOVER_EVENTS:
        if spot is None or not 1 <= spot <= 99:
            raise ValueError(f'{event} needs the new offense\'s published spot')
        flags['turnover'] = True
        return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                'togo': min(10, spot), 'yl': spot}, 'turnover', flags
    if event in ('run', 'pass_complete') and yards >= st['yl']:
        flags['touchdown'] = True
        return None, 'touchdown', flags
    new_yl = st['yl'] - yards
    if new_yl >= 100:
        flags['safety'] = True
        return None, 'safety', flags
    if new_yl <= 0:
        raise AssertionError(f'unreachable: gain {yards} from yardline {st["yl"]} is a touchdown')
    if yards >= st['togo']:
        return {'offense': st['offense'], 'defense': st['defense'], 'down': 1,
                'togo': min(10, new_yl), 'yl': new_yl}, None, flags
    if st['down'] == 4:
        flags['turnover_on_downs'] = True
        flipped = 100 - new_yl
        return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                'togo': min(10, flipped), 'yl': flipped}, 'turnover_on_downs', flags
    return {'offense': st['offense'], 'defense': st['defense'], 'down': st['down'] + 1,
            'togo': st['togo'] - yards, 'yl': new_yl}, None, flags
