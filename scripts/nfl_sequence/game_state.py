"""E2 first piece: coin-toss ledger, half-start kickoffs, and linkage of E1 drives into one game.

Scope in this piece:
- the coin-toss ledger for the normal-game policy (docs/rules/NFL-2026-GAME-STATE-RULES.md, section 3 and 7):
  the first-choice captain receives, and each team kicks off once per half;
- the two half-start kickoffs, derived from the ledger and validated;
- restarts after scores (the scoring team kicks off), after a safety (the conceding team kicks the free kick), at
  halftime (the second-half kickoff), and after punts and turnovers (the receiving team starts at its published spot);
- field goals: made for 3 and a kickoff by the kicker, or missed and the other team takes over at the spot of the kick;
- tries: after each touchdown (6 points), an extra point (1) or a two-point try (2), then the kickoff;
- the clock carried between drives, and regulation end.

Kick outcomes are drawn from the published nfl_pbp rates (scripts/nfl_sequence/measure_kick_outcomes.py, 2022-2025,
weeks 1-18): a field goal's make rate in its yardline_100 bucket, the extra-point rate, the two-point rate, and
the share of post-touchdown attempts that were two-point tries. Each draw is a labelled sample from that published rate. It is not
the outcome of a real game. A cell with fewer than MIN_KICK_N attempts blocks the game; nothing is filled from a
neighbouring cell.

Explicitly not modelled, and handled as branches that stop the game:
- blocked kicks, returned misses and touchbacks: a missed kick gives the other team the spot of the kick;
- restarts that cross a quarter end, including a score in the last seconds of a half;
- a change of possession with the clock already at zero;
- onside kicks, overtime, penalties, timeouts, the exception coin-toss paths (`explicit_exception_scenario`), and player
  statistics (no participants are supplied).

Kickoff convention in the published nfl_pbp (measured 2026-10-24): on a kickoff row `posteam` is the RECEIVING team and
`defteam` is the KICKING team. The receiving team's next run or pass in the same quarter gives the starting spot.
"""
import random
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402

NORMAL_MODE = 'normal_nfl_game'
EXCEPTION_MODE = 'explicit_exception_scenario'
QUARTER_LENGTH = 900
TD_POINTS = 6
FG_POINTS = 3
SAFETY_POINTS = 2
TRY_POINTS = {'extra_point': 1, 'two_point': 2}
FG_BUCKETS = ('1-9', '10-19', '20-29', '30-39', '40-49', '50+')
MIN_KICK_N = 30  # a thinner published cell is refused, the same floor E1 applies to its pool cells


def other(team, teams):
    return teams[1] if team == teams[0] else teams[0]


def fg_bucket(yardline_100):
    """The yardline_100 bucket of a field goal, with the same labels as measure_kick_outcomes.BUCKET."""
    for limit, label in ((10, '1-9'), (20, '10-19'), (30, '20-29'), (40, '30-39'), (50, '40-49')):
        if yardline_100 < limit:
            return label
    return '50+'


