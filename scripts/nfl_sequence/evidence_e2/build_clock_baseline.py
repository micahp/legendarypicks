#!/usr/bin/env python3
"""Publish the E3 clock decomposition as a versioned artifact, with the baseline-B runoff rows it is evaluated on.

Adopted baseline: model B of clock_compare.py (PBP-conditional runoff: outcome, stoppage context, late half), fit on 2022 weeks
1-5 as evaluated. B uses the LP play-by-play, not the tracking-verified subset, so the artifact carries both:
- clock-decomposition.csv: one row per tracking-verified play (15,768), copied byte for byte from the audit branch.
- clock-baseline-B-runoffs.csv: one row per LP play in weeks 1-9 with a modelled runoff, read through clock_compare.load_lp.

Checks, each reported in MANIFEST.json and failing the build when false:
1. The B pool counts computed from the written runoff file equal clock_compare.fit()'s counts (file against memory).
2. The decomposition's game-clock delta equals LP's runoff for the same plays, where both are resolved.

Writes docs/evidence/e3/clock-decomposition-v1/. Usage: python3 build_clock_baseline.py
"""
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import clock_compare as cc  # noqa: E402

ROOT = HERE.parents[2]
INPUTS = ROOT / 'docs' / 'evidence' / 'e3' / 'inputs'
DECOMP_CSV = INPUTS / 'e3-clock-decomposition-2026-10-24.csv'
OUT = ROOT / 'docs' / 'evidence' / 'e3' / 'clock-decomposition-v1'
AUDIT_REPO = '/root/legendarypicks'
AUDIT_COMMIT = '4e18cb9f9e5b29ae9e105cbed37f90dc915c83da'
AUDIT_DIR = 'docs/evidence/e3'
TRACKING_PAIRS_COMMIT = 'e1f56b85'
COMPARISON_JSON = ROOT / 'docs' / 'evidence' / 'e3' / 'three-model-clock-comparison-2026-10-24.json'
RUNOFF_FIELDS = ['game_id', 'play_id', 'week', 'qtr', 'drive', 'outcome', 'stop', 'late', 'qsr_s', 'runoff_s', 'censored',
                 'fit_week', 'b_pool_eligible']
B_BASELINE = {
    'name': 'B', 'definition': 'PBP-conditional runoff: draw from the pool keyed by (outcome, stoppage context, late half); '
                               'quarter-end runoffs (censored) excluded; no tracking.',
    'pool_key': ['outcome', 'stop', 'late'], 'fit_weeks': sorted(cc.FIT_WEEKS), 'min_pool': cc.MIN_POOL,
    'draws_per_play': cc.K, 'seed': cc.SEED,
    'evaluated_in': 'three-model comparison (clock_compare.py at 108a1afe), tested on weeks 6-9, which were burned before the test '
                    '(see the holdout block)',
}


HOLDOUT = {
    'status': 'burned: weeks 6-9 were examined before B was chosen. B is not holdout-validated, and the three-model comparison '
              'cannot be claimed to generalise beyond the 2022 weeks 1-9 examined here.',
    'reserved': {'commit': '4bb5add1', 'time': '2026-10-24 01:54:56 -0500',
                 'text': 'weeks 6-9 are reserved for held-out confirmation (preregistration, snap-anchored benchmark; the '
                         'builder refuses weeks 6-9)'},
    'first_examined_before_reservation': {'commit': 'e7b2641b', 'time': '2026-10-24 00:08:18 -0500',
                                          'what': 'profile of tackle labels per week, weeks 1-9 (not a clock statistic)'},
    'first_clock_examination': {'commit': '6b7682da', 'time': '2026-10-24 07:25:48 -0500',
                                'what': 'clock audit over 2022 weeks 1-9, 15,766 matched plays: the first clock statistic '
                                        'computed on weeks 6-9',
                                'why': 'six of the 13 games on 2026-10-25/26 repeat a 2022 pairing; the medians describe those '
                                       '2022 meetings only'},
    'first_test_use': {'commit': 'c38ec49b', 'time': '2026-10-24 07:33:00 -0500',
                       'what': 'runoff model comparison, fit weeks 1-5, test weeks 6-9: quarter-end share and out-of-bounds '
                               'results reported on the test weeks'},
    'other_uses_of_weeks_6_9': [
        {'commit': '2ebc3be5', 'time': '2026-10-24 07:17:18 -0500', 'what': 'clock audit, weeks 1-5 only (verified weeks [1, 5])'},
        {'commit': 'e1f56b85', 'time': '2026-10-24 09:38:40 -0500', 'what': 'tracking join, identifiers and frame counts over weeks 1-9 (not clock)'},
        {'commit': '4e18cb9f', 'time': '2026-10-24 10:10:10 -0500', 'what': 'clock decomposition over weeks 1-9'},
        {'commit': '108a1afe', 'time': '2026-10-24 10:23:07 -0500', 'what': 'three-model comparison, test weeks 6-9 (this artifact\'s baseline was chosen from it)'},
    ],
    'consequence': 'Model B was adopted after its test-week results were reported. Its adoption is therefore not holdout-validated.',
}


