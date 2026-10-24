#!/usr/bin/env python3
"""Play seeds 1-300 through the E2 engine, check every record with the independent legality checker, and compare the
outcome with the frozen per-seed survey (docs/fixtures/e2/survey-per-seed-300.csv).

The engine plays the games. The legality checker (legality_check.py) judges them and imports nothing from the engine. The
matrix count is taken from rules_matrix as the frozen survey took it, so the two counts can be compared directly.

Two verdicts are reported and kept apart. `legal_modelled` is consistency under the modelled rules. `legal_complete_game`
also requires complete regulation and no unmodelled transition (penalty, two-minute warning). A complete game that crosses
2:00 in a late half is therefore legal under the modelled rules and is not a legal complete game.

Writes one row per seed and a summary. Usage: python3 survey_legality_300.py [--out-dir DIR]
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

FROZEN = HERE.parents[2] / 'docs' / 'fixtures' / 'e2' / 'survey-per-seed-300.csv'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=str(HERE.parents[2] / 'docs' / 'evidence' / 'e2'))
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ref, _ = er.load()
    with open(FROZEN, newline='') as f:
        frozen = {int(r['seed']): r for r in csv.DictReader(f)}

    rows, mismatches = [], []
    for seed in range(1, 301):
        record = gs.play_game(seed, ref)
        gs.validate_game(record)  # fail closed: any refused invariant stops the survey
        failed = sorted(k for k, v in lc.run(record).items() if v)
        matrix_fail = sum(1 for r in rm.check(record) if r['status'] == 'FAIL')
        complete = bool(record['complete_regulation'])
        regulation_end = bool(record['regulation_end_reached'])
        row = {'seed': seed, 'status': record['status'], 'blocker': record.get('blocker') or '',
               'complete_regulation': complete,
               'regulation_end_reached': regulation_end,
               'complete_game': bool(record['complete_game']),
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
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        'seeds': len(rows),
        'status': dict(Counter(r['status'] for r in rows)),
        'complete_regulation': sum(1 for r in rows if r['complete_regulation']),
        'blocked_never_complete': all(not r['complete_regulation'] for r in rows if r['status'] == 'blocked'),
        'blocked_described_complete': sum(1 for r in rows if r['status'] == 'blocked' and r['complete_regulation']),
        'complete_game': sum(1 for r in rows if r['complete_game']),
        'regulation_end_reached': sum(1 for r in rows if r['regulation_end_reached']),
        'regulation_end_guarded': sum(1 for r in rows if r['status'] == 'regulation_end_guarded'),
        'guarded_described_complete': sum(1 for r in rows if r['unmodelled_transitions'] and (
            r['status'] == 'complete_regulation' or r['complete_game'])),
        'validate_game_passed': len(rows),
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
