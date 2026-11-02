"""2025 coverage and provenance for the depth-chart adapter.

For each 2025 regular-season game, each team, and each horizon (early and final), selects the depth state the adapter would
use and writes one row to outputs/depth_coverage_2025.csv. Each row carries the cutoff, the snapshot used, the staleness,
the identity counts, and a check that the snapshot is at or before the cutoff. Reads the database read only.

Run from the repository root:
    python3 docs/research/slc-v2-depth-adapter-2026-11-02/build_coverage.py
"""
import csv
import os
import sqlite3
import statistics
import sys
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'scripts'))
import depth_adapter as da  # noqa: E402
from nfl_team_codes import to_nflverse_team_code  # noqa: E402

DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
DEPTH = '/root/gridiron-playbooks-research/data/raw/depth_charts_2025.parquet'
PLAYERS = '/root/gridiron-playbooks-research/data/raw/players.csv'
OUT = os.path.join(HERE, 'outputs', 'depth_coverage_2025.csv')


def schedule_games():
    con = sqlite3.connect(DB, uri=True)
    try:
        return con.execute("select game_id, gameday, gametime, home_team, away_team from nfl_schedule "
                           "where season = 2025 and game_type = 'REG' order by gameday, game_id").fetchall()
    finally:
        con.close()


def main():
    rows = da.load_snapshot_rows(DEPTH)
    index = da.identity_index_from_players(PLAYERS)
    store = da.SnapshotStore(rows)
    sha = rows[0]['source_sha256']
    depth_teams = set(store.sorted_times)
    games = [(gid, day, time, to_nflverse_team_code(home), to_nflverse_team_code(away))
             for gid, day, time, home, away in schedule_games()]
    missing_teams = sorted({t for g in games for t in (g[3], g[4]) if t not in depth_teams})
    if missing_teams:
        raise SystemExit(f'schedule teams absent from the depth file: {missing_teams}')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fields = ['game_id', 'team', 'horizon', 'cutoff_utc', 'reason', 'snapshot_dt_utc', 'snapshot_le_cutoff',
              'staleness_hours', 'source_sha256', 'entries', 'gsis', 'gsis_unverified', 'espn_unique', 'ambiguous',
              'unmatched', 'duplicate_slot', 'duplicate_identity', 'unknown_role']
    reasons = collections.Counter()
    staleness = collections.defaultdict(list)
    with open(OUT, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for game_id, gameday, gametime, home, away in games:
            early, final = da.game_horizons(gameday, gametime)
            for team in (home, away):
                for horizon, cutoff in (('early', early), ('final', final)):
                    state = da.depth_state(store, team, cutoff, index, source_sha256=sha)
                    snap = state['snapshot_dt']
                    le = snap is None or snap <= cutoff
                    if not le:
                        raise AssertionError(f'{game_id} {team} {horizon}: snapshot {snap} after cutoff {cutoff}')
                    reasons[(horizon, state['reason'])] += 1
                    if state['staleness_seconds'] is not None:
                        staleness[horizon].append(state['staleness_seconds'] / 3600)
                    c = state['counts']
                    writer.writerow({
                        'game_id': game_id, 'team': team, 'horizon': horizon,
                        'cutoff_utc': cutoff.isoformat(), 'reason': state['reason'],
                        'snapshot_dt_utc': snap.isoformat() if snap else '', 'snapshot_le_cutoff': le,
                        'staleness_hours': round(state['staleness_seconds'] / 3600, 2) if state['staleness_seconds'] is not None else '',
                        'source_sha256': sha, 'entries': len(state['entries']),
                        'gsis': c['gsis'], 'gsis_unverified': c['gsis_unverified'], 'espn_unique': c['espn_unique'],
                        'ambiguous': c['ambiguous'], 'unmatched': c['unmatched'],
                        'duplicate_slot': c['duplicate_slot'], 'duplicate_identity': c['duplicate_identity'],
                        'unknown_role': c['unknown_role'],
                    })
    print('games', len(games), 'depth teams', len(depth_teams), 'source sha256', sha)
    for key, count in sorted(reasons.items()):
        print('  ', key, count)
    for horizon, values in sorted(staleness.items()):
        print(f'   staleness hours, {horizon}: median {statistics.median(values):.1f}, max {max(values):.1f}, n {len(values)}')
    print('wrote', OUT)


if __name__ == '__main__':
    main()
