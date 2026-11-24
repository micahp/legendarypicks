"""Autonomous Gridiron execution through the SLC regulation-game lifecycle.

Historical team playbooks supply pregame aggregate tendencies only. Executable
calls and player assignments are authored in Gridiron; live results are never
looked up in historical play outcomes.
"""
from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

import game_state
import gridiron_bridge
import participation_field
import pregame_snapshot


def _clamp(value, low, high):
    return min(high, max(low, value))


def _sigmoid(value):
    return 1 / (1 + math.exp(-_clamp(value, -30, 30)))


class AutonomousTimeoutDecisions:
    """Timeout calls from live clock, score and possession, with a separate quality rating."""

    def __init__(self, execution, remaining, points):
        self.execution = execution
        self.left = dict(remaining)
        self.points = dict(points)
        self.clock = None

    def decide(self, _rng, before, after, terminal, event, row):
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
                 coaching_profiles=None):
        self.seed = int(seed)
        self.snapshot_path = str(snapshot_path)
        self.snapshot = pregame_snapshot.load_frozen_snapshot(self.snapshot_path)
        self.teams = (self.snapshot['schedule']['home_team'], self.snapshot['schedule']['away_team'])
        self.team_by_side = {'A': self.teams[0], 'B': self.teams[1]}
        self.profile_paths = {team: str(Path(playbook_dir) / f'{team}-2025.json') for team in self.teams}
        self.playbook_manifest = str(playbook_manifest)
        self.participation_sha256 = participation_sha256
        self.field = participation_field.Field.load(participation_path, participation_sha256)
        self.engine_root = str(engine_root)
        self.ratings_path = ratings_path
        self.coaching_profiles = coaching_profiles or {}
        self.session = gridiron_bridge.GridironSession(self.engine_root)
        self.play_index = 0
        self._play_prior_cache = {}
        self.current_score_diff = 0

    def close(self):
        self.session.close()

    def coaching_quality(self, team, decision):
        profile = self.coaching_profiles.get(self.team_by_side.get(team, team), {})
        value = profile.get(f'{decision}_quality', 70)
        return int(_clamp(value, 1, 99))

    def timeout_model(self, remaining, points):
        return AutonomousTimeoutDecisions(self, remaining, points)

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
            family = selected if selected in ('run', 'pass') else self._choose_family(state, side, self.play_index)
            call_state = {**state, 'offense_direction': context['direction']}
            call, provenance = gridiron_bridge.build_call(
                self.snapshot_path, self.field, self.participation_sha256,
                self.profile_paths, self.playbook_manifest,
                seed=self._decision_seed(self.play_index, 'gridiron'), family=family, state=call_state,
                ratings_path=self.ratings_path)
            result, timing = self.session.play(call)
            return self._map_scrimmage_result(call, result, timing, provenance, state, context,
                                              decision_note, family)
        play_id = int(context['play_index'])
        row = {'game_id': self.snapshot['schedule']['game_id'], 'play_id': play_id,
               'play_type': play_type, 'yards_gained': 0, 'live_elapsed_seconds': 4.0,
               'dead_ball_seconds': 0.0, 'clock_stopped': True, 'out_of_bounds': False,
               'decision_note': decision_note,
               'participants': {'attribution': 'autonomous_execution', 'timeout': False,
                                'out_of_bounds': False}}
        return {'event': event, 'row': row, 'clock_runoff_seconds': 4.0, 'spot': None}

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
        if abs(final_x - (los_x + direction * outcome['yards_gained'])) > 0.003:
            raise ValueError('gridiron_final_spot_mismatch')
        events = result['events']
        thrown = next((item for item in events if item['type'] == 'throw'), None)
        caught = next((item for item in events if item['type'] == 'catch'), None)
        interception = next((item for item in events if item['type'] == 'interception'), None)
        reason = outcome['event']
        if outcome['turnover']:
            if not interception:
                raise ValueError('gridiron_turnover_without_interception_event')
            event = 'interception'
        elif reason == 'incomplete':
            event = 'pass_incomplete'
        elif reason == 'sack' or result.get('participants', {}).get('sackers'):
            event = 'sack'
        elif family == 'run' or (not thrown and outcome.get('carrier_id') == call['offense']['lineup']['QB']):
            event = 'run'
        elif caught:
            event = 'pass_complete'
        else:
            raise ValueError('gridiron_result_classification_unsupported:' + str(reason))
        if reason not in ('tackle', 'out_of_bounds', 'incomplete', 'sack', 'touchdown', 'interception', 'safety'):
            raise ValueError('gridiron_terminal_unsupported:' + str(reason))
        if outcome.get('is_touchdown') and outcome.get('turnover'):
            raise ValueError('autonomous_defensive_touchdown_requires_ceg_play_2')
        gain = math.floor(outcome['yards_gained']) if event in ('run', 'pass_complete', 'sack') else 0
        spot = None
        if event == 'interception':
            receiving_yl = final_x if direction == 1 else 100 - final_x
            spot = int(round(receiving_yl))
            if not 1 <= spot <= 99:
                raise ValueError('gridiron_interception_dead_ball_requires_ceg_play_2')
        elapsed = max(1, math.ceil(outcome['elapsed_seconds']))
        dead = 0 if reason in ('out_of_bounds', 'incomplete', 'touchdown', 'safety') else 27
        row = {'game_id': self.snapshot['schedule']['game_id'], 'play_id': int(context['play_index']),
               'play_type': 'run' if event == 'run' else 'pass', 'yards_gained': gain,
               'live_elapsed_seconds': elapsed, 'dead_ball_seconds': dead,
               'clock_stopped': dead == 0, 'out_of_bounds': reason == 'out_of_bounds',
               'decision_note': decision_note or {'selection': family,
                   'team_playbook_prior': self._playbook_prior(call['offense']['team'])['use'],
                   'concept': call['offense']['call']['concept'],
                   'assignments': 'authored_executable_gridiron_diagram'},
               'participants': self._participants(call, result, event, state)}
        row['participants']['out_of_bounds'] = reason == 'out_of_bounds'
        if decision_note:
            row['decision_note'] = {**decision_note, 'play_family': family,
                                    'executable_concept': call['offense']['call']['concept']}
        if elapsed + dead >= state['clock']:
            runoff = state['clock']
        else:
            runoff = elapsed + dead
        execution = {'schema_version': result['schema_version'], 'call': call,
                     'result': result, 'provenance': provenance, 'timing': timing,
                     'viewer': 'gridiron_result.trajectory.frames'}
        return {'event': event, 'row': row, 'clock_runoff_seconds': runoff, 'spot': spot,
                'execution': execution}

    def _participants(self, call, result, event, state):
        side = state['offense']
        team = self.team_by_side[side]
        defense = 'B' if side == 'A' else 'A'
        roster_rows = {row['gsis_id']: row for roster_side in ('home', 'away')
                       for row in self.snapshot['rosters'][roster_side]['players']}
        qb = call['offense']['lineup']['QB']
        outcome = result['result']
        receiver_event = next((e for e in result['events'] if e['type'] == 'catch'), None)
        throw_event = next((e for e in result['events'] if e['type'] == 'throw'), None)
        receiver = receiver_event['player_id'] if receiver_event else throw_event.get('target_id') if throw_event else None
        carrier = outcome.get('carrier_id')
        passer = None if event == 'run' else qb
        rusher = carrier if event == 'run' else None
        participants = {'passer_id': passer, 'rusher_id': rusher, 'receiver_id': receiver,
                        'interceptor_id': result['participants'].get('interceptor'),
                        'attribution': 'autonomous_execution', 'timeout': False}
        for role, pid in (('passer', passer), ('rusher', rusher), ('receiver', receiver)):
            if pid is None:
                continue
            data = roster_rows.get(pid, {})
            participants.update({f'{role}_name': data.get('player_name'),
                                 f'{role}_position': data.get('pos_abb'),
                                 f'{role}_team': data.get('team'),
                                 f'{role}_side': side if data.get('team') == team else defense})
        return participants

    def special_teams(self, event, state, row, _runoff, _spot, rng):
        team = self.team_by_side[state['offense']]
        roster_side = 'home' if team == self.snapshot['schedule']['home_team'] else 'away'
        players = self.snapshot['rosters'][roster_side]['players']
        if event == 'punt':
            punter = min((p for p in players if p.get('pos_abb') == 'P'),
                         key=lambda p: (p.get('pos_rank', 999), p['gsis_id']), default=None)
            distance = max(25, min(65, round(42 + rng.uniform(-5, 5))))
            projected_spot = 100 - state['yl'] + distance
            receiving_spot = 80 if projected_spot >= 100 else int(_clamp(projected_spot, 1, 99))
            return {'event': 'punt', 'clock_runoff_seconds': 6,
                    'spot': receiving_spot,
                    'metadata': {'special_teams_execution': {
                        'kind': 'punt', 'punter_id': punter['gsis_id'] if punter else None,
                        'generated_punt_distance_yards': distance,
                        'return_model': 'bounded_no_return_v1',
                        'assignments': 'authored_11_player_punt_coverage_and_return_roles'}}}
        kick_distance = state['yl'] + 17
        kicker = min((p for p in players if p.get('pos_abb') == 'PK'),
                     key=lambda p: (p.get('pos_rank', 999), p['gsis_id']), default=None)
        rating = self._player_rating(kicker['gsis_id'], 'KAC') if kicker else 70
        p_make = _sigmoid((62 - kick_distance) * 0.16 + (rating - 70) * 0.035)
        made = rng.random() < p_make
        return {'event': 'field_goal_attempt', 'clock_runoff_seconds': 5,
                'metadata': {'field_goal_result': 'made' if made else 'missed',
                             'field_goal_execution': {'kicker_id': kicker['gsis_id'] if kicker else None,
                                 'kick_distance_yards': kick_distance, 'kicker_accuracy_rating': rating,
                                 'make_probability': p_make, 'result': 'made' if made else 'missed',
                                 'assignments': 'authored_11_player_field_goal_unit_roles'},
                             'field_goal_result_source': {'kind': 'generated_player_execution',
                                 'distance_yards': kick_distance, 'kicker_accuracy_rating': rating,
                                 'probability_made': p_make}}}

    def _player_rating(self, player_id, name):
        rows, _ = gridiron_bridge._ratings(self.ratings_path)
        player = rows.get(player_id, {})
        return int(player.get('ratings', {}).get(name, 70))

    def kick(self, kind, kicker, receiver, context):
        # A rule-bounded touchback is the current V1 free-kick model. The SLC
        # lifecycle owns possession, clock, period and score transitions.
        return {'clock_runoff_seconds': 5, 'receiving_start_yardline_100': 65,
                'clock_starts_on': 'legal_touch', 'touchdown': False,
                'execution': {'kind': kind, 'kicking_team': kicker, 'receiving_team': receiver,
                              'result': 'touchback', 'receiving_start_yardline_100': 65,
                              'origin': 'authored_rule_bounded_free_kick_v1',
                              'assignments': 'authored_11_player_kick_coverage_and_return_roles'}}

    def try_after_touchdown(self, situation):
        scorer = self.team_by_side.get(self.current_team, self.current_team)
        quality = self.coaching_quality(self.current_team, 'two_point')
        margin = situation['margin']
        choose_two = margin == -2 and random.Random(
            self._decision_seed(self.play_index, 'two_point_choice')).random() < quality / 100
        if margin not in (-2, -1) and quality < 85:
            choose_two = random.Random(self._decision_seed(self.play_index, 'two_point')).random() < (85 - quality) / 400
        if choose_two:
            probability = 0.46
            made = random.Random(self._decision_seed(self.play_index, 'two_point_execution')).random() < probability
            return (2 if made else 0), {**game_state.try_record('two_point', made),
                    'decision': {'expected_points_two': 2 * probability, 'expected_points_extra_point': 0.94,
                                 'coaching_quality': quality}}, None
        kicker_id = self._special_player(scorer, 'PK')
        rating = self._player_rating(kicker_id, 'KAC') if kicker_id else 70
        probability = _clamp(0.94 + (rating - 70) * 0.0015, 0.8, 0.995)
        made = random.Random(self._decision_seed(self.play_index, 'extra_point')).random() < probability
        return int(made), {**game_state.try_record('extra_point', made),
                'decision': {'expected_points_extra_point': probability,
                             'coaching_quality': quality}}, None

    def _special_player(self, team, position):
        roster_side = 'home' if team == self.snapshot['schedule']['home_team'] else 'away'
        choices = [p for p in self.snapshot['rosters'][roster_side]['players'] if p.get('pos_abb') == position]
        return min(choices, key=lambda p: (p.get('pos_rank', 999), p['gsis_id']))['gsis_id'] if choices else None

    def overtime_first_choice(self, winner, _loser, _score):
        # Receiving has the higher authored V1 value; the toss decision is a
        # coaching decision, independent of any eventual drive result.
        quality = self.coaching_quality(winner, 'overtime')
        return 'receive' if quality >= 50 else 'kick'

    def set_offense(self, side):
        self.current_team = side


def play_autonomous_game(seed, ref, *, snapshot_path, participation_path, participation_sha256,
                         playbook_dir, playbook_manifest, engine_root, ratings_path=None,
                         coaching_profiles=None, **game_kwargs):
    """Run one complete SLC game whose snaps are generated by Gridiron agents."""
    source = AutonomousGameExecution(
        seed=seed, snapshot_path=snapshot_path, participation_path=participation_path,
        participation_sha256=participation_sha256, playbook_dir=playbook_dir,
        playbook_manifest=playbook_manifest, engine_root=engine_root, ratings_path=ratings_path,
        coaching_profiles=coaching_profiles)
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
