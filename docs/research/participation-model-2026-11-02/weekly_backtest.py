#!/usr/bin/env python3
"""Week-over-week backtest of the lineup grouping model, 2022 to 2025 (research).

For every offensive snap of a target season, the grouping (personnel with line and QB counts, for example 12-OL6) is
forecast from data available before that game's week: the team, the situation cell (participation_field.supported_cell),
the previous grouping and the play's call (run or dropback), as the engine draws it (participation_field.Field.group_probs,
schema v4, with its shrinkage). Each forecast is scored by the log probability of the observed grouping. The previous
grouping and the call are the observed ones, so every arm is scored on the same history.

Arms:
  A0  the current table weights: the four seasons before the target, weighted 1, 0.5, 0.25, 0.125 (participation_model.RECENCY).
  A1  season weights d ** age over the K seasons before the target; (d, K) chosen on the tuning targets.
  A2  A1 plus a current-season update from published snap counts (the signal a live forecast has). Each team's RB (with
      FB), TE and WR snaps per team snap in its games before the target week give a target mean, blended with the prior
      mean as (N0 * prior + G * snap counts) / (N0 + G), G the games played. The forecast is tilted exponentially,
      p(g) * exp(lambda . n(g)), with lambda set so the team's prior grouping mix has that mean. Line counts are left out:
      snap counts reproduce participation's line count poorly (r = 0.15 per team-game, 2016 to 2025) but its TE (0.98),
      WR (0.97) and RB (0.85) counts well.
  A3  A1 plus the current season's participation before the target week (an upper bound: live 2026 has no participation).
      The prior seasons' counts are scaled by N0 / (N0 + G) and the current season's earlier weeks are added at weight 1.

Selection, fixed before the 2022 to 2025 run: each arm's parameters are the ones with the lowest pooled log loss on the
tuning targets 2019 to 2021 (all weeks, postseason included). Grids: d in {0.25, 0.5, 0.75, 1.0}, K in {1, 2, 3, 4, 6};
N0 in {1, 2, 4, 8, 16} for A2 and A3, each given A1's (d, K). For 2019 only three earlier seasons exist (2016 to 2018), so
K of 4 and 6 use three there. The 2022 to 2025 results for every grid point are also written, marked post hoc.

Scoring: an observed grouping the forecast gives no probability is scored on a floor, p' = (1 - EPS) p + EPS / V over the V
grouping codes seen in 2016 to 2025; every arm gets the same floor and the count of floored snaps is reported. Differences
between arms have game-clustered bootstrap intervals (a team-game is the cluster), by part of the season: weeks 1 to 4, 5 to
9, 10 to the end of the regular season, and the postseason.

Usage: python3 weekly_backtest.py --tables <scrimmage_participation.csv.gz, 2016 to 2025, with qb_dropback>
           --snap-dir <nflverse snap_counts parquet dir> --out <json> [--targets 2022,2023,2024,2025] [--tune 2019,2020,2021]
"""
import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / 'scripts' / 'nfl_sequence'))
import lineup_fit  # noqa: E402
import participation_field as pf  # noqa: E402
import participation_model as pm  # noqa: E402

FIRST_SEASON = 2016
EPS = 1e-3
DECAYS = (0.25, 0.5, 0.75, 1.0)
WINDOWS = (1, 2, 3, 4, 6)
N0S = (1, 2, 4, 8, 16)
A0 = (0.5, 4)
TILT_CLASSES = ('RB', 'TE', 'WR')
SNAP_CLASS = {'RB': 'RB', 'FB': 'RB', 'TE': 'TE', 'WR': 'WR'}
sys.path.insert(0, str(HERE.parents[2] / 'scripts'))
import nfl_team_codes  # noqa: E402
snap_team = nfl_team_codes.to_nflverse  # snap counts keep the old codes; play-by-play uses the current ones
TEAM_MIX_PRIOR_PLAYS = 50.0  # pseudo-plays of the league mix in a team's prior grouping mix (for the tilt only)
BOOT = 2000


def period(season_type, week, last_regular):
    if season_type == 'POST':
        return 'post'
    return 'w01-04' if week <= 4 else 'w05-09' if week <= 9 else f'w10-{last_regular}'


