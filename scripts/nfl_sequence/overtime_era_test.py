#!/usr/bin/env python3
"""Rule-era check for the observed overtime drive pool before the pool is pooled across eras.

The eras are the registry's regular-season overtime regimes (rule_regimes.regime_key, domain overtime), so the 2025 split
comes from the registry (2025-REG-OT-BOTH), not from a hard-coded year. Two comparisons are reported, each separately, with
a permutation p-value (era labels shuffled, fixed seed):

  1. outcome categories of the drive (touchdown, field goal made or missed, punt, turnover, other): chi-square statistic
  2. offensive points per drive: difference of means, two-sided

Source: docs/fixtures/e2/overtime_drives_2022_2025.csv (checked against its manifest). Stdlib only.

    python3 scripts/nfl_sequence/overtime_era_test.py
"""
import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import rule_regimes as rr

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'docs/fixtures/e2/overtime_drives_2022_2025.csv'
DEFAULT_OUT = REPO / 'docs/evidence/e2-overtime/overtime-drive-era-test.json'
SHUFFLES = 10000
SEED = 20261026
CATEGORIES = ('touchdown', 'field_goal_made', 'field_goal_missed', 'punt', 'turnover', 'other')


def category(outcome):
    if outcome in ('touchdown', 'defense_touchdown'):
        return 'touchdown'
    if outcome in ('field_goal_made', 'field_goal_missed', 'punt'):
        return outcome
    if outcome in ('turnover', 'turnover_on_downs'):
        return 'turnover'
    return 'other'


def chi_square(labels, cats):
    table, row, col = Counter(zip(labels, cats)), Counter(labels), Counter(cats)
    n, total = len(cats), 0.0
    for e in row:
        for c in col:
            expected = row[e] * col[c] / n
            total += (table.get((e, c), 0) - expected) ** 2 / expected
    return total


def mean_difference(labels, values):
    a = [v for v, lab in zip(values, labels) if lab == 'early']
    b = [v for v, lab in zip(values, labels) if lab == 'late']
    return sum(b) / len(b) - sum(a) / len(a)


def permutation_p(stat, labels, fn, two_sided):
    rng = random.Random(SEED)
    shuffled, hits = list(labels), 0
    for _ in range(SHUFFLES):
        rng.shuffle(shuffled)
        value = fn(shuffled)
        if (abs(value) >= abs(stat)) if two_sided else (value >= stat):
            hits += 1
    return (hits + 1) / (SHUFFLES + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    registry, registry_sha = rr.load_registry()
    rows = [r for r in csv.DictReader(SOURCE.open()) if int(r['week']) <= 18]
    keys = {}
    for r in rows:
        keys.setdefault(r['season'], rr.regime_key(registry, int(r['season']), 'REG', 'overtime'))
    era_keys = sorted(set(keys.values()), key=lambda k: min(int(s) for s, v in keys.items() if v == k))
    if len(era_keys) != 2:
        raise SystemExit(f'expected two overtime eras in the pool, found {len(era_keys)}')
    early_key, late_key = era_keys
    labels = ['early' if keys[r['season']] == early_key else 'late' for r in rows]
    cats = [category(r['outcome']) for r in rows]
    points = [int(r['points_offense']) for r in rows]
    chi = chi_square(labels, cats)
    diff = mean_difference(labels, points)
    manifest = json.loads(Path(f'{SOURCE}.manifest.json').read_text())
    source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if manifest['output']['sha256'] != source_sha:
        raise SystemExit('the overtime drive file does not match its manifest')
    result = {
        'source': str(SOURCE.relative_to(REPO)), 'source_sha256': source_sha,
        'registry_sha256': registry_sha, 'overtime_rules': {'early': list(early_key), 'late': list(late_key)},
        'seasons': {'early': sorted({s for s, v in keys.items() if v == early_key}),
                    'late': sorted({s for s, v in keys.items() if v == late_key})},
        'drives': {'early': labels.count('early'), 'late': labels.count('late')},
        'usable_drives': {e: sum(1 for r, lab in zip(rows, labels) if lab == e and r['status'] == 'usable')
                          for e in ('early', 'late')},
        'outcomes': {e: {c: sum(1 for x, y, z in zip(labels, cats, rows) if x == e and y == c) for c in CATEGORIES}
                     for e in ('early', 'late')},
        'chi_square': {'statistic': round(chi, 4), 'permutation_p': permutation_p(
            chi, labels, lambda lab: chi_square(lab, cats), two_sided=False), 'df_nominal': len(CATEGORIES) - 1},
        'points_per_drive': {e: round(sum(p for p, x in zip(points, labels) if x == e) / labels.count(e), 4)
                             for e in ('early', 'late')},
        'points_difference_late_minus_early': {'value': round(diff, 4), 'permutation_p_two_sided': permutation_p(
            diff, labels, lambda lab: mean_difference(lab, points), two_sided=True)},
        'shuffles': SHUFFLES, 'seed': SEED,
        'manifest': {'games_with_overtime': manifest['games_with_overtime'], 'drive_count': manifest['drive_count']},
        'decision': 'reported separately; the engine pool is unchanged (pooled 2022-2025) until a 2025-only sensitivity run',
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: result[k] for k in ('drives', 'usable_drives', 'chi_square', 'points_per_drive',
                                             'points_difference_late_minus_early')}, indent=2))


if __name__ == '__main__':
    main()
