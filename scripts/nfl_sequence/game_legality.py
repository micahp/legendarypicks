"""Football legality of one emitted game: play by play, drive by drive, quarter by quarter.

Every check reads the record only. A state the game could not reach raises ILLEGAL_STATE and names the drive and play
that break the rule. Nothing here repairs a record: a violation is the finding.
"""
from football_assertions import FootballAssertionError

# Terminals after which the other team has the ball on the next drive, unless a kickoff follows.
POSSESSION_ENDS = ('punt', 'turnover', 'turnover_on_downs', 'field_goal_attempt', 'touchdown')
# Outcome flags that end a drive, so no play may follow them inside the same drive.
DRIVE_ENDING_OUTCOMES = ('touchdown', 'turnover', 'turnover_on_downs', 'punt', 'field_goal_attempt', 'safety')
KNOWN_TERMINALS = frozenset(POSSESSION_ENDS + ('halftime', 'end_of_regulation', 'end_of_overtime', 'safety'))
TIMEOUTS_PER_HALF = 3
QUARTER_SECONDS = 900
OVERTIME_QUARTER = 5
OVERTIME_SECONDS = 600
OVERTIME_TIMEOUTS = 2  # Rule 16, Article 3(e): two timeouts per team in overtime, as the engine states
PERIOD_START_CLOCK = {3: QUARTER_SECONDS, OVERTIME_QUARTER: OVERTIME_SECONDS}  # the clock a half or overtime opens at
PERIOD_KICKOFFS = ('half_start', 'overtime_start')
# Who may score on each terminal. A touchdown or a made field goal is the offense's; a turnover return, a punt return or a
# safety is the defense's. Regulation's last drive and the half's last drive are not scoring terminals.
SCORING_SIDE = {'touchdown': 'offense', 'field_goal_attempt': 'offense', 'turnover': 'defense', 'punt': 'defense',
                'safety': 'defense'}
POST_SCORE_KICKS = ('post_score', 'post_field_goal')


def _fail(message):
    raise FootballAssertionError('ILLEGAL_STATE', message)


def _other(team):
    if team not in ('A', 'B'):
        _fail(f'unknown team {team!r}')
    return 'B' if team == 'A' else 'A'


def _score(state, team):
    return state['home_score'] if team == 'A' else state['away_score']


def _where(drive, play=None):
    if play is None:
        return f"drive {drive['index']}"
    return f"drive {drive['index']} play {play['sequence']}"


def _period_length(quarter):
    return OVERTIME_SECONDS if quarter == OVERTIME_QUARTER else QUARTER_SECONDS


def _state_domain(drive, play):
    for tag in ('state_before', 'state_after'):
        s = play[tag]
        where = f'{_where(drive, play)} {tag}'
        if s['quarter'] not in (1, 2, 3, 4, OVERTIME_QUARTER):
            _fail(f'{where}: quarter {s["quarter"]} is not a quarter')
        if s['offense_team'] not in ('A', 'B') or s['defense_team'] != _other(s['offense_team']):
            _fail(f'{where}: offense {s["offense_team"]} and defense {s["defense_team"]} are not the two teams')
        for key in ('home_score', 'away_score'):
            if s[key] < 0:
                _fail(f'{where}: {key} {s[key]} is negative')
        if not 0 <= s['clock_seconds'] <= QUARTER_SECONDS:
            _fail(f'{where}: clock {s["clock_seconds"]} is outside 0..{QUARTER_SECONDS}')
        for side in ('home_timeouts', 'away_timeouts'):
            if not 0 <= s[side] <= TIMEOUTS_PER_HALF:
                _fail(f'{where}: {side} {s[side]} is outside 0..{TIMEOUTS_PER_HALF}')
        if s['down'] is None:
            continue
        if s['down'] not in (1, 2, 3, 4):
            _fail(f'{where}: down {s["down"]} is not 1 to 4')
        if not 1 <= s['yards_to_go'] <= 99:
            _fail(f'{where}: yards to go {s["yards_to_go"]} is outside 1..99')
        if not 1 <= s['yardline_100'] <= 99:
            _fail(f'{where}: yardline_100 {s["yardline_100"]} is outside 1..99')


