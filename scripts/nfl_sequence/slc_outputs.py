"""Versioned per-seed SLC box scores and distribution summaries."""
from __future__ import annotations

import math


BOX_SCHEMA = 'lp-nfl-slc-boxscore-1'
TEAM_FIELDS = {
    'points': 'points', 'touchdowns': 'touchdowns', 'offensive_touchdowns': 'offensive_touchdowns',
    'observed_overtime_touchdowns': 'observed_overtime_touchdowns',
    'drives': 'drives', 'possession_seconds': 'possession_seconds', 'plays': 'plays',
    'rush_attempts': 'rush_att', 'rushing_yards': 'rush_yds', 'pass_attempts': 'pass_att',
    'completions': 'pass_comp', 'passing_yards': 'pass_yds', 'interceptions': 'interceptions',
    'targets': 'pass_tgt', 'sacks_taken': 'sacks_taken', 'sack_yards': 'sack_yds', 'punts': 'punts',
    'field_goal_attempts': 'fg_att', 'field_goals_made': 'fg_made', 'turnovers': 'turnovers',
    'fumbles_lost': 'fumbles_lost', 'turnovers_on_downs': 'turnovers_on_downs',
}
PLAYER_FIELDS = {
    'passing': ('att', 'comp', 'yds', 'td', 'int', 'sacked', 'sack_yds'),
    'rushing': ('att', 'yds', 'td'),
    'receiving': ('tgt', 'rec', 'yds', 'td'),
    'miscellaneous': ('fumbles_lost',),
}


def _int_or_zero(value):
    return 0 if value is None else int(value)


def _roster_index(snapshot):
    by_id = {}
    for side in ('home', 'away'):
        roster = snapshot['rosters'][side]
        for player in roster.get('players', []):
            stable_id = player.get('gsis_id')
            if not stable_id:
                continue
            entry = {
                'stable_player_id': str(stable_id),
                'identity_namespace': 'nfl_gsis_id',
                'lp_player_id': player.get('player_id'),
                'name': player.get('player_name'),
                'team': roster['team'],
                'position': player.get('pos_abb'),
                'roster_eligible': bool(player.get('roster_eligible', True)),
                'starter': bool(player.get('starter', False)),
            }
            previous = by_id.get(str(stable_id))
            if previous is not None and (previous['team'] != entry['team'] or previous['name'] != entry['name']):
                raise ValueError(f"snapshot has conflicting roster identity for GSIS {stable_id}")
            by_id[str(stable_id)] = entry
    return by_id


def _red_zone_diagnostics(record):
    by_side = {}
    for drive in record.get('drives', []):
        side = drive.get('offense_team')
        item = by_side.setdefault(side, {'red_zone_trips': 0, 'red_zone_plays': 0,
                                         'red_zone_touchdowns': 0, 'red_zone_field_goals': 0})
        in_zone = [play for play in drive.get('plays', [])
                   if play.get('state_before', {}).get('yardline_100') is not None
                   and int(play['state_before']['yardline_100']) <= 20]
        if not in_zone:
            continue
        item['red_zone_trips'] += 1
        item['red_zone_plays'] += len(in_zone)
        if drive.get('terminal') == 'touchdown':
            item['red_zone_touchdowns'] += 1
        if drive.get('field_goal_made') is not None:
            item['red_zone_field_goals'] += 1
    return by_side


