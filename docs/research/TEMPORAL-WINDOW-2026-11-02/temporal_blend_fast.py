"""Same comparison as temporal_blend.py, computed from per-game counts instead of cumulative copies.

Each team-season stores one count per game (finest context only). Windows are sums over the games in them, and the blend
is computed per play from the previous-season total and the current-season sum. The numbers match temporal_blend.py.

Targets: offense run and pass calls in 2024 and 2025. Prior seasons start at 2023. The 2022 formation labels are unreliable,
so 2022 is excluded from every prior and window.
"""
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts' / 'nfl_sequence'))
import playcall_table as pt  # noqa: E402
import formal_playcall as fp  # noqa: E402

RAW = Path('/root/gridiron-playbooks-research/data/raw')
SEASONS = [2022, 2023, 2024, 2025]
TARGETS = [2024, 2025]
PRIOR_FLOOR = 2023
K = pt.K
EPS = 1e-6
STEPS = ['P', 'F', 'R', 'C']
BINS = [('1-3', 1, 3), ('4-8', 4, 8), ('9-13', 9, 13), ('14-18', 14, 18)]
TEAM = ['B', 'C', 'D3', 'D5', 'E2', 'E4', 'E8']
MODELS = ['A'] + TEAM
N0S = {'E2': 2.0, 'E4': 4.0, 'E8': 8.0}
OUT = Path(__file__).resolve().parent / 'temporal_blend_fast.json'


def levels_of(r):
    """Per step, the contexts from finest to coarsest. Each context is a tuple; the last one is the empty root."""
    s = (r['down'], r['dist'], r['field'], r['score'], r['time'])
    P, F, R = r['P'], r['F'], r['R']
    return {
        'P': [s, ()],
        'F': [s + (P,), s, ()],
        'R': [s + (P, F), s + (P,), s, ()],
        'C': [s + (P, F, R), s + (R,), (R,), ()],
    }


def build_league(prior_records):
    """nested[(step, level_index, ctx)] -> Counter of outcomes, over the prior records."""
    nested = defaultdict(Counter)
    for r in prior_records:
        lv = levels_of(r)
        for step in STEPS:
            o = r[step]
            for i, ctx in enumerate(lv[step]):
                nested[(step, i, ctx)][o] += 1
    return nested


def league_chain(nested, step, levels):
    """The backoff chain's distribution at the finest context, as a dict outcome -> probability."""
    p = {}
    for i in reversed(range(len(levels[step]))):
        c = nested.get((step, i, levels[step][i]))
        if not c:
            continue
        n = sum(c.values())
        if not p:
            p = {o: v / n for o, v in c.items()}
        else:
            new = {}
            for o in set(p) | set(c):
                new[o] = (c.get(o, 0) + K * p.get(o, 0.0)) / (n + K)
            p = new
    return p


