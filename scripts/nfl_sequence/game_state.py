"""E2 game: coin-toss ledger, kickoffs, scoring, clock management, and linkage of E1 drives into one regulation game.

Scope:
- the coin-toss ledger for the normal-game policy (docs/rules/NFL-2026-GAME-STATE-RULES.md, sections 1-3 and 7): the
  first-choice captain receives, and each team kicks off once per half;
- the two half-start kickoffs, derived from the ledger and validated;
- scoring: touchdowns (6, then a try: an extra point for 1, or a two-point try for 2), field goals (3, made or missed),
  and safeties (2);
- restarts after scores (the scoring team kicks off; a safety is a free kick by the conceding team), after halftime (the
  second-half kickoff), and after punts and turnovers (the receiving team starts at its published spot);
- clock management: quarters are 15 minutes, a quarter change keeps possession and the spot (no kickoff, rules section
  2), halftime ends the first half and starts the second with a kickoff (section 3), and the fourth-quarter expiry ends
  regulation. A clock that runs out on a score, a possession change or a kickoff is resolved by the quarter it expires
  in;
- participants: each play carries the observed passer, rusher and receiver ids of the play it was sampled from, labelled
  as such, and player and team lines are computed from the plays (game_stats.py).

Kick outcomes are drawn from the published nfl_pbp rates (measure_kick_outcomes.py, 2022-2025, weeks 1-18): a field
goal's make rate in its yardline_100 bucket, the extra-point rate, the two-point rate, and the share of post-touchdown
attempts that were two-point tries. Each draw is a labelled sample from a published rate, not the outcome of a real
game. A cell with fewer than MIN_KICK_N attempts blocks the game, and nothing is filled from a neighbouring cell.

Explicitly not modelled. Each one is listed in every record's `unsupported_rules`, and the rules matrix marks it:
timeouts (the published table has no timeout fields), the two-minute warning, penalties (E1 excludes penalty plays),
onside kicks, overtime (a tie after regulation blocks the game as `overtime_not_modelled`), the exception coin-toss
paths, and lineups (participants are the players on the sampled observed plays, not this game's roster).

Kickoff convention in the published nfl_pbp (measured 2026-10-24): on a kickoff row `posteam` is the RECEIVING team and
`defteam` is the KICKING team. The receiving team's next run or pass in the same quarter gives the starting spot.
"""
import random
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
import game_stats  # noqa: E402

NORMAL_MODE = 'normal_nfl_game'
EXCEPTION_MODE = 'explicit_exception_scenario'
QUARTER_LENGTH = 900
TD_POINTS = 6
FG_POINTS = 3
SAFETY_POINTS = 2
TRY_POINTS = {'extra_point': 1, 'two_point': 2}
FG_BUCKETS = ('1-9', '10-19', '20-29', '30-39', '40-49', '50+')
# The kick spot is the holder's position, not the snap. The published yardline_100 of a field goal is the snap position, the
# line of scrimmage. The holder stands HOLDER_OFFSET yards behind it, so the ball is kicked that much further from the goal.
# The offset is an authored placement value, not a number taken from the published data; the rules matrix carries its own
# copy and checks against it.
HOLDER_OFFSET = 7
# The clock a made field goal takes is the kick itself. Measured on the published nfl_pbp, 2022-2025: the game clock from a
# made kick's snap to the next snap (the kickoff) has a median of 4 s and is at most 5 s on 98.9% of 3,682 made kicks. The
# charge is capped at this value, and the rest of the observed runoff is not charged to the kick.
KICK_DURATION_SECONDS = 5
MIN_KICK_N = 30  # a thinner published cell is refused, the same floor E1 applies to its pool cells
UNSUPPORTED_RULES = ('timeouts', 'two_minute_warning', 'penalties', 'onside_kicks', 'overtime',
                     'exception_coin_toss', 'lineups')
