#!/usr/bin/env python3
"""Independent cross-check: League Station per-edition preview vs the Madden archive.

League Station's free preview lists the top players per edition with an attribute row.
It shares no code or ID with the archive, so agreement on the same player and release is
evidence about the ratings themselves. Matching is by normalized name within a release;
only names that are unique in the archive for that release are compared. Attribute
mapping (SPD->SPEED etc.) is name-level, so disagreement on a renamed column is also a
check on the mapping.

The edition label for madden-25-2013.csv is decided by overlap, not by its file name.
"""

import argparse
import csv
import glob
import io
import json
import os
import re
import statistics
import sys
import zipfile
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_madden_ratings import norm_name  # noqa: E402

RENAME = {'SPD': 'SPEED', 'REL': 'RLS', 'IMP': 'IBL', 'TKL': 'TAK', 'MAN': 'MCV', 'ZON': 'ZCV'}
NON_ATTR = {'grp', 'Player', 'Pos', 'Ht', 'Wt'}


def edition_release(fname):
    base = os.path.basename(fname)[:-4]
    m = re.fullmatch(r'madden-(\d{2})', base)
    if m:
        return [2000 + int(m.group(1))]
    m = re.fullmatch(r'madden-(\d{4})', base)
    if m:
        return [int(m.group(1))]
    if base == 'madden-25-2013':
        return [2013, 2014]  # decided by overlap below
    raise ValueError(f'unrecognised edition file {base}')


def to_int(v):
    v = (v or '').strip()
    if v in ('', '--', '-'):
        return None
    try:
        return int(v)
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', required=True)
    ap.add_argument('--editions-dir', required=True)
    ap.add_argument('--summary-json', required=True)
    args = ap.parse_args()

    zf = zipfile.ZipFile(args.zip)
    arch = list(csv.DictReader(io.StringIO(zf.read('out/madden_ratings_long.csv').decode('utf-8'))))
    arch_cols = list(arch[0].keys())
    index = defaultdict(list)
    for r in arch:
        index[(int(r['madden_release']), norm_name(r['player_name']))].append(r)

    summary = {'editions': {}, 'per_attribute': {}}
    compared = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(args.editions_dir, 'madden-*.csv'))):
        ed = os.path.basename(path)
        with open(path, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        candidates = edition_release(path)
        best = None
        scores = {}
        for rel in candidates:
            hits = sum(1 for r in rows if len(index.get((rel, norm_name(r['Player'])), [])) == 1)
            scores[rel] = hits
        best = max(scores, key=scores.get)
        if len(candidates) > 1 and scores[candidates[0]] == scores[candidates[1]]:
            print(f'FAIL: {ed} overlap tie {scores}; cannot decide the release label')
            return 1
        matched = ambiguous = missing = 0
        for r in rows:
            cands = index.get((best, norm_name(r['Player'])), [])
            if not cands:
                missing += 1
                continue
            if len(cands) > 1:
                ambiguous += 1
                continue
            matched += 1
            a = cands[0]
            for col, val in r.items():
                if col in NON_ATTR:
                    continue
                target = RENAME.get(col, col)
                if target not in arch_cols:
                    continue
                lv, av = to_int(val), to_int(a[target])
                if lv is None or av is None:
                    continue
                compared[col].append((lv, av))
        summary['editions'][ed] = {'release_label': best, 'overlap_by_candidate': scores,
                                   'rows': len(rows), 'matched_unique': matched,
                                   'ambiguous_name_skipped': ambiguous, 'not_in_archive': missing}
        print(f'{ed}: release {best} (overlap {scores}); rows {len(rows)}, matched {matched}, '
              f'ambiguous {ambiguous}, not in archive {missing}')

    for col in sorted(compared):
        pairs = compared[col]
        exact = sum(1 for lv, av in pairs if lv == av)
        summary['per_attribute'][col] = {
            'archive_column': RENAME.get(col, col),
            'pairs': len(pairs),
            'exact_share': round(exact / len(pairs), 3),
            'mean_abs_diff': round(statistics.mean(abs(lv - av) for lv, av in pairs), 2),
        }
    print('per attribute (league station vs archive):')
    for col, v in summary['per_attribute'].items():
        print(f"  {col:>5} -> {v['archive_column']:<6} pairs {v['pairs']:>5}  exact {v['exact_share']:.3f}  "
              f"mean|diff| {v['mean_abs_diff']}")

    absent = sum(e['not_in_archive'] for e in summary['editions'].values())
    summary['same_release_absent_rows'] = absent
    print(f'FAIL: {absent} League Station rows have no same-release archive match' if absent else
          'PASS: every League Station row has a same-release archive match')
    with open(args.summary_json, 'w') as f:
        json.dump(summary, f, indent=2)
        f.write('\n')
    print(f'wrote {args.summary_json}')
    return 1 if absent else 0


if __name__ == '__main__':
    sys.exit(main())