def _ends_drive_flag(outcome, flag):
    """A blocked kick sets field_goal_attempt but leaves the ball live: the same team may keep it and the drive goes on.
    It ends the drive only through a touchdown, a turnover or a change of hands, which carry their own flags."""
    if flag == 'field_goal_attempt' and outcome.get('field_goal_result') == 'blocked':
        return False
    return True


def _play_chain(drive, plays):
    """Each play starts from the state the previous play left, inside one possession."""
    for prev, nxt in zip(plays, plays[1:]):
        for flag in DRIVE_ENDING_OUTCOMES:
            if _ends_drive_flag(prev['outcome'], flag) and prev['outcome'].get(flag):
                _fail(f'{_where(drive, prev)} ends the drive ({flag}) but play {nxt["sequence"]} follows it')
        after, before = prev['state_after'], nxt['state_before']
        where = _where(drive, nxt)
        if before['offense_team'] != after['offense_team'] or before['defense_team'] != after['defense_team']:
            _fail(f'{where}: possession changed inside a drive with no kick or turnover')
        for key in ('home_score', 'away_score', 'home_timeouts', 'away_timeouts'):
            if before[key] != after[key]:
                _fail(f'{where}: {key} is {before[key]} but the previous play left {after[key]}')
        if before['quarter'] == after['quarter']:
            if before['clock_seconds'] != after['clock_seconds']:
                _fail(f'{where}: clock {before["clock_seconds"]} does not continue from {after["clock_seconds"]}')
        else:
            if before['quarter'] != after['quarter'] + 1:
                _fail(f'{where}: quarter moved from {after["quarter"]} to {before["quarter"]}')
            if after.get('clock_status') != 'period_ended':
                _fail(f'{where}: quarter changes without the previous play ending the period')
            if before['clock_seconds'] != after['clock_seconds']:
                _fail(f'{where}: clock {before["clock_seconds"]} does not continue from {after["clock_seconds"]} '
                      f'across a change of ends')
    for prev in plays[:-1]:  # the last play's end state is the next possession, which the drive boundary checks
        _down_and_distance(drive, prev)
    if plays and plays[-1]['outcome'].get('field_goal_result') == 'blocked':
        _down_and_distance(drive, plays[-1])  # a blocked kick ends its drive, but its hand-over is still a first down


def _down_and_distance(drive, play):
    """A play moves the down, the spot and the distance from its own start to its own end, by its gain."""
    before, after, outcome = play['state_before'], play['state_after'], play['outcome']
    if outcome.get('penalty') or after['down'] is None:
        return  # a penalty moves the ball by a rule this check does not model; a terminal play has no next down
    if outcome.get('field_goal_result') == 'blocked':
        # A blocked kick that changes hands is a first down for the receiving team at the spot. A kicking-team recovery
        # keeps the ball live with the same team, and the observed next snap sets its down and distance, which
        # this check does not model: only the state domain applies to it.
        if after['offense_team'] != before['offense_team']:
            where = f'{_where(drive, play)} state_after'
            if after['down'] != 1 or after['yards_to_go'] != min(10, after['yardline_100']):
                _fail(f'{where}: a blocked kick hands over a first down; found down {after["down"]} and '
                      f'{after["yards_to_go"]} to go at yardline {after["yardline_100"]}')
        return
    where = f'{_where(drive, play)} state_after'
    gain = outcome.get('yards_gained')
    if gain is None:
        _fail(f'{_where(drive, play)} leaves down {after["down"]} but carries no yards gained')
    if before['down'] is None:
        _fail(f'{_where(drive, play)} is a live play with no down')
    if after['yardline_100'] != before['yardline_100'] - gain:
        _fail(f'{where}: a gain of {gain} moved the ball from {before["yardline_100"]} to {after["yardline_100"]}')
    if gain >= before['yards_to_go']:  # the distance is covered, so the next play is a first down
        if after['down'] != 1 or after['yards_to_go'] != min(10, after['yardline_100']):
            _fail(f'{where}: a gain of {gain} covers {before["yards_to_go"]} to go; the next play must be down 1 '
                  f'and {min(10, after["yardline_100"])} to go, found down {after["down"]} and {after["yards_to_go"]}')
        return
    if after['down'] != before['down'] + 1:
        _fail(f'{where}: down {before["down"]} with a gain of {gain} short of {before["yards_to_go"]} '
              f'became down {after["down"]}')
    if after['yards_to_go'] != before['yards_to_go'] - gain:
        _fail(f'{where}: a gain of {gain} left {after["yards_to_go"]} to go from {before["yards_to_go"]}')