class CoinTossLedger:
    """Normal-game coin-toss ledger for two teams, `winner` and `loser`.

    `winner_choice` is `receive` or `defer`. Normal mode refuses kick and goal-to-defend choices, which the rules file
    says must not be sampled. The first-choice captain receives. In the defer path the loser has the first-half choice,
    and the winner has the second-half choice.
    """

    def __init__(self, winner, loser, winner_choice, mode=NORMAL_MODE):
        if winner == loser:
            raise ValueError('winner and loser must differ')
        if mode == EXCEPTION_MODE:
            raise NotImplementedError('explicit_exception_scenario is not implemented in the first E2 piece')
        if mode != NORMAL_MODE:
            raise ValueError(f'unknown policy mode {mode!r}')
        if winner_choice not in ('receive', 'defer'):
            raise ValueError(f'normal_nfl_game: winner choice {winner_choice!r} is not eligible; only receive or defer')
        self.teams = (winner, loser)
        self.winner, self.loser = winner, loser
        self.winner_choice = winner_choice
        self.mode = mode
        self.deferred = winner_choice == 'defer'
        self.first_chooser = loser if self.deferred else winner
        self.second_chooser = winner if self.deferred else loser
        # Normal mode: the first-choice captain receives. The opening receiver is the first chooser (defer: the loser).
        self.q1_receiver = self.first_chooser
        self.q1_kicker = other(self.q1_receiver, self.teams)
        self.q3_receiver = self.second_chooser
        self.q3_kicker = other(self.q3_receiver, self.teams)
        # Goal privileges go to the team that does not hold the choice. These orient the field; they are authored
        # simulation choices, labelled as such in every record.
        self.goal_first_half = other(self.first_chooser, self.teams)
        self.goal_second_half = other(self.second_chooser, self.teams)

    def ledger(self):
        return {'winner': self.winner, 'loser': self.loser, 'winner_choice': self.winner_choice,
                'winner_deferred': self.deferred, 'first_half_chooser': self.first_chooser,
                'second_half_chooser': self.second_chooser, 'policy_mode': self.mode,
                'source': 'authored_simulation_choice'}

    def half_start_kickoffs(self):
        return [
            {'quarter': 1, 'kicking_team': self.q1_kicker, 'receiving_team': self.q1_receiver, 'reason': 'half_start'},
            {'quarter': 3, 'kicking_team': self.q3_kicker, 'receiving_team': self.q3_receiver, 'reason': 'half_start'},
        ]

    def attacks_x100(self, team, quarter):
        """Orientation: +1 when `team` attacks stadium x=100 in `quarter`. Authored, not sourced.

        Q1 goal-first-half team defends x=0; ends change after Q1, so Q2 flips. Halftime does not flip ends.
        Q3 uses the second-half goal choice (authored); ends change after Q3, so Q4 flips.
        """
        if quarter == 1:
            attacker = self.goal_first_half
        elif quarter == 2:
            attacker = other(self.goal_first_half, self.teams)
        elif quarter == 3:
            attacker = self.second_chooser
        else:
            attacker = other(self.second_chooser, self.teams)
        return 1 if team == attacker else -1


def validate_half_start(kickoffs):
    """Fail closed on the normal-game invariant: exactly two half-start kickoffs, one per team, Q3 receiver kicks Q1."""
    half = [k for k in kickoffs if k['reason'] == 'half_start']
    if len(half) != 2 or sorted(k['quarter'] for k in half) != [1, 3]:
        raise AssertionError(f'expected two half-start kickoffs in Q1 and Q3, got {half}')
    kickers = {k['kicking_team'] for k in half}
    if len(kickers) != 2:
        raise AssertionError(f'normal game: the same team kicks both half-start kickoffs: {half}')
    q1, q3 = sorted(half, key=lambda k: k['quarter'])
    if q3['receiving_team'] != q1['kicking_team'] or q3['kicking_team'] != q1['receiving_team']:
        raise AssertionError('Q3 kickoff must reverse the Q1 kickoff teams in a normal game')


def build_kickoff_pool(rows):
    """Starting spots and time after kickoffs, from published kickoff rows (receiving team = posteam)."""
    by_game = {}
    for r in rows:
        by_game.setdefault(r['game_id'], []).append(r)
    pool, excluded = [], Counter()
    for plays in by_game.values():
        for i, row in enumerate(plays[:-1]):
            if row['play_type'] != 'kickoff':
                continue
            nxt = plays[i + 1]
            if (nxt['posteam'] != row['posteam'] or nxt['play_type'] not in ('run', 'pass')
                    or nxt['qtr'] != row['qtr'] or nxt['yardline_100'] is None
                    or row['game_seconds_remaining'] is None or nxt['game_seconds_remaining'] is None):
                excluded['kickoff without a clean receiving snap'] += 1
                continue
            runoff = int(round(row['game_seconds_remaining'] - nxt['game_seconds_remaining']))
            spot = int(nxt['yardline_100'])
            if runoff < 0 or not 1 <= spot <= 99:
                excluded['kickoff with an impossible runoff or spot'] += 1
                continue
            pool.append({'spot': spot, 'runoff': runoff, 'game_id': row['game_id'], 'play_id': int(row['play_id']),
                         'game_date': row['game_date']})
    return pool, excluded


