"""Chronological held-out check of per-game opportunity shares (research). Fit on one season, score the next, never the reverse.

Both models use the same base shares from the fit season. The fixed-share adapter predicts multinomial counts with those shares. The
Dirichlet-multinomial predicts with per-game shares around them, with phi fitted on the fit season by maximum likelihood. Scored on the
held-out season's team-games: the log-likelihood per team-game (the difference has a bootstrap interval over games), and for each
role and position group's players the observed count mean, variance and zero rate against each model's prediction. Team-games where a
player has no fit-season history are scored on the players that do; the restriction is recorded in the output.

Usage: python3 validate_share_distributions.py --fit-season 2024 --test-season 2025 --out JSON
Optional: --concentration-fit-seasons 2022,2023,2024 fits a shared phi on multiple seasons while retaining each season's base shares.
"""
import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

import share_distributions as sdm
import share_validation as sv
import build_player_workload_reference as workload_reference

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = Path('/root/gridiron-playbooks-research/data/raw')
DEFAULT_REFERENCE_MANIFEST = REPO_ROOT / 'docs/research/player-workload-reference-2026-10-30-v3/manifest.json'
DEFAULT_POSITION_MAP = REPO_ROOT / 'docs/research/share-distribution-holdout-2026-10-31/position-map.csv'


def team_game_counts(data_dir, season, role):
    """Load regular-season player opportunities from the hash-pinned nflverse PBP CSV."""
    try:
        column, play_type = sdm.ROLE_SQL[role]
    except KeyError as exc:
        raise ValueError(f'unsupported share role: {role}') from exc
    path = Path(data_dir) / f'pbp_{int(season)}.csv.gz'
    games = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    season_counts = defaultdict(lambda: defaultdict(int))
    for row in workload_reference.read_rows(path, compressed=True):
        if row.get('season_type') != 'REG' or row.get('play_type') != play_type:
            continue
        try:
            row_season = int(float(row.get('season') or 0))
            week = int(float(row.get('week') or 0))
        except ValueError as exc:
            raise ValueError(f'{path}: invalid season/week in PBP row') from exc
        if row_season != int(season) or not 1 <= week <= 18:
            continue
        game, team, player = row.get('game_id'), row.get('posteam'), row.get(column)
        if not game or not team or not player:
            continue
        games[team][game][player] += 1
        season_counts[team][player] += 1
    return games, season_counts


