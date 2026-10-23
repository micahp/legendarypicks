#!/usr/bin/env python3
"""Does the archive's 2027 row reflect the 18 Sept 2026 in-season Madden 27 update?

The (old, new) overall pairs are the ones reported in the Yahoo Sports article dated
2026-09-18 (https://sports.yahoo.com/articles/madden-27-ratings-reveals-biggest-104642370.html),
transcribed as published. For each player the archive's 2027 OVR is compared with the old
and the new value. A launch-day snapshot matches 'old'; a snapshot taken after the update
matches 'new'. Players absent from the 2027 release are counted, not dropped.
"""

import argparse
import csv
import io
import json
import os
import sys
import zipfile
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_madden_ratings import norm_name  # noqa: E402

CHANGES = [
    ('T.J. Watt', 93, 96), ('Justin Jefferson', 94, 96), ('Fred Warner', 97, 98),
    ('Bijan Robinson', 95, 96), ('Lamar Jackson', 94, 95), ('Aidan Hutchinson', 93, 94),
    ('Derrick Henry', 93, 94), ('Zack Baun', 92, 93), ('Caleb Williams', 90, 91),
    ('Kenneth Walker', 90, 91), ('Quinyon Mitchell', 89, 90), ('Trey Hendrickson', 88, 89),
    ('Zay Flowers', 88, 89), ('Chris Olave', 87, 88), ('George Pickens', 87, 88),
    ("D'Andre Swift", 85, 86), ('Julian Love', 85, 86), ('Bucky Irving', 84, 85),
    ('Jaylen Waddle', 84, 85), ('Kevin Byard III', 84, 85), ('Jevon Holland', 83, 84),
    ('Landon Dickerson', 83, 84), ('Drake Maye', 92, 89), ('James Cook III', 94, 93),
    ('DeForest Buckner', 93, 92), ('Quinnen Williams', 92, 91), ('Josh Jacobs', 91, 90),
    ('Jaylon Johnson', 90, 89), ('Justin Herbert', 90, 89),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', required=True)
    ap.add_argument('--release', type=int, default=2027)
    ap.add_argument('--summary-json', required=True)
    args = ap.parse_args()

    zf = zipfile.ZipFile(args.zip)
    arch = list(csv.DictReader(io.StringIO(zf.read('out/madden_ratings_long.csv').decode('utf-8'))))
    by_name = defaultdict(list)
    for r in arch:
        if r['madden_release'] == str(args.release):
            by_name[norm_name(r['player_name'])].append(r)

    tally = {'old': 0, 'new': 0, 'other': 0, 'absent': 0, 'ambiguous': 0}
    rows = []
    for name, old, new in CHANGES:
        cands = by_name.get(norm_name(name), [])
        if not cands:
            tally['absent'] += 1
            rows.append({'player': name, 'old': old, 'new': new, 'archive': None, 'match': 'absent'})
            continue
        if len(cands) > 1:
            tally['ambiguous'] += 1
            rows.append({'player': name, 'old': old, 'new': new, 'archive': None, 'match': 'ambiguous'})
            continue
        v = int(cands[0]['OVR']) if cands[0]['OVR'].strip() else None
        tag = 'old' if v == old else 'new' if v == new else 'other'
        tally[tag] += 1
        rows.append({'player': name, 'old': old, 'new': new, 'archive': v, 'match': tag})

    print(f'release {args.release}: of {len(CHANGES)} reported changes, '
          f'archive matches old={tally["old"]}, new={tally["new"]}, other={tally["other"]}, '
          f'absent={tally["absent"]}, ambiguous={tally["ambiguous"]}')
    summary = {'release': args.release, 'changes_tested': len(CHANGES), 'tally': tally, 'rows': rows,
               'source': 'https://sports.yahoo.com/articles/madden-27-ratings-reveals-biggest-104642370.html',
               'source_date': '2026-09-18'}
    with open(args.summary_json, 'w') as f:
        json.dump(summary, f, indent=2)
        f.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
