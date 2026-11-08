"""Research-only isolated adaptive workload shares from frozen, week-bounded counts."""
import copy
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def apply(table, input_path, expected_sha256, season, week, teams, concentrations=None, n0=4.0):
    raw = Path(input_path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise ValueError('frozen workload input hash mismatch')
    source = json.loads(gzip.decompress(raw))
    if source.get('schema') != 'lp.workload.evaluation-inputs.v1':
        raise ValueError('unsupported frozen workload input schema')
    if n0 <= 0 or week < 1:
        raise ValueError('invalid workload adaptation cutoff or prior weight')
    if int(table['season']) != season - 1:
        raise ValueError('historical workload season differs from target')
    result = copy.deepcopy(table)
    evidence = {}
    for role in ('carry', 'receive'):
        role_games = source['games'].get(str(season), {}).get(role, [])
        for team in sorted(teams):
            earlier = [g for g in role_games if g['team'] == team and int(g['week']) < week]
            if len({g['game_id'] for g in earlier}) != len(earlier):
                raise ValueError('duplicate earlier team game')
            current = defaultdict(int)
            for game in earlier:
                for player, count in game['counts'].items():
                    current[player] += count
            total = sum(current.values())
            prior = {player: weight for (tm, player), weight in result['base'][role].items() if tm == team}
            if not prior:
                raise ValueError(f'no historical {role} base for {team}')
            weight = n0 / (n0 + len(earlier))
            for player in set(prior) | set(current):
                result['base'][role][(team, player)] = (weight * prior.get(player, 0.0)
                    + (1 - weight) * current.get(player, 0) / total if total else prior.get(player, 0.0))
            evidence[f'{team}:{role}'] = {'earlier_games': sorted(g['game_id'] for g in earlier),
                                         'earlier_opportunities': total, 'historical_weight': weight}
        if concentrations is not None:
            for group, phi in concentrations.get(role, {}).items():
                if group not in result['phi'][role] or not isinstance(phi, (int, float)) or phi <= 0:
                    raise ValueError(f'unsupported concentration {role}:{group}')
                result['phi'][role][group] = float(phi)
    return result, {'input_sha256': digest, 'target_season': season, 'target_week': week,
                    'n0': n0, 'evidence': evidence, 'concentrations': concentrations,
                    'cutoff_safety': 'week_bounded_source_acquisition_unverified'}
