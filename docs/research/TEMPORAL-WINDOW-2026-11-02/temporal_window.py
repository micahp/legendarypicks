"""Chronological ablation of historical windows for run-or-pass calls (exploratory, not a gate).

Targets: every run or pass call in 2023, 2024 and 2025. Each target is scored from information before its game:
  A  league prior seasons only (situation cell, smoothed to the overall prior rate)
  B  same team, previous season, all games
  C  same team, current season, games before the target game's week
  D3 same team, current season, last 3 games before the target game
  D5 same team, current season, last 5 games before the target game
  E  previous-season prior whose weight falls as current games accumulate: n0 / (n0 + games played), n0 = 4
Every team model smooths its situation cell toward the league situation cell from model A with K = 20 pseudo-plays.
The team's own target game is never in its window.
"""
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts' / 'nfl_sequence'))
import playcall_table as pt  # noqa: E402
import formal_playcall as fp  # noqa: E402

RAW = Path('/root/gridiron-playbooks-research/data/raw')
SEASONS = [2022, 2023, 2024, 2025]
TARGETS = [2023, 2024, 2025]
K = pt.K
N0 = 4.0
BINS = [('1-3', 1, 3), ('4-8', 4, 8), ('9-13', 9, 13), ('14-18', 14, 18)]
MODELS = ['A', 'B', 'C', 'D3', 'D5', 'E']
OUT = Path(__file__).resolve().parent / 'temporal_window.json'


def sit_of(r):
    return (r['down'], r['dist'], r['field'], r['score'], r['time'])


