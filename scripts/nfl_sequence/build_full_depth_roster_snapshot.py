#!/usr/bin/env python3
"""Build a pinned KC-SEA full depth-chart roster with per-role starter flags and jersey numbers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEPTH_GROUPS = {'3WR 1TE', 'Special Teams'}
DEPTH_COLUMNS = ['dt', 'team', 'player_name', 'gsis_id', 'pos_grp', 'pos_abb', 'pos_rank']
ROSTER_COLUMNS = ['team', 'week', 'game_type', 'jersey_number', 'gsis_id', 'full_name']


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_depth_date(table: dict, team: str) -> str:
    dates = sorted({str(dt) for dt, code in zip(table['dt'], table['team']) if code == team})
    if not dates:
        raise ValueError(f'no nflverse depth-chart rows for {team}')
    return dates[-1]


def resolve_player_ids(gsis_ids: set[str], db_path: str) -> dict[str, int]:
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    try:
        ids = {}
        for gsis_id in sorted(gsis_ids):
            row = con.execute(
                "SELECT id FROM players WHERE league='nfl' AND nfl_gsis_id=? LIMIT 1", (gsis_id,)
            ).fetchone()
            if row:
                ids[gsis_id] = row[0]
        missing = sorted(gsis_ids - ids.keys())
        if missing:
            raise ValueError(f'{len(missing)} depth-chart players have no canonical LP player id: {missing[:5]}')
        return ids
    finally:
        con.close()


def drop_off_roster(team: str, rows: dict, starts: set, on_roster) -> tuple[dict, set, list, list]:
    """Remove depth rows for players who are not on this team's jersey-week roster.

    rows maps (group, pos, rank, gsis) to a player name; starts holds the builder-selected starter roles; on_roster(gsis)
    says whether the player is on the roster. Each starting role a removed player held goes to the best rostered backup
    at the same group and position, and the rostered backup keeps its own rank. Returns (kept rows, starter roles,
    removed role rows, promotions). Raises ValueError when a starting role has no rostered backup.
    """
    removed = sorted(role for role in rows if not on_roster(role[3]))
    kept = {role: name for role, name in rows.items() if on_roster(role[3])}
    active = set(starts) - set(removed)
    promotions = []
    for role in sorted(set(starts) & set(removed)):
        group, pos, rank, gsis = role
        backups = sorted((r for r in kept if r[0] == group and r[1] == pos and r not in active), key=lambda r: r[2])
        if not backups:
            raise ValueError(f'{team} has no rostered backup for {pos} {rank} after {gsis} left the week roster')
        active.add(backups[0])
        promotions.append({'group': group, 'pos_abb': pos, 'pos_rank': rank, 'replaced_gsis_id': gsis,
                           'promoted_gsis_id': backups[0][3], 'promoted_pos_rank': backups[0][2]})
    return kept, active, removed, promotions


def build(args) -> tuple[dict, dict]:
    starter_path = Path(args.starter_snapshot)
    starter_provenance_path = Path(args.starter_provenance)
    depth_path = Path(args.depth_charts)
    roster_path = Path(args.roster)
    starter_bytes = starter_path.read_bytes()
    starter = json.loads(starter_bytes)
    starter_provenance = json.loads(starter_provenance_path.read_text())
    starter_sha = hashlib.sha256(starter_bytes).hexdigest()
    if starter.get('schema') != 'lp-nfl-starters-snapshot-1':
        raise ValueError('the starter input does not use lp-nfl-starters-snapshot-1')
    if starter_provenance.get('output', {}).get('sha256') != starter_sha:
        raise ValueError('the starter snapshot does not match its provenance hash')

    source_artifacts = starter_provenance.get('source_artifacts', [])
    by_name = {item['name']: item for item in source_artifacts}
    for path in (depth_path, roster_path):
        pin = by_name.get(path.name)
        if not pin or sha256(path) != pin.get('sha256'):
            raise ValueError(f'{path.name} does not match the pinned nflverse source hash')

    depth = pq.read_table(depth_path, columns=DEPTH_COLUMNS).to_pydict()
    roster_table = pq.read_table(roster_path, columns=ROSTER_COLUMNS).to_pydict()
    regular_weeks = [week for week, kind in zip(roster_table['week'], roster_table['game_type']) if kind == 'REG']
    jersey_week = max(regular_weeks) if regular_weeks else None
    if jersey_week != args.jersey_week:
        raise ValueError(f'nflverse roster source is at week {jersey_week}; the frozen game is week {args.jersey_week}')

    jersey_by_id = {}
    target_teams = {starter['rosters'][side]['team'] for side in ('away', 'home')}
    for i, gsis_id in enumerate(roster_table['gsis_id']):
        if roster_table['game_type'][i] != 'REG' or roster_table['week'][i] != jersey_week:
            continue
        if roster_table['team'][i] not in target_teams or not gsis_id:
            continue
        value = (roster_table['team'][i], roster_table['jersey_number'][i])
        old = jersey_by_id.get(gsis_id)
        if old is not None and old != value:
            raise ValueError(f'conflicting week {jersey_week} roster rows for GSIS id {gsis_id}')
        jersey_by_id[gsis_id] = value

    staged = {}
    for side in ('away', 'home'):
        team_roster = starter['rosters'][side]
        team = team_roster['team']
        depth_date = latest_depth_date(depth, team)
        if depth_date != team_roster['depth_chart_dt']:
            raise ValueError(f'{team} latest depth-chart date differs from the pinned starter snapshot')
        groups = DEPTH_GROUPS | {team_roster['defense_group']}
        rows = {}
        for i in range(len(depth['dt'])):
            if (depth['team'][i] != team or str(depth['dt'][i]) != depth_date
                    or depth['pos_grp'][i] not in groups or not depth['gsis_id'][i]
                    or depth['pos_rank'][i] is None or int(depth['pos_rank'][i]) < 1):
                continue
            role = (depth['pos_grp'][i], depth['pos_abb'][i], int(depth['pos_rank'][i]), depth['gsis_id'][i])
            player_name = depth['player_name'][i]
            previous = rows.get(role)
            if previous is not None and previous != player_name:
                raise ValueError(f'{team} has conflicting depth-chart names for role {role}')
            rows[role] = player_name

        starts = {
            (player['group'], player['pos_abb'], player['pos_rank'], player['gsis_id'])
            for player in team_roster['players']
        }
        if len(starts) != 28 or not starts.issubset(rows):
            raise ValueError(f'{team} full depth chart does not contain the 28 builder-selected starters')
        staged[side] = (team_roster, depth_date, rows, starts)
    def on_roster(team, gsis_id):
        entry = jersey_by_id.get(gsis_id)
        return entry is not None and entry[0] == team and entry[1] is not None

    unique_ids = {role[3] for team_roster, _, rows, _ in staged.values() for role in rows
                  if on_roster(team_roster['team'], role[3])}
    player_ids = resolve_player_ids(unique_ids, args.db)
    rosters = {}
    for side, (team_roster, depth_date, rows, starts) in staged.items():
        team = team_roster['team']
        kept, active, removed, promotions = drop_off_roster(
            team, rows, starts, lambda gsis_id, team=team: on_roster(team, gsis_id))
        players = []
        role_keys = set()
        for group, pos, rank, gsis_id in sorted(kept):
            roster_entry = jersey_by_id.get(gsis_id)
            if roster_entry is None or roster_entry[0] != team or roster_entry[1] is None:
                raise ValueError(f'{team} full depth chart player {gsis_id} has no week {jersey_week} jersey number')
            role_key = (group, pos, rank)
            if role_key in role_keys:
                raise ValueError(f'{team} full depth chart has duplicate role {role_key}')
            role_keys.add(role_key)
            players.append({
                'gsis_id': gsis_id, 'player_id': player_ids[gsis_id], 'player_name': kept[(group, pos, rank, gsis_id)],
                'pos_abb': pos, 'pos_rank': rank, 'group': group,
                'unit': 'offense' if group == '3WR 1TE' else 'special_teams' if group == 'Special Teams' else 'defense',
                'snapshot_at': depth_date, 'source': 'nflverse_depth_charts', 'team': team,
                'jersey_number': int(roster_entry[1]),
                'starter': (group, pos, rank, gsis_id) in active,
            })
        if sum(player['starter'] for player in players) != 28:
            raise ValueError(f'{team} full depth chart must mark exactly 28 starter roles')
        rosters[side] = {
            'team': team, 'depth_chart_dt': depth_date, 'defense_group': team_roster['defense_group'],
            'jersey_week': jersey_week, 'players': players, 'missing': [],
            'not_on_roster': sorted({gsis_id for _, _, _, gsis_id in removed}),
            'promotions': promotions,
        }

    generated_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    doc = {
        'schema': 'lp-nfl-full-depth-roster-snapshot-1',
        'generated_at': generated_at,
        'source': 'nflverse_depth_charts',
        'roster_source': 'nflverse_rosters',
        'source_artifacts': source_artifacts,
        'starter_snapshot_sha256': starter_sha,
        'rosters': rosters,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n')

    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=REPO, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True).strip())
    builder_path = Path(__file__).resolve()
    builder_file = builder_path.relative_to(REPO).as_posix()
    provenance = {
        'schema': 'lp-nfl-full-depth-roster-provenance-1',
        'starter_builder': starter_provenance['builder'],
        'starter_snapshot': {'file': starter_path.name, 'sha256': starter_sha},
        'full_depth_builder': {
            'repository': 'micahp/legendarypicks', 'branch': branch, 'commit': commit,
            'file': builder_file, 'file_sha256': sha256(builder_path), 'worktree_dirty': dirty,
        },
        'source_artifacts': source_artifacts,
        'identity_lookup': {
            'source': 'Legendary Picks canonical players table',
            'join': 'players.league = nfl AND players.nfl_gsis_id = depth_chart.gsis_id',
            'mode': 'read-only', 'resolved_unique_players': len(unique_ids), 'unresolved_unique_players': 0,
        },
        'output': {
            'file': out_path.name, 'sha256': sha256(out_path), 'generated_at': generated_at,
            'role_row_counts': {rosters[s]['team']: len(rosters[s]['players']) for s in rosters},
            'unique_player_counts': {rosters[s]['team']: len({p['gsis_id'] for p in rosters[s]['players']}) for s in rosters},
            'starter_role_counts': {rosters[s]['team']: sum(p['starter'] for p in rosters[s]['players']) for s in rosters},
            'missing_jersey_numbers': 0,
        },
    }
    provenance_path = Path(args.provenance_out)
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + '\n')
    return doc, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--depth-charts', required=True)
    parser.add_argument('--roster', required=True)
    parser.add_argument('--starter-snapshot', required=True)
    parser.add_argument('--starter-provenance', required=True)
    parser.add_argument('--db', required=True, help='LP identity database opened read-only')
    parser.add_argument('--out', required=True)
    parser.add_argument('--provenance-out', required=True)
    parser.add_argument('--jersey-week', type=int, default=7,
                        help='regular-season week the nflverse roster source must be at (the frozen game week)')
    args = parser.parse_args()
    doc, provenance = build(args)
    for side in ('away', 'home'):
        roster = doc['rosters'][side]
        print(f"{roster['team']}: {len(roster['players'])} role rows, "
              f"{len({p['gsis_id'] for p in roster['players']})} unique players, "
              f"{sum(p['starter'] for p in roster['players'])} starter roles, 0 jersey gaps")
    print(f"wrote {args.out} sha256={provenance['output']['sha256']}")


if __name__ == '__main__':
    main()
