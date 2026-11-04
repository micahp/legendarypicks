#!/usr/bin/env python3
"""Role-based snap, target and carry shares for every team-week, league and team aggregates, and snap-share change
through the season (research reference, pinned so it is not recomputed for each comparison).

Roles: within each team and week, the players listed at RB (or HB), at TE and at WR in the published snap counts are ranked by
offensive snaps, most first (ties by gsis id): RB1, RB2, TE1, TE2, WR1, WR2, WR3. FB is ranked apart (FB1). A role is a
rank in that week, so a team's WR1 can be a different player from week to week.

Sources, all published nflverse releases: snap_counts_<season>.parquet (offensive snaps; pfr ids mapped to gsis ids by
snap_update.load_published, unmatched rows counted) and stats_player_week_<season>.parquet (targets and carries by gsis
id). Shares: snap share = player offensive snaps / team offensive snaps (snap_update's team snaps); target share =
player targets / the team's targets that week; carry share = player carries / the team's carries that week (QBs
included in the team total).

Outputs in --out-dir:
- role_usage_team_week.csv.gz: one row per season, week, team and role.
- role_usage_league.csv: per season, season type and role, the mean and 10th, 50th and 90th percentiles of each share.
- role_usage_team_season.csv: per regular season, team and role, the team's mean shares next to the league's.
- snap_trajectory_team.csv: per regular season, team and role, mean snap share in weeks 1-4, 5-8 and 9-18.
- snap_trajectory_players.csv: per regular season and position, how much skill players' snap shares move between weeks
  1-4 and 5-8 (players with at least 2 games in each).
- manifest.json: source file and output hashes, row counts and unmatched counts.

Usage: python3 build_role_usage.py --raw <nflverse raw dir> --players-csv players.csv --seasons 2016-2026
           --out-dir <dir> [--stats-override 2026=<stats_player_week_2026.parquet>]
"""
import argparse
import csv
import gzip
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts' / 'nfl_sequence'))
import snap_update as su  # noqa: E402

ROLE_POS = {'RB': 2, 'TE': 2, 'WR': 3, 'FB': 1}
POS_ALIAS = {'HB': 'RB'}  # the newer snap-count files list some backs as HB
SHARES = ('snap_share', 'target_share', 'carry_share')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quantiles(values):
    xs = sorted(values)
    n = len(xs)
    q = lambda p: xs[min(n - 1, int(p * (n - 1) + 0.5))]  # noqa: E731
    return {'mean': round(sum(xs) / n, 4), 'p10': round(q(0.1), 4), 'p50': round(q(0.5), 4), 'p90': round(q(0.9), 4)}


