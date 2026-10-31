"""Versioned per-seed SLC box scores and distribution summaries."""
from __future__ import annotations

import math

import football_assertions


BOX_SCHEMA = 'lp-nfl-slc-boxscore-3'
PERIODS = ('Q1', 'Q2', 'Q3', 'Q4', 'OT')
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


def _depth_chart_qb1(roster):
    injury_report = roster.get('injury_report') or {}
    statuses = {p.get('gsis_id'): p.get('report_status')
                for p in injury_report.get('players', []) if p.get('gsis_id')}
    available = []
    for player in roster.get('players', []):
        if player.get('pos_abb') != 'QB' or not player.get('roster_eligible', True):
            continue
        availability = player.get('availability') or {}
        status = statuses.get(player.get('gsis_id'))
        if status in ('Out', 'Doubtful') or availability.get('decision') in ('out', 'exclude', 'excluded'):
            continue
        try:
            rank = int(player.get('pos_rank'))
        except (TypeError, ValueError):
            continue
        if rank > 0:
            available.append((rank, str(player.get('gsis_id') or ''), player))
    if not available:
        return None
    best_rank = min(rank for rank, _, _ in available)
    leaders = [player for rank, _, player in available if rank == best_rank]
    return leaders[0].get('gsis_id') if len(leaders) == 1 else None


def _roster_index(snapshot):
    by_id = {}
    for side in ('home', 'away'):
        roster = snapshot['rosters'][side]
        qb1_id = _depth_chart_qb1(roster)
        for player in roster.get('players', []):
            stable_id = player.get('gsis_id')
            if not stable_id:
                continue
            if player.get('pos_abb') == 'QB':
                starter = (str(stable_id) == str(qb1_id)) if qb1_id is not None else None
                starter_basis = 'depth_chart_rank_and_availability' if qb1_id is not None else 'unknown'
            else:
                source_starter = player.get('starter')
                starter = bool(source_starter) if isinstance(source_starter, bool) else None
                starter_basis = 'snapshot_starter_field' if starter is not None else 'unknown'
            entry = {
                'stable_player_id': str(stable_id),
                'identity_namespace': 'nfl_gsis_id',
                'lp_player_id': player.get('player_id'),
                'name': player.get('player_name'),
                'team': roster['team'],
                'position': player.get('pos_abb'),
                'roster_eligible': bool(player.get('roster_eligible', True)),
                'starter': starter,
                'starter_basis': starter_basis,
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
                                         'red_zone_touchdowns': 0, 'red_zone_field_goals': 0,
                                         'red_zone_field_goal_attempts': 0,
                                         'red_zone_field_goals_made': 0,
                                         'red_zone_scoring_drives': 0})
        in_zone = [play for play in drive.get('plays', [])
                   if play.get('state_before', {}).get('yardline_100') is not None
                   and int(play['state_before']['yardline_100']) <= 20]
        if not in_zone:
            continue
        item['red_zone_trips'] += 1
        item['red_zone_plays'] += len(in_zone)
        offensive_touchdown = (drive.get('terminal') == 'touchdown'
                              and drive.get('touchdown_scored_by') == side)
        if offensive_touchdown:
            item['red_zone_touchdowns'] += 1
        if drive.get('field_goal_made') is not None:
            item['red_zone_field_goal_attempts'] += 1
            item['red_zone_field_goals'] += 1
            if drive['field_goal_made']:
                item['red_zone_field_goals_made'] += 1
        if offensive_touchdown or drive.get('field_goal_made') is True:
            item['red_zone_scoring_drives'] += 1
    return by_side


def _points_by_period(record):
    """Attribute points to the scoring play's period, preserving unexplained points."""
    points = {side: {period: 0 for period in PERIODS} for side in ('A', 'B')}
    complete = True
    for drive in record.get('drives', []):
        scoring = drive.get('points_scored_on_drive')
        if not isinstance(scoring, dict):
            continue
        try:
            amount = int(scoring.get('points') or 0)
        except (TypeError, ValueError):
            complete = False
            continue
        if amount == 0:
            continue
        side = scoring.get('team')
        if side not in points:
            complete = False
            continue
        plays = drive.get('plays') or []
        quarter = ((plays[-1].get('state_before') or {}).get('quarter') if plays
                   else drive.get('quarter_start'))
        label = _period_label(quarter)
        if label is None:
            complete = False
            continue
        points[side][label] += amount

    for side in ('A', 'B'):
        final_points = int((record.get('points') or {}).get(side) or 0)
        unclassified = final_points - sum(points[side].values())
        points[side]['unclassified'] = unclassified
        if unclassified != 0:
            complete = False
    return points, complete