# Each unmodelled rule has a named guard. A record must carry every guard; the matrix checks it, and no guard lets a
# record claim the rule is modelled.
GUARDS = {
    'timeouts': {'guard': 'no timeout is drawn: the published table has no timeout fields. A sampled play flagged with a timeout '
                          'charges one of the three per half to the side it names, if that side has one left (_apply_timeouts); '
                          'the stoppage is inside the observed runoff, and the rule itself is not checked against the rulebook',
                 'enforced_by': 'unsupported_rules; valid_full_game is false'},
    'two_minute_warning': {'guard': 'no two-minute stoppage is modelled. The sampled runoff is used as recorded, and it is not '
                                    'checked for a warning stoppage: the warning is not identifiable in the play-by-play, so '
                                    'whether observed runoffs carry it is unverified',
                           'enforced_by': 'unsupported_rules; valid_full_game is false'},
    'penalties': {'guard': 'no penalty is drawn: E1 excludes penalty plays from its pool (classify: penalty, not modelled)',
                  'enforced_by': 'E1 pool exclusion, counted in the pool exclusions'},
    'onside_kicks': {'guard': 'every kickoff is drawn from the observed kickoff pool; no onside kick is drawn',
                     'enforced_by': 'kickoff pool; unsupported_rules'},
    'overtime': {'guard': 'a tie after regulation blocks the game as overtime_not_modelled',
                 'enforced_by': 'record status; the game is not complete'},
    'exception_coin_toss': {'guard': 'explicit_exception_scenario raises NotImplementedError in CoinTossLedger',
                            'enforced_by': 'CoinTossLedger'},
    'lineups': {'guard': 'participants are labelled sampled_observed_play; no lineup or substitution is modelled',
                'enforced_by': 'participants attribution label'},
}
SCORING_TERMINALS = ('touchdown', 'safety', 'field_goal_attempt')
PRACTICE_RULE = 'provisional_practice_rule'
AUTHORED_RULE = 'authored_modelling_choice'
PENDING_2026 = 'pending_2026_rulebook'
PRACTICE_SOURCE = ('NFL practice, not written in docs/rules/NFL-2026-GAME-STATE-RULES.md. Confirm against the 2026 '
                   'rulebook before it is read as a rules-file fact.')
PROVISIONAL_RULES = (
    {'id': 'post_score_kick_after_quarter_expiry', 'label': PRACTICE_RULE, 'status': PENDING_2026,
     'applies_to': 'a touchdown, made field goal or safety whose clock expires in Q1 or Q3',
     'effect': 'the scoring side (or the conceding side, after a safety) kicks off at the start of the next quarter',
     'source': PRACTICE_SOURCE},
    {'id': 'no_post_score_kick_at_halftime', 'label': PRACTICE_RULE, 'status': PENDING_2026,
     'applies_to': 'a score whose clock expires in Q2',
     'effect': 'no post-score kickoff; the second-half kickoff from the ledger follows',
     'source': PRACTICE_SOURCE},
    {'id': 'quarter_ends_during_kick_return', 'label': AUTHORED_RULE, 'status': PENDING_2026,
     'applies_to': 'a kickoff whose runoff exhausts the clock',
     'effect': 'the quarter ends on the return; the receiver starts the next quarter at the kick spot',
     'source': 'authored modelling choice, matching E1 clamping a play runoff at 0:00; not in the rules file'},
)
GAPS = ['field-goal and try outcomes are drawn from the published nfl_pbp rates (2022-2025, weeks 1-18): each draw '
        'is a '
        'labelled sample, not the result of a real game',
        'blocked kicks and returned misses are not modelled: a missed kick gives the other team the spot of the kick',
        'timeouts, the two-minute warning, penalties, onside kicks, overtime and the exception coin-toss paths are not '
        'modelled, and each is listed in unsupported_rules',
        'participants are the players on the observed plays each simulated play was sampled from: they are labelled as '
        'sampled, and they are not this game\'s roster, lineup or substitutions']


