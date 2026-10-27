"""S0b: a simple chronological team-strength baseline for NFL game winners (research, dev only, no production output).

Forecast for a regular-season game: P(home win) = sigmoid(b0 + b1 * (home prior margin - away prior margin)), where a
team's prior margin is its mean points margin in earlier weeks of the same season. A team needs at least MIN_PRIOR
earlier games for the game to be scored. Games in the same week never count toward each other.

Splits (fixed in docs/NFL-TEAM-STRENGTH-EXPERIMENT-PLAN-2026-10-27.md, section 4): fit 2010 to 2017, validation 2018 to
2020, test 2021 to 2025. The 2026 season is the sealed holdout and is not read. The model is fitted once on the fit
window and not refitted or tuned on the evaluation seasons.

Comparators: a constant 0.5 forecast (Brier 0.25 by construction) and a home-only forecast (the fit-window home win rate).
Ties are excluded from the binary metrics and counted.

Usage: python3 s0_baseline.py            # print the report
"""
import math
import random
import sqlite3
from collections import defaultdict

DEV_DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
MIN_PRIOR = 4
FIT = range(2010, 2018)
VALIDATION = range(2018, 2021)
TEST = range(2021, 2026)
CLIP = (0.001, 0.999)
BOOT_REPS = 2000


def sigmoid(z):
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def load_games(dev):
    """Completed regular-season games 2010 to 2025, in week order. The 2026 season is not read."""
    return dev.execute("""select game_id, season, week, home_team, away_team, home_score, away_score
        from nfl_schedule where game_type = 'REG' and season between 2010 and 2025
        and home_score is not null and away_score is not null order by season, week, game_id""").fetchall()


def scored_features(games):
    """One dict per game: prior margins, the scored flag, and the outcome. Prior margins use earlier weeks only."""
    out = []
    by_season = defaultdict(lambda: defaultdict(list))
    for g in games:
        by_season[g[1]][g[2]].append(g)
    for season in sorted(by_season):
        history = defaultdict(list)   # team -> [margin] from earlier weeks of this season
        for week in sorted(by_season[season]):
            week_games = by_season[season][week]
            for gid, _, wk, home, away, hs, as_ in week_games:
                h, a = history[home], history[away]
                scored = len(h) >= MIN_PRIOR and len(a) >= MIN_PRIOR
                out.append(dict(game_id=gid, season=season, week=wk, home=home, away=away,
                                x=(sum(h) / len(h) - sum(a) / len(a)) if scored else None, scored=scored,
                                y=None if hs == as_ else (1 if hs > as_ else 0), tie=hs == as_))
            for gid, _, wk, home, away, hs, as_ in week_games:
                history[home].append(hs - as_)
                history[away].append(as_ - hs)
    return out


