#!/usr/bin/env python3
"""Summarize the three paired SLC-V2 pass-label smoke arms from compressed ledgers."""
import collections
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'simulation-outputs'
ARMS = ('legacy', 'off', 'two-stage')
EVENTS = ('sack', 'pass_complete', 'pass_incomplete', 'interception', 'fumble_lost')


def records(path):
    with gzip.open(path, 'rt') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def summarize(arm):
    seeds = records(OUT / f'{arm}.seeds.jsonl.gz')
    boxes = records(OUT / f'{arm}.boxscores.jsonl.gz')
    header = seeds[0]['header']
    seed_rows = seeds[1:]
    box_rows = [row for row in boxes[1:] if row.get('type') != 'header']
    by_seed = {row['seed']: row for row in box_rows}
    event_counts = collections.Counter()
    dropback_plays = 0
    staged_sack_probabilities = []
    team_stats = collections.Counter()
    total_points = []
    score_rows = []
    score_tail = {'team_scores_le_10': 0, 'games_total_ge_60': 0}
    for row in seed_rows:
        outcome = row['outcome']
        home, away = int(outcome['home_points']), int(outcome['away_points'])
        total_points.append(home + away)
        score_rows.append({'seed': row['seed'], 'home': home, 'away': away,
                           'valid_full_game': bool(outcome.get('valid_full_game'))})
        score_tail['team_scores_le_10'] += int(home <= 10) + int(away <= 10)
        score_tail['games_total_ge_60'] += int(home + away >= 60)
        if not outcome.get('valid_full_game'):
            continue
        for trace in outcome.get('outcome_probability_traces', []):
            if trace.get('intent') == 'dropback' and trace.get('outcome_intent') == 'dropback':
                event = trace.get('event_selected')
                if event in EVENTS:
                    event_counts[event] += 1
                    dropback_plays += 1
            for stage in trace.get('stages', []):
                if stage.get('stage') == 'two_stage_pre_pass_group':
                    staged_sack_probabilities.append(stage.get('sack_probability'))
    reconciliation = collections.Counter()
    for box in box_rows:
        reconciliation[box.get('reconciliation', {}).get('status', 'missing')] += 1
        for team in box.get('teams', []):
            stats = team.get('stats', {})
            for key in ('points', 'plays', 'completions', 'pass_attempts', 'sacks_taken',
                        'interceptions', 'fumbles_lost', 'turnovers', 'first_downs'):
                team_stats[key] += int(stats.get(key) or 0)
    if len(by_seed) != len(seed_rows):
        raise ValueError(f'{arm}: box-score sidecar seed count mismatch')
    return {'mode': header.get('playcall_pass_label_mode'),
            'stream_root_sha256': header['rng_protocol']['stream_root_sha256'],
            'source_commit': header.get('source_commit'),
            'producer_sha256': header['pairing_identity']['execution_settings'].get('additional_producer_sha256', {}),
            'source_file_sha256': header['pairing_identity']['execution_settings'].get('producer_file_sha256', {}),
            'seeds': [row['seed'] for row in seed_rows],
            'valid_games': sum(row['valid_full_game'] for row in score_rows),
            'game_count': len(score_rows),
            'strict_boxscore_reconciliation': dict(reconciliation),
            'scores': score_rows,
            'mean_points_per_team': sum(sum((r['home'], r['away'])) for r in score_rows) / (2 * len(score_rows)),
            'mean_game_total': sum(total_points) / len(total_points),
            'score_tails': score_tail,
            'dropbacks': dropback_plays,
            'two_stage_first_stage_draws': len(staged_sack_probabilities),
            'mean_two_stage_first_stage_sack_probability': (
                sum(x for x in staged_sack_probabilities if x is not None) /
                max(1, sum(x is not None for x in staged_sack_probabilities))),
            'dropback_events': dict(event_counts),
            'dropback_rates': {event: event_counts[event] / dropback_plays if dropback_plays else None
                               for event in EVENTS},
            'summed_team_boxscore_stats': dict(team_stats)}


def main():
    results = {arm: summarize(arm) for arm in ARMS}
    roots = {arm: result['stream_root_sha256'] for arm, result in results.items()}
    seeds = {arm: result['seeds'] for arm, result in results.items()}
    if len(set(roots.values())) != 1:
        raise ValueError(f'paired RNG roots differ: {roots}')
    if len(set(tuple(values) for values in seeds.values())) != 1:
        raise ValueError(f'seed IDs differ: {seeds}')
    if any(result['valid_games'] != result['game_count'] for result in results.values()):
        raise ValueError('at least one full-game seed failed validation')
    result = {'schema': 'slc-pass-label-ordering-simulation-summary-v1',
              'paired_stream_root_sha256': next(iter(roots.values())),
              'paired_seed_ids': next(iter(seeds.values())),
              'arms': results,
              'scope': 'Three paired ARI-SEA V2/D1 seeds per arm. Full-game smoke check only; not a scoring calibration study.'}
    result['input_identity'] = {
        'database_sha256': json.loads((HERE / 'audit-results.json').read_text())['database_sha256'],
        'pbp_2026_sha256': '5030e8fc1739ea8f93ce67b461f76d3ae89b2f952d430ddbfa5b7f7f07d44b18',
        'snapshot_sha256': 'cc44c5e0f0e3216a6785d2b79af65174a27b95133e8600da07d412237338e475',
        'playcall_artifact_sha256': 'c8f16540931f6fddc61b6e62797ecd71dfff11897c393c531033eef623328ce5',
        'snap_counts_sha256': '36f28e18af3080df9f160d42dd5e3e59c37cfacf0dd24772ea51cfd41cadcfca',
        'workload_D1_sha256': 'cec16cb2462ef71eaf0fc5d300ce6729e57c915b114dd8615f8e7d924986a618',
        'participation_field_sha256': '9aaf7e57ce45bc525393de105c2b803673d441b589588a279a28e57ce2880a41',
    }
    result['compressed_artifacts'] = {
        path.name: {'bytes': path.stat().st_size, 'sha256': sha(path)}
        for path in sorted(OUT.glob('*.gz'))
    }
    path = HERE / 'simulation-results.json'
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
