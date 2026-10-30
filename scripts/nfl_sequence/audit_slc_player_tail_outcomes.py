#!/usr/bin/env python3
"""Audit named ARI-DAL SLC tail outcomes from immutable seed and boxscore artifacts."""
import argparse
import csv
import gzip
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import player_shares
import share_distributions


CASES = (
    {'id': 'javonte_williams_46_carries', 'player': 'Javonte Williams', 'role': 'carry',
     'metric': 'rush_attempts', 'threshold': 46, 'record_boundary': 45},
    {'id': 'javonte_williams_297_rush_yards', 'player': 'Javonte Williams', 'role': 'carry',
     'metric': 'rushing_yards', 'threshold': 297, 'record_boundary': 296},
    {'id': 'michael_wilson_29_targets', 'player': 'Michael Wilson', 'role': 'receive',
     'metric': 'targets', 'threshold': 29, 'record_boundary': 28},
    {'id': 'michael_wilson_22_receptions', 'player': 'Michael Wilson', 'role': 'receive',
     'metric': 'receptions', 'threshold': 22, 'record_boundary': 21},
    {'id': 'george_pickens_29_targets', 'player': 'George Pickens', 'role': 'receive',
     'metric': 'targets', 'threshold': 29, 'record_boundary': 28},
    {'id': 'jacoby_brissett_50_rush_yards', 'player': 'Jacoby Brissett', 'role': 'carry',
     'metric': 'rushing_yards', 'threshold': 50, 'record_boundary': 296},
    {'id': 'bam_knight_30_carries', 'player': 'Bam Knight', 'role': 'carry',
     'metric': 'rush_attempts', 'threshold': 30, 'record_boundary': 45},
)
EXPECTED_COUNTS = {
    'javonte_williams_46_carries': 11,
    'michael_wilson_29_targets': 15,
    'george_pickens_29_targets': 2,
    'jacoby_brissett_50_rush_yards': 1387,
    'bam_knight_30_carries': 207,
}
EXPECTED_MAXIMA = {
    'javonte_williams_46_carries': 54,
    'javonte_williams_297_rush_yards': 300,
    'michael_wilson_29_targets': 36,
    'michael_wilson_22_receptions': 23,
    'george_pickens_29_targets': 32,
    'jacoby_brissett_50_rush_yards': 147,
}
FLOOR = 0.01


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksums(artifact_dir):
    checksums = artifact_dir / 'SHA256SUMS.txt'
    if not checksums.is_file():
        raise FileNotFoundError(checksums)
    verified = {}
    for line in checksums.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        expected, name = line.split(maxsplit=1)
        name = name.lstrip('*').strip()
        path = artifact_dir / name
        if not path.is_file():
            raise FileNotFoundError(f'checksum entry missing from artifact archive: {name}')
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f'checksum mismatch for {name}: {actual} != {expected}')
        verified[name] = actual
    return verified