def build_boxscore(seed, outcome, record, snapshot, profile_manifest, archive_validation=None):
    """Create one self-contained game record. SLC participant IDs must belong to the frozen roster."""
    schedule = snapshot['schedule']
    profile = profile_manifest['profile']
    # Both comparison arms use a frozen pregame snapshot. S0's legacy participant
    # adapter also samples from that roster, so its lines can and must be checked
    # against the same stable identities and zero-filled roster population.
    strict_roster = True
    stats = (record or {}).get('stats') or {}
    team_stats = stats.get('team') or {}
    side_metadata = {'A': ('home', schedule['home_team']), 'B': ('away', schedule['away_team'])}
    teams = []
    red_zone = _red_zone_diagnostics(record or {})
    for side, (home_away, team_code) in side_metadata.items():
        source = team_stats.get(side, {})
        values = {field: _int_or_zero(source.get(key)) for field, key in TEAM_FIELDS.items()}
        values['points'] = (record or {}).get('points', {}).get(side)
        values['red_zone'] = red_zone.get(side, {'red_zone_trips': 0, 'red_zone_plays': 0,
                                                  'red_zone_touchdowns': 0, 'red_zone_field_goals': 0})
        teams.append({'side': side, 'home_away': home_away, 'team': team_code, 'stats': values})

    roster = _roster_index(snapshot)
    actual = {}
    attribution = stats.get('player_attribution')
    for player in stats.get('player', []):
        key = str(player.get('player_id'))
        if key in actual:
            raise ValueError(f'seed {seed}: duplicate player box-score identity {key}')
        meta = roster.get(key)
        if strict_roster and meta is None:
            raise ValueError(f'seed {seed}: SLC participant {key} is not present on the frozen roster')
        line = {
            **(meta or {}),
            'stable_player_id': str(meta['stable_player_id']) if meta else key,
            'identity_namespace': 'nfl_gsis_id' if meta else 'source_participant_id',
            'name': player.get('player_name', player.get('name', (meta or {}).get('name'))),
            'team': player.get('player_team', player.get('team', (meta or {}).get('team'))),
            'position': player.get('player_position', player.get('position', (meta or {}).get('position'))),
            'side': player.get('player_side'),
            'roster_eligible': bool((meta or {}).get('roster_eligible', False)),
            'attribution': player.get('attribution', attribution),
        }
        for category, fields in PLAYER_FIELDS.items():
            source_cat = player.get(category) or {}
            line[category] = {field: _int_or_zero(source_cat.get(field)) for field in fields}
        actual[key] = line

    if strict_roster:
        for player_id, meta in roster.items():
            if player_id in actual:
                continue
            line = {**meta, 'side': 'A' if meta['team'] == schedule['home_team'] else 'B',
                    'attribution': attribution or 'pre_event_selection'}
            for category, fields in PLAYER_FIELDS.items():
                line[category] = {field: 0 for field in fields}
            actual[player_id] = line

    boxscore = {
        'schema': BOX_SCHEMA,
        'game_id': schedule['game_id'],
        'seed': int(seed),
        'model_id': profile_manifest['model_id'],
        'configuration_hash': profile_manifest['configuration_hash'],
        'source_cutoff': snapshot['as_of'],
        'evaluation_class': profile_manifest.get('evaluation_class', 'prospective'),
        'historical_classification': (archive_validation or {}).get('classification'),
        'prospective': bool((archive_validation or {}).get('prospective', True)),
        'home_team': schedule['home_team'], 'away_team': schedule['away_team'],
        'status': _box_status(outcome),
        'exact_layer_configuration': profile_manifest['enabled_layers'],
        'player_attribution_mode': attribution or 'unavailable',
        'reconciliation': None,
        'teams': teams,
        'players': [actual[key] for key in sorted(actual)],
    }
    boxscore['reconciliation'] = reconcile_boxscore(boxscore, strict=False)
    return boxscore


def _box_status(outcome):
    if outcome.get('valid_full_game'):
        return 'valid_complete'
    if outcome.get('tied_at_regulation_end'):
        return 'regulation_tie'
    if outcome.get('status') in ('simulation_error', 'validation_error'):
        return 'error'
    if outcome.get('blocker'):
        return 'blocked'
    return 'incomplete'