def _play_clock(drive, play):
    """Inside a quarter the clock falls by the play's runoff and stops at 0:00. A quarter changes only when the clock runs
    out, and the new quarter opens at its full length. A penalty moves the clock by a rule this check does not model."""
    before, after, outcome = play['state_before'], play['state_after'], play['outcome']
    if outcome.get('penalty'):
        return
    where = f'{_where(drive, play)}'
    runoff = outcome.get('clock_runoff_seconds')
    if runoff is None:
        _fail(f'{where} carries no clock runoff, so its clock cannot be checked')
    if before['quarter'] == after['quarter']:
        expected = max(0, before['clock_seconds'] - runoff)
        if after['clock_seconds'] != expected:
            _fail(f'{where}: a runoff of {runoff} from {before["clock_seconds"]} leaves the clock at {expected}, '
                  f'not {after["clock_seconds"]}')
        return
    if before['clock_seconds'] > runoff:
        _fail(f'{where}: quarter {before["quarter"]} ends with {before["clock_seconds"] - runoff} seconds left after '
              f'a runoff of {runoff}')
    if after['clock_seconds'] != _period_length(after['quarter']):
        _fail(f'{where}: quarter {after["quarter"]} opens at {after["clock_seconds"]}, not '
              f'{_period_length(after["quarter"])}')


def _play_scores(drive, play):
    """A score never falls within a play."""
    before, after = play['state_before'], play['state_after']
    for key in ('home_score', 'away_score'):
        if after[key] < before[key]:
            _fail(f'{_where(drive, play)}: {key} fell from {before[key]} to {after[key]}')


def _drive(drive, return_drives=frozenset()):
    """One drive is a contiguous run of plays that starts and ends where its header says."""
    plays = drive['plays']
    if not plays:
        _fail(f'{_where(drive)} has no plays, so it cannot end in {drive["terminal"]!r}')
    first, last = plays[0]['state_before'], plays[-1]['state_after']
    if drive['quarter_start'] != first['quarter'] or drive['clock_start'] != first['clock_seconds']:
        _fail(f'{_where(drive)} starts at quarter {drive["quarter_start"]} {drive["clock_start"]}, '
              f'but its first play starts at quarter {first["quarter"]} {first["clock_seconds"]}')
    if drive['offense_team'] != first['offense_team']:
        _fail(f'{_where(drive)} is {drive["offense_team"]}, but its first play is {first["offense_team"]}')
    if drive['end_quarter'] != last['quarter'] or drive['end_clock'] != last['clock_seconds']:
        _fail(f'{_where(drive)} ends at quarter {drive["end_quarter"]} {drive["end_clock"]}, '
              f'but its last play ends at quarter {last["quarter"]} {last["clock_seconds"]}')
    if drive['terminal'] not in KNOWN_TERMINALS:
        _fail(f'{_where(drive)} has an unknown terminal {drive["terminal"]!r}')
    _play_chain(drive, plays)
    for play in plays:
        _state_domain(drive, play)
        _play_clock(drive, play)
        _play_scores(drive, play)
    _drive_points(drive, plays, return_drives)


def _blocked_kick_touchdown(drive):
    """The drive ends on a blocked kick that is a touchdown: the kicking or receiving side scores, as the kick was classified."""
    plays = drive.get('plays')
    if not plays:
        return False
    last = plays[-1]
    return last['event_type'] in ('blocked_punt', 'blocked_field_goal') and bool(last['outcome'].get('touchdown'))


