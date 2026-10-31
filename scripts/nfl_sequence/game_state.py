"""E2 game: coin-toss ledger, kickoffs, scoring, clock management, and linkage of E1 drives into one regulation game.

Scope:
- the coin-toss ledger for the normal-game policy (docs/rules/NFL-2026-GAME-STATE-RULES.md, sections 1-3 and 7): the
  first-choice captain receives, and each team kicks off once per half;
- the two half-start kickoffs, derived from the ledger and validated;
- scoring: touchdowns (6, then a try: an extra point for 1, or a two-point try for 2), field goals (3, made or missed),
  and safeties (2);
- post-touchdown and made-field-goal restarts, after halftime (the second-half kickoff), and after punts and turnovers (the
  receiving team starts at its published spot); safety scoring is recorded, but a safety free kick blocks pending a separate,
  observed safety-kick outcome table;
- clock management: quarters are 15 minutes, a quarter change keeps possession and the spot (no kickoff, rules section
  2), halftime ends the first half and starts the second with a kickoff (section 3), and the fourth-quarter expiry ends
  regulation. A clock that runs out on a score, a possession change or a kickoff is resolved by the quarter it expires
  in;
- participants: a pregame game fixes QB1 and assigns eligible backs and receivers from the frozen depth chart using
  historical role shares and depth ranks; other research modes retain their observed-play participants. These are
  statistical player-line allocations, not player-specific performance projections or complete on-field lineups.

Kick outcomes are drawn from the published nfl_pbp rates (measure_kick_outcomes.py, 2022-2025, weeks 1-18): a field
goal's make rate in its yardline_100 bucket, the extra-point rate, the two-point rate, and the share of post-touchdown
attempts that were two-point tries. Each draw is a labelled sample from a published rate, not the outcome of a real
game. A cell with fewer than MIN_KICK_N attempts blocks the game, and nothing is filled from a neighbouring cell.

Clock intervals carry observed snap-to-snap runoff, stoppage reasons and restart triggers; first-down and out-of-bounds
restart rules are approximated and remain a capability limitation. Timeouts are charged to the named team, limited to
three per half and represented as clock stops; an unresolved or exhausted call blocks the record. The record's
`unsupported_rules` names only exceptional paths it actually takes. Other capability limitations remain in
`rule_capability_limitations`: penalties are excluded from E1 and block if encountered; onside kicks and exception coin
toss paths are not generated; ties block because overtime is not modelled; safety free kicks lack a separate outcome
table; and a missed field goal is awarded at the rule-defined spot without modeling a return after a beyond-line touch.
The pregame offense participants come from the frozen roster, but the engine does not build a complete 22-player lineup,
defensive personnel or substitutions.

Kickoff convention in the published nfl_pbp (measured 2026-10-24): on a kickoff row `posteam` is the RECEIVING team and
`defteam` is the KICKING team. The receiving team's next run or pass in the same quarter gives the starting spot.
"""
import copy
import random
import hashlib
from collections import Counter, defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
import game_stats  # noqa: E402
import pre_event as pe  # noqa: E402
import reducer  # noqa: E402
import football_assertions  # noqa: E402
import field_goal_feasibility as fg_feasibility  # noqa: E402
from paired_random_streams import PairedRandomStreams  # noqa: E402

NORMAL_MODE = 'normal_nfl_game'
EXCEPTION_MODE = 'explicit_exception_scenario'
PREGAME_USAGE_VERSION = 'pregame-role-usage-v1'
QUARTER_LENGTH = 900
TD_POINTS = 6
FG_POINTS = 3
SAFETY_POINTS = 2
SAFETY_KICK_POOL = 'safety_kick_outcomes_2022_2025'  # the source label a sampled safety free kick must carry
OVERTIME_LENGTH = 600  # Rule 16, Article 3: one 10-minute period in the regular season
OVERTIME_TIMEOUTS = 2  # Rule 16, Article 3(e): two timeouts per team
OVERTIME_TERMINAL = {'touchdown': 'touchdown', 'defense_touchdown': 'touchdown', 'field_goal_made': 'field_goal_attempt',
                     'field_goal_missed': 'field_goal_attempt', 'punt': 'punt', 'turnover': 'turnover',
                     'turnover_on_downs': 'turnover_on_downs', 'period_end': 'end_of_overtime'}  # observed ending -> terminal
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
UNSUPPORTED_RULES = ('clock_start_stop', 'timeouts', 'penalties', 'onside_kicks', 'overtime',
                     'exception_coin_toss', 'lineups', 'missed_field_goal_return', 'safety_free_kick', 'blocked_kicks')