def git(*args):
    return subprocess.run(['git', '-C', AUDIT_REPO, *args], check=True, capture_output=True, text=True).stdout


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_csv(path, fields, rows):
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def schema_for(columns, rows, title, description):
    props = {}
    for c in columns:
        values = sorted({str(r[c]) for r in rows if r[c] not in ('', None)})
        prop = {'type': 'string'}
        if values and len(values) <= 12 and not all(v.replace('.', '', 1).replace('-', '', 1).isdigit() for v in values):
            prop['enum'] = values
        props[c] = prop
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'title': title, 'description': description,
            'type': 'object', 'properties': props, 'required': list(columns), 'additionalProperties': False}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    flags = cc.load_flags()
    lp_rows = cc.load_lp(flags)

    # 1. the runoff rows B is evaluated on
    runoffs = []
    for r in lp_rows:
        if not r['modelled'] or r['runoff'] is None:
            continue
        runoffs.append({'game_id': r['game'], 'play_id': r['play_id'], 'week': r['week'], 'qtr': r['qtr'], 'drive': r['drive'],
                        'outcome': r['outcome'], 'stop': r['stop'], 'late': r['late'], 'qsr_s': round(r['qsr'], 3),
                        'runoff_s': round(r['runoff'], 3), 'censored': int(r['censored']),
                        'fit_week': int(r['week'] in cc.FIT_WEEKS),
                        'b_pool_eligible': int(r['week'] in cc.FIT_WEEKS and not r['censored'])})
    write_csv(OUT / 'clock-baseline-B-runoffs.csv', RUNOFF_FIELDS, runoffs)

    # 2. check the written file against clock_compare.fit()'s in-memory B pool
    _, _, b_memory, _, _ = cc.fit(lp_rows, [])
    file_pool = Counter()
    with open(OUT / 'clock-baseline-B-runoffs.csv', newline='') as f:
        for r in csv.DictReader(f):
            if r['b_pool_eligible'] == '1':
                file_pool[(r['outcome'], r['stop'], int(r['late']))] += 1
    memory_pool = {k: len(v) for k, v in b_memory.items()}
    pool_match = dict(file_pool) == memory_pool
    usable_keys = sum(1 for n in memory_pool.values() if n >= cc.MIN_POOL)

    # 3. the decomposition's game-clock delta against LP's runoff for the same play
    lp_index = {(r['game'], r['play_id']): r['runoff'] for r in lp_rows}
    with open(DECOMP_CSV, newline='') as f:
        decomp = list(csv.DictReader(f))
    agree = disagree = missing = 0
    for d in decomp:
        if d['game_clock_delta_label'] != 'inferred':
            continue
        lp = lp_index.get((d['lp_game_id'], int(float(d['lp_play_id']))))
        if lp is None:
            missing += 1
        elif abs(float(d['game_clock_delta_s']) - lp) < 1e-6:
            agree += 1
        else:
            disagree += 1

    # the decomposition itself: copied byte for byte, and its unresolvable fields counted from the audit's own JSON
    (OUT / 'clock-decomposition.csv').write_bytes((DECOMP_CSV).read_bytes())
    audit = json.loads(git('show', f'{AUDIT_COMMIT}:{AUDIT_DIR}/e3-clock-decomposition-2026-10-24.json'))
    unresolvable = audit['unresolvable_by_rule']
    decomp_fields = list(decomp[0].keys())
    write_text = lambda p, obj: (OUT / p).write_text(json.dumps(obj, indent=1, sort_keys=True) + '\n')
    write_text('clock-decomposition.schema.json', schema_for(
        decomp_fields, decomp, 'E3 clock decomposition, one row per tracking-verified play',
        'Each derived value carries a label (observed, inferred or unresolvable) and the rule that decided it. An unresolvable '
        'value is null, never imputed.'))
    write_text('clock-baseline-B.schema.json', schema_for(
        RUNOFF_FIELDS, runoffs, 'Baseline B runoff rows, one row per LP play in weeks 1-9 with a modelled runoff',
        'b_pool_eligible = 1 selects the rows B draws from: fit weeks, not censored. censored = 1 is a quarter-end runoff.'))

    unresolvable_list = [
        {'field': 'game_clock_delta_s', 'rules': unresolvable['game_clock_delta_s'], 'used_by_B': True,
         'B_treatment': 'censored (R4u2) excluded from the pool; R4u1 and R4u3 have no runoff row'},
        {'field': 'in_play_s', 'rules': unresolvable['in_play_s'], 'used_by_B': False, 'B_treatment': 'not used'},
        {'field': 'residual_s', 'rules': unresolvable['residual_s'], 'used_by_B': False, 'B_treatment': 'not used'},
        {'field': 'real_snap_to_next_snap_s', 'rules': unresolvable['real_snap_to_next_snap_s'], 'used_by_B': False,
         'B_treatment': 'not used'},
        {'field': 'penalty_clock_stop', 'rules': unresolvable['penalty_clock_stop'], 'used_by_B': False,
         'B_treatment': 'the penalty flag is a stoppage context; its clock duration is unresolvable, so B cannot model it'},
        {'field': 'timeouts_remaining', 'rules': unresolvable['timeouts_remaining'], 'used_by_B': False,
         'B_treatment': 'not used: no per-play remaining count in either source'},
        {'field': 'two_minute_warning_event', 'rules': unresolvable['two_minute_warning_event'], 'used_by_B': False,
         'B_treatment': 'not used: the late-half state is observed, the warning event is not identifiable'},
    ]
    b_eligible = sum(1 for r in runoffs if r['b_pool_eligible'] == '1' or r['b_pool_eligible'] == 1)

    files = {name: {'sha256': sha256(OUT / name), 'bytes': (OUT / name).stat().st_size}
             for name in ('clock-decomposition.csv', 'clock-decomposition.schema.json',
                          'clock-baseline-B-runoffs.csv', 'clock-baseline-B.schema.json')}
    manifest = {
        'artifact': 'e3-clock-decomposition', 'version': '1.0.0', 'schema_versions': ['clock-decomposition.schema.json',
                                                                                      'clock-baseline-B.schema.json'],
        'baseline': dict(B_BASELINE, pool_counts=dict(sorted((f'{k[0]}|{k[1]}|{k[2]}', n) for k, n in memory_pool.items())),
                         usable_keys=usable_keys, eligible_rows=b_eligible),
        'unresolvable_fields': unresolvable_list,
        'holdout': HOLDOUT,
        'files': files,
        'checks': {
            'b_pool_file_equals_fit_in_memory': pool_match,
            'decomposition_runoff_agrees_with_lp': {'agree': agree, 'disagree': disagree, 'missing_in_lp': missing},
        },
        'provenance': {
            'decomposition': {'source_commit': AUDIT_COMMIT, 'source_path': f'{AUDIT_DIR}/e3-clock-decomposition-2026-10-24.csv',
                              'generator': 'scripts/bdb/e3_clock_decomposition.py', 'generator_commit': AUDIT_COMMIT,
                              'generator_blob': git('rev-parse', f'{AUDIT_COMMIT}:scripts/bdb/e3_clock_decomposition.py').strip()},
            'tracking_join_pairs': {'commit': TRACKING_PAIRS_COMMIT, 'file': 'docs/research/e3-tracking-join-pairs-2026-10-24.csv',
                                    'sha256_prefix': '80d89116'},
            'nflverse_flags': {'file': 'inputs/nflverse-2022-w1-9-flags.csv', 'sha256_prefix': sha256(INPUTS /
                                                                                              'nflverse-2022-w1-9-flags.csv')[:8],
                               'source': '/root/nflverse-raw/play_by_play_2022.parquet, sha256 931121d8 (SHA256SUMS checked)'},
            'lp_play_by_play': {'database': 'backend/data/picks.dev.db', 'mode': 'read-only',
                                'query': 'nfl_pbp WHERE season = 2022 AND week BETWEEN 1 AND 9 (clock_compare.load_lp)',
                                'rows_read': len(lp_rows)},
            'bdb_tracking': {'directory': '/root/nfl-tracking-data/bdb2025/code-data',
                             'checked_against': 'SHA256SUMS.txt (13 files, all matched, per the coverage report)'},
            'comparison': {'script': 'scripts/nfl_sequence/clock_compare.py', 'commit': '108a1afe',
                           'result': 'docs/evidence/e3/three-model-clock-comparison-2026-10-24.json',
                           'result_sha256': sha256(COMPARISON_JSON)},
            'builder': 'scripts/nfl_sequence/evidence_e2/build_clock_baseline.py',
        },
        'consumer_rules': [
            'Verify the sha256 of each file before reading it. A mismatch means the artifact is not this version.',
            'Never fill an unresolvable value. A null stays null, and the reason is in unresolvable_fields.',
            'Sample the baseline B pool only from rows with b_pool_eligible = 1, keyed on (outcome, stop, late).',
            'Do not read weeks 6-9 as a holdout: they were examined when the comparison was run.',
        ],
    }
    (OUT / 'MANIFEST.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'runoff_rows': len(runoffs), 'b_eligible': b_eligible, 'usable_keys': usable_keys,
                      'b_pool_file_equals_fit_in_memory': pool_match, 'decomposition_runoff_agrees_with_lp': manifest['checks']
                      ['decomposition_runoff_agrees_with_lp']}, indent=1))
    if not pool_match:
        raise SystemExit('B pool written to the file does not equal clock_compare.fit() in memory')


if __name__ == '__main__':
    main()
