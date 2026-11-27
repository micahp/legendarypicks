"""Translate frozen SLC football states into pinned live Gridiron executions.

Historical playbook outcomes are reduced to team-season tendencies only;
player assignments and play results come from the live executor.
"""
import argparse
import hashlib
import json
import math
import random
import subprocess
import time
from pathlib import Path

import game_stats
import live_participation
import participation_field
import pregame_snapshot
import reducer
import roster_preflight
import v1_complete_roster
from scripts import nfl_team_codes

ENGINE_COMMIT = 'f1fbfab564bca29855247f9756235a1d9b875e99'
PLAYBOOK_MANIFEST_SHA256 = '220af2a590b2e7ddf5c28a32977aadd4d5a5e6e128ca8392da8bac37ef0917ac'
DEFENSE_SLOTS = ('LEDGE', 'LDT', 'RDT', 'REDGE', 'MLB', 'WLB', 'NB', 'LCB', 'RCB', 'SS', 'FS')
DEFENSE_POSITION_CANDIDATES = {
    'LEDGE': ('LDE', 'RDE', 'DE', 'EDGE', 'LOLB', 'ROLB', 'OLB'),
    'LDT': ('LDT', 'NT', 'DT', 'RDT'),
    'RDT': ('RDT', 'NT', 'DT', 'LDT'),
    'REDGE': ('RDE', 'LDE', 'DE', 'EDGE', 'ROLB', 'LOLB', 'OLB'),
    'MLB': ('MLB', 'ILB', 'RILB', 'LILB'),
    'WLB': ('WLB', 'SLB', 'RILB', 'LILB', 'OLB'),
    'NB': ('NB', 'CB', 'LCB', 'RCB', 'SS', 'FS', 'S'),
    'LCB': ('LCB', 'CB', 'RCB'),
    'RCB': ('RCB', 'CB', 'LCB'),
    'SS': ('SS', 'S', 'FS'),
    'FS': ('FS', 'S', 'SS'),
}
DEFENSE_POSITION_FALLBACKS = {
    # Some current rosters identify a 3-4 end as LDE/RDE instead of DT. If a
    # team has only one eligible interior label, its next interior assignment
    # can use a distinct eligible end in the authored nickel front.
    'LDT': ('LDE', 'RDE', 'DE', 'EDGE'),
    'RDT': ('LDE', 'RDE', 'DE', 'EDGE'),
}
GENERIC_DEFENSE_POSITIONS = {
    'LEDGE': ('DL',), 'REDGE': ('DL',), 'LDT': ('DL',), 'RDT': ('DL',),
    'MLB': ('LB',), 'WLB': ('LB',), 'NB': ('DB',), 'LCB': ('DB',),
    'RCB': ('DB',), 'SS': ('DB',), 'FS': ('DB',),
}
EXAMPLE_ASSIGNMENT_COVERAGE = {'cover_1': 'man', 'cover_3': 'zone'}
MIN_COVERAGE_ASSIGNMENTS = {'cover_1': ('man', 1), 'cover_3': ('zone', 3)}
COMMON_LIVE_RATINGS = ('SPD', 'ACC', 'AGI', 'STR', 'AWR')
OFFENSE_LIVE_RATINGS = {
    'QB': ('THA',),
    'RB': ('BCV', 'BTK', 'CAR', 'ELU'),
    'WR': ('CTH',),
    'TE': ('CTH',),
    'LT': ('PBK', 'RBK', 'IBL'), 'LG': ('PBK', 'RBK', 'IBL'),
    'C': ('PBK', 'RBK', 'IBL'), 'RG': ('PBK', 'RBK', 'IBL'),
    'RT': ('PBK', 'RBK', 'IBL'),
}
SCRIMMAGE_RATING_KEYS = frozenset({
    'SPD', 'ACC', 'AGI', 'STR', 'AWR', 'RBK', 'IBL', 'PBK', 'BSH', 'PMV', 'FMV',
    'TAK', 'BTK', 'ELU', 'BCV', 'TRK', 'PUR', 'CAR', 'PRC', 'CTH', 'CIT', 'THA',
})
CEG_CONTRACT_V3_COMMIT = '1aeabdba'
CEG_CONTRACT_V3_SHA256 = 'e4339c033a5933be74cf38492f83b21d8e63822d238ffa1cd2ccf0e6431abc35'