def load_prior_share_support(pbp_2025):
    counts = {'receive': Counter(), 'carry': Counter()}
    totals = {'receive': Counter(), 'carry': Counter()}
    with gzip.open(pbp_2025, 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row.get('season_type') != 'REG' or int(row.get('week') or 0) > 18:
                continue
            team = row.get('posteam')
            if not team:
                continue
            if row.get('play_type') == 'pass' and row.get('receiver_player_id'):
                role, player = 'receive', row['receiver_player_id']
            elif row.get('play_type') == 'run' and row.get('rusher_player_id'):
                role, player = 'carry', row['rusher_player_id']
            else:
                continue
            counts[role][(team, player)] += 1
            totals[role][team] += 1
    return counts, totals


def load_sqlite_role_counts(database, teams):
    columns = {'receive': ('receiver_player_id', 'pass'), 'carry': ('rusher_player_id', 'run')}
    output = {}
    con = sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro', uri=True, timeout=10)
    try:
        for role, (column, play_type) in columns.items():
            rows = con.execute(
                f"SELECT posteam, {column}, COUNT(*) FROM nfl_pbp WHERE season = 2025 AND week <= 18 "
                f"AND play_type = ? AND posteam IN ({','.join('?' for _ in teams)}) "
                f"AND posteam IS NOT NULL AND {column} IS NOT NULL GROUP BY posteam, {column}",
                (play_type, *teams)).fetchall()
            output[role] = {(team, player_id): count for team, player_id, count in rows}
    finally:
        con.close()
    return output


def _stat(player, metric):
    if metric == 'rush_attempts':
        return int(player['rushing']['att'])
    if metric == 'rushing_yards':
        return int(player['rushing']['yds'])
    if metric == 'targets':
        return int(player['receiving']['tgt'])
    if metric == 'receptions':
        return int(player['receiving']['rec'])
    raise ValueError(metric)


def _player_line(player):
    return {category: dict(values) for category, values in (
        ('passing', player['passing']), ('rushing', player['rushing']),
        ('receiving', player['receiving']), ('miscellaneous', player['miscellaneous']))}


def load_snapshot(artifact_dir):
    summary_path = artifact_dir / 'worker-01.json.gz'
    with gzip.open(summary_path, 'rt', encoding='utf-8') as handle:
        summary = json.load(handle)
    snapshot = summary.get('pregame_snapshot')
    if not snapshot:
        raise ValueError('worker summary does not contain its frozen pregame snapshot')
    qbs = {}
    rosters_by_team = {}
    for roster in snapshot['rosters'].values():
        team = roster['team']
        rosters_by_team[team] = roster
        for player in roster.get('players', []):
            if player.get('pos_abb') == 'QB':
                qbs[player['gsis_id']] = {'name': player.get('player_name'), 'team': team,
                                          'depth_rank': int(player['pos_rank'])}
    return snapshot, qbs, summary_path, summary['playcall_layer']['player_share_distribution']


def audit(artifact_dir, data_dir, out_dir, share_db=None):
    artifact_dir, data_dir, out_dir = Path(artifact_dir), Path(data_dir), Path(out_dir)
    artifact_hashes = verify_checksums(artifact_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f'refusing to overwrite nonempty output directory: {out_dir}')
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot, qbs, summary_path, share_model = load_snapshot(artifact_dir)
    pbp_path = data_dir / 'pbp_2025.csv.gz'
    benchmark_manifest_path = (Path(__file__).resolve().parents[2] / 'docs' / 'research'
                               / 'player-workload-reference-2026-10-30' / 'manifest.json')
    benchmark_manifest = json.loads(benchmark_manifest_path.read_text(encoding='utf-8'))
    expected_pbp_hash = benchmark_manifest['sources']['local_source_files']['pbp_2025.csv.gz']
    actual_pbp_hash = sha256(pbp_path)
    if actual_pbp_hash != expected_pbp_hash:
        raise ValueError(f'2025 PBP source hash mismatch: {actual_pbp_hash} != {expected_pbp_hash}')
    prior_counts, prior_totals = load_prior_share_support(pbp_path)
    share_db_validation = None
    share_db_hash = None
    if share_db is not None:
        share_db = Path(share_db)
        producer_audit = json.loads((artifact_dir / 'postrun-audit.json').read_text(encoding='utf-8'))
        producer_db_hash = producer_audit['provenance']['source_database_sha256']
        share_db_hash = sha256(share_db)
        producer_role_counts = load_sqlite_role_counts(share_db, ('ARI', 'DAL'))
        role_match = {
            role: producer_role_counts[role] == {
                key: count for key, count in prior_counts[role].items() if key[0] in ('ARI', 'DAL')
            }
            for role in ('receive', 'carry')
        }
        if not all(role_match.values()):
            raise ValueError(f'2025 ARI/DAL share-prior counts differ between pinned CSV and SQLite: {role_match}')
        share_db_validation = {
            'file': str(share_db), 'producer_database_sha256': producer_db_hash,
            'available_database_sha256': share_db_hash,
            'database_file_hash_matches_producer': share_db_hash == producer_db_hash,
            'ari_dal_role_counts_match_pinned_csv': role_match,
            'team_role_opportunity_counts': {
                f'{team}:{role}': sum(n for (row_team, _), n in producer_role_counts[role].items()
                                      if row_team == team)
                for team in ('ARI', 'DAL') for role in ('receive', 'carry')
            },
        }
    share_table = {
        'phi': {role: float(share_model['concentration'][role]['phi'])
                for role in ('receive', 'carry')},
        'model': share_model.get('model_version'),
        'base': {role: {(team, player_id): count / prior_totals[role][team]
                        for (team, player_id), count in prior_counts[role].items()
                        if prior_totals[role][team]}
                 for role in ('receive', 'carry')},
    }
    role_positions = {'receive': player_shares.TARGET_POSITIONS, 'carry': player_shares.CARRY_POSITIONS}
    share_populations = {}
    rosters_by_team = {r['team']: r for r in snapshot['rosters'].values()}
    players_by_team = {
        team: {p['gsis_id']: p for p in roster.get('players', []) if p.get('gsis_id')}
        for team, roster in rosters_by_team.items()
    }
    for team, roster in rosters_by_team.items():
        for role, positions in role_positions.items():
            population = share_distributions.eligible_players(
                [p for p in roster.get('players', []) if p.get('pos_abb') in positions],
                roster.get('injury_report'))
            share_populations[(team, role)] = tuple(sorted(p['gsis_id'] for p in population))
    artifact_hashes['worker-01.json.gz'] = sha256(summary_path)
    findings = []
    all_seeds = set()
    boxscore_count = 0
    game_status_counts = Counter()
    completed_overtime_tie_seeds = []
    regulation_tie_completed_seeds = []
    decisive_game_count = 0
    starter_values = Counter()
    backup_qb_participation = []
    game_share_cache = {}

    for seed_path in sorted(artifact_dir.glob('worker-*.seeds.jsonl.gz')):
        boxscore_path = seed_path.with_name(seed_path.name.replace('.seeds.', '.boxscores.'))
        if not boxscore_path.is_file():
            raise FileNotFoundError(boxscore_path)
        boxes = {}
        with gzip.open(boxscore_path, 'rt', encoding='utf-8') as handle:
            for line in handle:
                row = json.loads(line)
                if row.get('type') == 'manifest':
                    continue
                row = dict(row)
                row.pop('type', None)
                seed = int(row['seed'])
                if seed in boxes:
                    raise ValueError(f'{boxscore_path}: duplicate boxscore seed {seed}')
                boxes[seed] = row
        artifact_hashes[seed_path.name] = sha256(seed_path)
        artifact_hashes[boxscore_path.name] = sha256(boxscore_path)

        with gzip.open(seed_path, 'rt', encoding='utf-8') as handle:
            first = json.loads(next(handle))
            if 'header' not in first:
                raise ValueError(f'{seed_path}: missing seed-ledger header')
            for line in handle:
                record = json.loads(line)
                seed = int(record['seed'])
                if seed in all_seeds:
                    raise ValueError(f'duplicate seed across archived workers: {seed}')
                all_seeds.add(seed)
                outcome = record['outcome']
                box = outcome['boxscore']
                comparable = boxes.get(seed)
                if comparable is None or box != comparable:
                    raise ValueError(f'seed {seed}: ledger and archived boxscore differ or boxscore is missing')
                boxscore_count += 1
                status = outcome.get('status')
                game_status_counts[status] += 1
                home_points, away_points = int(outcome['home_points']), int(outcome['away_points'])
                if status == 'complete_overtime' and home_points == away_points:
                    completed_overtime_tie_seeds.append(seed)
                if status in ('complete_regulation', 'complete_overtime') and home_points != away_points:
                    decisive_game_count += 1
                if status == 'complete_regulation' and home_points == away_points:
                    regulation_tie_completed_seeds.append(seed)
                for player in box['players']:
                    starter_values[str(player.get('starter'))] += 1
                    qb = qbs.get(player.get('stable_player_id'))
                    if qb and qb['depth_rank'] > 1:
                        rushing_attempts = int(player['rushing']['att'])
                        targets = int(player['receiving']['tgt'])
                        if rushing_attempts > 0 or targets > 0:
                            backup_qb_participation.append({
                                'seed': seed, 'player_id': player['stable_player_id'],
                                'player_name': player['name'], 'team': qb['team'],
                                'depth_rank': qb['depth_rank'],
                                'rush_attempts': rushing_attempts,
                                'rushing_yards': int(player['rushing']['yds']),
                                'targets': targets,
                                'receptions': int(player['receiving']['rec']),
                                'receiving_yards': int(player['receiving']['yds']),
                            })

                if outcome.get('status') not in ('complete_regulation', 'complete_overtime'):
                    continue
                team_rows = {item['team']: item['stats'] for item in box['teams']}
                player_by_name = {item['name']: item for item in box['players']}
                pc = outcome.get('playcall') or {}
                for case in CASES:
                    player = player_by_name.get(case['player'])
                    if player is None:
                        continue
                    value = _stat(player, case['metric'])
                    if value < case['threshold']:
                        continue
                    team = player['team']
                    stats = team_rows[team]
                    denominator = int(stats['rush_attempts'] if case['role'] == 'carry' else stats['targets'])
                    opportunities = int(player['rushing']['att'] if case['role'] == 'carry'
                                        else player['receiving']['tgt'])
                    prior_n = prior_counts[case['role']][(team, player['stable_player_id'])]
                    prior_team_n = prior_totals[case['role']][team]
                    prior_share = prior_n / prior_team_n if prior_team_n else 0.0
                    share_key = (seed, team, case['role'])
                    if share_key not in game_share_cache:
                        population_ids = share_populations[(team, case['role'])]
                        game_share_cache[share_key] = share_distributions.game_shares(
                            share_table, team, str(seed), population_ids, case['role'],
                            snapshot['snapshot_sha256'])
                    sampled_shares = game_share_cache[share_key]
                    same_position_ids = [gsis_id for gsis_id in share_populations[(team, case['role'])]
                                         if players_by_team[team][gsis_id].get('pos_abb') == player['position']]
                    position_share_total = sum(sampled_shares.get(gsis_id, 0.0)
                                               for gsis_id in same_position_ids)
                    sampled_position_share = (sampled_shares.get(player['stable_player_id'], 0.0)
                                              / position_share_total if position_share_total else None)
                    base_position_share_total = sum(share_table['base'][case['role']].get((team, gsis_id), 0.0)
                                                    for gsis_id in same_position_ids)
                    share_vector = {
                        gsis_id: {
                            'player_name': players_by_team[team][gsis_id].get('player_name'),
                            'position': players_by_team[team][gsis_id].get('pos_abb'),
                            'base_share': share_table['base'][case['role']].get((team, gsis_id), 0.0),
                            'floor_applied': share_table['base'][case['role']].get((team, gsis_id), 0.0) < FLOOR,
                            'sampled_game_share': sampled_shares.get(gsis_id),
                        }
                        for gsis_id in share_populations[(team, case['role'])]
                    }
                    line = {
                        'finding_id': case['id'],
                        'classification': ('RECORD_EXCEEDANCE' if value > case['record_boundary']
                                           else 'WORKLOAD_ALERT'),
                        'player_name': player['name'], 'player_id': player['stable_player_id'],
                        'team': team, 'position': player['position'], 'roster_eligible': player['roster_eligible'],
                        'exported_starter': player.get('starter'), 'seed': seed,
                        'game_status': outcome['status'],
                        'overtime': outcome['status'] == 'complete_overtime',
                        'home_points': int(outcome['home_points']), 'away_points': int(outcome['away_points']),
                        'team_plays': int(stats['plays']), 'team_pass_attempts': int(stats['pass_attempts']),
                        'team_sacks_taken': int(stats['sacks_taken']),
                        'team_dropbacks': int(stats['pass_attempts']) + int(stats['sacks_taken']),
                        'team_rush_decisions': int(stats['rush_attempts']),
                        'team_targets': int(stats['targets']), 'metric': case['metric'], 'value': value,
                        'threshold': case['threshold'], 'record_boundary': case['record_boundary'],
                        'player_line_json': json.dumps(_player_line(player), sort_keys=True, separators=(',', ':')),
                        'realized_player_share': opportunities / denominator if denominator else None,
                        'prior_2025_role_opportunities': prior_n,
                        'prior_2025_team_role_opportunities': prior_team_n,
                        'prior_2025_base_share': prior_share,
                        'prior_2025_within_position_share': (prior_share / base_position_share_total
                                                              if base_position_share_total else None),
                        'share_floor_applied': prior_share < FLOOR,
                        'share_weight_floor': FLOOR,
                        'sampled_game_share': sampled_shares.get(player['stable_player_id']),
                        'sampled_share_within_position': sampled_position_share,
                        'sampled_game_share_vector_json': json.dumps(share_vector, sort_keys=True,
                                                                     separators=(',', ':')),
                        'sampled_share_position_population_n': len(same_position_ids),
                        'sampled_game_share_population_n': len(share_populations[(team, case['role'])]),
                        'playcall_run_decisions': pc.get('run'),
                        'playcall_dropbacks': pc.get('dropback'),
                        'playcall_qb_scrambles': pc.get('qb_scramble'),
                        'aggregate_fallback_events_json': json.dumps(pc.get('fallback_events', {}),
                                                                     sort_keys=True, separators=(',', ':')),
                        'participant_selection_trace_archived': False,
                        'sampled_game_share_vector_archived': False,
                        'sampled_game_share_reconstructed': True,
                    }
                    findings.append(line)

    expected = set(range(1, 10001))
    if all_seeds != expected:
        raise ValueError(f'seed coverage mismatch: {len(all_seeds)} unique, '
                         f'missing={sorted(expected - all_seeds)[:10]}')
    if game_status_counts != Counter({'complete_regulation': 9479, 'complete_overtime': 515, 'blocked': 6}):
        raise ValueError(f'published status counts changed: {dict(game_status_counts)}')
    if len(completed_overtime_tie_seeds) != 11:
        raise ValueError(f'published final overtime tie count changed: {len(completed_overtime_tie_seeds)}')
    if decisive_game_count != 9983:
        raise ValueError(f'published decisive-game winner denominator changed: {decisive_game_count}')
    if regulation_tie_completed_seeds:
        raise ValueError('a game tied at the end of regulation was incorrectly marked complete in regulation')
    counts = Counter(row['finding_id'] for row in findings)
    for case_id, count in EXPECTED_COUNTS.items():
        if counts[case_id] != count:
            raise ValueError(f'{case_id}: observed {counts[case_id]}, expected {count} from published report')
    for case_id, maximum in EXPECTED_MAXIMA.items():
        observed_maximum = max((int(row['value']) for row in findings if row['finding_id'] == case_id), default=0)
        if observed_maximum != maximum:
            raise ValueError(f'{case_id}: observed maximum {observed_maximum}, expected {maximum} from published report')

    fields = tuple(findings[0]) if findings else ('finding_id', 'seed')
    with (out_dir / 'per_seed_player_tail_findings.csv').open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(sorted(findings, key=lambda row: (row['finding_id'], row['seed'])))

    summary = {
        'schema': 'lp.nfl.slc-player-tail-audit.v1',
        'game_id': '2026_08_ARI_DAL',
        'artifact_seed_count': len(all_seeds), 'boxscore_count': boxscore_count,
        'completed_game_denominator': 9994,
        'completed_game_status_counts': dict(game_status_counts),
        'completed_overtime_tie_count': len(completed_overtime_tie_seeds),
        'completed_overtime_tie_seeds': sorted(completed_overtime_tie_seeds),
        'decisive_game_winner_denominator': decisive_game_count,
        'regulation_ties_marked_complete': regulation_tie_completed_seeds,
        'source_run_unchanged': True,
        'source_artifact_sha256': artifact_hashes,
        'source_data_sha256': {'pbp_2025.csv.gz': actual_pbp_hash,
                               'player_workload_reference_manifest.json': sha256(benchmark_manifest_path)},
        'source_database_sha256': share_db_hash,
        'share_database_validation': share_db_validation,
        'record_boundaries': {'rush_attempts': 45, 'targets': 28, 'receptions': 21,
                              'rushing_yards': 296},
        'findings': {},
    }
    # Build the concise findings from the exact per-seed rows after the full stream checks.
    summary['findings'] = {}
    for case in CASES:
        rows = [row for row in findings if row['finding_id'] == case['id']]
        summary['findings'][case['id']] = {
            'player': case['player'], 'metric': case['metric'], 'threshold': case['threshold'],
            'record_boundary': case['record_boundary'], 'count': len(rows),
            'frequency_completed_games': len(rows) / 9994,
            'maximum': max((int(row['value']) for row in rows), default=0),
            'seeds': [int(row['seed']) for row in rows],
        }
    rushing_backup_qbs = [row for row in backup_qb_participation if row['rush_attempts'] > 0]
    receiving_backup_qbs = [row for row in backup_qb_participation if row['targets'] > 0]
    backup_qb_by_player = {}
    for row in backup_qb_participation:
        player = backup_qb_by_player.setdefault(row['player_id'], {
            'player_name': row['player_name'], 'team': row['team'], 'depth_rank': row['depth_rank'],
            'rushing_player_games': 0, 'rush_attempts': 0, 'rushing_yards': 0,
            'receiving_player_games': 0, 'targets': 0, 'receptions': 0, 'receiving_yards': 0,
        })
        if row['rush_attempts'] > 0:
            player['rushing_player_games'] += 1
        if row['targets'] > 0:
            player['receiving_player_games'] += 1
        for metric in ('rush_attempts', 'rushing_yards', 'targets', 'receptions', 'receiving_yards'):
            player[metric] += row[metric]
    backup_qb_csv = out_dir / 'backup_qb_participation.csv'
    backup_fields = ('seed', 'player_id', 'player_name', 'team', 'depth_rank', 'rush_attempts',
                     'rushing_yards', 'targets', 'receptions', 'receiving_yards')
    with backup_qb_csv.open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=backup_fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(sorted(backup_qb_participation, key=lambda row: (row['seed'], row['player_id'])))
    summary['backup_qb_audit'] = {
        'qb_depth_ranks_from_frozen_snapshot': qbs,
        'backup_qb_rushing_player_games': len(rushing_backup_qbs),
        'backup_qb_rushing_unique_game_count': len({row['seed'] for row in rushing_backup_qbs}),
        'backup_qb_rushing_attempts': sum(row['rush_attempts'] for row in rushing_backup_qbs),
        'backup_qb_rushing_yards': sum(row['rushing_yards'] for row in rushing_backup_qbs),
        'backup_qb_receiving_player_games': len(receiving_backup_qbs),
        'backup_qb_receiving_unique_game_count': len({row['seed'] for row in receiving_backup_qbs}),
        'backup_qb_targets': sum(row['targets'] for row in receiving_backup_qbs),
        'backup_qb_by_player': backup_qb_by_player,
        'backup_qb_participation_csv': backup_qb_csv.name,
        'run_selection_mechanism': ('producer allowed all injury-eligible QBs into the ordinary carry share pool; '
                                    'no in-game QB substitution event was recorded'),
        'target_selection_mechanism': ('producer had an explicit backup-QB trick-target branch at '
                                       'QB_RECEIVER_RATE = 17/33802 per eligible dropback'),
        'starter_field_counts_across_boxscore_player_rows': dict(starter_values),
    }
    summary['traceability'] = {
        'seed_ledgers_and_boxscores_reconcile': True,
        'seed_specific_player_selection_trace_archived': False,
        'sampled_game_share_vector_archived': False,
        'per_seed_playcall_counters_archived': True,
        'per_seed_fallback_events_archived': True,
        'share_fallback_reconstructed_from_2025_player_opportunity_support': True,
        'share_fallback_scope': ('base-share floor status and exact game-level Dirichlet draw reconstructed; '
                                 'per-play participant choices remain absent'),
    }
    summary['traceability']['sampled_game_share_vector_reconstructed'] = True
    summary['traceability']['share_reconstruction_basis'] = (
        'exact deterministic game_shares draw using the frozen snapshot hash, seed, team, role, '
        'pinned 2025 PBP base shares, and archived fit concentrations; no game simulation replay')
    summary['share_model'] = {
        'model_version': share_model['model_version'],
        'source_season': share_model['source_season'], 'cutoff_season': share_model['cutoff_season'],
        'concentration': share_model['concentration'],
        'eligible_population_sizes': {f'{team}:{role}': len(ids)
                                      for (team, role), ids in sorted(share_populations.items())},
        'share_distributions_source_sha256': sha256(Path(__file__).with_name('share_distributions.py')),
    }
    (out_dir / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n',
                                          encoding='utf-8')
    summary['output_sha256'] = {path.name: sha256(path) for path in sorted(out_dir.iterdir())}
    (out_dir / 'manifest.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n',
                                          encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--share-db', type=Path,
                        help='SQLite used to validate reconstructed ARI/DAL 2025 player opportunity counts')
    args = parser.parse_args()
    summary = audit(args.artifact_dir, args.data_dir, args.out_dir, share_db=args.share_db)
    for case_id, finding in summary['findings'].items():
        print(f"{case_id}: {finding['count']} cases, max {finding['maximum']}")


if __name__ == '__main__':
    main()
