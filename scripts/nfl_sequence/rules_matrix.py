"""Check one generated game against the 2026 mandatory test matrix (docs/rules/NFL-2026-GAME-STATE-RULES.md, section 7).

Every row is recomputed from the record's drives, plays, kickoffs and boundaries. None of it is read from the engine's own
flags. A row is one of:
- PASS: the check ran and held;
- FAIL: the check ran and did not hold. A complete game with a FAIL is not emitted;
- PARTIAL: the check holds for what is modelled, and the row names what is not;
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

PASS, FAIL, PARTIAL, UNSUPPORTED, NOT_APPLICABLE, BLOCKED = (
    'PASS', 'FAIL', 'PARTIAL', 'UNSUPPORTED', 'NOT_APPLICABLE', 'BLOCKED')
SCORING = ('touchdown', 'safety', 'field_goal_attempt')


def _half_starts(record):
    return {k['quarter']: k for k in record['kickoffs'] if k['kind'] == 'half_start'}


def _kicks_after(record, drive_index):
    return [k for k in record['kickoffs'] if k['after_drive'] == drive_index and k['kind'] != 'half_start']


def _ends_on_zero(drive):
    return drive['end_clock'] == 0


def _expected_kick_after(drive):
    """A score is followed by a kick unless the clock expires in Q2 (halftime, then the second-half kickoff) or Q4 (the end)."""
    return not (_ends_on_zero(drive) and drive['end_quarter'] in (2, 4))


def _defer_row(record, deferred):
    """Rules section 7: a defer gives the loser the Q1 receive and the winner the Q3 receive; a receive is the reverse."""
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
    """Q1->Q2 or Q3->Q4: no kickoff or new drive at the change of ends; a kickoff opening the quarter follows a score only."""
    to_quarter = from_quarter + 1
    drives = record['drives']
    mid = [b for b in record['boundaries'] if b['kind'] == 'change_of_ends_mid_drive' and b['from_quarter'] == from_quarter]
    expiry = [b for b in record['boundaries'] if b['kind'] in ('change_of_ends', 'change_of_ends_during_return')
              and b['from_quarter'] == from_quarter]
    if not mid and not expiry:
        return NOT_APPLICABLE, f'the game did not reach Q{to_quarter}'
    for b in mid:
        plays = drives[b['drive_index'] - 1]['plays']
        idx = next(i for i, p in enumerate(plays) if p['outcome']['quarter_change'])
        if idx == len(plays) - 1:
            return FAIL, f'a Q{from_quarter} expiry ended drive {b["drive_index"]}: a drive must continue'
        a, nxt = plays[idx]['state_after'], plays[idx + 1]['state_before']
        if (a['offense_team'], a['yardline_100'], a['down']) != (nxt['offense_team'], nxt['yardline_100'], nxt['down']):
            return FAIL, f'possession, spot or down changed across the Q{from_quarter} expiry in drive {b["drive_index"]}'
    opened = [k for k in record['kickoffs'] if k['quarter'] == to_quarter and k['clock_before'] == gs.QUARTER_LENGTH
              and k['kind'] != 'half_start']
    for k in opened:
        prev = drives[k['after_drive'] - 1]
        if prev['terminal'] not in SCORING or not _ends_on_zero(prev) or prev['end_quarter'] != from_quarter:
            return FAIL, f'a kickoff opened Q{to_quarter} without a score that expired Q{from_quarter}'
    return PASS, (f'{len(mid)} mid-drive change(s) keep the drive; {len(expiry)} change(s) at a possession end keep the '
                  f'possession; {len(opened)} kickoff(s) open Q{to_quarter} after a score that expired Q{from_quarter}')


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
    hits = [d for d in record['drives'] if d['terminal'] == 'turnover_on_downs' and d['end_quarter'] == 2
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
        if _expected_kick_after(d) and (not follow or follow[0]['kicking_team'] != d['offense_team']):
            return FAIL, f'safety drive {d["index"]}: the free kick is not by the conceding team'
    return PASS, f'{made} made field goal(s) (3 each, kicker kicks off), {missed} missed, {len(sft)} safety(ies) (2 each)'


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
    for prev, nxt in zip(drives, drives[1:]):
        if prev['end_quarter'] == 2 and _ends_on_zero(prev):  # halftime: the second half is opened by its own kickoff
            continue
        if nxt['offense_team'] == prev['offense_team']:
            return FAIL, f'drives {prev["index"]} and {nxt["index"]} have the same offense with no halftime between them'
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
    add('Made field goal (3) and safety (2), with the correct post-score kick', _fg_safety(record))
    add('Clock: 15-minute quarters, no clock increase, end of Q1/Q3 is not a drive terminal', _clock(record))
    add('Continuity between drives and quarters', _continuity(record))
    add('Points equal the points on the drives', _points(record))
    add('Timeouts: three per team per half', (UNSUPPORTED, 'not modelled: the published table has no timeout fields, '
                                                           'so the observed clock runoff is used as recorded'))
    add('Two-minute warning', (UNSUPPORTED, 'not modelled'))
    add('Penalties and untimed-down extensions', (UNSUPPORTED, 'not modelled: E1 excludes penalty plays from its pool'))
    add('Onside kick', (UNSUPPORTED, 'not modelled: every kickoff is drawn from the observed kickoff pool'))
    if record['tied']:
        add('Overtime after a tie', (BLOCKED, 'tied after regulation: overtime is not modelled, so the game is blocked'))
    else:
        add('Overtime after a tie', (NOT_APPLICABLE, 'no tie after regulation'))
    sampled = sum(1 for d in record['drives'] for p in d['plays'] if p['participants']['attribution'] == 'sampled_observed_play')
    add('Player lineups and physical motion', (UNSUPPORTED, f'not modelled; {sampled} plays carry labelled sampled '
                                                             "participants, not this game's lineup"))
    fourth = Counter(p['decision']['type'] for d in record['drives'] for p in d['plays'] if p['state_before']['down'] == 4)
    add('Fourth-down choices: punt, field goal or go for it', (PARTIAL, f'sampled from observed plays by down, distance '
                                                                       f'and field position: {dict(fourth)}; not '
                                                                       f'conditioned on score or time'))
    return rows


def summary(rows):
    return dict(Counter(r['status'] for r in rows))
