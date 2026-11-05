#!/usr/bin/env python3
"""Blocked seeds for 2026_09_JAX_BAL across the v1, v15 and v2 outputs: blocker families, drive boundaries, run exposure.

Read-only. Reads out/<arm>/game.seeds.jsonl, game.boxscores.jsonl and game.json and writes only --out.

Where a block happens: the recorded plays stop one play before the blocked play. The blocked play is the first play of
unresolved_transition.decision.drive_index, so the previous recorded play is the last play of the drive before it.

Pairing: v1 and v15 share the rng scheme v1 and stream key, so their seeds are paired. v2 uses the rng scheme v2 with its
own stream root, so a seed number in v2 is not the same random stream. v2 is compared with v15 in aggregate only.

Usage: python3 blocked_seed_analysis.py --root /root/repro/jax-bal-w09/out --out REPORT.json
"""
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ARMS = ('v1', 'v15', 'v2')
ARG = re.compile(r"\((\d+), '([^']+)', '([^']+)'\)")
TAIL = re.compile(r":\(.*\)$")
RUN_FAMILY = 'non_scramble_run_source_rows_missing'


def family(reason):
    return TAIL.sub('', reason)


def cell_of(reason):
    match = ARG.search(reason)
    return None if match is None else (int(match.group(1)), match.group(2), match.group(3))


def distance_bucket(yards):
    if yards <= 3:
        return '1-3'
    if yards <= 6:
        return '4-6'
    if yards <= 10:
        return '7-10'
    return '11+'


def yardline_bucket(yardline_100):
    if yardline_100 <= 9:
        return '1-9'
    if yardline_100 <= 19:
        return '10-19'
    if yardline_100 <= 49:
        return '20-49'
    if yardline_100 <= 79:
        return '50-79'
    return '80-99'


def state_cell(state):
    return (state['down'], distance_bucket(state['yards_to_go']), yardline_bucket(state['yardline_100']))


def read_arm(root, arm):
    outcomes, header = {}, None
    with open(root / arm / 'game.seeds.jsonl') as handle:
        for line in handle:
            row = json.loads(line)
            if 'header' in row:
                header = row['header']
                continue
            outcome = row['outcome']
            outcomes[outcome['seed']] = {key: outcome.get(key) for key in
                                         ('status', 'blocker', 'home_points', 'away_points', 'unresolved_transition')}
    plays = {}
    with open(root / arm / 'game.boxscores.jsonl') as handle:
        for line in handle:
            row = json.loads(line)
            if row.get('type') == 'manifest':
                continue
            plays[row['seed']] = sorted(row['realism']['plays'], key=lambda play: play['sequence'])
    with open(root / arm / 'game.json') as handle:
        blocker_counts = json.load(handle)['summary']['blocker_counts']
    return {'header': header, 'outcomes': outcomes, 'plays': plays, 'blocker_counts': blocker_counts}


def two_proportion_z(x1, x2, n1, n2):
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    spread = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    return None if spread == 0 else round((p2 - p1) / spread, 2)


def drive_starts(plays):
    """{drive_index: (total points, margin)} at the first recorded play of each drive. Plays are in sequence order."""
    starts = {}
    for play in plays:
        state = play['state_before']
        starts.setdefault(state['drive_index'], (state['home_score'] + state['away_score'],
                                                 abs(state['home_score'] - state['away_score'])))
    return starts


def start_comparison(expected, observed):
    """Blocked seeds' points at the start of the drive before their block, against complete seeds at that same drive.

    Both sides are measured before the blocked drive, so the blocked seed's score path is fully recorded. The complete
    seeds' mean at each drive index is the expected value for the blocked seeds at that index.
    """
    means = {drive: (mean([t for t, _ in pairs]), mean([m for _, m in pairs])) for drive, pairs in expected.items()}
    diffs_total, diffs_margin, by_arm = [], [], defaultdict(list)
    for arm, drive, (total, margin) in observed:
        if drive not in means:
            continue
        diffs_total.append(total - means[drive][0])
        diffs_margin.append(margin - means[drive][1])
        by_arm[arm].append(total - means[drive][0])

    def summarise(values):
        if not values:
            return None
        avg = mean(values)
        spread = math.sqrt(sum((v - avg) ** 2 for v in values) / (len(values) - 1)) if len(values) > 1 else None
        return {'n': len(values), 'mean_difference': round(avg, 3),
                'ci95': None if spread is None else [round(avg - 1.96 * spread / math.sqrt(len(values)), 3),
                                                     round(avg + 1.96 * spread / math.sqrt(len(values)), 3)]}
    return {'total_points': summarise(diffs_total), 'margin': summarise(diffs_margin),
            'by_arm_total_points': {arm: summarise(values) for arm, values in sorted(by_arm.items())}}


def mean(values):
    return sum(values) / len(values) if values else None