def _scoring_team(drive, return_drives=frozenset()):
    """Only the side the terminal names may score on that drive: the offense on a touchdown or a made field goal, the
    defense on a turnover return, a punt return or a safety. Regulation's and the half's last drives score nothing here."""
    scored = drive.get('points_scored_on_drive')
    if not scored:
        return
    terminal = drive['terminal']
    if terminal not in SCORING_SIDE:
        if terminal in ('halftime', 'end_of_regulation'):
            return
        _fail(f'{_where(drive)} scores {scored["points"]} for {scored["team"]} on a {terminal} drive')
    if terminal == 'touchdown' and _blocked_kick_touchdown(drive):
        expected = drive['plays'][-1]['outcome'].get('scoring_team')  # a blocked kick may score for either side
        if scored['team'] != expected:
            _fail(f'{_where(drive)} is a blocked-kick touchdown that scores for {scored["team"]}, but the kick '
                  f'was classified for {expected}')
        return
    side = SCORING_SIDE[terminal]
    if terminal == 'touchdown' and drive['index'] in return_drives:
        side = 'defense'  # Article 5(a): the overtime return touchdown the record names, scored by the defense
    expected = drive['offense_team'] if side == 'offense' else _other(drive['offense_team'])
    if scored['team'] != expected:
        _fail(f'{_where(drive)} is a {terminal} that scores for {scored["team"]}; only the {side}, team {expected}, '
              f'can score on it')


def _drive_points(drive, plays, return_drives=frozenset()):
    """The score moves by the drive's own points for the team that scored, and by nothing for anyone else."""
    before, after = plays[0]['state_before'], plays[-1]['state_after']
    _scoring_team(drive, return_drives)
    scored = drive.get('points_scored_on_drive')
    for team in ('A', 'B'):
        delta = _score(after, team) - _score(before, team)
        expected = scored['points'] if scored and scored['team'] == team else 0
        if delta != expected:
            _fail(f'{_where(drive)}: team {team} score moved by {delta} but the drive scored {expected}')
    if drive['terminal'] == 'touchdown' and not (scored and scored['points'] >= 6):
        _fail(f'{_where(drive)} is a touchdown drive without six points')
    if drive['terminal'] == 'field_goal_attempt' and bool(drive.get('field_goal_made')) != bool(scored):
        _fail(f'{_where(drive)} records field_goal_made={drive.get("field_goal_made")} against points {scored}')


KICKOFF_FIELDS = ('after_drive', 'kind', 'quarter', 'kicking_team', 'receiving_team', 'clock_before', 'clock_after',
                  'clock_clamped_to_zero', 'clock_expired_during_kickoff')


def _kicks_after(record):
    """Kickoffs keyed by the drive they follow (0 is the opening kickoff)."""
    kicks = {}
    for kick in record['kickoffs']:
        missing = [f for f in KICKOFF_FIELDS if f not in kick]
        if missing:
            _fail(f'a kickoff after drive {kick.get("after_drive")} lacks {missing}; this record predates the '
                  f'legality checks and cannot be checked')
        if kick['after_drive'] in kicks:
            first = kicks[kick['after_drive']]
            if not (_ends_first_half(first) and kick['kind'] == 'half_start'):
                _fail(f'two kickoffs follow drive {kick["after_drive"]}')
            first['half_start'] = kick  # the second-half kickoff that a first-half kickoff expiring the half is followed by
            continue
        kicks[kick['after_drive']] = dict(kick)
    return kicks


def _ends_first_half(kick):
    """A post-score kickoff in the second quarter whose runoff expires the half: the second-half kickoff follows it."""
    return (kick['kind'] in POST_SCORE_KICKS + ('safety_free_kick',) and kick['quarter'] == 2
            and kick['clock_expired_during_kickoff'])