def other(team, teams):
    return teams[1] if team == teams[0] else teams[0]


def fg_bucket(yardline_100):
    """The yardline_100 bucket of a field goal, with the same labels as measure_kick_outcomes.BUCKET."""
    for limit, label in ((10, '1-9'), (20, '10-19'), (30, '20-29'), (40, '30-39'), (50, '40-49')):
        if yardline_100 < limit:
            return label
    return '50+'


def drive_index_mismatches(record):
    """Every play state whose drive_index is not its drive's game-level index: (drive numbers, state count, examples).

    Counted in full, not stopped at the first. The archived 5fcaa6bc record has 280 such states in 23 drives (2 to 24), which
    is the known finding of 23 drive-index mismatches.
    """
    bad_drives, states, examples = set(), 0, []
    for d in record['drives']:
        for play in d['plays']:
            for side in ('state_before', 'state_after'):
                got = play[side].get('drive_index')
                if got != d['index']:
                    bad_drives.add(d['index'])
                    states += 1
                    if len(examples) < 3:
                        examples.append(f'drive {d["index"]}: play {play["sequence"]} {side} carries drive_index {got}')
    return sorted(bad_drives), states, examples


def kick_spot_yardline_100(snap_yardline_100):
    """Yardline_100 of the kick, from the snap position: the holder stands HOLDER_OFFSET yards further from the goal.

    Capped at 99, the kicking team's own goal line. A field goal snapped from further back than that is not in the data.
    """
    return min(99, snap_yardline_100 + HOLDER_OFFSET)


def missed_field_goal_spot(kick_spot_yardline_100):
    """Yardline_100 of the receiving team after a missed field goal, from the spot of the kick (the holder's spot).

    Review note, Rule 11-4-2: the receiving team takes possession at the spot of the kick, or at its own 20 when the kick
    spot is inside its 20. The rulebook text is not in the repository, so this rule is cited from the review and is marked
    as such in the rules matrix. The receiving team's yardline_100 is 100 - kick spot; when that is inside its own 20 (above
    80), the spot is 80. The argument is the kick spot, not the snap position. Blocked kicks are not missed kicks and are
    never passed here (they are scoped out of the table).
    """
    spot = 100 - kick_spot_yardline_100
    return 80 if spot > 80 else spot


def quarter_end_kind(quarter):
    """What an expired clock means at the end of `quarter` when no play is left (rules file, sections 2-3)."""
    if quarter in (1, 3):
        return 'quarter_change'
    if quarter == 2:
        return 'halftime'
    return 'regulation_end'


class Reference:
    """The observed data a game is drawn from. Built once by e2_reference.load().

    `participants` maps (game_id, play_id) of an observed play to (passer, rusher, receiver) ids.
    """

    def __init__(self, pool, kickoff_pool, kicks, participants):
        self.pool = pool
        self.kickoff_pool = kickoff_pool
        self.kicks = kicks
        self.participants = participants

    def participants_for(self, play):
        src = play['outcome']['sampled_from']
        facts = self.participants.get((src['game_id'], src['play_id']), {})
        keys = ('passer_id', 'rusher_id', 'receiver_id', 'posteam', 'air_yards', 'yards_after_catch', 'timeout',
                'timeout_team', 'out_of_bounds')
        out = {k: facts.get(k) for k in keys}
        out.update(attribution='sampled_observed_play', sampled_from=src)
        return out


class CoinTossLedger:
    """Normal-game coin-toss ledger for two teams, `winner` and `loser`.

    `winner_choice` is `receive` or `defer`. Normal mode refuses kick and goal-to-defend choices, which the rules
    file says must not be sampled. The first-choice captain receives. In the defer path the loser has the first-half
    choice, and the winner has the second-half choice.
    """

    def __init__(self, winner, loser, winner_choice, mode=NORMAL_MODE):
        if winner == loser:
            raise ValueError('winner and loser must differ')
        if mode == EXCEPTION_MODE:
            raise NotImplementedError('explicit_exception_scenario is not implemented in this E2 piece')
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

        Q1 goal-first-half team defends x=0; ends change after Q1, so Q2 flips. Halftime does not flip ends. Q3
        uses the second-half goal choice (authored); ends change after Q3, so Q4 flips.
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
    """Fail closed on the normal-game invariant: exactly two half-start kickoffs, one per team, Q3 receiver kicks Q1.
    """
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


