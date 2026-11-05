#!/usr/bin/env python3
"""Add the 2026 week 9 team kicker rows to the pinned kicker table, under build_kicker_table.py's own assignment rule.

The pinned table stops at week 8, because its assignments were read from the weekly roster captured on 2026-11-04. The
kicker fits (kickers) are unchanged; only assignments gain week 9 rows. Each team's week 9 kicker is the one ACT kicker on
the weekly roster. A team with none takes its single DEV (practice-squad) kicker, as build_kicker_table.py does. Anything
else refuses, and a team that cannot be resolved gets no row, so the engine refuses that team's game.

Usage: python3 extend_kicker_table_week9.py --roster roster_weekly_2026.parquet --out OUT.json
"""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
PINNED = HERE / 'kicker_table_through_2025_assign_2026.json'
WEEK = 9


def week_assignments(roster, week):
    t = pq.read_table(roster, columns=['season', 'week', 'team', 'position', 'status', 'gsis_id']).to_pydict()
    active, practice, teams = defaultdict(set), defaultdict(set), set()
    for i in range(len(t['week'])):
        if int(t['week'][i]) != week or int(t['season'][i]) != 2026:
            continue
        team = t['team'][i]
        teams.add(team)
        if t['position'][i] != 'K':
            continue
        if t['status'][i] == 'ACT':
            active[team].add(t['gsis_id'][i])
        elif t['status'][i] == 'DEV':
            practice[team].add(t['gsis_id'][i])
    rows, unresolved = [], []
    for team in sorted(teams):
        if len(active[team]) > 1:
            raise ValueError(f'{team} has more than one active kicker in week {week}: {sorted(active[team])}')
        if active[team]:
            rows.append([2026, week, team, next(iter(active[team]))])
        elif len(practice[team]) == 1:
            rows.append([2026, week, team, next(iter(practice[team]))])
        else:
            unresolved.append(team)
    return rows, unresolved


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--roster', required=True, help='nflverse roster_weekly_2026.parquet')
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    pinned = json.loads(PINNED.read_text())
    if any(row[1] == WEEK for row in pinned['assignments']):
        raise SystemExit(f'the pinned table already has week {WEEK} rows')
    rows, unresolved = week_assignments(a.roster, WEEK)
    table = dict(pinned)
    table['assignments'] = pinned['assignments'] + rows
    table['extended_weeks'] = {'season': 2026, 'week': WEEK, 'rule': 'build_kicker_table.py assignment rule on the weekly roster',
                               'roster_sha256': hashlib.sha256(Path(a.roster).read_bytes()).hexdigest(),
                               'pinned_table_sha256': hashlib.sha256(PINNED.read_bytes()).hexdigest(),
                               'rows': len(rows), 'unresolved_teams': unresolved}
    Path(a.out).write_text(json.dumps(table, indent=1, sort_keys=True) + '\n')
    print(f'wrote {a.out}: {len(rows)} week {WEEK} team rows; unresolved {unresolved or "none"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