def _expects_kickoff(drive):
    """A drive that ends the ball's possession by a score, a half or a safety is followed by a kickoff. A turnover return or
    a punt return that scores hands the ball back to the team it was taken from, through a kickoff by the scorer."""
    if drive['terminal'] in ('touchdown', 'halftime', 'safety'):
        return True
    if drive['terminal'] == 'field_goal_attempt':
        return bool(drive.get('field_goal_made'))
    return drive['terminal'] in ('turnover', 'punt') and bool(drive.get('points_scored_on_drive'))


def _opening_receiver(record):
    ledger = record['ledger']
    if ledger['winner_choice'] == 'defer':
        return ledger['loser']
    if ledger['winner_choice'] == 'receive':
        return ledger['winner']
    _fail(f'opening choice {ledger["winner_choice"]!r} is not a legal opening choice')


def _ends_the_game(record, drive, kick):
    """The game ends after regulation's last drive, or after an overtime drive, or on a score that leaves it untied and
    runs the fourth quarter out: either the drive reaches 0:00, or the post-score kickoff's runoff expires the clock."""
    if drive['terminal'] == 'end_of_regulation' or drive['end_quarter'] == OVERTIME_QUARTER:
        return True
    final = drive['plays'][-1]['state_after']
    scored = drive.get('points_scored_on_drive')
    untied = _score(final, 'A') != _score(final, 'B') and record['points']['A'] != record['points']['B']
    if drive['end_quarter'] == 4 and drive['end_clock'] == 0 and untied:
        return True  # the fourth quarter expires on this drive with the score untied: a missed or blocked kick ends it too
    if not (drive['end_quarter'] == 4 and bool(scored) and untied):
        return False
    if drive['end_clock'] == 0:
        return True
    # a late score: the kick that follows is what runs the clock out, so the game ends on its return
    return kick is not None and _game_ending_kick(kick)


def _skips_post_score_kick(drive):
    """A score whose clock expires in the second quarter takes no post-score kick: a touchdown, made field goal or safety
    ending the first half (the provisional no_post_score_kick_at_halftime rule)."""
    return (drive['terminal'] in ('touchdown', 'field_goal_attempt', 'safety') and bool(drive.get('points_scored_on_drive'))
            and drive['end_quarter'] == 2 and drive['end_clock'] == 0)


def _game_ending_kick(kick):
    """A post-score or post-field-goal kickoff in the fourth quarter whose runoff expires the clock: the game ends on its return."""
    return kick['kind'] in POST_SCORE_KICKS and kick['quarter'] == 4 and kick['clock_expired_during_kickoff']


def _kickoff_clock(drive, kick):
    """A kickoff that opens a period starts at that period's length; any other starts where the drive ended."""
    if kick['kind'] in PERIOD_KICKOFFS:
        if kick['clock_before'] != PERIOD_START_CLOCK[kick['quarter']]:
            _fail(f'the {kick["kind"]} kickoff in quarter {kick["quarter"]} starts at {kick["clock_before"]}, '
                  f'not {PERIOD_START_CLOCK[kick["quarter"]]}')
        return
    if kick['clock_before'] == drive['end_clock']:
        return
    if (drive['end_clock'] == 0 and kick['quarter'] == drive['end_quarter'] + 1
            and kick['clock_before'] == QUARTER_SECONDS):
        return  # the drive ended the quarter at 0:00, so the kick opens the next quarter at its full length
    _fail(f'the kickoff after {_where(drive)} starts at {kick["clock_before"]}, not the drive end {drive["end_clock"]}')


def _ends_regulation(drive):
    """A scoring or change-of-possession play can itself expire the fourth quarter."""
    return (drive['terminal'] == 'end_of_regulation'
            or (drive['end_quarter'], drive['end_clock']) == (4, 0))