def _restart(kind, kicker, receiver, quarter, clock, kickoff_pool, rng, events):
    """Sample a kickoff from the pool and return (clock_after, spot), or (None, reason) if it cannot be placed."""
    sample = rng.choice(kickoff_pool)
    clock_after = clock - sample['runoff']
    events.append({'kind': kind, 'kicking_team': kicker, 'receiving_team': receiver, 'quarter': quarter,
                   'clock_before': clock, 'runoff_seconds': sample['runoff'], 'spot_yardline_100': sample['spot'],
                   'source': {'game_id': sample['game_id'], 'play_id': sample['play_id'],
                              'game_date': sample['game_date']}})
    if clock_after <= 0:
        return None, 'restart_crosses_quarter_end'
    return clock_after, sample['spot']


def _draw(rng, cell, name):
    """A made or missed draw at the published rate of `cell` = (made, missed).

    Returns (made, None), or (None, reason) when the cell is too thin.
    """
    made, missed = cell
    if made + missed < MIN_KICK_N:
        return None, f'thin_kick_cell:{name}'
    return rng.random() < made / (made + missed), None


def _try_after_touchdown(rng, kicks):
    """The try after a touchdown: a two-point try at the published share of post-touchdown attempts, else an extra
    point.

    Returns (points, record, None), or (None, None, reason) when the cell it needs is too thin.
    """
    two_tries = sum(kicks['two_point'])
    total = two_tries + sum(kicks['extra_point'])
    kind = 'two_point' if rng.random() < (two_tries / total if total else 0) else 'extra_point'
    made, why = _draw(rng, kicks[kind], kind)
    if why:
        return None, None, why
    return (TRY_POINTS[kind] if made else 0), {'kind': kind, 'made': made}, None


