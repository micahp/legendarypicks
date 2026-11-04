#!/usr/bin/env python3
"""Score player projections, workloads and (where the arm has lineups) snap shares from per-seed box scores, for several
arms over the same games (SLC V1, V1.5 and v2 over 2026 weeks 1 to 8).

Each arm directory holds simulate_pregame_batch.py outputs run with --export-boxscores, plain or gzipped:
<game_id>.json (its summary marks each seed complete_game), <game_id>.boxscores.jsonl and <game_id>.seeds.jsonl. Only
complete-game seeds are used, the seed rule of the winner scoring. Observed values are the published nflverse weekly
player stats (regular season, by game_id and gsis id; a rostered player absent from the file recorded 0) and, for snap
shares, the published snap counts (snap_update.load_published, pfr id to gsis id; share = offense snaps / team snaps).

Per stat (carries, rushing yards, targets, receptions, receiving yards, pass attempts, passing yards, rushing and
receiving touchdowns) and arm, over player-games where any arm projects more than 0 or the player recorded more than 0:
mean absolute error of the mean projection, CRPS of the seed distribution, and the share of observations inside the
central 80% interval of the seeds (10th to 90th percentile, inclusive). Also for players who recorded the stat.
Team workload shape per team-game: the top target share (most targets / team targets) and the top carry share, CRPS
against the observed value. Role shares per team-game, the mean over seeds against the observed: usage roles TGT1-3
(players ranked by targets, each one's target share) and CAR1-2 (by carries), for every arm; and for an arm with lineups,
snap roles RB1-2, TE1-2, WR1-3 ranked by snaps within position, as in docs/research/role-usage-reference-2026-11-04. Paired differences between arms have game-clustered bootstrap 95% intervals. Players with
published stats who are not on the simulated roster are counted, not scored.

Usage: python3 score_player_workloads.py --arm V1=DIR --arm V15=DIR --arm V2=DIR --stats stats_player_week_2026.parquet
           --snap-raw <nflverse raw dir> --players-csv players.csv --out REPORT.json [--compare V15,V2 --compare V1,V15]
"""
import argparse
import gzip
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts' / 'nfl_sequence'))

STATS = {  # name -> (box-score group, key, published column)
    'carries': ('rushing', 'att', 'carries'), 'rushing_yards': ('rushing', 'yds', 'rushing_yards'),
    'targets': ('receiving', 'tgt', 'targets'), 'receptions': ('receiving', 'rec', 'receptions'),
    'receiving_yards': ('receiving', 'yds', 'receiving_yards'), 'pass_attempts': ('passing', 'att', 'attempts'),
    'passing_yards': ('passing', 'yds', 'passing_yards'), 'rushing_tds': ('rushing', 'td', 'rushing_tds'),
    'receiving_tds': ('receiving', 'td', 'receiving_tds'),
}
BOOT = 4000
SKILL = {'RB', 'FB', 'TE', 'WR'}


def read_lines(base):
    path = Path(str(base) + '.gz') if Path(str(base) + '.gz').exists() else Path(base)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_json(base):
    path = Path(str(base) + '.gz') if Path(str(base) + '.gz').exists() else Path(base)
    return json.loads(gzip.open(path, 'rt').read() if path.suffix == '.gz' else path.read_text())


def load_game(directory, game):
    """(seeds kept, {seed: {gsis: player row}}, {seed: lineup summary or None}, {gsis: (team, position)})."""
    payload = read_json(Path(directory) / f'{game}.json')
    keep = sorted(row['seed'] for row in payload['summary']['outcomes'] if row.get('complete_game'))
    box, roster = {}, {}
    for row in read_lines(Path(directory) / f'{game}.boxscores.jsonl')[1:]:
        b = row.get('boxscore', row)
        if b.get('seed') in keep:
            box[b['seed']] = {p['stable_player_id']: p for p in b['players'] if p.get('stable_player_id')}
            for p in b['players']:
                if p.get('stable_player_id'):
                    roster[p['stable_player_id']] = (p.get('team'), p.get('position'))
    lineups = {}
    for row in read_lines(Path(directory) / f'{game}.seeds.jsonl')[1:]:
        o = row.get('outcome', row)
        if o.get('seed') in keep:
            lineups[o['seed']] = (o.get('playcall') or {}).get('lineup')
    missing = [s for s in keep if s not in box]
    if missing:
        raise ValueError(f'{directory}/{game}: complete seeds {missing} have no box score')
    return keep, box, lineups, roster


