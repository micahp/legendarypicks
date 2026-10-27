#!/usr/bin/env python3
"""Compare two pinned-validity arms seed by seed: which seeds changed, and why.

Usage: compare_safety_arm.py BASELINE.csv NEW.csv
Every seed is compared on every field. A changed seed is expected only if the baseline blocked it on a safety free kick.
"""
import csv
import sys
from collections import Counter


def load(path):
    with open(path, newline='') as f:
        return {int(r['seed']): r for r in csv.DictReader(f)}


def main(base_path, new_path):
    base, new = load(base_path), load(new_path)
    assert set(base) == set(new), (len(base), len(new))
    fields = [f for f in next(iter(base.values())).keys() if f != 'seed']
    changed = [s for s in sorted(base) if any(base[s][f] != new[s][f] for f in fields)]
    print(f'seeds: baseline {len(base)}, new {len(new)}; changed rows: {len(changed)}')
    print('baseline outcomes:', dict(Counter(r['outcome'] for r in base.values())))
    print('new outcomes:     ', dict(Counter(r['outcome'] for r in new.values())))
    transitions = Counter((base[s]['outcome'], new[s]['outcome']) for s in changed)
    print('transitions of changed seeds (baseline -> new):', dict(transitions))
    unexpected = [s for s in changed if 'safety' not in (base[s]['blocker'] + base[s]['scope_out']).lower()]
    print('changed seeds NOT baseline-blocked on a safety:', unexpected)
    print('baseline blockers of changed seeds:', dict(Counter(base[s]['blocker'] for s in changed)))
    print('new blockers of changed seeds:     ', dict(Counter(new[s]['blocker'] for s in changed)))
    print('changed seeds:', changed)
    diffs = Counter(f for s in changed for f in fields if base[s][f] != new[s][f])
    print('fields that differ on changed seeds:', dict(diffs))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
