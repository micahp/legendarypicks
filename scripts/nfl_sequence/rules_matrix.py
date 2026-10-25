"""Check one generated game against the 2026 mandatory test matrix (docs/rules/NFL-2026-GAME-STATE-RULES.md, section 7).

Every row is recomputed from the record's drives, plays, kickoffs and boundaries. None of it is read from the engine's
own flags. A row is one of:
- PASS: the check ran and held;
- FAIL: the check ran and did not hold. A complete game with a FAIL is not emitted;
- PARTIAL: the check holds for what is modelled, and the row names what is not;
- PROVISIONAL: the check holds for a rule that is practice-sourced and not written in the rules file. The row says so
  and stays pending the 2026 rulebook;
- UNSUPPORTED: the rule is not modelled, and the record says so in unsupported_rules;
- NOT_APPLICABLE: this game did not take that path (for example, the winner received, so the defer row does not apply);
- BLOCKED: the game did not finish, so the check cannot apply.

Usage: rules_matrix.check(record) -> list of {'case', 'status', 'evidence'}.
"""
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import game_state as gs  # noqa: E402

PASS, FAIL, PARTIAL, UNSUPPORTED, NOT_APPLICABLE, BLOCKED, PROVISIONAL = (
    'PASS', 'FAIL', 'PARTIAL', 'UNSUPPORTED', 'NOT_APPLICABLE', 'BLOCKED', 'PROVISIONAL')
SCORING = ('touchdown', 'safety', 'field_goal_attempt')
HOLDER_OFFSET = 7  # the holder's placement behind the snap; the same authored value as game_state.HOLDER_OFFSET, kept separate
KICK_DURATION_MAX = 5  # the made-kick clock bound; the same value as game_state.KICK_DURATION_SECONDS, kept separate


def _half_starts(record):
    return {k['quarter']: k for k in record['kickoffs'] if k['kind'] == 'half_start'}


def _kicks_after(record, drive_index):
    return [k for k in record['kickoffs'] if k['after_drive'] == drive_index and k['kind'] != 'half_start']


def _ends_on_zero(drive):
    return drive['end_clock'] == 0


def _expected_kick_after(drive):
    """A score is followed by a kick unless the clock expires in Q2 (halftime, then the second-half kickoff) or Q4 (the
    end).
    """
    return not (_ends_on_zero(drive) and drive['end_quarter'] in (2, 4))


def _defer_row(record, deferred):
    """Rules section 7: a defer gives the loser the Q1 receive and the winner the Q3 receive; a receive is the reverse.
    """
    ledger, k = record['ledger'], _half_starts(record)
    if ledger['winner_deferred'] != deferred:
        return NOT_APPLICABLE, 'this game took the other opening path'
    winner, loser = ledger['winner'], ledger['loser']
    want1, want3 = (loser, winner) if deferred else (winner, loser)
    got1 = k[1]['receiving_team']
    got3 = k[3]['receiving_team'] if 3 in k else None
    if got1 != want1 or (got3 is not None and got3 != want3):
        return FAIL, f'Q1 receiver {got1} (expected {want1}), Q3 receiver {got3} (expected {want3})'
    return PASS, f'Q1 receiver {got1}; Q3 receiver {got3}; {"winner deferred" if deferred else "winner received"}'


def _refused(choice):
    try:
        gs.CoinTossLedger('A', 'B', choice)
    except ValueError:
        return PASS, f'{choice} refused in normal mode'
    return FAIL, f'{choice} was accepted in normal mode'


def _exception_refused():
    try:
        gs.CoinTossLedger('A', 'B', 'receive', mode=gs.EXCEPTION_MODE)
    except NotImplementedError:
        return PASS, 'explicit exception path refused'
    return FAIL, 'exception path accepted'