def main():
    recs, _excluded = pt.records(RAW, SEASONS, scheme='current')
    week = {}
    for season in SEASONS:
        for row in fp.load_season(RAW, season):
            week[row['game_id']] = int(row['week'])
    offense = [r for r in recs if r['R'] in ('run', 'pass') and r['P'] != 'SPECIAL' and r['season'] >= PRIOR_FLOOR]

    # One count per game and finest context, then the games in week order.
    game_counts = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    for r in offense:
        lv = levels_of(r)
        games = game_counts[(r['season'], r['team'])][r['game_id']]
        for step in STEPS:
            games[(step, lv[step][0])][r[step]] += 1
    order = {key: sorted(games, key=lambda g: week[g]) for key, games in game_counts.items()}

    # Whole-season totals per team-season, for the previous-season prior.
    totals = {}
    for key, games in game_counts.items():
        tot = defaultdict(Counter)
        for g in order[key]:
            for sc, c in games[g].items():
                tot[sc].update(c)
        totals[key] = tot

    def span(key, lo, hi, sc):
        """Counts for one finest context over the team's games order[lo:hi]."""
        c = Counter()
        games = game_counts[key]
        for g in order[key][lo:hi]:
            part = games[g].get(sc)
            if part:
                c.update(part)
        return c

    results = {m: [] for m in MODELS}
    league_cache = {}
    for target in TARGETS:
        prior = [r for r in offense if PRIOR_FLOOR <= r['season'] < target]
        nested = build_league(prior)
        for r in offense:
            if r['season'] != target:
                continue
            team = r['team']
            key = (target, team)
            if key not in order:
                continue
            w = week[r['game_id']]
            k = sum(1 for g in order[key] if week[g] < w)
            prev_key = (target - 1, team)
            prev_tot = totals.get(prev_key, {})
            lv = levels_of(r)
            bin_name = next(name for name, lo_w, hi_w in BINS if lo_w <= w <= hi_w)
            step_probs = {}
            for step in STEPS:
                o = r[step]
                ck = (target, step, tuple(lv[step]))
                if ck not in league_cache:
                    league_cache[ck] = league_chain(nested, step, lv)
                pl = league_cache[ck]
                pa = pl.get(o, 0.0)
                sc = (step, lv[step][0])
                cur = span(key, 0, k, sc)
                windows = {
                    'B': prev_tot.get(sc, Counter()),
                    'C': cur,
                    'D3': span(key, max(0, k - 3), k, sc),
                    'D5': span(key, max(0, k - 5), k, sc),
                }
                prev = prev_tot.get(sc, Counter())
                for name, n0 in N0S.items():
                    wp = n0 / (n0 + k)
                    blend = Counter()
                    for oc, v in prev.items():
                        blend[oc] += wp * v
                    for oc, v in cur.items():
                        blend[oc] += v
                    windows[name] = blend
                out = {'A': (pa, max(pl, key=pl.get) if pl else None)}
                for m in TEAM:
                    wc = windows[m]
                    n = sum(wc.values())
                    x = wc.get(o, 0.0)
                    p_m = (x + K * pa) / (n + K)
                    cand = set(pl) | set(wc)
                    best = max(cand, key=lambda c_: (wc.get(c_, 0.0) + K * pl.get(c_, 0.0)) / (n + K)) if cand else None
                    out[m] = (p_m, best)
                step_probs[step] = out
            for m in MODELS:
                losses, correct = {}, {}
                for step in STEPS:
                    p_m, best = step_probs[step][m]
                    p_m = min(max(p_m, EPS), 1 - EPS)
                    losses[step] = -math.log(p_m)
                    correct[step] = int(best == r[step])
                results[m].append({'bin': bin_name, 'season': target, 'week': w, 'game_id': r['game_id'],
                                   'play': (r['game_id'], r['play_id'], team),
                                   'joint': sum(losses.values()), 'loss': losses, 'correct': correct})

    summary = {}
    for m in MODELS:
        summary[m] = {}
        for name, _lo, _hi in BINS:
            rows = [x for x in results[m] if x['bin'] == name]
            if not rows:
                continue
            summary[m][name] = {
                'n': len(rows),
                'joint': round(sum(x['joint'] for x in rows) / len(rows), 5),
                'loss': {s: round(sum(x['loss'][s] for x in rows) / len(rows), 5) for s in STEPS},
                'accuracy': {s: round(sum(x['correct'][s] for x in rows) / len(rows), 4) for s in STEPS},
            }

    base = {x['play']: x for x in results['B']}
    rng = random.Random(1)
    diff = {}
    for m in ['C', 'D3', 'D5', 'E2', 'E4', 'E8']:
        diff[m] = {}
        for name, _lo, _hi in BINS:
            games = defaultdict(lambda: [0.0, 0])
            for x in results[m]:
                if x['bin'] != name:
                    continue
                games[x['game_id']][0] += x['joint'] - base[x['play']]['joint']
                games[x['game_id']][1] += 1
            if not games:
                continue
            total_d = sum(v[0] for v in games.values())
            total_n = sum(v[1] for v in games.values())
            ids = list(games)
            reps = []
            for _ in range(1000):
                smp = [games[g] for g in rng.choices(ids, k=len(ids))]
                reps.append(sum(v[0] for v in smp) / sum(v[1] for v in smp))
            reps.sort()
            diff[m][name] = {'joint_diff_vs_B': round(total_d / total_n, 5),
                             'ci95': [round(reps[25], 5), round(reps[974], 5)]}

    out = {'summary': summary, 'joint_diff_vs_B': diff,
           'settings': {'K': K, 'N0s': N0S, 'targets': TARGETS, 'prior_floor': PRIOR_FLOOR, 'scheme': 'current'}}
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print('written', OUT)


if __name__ == '__main__':
    main()
