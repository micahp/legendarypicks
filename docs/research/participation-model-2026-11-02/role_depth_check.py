#!/usr/bin/env python3
"""Do frozen depth-chart roles add information to the cutoff-safe snap-share estimate? (SLC v2 step 2, research).

For each 2025 regular-season player-game in the snap-share targets, the depth role is the player's place on his team's
offensive depth chart (WR1, WR2, WR3, TE1, TE2), taken from the snapshot the depth adapter selects at the final horizon
(kickoff minus one hour). Players outside the 3WR 1TE group, or not on the chart, get no role.

The depth file lists offense only in the 3WR 1TE group, so RB, FB and OL roles are not available from it.

Test. The snap-share estimate for each player-game is fixed (it used only earlier games). A role offset is fit on
residuals in weeks 1 to 9 and tested on weeks 10 to 18: prediction = estimate + offset[role]. If the offsets do not
beat the estimate alone out of sample, depth roles add nothing beyond the history.

Usage: python3 role_depth_check.py --targets <snap_share_targets.csv> --out <json>
"""
import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEPTH_DIR = HERE.parent / 'slc-v2-depth-adapter-2026-11-02'
sys.path.insert(0, str(DEPTH_DIR))
sys.path.insert(0, str(HERE.parents[2] / 'scripts'))
import depth_adapter as da  # noqa: E402
from nfl_team_codes import to_nflverse_team_code  # noqa: E402

DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
DEPTH = '/root/gridiron-playbooks-research/data/raw/depth_charts_2025.parquet'
PLAYERS = '/root/gridiron-playbooks-research/data/raw/players.csv'
SPLIT_WEEK = 9


def roles_by_game(store, index, sha):
    """{(game_id, nflverse team, gsis_id): role} from the final-horizon depth state for each team in each 2025 game."""
    con = sqlite3.connect(DB, uri=True)
    games = con.execute("select game_id, gameday, gametime, home_team, away_team from nfl_schedule "
                        "where season = 2025 and game_type = 'REG' order by gameday, game_id").fetchall()
    con.close()
    out, unmapped = {}, set()
    for game_id, gameday, gametime, home, away in games:
        _early, final = da.game_horizons(gameday, gametime)
        for raw_team in (home, away):
            team = to_nflverse_team_code(raw_team)
            state = da.depth_state(store, team, final, index, source_sha256=sha)
            if state['reason'] != 'ok':
                unmapped.add((game_id, team, state['reason']))
                continue
            wr = sorted((e for e in state['entries'] if e['pos_abb'] in ('WR', 'TE') and e['gsis_id']
                         and (e['pos_grp'] or '').startswith('3WR')), key=lambda e: e['pos_rank'] or 99)
            counters = defaultdict(int)
            for entry in wr:
                counters[entry['pos_abb']] += 1
                out[(game_id, team, entry['gsis_id'])] = f"{entry['pos_abb']}{counters[entry['pos_abb']]}"
    return out, unmapped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--targets', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()

    rows = [r for r in csv.DictReader(open(args.targets, newline='', encoding='utf-8')) if r['season'] == '2025']
    rows_depth = da.load_snapshot_rows(DEPTH)
    store = da._as_store(rows_depth)
    sha = da.sha256_file(DEPTH)
    index = da.identity_index_from_players(PLAYERS)
    roles, unmapped = roles_by_game(store, index, sha)

    wr_te = [r for r in rows if (r['prior_group'] in ('WR', 'TE'))]
    matched = [r for r in wr_te if (r['game_id'], r['team'], r['gsis_id']) in roles]
    for r in rows:
        r['role'] = roles.get((r['game_id'], r['team'], r['gsis_id']), 'none')

    by_role = defaultdict(lambda: [0, 0.0, 0.0])
    for r in rows:
        if r['role'] == 'none':
            continue
        cell = by_role[r['role']]
        cell[0] += 1
        cell[1] += float(r['obs_share'])
        cell[2] += float(r['estimate'])
    role_means = {role: {'targets': n, 'mean_obs_share': round(o / n, 4), 'mean_estimate': round(e / n, 4)}
                  for role, (n, o, e) in sorted(by_role.items())}

    train = [r for r in rows if int(r['week']) <= SPLIT_WEEK]
    test = [r for r in rows if int(r['week']) > SPLIT_WEEK]
    offset = defaultdict(lambda: [0.0, 0])
    for r in train:
        if r['role'] != 'none':
            offset[r['role']][0] += float(r['obs_share']) - float(r['estimate'])
            offset[r['role']][1] += 1
    offset = {role: total / n for role, (total, n) in offset.items() if n >= 30}

    def mse(predict):
        return sum((float(r['obs_share']) - predict(r)) ** 2 for r in test) / len(test)

    base = mse(lambda r: float(r['estimate']))
    with_roles = mse(lambda r: float(r['estimate']) + offset.get(r['role'], 0.0))
    out = {'source': args.targets.name, 'split_week': SPLIT_WEEK,
           'depth_source_sha256': sha, 'depth_file': Path(DEPTH).name,
           'unmapped_team_games': sorted(unmapped)[:20], 'unmapped_count': len(unmapped),
           'targets_2025': len(rows), 'wr_te_targets': len(wr_te), 'wr_te_with_role': len(matched),
           'role_coverage_wr_te': round(len(matched) / max(len(wr_te), 1), 4),
           'role_means_2025': role_means,
           'offsets_fit_weeks_1_9': {k: round(v, 4) for k, v in sorted(offset.items())},
           'test_weeks_10_18': {'targets': len(test), 'mse_estimate_only': round(base, 6),
                                'mse_estimate_plus_role_offset': round(with_roles, 6),
                                'improvement': round(base - with_roles, 6)}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({k: out[k] for k in ('role_coverage_wr_te', 'unmapped_count', 'test_weeks_10_18')}, sort_keys=True))


if __name__ == '__main__':
    main()