def _scrimmage_ratings(ratings, *, family, player_id, quarterback_id):
    """Pass only ratings accepted by the pinned scrimmage schema and concept."""
    supported = {name: value for name, value in ratings.items() if name in SCRIMMAGE_RATING_KEYS}
    if family == 'run' or player_id != quarterback_id:
        supported.pop('THA', None)
    if family == 'pass':
        for name in ('IBL', 'BCV', 'TRK', 'CIT'):
            supported.pop(name, None)
    return supported


def _player_roles(offense_roles, defense_slots):
    """Index all 22 selected players by their executor role."""
    roles = {player_id: role for player_id, role in offense_roles.items()}
    roles.update({player_id: role for role, player_id in defense_slots.items()})
    return roles


def _validate_player_ratings(player_id, role, ratings, family):
    if role in OFFENSE_LIVE_RATINGS:
        required = list(COMMON_LIVE_RATINGS)
        required.extend(name for name in OFFENSE_LIVE_RATINGS[role]
                        if name != 'THA' or family == 'pass')
    elif role in ('LEDGE', 'LDT', 'RDT', 'REDGE'):
        required = [*COMMON_LIVE_RATINGS, 'BSH', 'FMV', 'PMV']
    elif role in ('MLB', 'WLB', 'NB', 'LCB', 'RCB', 'SS', 'FS'):
        required = [*COMMON_LIVE_RATINGS, 'PRC', 'PUR', 'TAK']
    else:
        raise ValueError(f'gridiron_bridge_player_role_missing:{player_id}:{role}')
    for name in required:
        if type(ratings.get(name)) is not int or not 1 <= ratings[name] <= 99:
            raise ValueError(f'gridiron_bridge_player_rating_missing:{player_id}:{name}')


def _validate_coverage_assignments(call):
    """Reject explicit passing assignments that contradict the declared shell."""
    offense_call = call.get('offense', {}).get('call', {})
    if offense_call.get('family') != 'pass' or offense_call.get('concept') != 'assigned':
        return
    coverage = call.get('defense', {}).get('call', {}).get('coverage')
    requirement = MIN_COVERAGE_ASSIGNMENTS.get(coverage)
    if requirement is None:
        raise ValueError('gridiron_bridge_coverage_assignment_unsupported:' + str(coverage))
    assignments = call.get('assignments')
    defense = assignments.get('defense') if isinstance(assignments, dict) else None
    if not isinstance(defense, dict):
        raise ValueError('gridiron_bridge_coverage_assignments_missing:' + str(coverage))
    kind, minimum = requirement
    actual = sum(1 for task in defense.values()
                 if isinstance(task, dict) and task.get('kind') == kind)
    if actual < minimum:
        raise ValueError(f'gridiron_bridge_coverage_assignment_mismatch:{coverage}:{kind}_count_{actual}_min_{minimum}')


def _defensive_lineup(resolved, roster):
    """Resolve authored nickel roles against equivalent roster position labels."""
    allowed = v1_complete_roster.eligible_ids(resolved)
    selected = {}
    for slot in DEFENSE_SLOTS:
        position_groups = [DEFENSE_POSITION_CANDIDATES[slot]]
        if slot in DEFENSE_POSITION_FALLBACKS:
            position_groups.append(DEFENSE_POSITION_FALLBACKS[slot])
        position_groups.append(GENERIC_DEFENSE_POSITIONS[slot])
        choices = []
        for group in position_groups:
            for position in group:
                choices = [p for p in roster if p.get('gsis_id') in allowed and p.get('gsis_id') not in selected
                           and p.get('pos_abb') == position
                           and type(p.get('pos_rank')) is int and p['pos_rank'] > 0]
                if choices:
                    break
            if choices:
                break
        if not choices:
            raise ValueError('gridiron_live_defense_role_unresolved:' + slot)
        choices.sort(key=lambda p: (p['pos_rank'], p['gsis_id']))
        selected[choices[0]['gsis_id']] = slot
    return selected


