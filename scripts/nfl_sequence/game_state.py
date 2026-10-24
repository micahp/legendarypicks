"""E2 first piece: coin-toss ledger, half-start kickoffs, and linkage of E1 drives into one game.

Scope in this piece:
- the coin-toss ledger for the normal-game policy (docs/rules/NFL-2026-GAME-STATE-RULES.md, section 3 and 7):
  the first-choice captain receives, and each team kicks off once per half;
- the two half-start kickoffs, derived from the ledger and validated;
- restarts after scores (the scoring team kicks off), after a safety (the conceding team kicks the free kick), at
  halftime (the second-half kickoff), and after punts and turnovers (the receiving team starts at its published spot);
- a scoring ledger for touchdowns (6, with the try pending) and safeties (2);
- the clock carried between drives, and regulation end.

Explicitly not modelled, and handled as branches that stop or stay pending:
- field-goal results: an attempt stops the game as `field_goal_result_unpublished`. The result IS in nfl_pbp
  (`series_result`, measured in docs/SEQUENCE-E2-FIRST-PIECE-2026-10-24.md); the engine does not consume it yet, and the
  blocker key keeps its old name so this pass changes no engine behaviour;
- try (extra point and two-point) results: a touchdown leaves its try pending, so the game cannot be valid. The result
  IS in nfl_pbp (`success`), and the engine does not consume it yet;
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
SAFETY_POINTS = 2


def other(team, teams):
    return teams[1] if team == teams[0] else teams[0]


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


def play_game(seed, pool, kickoff_pool, winner_choice=None, max_drives=80):
    """Link E1 drives into one game under the normal-game policy. Returns a record; it never raises for a branch."""
    rng = random.Random(seed)
    choice = winner_choice or rng.choice(['receive', 'defer'])
    ledger = CoinTossLedger('A', 'B', choice)
    kickoffs = ledger.half_start_kickoffs()
    validate_half_start(kickoffs)
    events, drives = [], []
    points, pat_pending = Counter(), Counter()
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
        drives.append({'index': len(drives) + 1, 'offense_team': offense, 'quarter_start': quarter,
                       'clock_start': clock, 'plays': len(plays), 'terminal': terminal,
                       'end_quarter': last['quarter'], 'end_clock': last['clock_seconds'],
                       'points_scored_on_drive': None})
        quarter, clock = last['quarter'], last['clock_seconds']
        if terminal == 'field_goal_attempt':
            blocker, status = 'field_goal_result_unpublished', 'blocked'
            break
        if terminal == 'end_of_regulation':
            status = 'complete_regulation'
            break
        if terminal in ('punt', 'turnover', 'turnover_on_downs'):
            offense = last['offense_team']
            defense = other(offense, ledger.teams)
            yl = last['yardline_100']
            down, togo = 1, min(10, yl)
            continue
        if terminal == 'touchdown':
            scorer = offense
            points[scorer] += TD_POINTS
            pat_pending[scorer] += 1
            drives[-1]['points_scored_on_drive'] = {'team': scorer, 'points': TD_POINTS, 'try': 'pending'}
            kicker, receiver, kind = scorer, other(scorer, ledger.teams), 'post_score'
        elif terminal == 'safety':
            scorer = defense
            points[scorer] += SAFETY_POINTS
            drives[-1]['points_scored_on_drive'] = {'team': scorer, 'points': SAFETY_POINTS, 'try': None}
            kicker, receiver, kind = offense, scorer, 'safety_free_kick'
        elif terminal == 'halftime':
            kicker, receiver, kind = kickoffs[1]['kicking_team'], kickoffs[1]['receiving_team'], 'half_start'
            quarter, clock = 3, QUARTER_LENGTH
        else:
            blocker, status = f'unhandled_terminal:{terminal}', 'blocked'
            break
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
        'pat_pending': {'A': pat_pending['A'], 'B': pat_pending['B']},
        'status': status or 'blocked', 'blocker': blocker, 'tied': tied,
        'final_quarter': quarter, 'final_clock_seconds': clock,
        'gaps': ['field-goal results are published in nfl_pbp (series_result) but not consumed: '
                 'an attempt stops the game',
                 'try results are published in nfl_pbp (success) but not consumed: touchdown points are pending',
                 'onside kicks, overtime, penalties, timeouts and the exception coin-toss paths are not modelled',
                 'player statistics are null: no participants are supplied'],
    }
    record['valid_full_game'] = bool(completed and not tied and sum(pat_pending.values()) == 0
                                     and blocker is None)
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
    td = sum(1 for d in record['drives'] if d['terminal'] == 'touchdown')
    safety = sum(1 for d in record['drives'] if d['terminal'] == 'safety')
    if sum(record['points'].values()) != TD_POINTS * td + SAFETY_POINTS * safety:
        raise AssertionError('points ledger disagrees with touchdown and safety drives')
    checks.append('points equal 6 per touchdown plus 2 per safety')
    if sum(record['pat_pending'].values()) != td:
        raise AssertionError('pending tries must equal touchdowns')
    checks.append('one pending try per touchdown')
    quarter_prev = 0
    for d in record['drives']:
        if d['quarter_start'] < quarter_prev:
            raise AssertionError('quarter went backwards')
        quarter_prev = d['quarter_start']
    checks.append('quarters never decrease')
    if record['valid_full_game']:
        if record['status'] != 'complete_regulation' or record['blocker'] is not None or record['tied']:
            raise AssertionError('valid_full_game requires complete regulation, no blocker and no tie')
        if sum(record['pat_pending'].values()) != 0:
            raise AssertionError('valid_full_game cannot have pending tries')
    checks.append('valid_full_game only when complete, unblocked, untied and with no pending tries')
    return checks
