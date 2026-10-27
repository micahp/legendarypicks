#!/usr/bin/env python3
"""Free-running games: the E2 control against research clock D, on the same seeds.

Each seed is played twice, once with the E2 clock (control) and once with D, both through game_state.play_game with the
same reference. The outcome sequence matches until the two clocks first disagree about a quarter, after which the games
diverge. The per-seed rows and the summary here are what the comparison reports.

Usage: python3 clock_d_games.py --seeds 300 [--out-dir DIR]
"""
import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clock_d as cd  # noqa: E402
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402

DEV_GAMES = ('2022_05_CIN_BAL', '2022_09_GB_DET', '2022_05_MIA_NYJ', '2022_06_SF_ATL', '2022_07_TB_CAR', '2022_06_DAL_PHI')
LATE = 120


def play_rows(record):
    """Every drive play, with its quarter, clock at the snap, runoff and whether it clamped."""
    rows = []
    for d in record['drives']:
        for p in d['plays']:
            s = p['state_before']
            rows.append({'drive': d['index'], 'event': p['event_type'], 'quarter': s['quarter'],
                         'clock': s['clock_seconds'], 'runoff': p['outcome']['clock_runoff_seconds'],
                         'clamped': p['outcome']['clock_clamped_to_zero'],
                         'ends_quarter': p['outcome']['clock_clamped_to_zero'] or p['outcome']['quarter_change']
                         or p['outcome'].get('clock_only_terminal') is not None and
                         p['outcome'].get('clock_only_terminal') is not False})
    return rows


def per_seed(seed, record):
    rows = play_rows(record)
    per_q = Counter(r['quarter'] for r in rows)
    drive_seconds = [sum(p['outcome']['clock_runoff_seconds'] for p in d['plays']) for d in record['drives']]
    ends = Counter()
    for d in record['drives']:
        last = d['plays'][-1] if d['plays'] else None
        if last and (last['outcome']['clock_clamped_to_zero'] or last['outcome']['quarter_change']):
            ends[last['event_type']] += 1
    late = [r for r in rows if r['quarter'] in cd.LATE_QUARTERS and r['clock'] <= LATE]
    kinds = Counter(b['kind'] for b in record['boundaries'])
    return {
        'seed': seed, 'status': record['status'], 'complete_regulation': record['complete_regulation'],
        'plays': len(rows), 'drives': len(record['drives']),
        'points_A': record['points'].get('A', 0), 'points_B': record['points'].get('B', 0),
        'points': sum(record['points'].values()),
        'plays_q1': per_q[1], 'plays_q2': per_q[2], 'plays_q3': per_q[3], 'plays_q4': per_q[4],
        'clamped_plays': sum(1 for r in rows if r['clamped']),
        'boundaries': dict(kinds), 'quarter_end_events': dict(ends),
        'median_drive_seconds': statistics.median(drive_seconds) if drive_seconds else None,
        'late_plays': len(late), 'late_run_or_pass': sum(1 for r in late if r['event'] in ('run', 'pass_complete',
                                                                                          'pass_incomplete', 'sack')),
        'final_quarter': record['final_quarter'], 'final_clock_seconds': record['final_clock_seconds'],
        'blocker': record.get('blocker'),
    }


def summarise(rows):
    complete = [r for r in rows if r['complete_regulation']]
    out = {'games': len(rows), 'complete_regulation': len(complete),
           'blocked': sum(1 for r in rows if r['status'] == 'blocked')}
    for k in ('plays', 'drives', 'points', 'plays_q1', 'plays_q2', 'plays_q3', 'plays_q4', 'clamped_plays', 'late_plays'):
        vals = [r[k] for r in complete]
        out[k] = {'mean': round(statistics.fmean(vals), 2), 'median': statistics.median(vals),
                  'p10': sorted(vals)[len(vals) // 10], 'p90': sorted(vals)[(9 * len(vals)) // 10]} if vals else None
    ends = Counter()
    for r in complete:
        ends.update(r['quarter_end_events'])
    out['quarter_end_events'] = dict(ends)
    out['boundaries'] = dict(sum((Counter(r['boundaries']) for r in complete), Counter()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=300)
    ap.add_argument('--out-dir', default=str(Path(__file__).resolve().parents[2] / 'docs' / 'research' / 'e3'))
    args = ap.parse_args()

    ref, _ = er.load()
    train = [r for r in cd.load_window(e1.DEFAULT_DB, 2022, 2022, 1, 5) if r['game_id'] not in DEV_GAMES]
    model = cd.fit(train, cd.load_flags())

    runs = {}
    for label, clock_model in (('E2', None), ('D', model)):
        ref.clock_model = clock_model
        rows = []
        for seed in range(1, args.seeds + 1):
            record = gs.play_game(seed, ref)
            rows.append(per_seed(seed, record))
        runs[label] = rows

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / 'clock-d-games-per-seed.csv', 'w', newline='') as f:
        fields = list(runs['E2'][0].keys())
        writer = csv.DictWriter(f, fieldnames=['clock'] + fields)
        writer.writeheader()
        for label in ('E2', 'D'):
            for r in runs[label]:
                writer.writerow({'clock': label, **{k: json.dumps(v) if isinstance(v, dict) else v for k, v in r.items()}})
    summary = {label: summarise(rows) for label, rows in runs.items()}
    summary['model'] = {'fit_counts': {k: v for k, v in model.fit_counts.items()
                                        if not k.startswith('plays fitted') and not k.startswith('quarter-ending')},
                        'train': 'weeks 1-5 of 2022, excluding the six development games'}
    (out_dir / 'clock-d-games-summary.json').write_text(json.dumps(summary, indent=1, sort_keys=True) + '\n')
    print(json.dumps(summary, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
