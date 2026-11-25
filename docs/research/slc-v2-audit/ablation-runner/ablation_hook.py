"""SLC V2 layer ablation hook (SLC-V2-LAYER-ABLATION-SPEC-2026-11-24).

Called by the copied portable runner right after the control's RNG plan is fixed, so every arm draws from the same
random streams. It (1) swaps in the patched sampler (zero-weight guards, research switches, path instrumentation) and
(2) applies the arm's layer overrides: the constructor defaults of the attributes each layer's loader sets
(e2_reference.load, slc_engine.load_reference). It also counts every sampling path and fallback in the decision
records and writes them next to the game output.
"""
from __future__ import annotations

import functools
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

PATCHED = Path(__file__).resolve().parent / 'slc_playcall_patched.py'
BOTH = {'research_disable_event_multipliers': True, 'research_disable_row_filters': True}
STREAK_OFF = {'streak_shifts': None, 'streak_league': None, 'streak_outcomes': False}
ARMS = {
    'A00_control': {},
    'A01_score_clock_playcalling': {'score_clock_playcalling_enabled': False},
    'A02_point_splits': {'point_shifts': None},
    'A03_team_streak_splits': {'streak_shifts': None},
    'A04_league_streak_splits': {'streak_league': None, 'streak_outcomes': False},
    'A05_current_streak_context': {'current_streak': {}, **STREAK_OFF},
    'A07_decision_labels': {'decision_table': None, 'decision_outcomes': False, 'decision_filter': False,
                            'playbook_table': None, 'pass_label_mode': 'legacy'},
    'A08_decision_row_filter': {'decision_filter': False},
    'A09_playbook_priors': {'playbook_table': None},
    'A10_formation_personnel_outcomes': {'formation_outcomes': False, 'formation_priors': None},
    'A11_defensive_coverage_outcomes': {'coverage_outcomes': False, 'defense_priors': None},
    'A12_exact_yardline_outcomes': {'exact_yardline': False},
    'A13_team_offense_defense_outcomes': {'team_outcomes': None},
    'A14_player_conditioned_outcomes': {'player_outcome_table': None},
    'A15_dirichlet_player_shares': {'share_table': None},
    'A16_target_role_priors': {'role_table': None},
    'A17_no_event_multipliers': {'research_disable_event_multipliers': True},
    'A18_no_row_filters': {'research_disable_row_filters': True},
    'A19_no_multipliers_no_filters': dict(BOTH),
    'A22_league_outcomes': {**BOTH, 'team_outcomes': None, 'player_outcome_table': None},
    'A23_minimal_situational': None,  # no SLC sampler at all: plain situation-cell sampling (the S0 path)
}
FALLBACK_FIELDS = ('row_weight_fallback', 'two_stage_pass_fallback', 'outcome_weight_fallback', 'formation_fallback',
                   'coverage_fallback', 'streak_fallback', 'exact_yardline_fallback', 'qb_target_role_fallback',
                   'qb_scramble_fallback', 'qb_target_role_draw_fallback', 'fallback')
STATS = {'games': 0, 'decisions': 0, 'path': Counter(), 'fallbacks': Counter(), 'labels_unmatched': Counter(),
         'split_fallbacks': Counter(), 'team_outcome_fallbacks': Counter(), 'exact_rows': Counter(),
         'filters': defaultdict(lambda: {'applied': 0, 'before': 0, 'after': 0}), 'ess': []}


def _bucket(n):
    return 'none' if n is None else '0' if n == 0 else '1-9' if n < 10 else '10-49' if n < 50 else '50+'


def _observe(decisions):
    """One JSON line per game, in a file per process (forked workers do not run exit handlers)."""
    for key in ('path', 'fallbacks', 'labels_unmatched', 'split_fallbacks', 'team_outcome_fallbacks', 'exact_rows'):
        STATS[key].clear()
    STATS['filters'].clear()
    STATS['ess'].clear()
    STATS['games'], STATS['decisions'] = 1, 0
    for d in decisions:
        STATS['decisions'] += 1
        STATS['path'][str(d.get('sampling_path'))] += 1
        for field in FALLBACK_FIELDS:
            value = d.get(field)
            if value:
                STATS['fallbacks'][f'{field}:{value}'] += 1
        for cat in d.get('labels_unmatched') or ():
            STATS['labels_unmatched'][cat] += 1
        for item in d.get('split_fallbacks') or ():
            STATS['split_fallbacks'][item] += 1
        for item in d.get('team_outcome_fallbacks') or ():
            STATS['team_outcome_fallbacks'][item.split(':')[0]] += 1
        STATS['exact_rows'][_bucket(d.get('exact_outcome_rows'))] += 1
        counts = d.get('row_filter_counts') or []
        for (_, before), (name, after) in zip(counts, counts[1:]):
            row = STATS['filters'][name]
            row['applied'] += 1
            row['before'] += before
            row['after'] += after
        if d.get('backoff_effective_sample_size') is not None:
            STATS['ess'].append(d['backoff_effective_sample_size'])


def _write():
    out = os.environ.get('ABLATION_STATS_OUT')
    if not out:
        return
    out = f'{out}.{os.getpid()}.jsonl'
    ess = sorted(STATS['ess'])
    payload = {'arm': os.environ.get('ABLATION_ARM'), 'games': STATS['games'], 'decisions': STATS['decisions'],
               'sampling_path': dict(STATS['path']), 'fallbacks': dict(STATS['fallbacks']),
               'labels_unmatched': dict(STATS['labels_unmatched']), 'split_fallbacks': dict(STATS['split_fallbacks']),
               'team_outcome_fallbacks': dict(STATS['team_outcome_fallbacks']),
               'exact_outcome_rows': dict(STATS['exact_rows']), 'row_filters': {k: dict(v) for k, v in STATS['filters'].items()},
               'backoff_ess': ({'n': len(ess), 'median': ess[len(ess) // 2], 'p10': ess[len(ess) // 10]} if ess else None)}
    with open(out, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, sort_keys=True) + '\n')


def apply(reference, slc_engine, rng_plan):
    arm = os.environ.get('ABLATION_ARM', 'A00_control')
    if arm not in ARMS:
        raise SystemExit(f'unknown ablation arm {arm!r}')
    if ARMS[arm] is None:
        reference.contextual_sampler = None  # the runner then takes the plain game_state path for every seed
        print(f'ablation arm {arm}: no SLC sampler; stream root {rng_plan.manifest().get("stream_root_sha256")}',
              flush=True)
        return
    sampler = getattr(reference, 'contextual_sampler', None)
    if sampler is None:
        raise SystemExit('the pack has no SLC sampler')
    module = __import__(type(sampler).__module__)
    exec(compile(PATCHED.read_text(), str(PATCHED), 'exec'), module.__dict__)  # the patched sampler, same module
    sampler.__class__ = module.PlayCallSampler
    for name, value in ARMS[arm].items():
        if not hasattr(sampler, name) and not name.startswith('research_'):
            raise SystemExit(f'{arm}: sampler has no attribute {name!r}')
        setattr(sampler, name, value)
    if getattr(slc_engine.play, '_ablation_wrapped', False):  # one process runs many games: wrap once
        return
    original = slc_engine.play

    @functools.wraps(original)  # the runner inspects play's signature for rng_plan
    def play(*args, **kwargs):
        record, decisions = original(*args, **kwargs)
        _observe(decisions)
        _write()
        return record, decisions

    play._ablation_wrapped = True
    slc_engine.play = play
    print(f'ablation arm {arm}: {len(ARMS[arm])} override(s); stream root {rng_plan.manifest().get("stream_root_sha256")}',
          flush=True)
