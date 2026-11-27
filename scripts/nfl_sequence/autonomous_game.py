"""Autonomous Gridiron execution through the SLC regulation-game lifecycle.

Historical team playbooks supply pregame aggregate tendencies only. Executable
calls and player assignments are authored in Gridiron; live results are never
looked up in historical play outcomes.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, replace
from pathlib import Path

import ceg_contract
import ceg_contract_v3
import event_expansion_rules
from event_expansion import EventExpansionSwitches
import game_state
import gridiron_bridge
import participation_field
import pregame_snapshot
import roster_preflight
import snap_clock
import snap_update
import shared_participation
import v1_complete_roster


SPECIAL_TEAMS_RATING_KEYS = frozenset({
    'SPD', 'ACC', 'AGI', 'STR', 'AWR', 'PUR', 'TAK', 'BSH', 'RBK', 'IBL',
    'CTH', 'CAR', 'BCV', 'ELU', 'TRK', 'PRC', 'KPW', 'KAC',
})
GRIDIRON_FUMBLE_RETURN_RAW_TOLERANCE_YARDS = 0.001


def _gridiron_yardline_round(value, label):
    """Match JavaScript Math.round for nonnegative, continuous field spots."""
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= 100):
        raise ValueError(f'gridiron_{label}_spot_invalid')
    return math.floor(value + 0.5)


def _validate_gridiron_fumble_return(fumble, direction):
    """Validate continuous geometry and whole-yard stats as separate facts."""
    if direction not in (-1, 1):
        raise ValueError('gridiron_fumble_return_direction_invalid')
    side = fumble.get('recovery_side')
    if side not in ('O', 'D'):
        raise ValueError('gridiron_fumble_recovery_team_invalid')
    recovery = fumble.get('recovery_spot') or {}
    dead = fumble.get('dead_ball_spot') or {}
    recovery_x = recovery.get('x')
    dead_x = dead.get('x')
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or not 0 <= value <= 100
           for value in (recovery_x, dead_x)):
        raise ValueError('gridiron_fumble_return_endpoint_missing_or_invalid')
    recovery_y = _gridiron_yardline_round(
        100 - recovery_x if direction == 1 else recovery_x, 'recovery')
    dead_y = _gridiron_yardline_round(100 - dead_x if direction == 1 else dead_x, 'dead_ball')
    advance_sign = -1 if side == 'O' else 1
    expected_stat_yards = (dead_y - recovery_y) * advance_sign
    stat_yards = fumble.get('return_yards')
    if type(stat_yards) is not int:
        raise ValueError('gridiron_fumble_statistical_return_yards_missing_or_invalid')
    if stat_yards != expected_stat_yards:
        raise ValueError('gridiron_fumble_statistical_return_yards_disagree_with_rounded_spots')
    displacement = fumble.get('return_displacement_yards')
    if (isinstance(displacement, bool) or not isinstance(displacement, (int, float))
            or not math.isfinite(displacement)):
        raise ValueError('gridiron_fumble_return_displacement_missing_or_invalid')
    expected_displacement = (dead_x - recovery_x) * (direction if side == 'O' else -direction)
    if abs(displacement - expected_displacement) > GRIDIRON_FUMBLE_RETURN_RAW_TOLERANCE_YARDS:
        raise ValueError('gridiron_fumble_return_yards_disagree_with_raw_endpoints')
    return {'recovery_yardline_100': recovery_y, 'dead_ball_yardline_100': dead_y,
            'return_yards': stat_yards, 'return_displacement_yards': displacement}


GRIDIRON_SCRIMMAGE_DEAD_BALL_REASONS = frozenset({
    'tackle', 'out_of_bounds', 'incomplete', 'sack', 'touchdown', 'safety',
})
GRIDIRON_SCRIMMAGE_POSSESSION_EVENTS = frozenset({
    'interception', 'fumble', 'fumble_recovery',
})
GRIDIRON_SPECIAL_TEAMS_EMITTED_RESULTS = {
    'punt': frozenset({'return', 'muff', 'touchback', 'fair_catch', 'downed', 'out_of_bounds'}),
    'field_goal': frozenset({'made', 'missed', 'blocked'}),
    'kickoff': frozenset({'return', 'muff', 'touchback', 'downed', 'out_of_bounds'}),
}
# Each listed result has an explicit V3 conversion branch below. Unlisted
# executor output is a named blocker; it is never rewritten into a nearby case.
GRIDIRON_SPECIAL_TEAMS_RESULT_HANDLERS = {
    'punt': {
        'return': 'return_facts', 'muff': 'muff_roles_and_recovery',
        'touchback': 'dead_ball_and_receiving_restart', 'fair_catch': 'fair_catch_signal',
        'downed': 'dead_ball_spot', 'out_of_bounds': 'dead_ball_spot',
    },
    'field_goal': {
        'made': 'field_goal_scoring', 'missed': 'missed_kick_restart',
        'blocked': 'blocked_field_goal_recovery',
    },
    'kickoff': {
        'return': 'return_facts', 'muff': 'muff_roles_and_recovery',
        'touchback': 'dead_ball_and_receiving_restart', 'fair_catch': 'fair_catch_signal',
        'downed': 'dead_ball_spot', 'out_of_bounds': 'kickoff_oob_choice_and_restart',
    },
}


def playbook_profile_path(playbook_dir, team, season=2025):
    """Resolve schedule/PBP team codes to the nflverse playbook filename vocabulary."""
    profile_team = gridiron_bridge.nfl_team_codes.to_nflverse_team_code(team)
    return str(Path(playbook_dir) / f'{profile_team}-{season}.json')


def _clamp(value, low, high):
    return min(high, max(low, value))


def _sigmoid(value):
    return 1 / (1 + math.exp(-_clamp(value, -30, 30)))


def classify_live_scrimmage_result(call, result):
    """Separate snap action, possession history, score facts and dead-ball cause."""
    outcome = result.get('result') or {}
    events = result.get('events') or []
    action = (call.get('offense') or {}).get('call') or {}
    family = action.get('family')
    reason = outcome.get('event')
    interceptions = [event for event in events if event.get('type') == 'interception']
    throws = [event for event in events if event.get('type') == 'throw']
    catches = [event for event in events if event.get('type') == 'catch']
    sackers = (result.get('participants') or {}).get('sackers') or []
    fumble = outcome.get('fumble')
    if reason not in GRIDIRON_SCRIMMAGE_DEAD_BALL_REASONS:
        raise ValueError('gridiron_dead_ball_reason_unsupported:' + str(reason))

    # This is the offensive action that began at the snap. It remains distinct
    # from the later carrier, which may be a defender or a fumble recoverer.
    if family not in ('run', 'pass'):
        raise ValueError('gridiron_original_offensive_action_unsupported:' + str(family))
    if interceptions:
        snap_event = 'interception'
    elif reason == 'incomplete':
        snap_event = 'pass_incomplete'
    elif reason == 'sack' or sackers:
        snap_event = 'sack'
    elif family == 'run':
        snap_event = 'run'
    elif catches:
        snap_event = 'pass_complete'
    elif (not throws and outcome.get('carrier_id')
          == ((call.get('offense') or {}).get('lineup') or {}).get('QB')):
        snap_event = 'run'  # a live QB scramble is a run even when the call began as a pass
    else:
        raise ValueError('gridiron_action_and_live_events_do_not_classify:' + str(reason))

    possession_history = []
    for event in events:
        if event.get('type') not in GRIDIRON_SCRIMMAGE_POSSESSION_EVENTS:
            continue
        possession_history.append({key: event.get(key) for key in (
            'type', 'player_id', 'fumbler_id', 'recoverer_id', 'team', 'recovery_team',
            'recovery_spot', 'at', 'spot') if key in event})
    if fumble is not None:
        fumble_event = next((item for item in possession_history if item['type'] == 'fumble'), None)
        if fumble_event is None:
            fumble_event = {'type': 'fumble'}
            possession_history.append(fumble_event)
        recovery_event = next((item for item in possession_history if item['type'] == 'fumble_recovery'), None)
        if recovery_event is None:
            recovery_event = {'type': 'fumble_recovery'}
            possession_history.append(recovery_event)
        for key in ('fumbler_id', 'fumble_spot'):
            if key in fumble:
                fumble_event.setdefault(key, fumble[key])
        for key in ('fumbler_id', 'recoverer_id', 'recovery_team', 'recovery_spot'):
            if key in fumble:
                recovery_event.setdefault(key, fumble[key])

    scoring_events = [event for event in events if event.get('type') in ('touchdown', 'safety')]
    if len(scoring_events) > 1:
        raise ValueError('gridiron_multiple_terminal_scoring_events')
    score_kind = ('touchdown' if outcome.get('is_touchdown') else
                  'safety' if reason == 'safety' else None)
    if score_kind is not None and not scoring_events:
        raise ValueError('gridiron_terminal_scoring_fact_missing')
    if scoring_events and score_kind != scoring_events[0].get('type'):
        raise ValueError('gridiron_scoring_event_disagrees_with_terminal_facts')
    scoring_side = scoring_events[0].get('team') if scoring_events else None
    if scoring_side not in (None, 'O', 'D'):
        raise ValueError('gridiron_scoring_team_side_invalid:' + str(scoring_side))
    scoring = ({'kind': score_kind,
                'team': scoring_side}
               if score_kind else None)
    final_possession = outcome.get('possession_team')
    if fumble is not None and fumble.get('recovery_team') is not None:
        if final_possession is not None and final_possession != fumble.get('recovery_team'):
            raise ValueError('gridiron_final_possession_disagrees_with_fumble_recovery')
        final_possession = fumble.get('recovery_team')
    return {
        'original_offensive_action': {'family': family, 'concept': action.get('concept')},
        'snap_event': snap_event,
        'possession_history': possession_history,
        'final_possession_team': final_possession,
        'scoring': scoring,
        'dead_ball_reason': reason,
    }


class AutonomousTimeoutDecisions:
    """Timeout calls from live clock, score and possession, with a separate quality rating."""

    def __init__(self, execution, remaining, points):
        self.execution = execution
        self.left = dict(remaining)
        self.points = dict(points)
        self.clock = execution.snap_clock

    def decide(self, _rng, before, after, terminal, event, row):
        if (after is not None and after.get('offense') != before.get('offense')):
            return None, {'caller_team': None,
                          'decision': 'possession_change_already_stops_clock'}
        if (after is None or after.get('down') is None or terminal in ('touchdown', 'safety', 'field_goal_attempt', 'punt')
                or event == 'pass_incomplete' or row.get('out_of_bounds')):
            return None, {'caller_team': None, 'decision': 'no_live_clock_value'}
        quarter, clock = before['quarter'], before['clock']
        if quarter not in (2, 4) or not 0 < clock <= 120:
            return None, {'caller_team': None, 'decision': 'outside_late_half_window'}
        offense, defense = after['offense'], after['defense']
        trailing = [team for team in (offense, defense)
                    if self.points.get(team, 0) < self.points.get(defense if team == offense else offense, 0)]
        eligible = [team for team in trailing if self.left.get(team, 0) > 0]
        if not eligible or row.get('clock_stopped'):
            return None, {'caller_team': None, 'decision': 'no_trailing_team_timeout_value'}
        caller = max(eligible, key=lambda team: (self.execution.coaching_quality(team, 'timeout'), team))
        quality = self.execution.coaching_quality(caller, 'timeout')
        urgency = _clamp((121 - clock) / 120, 0, 1)
        probability = quality / 100 * urgency
        rng = random.Random(self.execution._decision_seed(row['play_id'], 'timeout'))
        called = rng.random() < probability
        if called:
            self.left[caller] -= 1
        return (caller if called else None), {
            'caller_team': caller if called else None,
            'decision': 'preserve_clock_for_trailing_team',
            'clock_seconds': clock,
            'score_margin_for_caller': self.points.get(caller, 0) - self.points.get(
                defense if caller == offense else offense, 0),
            'timeouts_before': self.left.get(caller, 0) + int(called),
            'quality_rating': quality,
            'call_probability': probability,
            'called': called,
            'information_available': ['current_score', 'current_clock', 'current_possession', 'timeouts_remaining'],
        }

    def runoff(self, _rng, _cell, _event, _row, runoff, called, _late):
        return runoff

    def out_of_bounds(self, row):
        return bool(row.get('out_of_bounds'))

    def margin(self, team):
        other = next((key for key in self.points if key != team), None)
        return self.points.get(team, 0) - (self.points.get(other, 0) if other else 0)


class AutonomousGameExecution:
    """The SLC callback provider backed by one persistent Gridiron process."""

    def __init__(self, *, seed, snapshot_path, participation_path, participation_sha256,
                 playbook_dir, playbook_manifest, engine_root, ratings_path=None,
                 coaching_profiles=None, participation_snap_counts=None, participation_entry_current=True):
        self.seed = int(seed)
        self.snapshot_path = str(snapshot_path)
        self.snapshot = pregame_snapshot.load_frozen_snapshot(self.snapshot_path)
        self.teams = (self.snapshot['schedule']['home_team'], self.snapshot['schedule']['away_team'])
        self.team_by_side = {'A': self.teams[0], 'B': self.teams[1]}
        self.profile_paths = {team: playbook_profile_path(playbook_dir, team) for team in self.teams}
        self.playbook_manifest = str(playbook_manifest)
        self.participation_sha256 = participation_sha256
        self.field = participation_field.Field.load(participation_path, participation_sha256)
        snaps = snap_update.SnapCounts.load(*participation_snap_counts) if participation_snap_counts else None
        self.participation = shared_participation.Policy(self.field, self.snapshot, snaps, participation_entry_current)
        self.engine_root = str(engine_root)
        self.ratings_path = ratings_path
        self.coaching_profiles = coaching_profiles or {}
        self.snap_clock = snap_clock.SnapClock.load()
        self.contract_v3_commit = gridiron_bridge._check_ceg_contract_v3()
        self.session = gridiron_bridge.GridironSession(self.engine_root, player_evaluation_mode='shared_snapshot')
        self.event_switches = EventExpansionSwitches()
        self.event_manifest_sha256 = hashlib.sha256(
            (f'{self.session.commit}:{gridiron_bridge.PLAYBOOK_MANIFEST_SHA256}:{participation_sha256}:'
             f'{self.snap_clock.sha256}:{shared_participation.VERSION}:'
             f'{snaps.sha256 if snaps else None}:{participation_entry_current}').encode()
        ).hexdigest()
        self.play_index = 0
        self._play_prior_cache = {}
        self.current_score_diff = 0

    def close(self):
        self.session.close()

    def _rating_profile_path(self):
        if self.ratings_path:
            return str(self.ratings_path)
        game_id = self.snapshot.get('schedule', {}).get('game_id')
        if game_id:
            game_profile = Path(self.engine_root) / 'data' / f'ratings-{game_id}.json'
            if game_profile.is_file():
                return str(game_profile)
        return str(Path(self.engine_root) / 'data' / 'ratings.json')

    def coaching_quality(self, team, decision):
        profile = getattr(self, 'coaching_profiles', {}).get(self.team_by_side.get(team, team), {})
        value = profile.get(f'{decision}_quality', 70)
        return int(_clamp(value, 1, 99))

    def timeout_model(self, remaining, points):
        return AutonomousTimeoutDecisions(self, remaining, points)

    def apply_event(self, state, event_record):
        if isinstance(event_record, ceg_contract_v3.GeneratedPlayV3):
            applied = event_expansion_rules.apply_v3_play(
                state, event_record, switches=self.event_switches)
            if applied.scoring_team is not None:
                self.current_team = applied.scoring_team
            return applied
        adapters = {
            'punt': event_expansion_rules.apply_punt_play,
            'field_goal_attempt': event_expansion_rules.apply_field_goal_play,
            'kickoff': event_expansion_rules.apply_kickoff_play,
        }
        adapter = adapters.get(event_record.event)
        applied = (event_expansion_rules.apply_scrimmage_play(
            state, event_record, switches=self.event_switches) if adapter is None else
            adapter(state, event_record, switches=self.event_switches))
        if applied.scoring_team is not None:
            self.current_team = applied.scoring_team
        return applied

    def _decision_seed(self, play_index, purpose):
        material = f'{self.seed}:{play_index}:{purpose}'.encode()
        return int.from_bytes(hashlib.sha256(material).digest()[:8], 'big')

    def _playbook_prior(self, team):
        if team not in self._play_prior_cache:
            path = self.profile_paths[team]
            prior = gridiron_bridge._profile(path, self.playbook_manifest,
                                             int(self.snapshot['schedule']['season']), team)
            self._play_prior_cache[team] = prior
        return self._play_prior_cache[team]

    def _select_fourth_down(self, state, side, play_index):
        """Compare generated go, punt and field-goal expected points before the snap."""
        yl, togo = state['yl'], state['togo']
        prior = self._playbook_prior(self.team_by_side[side])
        q_go = _sigmoid(1.65 - 0.2 * togo)
        def expected_points(yards_to_goal):
            return max(0.0, 5.5 - 0.072 * _clamp(yards_to_goal, 0, 100))

        go_ev = q_go * expected_points(max(1, yl - togo)) - (1 - q_go) * expected_points(100 - yl)
        candidates = {'go': go_ev}
        punt_net = 42.0
        punt_start = int(_clamp(round(100 - yl + punt_net), 1, 99))
        candidates['punt'] = -expected_points(punt_start)
        kick_distance = yl + 17
        if kick_distance <= 65:
            p_make = _sigmoid((62 - kick_distance) * 0.16 + 0.45)
            missed_start = max(80, int(_clamp(round(100 - yl - 7), 1, 99)))
            candidates['field_goal'] = p_make * 3 - (1 - p_make) * expected_points(missed_start)

        quality = self.coaching_quality(side, 'fourth_down')
        # Lower decision quality spreads probability across alternatives; it never changes execution.
        temperature = max(0.08, (100 - quality) / 18)
        weights = {option: math.exp(_clamp((value - max(candidates.values())) / temperature, -40, 0))
                   for option, value in candidates.items()}
        # Team season play calling is a tendency prior, independent of the coach's decision quality.
        if 'go' in weights:
            weights['go'] *= 0.75 + 0.5 * (1 - prior['pass_rate'])
        rng = random.Random(self._decision_seed(play_index, 'fourth_down'))
        choice = rng.choices(list(weights), weights=list(weights.values()), k=1)[0]
        return choice, {'choice': choice, 'candidate_expected_points': candidates,
                        'coaching_quality': quality, 'team_run_pass_tendency': prior['pass_rate'],
                        'decision_temperature': temperature,
                        'information_available': ['down', 'distance', 'field_position', 'score', 'clock']}

    def _choose_family(self, state, side, play_index):
        team = self.team_by_side[side]
        pass_rate = self._playbook_prior(team)['pass_rate']
        # Distance and down shape the decision around the prior; nothing uses a future result.
        if state['down'] == 1:
            pass_rate += 0.02
        elif state['down'] == 3:
            pass_rate += _clamp((state['togo'] - 5) * 0.035, -0.1, 0.25)
        return 'pass' if random.Random(self._decision_seed(play_index, 'play_family')).random() < _clamp(
            pass_rate, 0.05, 0.95) else 'run'

    def event_source(self, state, context):
        self.play_index = int(context['play_index'])
        self.current_score_diff = int(context.get('score_diff', 0))
        side = state['offense']
        decision_note = None
        family = None
        selected = 'scrimmage'
        if state['down'] == 4:
            selected, fourth_down = self._select_fourth_down(state, side, self.play_index)
            decision_note = {'coaching_decision': fourth_down}
        if selected == 'field_goal':
            event, play_type = 'field_goal_attempt', 'field_goal'
        elif selected == 'punt':
            event, play_type = 'punt', 'punt'
        else:
            # The engine currently supports only 11 personnel. Select the actual players before the run/pass draw.
            # Do not pretend other formations have executable assignments.
            prepared = self.participation.prepare(self.team_by_side[side], state,
                                                  self._decision_seed(self.play_index, 'gridiron'), group='11')
            family = selected if selected in ('run', 'pass') else self._choose_family(state, side, self.play_index)
            call_state = {**state, 'offense_direction': context['direction']}
            call, provenance = gridiron_bridge.build_call(
                self.snapshot_path, self.field, self.participation_sha256,
                self.profile_paths, self.playbook_manifest,
                seed=self._decision_seed(self.play_index, 'gridiron'), family=family, state=call_state,
                ratings_path=self._rating_profile_path(), prepared_participation=prepared)
            result, timing = self.session.play(call)
            self.participation.commit(prepared)
            return self._map_scrimmage_result(call, result, timing, provenance, state, context,
                                              decision_note, family)
        play_id = int(context['play_index'])
        row = {'game_id': self.snapshot['schedule']['game_id'], 'play_id': play_id,
               'play_type': play_type,
               'dead_ball_seconds': 0.0, 'clock_stopped': True, 'out_of_bounds': False,
               'decision_note': decision_note,
               'participants': {'attribution': 'autonomous_execution', 'timeout': False,
                                'out_of_bounds': False}}
        # E1 requires a row shell before invoking the live kick executor. This
        # zero-runoff placeholder is never a punt or field-goal outcome.
        return {'event': event, 'row': row, 'clock_runoff_seconds': 0.0, 'spot': None}

    def _map_scrimmage_result(self, call, result, timing, provenance, state, context,
                              decision_note, family):
        outcome = result['result']
        if (not all(isinstance(outcome.get(key), (int, float)) and math.isfinite(outcome[key])
                    for key in ('yards_gained', 'elapsed_seconds'))
                or not isinstance(outcome.get('final_ball_spot'), dict)
                or not isinstance(outcome['final_ball_spot'].get('x_yards'), (int, float))
                or not math.isfinite(outcome['final_ball_spot']['x_yards'])):
            raise ValueError('gridiron_nonfinite_live_result')
        direction = context['direction']
        los_x = call['situation']['yardline_100']
        final_x = outcome['final_ball_spot']['x_yards']
        events = result['events']
        fumble = outcome.get('fumble')
        fumble_geometry = (_validate_gridiron_fumble_return(fumble, direction)
                           if fumble is not None else None)
        classification = classify_live_scrimmage_result(call, result)
        pass_interference = next((item for item in events if item['type'] == 'pass_interference'), None)
        if (pass_interference is None
                and abs(final_x - (los_x + direction * outcome['yards_gained'])) > 0.003):
            raise ValueError('gridiron_final_spot_mismatch')
        thrown = next((item for item in events if item['type'] == 'throw'), None)
        caught = next((item for item in events if item['type'] == 'catch'), None)
        interception = next((item for item in events if item['type'] == 'interception'), None)
        reason = classification['dead_ball_reason']
        if pass_interference is not None:
            if (family != 'pass' or thrown is None
                    or not isinstance(pass_interference.get('spot'), dict)):
                raise ValueError('gridiron_pass_interference_terminal_facts_invalid')
        event = classification['snap_event']
        if outcome['turnover'] and interception is None and not (
                fumble is not None and fumble.get('recovery_side') == 'D'):
            raise ValueError('gridiron_turnover_lacks_possession_change_fact')
        if interception is not None and fumble is not None:
            gain = 0
        elif fumble is not None:
            fumble_x = fumble.get('fumble_spot', {}).get('x')
            if not isinstance(fumble_x, (int, float)) or not math.isfinite(fumble_x):
                raise ValueError('gridiron_fumble_spot_missing')
            gain = math.floor((fumble_x - los_x) * direction)
        elif event == 'interception':
            interception_at = interception.get('at')
            if not isinstance(interception_at, dict) or not isinstance(interception_at.get('x'), (int, float)):
                raise ValueError('gridiron_interception_location_missing')
            catch_x = _clamp(interception_at['x'], 0, 100)
            gain = int(round((catch_x - los_x) * direction))
        elif event in ('run', 'pass_complete', 'sack'):
            if outcome.get('is_touchdown'):
                gain = state['yl']
            elif reason == 'safety':
                gain = state['yl'] - 100
            else:
                gain = math.floor(outcome['yards_gained'])
        else:
            gain = 0
        spot = None
        penalty_decision = (self._decide_pass_interference(call, result, state, direction,
                            pass_interference, context['play_index']) if pass_interference else None)
        event_record = self._ceg_play(call, result, event, gain, state, direction, los_x,
                                      final_x, reason, interception, caught, thrown, pass_interference,
                                      penalty_decision)
        if interception is not None and fumble is not None:
            event_record = self._ceg_play_v3_turnover_chain(event_record, result, interception, direction)
        if event == 'interception':
            receiving_yl = final_x if direction == 1 else 100 - final_x
            spot = int(round(receiving_yl))
        elapsed = max(0.0, float(outcome['elapsed_seconds']))
        live_clock_seconds = max(1, math.ceil(elapsed))
        dead = 0
        yardage_for_slc = (0 if event == 'interception' and event_record.possession is not None
                           and event_record.possession.touchback else gain)
        row = {'game_id': self.snapshot['schedule']['game_id'], 'play_id': int(context['play_index']),
               'play_type': 'run' if event == 'run' else 'pass', 'yards_gained': yardage_for_slc,
               'live_elapsed_seconds': elapsed, 'dead_ball_seconds': dead,
               'clock_stopped': reason in ('out_of_bounds', 'incomplete', 'touchdown', 'safety'),
               'out_of_bounds': reason == 'out_of_bounds',
               'decision_note': decision_note or {'selection': family,
                   'team_playbook_prior': self._playbook_prior(call['offense']['team'])['use'],
                   'concept': call['offense']['call']['concept'],
                   'assignments': 'authored_executable_gridiron_diagram'},
               'participants': self._participants(call, result, event, state)}
        if fumble is not None:
            row['participants'].update({
                'fumbler_id': fumble['fumbler_id'],
                'recoverer_id': fumble['recoverer_id'],
                'returner_id': fumble.get('returner_id') or outcome.get('carrier_id'),
                'fumble_spot_yards_gained': gain,
                'fumble_recovery_team': state['defense'] if fumble['recovery_side'] == 'D' else state['offense'],
                'fumble_return_yards': fumble_geometry['return_yards'],
            })
            if event == 'run':
                row['participants']['rushing_yards'] = gain
            elif event == 'pass_complete':
                row['participants']['passing_yards'] = gain
                row['participants']['receiving_yards'] = gain
        if pass_interference is not None:
            defender_id = pass_interference.get('defender_id')
            defender_side = 'B' if state['offense'] == 'A' else 'A'
            defender = self._actor_row(defender_id, defender_side)
            row['participants'].update({
                'penalty_offender_id': defender_id,
                'penalty_offender_name': defender.get('player_name'),
                'penalty_offender_position': defender.get('pos_abb'),
                'penalty_offender_team': defender.get('team'),
                'penalty_offender_side': 'B' if state['offense'] == 'A' else 'A',
            })
            row['decision_note'] = {**(row.get('decision_note') or {}),
                                    'pass_interference_decision': penalty_decision}
        row['participants']['out_of_bounds'] = reason == 'out_of_bounds'
        if decision_note:
            row['decision_note'] = {**decision_note, 'play_family': family,
                                    'executable_concept': call['offense']['call']['concept']}
        runoff = elapsed + dead
        execution = {'schema_version': result['schema_version'], 'call': call,
                     'result': result, 'provenance': provenance, 'timing': timing,
                     'classification': classification,
                     'ceg_event': asdict(event_record),
                     'viewer': 'gridiron_result.trajectory.frames'}
        return {'event': event, 'row': row, 'clock_runoff_seconds': runoff, 'spot': spot,
                'execution': execution, 'event_record': event_record}

    @staticmethod
    def _ceg_play_v3_turnover_chain(base, result, interception, direction):
        facts = result['result'].get('fumble') or {}
        interceptor_id = (result.get('participants') or {}).get('interceptor') or result['result'].get('interception_id')
        fumbler_id, recoverer_id = facts.get('fumbler_id'), facts.get('recoverer_id')
        recovery_role = {'O': 'offense', 'D': 'defense'}.get(facts.get('recovery_side'))
        post_returner_id = result['result'].get('carrier_id') or recoverer_id
        if (not interceptor_id or not fumbler_id or not recoverer_id or not post_returner_id
                or recovery_role is None):
            raise ValueError('gridiron_interception_return_fumble_roles_incomplete')

        fumble_geometry = _validate_gridiron_fumble_return(facts, direction)

        def yardline(point):
            x = (point or {}).get('x')
            if (isinstance(x, bool) or not isinstance(x, (int, float))
                    or not math.isfinite(x) or not 0 <= x <= 100):
                raise ValueError('gridiron_interception_return_fumble_spot_missing')
            return _gridiron_yardline_round(100 - x if direction == 1 else x, 'turnover_chain')

        interception_y = yardline(interception.get('at'))
        fumble_y = yardline(facts.get('fumble_spot'))
        recovery_y = fumble_geometry['recovery_yardline_100']
        dead_y = fumble_geometry['dead_ball_yardline_100']
        initial_return_yards = fumble_y - interception_y
        post_return_yards = fumble_geometry['return_yards']
        scoring_kind = base.scoring.kind if base.scoring is not None else None
        scoring_team = base.scoring.team if base.scoring is not None else None
        chain = ceg_contract_v3.ScrimmageTurnoverChainV3(
            initial_turnover='interception', initial_possession_team='defense',
            turnover_spot=ceg_contract_v3.FieldSpotV3(interception_y, 'offense'),
            initial_returner=ceg_contract.PlayerRoleV2.named(interceptor_id),
            initial_return_yards=initial_return_yards,
            fumbler=ceg_contract.PlayerRoleV2.named(fumbler_id),
            fumble_spot=ceg_contract_v3.FieldSpotV3(fumble_y, 'offense'),
            recoverer=ceg_contract.PlayerRoleV2.named(recoverer_id),
            recovery_team=recovery_role,
            recovery_spot=ceg_contract_v3.FieldSpotV3(recovery_y, 'offense'),
            post_recovery_returner=ceg_contract.PlayerRoleV2.named(post_returner_id),
            post_recovery_return_yards=post_return_yards,
            dead_ball_spot=ceg_contract_v3.FieldSpotV3(dead_y, 'offense'),
            final_possession_team=recovery_role,
            interceptor=ceg_contract.PlayerRoleV2.named(interceptor_id),
            scoring_kind=scoring_kind, scoring_team=scoring_team)
        values = {name: getattr(base, name) for name in ceg_contract.GeneratedPlayV2.__dataclass_fields__}
        final_possession = ceg_contract.PossessionV2(
            team=recovery_role, how='fumble_recovery',
            turnover_spot_yardline_100=fumble_y,
            recovery_spot_yardline_100=recovery_y,
            dead_ball_yardline_100=dead_y,
            return_yards=post_return_yards,
            returner=ceg_contract.PlayerRoleV2.named(post_returner_id),
            recovered_by=ceg_contract.PlayerRoleV2.named(recoverer_id),
            fumble_spot_yardline_100=fumble_y)
        values.update(contract=ceg_contract_v3.CONTRACT_V3_VERSION,
                      possession=final_possession,
                      players=replace(
                          base.players, returner=ceg_contract.PlayerRoleV2.named(post_returner_id)),
                      turnover_chain=chain)
        return ceg_contract_v3.GeneratedPlayV3(**values)

    def _decide_pass_interference(self, call, result, state, direction, pass_interference, play_index):
        spot_x = pass_interference['spot']['x']
        foul_spot = int(round(100 - spot_x if direction == 1 else spot_x))
        accepted_y = 1 if foul_spot == 0 else foul_spot
        def expected_points(yards_to_goal):
            return max(0.0, 5.5 - 0.072 * _clamp(yards_to_goal, 0, 100))

        accepted_ev = expected_points(accepted_y) + 0.35  # spot foul plus automatic first down
        outcome = result['result']
        if outcome.get('turnover'):
            dead_x = _clamp(outcome['final_ball_spot']['x_yards'], 0, 100)
            dead_spot = int(round(100 - dead_x if direction == 1 else dead_x))
            declined_ev = -6.5 if outcome.get('is_touchdown') else (
                -2.0 if outcome.get('event') == 'safety' else
                -expected_points(100 - dead_spot))
        elif outcome.get('is_touchdown'):
            declined_ev = 6.5
        elif outcome.get('event') == 'safety':
            declined_ev = -2.0
        elif outcome['event'] == 'incomplete':
            if state['down'] == 4:
                declined_ev = -expected_points(100 - state['yl'])
            else:
                declined_ev = expected_points(state['yl']) - 0.18 * state['down']
        else:
            gain = math.floor(outcome['yards_gained'])
            declined_y = max(1, state['yl'] - gain)
            first = gain >= state['togo']
            next_down = 1 if first else state['down'] + 1
            if next_down > 4:
                declined_ev = -expected_points(100 - declined_y)
            else:
                declined_ev = expected_points(declined_y) - 0.18 * next_down
        quality = self.coaching_quality(state['offense'], 'penalty')
        best = 'accepted' if accepted_ev >= declined_ev else 'declined'
        rng = random.Random(self._decision_seed(play_index, 'dpi_acceptance'))
        if rng.random() < quality / 100:
            disposition = best
        else:
            disposition = 'declined' if best == 'accepted' else 'accepted'
        return {'disposition': disposition, 'foul_spot_yardline_100': foul_spot,
                'accepted_expected_value': round(accepted_ev, 3),
                'declined_expected_value': round(declined_ev, 3), 'quality_rating': quality,
                'optimal_disposition': best, 'probability_of_optimal_choice': quality / 100,
                'information_available': ['foul_spot', 'pass_terminal_state', 'resulting_possession',
                                          'return_endpoint', 'down', 'yards_to_go',
                                          'yardline_100', 'penalty_rule']}

    def _ceg_play(self, call, result, event, yards, state, direction, los_x, final_x, reason,
                  interception, caught, thrown, pass_interference=None, penalty_decision=None):
        outcome = result['result']
        live_clock_seconds = max(1, math.ceil(outcome['elapsed_seconds']))
        players = result.get('participants', {})
        offense_players = call['offense']['lineup']
        fumble_info = outcome.get('fumble')
        fumble_geometry = (_validate_gridiron_fumble_return(fumble_info, direction)
                           if fumble_info is not None else None)
        original_carrier = fumble_info.get('fumbler_id') if fumble_info else outcome.get('carrier_id')
        passer_id = None if event == 'run' and original_carrier != offense_players['QB'] else offense_players['QB']
        rusher_id = (fumble_info.get('fumbler_id') if fumble_info and event == 'run'
                     else outcome.get('carrier_id') if event == 'run' else None)
        receiver_id = (caught.get('player_id') if caught else
                       thrown.get('target_id') if thrown else None)
        interceptor_id = players.get('interceptor')
        sacker_ids = players.get('sackers') or []
        call_intent = 'designed_run' if call['offense']['call']['family'] == 'run' else 'dropback'
        ceg_event = ('scramble' if event == 'run' and call_intent == 'dropback' else event)
        touchdown = bool(outcome.get('is_touchdown'))
        scoring = None
        possession = None
        fumbler_id = fumble_info.get('fumbler_id') if fumble_info else None
        recoverer_id = fumble_info.get('recoverer_id') if fumble_info else None
        returner_id = ((fumble_info.get('returner_id') or outcome.get('carrier_id'))
                       if fumble_info else None)
        if fumble_info is not None and (not returner_id or not recoverer_id):
            raise ValueError('gridiron_fumble_return_roles_incomplete')
        roles = ceg_contract.PlayerRolesV2(
            passer=(ceg_contract.PlayerRoleV2.named(passer_id) if passer_id else ceg_contract.PlayerRoleV2.none()),
            rusher=(ceg_contract.PlayerRoleV2.named(rusher_id) if rusher_id else ceg_contract.PlayerRoleV2.none()),
            receiver=(ceg_contract.PlayerRoleV2.named(receiver_id) if receiver_id else ceg_contract.PlayerRoleV2.none()),
            interceptor=(ceg_contract.PlayerRoleV2.named(interceptor_id) if interceptor_id else ceg_contract.PlayerRoleV2.none()),
            sacker=(ceg_contract.PlayerRoleV2.named(sacker_ids[0]) if sacker_ids else ceg_contract.PlayerRoleV2.none()),
            fumbler=(ceg_contract.PlayerRoleV2.named(fumbler_id) if fumbler_id else ceg_contract.PlayerRoleV2.none()),
            recoverer=(ceg_contract.PlayerRoleV2.named(recoverer_id) if recoverer_id else ceg_contract.PlayerRoleV2.none()),
            returner=(ceg_contract.PlayerRoleV2.named(returner_id) if returner_id else ceg_contract.PlayerRoleV2.none()))

        if fumble_info is not None:
            recovery_side = fumble_info.get('recovery_side')
            if recovery_side not in ('O', 'D'):
                raise ValueError('gridiron_fumble_recovery_team_invalid')
            fumble_x = fumble_info['fumble_spot']['x']
            recovery_x = fumble_info['recovery_spot']['x']
            dead_spot_x = fumble_info['dead_ball_spot']['x']
            fumble_y = _gridiron_yardline_round(
                100 - fumble_x if direction == 1 else fumble_x, 'fumble')
            recovery_y = _gridiron_yardline_round(
                100 - recovery_x if direction == 1 else recovery_x, 'recovery')
            dead_y = _gridiron_yardline_round(
                100 - dead_spot_x if direction == 1 else dead_spot_x, 'dead_ball')
            fumble_role = 'offense' if recovery_side == 'O' else 'defense'
            if recovery_side == 'O':
                possession = ceg_contract.PossessionV2(
                    team='offense', how='kept', recovery_spot_yardline_100=recovery_y,
                    dead_ball_yardline_100=dead_y, recovered_by=ceg_contract.PlayerRoleV2.named(recoverer_id),
                    # Kept possession has no turnover-return fields in ceg-play-2.
                    # Raw recovery geometry is validated above; the actor and
                    # original facts remain in the execution record.
                    fumble_spot_yardline_100=fumble_y)
            else:
                possession = ceg_contract.PossessionV2(
                    team='defense', how='fumble_recovery', turnover_spot_yardline_100=fumble_y,
                    recovery_spot_yardline_100=recovery_y, dead_ball_yardline_100=dead_y,
                    return_yards=fumble_geometry['return_yards'],
                    recovered_by=ceg_contract.PlayerRoleV2.named(recoverer_id),
                    returner=ceg_contract.PlayerRoleV2.named(returner_id),
                    fumble_spot_yardline_100=fumble_y)
            if touchdown:
                scoring = ceg_contract.ScoringV2('touchdown', fumble_role)
            elif reason == 'safety':
                scoring = ceg_contract.ScoringV2('safety', 'defense' if recovery_side == 'O' else 'offense')
        elif ceg_event == 'interception':
            caught_spot = _clamp(interception['at']['x'], 0, 100)
            turnover_spot = int(round(100 - caught_spot if direction == 1 else caught_spot))
            dead_x = _clamp(final_x, 0, 100)
            dead_spot = int(round(100 - dead_x if direction == 1 else dead_x))
            return_yards = dead_spot - turnover_spot
            if touchdown and dead_spot != 100:
                raise ValueError(
                    f'gridiron_defensive_touchdown_spot_mismatch:direction={direction},'
                    f'final_x={final_x},interception_x={caught_spot},dead={dead_spot},'
                    f'turnover={turnover_spot},reason={reason}')
            return_safety = not touchdown and dead_spot == 0 and turnover_spot > 0
            if not touchdown and reason == 'safety' and dead_spot != 0:
                raise ValueError('gridiron_interception_safety_spot_mismatch')
            if not touchdown and not return_safety and dead_spot == 100:
                raise ValueError('gridiron_interception_goal_line_needs_touchdown')
            touchback = not touchdown and not return_safety and dead_spot == 0
            possession = ceg_contract.PossessionV2(
                team='defense', how='interception',
                turnover_spot_yardline_100=turnover_spot,
                dead_ball_yardline_100=dead_spot, return_yards=return_yards,
                returner=ceg_contract.PlayerRoleV2.named(interceptor_id),
                touchback=touchback,
                next_yardline_100=20 if touchback else None)
            if touchdown:
                scoring = ceg_contract.ScoringV2('touchdown', 'defense')
            elif return_safety or reason == 'safety':
                scoring = ceg_contract.ScoringV2('safety', 'offense')
        elif touchdown:
            scoring = ceg_contract.ScoringV2('touchdown', 'offense')
        elif reason == 'safety':
            scoring = ceg_contract.ScoringV2('safety', 'defense')
            possession = ceg_contract.PossessionV2(
                team='offense', how='kept', dead_ball_yardline_100=100)

        air_yards = yac = None
        if event == 'pass_complete':
            catch = caught.get('at') if caught else None
            if not isinstance(catch, dict) or not isinstance(catch.get('x'), (int, float)):
                raise ValueError('gridiron_completion_location_missing')
            air_yards = int(round((catch['x'] - los_x) * direction))
            yac = yards - air_yards
        contract_yards = (0 if event == 'interception' and possession is not None
                          and possession.touchback else yards)

        provenance = ceg_contract.ProvenanceV2(
            generator='gridiron.autonomous_from_snap', version=result['schema_version'],
            manifest_sha256=self.event_manifest_sha256,
            components=('authored_assignments', 'bounded_player_movement', 'live_ball_interaction'),
            draw_ids=(str(call['play_id']),))
        call_provenance = ceg_contract.ProvenanceV2(
            generator='slc.autonomous_playcall', version='v1',
            manifest_sha256=self.event_manifest_sha256,
            components=('team_season_playbook_prior', 'situation_policy'),
            draw_ids=(str(call['seed']),))
        penalty = None
        if pass_interference is not None:
            foul_spot_x = pass_interference['spot']['x']
            foul_spot = int(round(100 - foul_spot_x if direction == 1 else foul_spot_x))
            penalty = ceg_contract.PenaltyV2(
                phase='live_ball',
                fouls=(ceg_contract.PenaltyFoulV2(
                    'defensive_pass_interference', 'defense', 0, foul_spot=foul_spot,
                    player=ceg_contract.PlayerRoleV2.named(pass_interference['defender_id'])),),
                disposition=penalty_decision['disposition'],
                automatic_first_down=(True if penalty_decision['disposition'] == 'accepted' else None),
                provenance=provenance)
        return ceg_contract.GeneratedPlayV2(
            contract=ceg_contract.CONTRACT_V2_VERSION,
            call=ceg_contract.PlayCallV2(call_intent, provenance=call_provenance),
            event=ceg_event, yards_gained=contract_yards, air_yards=air_yards,
            yards_after_catch=yac, possession=possession, scoring=scoring,
            fumble=fumble_info is not None, penalty=penalty, provenance=provenance,
            clock=ceg_contract.ClockV2(
                runoff_seconds=live_clock_seconds,
                live_seconds=live_clock_seconds,
                dead_ball_seconds=0,
                stop_class=('stopped' if reason in ('out_of_bounds', 'incomplete', 'touchdown', 'safety')
                            else 'running')),
            out_of_bounds=reason == 'out_of_bounds', players=roles,
            probabilities=({'dpi_decision': penalty_decision} if penalty_decision else {}))

    def _actor_row(self, pid, side):
        """Resolve a live actor against its expected game-side roster."""
        roster_side = {'A': 'home', 'B': 'away'}[side]
        club = self.team_by_side[side]
        rows = [row for row in self.snapshot['rosters'][roster_side]['players']
                if row['gsis_id'] == pid and row.get('team') == club]
        if not rows and any(row.get('gsis_id') == pid for row in
                            (self.snapshot['rosters'][roster_side].get('membership') or {}).get('players', [])):
            # Participation includes eligible weekly-roster players who do not
            # appear on the published depth chart. Resolve those actors using
            # the same eligibility policy that selected them.
            resolved = getattr(self, '_actor_resolved_rosters', None)
            if resolved is None:
                resolved = roster_preflight.resolve(self.snapshot)
                self._actor_resolved_rosters = resolved
            team_roster = resolved[roster_side]
            if pid in v1_complete_roster.eligible_ids(team_roster):
                player = next(row for row in team_roster['players'] if row['gsis_id'] == pid)
                return {'gsis_id': pid, 'player_name': player['name'],
                        'pos_abb': player['pos'], 'team': club}
        if not rows:
            raise ValueError(f'gridiron_actor_not_on_expected_roster:{pid}:{side}')
        return rows[0]

    def _participants(self, call, result, event, state):
        side = state['offense']
        defense = 'B' if side == 'A' else 'A'
        qb = call['offense']['lineup']['QB']
        outcome = result['result']
        receiver_event = next((e for e in result['events'] if e['type'] == 'catch'), None)
        throw_event = next((e for e in result['events'] if e['type'] == 'throw'), None)
        receiver = receiver_event['player_id'] if receiver_event else throw_event.get('target_id') if throw_event else None
        fumble = outcome.get('fumble')
        carrier = (fumble.get('fumbler_id') if fumble else None) or outcome.get('carrier_id')
        passer = None if event == 'run' else qb
        rusher = carrier if event == 'run' else None
        participants = {'passer_id': passer, 'rusher_id': rusher, 'receiver_id': receiver,
                        'interceptor_id': result['participants'].get('interceptor'),
                        'attribution': 'autonomous_execution', 'timeout': False}

        def actor(role, pid, actor_side):
            if pid is None:
                return
            data = self._actor_row(pid, actor_side)
            participants.update({f'{role}_name': data.get('player_name'),
                                 f'{role}_position': data.get('pos_abb'),
                                 f'{role}_team': data['team'],
                                 f'{role}_side': actor_side})

        for role, pid in (('passer', passer), ('rusher', rusher), ('receiver', receiver)):
            actor(role, pid, side)
        if fumble:
            fumbler_side = defense if event == 'interception' else side
            recovery_side = {'O': side, 'D': defense}.get(fumble.get('recovery_side'))
            if recovery_side is None:
                raise ValueError('gridiron_fumble_recovery_team_invalid')
            post_returner_id = (fumble.get('returner_id') or outcome.get('carrier_id')
                                or fumble.get('recoverer_id'))
            participants.update({
                'fumbler_id': fumble.get('fumbler_id'),
                'recoverer_id': fumble.get('recoverer_id'),
                'post_recovery_returner_id': post_returner_id,
                'returner_id': post_returner_id,
            })
            actor('fumbler', fumble.get('fumbler_id'), fumbler_side)
            actor('recoverer', fumble.get('recoverer_id'), recovery_side)
            actor('returner', post_returner_id, recovery_side)
        return participants

    def _special_teams_call(self, kind, kicking_team, receiving_team, yardline_100, play_index):
        roster_side = 'home' if kicking_team == self.snapshot['schedule']['home_team'] else 'away'
        receiving_roster_side = 'home' if receiving_team == self.snapshot['schedule']['home_team'] else 'away'
        kicking_roster = self.snapshot['rosters'][roster_side]['players']
        receiving_roster = self.snapshot['rosters'][receiving_roster_side]['players']
        checks, resolved = roster_preflight.check(self.snapshot)
        if (roster_preflight.failed(checks)
                or roster_preflight.exclusions_applied(self.snapshot, resolved)[1] != 'PASS'):
            raise ValueError('gridiron_roster_preflight_failed')
        allowed_kicking = v1_complete_roster.eligible_ids(resolved[roster_side])
        allowed_receiving = v1_complete_roster.eligible_ids(resolved[receiving_roster_side])

        def ordered(rows, allowed):
            ranked = sorted((p for p in rows if p.get('gsis_id') in allowed),
                            key=lambda p: (p.get('pos_rank') if type(p.get('pos_rank')) is int
                                           and p['pos_rank'] > 0 else 999, p['gsis_id']))
            unique, seen = [], set()
            for player in ranked:
                if player['gsis_id'] not in seen:
                    unique.append(player)
                    seen.add(player['gsis_id'])
            return unique

        kick_order = ordered(kicking_roster, allowed_kicking)
        receive_order = ordered(receiving_roster, allowed_receiving)
        spec_positions = ('P',) if kind == 'punt' else ('PK', 'K')
        specialists = [p for p in kick_order if p.get('pos_abb') in spec_positions]
        if not specialists:
            raise ValueError(f'autonomous_eligible_{"punter" if kind == "punt" else "kicker"}_missing:{kicking_team}')
        specialist = specialists[0]
        return_positions = ('PR', 'RB', 'WR', 'CB', 'DB', 'FS', 'SS', 'S')
        returners = [p for p in receive_order if p.get('pos_abb') in return_positions]
        if not returners:
            raise ValueError(f'autonomous_eligible_returner_missing:{receiving_team}')
        selected_returner = returners[0]
        coverage = [p for p in kick_order if p['gsis_id'] != specialist['gsis_id']][:10]
        blockers = [p for p in receive_order if p['gsis_id'] != selected_returner['gsis_id']][:10]
        if len(coverage) != 10:
            raise ValueError(f'autonomous_special_teams_coverage_unit_short:{kicking_team}:{len(coverage)}')
        if len(blockers) != 10:
            raise ValueError(f'autonomous_special_teams_return_unit_short:{receiving_team}:{len(blockers)}')

        ratings_path = self._rating_profile_path()
        if not Path(ratings_path).is_file():
            raise ValueError('autonomous_special_teams_ratings_dataset_missing')
        ratings, rating_source = gridiron_bridge._ratings(ratings_path)
        rating_sha256 = gridiron_bridge._sha(ratings_path)
        ids = [specialist['gsis_id'], *(p['gsis_id'] for p in coverage),
               selected_returner['gsis_id'], *(p['gsis_id'] for p in blockers)]
        if len(ids) != 22 or len(set(ids)) != 22:
            raise ValueError('autonomous_special_teams_lineup_not_22_unique_players')
        profiles = {}
        for pid in ids:
            profile = ratings.get(pid)
            if not profile or not isinstance(profile.get('ratings'), dict):
                raise ValueError('autonomous_special_teams_rating_profile_missing:' + pid)
            profiles[pid] = {'ratings': {key: value for key, value in profile['ratings'].items()
                                         if key in SPECIAL_TEAMS_RATING_KEYS},
                              'physics': profile.get('physics') or {}}
        call = {
            'schema_version': 'gridiron.autonomous-special-teams.v1',
            'kind': kind, 'seed': str(self._decision_seed(play_index, 'gridiron_' + kind)),
            'kicking_team': kicking_team, 'receiving_team': receiving_team,
            'yardline_100': yardline_100, 'ball_lateral_yards': 26.67,
            'lineups': {
                'kicking': {('punter' if kind == 'punt' else 'kicker'): specialist['gsis_id'],
                            'coverage': [p['gsis_id'] for p in coverage]},
                'receiving': {'returner': selected_returner['gsis_id'],
                              'blockers': [p['gsis_id'] for p in blockers]},
            },
            'player_profiles': profiles,
        }
        # Resolve actors from the selected live units, not a merged roster.
        player_rows = {p['gsis_id']: p for p in (specialist, *coverage, selected_returner, *blockers)}
        provenance = {'dataset': Path(ratings_path).name, 'sha256': rating_sha256,
                      **rating_source, 'player_ids': ids}
        return call, player_rows, provenance

    def _execute_live_special_teams(self, kind, kicking_team, receiving_team, yardline_100,
                                    play_index, row=None, free_kick_kind=None):
        kicking_side = (kicking_team if kicking_team in self.team_by_side else
                        next((side for side, team in self.team_by_side.items() if team == kicking_team), None))
        receiving_side = (receiving_team if receiving_team in self.team_by_side else
                          next((side for side, team in self.team_by_side.items() if team == receiving_team), None))
        if kicking_side is None or receiving_side is None or kicking_side == receiving_side:
            return {'blocker': 'autonomous_special_teams_team_identity_invalid'}
        kicking_club = self.team_by_side[kicking_side]
        receiving_club = self.team_by_side[receiving_side]
        # GridIron's field-goal input yardline is the line of scrimmage. The
        # rules restart is measured from the holder's spot, seven yards behind
        # the line, where the live executor places the ball for the kick.
        kick_spot_yardline = (game_state.kick_spot_yardline_100(int(yardline_100))
                              if kind == 'field_goal' else int(yardline_100))
        try:
            call, player_rows, rating_provenance = self._special_teams_call(
                kind, kicking_club, receiving_club, yardline_100, play_index)
            result, timing = self.session.special_teams(call)
        except (OSError, TypeError, ValueError) as exc:
            return {'blocker': str(exc)}
        if result.get('status') != 'complete' or not isinstance(result.get('result'), dict):
            reason = (result.get('failure') or {}).get('reason', 'result_record_missing')
            return {'blocker': f'gridiron_special_teams_execution_failed:{kind}:{reason}',
                    'execution': {'call': call, 'result': result, 'timing': timing,
                                  'rating_provenance': rating_provenance,
                                  'viewer': 'gridiron_result.trajectory.frames'}}
        facts = result['result']
        result_name = facts.get('result')
        if result_name not in GRIDIRON_SPECIAL_TEAMS_RESULT_HANDLERS.get(kind, {}):
            return {'blocker': f'gridiron_special_teams_outcome_unmapped:{kind}:{result_name}',
                    'execution': {'call': call, 'result': result, 'timing': timing,
                                  'rating_provenance': rating_provenance,
                                  'viewer': 'gridiron_result.trajectory.frames'}}

        # The rule choice is made after the live kick has gone out, from the
        # receiving coach's available options and pre-whistle field position.
        if kind == 'kickoff' and result_name == 'out_of_bounds':
            out_spot = facts.get('out_of_bounds_spot_yardline_100', facts.get('dead_ball_yardline_100'))
            if type(out_spot) is not int:
                return {'blocker': 'kickoff_out_of_bounds_spot_missing',
                        'execution': {'call': call, 'result': result, 'timing': timing}}
            distance = 30 if free_kick_kind == 'safety_free_kick' else 25
            legal_options = [('inbounds_spot', out_spot),
                             ('distance_from_kick', int(yardline_100) - distance)]
            legal_options = [(name, spot) for name, spot in legal_options if 0 < spot < 100]
            if not legal_options:
                return {'blocker': 'autonomous_kickoff_out_of_bounds_has_no_legal_restart_spot'}

            def expected_points(kicking_frame_spot):
                receiver_yardline = 100 - kicking_frame_spot
                return max(0.0, 5.5 - 0.072 * receiver_yardline)

            quality = self.coaching_quality(receiving_side, 'kickoff')
            best = max(legal_options, key=lambda item: (expected_points(item[1]), item[0]))
            worst = min(legal_options, key=lambda item: (expected_points(item[1]), item[0]))
            choose_best = random.Random(self._decision_seed(
                play_index, 'kickoff_out_of_bounds_option')).random() < quality / 100
            restart_option, enforced_spot = best if choose_best else worst
            facts = {**facts, 'out_of_bounds_spot_yardline_100': out_spot,
                     'dead_ball_yardline_100': out_spot,
                     'restart_yardline_100': enforced_spot,
                     'restart_option': restart_option,
                     'restart_options': [{'option': name, 'dead_ball_yardline_100': spot,
                                          'expected_points': round(expected_points(spot), 3)}
                                         for name, spot in legal_options],
                     'decision': {'coaching_quality': quality,
                                  'selected_best_option': choose_best,
                                  'information_available': ['kick_spot', 'out_of_bounds_spot',
                                                            'safety_kick_status', 'rule_options']}}
            result = {**result, 'result': facts}

        named = lambda pid: (ceg_contract.PlayerRoleV2.named(pid) if pid
                             else ceg_contract.PlayerRoleV2.none())
        spot = lambda value, frame='kicking_team': (
            ceg_contract_v3.FieldSpotV3(int(value), frame) if type(value) in (int, float)
            and math.isfinite(value) and int(value) == value else None)
        none_role = ceg_contract.PlayerRoleV2.none()
        returner = named(facts.get('returner_id'))
        recovery_team = facts.get('recovery_team')
        possession_after = facts.get('possession_after')
        if possession_after not in ('kicking_team', 'receiving_team') and result_name not in ('made', 'missed', 'period_expired'):
            return {'blocker': f'gridiron_special_teams_possession_missing:{kind}:{result_name}',
                    'execution': {'call': call, 'result': result, 'timing': timing}}

        dead_spot = spot(facts.get('dead_ball_yardline_100'))
        restart_spot = None
        recovery_spot = spot(facts.get('recovery_yardline_100'))
        recoverer = named(facts.get('recoverer_id'))
        return_facts = None
        fair_catcher = None
        kickoff_oob = None
        safety = None
        blocked_fg = None
        scoring = None

        if result_name == 'return':
            start = spot(facts.get('return_start_yardline_100'))
            returner = named(facts.get('returner_id'))
            if returner.status == 'none' or start is None or dead_spot is None:
                return {'blocker': 'kick_return_execution_roles_or_spots_missing',
                        'execution': {'call': call, 'result': result, 'timing': timing}}
            return_facts = ceg_contract_v3.KickReturnV3(
                returning_team=possession_after, returner=returner,
                return_start_spot=start, dead_ball_spot=dead_spot,
                return_yards=int(facts['return_yards']), muffing_returner=none_role,
                recoverer=none_role, post_recovery_returner=none_role,
                scoring_kind=facts.get('scoring'), scoring_team=facts.get('scoring_team'))
        elif result_name == 'muff':
            muffing = named(facts.get('muffing_returner_id') or facts.get('fumbler_id'))
            recoverer = named(facts.get('recoverer_id'))
            post_returner = named(facts.get('post_recovery_returner_id'))
            recovery_spot = spot(facts.get('recovery_yardline_100'))
            fumble_spot = spot(facts.get('fumble_spot_yardline_100'))
            if any(role.status == 'none' for role in (muffing, recoverer, post_returner)):
                return {'blocker': 'kick_muff_player_roles_missing',
                        'execution': {'call': call, 'result': result, 'timing': timing}}
            if any(location is None for location in (dead_spot, recovery_spot, fumble_spot)):
                return {'blocker': 'kick_muff_spot_or_frame_missing',
                        'execution': {'call': call, 'result': result, 'timing': timing}}
            return_facts = ceg_contract_v3.KickReturnV3(
                returning_team=possession_after, returner=none_role,
                return_start_spot=None, dead_ball_spot=dead_spot,
                return_yards=int(facts['return_yards']), muffing_returner=muffing,
                recoverer=recoverer, post_recovery_returner=post_returner,
                recovery_spot=recovery_spot, fumble_spot=fumble_spot,
                scoring_kind=facts.get('scoring'), scoring_team=facts.get('scoring_team'))
            if facts.get('touchback'):
                restart_yardline = facts.get('receiving_restart_yardline_100')
                restart_spot = (spot(100 - restart_yardline, 'receiving_team')
                                if type(restart_yardline) is int else None)
                if restart_spot is None:
                    return {'blocker': 'kick_muff_touchback_restart_spot_missing',
                            'execution': {'call': call, 'result': result, 'timing': timing}}
        elif result_name == 'touchback':
            if type(facts.get('dead_ball_yardline_100')) is not int:
                return {'blocker': 'kick_touchback_restart_spot_missing'}
            # GridIron publishes the receiving restart in the kicking-team frame;
            # ceg-play-3 also records the physical ball dead at the goal line.
            restart_spot = ceg_contract_v3.FieldSpotV3(
                100 - int(facts['dead_ball_yardline_100']), 'receiving_team')
            dead_spot = ceg_contract_v3.FieldSpotV3(0, 'kicking_team')
        elif result_name == 'fair_catch':
            dead_spot = spot(facts.get('dead_ball_yardline_100'))
            fair_catcher = named(facts.get('returner_id'))
            if dead_spot is None or fair_catcher.status == 'none':
                return {'blocker': 'fair_catch_player_or_spot_missing'}
        elif result_name == 'downed':
            if dead_spot is None:
                return {'blocker': 'downed_kick_spot_missing'}
        elif result_name == 'out_of_bounds':
            dead_spot = spot(facts.get('out_of_bounds_spot_yardline_100'))
            if dead_spot is None:
                return {'blocker': 'kick_out_of_bounds_spot_missing'}
            if kind == 'kickoff':
                choice = {'inbounds_spot': 'at_out_of_bounds_spot',
                          'distance_from_kick': 'at_distance_from_kick'}.get(facts.get('restart_option'))
                raw_restart = facts.get('restart_yardline_100')
                if choice is None or type(raw_restart) is not int:
                    return {'blocker': 'kickoff_out_of_bounds_choice_unresolved'}
                restart_spot = ceg_contract_v3.FieldSpotV3(100 - raw_restart, 'receiving_team')
                kickoff_oob = ceg_contract_v3.KickoffOutOfBoundsV3(
                    cause='kicking_team_out_of_bounds', choice=choice,
                    out_of_bounds_spot=dead_spot, restart_spot=restart_spot,
                    distance_yards=(30 if free_kick_kind == 'safety_free_kick' else 25)
                    if choice == 'at_distance_from_kick' else None)
        elif result_name == 'missed':
            restart_yardline = game_state.missed_field_goal_spot(kick_spot_yardline)
            restart_spot = ceg_contract_v3.FieldSpotV3(restart_yardline, 'receiving_team')
            dead_spot = ceg_contract_v3.FieldSpotV3(0, 'kicking_team')
            possession_after = 'receiving_team'
        elif result_name == 'blocked':
            if kind != 'field_goal':
                return {'blocker': 'blocked_punt_live_recovery_not_supported_by_ceg_play_3'}
            recovery_team = facts.get('recovery_team')
            post_returner = named(facts.get('post_block_returner_id') or facts.get('returner_id'))
            recoverer = named(facts.get('recoverer_id'))
            if recovery_team not in ('kicking_team', 'receiving_team'):
                return {'blocker': 'blocked_field_goal_recovery_team_missing'}
            if post_returner.status == 'none' or recoverer.status == 'none':
                return {'blocker': 'blocked_field_goal_recovery_player_missing'}
            if recovery_spot is None or dead_spot is None or type(facts.get('return_yards')) is not int:
                return {'blocker': 'blocked_field_goal_recovery_or_return_spot_missing'}
            blocked_fg = ceg_contract_v3.BlockedFieldGoalReturnV3(
                recovery_team=recovery_team, recovery_spot=recovery_spot,
                recoverer=recoverer, post_block_returner=post_returner,
                return_yards=int(facts['return_yards']), dead_ball_spot=dead_spot,
                possession_after=possession_after,
                scoring_kind=facts.get('scoring'), scoring_team=facts.get('scoring_team'))

        if facts.get('scoring') in ('touchdown', 'safety'):
            score_team = facts.get('scoring_team')
            if score_team not in ('kicking_team', 'receiving_team'):
                return {'blocker': 'kick_scoring_team_missing'}
            scoring = ceg_contract.ScoringV2(facts['scoring'], score_team)
            if facts['scoring'] == 'safety':
                possessing_team = possession_after
                if possessing_team not in ('kicking_team', 'receiving_team'):
                    return {'blocker': 'kick_safety_possessing_team_missing'}
                free_kick_team = 'receiving_team' if score_team == 'kicking_team' else 'kicking_team'
                safety = ceg_contract_v3.KickSafetyV3(
                    scoring_team=score_team, possessing_team=possessing_team,
                    safety_dead_ball_spot=ceg_contract_v3.FieldSpotV3(100, possessing_team),
                    free_kick_team=free_kick_team,
                    free_kick_spot=ceg_contract_v3.FieldSpotV3(80, free_kick_team),
                    free_kick_spot_basis='own_20', receiving_team=score_team,
                    restart_status='pending')
        elif kind == 'field_goal' and result_name == 'made':
            scoring = ceg_contract.ScoringV2('field_goal', 'kicking_team')

        kick_kind = ('safety_kick' if kind == 'kickoff' and free_kick_kind == 'safety_free_kick'
                     else 'field_goal' if kind == 'field_goal' else kind)
        event_name = 'field_goal_attempt' if kind == 'field_goal' else ('kickoff' if kind == 'kickoff' else kind)
        if result_name == 'blocked':
            result_name = 'blocked'
        kick = ceg_contract_v3.KickV3(
            kind=kick_kind, kicking_team=kicking_side, receiving_team=receiving_side,
            # The contract's pre-kick state spot is the LOS. Miss enforcement
            # separately derives the actual holder spot from that LOS.
            kick_spot=ceg_contract_v3.FieldSpotV3(int(yardline_100), 'kicking_team'),
            distance_yards=(int(facts['distance_yards']) if type(facts.get('distance_yards')) in (int, float)
                            and math.isfinite(facts['distance_yards']) else None),
            result=result_name, possession_after=possession_after,
            dead_ball_spot=dead_spot,
            receiving_restart_spot=(None if kind == 'kickoff' and result_name == 'out_of_bounds'
                                    else restart_spot),
            recovery_team=recovery_team, recovery_spot=recovery_spot, recoverer=recoverer,
            return_facts=return_facts, fair_catcher=fair_catcher,
            out_of_bounds_spot=(dead_spot if result_name == 'out_of_bounds' else None),
            kickoff_oob=kickoff_oob, safety=safety, blocked_field_goal_return=blocked_fg)
        elapsed = max(0, int(math.ceil(facts.get('live_elapsed_seconds', facts.get('elapsed_seconds')) or 0)))
        runoff = max(0, int(facts.get('clock_runoff_seconds') or 0))
        dead_seconds = 0
        clock = ceg_contract.ClockV2(runoff, runoff, 0, 'stopped')
        roles = (ceg_contract.PlayerRolesV2(punter=named(call['lineups']['kicking'].get('punter')),
                    returner=(return_facts.post_recovery_returner if result_name == 'muff' else returner),
                    recoverer=recoverer,
                    fumbler=(return_facts.muffing_returner if result_name == 'muff' else none_role))
                 if kind == 'punt' else
                 ceg_contract.PlayerRolesV2(kicker=named(call['lineups']['kicking'].get('kicker')),
                    returner=(return_facts.post_recovery_returner if result_name == 'muff' else returner),
                    recoverer=recoverer,
                    fumbler=(return_facts.muffing_returner if result_name == 'muff' else none_role)))
        provenance = ceg_contract.ProvenanceV2(
            generator='gridiron.autonomous_special_teams', version='v1',
            manifest_sha256=self.event_manifest_sha256,
            components=('player_rating', 'authored_kick_model', 'live_player_execution', 'field_geometry'),
            draw_ids=(f"{self.seed}:{play_index}:{kind}",))
        event_record = ceg_contract_v3.GeneratedPlayV3(
            contract=ceg_contract_v3.CONTRACT_V3_VERSION,
            call=ceg_contract.PlayCallV2('kickoff' if kind == 'kickoff' else kick_kind, provenance=provenance),
            event=event_name, yards_gained=None, provenance=provenance, clock=clock,
            fumble=(result_name == 'muff'), scoring=scoring, kick=kick, players=roles,
            probabilities=({'fair_catch': True} if result_name == 'fair_catch' else {}),
            turnover_chain=None)
        participants = {'attribution': 'autonomous_execution',
                        'punter_id': call['lineups']['kicking'].get('punter') if kind == 'punt' else None,
                        'kicker_id': call['lineups']['kicking'].get('kicker') if kind != 'punt' else None,
                        'returner_id': (facts.get('post_recovery_returner_id') if result_name == 'muff'
                                        else facts.get('returner_id')),
                        'muffing_returner_id': facts.get('muffing_returner_id'),
                        'fumbler_id': facts.get('fumbler_id') or facts.get('muffing_returner_id'),
                        'post_recovery_returner_id': facts.get('post_recovery_returner_id'),
                        'recoverer_id': facts.get('recoverer_id'),
                        'fumble_recovery_team': possession_after if result_name == 'muff' else None,
                        'fumble_return_yards': facts.get('return_yards') if result_name == 'muff' else None,
                        'return_touchdown': facts.get('scoring') == 'touchdown',
                        'fair_catch': result_name == 'fair_catch',
                        'out_of_bounds': bool(facts.get('out_of_bounds')),
                        'kickoff_out_of_bounds_restart_option': facts.get('restart_option')}
        for role, pid in (('punter' if kind == 'punt' else 'kicker',
                           call['lineups']['kicking'].get('punter' if kind == 'punt' else 'kicker')),
                          ('returner', participants.get('returner_id')),
                          ('fumbler', participants.get('fumbler_id')),
                          ('muffing_returner', facts.get('muffing_returner_id')),
                          ('recoverer', facts.get('recoverer_id'))):
            if pid is None:
                continue
            player = player_rows.get(pid)
            if player is None or player.get('team') not in (kicking_club, receiving_club):
                raise ValueError(f'gridiron_special_teams_actor_not_on_live_roster:{pid}')
            participants.update({f'{role}_{field}': player.get(key) for field, key in (
                ('name', 'player_name'), ('position', 'pos_abb'), ('team', 'team'))})
            participants[f'{role}_side'] = (kicking_side if player['team'] == kicking_club
                                             else receiving_side)
        execution = {'schema_version': result['schema_version'], 'call': call, 'result': result,
                     'timing': timing, 'rating_provenance': rating_provenance,
                     'ceg_event': asdict(event_record), 'viewer': 'gridiron_result.trajectory.frames'}
        field_goal_evidence = None
        if kind == 'field_goal':
            kicker_id = call['lineups']['kicking']['kicker']
            kicker_ratings = call['player_profiles'][kicker_id]['ratings']
            field_goal_evidence = {
                'source': 'gridiron_live_ball_trajectory', 'result': result_name,
                'kick_distance_yards': facts.get('distance_yards'),
                'kick_power_rating': kicker_ratings['KPW'],
                'kick_accuracy_rating': kicker_ratings['KAC'],
            }
        if row is not None:
            row['participants'].update(participants)
            row['live_elapsed_seconds'] = elapsed
            row['dead_ball_seconds'] = dead_seconds
            row['clock_stopped'] = True
            row['out_of_bounds'] = bool(facts.get('out_of_bounds'))
            row.setdefault('decision_note', {})['special_teams_result'] = result_name
            row['decision_note']['fair_catch'] = bool(facts.get('fair_catch'))
        return {'event': event_name, 'clock_runoff_seconds': runoff, 'event_record': event_record,
                'execution': execution, 'participants': participants,
                'metadata': {'special_teams_execution': {
                    'kind': kind, 'distance_yards': facts.get('distance_yards'),
                    'return_yards': facts.get('return_yards'), 'fair_catch': bool(facts.get('fair_catch')),
                    'out_of_bounds': bool(facts.get('out_of_bounds')),
                    'restart_option': facts.get('restart_option'),
                    'out_of_bounds_spot_yardline_100': facts.get('out_of_bounds_spot_yardline_100'),
                    'restart_options': facts.get('restart_options'),
                    'gridiron_engine_commit': timing['engine_commit'],
                    **({'field_goal_execution': field_goal_evidence} if field_goal_evidence else {})}}}

    def special_teams(self, event, state, row, _runoff, _spot, rng):
        if event == 'punt':
            return self._execute_live_special_teams('punt', state['offense'], state['defense'], state['yl'],
                                                    row['play_id'], row)
        if event == 'field_goal_attempt':
            return self._execute_live_special_teams('field_goal', state['offense'], state['defense'], state['yl'],
                                                    row['play_id'], row)
        return {'blocker': 'autonomous_special_teams_event_unsupported:' + str(event)}
    def _player_rating(self, player_id, name):
        path = self._rating_profile_path()
        rows, _ = gridiron_bridge._ratings(path) if Path(path).is_file() else ({}, {})
        player = rows.get(player_id)
        rating = (player.get('ratings', {}).get(name) if player else None)
        if type(rating) is not int or not 1 <= rating <= 99:
            raise ValueError(f'autonomous_player_rating_missing:{player_id}:{name}')
        return rating

    def kick(self, kind, kicker, receiver, context):
        kick_spot = 80 if kind == 'safety_free_kick' else 65
        sequence = getattr(self, 'kickoff_index', 0)
        self.kickoff_index = sequence + 1
        result = self._execute_live_special_teams(
            'kickoff', kicker, receiver, kick_spot,
            self._decision_seed(sequence, 'gridiron_' + kind), free_kick_kind=kind)
        if result.get('blocker'):
            return result
        result.update({'clock_starts_on': 'legal_touch',
                       'execution': {**result['execution'], 'kick_kind': kind}})
        return result

    def try_after_touchdown(self, situation):
        scorer = self.team_by_side.get(self.current_team, self.current_team)
        quality = self.coaching_quality(self.current_team, 'two_point')
        profile = getattr(self, 'coaching_profiles', {}).get(scorer, {})
        tendency = _clamp(float(profile.get('two_point_tendency', 0.08)), 0.0, 1.0)
        expected_two, expected_extra = 2 * 0.46, 0.94
        urgent_two = (situation['margin'] == -2
                      or situation['margin'] == -1 and situation['quarter'] == 4
                      and situation['clock'] <= 120)
        two_is_optimal = urgent_two or expected_two > expected_extra
        two_probability = (tendency + quality / 100 * (1 - tendency) if two_is_optimal
                           else tendency * (1 - quality / 100))
        choose_two = random.Random(
            self._decision_seed(self.play_index, 'two_point_choice')).random() < two_probability
        direction = situation.get('offense_direction', 1)
        try_index = self.play_index + 1
        if choose_two:
            side = self.current_team
            opponent = 'B' if side == 'A' else 'A'
            # The try is untimed, but the call needs the actual game period and clock.
            # LP yardline_100 measures distance to the opponent's goal.
            play_state = {'offense': side, 'defense': opponent, 'quarter': situation['quarter'],
                          'clock': situation['clock'], 'down': 1, 'togo': 2, 'yl': 2,
                          'offense_direction': direction}
            family = self._choose_family(play_state, side, try_index)
            call, _, provenance = gridiron_bridge.build_call(
                self.snapshot_path, self.field, self.participation_sha256,
                self.profile_paths, self.playbook_manifest,
                seed=self._decision_seed(try_index, 'two_point_gridiron'), family=family,
                state=play_state, ratings_path=self._rating_profile_path())
            try:
                result, timing = self.session.play(call)
                generated = self._map_scrimmage_result(
                    call, result, timing, provenance, play_state,
                    {'play_index': try_index, 'direction': direction},
                    {'selection': 'two_point_try', 'family': family}, family)
                applied = self.apply_event(play_state, generated['event_record'])
            except (AssertionError, OSError, TypeError, ValueError) as exc:
                return 0, game_state.try_record('two_point', False), 'autonomous_two_point_execution:' + str(exc)
            made = applied.terminal == 'touchdown' and applied.scoring_team == side
            opponent_points = (2 if applied.terminal == 'touchdown'
                               and applied.scoring_team == opponent else 0)
            record = {**game_state.try_record('two_point', made),
                      'opponent_points': opponent_points,
                      'decision': {'expected_points_two': expected_two,
                                   'expected_points_extra_point': expected_extra,
                                   'two_point_probability': round(two_probability, 4),
                                   'coaching_quality': quality, 'tendency': tendency,
                                   'information_available': ['score', 'quarter', 'clock',
                                                             'expected_points_of_available_tries']},
                      'execution': {**generated['execution'], 'kind': 'two_point_scrimmage',
                                    'family': family}}
            participants = (generated.get('row') or {}).get('participants') or {}
            record['execution']['player_ids'] = participants
            record['try_actor_ids'] = [pid for pid in (
                participants.get('rusher_id'), participants.get('receiver_id'),
                participants.get('passer_id')) if pid]
            record['try_player_details'] = participants
            return (2 if made else 0), record, None
        opponent = next(team for team in self.teams if team != scorer)
        result = self._execute_live_special_teams(
            'field_goal', scorer, opponent, 15, try_index)
        if result.get('blocker'):
            return 0, game_state.try_record('extra_point', False), result['blocker']
        kicker_id = result['execution']['call']['lineups']['kicking']['kicker']
        execution_result = result['execution']['result']['result']
        made = execution_result['result'] == 'made'
        opponent_points = (2 if execution_result.get('scoring') == 'touchdown'
                           and execution_result.get('scoring_team') == 'receiving_team' else 0)
        record = {**game_state.try_record('extra_point', made),
                  'opponent_points': opponent_points, 'kicker_id': kicker_id,
                  'kicker_details': {field: result['participants'].get('kicker_' + field)
                                     for field in ('name', 'position', 'team', 'side')},
                  'decision': {'expected_points_extra_point': expected_extra,
                               'expected_points_two': expected_two,
                               'two_point_probability': round(two_probability, 4),
                               'coaching_quality': quality, 'tendency': tendency,
                               'information_available': ['score', 'quarter', 'clock',
                                                         'expected_points_of_available_tries']},
                  'execution': {**result['execution'], 'kind': 'extra_point_field_goal'}}
        return int(made), record, None

    def overtime_first_choice(self, winner, _loser, _score):
        # Receiving has the higher authored V1 value; the toss decision is a
        # coaching decision, independent of any eventual drive result.
        quality = self.coaching_quality(winner, 'overtime')
        return 'receive' if quality >= 50 else 'kick'

    def set_offense(self, side):
        self.current_team = side


def play_autonomous_game(seed, ref, *, snapshot_path, participation_path, participation_sha256,
                         playbook_dir, playbook_manifest, engine_root, ratings_path=None,
                         coaching_profiles=None, participation_snap_counts=None,
                         participation_entry_current=True, **game_kwargs):
    """Run one complete SLC game whose snaps are generated by Gridiron agents."""
    source = AutonomousGameExecution(
        seed=seed, snapshot_path=snapshot_path, participation_path=participation_path,
        participation_sha256=participation_sha256, playbook_dir=playbook_dir,
        playbook_manifest=playbook_manifest, engine_root=engine_root, ratings_path=ratings_path,
        coaching_profiles=coaching_profiles, participation_snap_counts=participation_snap_counts,
        participation_entry_current=participation_entry_current)
    try:
        original_event_source = source.event_source
        def event_source(state, context):
            source.current_team = state['offense']
            return original_event_source(state, context)
        source.event_source = event_source
        return game_state.play_game(seed, ref, pregame_snapshot=source.snapshot,
                                    execution_source=source, **game_kwargs)
    finally:
        source.close()