def _add_offensive_line(players, roster):
    for role in ('LT', 'LG', 'C', 'RG', 'RT'):
        rows = [p for p in roster if p['gsis_id'] not in players and p['pos_abb'] == role]
        if not rows:
            compatible = {'LT': ('OT', 'T', 'OL'), 'RT': ('OT', 'T', 'OL'),
                          'LG': ('G', 'OG', 'OL'), 'RG': ('G', 'OG', 'OL'), 'C': ('OL',)}[role]
            rows = [p for p in roster if p['gsis_id'] not in players and p['pos_abb'] in compatible]
        if not rows:
            raise ValueError('gridiron_missing_line_role:' + role)
        rank = min(p['pos_rank'] for p in rows)
        best = {p['gsis_id'] for p in rows if p['pos_rank'] == rank}
        if len(best) != 1 and any(p.get('rank_source') != 'unranked_sort_only'
                                  for p in rows if p['pos_rank'] == rank):
            raise ValueError('gridiron_ambiguous_line_role:' + role)
        players[sorted(best)[0]] = role
    return players


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_engine(root):
    root = Path(root)
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != ENGINE_COMMIT:
        raise ValueError('gridiron_engine_commit_mismatch:' + commit)
    if subprocess.run(['git', '-C', str(root), 'diff', '--quiet', 'HEAD', '--', 'engine'], check=False).returncode:
        raise ValueError('gridiron_engine_modified')
    return commit


def _check_ceg_contract_v3():
    path = Path(__file__).resolve().with_name('ceg_contract_v3.py')
    if not path.is_file() or _sha(path) != CEG_CONTRACT_V3_SHA256:
        raise ValueError('ceg_play_3_contract_hash_mismatch')
    return CEG_CONTRACT_V3_COMMIT


def _profile(path, manifest_path, season, team):
    if _sha(manifest_path) != PLAYBOOK_MANIFEST_SHA256:
        raise ValueError('gridiron_playbook_manifest_hash_mismatch')
    manifest = json.loads(Path(manifest_path).read_text())
    playbook_team = nfl_team_codes.to_nflverse_team_code(team)
    matches = [row for row in manifest.get('team_seasons', []) if row.get('team') == playbook_team
               and int(row.get('season', -1)) == season - 1 and row.get('output') == Path(path).name]
    if len(matches) != 1 or _sha(path) != matches[0].get('output_sha256'):
        raise ValueError('gridiron_playbook_hash_or_identity_mismatch')
    profile = json.loads(Path(path).read_text())
    if profile.get('team_id') != playbook_team or int(profile.get('season', -1)) != season - 1:
        raise ValueError('gridiron_playbook_cutoff_invalid')
    # Only the pregame aggregate is read; never pass observed plays or outcomes.
    rate = profile['offense']['profile']['run_pass']['categories']['pass']['rate']
    if not isinstance(rate, (float, int)) or not 0 <= rate <= 1:
        raise ValueError('gridiron_playbook_prior_invalid')
    return {'team': team, 'playbook_team_code': playbook_team,
            'season': season - 1, 'pass_rate': rate, 'sha256': _sha(path),
            'manifest_sha256': _sha(manifest_path), 'use': 'prior_season_aggregate_only'}


_RATING_CACHE = {}


def _ratings(path):
    if path is None:
        return {}, {}
    path = Path(path)
    key = (str(path.resolve()), path.stat().st_mtime_ns)
    if key not in _RATING_CACHE:
        payload = json.loads(path.read_text())
        rows = payload.get('players', {})
        _RATING_CACHE.clear()
        meta = payload.get('meta', {})
        _RATING_CACHE[key] = ({row['gsis']: row for row in rows.values() if row.get('gsis')},
                              {'dataset': path.name, 'season': meta.get('season'),
                               'through_week': meta.get('through_week'),
                               'game_id': meta.get('game_id'),
                               'as_of': meta.get('cutoff_utc'),
                               'schema': meta.get('schema'),
                               'source_class': meta.get('rating_source_class', 'estimated'),
                               'evidence_source_class': meta.get('evidence_source_class', 'nfl_derived'),
                               'roster_snapshot_sha256': meta.get('roster_snapshot_sha256'),
                               'source': 'provenance_aware_player_ratings'})
    return _RATING_CACHE[key]