def main():
    recs, _excluded = pt.records(RAW, SEASONS, scheme='current')
    week = {}
    for season in SEASONS:
        for row in fp.load_season(RAW, season):
            week[row['game_id']] = int(row['week'])
    runs = [r for r in recs if r['R'] in ('run', 'pass')]

    league = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    per_game = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0])))
    for r in runs:
        s = sit_of(r)
        y = int(r['R'] == 'pass')
        league[r['season']][s][0] += 1
        league[r['season']][s][1] += y
        cell = per_game[(r['season'], r['team'])][r['game_id']][s]
        cell[0] += 1
        cell[1] += y

    # Prior league per target season: all seasons strictly before it.
    prior_league, prior_all = {}, {}
    for target in TARGETS:
        agg = defaultdict(lambda: [0, 0])
        for season in SEASONS:
            if season >= target:
                continue
            for s, (n, x) in league[season].items():
                agg[s][0] += n
                agg[s][1] += x
        prior_league[target] = agg
        total_n = sum(v[0] for v in agg.values())
        total_x = sum(v[1] for v in agg.values())
        prior_all[target] = total_x / total_n

    # Per team-season: cumulative counts after the first k games, games in week order.
    cum, order = {}, {}
    for key, games in per_game.items():
        ordered = sorted(games, key=lambda g: week[g])
        order[key] = ordered
        snaps = [{}]
        running = {}
        for g in ordered:
            for s, (n, x) in games[g].items():
                tot = running.setdefault(s, [0, 0])
                tot[0] += n
                tot[1] += x
            snaps.append({s: list(v) for s, v in running.items()})
        cum[key] = snaps

    window_cache = {}

    def window(key, k, n_games):
        """Counts over the n_games games just before index k (k = games played before the target)."""
        ck = (key, k, n_games)
        if ck not in window_cache:
            hi = cum[key][k]
            lo = cum[key][max(0, k - n_games)]
            out = {}
            for s, (n, x) in hi.items():
                ln, lx = lo.get(s, [0, 0])
                if n - ln > 0:
                    out[s] = [n - ln, x - lx]
            window_cache[ck] = out
        return window_cache[ck]

    def p_league(target, s):
        n, x = prior_league[target].get(s, [0, 0])
        return (x + K * prior_all[target]) / (n + K)

    def smooth(counts, s, pa):
        n, x = counts.get(s, [0, 0])
        return (x + K * pa) / (n + K), n

    results = {m: [] for m in MODELS}
    for r in runs:
        target = r['season']
        if target not in TARGETS:
            continue
        team = r['team']
        key = (target, team)
        if key not in cum:
            continue
        w = week[r['game_id']]
        k = sum(1 for g in order[key] if week[g] < w)
        s = sit_of(r)
        y = int(r['R'] == 'pass')
        pa = p_league(target, s)
        prev_key = (target - 1, team)
        prev_total = cum[prev_key][-1] if prev_key in cum else {}
        cur_window_all = cum[key][k]
        preds = {'A': pa}
        n_prev_s = prev_total.get(s, [0, 0])
        preds['B'], nb = smooth(prev_total, s, pa)
        preds['C'], nc = smooth(cur_window_all, s, pa)
        preds['D3'], nd3 = smooth(window(key, k, 3), s, pa)
        preds['D5'], nd5 = smooth(window(key, k, 5), s, pa)
        wp = N0 / (N0 + k)
        cur_s = cur_window_all.get(s, [0, 0])
        blended = {s: [wp * n_prev_s[0] + cur_s[0], wp * n_prev_s[1] + cur_s[1]]}
        preds['E'], ne = smooth(blended, s, pa)
        bin_name = next(name for name, lo, hi in BINS if lo <= w <= hi)
        for m in MODELS:
            p = min(max(preds[m], 1e-6), 1 - 1e-6)
            loss = -math.log(p) if y else -math.log(1 - p)
            results[m].append({'bin': bin_name, 'week': w, 'season': target, 'game_id': r['game_id'],
                               'play': (r['game_id'], r['play_id'], team), 'loss': loss, 'brier': (p - y) ** 2, 'k': k})

    summary = {}
    for m in MODELS:
        summary[m] = {}
        for name, _lo, _hi in BINS:
            rows = [row for row in results[m] if row['bin'] == name]
            if rows:
                summary[m][name] = {'n': len(rows),
                                    'logloss': round(sum(x['loss'] for x in rows) / len(rows), 5),
                                    'brier': round(sum(x['brier'] for x in rows) / len(rows), 5)}

    rng = random.Random(1)
    diff_ci = {}
    base = {row['play']: row['loss'] for row in results['B']}
    for m in ['C', 'D3', 'D5', 'E']:
        diff_ci[m] = {}
        for name, _lo, _hi in BINS:
            games = defaultdict(lambda: [0.0, 0])
            for row in results[m]:
                if row['bin'] != name:
                    continue
                b = base[row['play']]
                games[row['game_id']][0] += row['loss'] - b
                games[row['game_id']][1] += 1
            if not games:
                continue
            total_d = sum(v[0] for v in games.values())
            total_n = sum(v[1] for v in games.values())
            ids = list(games)
            reps = []
            for _ in range(1000):
                sample = [games[g] for g in rng.choices(ids, k=len(ids))]
                reps.append(sum(v[0] for v in sample) / sum(v[1] for v in sample))
            reps.sort()
            diff_ci[m][name] = {'mean_diff_vs_B': round(total_d / total_n, 5),
                                'ci95': [round(reps[25], 5), round(reps[974], 5)]}

    weekly = {m: {} for m in ['B', 'C', 'E']}
    for m in weekly:
        for wk in range(1, 19):
            rows = [row for row in results[m] if row['week'] == wk]
            if rows:
                weekly[m][wk] = round(sum(x['loss'] for x in rows) / len(rows), 5)

    out = {'summary': summary, 'diff_vs_B': diff_ci, 'weekly_logloss': weekly,
           'settings': {'K': K, 'N0': N0, 'targets': TARGETS, 'scheme': 'current'}}
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(out['summary'], sort_keys=True))
    print(json.dumps(out['diff_vs_B'], sort_keys=True))
    print(json.dumps(out['weekly_logloss'], sort_keys=True))


if __name__ == '__main__':
    main()