def _possession_and_clock(record, drives, kicks):
    """Each drive picks up the ball and the clock where the previous drive or kickoff left them."""
    opening = kicks.get(0)
    if opening is None or opening['kind'] != 'half_start' or opening['quarter'] != 1:
        _fail('the game does not open with a first-half kickoff')
    if drives[0]['offense_team'] != opening['receiving_team'] or drives[0]['offense_team'] != _opening_receiver(record):
        _fail('the opening kickoff receiver does not match the opening choice')
    for index, drive in enumerate(drives):
        if drive['index'] != index + 1:
            _fail(f'drive numbering breaks at {drive["index"]}: expected {index + 1}')
        nxt = drives[index + 1] if index + 1 < len(drives) else None
        kick = kicks.get(drive['index'])
        if _ends_regulation(drive):
            tied = _score(drive['plays'][-1]['state_after'], 'A') == _score(drive['plays'][-1]['state_after'], 'B')
            if tied and (kick is None or kick['kind'] != 'overtime_start'):
                _fail(f'{_where(drive)} ends regulation tied but no overtime kickoff follows it')
            if not tied and (kick is not None or nxt is not None):
                _fail(f'{_where(drive)} ends regulation untied, so the game must end there')
            if not tied:
                continue
        elif drive['terminal'] == 'end_of_overtime' and nxt is None:
            if drive['end_quarter'] != OVERTIME_QUARTER or drive['end_clock'] != 0 or kick is not None:
                _fail(f'{_where(drive)} ends overtime but is not an overtime drive that ends at 0:00 with no kick after')
            continue
        elif drive['terminal'] == 'end_of_overtime':
            _fail(f'{_where(drive)} ends overtime, but {_where(nxt)} follows it')
        elif nxt is None:
            if not _ends_the_game(record, drive, kick):
                _fail(f'the last drive ends with {drive["terminal"]!r} in quarter {drive["end_quarter"]} '
                      f'at {drive["end_clock"]}, which does not end the game')
            if kick is not None and not _game_ending_kick(kick):
                _fail('a kickoff follows the last drive')
            continue
        if kick is None:
            if _expects_kickoff(drive):
                _fail(f'{_where(drive)} ends with {drive["terminal"]} and must be followed by a kickoff')
            if nxt['offense_team'] != _other(drive['offense_team']):
                _fail(f'{_where(nxt)} has {nxt["offense_team"]} on offense after {drive["terminal"]} '
                      f'by {drive["offense_team"]}')
        else:
            starts_second_half = (kick['kind'] == 'half_start' and kick['quarter'] == 3
                                  and (drive['end_quarter'], drive['end_clock']) == (2, 0))
            if not _ends_regulation(drive) and not starts_second_half and not _expects_kickoff(drive):
                _fail(f'{_where(drive)} ends with {drive["terminal"]} and no kickoff can follow it')
            _kickoff_clock(drive, kick)
            half = kick.get('half_start') if _ends_first_half(kick) else None
            if _ends_first_half(kick) and half is None:
                _fail(f'the kickoff after {_where(drive)} expires the first half, but no second-half kickoff follows it')
            handoff = half or kick  # after a first-half expiry the ball changes hands on the second-half kickoff
            scored = drive.get('points_scored_on_drive')
            if scored and kick['kind'] in POST_SCORE_KICKS and kick['kicking_team'] != scored['team']:
                _fail(f'the {kick["kind"]} kickoff after {_where(drive)} is kicked by {kick["kicking_team"]}, '
                      f'but {scored["team"]} scored')
            if nxt['offense_team'] != handoff['receiving_team']:
                _fail(f'{_where(nxt)} has {nxt["offense_team"]} on offense but the kickoff went to {handoff["receiving_team"]}')
            if kick['kicking_team'] != _other(kick['receiving_team']):
                _fail(f'the kickoff after {_where(drive)} is kicked and received by the same team')
            expired = kick['clock_clamped_to_zero'] or kick['clock_expired_during_kickoff']
            if not expired and nxt['clock_start'] != kick['clock_after']:
                _fail(f'{_where(nxt)} starts at {nxt["clock_start"]}, but the kickoff ends at {kick["clock_after"]}')
            if half is not None:
                if nxt['quarter_start'] != half['quarter'] or nxt['clock_start'] != half['clock_after']:
                    _fail(f'{_where(nxt)} should open the second half at {half["clock_after"]} after the second-half kickoff, '
                          f'found quarter {nxt["quarter_start"]} at {nxt["clock_start"]}')
            elif kick['clock_clamped_to_zero'] or kick['clock_expired_during_kickoff']:
                # the period ends during the kick: the next quarter opens where the kick left off, not with a second kick
                if nxt['quarter_start'] != kick['quarter'] + 1 or nxt['clock_start'] != QUARTER_SECONDS:
                    _fail(f'{_where(nxt)} should open quarter {kick["quarter"] + 1} at {QUARTER_SECONDS} after a kick '
                          f'that expired the clock, found quarter {nxt["quarter_start"]} at {nxt["clock_start"]}')
            elif nxt['quarter_start'] != kick['quarter']:
                _fail(f'{_where(nxt)} starts in quarter {nxt["quarter_start"]}, but the kickoff is in quarter {kick["quarter"]}')
            if kick['kind'] == 'half_start' and (drive['end_quarter'], drive['end_clock']) != (2, 0):
                _fail(f'a second-half kickoff follows {_where(drive)}, which does not end the first half')
            if kick['kind'] == 'overtime_start' and not _ends_regulation(drive):
                _fail(f'an overtime kickoff follows {_where(drive)}, which does not end regulation')
        _check_boundary(drive, nxt, kick_expired_half=kick is not None and _ends_first_half(kick))