class _Game:
    """One game in progress. Each drive is an E1 drive; this class decides what follows it."""

    def __init__(self, seed, ref, ledger, rng):
        self.seed = seed
        self.simulation_id = f'e2-{e1.MODEL_VERSION}-seed{seed}'
        self.next_play_sequence = 1
        self.ref = ref
        self.ledger = ledger
        self.rng = rng
        self.kickoffs = ledger.half_start_kickoffs()
        self.quarter, self.clock = 1, QUARTER_LENGTH
        self.offense = self.defense = None
        self.yl = self.down = self.togo = None
        self.events, self.drives, self.boundaries = [], [], []
        self.timeouts = {'A': 3, 'B': 3}  # per half; A is the home side, B the away side (authored labels)
        self.points = Counter()
        self.status = None
        self.blocker = None

    def block(self, reason):
        self.blocker, self.status = reason, 'blocked'

    def _take_possession(self, offense, yl):
        self.offense, self.defense = offense, other(offense, self.ledger.teams)
        self.yl, self.down, self.togo = yl, 1, min(10, yl)

    def _new_quarter(self, kind):
        self.boundaries.append({'from_quarter': self.quarter, 'to_quarter': self.quarter + 1, 'kind': kind,
                                'clock_before': 0, 'drive_index': len(self.drives)})
        self.quarter += 1
        self.clock = QUARTER_LENGTH

    def _half_start(self):
        """Halftime: the first half is over, and the second-half kickoff follows (rules file, section 3)."""
        self.boundaries.append({'from_quarter': 2, 'to_quarter': 3, 'kind': 'halftime', 'clock_before': 0,
                                'drive_index': len(self.drives)})
        self.quarter, self.clock = 3, QUARTER_LENGTH
        self.timeouts = {'A': 3, 'B': 3}  # a new half: three per team
        k = self.kickoffs[1]
        self._kick('half_start', k['kicking_team'], k['receiving_team'])

    def _kick(self, kind, kicker, receiver, clock_rule=None):
        """A kickoff, sampled from the observed kickoff pool. A kick that runs the clock out ends the quarter on
        the return.
        """
        sample = self.rng.choice(self.ref.kickoff_pool)
        clock_before = self.clock
        self.clock = max(0, self.clock - sample['runoff'])
        self.events.append({'kind': kind, 'kicking_team': kicker, 'receiving_team': receiver, 'quarter': self.quarter,
                            'clock_before': clock_before, 'runoff_seconds': sample['runoff'],
                            'clock_clamped_to_zero': clock_before - sample['runoff'] < 0,
                            'spot_yardline_100': sample['spot'], 'after_drive': len(self.drives),
                            'clock_rule': clock_rule,
                            'source': {'game_id': sample['game_id'], 'play_id': sample['play_id'],
                                       'game_date': sample['game_date']}})
        if self.clock > 0:
            self._take_possession(receiver, sample['spot'])
            return
        self.events[-1]['clock_rule'] = AUTHORED_RULE
        boundary = quarter_end_kind(self.quarter)
        if boundary == 'quarter_change':
            self._new_quarter('change_of_ends_during_return')
            self._take_possession(receiver, sample['spot'])
        elif boundary == 'halftime':
            self._half_start()
        else:
            self.status = 'complete_regulation'

    def _apply(self, then, clock_rule=None):
        if then[0] == 'possession':
            self._take_possession(then[1], then[2])
        else:
            _, kind, kicker, receiver = then
            self._kick(kind, kicker, receiver, clock_rule)

    def _continue(self, then):
        """The event that follows a play. An expired clock resolves the quarter first (rules file, sections 2-3).
        """
        if self.clock > 0:
            self._apply(then)
            return
        boundary = quarter_end_kind(self.quarter)
        if boundary == 'quarter_change':
            self._new_quarter('change_of_ends')
            self._apply(then, PRACTICE_RULE if then[0] == 'kick' else None)
        elif boundary == 'halftime':
            if then[0] == 'kick':  # a score that expires Q2: no post-score kickoff (provisional practice rule)
                self.boundaries.append({'from_quarter': 2, 'to_quarter': 3, 'kind': 'skipped_post_score_kick',
                                        'skipped_kind': then[1], 'clock_rule': PRACTICE_RULE,
                                        'drive_index': len(self.drives)})
            self._half_start()
        else:
            self.status = 'complete_regulation'

    def _drive(self):
        """One drive. The plays are stamped with the score before and after it, so every state carries the running score."""
        before = (self.points['A'], self.points['B'])
        self._last_plays = None
        self._drive_body()
        if self._last_plays:
            after = (self.points['A'], self.points['B'])
            _stamp_scores(self._last_plays, before, after)

    def _charge_made_kick(self, play, drive):
        """A made field goal's clock charge is the kick itself, at most KICK_DURATION_SECONDS.

        The sampled runoff runs on to the kickoff, and the kickoff subsystem starts from its own runoff. The charge replaces the
        sampled runoff on the kick play, and the drive's end clock and the game clock follow it. If the observed runoff already
        expires the clock, the kick is not separated: the quarter-end rules apply to that play as they did before.
        """
        before = play['state_before']['clock_seconds']
        observed = play['outcome']['clock_runoff_seconds']
        if observed >= before:
            play['outcome']['kick_duration_seconds'] = None
            return
        charge = min(observed, KICK_DURATION_SECONDS)
        play['outcome']['clock_runoff_seconds'] = charge
        play['outcome']['kick_duration_seconds'] = charge
        play['outcome']['ordinary_runoff_not_charged'] = observed - charge
        play['state_after']['clock_seconds'] = before - charge
        drive['end_clock'] = before - charge
        self.clock = before - charge

    def _apply_timeouts(self, plays):
        """A timeout is a transition, not a value written into both sides of a play.

        state_before carries the counts the previous play left. A flagged sampled play has a timeout called by the team the
        observed play names; it is charged to that side when that side still has one, and the charge appears only in
        state_after. The timeout is a clock stop: it does not move the clock. The stoppage time is already inside the sampled
        runoff, and the next play starts from the clock this play leaves.
        """
        for play in plays:
            part = play['participants']
            part['timeout_applied'] = False
            play['state_before']['home_timeouts'] = self.timeouts['A']
            play['state_before']['away_timeouts'] = self.timeouts['B']
            if part['timeout']:
                mapped = self.offense if part['timeout_team'] == part['posteam'] else self.defense
                if self.timeouts[mapped] > 0:
                    self.timeouts[mapped] -= 1
                    part['timeout_applied'] = True
                part['timeout_charged_to'] = mapped
            play['state_after']['home_timeouts'] = self.timeouts['A']
            play['state_after']['away_timeouts'] = self.timeouts['B']

    def _drive_body(self):
        start = {'quarter': self.quarter, 'clock': self.clock, 'offense': self.offense, 'defense': self.defense,
                 'yl': self.yl, 'down': self.down, 'togo': self.togo,
                 'dir': self.ledger.attacks_x100(self.offense, self.quarter)}
        plays, terminal = e1.simulate(start, self.seed * 1000 + len(self.drives), self.ref.pool, self.simulation_id)
        if plays is None:
            self.block(terminal)
            return
        e1.check_drive(plays, terminal)
        self._last_plays = plays
        drive_index = len(self.drives) + 1
        for play in plays:
            play['sequence'] = self.next_play_sequence
            play['id'] = f'{self.simulation_id}:{self.next_play_sequence}'
            self.next_play_sequence += 1
            play['participants'] = self.ref.participants_for(play)
            play['state_before']['drive_index'] = drive_index  # E1 writes 1 on every play; the game index is written here
            play['state_after']['drive_index'] = drive_index
        self._apply_timeouts(plays)
        last = plays[-1]['state_after']
        drive = {'index': len(self.drives) + 1, 'offense_team': self.offense, 'quarter_start': self.quarter,
                 'clock_start': self.clock, 'plays': plays, 'terminal': terminal,
                 'end_quarter': last['quarter'], 'end_clock': last['clock_seconds'],
                 'points_scored_on_drive': None, 'field_goal_made': None}
        self.drives.append(drive)
        for play in plays:  # a quarter change inside a drive: the drive goes on (rules file, section 2)
            if play['outcome']['quarter_change']:
                self.boundaries.append({'from_quarter': play['state_before']['quarter'],
                                        'to_quarter': play['state_after']['quarter'],
                                        'kind': 'change_of_ends_mid_drive', 'drive_index': drive['index']})
        self.quarter, self.clock = last['quarter'], last['clock_seconds']
        if terminal == 'halftime':
            self._half_start()
        elif terminal == 'end_of_regulation':
            self.status = 'complete_regulation'
        elif terminal == 'field_goal_attempt':
            snap_yl = plays[-1]['state_before']['yardline_100']  # the published yardline_100 is the snap position
            kick_spot = kick_spot_yardline_100(snap_yl)  # the holder's spot: where the ball is actually kicked from
            bucket = fg_bucket(snap_yl)  # the published make-rate cells are keyed on the snap position, so the bucket is too
            made, why = _draw(self.rng, self.ref.kicks['field_goal'].get(bucket, (0, 0)), f'field_goal:{bucket}')
            if why:
                self.block(why)
                return
            drive['field_goal_made'] = made
            drive['snap_yardline_100'] = snap_yl
            drive['kick_spot_yardline_100'] = kick_spot
            if made:
                self._charge_made_kick(plays[-1], drive)
                self.points[self.offense] += FG_POINTS
                drive['points_scored_on_drive'] = {'team': self.offense, 'points': FG_POINTS, 'try': None}
                self._continue(('kick', 'post_field_goal', self.offense, other(self.offense, self.ledger.teams)))
            else:  # the other team takes over at the spot of the kick, the same dead-ball spot (rules file, section 4)
                self._continue(('possession', self.defense, missed_field_goal_spot(kick_spot)))
        elif terminal in ('punt', 'turnover', 'turnover_on_downs'):
            self._continue(('possession', last['offense_team'], last['yardline_100']))
        elif terminal == 'touchdown':
            scorer = self.offense
            try_points, try_record, why = _try_after_touchdown(self.rng, self.ref.kicks)
            if why:
                self.block(why)
                return
            self.points[scorer] += TD_POINTS + try_points
            drive['points_scored_on_drive'] = {'team': scorer, 'points': TD_POINTS + try_points, 'try': try_record}
            self._continue(('kick', 'post_score', scorer, other(scorer, self.ledger.teams)))
        elif terminal == 'safety':
            scorer = self.defense
            self.points[scorer] += SAFETY_POINTS
            drive['points_scored_on_drive'] = {'team': scorer, 'points': SAFETY_POINTS, 'try': None}
            self._continue(('kick', 'safety_free_kick', self.offense, scorer))
        else:
            self.block(f'unhandled_terminal:{terminal}')

    def run(self, max_drives):
        k = self.kickoffs[0]
        self._kick('half_start', k['kicking_team'], k['receiving_team'])
        while self.status is None:
            if len(self.drives) >= max_drives:
                self.block('drive_limit')
                break
            self._drive()
        return self

    def record(self):
        tied = self.points['A'] == self.points['B']
        status, blocker = self.status or 'blocked', self.blocker
        if status == 'complete_regulation' and tied:
            status, blocker = 'blocked', 'overtime_not_modelled'
        complete = status == 'complete_regulation'
        points = {'A': self.points['A'], 'B': self.points['B']}
        scope_out = scope_out_reasons(blocker, complete, tied)
        return {
            'mode': 'legal_game_state_first_piece', 'seed': self.seed, 'simulation_id': self.simulation_id,
            'ledger': self.ledger.ledger(), 'kickoffs': self.events, 'boundaries': self.boundaries,
            'drives': self.drives, 'points': points, 'stats': game_stats.compute(self.drives, points),
            'status': status, 'blocker': blocker, 'tied': tied, 'complete_regulation': complete,
            'final_quarter': self.quarter, 'final_clock_seconds': self.clock,
            'complete_game': bool(complete and blocker is None and not tied),
            'scope_out': scope_out,
            'valid_full_game': bool(complete and blocker is None and not UNSUPPORTED_RULES),
            'unsupported_rules': list(UNSUPPORTED_RULES), 'guards': {r: dict(GUARDS[r]) for r in UNSUPPORTED_RULES},
            'gaps': GAPS,
            'provisional_rules': [dict(r) for r in PROVISIONAL_RULES],
            'provisional_counts': {
                'post_score_kickoffs_after_quarter_expiry': sum(1 for k in self.events
                                                                if k['clock_rule'] == PRACTICE_RULE),
                'skipped_post_score_kicks_at_halftime': sum(1 for b in self.boundaries
                                                            if b.get('clock_rule') == PRACTICE_RULE),
                'quarter_ends_during_kick_return': sum(1 for k in self.events if k['clock_rule'] == AUTHORED_RULE),
            },
        }