def solve(a, b):
    """Solve a small linear system by Gaussian elimination."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[c][c] != 0:
                f = m[r][c] / m[c][c]
                m[r] = [mr - f * mc for mr, mc in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_logistic(xs, ys, iters=50):
    """Maximum likelihood weights for P(y=1) = sigmoid(w . x). Each x includes the intercept term."""
    k = len(xs[0])
    w = [0.0] * k
    for _ in range(iters):
        grad = [0.0] * k
        hess = [[0.0] * k for _ in range(k)]
        for x, y in zip(xs, ys):
            p = sigmoid(sum(wi * xi for wi, xi in zip(w, x)))
            for i in range(k):
                grad[i] += (y - p) * x[i]
                for j in range(k):
                    hess[i][j] += p * (1 - p) * x[i] * x[j]
        step = solve(hess, grad)
        w = [wi + si for wi, si in zip(w, step)]
        if max(abs(s) for s in step) < 1e-10:
            break
    return w


def clip(p):
    return min(CLIP[1], max(CLIP[0], p))


def metrics(rows, probs):
    ys = [r['y'] for r in rows]
    n = len(ys)
    brier = sum((p - y) ** 2 for p, y in zip(probs, ys)) / n
    logloss = sum(-(y * math.log(clip(p)) + (1 - y) * math.log(1 - clip(p))) for p, y in zip(probs, ys)) / n
    # A constant forecast has no spread to recalibrate, so its slope is undefined and reported as None.
    slope = None
    if len(set(probs)) > 1:
        logits = [[1.0, math.log(p / (1 - p))] for p in (min(max(p, 1e-6), 1 - 1e-6) for p in probs)]
        slope = fit_logistic(logits, ys)[1]
    bins = defaultdict(lambda: [0, 0.0, 0.0])
    for p, y in zip(probs, ys):
        b = min(9, int(p * 10))
        bins[b][0] += 1
        bins[b][1] += p
        bins[b][2] += y
    reliability = [(f'{b / 10:.1f}-{(b + 1) / 10:.1f}', c, mp / c, ob / c)
                   for b, (c, mp, ob) in sorted(bins.items()) if c >= 20]
    return dict(n=n, brier=brier, logloss=logloss, calibration_slope=slope, reliability=reliability,
                mean_p=sum(probs) / n, home_win_rate=sum(ys) / n)


def block_bootstrap_brier_gap(rows, probs_a, probs_b, seed=0):
    """95 percent interval for mean Brier(A) minus Brier(B), resampling whole weeks (season, week) with replacement."""
    blocks = defaultdict(list)
    for r, pa, pb in zip(rows, probs_a, probs_b):
        blocks[(r['season'], r['week'])].append((pa - r['y']) ** 2 - (pb - r['y']) ** 2)
    keys = list(blocks)
    rng = random.Random(seed)
    gaps = []
    for _ in range(BOOT_REPS):
        sample = [rng.choice(keys) for _ in keys]
        total = sum(sum(blocks[k]) for k in sample)
        count = sum(len(blocks[k]) for k in sample)
        gaps.append(total / count)
    gaps.sort()
    observed = sum(sum(v) for v in blocks.values()) / sum(len(v) for v in blocks.values())
    return observed, gaps[int(0.025 * BOOT_REPS)], gaps[int(0.975 * BOOT_REPS)]


def run(dev):
    feats = scored_features(load_games(dev))
    total = defaultdict(lambda: dict(games=0, scored=0, ties=0))
    for f in feats:
        t = total[f['season']]
        t['games'] += 1
        t['scored'] += f['scored']
        t['ties'] += f['tie']
    fit = [f for f in feats if f['season'] in FIT and f['scored'] and f['y'] is not None]
    xs = [[1.0, f['x']] for f in fit]
    ys = [f['y'] for f in fit]
    w = fit_logistic(xs, ys)
    home_rate = sum(ys) / len(ys)
    results = {}
    for name, window in (('validation', VALIDATION), ('test', TEST)):
        rows = [f for f in feats if f['season'] in window and f['scored'] and f['y'] is not None]
        p_s0b = [sigmoid(w[0] + w[1] * f['x']) for f in rows]
        p_home = [home_rate] * len(rows)
        p_half = [0.5] * len(rows)
        results[name] = dict(
            s0b=metrics(rows, [clip(p) for p in p_s0b]),
            home_only=metrics(rows, p_home),
            constant_half=metrics(rows, p_half),
            gap_vs_home_only=block_bootstrap_brier_gap(rows, p_s0b, p_home),
        )
    return dict(weights=w, fit_games=len(fit), fit_home_rate=home_rate, coverage=dict(total), results=results)


def report(out):
    print(f"S0b weights: intercept {out['weights'][0]:+.4f} (home advantage in logit), margin slope "
          f"{out['weights'][1]:+.4f}")
    print(f"fit games {out['fit_games']} (2010 to 2017), fit home win rate {out['fit_home_rate']:.4f}")
    print('\ncoverage (regular season, all games, scored = both teams have at least 4 earlier games):')
    for season, t in sorted(out['coverage'].items()):
        print(f"  {season}: games {t['games']}, scored {t['scored']} ({t['scored'] / t['games']:.1%}), ties {t['ties']}")
    for name, block in out['results'].items():
        print(f"\n{name}: n {block['s0b']['n']}, home win rate {block['s0b']['home_win_rate']:.4f}")
        for label in ('s0b', 'home_only', 'constant_half'):
            m = block[label]
            slope = 'n/a' if m['calibration_slope'] is None else f"{m['calibration_slope']:.3f}"
            print(f"  {label:13s} brier {m['brier']:.4f}  logloss {m['logloss']:.4f}  "
                  f"calibration slope {slope}  mean p {m['mean_p']:.3f}")
        gap, lo, hi = block['gap_vs_home_only']
        print(f"  S0b minus home-only Brier: {gap:+.4f}  95% week-block interval [{lo:+.4f}, {hi:+.4f}]")
        print('  reliability (bins with at least 20 games): bin, n, mean p, observed')
        for label, c, mp, ob in block['s0b']['reliability']:
            print(f"    {label}  {c:4d}  {mp:.3f}  {ob:.3f}")


def main():
    dev = sqlite3.connect(DEV_DB, uri=True)
    report(run(dev))


if __name__ == '__main__':
    main()
