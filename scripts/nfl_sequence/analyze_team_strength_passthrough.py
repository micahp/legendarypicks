#!/usr/bin/env python3
"""Summarize the paired SLC team-strength ablation seed ledgers.

Reads the frozen 40-seed team-neutral, score-clock, and team-outcome arms and
reports valid coverage plus paired t intervals on their common valid seeds.
"""
import argparse
import json
from pathlib import Path

from scipy import stats


MATCHUPS = ('MIA-NE', 'SEA-CHI', 'NYJ-LV')
ARMS = ('team-neutral', 'off', 'on')
CONTRASTS = (
    ('off', 'team-neutral', 'call_effect_off_minus_neutral'),
    ('on', 'off', 'team_outcomes_on_minus_off'),
    ('on', 'team-neutral', 'combined_on_minus_neutral'),
)
METRICS = ('home_margin', 'total_points', 'home_win')
SOURCE_COMMIT = '03c8c1f7ded4b382855534d484697f15d42e8903'
BASE_ARTIFACT_SHA256 = '27c02afd6d9f6f80a38b3bc7ae278b1efebcc7caa5664688c64c55bc0c698ac7'
NEUTRAL_ARTIFACT_SHA256 = '29bcadd8ec40c07ae5dddc38ddfe84cf9483c98124295ea994d2c32017adede5'


def read_ledger(path):
    with path.open() as stream:
        header = json.loads(next(stream))['header']
        rows = {}
        for line in stream:
            item = json.loads(line)
            outcome = item['outcome']
            seed = int(item['seed'])
            if seed in rows:
                raise ValueError(f'{path}: duplicate seed {seed}')
            rows[seed] = {
                'valid_full_game': bool(outcome['valid_full_game']),
                'home_margin': float(outcome['home_points'] - outcome['away_points']),
                'total_points': float(outcome['home_points'] + outcome['away_points']),
                'home_win': float(outcome['home_points'] > outcome['away_points']),
            }
    if header.get('seed_start') != 1 or len(rows) != 40 or sorted(rows) != list(range(1, 41)):
        raise ValueError(f'{path}: expected exactly seeds 1 through 40')
    return header, rows


def paired_interval(values):
    n = len(values)
    if n < 2:
        raise ValueError(f'paired interval needs at least two rows, got {n}')
    mean = stats.tmean(values)
    se = stats.sem(values)
    critical = stats.t.ppf(0.975, n - 1)
    return {
        'n': n,
        'mean': float(mean),
        'ci95_low': float(mean - critical * se),
        'ci95_high': float(mean + critical * se),
    }


def analyze(root):
    result = {
        'method': 'paired t interval on common valid seed IDs; two-sided 95%',
        'expected_seeds': list(range(1, 41)),
        'matchups': {},
    }
    for matchup in MATCHUPS:
        ledgers = {}
        headers = {}
        for arm in ARMS:
            headers[arm], ledgers[arm] = read_ledger(root / f'{matchup}-{arm}.seeds.jsonl')
            header = headers[arm]
            expected_artifact = NEUTRAL_ARTIFACT_SHA256 if arm == 'team-neutral' else BASE_ARTIFACT_SHA256
            expected_team_outcomes = arm == 'on'
            if header.get('source_commit') != SOURCE_COMMIT:
                raise ValueError(f'{matchup}-{arm}: unexpected source commit {header.get("source_commit")}')
            if header.get('playcall_artifact_sha256') != expected_artifact:
                raise ValueError(f'{matchup}-{arm}: unexpected play-call artifact hash')
            if bool(header.get('playcall_team_outcomes')) != expected_team_outcomes:
                raise ValueError(f'{matchup}-{arm}: unexpected team-outcome flag')
        game_ids = {headers[arm].get('game_id') for arm in ARMS}
        if len(game_ids) != 1:
            raise ValueError(f'{matchup}: arm game ids differ: {sorted(game_ids)}')
        source_hashes = {headers[arm].get('source_snapshot_sha256') for arm in ARMS}
        if len(source_hashes) != 1:
            raise ValueError(f'{matchup}: arm source snapshots differ')
        common = [seed for seed in range(1, 41)
                  if all(ledgers[arm][seed]['valid_full_game'] for arm in ARMS)]
        if not common:
            raise ValueError(f'{matchup}: no seed valid in all arms')
        item = {
            'game_id': next(iter(game_ids)),
            'source_snapshot_sha256': next(iter(source_hashes)),
            'valid_full_games_by_arm': {
                arm: sum(row['valid_full_game'] for row in ledgers[arm].values())
                for arm in ARMS
            },
            'common_valid_seeds': common,
            'contrasts': {},
        }
        for left, right, label in CONTRASTS:
            item['contrasts'][label] = {}
            for metric in METRICS:
                deltas = [ledgers[left][seed][metric] - ledgers[right][seed][metric]
                          for seed in common]
                item['contrasts'][label][metric] = paired_interval(deltas)
        result['matchups'][matchup] = item
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('docs/research/slc-team-strength-passthrough-2026-10-29'))
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = analyze(args.root)
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded)
    else:
        print(encoded, end='')


if __name__ == '__main__':
    main()