def _stamp_scores(plays, before, after):
    """Every state of the drive carries the score before it. Only the last play's state_after takes the score after it."""
    for i, play in enumerate(plays):
        last = i == len(plays) - 1
        for side, score in (('state_before', before), ('state_after', after if last else before)):
            play[side]['home_score'] = score[0]
            play[side]['away_score'] = score[1]


def scope_out_reasons(blocker, complete, tied):
    """Why a seed is not a complete game. Scoped out, not guessed: each reason is named and carried in the record."""
    reasons = []
    if blocker == 'overtime_not_modelled':
        reasons.append({'reason': 'overtime', 'detail': 'tied after regulation; overtime is rule-version-sensitive and '
                                                        'not modelled, so the tied game is not complete'})
    elif blocker and blocker.startswith('thin_kick_cell'):
        reasons.append({'reason': 'rare kick outcome', 'detail': f'{blocker}: fewer published attempts than '
                                                                  f'MIN_KICK_N in that cell'})
    elif blocker and blocker.startswith('thin pool cell'):
        reasons.append({'reason': 'thin E1 pool cell', 'detail': blocker})
    elif blocker == 'drive_limit':
        reasons.append({'reason': 'drive limit', 'detail': 'the game ran past max_drives'})
    elif blocker:
        reasons.append({'reason': 'other', 'detail': blocker})
    return reasons


