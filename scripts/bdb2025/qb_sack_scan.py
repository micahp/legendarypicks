#!/usr/bin/env python3
"""List every play with a qb_sack tracking event, across the nine staged weeks.

Writes /root/nfl-tracking-data/bdb2025/audit/qb_sack_plays.json (outside git). Used by the eligibility step.
"""
import json
D = '/root/nfl-tracking-data/bdb2025/code-data'
OUT = '/root/nfl-tracking-data/bdb2025/audit/qb_sack_plays.json'
sack = set()
for w in range(1, 10):
    with open(f'{D}/tracking_week_{w}.csv', newline='', encoding='utf-8') as f:
        for line in f:
            s = line.rstrip('\r\n')
            if s.startswith('"gameId"'):
                continue
            if s.endswith(',"qb_sack"') or s.endswith(',qb_sack'):
                g, p = s.split(',', 2)[:2]
                sack.add((g, p))
json.dump(sorted(list(k) for k in sack), open(OUT, 'w'))
print('plays with a qb_sack event:', len(sack))