def load_games(tables, seasons):
    """[(season, week, season_type, game_id, team, [(group, cell, call), ...])] in play order."""
    plays = defaultdict(list)
    meta = {}
    for row in pm.load_scrimmage(tables, set(seasons)):
        call = lineup_fit.intent_of(row)
        if call is None:
            raise ValueError('the table has no qb_dropback column; rebuild it with build_tables.py')
        key = (row['game_id'], row['posteam'])
        plays[key].append((int(row['play_id']), row['group'], pm.cell_of(row), call))
        meta[key] = (int(row['season']), int(row['week']), row['season_type'])
    return [meta[key] + key + ([item[1:] for item in sorted(items)],) for key, items in sorted(plays.items())]


def load_snaps(snap_dir, seasons):
    """{(season, team): {week: Counter(class snaps, 'team' = team snaps)}} from published nflverse snap counts."""
    import pyarrow.parquet as pq
    out = defaultdict(lambda: defaultdict(Counter))
    for season in seasons:
        d = pq.read_table(Path(snap_dir) / f'snap_counts_{season}.parquet').to_pydict()
        team_snaps = defaultdict(list)
        for i in range(len(d['game_id'])):
            team = snap_team(d['team'][i])
            key = (season, team, int(d['week'][i]))
            snaps, pct = d['offense_snaps'][i] or 0.0, d['offense_pct'][i] or 0.0
            cls = SNAP_CLASS.get(d['position'][i])
            if cls and snaps:
                out[(season, team)][key[2]][cls] += snaps
            if pct >= 0.5:
                team_snaps[key].append(snaps / pct)
        for (s, team, week), values in team_snaps.items():
            out[(s, team)][week]['team'] = statistics.median(values)
    return out


class Counts:
    """Flat transition counts: league and team, by call, with the totals group_probs needs."""

    def __init__(self):
        self.league = Counter()  # (cell, call, prev, group)
        self.league_n = Counter()  # (cell, call, prev)
        self.team = Counter()  # (team, cell, call, prev, group)
        self.team_n = Counter()  # (team, cell, call, prev)
        self.marginal = Counter()  # (cell, call, group)
        self.marginal_n = Counter()  # (cell, call)
        self.cell_n = Counter()  # cell
        self.team_mix = Counter()  # (team, group)

    def add_game(self, team, seq):
        prev = pf.START
        for group, cell, call in seq:
            self.league[(cell, call, prev, group)] += 1
            self.league_n[(cell, call, prev)] += 1
            self.team[(team, cell, call, prev, group)] += 1
            self.team_n[(team, cell, call, prev)] += 1
            self.marginal[(cell, call, group)] += 1
            self.marginal_n[(cell, call)] += 1
            self.cell_n[cell] += 1
            self.team_mix[(team, group)] += 1
            prev = group

    def add(self, other, weight):
        for name in ('league', 'league_n', 'team', 'team_n', 'marginal', 'marginal_n', 'cell_n', 'team_mix'):
            mine = getattr(self, name)
            for key, value in getattr(other, name).items():
                mine[key] += weight * value


class Model:
    """group_probs over prior counts scaled by `prior_scale` plus current-season counts, as participation_field computes it."""

    def __init__(self, prior, groups_by_cell_call, current=None, prior_scale=1.0):
        self.prior, self.current, self.scale = prior, current, prior_scale
        self.groups = groups_by_cell_call
        self.marginal_by_cell = None  # supported_cell reads plays() below instead
        self.status = Counter()

    def get(self, name, key):
        value = self.scale * getattr(self.prior, name).get(key, 0.0)
        return value + (getattr(self.current, name).get(key, 0.0) if self.current is not None else 0.0)

    def plays(self, cell):
        return self.get('cell_n', cell)

    def supported_cell(self, cell, cells):
        """participation_field.Field.supported_cell on these counts."""
        if self.plays(cell) >= pf.MIN_CELL_PLAYS:
            return cell
        down, distance, field = cell.split('|')
        self.status['cell_fallback'] += 1
        if distance in pf.DISTANCES:
            rank = pf.DISTANCES.index(distance)
            for other in sorted(pf.DISTANCES, key=lambda d: (abs(pf.DISTANCES.index(d) - rank), pf.DISTANCES.index(d))):
                if self.plays(f'{down}|{other}|{field}') >= pf.MIN_CELL_PLAYS:
                    return f'{down}|{other}|{field}'
        same_down = [c for c in cells if c.startswith(f'{down}|') and self.plays(c) >= pf.MIN_CELL_PLAYS]
        return max(same_down, key=lambda c: (self.plays(c), c)) if same_down else None

    def probs(self, team, cell, call, prev):
        calls = (call,) if self.get('marginal_n', (cell, call)) > 0 else ('run', 'dropback')
        if len(calls) == 2:
            self.status['call_cell_missing'] += 1
        groups = set().union(*(self.groups.get((cell, c), ()) for c in calls))
        marginal = Counter({g: sum(self.get('marginal', (cell, c, g)) for c in calls) for g in groups})
        marginal = Counter({g: v for g, v in marginal.items() if v > 0})
        if not marginal:
            return {}
        league = Counter({g: sum(self.get('league', (cell, c, prev, g)) for c in calls) for g in marginal})
        team_counts = Counter({g: sum(self.get('team', (team, cell, c, prev, g)) for c in calls) for g in marginal})
        return pf.Field._shrunk(marginal, league, team_counts)