def player_positions(position_map_path):
    """Load the pinned export of share_distributions.player_positions from the model database."""
    positions = {}
    with Path(position_map_path).open('r', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            player, position = row.get('gsis_id'), row.get('position')
            if not player or not position or player in positions:
                raise ValueError(f'{position_map_path}: invalid or duplicate GSIS position row {row}')
            positions[player] = position
    return positions


def load_offensive_game_eligibility(data_dir, season):
    """Map (team, game) to offensive players with at least one matched scrimmage snap."""
    data_dir = Path(data_dir)
    pbp_path = data_dir / f'pbp_{int(season)}.csv.gz'
    participation_path = data_dir / f'pbp_participation_{int(season)}.csv'
    regular_play_keys, scrimmage_teams = set(), {}
    with gzip.open(pbp_path, 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row.get('season_type') != 'REG':
                continue
            game, play = row.get('game_id'), str(row.get('play_id') or '')
            if not game or not play:
                raise ValueError(f'{pbp_path}: missing regular-season game/play key')
            key = (game, play)
            if key in regular_play_keys:
                raise ValueError(f'{pbp_path}: duplicate regular-season play key {key}')
            regular_play_keys.add(key)
            if workload_reference._is_scrimmage_row(row):
                scrimmage_teams[key] = row.get('posteam')

    eligible = defaultdict(set)
    seen = set()
    counts = Counter()
    for row in workload_reference.read_rows(participation_path):
        counts['participation_rows'] += 1
        game = row.get('nflverse_game_id')
        if not game:
            raise ValueError(f'{participation_path}: missing nflverse_game_id')
        try:
            game_season, week = (int(value) for value in game.split('_', 2)[:2])
        except (ValueError, IndexError) as exc:
            raise ValueError(f'{participation_path}: invalid game ID {game!r}') from exc
        if game_season != int(season) or not 1 <= week <= 18:
            continue
        play = str(row.get('play_id') or '')
        key = (game, play)
        if not play or key in seen:
            raise ValueError(f'{participation_path}: missing or duplicate participation key {key}')
        seen.add(key)
        player_ids = {player.strip() for player in (row.get('offense_players') or '').split(';') if player.strip()}
        if key not in regular_play_keys:
            if player_ids:
                raise ValueError(f'{participation_path}: populated key has no regular PBP match {key}')
            counts['empty_unmatched_rows'] += 1
            continue
        if key not in scrimmage_teams:
            counts['non_scrimmage_rows_excluded'] += 1
            continue
        team = row.get('possession_team') or scrimmage_teams[key]
        pbp_team = scrimmage_teams[key]
        if team and pbp_team and team != pbp_team:
            raise ValueError(f'{participation_path}: possession team mismatch at {key}: {team} != {pbp_team}')
        if not team:
            raise ValueError(f'{participation_path}: scrimmage row has no possession team at {key}')
        counts['scrimmage_rows_joined'] += 1
        eligible[(team, game)].update(player_ids)
    counts['eligible_team_games'] = len(eligible)
    counts['eligible_player_team_games'] = sum(len(players) for players in eligible.values())
    return eligible, dict(counts)


def fit_position_groups(games, season_counts, season, role, positions):
    """Fit exactly the whole-role and position-conditioned concentrations used by the share model."""
    fitted = {'all': sdm.fit_from_counts(games, season_counts, season)}
    for group, allowed in sdm.POSITION_GROUPS[role].items():
        if group == 'all':
            continue
        group_games, group_counts = sdm.filter_position_group(games, positions, allowed)
        if group_counts:
            fitted[group] = {**sdm.fit_from_counts(group_games, group_counts, season), 'position_group': group}
        else:
            fitted[group] = {**fitted['all'], 'fallback': 'all', 'position_group': group}
    return fitted


def fit_pooled_concentration(season_datasets):
    """Fit one shared concentration while retaining each season's own team-player base shares."""
    observations = []
    for games, season_counts in season_datasets:
        base = sdm.base_shares(season_counts)
        for team, by_game in games.items():
            roster = {player: base[(team, player)] for player in season_counts.get(team, {})}
            for counts in by_game.values():
                total = sum(counts.values())
                if total > 0:
                    observations.append((counts, total, roster))
    if not observations:
        raise ValueError('pooled concentration fit has no non-empty team-games')

    profile = []
    for phi in sdm.PHI_GRID:
        loglik = sum(sdm._dm_loglik(counts, total, {player: phi * share for player, share in base.items()})
                     for counts, total, base in observations)
        profile.append((phi, loglik))
    phi_hat, loglik_hat = max(profile, key=lambda row: row[1])
    supported = [phi for phi, loglik in profile if loglik >= loglik_hat - 1.92]
    return {
        'phi': phi_hat,
        'phi_interval': [min(supported), max(supported)],
        'loglik': round(loglik_hat, 3),
        'team_games': len(observations),
        'team_seasons': sum(len(games) for games, _counts in season_datasets),
    }


def verify_pinned_inputs(data_dir, manifest_path, filenames):
    """Require every input to match the source hashes in the committed benchmark manifest."""
    data_dir = Path(data_dir)
    manifest = json.loads(Path(manifest_path).read_text())
    expected = manifest.get('sources', {}).get('local_source_files', {})
    hashes = {}
    for filename in sorted(set(filenames)):
        if filename not in expected:
            raise ValueError(f'{filename} is not pinned in {manifest_path}')
        path = data_dir / filename
        actual = workload_reference.sha256(path)
        if actual != expected[filename]:
            raise ValueError(f'{path} SHA-256 {actual} does not match pinned {expected[filename]}')
        hashes[filename] = actual
    return hashes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fit-season', type=int, default=2024)
    ap.add_argument('--test-season', type=int, default=2025)
    ap.add_argument('--data-dir', type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument('--reference-manifest', type=Path, default=DEFAULT_REFERENCE_MANIFEST)
    ap.add_argument('--position-map', type=Path, default=DEFAULT_POSITION_MAP)
    ap.add_argument('--concentration-fit-seasons', type=str, default='')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.fit_season >= args.test_season:
        ap.error('--fit-season must precede --test-season')
    try:
        concentration_fit_seasons = sorted(set(
            int(value.strip()) for value in args.concentration_fit_seasons.split(',') if value.strip()))
    except ValueError:
        ap.error('--concentration-fit-seasons must be a comma-separated list of years')
    if concentration_fit_seasons and (concentration_fit_seasons[-1] != args.fit_season
                                       or concentration_fit_seasons[0] < 2022):
        ap.error('concentration fit seasons must be pinned years from 2022 through --fit-season and include --fit-season')
    source_seasons = set(concentration_fit_seasons or [args.fit_season]) | {args.fit_season, args.test_season}
    input_names = [f'pbp_{season}.csv.gz' for season in source_seasons]
    input_names.append(f'pbp_participation_{args.test_season}.csv')
    input_hashes = verify_pinned_inputs(args.data_dir, args.reference_manifest, input_names)
    positions = player_positions(args.position_map)
    eligible_players, eligibility_metadata = load_offensive_game_eligibility(args.data_dir, args.test_season)
    result = {
        'fit_season': args.fit_season,
        'test_season': args.test_season,
        'source': {
            'reference_manifest': str(args.reference_manifest),
            'reference_manifest_sha256': workload_reference.sha256(args.reference_manifest),
            'input_sha256': input_hashes,
            'position_source': {
                'file': str(args.position_map),
                'sha256': workload_reference.sha256(args.position_map),
                'query': "SELECT nfl_gsis_id, MIN(position) FROM players WHERE lower(league)='nfl' AND nfl_gsis_id IS NOT NULL AND position IS NOT NULL GROUP BY nfl_gsis_id",
            },
            'eligibility_source': f'pinned pbp_participation_{args.test_season}.csv joined to regular-season scrimmage plays',
            'eligibility': eligibility_metadata,
            'code_sha256': {
                'validate_share_distributions.py': workload_reference.sha256(Path(__file__)),
                'share_distributions.py': workload_reference.sha256(Path(sdm.__file__)),
                'share_validation.py': workload_reference.sha256(Path(sv.__file__)),
                'build_player_workload_reference.py': workload_reference.sha256(Path(workload_reference.__file__)),
            },
        },
        'roles': {},
    }
    for role in ('receive', 'carry'):
        fit_games, fit_season_counts = team_game_counts(args.data_dir, args.fit_season, role)
        fitted_by_group = fit_position_groups(fit_games, fit_season_counts, args.fit_season, role, positions)
        fitted = fitted_by_group['all']
        base = fitted['base']
        phi = fitted['phi']
        test_games, _ = team_game_counts(args.data_dir, args.test_season, role)
        role_result = sv.evaluate_share_holdout(
            test_games, base, phi, eligible_players_by_game=eligible_players, reps=2000, seed=1)
        role_result.update({
            'phi_fit': round(phi, 3), 'phi_interval_fit': [round(x, 3) for x in fitted['phi_interval']],
            'beta_binomial_phi_fit': fitted['beta_binomial_phi'], 'fit_team_games': fitted['team_games'],
            'fit_game_clusters': len({game for by_game in fit_games.values() for game in by_game}),
            'fit_teams': fitted['teams'],
        })
        role_result['position_groups'] = {}
        for group, allowed in sdm.POSITION_GROUPS[role].items():
            if group == 'all':
                continue
            group_fit = fitted_by_group[group]
            group_result = {
                'phi_fit': round(group_fit['phi'], 3),
                'phi_interval_fit': [round(x, 3) for x in group_fit['phi_interval']],
                'fit_team_games': group_fit['team_games'],
                'fit_teams': group_fit['teams'],
            }
            if group_fit.get('fallback'):
                group_result.update({'status': 'pooled_fallback', 'fallback': group_fit['fallback']})
            else:
                group_test_games, _ = sdm.filter_position_group(test_games, positions, allowed)
                try:
                    group_result.update(sv.evaluate_share_holdout(
                        group_test_games, group_fit['base'], group_fit['phi'],
                        eligible_players_by_game=eligible_players, reps=2000, seed=1))
                    group_result['status'] = 'scored'
                except ValueError as exc:
                    group_result.update({'status': 'not_scored', 'reason': str(exc)})
            role_result['position_groups'][group] = group_result

        if concentration_fit_seasons:
            pooled_role_result = {}
            training_data = {args.fit_season: (fit_games, fit_season_counts)}
            for season in concentration_fit_seasons:
                if season not in training_data:
                    training_data[season] = team_game_counts(args.data_dir, season, role)
            for group, allowed in sdm.POSITION_GROUPS[role].items():
                group_datasets = []
                group_train_games = 0
                group_train_team_seasons = 0
                for season in concentration_fit_seasons:
                    season_games, season_counts = training_data[season]
                    if allowed is not None:
                        season_games, season_counts = sdm.filter_position_group(
                            season_games, positions, allowed)
                    if season_counts:
                        group_datasets.append((season_games, season_counts))
                        group_train_games += sum(len(by_game) for by_game in season_games.values())
                        group_train_team_seasons += len(season_games)
                if not group_datasets:
                    pooled_role_result[group] = {'status': 'not_scored', 'reason': 'no fit support'}
                    continue
                pooled_fit = fit_pooled_concentration(group_datasets)
                latest_model = fitted_by_group[group]
                candidate_test_games = test_games
                if allowed is not None:
                    candidate_test_games, _ = sdm.filter_position_group(test_games, positions, allowed)
                try:
                    metrics = sv.evaluate_share_holdout(
                        candidate_test_games, latest_model['base'], pooled_fit['phi'],
                        eligible_players_by_game=eligible_players, reps=2000, seed=1)
                    pooled_role_result[group] = {
                        'status': 'scored',
                        'fit_seasons': concentration_fit_seasons,
                        'fit_team_games': group_train_games,
                        'fit_team_seasons': group_train_team_seasons,
                        'phi_fit': pooled_fit['phi'],
                        'phi_interval_fit': pooled_fit['phi_interval'],
                        **metrics,
                    }
                except ValueError as exc:
                    pooled_role_result[group] = {
                        'status': 'not_scored', 'fit_seasons': concentration_fit_seasons,
                        'fit_team_games': group_train_games, 'phi_fit': pooled_fit['phi'],
                        'phi_interval_fit': pooled_fit['phi_interval'], 'reason': str(exc),
                    }
            role_result['pooled_concentration_candidate'] = pooled_role_result
        result['roles'][role] = role_result
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