def crps(samples, y):
    xs = sorted(samples)
    n = len(xs)
    return sum(abs(x - y) for x in xs) / n - sum(x * (2 * i - (n - 1)) for i, x in enumerate(xs)) / (n * n)


def central80(samples):
    xs = sorted(samples)
    n = len(xs)
    return xs[int(0.1 * (n - 1))], xs[int(round(0.9 * (n - 1)))]


def bootstrap(per_game, rng):
    """per_game: {game: (sum of differences, count)} -> (mean, low, high)."""
    games = sorted(per_game)
    total = sum(v[1] for v in per_game.values())
    if not total:
        return None
    point = sum(v[0] for v in per_game.values()) / total
    draws = []
    for _ in range(BOOT):
        pick = [per_game[rng.choice(games)] for _ in games]
        n = sum(p[1] for p in pick)
        if n:
            draws.append(sum(p[0] for p in pick) / n)
    draws.sort()
    return [round(point, 5), round(draws[int(0.025 * len(draws))], 5), round(draws[int(0.975 * len(draws)) - 1], 5)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arm', action='append', required=True, help='NAME=DIR')
    ap.add_argument('--stats', type=Path, required=True)
    ap.add_argument('--snap-raw', type=Path, required=True)
    ap.add_argument('--players-csv', type=Path, required=True)
    ap.add_argument('--compare', action='append', default=[], help='A,B: report B minus A')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    import pandas as pd
    import snap_update as su
    arms = dict(item.split('=', 1) for item in args.arm)
    games = sorted(set.intersection(*[{p.name.split('.')[0] for p in Path(d).glob('*.json*')
                                       if p.name.endswith(('.json', '.json.gz'))} for d in arms.values()]))
    stats = pd.read_parquet(args.stats)
    stats = stats[stats.season_type == 'REG']
    obs = {(r.game_id, r.player_id): r for r in stats.itertuples()}
    published_by_game = defaultdict(set)
    for g, pid in obs:
        published_by_game[g].add(pid)
    snaps = su.SnapCounts(su.load_published(args.snap_raw, 2026, args.players_csv), 'published')

    rows = defaultdict(list)  # stat -> [(game, week, pid, observed, {arm: (mean, crps, inside)})]
    shape = defaultdict(list)  # 'top_target_share' / 'top_carry_share' -> [(game, team, observed, {arm: crps})]
    snap_rows = []  # (game, team, pid, observed share, {arm: mean simulated share})
    role_rows = []  # (game, team, role, observed share, arm, mean simulated share)
    coverage = defaultdict(int)
    for game in games:
        week = int(game.split('_')[1])
        loaded = {name: load_game(d, game) for name, d in arms.items()}
        roster = {}
        for name, (_k, _b, _l, r) in loaded.items():
            roster.update(r)
        not_projected = [pid for pid in published_by_game.get(game, ()) if pid not in roster]
        coverage['published_not_on_simulated_roster'] += len(not_projected)
        coverage['published_not_on_simulated_roster_with_offense'] += sum(
            1 for pid in not_projected if any(getattr(obs[(game, pid)], STATS[s][2]) or 0 for s in STATS))
        coverage['games'] += 1
        coverage['seeds_' + '_'.join(f'{n}{len(v[0])}' for n, v in sorted(loaded.items()))] += 1
        for stat, (group, key, column) in STATS.items():
            for pid in sorted(roster):
                y = float(getattr(obs[(game, pid)], column) or 0) if (game, pid) in obs else 0.0
                per_arm = {}
                for name, (keep, box, _l, _r) in loaded.items():
                    xs = [float(box[s].get(pid, {}).get(group, {}).get(key, 0) or 0) for s in keep]
                    lo, hi = central80(xs)
                    per_arm[name] = (sum(xs) / len(xs), crps(xs, y), lo <= y <= hi)
                if y > 0 or any(v[0] > 0 for v in per_arm.values()):
                    rows[stat].append((game, week, pid, y, per_arm))
        teams = {t for t, _p in roster.values() if t}
        for team in sorted(teams):
            for label, (group, key, column) in (('top_target_share', STATS['targets']),
                                                 ('top_carry_share', STATS['carries'])):
                team_pids = [pid for pid, (t, _p) in roster.items() if t == team]
                vals = [float(getattr(obs[(game, pid)], column) or 0) for pid in team_pids if (game, pid) in obs]
                total = sum(vals)
                if not total:
                    continue
                y = max(vals) / total
                per_arm = {}
                for name, (keep, box, _l, _r) in loaded.items():
                    xs = []
                    for s in keep:
                        v = [float(box[s].get(pid, {}).get(group, {}).get(key, 0) or 0) for pid in team_pids]
                        if sum(v):
                            xs.append(max(v) / sum(v))
                    if xs:
                        per_arm[name] = crps(xs, y)
                if len(per_arm) == len(loaded):
                    shape[label].append((game, team, y, per_arm))
        for team in sorted(teams):  # usage roles: top receivers by targets, top backs by carries
            team_pids = [pid for pid, (t, _p) in roster.items() if t == team]
            for label, (group, key, column), depth in (('TGT', STATS['targets'], 3), ('CAR', STATS['carries'], 2)):
                vals = sorted((float(getattr(obs[(game, pid)], column) or 0) for pid in team_pids if (game, pid) in obs),
                              reverse=True)
                total = sum(vals)
                if not total:
                    continue
                for name, (keep, box, _l, _r) in loaded.items():
                    sims = defaultdict(float)
                    for s in keep:
                        v = sorted((float(box[s].get(pid, {}).get(group, {}).get(key, 0) or 0) for pid in team_pids),
                                   reverse=True)
                        tot = sum(v)
                        for rank in range(depth):
                            sims[rank] += (v[rank] / tot if tot and rank < len(v) else 0.0) / len(keep)
                    for rank in range(depth):
                        role_rows.append((game, team, f'{label}{rank + 1}',
                                          vals[rank] / total if rank < len(vals) else 0.0, name, sims[rank]))
        for name, (keep, _b, lineups, r) in loaded.items():
            if not any(lineups.get(s) for s in keep):
                continue
            for team in sorted(teams):  # snap roles, as in the role usage reference: rank by snaps within position
                team_snaps = snaps.team_snaps.get((team, week))
                if not team_snaps:
                    continue
                published = snaps.player.get((team, week), {})
                for pos, depth in (('RB', 2), ('TE', 2), ('WR', 3)):
                    obs_ranked = sorted((n for pid, n in published.items()
                                         if {'HB': 'RB'}.get(snaps.position.get(pid), snaps.position.get(pid)) == pos),
                                        reverse=True)
                    sims = defaultdict(float)
                    for s in keep:
                        lu = (lineups.get(s) or {}).get(team)
                        if not lu or not lu['team_snaps']:
                            continue
                        v = sorted((n for pid, n in lu['player_snaps'].items() if r.get(pid, (None, None))[1] == pos),
                                   reverse=True)
                        for rank in range(depth):
                            sims[rank] += (v[rank] / lu['team_snaps'] if rank < len(v) else 0.0) / len(keep)
                    for rank in range(depth):
                        role_rows.append((game, team, f'{pos}{rank + 1}_snap',
                                          obs_ranked[rank] / team_snaps if rank < len(obs_ranked) else 0.0, name,
                                          sims[rank]))
            for team in sorted(teams):
                team_snaps = snaps.team_snaps.get((team, week))
                if not team_snaps:
                    coverage[f'{name}_snap_team_game_without_published_snaps'] += 1
                    continue
                published = snaps.player.get((team, week), {})
                sims = defaultdict(float)
                for s in keep:
                    lu = (lineups.get(s) or {}).get(team)
                    if lu and lu['team_snaps']:
                        for pid, n in lu['player_snaps'].items():
                            sims[pid] += n / lu['team_snaps'] / len(keep)
                pids = {pid for pid, (t, p) in r.items() if t == team and p in SKILL} | set(sims) | \
                    {pid for pid in published if snaps.position.get(pid) in SKILL}
                for pid in sorted(pids):
                    snap_rows.append((game, team, pid, published.get(pid, 0.0) / team_snaps, name, sims.get(pid, 0.0)))

    report = {'games': len(games), 'arms': arms, 'coverage': dict(coverage),
              'stats_file_sha256': hashlib.sha256(args.stats.read_bytes()).hexdigest(), 'stats': {}, 'shape': {},
              'snap_share': {}, 'differences': {}}
    names = sorted(arms)
    for stat, items in rows.items():
        out = {}
        for cohort, keep in (('all', lambda r: True), ('observed_positive', lambda r: r[3] > 0)):
            sel = [r for r in items if keep(r)]
            out[cohort] = {'n': len(sel), **{name: {
                'mae': round(sum(abs(r[4][name][0] - r[3]) for r in sel) / len(sel), 4),
                'crps': round(sum(r[4][name][1] for r in sel) / len(sel), 4),
                'coverage80': round(sum(r[4][name][2] for r in sel) / len(sel), 4),
                'mean_projection': round(sum(r[4][name][0] for r in sel) / len(sel), 4),
                'mean_observed': round(sum(r[3] for r in sel) / len(sel), 4)} for name in names}}
        for tier, keep in (('week8', lambda r: r[1] == 8), ('weeks1_7', lambda r: r[1] < 8)):
            sel = [r for r in items if keep(r) and r[3] > 0]
            if sel:
                out[f'observed_positive_{tier}'] = {'n': len(sel), **{name: {
                    'mae': round(sum(abs(r[4][name][0] - r[3]) for r in sel) / len(sel), 4),
                    'crps': round(sum(r[4][name][1] for r in sel) / len(sel), 4)} for name in names}}
        report['stats'][stat] = out
    for label, items in shape.items():
        report['shape'][label] = {'team_games': len(items), **{name: round(sum(i[3][name] for i in items) / len(items), 4)
                                                               for name in names}}
    by_arm = defaultdict(list)
    for game, team, pid, y, name, x in snap_rows:
        by_arm[name].append((game, y, x))
    for name, items in by_arm.items():
        pos = [i for i in items if i[1] > 0]
        report['snap_share'][name] = {'player_games': len(items),
                                      'mae': round(sum(abs(x - y) for _g, y, x in items) / len(items), 4),
                                      'mae_observed_positive': round(sum(abs(x - y) for _g, y, x in pos) / len(pos), 4)}
    roles = defaultdict(lambda: defaultdict(list))
    for game, team, role, y, name, x in role_rows:
        roles[role][name].append((y, x))
    report['roles'] = {role: {name: {'team_games': len(v), 'mae': round(sum(abs(x - y) for y, x in v) / len(v), 4),
                                     'mean_simulated': round(sum(x for _y, x in v) / len(v), 4),
                                     'mean_observed': round(sum(y for y, _x in v) / len(v), 4)}
                              for name, v in sorted(by.items())} for role, by in sorted(roles.items())}
    rng = random.Random(20261104)
    for pair in args.compare:
        a, b = pair.split(',')
        diff = {}
        for stat, items in rows.items():
            for cohort, keep in (('all', lambda r: True), ('observed_positive', lambda r: r[3] > 0)):
                for metric, idx in (('mae', None), ('crps', 1)):
                    per_game = defaultdict(lambda: [0.0, 0])
                    for r in items:
                        if keep(r):
                            if idx is None:
                                d = abs(r[4][b][0] - r[3]) - abs(r[4][a][0] - r[3])
                            else:
                                d = r[4][b][1] - r[4][a][1]
                            per_game[r[0]][0] += d
                            per_game[r[0]][1] += 1
                    diff[f'{stat}.{cohort}.{metric}'] = bootstrap(per_game, rng)
        for label, items in shape.items():
            per_game = defaultdict(lambda: [0.0, 0])
            for game, _t, _y, per_arm in items:
                per_game[game][0] += per_arm[b] - per_arm[a]
                per_game[game][1] += 1
            diff[f'{label}.crps'] = bootstrap(per_game, rng)
        report['differences'][f'{b}_minus_{a}'] = diff
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps({'games': len(games), 'coverage': dict(coverage)}))
    for stat in ('carries', 'targets', 'receptions', 'rushing_yards', 'receiving_yards'):
        if stat in report['stats']:
            o = report['stats'][stat]['observed_positive']
            print(stat, o['n'], {n: (o[n]['mae'], o[n]['crps'], o[n]['coverage80']) for n in names})
    print('shape', report['shape'])
    print('snap_share', report['snap_share'])
    for role, by in report['roles'].items():
        print('role', role, {n: (v['mae'], v['mean_simulated'], v['mean_observed']) for n, v in by.items()})
    for k, v in report['differences'].items():
        print(k, {s: v[s] for s in v if s.endswith('observed_positive.mae') or s.endswith('crps') and 'share' in s})


if __name__ == '__main__':
    main()