def tilt_lambda(mix, target):
    """lambda with sum_g mix(g) exp(lambda . n(g)) n(g) / Z = target (damped Newton). mix: {group: weight}."""
    vecs = {g: vector(g) for g in mix}
    total = sum(mix.values())
    lam = [0.0] * len(TILT_CLASSES)
    for _ in range(50):
        w = {g: mix[g] / total * math.exp(sum(l * x for l, x in zip(lam, vecs[g]))) for g in mix}
        z = sum(w.values())
        mean = [sum(w[g] * vecs[g][i] for g in w) / z for i in range(len(lam))]
        grad = [m - t for m, t in zip(mean, target)]
        if max(abs(x) for x in grad) < 1e-6:
            break
        cov = [[sum(w[g] * (vecs[g][i] - mean[i]) * (vecs[g][j] - mean[j]) for g in w) / z + (1e-6 if i == j else 0.0)
                for j in range(len(lam))] for i in range(len(lam))]
        step = solve(cov, grad)
        scale = min(1.0, 1.0 / max(1e-12, max(abs(s) for s in step)))
        lam = [max(-5.0, min(5.0, l - scale * s)) for l, s in zip(lam, step)]
    return lam


def solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def mean_counts(mix):
    total = sum(mix.values())
    return [sum(v * vector(g)[i] for g, v in mix.items()) / total for i in range(len(TILT_CLASSES))]


_VECTORS = {}


def vector(group):
    """The grouping's RB, TE and WR counts."""
    if group not in _VECTORS:
        counts = pf.group_counts(group)
        _VECTORS[group] = tuple(counts[c] for c in TILT_CLASSES)
    return _VECTORS[group]


