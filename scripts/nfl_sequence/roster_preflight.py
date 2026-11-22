"""One preflight for every NFL run: resolve each team's playable roster from a pregame snapshot, and check a run used it.

The depth chart is not the game-day roster. resolve() feeds the snapshot's depth chart and injury report through
roster_resolution.resolve_team (the lp-nfl-resolved-roster-2 contract): Out and inactive players are excluded, the
highest-ranked eligible backup is promoted, original depth ranks and every exclusion reason are kept. check() turns that
into the PASS/FAIL table a run must clear. postflight() reads a finished run's player box scores and fails when an
excluded player got any stats or a team's passer was not its resolved QB1.

Snapshot builders call resolve() and refuse on any FAIL; runners call check() before a run and postflight() after it.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta

import roster_resolution

MAX_DEPTH_AGE = timedelta(hours=24)
# Roles every team must fill. One group per role family, so one player never fills two slots of the same family.
ROLES = [
    {'role': 'QB1', 'positions': ['QB'], 'required': True, 'group': 'QB'},
    {'role': 'RB1', 'positions': ['RB'], 'required': True, 'group': 'RB'},
    {'role': 'WR1', 'positions': ['WR'], 'required': True, 'group': 'WR'},
    {'role': 'WR2', 'positions': ['WR'], 'required': True, 'group': 'WR'},
    {'role': 'TE1', 'positions': ['TE'], 'required': True, 'group': 'TE'},
    {'role': 'PK', 'positions': ['PK', 'K'], 'required': True, 'group': 'PK', 'kind': 'PK'},
]
INJURY = {'Out': 'OUT', 'Doubtful': 'DOUBTFUL', 'Questionable': 'QUESTIONABLE'}


def _utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def _z(text):
    return _utc(text).strftime('%Y-%m-%dT%H:%M:%SZ')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def unwrap(snapshot):
    """The pregame snapshot inside a runner file, or the snapshot itself."""
    return snapshot.get('pregame_snapshot', snapshot)


def resolve(snapshot):
    """{'away': resolved, 'home': resolved, 'matchup_blocks': [...], 'content_hash': ...} for one pregame snapshot."""
    snap = unwrap(snapshot)
    as_of = _z(snap['as_of'])
    out = {}
    for side in ('away', 'home'):
        roster = snap['rosters'][side]
        report = roster.get('injury_report') or {}
        status = {p['gsis_id']: p['report_status'] for p in report.get('players', [])}
        rows = {}
        for p in roster['players']:
            row = rows.setdefault(p['gsis_id'], {
                'gsis_id': p['gsis_id'], 'name': p['player_name'], 'pos': p['pos_abb'], 'membership': 'ACTIVE_ROSTER',
                'depth_rank': p['pos_rank'], 'injury': INJURY.get(status.get(p['gsis_id'])),
                'observed_utc': _z(roster['snapshot_at']), 'positions': []})
            row['positions'].append((p['pos_abb'], p['pos_rank']))
        out[side] = roster_resolution.resolve_team(snap['schedule']['game_id'], roster['team'], as_of,
                                                   list(rows.values()), [], ROLES)
    out['matchup_blocks'] = roster_resolution.check_matchup([out['away'], out['home']])
    out['content_hash'] = _digest({k: (v['content_hash'] if isinstance(v, dict) else v) for k, v in out.items()})
    return out


def resolved_qb1(resolved_team):
    return next(r['gsis_id'] for r in resolved_team['roles'] if r['role'] == 'QB1')


def excluded(resolved_team):
    """{gsis_id: (name, exclusion reason)} for players the resolver removed."""
    return {p['gsis_id']: (p['name'], p['exclusion_reason']) for p in resolved_team['players'] if not p['official_eligible']}


def check(snapshot, market_qbs=None):
    """(rows, resolved): rows are (check, PASS/FAIL, detail). market_qbs is {team: {gsis ids with a passing-yards prop}}
    or None when no market is checked."""
    snap = unwrap(snapshot)
    resolved = resolve(snapshot)
    cutoff = _utc(snap['as_of'])
    rows = []
    for side in ('away', 'home'):
        roster, res = snap['rosters'][side], resolved[side]
        team = roster['team']
        age = cutoff - _utc(roster['snapshot_at'])
        rows.append((f'{team} depth chart current', 'PASS' if age <= MAX_DEPTH_AGE else 'FAIL',
                     f"{roster['snapshot_at']}, {age.total_seconds() / 3600:.1f}h before the cutoff"))
        report = roster.get('injury_report') or {}
        published = [p.get('published_utc') for p in report.get('players', [])]
        late = [t for t in published if t and _utc(t) > cutoff]
        ok = bool(report.get('players')) and all(published) and not late
        rows.append((f'{team} injury report applies to this game', 'PASS' if ok else 'FAIL',
                     f"{len(published)} statuses, {sum(1 for t in published if not t)} without a publish time, "
                     f"{len(late)} after the cutoff, {len(report.get('obsolete', []))} dropped as from a previous game"))
        qb = resolved_qb1(res)
        role = next(r for r in res['roles'] if r['role'] == 'QB1')
        names = {p['gsis_id']: p['name'] for p in res['players']}
        detail = f"{names.get(qb)} ({qb})" if qb else 'none'
        if role['extra'].get('promoted'):
            detail += ' promoted over ' + ', '.join(f"{names[g]} [{excluded(res)[g][1]}]" for g in role['extra']['excluded_ranked_ahead'])
        rows.append((f'{team} resolved eligible QB1', 'PASS' if qb and role['status'] == 'ASSIGNED' else 'FAIL', detail))
        if market_qbs is not None:
            priced = market_qbs.get(team, set())
            rows.append((f'{team} resolved QB1 has a passing-yards prop', 'PASS' if qb in priced else 'FAIL',
                         f"priced: {sorted(names.get(g, g) for g in priced) or 'none'}"))
        rows.append((f'{team} unresolved required roles', 'PASS' if not res['blocks'] else 'FAIL',
                     ', '.join(res['blocks']) or '0'))
    rows.append(('conflicting player-team memberships', 'PASS' if not resolved['matchup_blocks'] else 'FAIL',
                 ', '.join(resolved['matchup_blocks']) or '0'))
    return rows, resolved


def postflight(snapshot, run_output, resolved=None):
    """Rows for a finished run: excluded players with stats, and seeds whose passer was not the resolved QB1."""
    snap = unwrap(snapshot)
    resolved = resolved or resolve(snapshot)
    teams = {snap['rosters'][s]['team']: resolved[s] for s in ('away', 'home')}
    seeds = run_output.get('player_boxscores_by_seed') or []
    if not seeds:
        return [('run has player box scores', 'FAIL', 'no player_boxscores_by_seed')]
    out_hits, passers = Counter(), {t: Counter() for t in teams}
    for seed in seeds:
        for p in seed['players']:
            res = teams.get(p.get('player_team'))
            if res is None:
                continue
            if p['player_id'] in excluded(res):
                out_hits[(p['player_team'], p['player_name'])] += 1
            if (p.get('passing') or {}).get('att'):
                passers[p['player_team']][p['player_id']] += 1
    rows = [('run has player box scores', 'PASS', f'{len(seeds)} seeds'),
            ('excluded players receiving stats', 'PASS' if not out_hits else 'FAIL',
             ', '.join(f'{t} {n} in {c} seeds' for (t, n), c in out_hits.items()) or '0')]
    for team, res in teams.items():
        qb = resolved_qb1(res)
        top = passers[team].most_common(1)
        main = top[0][0] if top else None
        rows.append((f'{team} simulated passer is the resolved QB1', 'PASS' if main == qb else 'FAIL',
                     f'most seeds: {main}, resolved: {qb}'))
    return rows


def render(title, rows):
    width = max(len(r[0]) for r in rows)
    return '\n'.join([title] + [f'  {name:<{width}}  {result}  {detail}' for name, result, detail in rows])


def failed(rows):
    return [r for r in rows if r[1] != 'PASS']
