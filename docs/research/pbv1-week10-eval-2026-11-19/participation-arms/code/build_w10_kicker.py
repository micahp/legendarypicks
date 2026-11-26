"""Add week 10 kicker rows to the week 9 table, from the 2026 weekly roster published 2026-11-11 07:04 UTC.
Publisher time is before every Week 10 cutoff (earliest 2026-11-11 12:00 UTC). Same assignment rule as the pinned table."""
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, '/root/tnf-batch/kicker')
import extend_kicker_table_week9 as ext

BASE = Path('/root/lp-slc-v2/docs/research/fg-kicker-2026-11-04/kicker_table_through_2025_assign_2026_w09.json')
ROSTER = Path('/root/lp-slc-v2/docs/research/slc-was-nyg-tnf-2026-11-12/capture/roster_weekly_2026.parquet')
OUT = Path('/root/tnf-batch/kicker/kicker_table_through_2026_w10.json')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


pinned = json.loads(BASE.read_text())
assert not any(r[1] == 10 for r in pinned['assignments']), 'base already has week 10'
import pyarrow.parquet as pq
from collections import defaultdict
t = pq.read_table(str(ROSTER), columns=['season', 'week', 'team', 'position', 'status', 'gsis_id']).to_pydict()
active, practice, teams = defaultdict(set), defaultdict(set), set()
for i in range(len(t['week'])):
    if int(t['week'][i]) != 10 or int(t['season'][i]) != 2026:
        continue
    teams.add(t['team'][i])
    if t['position'][i] != 'K':
        continue
    if t['status'][i] == 'ACT':
        active[t['team'][i]].add(t['gsis_id'][i])
    elif t['status'][i] == 'DEV':
        practice[t['team'][i]].add(t['gsis_id'][i])
prev = {team: pid for season, week, team, pid in pinned['assignments'] if week == 9}
rows, unresolved, continuity = [], [], []
for team in sorted(teams):
    if len(active[team]) > 1 and prev.get(team) in active[team]:
        # Two active kickers: keep last week's kicker if he is one of them (continuity rule, stated in the report).
        active[team] = {prev[team]}
        continuity.append(team)
    if len(active[team]) > 1:
        unresolved.append(team)  # two active kickers and no continuity: no row, so the engine refuses that game
    elif active[team]:
        rows.append([2026, 10, team, next(iter(active[team]))])
    elif len(practice[team]) == 1:
        rows.append([2026, 10, team, next(iter(practice[team]))])
    else:
        unresolved.append(team)

table = dict(pinned)
table['assignments'] = pinned['assignments'] + rows
table['week10_extension'] = {'week': 10, 'rule': 'build_kicker_table.py assignment rule on the weekly roster',
                             'roster_sha256': sha(ROSTER), 'roster_last_modified_utc': '2026-11-11T07:04:34Z',
                             'base_sha256': sha(BASE), 'rows': len(rows), 'unresolved_teams': unresolved, 'continuity_resolved': continuity}
OUT.write_text(json.dumps(table, indent=1, sort_keys=True) + '\n')
print(f'wrote {OUT} sha256 {sha(OUT)} rows {len(rows)} unresolved {unresolved or "none"} continuity {continuity}')