def _check_boundary(drive, nxt, kick_expired_half=False):
    """Quarters step forward by one, and the score and the timeouts run continuously across the drive boundary."""
    last = drive['plays'][-1]['state_after']
    first = nxt['plays'][0]['state_before']
    if nxt['quarter_start'] not in (drive['end_quarter'], drive['end_quarter'] + 1):
        _fail(f'{_where(nxt)} starts in quarter {nxt["quarter_start"]} after {_where(drive)} ends in {drive["end_quarter"]}')
    for key in ('home_score', 'away_score'):
        if first[key] != last[key]:
            _fail(f'{_where(nxt)} starts with {key} {first[key]}, but {_where(drive)} ended with {last[key]}')
    if (drive['end_quarter'], nxt['quarter_start']) == (2, 3):
        if drive['end_clock'] != 0 and not kick_expired_half:  # a kickoff that expires the half is the drive's last event
            _fail(f'{_where(nxt)} opens the second half after {_where(drive)}, which ends at quarter '
                  f'{drive["end_quarter"]} {drive["end_clock"]}')
        for side in ('home_timeouts', 'away_timeouts'):
            if first[side] != TIMEOUTS_PER_HALF:
                _fail(f'{_where(nxt)} starts the second half with {side} {first[side]}, not {TIMEOUTS_PER_HALF}')
    elif _ends_regulation(drive):
        if nxt['quarter_start'] != OVERTIME_QUARTER:
            _fail(f'{_where(nxt)} starts in quarter {nxt["quarter_start"]} after regulation')
        for side in ('home_timeouts', 'away_timeouts'):
            if first[side] != OVERTIME_TIMEOUTS:
                _fail(f'{_where(nxt)} starts overtime with {side} {first[side]}, not {OVERTIME_TIMEOUTS}')
    else:
        for side in ('home_timeouts', 'away_timeouts'):
            if first[side] != last[side]:
                _fail(f'{side} changed between {_where(drive)} and {_where(nxt)} with no period boundary')