def build_call(snapshot_path, field_path, field_hash, profile_path, manifest_path, *, seed, family, state,
               ratings_path=None, prepared_participation=None, resolved_rosters=None):
    snapshot = pregame_snapshot.load_frozen_snapshot(snapshot_path)
    resolved = resolved_rosters
    if resolved is None:
        checks, resolved = roster_preflight.check(snapshot)
        if roster_preflight.failed(checks) or roster_preflight.exclusions_applied(snapshot, resolved)[1] != 'PASS':
            raise ValueError('gridiron_roster_preflight_failed')
    team_by_side = {'home': snapshot['schedule']['home_team'], 'away': snapshot['schedule']['away_team']}
    if state['offense'] in ('A', 'B'):
        offense_team = team_by_side['home' if state['offense'] == 'A' else 'away']
        defense_team = team_by_side['home' if state['defense'] == 'A' else 'away']
    else:
        offense_team, defense_team = state['offense'], state['defense']
    side_by_team = {team: side for side, team in team_by_side.items()}
    if offense_team not in side_by_team or defense_team not in side_by_team or offense_team == defense_team:
        raise ValueError('gridiron_bridge_team_identity_mismatch')
    offense_side, defense_side = side_by_team[offense_team], side_by_team[defense_team]
    if family not in ('run', 'pass', 'prior'):
        raise ValueError('gridiron_bridge_family_unsupported')
    season = int(snapshot['schedule']['season'])
    selected_profile_path = profile_path.get(offense_team) if isinstance(profile_path, dict) else profile_path
    if selected_profile_path is None:
        raise ValueError('gridiron_team_playbook_profile_missing:' + offense_team)
    prior = _profile(selected_profile_path, manifest_path, season, offense_team)
    selection = 'explicit_supported_concept'
    if family == 'prior':
        family = 'pass' if random.Random(f'slc-gridiron-prior:{seed}').random() < prior['pass_rate'] else 'run'
        selection = 'seeded_prior_season_team_pass_rate'
    field = (field_path if isinstance(field_path, participation_field.Field)
             else participation_field.Field.load(field_path, field_hash))
    roster = v1_complete_roster.eligible_rows(resolved[offense_side])
    selected = prepared_participation
    if selected is None:
        selected = live_participation.advance(field, team=offense_team, season=season, resolved=resolved[offense_side],
                                              roster=roster, group='11', seed=seed)
    elif (selected['team'] != offense_team or selected['group'] != '11' or
          selected['source_sha256'] != field.sha256):
        raise ValueError('gridiron_prepared_participation_mismatch')
    allowed = v1_complete_roster.eligible_ids(resolved[offense_side])
    players = {selected['qb1']: 'QB', **selected['slots']}
    if not set(players).issubset(allowed):
        raise ValueError('gridiron_prepared_participation_ineligible')
    _add_offensive_line(players, roster)
    slots = {role: next(pid for pid, value in players.items() if value == role)
             for role in ('QB', 'RB', 'TE', 'LT', 'LG', 'C', 'RG', 'RT')}
    receivers = sorted(pid for pid, role in players.items() if role == 'WR')
    if len(players) != 11 or len(receivers) != 3:
        raise ValueError('gridiron_offensive_group_unsupported')
    slots.update({f'WR{i + 1}': pid for i, pid in enumerate(receivers)})
    dslots = _defensive_lineup(resolved[defense_side], v1_complete_roster.eligible_rows(resolved[defense_side]))
    dslots = {slot: next(pid for pid, value in dslots.items() if value == slot) for slot in DEFENSE_SLOTS}
    player_roles = _player_roles(players, dslots)
    ids = list(slots.values()) + list(dslots.values())
    if len(ids) != 22 or len(set(ids)) != 22:
        raise ValueError('gridiron_lineup_not_unique')
    # Gridiron uses absolute x despite the contract field's name. For +x offense,
    # LP's offense-relative yardline_100 maps to 100 - yardline_100.
    direction = state.get('offense_direction', 1)
    if direction not in (-1, 1):
        raise ValueError('gridiron_bridge_offense_direction_invalid')
    x = 100 - int(state['yl']) if direction == 1 else int(state['yl'])
    rating_rows, rating_source = _ratings(ratings_path)
    if rating_source.get('schema') == 'gridiron-player-ratings-provenance-v1':
        if (rating_source.get('game_id') != snapshot['schedule']['game_id']
                or rating_source.get('as_of') != snapshot.get('as_of')
                or rating_source.get('roster_snapshot_sha256') != _sha(snapshot_path)
                or rating_source.get('through_week') != int(snapshot['schedule']['week']) - 1):
            raise ValueError('gridiron_bridge_player_rating_provenance_mismatch')
    rating_ids = {}
    player_profiles = {}
    for pid in ids:
        record = rating_rows.get(pid)
        if not isinstance(record, dict):
            raise ValueError('gridiron_bridge_player_rating_profile_missing:' + pid)
        ratings = dict(record.get('ratings', {}))
        role = player_roles.get(pid)
        _validate_player_ratings(pid, role, ratings, family)
        mass = record.get('physics', {}).get('mass')
        if not isinstance(mass, (int, float)) or not math.isfinite(mass) or mass <= 0:
            raise ValueError('gridiron_bridge_player_physics_missing:' + pid)
        ratings = _scrimmage_ratings(ratings, family=family, player_id=pid,
                                     quarterback_id=slots['QB'])
        player_profiles[pid] = {'ratings': ratings,
                                 'physics': ({'mass': record['physics']['mass']}
                                             if record.get('physics', {}).get('mass') else {})}
        rating_ids[pid] = rating_source
    call = {'schema_version': 'gridiron.autonomous-play.v1', 'mode': 'autonomous_from_snap',
            'play_id': f"{snapshot['schedule']['game_id']}:{offense_team}:{family}:{seed}", 'seed': str(seed),
            'situation': {'quarter': state['quarter'], 'clock_seconds': state['clock'], 'down': state['down'],
                          'yards_to_go': state['togo'], 'yardline_100': x, 'offense_direction': direction,
                          'ball_lateral_yards': 160 / 6},
            'offense': {'team': offense_team, 'formation': 'singleback_11',
                        'call': {'family': family, 'concept': 'inside_zone' if family == 'run' else 'assigned',
                                 'direction': 'right', 'snap_type': 'under_center' if family == 'run' else 'shotgun'},
                        'lineup': slots},
            'defense': {'team': defense_team, 'call': {'front': 'nickel_over', 'coverage': 'cover_1', 'run_fit': 'spill_force'},
                        'lineup': dslots},
            'player_profiles': player_profiles}
    return call, {'snapshot_sha256': snapshot['snapshot_sha256'], 'snapshot_verified': snapshot['evaluation']['verified'],
                  'participation_sha256': field_hash, 'playbook_prior': prior,
                  'lineup_selection': selected, 'attribute_source': 'named_player_specific_estimated_ratings',
                  'concept_selection': selection, 'formation_selection': 'explicit_11_personnel',
                  'player_rating_sources': rating_ids,
                  'player_rating_coverage': len(rating_ids) / len(ids)}


