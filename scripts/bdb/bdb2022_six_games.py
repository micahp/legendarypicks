#!/usr/bin/env python3
"""Clock replay of the six 2022 games whose pairings repeat this weekend's 2026 matchups (the focus section of the weeks 1-9 audit).

Each game keeps its real play sequence. Runoffs on run, pass, sack and similar plays are drawn from each model (A, B, C as in
bdb2022_clock_models.py); everything else (kickoffs, punts, field goals, markers) keeps its observed runoff. The pools are fitted
on every matched play outside the six games, so the games never test themselves.

For each quarter, the clock the draws consume is compared with the clock the observed plays consumed. That total is known exactly
from the play-by-play (first play's clock minus the quarter-end marker's clock). A draw total above the observed total would run
the clock out before the observed last play; one below would leave clock unused at the marker.

Nothing here simulates team strength, scoring or the 2026 teams. The sequences and team identities are the 2022 games'.

Usage: python3 bdb2022_six_games.py [--out-dir DIR]
"""
import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import importlib.util

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cm = load_module('bdb2022_clock_models', HERE / 'bdb2022_clock_models.py')
SEED = 20261025
AUDIT_JSON = ROOT / 'docs' / 'research' / 'bdb2022-clock-audit-weeks1-9-2026-10-24.json'


def six_games():
    """2022 game id -> 2026 schedule id, for the 2022 games that repeat a focus pairing (from the audit's focus section)."""
    audit = json.load(open(AUDIT_JSON))
    out = {}
    for f in audit['focus']:
        for d in f['dataset_games']:
            if d['matched_plays'] > 0:
                out[d['lp_game_id']] = f['schedule_game_id']
    return out


def median(values):
    s = sorted(values)
    return s[len(s) // 2] if len(s) % 2 else round((s[len(s) // 2 - 1] + s[len(s) // 2]) / 2, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=str(ROOT / 'docs' / 'research'))
    args = ap.parse_args()

    games = six_games()
    if len(games) != 6:
        raise SystemExit(f'expected six focus games, found {len(games)}: {games}')
    extras = cm.audit.load_extras()
    lp_plays = cm.load_lp(extras)
    lp_by_key = {(p['game_id'], p['play_id']): p for p in lp_plays}
    matched = cm.load_matched(lp_by_key)
    fit = [x for x in matched if x['game'] not in games]
    pools = cm.build_pools(fit)
    draw = cm.make_draw(pools, random.Random(SEED))
    K = cm.K

    seqs = defaultdict(list)
    for p in lp_plays:
        if p['game_id'] in games:
            seqs[p['game_id']].append(p)

    counts = {m: Counter() for m in 'ABC'}
    quarter_rows, skipped = [], Counter()
    for gid in sorted(games):
        by_q = defaultdict(list)
        for p in seqs[gid]:
            by_q[p['qtr']].append(p)
        if max(by_q) > 4:
            raise SystemExit(f'{gid} has an overtime period; this replay covers regulation only')
        for q in sorted(by_q):
            rows = by_q[q]
            if len(rows) < 2 or any(r['gsr'] is None for r in rows):
                skipped['quarter without clock stamps'] += 1
                continue
            body = rows[:-1]
            if any(r['runoff'] is None for r in body):
                skipped['unresolved runoff inside the quarter'] += 1
                continue
            obs_total = rows[0]['gsr'] - rows[-1]['gsr']
            if sum(r['runoff'] for r in body) != obs_total:
                raise SystemExit(f'{gid} Q{q}: observed runoffs do not sum to the quarter clock')
            errors = {}
            for m in 'ABC':
                sums = [0] * K
                for r in body:
                    d = None
                    if (r['outcome'] in cm.MODELLED and r['down'] is not None and r['distance'] is not None
                            and r['yardline'] is not None):
                        d = draw(m, r)
                        if d is None:
                            counts[m]['observed: thin pool'] += 1
                        else:
                            counts[m]['modelled'] += 1
                    else:
                        counts[m]['observed: not a modelled play'] += 1
                    if d is None:
                        d = [r['runoff']] * K
                    sums = [a + b for a, b in zip(sums, d)]
                errors[m] = [s - obs_total for s in sums]
            quarter_rows.append({'game': gid, 'schedule_game': games[gid], 'quarter': int(q), 'plays': len(rows),
                                 'observed_clock_seconds': obs_total, 'errors': errors})

    model_out = {}
    for m in 'ABC':
        all_errors = [e for row in quarter_rows for e in row['errors'][m]]
        per_quarter = [{'game': row['game'], 'quarter': row['quarter'], 'plays': row['plays'],
                        'observed_clock_seconds': row['observed_clock_seconds'],
                        'median_error_seconds': median(row['errors'][m]),
                        'p10': round(sorted(row['errors'][m])[int(0.10 * (K - 1))], 1),
                        'p90': round(sorted(row['errors'][m])[int(0.90 * (K - 1))], 1),
                        'share_overshoot': round(sum(1 for e in row['errors'][m] if e > 0) / K, 3)}
                       for row in quarter_rows]
        game_totals = {}
        for gid in sorted(games):
            rows = [row for row in quarter_rows if row['game'] == gid]
            if len(rows) == 4:
                totals = [sum(row['errors'][m][k] for row in rows) for k in range(K)]
                game_totals[gid] = {'median_total_error_seconds': median(totals),
                                    'share_overshoot': round(sum(1 for t in totals if t > 0) / K, 3)}
        model_out[m] = {
            'quarters': per_quarter,
            'median_error_seconds': median(all_errors),
            'mean_abs_error_seconds': round(sum(abs(e) for e in all_errors) / len(all_errors), 2),
            'share_overshoot': round(sum(1 for e in all_errors if e > 0) / len(all_errors), 4),
            'share_undershoot': round(sum(1 for e in all_errors if e < 0) / len(all_errors), 4),
            'game_totals': game_totals,
            'play_draws': dict(counts[m]),
        }

    result = {
        'games': {gid: games[gid] for gid in sorted(games)},
        'fit': 'every matched play outside the six games', 'draws_per_quarter': K, 'seed': SEED,
        'quarters_used': len(quarter_rows), 'skipped': dict(skipped),
        'models': model_out,
    }
    out = Path(args.out_dir) / 'bdb2022-six-games-clock-replay-2026-10-24.json'
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'models'}, indent=1, sort_keys=True))
    for m in 'ABC':
        s = model_out[m]
        print(m, 'median error', s['median_error_seconds'], 'mean abs', s['mean_abs_error_seconds'],
              'overshoot', s['share_overshoot'], 'undershoot', s['share_undershoot'], 'draws', s['play_draws'])


if __name__ == '__main__':
    main()