def _quarters(record, drives):
    """Every quarter change the plays and drive headers show is a declared boundary, and every boundary happens."""
    observed = []
    for position, drive in enumerate(drives):
        quarter = drive['plays'][0]['state_before']['quarter']
        for play in drive['plays']:
            after = play['state_after']
            if after['quarter'] != quarter:
                observed.append((drive['index'], quarter, after['quarter']))
                quarter = after['quarter']
        if drive['end_quarter'] != quarter:
            _fail(f'{_where(drive)} ends in quarter {drive["end_quarter"]} but its plays reach {quarter}')
        if position + 1 < len(drives) and drives[position + 1]['quarter_start'] != quarter:
            observed.append((drive['index'], quarter, drives[position + 1]['quarter_start']))
    for b in record['boundaries']:
        if b['kind'] == 'skipped_post_score_kick':
            drive = drives[b['drive_index'] - 1]
            if not _skips_post_score_kick(drive):
                _fail(f'{_where(drive)} skips a post-score kick but is not a score ending the first half')
    declared = [(b['drive_index'], b['from_quarter'], b['to_quarter']) for b in record['boundaries']
                if b['kind'] != 'skipped_post_score_kick']
    if sorted(observed) != sorted(declared):
        _fail(f'quarter changes {sorted(observed)} do not match the declared boundaries {sorted(declared)}')
    halftimes = [b for b in record['boundaries'] if b['kind'] == 'halftime']
    if len(halftimes) != 1 or (halftimes[0]['from_quarter'], halftimes[0]['to_quarter']) != (2, 3):
        _fail('a game has one halftime, from quarter 2 to quarter 3')
    for b in record['boundaries']:
        if b['kind'] == 'change_of_ends_mid_drive' and (b['from_quarter'], b['to_quarter']) not in ((1, 2), (3, 4)):
            _fail(f'drive {b["drive_index"]} changes ends mid-drive from quarter {b["from_quarter"]} to '
                  f'{b["to_quarter"]}; only the first and third quarter ends change ends inside a drive')


def _timeouts(drives):
    """Timeouts only fall within a half and refill at the half: the same team's count never rises mid-half."""
    for drive in drives:
        for play in drive['plays']:
            before, after = play['state_before'], play['state_after']
            if before['quarter'] != after['quarter'] and not (before['quarter'] == 2 and after['quarter'] == 3):
                continue
            for side in ('home_timeouts', 'away_timeouts'):
                if after[side] > before[side]:
                    _fail(f'{_where(drive, play)}: {side} rose from {before[side]} to {after[side]} in the same half')


def _game(record, drives):
    """The final score, the final clock and the regulation ending must agree with the drives."""
    final = drives[-1]['plays'][-1]['state_after']
    for team in ('A', 'B'):
        scored = sum(d['points_scored_on_drive']['points'] for d in drives
                     if d.get('points_scored_on_drive') and d['points_scored_on_drive']['team'] == team)
        if scored != record['points'][team] or _score(final, team) != record['points'][team]:
            _fail(f'team {team}: drives score {scored}, the final state shows {_score(final, team)}, '
                  f'and the record says {record["points"][team]}')
    overtime = any(d['plays'][0]['state_before']['quarter'] == OVERTIME_QUARTER for d in drives)
    if record['complete_regulation']:
        if record['final_quarter'] != (OVERTIME_QUARTER if overtime else 4):
            _fail(f'a complete regulation game ends in quarter {record["final_quarter"]}, '
                  f'not {OVERTIME_QUARTER if overtime else 4}')
        if not overtime and (record['final_clock_seconds'] != 0 or record['points']['A'] == record['points']['B']):
            _fail(f'a complete regulation game without overtime must end at 0 and untied, '
                  f'found {record["final_clock_seconds"]} and {record["points"]}')


def check(record):
    """Refuse the first state, transition or drive the game could not have reached. Returns the checks that passed."""
    drives = record['drives']
    if not drives:
        _fail('the record has no drives to check')
    overtime = record.get('overtime') or {}
    article_5a = overtime.get('article_5a')
    return_drives = frozenset({article_5a['drive_index']} if article_5a and article_5a['return_touchdown'] else ())
    for drive in drives:
        _drive(drive, return_drives)
    kicks = _kicks_after(record)
    _possession_and_clock(record, drives, kicks)
    _quarters(record, drives)
    _timeouts(drives)
    _game(record, drives)
    return ['play domain', 'play clock and score', 'play chain and downs', 'drive headers', 'scoring side',
            'drive points', 'possession and kickoffs', 'quarter boundaries', 'timeouts', 'final score']