def _change_of_ends(record, from_quarter):
    """Q1->Q2 or Q3->Q4: no kickoff or new drive at the change of ends; a kickoff opening the quarter follows a score
    only.
    """
    to_quarter = from_quarter + 1
    drives = record['drives']
    mid = [b for b in record['boundaries']
           if b['kind'] == 'change_of_ends_mid_drive' and b['from_quarter'] == from_quarter]
    expiry = [b for b in record['boundaries'] if b['kind'] in ('change_of_ends', 'change_of_ends_during_return')
              and b['from_quarter'] == from_quarter]
    if not mid and not expiry:
        return NOT_APPLICABLE, f'the game did not reach Q{to_quarter}'
    possession_ends = 0
    for b in mid:
        drive_index = b['drive_index']
        drive = drives[drive_index - 1]
        plays = drive['plays']
        idx = next(i for i, p in enumerate(plays) if p['outcome']['quarter_change'])
        a = plays[idx]['state_after']
        if idx == len(plays) - 1:
            if drive['terminal'] not in ('punt', 'turnover', 'turnover_on_downs'):
                return FAIL, f'a Q{from_quarter} expiry ended drive {drive_index} without a possession-ending play'
            if drive_index >= len(drives):
                return BLOCKED, f'drive {drive_index} changed possession at the Q{from_quarter} expiry, but the next drive is absent'
            following = drives[drive_index]['plays'][0]
            before = following['state_before']
            if any(a[k] != before[k] for k in ('quarter', 'clock_seconds', 'offense_team', 'yardline_100', 'down', 'yards_to_go')):
                return FAIL, f'possession, spot, down or clock changed at the Q{from_quarter} expiry after drive {drive_index}'
            if plays[idx]['field']['after']['dir'] != following['field']['before']['dir']:
                return FAIL, f'attacking direction changed incorrectly at the Q{from_quarter} expiry after drive {drive_index}'
            possession_ends += 1
        else:
            nxt = plays[idx + 1]
            after = nxt['state_before']
            if any(a[k] != after[k] for k in ('quarter', 'clock_seconds', 'offense_team', 'yardline_100', 'down', 'yards_to_go')):
                return FAIL, (f'possession, spot, down or clock changed across the Q{from_quarter} expiry in drive '
                              f'{drive_index}')
            if plays[idx]['field']['after']['dir'] != nxt['field']['before']['dir']:
                return FAIL, f'attacking direction changed across the Q{from_quarter} expiry in drive {drive_index}'
    opened = [k for k in record['kickoffs'] if k['quarter'] == to_quarter and k['clock_before'] == gs.QUARTER_LENGTH
              and k['kind'] != 'half_start']
    for k in opened:
        # The kickoff follows a score that either ran into this quarter (a score after a mid-drive change of ends) or
        # expired the quarter it was scored in. A change of ends alone never triggers a kickoff.
        prev = drives[k['after_drive'] - 1]
        ran_into_new_quarter = prev['end_quarter'] == to_quarter
        expired_old_quarter = prev['end_quarter'] == from_quarter and _ends_on_zero(prev)
        if prev['terminal'] not in SCORING or not (ran_into_new_quarter or expired_old_quarter):
            return FAIL, f'a kickoff opened Q{to_quarter} without a score that ended the quarter change'
    return PASS, (f'{len(mid) - possession_ends} mid-drive change(s) keep the drive; {possession_ends} change(s) at a possession end keep '
                  f'the possession; {len(opened)} kickoff(s) open Q{to_quarter} after a score that expired '
                  f'Q{from_quarter}')


def _halftime(record, ledger_kicks):
    k = _half_starts(record)
    if 3 not in k:
        return NOT_APPLICABLE, 'the game did not reach Q3'
    want = ledger_kicks[3]
    if (k[3]['kicking_team'], k[3]['receiving_team']) != (want['kicking_team'], want['receiving_team']):
        return FAIL, f'Q3 kickoff {k[3]["kicking_team"]}->{k[3]["receiving_team"]} disagrees with the ledger'
    if k[3]['clock_before'] != gs.QUARTER_LENGTH:
        return FAIL, 'the Q3 kickoff does not start at 15:00'
    expired = [d for d in record['drives'] if d['end_quarter'] == 2 and _ends_on_zero(d) and d['terminal'] in SCORING]
    for d in expired:
        if any(kk['kind'] != 'half_start' for kk in record['kickoffs'] if kk['after_drive'] == d['index']):
            return FAIL, f'a score that expired Q2 (drive {d["index"]}) was followed by a post-score kickoff'
    return PASS, (f'Q3 kickoff {k[3]["kicking_team"]}->{k[3]["receiving_team"]} from the ledger at 15:00; '
                  f'{len(expired)} score(s) expired Q2 with no post-score kickoff')


