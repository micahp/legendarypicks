"""Frozen lp-nfl-resolved-roster-2 teams -> starter rows for the SLC batch (SLC-NFL-ROSTER-RESOLUTION-V2).

The converter refuses unless every check passes; it never fills a gap with a guess:
* each team's content hash recomputes from its own body,
* each team has no blocks,
* all 28 starter roles are assigned or projected, and every role name is known,
* every role player has an LP player id and a jersey number,
* nothing in the frozen file is dated after its cutoff.

It writes one row per starter role, with the group, position and rank the batch needs. Backups are not in the resolver's
output yet, so the rows are starters only. The old full-depth consumer keeps its own pins and is not changed here.
"""
from __future__ import annotations

import json

import roster_resolution as rr

# role name -> (group, position, rank). Holder and kick returner are special-teams slots.
ROLE_SLOTS = {
    'QB1': ('OFF', 'QB', 1), 'RB1': ('OFF', 'RB', 1), 'WR1': ('OFF', 'WR', 1), 'WR2': ('OFF', 'WR', 2),
    'WR3': ('OFF', 'WR', 3), 'TE1': ('OFF', 'TE', 1), 'LT': ('OFF', 'LT', 1), 'LG': ('OFF', 'LG', 1),
    'C': ('OFF', 'C', 1), 'RG': ('OFF', 'RG', 1), 'RT': ('OFF', 'RT', 1),
    'DL1': ('DEF', 'DL', 1), 'DL2': ('DEF', 'DL', 2), 'DL3': ('DEF', 'DL', 3), 'DL4': ('DEF', 'DL', 4),
    'LB1': ('DEF', 'LB', 1), 'LB2': ('DEF', 'LB', 2), 'LB3': ('DEF', 'LB', 3),
    'CB1': ('DEF', 'CB', 1), 'CB2': ('DEF', 'CB', 2), 'S1': ('DEF', 'S', 1), 'S2': ('DEF', 'S', 2),
    'PK': ('ST', 'K', 1), 'P': ('ST', 'P', 1), 'LS': ('ST', 'LS', 1), 'H': ('ST', 'H', 1),
    'KR': ('ST', 'KR', 1), 'PR': ('ST', 'PR', 1),
}
STARTER_ROLES = 28
SCHEMA_IN = rr.SCHEMA


def _verify_team(team, result):
    body = {key: value for key, value in result.items() if key != 'content_hash'}
    if rr._digest(body) != result.get('content_hash'):
        raise ValueError(f'{team}: content hash does not recompute; the frozen file was changed')
    if result.get('blocks'):
        raise ValueError(f"{team}: refused, blocks present: {', '.join(result['blocks'])}")


def convert(frozen, lp_ids, jerseys):
    """Per-team starter rows. `lp_ids` maps GSIS id -> LP player id; `jerseys` maps GSIS id -> jersey number."""
    if frozen.get('schema') != SCHEMA_IN:
        raise ValueError(f"unsupported schema {frozen.get('schema')!r}")
    if frozen.get('forecast_class') == 'GAMEDAY_FINAL':
        raise ValueError('GAMEDAY_FINAL rosters are not converted while elevations or inactives are unverified')
    cutoff = frozen['as_of_utc']
    teams = frozen.get('teams', {})
    if not teams:
        raise ValueError('no teams in the frozen roster')
    out = {}
    for team, result in sorted(teams.items()):
        _verify_team(team, result)
        if result.get('as_of_utc') != cutoff:
            raise ValueError(f'{team}: as_of differs from the frozen file cutoff')
        roles = result.get('roles', [])
        if len(roles) != STARTER_ROLES:
            raise ValueError(f'{team}: {len(roles)} starter roles, need {STARTER_ROLES}')
        rows = []
        for role in roles:
            name = role['role']
            if name not in ROLE_SLOTS:
                raise ValueError(f'{team}: unknown role {name!r}')
            if role['status'] not in ('ASSIGNED', 'PROJECTED'):
                raise ValueError(f"{team}: role {name} is {role['status']}")
            gsis = role['gsis_id']
            if gsis is None:
                raise ValueError(f'{team}: role {name} has no player')
            if gsis not in lp_ids:
                raise ValueError(f'{team}: role {name} player {gsis} has no LP player id')
            if gsis not in jerseys:
                raise ValueError(f'{team}: role {name} player {gsis} has no jersey number')
            group, pos, rank = ROLE_SLOTS[name]
            name_of = next(p['name'] for p in result['players'] if p['gsis_id'] == gsis)
            rows.append({'gsis_id': gsis, 'player_id': lp_ids[gsis], 'player_name': name_of,
                         'jersey_number': jerseys[gsis], 'group': group, 'pos_abb': pos, 'pos_rank': rank,
                         'role': name, 'starter': True,
                         'projection_status': 'PROJECTED_ELEVATION' if role['status'] == 'PROJECTED' else None})
        out[team] = {'team': team, 'as_of_utc': cutoff, 'forecast_class': frozen['forecast_class'],
                     'content_hash': result['content_hash'], 'players': sorted(rows, key=lambda r: (r['group'], r['pos_abb'], r['pos_rank']))}
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('frozen')
    ap.add_argument('--lp-ids', required=True, help='JSON object: GSIS id -> LP player id')
    ap.add_argument('--jerseys', required=True, help='JSON object: GSIS id -> jersey number')
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    frozen = json.load(open(a.frozen))
    out = convert(frozen, json.load(open(a.lp_ids)), json.load(open(a.jerseys)))
    with open(a.out, 'w') as f:
        json.dump(out, f, indent=1, sort_keys=True)
    for team, body in out.items():
        print(team, len(body['players']), 'starter rows, content_hash', body['content_hash'][:12])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