class Backtest:
    def __init__(self, games, snaps):
        self.games = games
        self.snaps = snaps
        self.seasons = sorted({g[0] for g in games})
        self.by_season = defaultdict(list)
        for g in games:
            self.by_season[g[0]].append(g)
        self.season_counts = {}
        groups = defaultdict(set)
        for season, items in self.by_season.items():
            c = Counts()
            for _s, _w, _t, _game, team, seq in items:
                c.add_game(team, seq)
                for group, cell, call in seq:
                    groups[(cell, call)].add(group)
            self.season_counts[season] = c
        self.groups = groups
        self.vocab = sorted({grp for v in groups.values() for grp in v})
        self.cells = sorted({cell for (cell, _call) in groups})
        self.last_regular = {s: max(g[1] for g in items if g[2] == 'REG') for s, items in self.by_season.items()}
        self.prior_cache = {}

    def prior(self, target, decay, window):
        key = (target, decay, window)
        if key not in self.prior_cache:
            c = Counts()
            for season in range(target - window, target):
                if season in self.season_counts:
                    c.add(self.season_counts[season], decay ** (target - 1 - season))
            self.prior_cache = {key: c}  # one at a time: the counts are large
        return self.prior_cache[key]

    def score(self, target, decay, window, arm='A1', n0=None):
        """{(game_id, team): {'period', 'sum', 'n', 'floored'}} for one target season."""
        prior = self.prior(target, decay, window)
        current = Counts()
        weeks = sorted({g[1] for g in self.by_season[target]})
        out = {}
        memo = {}
        status = Counter()
        for week in weeks:
            items = [g for g in self.by_season[target] if g[1] == week]
            if arm == 'A3':  # the current-season counts change each week
                memo = {}
            for season, _w, season_type, game, team, seq in items:
                g_before = self.games_before(target, team, week)
                if arm == 'A3':
                    model = Model(prior, self.groups, current, n0 / (n0 + g_before) if g_before else 1.0)
                else:
                    model = Model(prior, self.groups)
                lam = None
                if arm == 'A2' and g_before:
                    lam = self.snap_tilt(prior, target, team, week, n0, g_before)
                total, floored, prev = 0.0, 0, pf.START
                for group, cell, call in seq:
                    used = model.supported_cell(cell, self.cells)
                    mkey = (team, used, call, prev)
                    if mkey not in memo:
                        memo[mkey] = model.probs(team, used, call, prev) if used else {}
                    probs = memo[mkey]
                    if lam is not None and probs:
                        w = {g: p * math.exp(sum(l * x for l, x in zip(lam, vector(g)))) for g, p in probs.items()}
                        z = sum(w.values())
                        probs = {g: v / z for g, v in w.items()}
                    p = probs.get(group, 0.0)
                    if p <= 0:
                        floored += 1
                    total += math.log((1 - EPS) * p + EPS / len(self.vocab))
                    prev = group
                status.update(model.status)
                out[(game, team)] = {'period': period(season_type, week, self.last_regular[target]), 'sum': total,
                                     'n': len(seq), 'floored': floored}
            if arm == 'A3':
                for _s, _w, _t, _game, team, seq in items:
                    current.add_game(team, seq)
        return out, dict(status)

    def games_before(self, season, team, week):
        return sum(1 for w, c in self.snaps.get((season, team), {}).items() if w < week and c.get('team'))

    def snap_tilt(self, prior, season, team, week, n0, games):
        league_mix = Counter()
        for (t, g), v in prior.team_mix.items():
            league_mix[g] += v
        league_total = sum(league_mix.values())
        mix = Counter({g: prior.team_mix.get((team, g), 0.0) + TEAM_MIX_PRIOR_PLAYS * v / league_total
                       for g, v in league_mix.items() if v > 0})
        prior_mean = mean_counts(mix)
        snaps = Counter()
        for w, c in self.snaps[(season, team)].items():
            if w < week and c.get('team'):
                snaps.update(c)
        observed = [snaps[c] / snaps['team'] for c in TILT_CLASSES]
        target = [(n0 * p + games * o) / (n0 + games) for p, o in zip(prior_mean, observed)]
        return tilt_lambda(mix, target)


def pooled(results):
    s = sum(r['sum'] for res in results for r in res.values())
    n = sum(r['n'] for res in results for r in res.values())
    return -s / n


def by_period(results):
    acc = defaultdict(lambda: [0.0, 0])
    for res in results:
        for r in res.values():
            acc[r['period']][0] += r['sum']
            acc[r['period']][1] += r['n']
            acc['all'][0] += r['sum']
            acc['all'][1] += r['n']
    return {p: round(-v[0] / v[1], 5) for p, v in sorted(acc.items())}