def _both_half_kickoffs(record):
    half = [k for k in record['kickoffs'] if k['kind'] == 'half_start']
    if len(half) == 1:
        return BLOCKED, 'the game did not reach the Q3 kickoff'
    if len(half) != 2 or sorted(k['quarter'] for k in half) != [1, 3]:
        return FAIL, f'{len(half)} half-start kickoffs'
    if half[0]['kicking_team'] == half[1]['kicking_team']:
        return FAIL, 'the same team kicks both half-start kickoffs'
    gs.validate_half_start([{'quarter': k['quarter'], 'kicking_team': k['kicking_team'],
                             'receiving_team': k['receiving_team'], 'reason': 'half_start'} for k in half])
    return PASS, (f"Q1 {half[0]['kicking_team']} kicks to {half[0]['receiving_team']}; "
                  f"Q3 {half[1]['kicking_team']} kicks to {half[1]['receiving_team']}")


def _turnover_on_downs_q2(record):
    hits = [d for d in record['drives'] if d['terminal'] == 'turnover_on_downs' and d['plays'][-1]['state_before']['quarter'] == 2
            and not _ends_on_zero(d)]
    if not hits:
        return NOT_APPLICABLE, 'no turnover on downs in Q2 in this game'
    for d in hits:
        if d['index'] >= len(record['drives']):
            return FAIL, f'drive {d["index"]} is the last drive of a blocked game'
        nxt = record['drives'][d['index']]
        last = d['plays'][-1]
        if nxt['offense_team'] == d['offense_team']:
            return FAIL, f'drive {d["index"]}: the offense did not change on a turnover on downs'
        if nxt['plays'][0]['state_before']['yardline_100'] != last['state_after']['yardline_100']:
            return FAIL, f'drive {d["index"]}: the new offense does not start at the spot the turnover left'
        if nxt['plays'][0]['field']['before']['dir'] != -last['field']['before']['dir']:
            return FAIL, f'drive {d["index"]}: the attacking direction did not flip'
    return PASS, f'{len(hits)} turnover(s) on downs in Q2: offense changes, spot and direction hold'


def _two_minute_warning(record):
    """Derive the warning from down and kickoff clocks, then compare its recorded event markers."""
    expected_plays, expected_kicks = set(), set()
    for drive in record['drives']:
        for play in drive['plays']:
            before, after = play['state_before'], play['state_after']
            if (before['quarter'] in (2, 4) and after['quarter'] == before['quarter'] and
                    before['clock_seconds'] > 120 >= after['clock_seconds'] > 0):
                expected_plays.add((drive['index'], play['sequence'], after['clock_seconds']))
    for i, kick in enumerate(record['kickoffs']):
        clock_after = kick.get('clock_after', max(0, kick['clock_before'] - kick['runoff_seconds']))
        expired = kick.get('clock_expired_during_kickoff', kick['runoff_seconds'] >= kick['clock_before'])
        if (kick['quarter'] in (2, 4) and not expired and kick['clock_before'] > 120 >= clock_after > 0):
            expected_kicks.add((i, clock_after))

    marked_plays = {(drive['index'], play['sequence'], play['state_after']['clock_seconds'])
                    for drive in record['drives'] for play in drive['plays']
                    if play['outcome'].get('two_minute_warning')}
    marked_kicks = {(i, kick.get('clock_after', max(0, kick['clock_before'] - kick['runoff_seconds'])))
                    for i, kick in enumerate(record['kickoffs'])
                    if kick.get('two_minute_warning')}
    if expected_plays != marked_plays or expected_kicks != marked_kicks:
        return FAIL, (f'warning markers disagree with independently derived crossings: plays '
                      f'{len(marked_plays)}/{len(expected_plays)}, kickoffs {len(marked_kicks)}/{len(expected_kicks)}')
    # Enforce at most one warning in each half, across scrimmage plays and kickoffs.
    counts = {q: sum(1 for drive in record['drives'] for play in drive['plays']
                     if play['outcome'].get('two_minute_warning') and play['state_before']['quarter'] == q)
              + sum(1 for kick in record['kickoffs'] if kick.get('two_minute_warning') and kick['quarter'] == q)
              for q in (2, 4)}
    if any(n > 1 for n in counts.values()):
        return FAIL, f'more than one warning in a half: {counts}'
    if not expected_plays and not expected_kicks:
        return NOT_APPLICABLE, 'no down or kickoff crossed 2:00 before the period ended'
    return PASS, (f'{len(expected_plays)} play warning marker(s) and {len(expected_kicks)} kickoff warning marker(s), at their '
                  'observed post-down clocks; at most one per half. Clock state/restart lifecycle is separately unsupported.')


