"""One-play bridge to a pinned Gridiron autonomous executor.

This is a research boundary, not full-game execution. Historical playbook
outcomes are not passed to the executor. Clock output stops at the whistle.
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

ENGINE_COMMIT = '1800e843ccc59edb5f40ff090a2b4806f5ea630f'
PLAYBOOK_MANIFEST_SHA256 = '9d4749f817e97f4e3da0b6c5170eae0fa922d8b1b59d608ab4ce9dd990c2e929'
DEFENSE_POSITIONS = ('LDE', 'LDT', 'RDT', 'RDE', 'MLB', 'WLB', 'NB', 'LCB', 'RCB', 'SS', 'FS')
DEFENSE_SLOTS = ('LEDGE', 'LDT', 'RDT', 'REDGE', 'MLB', 'WLB', 'NB', 'LCB', 'RCB', 'SS', 'FS')


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


def _profile(path, manifest_path, season, team):
    if _sha(manifest_path) != PLAYBOOK_MANIFEST_SHA256:
        raise ValueError('gridiron_playbook_manifest_hash_mismatch')
    manifest = json.loads(Path(manifest_path).read_text())
    matches = [row for row in manifest.get('team_seasons', []) if row.get('team') == team
               and int(row.get('season', -1)) == season - 1 and row.get('output') == Path(path).name]
    if len(matches) != 1 or _sha(path) != matches[0].get('output_sha256'):
        raise ValueError('gridiron_playbook_hash_or_identity_mismatch')
    profile = json.loads(Path(path).read_text())
    if profile.get('team_id') != team or int(profile.get('season', -1)) != season - 1:
        raise ValueError('gridiron_playbook_cutoff_invalid')
    # Only the pregame aggregate is read; never pass observed plays or outcomes.
    rate = profile['offense']['profile']['run_pass']['categories']['pass']['rate']
    if not isinstance(rate, (float, int)) or not 0 <= rate <= 1:
        raise ValueError('gridiron_playbook_prior_invalid')
    return {'season': season - 1, 'pass_rate': rate, 'sha256': _sha(path),
            'manifest_sha256': _sha(manifest_path), 'use': 'prior_season_aggregate_only'}


def build_call(snapshot_path, field_path, field_hash, profile_path, manifest_path, *, seed, family, state):
    snapshot = pregame_snapshot.load_frozen_snapshot(snapshot_path)
    checks, resolved = roster_preflight.check(snapshot)
    if roster_preflight.failed(checks) or roster_preflight.exclusions_applied(snapshot, resolved)[1] != 'PASS':
        raise ValueError('gridiron_roster_preflight_failed')
    if snapshot['schedule']['game_id'] != '2026_11_MIN_SF':
        raise ValueError('gridiron_bridge_game_not_supported')
    if family not in ('run', 'pass', 'prior'):
        raise ValueError('gridiron_bridge_family_unsupported')
    season = int(snapshot['schedule']['season'])
    prior = _profile(profile_path, manifest_path, season, 'MIN')
    selection = 'explicit_supported_concept'
    if family == 'prior':
        family = 'pass' if random.Random(f'slc-gridiron-prior:{seed}').random() < prior['pass_rate'] else 'run'
        selection = 'seeded_prior_season_team_pass_rate'
    field = participation_field.Field.load(field_path, field_hash)
    roster = snapshot['rosters']['away']['players']
    selected = live_participation.advance(field, team='MIN', season=season, resolved=resolved['away'],
                                           roster=roster, group='11', seed=seed)
    allowed = v1_complete_roster.eligible_ids(resolved['away'])
    players = {selected['qb1']: 'QB', **selected['slots']}
    for role in ('LT', 'LG', 'C', 'RG', 'RT'):
        rows = [p for p in roster if p['gsis_id'] in allowed and p['gsis_id'] not in players
                and p['pos_abb'] == role and type(p['pos_rank']) is int and p['pos_rank'] > 0]
        if not rows:
            raise ValueError('gridiron_missing_line_role:' + role)
        rank = min(p['pos_rank'] for p in rows)
        best = {p['gsis_id'] for p in rows if p['pos_rank'] == rank}
        if len(best) != 1:
            raise ValueError('gridiron_ambiguous_line_role:' + role)
        players[best.pop()] = role
    slots = {role: next(pid for pid, value in players.items() if value == role)
             for role in ('QB', 'RB', 'TE', 'LT', 'LG', 'C', 'RG', 'RT')}
    receivers = sorted(pid for pid, role in players.items() if role == 'WR')
    if len(players) != 11 or len(receivers) != 3:
        raise ValueError('gridiron_offensive_group_unsupported')
    slots.update({f'WR{i + 1}': pid for i, pid in enumerate(receivers)})
    defense = live_participation.defense_lineup(resolved=resolved['home'], roster=snapshot['rosters']['home']['players'],
                                                positions=DEFENSE_POSITIONS)['players']
    dslots = {slot: next(pid for pid, value in defense.items() if value == role)
              for slot, role in zip(DEFENSE_SLOTS, DEFENSE_POSITIONS)}
    ids = list(slots.values()) + list(dslots.values())
    if len(ids) != 22 or len(set(ids)) != 22:
        raise ValueError('gridiron_lineup_not_unique')
    # Gridiron uses absolute x despite the contract field's name. For +x offense,
    # LP's offense-relative yardline_100 maps to 100 - yardline_100.
    x = 100 - int(state['yl'])
    call = {'schema_version': 'gridiron.autonomous-play.v1', 'mode': 'autonomous_from_snap',
            'play_id': f"{snapshot['schedule']['game_id']}:{family}:{seed}", 'seed': str(seed),
            'situation': {'quarter': state['quarter'], 'clock_seconds': state['clock'], 'down': state['down'],
                          'yards_to_go': state['togo'], 'yardline_100': x, 'offense_direction': 1,
                          'ball_lateral_yards': 160 / 6},
            'offense': {'team': 'MIN', 'formation': 'singleback_11',
                        'call': {'family': family, 'concept': 'inside_zone' if family == 'run' else 'slant_flat',
                                 'direction': 'right', 'snap_type': 'under_center' if family == 'run' else 'shotgun'},
                        'lineup': slots},
            'defense': {'team': 'SF', 'call': {'front': 'nickel_over', 'coverage': 'cover_1', 'run_fit': 'spill_force'},
                        'lineup': dslots},
            'player_profiles': {pid: {'ratings': {}, 'physics': {}} for pid in ids}}
    return call, {'snapshot_sha256': snapshot['snapshot_sha256'], 'snapshot_verified': snapshot['evaluation']['verified'],
                  'participation_sha256': field_hash, 'playbook_prior': prior,
                  'lineup_selection': selected, 'attribute_source': 'gridiron_authored_archetype_defaults',
                  'concept_selection': selection, 'formation_selection': 'explicit_11_personnel'}


def run(engine_root, call):
    commit = _check_engine(engine_root)
    start = time.monotonic()
    proc = subprocess.run(['node', str(Path(engine_root) / 'engine/autonomous/slc-cli.js')],
                          input=json.dumps(call), capture_output=True, text=True, check=False)
    if proc.returncode:
        raise ValueError('gridiron_executor_failed:' + proc.stderr.strip())
    result = json.loads(proc.stdout)
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
    return result, {'engine_commit': commit, 'elapsed_wall_seconds': time.monotonic() - start}


def reduce_result(call, result, state):
    """Map supported live events to the SLC reducer and player stats at whistle."""
    if call['situation']['offense_direction'] != 1 or call['situation']['yardline_100'] != 100 - state['yl']:
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
    if abs(outcome['final_ball_spot']['x_yards'] - (call['situation']['yardline_100'] + outcome['yards_gained'])) > 0.003:
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
    if reason not in ('tackle', 'out_of_bounds', 'incomplete', 'sack', 'touchdown'):
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
