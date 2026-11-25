"""SLC V2 mechanism ablation hook (SLC-V2-LAYER-ABLATION-SPEC-2026-11-24, amendments 1-2).

Called by the copied portable runner right after the control's RNG plan is fixed, so every arm draws from the same
random streams. It swaps in the patched engine modules (zero-weight guards, one research switch per mechanism, path and
mechanism instrumentation), restores the loaded sampler's original settings, then applies the arm: a set of mechanisms
switched off (`sampler.research_off`) and, for layers without a switch, attribute overrides. It counts every sampling
path, fallback and applied mechanism per game, and writes an arm manifest that separates loaded tables from active
mechanisms.
"""
from __future__ import annotations

import functools
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCHED = ('slc_playcall', 'qb_decisions', 'pre_event', 'slc_engine')  # files HERE/<name>_patched.py

MULTIPLIERS = frozenset({'formation_outcome_lift', 'coverage_outcome_lift', 'streak_outcome_lift', 'label_outcome_lift',
                         'label_conditional_pass_model', 'team_event_weights', 'player_event_weights',
                         'player_row_weights'})
FILTERS = frozenset({'formation_row_filter', 'coverage_row_filter', 'streak_row_filter', 'label_row_filter',
                     'qb_target_role_row_filter', 'exact_yardline_row_filter'})
QB = frozenset({'qb_scramble_probability', 'qb_target_role_selection', 'qb_target_role_row_filter'})


def arm(off=(), **attrs):
    return {'off': frozenset(off), 'attrs': attrs}


ARMS = {
    'A00_control': arm(),
    'P1_score_clock_playcalling': arm({'score_clock_playcalling'}),
    'P2_point_split_shift': arm({'point_split_shift'}),
    'P3_team_streak_shift': arm({'team_streak_shift'}),
    'P4_league_streak_shift': arm({'league_streak_shift'}),
    'Q1_qb_scramble_probability': arm({'qb_scramble_probability'}),
    'Q2_qb_target_role_selection': arm({'qb_target_role_selection'}),
    'Q3_qb_target_role_row_filter': arm({'qb_target_role_row_filter'}),
    'Q4_qb_decision_model': arm(QB),
    'L1_label_generation': arm({'label_generation'}),
    'L2_label_outcome_lift': arm({'label_outcome_lift'}),
    'L3_label_conditional_pass_model': arm({'label_conditional_pass_model'}),
    'L4_label_row_filter': arm({'label_row_filter'}),
    'L5_label_participant_allocation': arm({'label_participant_allocation'}),
    'L6_label_outcome_modifiers': arm({'label_outcome_lift', 'label_conditional_pass_model'}),
    'L7_playbook_label_priors': arm({'playbook_label_priors'}),
    'K1_streak_outcome_lift': arm({'streak_outcome_lift'}),
    'K2_streak_row_filter': arm({'streak_row_filter'}),
    'K3_streak_context': arm(current_streak={}),
    'F1_formation_choice': arm({'formation_choice'}),
    'F2_formation_outcome_lift': arm({'formation_outcome_lift'}),
    'F3_formation_row_filter': arm({'formation_row_filter'}),
    'C1_coverage_choice': arm({'coverage_choice'}),
    'C2_coverage_outcome_lift': arm({'coverage_outcome_lift'}),
    'C3_coverage_row_filter': arm({'coverage_row_filter'}),
    'T1_team_event_weights': arm({'team_event_weights'}),
    'U1_player_event_weights': arm({'player_event_weights'}),
    'U2_player_row_weights': arm({'player_row_weights'}),
    'U3_player_outcome_strength': arm({'player_event_weights', 'player_row_weights'}),
    'D1_dirichlet_player_shares': arm({'dirichlet_player_shares'}),
    'R1_target_role_priors': arm({'target_role_priors'}),
    'X1_exact_yardline_row_filter': arm({'exact_yardline_row_filter'}),
    'G1_no_multipliers': arm(MULTIPLIERS),
    'G2_no_filters': arm(FILTERS),
    'G3_no_multipliers_no_filters': arm(MULTIPLIERS | FILTERS),
    'G4_league_outcomes': arm(MULTIPLIERS | FILTERS, team_outcomes=None, player_outcome_table=None),
    'S1_participation_lineup': arm(participation_field=None),
    'S2_kicker_field_goals': arm(fg_kicker=None),
    'Z1_minimal_situational': None,  # no SLC sampler at all: plain situation-cell sampling (the S0 path)
}
LOADED_ATTRS = ('team_outcomes', 'transition_strength', 'formation_priors', 'defense_priors', 'player_shares',
                'share_table', 'role_table', 'decision_table', 'playbook_table', 'qb_decision_table',
                'player_outcome_table', 'point_shifts', 'streak_shifts', 'streak_league', 'current_streak',
                'participation_field', 'fg_kicker', 'pass_label_outcome_model', 'source_pool')