def _validate_result(call, result):
    if result.get('schema_version') != 'gridiron.autonomous-result.v1' or result.get('status') != 'complete':
        raise ValueError('gridiron_play_incomplete:' + str(result.get('failure')))
    if not result.get('diagnostics', {}).get('reconciliation', {}).get('ok'):
        raise ValueError('gridiron_reconciliation_failed')
    if result['diagnostics'].get('outcome_inputs') != [] or result.get('seed') != str(call['seed']):
        raise ValueError('gridiron_outcome_or_seed_mismatch')
    expected = set(call['offense']['lineup'].values()) | set(call['defense']['lineup'].values())
    recorded = [p['id'] for p in result['trajectory']['roster']]
    if len(recorded) != 22 or set(recorded) != expected:
        raise ValueError('gridiron_result_roster_mismatch')
    if (result['call']['offense'] != call['offense']['team'] or result['call']['defense'] != call['defense']['team']
            or result['call']['concept'] != call['offense']['call']['concept']):
        raise ValueError('gridiron_result_call_mismatch')
    return result


def _validate_special_teams_result(call, result):
    if (result.get('schema_version') != 'gridiron.autonomous-special-teams.v1'
            or result.get('status') != 'complete' or result.get('kind') != call.get('kind')
            or result.get('seed') != str(call.get('seed'))):
        raise ValueError('gridiron_special_teams_incomplete:' + str(result.get('failure')))
    if result.get('diagnostics', {}).get('outcome_inputs') != []:
        raise ValueError('gridiron_special_teams_outcome_input_detected')
    if (result['diagnostics'].get('assignments_executed') != 22
            or result['diagnostics'].get('expected_assignments') != 22):
        raise ValueError('gridiron_special_teams_assignment_count_mismatch')
    expected = {call['lineups']['kicking']['punter' if call['kind'] == 'punt' else 'kicker'],
                *call['lineups']['kicking']['coverage'], call['lineups']['receiving']['returner'],
                *call['lineups']['receiving']['blockers']}
    roster = result.get('trajectory', {}).get('roster', [])
    if len(roster) != 22 or {row.get('id') for row in roster} != expected:
        raise ValueError('gridiron_special_teams_roster_mismatch')
    assigned = {event.get('player_id') for event in result.get('events', [])
                if event.get('type') == 'assignment_executed'}
    if assigned != expected:
        raise ValueError('gridiron_special_teams_assignments_missing')
    events = result.get('events', [])
    if not events or events[-1].get('type') != 'whistle':
        raise ValueError('gridiron_special_teams_whistle_missing')
    trajectory = result.get('trajectory', {})
    frames, stride = trajectory.get('frames'), trajectory.get('stride')
    if (not isinstance(frames, list) or not frames or type(stride) is not int
            or any(not isinstance(frame, list) or len(frame) != stride
                   or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in frame)
                   for frame in frames)):
        raise ValueError('gridiron_special_teams_trajectory_invalid')
    expected_results = (('made', 'missed', 'blocked') if call.get('kind') == 'field_goal'
                        else ('return', 'touchback', 'muff', 'downed', 'fair_catch', 'out_of_bounds'))
    if result.get('result', {}).get('result') not in expected_results:
        raise ValueError('gridiron_special_teams_result_classification_invalid')
    return result


