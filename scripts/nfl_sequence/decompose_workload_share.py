"""Decompose a simulated player share into position-group frequency times within-group share (research, no game is simulated).

The chooser picks a position group for a play, then draws a player inside that group from the game's Dirichlet shares. So a player's
expected share of the team's opportunities is about P(group) times his share inside the group. This script prints the parts for one
player, from the snapshot and the database, next to the real shares and the simulated mean from the saved 50-seed arms.

P(group) is the real frequency in the current season before the cutoff. The simulator's own group frequency is not exported, so this
is a proxy; the report says so.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import player_shares as ps  # noqa: E402
import share_distributions as sd  # noqa: E402

GROUP_POSITIONS = {'receive': {'WR': ('WR',), 'TE': ('TE',), 'RB': ('RB',)},
                   'carry': {'RB': ('RB',), 'QB': ('QB',), 'WR_TE': ('WR', 'TE')}}


def real_group_frequency(con, team, role, season, last_week, positions):
    column, play_type = ('receiver_player_id', 'pass') if role == 'receive' else ('rusher_player_id', 'run')
    rows = con.execute(f"SELECT {column}, COUNT(*) FROM nfl_pbp WHERE season=? AND week<=? AND play_type=? AND posteam=? "
                       f"AND {column} IS NOT NULL GROUP BY {column}", (season, last_week, play_type, team)).fetchall()
    total = sum(n for _, n in rows) or 1
    groups = {}
    for pid, n in rows:
        groups.setdefault(positions.get(pid, '?'), 0)
        groups[positions.get(pid, '?')] += n
    return total, {k: v / total for k, v in groups.items()}


def decompose(db, snapshot_path, cutoff, last_week, team, gsis, role, draws=2000):
    snapshot = json.loads(Path(snapshot_path).read_text())
    roster = next(r for r in snapshot['rosters'].values() if r['team'] == team)
    positions = sd.player_positions(db)
    table = sd.load(db, cutoff)
    positions_in_pool = ps.TARGET_POSITIONS if role == 'receive' else ps.CARRY_POSITIONS
    pool = [p for p in roster['players'] if p['pos_abb'] in positions_in_pool]
    pool = [p for p in pool if p.get('roster_eligible', True)]
    target = next(p for p in pool if p['gsis_id'] == gsis)
    if role == 'receive':
        group_name = target['pos_abb']
    else:
        group_name = 'RB' if target['pos_abb'] == 'RB' else 'QB' if target['pos_abb'] == 'QB' else 'WR_TE'
    group_allowed = GROUP_POSITIONS[role][group_name]
    group_players = [p for p in pool if p['pos_abb'] in group_allowed]
    rng_seeds = [f'decompose:{i}' for i in range(draws)]
    inside = []
    for seed in rng_seeds:
        shares = sd.game_shares(table, team, 'decompose-game', [p['gsis_id'] for p in group_players], role, seed,
                                group=group_name)
        inside.append(shares[gsis])
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        total_now, freq_now = real_group_frequency(con, team, role, cutoff, last_week, positions)
        total_prior, freq_prior = real_group_frequency(con, team, role, cutoff - 1, 18, positions)
        real_player = {}
        for season, weeks in ((cutoff - 1, 18), (cutoff, last_week)):
            column, play_type = ('receiver_player_id', 'pass') if role == 'receive' else ('rusher_player_id', 'run')
            rows = con.execute(f"SELECT COUNT(*) FROM nfl_pbp WHERE season=? AND week<=? AND play_type=? AND posteam=? "
                               f"AND {column}=?", (season, weeks, play_type, team, gsis)).fetchone()[0]
            team_total = con.execute(f"SELECT COUNT(*) FROM nfl_pbp WHERE season=? AND week<=? AND play_type=? AND posteam=? "
                                     f"AND {column} IS NOT NULL", (season, weeks, play_type, team)).fetchone()[0]
            real_player[season] = rows / team_total if team_total else None
    finally:
        con.close()
    base = table['base'][role]
    group_real_now = freq_now.get(group_name, 0.0)
    conditional = float(np.mean(inside))
    return {
        'player': target.get('player_name'), 'gsis_id': gsis, 'team': team,
        'role': role, 'group': group_name, 'cutoff': cutoff, 'last_week': last_week,
        'base_share_prior_season': base.get((team, gsis)), 'floor_weight_used': (team, gsis) not in base,
        'candidate_population_size': len(group_players), 'population_positions': sorted({p['pos_abb'] for p in group_players}),
        'conditional_share_in_group_mean': conditional,
        'conditional_share_in_group_p10': float(np.quantile(inside, 0.1)),
        'conditional_share_in_group_p90': float(np.quantile(inside, 0.9)),
        'group_frequency_real_current_to_cutoff': group_real_now, 'group_frequency_real_prior': freq_prior.get(group_name, 0.0),
        'implied_team_share': group_real_now * conditional,
        'real_player_share_prior_season': real_player[cutoff - 1], 'real_player_share_current_to_cutoff': real_player[cutoff],
        'phi_group': table['phi'][role].get(group_name, table['phi'][role]['all']) if isinstance(table['phi'][role], dict)
        else table['phi'][role],
        'lineup_restriction': 'not traced: the simulated lineup filter is not exported by this script',
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='/root/legendarypicks/backend/data/picks.dev.db')
    ap.add_argument('--snapshot', required=True)
    ap.add_argument('--cutoff-season', type=int, default=2026)
    ap.add_argument('--last-week', type=int, default=8)
    ap.add_argument('--team', required=True)
    ap.add_argument('--gsis', required=True)
    ap.add_argument('--role', choices=('receive', 'carry'), required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    out = decompose(args.db, args.snapshot, args.cutoff_season, args.last_week, args.team, args.gsis, args.role)
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps(out, indent=1, sort_keys=True, default=str))


if __name__ == '__main__':
    main()