FALLBACK_FIELDS = ('row_weight_fallback', 'two_stage_pass_fallback', 'outcome_weight_fallback', 'formation_fallback',
                   'coverage_fallback', 'streak_fallback', 'exact_yardline_fallback', 'qb_target_role_fallback',
                   'qb_scramble_fallback', 'qb_target_role_draw_fallback', 'fallback')
_STATE = {'patched': False, 'original': None, 'sampler': None, 'manifest_written': set()}


def _patch_modules():
    if _STATE['patched']:
        return
    import sys
    for name in PATCHED:
        module = sys.modules.get(name) or __import__(name)
        path = HERE / f'{name}_patched.py'
        exec(compile(path.read_text(), str(path), 'exec'), module.__dict__)
    _STATE['patched'] = True


def _bucket(n):
    return 'none' if n is None else '0' if n == 0 else '1-9' if n < 10 else '10-49' if n < 50 else '50+'


def _game_stats(decisions):
    s = {'decisions': len(decisions), 'path': Counter(), 'fallbacks': Counter(), 'mechanisms_applied': Counter(),
         'evidence': Counter(), 'exact_rows': Counter(), 'filters': defaultdict(lambda: [0, 0, 0]), 'ess': []}
    for d in decisions:
        s['path'][str(d.get('sampling_path'))] += 1
        for field in FALLBACK_FIELDS:
            if d.get(field):
                s['fallbacks'][f'{field}:{d[field]}'] += 1
        for name, used in (d.get('mechanisms_applied') or {}).items():
            s['mechanisms_applied'][name] += int(bool(used))
        ev = s['evidence']
        ev['formation_drawn'] += d.get('formation') is not None
        ev['coverage_drawn'] += d.get('coverage') is not None
        ev['labels_drawn'] += bool(d.get('labels'))
        ev[f"qb_action:{d.get('qb_action')}"] += 1
        ev['qb_target_role_drawn'] += d.get('qb_target_role') is not None
        ev[f"qb_scramble_probability_source:{d.get('qb_scramble_probability_source')}"] += 1
        ev[f"participant_share_model:{d.get('participant_share_model')}"] += 1
        ev['target_role_prior_used'] += bool(d.get('target_role_prior_used'))
        ev['playbook_used'] += bool(d.get('playbook_used'))
        ev[f"call_policy_source:{d.get('call_policy_source')}"] += 1
        s['exact_rows'][_bucket(d.get('exact_outcome_rows'))] += 1
        counts = d.get('row_filter_counts') or []
        for (_, before), (name, after) in zip(counts, counts[1:]):
            row = s['filters'][name]
            row[0] += 1
            row[1] += before
            row[2] += after
        if d.get('backoff_effective_sample_size') is not None:
            s['ess'].append(d['backoff_effective_sample_size'])
    return s