class GridironSession:
    """One persistent, sequential engine process for many independent plays."""

    def __init__(self, engine_root, player_evaluation_mode=None):
        if player_evaluation_mode not in (None, 'legacy_sequential', 'shared_snapshot'):
            raise ValueError('gridiron_player_evaluation_mode_unsupported')
        self.player_evaluation_mode = player_evaluation_mode
        self.commit = _check_engine(engine_root)
        self.proc = subprocess.Popen(['node', str(Path(engine_root) / 'engine/autonomous/slc-server.js')],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.next_id = 0

    def request(self, op, **kwargs):
        self.next_id += 1
        request = {'id': self.next_id, 'op': op, **kwargs}
        try:
            self.proc.stdin.write(json.dumps(request, separators=(',', ':')) + '\n')
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        except (BrokenPipeError, OSError) as exc:
            raise ValueError('gridiron_server_failed') from exc
        if not line:
            raise ValueError('gridiron_server_closed')
        response = json.loads(line)
        if response.get('id') != self.next_id:
            raise ValueError('gridiron_server_response_id_mismatch')
        if not response.get('ok'):
            raise ValueError('gridiron_executor_failed:' + str(response.get('error')))
        return response

    def play(self, call):
        if call.get('offense', {}).get('call', {}).get('family') == 'run' and 'assignments' not in call:
            direction = call['offense']['call']['direction']
            call['assignments'] = self.request('example_run_assignments', direction=direction)['value']
        elif call.get('offense', {}).get('call', {}).get('concept') == 'assigned' and 'assignments' not in call:
            coverage = call.get('defense', {}).get('call', {}).get('coverage')
            assignment_coverage = EXAMPLE_ASSIGNMENT_COVERAGE.get(coverage)
            if assignment_coverage is None:
                raise ValueError('gridiron_bridge_example_assignment_coverage_unsupported:' + str(coverage))
            call['assignments'] = self.request(
                'example_assignments', concept='slant_flat', coverage=assignment_coverage,
                direction=call['offense']['call']['direction'])['value']
        _validate_coverage_assignments(call)
        mode = getattr(self, 'player_evaluation_mode', None)
        if mode is not None:
            call['player_evaluation_mode'] = mode
        start = time.monotonic()
        response = self.request('play', call=call)
        result = _validate_result(call, response['value'])
        if mode is not None and result.get('diagnostics', {}).get('player_evaluation_mode') != mode:
            raise ValueError('gridiron_player_evaluation_mode_mismatch')
        return result, {'engine_commit': self.commit,
                'elapsed_wall_seconds': time.monotonic() - start, 'engine_ms': response['engine_ms']}

    def special_teams(self, call):
        mode = getattr(self, 'player_evaluation_mode', None)
        if mode is not None:
            call['player_evaluation_mode'] = mode
        start = time.monotonic()
        response = self.request('special_teams', call=call)
        result = _validate_special_teams_result(call, response['value'])
        if mode is not None and result.get('diagnostics', {}).get('player_evaluation_mode') != mode:
            raise ValueError('gridiron_player_evaluation_mode_mismatch')
        return result, {'engine_commit': self.commit,
                'elapsed_wall_seconds': time.monotonic() - start, 'engine_ms': response['engine_ms']}

    def close(self):
        if self.proc.stdin:
            self.proc.stdin.close()
        if self.proc.stdout:
            self.proc.stdout.close()
        self.proc.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def run(engine_root, call):
    with GridironSession(engine_root) as session:
        return session.play(call)


def reduce_result(call, result, state):
    """Map supported live events to the SLC reducer and player stats at whistle."""
    direction = call['situation'].get('offense_direction')
    expected_direction = state.get('offense_direction', 1)
    expected_los = state['yl'] if direction == -1 else 100 - state['yl']
    if (direction not in (-1, 1) or direction != expected_direction
            or call['situation']['yardline_100'] != expected_los):
        raise ValueError('gridiron_coordinate_contract_mismatch')
    if any(call['situation'][key] != state[other] for key, other in
           (('quarter', 'quarter'), ('clock_seconds', 'clock'), ('down', 'down'), ('yards_to_go', 'togo'))):
        raise ValueError('gridiron_situation_contract_mismatch')
    if (call['offense']['team'], call['defense']['team']) != (state['offense'], state['defense']):
        raise ValueError('gridiron_team_contract_mismatch')
    outcome = result['result']
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in
           (outcome['yards_gained'], outcome['final_ball_spot']['x_yards'], outcome['elapsed_seconds'])) or outcome['elapsed_seconds'] <= 0:
        raise ValueError('gridiron_nonfinite_or_invalid_result')
    if not outcome['turnover'] and outcome['possession_team'] != call['offense']['team']:
        raise ValueError('gridiron_possession_mismatch')
    expected_final_x = call['situation']['yardline_100'] + direction * outcome['yards_gained']
    if abs(outcome['final_ball_spot']['x_yards'] - expected_final_x) > 0.003:
        raise ValueError('gridiron_final_spot_mismatch')
    events = result['events']
    if any(e['type'] in ('fumble', 'safety') for e in events):
        raise ValueError('gridiron_fumble_or_safety_unsupported')
    thrown = next((e for e in events if e['type'] == 'throw'), None)
    caught = next((e for e in events if e['type'] == 'catch'), None)
    interception = next((e for e in events if e['type'] == 'interception'), None)
    reason = outcome['event']
    if outcome['turnover']:
        if not interception or outcome['possession_team'] != call['defense']['team']:
            raise ValueError('gridiron_turnover_unsupported')
        event = 'interception'
    elif reason == 'incomplete':
        event = 'pass_incomplete'
    elif reason == 'sack':
        event = 'sack'
    elif call['offense']['call']['family'] == 'run':
        event = 'run'
    elif not thrown and outcome['carrier_id'] == call['offense']['lineup']['QB']:
        event = 'run'
    elif caught:
        event = 'pass_complete'
    else:
        raise ValueError('gridiron_result_classification_unsupported:' + str(reason))
    if reason not in ('tackle', 'out_of_bounds', 'incomplete', 'sack', 'touchdown', 'interception'):
        raise ValueError('gridiron_terminal_unsupported:' + str(reason))
    if outcome['is_touchdown'] and outcome['turnover']:
        raise ValueError('gridiron_defensive_touchdown_unsupported')
    gain = math.floor(outcome['yards_gained'])
    yards = gain if event in ('run', 'pass_complete', 'sack') else 0
    yards = min(state['yl'], max(state['yl'] - 100, yards))
    spot = 100 - state['yl'] + gain if event == 'interception' else None
    if spot is not None and not 1 <= spot <= 99:
        raise ValueError('gridiron_turnover_spot_unsupported')
    elapsed = math.ceil(outcome['elapsed_seconds'])
    if elapsed >= state['clock'] or (state['quarter'] in (2, 4) and state['clock'] > 120 >= state['clock'] - elapsed):
        raise ValueError('gridiron_clock_boundary_unsupported')
    after, terminal, flags = reducer.apply_play(state, event, yards, spot)
    if flags['safety']:
        raise ValueError('gridiron_safety_unsupported')
    if bool(flags['touchdown']) != bool(outcome['is_touchdown']):
        raise ValueError('gridiron_touchdown_disagreement')
    qb = call['offense']['lineup']['QB']
    offense_ids = set(call['offense']['lineup'].values())
    if event == 'run' and outcome['carrier_id'] not in offense_ids:
        raise ValueError('gridiron_rusher_not_on_offense')
    if caught and caught.get('player_id') not in offense_ids:
        raise ValueError('gridiron_receiver_not_on_offense')
    participants = {'passer_id': None if event == 'run' else qb,
                    'rusher_id': outcome['carrier_id'] if event == 'run' else None,
                    'receiver_id': caught.get('player_id') if caught else (thrown.get('target_id') if thrown else None),
                    'attribution': 'gridiron_autonomous'}
    play = {'event_type': event, 'state_before': {'yardline_100': state['yl']},
            'participants': participants, 'outcome': {'yards_gained': yards, **flags}}
    return {'play': play, 'state_at_whistle': after, 'terminal': terminal,
            'clock_at_whistle': state['clock'] - elapsed,
            'player_statistics': game_stats.player_lines([{'plays': [play]}]),
            'clock_scope': 'live_ball_only; next_snap_not_modelled'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('snapshot', 'participation', 'participation-sha256', 'playbook', 'manifest', 'engine', 'out'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--family', choices=('run', 'pass', 'prior'), default='prior')
    parser.add_argument('--state', required=True, help='JSON file containing the pre-snap SLC state')
    args = parser.parse_args()
    state = json.loads(Path(args.state).read_text())
    call, provenance = build_call(args.snapshot, args.participation, args.participation_sha256,
                                  args.playbook, args.manifest, seed=args.seed, family=args.family, state=state)
    result, timing = run(args.engine, call)
    output = {'schema_version': 'slc.gridiron-single-play.v1', 'call': call, 'provenance': provenance,
              'gridiron_result': result, 'slc_reduction': reduce_result(call, result, state), 'timing': timing}
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, separators=(',', ':')), encoding='utf-8')
    print(f'record {destination} sha256 {_sha(destination)}')


if __name__ == '__main__':
    main()
