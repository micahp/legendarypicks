"""Fail-fast validation for every external input used by an SLC simulation."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3


class PreflightError(ValueError):
    pass


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _database_errors(path, required_tables=()):
    path = Path(path).expanduser()
    if not path.is_file():
        return [f'database is missing: {path}']
    try:
        uri = path.resolve().as_uri() + '?mode=ro'
        with sqlite3.connect(uri, uri=True, timeout=10) as connection:
            names = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            missing = sorted(set(required_tables) - names)
            errors = [f'database is missing required table/view {name}: {path}' for name in missing]
            connection.execute('SELECT 1').fetchone()
            return errors
    except Exception as exc:
        return [f'database cannot be opened read-only: {path}: {type(exc).__name__}: {exc}']


def validate_cli_paths(args):
    """Check explicitly supplied inputs and the read-only database before snapshot/model work."""
    errors = _database_errors(getattr(args, 'db', ''))
    file_options = (
        'snapshot_file', 'readiness_matrix', 'archive_manifest', 'historical_streak_file',
        'roster_snapshot', 'roster_provenance', 'availability_snapshot', 'game_info_snapshot',
        'playcall_artifact', 'playcall_point_splits_cache', 'playcall_streak_cache',
        'playcall_streak_file',
    )
    dir_options = ('archive_root', 'availability_store')
    checked_files = checked_dirs = 0
    for name in file_options:
        value = getattr(args, name, None)
        if value is None or value == '':
            continue
        path = Path(value).expanduser()
        checked_files += 1
        if not path.is_file():
            errors.append(f'input file is missing or not a regular file (--{name.replace("_", "-")}): {path}')
    for name in dir_options:
        value = getattr(args, name, None)
        if value is None or value == '':
            continue
        path = Path(value).expanduser()
        checked_dirs += 1
        if not path.is_dir():
            errors.append(f'input directory is missing or not a directory (--{name.replace("_", "-")}): {path}')
    if errors:
        raise PreflightError('input preflight failed before simulation:\n - ' + '\n - '.join(errors))
    print(f'input preflight passed: database opened read-only; {checked_files} input files and '
          f'{checked_dirs} input directories present', flush=True)


def validate_comparison_paths(args):
    errors = _database_errors(args.db, ('nfl_pbp', 'nfl_schedule'))
    for name in ('readiness_matrix', 'archive_manifest', 'artifact'):
        path = Path(getattr(args, name))
        if not path.is_file():
            errors.append(f'comparison input file is missing (--{name.replace("_", "-")}): {path}')
    for name in ('archive_root', 'snapshot_dir'):
        path = Path(getattr(args, name))
        if not path.is_dir():
            errors.append(f'comparison input directory is missing (--{name.replace("_", "-")}): {path}')
    if errors:
        raise PreflightError('input preflight failed before simulation:\n - ' + '\n - '.join(errors))
    print('input preflight passed: comparison database, manifests, artifact, and archive directories are present',
          flush=True)


def _parquet_errors(path, required_columns):
    path = Path(path)
    if not path.is_file():
        return [f'required decision-label Parquet is missing: {path}']
    try:
        import pyarrow.parquet as pq
        parquet = pq.ParquetFile(path)
        columns = set(parquet.schema_arrow.names)
        missing = sorted(set(required_columns) - columns)
        errors = [f'{path}: missing Parquet columns {missing}'] if missing else []
        if parquet.metadata.num_rows == 0:
            errors.append(f'{path}: Parquet contains zero rows')
        return errors
    except Exception as exc:
        return [f'{path}: Parquet metadata/schema cannot be read: {type(exc).__name__}: {exc}']


def _decision_errors(season):
    import decision_layer as decision
    season = int(season)
    if season <= decision.FIRST_CHARTED_SEASON:
        return [f'decision labels need at least one prior charted season after '
                f'{decision.FIRST_CHARTED_SEASON}; target season is {season}']
    errors = _parquet_errors(decision.PLAYERS_PARQUET, ('gsis_id', 'position'))
    seasons = list(range(decision.FIRST_CHARTED_SEASON, season))
    for year in seasons:
        errors.extend(_parquet_errors(decision.PBP_PARQUET.format(season=year),
                                      ('game_id', 'play_id', 'pass_length')))
    return errors, len(seasons) + 1


def _playbook_errors(season, target_teams):
    import playbook_crosscheck as crosscheck
    root = Path(crosscheck.PLAYBOOKS)
    target_teams = {crosscheck.TEAM_CODE.get(team, team) for team in target_teams}
    manifest_path = root / 'build_manifest.json'
    errors = []
    if not manifest_path.is_file():
        return [f'playbook build manifest is missing: {manifest_path}'], 0
    try:
        manifest = json.loads(manifest_path.read_text())
        entries = [item for item in manifest['team_seasons'] if int(item['season']) == int(season) - 1]
    except Exception as exc:
        return [f'playbook build manifest is invalid: {manifest_path}: {type(exc).__name__}: {exc}'], 0
    if len(entries) != 32:
        errors.append(f'playbook manifest needs 32 team files for {int(season)-1}; found {len(entries)}')
    teams = set()
    seen_outputs = set()
    for entry in entries:
        output = str(entry.get('output', ''))
        if not output or Path(output).name != output or output in seen_outputs:
            errors.append(f'playbook manifest has invalid or duplicate output name: {output!r}')
            continue
        seen_outputs.add(output)
        path = root / output
        team = crosscheck.TEAM_CODE.get(entry.get('team'), entry.get('team'))
        if team in teams:
            errors.append(f'playbook manifest has duplicate team {team} for season {int(season)-1}')
        teams.add(team)
        if not path.is_file():
            errors.append(f'playbook file is missing: {path}')
            continue
        try:
            actual = _sha256(path)
            if actual != entry['output_sha256']:
                errors.append(f'playbook checksum mismatch: {path}; expected {entry["output_sha256"]}, got {actual}')
            data = json.loads(path.read_text())
            file_team = crosscheck.TEAM_CODE.get(data.get('team_id'), data.get('team_id'))
            if file_team != team:
                errors.append(f'playbook team identity mismatch: {path}; manifest={team}, file={file_team}')
            plays = data.get('offense', {}).get('observed_plays')
            if not isinstance(plays, list) or not plays:
                errors.append(f'playbook has no offensive observed_plays: {path}')
        except Exception as exc:
            errors.append(f'playbook cannot be verified: {path}: {type(exc).__name__}: {exc}')
    missing_teams = sorted(set(target_teams) - teams)
    if missing_teams:
        errors.append(f'playbook prior is missing target-game teams {missing_teams} for season {int(season)-1}')
    return errors, len(entries)


def _frame_errors():
    import playcall_observations as observations
    errors = []
    for season in range(observations.FIRST_SEASON, observations.LAST_SEASON + 1):
        try:
            path, pinned = observations.score_source(season)
            if not path.is_file():
                errors.append(f'play-call score source is missing for {season}: {path}')
            if not isinstance(pinned, str) or len(pinned) != 64:
                errors.append(f'play-call score source has no valid SHA-256 pin for {season}: {path}')
            elif path.is_file():
                actual = _sha256(path)
                if actual != pinned:
                    errors.append(f'play-call score source checksum mismatch for {season}: {path}; '
                                  f'expected {pinned}, got {actual}')
        except Exception as exc:
            errors.append(f'play-call score source manifest failed for {season}: {type(exc).__name__}: {exc}')
    flags = Path(observations.FLAGS_PATH)
    if not flags.is_file():
        errors.append(f'play-call score exception fixture is missing: {flags}')
    else:
        try:
            with flags.open(newline='') as handle:
                columns = set(csv.DictReader(handle).fieldnames or ())
            missing = {'game_id', 'play_id', 'label'} - columns
            if missing:
                errors.append(f'play-call score exception fixture lacks columns {sorted(missing)}: {flags}')
        except Exception as exc:
            errors.append(f'play-call score exception fixture is unreadable: {flags}: {type(exc).__name__}: {exc}')
    return errors


def validate_model_sources(args, snapshot):
    """Validate all selected model inputs before loading the reference pool or launching any child run."""
    schedule = snapshot['schedule']
    season = int(schedule['season'])
    teams = {schedule['home_team'], schedule['away_team']}
    errors = _database_errors(args.db, ('nfl_pbp', 'nfl_schedule'))
    decision = bool(getattr(args, 'playcall_decision', False))
    playbook = bool(getattr(args, 'playcall_playbook', False))
    frame = any(bool(getattr(args, name, False)) for name in (
        'playcall_point_splits', 'playcall_point_splits_cache', 'playcall_streak_splits',
        'playcall_streak_cache', 'playcall_streak_league'))
    if decision:
        errors.extend(_database_errors(args.db, ('nfl_hist_ftn_charting',)))
        decision_result = _decision_errors(season)
        if isinstance(decision_result, tuple):
            decision_errors, decision_files = decision_result
            errors.extend(decision_errors)
        else:
            decision_files = 0
            errors.extend(decision_result)
    else:
        decision_files = 0
    if playbook:
        playbook_errors, playbook_files = _playbook_errors(season, teams)
        errors.extend(playbook_errors)
    else:
        playbook_files = 0
    if frame:
        errors.extend(_frame_errors())
    if args.playcall_artifact:
        try:
            import slc_engine
            import slc_playcall
            artifact = json.loads(Path(args.playcall_artifact).read_text())
            slc_playcall.PlayCallLayer(artifact)
            slc_engine.check_artifact_cutoff(artifact, season)
        except Exception as exc:
            errors.append(f'play-call artifact is invalid for target season {season}: '
                          f'{type(exc).__name__}: {exc}')
    streak_file = getattr(args, 'playcall_streak_file', None)
    if streak_file:
        path = Path(streak_file)
        try:
            data = json.loads(path.read_text())
            streak_teams = data['teams']
            missing = sorted(teams - set(streak_teams))
            if missing:
                errors.append(f'current streak input lacks target teams {missing}: {path}')
            for team in teams & set(streak_teams):
                if not isinstance(streak_teams[team], dict) or 'streak' not in streak_teams[team]:
                    errors.append(f'current streak input has invalid record for {team}: {path}')
        except Exception as exc:
            errors.append(f'current streak input is invalid: {path}: {type(exc).__name__}: {exc}')
    if errors:
        raise PreflightError('input preflight failed before simulation:\n - ' + '\n - '.join(errors))
    print(f'input preflight passed: season {season}; database tables available; '
          f'{decision_files} decision Parquets; {playbook_files} manifest-pinned playbooks; '
          f'{16 if frame else 0} play-call frame score sources', flush=True)


def validate_comparison_sources(args, target_games):
    """Validate shared inputs for the entire paired comparison before the first child process starts."""
    seasons = {int(game['season']) for game in target_games}
    if len(seasons) != 1:
        raise PreflightError(f'input preflight failed before simulation: comparison targets multiple seasons {sorted(seasons)}')
    season = next(iter(seasons))
    teams = set()
    for game in target_games:
        teams.update((game['home_team'], game['away_team']))
    errors = _database_errors(args.db, ('nfl_pbp', 'nfl_schedule', 'nfl_hist_ftn_charting'))
    decision_errors, decision_files = _decision_errors(season)
    errors.extend(decision_errors)
    playbook_errors, playbook_files = _playbook_errors(season, teams)
    errors.extend(playbook_errors)
    errors.extend(_frame_errors())
    try:
        import slc_engine
        import slc_playcall
        artifact = json.loads(Path(args.artifact).read_text())
        slc_playcall.PlayCallLayer(artifact)
        slc_engine.check_artifact_cutoff(artifact, season)
    except Exception as exc:
        errors.append(f'play-call artifact is invalid for target season {season}: {type(exc).__name__}: {exc}')
    if errors:
        raise PreflightError('input preflight failed before simulation:\n - ' + '\n - '.join(errors))
    print(f'input preflight passed: {len(target_games)} comparison games; {decision_files} decision Parquets; '
          f'{playbook_files} manifest-pinned playbooks; 16 play-call frame score sources', flush=True)