def analyse(root):
    data = {arm: read_arm(root, arm) for arm in ARMS}
    report = {'arms': {}, 'families': {}, 'v1_v15_paired': {}, 'v2_vs_v15': {}, 'drive_boundaries': {},
              'run_exposure': {}}

    for arm, arm_data in data.items():
        outcomes = arm_data['outcomes']
        blocked = [o for o in outcomes.values() if o['status'] == 'blocked']
        report['arms'][arm] = {
            'seed_rows': len(outcomes),
            'status': dict(Counter(o['status'] for o in outcomes.values())),
            'blocked': len(blocked),
            'blocker_counts_match_game_json': Counter(o['blocker'] for o in blocked) == Counter(arm_data['blocker_counts']),
            'rng_scheme': arm_data['header']['rng_protocol']['scheme'],
        }

    families = defaultdict(lambda: {arm: 0 for arm in ARMS})
    for arm, arm_data in data.items():
        for o in arm_data['outcomes'].values():
            if o['status'] == 'blocked':
                families[family(o['blocker'])][arm] += 1
    for name, counts in sorted(families.items(), key=lambda item: -sum(item[1].values())):
        report['families'][name] = dict(counts, v2_minus_v15=counts['v2'] - counts['v15'],
                                        z_v2_vs_v15=two_proportion_z(counts['v15'], counts['v2'], 1000, 1000))

    v1, v15 = data['v1']['outcomes'], data['v15']['outcomes']
    report['v1_v15_paired'] = {
        'seeds': len(v1),
        'same_status': sum(1 for seed in v1 if v1[seed]['status'] == v15[seed]['status']),
        'both_blocked': sum(1 for seed in v1 if v1[seed]['status'] == 'blocked' and v15[seed]['status'] == 'blocked'),
        'both_blocked_same_reason': sum(1 for seed in v1 if v1[seed]['status'] == 'blocked'
                                        and v15[seed]['status'] == 'blocked' and v1[seed]['blocker'] == v15[seed]['blocker']),
    }
    blocked_v15 = sum(1 for o in v15.values() if o['status'] == 'blocked')
    blocked_v2 = sum(1 for o in data['v2']['outcomes'].values() if o['status'] == 'blocked')
    report['v2_vs_v15'] = {'blocked_v15': blocked_v15, 'blocked_v2': blocked_v2,
                           'z': two_proportion_z(blocked_v15, blocked_v2, 1000, 1000)}

    # Drive boundaries: the event type of the play before each drive start. Complete seeds give the base rate; blocked
    # seeds give the event before their blocking drive, which is the last recorded play.
    boundary, block_transition = Counter(), Counter()
    boundary_quarter, block_quarter = Counter(), Counter()
    checks = Counter()
    block_rows = []
    runs_in_cell, blocks_in_cell = Counter(), Counter()
    expected = defaultdict(list)
    observed = []
    for arm, arm_data in data.items():
        for seed, o in arm_data['outcomes'].items():
            plays = arm_data['plays'].get(seed, [])
            for play in plays:
                if play.get('decision_type') == 'run':
                    runs_in_cell[(arm, state_cell(play['state_before']))] += 1
            starts = drive_starts(plays)
            if o['status'] != 'blocked':
                for prev, cur in zip(plays, plays[1:]):
                    if cur['state_before']['drive_index'] != prev['state_before']['drive_index']:
                        boundary[prev['event_type']] += 1
                        boundary_quarter[prev['state_before']['quarter']] += 1
                for drive, start in starts.items():
                    expected[drive].append(start)
                continue
            transition = o['unresolved_transition'] or {}
            block_drive = (transition.get('decision') or {}).get('drive_index')
            if o['blocker'] and family(o['blocker']) == RUN_FAMILY:
                blocks_in_cell[(arm, cell_of(o['blocker']))] += 1
            if not plays:
                checks[f'{arm} blocked seed with no plays recorded'] += 1
                continue
            last = plays[-1]['state_before']
            if block_drive is None:
                checks['blocked seed with no drive index (kick-family block)'] += 1
            elif last['drive_index'] == block_drive - 1:
                checks['previous recorded play is the drive before the block'] += 1
            else:
                checks['previous recorded play is NOT the drive before the block'] += 1
            if block_drive is not None:
                block_transition[plays[-1]['event_type']] += 1
                block_quarter[last['quarter']] += 1
                if block_drive - 1 in starts:
                    observed.append((arm, block_drive - 1, starts[block_drive - 1]))
            block_rows.append({'arm': arm, 'seed': seed, 'family': family(o['blocker']), 'cell': cell_of(o['blocker']),
                               'quarter': last['quarter'], 'block_drive': block_drive,
                               'margin_before_last_play': abs(last['home_score'] - last['away_score']),
                               'previous_event': plays[-1]['event_type']})
    report['drive_boundaries'] = {'complete_seed_drive_endings': dict(boundary),
                                  'blocked_seed_drive_ending_before_block': dict(block_transition),
                                  'complete_seed_drive_ending_quarter': dict(boundary_quarter),
                                  'blocked_seed_drive_ending_quarter': dict(block_quarter),
                                  'checks': dict(checks)}
    report['drive_start_comparison'] = start_comparison(expected, observed)

    report['block_rows'] = {'count': len(block_rows),
                            'by_quarter': {f'{arm} Q{quarter}': n for (arm, quarter), n in sorted(
                                Counter((r['arm'], r['quarter']) for r in block_rows).items())}}

    # Run exposure: blocks in a cell per recorded run play in that cell, by yardline bucket, per arm.
    exposure = {}
    for arm in ARMS:
        by_yard = defaultdict(lambda: [0, 0])
        for (a, cell), n in runs_in_cell.items():
            if a == arm:
                by_yard[cell[2]][0] += n
        for (a, cell), n in blocks_in_cell.items():
            if a == arm:
                by_yard[cell[2]][1] += n
        exposure[arm] = {yard: {'recorded_runs': runs, 'run_blocks': blocks,
                                'per_1000_run_exposures': round(1000 * blocks / (runs + blocks), 2)}
                         for yard, (runs, blocks) in sorted(by_yard.items())}
    report['run_exposure'] = exposure
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args(argv)
    report = analyse(args.root)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps(report, indent=1, sort_keys=True, default=str))


if __name__ == '__main__':
    main()
