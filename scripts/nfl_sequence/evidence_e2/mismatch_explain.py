#!/usr/bin/env python3
"""Counterfactually check whether the regulation-only sampling pool explains frozen-survey outcome changes.

For each changed seed, run the current engine once with its current regulation-only pool and once with the previous all-quarter
pool. The current code and random seed stay fixed; only the reference population changes. Compare both outcomes with the frozen
per-seed survey. Writes MISMATCH-300-SUCCESSOR-2026-10-24.md/.json. Usage: python3 mismatch_explain.py
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import rules_matrix as rm  # noqa: E402
import versions  # noqa: E402

ROOT = HERE.parents[2]
EV = ROOT / 'docs' / 'evidence' / 'e2-successor'
SUMMARY = EV / 'legality-survey-300-summary.json'
FROZEN_CSV = ROOT / 'docs' / 'fixtures' / 'e2' / 'survey-per-seed-300.csv'
OUT_MD = EV / 'MISMATCH-300-SUCCESSOR-2026-10-24.md'
OUT_JSON = EV / 'MISMATCH-300-SUCCESSOR-2026-10-24.json'


def outcome_key(record):
    status = 'complete_regulation' if record['status'] == 'regulation_end_guarded' else record['status']
    return {'status': status, 'blocker': record.get('blocker') or '',
            'complete_game': bool(record['complete_game']),
            'regulation_end_reached': bool(record['regulation_end_reached'])}


def pool_size(reference):
    return {'e1_play_rows': sum(len(cell) for cell in reference.pool.values()),
            'kickoff_rows': len(reference.kickoff_pool),
            'pool_scope': reference.pool_scope}


def main():
    summary = json.loads(SUMMARY.read_text())
    frozen = {int(r['seed']): r for r in csv.DictReader(open(FROZEN_CSV, newline=''))}
    changed = {int(m['seed']): m for m in summary['mismatches_vs_frozen']}
    filtered_ref, _ = er.load(regulation_only=True)
    all_quarters_ref, _ = er.load(regulation_only=False)
    rows = []

    for seed, survey_row in sorted(changed.items()):
        frozen_row = frozen[seed]
        frozen_key = {'status': frozen_row['status'], 'blocker': frozen_row['blocker'],
                      'complete_game': frozen_row['complete_game'] == 'True',
                      'regulation_end_reached': frozen_row['complete_game'] == 'True'}
        filtered_key = {'status': ('complete_regulation' if survey_row['engine_now']['status'] == 'regulation_end_guarded'
                                   else survey_row['engine_now']['status']),
                        'blocker': survey_row['engine_now']['blocker'],
                        'complete_game': bool(survey_row['engine_now']['complete_game']),
                        'regulation_end_reached': bool(survey_row['engine_now']['regulation_end_reached'])}
        all_record = gs.play_game(seed, all_quarters_ref)
        all_key = outcome_key(all_record)
        filtered_matches = filtered_key == frozen_key
        all_matches = all_key == frozen_key
        status_fields = ('status', 'blocker', 'regulation_end_reached')
        all_status_matches = all(all_key[k] == frozen_key[k] for k in status_fields)
        guard_kinds = sorted({x['kind'] for x in all_record.get('unmodelled_transitions', [])})
        if not filtered_matches and all_matches:
            cause = 'regulation_only_pool'
        elif filtered_matches:
            cause = 'audit_or_non_outcome_difference'
        else:
            cause = 'not_explained_by_pool_alone'
        if cause == 'regulation_only_pool':
            detail = 'regulation_only_pool_changes_frozen_outcome'
        elif all_status_matches and all_key['complete_game'] != frozen_key['complete_game'] and 'two_minute_warning' in guard_kinds:
            detail = 'two_minute_guard_keeps_complete_game_false'
        elif not all_status_matches:
            detail = 'status_or_blocker_differs_with_all_quarter_pool'
        else:
            detail = 'other_difference'
        rows.append({'seed': seed, 'frozen': frozen_key, 'regulation_only': filtered_key,
                     'all_quarters_counterfactual': all_key,
                     'regulation_only_outcome_matches_frozen': filtered_matches,
                     'all_quarters_outcome_matches_frozen': all_matches,
                     'all_quarters_status_blocker_regulation_match': all_status_matches,
                     'all_quarters_unmodelled_kinds': guard_kinds,
                     'classification': cause,
                     'classification_detail': detail,
                     'frozen_matrix_fail': int(frozen_row['matrix_fail']),
                     'regulation_only_matrix_fail': int(survey_row['engine_now']['matrix_fail']),
                     'all_quarters_matrix_fail': sum(1 for r in rm.check(all_record) if r['status'] == 'FAIL')})
        print(f"seed {seed}: {cause}; filtered={filtered_key['status']}/{filtered_key['blocker'] or '-'}; "
              f"all-quarter={all_key['status']}/{all_key['blocker'] or '-'}; frozen={frozen_key['status']}/{frozen_key['blocker'] or '-'}",
              flush=True)

    counts = {}
    detail_counts = {}
    for row in rows:
        counts[row['classification']] = counts.get(row['classification'], 0) + 1
        detail_counts[row['classification_detail']] = detail_counts.get(row['classification_detail'], 0) + 1
    result = {'base_model_version': versions.source_snapshot()['base_model_version'],
              'research_source_sha256': versions.source_snapshot()['source_tree_sha256'],
              'frozen_reference': 'a442dcd72559cfaf2d04737fc2454cea486faf09',
              'counterfactual': 'same current engine and seed; switch only between regulation_only=True/False reference pools',
              'pools': {'regulation_only': pool_size(filtered_ref), 'all_quarters': pool_size(all_quarters_ref)},
              'changed_seeds': len(rows), 'classification_counts': counts, 'classification_detail_counts': detail_counts,
              'rows': rows}
    OUT_JSON.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    lines = [
        '# E2 successor: counterfactual for seeds changed from the frozen survey', '',
        f"Frozen reference `{result['frozen_reference']}`. Current engine base `{result['base_model_version']}`; exact source-tree "
        f"SHA-256 `{result['research_source_sha256']}`.",
        'The control holds the current engine and each random seed fixed and changes only the reference population from '
        '`regulation_only=True` to `regulation_only=False`.',
        f"Changed seeds: {len(rows)}. Classifications: {', '.join(f'{k} {v}' for k, v in sorted(counts.items())) or 'none'}.", '',
        f"Detail: {', '.join(f'{k} {v}' for k, v in sorted(detail_counts.items()))}. For the two-minute guard cases, the "
        'all-quarter run matches the frozen status, blocker and regulation-end outcome, while the current unmodelled-transition '
        'guard correctly leaves `complete_game=false`.', '',
        '| pool | E1 play rows | kickoff rows | overtime rows excluded |', '|---|---:|---:|---:|',
        f"| regulation only | {result['pools']['regulation_only']['e1_play_rows']} | "
        f"{result['pools']['regulation_only']['kickoff_rows']} | "
        f"{result['pools']['regulation_only']['pool_scope']['overtime_rows_excluded_from_pool']} |",
        f"| all quarters | {result['pools']['all_quarters']['e1_play_rows']} | "
        f"{result['pools']['all_quarters']['kickoff_rows']} | 0 |", '',
        '| seed | frozen outcome | regulation-only | all-quarter control | classification detail | matrix FAIL rows (frozen / filtered / control) |',
        '|---:|---|---|---|---|---:|',
    ]
    for row in rows:
        f, r, a = row['frozen'], row['regulation_only'], row['all_quarters_counterfactual']
        lines.append(f"| {row['seed']} | {f['status']}/{f['blocker'] or '-'} | {r['status']}/{r['blocker'] or '-'} | "
                     f"{a['status']}/{a['blocker'] or '-'} | `{row['classification_detail']}` | "
                     f"{row['frozen_matrix_fail']} / {row['regulation_only_matrix_fail']} / {row['all_quarters_matrix_fail']} |")
    OUT_MD.write_text('\n'.join(lines) + '\n')
    print(f"wrote {OUT_MD} and {OUT_JSON}; classifications {counts}; details {detail_counts}")


if __name__ == '__main__':
    main()