def _touchdowns(record):
    tds = [d for d in record['drives'] if d['terminal'] == 'touchdown']
    if not tds:
        return NOT_APPLICABLE, 'no touchdown in this game'
    kicked = 0
    for d in tds:
        p = d['points_scored_on_drive']
        if p is None or p['try'] is None:
            return FAIL, f'touchdown drive {d["index"]} has no try'
        want = gs.TD_POINTS + (gs.TRY_POINTS[p['try']['kind']] if p['try']['made'] else 0)
        if p['points'] != want:
            return FAIL, f'touchdown drive {d["index"]}: {p["points"]} points, expected {want}'
        follow = [k for k in _kicks_after(record, d['index']) if k['kind'] == 'post_score']
        if _expected_kick_after(d):
            if not follow or follow[0]['kicking_team'] != d['offense_team']:
                return FAIL, f'touchdown drive {d["index"]}: no post-score kickoff by the scorer'
            kicked += 1
        elif follow:
            return FAIL, f'touchdown drive {d["index"]} expired the game or the half, and still kicked off'
    return PASS, f'{len(tds)} touchdown(s): 6 + try, no automatic try, {kicked} post-score kickoff(s) by the scorer'


def _fg_safety(record):
    fgs = [d for d in record['drives'] if d['terminal'] == 'field_goal_attempt']
    sft = [d for d in record['drives'] if d['terminal'] == 'safety']
    if not fgs and not sft:
        return NOT_APPLICABLE, 'no field goal attempt or safety in this game'
    made = missed = 0
    for d in fgs:
        if d['field_goal_made'] is None:
            return BLOCKED, f'field goal drive {d["index"]} has no result'
        if not d['field_goal_made']:
            missed += 1
            continue
        made += 1
        if d['points_scored_on_drive'] is None or d['points_scored_on_drive']['points'] != gs.FG_POINTS:
            return FAIL, f'made field goal drive {d["index"]} is not 3 points'
        if _expected_kick_after(d) and not [k for k in _kicks_after(record, d['index'])
                                            if k['kind'] == 'post_field_goal']:
            return FAIL, f'made field goal drive {d["index"]} has no kickoff by the kicker'
    for d in sft:
        if d['points_scored_on_drive']['points'] != gs.SAFETY_POINTS:
            return FAIL, f'safety drive {d["index"]} is not 2 points'
        follow = [k for k in _kicks_after(record, d['index']) if k['kind'] == 'safety_free_kick']
        if (record.get('blocker') == 'safety_free_kick_not_modelled' and not follow
                and d is record['drives'][-1]):
            return BLOCKED, f'safety drive {d["index"]}: no separate observed safety-free-kick outcome table; game blocked'
        if _expected_kick_after(d) and (not follow or follow[0]['kicking_team'] != d['offense_team']):
            return FAIL, f'safety drive {d["index"]}: the free kick is not by the conceding team'
    return PASS, (f'{made} made field goal(s) (3 each, kicker kicks off), {missed} missed, '
                  f'{len(sft)} safety(ies) (2 each)')


def _clock(record):
    for d in record['drives']:
        if not 0 <= d['clock_start'] <= gs.QUARTER_LENGTH:
            return FAIL, f'drive {d["index"]} starts at clock {d["clock_start"]}'
        if d['plays'][0]['state_before']['clock_seconds'] != d['clock_start']:
            return FAIL, f'drive {d["index"]}: the clock at its start does not match its first play'
        for p in d['plays']:
            a, b = p['state_before'], p['state_after']
            if a['quarter'] == b['quarter'] and b['clock_seconds'] > a['clock_seconds']:
                return FAIL, f'drive {d["index"]}: the clock rose inside Q{a["quarter"]}'
            if not 0 <= b['clock_seconds'] <= gs.QUARTER_LENGTH:
                return FAIL, f'drive {d["index"]}: clock {b["clock_seconds"]} is outside 0..900'
    return PASS, f"{len(record['drives'])} drives: every clock within 0..900 and never rising inside a quarter"