def bucket(week):
    return 'w01_04' if week <= 4 else 'w05_08' if week <= 8 else 'w09_18'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', type=Path, required=True)
    ap.add_argument('--players-csv', type=Path, required=True)
    ap.add_argument('--seasons', required=True)
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--stats-override', action='append', default=[])
    args = ap.parse_args()
    import pyarrow.parquet as pq
    lo, hi = (int(x) for x in args.seasons.split('-'))
    override = {int(k): Path(v) for k, v in (item.split('=', 1) for item in args.stats_override)}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {'sources': {}, 'coverage': {}, 'outputs': {}}
    rows = []
    for season in range(lo, hi + 1):
        snap_path = args.raw / 'snap_counts' / f'snap_counts_{season}.parquet'
        stats_path = override.get(season, args.raw / 'stats_player' / f'stats_player_week_{season}.parquet')
        manifest['sources'][season] = {'snap_counts': [str(snap_path), sha(snap_path)],
                                       'stats_player_week': [str(stats_path), sha(stats_path)]}
        snaps = su.load_published(args.raw, season, args.players_csv)
        game_type = {}
        sc = pq.read_table(snap_path, columns=['week', 'team', 'game_type']).to_pydict()
        for i in range(len(sc['week'])):
            game_type[(su.snap_team(sc['team'][i]), int(sc['week'][i]))] = \
                'REG' if sc['game_type'][i] == 'REG' else 'POST'
        st = pq.read_table(stats_path, columns=['player_id', 'week', 'team', 'targets', 'carries']).to_pydict()
        usage = defaultdict(dict)
        team_tot = defaultdict(lambda: [0.0, 0.0])
        for i in range(len(st['player_id'])):
            team, week = su.snap_team(st['team'][i]), int(st['week'][i])
            t, c = float(st['targets'][i] or 0), float(st['carries'][i] or 0)
            usage[(team, week)][st['player_id'][i]] = (t, c)
            team_tot[(team, week)][0] += t
            team_tot[(team, week)][1] += c
        team_snaps = {(t, w): s for t, w, s in snaps['team_snaps']}
        by_tw = defaultdict(list)
        for team, week, pid, pos, n in snaps['player_snaps']:
            pos = POS_ALIAS.get(pos, pos)
            if pos in ROLE_POS:
                by_tw[(team, week)].append((pos, n, pid))
        cov = {'snap_unmatched_skill_snaps': snaps['coverage'].get('unmatched_skill_snaps', 0.0),
               'team_weeks': len(by_tw), 'team_weeks_without_stats': 0}
        for (team, week), players in sorted(by_tw.items()):
            if (team, week) not in team_tot:
                cov['team_weeks_without_stats'] += 1
                continue
            tt, tc = team_tot[(team, week)]
            for pos, keep in ROLE_POS.items():
                ranked = sorted((p for p in players if p[0] == pos), key=lambda p: (-p[1], p[2]))[:keep]
                for rank, (_pos, n, pid) in enumerate(ranked, 1):
                    t, c = usage[(team, week)].get(pid, (0.0, 0.0))
                    rows.append({'season': season, 'week': week, 'season_type': game_type.get((team, week), 'REG'),
                                 'team': team, 'role': f'{pos}{rank}', 'gsis_id': pid, 'snaps': n,
                                 'snap_share': round(n / team_snaps[(team, week)], 4),
                                 'target_share': round(t / tt, 4) if tt else 0.0,
                                 'carry_share': round(c / tc, 4) if tc else 0.0, 'targets': t, 'carries': c})
        manifest['coverage'][season] = cov
        print(season, cov, flush=True)

    fields = list(rows[0])
    out = args.out_dir / 'role_usage_team_week.csv.gz'
    with gzip.open(out, 'wt', newline='') as handle:
        w = csv.DictWriter(handle, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    league = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for s in SHARES:
            league[(r['season'], r['season_type'], r['role'])][s].append(r[s])
    with open(args.out_dir / 'role_usage_league.csv', 'w', newline='') as handle:
        w = csv.writer(handle)
        w.writerow(['season', 'season_type', 'role', 'team_weeks'] + [f'{s}_{k}' for s in SHARES
                                                                       for k in ('mean', 'p10', 'p50', 'p90')])
        for (season, stype, role), v in sorted(league.items()):
            w.writerow([season, stype, role, len(v['snap_share'])] + [quantiles(v[s])[k] for s in SHARES
                                                                       for k in ('mean', 'p10', 'p50', 'p90')])

    team = defaultdict(lambda: defaultdict(list))
    traj = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r['season_type'] != 'REG':
            continue
        for s in SHARES:
            team[(r['season'], r['team'], r['role'])][s].append(r[s])
        traj[(r['season'], r['team'], r['role'])][bucket(r['week'])].append(r['snap_share'])
    with open(args.out_dir / 'role_usage_team_season.csv', 'w', newline='') as handle:
        w = csv.writer(handle)
        w.writerow(['season', 'team', 'role', 'games'] + [f'{s}_{k}' for s in SHARES for k in ('team', 'league', 'diff')])
        for (season, t, role), v in sorted(team.items()):
            line = [season, t, role, len(v['snap_share'])]
            for s in SHARES:
                tm = sum(v[s]) / len(v[s])
                lg = quantiles(league[(season, 'REG', role)][s])['mean']
                line += [round(tm, 4), lg, round(tm - lg, 4)]
            w.writerow(line)
    with open(args.out_dir / 'snap_trajectory_team.csv', 'w', newline='') as handle:
        w = csv.writer(handle)
        w.writerow(['season', 'team', 'role', 'w01_04', 'w05_08', 'w09_18', 'change_w01_04_to_w05_08'])
        for (season, t, role), v in sorted(traj.items()):
            m = {b: round(sum(x) / len(x), 4) if x else '' for b, x in ((b, v.get(b, [])) for b in
                                                                         ('w01_04', 'w05_08', 'w09_18'))}
            ch = round(m['w05_08'] - m['w01_04'], 4) if m['w01_04'] != '' and m['w05_08'] != '' else ''
            w.writerow([season, t, role, m['w01_04'], m['w05_08'], m['w09_18'], ch])

    # Player-level movement of snap share between weeks 1-4 and 5-8 (any role), per season and position.
    player = defaultdict(lambda: defaultdict(list))
    pos_of = {}
    for season in range(lo, hi + 1):
        snaps = su.load_published(args.raw, season, args.players_csv)
        ts = {(t, wk): s for t, wk, s in snaps['team_snaps']}
        for t, wk, pid, pos, n in snaps['player_snaps']:
            pos = POS_ALIAS.get(pos, pos)
            if pos in ROLE_POS and wk <= 8 and (t, wk) in ts:
                player[(season, t, pid)][bucket(wk)].append(n / ts[(t, wk)])
                pos_of[pid] = pos
    moves = defaultdict(list)
    for (season, t, pid), v in player.items():
        if len(v['w01_04']) >= 2 and len(v['w05_08']) >= 2:
            moves[(season, pos_of[pid])].append(statistics.mean(v['w05_08']) - statistics.mean(v['w01_04']))
    with open(args.out_dir / 'snap_trajectory_players.csv', 'w', newline='') as handle:
        w = csv.writer(handle)
        w.writerow(['season', 'position', 'players', 'mean_abs_change', 'share_moving_10pts_or_more', 'mean_change',
                    'p10_change', 'p90_change'])
        for (season, pos), xs in sorted(moves.items()):
            q = quantiles(xs)
            w.writerow([season, pos, len(xs), round(sum(abs(x) for x in xs) / len(xs), 4),
                        round(sum(abs(x) >= 0.10 for x in xs) / len(xs), 4), q['mean'], q['p10'], q['p90']])
    for path in sorted(args.out_dir.glob('*')):
        if path.name != 'manifest.json' and path.suffix != '.py':
            manifest['outputs'][path.name] = sha(path)
    manifest['team_week_rows'] = len(rows)
    (args.out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print('rows', len(rows), json.dumps(manifest['outputs'], indent=0))


if __name__ == '__main__':
    main()
