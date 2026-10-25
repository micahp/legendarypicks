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
EVENT_VOCABULARY = DOWN_EVENTS + TURNOVER_EVENTS + (
    'punt', 'field_goal_attempt', 'blocked_punt', 'blocked_field_goal')
TERMINALS = ('touchdown', 'safety', 'turnover', 'turnover_on_downs', 'punt', 'field_goal_attempt',
             'halftime', 'end_of_regulation')
FLAGS = ('touchdown', 'safety', 'turnover', 'turnover_on_downs', 'punt', 'punt_attempt', 'field_goal_attempt')


def _no_flags():
    return {flag: False for flag in FLAGS}


def apply_play(st, event, yards, spot=None, kick_outcome=None):
    """Apply one sampled play. Returns (after, terminal, flags).

    `after` is the state at the next snap, or None when the drive ends with no next snap (touchdown, safety,
    field-goal attempt). `terminal` is None when the drive goes on, otherwise one of TERMINALS. The drive loop decides
    `halftime` (Q2 expiry) and `end_of_regulation` (Q4 expiry) from the clock. A Q1 or Q3 expiry is a change of ends,
    not a terminal, so `end_of_period` is not a terminal.
    """
    if event not in EVENT_VOCABULARY:
        raise ValueError(f'unknown event {event!r}; the reducer refuses to guess')
    flags = _no_flags()
    if event == 'field_goal_attempt':
        flags['field_goal_attempt'] = True
        return None, 'field_goal_attempt', flags
    if event in ('blocked_punt', 'blocked_field_goal'):
        return apply_blocked_kick(st, event, kick_outcome)
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


def apply_blocked_kick(st, event, outcome):
    """Resolve a sampled blocked scrimmage kick under Rule 9 using an observed transition record.

    Yardlines in `outcome` are from the relevant team's offensive perspective. The reducer owns possession, downs, and
    the next spot; the sampled record supplies the blocked-kick recovery and return facts only.
    """
    if event not in ('blocked_punt', 'blocked_field_goal'):
        raise ValueError(f'not a blocked-kick event: {event!r}')
    if not isinstance(outcome, dict) or outcome.get('classification_status') not in (
            'classified_recovery', 'classified_dead_ball_award', 'touchdown', 'safety', 'period_expired'):
        raise ValueError('blocked kick needs a classified observed outcome')
    expected_type = 'punt' if event == 'blocked_punt' else 'field_goal'
    if outcome.get('kick_type') != expected_type:
        raise ValueError(f'{event} cannot use {outcome.get("kick_type")!r} outcome data')

    flags = _no_flags()
    flags['punt_attempt'] = event == 'blocked_punt'
    flags['field_goal_attempt'] = event == 'blocked_field_goal'
    if outcome.get('touchdown'):
        role = outcome.get('scoring_role')
        if role not in ('kicking_team', 'receiving_team'):
            raise ValueError('blocked-kick touchdown needs a scoring-team role')
        flags['touchdown'] = True
        flags['scoring_team'] = st['offense'] if role == 'kicking_team' else st['defense']
        return None, 'touchdown', flags
    if outcome.get('safety'):
        flags['safety'] = True
        flags['scoring_team'] = st['defense']
        return None, 'safety', flags

    recovery_role = outcome.get('recovery_role')
    endpoint = outcome.get('return_endpoint_yardline_100')
    if recovery_role == 'receiving_team':
        if not isinstance(endpoint, int) or not 1 <= endpoint <= 99:
            raise ValueError('receiving-team recovery needs a field-of-play return endpoint')
        flags['turnover'] = True
        return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                'togo': min(10, endpoint), 'yl': endpoint}, 'turnover', flags

    if recovery_role == 'kicking_team':
        recovery_spot = outcome.get('recovery_spot_yardline_100')
        crossed_line = outcome.get('crossed_line')
        if not isinstance(recovery_spot, int) or not 1 <= recovery_spot <= 99 or crossed_line not in (0, 1, False, True):
            raise ValueError('kicking-team recovery needs a spot and a known line-crossing classification')
        crossed_line = bool(crossed_line)
        if crossed_line:
            touched_beyond_line = outcome.get('receiving_team_touched_beyond_line')
            if touched_beyond_line not in (0, 1, False, True):
                raise ValueError('kicking-team recovery beyond the line needs a known receiving-team touch result')
            if not bool(touched_beyond_line):
                flags['turnover'] = True
                receiver_spot = 100 - recovery_spot
                return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                        'togo': min(10, receiver_spot), 'yl': receiver_spot}, 'turnover', flags
            # A legal recovery by the kicking team beyond the line is dead at the recovery spot (Rule 9-3-2).
            flags['first_down'] = True
            return {'offense': st['offense'], 'defense': st['defense'], 'down': 1,
                    'togo': min(10, recovery_spot), 'yl': recovery_spot}, None, flags

        if recovery_spot < st['yl']:
            raise ValueError('recovery marked behind the line is beyond the kicking team’s line of scrimmage')
        if not isinstance(endpoint, int) or not 0 <= endpoint <= 100:
            raise ValueError('kicking-team recovery needs the return endpoint')
        gained = st['yl'] - endpoint
        if endpoint == 0:
            flags['touchdown'] = True
            flags['scoring_team'] = st['offense']
            return None, 'touchdown', flags
        if endpoint == 100:
            flags['safety'] = True
            flags['scoring_team'] = st['defense']
            return None, 'safety', flags
        if gained >= st['togo']:
            flags['first_down'] = True
            return {'offense': st['offense'], 'defense': st['defense'], 'down': 1,
                    'togo': min(10, endpoint), 'yl': endpoint}, None, flags
        if st['down'] == 4:
            flags['turnover_on_downs'] = True
            flags['turnover'] = True
            receiver_spot = 100 - endpoint
            return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                    'togo': min(10, receiver_spot), 'yl': receiver_spot}, 'turnover_on_downs', flags
        return {'offense': st['offense'], 'defense': st['defense'], 'down': st['down'] + 1,
                'togo': st['togo'] - gained, 'yl': endpoint}, None, flags

    if outcome.get('classification_status') == 'classified_dead_ball_award':
        if outcome.get('possession_after_role') != 'receiving_team' or not isinstance(endpoint, int) or not 1 <= endpoint <= 99:
            raise ValueError('dead-ball award needs the receiving team and its observed next spot')
        flags['turnover'] = True
        return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                'togo': min(10, endpoint), 'yl': endpoint}, 'turnover', flags

    raise ValueError('blocked-kick recovery team is not classified')