def _continuity(record):
    drives = record['drives']
    if drives[0]['offense_team'] != record['kickoffs'][0]['receiving_team']:
        return FAIL, 'the first drive does not start with the Q1 receiver'
    halftime_after = {b['drive_index'] for b in record['boundaries'] if b['kind'] == 'halftime'}
    for prev, nxt in zip(drives, drives[1:]):
        # The second half is opened by its own kickoff, whichever event ran the clock.
        if prev['index'] in halftime_after:
            continue
        if nxt['offense_team'] == prev['offense_team']:
            return FAIL, (f'drives {prev["index"]} and {nxt["index"]} have the same offense with no halftime '
                          f'between them')
    return PASS, f'{len(drives)} drives chain: each new drive starts with the team the previous event gave the ball to'


def _points(record):
    by = {'A': 0, 'B': 0}
    for d in record['drives']:
        p = d['points_scored_on_drive']
        if p:
            by[p['team']] += p['points']
    if by != record['points']:
        return FAIL, f'drives score {by}, the record says {record["points"]}'
    return PASS, f'drives score {by}, equal to the record'


def _provisional(record):
    """The two practice-sourced clock rules, recomputed from the drives: a score that expires Q1 or Q3 is followed by a
    kickoff in the next quarter, and a score that expires Q2 is not. Pending the 2026 rulebook, so PROVISIONAL,
    never PASS.
    """
    kicked = skipped = 0
    for d in record['drives']:
        if d['points_scored_on_drive'] is None or not _ends_on_zero(d):
            continue
        follow = [k for k in _kicks_after(record, d['index'])]
        if d['end_quarter'] in (1, 3):
            if not follow:
                return FAIL, f'drive {d["index"]} scored at the Q{d["end_quarter"]} expiry with no kickoff after it'
            kicked += 1
        elif d['end_quarter'] == 2:
            if follow:
                return FAIL, f'drive {d["index"]} scored at the Q2 expiry and still kicked off'
            skipped += 1
    if not kicked and not skipped:
        return NOT_APPLICABLE, 'no score expired a quarter in this game'
    return PROVISIONAL, (f'practice rule, pending the 2026 rulebook: {kicked} post-score kickoff(s) after a Q1/Q3 '
                         f'expiry, {skipped} score(s) at the Q2 expiry with no post-score kickoff')


def _kick_duration(record):
    """A made field goal takes at most five seconds of clock: the kick itself, measured on the published nfl_pbp (see
    game_state.KICK_DURATION_SECONDS). A kick whose separation was not applied (the clock expired on it) is not checked."""
    checked = 0
    for d in record['drives']:
        if d['terminal'] != 'field_goal_attempt' or d['field_goal_made'] is not True:
            continue
        kick = d['plays'][-1]
        if kick['outcome'].get('kick_duration_seconds') is None:
            continue
        checked += 1
        if kick['outcome']['clock_runoff_seconds'] > KICK_DURATION_MAX:
            return FAIL, (f'made field goal in drive {d["index"]} charged {kick["outcome"]["clock_runoff_seconds"]} s; '
                          f'the maximum is {KICK_DURATION_MAX} s')
    if not checked:
        return NOT_APPLICABLE, 'no made field goal with a separated kick duration in this game'
    return PASS, f'{checked} made field goal(s) charged at most {KICK_DURATION_MAX} s of clock'