def play_game(seed, pool, kickoff_pool, kicks, winner_choice=None, max_drives=80):
    """Link E1 drives into one game under the normal-game policy. Returns a record; it never raises for a branch.

    `kicks` is the published kick table (measure_kick_outcomes.load_kick_table). It is required, so a game is never
    played with a silent default.
    """
    rng = random.Random(seed)
    choice = winner_choice or rng.choice(['receive', 'defer'])
    ledger = CoinTossLedger('A', 'B', choice)
    kickoffs = ledger.half_start_kickoffs()
    validate_half_start(kickoffs)
    events, drives = [], []
    points = Counter()
    blocker = None
    quarter, clock = 1, QUARTER_LENGTH
    status = None

    # Opening kickoff: Q1 half-start.
    clock_after, spot = _restart('half_start', kickoffs[0]['kicking_team'], kickoffs[0]['receiving_team'],
                                 1, clock, kickoff_pool, rng, events)
    if clock_after is None:
        blocker, status = spot, 'blocked'
        spot = None
    else:
        clock = clock_after
    offense = kickoffs[0]['receiving_team']
    defense = other(offense, ledger.teams)
    yl = spot
    down, togo = 1, 10
    while status is None:
        if len(drives) >= max_drives:
            blocker, status = 'drive_limit', 'blocked'
            break
        start = {'quarter': quarter, 'clock': clock, 'offense': offense, 'defense': defense, 'yl': yl, 'down': down,
                 'togo': togo, 'dir': ledger.attacks_x100(offense, quarter)}
        simulation_id = f'e2-{seed}-drive{len(drives) + 1}'
        plays, terminal = e1.simulate(start, seed * 1000 + len(drives), pool, simulation_id)
        if plays is None:
            blocker, status = terminal, 'blocked'
            break
        e1.check_drive(plays, terminal)
        last = plays[-1]['state_after']
        drive = {'index': len(drives) + 1, 'offense_team': offense, 'quarter_start': quarter,
                 'clock_start': clock, 'plays': len(plays), 'terminal': terminal,
                 'end_quarter': last['quarter'], 'end_clock': last['clock_seconds'],
                 'points_scored_on_drive': None, 'field_goal_made': None}
        drives.append(drive)
        quarter, clock = last['quarter'], last['clock_seconds']
        if terminal == 'end_of_regulation':
            status = 'complete_regulation'
            break

        change = None  # (new offense, spot) when possession changes without a kickoff
        restart = None  # (kind, kicker, receiver) when a kickoff follows
        if terminal == 'field_goal_attempt':
            kick_yl = plays[-1]['state_before']['yardline_100']
            bucket = fg_bucket(kick_yl)
            made, why = _draw(rng, kicks['field_goal'].get(bucket, (0, 0)), f'field_goal:{bucket}')
            if why:
                blocker, status = why, 'blocked'
                break
            drive['field_goal_made'] = made
            if made:
                points[offense] += FG_POINTS
                drive['points_scored_on_drive'] = {'team': offense, 'points': FG_POINTS, 'try': None}
                restart = ('post_field_goal', offense, other(offense, ledger.teams))
            else:
                change = (defense, 100 - kick_yl)  # the other team takes over at the spot of the kick
        elif terminal in ('punt', 'turnover', 'turnover_on_downs'):
            change = (last['offense_team'], last['yardline_100'])
        elif terminal == 'touchdown':
            scorer = offense
            try_points, try_record, why = _try_after_touchdown(rng, kicks)
            if why:
                blocker, status = why, 'blocked'
                break
            points[scorer] += TD_POINTS + try_points
            drive['points_scored_on_drive'] = {'team': scorer, 'points': TD_POINTS + try_points, 'try': try_record}
            restart = ('post_score', scorer, other(scorer, ledger.teams))
        elif terminal == 'safety':
            scorer = defense
            points[scorer] += SAFETY_POINTS
            drive['points_scored_on_drive'] = {'team': scorer, 'points': SAFETY_POINTS, 'try': None}
            restart = ('safety_free_kick', offense, scorer)
        elif terminal == 'halftime':
            quarter, clock = 3, QUARTER_LENGTH
            restart = ('half_start', kickoffs[1]['kicking_team'], kickoffs[1]['receiving_team'])
        else:
            blocker, status = f'unhandled_terminal:{terminal}', 'blocked'
            break

        if change is not None:
            if clock == 0:
                blocker, status = 'possession_change_at_zero_clock', 'blocked'
                break
            offense, yl = change
            defense = other(offense, ledger.teams)
            down, togo = 1, min(10, yl)
            continue

        kind, kicker, receiver = restart
        clock_after, spot = _restart(kind, kicker, receiver, quarter, clock, kickoff_pool, rng, events)
        if clock_after is None:
            blocker, status = spot, 'blocked'
            break
        clock = clock_after
        offense, defense = receiver, kicker
        yl, down, togo = spot, 1, 10

    tied = points['A'] == points['B']
    completed = status == 'complete_regulation'
    record = {
        'mode': 'legal_game_state_first_piece', 'seed': seed, 'valid_full_game': False,
        'ledger': ledger.ledger(), 'kickoffs': events, 'drives': drives,
        'points': {'A': points['A'], 'B': points['B']},
        'status': status or 'blocked', 'blocker': blocker, 'tied': tied,
        'final_quarter': quarter, 'final_clock_seconds': clock,
        'gaps': ['field-goal and try outcomes are drawn from the published nfl_pbp rates (2022-2025, weeks 1-18): '
                 'each draw is a labelled sample, not the result of a real game',
                 'blocked kicks and returned misses are not modelled: a missed kick gives the other team the kick spot',
                 'restarts that cross a quarter end, including a score in the last seconds of a half, block the game',
                 'onside kicks, overtime, penalties, timeouts and the exception coin-toss paths are not modelled',
                 'player statistics are null: no participants are supplied'],
    }
    record['valid_full_game'] = bool(completed and not tied and blocker is None)
    return record


