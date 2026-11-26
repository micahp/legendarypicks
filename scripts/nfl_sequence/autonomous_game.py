"""Autonomous Gridiron execution through the SLC regulation-game lifecycle.

Historical team playbooks supply pregame aggregate tendencies only. Executable
calls and player assignments are authored in Gridiron; live results are never
looked up in historical play outcomes.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict
from pathlib import Path

import ceg_contract
import event_expansion_rules
from event_expansion import EventExpansionSwitches
import game_state
import gridiron_bridge
import participation_field
import pregame_snapshot
import roster_preflight
import v1_complete_roster


SPECIAL_TEAMS_RATING_KEYS = frozenset({
    'SPD', 'ACC', 'AGI', 'STR', 'AWR', 'PUR', 'TAK', 'BSH', 'RBK', 'IBL',
    'CTH', 'CAR', 'BCV', 'ELU', 'TRK', 'PRC', 'KPW', 'KAC',
})


def playbook_profile_path(playbook_dir, team, season=2025):
    """Resolve schedule/PBP team codes to the nflverse playbook filename vocabulary."""
    profile_team = gridiron_bridge.nfl_team_codes.to_nflverse_team_code(team)
    return str(Path(playbook_dir) / f'{profile_team}-{season}.json')


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
        self.profile_paths = {team: playbook_profile_path(playbook_dir, team) for team in self.teams}
        self.playbook_manifest = str(playbook_manifest)
        self.participation_sha256 = participation_sha256
        self.field = participation_field.Field.load(participation_path, participation_sha256)
        self.engine_root = str(engine_root)
        self.ratings_path = ratings_path
        self.coaching_profiles = coaching_profiles or {}
        self.session = gridiron_bridge.GridironSession(self.engine_root)
        self.event_switches = EventExpansionSwitches()
        self.event_manifest_sha256 = hashlib.sha256(
            f'{self.session.commit}:{gridiron_bridge.PLAYBOOK_MANIFEST_SHA256}:{participation_sha256}'.encode()
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
            family = selected if selected in ('run', 'pass') else self._choose_family(state, side, self.play_index)
            call_state = {**state, 'offense_direction': context['direction']}
            call, provenance = gridiron_bridge.build_call(
                self.snapshot_path, self.field, self.participation_sha256,
                self.profile_paths, self.playbook_manifest,
                seed=self._decision_seed(self.play_index, 'gridiron'), family=family, state=call_state,
                ratings_path=self._rating_profile_path())
            result, timing = self.session.play(call)
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
        pass_interference = next((item for item in events if item['type'] == 'pass_interference'), None)
        if (pass_interference is None
                and abs(final_x - (los_x + direction * outcome['yards_gained'])) > 0.003):
            raise ValueError('gridiron_final_spot_mismatch')
        thrown = next((item for item in events if item['type'] == 'throw'), None)
        caught = next((item for item in events if item['type'] == 'catch'), None)
        interception = next((item for item in events if item['type'] == 'interception'), None)
        reason = outcome['event']
        if interception is not None and fumble is not None:
            raise ValueError('gridiron_interception_return_fumble_sequence_unsupported')
        if pass_interference is not None:
            if (family != 'pass' or thrown is None
                    or not isinstance(pass_interference.get('spot'), dict)):
                raise ValueError('gridiron_pass_interference_terminal_facts_invalid')
        if outcome['turnover']:
            if interception and fumble is None:
                event = 'interception'
            elif fumble is not None and fumble.get('recovery_side') == 'D':
                event = ('sack' if reason == 'sack' or result.get('participants', {}).get('sackers') else
                         'run' if family == 'run' or not thrown else 'pass_complete')
            else:
                raise ValueError('gridiron_turnover_without_interception_or_defensive_fumble_recovery')
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
        if fumble is not None:
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
        if event == 'interception':
            receiving_yl = final_x if direction == 1 else 100 - final_x
            spot = int(round(receiving_yl))
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
        if fumble is not None:
            row['participants'].update({
                'fumbler_id': fumble['fumbler_id'],
                'recoverer_id': fumble['recoverer_id'],
                'returner_id': fumble['recoverer_id'] if fumble['recovery_side'] == 'D' else None,
                'fumble_spot_yards_gained': gain,
                'fumble_recovery_team': state['defense'] if fumble['recovery_side'] == 'D' else state['offense'],
                'fumble_return_yards': fumble.get('return_yards') if fumble['recovery_side'] == 'D' else None,
            })
            if event == 'run':
                row['participants']['rushing_yards'] = gain
            elif event == 'pass_complete':
                row['participants']['passing_yards'] = gain
                row['participants']['receiving_yards'] = gain
        if pass_interference is not None:
            defender_id = pass_interference.get('defender_id')
            roster_rows = {p['gsis_id']: p for side in ('home', 'away')
                           for p in self.snapshot['rosters'][side]['players']}
            defender = roster_rows.get(defender_id)
            if defender is None:
                raise ValueError('gridiron_pass_interference_defender_not_in_frozen_roster')
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
                     'ceg_event': asdict(event_record),
                     'viewer': 'gridiron_result.trajectory.frames'}
        return {'event': event, 'row': row, 'clock_runoff_seconds': runoff, 'spot': spot,
                'execution': execution, 'event_record': event_record}

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
        players = result.get('participants', {})
        offense_players = call['offense']['lineup']
        fumble_info = outcome.get('fumble')
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
        returner_id = recoverer_id if fumble_info and fumble_info.get('recovery_side') == 'D' else None
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
            fumble_y = int(round(100 - fumble_x if direction == 1 else fumble_x))
            recovery_y = int(round(100 - recovery_x if direction == 1 else recovery_x))
            dead_y = int(round(100 - dead_spot_x if direction == 1 else dead_spot_x))
            fumble_role = 'offense' if recovery_side == 'O' else 'defense'
            if recovery_side == 'O':
                possession = ceg_contract.PossessionV2(
                    team='offense', how='kept', recovery_spot_yardline_100=recovery_y,
                    dead_ball_yardline_100=dead_y, recovered_by=ceg_contract.PlayerRoleV2.named(recoverer_id),
                    fumble_spot_yardline_100=fumble_y)
            else:
                return_yards = int(round(dead_y - recovery_y))
                if fumble_info.get('return_yards') is not None and int(round(fumble_info['return_yards'])) != return_yards:
                    raise ValueError('gridiron_fumble_return_yards_disagree_with_endpoint')
                possession = ceg_contract.PossessionV2(
                    team='defense', how='fumble_recovery', turnover_spot_yardline_100=fumble_y,
                    recovery_spot_yardline_100=recovery_y, dead_ball_yardline_100=dead_y,
                    return_yards=return_yards,
                    recovered_by=ceg_contract.PlayerRoleV2.named(recoverer_id),
                    returner=ceg_contract.PlayerRoleV2.named(recoverer_id),
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
            event=ceg_event, yards_gained=yards, air_yards=air_yards,
            yards_after_catch=yac, possession=possession, scoring=scoring,
            fumble=fumble_info is not None, penalty=penalty, provenance=provenance,
            clock=ceg_contract.ClockV2(
                runoff_seconds=max(1, math.ceil(outcome['elapsed_seconds'])) +
                (0 if reason in ('out_of_bounds', 'incomplete', 'touchdown', 'safety') else 27),
                live_seconds=max(1, math.ceil(outcome['elapsed_seconds'])),
                dead_ball_seconds=(0 if reason in ('out_of_bounds', 'incomplete', 'touchdown', 'safety') else 27),
                stop_class=('stopped' if reason in ('out_of_bounds', 'incomplete', 'touchdown', 'safety')
                            else 'running')),
            out_of_bounds=reason == 'out_of_bounds', players=roles,
            probabilities=({'dpi_decision': penalty_decision} if penalty_decision else {}))

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
        fumble = outcome.get('fumble')
        carrier = (fumble.get('fumbler_id') if fumble else None) or outcome.get('carrier_id')
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
        if fumble:
            fumbler = roster_rows.get(fumble.get('fumbler_id'), {})
            recoverer = roster_rows.get(fumble.get('recoverer_id'), {})
            returner = recoverer if fumble.get('recovery_side') == 'D' else {}
            participants.update({
                'fumbler_id': fumble.get('fumbler_id'),
                'recoverer_id': fumble.get('recoverer_id'),
                'returner_id': fumble.get('recoverer_id') if returner else None,
                'fumbler_name': fumbler.get('player_name'),
                'fumbler_position': fumbler.get('pos_abb'),
                'fumbler_team': fumbler.get('team'),
                'fumbler_side': side if fumbler.get('team') == team else defense,
                'recoverer_name': recoverer.get('player_name'),
                'recoverer_position': recoverer.get('pos_abb'),
                'recoverer_team': recoverer.get('team'),
                'recoverer_side': side if recoverer.get('team') == team else defense,
                'returner_name': returner.get('player_name'),
                'returner_position': returner.get('pos_abb'),
                'returner_team': returner.get('team'),
                'returner_side': defense if returner else None,
            })
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
        player_rows = {p['gsis_id']: p for p in (*kicking_roster, *receiving_roster)}
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
        try:
            call, player_rows, rating_provenance = self._special_teams_call(
                kind, kicking_club, receiving_club, yardline_100, play_index)
            result, timing = self.session.special_teams(call)
        except (OSError, TypeError, ValueError) as exc:
            return {'blocker': str(exc)}
        facts = result['result']
        if kind == 'kickoff' and facts.get('returner_id') is None and facts['result'] not in ('touchback', 'muff'):
            if facts['result'] == 'out_of_bounds':
                out_spot = int(facts['dead_ball_yardline_100'])
                distance = 30 if free_kick_kind == 'safety_free_kick' else 25
                legal_options = [('inbounds_spot', out_spot),
                                 ('30_yards_from_safety_kick' if distance == 30 else '25_yards_from_kick',
                                  int(yardline_100) - distance)]
                legal_options = [(name, spot) for name, spot in legal_options if 0 < spot < 100]
                if not legal_options:
                    return {'blocker': 'autonomous_kickoff_out_of_bounds_has_no_legal_restart_spot'}

                def expected_points(dead_spot):
                    yards_to_goal = 100 - dead_spot
                    return max(0.0, 5.5 - 0.072 * yards_to_goal)

                quality = self.coaching_quality(receiving_side, 'kickoff')
                best = max(legal_options, key=lambda item: (expected_points(item[1]), item[0]))
                worst = min(legal_options, key=lambda item: (expected_points(item[1]), item[0]))
                choose_best = random.Random(self._decision_seed(
                    play_index, 'kickoff_out_of_bounds_option')).random() < quality / 100
                restart_option, enforced_spot = best if choose_best else worst
                facts = {**facts, 'out_of_bounds_spot_yardline_100': out_spot,
                         'dead_ball_yardline_100': enforced_spot,
                         'restart_option': restart_option,
                         'restart_options': [{'option': name, 'dead_ball_yardline_100': spot,
                                              'expected_points': round(expected_points(spot), 3)}
                                             for name, spot in legal_options],
                         'decision': {'coaching_quality': quality,
                                      'selected_best_option': choose_best,
                                      'information_available': ['kick_spot', 'out_of_bounds_spot',
                                                                'safety_kick_status', 'rule_options']}}
                result = {**result, 'result': facts}
            else:
                return {'blocker': 'autonomous_kickoff_downed_ball_recovery_not_integrated',
                        'execution': {'call': call, 'result': result, 'timing': timing,
                                      'rating_provenance': rating_provenance,
                                      'viewer': 'gridiron_result.trajectory.frames'}}
        named = lambda pid: (ceg_contract.PlayerRoleV2.named(pid) if pid
                             else ceg_contract.PlayerRoleV2.none())
        returner = named(facts.get('returner_id'))
        recoverer = named(facts.get('recoverer_id'))
        result_name = facts['result']
        recovery_team = facts.get('recovery_team')
        possession_after = facts.get('possession_after')
        unsupported_result = {
            'downed': 'punt_result_requires_ceg_play_2_extension:downed',
            'fair_catch': 'punt_result_requires_ceg_play_2_extension:fair_catch',
            'out_of_bounds': f'{kind}_out_of_bounds_requires_ceg_play_2_extension',
        }.get(result_name)
        if unsupported_result:
            return {'blocker': unsupported_result,
                    'execution': {'call': call, 'result': result, 'timing': timing,
                                  'rating_provenance': rating_provenance,
                                  'viewer': 'gridiron_result.trajectory.frames'}}
        if facts.get('scoring') == 'safety':
            return {'blocker': 'kick_safety_unsupported',
                    'execution': {'call': call, 'result': result, 'timing': timing,
                                  'rating_provenance': rating_provenance,
                                  'viewer': 'gridiron_result.trajectory.frames'}}
        if result_name == 'muff' and facts.get('return_yards') not in (None, 0):
            return {'blocker': 'muff_return_yardage_attribution_unsupported',
                    'execution': {'call': call, 'result': result, 'timing': timing,
                                  'rating_provenance': rating_provenance,
                                  'viewer': 'gridiron_result.trajectory.frames'}}
        if result_name == 'muff' and facts.get('scoring') == 'touchdown':
            return {'blocker': 'muff_return_touchdown_attribution_unsupported',
                    'execution': {'call': call, 'result': result, 'timing': timing,
                                  'rating_provenance': rating_provenance,
                                  'viewer': 'gridiron_result.trajectory.frames'}}
        if result_name == 'blocked' and facts.get('scoring') == 'touchdown':
            return {'blocker': 'blocked_return_touchdown_attribution_unsupported',
                    'execution': {'call': call, 'result': result, 'timing': timing,
                                  'rating_provenance': rating_provenance,
                                  'viewer': 'gridiron_result.trajectory.frames'}}
        kick_kind = 'field_goal' if kind == 'field_goal' else kind
        event_name = 'field_goal_attempt' if kind == 'field_goal' else kind
        kick = ceg_contract.KickV2(
            kick_kind, kicking_side, receiving_side, int(yardline_100), facts.get('distance_yards'),
            result_name, possession_after=possession_after,
            recovery_team=recovery_team,
            recovery_yardline_100=facts.get('recovery_yardline_100'),
            return_start_yardline_100=facts.get('return_start_yardline_100'),
            dead_ball_yardline_100=facts.get('dead_ball_yardline_100'),
            return_yards=facts.get('return_yards'),
            receiving_team_touched_beyond_line=facts.get('receiving_team_touched_beyond_line'),
            returner=returner, recoverer=recoverer,
            out_of_bounds=bool(facts.get('out_of_bounds')),
            fumble_spot_yardline_100=facts.get('fumble_spot_yardline_100'))
        elapsed = max(0, int(math.ceil(facts.get('live_elapsed_seconds', facts.get('elapsed_seconds')) or 0)))
        runoff = max(0, int(facts.get('clock_runoff_seconds') or 0))
        live_seconds, dead_seconds = runoff, 0
        clock = ceg_contract.ClockV2(runoff, live_seconds, dead_seconds, 'stopped')
        score_role = facts.get('scoring_team')
        score = (ceg_contract.ScoringV2('field_goal', 'kicking_team')
                 if kind == 'field_goal' and facts.get('scoring') == 'field_goal' else
                 ceg_contract.ScoringV2(facts['scoring'], score_role)
                 if facts.get('scoring') in ('touchdown', 'safety')
                 and score_role in ('kicking_team', 'receiving_team') else
                 ceg_contract.ScoringV2('touchdown', 'receiving_team')
                 if facts.get('scoring') == 'touchdown' else None)
        roles = (ceg_contract.PlayerRolesV2(punter=named(call['lineups']['kicking'].get('punter')),
                                            returner=returner, recoverer=recoverer)
                 if kind == 'punt' else
                 ceg_contract.PlayerRolesV2(kicker=named(call['lineups']['kicking'].get('kicker')),
                                            returner=returner, recoverer=recoverer))
        provenance = ceg_contract.ProvenanceV2(
            generator='gridiron.autonomous_special_teams', version='v1',
            manifest_sha256=self.event_manifest_sha256,
            components=('player_rating', 'authored_kick_model', 'live_player_execution', 'field_geometry'),
            draw_ids=(f"{self.seed}:{play_index}:{kind}",))
        event_record = ceg_contract.GeneratedPlayV2(
            contract=ceg_contract.CONTRACT_V2_VERSION,
            call=ceg_contract.PlayCallV2(kick_kind, provenance=provenance),
            event=event_name, yards_gained=None, provenance=provenance, clock=clock,
            fumble=(result_name == 'muff'), scoring=score, kick=kick, players=roles,
            probabilities=({'fair_catch': True} if facts.get('fair_catch') else {}))
        participants = {'attribution': 'autonomous_execution',
                        'returner_id': facts.get('returner_id'),
                        'recoverer_id': facts.get('recoverer_id'),
                        'return_touchdown': facts.get('scoring') == 'touchdown',
                        'fair_catch': bool(facts.get('fair_catch')),
                        'out_of_bounds': bool(facts.get('out_of_bounds')),
                        'kickoff_out_of_bounds_restart_option': facts.get('restart_option')}
        for role, pid in (('punter' if kind == 'punt' else 'kicker',
                           call['lineups']['kicking'].get('punter' if kind == 'punt' else 'kicker')),
                          ('returner', facts.get('returner_id')),
                          ('recoverer', facts.get('recoverer_id'))):
            if pid is None:
                continue
            player = player_rows.get(pid, {})
            participants.update({f'{role}_{field}': player.get(key) for field, key in (
                ('name', 'player_name'), ('position', 'pos_abb'), ('team', 'team'))})
            participants[f'{role}_side'] = (kicking_side if player.get('team') == kicking_club
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
            play_state = {'offense': side, 'defense': opponent, 'down': 1, 'togo': 2, 'yl': 98,
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
                                    'family': family, 'player_ids': generated['participants']}}
            participants = generated.get('participants') or {}
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