def reconcile_boxscore(boxscore, *, strict):
    results = []
    for team in boxscore['teams']:
        side, team_stats = team['side'], team['stats']
        players = [p for p in boxscore['players'] if p.get('side') == side]
        sums = {
            'rush_attempts': sum(p['rushing']['att'] for p in players),
            'rushing_yards': sum(p['rushing']['yds'] for p in players),
            'pass_attempts': sum(p['passing']['att'] for p in players),
            'completions': sum(p['passing']['comp'] for p in players),
            'passing_yards': sum(p['passing']['yds'] for p in players),
            'interceptions': sum(p['passing']['int'] for p in players),
            'sacks_taken': sum(p['passing']['sacked'] for p in players),
            'sack_yards': sum(p['passing']['sack_yds'] for p in players),
            'targets': sum(p['receiving']['tgt'] for p in players),
            'receptions': sum(p['receiving']['rec'] for p in players),
            'fumbles_lost': sum(p['miscellaneous']['fumbles_lost'] for p in players),
        }
        checks = {'rush_attempts': 'rush_attempts', 'rushing_yards': 'rushing_yards',
                  'pass_attempts': 'pass_attempts', 'completions': 'completions',
                  'passing_yards': 'passing_yards', 'interceptions': 'interceptions',
                  'sacks_taken': 'sacks_taken', 'sack_yards': 'sack_yards', 'targets': 'targets',
                  'fumbles_lost': 'fumbles_lost'}
        mismatches = {key: {'players': sums[key], 'team': team_stats[stat]}
                      for key, stat in checks.items() if sums[key] != team_stats[stat]}
        if sums['receptions'] != team_stats['completions']:
            mismatches['receptions'] = {'players': sums['receptions'], 'team': team_stats['completions']}
        player_offensive_tds = (sum(p['passing']['td'] + p['rushing']['td'] for p in players))
        unassigned_offensive_tds = team_stats['observed_overtime_touchdowns']
        reconciled_team_offensive_tds = team_stats['offensive_touchdowns'] - unassigned_offensive_tds
        if player_offensive_tds != reconciled_team_offensive_tds:
            mismatches['offensive_touchdowns'] = {
                'players': player_offensive_tds, 'team': team_stats['offensive_touchdowns'],
                'unassigned_observed_overtime': unassigned_offensive_tds,
                'reconciled_team_total': reconciled_team_offensive_tds}
        results.append({'team': team['team'], 'side': side, 'player_sums': sums,
                        'team_values': {key: team_stats[key] for key in checks.values()},
                        'matches': not mismatches, 'mismatches': mismatches})
    all_match = all(item['matches'] for item in results)
    return {'status': 'passed' if all_match else 'failed', 'strict': strict, 'teams': results}


def _quantiles(values):
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return {key: None for key in ('p5', 'p10', 'p25', 'p50', 'p75', 'p90', 'p95')}
    def at(p):
        index = (len(ordered) - 1) * p
        low = math.floor(index)
        high = math.ceil(index)
        return ordered[low] + (ordered[high] - ordered[low]) * (index - low)
    return {f'p{int(p * 100)}': at(p) for p in (.05, .10, .25, .50, .75, .90, .95)}


def _distribution(values):
    if not values:
        return {'sample_count': 0, 'mean': None, 'standard_deviation': None, 'median': None,
                'probability_zero': None, 'quantiles': _quantiles([]), 'histogram': {}}
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    histogram = {}
    for value in values:
        key = str(value)
        histogram[key] = histogram.get(key, 0) + 1
    return {'sample_count': len(values), 'mean': mean, 'standard_deviation': math.sqrt(variance),
            'median': _quantiles(values)['p50'], 'probability_zero': sum(value == 0 for value in values) / len(values),
            'quantiles': _quantiles(values), 'histogram': dict(sorted(histogram.items(), key=lambda x: float(x[0])))}