def _period_label(value):
    try:
        quarter = int(value)
    except (TypeError, ValueError):
        return None
    if quarter == 5:
        return 'OT'
    return f'Q{quarter}' if quarter in (1, 2, 3, 4) else None


def _period_time(quarter, clock):
    """Return elapsed game seconds for a quarter/clock pair when both are known."""
    try:
        return (int(quarter) - 1) * 900 + (900 - int(clock))
    except (TypeError, ValueError):
        return None


def _play_period_seconds(play, period):
    before = play.get('state_before') or {}
    after = play.get('state_after') or {}
    start = _period_time(before.get('quarter'), before.get('clock_seconds'))
    end = _period_time(after.get('quarter'), after.get('clock_seconds'))
    try:
        quarter_number = 5 if period == 'OT' else int(period[1:])
    except (TypeError, ValueError):
        return 0
    if start is None or end is None or end < start:
        return 0
    period_start = (quarter_number - 1) * 900
    period_end = quarter_number * 900
    return max(0, min(end, period_end) - max(start, period_start))


def _quarter_by_quarter(record, snapshot):
    """Build period-level boxscore lines and drive summaries from the recorded plays."""
    import game_stats

    schedule = snapshot['schedule']
    team_by_side = {'A': schedule['home_team'], 'B': schedule['away_team']}
    roster = _roster_index(snapshot)
    points_by_side, scoring_complete = _points_by_period(record)
    points_by_team = {
        team_by_side[side]: dict(points_by_side[side]) for side in ('A', 'B')
    }
    team_stats = {team: {period: {} for period in PERIODS} for team in team_by_side.values()}
    drive_summary = {team: {period: {
        'drives_started': 0, 'drives_ended': 0, 'scoring_drives': 0,
        'points_scored': 0, 'points_allowed': 0, 'plays': 0, 'net_yards': 0,
        'turnovers': 0,
    } for period in PERIODS} for team in team_by_side.values()}
    player_stats = {period: {} for period in PERIODS}
    drive_summaries = []
    complete = scoring_complete

    for drive_index, drive in enumerate(record.get('drives', []), 1):
        side = drive.get('offense_team')
        offense_team = team_by_side.get(side)
        if offense_team is None:
            complete = False
            continue
        plays = drive.get('plays') or []
        grouped = {}
        for play in plays:
            state = play.get('state_before') or {}
            label = _period_label(state.get('quarter'))
            if label is None:
                complete = False
                continue
            grouped.setdefault(label, []).append(play)

        start_period = _period_label(drive.get('quarter_start'))
        last_state = ((plays[-1].get('state_after') or {}) if plays else {})
        end_period = _period_label(drive.get('end_quarter', last_state.get('quarter')))
        scoring = drive.get('points_scored_on_drive')
        scoring_team = team_by_side.get(scoring.get('team')) if isinstance(scoring, dict) else None
        try:
            drive_points = int(scoring.get('points') or 0) if isinstance(scoring, dict) else 0
        except (TypeError, ValueError):
            drive_points = 0
            complete = False
        scoring_period = None
        if drive_points:
            scoring_period = _period_label((plays[-1].get('state_before') or {}).get('quarter')) if plays else start_period
            if scoring_period is None:
                complete = False

        first_state = (plays[0].get('state_before') or {}) if plays else {}
        first_spot = first_state.get('yardline_100')
        end_spot = last_state.get('yardline_100')
        try:
            net_yards = sum(int((play.get('outcome') or {}).get('yards_gained') or 0) for play in plays)
        except (TypeError, ValueError):
            net_yards = 0
            complete = False
        turnovers = sum(bool((play.get('outcome') or {}).get('turnover')) for play in plays)
        summary = {
            'drive_index': drive.get('index', drive_index), 'offense_team': offense_team,
            'start_period': start_period, 'end_period': end_period, 'scoring_period': scoring_period,
            'clock_start': drive.get('clock_start'), 'end_clock': drive.get('end_clock', last_state.get('clock_seconds')),
            'start_yardline_100': first_spot, 'end_yardline_100': end_spot,
            'terminal': drive.get('terminal'), 'play_count': len(plays), 'net_yards': net_yards,
            'turnovers': turnovers, 'scoring_team': scoring_team, 'points': drive_points,
        }
        drive_summaries.append(summary)

        if start_period:
            drive_summary[offense_team][start_period]['drives_started'] += 1
        if end_period:
            drive_summary[offense_team][end_period]['drives_ended'] += 1
        if scoring_period:
            entry = drive_summary[offense_team][scoring_period]
            entry['scoring_drives'] += 1
            entry['points_scored' if scoring_team == offense_team else 'points_allowed'] += drive_points

        if not plays and end_period:
            line = team_stats[offense_team][end_period]
            if drive.get('field_goal_made') is not None:
                line['field_goal_attempts'] = line.get('field_goal_attempts', 0) + 1
                line['field_goals_made'] = line.get('field_goals_made', 0) + int(bool(drive['field_goal_made']))
            if drive.get('terminal') == 'touchdown' and scoring_team:
                scoring_line = team_stats[scoring_team][end_period]
                scoring_line['touchdowns'] = scoring_line.get('touchdowns', 0) + 1
                if scoring_team == offense_team:
                    scoring_line['offensive_touchdowns'] = scoring_line.get('offensive_touchdowns', 0) + 1
                    if drive.get('observed_overtime_drive'):
                        scoring_line['observed_overtime_touchdowns'] = (
                            scoring_line.get('observed_overtime_touchdowns', 0) + 1)

        for label, period_plays in grouped.items():
            # game_stats already defines the event-to-stat accounting. A period fragment retains only
            # plays from that period so drives spanning a boundary contribute to both periods.
            first = period_plays[0]
            last = period_plays[-1]
            first_before = first.get('state_before') or {}
            last_after = last.get('state_after') or {}
            last_is_drive_end = (last is plays[-1] and label == end_period)
            fragment = {
                'offense_team': side,
                'quarter_start': first_before.get('quarter'),
                'clock_start': first_before.get('clock_seconds'),
                'end_quarter': last_after.get('quarter', first_before.get('quarter')),
                'end_clock': last_after.get('clock_seconds', first_before.get('clock_seconds')),
                'plays': period_plays,
                'terminal': drive.get('terminal') if last_is_drive_end else 'period_segment',
                'field_goal_made': None,
            }
            calculated = game_stats.team_stats([fragment], {})
            calculated_side = calculated.get(side, {})
            line = team_stats[offense_team][label]
            line['plays'] = line.get('plays', 0) + int(calculated_side.get('plays', 0))
            for output_name, source_name in TEAM_FIELDS.items():
                if output_name in ('points', 'drives', 'possession_seconds'):
                    continue
                line[output_name] = line.get(output_name, 0) + int(calculated_side.get(source_name, 0) or 0)
            line['possession_seconds'] = line.get('possession_seconds', 0) + sum(
                _play_period_seconds(play, label) for play in period_plays)
            drive_summary[offense_team][label]['plays'] += len(period_plays)
            drive_summary[offense_team][label]['net_yards'] += sum(
                int((play.get('outcome') or {}).get('yards_gained') or 0) for play in period_plays)
            drive_summary[offense_team][label]['turnovers'] += sum(
                bool((play.get('outcome') or {}).get('turnover')) for play in period_plays)

            for player in game_stats.player_lines([fragment]):
                player_id = str(player['player_id'])
                meta = roster.get(player_id, {})
                entry = player_stats[label].setdefault(player_id, {
                    **meta,
                    'stable_player_id': player_id,
                    'name': player.get('player_name', meta.get('name')),
                    'team': player.get('player_team', meta.get('team')),
                    'position': player.get('player_position', meta.get('position')),
                    'side': player.get('player_side'),
                    'attribution': player.get('attribution'),
                    'passing': {field: 0 for field in PLAYER_FIELDS['passing']},
                    'rushing': {field: 0 for field in PLAYER_FIELDS['rushing']},
                    'receiving': {field: 0 for field in PLAYER_FIELDS['receiving']},
                    'miscellaneous': {field: 0 for field in PLAYER_FIELDS['miscellaneous']},
                })
                for category, fields in PLAYER_FIELDS.items():
                    for field in fields:
                        entry[category][field] += int((player.get(category) or {}).get(field, 0) or 0)

    for team in team_by_side.values():
        for period in PERIODS:
            line = team_stats[team][period]
            for field in TEAM_FIELDS:
                line.setdefault(field, 0)
            line['drives'] = drive_summary[team][period]['drives_started']
            line.setdefault('plays', 0)
            line.setdefault('possession_seconds', 0)
            # Period scoring belongs to the team that scored; drive offense and scoring team can differ on returns/safeties.
            line['points'] = points_by_team[team][period]

    return {
        'schema': 'lp-nfl-slc-quarter-boxscore-1',
        'periods': list(PERIODS), 'complete': complete, 'scoring_complete': scoring_complete,
        'player_stats_scope': 'players_with_period_activity; omitted roster players have zero period stats',
        'points_by_team': points_by_team,
        'team_stats': team_stats,
        'player_stats': {period: [rows[key] for key in sorted(rows)] for period, rows in player_stats.items()},
        'drive_summaries': drive_summaries,
        'drive_summary_by_team_and_period': drive_summary,
    }


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
                                                  'red_zone_touchdowns': 0, 'red_zone_field_goals': 0,
                                                  'red_zone_field_goal_attempts': 0,
                                                  'red_zone_field_goals_made': 0,
                                                  'red_zone_scoring_drives': 0})
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
        has_opportunity = any(
            int((player.get(category) or {}).get(field, 0) or 0) > 0
            for category, fields in PLAYER_FIELDS.items() for field in fields
            if field not in ('yds', 'sack_yds')
        )
        if meta is not None and not meta['roster_eligible'] and has_opportunity:
            context = {
                'game_id': schedule.get('game_id', 'unknown'), 'seed': int(seed), 'play_index': None,
                'state_before': 'game_start',
                'decision': {'participant_id': key, 'roster_eligible': False},
                'outcome': {'player_stats': player}, 'state_after': 'game_end',
                'source_artifact_hashes': {
                    'snapshot.snapshot_sha256': snapshot.get('snapshot_sha256', 'unavailable')},
            }
            raise football_assertions.FootballAssertionError(
                'ILLEGAL_STATE',
                f'seed {seed}: SLC participant {key} has a stat opportunity but is not roster-eligible',
                context=context)
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

    quarterly = _quarter_by_quarter(record or {}, snapshot)
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
        'points_by_period': quarterly['points_by_team'],
        'quarter_scoring_complete': quarterly['scoring_complete'],
        'quarter_by_quarter': quarterly,
        'teams': teams,
        'players': [actual[key] for key in sorted(actual)],
    }
    boxscore['reconciliation'] = reconcile_boxscore(boxscore, strict=False)
    # The serialized score comes from the game's points ledger; keep the
    # independently computed team line in agreement before this becomes a
    # per-seed box score.
    for team in boxscore['teams']:
        side = team['side']
        stats_points = _int_or_zero(team_stats.get(side, {}).get('points'))
        game_points = _int_or_zero((record or {}).get('points', {}).get(side))
        if stats_points != game_points:
            item = next(row for row in boxscore['reconciliation']['teams'] if row['side'] == side)
            item['matches'] = False
            item['mismatches']['team_points_vs_game_points'] = {
                'team_stats': stats_points, 'game_points': game_points,
            }
            boxscore['reconciliation']['status'] = 'failed'
            boxscore['reconciliation']['failure_class'] = 'STAT_ACCOUNTING'
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
        sums['turnovers'] = sums['interceptions'] + sums['fumbles_lost']
        checks = {'rush_attempts': 'rush_attempts', 'rushing_yards': 'rushing_yards',
                  'pass_attempts': 'pass_attempts', 'completions': 'completions',
                  'passing_yards': 'passing_yards', 'interceptions': 'interceptions',
                  'sacks_taken': 'sacks_taken', 'sack_yards': 'sack_yards', 'targets': 'targets',
                  'fumbles_lost': 'fumbles_lost', 'turnovers': 'turnovers'}
        mismatches = {key: {'players': sums[key], 'team': team_stats[stat]}
                      for key, stat in checks.items() if sums[key] != team_stats[stat]}
        if team_stats['completions'] > team_stats['pass_attempts']:
            mismatches['completions_exceed_attempts'] = {
                'completions': team_stats['completions'], 'attempts': team_stats['pass_attempts']}
        if team_stats['completions'] + team_stats['interceptions'] > team_stats['pass_attempts']:
            mismatches['pass_components_exceed_attempts'] = {
                'completions_plus_interceptions': team_stats['completions'] + team_stats['interceptions'],
                'attempts': team_stats['pass_attempts']}
        if team_stats['targets'] > team_stats['pass_attempts']:
            mismatches['targets_exceed_attempts'] = {
                'targets': team_stats['targets'], 'attempts': team_stats['pass_attempts']}
        if sums['receptions'] > sums['targets']:
            mismatches['receptions_exceed_targets'] = {
                'receptions': sums['receptions'], 'targets': sums['targets']}
        if sums['receptions'] != team_stats['completions']:
            mismatches['receptions'] = {'players': sums['receptions'], 'team': team_stats['completions']}
        # A passing touchdown is a passer credit on the same play that gives the
        # scorer a receiving touchdown. Count scorers once via rushing/receiving.
        player_offensive_tds = sum(p['rushing']['td'] + p['receiving']['td'] for p in players)
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
    result = {'status': 'passed' if all_match else 'failed', 'strict': strict, 'teams': results}
    if not all_match:
        result['failure_class'] = 'STAT_ACCOUNTING'
    return result


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
        red_fields = ('red_zone_trips', 'red_zone_plays', 'red_zone_touchdowns', 'red_zone_field_goals',
                      'red_zone_field_goal_attempts', 'red_zone_field_goals_made', 'red_zone_scoring_drives')
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