def play_game(seed, ref, winner_choice=None, max_drives=80, winner=None):
    """Play one game under the normal-game policy. Returns a record; it never raises for a branch.

    `ref` is the observed Reference (e2_reference.load). It is required, so a game is never played with a silent
    default. The toss winner (team 'A' or 'B') and the winner's choice (receive or defer) are both sampled from the seed,
    unless a caller fixes them for a test.
    """
    rng = random.Random(seed)
    toss_winner = winner or rng.choice(['A', 'B'])
    toss_loser = other(toss_winner, ('A', 'B'))
    choice = winner_choice or rng.choice(['receive', 'defer'])
    ledger = CoinTossLedger(toss_winner, toss_loser, choice)
    validate_half_start(ledger.half_start_kickoffs())
    return _Game(seed, ref, ledger, rng).run(max_drives).record()


def validate_game(record):
    """Fail closed on the ledger, clock and points invariants of one record. Returns the list of checks that passed.
    """
    checks = []
    simulation_id = record.get('simulation_id')
    if not isinstance(simulation_id, str) or not simulation_id:
        raise AssertionError('game record requires one non-empty simulation_id')
    expected_sequence = 1
    for drive in record['drives']:
        for play in drive['plays']:
            if play.get('sequence') != expected_sequence or play.get('id') != f'{simulation_id}:{expected_sequence}':
                raise AssertionError(
                    f'play {expected_sequence} must use game-wide id {simulation_id}:{expected_sequence}')
            expected_sequence += 1
    checks.append('game-wide play IDs use one simulation_id and contiguous sequence')
    ledger = record['ledger']
    expected = CoinTossLedger(ledger['winner'], ledger['loser'], ledger['winner_choice'], ledger['policy_mode'])
    expected_half = expected.half_start_kickoffs()
    recorded_half = [k for k in record['kickoffs'] if k['kind'] == 'half_start']
    if len(recorded_half) > 2:
        raise AssertionError(f'more than two half-start kickoffs recorded: {recorded_half}')
    for got in recorded_half:
        want = next((k for k in expected_half if k['quarter'] == got['quarter']), None)
        if want is None or ((got['kicking_team'], got['receiving_team'])
                            != (want['kicking_team'], want['receiving_team'])):
            raise AssertionError(f'recorded half-start kickoff disagrees with the ledger: {got}')
    checks.append('recorded half-start kickoffs equal the ledger')
    if len(recorded_half) == 2:
        validate_half_start([{'quarter': k['quarter'], 'kicking_team': k['kicking_team'],
                              'receiving_team': k['receiving_team'], 'reason': 'half_start'} for k in recorded_half])
        checks.append('two half-start kickoffs, one per team, Q3 reverses Q1')
    elif record['final_quarter'] >= 3 and record['complete_regulation']:
        raise AssertionError('a complete game must have two half-start kickoffs')
    bad_drives, bad_states, examples = drive_index_mismatches(record)
    if bad_drives:
        raise AssertionError(f'{len(bad_drives)} drive-index mismatches: {bad_states} play states carry the wrong drive_index '
                             f'in drives {bad_drives}; first: {examples[0]}')
    checks.append('every play state carries its drive index, in state_before and state_after')
    missing = [r for r in UNSUPPORTED_RULES if r not in record.get('guards', {})]
    if missing:
        raise AssertionError(f'unsupported rules without a guard: {missing}')
    checks.append('every unsupported rule carries a guard')
    by_team = Counter()
    for d in record['drives']:
        p = d['points_scored_on_drive']
        if d['terminal'] == 'touchdown':
            if p is None:  # only a try that could not be drawn (a thin cell) leaves a touchdown unscored, and it blocks
                if record['blocker'] is None or d is not record['drives'][-1]:
                    raise AssertionError(f'touchdown drive without a recorded try: {d["index"]}')
            else:
                t = p['try']
                if t is None or t['kind'] not in TRY_POINTS:
                    raise AssertionError(f'touchdown drive without a recorded try: {d["index"]}')
                if p['points'] != TD_POINTS + (TRY_POINTS[t['kind']] if t['made'] else 0):
                    raise AssertionError(f'touchdown points disagree with the try: {d["index"]}')
        if d['terminal'] == 'field_goal_attempt' and d['field_goal_made'] is not None:
            if d['field_goal_made'] != bool(p):
                raise AssertionError(f'field goal result disagrees with its points: {d["index"]}')
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
        if (not record['complete_regulation'] or record['blocker'] is not None or record['tied']
                or record['unsupported_rules']):
            raise AssertionError(
                'valid_full_game requires complete regulation, no blocker, no tie and no unsupported rule')
    checks.append('valid_full_game only when complete, unblocked, untied and with no unsupported rule')
    return checks
