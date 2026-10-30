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
             'halftime', 'end_of_regulation', 'end_of_overtime')
FLAGS = ('touchdown', 'safety', 'turnover', 'turnover_on_downs', 'punt', 'punt_attempt', 'field_goal_attempt')


def _no_flags():
    return {flag: False for flag in FLAGS}


def _validate_state(st):
    if not isinstance(st, dict):
        raise ValueError('play state must be an offense-relative mapping')
    offense, defense = st.get('offense'), st.get('defense')
    down, togo, yardline = st.get('down'), st.get('togo'), st.get('yl')
    if not offense or not defense or offense == defense:
        raise ValueError('play state needs two distinct teams')
    if type(down) is not int or not 1 <= down <= 4:
        raise ValueError(f'play state down must be 1 through 4 (got {down!r})')
    if type(yardline) is not int or not 1 <= yardline <= 99:
        raise ValueError(f'play state yardline must be 1 through 99 (got {yardline!r})')
    if type(togo) is not int or not 1 <= togo <= yardline:
        raise ValueError(f'play state distance must be 1 through the distance to goal (got {togo!r})')


BLOCKED_KICK_STATUSES = ('classified_recovery', 'classified_dead_ball_spot', 'touchdown', 'safety', 'classified_next_snap',
                         'period_expired')


class UnmodelledOutcome(ValueError):
    """A sampled outcome that lands off the field, so no spot can be given without guessing (a safety, a touchback or a
    touchdown is not in the observed record). The drive loop turns it into a named block. It is a ValueError, so a caller
    that does not catch it still fails loudly."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def apply_play(st, event, yards, spot=None, kick_outcome=None):
    """Apply one sampled play. Returns (after, terminal, flags).

    `after` is the state at the next snap, or None when the drive ends with no next snap (touchdown, safety,
    field-goal attempt). `terminal` is None when the drive goes on, otherwise one of TERMINALS. The drive loop decides
    `halftime` (Q2 expiry) and `end_of_regulation` (Q4 expiry) from the clock. A Q1 or Q3 expiry is a change of ends,
    not a terminal, so `end_of_period` is not a terminal.
    """
    if event not in EVENT_VOCABULARY:
        raise ValueError(f'unknown event {event!r}; the reducer refuses to guess')
    _validate_state(st)
    if event in ('run', 'pass_complete', 'pass_incomplete', 'sack'):
        if type(yards) is not int:
            raise ValueError(f'{event} needs an integer yards-gained result (got {yards!r})')
        if event == 'pass_incomplete' and yards != 0:
            raise ValueError(f'an incomplete pass must have zero yards gained (got {yards})')
        if event in ('run', 'pass_complete', 'sack'):
            if yards > st['yl']:
                raise ValueError(f'{event} gain {yards} exceeds the {st["yl"]} yards to the goal line')
            if st['yl'] - yards > 100:
                raise ValueError(f'{event} loss {yards} carries the ball past its own goal line')
        if event == 'sack' and yards > 0:
            raise ValueError('a sack cannot produce positive yardage')
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
    _validate_state(st)
    if not isinstance(outcome, dict) or outcome.get('classification_status') not in BLOCKED_KICK_STATUSES:
        raise ValueError('blocked kick needs a classified observed outcome')
    expected_type = 'punt' if event == 'blocked_punt' else 'field_goal'
    if outcome.get('kick_type') != expected_type:
        raise ValueError(f'{event} cannot use {outcome.get("kick_type")!r} outcome data')

    flags = _no_flags()
    flags['punt_attempt'] = event == 'blocked_punt'
    flags['field_goal_attempt'] = event == 'blocked_field_goal'
    if outcome.get('classification_status') == 'period_expired':
        # The kick uses the rest of the half or the game, so no possession carries over and no spot is needed.
        return None, None, flags
    if outcome.get('classification_status') == 'classified_next_snap':
        # Rule 11-4-2: the receivers' first snap is the observed result of an untouched blocked field goal.
        if outcome.get('possession_after_role') != 'receiving_team':
            raise ValueError('next-snap blocked kick needs receiving-team possession')
        yardline, down, togo = (outcome.get('next_snap_yardline_100'), outcome.get('next_snap_down'),
                                outcome.get('next_snap_ydstogo'))
        if (not all(type(v) is int for v in (yardline, down, togo))
                or not 1 <= yardline <= 99 or not 1 <= down <= 4 or not 1 <= togo <= yardline):
            raise ValueError('next-snap blocked kick needs a legal observed start spot, down and distance')
        flags['turnover'] = True
        return {'offense': st['defense'], 'defense': st['offense'], 'down': down, 'togo': togo,
                'yl': yardline}, 'turnover', flags
    if outcome.get('touchdown'):
        role = outcome.get('scoring_role')
        if role not in ('kicking_team', 'receiving_team'):
            scoring_team = outcome.get('scoring_team')
            if scoring_team and scoring_team == outcome.get('posteam'):
                role = 'kicking_team'
            elif scoring_team and scoring_team == outcome.get('defteam'):
                role = 'receiving_team'
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
    endpoint_delta = outcome.get('return_endpoint_yards_from_los')
    if recovery_role == 'receiving_team':
        if not isinstance(endpoint_delta, int):
            raise ValueError('receiving-team recovery needs a kick-relative return endpoint')
        endpoint = 100 - st['yl'] + endpoint_delta
        if not 1 <= endpoint <= 99:
            raise UnmodelledOutcome('blocked_kick_receiving_return_outside_field')
        flags['turnover'] = True
        return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                'togo': min(10, endpoint), 'yl': endpoint}, 'turnover', flags

    if recovery_role == 'kicking_team':
        recovery_delta = outcome.get('recovery_yards_from_los')
        if not isinstance(recovery_delta, int) or not isinstance(endpoint_delta, int):
            raise ValueError('kicking-team recovery needs kick-relative recovery and return spots')
        recovery_spot = st['yl'] - recovery_delta
        if not 1 <= recovery_spot <= 99:
            raise UnmodelledOutcome('blocked_kick_kicking_recovery_outside_field')
        crossed_line = recovery_delta > 0
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

        endpoint = st['yl'] - endpoint_delta
        if not 0 <= endpoint <= 100:
            raise UnmodelledOutcome('blocked_kick_kicking_return_outside_field')
        gained = endpoint_delta
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

    if outcome.get('classification_status') == 'classified_dead_ball_spot':
        dead_delta = outcome.get('dead_ball_yards_from_los')
        if (outcome.get('possession_after_role') != 'receiving_team' or not isinstance(dead_delta, int)):
            raise ValueError('described dead-ball spot needs receiving possession and a kick-relative spot')
        endpoint = 100 - st['yl'] + dead_delta
        if not 1 <= endpoint <= 99:
            raise UnmodelledOutcome('blocked_kick_dead_ball_outside_field')
        flags['turnover'] = True
        return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                'togo': min(10, endpoint), 'yl': endpoint}, 'turnover', flags

    raise ValueError('blocked-kick recovery team is not classified')
