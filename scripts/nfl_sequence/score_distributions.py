#!/usr/bin/env python3
"""Score distributions and win-probability bounds for one matchup's batch runs, conditional on completed simulations.

Completed seeds have status complete_regulation or complete_overtime. Blocked seeds have no final score, so they are
reported as a count and left out of every distribution. Win bounds on the unconditional probability over all seeds treat
every blocked seed as a home win (upper) or as a home loss (lower). Ties count as neither side's win.

The narrowest 80% band is the shortest run of consecutive integer scores whose completed-seed share is at least 80%. If
two bands have the same width, the lower one is kept.

Usage: python3 score_distributions.py --root OUT --arm v1 --arm v15 --arm v2 --home BAL --away JAX --out-dir DIR
"""
import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path

COMPLETE = ('complete_regulation', 'complete_overtime')
LEVEL = 0.8


def read_outcomes(path):
    outcomes = []
    with open(path) as handle:
        for line in handle:
            row = json.loads(line)
            if 'outcome' in row:
                outcome = row['outcome']
                outcomes.append({key: outcome.get(key) for key in ('seed', 'status', 'home_points', 'away_points')})
    return outcomes


def narrowest_band(counts, level=LEVEL):
    """(low, high, share) of the shortest run of integer values holding at least `level` of the completed mass."""
    total = sum(counts.values())
    values = sorted(counts)
    best = None
    for index, low in enumerate(values):
        mass = 0
        for high in values[index:]:
            mass += counts[high]
            if mass / total >= level:
                if best is None or high - low < best[1] - best[0]:
                    best = (low, high, mass / total)
                break
    return best


def summarise(values):
    counts = Counter(values)
    low, high, share = narrowest_band(counts)
    ordered = sorted(values)
    median = statistics.median(ordered)
    return {'completed': len(values), 'median': int(median) if float(median).is_integer() else median,
            'mean': round(statistics.fmean(ordered), 2),
            'narrowest_80_low': low, 'narrowest_80_high': high, 'narrowest_80_share': round(share, 3),
            'counts': counts}


def arm_summary(name, outcomes, home, away):
    completed = [o for o in outcomes if o['status'] in COMPLETE]
    blocked = sum(1 for o in outcomes if o['status'] == 'blocked')
    if len(completed) + blocked != len(outcomes):
        raise ValueError(f'{name}: {len(outcomes) - len(completed) - blocked} seeds are neither completed nor blocked')
    home_points = [o['home_points'] for o in completed]
    away_points = [o['away_points'] for o in completed]
    margin = [h - a for h, a in zip(home_points, away_points)]
    total = [h + a for h, a in zip(home_points, away_points)]
    home_wins = sum(1 for h, a in zip(home_points, away_points) if h > a)
    away_wins = sum(1 for h, a in zip(home_points, away_points) if a > h)
    ties = len(completed) - home_wins - away_wins
    seeds = len(outcomes)
    return {
        'arm': name, 'seeds': seeds, 'completed': len(completed), 'blocked': blocked,
        'blocked_rate': round(blocked / seeds, 3),
        'scores': {home: summarise(home_points), away: summarise(away_points),
                   'total': summarise(total), f'margin_{home}_minus_{away}': summarise(margin)},
        'ties_completed': ties,
        f'{home}_win_given_completed': round(home_wins / len(completed), 4),
        f'{away}_win_given_completed': round(away_wins / len(completed), 4),
        f'{home}_win_bounds': [round(home_wins / seeds, 4), round((home_wins + blocked) / seeds, 4)],
        f'{away}_win_bounds': [round(away_wins / seeds, 4), round((away_wins + blocked) / seeds, 4)],
    }


def write_histograms(path, summaries):
    with open(path, 'w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['arm', 'measure', 'value', 'count', 'share_of_completed'])
        for summary in summaries:
            for measure, stats in summary['scores'].items():
                completed = stats['completed']
                for value, count in sorted(stats['counts'].items()):
                    writer.writerow([summary['arm'], measure, value, count, round(count / completed, 5)])


def write_markdown(path, summaries, home, away):
    lines = [f'# Score distributions, {away} at {home}, conditional on completed simulations', '',
             'Every distribution below uses completed seeds only. Blocked seeds have no final score, so each table shows '
             'the blocked count next to it. The win bounds are for the unconditional probability over all seeds: the '
             'lower bound counts every blocked seed as a loss for that side, and the upper bound counts it as a win.', '']
    lines += ['| Arm | Seeds | Completed | Blocked | Blocked rate | Ties (completed) |', '|---|---:|---:|---:|---:|---:|']
    for s in summaries:
        lines.append(f"| {s['arm']} | {s['seeds']} | {s['completed']} | {s['blocked']} | {s['blocked_rate']:.1%} | "
                     f"{s['ties_completed']} |")
    lines += ['', '## Scores (completed seeds)', '',
              f'| Arm | Measure | Median | Mean | Narrowest 80% band | Share in band |', '|---|---|---:|---:|---|---:|']
    for s in summaries:
        for measure, stats in s['scores'].items():
            band = f"{stats['narrowest_80_low']} to {stats['narrowest_80_high']}"
            lines.append(f"| {s['arm']} | {measure} | {stats['median']} | {stats['mean']} | {band} | "
                         f"{stats['narrowest_80_share']:.1%} |")
    lines += ['', f'## {home} and {away} win probability', '',
              f'| Arm | {home} win, completed | {home} win bounds (all seeds) | {away} win, completed | '
              f'{away} win bounds (all seeds) |', '|---|---:|---|---:|---|']
    for s in summaries:
        hb, ab = s[f'{home}_win_bounds'], s[f'{away}_win_bounds']
        lines.append(f"| {s['arm']} | {s[f'{home}_win_given_completed']:.1%} | {hb[0]:.1%} to {hb[1]:.1%} | "
                     f"{s[f'{away}_win_given_completed']:.1%} | {ab[0]:.1%} to {ab[1]:.1%} |")
    lines += ['', 'Histograms: `score_distributions.csv` (one row per arm, measure and value).', '']
    path.write_text('\n'.join(lines))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--arm', action='append', required=True)
    ap.add_argument('--home', required=True)
    ap.add_argument('--away', required=True)
    ap.add_argument('--out-dir', type=Path, required=True)
    args = ap.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    for arm in args.arm:
        outcomes = read_outcomes(args.root / arm / 'game.seeds.jsonl')
        summaries.append(arm_summary(arm, outcomes, args.home, args.away))
    for s in summaries:
        for stats in s['scores'].values():
            stats['counts'] = {int(k): v for k, v in sorted(stats['counts'].items())}
    (args.out_dir / 'score_distributions.json').write_text(json.dumps(summaries, indent=1, sort_keys=True) + '\n')
    write_histograms(args.out_dir / 'score_distributions.csv', summaries)
    write_markdown(args.out_dir / 'SCORE-DISTRIBUTIONS.md', summaries, args.home, args.away)
    for s in summaries:
        print(s['arm'], s['completed'], s['blocked'], s['ties_completed'], s[f'{args.home}_win_bounds'],
              {k: (v['median'], v['narrowest_80_low'], v['narrowest_80_high']) for k, v in s['scores'].items()})


if __name__ == '__main__':
    main()
