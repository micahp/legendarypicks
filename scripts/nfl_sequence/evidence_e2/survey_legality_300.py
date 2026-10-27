#!/usr/bin/env python3
"""Play seeds 1-300 through the E2 engine, check every record with the independent legality checker, and compare the
outcome with the frozen per-seed survey (docs/fixtures/e2/survey-per-seed-300.csv).

The engine plays the games. The legality checker (legality_check.py) judges them and imports nothing from the engine. The
matrix count is taken from rules_matrix as the frozen survey took it, so the two counts can be compared directly.

Two verdicts are reported and kept apart. `legal_modelled` is consistency under the modelled rules, including the two-minute
warning at its actual post-down clock. `legal_complete_game` is a model-scoped candidate that also requires complete regulation
and no encountered unmodelled transition. It is not shared-v1 full-game certification.

Writes one row per seed and a summary. With --records-dir, each record is also written as seed-NNN.json, for the Gridiron audit
(gridiron_population.py). Usage: python3 survey_legality_300.py [--out-dir DIR] [--records-dir DIR]
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # the engine (nfl_sequence)
sys.path.insert(0, str(HERE))  # the independent checker
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import legality_check as lc  # noqa: E402
import rules_matrix as rm  # noqa: E402
import drive_index_check as di  # noqa: E402
import versions  # noqa: E402

FROZEN = HERE.parents[2] / 'docs' / 'fixtures' / 'e2' / 'survey-per-seed-300.csv'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=str(HERE.parents[2] / 'docs' / 'evidence' / 'e2'))
    ap.add_argument('--records-dir', default=None)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records_dir = Path(args.records_dir) if args.records_dir else None
    if records_dir:
        records_dir.mkdir(parents=True, exist_ok=True)

    source = versions.source_snapshot()
    ref, _ = er.load()
    with open(FROZEN, newline='') as f:
        frozen = {int(r['seed']): r for r in csv.DictReader(f)}

    rows, mismatches = [], []
    di_drives = di_states = di_checked = 0
    for seed in range(1, 301):
        record = gs.play_game(seed, ref)
        gs.validate_game(record)  # fail closed: any refused invariant stops the survey
        if records_dir:
            (records_dir / f'seed-{seed:03d}.json').write_text(
                json.dumps(versions.research_stamp(record, source), sort_keys=True))
        seed_drives, seed_states, seed_checked = di.check_record(record)
        di_drives, di_states, di_checked = di_drives + seed_drives, di_states + seed_states, di_checked + seed_checked
        di.require_zero(seed_drives, seed_states, f'seed {seed}')  # the drive index is asserted on every seed
        failed = sorted(k for k, v in lc.run(record).items() if v)
        matrix_fail = sum(1 for r in rm.check(record) if r['status'] == 'FAIL')
        complete = bool(record['complete_regulation'])
        regulation_end = bool(record['regulation_end_reached'])
        row = {'seed': seed, 'status': record['status'], 'blocker': record.get('blocker') or '',
               'complete_regulation': complete,
               'regulation_end_reached': regulation_end,
               'complete_game': bool(record['complete_game']),
               'valid_full_game': bool(record['valid_full_game']),
               'record_mode': record['mode'],
               'legal_modelled': lc.legal_modelled(record),
               'legal_complete_game': lc.legal_complete_game(record),
               'checker_failed_checks': ';'.join(failed),
               'try_findings': len(lc.check_conversions(record)),
               'unmodelled_transitions': len(record.get('unmodelled_transitions') or []),
               'scope_out': ';'.join(x['reason'] for x in record['scope_out']),
               'matrix_fail': matrix_fail}
        rows.append(row)
        old = frozen[seed]
        sim_status = 'complete_regulation' if record['status'] == 'regulation_end_guarded' else record['status']
        same = (sim_status == old['status'] and (record.get('blocker') or '') == old['blocker']
                and regulation_end == (old['complete_game'] == 'True') and matrix_fail == int(old['matrix_fail']))
        if not same:
            mismatches.append({'seed': seed, 'engine_now': row, 'frozen': {k: old[k] for k in
                                                                            ('status', 'blocker', 'complete_game',
                                                                             'matrix_fail')}})
        if seed % 50 == 0:
            print(f'seed {seed}: {sum(1 for r in rows if r["legal_modelled"])} legal_modelled so far', flush=True)

    with open(out_dir / 'legality-survey-300.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        'seeds': len(rows),
        'source': source,
        'record_mode': dict(Counter(r['record_mode'] for r in rows)),
        'status': dict(Counter(r['status'] for r in rows)),
        'complete_regulation': sum(1 for r in rows if r['complete_regulation']),
        'blocked_never_complete': all(not r['complete_regulation'] for r in rows if r['status'] == 'blocked'),
        'blocked_described_complete': sum(1 for r in rows if r['status'] == 'blocked' and r['complete_regulation']),
        'complete_game': sum(1 for r in rows if r['complete_game']),
        'valid_full_game': sum(1 for r in rows if r['valid_full_game']),
        'valid_full_game_definition': ('Shared-v1 pregame_full_game claim; it requires independently passing applicable game-state '
                                       'checks plus scheduled game identity, pregame as-of and kickoff, roster/snapshot provenance, and '
                                       'no unsupported transition. It is distinct from a complete model-scoped regulation record.'),
        'regulation_end_reached': sum(1 for r in rows if r['regulation_end_reached']),
        'regulation_end_guarded': sum(1 for r in rows if r['status'] == 'regulation_end_guarded'),
        'guarded_described_complete': sum(1 for r in rows if r['unmodelled_transitions'] and (
            r['status'] == 'complete_regulation' or r['complete_game'])),
        'validate_game_passed': len(rows),
        'drive_index_mismatch_drives': di_drives,
        'drive_index_mismatch_states': di_states,
        'drive_index_states_checked': di_checked,
        'scope_out_seeds': {reason: sum(1 for r in rows if reason in r['scope_out'].split(';'))
                            for reason in ('overtime', 'rare kick outcome', 'thin E1 pool cell', 'penalty', 'drive limit',
                                           'other')},
        'legal_modelled': sum(1 for r in rows if r['legal_modelled']),
        'legal_modelled_illegal': [r['seed'] for r in rows if not r['legal_modelled']],
        'legal_complete_game': sum(1 for r in rows if r['legal_complete_game']),
        'complete_but_unmodelled': sum(1 for r in rows if r['complete_regulation'] and r['unmodelled_transitions']),
        'records_with_unmodelled_transitions': sum(1 for r in rows if r['unmodelled_transitions']),
        'try_findings_total': sum(r['try_findings'] for r in rows),
        'matrix_fail_rows': sum(r['matrix_fail'] for r in rows),
        'matches_frozen_survey': len(rows) - len(mismatches),
        'mismatches_vs_frozen': mismatches,
    }
    (out_dir / 'legality-survey-300-summary.json').write_text(json.dumps(summary, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'mismatches_vs_frozen'}, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