def validate_game(record):
    """Fail closed on every ledger and ordering invariant. Returns the list of checks that passed.

    The recorded half-start kickoffs must equal the ledger's expected kickoffs. A game blocked before halftime has only
    the Q1 kickoff, so the two-kickoff invariant applies only when the Q3 kickoff was reached.
    """
    checks = []
    ledger = record['ledger']
    expected = CoinTossLedger(ledger['winner'], ledger['loser'], ledger['winner_choice'], ledger['policy_mode'])
    expected_half = expected.half_start_kickoffs()
    recorded_half = [k for k in record['kickoffs'] if k['kind'] == 'half_start']
    if len(recorded_half) > 2:
        raise AssertionError(f'more than two half-start kickoffs recorded: {recorded_half}')
    for got in recorded_half:
        want = next((k for k in expected_half if k['quarter'] == got['quarter']), None)
        if want is None or (got['kicking_team'], got['receiving_team']) != (want['kicking_team'], want['receiving_team']):
            raise AssertionError(f'recorded half-start kickoff disagrees with the ledger: {got}')
    checks.append('recorded half-start kickoffs equal the ledger')
    if len(recorded_half) == 2:
        validate_half_start([{'quarter': k['quarter'], 'kicking_team': k['kicking_team'],
                              'receiving_team': k['receiving_team'], 'reason': 'half_start'} for k in recorded_half])
        checks.append('two half-start kickoffs, one per team, Q3 reverses Q1')
    elif record['final_quarter'] >= 3 and record['status'] == 'complete_regulation':
        raise AssertionError('a complete game must have two half-start kickoffs')
    by_team = Counter()
    for d in record['drives']:
        p = d['points_scored_on_drive']
        last_drive = d is record['drives'][-1]
        if d['terminal'] == 'touchdown':
            if p is None:  # only a try that could not be drawn (a thin cell) leaves a touchdown unscored, and it blocks
                if record['blocker'] is None or not last_drive:
                    raise AssertionError(f'touchdown drive without a recorded try: {d}')
            else:
                t = p['try']
                if t is None or t['kind'] not in TRY_POINTS:
                    raise AssertionError(f'touchdown drive without a recorded try: {d}')
                if p['points'] != TD_POINTS + (TRY_POINTS[t['kind']] if t['made'] else 0):
                    raise AssertionError(f'touchdown points disagree with the try: {d}')
        if d['terminal'] == 'field_goal_attempt' and d['field_goal_made'] is not None:
            if d['field_goal_made'] != bool(p):
                raise AssertionError(f'field goal result disagrees with its points: {d}')
        if p is not None:
            by_team[p['team']] += p['points']
    if by_team['A'] != record['points']['A'] or by_team['B'] != record['points']['B']:
        raise AssertionError('points ledger disagrees with the points recorded on each drive')
    checks.append('game points equal the points recorded on each drive, touchdown tries included')
    quarter_prev = 0
    for d in record['drives']:
        if d['quarter_start'] < quarter_prev:
            raise AssertionError('quarter went backwards')
        quarter_prev = d['quarter_start']
    checks.append('quarters never decrease')
    if record['valid_full_game']:
        if record['status'] != 'complete_regulation' or record['blocker'] is not None or record['tied']:
            raise AssertionError('valid_full_game requires complete regulation, no blocker and no tie')
    checks.append('valid_full_game only when complete, unblocked and untied')
    return checks