def diff_ci(a, b, rng):
    """Log loss of b minus a (negative: b is better), by period, with a team-game bootstrap 95% interval."""
    keys = [(i, k) for i, res in enumerate(a) for k in res]
    out = {}
    periods = sorted({a[i][k]['period'] for i, k in keys}) + ['all']
    for p in periods:
        ks = [(i, k) for i, k in keys if p == 'all' or a[i][k]['period'] == p]
        d = [(a[i][k]['sum'] - b[i][k]['sum'], a[i][k]['n']) for i, k in ks]
        point = sum(x for x, _ in d) / sum(n for _, n in d)
        draws = []
        for _ in range(BOOT):
            pick = [d[rng.randrange(len(d))] for _ in d]
            draws.append(sum(x for x, _ in pick) / sum(n for _, n in pick))
        draws.sort()
        out[p] = {'mean': round(point, 5), 'ci95': [round(draws[int(0.025 * BOOT)], 5), round(draws[int(0.975 * BOOT) - 1], 5)],
                  'team_games': len(ks)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--snap-dir', type=Path, required=True)
    ap.add_argument('--targets', default='2022,2023,2024,2025')
    ap.add_argument('--tune', default='2019,2020,2021')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    targets = [int(s) for s in args.targets.split(',')]
    tune = [int(s) for s in args.tune.split(',')]
    seasons = list(range(FIRST_SEASON, max(targets) + 1))
    games = load_games(args.tables, seasons)
    snaps = load_snaps(args.snap_dir, sorted(set(targets) | set(tune)))
    bt = Backtest(games, snaps)
    missing = [(g[0], g[4]) for g in games if g[0] in set(targets) | set(tune) and (g[0], g[4]) not in snaps]
    if missing:
        raise ValueError(f'team-seasons with no snap counts: {sorted(set(missing))[:10]}')
    report = {'tables': str(args.tables), 'tables_sha256': pf.sha256_file(args.tables), 'snap_dir': str(args.snap_dir),
              'eps': EPS, 'vocab': len(bt.vocab), 'targets': targets, 'tune': tune,
              'snaps_by_season': {s: sum(len(g[5]) for g in bt.by_season[s]) for s in seasons}}
    print('snaps by season', report['snaps_by_season'], flush=True)

    def run(seasons_, d, k, arm='A1', n0=None):
        results, status = [], Counter()
        for s in seasons_:
            res, st = bt.score(s, d, k, arm, n0)
            results.append(res)
            status.update(st)
        return results, dict(status)

    grid = {}
    for d in DECAYS:
        for k in WINDOWS:
            res, _ = run(tune, d, k)
            grid[(d, k)] = pooled(res)
            print(f'tune A1 d={d} K={k} {grid[(d, k)]:.5f}', flush=True)
    d1, k1 = min(grid, key=lambda key: (grid[key], key))
    report['tune_A1'] = {f'd={d},K={k}': round(v, 5) for (d, k), v in sorted(grid.items())}
    report['selected_A1'] = {'decay': d1, 'window': k1}
    sel = {}
    for arm in ('A2', 'A3'):
        scores = {}
        for n0 in N0S:
            res, _ = run(tune, d1, k1, arm, n0)
            scores[n0] = pooled(res)
            print(f'tune {arm} N0={n0} {scores[n0]:.5f}', flush=True)
        sel[arm] = min(scores, key=lambda n0: (scores[n0], n0))
        report[f'tune_{arm}'] = {str(n0): round(v, 5) for n0, v in scores.items()}
        report[f'selected_{arm}'] = {'n0': sel[arm]}

    final = {}
    final['A0'], st0 = run(targets, *A0)
    final['A1'], st1 = run(targets, d1, k1)
    final['A2'], st2 = run(targets, d1, k1, 'A2', sel['A2'])
    final['A3'], st3 = run(targets, d1, k1, 'A3', sel['A3'])
    report['status'] = {'A0': st0, 'A1': st1, 'A2': st2, 'A3': st3}
    report['log_loss'] = {arm: by_period(res) for arm, res in final.items()}
    report['floored_snaps'] = {arm: sum(r['floored'] for res in v for r in res.values()) for arm, v in final.items()}
    report['log_loss_by_season'] = {arm: {s: round(pooled([res]), 5) for s, res in zip(targets, v)}
                                    for arm, v in final.items()}
    rng = random.Random(20261104)
    report['differences'] = {'A1_minus_A0': diff_ci(final['A0'], final['A1'], rng),
                             'A2_minus_A1': diff_ci(final['A1'], final['A2'], rng),
                             'A3_minus_A1': diff_ci(final['A1'], final['A3'], rng),
                             'A3_minus_A2': diff_ci(final['A2'], final['A3'], rng)}
    post_hoc = {}
    for d in DECAYS:
        for k in WINDOWS:
            res, _ = run(targets, d, k)
            post_hoc[f'd={d},K={k}'] = round(pooled(res), 5)
    report['post_hoc_A1_grid_on_targets'] = post_hoc
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True))
    for arm in final:
        print(arm, report['log_loss'][arm], 'floored', report['floored_snaps'][arm])
    for name, v in report['differences'].items():
        print(name, {p: (x['mean'], x['ci95']) for p, x in v.items()})


if __name__ == '__main__':
    main()