def aggregate_boxscores(boxscores, requested_games=None):
    """Aggregate only unique valid complete seeds; retain explicit coverage and failure counts."""
    latest = {}
    duplicates = 0
    for box in boxscores:
        seed = int(box['seed'])
        if seed in latest:
            duplicates += 1
        latest[seed] = box
    unique = list(latest.values())
    valid = [box for box in unique if box['status'] == 'valid_complete']
    team_stats = {}
    for team in sorted({line['team'] for box in valid for line in box['teams']}):
        lines = [line for box in valid for line in box['teams'] if line['team'] == team]
        fields = sorted({field for line in lines for field, value in line['stats'].items()
                         if isinstance(value, (int, float)) and not isinstance(value, bool)})
        team_stats[team] = {field: _distribution([line['stats'][field] for line in lines]) for field in fields}
        team_stats[team]['scoring_frequency'] = sum(line['stats']['points'] > 0 for line in lines) / len(lines)
        red_fields = ('red_zone_trips', 'red_zone_plays', 'red_zone_touchdowns', 'red_zone_field_goals')
        team_stats[team]['red_zone'] = {
            field: _distribution([line['stats']['red_zone'].get(field, 0) for line in lines]) for field in red_fields}
    player_metadata = {}
    for box in valid:
        for player in box['players']:
            key = (player['team'], player['stable_player_id'])
            player_metadata.setdefault(key, {field: player.get(field) for field in
                                             ('stable_player_id', 'name', 'team', 'position',
                                              'roster_eligible', 'starter')})
    player_values = {key: {'metadata': metadata, 'values': {}} for key, metadata in player_metadata.items()}
    for box in valid:
        lines = {(player['team'], player['stable_player_id']): player for player in box['players']}
        for key, entry in player_values.items():
            player = lines.get(key)
            for category, fields in PLAYER_FIELDS.items():
                for field in fields:
                    value = player[category][field] if player else 0
                    entry['values'].setdefault(f'{category}.{field}', []).append(value)
    players = []
    for (_team, _player_id), entry in sorted(player_values.items()):
        players.append({**entry['metadata'], 'statistics': {
            key: _distribution(values) for key, values in sorted(entry['values'].items())}})

    game_values = {
        'home_points': [box['teams'][0]['stats']['points'] for box in valid],
        'away_points': [box['teams'][1]['stats']['points'] for box in valid],
        'total_points': [sum(line['stats']['points'] for line in box['teams']) for box in valid],
        'home_margin': [box['teams'][0]['stats']['points'] - box['teams'][1]['stats']['points'] for box in valid],
    }
    winners = {'home': 0, 'away': 0, 'tie': 0}
    scoring = {'home_nonzero': 0, 'away_nonzero': 0, 'both_nonzero': 0, 'neither_nonzero': 0}
    for box in valid:
        home, away = (line['stats']['points'] for line in box['teams'])
        winners['home' if home > away else 'away' if away > home else 'tie'] += 1
        scoring['home_nonzero'] += int(home > 0)
        scoring['away_nonzero'] += int(away > 0)
        scoring['both_nonzero'] += int(home > 0 and away > 0)
        scoring['neither_nonzero'] += int(home == 0 and away == 0)
    n_valid = len(valid)
    return {
        'schema': 'lp-nfl-slc-distribution-summary-1',
        'requested_games': requested_games if requested_games is not None else len(unique),
        'unique_seeds': len(unique), 'duplicate_ledger_rows': duplicates,
        'valid_complete_games': n_valid, 'coverage': n_valid / requested_games if requested_games else None,
        'status_counts': {status: sum(box['status'] == status for box in unique)
                          for status in ('valid_complete', 'regulation_tie', 'incomplete', 'blocked', 'error')},
        'game': {key: _distribution(values) for key, values in game_values.items()},
        'winner_probability': {key: count / n_valid if n_valid else None for key, count in winners.items()},
        'scoring_frequency': {key: count / n_valid if n_valid else None for key, count in scoring.items()},
        'teams': team_stats, 'players': players,
    }