def _missed_fg_spot(record):
    """A missed field goal gives the receiving team the spot of the kick, or its own 20 when that spot is inside its 20.

    The kick spot is the holder's spot: the snap position plus HOLDER_OFFSET, capped at 99. The published yardline_100 is the
    snap position, so the check takes the snap from the state and adds the offset itself, and does not read the engine's
    recorded kick spot. Source: the review note cites Rule 11-4-2. The rulebook text is not in the repository, so the rule is
    marked as cited, not verified.
    """
    checked = 0
    for i, d in enumerate(record['drives']):
        if d['terminal'] != 'field_goal_attempt' or d['field_goal_made'] is not False:
            continue
        if i + 1 >= len(record['drives']):
            continue  # the game ended on the miss: no next drive to check
        snap_yl = d['plays'][-1]['state_before']['yardline_100']
        kick_spot = min(99, snap_yl + HOLDER_OFFSET)
        spot = 100 - kick_spot
        expected = 80 if spot > 80 else spot
        nxt = record['drives'][i + 1]
        got = nxt['plays'][0]['state_before']['yardline_100']
        if nxt['offense_team'] == d['offense_team'] or got != expected:
            return FAIL, (f'missed field goal in drive {d["index"]} from snap {snap_yl} (kick spot {kick_spot}): next drive '
                          f'starts at {got}, expected {expected}')
        checked += 1
    if not checked:
        return NOT_APPLICABLE, 'no missed field goal followed by a drive in this game'
    return PASS, f'{checked} missed field goal(s): receiving team at the kick spot (snap + {HOLDER_OFFSET}), or its own 20'


def _drive_index(record):
    """Every play's state_before and state_after carry its drive's game-level index, and the indices run 1..n."""
    indices = [d['index'] for d in record['drives']]
    if indices != list(range(1, len(indices) + 1)):
        return FAIL, f'drive indices are not 1..{len(indices)}: {indices[:10]}'
    bad_drives, bad_states, examples = gs.drive_index_mismatches(record)
    if bad_drives:
        return FAIL, (f'{len(bad_drives)} drive-index mismatches: {bad_states} play states in drives {bad_drives}; '
                      f'first: {examples[0]}')
    return PASS, f'{len(indices)} drives, every play state carries its drive index'


def _provisional_into(record, quarter):
    """Kickoffs that open `quarter` after a score: the practice-sourced rule, recomputed from the kickoffs."""
    return sum(1 for k in record['kickoffs'] if k['kind'] != 'half_start' and k['quarter'] == quarter
               and k['clock_before'] == gs.QUARTER_LENGTH)


def _provisional_skips(record):
    """Scores that expire Q2: the practice rule says no post-score kickoff follows them."""
    return sum(1 for d in record['drives'] if d['terminal'] in SCORING and d['end_quarter'] == 2 and _ends_on_zero(d))


def _provisional_expiry_scores(record, terminals):
    """Scores that expire Q1 or Q3: the post-score kickoff that follows is the practice rule."""
    return sum(1 for d in record['drives'] if d['terminal'] in terminals and d['end_quarter'] in (1, 3)
               and _ends_on_zero(d) and d['points_scored_on_drive'] is not None)


# A row whose PASS depends on a practice-sourced rule is reported PROVISIONAL, never PASS.
PROVISIONAL_DEPENDENCIES = {
    'Q1->Q2 change of ends': lambda r: ('kickoffs that open Q2 after a score', _provisional_into(r, 2)),
    'Q3->Q4 change of ends': lambda r: ('kickoffs that open Q4 after a score', _provisional_into(r, 4)),
    'Q2->Q3 halftime: kickoff, clock reset, second-half choice':
        lambda r: ('scores that expire Q2 with no post-score kickoff', _provisional_skips(r)),
    'Touchdown: six points, a distinct try, post-score kickoff':
        lambda r: ('touchdowns that expire Q1 or Q3, kicked off in the next quarter',
                   _provisional_expiry_scores(r, ('touchdown',))),
    'Made field goal (3) and safety (2), with the correct post-score kick':
        lambda r: ('field goals and safeties that expire Q1 or Q3, kicked off in the next quarter',
                   _provisional_expiry_scores(r, ('field_goal_attempt', 'safety'))),
}


def _mark_provisional(record, rows):
    for row in rows:
        dep = PROVISIONAL_DEPENDENCIES.get(row['case'])
        if dep is None or row['status'] != PASS:
            continue
        label, count = dep(record)
        if count:
            row['status'] = PROVISIONAL
            row['evidence'] = (f"{row['evidence']}; provisional practice rule, pending the 2026 rulebook: "
                               f"{count} {label}")
    return rows


