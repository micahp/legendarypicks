"""Where a player's modeled carry or target share comes from, before any game is simulated (research).

For one pregame snapshot and one player, this prints the pieces the Dirichlet workload layer starts from: the player's real share in
earlier seasons and in the current season before the cutoff, the eligible roster the draw is made over, the share each eligible player
gets after the floor and the position-group renormalisation, the fitted concentration, and the distribution of shares the layer draws.
It simulates no game and reads only the database and the snapshot, so it cannot show how team volume or play calling move a count.
"""
import argparse
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import player_shares as ps  # noqa: E402
import share_distributions as sd  # noqa: E402

ROLES = {'receive': ('receiver_player_id', 'pass', ps.TARGET_POSITIONS), 'carry': ('rusher_player_id', 'run', ps.CARRY_POSITIONS)}
DRAWS = 2000


def counts(con, seasons, role, last_week=None):
    """{team: {player: count}} and {team: total} for the seasons, regular season weeks up to last_week."""
    column, play_type, _ = ROLES[role]
    marks = ','.join('?' * len(seasons))
    sql = (f"SELECT posteam, {column}, COUNT(*) FROM nfl_pbp WHERE season IN ({marks}) AND week <= ? AND play_type = ? "
           f"AND posteam IS NOT NULL AND {column} IS NOT NULL GROUP BY posteam, {column}")
    by_team = defaultdict(dict)
    for team, player, n in con.execute(sql, (*seasons, 18 if last_week is None else last_week, play_type)):
        by_team[team][player] = n
    return by_team, {team: sum(players.values()) for team, players in by_team.items()}


def share(by_team, totals, team, player):
    total = totals.get(team, 0)
    return (by_team.get(team, {}).get(player, 0) / total) if total else None


def quantile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]


def attribute(db, snapshot_path, cutoff_season, last_week, team, gsis, role):
    snapshot = json.loads(Path(snapshot_path).read_text())
    roster = next(r for r in snapshot['rosters'].values() if r['team'] == team)
    positions = ROLES[role][2]
    pool = [p for p in roster['players'] if p['pos_abb'] in positions]
    injuries = {p['gsis_id']: p.get('report_status') for p in (roster.get('injury_report') or {}).get('players', [])}
    eligible = [p for p in pool if injuries.get(p['gsis_id']) not in sd.INELIGIBLE_STATUS]
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        prior_season = cutoff_season - 1
        history = {
            'prior_season': counts(con, [prior_season], role),
            'two_seasons_back': counts(con, [prior_season - 1], role),
            'fixed_adapter_window': counts(con, list(range(ps.FIRST_SEASON, cutoff_season)), role),
            'current_season_to_cutoff': counts(con, [cutoff_season], role, last_week),
        }
        names = dict(con.execute("SELECT nfl_gsis_id, name FROM players WHERE lower(league)='nfl' AND nfl_gsis_id IS NOT NULL"))
    finally:
        con.close()
    table = sd.load(db, cutoff_season)
    base = table['base'][role]
    phi = table['phi'][role]
    weights = {p['gsis_id']: max(base.get((team, p['gsis_id']), 0.0), sd.FLOOR) for p in eligible}
    weight_total = sum(weights.values())
    rows = []
    for p in eligible:
        pid = p['gsis_id']
        rows.append({
            'player': p['player_name'], 'gsis_id': pid, 'position': p['pos_abb'], 'depth_rank': p['pos_rank'],
            'report_status': injuries.get(pid, 'no report'),
            **{f'{label}_share': share(*history[label], team, pid) for label in history},
            'dirichlet_base_share': base.get((team, pid)), 'floor_used': (team, pid) not in base,
            'weight_after_floor': weights[pid], 'conditional_share_in_eligible_group': weights[pid] / weight_total})
    draws = defaultdict(list)
    for i in range(DRAWS):
        drawn = sd.game_shares(table, team, f'attribution:{i}', [p['gsis_id'] for p in eligible], role, 'attribution')
        for pid, value in drawn.items():
            draws[pid].append(value)
    for row in rows:
        values = draws[row['gsis_id']]
        row['draw_mean'] = statistics.fmean(values)
        row['draw_median'] = quantile(values, 0.5)
        row['draw_p10'] = quantile(values, 0.1)
        row['draw_p90'] = quantile(values, 0.9)
    target = next(row for row in rows if row['gsis_id'] == gsis)
    team_totals = {label: history[label][1].get(team) for label in history}
    return {'team': team, 'role': role, 'player': target['player'], 'cutoff_season': cutoff_season,
            'current_season_last_week': last_week, 'eligible_count': len(eligible), 'pool_count': len(pool),
            'injury_report_entries': len(injuries), 'phi_all': phi.get('all'), 'phi_by_group': phi,
            'team_opportunity_totals': team_totals, 'target_row': target, 'eligible_roster': rows,
            'model': table['model'], 'draws': DRAWS, 'names': {pid: names.get(pid) for pid in weights}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='/root/legendarypicks/backend/data/picks.dev.db')
    ap.add_argument('--snapshot', required=True)
    ap.add_argument('--cutoff-season', type=int, default=2026)
    ap.add_argument('--last-week', type=int, default=8, help='last regular-season week of the current season before the game')
    ap.add_argument('--team', required=True)
    ap.add_argument('--gsis', required=True)
    ap.add_argument('--role', choices=tuple(ROLES), required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    result = attribute(args.db, args.snapshot, args.cutoff_season, args.last_week, args.team, args.gsis, args.role)
    Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    t = result['target_row']
    print(result['player'], args.role, 'eligible', result['eligible_count'], 'phi', result['phi_all'])
    for key in ('two_seasons_back_share', 'prior_season_share', 'fixed_adapter_window_share', 'current_season_to_cutoff_share',
                'conditional_share_in_eligible_group', 'draw_mean', 'draw_p10', 'draw_median', 'draw_p90'):
        print(f'  {key}: {t[key]:.3f}' if t[key] is not None else f'  {key}: none')


if __name__ == '__main__':
    main()