def _write_game(arm_name, decisions):
    out = os.environ.get('ABLATION_STATS_OUT')
    if not out:
        return
    s = _game_stats(decisions)
    payload = {'arm': arm_name, 'decisions': s['decisions'], 'sampling_path': dict(s['path']),
               'fallbacks': dict(s['fallbacks']), 'mechanisms_applied': dict(s['mechanisms_applied']),
               'evidence': dict(s['evidence']), 'exact_outcome_rows': dict(s['exact_rows']),
               'row_filters': {k: {'applied': v[0], 'before': v[1], 'after': v[2]} for k, v in s['filters'].items()},
               'backoff_ess': s['ess']}
    with open(f'{out}.{os.getpid()}.jsonl', 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, sort_keys=True) + '\n')


def _write_manifest(arm_name, sampler, spec):
    out = os.environ.get('ABLATION_STATS_OUT')
    if not out or arm_name in _STATE['manifest_written']:
        return
    import slc_playcall
    off = set(spec['off']) if spec else set(getattr(slc_playcall, 'RESEARCH_MECHANISMS', ()))
    manifest = {
        'arm': arm_name,
        'loaded_artifacts': ({name: getattr(sampler, name, None) not in (None, {}, False) for name in LOADED_ATTRS}
                             if sampler is not None else {}),
        'research_off': sorted(off),
        'attribute_overrides': sorted(spec['attrs']) if spec else ['contextual_sampler'],
        'active_mechanisms': sorted(set(getattr(slc_playcall, 'RESEARCH_MECHANISMS', ())) - off),
        'note': 'a loaded table does not mean its mechanism is active: active_mechanisms is the switch state, and '
                'mechanisms_applied in the per-game stats is what ran',
    }
    Path(f'{out}.manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    _STATE['manifest_written'].add(arm_name)


def apply(reference, slc_engine, rng_plan):
    arm_name = os.environ.get('ABLATION_ARM', 'A00_control')
    if arm_name not in ARMS:
        raise SystemExit(f'unknown ablation arm {arm_name!r}')
    spec = ARMS[arm_name]
    if spec is None:
        reference.contextual_sampler = None  # the runner then takes the plain game_state path for every seed
        _write_manifest(arm_name, None, None)
        print(f'ablation arm {arm_name}: no SLC sampler; stream root {rng_plan.manifest().get("stream_root_sha256")}',
              flush=True)
        return
    sampler = getattr(reference, 'contextual_sampler', None)
    if sampler is None:
        raise SystemExit('the pack has no SLC sampler')
    _patch_modules()
    import slc_playcall
    sampler.__class__ = slc_playcall.PlayCallSampler
    if _STATE['original'] is None or _STATE['sampler'] is not sampler:  # first game with this loaded pack
        _STATE['sampler'] = sampler
        _STATE['original'] = {name: getattr(sampler, name) for name in
                              {a for s in ARMS.values() if s for a in s['attrs']}}
    for name, value in _STATE['original'].items():  # restore, then apply this arm
        setattr(sampler, name, value)
    unknown = spec['off'] - slc_playcall.RESEARCH_MECHANISMS
    if unknown:
        raise SystemExit(f'{arm_name}: unknown mechanisms {sorted(unknown)}')
    sampler.research_off = spec['off']
    for name, value in spec['attrs'].items():
        if not hasattr(sampler, name):
            raise SystemExit(f'{arm_name}: sampler has no attribute {name!r}')
        setattr(sampler, name, value)
    _write_manifest(arm_name, sampler, spec)
    if not getattr(slc_engine.play, '_ablation_wrapped', False):  # one process runs many games: wrap once
        original = slc_engine.play

        @functools.wraps(original)  # the runner inspects play's signature for rng_plan
        def play(*args, **kwargs):
            record, decisions = original(*args, **kwargs)
            _write_game(os.environ.get('ABLATION_ARM'), decisions)
            return record, decisions

        play._ablation_wrapped = True
        slc_engine.play = play
    print(f'ablation arm {arm_name}: off={sorted(spec["off"])} attrs={sorted(spec["attrs"])}; '
          f'stream root {rng_plan.manifest().get("stream_root_sha256")}', flush=True)
