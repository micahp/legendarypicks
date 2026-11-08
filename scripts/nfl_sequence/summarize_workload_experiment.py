"""Summarize paired workload ledgers with independently verified per-seed streams."""
import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

import paired_seed_ablation as paired


def read(path):
    with Path(path).open() as handle:
        header = json.loads(next(handle))['header']
        rows = [json.loads(line) for line in handle if line.strip()]
    seeds = {}
    for row in rows:
        seed = row['seed']
        if seed in seeds:
            raise ValueError(f'duplicate seed {seed} in {path}')
        seeds[seed] = row['outcome']
    return header, seeds


def distribution(values):
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    return {'n': len(values), 'mean': float(np.mean(arr)), 'median': float(np.median(arr)),
            'p10': float(np.quantile(arr, .1)), 'p90': float(np.quantile(arr, .9))}


def summarize(paths):
    arms = {arm: read(path) for arm, path in paths.items()}
    root, _ = paired.validate_v2_header(arms['C'][0])
    control_header = arms['C'][0]
    seeds = set(arms['C'][1])
    if not seeds:
        raise ValueError('no control seeds')
    unverified_streams = []
    for arm, (header, rows) in arms.items():
        if set(rows) != seeds:
            raise ValueError(f'{arm} seed IDs differ from control')
        if header['rng_protocol']['stream_root_sha256'] != root:
            raise ValueError(f'{arm} RNG root differs')
        if arm != 'C':
            baseline = header.get('paired_workload_baseline') or {}
            if baseline.get('baseline_header_sha256') != paired.rng_protocol.canonical_sha256(control_header):
                raise ValueError(f'{arm} did not bind to this control header')
        for seed, outcome in rows.items():
            try:
                paired.validate_v2_streams(outcome, root, seed, arm)
            except paired.PairingError:
                if outcome.get('valid_full_game'):
                    raise
                unverified_streams.append({'arm': arm, 'seed': seed})
    valid = [seed for seed in sorted(seeds) if all(
        rows[seed].get('valid_full_game') is True and
        (rows[seed].get('boxscore', {}).get('reconciliation') or {}).get('status') == 'passed'
        for _, rows in arms.values())]
    out = {'root_sha256': root, 'source_snapshot_sha256': control_header.get('source_snapshot_sha256'),
           'source_commit': control_header.get('source_commit'),
           'pairing_identity': control_header.get('pairing_identity'), 'requested_seeds': len(seeds), 'paired_valid': len(valid),
           'excluded_seeds': sorted(seeds - set(valid)), 'unverified_streams': unverified_streams,
           'arms': {}, 'paired_player_deltas': {}}
    player_values = {}
    for arm, (header, rows) in arms.items():
        selection_groups = collections.Counter()
        selected = collections.Counter()
        candidate_presence = collections.Counter()
        candidate_weights = collections.defaultdict(list)
        population_weights = collections.defaultdict(list)
        players = collections.defaultdict(lambda: collections.defaultdict(list))
        eligibility = collections.defaultdict(set)
        statuses = collections.Counter()
        for seed in sorted(rows):
            outcome = rows[seed]
            statuses[outcome.get('status')] += 1
            if seed not in valid:
                continue
            for entry in (outcome.get('playcall') or {}).get('participant_selections', []):
                group = ','.join(entry.get('selected_positions') or [])
                selection_groups[(entry['team'], entry['role'], group)] += 1
                selected[(entry['team'], entry['role'], entry['selected'])] += 1
                for player in entry['candidates']:
                    key = (entry['team'], entry['role'], player)
                    candidate_presence[key] += 1
                    candidate_weights[key].append(entry['candidate_weights'][player])
                for player, weight in entry['population_weights'].items():
                    population_weights[(entry['team'], entry['role'], player)].append(weight)
            team_totals = {}
            for team_row in outcome['boxscore']['teams']:
                team_stats = team_row.get('stats') or {}
                team_totals[team_row['team']] = (team_stats.get('rush_attempts'), team_stats.get('pass_attempts'))
            for player in outcome['boxscore']['players']:
                key = (player['team'], player['stable_player_id'], player['name'])
                eligibility[key].add(str(player.get('roster_eligible')))
                players[key]['carries'].append(player['rushing']['att'])
                players[key]['targets'].append(player['receiving']['tgt'])
                rush_total, pass_total = team_totals.get(player['team'], (None, None))
                if rush_total:
                    players[key]['carry_share'].append(player['rushing']['att'] / rush_total)
                if pass_total:
                    players[key]['target_share'].append(player['receiving']['tgt'] / pass_total)
                if player.get('snaps') is not None:
                    players[key]['modeled_snaps'].append(player['snaps'])
        player_values[arm] = players
        out['arms'][arm] = {'status_counts': dict(statuses),
            'ledger_sha256': hashlib.sha256(Path(paths[arm]).read_bytes()).hexdigest(),
            'workload_identity': header.get('player_share_model_manifest'),
            'group_selections': [{'team': t, 'role': r, 'positions': p, 'decisions': n}
                                 for (t, r, p), n in sorted(selection_groups.items())],
            'players': [{'team': t, 'id': p, 'name': name,
                         **{metric: distribution(metrics.get(metric, [])) for metric in
                            ('carries', 'targets', 'modeled_snaps', 'carry_share', 'target_share')},
                         'roster_eligibility_values': sorted(eligibility[(t, p, name)]),
                         'selected_by_role': {role: selected[(t, role, p)] for role in ('carry', 'receive')},
                         'candidate_by_role': {role: candidate_presence[(t, role, p)] for role in ('carry', 'receive')},
                         'post_lineup_weight_by_role': {role: distribution(candidate_weights[(t, role, p)])
                                                        for role in ('carry', 'receive')},
                         'pre_lineup_weight_by_role': {role: distribution(population_weights[(t, role, p)])
                                                       for role in ('carry', 'receive')}}
                        for (t, p, name), metrics in sorted(players.items())]}
    for arm in ('D1', 'D2'):
        deltas = []
        for key in sorted(set(player_values['C']) & set(player_values[arm])):
            row = {'team': key[0], 'id': key[1], 'name': key[2]}
            for metric in ('carries', 'targets', 'modeled_snaps', 'carry_share', 'target_share'):
                c = player_values['C'][key].get(metric, [])
                d = player_values[arm][key].get(metric, [])
                row[metric] = distribution([y-x for x, y in zip(c, d)]) if len(c) == len(d) else None
            deltas.append(row)
        out['paired_player_deltas'][arm] = deltas
    return out


