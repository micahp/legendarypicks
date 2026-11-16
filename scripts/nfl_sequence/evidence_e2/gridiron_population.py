#!/usr/bin/env python3
"""Run Gridiron's adapter audit on every record of the 300-seed survey, one envelope per seed.

Gridiron's audit is an independent source. LP's validate_game passed a record that Gridiron's validation refused (a possession
change that ended a half, found on seed 1), so the population is checked by the audit, not by the engine's own checks. Each record
is wrapped by build_envelope.py, then checked by gridiron_adapter_proof.mjs in validation-only mode at each Gridiron head. The
viewer's refusal of guarded records is expected and is not counted here. Writes GRIDIRON-POPULATION-300-2026-10-24.json.
Usage: python3 gridiron_population.py <records-dir> <gridiron-root> [<gridiron-root> ...]
"""
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'GRIDIRON-POPULATION-300-2026-10-24.json'
PROOF = HERE / 'gridiron_adapter_proof.mjs'
ENVELOPE = HERE / 'build_envelope.py'


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    records_dir, roots = Path(sys.argv[1]), sys.argv[2:]
    paths = sorted(records_dir.glob('seed-*.json'))
    if len(paths) != 300:
        raise SystemExit(f'expected 300 records in {records_dir}, found {len(paths)}')
    per_root = {r: {'seeds': 0, 'accepted': 0, 'passed': 0, 'validation_finding_seeds': 0, 'football_finding_seeds': 0,
                    'finding_texts': Counter(), 'rows': []} for r in roots}
    with tempfile.TemporaryDirectory() as tmp:
        for path in paths:
            seed = int(path.stem.split('-')[1])
            envelope = Path(tmp) / f'{path.stem}.envelope.json'
            subprocess.run([sys.executable, str(ENVELOPE), str(path), str(envelope)], check=True, capture_output=True, text=True)
            for root in roots:
                done = subprocess.run(['node', str(PROOF), root, str(envelope)], check=True, capture_output=True, text=True)
                v = json.loads(done.stdout)['adapterValidationOnly']
                agg = per_root[root]
                agg['seeds'] += 1
                agg['accepted'] += bool(v['accepted'])
                agg['passed'] += bool(v.get('validationPassed'))
                if v.get('validationFindings'):
                    agg['validation_finding_seeds'] += 1
                if v.get('footballStateFindings'):
                    agg['football_finding_seeds'] += 1
                for text in v.get('validationFindingTexts', []) + v.get('footballStateFindingTexts', []):
                    agg['finding_texts'][text] += 1
                if v.get('validationFindings') or v.get('footballStateFindings') or not v['accepted']:
                    agg['rows'].append({'seed': seed, 'accepted': v['accepted'], 'validation': v.get('validationFindingTexts'),
                                        'football_state': v.get('footballStateFindingTexts')})
            if seed % 50 == 0:
                print(f'seed {seed} checked at {len(roots)} heads', flush=True)
    result = {'records': len(paths), 'heads': {r: {**a, 'finding_texts': dict(a['finding_texts'])} for r, a in per_root.items()}}
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    for r, a in per_root.items():
        print(f"{r}: {a['seeds']} seeds, accepted {a['accepted']}, validation passed {a['passed']}, "
              f"validation-finding seeds {a['validation_finding_seeds']}, football-state-finding seeds {a['football_finding_seeds']}")


if __name__ == '__main__':
    main()