# Each unmodelled rule has a named guard. A record must carry every guard; the matrix checks it, and no guard lets a
# record claim the rule is modelled.
GUARDS = {
    'clock_start_stop': {'guard': 'the record carries observed snap-to-snap runoff, clock state, stoppage reasons and restart triggers; '
                                  'restart-trigger semantics are a modeled approximation',
                         'enforced_by': 'clock_transition; rule_capability_limitations'},
    'timeouts': {'guard': 'observed timeouts decrement the named team within its three-per-half allowance and are recorded as clock stops; '
                          'an unavailable caller or exhausted allowance blocks the game',
                 'enforced_by': 'timeout state; clock_transition'},
    'penalties': {'guard': 'no penalty is drawn: E1 excludes penalty plays from its pool (classify: penalty, not modelled)',
                  'enforced_by': 'E1 pool exclusion, counted in the pool exclusions'},
    'onside_kicks': {'guard': 'every kickoff is drawn from the observed kickoff pool; no onside kick is drawn',
                     'enforced_by': 'kickoff pool; unsupported_rules'},
    'overtime': {'guard': 'a regulation tie with no observed overtime table is blocked as overtime_not_modelled; with the table, '
                          'overtime drives are observed and Rule 16 decides the winner',
                 'enforced_by': 'record status and the scope reason'},
    'exception_coin_toss': {'guard': 'explicit_exception_scenario raises NotImplementedError in CoinTossLedger',
                            'enforced_by': 'CoinTossLedger'},
    'lineups': {'guard': 'participants are labelled sampled_observed_play; no lineup or substitution is modelled',
                'enforced_by': 'participants attribution label'},
    'missed_field_goal_return': {'guard': 'Rule 11-4-2 exceptions (1) and (2): the receiving start spot is sampled from observed '
                                          'next-drive transitions after missed field goals; a returner, return touchdown and '
                                          'physical return are not reconstructed',
                                 'enforced_by': 'field_goal_return transition; rule_capability_limitations'},
    'safety_free_kick': {'guard': 'a safety free kick is drawn only from the observed 2022-2025 safety-kick table (receiving '
                                  'spot and clock; a kick with no receiving snap before the quarter ends is excluded). Without '
                                  'that table, or at a Q1/Q3 end with no clock left, the game blocks; the ordinary kickoff pool '
                                  'is never used',
                         'enforced_by': 'safety-kick source label in validate_game; record blocker when the table is absent'},
    'blocked_kicks': {'guard': 'blocked-kick rates and transitions are sampled from the pinned 2022-2025 nflverse fixture; '
                               'a sampled penalty, fumble, review, missing recovery, or unresolved endpoint blocks the game',
                      'enforced_by': 'blocked_kick_outcomes fixture classification_status; blocked-kick reducer'},
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
GAPS = ['field-goal, blocked field-goal and blocked punt outcomes are sampled from published 2022-2025 nflverse rates; '
        'the block rates are rare and carry wide confidence intervals, and unresolved sampled transitions block the game',
        'blocked-kick returns are recorded in team totals; individual returner statistics are not assigned to the frozen roster',
        'field-goal and try outcomes are drawn from the published nfl_pbp rates (2022-2025, weeks 1-18): each draw '
        'is a '
        'labelled sample, not the result of a real game',
        'missed-field-goal next-drive spots are sampled from observed transitions; returners and return touchdowns are not reconstructed',
        'safety free kicks are sampled from the observed 2022-2025 safety-kick table (spot and clock only); a safety at a Q1/Q3 '
        'end with no clock left still blocks',
        'penalties, onside kicks and exception coin-toss paths remain capability limitations; overtime is modelled for the regular-season '
        'period only (Rule 16: 10 minutes, the toss winner receives, the two-minute warning and Article 5(a) are not modelled); '
        'a game that takes an '
        'unsupported path is blocked or marked incomplete',
        'clock transitions use observed snap-to-snap runoff and explicit stoppages/restart triggers; restart-trigger semantics '
        'are an approximation and should be checked against the applicable season rulebook',
        'offense participants are sampled by role and depth rank from each team\'s frozen pregame depth chart; this is a '
        'statistical assignment and does not construct all 22 players, defensive personnel or substitutions']


def two_minute_stop(quarter, before, after, warned_quarters):
    """Apply the two-minute warning at the end of a down that crosses 2:00 (Rule 3 Section 41; Rule 4 Section 4(h)).

    The clock keeps the observed post-down value; the timeout does not rewind it to 2:00. The warning is once per half, so a
    quarter already in `warned_quarters` never stops again. Returns (clock after the down, warning occurred).
    """
    if quarter in LATE_QUARTERS and quarter not in warned_quarters and before > TWO_MINUTE_MARK >= after > 0:
        return after, True
    return after, False


def other(team, teams):
    return teams[1] if team == teams[0] else teams[0]


def fg_bucket(yardline_100):
    """The yardline_100 bucket of a field goal, with the same labels as measure_kick_outcomes.BUCKET."""
    for limit, label in ((10, '1-9'), (20, '10-19'), (30, '20-29'), (40, '30-39'), (50, '40-49')):
        if yardline_100 < limit:
            return label
    return '50+'


def _field_goal_source_is_current(source, feasibility):
    """Validate either the pinned snap-bucket source or the distance-aware model source against this snap."""
    if not isinstance(source, dict):
        return False
    if source.get('yardline_bucket') is not None:
        return (
            source.get('yardline_bucket') == fg_bucket(feasibility.get('snap_yardline_100'))
            and source.get('kick_distance_yards') == feasibility.get('kick_distance_yards')
            and source.get('historical_ceiling_yards') == feasibility.get('historical_ceiling_yards')
            and source.get('feasibility_source_sha256') == feasibility.get('source_sha256')
        )
    probabilities = source.get('probabilities')
    return (
        source.get('distance_yards') == feasibility.get('kick_distance_yards')
        and source.get('field_goal_feasibility') == feasibility
        and isinstance(source.get('table'), str)
        and isinstance(source.get('fallback_level'), str)
        and isinstance(probabilities, dict)
        and all(isinstance(probabilities.get(name), (int, float))
                and 0 <= probabilities[name] <= 1 for name in ('made', 'missed', 'blocked'))
        and abs(sum(probabilities[name] for name in ('made', 'missed', 'blocked')) - 1.0) < 1e-9
    )


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
    if quarter == 5:
        return 'overtime_end'
    return 'regulation_end'


class Reference:
    """The observed data a game is drawn from. Built once by e2_reference.load().

    `participants` maps (game_id, play_id) of an observed play to (passer, rusher, receiver) ids.
    """

    def __init__(self, pool, kickoff_pool, kicks, participants, missed_field_goal_pool=None, blocked_kicks=None,
                 try_policy=None, clock_model=None, safety_kick_pool=None, overtime_pool=None, overtime_toss=None,
                 overtime_try_p_two=None, overtime_p_kick=None, overtime_choice=None, contextual_sampler=None):
        self.pool = pool
        self.kickoff_pool = kickoff_pool
        # None keeps a safety free kick blocked. A list is the observed safety-kick table, sampled only for a safety kick.
        self.safety_kick_pool = safety_kick_pool
        # None keeps a regulation tie as overtime_not_modelled. A list is the observed regular-season overtime drive table.
        self.overtime_pool = overtime_pool
        # None is the seeded uniform first possession; 'A' or 'B' forces it, for the sensitivity runs.
        self.overtime_toss = overtime_toss
        # Overtime try fallback: a two-point probability for each margin bucket, from the try-decision table (2022-2025).
        self.overtime_try_p_two = overtime_try_p_two
        # The winning coach's kick-or-receive decision. overtime_p_kick is the observed rate (a seeded draw each game);
        # overtime_choice forces 'kick' or 'receive' for the labelled controls. Both None: always receive, the control.
        self.overtime_p_kick = overtime_p_kick
        self.overtime_choice = overtime_choice
        self.kicks = kicks
        self.blocker_fixes = frozenset()
        self.fg_ordinary_cutoff = 60.0
        self.participants = participants
        self.missed_field_goal_pool = missed_field_goal_pool or {}
        self.blocked_kicks = blocked_kicks or {'records': {'field_goal': [], 'punt': []}, 'rates': {}, 'sha256': None}
        # None keeps the published unconditional share. A try_policy.TryPolicy conditions the two-point decision on the
        # situation.
        self.try_policy = try_policy
        self.clock_model = clock_model  # None is the E2 default; a fitted clock_d.Model selects the research clock
        self.contextual_sampler = contextual_sampler
        self.contextual_pool_manifest = {}

    def _pre_event_participants(self, play, facts, pre, out, src, offense_team):
        """The players chosen before the outcome was drawn (pre_event.py). The outcome decides what they do, not who they are."""
        event = play['event_type']
        passing = event in pe.PASS_EVENTS or (event == 'fumble_lost' and facts.get('play_type') == 'pass')
        rushing = event == 'run' or (event == 'fumble_lost' and facts.get('play_type') == 'run')
        assigned = {}
        try:
            if passing:
                assigned['passer'] = pre['passer']
                if event != 'sack':  # a sack has no target
                    assigned['receiver'] = pre['receiver']
            if rushing:
                assigned['rusher'] = pre['rusher']
        except KeyError as exc:
            raise ValueError(f"pre-event selection for {event} has no {exc.args[0]}") from exc
        out.update(passer_id=None, rusher_id=None, receiver_id=None)
        out['sampled_play_context'] = {
            'posteam': facts.get('posteam'), 'defteam': facts.get('defteam'), 'play_type': facts.get('play_type'),
            'air_yards': facts.get('air_yards'), 'yards_after_catch': facts.get('yards_after_catch'),
            'timeout_team': facts.get('timeout_team'), 'out_of_bounds': facts.get('out_of_bounds'),
        }
        for field in ('passing_yards', 'receiving_yards', 'rushing_yards'):
            if field in facts:
                out['sampled_play_context'][field] = facts[field]
        for field in ('lateral_receiver_player_id', 'lateral_receiving_yards',
                      'lateral_rusher_player_id', 'lateral_rushing_yards'):
            if field in facts:
                out['sampled_play_context'][field] = facts[field]
        for key in ('posteam', 'defteam', 'air_yards', 'yards_after_catch', 'timeout_team', 'out_of_bounds'):
            out[key] = None
        for role, player in assigned.items():
            out[f'{role}_id'] = player['gsis_id']
            out[f'{role}_name'] = player['player_name']
            out[f'{role}_position'] = player['pos_abb']
            out[f'{role}_team'] = pre['team']
            out[f'{role}_side'] = offense_team
        out['attribution'] = 'pre_event_selection'
        out['sampled_from'] = src
        return out

    def participants_for(self, play, offense_team=None, snapshot=None, seed=None):
        src = play['outcome']['sampled_from']
        facts = self.participants.get((src['game_id'], src['play_id']), {})
        keys = ('passer_id', 'rusher_id', 'receiver_id', 'posteam', 'defteam', 'air_yards', 'yards_after_catch', 'timeout',
                'timeout_team', 'out_of_bounds')
        out = {k: facts.get(k) for k in keys}
        pre = play['outcome'].get('pre_event')
        if pre is not None:
            return self._pre_event_participants(play, facts, pre, out, src, offense_team)
        if getattr(getattr(self, 'contextual_sampler', None), 'participant_chooser', None) is not None:
            if play['event_type'] in pe.PASS_EVENTS or play['event_type'] in ('run', 'fumble_lost'):
                raise ValueError(f"pre-event participants are missing for {play['event_type']} at sequence {play.get('sequence')}")
            out.update(attribution='no_participant_modelled', sampled_from=src)  # kicks: no ball carrier or target is modelled
            return out
        if snapshot is None:
            out.update(attribution='sampled_observed_play', sampled_from=src)
            return out

        side = 'home' if offense_team == 'A' else 'away'
        team_roster = snapshot['rosters'][side]
        players = team_roster['players']
        event = play['event_type']
        source_play_type = facts.get('play_type')
        out.update(passer_id=None, rusher_id=None, receiver_id=None)
        out['sampled_play_context'] = {
            'posteam': facts.get('posteam'),
            'defteam': facts.get('defteam'),
            'play_type': source_play_type,
            'air_yards': facts.get('air_yards'),
            'yards_after_catch': facts.get('yards_after_catch'),
            'timeout_team': facts.get('timeout_team'),
            'out_of_bounds': facts.get('out_of_bounds'),
        }
        for key in ('posteam', 'defteam', 'air_yards', 'yards_after_catch', 'timeout_team', 'out_of_bounds'):
            out[key] = None

        def choose(groups, role):
            eligible = [p for p in players if p['pos_abb'] in groups]
            if not eligible:
                raise ValueError(f"pregame snapshot has no {role} for {team_roster['team']}")
            eligible.sort(key=lambda p: (p['pos_rank'], p['gsis_id']))
            if role == 'passer':
                starters = [p for p in eligible if p['pos_rank'] == 1]
                if len(starters) != 1:
                    raise ValueError(f"pregame snapshot must have exactly one QB1 for {team_roster['team']}")
                return starters[0]
            role_seed = f"{snapshot['snapshot_sha256']}:{seed}:{play['sequence']}:{role}".encode()
            draw = random.Random(int.from_bytes(hashlib.sha256(role_seed).digest()[:8], 'big'))
            return draw.choices(eligible, weights=[1 / p['pos_rank'] for p in eligible], k=1)[0]

        def choose_by_usage(usage_key, role):
            usage = snapshot['model_reference']['observed_reference'][usage_key]
            shares = usage['shares']
            groups = [position for position, share in shares.items()
                      if share > 0 and any(p['pos_abb'] == position for p in players)]
            if not groups:
                raise ValueError(f"pregame snapshot has no eligible {role} positions for {team_roster['team']}")
            weights = [shares[position] for position in groups]
            role_seed = f"{snapshot['snapshot_sha256']}:{seed}:{play['sequence']}:{role}:position".encode()
            draw = random.Random(int.from_bytes(hashlib.sha256(role_seed).digest()[:8], 'big'))
            position = draw.choices(groups, weights=weights, k=1)[0]
            choice_role = 'passer' if position == 'QB' else f'{role}_{position}'
            return choose({position}, choice_role)

        assigned = {}
        if event in ('pass_complete', 'pass_incomplete', 'interception', 'sack') or (
                event == 'fumble_lost' and source_play_type == 'pass'):
            assigned['passer'] = choose({'QB'}, 'passer')
            if event == 'pass_complete' or (event in ('pass_incomplete', 'interception') and facts.get('receiver_id')):
                assigned['receiver'] = choose_by_usage('receiver_position_usage', 'receiver')
        if event == 'run' or (event == 'fumble_lost' and source_play_type == 'run'):
            assigned['rusher'] = choose_by_usage('runner_position_usage', 'rusher')

        for role, player in assigned.items():
            out[f'{role}_id'] = player['gsis_id']
            out[f'{role}_name'] = player['player_name']
            out[f'{role}_position'] = player['pos_abb']
            out[f'{role}_team'] = team_roster['team']
            out[f'{role}_side'] = offense_team
        out['attribution'] = 'pregame_depth_chart_role_sample'
        out['sampled_from'] = src
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


def build_kickoff_pool(rows, include_season=False):
    """Starting spots and time after kickoffs, from published kickoff rows (receiving team = posteam).

    `include_season` adds the season to each sample for the research regime pool. It is off by default because the reference
    fingerprint hashes every sample, so the default pool's fingerprint must not change.
    """
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
            sample = {'spot': spot, 'runoff': runoff, 'game_id': row['game_id'], 'play_id': int(row['play_id']),
                      'game_date': row['game_date']}
            if include_season:
                sample['season'] = int(row['season'])
            pool.append(sample)
    return pool, excluded


def _draw(rng, cell, name):
    """A made or missed draw at the published rate of `cell` = (made, missed).

    Returns (made, None), or (None, reason) when the cell is too thin.
    """
    made, missed = cell
    if made + missed < MIN_KICK_N:
        return None, f'thin_kick_cell:{name}'
    return rng.random() < made / (made + missed), None


# Every try record carries the publisher's own result field for its kind, with the publisher's own values. No EPA-derived
# `success` flag is ever written into a try record: nflverse `success` is EPA-positive and is not a make result.
TRY_PUBLISHER_FIELD = {'extra_point': 'extra_point_result', 'two_point': 'two_point_conv_result'}
TRY_PUBLISHER_VALUE = {'extra_point': {True: 'good', False: 'failed'}, 'two_point': {True: 'success', False: 'failure'}}


def try_record(kind, made):
    """A try record: the kind, the made flag, and the publisher field for the kind (`extra_point_result` or
    `two_point_conv_result`), carrying the publisher value that matches the made flag."""
    return {'kind': kind, 'made': made, TRY_PUBLISHER_FIELD[kind]: TRY_PUBLISHER_VALUE[kind][made]}


TRY_MARGIN_BUCKETS = ((-999, -9, '<=-9'), (-8, -5, '-8..-5'), (-4, -1, '-4..-1'), (0, 0, '0'), (1, 4, '1..4'),
                      (5, 8, '5..8'), (9, 999, '>=9'))  # the same buckets as build_try_fallback.py


def try_margin_bucket(margin):
    for low, high, label in TRY_MARGIN_BUCKETS:
        if low <= margin <= high:
            return label
    raise ValueError(margin)


def _try_after_touchdown(rng, kicks, p_two=None):
    """The try after a touchdown: a two-point try at `p_two` (a try policy's probability for this situation), else at the
    published share of post-touchdown attempts. One draw picks the kind either way, so a seed's stream is the same under both
    policies. Otherwise an extra point.

    Returns (points, record, None), or (None, None, reason) when the cell it needs is too thin.
    """
    if p_two is None:
        two_tries = sum(kicks['two_point'])
        total = two_tries + sum(kicks['extra_point'])
        p_two = two_tries / total if total else 0
    kind = 'two_point' if rng.random() < p_two else 'extra_point'
    made, why = _draw(rng, kicks[kind], kind)
    if why:
        return None, None, why
    return (TRY_POINTS[kind] if made else 0), try_record(kind, made), None


class _TimeoutSamplingGuard:
    """Keep source-play timeout observations within each simulated team's remaining half allotment."""

    def __init__(self, participants, remaining):
        self.participants = participants
        self.initial = dict(remaining)
        self.remaining = dict(remaining)
        self.excluded = Counter()
        self._cell_cache = {}

    def _facts(self, sample):
        row = sample[1]
        try:
            key = (row['game_id'], int(float(row['play_id'])))
        except (KeyError, TypeError, ValueError):
            return {}
        return self.participants.get(key, {})

    def _timeout_side(self, sample, state):
        facts = self._facts(sample)
        if not facts.get('timeout'):
            return None, None
        caller = facts.get('timeout_team')
        posteam, defteam = facts.get('posteam'), facts.get('defteam')
        if caller and caller == posteam:
            side = state.get('offense')
        elif caller and caller == defteam:
            side = state.get('defense')
        else:
            return None, 'timeout_source_team_unresolved'
        if side not in self.remaining:
            return None, 'timeout_simulated_team_unresolved'
        return side, None

    def permits(self, sample, state):
        return self.rejection_reason(sample, state) is None

    def rejection_reason(self, sample, state):
        side, reason = self._timeout_side(sample, state)
        if reason:
            return reason
        if side is not None and self.remaining[side] <= 0:
            return f'timeout_limit_exhausted:{side}'
        return None

    def filter_cell(self, cell, state):
        if not self.requires_source_filter:
            self.last_filter = {'excluded_rows': 0, 'reasons': {}}
            self.last_filter_reused = False
            return cell
        exhausted = tuple(sorted(side for side, count in self.remaining.items() if count == 0))
        cache_key = (id(cell), state.get('offense'), state.get('defense'), exhausted)
        cached = self._cell_cache.get(cache_key)
        if cached is not None and cached[0] is cell:
            self.last_filter = cached[2]
            self.last_filter_reused = True
            return cached[1]
        kept, rejected = [], Counter()
        for sample in cell:
            side, reason = self._timeout_side(sample, state)
            if reason:
                rejected[reason] += 1
            elif side is not None and self.remaining[side] <= 0:
                rejected[f'timeout_limit_exhausted:{side}'] += 1
            else:
                kept.append(sample)
        self.excluded.update(rejected)
        self.last_filter_reused = False
        if not rejected:
            self.last_filter = {'excluded_rows': 0, 'reasons': {}}
            self._cell_cache[cache_key] = (cell, cell, self.last_filter)
            return cell
        self.last_filter = {'excluded_rows': sum(rejected.values()),
                             'reasons': dict(sorted(rejected.items()))}
        self._cell_cache[cache_key] = (cell, kept, self.last_filter)
        return kept

    def observe(self, sample, state):
        reason = self.rejection_reason(sample, state)
        if reason:
            raise ValueError(reason)
        side, _ = self._timeout_side(sample, state)
        if side is not None:
            self.remaining[side] -= 1

    def unavailable_reason(self):
        reasons_for_cell = self.last_filter.get('reasons', {})
        if reasons_for_cell:
            reasons = ','.join(f'{key}={value}' for key, value in sorted(reasons_for_cell.items()))
            return f'timeout_sampling_no_legal_source_rows:{reasons}'
        return 'timeout_sampling_no_source_rows'

    @property
    def requires_source_filter(self):
        return any(value == 0 for value in self.remaining.values())

    def describe(self):
        return {'initial_remaining': dict(self.initial), 'final_remaining': dict(self.remaining),
                'distinct_cell_rows_excluded_by_reason': dict(sorted(self.excluded.items()))}


class _Game:
    """One game in progress. Each drive is an E1 drive; this class decides what follows it."""

    def __init__(self, seed, ref, ledger, rng, pregame_snapshot=None, model_seed=None, paired_random_streams=None):
        self.seed = seed
        self.pregame_snapshot = pregame_snapshot
        snapshot_tag = f"-{pregame_snapshot['schedule']['game_id']}-{pregame_snapshot['snapshot_sha256'][:12]}" if pregame_snapshot else ''
        usage_tag = f'-{PREGAME_USAGE_VERSION}' if pregame_snapshot else ''
        self.simulation_id = f'e2-{e1.MODEL_VERSION}{usage_tag}{snapshot_tag}-seed{seed}'
        self.model_seed = seed if model_seed is None else model_seed
        self.next_play_sequence = 1
        self.ref = ref
        self.ledger = ledger
        self.rng = rng
        self.paired_random_streams = paired_random_streams
        self._paired_rng_indices = Counter()
        self.clock_draws = (ref.clock_model.for_game(seed, paired_random_streams=paired_random_streams)
                            if ref.clock_model is not None and paired_random_streams is not None else
                            ref.clock_model.for_game(seed) if ref.clock_model is not None else None)
        self.kickoffs = ledger.half_start_kickoffs()
        self.quarter, self.clock = 1, QUARTER_LENGTH
        self.offense = self.defense = None
        self.yl = self.down = self.togo = None
        self.events, self.drives, self.boundaries = [], [], []
        self.overtime = None  # set when a regulation tie goes to overtime (Rule 16)
        self.blocked_attempt = None  # the drive a block stopped, with evidence for plays and the unresolved attempt
        self.timeouts = {'A': 3, 'B': 3}  # per half; A is the home side, B the away side (authored labels)
        self.warned_quarters = set()  # the late quarters whose two-minute warning has stopped the clock this half
        self.points = Counter()
        self.status = None
        self.blocker = None

    def block(self, reason):
        self.blocker, self.status = reason, 'blocked'

    def _rng(self, stream, *coordinates):
        paired_random_streams = getattr(self, 'paired_random_streams', None)
        if paired_random_streams is None:
            return self.rng
        if not coordinates:
            indices = getattr(self, '_paired_rng_indices', None)
            if indices is None:
                indices = self._paired_rng_indices = Counter()
            coordinates = (indices[stream],)
            indices[stream] += 1
        return paired_random_streams.rng(stream, *coordinates)

    def _take_possession(self, offense, yl):
        if self.quarter == 5:
            self._overtime_possession(offense)
            if self.status is not None:
                return
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
        self.warned_quarters = set()  # a new half: the two-minute warning can stop the clock once more
        k = self.kickoffs[1]
        self._kick('half_start', k['kicking_team'], k['receiving_team'])

    def _kick(self, kind, kicker, receiver, clock_rule=None):
        """A kickoff, sampled from the observed kickoff pool, or a safety free kick sampled from the observed safety-kick
        table. A kick that runs the clock out ends the quarter on the return.
        """
        pool = self.ref.safety_kick_pool if kind == 'safety_free_kick' else self.ref.kickoff_pool
        sample = self._rng(f'free_kick:{kind}').choice(pool)
        source = {'game_id': sample['game_id'], 'play_id': sample['play_id'], 'game_date': sample['game_date']}
        if kind == 'safety_free_kick':
            source.update(pool=SAFETY_KICK_POOL, safety_play_id=sample['safety_play_id'],
                          kick_play_id=sample['kick_play_id'])
        clock_before = self.clock
        # The made-kick rule, applied to a kickoff: a runoff that fits is charged in full; a runoff that does not fit expires the
        # quarter. The expiry sets the clock to zero explicitly, and the overrun is recorded, not clamped away.
        expires = sample['runoff'] >= clock_before
        after_clock = 0 if expires else clock_before - sample['runoff']
        after_clock, stopped = (0, False) if expires else two_minute_stop(self.quarter, clock_before, after_clock,
                                                                          self.warned_quarters)
        if stopped:
            self.warned_quarters.add(self.quarter)
        self.clock = after_clock
        self.events.append({'kind': kind, 'kicking_team': kicker, 'receiving_team': receiver, 'quarter': self.quarter,
                            'clock_before': clock_before, 'runoff_seconds': sample['runoff'],
                            'clock_after': after_clock,
                            'clock_clamped_to_zero': False, 'clock_expired_during_kickoff': expires,
                            'two_minute_warning': stopped,
                            'runoff_overrun_seconds': sample['runoff'] - clock_before if expires else 0,
                            'spot_yardline_100': sample['spot'], 'after_drive': len(self.drives),
                            'clock_transition': {
                                'clock_starts_on': 'legal_touch',
                                'clock_interval': 'free_kick_to_next_snap',
                                'runoff_seconds': sample['runoff'],
                                'stoppages': ([{'kind': 'automatic_two_minute_warning', 'team': None}]
                                              if stopped else []),
                                'restart_trigger': 'period_restart' if expires else 'next_snap',
                                'restart_clock_seconds': after_clock,
                            },
                            'clock_rule': clock_rule,
                            'source': source})
        if not expires:
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
            self._regulation_over()

    def _regulation_over(self):
        """The clock ran out at the end of regulation or of overtime. A tie after regulation goes to overtime (Rule 16)."""
        if self.quarter == 5:
            self._end_overtime(self._points_leader())
        elif self.points['A'] == self.points['B'] and self.ref.overtime_pool is not None:
            self._begin_overtime()
        else:
            self.status = 'complete_regulation'

    def _begin_overtime(self):
        """Rule 16, Articles 2-3: a seeded fair coin toss, then the toss winner's kick-or-receive decision, then one
        10-minute period. A forced first possession (sensitivity) gives the toss winner the receive."""
        winner = self.ref.overtime_toss or self._rng('overtime_coin_toss').choice(sorted(self.ledger.teams))
        loser = other(winner, self.ledger.teams)
        if self.ref.overtime_toss is not None:
            choice, source = 'receive', 'forced first possession (sensitivity)'
        elif self.ref.overtime_choice is not None:
            choice, source = self.ref.overtime_choice, 'forced decision (labelled control)'
        elif self.ref.overtime_p_kick is not None:
            choice = 'kick' if self._rng('overtime_first_choice').random() < self.ref.overtime_p_kick else 'receive'
            source = 'observed kick-or-receive model (2025 regular season)'
        else:
            choice, source = 'receive', 'always receive (labelled control)'
        kicker, receiver = (winner, loser) if choice == 'kick' else (loser, winner)
        self.overtime = {'toss_winner': winner, 'receiving_team': receiver, 'kicking_team': kicker,
                         'first_possession_choice': choice, 'choice_source': source,
                         'choice_p_kick': self.ref.overtime_p_kick,
                         'regulation_points': dict(self.points), 'possessions': [], 'winner': None, 'result': None}
        self.boundaries.append({'from_quarter': 4, 'to_quarter': 5, 'kind': 'overtime', 'clock_before': 0,
                                'drive_index': len(self.drives)})
        self.quarter, self.clock = 5, OVERTIME_LENGTH
        self.timeouts = {'A': OVERTIME_TIMEOUTS, 'B': OVERTIME_TIMEOUTS}
        self._kick('overtime_start', kicker, receiver)

    def _points_leader(self):
        if self.points['A'] == self.points['B']:
            return None
        return max(self.points, key=self.points.get)

    def _overtime_possession(self, offense):
        """Rule 16, Article 3(b)-(d): once both teams have possessed, a leader wins; a tie carries on as sudden death."""
        possessions = self.overtime['possessions']
        if len(set(possessions)) == 2 and self._points_leader() is not None:
            self._end_overtime(self._points_leader())
            return
        possessions.append(offense)

    def _overtime_after_score(self, then):
        """A kick after a score in overtime. Returns True when the score decides the game."""
        _, kind, kicker, receiver = then
        if (kind == 'safety_free_kick' and len(self.overtime['possessions']) == 1
                and receiver == self.overtime['kicking_team']):
            # Article 3(a): the team that kicked off scores a safety on the receivers' initial possession and wins
            self._end_overtime(receiver)
            return True
        if len(set(self.overtime['possessions'])) == 2 and self._points_leader() is not None:
            self._end_overtime(self._points_leader())
            return True
        return False

    def _end_overtime(self, winner):
        self.overtime['winner'] = winner
        self.overtime['result'] = 'winner' if winner else 'tie'
        self.status = 'complete_overtime'

    def _apply(self, then, clock_rule=None):
        if then[0] == 'possession':
            self._take_possession(then[1], then[2])
        else:
            _, kind, kicker, receiver = then
            self._kick(kind, kicker, receiver, clock_rule)

    def _missed_field_goal_transition(self, snap_yardline_100, kick_spot_yardline_100):
        """Sample the receiver's next-drive starting spot from historical missed-kick transitions."""
        base_spot = missed_field_goal_spot(kick_spot_yardline_100)
        if self.clock == 0 and self.quarter in (2, 4):
            return {'status': 'period_expired', 'baseline_yardline_100': base_spot,
                    'receiving_start_yardline_100': None, 'spot_adjustment_yards': 0,
                    'source': None}
        bucket = fg_bucket(snap_yardline_100)
        bucket_pool = self.ref.missed_field_goal_pool.get(bucket, [])
        pool_name = bucket
        if len(bucket_pool) < MIN_KICK_N:
            bucket_pool = [sample for samples in self.ref.missed_field_goal_pool.values() for sample in samples]
            pool_name = 'all_kick_spots'
        eligible = [sample for sample in bucket_pool
                    if 1 <= base_spot + sample['spot_adjustment_yards'] <= 99]
        if not eligible:
            self.block('missed_field_goal_return_pool_unavailable')
            return None
        sample = self._rng('missed_field_goal_spot').choice(eligible)
        adjustment = sample['spot_adjustment_yards']
        return {'status': 'sampled_historical_next_drive_spot',
                'baseline_yardline_100': base_spot,
                'receiving_start_yardline_100': base_spot + adjustment,
                'spot_adjustment_yards': adjustment,
                'pool_bucket': pool_name, 'pool_sample_count': len(eligible),
                'source': dict(sample['source'])}

    def _continue(self, then):
        """The event that follows a play. An expired clock resolves the quarter first (rules file, sections 2-3).
        """
        if self.quarter == 5 and then[0] == 'kick' and self._overtime_after_score(then):
            return
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
            self._regulation_over()

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
            play['outcome']['clock_transition']['runoff_seconds'] = observed
            return
        charge = min(observed, KICK_DURATION_SECONDS)
        play['outcome']['clock_runoff_seconds'] = charge
        play['outcome']['kick_duration_seconds'] = charge
        play['outcome']['ordinary_runoff_not_charged'] = observed - charge
        play['state_after']['clock_seconds'] = before - charge
        drive['end_clock'] = before - charge
        self.clock = before - charge
        transition = play['outcome']['clock_transition']
        transition['runoff_seconds'] = charge
        transition['restart_clock_seconds'] = play['state_after']['clock_seconds']

    def _two_minute_stop_plays(self, plays, terminal):
        """Record the two-minute warning after the down that crosses 2:00 in a late quarter.

        Rule 3 Section 41 places the automatic timeout at the conclusion of the last down legally snapped or kicked before 2:00.
        The game clock therefore keeps its observed value at the dead ball. The timeout has no game-clock runoff; the next snap
        resumes from that value. Returns the original sampled plays and terminal unchanged apart from the warning marker.
        """
        for i, play in enumerate(plays):
            # The duration of a made field-goal down is applied after its outcome is drawn. Check that terminal play then.
            if terminal == 'field_goal_attempt' and i == len(plays) - 1:
                continue
            if self._mark_two_minute_warning(play):
                break
        return plays, terminal

    def _mark_two_minute_warning(self, play):
        before, after = play['state_before'], play['state_after']
        clock_after, stopped = two_minute_stop(before['quarter'], before['clock_seconds'], after['clock_seconds'],
                                                self.warned_quarters)
        if not stopped:
            return False
        self.warned_quarters.add(before['quarter'])
        play['outcome']['two_minute_warning'] = True
        after['clock_seconds'] = clock_after
        after['clock_status'] = 'running_at_next_snap'
        transition = play['outcome'].get('clock_transition')
        if transition is not None:
            transition['stoppages'].append({'kind': 'automatic_two_minute_warning', 'team': None})
            transition['restart_trigger'] = 'next_snap'
            transition['restart_clock_seconds'] = clock_after
        return True

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
                sampled = part.get('sampled_play_context', part)
                caller = sampled.get('timeout_team')
                if caller not in (sampled.get('posteam'), sampled.get('defteam')):
                    self.block('timeout_team_unresolved')
                    mapped = self.offense
                else:
                    mapped = self.offense if caller == sampled.get('posteam') else self.defense
                if caller in (sampled.get('posteam'), sampled.get('defteam')) and self.timeouts[mapped] > 0:
                    self.timeouts[mapped] -= 1
                    part['timeout_applied'] = True
                elif caller in (sampled.get('posteam'), sampled.get('defteam')):
                    self.block('timeout_limit_exceeded')
                part['timeout_charged_to'] = mapped
            play['state_after']['home_timeouts'] = self.timeouts['A']
            play['state_after']['away_timeouts'] = self.timeouts['B']
            if part['timeout']:
                play['outcome']['timeout_stop'] = {
                    'called_by': part['timeout_charged_to'], 'applied': part['timeout_applied'],
                    'counts_before': {'home': play['state_before']['home_timeouts'], 'away': play['state_before']['away_timeouts']},
                    'counts_after': {'home': play['state_after']['home_timeouts'], 'away': play['state_after']['away_timeouts']},
                    'clock_at_stop': play['state_after']['clock_seconds'], 'restart': 'the next snap, from clock_at_stop'}

    def _record_clock_transitions(self, plays):
        """Describe clock stops and restarts while retaining observed snap-to-next-snap intervals."""
        for play in plays:
            part, outcome = play['participants'], play['outcome']
            before, after = play['state_before'], play['state_after']
            reasons = []
            if part.get('timeout'):
                reasons.append({'kind': 'team_timeout' if part.get('timeout_applied') else 'illegal_team_timeout',
                                'team': part.get('timeout_charged_to')})
            if outcome.get('two_minute_warning'):
                reasons.append({'kind': 'automatic_two_minute_warning', 'team': None})
            if part.get('out_of_bounds'):
                reasons.append({'kind': 'runner_out_of_bounds', 'team': None})
            if play['event_type'] == 'pass_incomplete':
                reasons.append({'kind': 'incomplete_pass', 'team': None})
            first_down = (before.get('offense_team') == after.get('offense_team') and after.get('down') == 1
                          and before.get('down') != 1)
            if first_down and not (outcome.get('touchdown') or outcome.get('safety')):
                reasons.append({'kind': 'first_down', 'team': None})
            if outcome.get('touchdown') or play['event_type'] == 'field_goal_attempt' or outcome.get('safety'):
                reasons.append({'kind': 'score_or_try_transition', 'team': None})
            if outcome.get('turnover') or outcome.get('punt'):
                reasons.append({'kind': 'possession_change', 'team': None})
            if outcome.get('quarter_change') or after.get('end_of_drive') in ('halftime', 'end_of_regulation', 'end_of_overtime'):
                reasons.append({'kind': 'period_end', 'team': None})

            late_window = ((before['quarter'] == 2 and after['clock_seconds'] <= TWO_MINUTE_MARK)
                           or (before['quarter'] == 4 and after['clock_seconds'] <= 300))
            if any(reason['kind'] in ('automatic_two_minute_warning', 'team_timeout', 'incomplete_pass')
                   for reason in reasons):
                restart = 'next_snap'
            elif any(reason['kind'] == 'period_end' for reason in reasons):
                restart = 'period_restart'
            elif any(reason['kind'] in ('score_or_try_transition', 'possession_change') for reason in reasons):
                restart = 'free_kick_or_next_snap'
            elif any(reason['kind'] == 'first_down' for reason in reasons):
                restart = 'next_snap' if late_window else 'referee_signal'
            elif any(reason['kind'] == 'runner_out_of_bounds' for reason in reasons):
                restart = 'next_snap' if late_window else 'referee_signal'
            else:
                restart = 'continuous'
            play['state_before']['clock_status'] = 'running_at_snap'
            play['state_after']['clock_status'] = ('period_ended' if restart == 'period_restart' else 'running_at_next_snap')
            outcome['clock_transition'] = {
                'clock_interval': 'observed_snap_to_next_snap',
                'runoff_seconds': outcome['clock_runoff_seconds'],
                'stoppages': reasons,
                'restart_trigger': restart,
                'restart_clock_seconds': after['clock_seconds'] if restart != 'continuous' else None,
            }

    def _resolve_special_teams(self, event, state, source_row, runoff, spot, rng):
        """Sample kick outcomes from the observed rate tables and resolve blocked kicks using audited source records."""
        if event == 'field_goal_attempt':
            feasibility = fg_feasibility.evaluate(state['yl'])
            if not feasibility['eligible']:
                return {'blocker': 'field_goal_attempt_exceeds_historical_feasibility_ceiling'}
            if 'long_field_goal_feasibility' in getattr(self.ref, 'blocker_fixes', ()):
                model = self.ref.kicks.get('field_goal_distance_model')
                if model is None:
                    return {'blocker': 'field_goal_distance_model_missing'}
                kick_distance = feasibility['kick_distance_yards']
                if kick_distance > float(model['max_observed_attempt_yards']):
                    return {'blocker': 'field_goal_distance_over_observed_max'}
                sampler = getattr(self.ref, 'contextual_sampler', None)
                if sampler is None:
                    return {'blocker': 'field_goal_distance_sampler_missing'}
                try:
                    result, distribution = sampler._field_goal_probability_result(kick_distance, rng)
                except ValueError as exc:
                    return {'blocker': f'field_goal_distance_model_unavailable:{exc}'}
                source = {'table': model['source_file'], 'fallback_level': distribution['fallback_level'],
                          'distance_yards': kick_distance, 'support_n': distribution['support_n'],
                          'nearby_attempts': distribution['nearby_attempts'],
                          'max_observed_attempt_yards': model['max_observed_attempt_yards'],
                          'max_observed_attempt_source': model['max_observed_attempt_source'],
                          'max_observed_made_yards': model['max_observed_made_yards'],
                          'max_observed_made_source': model['max_observed_made_source'],
                          'probabilities': {key: distribution[key] for key in ('made', 'missed', 'blocked')},
                          'field_goal_feasibility': feasibility}
                if sampler is not None and sampler.decisions:
                    sampler.decisions[-1].update(fg_fallback_level=distribution['fallback_level'],
                                                 fg_distribution_support_n=distribution['nearby_attempts'],
                                                 fg_distribution_total_n=distribution['support_n'])
                if result != 'blocked':
                    return {'metadata': {'field_goal_result': result, 'field_goal_result_source': source,
                                         'field_goal_feasibility': feasibility}}
                kick_type, outcome = self._sample_blocked_kick(
                    'field_goal', rng, state['clock'], state['quarter'], state)
                if kick_type:
                    return {'blocker': kick_type}
                return {'event': 'blocked_field_goal', 'clock_runoff_seconds': outcome['clock_runoff_seconds'],
                        'kick_outcome': outcome,
                        'metadata': {'field_goal_result': 'blocked', 'field_goal_result_source': source,
                                     'field_goal_feasibility': feasibility}}
            bucket = fg_bucket(state['yl'])
            outcomes = self.ref.kicks.get('field_goal_outcomes', {}).get(bucket)
            if outcomes is None:
                return {'blocker': f'field_goal_outcomes_missing:{bucket}'}
            made, missed, blocked = outcomes
            attempts = made + missed + blocked
            if attempts < MIN_KICK_N:
                return {'blocker': f'thin_kick_cell:field_goal:{bucket}'}
            draw = rng.randrange(attempts)
            result = 'made' if draw < made else 'missed' if draw < made + missed else 'blocked'
            source = {'table': 'kick_results_2022_2025.csv', 'yardline_bucket': bucket,
                      'counts': {'made': made, 'missed': missed, 'blocked': blocked},
                      'attempts': attempts, 'kick_distance_yards': feasibility['kick_distance_yards'],
                      'historical_ceiling_yards': feasibility['historical_ceiling_yards'],
                      'bucket_kick_distance_range_yards': feasibility['historical_bucket_kick_distance_range_yards'],
                      'outcome_probability_basis': feasibility['outcome_probability_basis'],
                      'feasibility_source_sha256': feasibility['source_sha256']}
            if result != 'blocked':
                return {'metadata': {'field_goal_result': result, 'field_goal_result_source': source,
                                     'field_goal_feasibility': feasibility}}
            kick_type, outcome = self._sample_blocked_kick('field_goal', rng, state['clock'], state['quarter'], state)
            if kick_type:
                return {'blocker': kick_type}
            return {'event': 'blocked_field_goal', 'clock_runoff_seconds': outcome['clock_runoff_seconds'],
                    'kick_outcome': outcome,
                    'metadata': {'field_goal_result': 'blocked', 'field_goal_result_source': source,
                                 'field_goal_feasibility': feasibility}}

        rates = self.ref.blocked_kicks.get('rates', {}).get('punt_blocked', {})
        attempts, blocked = rates.get('attempts', 0), rates.get('blocked', 0)
        if attempts <= 0 or not 0 <= blocked <= attempts:
            return {'blocker': 'blocked_punt_rate_unavailable'}
        if rng.randrange(attempts) >= blocked:
            return None
        kick_type, outcome = self._sample_blocked_kick('punt', rng, state['clock'], state['quarter'], state)
        if kick_type:
            return {'blocker': kick_type}
        return {'event': 'blocked_punt', 'clock_runoff_seconds': outcome['clock_runoff_seconds'],
                'kick_outcome': outcome}

    def _sample_blocked_kick(self, kick_type, rng, clock, quarter, state=None):
        """Draw one observed blocked-kick record that fits the state.

        A period-expired row is a period-ending context, not a reusable next-possession result. Only Q2/Q4 can use it, and
        only when its observed play duration can reach the current clock. Q1/Q3 need a classified live-ball transition so
        the series can continue after the change of ends.
        """
        records = self.ref.blocked_kicks.get('records', {}).get(kick_type, [])
        if not records:
            return 'blocked_kick_outcome_pool_missing', None
        if 'blocked_kick_geometry' in getattr(self.ref, 'blocker_fixes', ()):
            return self._sample_blocked_kick_by_category(kick_type, records, rng, clock, quarter, state)
        categories, exclusions = self._eligible_blocked_kick_categories(records, clock, quarter)
        fitting = [record for group in categories.values() for record in group]
        if not fitting:
            return f'blocked_kick_no_clock_compatible_transition:{kick_type}', None
        sample = rng.choice(fitting)
        status = sample.get('classification_status')
        supported = reducer.BLOCKED_KICK_STATUSES
        if status not in supported:
            return f'blocked_kick_outcome_unresolved:{kick_type}:{status}', None
        runoff = sample.get('clock_runoff_seconds')
        if not isinstance(runoff, int) or runoff < 0:
            return f'blocked_kick_clock_unresolved:{kick_type}', None
        outcome = dict(sample)
        outcome['period_expired_category_exclusions'] = dict(sorted(exclusions.items()))
        outcome['reference_fixture_sha256'] = self.ref.blocked_kicks.get('sha256')
        scoring_team = outcome.get('scoring_team')
        if scoring_team:
            if scoring_team == outcome.get('posteam'):
                outcome['scoring_role'] = 'kicking_team'
            elif scoring_team == outcome.get('defteam'):
                outcome['scoring_role'] = 'receiving_team'
            else:
                return f'blocked_kick_scoring_team_unresolved:{kick_type}', None
        return None, outcome

    @staticmethod
    def _blocked_kick_category(record):
        status = record.get('classification_status')
        if status not in reducer.BLOCKED_KICK_STATUSES:
            return f'unresolved:{status}'
        if status == 'period_expired':
            return 'period_expired'
        if status == 'touchdown':
            return f'touchdown:{record.get("scoring_role") or "unknown"}'
        if status == 'safety':
            return 'safety'
        if status == 'classified_next_snap':
            return f'next_snap:{record.get("possession_after_role") or "unknown"}'
        if status == 'classified_dead_ball_spot':
            return f'dead_ball:{record.get("possession_after_role") or "unknown"}'
        return f'recovery:{record.get("recovery_role") or "unknown"}:{record.get("crossed_line")}'

    @staticmethod
    def _eligible_blocked_kick_categories(records, clock, quarter):
        """Keep terminal period rows only when the NFL state can end and no continuing spot is required."""
        categories = defaultdict(list)
        exclusions = Counter()
        for record in records:
            category = _Game._blocked_kick_category(record)
            if category == 'period_expired':
                if quarter not in (2, 4):
                    exclusions['period_expired_requires_half_or_game_end'] += 1
                    continue
                runoff = record.get('clock_runoff_seconds')
                if type(runoff) is not int or runoff < clock:
                    exclusions['period_expired_source_clock_too_short'] += 1
                    continue
            categories[category].append(record)
        return categories, exclusions

    def _sample_blocked_kick_by_category(self, kick_type, records, rng, clock, quarter, state):
        """Draw only among observed blocked-kick outcomes that resolve legally at this live state."""
        categories, exclusions = self._eligible_blocked_kick_categories(records, clock, quarter)
        if not categories:
            self._record_blocked_kick_geometry('no_clock_compatible_transition', 0, exclusions)
            return f'blocked_kick_no_clock_compatible_transition:{kick_type}', None
        if state is None:
            self._record_blocked_kick_geometry('state_missing', 0, exclusions)
            return f'blocked_kick_geometry_state_missing:{kick_type}', None
        event = 'blocked_punt' if kick_type == 'punt' else 'blocked_field_goal'
        drawable_by_category = {}
        geometry_exclusions = Counter()
        projected_by_id = {}
        unresolved_by_id = {}
        for category, rows in categories.items():
            drawable = []
            for row in rows:
                status = row.get('classification_status')
                if status not in reducer.BLOCKED_KICK_STATUSES:
                    drawable.append(row)
                    unresolved_by_id[id(row)] = f'blocked_kick_outcome_unresolved:{kick_type}:{status}'
                    continue
                runoff = row.get('clock_runoff_seconds')
                if type(runoff) is not int or runoff < 0:
                    drawable.append(row)
                    unresolved_by_id[id(row)] = f'blocked_kick_clock_unresolved:{kick_type}'
                    continue
                candidate = dict(row)
                scoring_team = candidate.get('scoring_team')
                if scoring_team and scoring_team not in (candidate.get('posteam'), candidate.get('defteam')):
                    drawable.append(row)
                    unresolved_by_id[id(row)] = f'blocked_kick_scoring_team_unresolved:{kick_type}'
                    continue
                try:
                    if status == 'classified_next_snap':
                        candidate = reducer.project_blocked_kick_next_snap(candidate, state)
                    reducer.apply_blocked_kick(state, event, candidate)
                except reducer.UnmodelledOutcome as exc:
                    geometry_exclusions[f'{category}:{exc}'] += 1
                    continue
                except (ValueError, TypeError, KeyError) as exc:
                    drawable.append(row)
                    unresolved_by_id[id(row)] = f'blocked_kick_outcome_unresolved:{kick_type}:{status}:{exc}'
                    continue
                drawable.append(row)
                projected_by_id[id(row)] = candidate
            if drawable:
                drawable_by_category[category] = drawable
        if not drawable_by_category:
            category = sorted(categories)[0]
            reason = next((key[len(category) + 1:] for key in sorted(geometry_exclusions)
                           if key.startswith(f'{category}:')), 'no compatible source transition')
            self._record_blocked_kick_geometry(category, 0, exclusions, geometry_exclusions)
            return f'blocked_kick_no_legal_geometry:{kick_type}:{category}:{reason}', None
        category_names = sorted(drawable_by_category)
        category = rng.choices(category_names,
                               weights=[len(drawable_by_category[name]) for name in category_names], k=1)[0]
        selected_rows = drawable_by_category[category]
        sample = rng.choice(selected_rows)
        if id(sample) in unresolved_by_id:
            self._record_blocked_kick_geometry(category, 0, exclusions, geometry_exclusions)
            return unresolved_by_id[id(sample)], None
        outcome = dict(projected_by_id[id(sample)])
        outcome['geometry_candidate_count'] = sum(id(row) not in unresolved_by_id for row in selected_rows)
        outcome['geometry_category'] = category
        outcome['period_expired_category_exclusions'] = dict(sorted(exclusions.items()))
        outcome['geometry_category_exclusions'] = dict(sorted(geometry_exclusions.items()))
        outcome['reference_fixture_sha256'] = self.ref.blocked_kicks.get('sha256')
        self._record_blocked_kick_geometry(category, outcome['geometry_candidate_count'],
                                           exclusions, geometry_exclusions)
        scoring_team = outcome.get('scoring_team')
        if scoring_team:
            if scoring_team == outcome.get('posteam'):
                outcome['scoring_role'] = 'kicking_team'
            elif scoring_team == outcome.get('defteam'):
                outcome['scoring_role'] = 'receiving_team'
            else:
                return f'blocked_kick_scoring_team_unresolved:{kick_type}', None
        return None, outcome

    def _record_blocked_kick_geometry(self, category, candidates, exclusions=None, geometry_exclusions=None):
        sampler = getattr(self.ref, 'contextual_sampler', None)
        if sampler is not None and sampler.decisions:
            sampler.decisions[-1].update(blocked_kick_geometry_category=category,
                                         blocked_kick_geometry_candidates=int(candidates),
                                         blocked_kick_period_expired_exclusions=dict(sorted((exclusions or {}).items())),
                                         blocked_kick_geometry_category_exclusions=dict(
                                             sorted((geometry_exclusions or {}).items())))

    def _try_situation(self, scorer):
        """What a try policy conditions on, read before the try is drawn: the scorer's margin after the six points, the
        quarter and clock, whether this is the scorer's first offensive drive, and whether it is the game's first touchdown.
        The drive being scored is already in self.drives, so it counts toward both drive tallies."""
        opponent = other(scorer, self.ledger.teams)
        return {
            'margin': self.points[scorer] + TD_POINTS - self.points[opponent], 'quarter': self.quarter, 'clock': self.clock,
            'opening_drive': scorer == self.offense and sum(1 for d in self.drives if d['offense_team'] == scorer) == 1,
            'first_td': sum(1 for d in self.drives if d.get('touchdown_scored_by')) == 1,
        }

    def _overtime_decided(self):
        """Rule 16, Article 3(b)-(c): both teams have possessed and one leads, or the score is level and the game is sudden
        death. Called after a score is on the board, so a touchdown that decides the game is recognised before its try."""
        return len(set(self.overtime['possessions'])) == 2 and self._points_leader() is not None

    def _article_5a_applies(self, offense, outcome, turnover_kind):
        """Article 5(a): the first team to possess scored, then the second team loses the ball on an interception or a fumble.
        The down runs to its conclusion, so a return touchdown counts and its try is still attempted (rules file, Rule 16)."""
        possessions = self.overtime['possessions']
        return (len(possessions) == 2 and offense == possessions[1] and bool(self.overtime.get('first_possession_scored'))
                and turnover_kind in ('interception', 'fumble') and outcome in ('turnover', 'defense_touchdown'))

    def _observed_overtime_drive(self):
        """Rule 16 with an observed drive, drawn the way the blocked kicks are: one observed regular-season overtime drive
        ends the possession, scores, or runs the period out. A drive fits the state when its observed time is within the
        clock; a period end fits when its observed time reaches the clock. The Rule 16 possession logic then checks it."""
        offense, defense, clock = self.offense, self.defense, self.clock
        fits = [d for d in self.ref.overtime_pool
                if (d['duration'] >= clock if d['outcome'] == 'period_end' else d['duration'] <= clock)]
        if not fits:
            self.block('overtime_drive_not_observed_for_clock')
            return
        sample = self._rng('observed_overtime_drive').choice(fits)
        self.clock = clock - min(sample['duration'], clock)
        points_before = {team: self.points[team] for team in self.ledger.teams}  # a Counter: an absent team is zero
        self.points[offense] += sample['points_offense']
        self.points[defense] += sample['points_defense']
        outcome = sample['outcome']
        scorer = offense if outcome in ('touchdown', 'field_goal_made') else defense if outcome == 'defense_touchdown' else None
        article_5a = self._article_5a_applies(offense, outcome, sample['turnover_kind'])
        if article_5a:
            self.overtime['article_5a'] = {'turnover_kind': sample['turnover_kind'], 'drive_index': len(self.drives) + 1,
                                           'return_touchdown': outcome == 'defense_touchdown',
                                           'leader_before_down': self._points_leader()}
        if len(self.overtime['possessions']) == 1 and scorer == offense:
            self.overtime['first_possession_scored'] = True
        points_on_drive = {'team': offense, 'points': FG_POINTS, 'try': None} if outcome == 'field_goal_made' else None
        try_source = None
        if outcome in ('touchdown', 'defense_touchdown'):
            tied_before = points_before['A'] == points_before['B']
            if tied_before and len(set(self.overtime['possessions'])) == 2 and not article_5a:
                # Sudden death: a touchdown from a tie is the team next scoring, so the game ends and no try is attempted.
                try_source = 'not_attempted_game_ends'
                points_on_drive = {'team': scorer, 'points': TD_POINTS, 'try': None}
            elif sample['try_kind']:
                # The point after the drive shows in the observed rows: the outcome is observed, not drawn.
                try_points = TRY_POINTS[sample['try_kind']] if sample['try_made'] else 0
                self.points[scorer] += try_points
                points_on_drive = {'team': scorer, 'points': TD_POINTS + try_points,
                                   'try': try_record(sample['try_kind'], sample['try_made'])}
                try_source = 'observed_point_after'
            else:
                # No point after was observed: the old rule ended the game without one. The try is drawn from the conditional
                # try table for the margin it is taken from; without that table it falls back to the regulation rates.
                if self.ref.overtime_try_p_two is not None:
                    margin = self.points[scorer] - self.points[other(scorer, self.ledger.teams)]
                    p_two = self.ref.overtime_try_p_two[try_margin_bucket(margin)]
                    source = 'conditional_try_fallback'
                else:
                    p_two, source = None, 'regulation_try_rates_fallback'
                try_points, try_rec, why = _try_after_touchdown(
                    self._rng('post_touchdown_try', self.next_play_sequence), self.ref.kicks, p_two)
                if why:
                    self.block(why)
                    return
                self.points[scorer] += try_points
                points_on_drive = {'team': scorer, 'points': TD_POINTS + try_points, 'try': try_rec}
                try_source = source
        drive = {'index': len(self.drives) + 1, 'offense_team': offense, 'quarter_start': 5, 'clock_start': clock,
                 'plays': [], 'terminal': OVERTIME_TERMINAL[outcome], 'end_quarter': 5, 'end_clock': self.clock,
                 'points_scored_on_drive': points_on_drive, 'try_source': try_source,
                 'field_goal_made': (outcome == 'field_goal_made') if outcome.startswith('field_goal') else None,
                 'observed_overtime_drive': {'outcome': outcome, 'source_game_id': sample['game_id'],
                                             'source_drive': sample['drive'], 'duration_seconds': sample['duration'],
                                             'points_offense': sample['points_offense'],
                                             'points_defense': sample['points_defense'],
                                             'turnover_kind': sample['turnover_kind'],
                                             'source_next_offense': sample['next_offense'],
                                             'source_next_yardline': sample['next_yardline']}}
        if scorer is not None:
            drive['touchdown_scored_by'] = scorer if outcome != 'field_goal_made' else None
        self.drives.append(drive)
        if outcome == 'period_end':
            self._regulation_over()
        elif scorer is not None:
            receiver = other(scorer, self.ledger.teams)
            self._continue(('kick', 'post_field_goal' if outcome == 'field_goal_made' else 'post_score', scorer, receiver))
        elif article_5a:
            # The down completes with no score: the first team's lead stands and the game ends (Article 5(a)).
            self._end_overtime(self._points_leader())
        else:
            # The pool's next_offense is a historical club abbreviation. The simulated game uses A/B labels;
            # non-scoring OT outcomes transfer possession to the other simulated team.
            self._continue(('possession', other(offense, self.ledger.teams), sample['next_yardline']))

    def _drive_body(self):
        if self.quarter == 5:
            return self._observed_overtime_drive()
        start = {'quarter': self.quarter, 'clock': self.clock, 'offense': self.offense, 'defense': self.defense,
                 'yl': self.yl, 'down': self.down, 'togo': self.togo,
                 'dir': self.ledger.attacks_x100(self.offense, self.quarter)}
        special_teams = (self._resolve_special_teams if self.ref.blocked_kicks.get('rates')
                         or self.ref.kicks.get('field_goal_outcomes') else None)
        research = {'clock': self.clock_draws} if self.clock_draws is not None else {}  # the E2 call is unchanged
        attempt = []  # the plays made before a block are evidence, kept apart from drives and stats
        sampler = self.ref.contextual_sampler
        timeout_guard = _TimeoutSamplingGuard(getattr(self.ref, 'participants', {}), self.timeouts)
        decision_log = getattr(sampler, 'decisions', None)
        decision_start = len(decision_log) if isinstance(decision_log, list) else None
        plays, terminal = e1.simulate(start, self.model_seed * 1000 + len(self.drives), self.ref.pool,
                                      self.simulation_id, special_teams=special_teams, partial=attempt,
                                      sampling_policy=self.ref.contextual_sampler,
                                      score_diff=self.points[self.offense] - self.points[self.defense],
                                      play_index_start=self.next_play_sequence,
                                      drive_index=len(self.drives) + 1,
                                      paired_random_streams=self.paired_random_streams,
                                      sampling_guard=timeout_guard, **research)
        if plays is None:
            self.blocked_attempt = {'drive_index': len(self.drives) + 1, 'offense_team': self.offense,
                                    'quarter_start': start['quarter'], 'clock_start': start['clock'],
                                    'state_at_drive_start': {key: start[key] for key in (
                                        'quarter', 'clock', 'offense', 'defense', 'yl', 'down', 'togo')},
                                    'blocker': terminal, 'plays_before_block': attempt,
                                    'timeout_sampling_guard': timeout_guard.describe(),
                                    'note': 'raw E1 plays before the block; not part of drives or stats'}
            if decision_start is not None:
                new_decisions = decision_log[decision_start:]
                unrepresented = new_decisions[len(attempt):]
                if unrepresented:
                    self.blocked_attempt['unrepresented_decisions'] = copy.deepcopy(unrepresented)
            self.block(terminal)
            return
        if any(p['outcome'].get('penalty') for p in plays):
            # a penalty is an unmodelled transition: the pool excludes penalty plays, so this should never be drawn; if it is,
            # the game is blocked, never completed
            self.block('penalty_not_modelled')
            return
        plays, terminal = self._two_minute_stop_plays(plays, terminal)
        e1.check_drive(plays, terminal)
        self._last_plays = plays
        drive_index = len(self.drives) + 1
        for play in plays:
            play['sequence'] = self.next_play_sequence
            play['id'] = f'{self.simulation_id}:{self.next_play_sequence}'
            self.next_play_sequence += 1
            play['participants'] = self.ref.participants_for(
                play, offense_team=self.offense, snapshot=self.pregame_snapshot, seed=self.seed)
            play['state_before']['drive_index'] = drive_index  # E1 writes 1 on every play; the game index is written here
            play['state_after']['drive_index'] = drive_index
        self._apply_timeouts(plays)
        if timeout_guard.remaining != self.timeouts:
            self.block('timeout_sampling_guard_mismatch')
        self._record_clock_transitions(plays)
        last = plays[-1]['state_after']
        drive = {'index': len(self.drives) + 1, 'offense_team': self.offense, 'quarter_start': self.quarter,
                 'clock_start': self.clock, 'plays': plays, 'terminal': terminal,
                 'end_quarter': last['quarter'], 'end_clock': last['clock_seconds'],
                 'points_scored_on_drive': None, 'field_goal_made': None}
        if timeout_guard.excluded or timeout_guard.remaining != self.timeouts:
            drive['timeout_sampling_guard'] = timeout_guard.describe()
        self.drives.append(drive)
        for play in plays:  # a quarter change inside a drive: the drive goes on (rules file, section 2)
            if play['outcome']['quarter_change']:
                self.boundaries.append({'from_quarter': play['state_before']['quarter'],
                                        'to_quarter': play['state_after']['quarter'],
                                        'kind': 'change_of_ends_mid_drive', 'drive_index': drive['index']})
        self.quarter, self.clock = last['quarter'], last['clock_seconds']
        if self.blocker:
            return
        if terminal == 'halftime':
            self._half_start()
        elif terminal in ('end_of_regulation', 'end_of_overtime'):
            self._regulation_over()
        elif terminal == 'field_goal_attempt':
            snap_yl = plays[-1]['state_before']['yardline_100']  # the published yardline_100 is the snap position
            kick_spot = kick_spot_yardline_100(snap_yl)  # the holder's spot: where the ball is actually kicked from
            bucket = fg_bucket(snap_yl)  # the published make-rate cells are keyed on the snap position, so the bucket is too
            result = plays[-1]['outcome'].get('field_goal_result')
            if result not in ('made', 'missed'):
                made, why = _draw(self._rng('field_goal_outcome', self.next_play_sequence),
                                  self.ref.kicks['field_goal'].get(bucket, (0, 0)), f'field_goal:{bucket}')
                if why:
                    self.block(why)
                    return
            else:
                made = result == 'made'
            drive['field_goal_made'] = made
            drive['snap_yardline_100'] = snap_yl
            drive['kick_spot_yardline_100'] = kick_spot
            if made:
                self._charge_made_kick(plays[-1], drive)
                self._mark_two_minute_warning(plays[-1])
                self.points[self.offense] += FG_POINTS
                drive['points_scored_on_drive'] = {'team': self.offense, 'points': FG_POINTS, 'try': None}
                self._continue(('kick', 'post_field_goal', self.offense, other(self.offense, self.ledger.teams)))
            else:  # the other team takes over at the spot of the kick, the same dead-ball spot (rules file, section 4)
                self._mark_two_minute_warning(plays[-1])
                if self.pregame_snapshot:
                    transition = self._missed_field_goal_transition(snap_yl, kick_spot)
                    if transition is None:
                        return
                    plays[-1]['outcome']['field_goal_return'] = transition
                    receiving_spot = transition['receiving_start_yardline_100']
                    self._continue(('possession', self.defense,
                                    missed_field_goal_spot(kick_spot) if receiving_spot is None else receiving_spot))
                else:
                    self._continue(('possession', self.defense, missed_field_goal_spot(kick_spot)))
        elif terminal in ('punt', 'turnover', 'turnover_on_downs'):
            self._continue(('possession', last['offense_team'], last['yardline_100']))
        elif terminal == 'touchdown':
            scorer = plays[-1]['outcome'].get('scoring_team') or self.offense
            drive['touchdown_scored_by'] = scorer
            situation = p_two = None
            if self.ref.try_policy is not None:
                situation = self._try_situation(scorer)
                p_two = self.ref.try_policy.p_two(**situation)
            try_points, try_record, why = _try_after_touchdown(
                self._rng('post_touchdown_try', self.next_play_sequence), self.ref.kicks, p_two)
            if why:
                self.block(why)
                return
            if situation is not None:
                drive['try_policy'] = {**situation, 'p_two': p_two, 'kind': try_record['kind']}
            self.points[scorer] += TD_POINTS + try_points
            drive['points_scored_on_drive'] = {'team': scorer, 'points': TD_POINTS + try_points, 'try': try_record}
            self._continue(('kick', 'post_score', scorer, other(scorer, self.ledger.teams)))
        elif terminal == 'safety':
            scorer = self.defense
            self.points[scorer] += SAFETY_POINTS
            drive['points_scored_on_drive'] = {'team': scorer, 'points': SAFETY_POINTS, 'try': None}
            quarter_boundary_safety_kick = ('safety_free_kick_boundaries' in getattr(self.ref, 'blocker_fixes', ())
                                             and self.ref.safety_kick_pool is not None)
            if (self.clock == 0 and quarter_end_kind(self.quarter) == 'quarter_change'
                    and not quarter_boundary_safety_kick):
                self.block('safety_free_kick_not_modelled')
            elif self.clock > 0 and self.ref.safety_kick_pool is None:
                self.block('safety_free_kick_not_modelled')
            else:
                # Time left on the clock means the free kick is due now, sampled from the observed safety-kick table. At a
                # Q2/Q4 boundary no safety kick is due before halftime or the end of regulation; the post-score rule skips it.
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
        # A tie is a regulation end with equal scores. A game stopped before regulation end is not tied, whatever its score.
        status, blocker = self.status or 'blocked', self.blocker
        tied = self.status in ('complete_regulation', 'complete_overtime') and self.points['A'] == self.points['B']
        if status == 'complete_regulation' and tied:
            status, blocker = 'blocked', 'overtime_not_modelled'
        complete = status in ('complete_regulation', 'complete_overtime')
        guarded = unmodelled_transitions(self.drives, self.events)
        unsupported = active_unsupported_rules(guarded, blocker)
        if complete and (guarded or unsupported):
            status = 'regulation_end_guarded'  # the simulation reached regulation end, but it is not a complete game
        points = {'A': self.points['A'], 'B': self.points['B']}
        snapshot = self.pregame_snapshot
        # a full game is valid only on verified input provenance; an exploratory replay stays a statistical game
        verified = bool((snapshot or {}).get('evaluation', {}).get('verified'))
        valid_candidate = bool(snapshot and verified and complete and blocker is None and not guarded and not unsupported)
        record_mode = ('pregame_full_game' if valid_candidate else 'pregame_statistical_game') if snapshot else 'legal_game_state_first_piece'
        scope_out = scope_out_reasons(blocker, complete) + guard_reasons(guarded)
        rec = {
            'mode': record_mode, 'seed': self.seed, 'simulation_id': self.simulation_id,
            'pregame_snapshot': snapshot,
            'game_id': snapshot['schedule']['game_id'] if snapshot else None,
            'as_of_utc': snapshot['as_of'] if snapshot else None,
            'teams': ({'home': snapshot['schedule']['home_team'], 'away': snapshot['schedule']['away_team']}
                      if snapshot else None),
            'scheduled_kickoff_local': ({'date': snapshot['schedule']['gameday'],
                                         'time': snapshot['schedule']['gametime'],
                                         'timezone': snapshot['schedule']['gametime_timezone']}
                                        if snapshot else None),
            'scheduled_kickoff_utc': snapshot['schedule']['scheduled_kickoff_utc'] if snapshot else None,
            'snapshot_hash': snapshot['snapshot_sha256'] if snapshot else None,
            'roster_snapshot_id': snapshot['roster_snapshot_id'] if snapshot else None,
            'model_version': (f'{e1.MODEL_VERSION}+{PREGAME_USAGE_VERSION}' if snapshot else e1.MODEL_VERSION),
            'rules_version': 'nfl-2026-e2-successor',
            'team_identity': ({'A': {'team': snapshot['schedule']['home_team'], 'side': 'home'},
                               'B': {'team': snapshot['schedule']['away_team'], 'side': 'away'}}
                              if snapshot else None),
            'ledger': self.ledger.ledger(), 'kickoffs': self.events, 'boundaries': self.boundaries,
            'drives': self.drives, 'points': points, 'stats': game_stats.compute(self.drives, points),
            'status': status, 'blocker': blocker, 'tied': tied, 'overtime': self.overtime,
            'complete_regulation': complete and not guarded and not unsupported,
            'regulation_end_reached': complete,
            'final_quarter': self.quarter, 'final_clock_seconds': self.clock,
            'complete_game': bool(complete and blocker is None and not guarded and not unsupported),
            'scope_out': scope_out,
            'unmodelled_transitions': guarded,
            'two_minute_warnings': two_minute_warnings(self.drives, self.events),
            'valid_full_game': valid_candidate,
            'unsupported_rules': unsupported,
            'rule_capability_limitations': list(UNSUPPORTED_RULES),
            'guards': {r: dict(GUARDS[r]) for r in UNSUPPORTED_RULES},
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
        if self.blocked_attempt is not None:
            rec['blocked_attempt'] = self.blocked_attempt
        paired_random_streams = getattr(self, 'paired_random_streams', None)
        if paired_random_streams is not None:
            rec['paired_random_streams'] = paired_random_streams.manifest()
        return rec


def _stamp_scores(plays, before, after):
    """Every state of the drive carries the score before it. Only the last play's state_after takes the score after it."""
    for i, play in enumerate(plays):
        last = i == len(plays) - 1
        for side, score in (('state_before', before), ('state_after', after if last else before)):
            play[side]['home_score'] = score[0]
            play[side]['away_score'] = score[1]


TWO_MINUTE_MARK = 120
LATE_QUARTERS = (2, 4)
def two_minute_warnings(drives, kickoffs):
    """Each two-minute warning, at the clock value left by its down, from plays and kickoffs."""
    found = []
    for event in kickoffs:
        if event.get('two_minute_warning'):
            found.append({'source': 'kickoff', 'quarter': event['quarter'], 'clock_seconds': event['clock_after']})
    for d in drives:
        for p in d['plays']:
            if p['outcome'].get('two_minute_warning'):
                found.append({'source': 'play', 'drive_index': d['index'], 'sequence': p['sequence'],
                              'quarter': p['state_before']['quarter'], 'clock_seconds': p['state_after']['clock_seconds']})
    return found


def unmodelled_transitions(drives, kickoffs):
    """Transitions whose legal state change is still missing, derived independently from sampled events."""
    found = []
    for d in drives:
        if d['terminal'] == 'field_goal_attempt' and d.get('field_goal_made') is False and not d.get('observed_overtime_drive'):
            result = d['plays'][-1]['outcome'].get('field_goal_return')
            if not isinstance(result, dict) or result.get('status') not in (
                    'sampled_historical_next_drive_spot', 'period_expired'):
                found.append({'kind': 'missed_field_goal_return', 'drive_index': d['index']})
        for p in d['plays']:
            if p['outcome'].get('penalty'):
                found.append({'kind': 'penalty', 'drive_index': d['index'], 'sequence': p['sequence']})
            if p['participants'].get('timeout') and not p['participants'].get('timeout_applied'):
                found.append({'kind': 'timeout', 'drive_index': d['index'], 'sequence': p['sequence']})
    return found


UNMODELLED_GUARD = {'penalty': 'penalties', 'timeout': 'timeouts',
                    'missed_field_goal_return': 'missed_field_goal_return'}
KICKOFF_KINDS = ('half_start', 'post_score', 'post_field_goal', 'safety_free_kick', 'overtime_start')


def guard_reasons(guarded):
    """One scope reason per unmodelled kind that occurs, each naming the guard that scopes it out."""
    reasons = []
    for kind in sorted({t['kind'] for t in guarded}):
        guard = UNMODELLED_GUARD[kind]
        reasons.append({'reason': f'unmodelled transition: {kind}', 'detail': f"guard {guard}: {GUARDS[guard]['guard']}"})
    return reasons


def scope_out_reasons(blocker, complete):
    """Why a seed is not a complete game. Scoped out, not guessed: each reason is named and carried in the record."""
    reasons = []
    if blocker == 'penalty_not_modelled':
        reasons.append({'reason': 'penalty', 'detail': 'a penalty transition is not modelled; the game is blocked, not completed'})
    elif blocker == 'overtime_not_modelled':
        reasons.append({'reason': 'overtime', 'detail': 'tied after regulation with no observed overtime table; overtime is '
                                                        'not played, so the tied game is not complete'})
    elif blocker and blocker.startswith('thin_kick_cell'):
        reasons.append({'reason': 'rare kick outcome', 'detail': f'{blocker}: fewer published attempts than '
                                                                  f'MIN_KICK_N in that cell'})
    elif blocker and blocker.startswith('thin pool cell'):
        reasons.append({'reason': 'thin E1 pool cell', 'detail': blocker})
    elif blocker == 'drive_limit':
        reasons.append({'reason': 'drive limit', 'detail': 'the game ran past max_drives'})
    elif blocker == 'safety_free_kick_not_modelled':
        reasons.append({'reason': 'safety free kick', 'detail': 'no separate observed safety-free-kick outcome table is available; '
                                                                'the game is blocked before an ordinary kickoff outcome is sampled'})
    elif blocker and blocker.startswith('blocked_kick'):
        reasons.append({'reason': 'blocked-kick transition unresolved',
                        'detail': f'{blocker}: the sampled blocked-kick record is not classifiable, so the game is blocked'})
    elif blocker:
        reasons.append({'reason': 'other', 'detail': blocker})
    return reasons


def active_unsupported_rules(guarded, blocker):
    """Return rule gaps exercised by this record; untaken paths remain capability limitations."""
    active = {UNMODELLED_GUARD[item['kind']] for item in guarded}
    if blocker == 'overtime_not_modelled':
        active.add('overtime')
    if blocker == 'safety_free_kick_not_modelled':
        active.add('safety_free_kick')
    if blocker == 'penalty_not_modelled':
        active.add('penalties')
    if blocker and blocker.startswith('blocked_kick'):
        active.add('blocked_kicks')
    return sorted(active)


def play_game(seed, ref, winner_choice=None, max_drives=80, winner=None, pregame_snapshot=None,
              paired_randomness=False):
    """Play one game under the normal-game policy. Returns a record; it never raises for a branch.

    `ref` is the observed Reference (e2_reference.load). It is required, so a game is never played with a silent
    default. The toss winner (team 'A' or 'B') and the winner's choice (receive or defer) are both sampled from the seed,
    unless a caller fixes them for a test.
    """
    snapshot_digest = pregame_snapshot['snapshot_sha256'] if pregame_snapshot else ''
    if paired_randomness and not snapshot_digest:
        raise ValueError('paired random streams require a frozen pregame snapshot')
    material = f'{seed}:{snapshot_digest}'.encode()
    model_seed = int.from_bytes(hashlib.sha256(material).digest()[:8], 'big')
    rng = random.Random(model_seed)
    streams = PairedRandomStreams(model_seed, snapshot_digest) if paired_randomness else None
    toss_rng = streams.rng('regulation_coin_toss') if streams else rng
    choice_rng = streams.rng('regulation_first_choice') if streams else rng
    toss_winner = winner or toss_rng.choice(['A', 'B'])
    toss_loser = other(toss_winner, ('A', 'B'))
    choice = winner_choice or choice_rng.choice(['receive', 'defer'])
    ledger = CoinTossLedger(toss_winner, toss_loser, choice)
    validate_half_start(ledger.half_start_kickoffs())
    return _Game(seed, ref, ledger, rng, pregame_snapshot, model_seed, streams).run(max_drives).record()


def _validate_game_impl(record):
    """Fail closed on the ledger, clock and points invariants of one record. Returns the list of checks that passed.
    """
    checks = []
    for d in record.get('drives', []):
        for p in d['plays']:
            if p['state_before']['clock_seconds'] < 0 or p['state_after']['clock_seconds'] < 0:
                raise AssertionError(f"a negative game clock in drive {d['index']} play {p['sequence']}: nothing may clamp it")
            transition = p['outcome'].get('clock_transition')
            if transition is None and not record.get('valid_full_game'):
                continue  # older research records predate explicit clock-transition annotations
            if not isinstance(transition, dict) or transition.get('clock_interval') != 'observed_snap_to_next_snap':
                raise AssertionError(f"drive {d['index']} play {p['sequence']} has no explicit clock transition")
            if transition.get('runoff_seconds') != p['outcome'].get('clock_runoff_seconds'):
                raise AssertionError(f"drive {d['index']} play {p['sequence']} clock transition disagrees with its runoff")
            if p['state_before'].get('clock_status') != 'running_at_snap':
                raise AssertionError(f"drive {d['index']} play {p['sequence']} does not start with the game clock running")
            expected_after = ('period_ended' if transition.get('restart_trigger') == 'period_restart'
                              else 'running_at_next_snap')
            if p['state_after'].get('clock_status') != expected_after:
                raise AssertionError(f"drive {d['index']} play {p['sequence']} has an invalid post-play clock status")
            if transition.get('restart_trigger') != 'continuous' and transition.get('restart_clock_seconds') != p['state_after']['clock_seconds']:
                raise AssertionError(f"drive {d['index']} play {p['sequence']} clock restart spot disagrees with state_after")
    # Scope refusals first: a record may not call a blocked, tied or guarded game complete, whatever its other fields say.
    if record.get('blocker') is not None and (record.get('complete_regulation') or record.get('complete_game')):
        raise AssertionError(f"a blocked record ({record['blocker']}) is never described as a complete game")
    if record.get('unmodelled_transitions') and (record.get('complete_game') or record.get('status') == 'complete_regulation'):
        kinds = sorted({t['kind'] for t in record['unmodelled_transitions']})
        raise AssertionError(f'a guarded game is never described as a complete game; it contains {kinds}')
    for index, drive in enumerate(record.get('drives', [])):
        if (drive.get('terminal') != 'field_goal_attempt' or drive.get('field_goal_made') is not False
                or drive.get('observed_overtime_drive')):  # an observed overtime miss carries its observed next start
            continue
        play = drive['plays'][-1]
        result = play['outcome'].get('field_goal_return')
        if result is None:
            if record.get('valid_full_game'):
                raise AssertionError(f"missed field goal in drive {drive['index']} has no receiving-spot transition")
            continue
        snap = play['state_before']['yardline_100']
        kick_spot = min(99, snap + HOLDER_OFFSET)
        baseline = missed_field_goal_spot(kick_spot)
        if result.get('baseline_yardline_100') != baseline:
            raise AssertionError(f"missed field goal in drive {drive['index']} has the wrong no-return baseline")
        if result.get('status') == 'period_expired':
            if (drive['end_clock'] != 0 or drive['end_quarter'] not in (2, 4)
                    or result.get('receiving_start_yardline_100') is not None):
                raise AssertionError(f"missed field goal in drive {drive['index']} has an invalid period-expiry transition")
            continue
        spot = result.get('receiving_start_yardline_100')
        adjustment = result.get('spot_adjustment_yards')
        source = result.get('source')
        if (result.get('status') != 'sampled_historical_next_drive_spot'
                or not isinstance(spot, int) or not 1 <= spot <= 99
                or not isinstance(adjustment, int) or spot != baseline + adjustment
                or not isinstance(source, dict) or not source.get('game_id')
                or not isinstance(source.get('play_id'), int) or not isinstance(source.get('next_play_id'), int)):
            raise AssertionError(f"missed field goal in drive {drive['index']} has an invalid sampled spot")
        if index + 1 < len(record['drives']) and not (
                drive['end_clock'] == 0 and drive['end_quarter'] in (2, 4)):
            next_drive = record['drives'][index + 1]
            expected_offense = play['state_after']['defense_team']
            got_spot = next_drive['plays'][0]['state_before']['yardline_100']
            if next_drive['offense_team'] != expected_offense or got_spot != spot:
                raise AssertionError(f"missed field goal in drive {drive['index']} disagrees with the next possession")
    snapshot = record.get('pregame_snapshot') or {}
    observed_reference = (snapshot.get('model_reference') or {}).get('observed_reference', {})
    pinned_blocked_source = observed_reference.get('blocked_kick_source_sha256')
    supported_blocked_statuses = set(reducer.BLOCKED_KICK_STATUSES)
    for drive in record.get('drives', []):
        for play in drive['plays']:
            event, outcome = play['event_type'], play['outcome']
            if outcome.get('field_goal_attempt'):
                before = play.get('state_before') or {}
                feasibility = fg_feasibility.evaluate(before.get('yardline_100'))
                if not feasibility['eligible']:
                    raise AssertionError(
                        f"drive {drive['index']} play {play['sequence']} attempts a field goal beyond the "
                        f"historical feasibility ceiling ({feasibility['kick_distance_yards']} yards)")
                recorded_feasibility = outcome.get('field_goal_feasibility')
                source = outcome.get('field_goal_result_source')
                if record.get('valid_full_game') and recorded_feasibility != feasibility:
                    raise AssertionError(
                        f"drive {drive['index']} play {play['sequence']} lacks current-state field-goal feasibility evidence")
                if record.get('valid_full_game') and not isinstance(source, dict):
                    raise AssertionError(
                        f"drive {drive['index']} play {play['sequence']} lacks distance-aware field-goal result evidence")
                if source is not None and not _field_goal_source_is_current(source, feasibility):
                    raise AssertionError(
                        f"drive {drive['index']} play {play['sequence']} field-goal result uses stale distance or source data")
            blocked = outcome.get('blocked_kick')
            if event not in ('blocked_punt', 'blocked_field_goal'):
                if blocked or outcome.get('field_goal_result') == 'blocked':
                    raise AssertionError(f"drive {drive['index']} play {play['sequence']} has a blocked result without a blocked event")
                continue
            kick_type = 'punt' if event == 'blocked_punt' else 'field_goal'
            if not isinstance(blocked, dict) or blocked.get('kick_type') != kick_type:
                raise AssertionError(f"drive {drive['index']} play {play['sequence']} has no matching blocked-kick outcome")
            if blocked.get('classification_status') not in supported_blocked_statuses:
                raise AssertionError(f"drive {drive['index']} play {play['sequence']} has an unresolved blocked-kick outcome")
            if (not isinstance(blocked.get('source_sha256'), str) or len(blocked['source_sha256']) != 64
                    or not blocked.get('source_file') or not blocked.get('game_id')
                    or not isinstance(blocked.get('play_id'), int)):
                raise AssertionError(f"drive {drive['index']} play {play['sequence']} lacks blocked-kick provenance")
            if (pinned_blocked_source
                    and blocked.get('reference_fixture_sha256') != pinned_blocked_source):
                raise AssertionError(f"drive {drive['index']} play {play['sequence']} uses an unpinned blocked-kick fixture")
            pinned_inputs = observed_reference.get('blocked_kick_input_source_sha256') or {}
            if pinned_inputs and pinned_inputs.get(blocked['source_file']) != blocked['source_sha256']:
                raise AssertionError(f"drive {drive['index']} play {play['sequence']} uses an unpinned blocked-kick input file")
            if kick_type == 'field_goal':
                if not outcome.get('field_goal_attempt') or outcome.get('field_goal_result') != 'blocked':
                    raise AssertionError(f"drive {drive['index']} play {play['sequence']} does not record its blocked field-goal attempt")
            elif not outcome.get('punt_attempt'):
                raise AssertionError(f"drive {drive['index']} play {play['sequence']} does not record its blocked punt attempt")
    checks.append('blocked-kick event types, attempts, classifications and source provenance')
    for k in record.get('kickoffs', []):
        if k['kind'] == 'safety_free_kick' and k.get('source', {}).get('pool') != SAFETY_KICK_POOL:
            raise AssertionError('safety free kick requires a separate observed safety-kick outcome table')
        if k['kind'] not in KICKOFF_KINDS:
            raise AssertionError(f"kickoff kind outside the engine's vocabulary: {k['kind']!r} (onside kicks are not modelled)")
        transition = k.get('clock_transition')
        if transition is None and not record.get('valid_full_game'):
            continue  # older research records predate explicit free-kick clock annotations
        if (not isinstance(transition, dict) or transition.get('clock_starts_on') != 'legal_touch'
                or transition.get('clock_interval') != 'free_kick_to_next_snap'
                or transition.get('runoff_seconds') != k['runoff_seconds']
                or transition.get('restart_clock_seconds') != k['clock_after']):
            raise AssertionError(f"{k['kind']} does not record its free-kick clock transition")
    if record.get('complete_regulation') and record['points']['A'] == record['points']['B'] and not record.get('overtime'):
        raise AssertionError('a tied regulation game is not a complete game without its overtime period')
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
    elif record['final_quarter'] >= 3 and (record['complete_regulation'] or record.get('regulation_end_reached')):
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
                if t is None and d.get('try_source') == 'not_attempted_game_ends':
                    # Rule 16: a touchdown that decides the game is the last scoring play, so no try is attempted.
                    if not (d is record['drives'][-1] and record['status'] == 'complete_overtime' and p['points'] == TD_POINTS):
                        raise AssertionError(f'a touchdown with no try must decide the overtime game: {d["index"]}')
                else:
                    if t is None or t['kind'] not in TRY_POINTS:
                        raise AssertionError(f'touchdown drive without a recorded try: {d["index"]}')
                    if p['points'] != TD_POINTS + (TRY_POINTS[t['kind']] if t['made'] else 0):
                        raise AssertionError(f'touchdown points disagree with the try: {d["index"]}')
                    field = TRY_PUBLISHER_FIELD[t['kind']]
                    if field not in t or t[field] != TRY_PUBLISHER_VALUE[t['kind']][t['made']] or 'success' in t:
                        raise AssertionError(f'try lacks its publisher result field {field}, or carries an EPA-style success '
                                             f'flag: {d["index"]}')
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
    # Continuity: the timeout counts carry from one play to the next, across drives and kickoffs, except at the halftime and
    # overtime resets;
    # the clock carries from one play to the next within a drive. A broken chain is refused, not repaired.
    prev = None
    for d in record['drives']:
        for i, p in enumerate(d['plays']):
            if prev is not None:
                period_reset = (prev['state_after']['quarter'], p['state_before']['quarter']) in ((2, 3), (4, 5))
                for key in ('home_timeouts', 'away_timeouts'):
                    if not period_reset and prev['state_after'][key] != p['state_before'][key]:
                        raise AssertionError(f"timeout count breaks at drive {d['index']} play {p['sequence']}: {key} "
                                             f"{prev['state_after'][key]} then {p['state_before'][key]}")
                if i > 0 and prev['state_after']['clock_seconds'] != p['state_before']['clock_seconds']:
                    raise AssertionError(f"clock breaks inside drive {d['index']} at play {p['sequence']}")
            prev = p
    for d in record['drives']:
        for p in d['plays']:
            stop = p['outcome'].get('timeout_stop')
            if stop is None:
                continue
            want_before = {'home': p['state_before']['home_timeouts'], 'away': p['state_before']['away_timeouts']}
            want_after = {'home': p['state_after']['home_timeouts'], 'away': p['state_after']['away_timeouts']}
            if stop['counts_before'] != want_before or stop['counts_after'] != want_after:
                raise AssertionError(f"timeout stop at drive {d['index']} play {p['sequence']} disagrees with its states")
            if stop['applied']:
                side = {'A': 'home', 'B': 'away'}[stop['called_by']]
                if want_before[side] - 1 != want_after[side]:
                    raise AssertionError(f"applied timeout at drive {d['index']} play {p['sequence']} does not drop its side by one")
    checks.append('timeout counts carry across plays and the halftime reset; clocks carry within a drive')
    checks.append('each explicit timeout stop agrees with the counts on its play')
    for d in record.get('drives', []):
        for p in d['plays']:
            before, after = p['state_before'], p['state_after']
            crossed = (before['quarter'] in LATE_QUARTERS and after['quarter'] == before['quarter']
                       and before['clock_seconds'] > TWO_MINUTE_MARK >= after['clock_seconds'] > 0)
            marked = bool(p['outcome'].get('two_minute_warning'))
            has_stop = any(item.get('kind') == 'automatic_two_minute_warning'
                           for item in p['outcome'].get('clock_transition', {}).get('stoppages', []))
            if crossed != marked or marked != has_stop:
                raise AssertionError(f"two-minute warning clock transition disagrees at drive {d['index']} play {p['sequence']}")
    for i, kick in enumerate(record.get('kickoffs', [])):
        after = kick['clock_after']
        crossed = (kick['quarter'] in LATE_QUARTERS and not kick['clock_expired_during_kickoff']
                   and kick['clock_before'] > TWO_MINUTE_MARK >= after > 0)
        marked = bool(kick.get('two_minute_warning'))
        has_stop = any(item.get('kind') == 'automatic_two_minute_warning'
                       for item in kick.get('clock_transition', {}).get('stoppages', []))
        if crossed != marked or marked != has_stop:
            raise AssertionError(f'two-minute warning clock transition disagrees at kickoff {i}')
    checks.append('two-minute warning events independently match clock crossings and restart transitions')
    expected_unmodelled = unmodelled_transitions(record.get('drives', []), record.get('kickoffs', []))
    if record.get('unmodelled_transitions') != expected_unmodelled:
        raise AssertionError('unmodelled transition list disagrees with the plays and kickoff events')
    checks.append('unmodelled transitions match the play and kickoff events')
    expected_unsupported = active_unsupported_rules(expected_unmodelled, record.get('blocker'))
    if record.get('unsupported_rules') != expected_unsupported:
        raise AssertionError('active unsupported rules disagree with the game events')
    checks.append('active unsupported rules match the game events')
    if record['valid_full_game']:
        if (record.get('mode') != 'pregame_full_game' or not record['complete_regulation'] or record['blocker'] is not None
                or (record['tied'] and not record.get('overtime')) or record['unsupported_rules']):
            raise AssertionError(
                'valid_full_game requires pregame_full_game mode, complete regulation, no blocker, a tie only after its '
                'overtime period, and no unsupported rule')
    checks.append('valid_full_game only when pregame_full_game, complete, unblocked, any tie played out in overtime, and no unsupported rule')
    return checks


def validate_game(record):
    """Run full-game checks and preserve a structured evidence envelope on every hard failure."""
    try:
        return _validate_game_impl(record)
    except football_assertions.FootballAssertionError:
        raise
    except Exception as exc:
        snapshot = (record or {}).get('pregame_snapshot') or {}
        game_id = ((snapshot.get('schedule') or {}).get('game_id')
                   or (record or {}).get('game_id') or 'unknown')
        evidence = football_assertions.failure_envelope(
            exc, seed=(record or {}).get('seed', 'unknown'), game_id=game_id, record=record)
        context = {field: evidence[field] for field in (
            'game_id', 'seed', 'play_index', 'state_before', 'decision', 'outcome', 'state_after',
            'source_artifact_hashes', 'violated_assertion')}
        if context['decision'] == 'unavailable':
            context['decision'] = None
        raise football_assertions.FootballAssertionError(
            evidence['failure_class'], str(exc), context=context) from exc