def _guards(record):
    """Every unmodelled rule carries a named guard in the record. A missing guard fails; a guard never makes a rule PASS."""
    guards = record.get('guards', {})
    missing = [r for r in gs.UNSUPPORTED_RULES if not guards.get(r, {}).get('guard')]
    if missing:
        return FAIL, f'unsupported rules without a guard: {missing}'
    return UNSUPPORTED, f'{len(gs.UNSUPPORTED_RULES)} unmodelled rules, each with a named guard'


def check(record):
    """The matrix rows for one record. Ledger rows use the ledger's own teams; every other row reads the record."""
    rows = []

    def add(case, result):
        status, evidence = result
        rows.append({'case': case, 'status': status, 'evidence': evidence})

    ledger = record['ledger']
    expected = {k['quarter']: k for k in gs.CoinTossLedger(ledger['winner'], ledger['loser'],
                                                            ledger['winner_choice']).half_start_kickoffs()}
    add('Opening toss winner defers, opponent receives', _defer_row(record, True))
    add('Opening winner receives (normal policy)', _defer_row(record, False))
    add('Winner chooses kick (normal mode)', _refused('kick'))
    add('Winner chooses defended goal first (normal mode)', _refused('defend_goal'))
    add('Explicit exception coin-toss path', _exception_refused())
    add('Q1->Q2 change of ends', _change_of_ends(record, 1))
    add('Q3->Q4 change of ends', _change_of_ends(record, 3))
    add('Q2->Q3 halftime: kickoff, clock reset, second-half choice', _halftime(record, expected))
    add('Both half-opening kickoffs, one per team, verified against the ledger', _both_half_kickoffs(record))
    add('Turnover on downs in Q2', _turnover_on_downs_q2(record))
    add('Touchdown: six points, a distinct try, post-score kickoff', _touchdowns(record))
    add('Missed field goal: receiving team at the kick spot or its own 20 (Rule 11-4-2, as cited)', _missed_fg_spot(record))
    add('Field goal made: the kick takes at most five seconds of clock', _kick_duration(record))
    add('Made field goal (3) and safety (2), with the correct post-score kick', _fg_safety(record))
    add('Clock: 15-minute quarters, no clock increase, end of Q1/Q3 is not a drive terminal', _clock(record))
    add('Continuity between drives and quarters', _continuity(record))
    add('Drive index: every play state carries its game-level drive index', _drive_index(record))
    add('Points equal the points on the drives', _points(record))
    add('Provisional clock rules: practice-sourced, pending the 2026 rulebook', _provisional(record))
    add('Timeouts: three per team per half', (UNSUPPORTED, 'not drawn: the published table has no timeout fields. A sampled '
                                                           'play flagged with a timeout charges one of the three to the side it '
                                                           'names, if that side has one left; its stoppage is inside the observed '
                                                           'runoff; the rule itself is not checked against the rulebook'))
    add('Unmodelled rules: each carries a named guard', _guards(record))
    add('Two-minute warning crossing marker', _two_minute_warning(record))
    add('Clock running/stopped and restart state',
        (UNSUPPORTED, record.get('guards', {}).get('clock_start_stop', {}).get('guard', 'missing clock_start_stop guard')))
    add('Penalties and untimed-down extensions', (UNSUPPORTED, 'not modelled: E1 excludes penalty plays from its pool'))
    add('Onside kick', (UNSUPPORTED, 'not modelled: every kickoff is drawn from the observed kickoff pool'))
    if record['tied']:
        add('Overtime after a tie',
            (BLOCKED, 'tied after regulation: overtime is not modelled, so the game is blocked'))
    else:
        add('Overtime after a tie', (NOT_APPLICABLE, 'no tie after regulation'))
    sampled = sum(1 for d in record['drives'] for p in d['plays']
                  if p['participants']['attribution'] == 'sampled_observed_play')
    add('Player lineups and physical motion', (UNSUPPORTED, f'not modelled; {sampled} plays carry labelled sampled '
                                                             "participants, not this game's lineup"))
    fourth = Counter(p['decision']['type'] for d in record['drives'] for p in d['plays']
                     if p['state_before']['down'] == 4)
    add('Fourth-down choices: punt, field goal or go for it',
        (PARTIAL, f'sampled from observed plays by down, distance and field position: {dict(fourth)}; not conditioned '
                  f'on score or time'))
    return _mark_provisional(record, rows)


def summary(rows):
    return dict(Counter(r['status'] for r in rows))
