"""Chronological ablation of historical windows for the full offensive play call (exploratory, not a gate).

Steps, each conditioned on the earlier steps as in the table: P personnel, F formation, R run or pass, C concept.
Targets: offense run and pass calls in 2024 and 2025. The 2022 formation labels are unreliable and the 2022 personnel is
reconstructed, so 2022 is excluded from every prior and window; 2023 therefore has no prior and is not a target here.

League (model A) is a backoff chain over the prior seasons: the finest context, then coarser contexts, down to the
step's marginal, with K = 20 pseudo-plays from the next coarser level. Team models smooth their own finest-context counts
toward model A's finest distribution with K = 20. The team's own target game is never in its window.

Windows: B previous season; C current season before the target game's week; D3 and D5 last 3 and 5 games; E previous season
weighted by N0 / (N0 + games played), N0 = 4, plus current season.
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
N0 = 4.0
EPS = 1e-6
STEPS = ['P', 'F', 'R', 'C']
BINS = [('1-3', 1, 3), ('4-8', 4, 8), ('9-13', 9, 13), ('14-18', 14, 18)]
MODELS = ['A', 'B', 'C', 'D3', 'D5', 'E']
OUT = Path(__file__).resolve().parent / 'temporal_joint.json'


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


def outcome_of(r, step):
    return r[step]


def build_league(prior_records):
    """nested[(step, level_index, ctx)] -> Counter of outcomes, over the prior records."""
    nested = defaultdict(Counter)
    for r in prior_records:
        lv = levels_of(r)
        for step in STEPS:
            o = outcome_of(r, step)
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


def team_nested_add(nd, r, step_ctx_finest):
    lv = levels_of(r)
    for step in STEPS:
        nd[(step, lv[step][0])][outcome_of(r, step)] += 1


def combine_scaled(prev, cur, wp):
    """Previous-season counts scaled by wp, plus current counts, per (step, ctx). Returns Counters with float values."""
    out = {}
    for key in set(prev) | set(cur):
        c = Counter()
        for o, v in prev.get(key, Counter()).items():
            c[o] += wp * v
        for o, v in cur.get(key, Counter()).items():
            c[o] += v
        out[key] = c
    return out


def main():
    recs, _excluded = pt.records(RAW, SEASONS, scheme='current')
    week = {}
    for season in SEASONS:
        for row in fp.load_season(RAW, season):
            week[row['game_id']] = int(row['week'])
    offense = [r for r in recs if r['R'] in ('run', 'pass') and r['P'] != 'SPECIAL' and r['season'] >= PRIOR_FLOOR]

    # Team-season game counts (finest context only), cumulative by games played before the target.
    game_nested = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    for r in offense:
        game_nested[(r['season'], r['team'])][r['game_id']]
        team_nested_add(game_nested[(r['season'], r['team'])][r['game_id']], r, None)
    order, cum = {}, {}
    for key, games in game_nested.items():
        ordered = sorted(games, key=lambda g: week[g])
        order[key] = ordered
        snaps = [{}]
        running = {}
        for g in ordered:
            for sc, c in games[g].items():
                running.setdefault(sc, Counter()).update(c)
            snaps.append({sc: Counter(c) for sc, c in running.items()})
        cum[key] = snaps

    cache = {}

    def window(key, k, n_games):
        ck = ('last', key, k, n_games)
        if ck not in cache:
            hi = cum[key][k]
            lo = cum[key][max(0, k - n_games)]
            out = {}
            for sc, c in hi.items():
                d = c - lo.get(sc, Counter())
                if d:
                    out[sc] = d
            cache[ck] = out
        return cache[ck]

    def prev_window(key):
        return cum[key][-1] if key in cum else {}

    def blended(key, k, wp):
        ck = ('blend', key, k)
        if ck not in cache:
            cache[ck] = combine_scaled(prev_window((key[0] - 1, key[1])), cum[key][k], wp)
        return cache[ck]

    results = {m: [] for m in MODELS}
    unseen = Counter()
    league_cache = {}
    for target in TARGETS:
        prior = [r for r in offense if PRIOR_FLOOR <= r['season'] < target]
        nested = build_league(prior)
        for r in offense:
            if r['season'] != target:
                continue
            team = r['team']
            key = (target, team)
            if key not in cum:
                continue
            w = week[r['game_id']]
            k = sum(1 for g in order[key] if week[g] < w)
            lv = levels_of(r)
            windows = {
                'B': prev_window((target - 1, team)),
                'C': cum[key][k],
                'D3': window(key, k, 3),
                'D5': window(key, k, 5),
            }
            wp = N0 / (N0 + k)
            windows['E'] = blended(key, k, wp)
            bin_name = next(name for name, lo_w, hi_w in BINS if lo_w <= w <= hi_w)
            step_probs = {}
            for step in STEPS:
                o = outcome_of(r, step)
                ck = (target, step, tuple(lv[step]))
                if ck not in league_cache:
                    league_cache[ck] = league_chain(nested, step, lv)
                pl = league_cache[ck]
                pa = pl.get(o, 0.0)
                finest = lv[step][0]
                per_model = {'A': (pa, pl)}
                for m in ['B', 'C', 'D3', 'D5', 'E']:
                    wc = windows[m].get((step, finest), Counter())
                    n = sum(wc.values())
                    x = wc.get(o, 0.0)
                    p_m = (x + K * pa) / (n + K)
                    cand = set(pl) | set(wc)
                    best = max(cand, key=lambda c_: (wc.get(c_, 0.0) + K * pl.get(c_, 0.0)) / (n + K)) if cand else None
                    per_model[m] = (p_m, best)
                step_probs[step] = per_model
                if pa == 0.0 and not any(windows[m].get((step, finest)) for m in ['B', 'C', 'D3', 'D5', 'E']):
                    unseen[step] += 1
            for m in MODELS:
                losses = {}
                correct = {}
                for step in STEPS:
                    p_m, best = step_probs[step][m] if m != 'A' else (step_probs[step]['A'][0], None)
                    o = outcome_of(r, step)
                    if m == 'A':
                        pl = league_cache[(target, step, tuple(lv[step]))]
                        best = max(pl, key=pl.get) if pl else None
                    p_m = min(max(p_m, EPS), 1 - EPS)
                    losses[step] = -math.log(p_m)
                    correct[step] = int(best == o)
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
    for m in ['C', 'D3', 'D5', 'E']:
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

    out = {'summary': summary, 'joint_diff_vs_B': diff, 'unseen_contexts': dict(unseen),
           'settings': {'K': K, 'N0': N0, 'targets': TARGETS, 'prior_floor': PRIOR_FLOOR, 'scheme': 'current'}}
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print('written', OUT)


if __name__ == '__main__':
    main()