def main():
    ap = argparse.ArgumentParser()
    for arm in ('C', 'D1', 'D2'):
        ap.add_argument('--' + arm.lower(), required=True)
    ap.add_argument('--observed-input', help='frozen workload inputs; observed earlier weeks only')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    result = summarize({'C': args.c, 'D1': args.d1, 'D2': args.d2})
    if args.observed_input:
        data = json.load(gzip.open(args.observed_input, 'rt'))
        observed = {}
        for role in ('carry', 'receive'):
            teams = {}
            for game in data['games']['2026'][role]:
                if game['week'] >= 9 or game['team'] not in ('ARI', 'SEA'):
                    continue
                team = teams.setdefault(game['team'], {'games': 0, 'opportunities': 0, 'players': {}})
                team['games'] += 1
                team['opportunities'] += sum(game['counts'].values())
                for player, count in game['counts'].items():
                    team['players'][player] = team['players'].get(player, 0) + count
            observed[role] = teams
        result['observed_before_week_9'] = observed
        for arm in result['arms'].values():
            for player in arm['players']:
                source = {}
                for role in ('carry', 'receive'):
                    team = observed[role].get(player['team'])
                    if team:
                        count = team['players'].get(player['id'], 0)
                        source[role] = {'team_games': team['games'], 'opportunities': count,
                                        'team_opportunities': team['opportunities'],
                                        'share': count / team['opportunities'] if team['opportunities'] else None,
                                        'opportunities_per_team_game': count / team['games'] if team['games'] else None}
                    else:
                        source[role] = None
                player['observed_prior_weeks'] = source
        result['observed_note'] = ('Prior weeks only; player missing from counts is not confirmed inactive. '
                                   'Counts are database-derived and acquisition-time provenance is unverified.')
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')

if __name__ == '__main__':
    main()
