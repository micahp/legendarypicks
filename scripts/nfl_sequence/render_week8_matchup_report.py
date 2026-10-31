"""Render a per-matchup Week 8 SLC run review from its immutable audit and benchmarks."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import tarfile
from collections import Counter, defaultdict
from pathlib import Path


MIN_PLAYER_REFERENCE_GAMES = 4
METRIC_MAP = {
    'rush_attempts': 'rush_attempts',
    'rush_yards': 'rushing_yards',
    'targets': 'targets',
    'receptions': 'receptions',
    'receiving_yards': 'receiving_yards',
    'pass_attempts': 'pass_attempts',
    'passing_yards': 'passing_yards',
}
RUNTIME_FIXES = (
    'run_scramble_backoff',
    'long_field_goal_feasibility',
    'blocked_kick_source_audit',
    'blocked_kick_geometry',
    'safety_free_kick_boundaries',
)
PREVIOUS_RUN_SOURCE = '7faa8eda'
SOURCE_CHANGE_NOTES = (
    ('52c59c10', 'Filter unsupported lateral source rows and retain blocked-decision evidence.'),
    ('fff76c08', 'Distinguish a final overtime tie from a tie at the end of regulation.'),
    ('c188ee3b / dee4a084', 'Build and publish cutoff-safe player workload references for 2022–2025 and 2026 Weeks 1–7.'),
    ('2a1022a5', 'Limit designed-run participants to active QB1; condition opportunity shares by position; honor roster eligibility; derive QB starter status from depth and availability; correct touchdown and box-score accounting.'),
    ('fa06fe84', 'Add event-clock replay windows for the separate Model D diagnostic; this is not an enabled SLC playcall layer in this run.'),
)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'{path} must contain a JSON object')
    return value


def _read_rows(path: Path) -> list[dict]:
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _integer(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _select_reference(player: dict, metric: str, player_rows: dict, position_rows: dict) -> dict | None:
    reference_metric = METRIC_MAP.get(metric)
    if reference_metric is None:
        return None
    player_id = str(player.get('player_id') or '')
    position = str(player.get('position') or '')
    for window in ('target_2026_w1_7', 'multi_2022_2025', 'train_2022_2024'):
        row = player_rows.get((window, player_id, reference_metric))
        if row and row.get('metric_status') != 'unavailable_source_classification':
            support = _integer(row.get('eligible_player_games'), _integer(row.get('game_sample_n')))
            if support >= MIN_PLAYER_REFERENCE_GAMES:
                return {**row, 'reference_window': window, 'reference_basis': 'player_shrunken_mean'}
    for window in ('target_2026_w1_7', 'multi_2022_2025', 'train_2022_2024'):
        row = position_rows.get((window, position, reference_metric))
        if row and row.get('metric_status') != 'unavailable_source_classification':
            return {**row, 'reference_window': window, 'reference_basis': 'position_mean'}
    return None


def _comparisons(game: dict, reference_dir: Path) -> list[dict]:
    player_rows = {
        (row['window'], row['player_id'], row['metric']): row
        for row in _read_rows(reference_dir / 'player_workload_distributions.csv')
    }
    position_rows = {
        (row['window'], row['position'], row['metric']): row
        for row in _read_rows(reference_dir / 'position_workload_distributions.csv')
    }
    output = []
    for player in game.get('player_distributions', []):
        reference = _select_reference(player, player['metric'], player_rows, position_rows)
        benchmark_mean = None
        support = None
        if reference:
            benchmark_mean = _number(reference.get('shrunken_mean'))
            if benchmark_mean is None:
                benchmark_mean = _number(reference.get('mean'))
            support = _integer(reference.get('eligible_player_games'), _integer(reference.get('game_sample_n')))
        sim_mean = _number(player.get('mean'))
        delta_pct = None
        if sim_mean is not None and benchmark_mean is not None and benchmark_mean > 0:
            delta_pct = (sim_mean - benchmark_mean) / benchmark_mean * 100
        output.append({
            'player_id': player.get('player_id'), 'player_name': player.get('player_name'),
            'team': player.get('team'), 'position': player.get('position'), 'metric': player['metric'],
            'simulated_game_sample_n': player.get('valid_game_sample_n'), 'simulated_mean': player.get('mean'),
            'simulated_zero_rate': player.get('zero_rate'), 'simulated_p95': player.get('p95'),
            'simulated_p99': player.get('p99'), 'simulated_maximum': player.get('maximum'),
            'maximum_seed': player.get('maximum_seed'),
            'historical_record_boundary': player.get('historical_record_boundary'),
            'record_exceedance_count': player.get('record_exceedance_count'),
            'record_exceedance_rate': player.get('record_exceedance_rate'),
            'record_exceedance_seeds': ','.join(map(str, player.get('record_exceedance_seeds', []))),
            'reference_window': reference.get('reference_window') if reference else None,
            'reference_basis': reference.get('reference_basis') if reference else None,
            'reference_games': support,
            'reference_mean': benchmark_mean,
            'reference_p95': _number(reference.get('p95')) if reference else None,
            'reference_p99': _number(reference.get('p99')) if reference else None,
            'reference_maximum': _number(reference.get('observed_maximum')) if reference else None,
            'mean_difference_pct': delta_pct,
            'absolute_mean_difference': abs(sim_mean - benchmark_mean)
            if sim_mean is not None and benchmark_mean is not None else None,
            'mean_difference_over_25pct_with_support': bool(
                reference and reference.get('reference_basis') == 'player_shrunken_mean'
                and support is not None and support >= MIN_PLAYER_REFERENCE_GAMES
                and sim_mean is not None and sim_mean > 0
                and delta_pct is not None and abs(delta_pct) > 25
            ),
            'position_prior_deviation_over_25pct': bool(
                reference and reference.get('reference_basis') == 'position_mean'
                and sim_mean is not None and sim_mean > 0
                and delta_pct is not None and abs(delta_pct) > 25
            ),
            'zero_simulated_with_positive_reference': bool(
                sim_mean == 0 and benchmark_mean is not None and benchmark_mean > 0
                and support is not None and support >= MIN_PLAYER_REFERENCE_GAMES
            ),
        })
    return output


def _boxscore_metadata(output_dir: Path) -> dict:
    archives = sorted((output_dir / 'outputs').glob('worker-*.tar.gz'))
    if not archives:
        return {'available': False}

    status_counts = Counter()
    starter_counts = defaultdict(Counter)
    starter_basis_counts = defaultdict(Counter)
    roster_counts = defaultdict(Counter)
    qb_usage = defaultdict(Counter)
    qb_players = defaultdict(Counter)
    for starter_label in ('true', 'false', 'unknown'):
        qb_usage[starter_label].update({
            'player_game_records': 0, 'pass_attempts': 0, 'rush_attempts': 0, 'targets': 0,
        })
    complete_games = 0
    for archive_path in archives:
        with tarfile.open(archive_path, 'r:gz') as archive:
            members = [member for member in archive.getmembers()
                       if member.name.endswith('.boxscores.jsonl')]
            if len(members) != 1:
                raise ValueError(f'{archive_path} must contain exactly one boxscore JSONL')
            source = archive.extractfile(members[0])
            if source is None:
                raise ValueError(f'cannot read boxscore JSONL from {archive_path}')
            for line in source:
                row = json.loads(line)
                if row.get('type') != 'game':
                    continue
                status = str(row.get('status') or 'unknown')
                status_counts[status] += 1
                if status != 'valid_complete':
                    continue
                complete_games += 1
                for player in row.get('players') or []:
                    position = str(player.get('position') or 'unknown')
                    starter = player.get('starter')
                    starter_label = 'unknown' if starter is None else str(bool(starter)).lower()
                    starter_counts[position][starter_label] += 1
                    starter_basis_counts[position][str(player.get('starter_basis') or 'unknown')] += 1
                    eligible = player.get('roster_eligible')
                    eligible_label = 'unknown' if eligible is None else str(bool(eligible)).lower()
                    roster_counts[position][eligible_label] += 1
                    if position != 'QB':
                        continue
                    passing = player.get('passing') or {}
                    rushing = player.get('rushing') or {}
                    receiving = player.get('receiving') or {}
                    stats = {
                        'pass_attempts': _integer(passing.get('att')),
                        'rush_attempts': _integer(rushing.get('att')),
                        'targets': _integer(receiving.get('tgt')),
                    }
                    if not any(stats.values()):
                        continue
                    qb_usage[starter_label]['player_game_records'] += 1
                    for metric, value in stats.items():
                        qb_usage[starter_label][metric] += value
                    player_key = (
                        str(player.get('name') or 'unknown'), starter_label,
                        str(player.get('starter_basis') or 'unknown'),
                    )
                    qb_players[player_key]['player_game_records'] += 1
                    for metric, value in stats.items():
                        qb_players[player_key][metric] += value

    return {
        'available': True,
        'archive_count': len(archives),
        'boxscore_status_counts': dict(status_counts),
        'valid_complete_games': complete_games,
        'starter_counts_by_position': {
            position: dict(counts) for position, counts in sorted(starter_counts.items())
        },
        'starter_basis_counts_by_position': {
            position: dict(counts) for position, counts in sorted(starter_basis_counts.items())
        },
        'roster_eligibility_counts_by_position': {
            position: dict(counts) for position, counts in sorted(roster_counts.items())
        },
        'qb_usage_by_starter': {
            starter: dict(counts) for starter, counts in sorted(qb_usage.items())
        },
        'qbs_with_usage': [
            {'name': key[0], 'starter': key[1], 'starter_basis': key[2], **dict(counts)}
            for key, counts in sorted(qb_players.items())
        ],
    }


def _fmt(value, digits=2):
    if value is None:
        return 'n/a'
    if isinstance(value, int):
        return str(value)
    return f'{value:.{digits}f}'


def _source_delta(source_repo: Path, current: str) -> tuple[str, list[str]]:
    try:
        stat = subprocess.run(
            ['git', '-C', str(source_repo), 'diff', '--shortstat', f'{PREVIOUS_RUN_SOURCE}..{current}'],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        commits = subprocess.run(
            ['git', '-C', str(source_repo), 'log', '--format=%h %s', f'{PREVIOUS_RUN_SOURCE}..{current}'],
            check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        return stat or 'No source diff reported.', commits
    except (OSError, subprocess.CalledProcessError):
        return 'Source diff unavailable in this checkout; source commit hashes are retained below.', []


def _write_csv(path: Path, rows: list[dict], *, replace_existing: bool = False) -> None:
    fields = list(rows[0]) if rows else ['player_id', 'player_name', 'team', 'position', 'metric']
    import io
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    _write_once(path, buffer.getvalue(), replace_existing=replace_existing)


def _write_once(path: Path, content: str, *, replace_existing: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding='utf-8') != content:
            if not replace_existing:
                raise FileExistsError(f'refusing to overwrite different report output: {path}')
            path.write_text(content, encoding='utf-8')
        return
    with path.open('x', encoding='utf-8') as handle:
        handle.write(content)


def _render(game: dict, header: dict, bumper: dict, comparisons: list[dict],
            audit_path: Path, header_path: Path, reference_dir: Path,
            bumper_path: Path, source_repo: Path, boxscore_metadata: dict) -> str:
    matchup = game['matchup']
    provenance = game.get('source_provenance') or {}
    current_source = str(provenance.get('source_commit') or header.get('source_commit') or 'unknown')
    diff_stat, commits = _source_delta(source_repo, current_source)
    counts = game.get('seed_status_counts') or {}
    complete = game.get('valid_full_games', 0)
    blocked = sum(game.get('blocker_counts', {}).values())
    errors = game.get('simulation_or_validation_errors', 0)
    layers = {key.removeprefix('playcall_'): value for key, value in header.items()
              if key.startswith('playcall_') and type(value) is bool}
    profile = header.get('slc_profile') or {}
    profile_name = (profile.get('profile') or profile.get('name') or profile.get('model_id')) \
        if isinstance(profile, dict) else profile
    flagged = [row for row in comparisons if row['mean_difference_over_25pct_with_support']]
    flagged.sort(key=lambda row: row['absolute_mean_difference'] or 0, reverse=True)
    position_prior_flags = [row for row in comparisons if row['position_prior_deviation_over_25pct']]
    position_prior_flags.sort(key=lambda row: row['absolute_mean_difference'] or 0, reverse=True)
    zero_use = [row for row in comparisons if row['zero_simulated_with_positive_reference']]
    zero_use.sort(key=lambda row: (row['team'] or '', row['player_name'] or '', row['metric']))
    record_alerts = [row for row in comparisons if _integer(row.get('record_exceedance_count')) > 0]
    record_alerts.sort(key=lambda row: (-_integer(row.get('record_exceedance_count')), row['player_name'] or '', row['metric']))

    lines = [
        f'# {matchup.replace("_", "–")} Week 8 SLC 10K results and player workload review', '',
        f'**Game:** `{game.get("game_id")}`  ',
        f'**Audit status:** `{game.get("status")}`  ',
        f'**Seeds accounted:** {game.get("accounted_seed_count", 0):,} / {game.get("requested_seed_count", 0):,}  ',
        f'**Completed:** {complete:,}  **Blocked:** {blocked:,}  **Simulation/validation errors:** {errors:,}  ',
        f'**Valid box scores reconciled:** {game.get("reconciled_valid_full_games", 0):,} / {complete:,}  ',
        f'**Final ties after overtime:** {game.get("final_ties", 0):,}  ',
        f'**Box-score export:** {header.get("boxscore_export", "not recorded")}  ',
        f'**Profile:** `{profile_name or "not recorded"}`', '',
        '## Outcome and integrity', '',
        '| Seed status | Count |', '|---|---:|',
    ]
    lines.extend(f'| `{status}` | {count:,} |' for status, count in sorted(counts.items()))
    lines += [
        '',
        f'Regulation end reached: {game.get("regulation_end_reached", 0):,}; tied at regulation end: '
        f'{game.get("tied_at_regulation_end", 0):,}; blocked before regulation ended: '
        f'{game.get("blocked_before_regulation_end", 0):,}; reconciliation failures: '
        f'{game.get("reconciliation_failures", 0):,}.',
        '',
        '| Blocker | Count |', '|---|---:|',
    ]
    blockers = game.get('blocker_counts') or {}
    if blockers:
        lines.extend(f'| `{name}` | {count:,} |' for name, count in sorted(blockers.items()))
    else:
        lines.append('| None | 0 |')
    lines += [
        '',
        f'Audit failures: {len(game.get("failures", []))}. Full seed-level exceptions and source artifact hashes are in '
        f'[`{audit_path.name}`]({audit_path.name}).',
        '',
    ]
    if boxscore_metadata.get('available'):
        lines += [
            '## Player eligibility and starter metadata', '',
            f'Archived boxscores scanned: {boxscore_metadata["valid_complete_games"]:,} valid completed games across '
            f'{boxscore_metadata["archive_count"]} worker archives. Starter status is `unknown` when the frozen roster '
            'does not provide evidence; it is not defaulted to false.', '',
            '| Position | Starter true | Starter false | Starter unknown | Roster eligible true | Roster eligible false |',
            '|---|---:|---:|---:|---:|---:|',
        ]
        for position, counts in boxscore_metadata['starter_counts_by_position'].items():
            eligible = boxscore_metadata['roster_eligibility_counts_by_position'].get(position, {})
            lines.append(
                f'| {position} | {counts.get("true", 0):,} | {counts.get("false", 0):,} | '
                f'{counts.get("unknown", 0):,} | {eligible.get("true", 0):,} | {eligible.get("false", 0):,} |'
            )
        lines += [
            '',
            'QB participation by exported starter flag:', '',
            '| Starter flag | QB player-game records with a pass, rush, or target | Pass attempts | Rush attempts | Targets |',
            '|---|---:|---:|---:|---:|',
        ]
        for starter, stats in boxscore_metadata['qb_usage_by_starter'].items():
            lines.append(
                f'| {starter} | {stats.get("player_game_records", 0):,} | '
                f'{stats.get("pass_attempts", 0):,} | {stats.get("rush_attempts", 0):,} | '
                f'{stats.get("targets", 0):,} |'
            )
        if boxscore_metadata['qb_usage_by_starter'].get('false', {}).get('player_game_records', 0) == 0:
            lines += ['', 'No `starter=false` quarterback had a credited pass attempt, rush attempt, or target in these archived games.']
        lines += ['', 'Quarterbacks with credited use:', '',
                  '| Player | Starter | Evidence basis | Player-game records | Pass attempts | Rush attempts | Targets |',
                  '|---|---|---|---:|---:|---:|---:|']
        for qb in boxscore_metadata['qbs_with_usage']:
            lines.append(
                f'| {qb["name"]} | {qb["starter"]} | {qb["starter_basis"]} | '
                f'{qb.get("player_game_records", 0):,} | {qb.get("pass_attempts", 0):,} | '
                f'{qb.get("rush_attempts", 0):,} | {qb.get("targets", 0):,} |'
            )
        lines += [
            '',
            '`roster_eligible` means present in the frozen roster snapshot; it does not claim the player entered the game.',
            '',
        ]
    else:
        lines += ['', '## Player eligibility and starter metadata', '',
                  'Archived worker boxscores were unavailable; starter and QB participation metadata could not be summarized.', '',]
    lines += [
        '## Player workload bumpers', '',
        'Historical single-game values are alert boundaries, not legal caps. A new record remains possible; each exceedance '
        'is reported with its frequency and seed, never clipped.', '',
        '| Metric | Historical boundary | Policy |', '|---|---:|---|',
    ]
    boundaries = bumper.get('historical_single_game_reference_boundaries') or {}
    for key, value in boundaries.items():
        lines.append(f'| {key.replace("_", " ")} | {value.get("value")} {value.get("unit", "")} | `{value.get("policy")}` |')
    lines += ['', '### Simulated record exceedances', '']
    if record_alerts:
        lines += ['| Player | Team | Metric | Boundary | Exceedances | Rate | Maximum | Seed |',
                  '|---|---|---|---:|---:|---:|---:|---:|']
        for row in record_alerts:
            lines.append(
                f'| {row["player_name"] or row["player_id"]} | {row["team"] or ""} | {row["metric"]} | '
                f'{row["historical_record_boundary"]} | {row["record_exceedance_count"]} | '
                f'{_fmt((_number(row["record_exceedance_rate"]) or 0) * 100, 3)}% | '
                f'{row["simulated_maximum"]} | {row["maximum_seed"]} |'
            )
    else:
        lines.append('No simulated player metric exceeded the configured historical record boundaries.')
    lines += ['', '### Provisional workload review gates', '',
              'These are review thresholds, not rules of play. Role-specific gates are only applied when the run provides enough '
              'evidence to identify that role; the complete per-player distributions and reference joins are in '
              f'[`player-workload-comparison.csv`](player-workload-comparison.csv).', '',
              '| Player/role | Metric | Ordinary range | Review at | Serious at |', '|---|---|---:|---:|---:|']
    for role, values in (bumper.get('provisional_player_review_thresholds') or {}).items():
        if 'rush_attempts_ordinary_range' in values:
            metric = 'rush attempts'
            ordinary = values['rush_attempts_ordinary_range']
            review = values.get('rush_attempts_review_at')
            serious = values.get('rush_attempts_serious_at')
        elif 'targets_ordinary_range' in values:
            metric = 'targets'
            ordinary = values['targets_ordinary_range']
            review = values.get('targets_review_at')
            serious = values.get('targets_serious_at')
        elif 'non_kneel_rush_attempts_ordinary_range' in values:
            metric = 'non-kneel QB rush attempts / rushing yards'
            ordinary = values['non_kneel_rush_attempts_ordinary_range']
            review = f'{values.get("rush_attempts_review_at")} att / {values.get("rush_yards_review_at")} yd'
            serious = f'{values.get("rush_attempts_serious_at")} att / {values.get("rush_yards_serious_at")} yd'
        elif 'pass_attempts_ordinary_range' in values:
            metric = 'pass attempts'
            ordinary = values['pass_attempts_ordinary_range']
            review = values.get('pass_attempts_review_at')
            serious = values.get('pass_attempts_serious_at')
        else:
            continue
        lines.append(f'| {role} | {metric} | {ordinary[0]}–{ordinary[1]} | {review} | {serious} |')
    lines += ['', '## Player means versus cutoff-safe references', '',
              'The CSV includes every audited player/metric, simulated zero rate, P95/P99/maximum, benchmark support, reference '
              'basis, and absolute and percentage mean differences. The first table uses supported player-level shrunken '
              'references only and excludes zero-use rows, which need an eligibility check before workload calibration. '
              'Position-prior comparisons and zero-use rows are shown separately. This is a distribution comparison, not a '
              'causal attribution to one model layer.', '']
    if flagged:
        lines += ['| Player | Pos | Metric | Sim mean | Reference mean | Ref basis | Window | Ref games | Δ/game | Difference | Sim P95 | Sim max |',
                  '|---|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|']
        for row in flagged[:40]:
            lines.append(
                f'| {row["player_name"] or row["player_id"]} | {row["position"] or ""} | {row["metric"]} | '
                f'{_fmt(_number(row["simulated_mean"]))} | {_fmt(_number(row["reference_mean"]))} | '
                f'{row["reference_basis"]} | {row["reference_window"]} | {row["reference_games"]} | '
                f'{_fmt(_number(row["absolute_mean_difference"]))} | '
                f'{_fmt(_number(row["mean_difference_pct"]))}% | {_fmt(_number(row["simulated_p95"]))} | '
                f'{row["simulated_maximum"]} |'
            )
        if len(flagged) > 40:
            lines.append(f'| … | … | … | … | … | … | … | … | … | … | … | {len(flagged) - 40} additional player-reference rows are in the CSV |')
    else:
        lines.append('No supported player-level reference differed from a nonzero simulated mean by more than 25%.')
    lines += ['', f'Position-prior deviations over 25%: {len(position_prior_flags)} rows. '
              'These are role-level context, not player-specific calibration failures; full details are in the CSV.', '']
    if zero_use:
        lines += [f'Zero simulated use with positive supported player history: {len(zero_use)} metric rows. '
                  'Check roster role and substitution eligibility before treating these as workload errors.', '',
                  '| Player | Team | Pos | Metric | Reference mean | Window | Ref games |',
                  '|---|---|---|---|---:|---|---:|']
        for row in zero_use[:24]:
            lines.append(
                f'| {row["player_name"] or row["player_id"]} | {row["team"] or ""} | {row["position"] or ""} | '
                f'{row["metric"]} | {_fmt(_number(row["reference_mean"]))} | {row["reference_window"]} | '
                f'{row["reference_games"]} |'
            )
    else:
        lines += ['No supported player history had zero simulated use.', '']
    lines += ['', '## Run version and changes since the prior run', '',
              f'- Previous run source: `{PREVIOUS_RUN_SOURCE}`; this run source: `{current_source}`.',
              f'- Source diff: {diff_stat}.',
              f'- Frozen snapshot SHA-256: `{provenance.get("snapshot_sha256", header.get("source_snapshot_sha256", "unknown"))}`.',
              f'- SLC configuration hash: `{provenance.get("configuration_hash", "unknown")}`.',
              f'- Playcall artifact SHA-256: `{provenance.get("playcall_artifact_sha256", header.get("playcall_artifact_sha256", "unknown"))}`.',
              f'- Benchmark manifest SHA-256: `{_hash(reference_dir / "manifest.json")}`.',
              f'- Boundary configuration SHA-256: `{_hash(bumper_path)}`.',
              f'- Run header saved as [`{header_path.name}`]({header_path.name}).',
              '', 'Changes in the producer source range:', '']
    if commits:
        lines.extend(f'- `{item}`' for item in commits)
    else:
        lines.append('- Commit range could not be read from the current source checkout.')
    lines += ['', 'Relevant behavior and scope:', '']
    lines.extend(f'- `{commit}`: {note}' for commit, note in SOURCE_CHANGE_NOTES)
    blocker_fixes = profile.get('blocker_resolution', {}).get('enabled_fixes', []) \
        if isinstance(profile, dict) else []
    lines += ['', 'Runtime blocker-fix switches recorded in the run header:', '']
    if blocker_fixes:
        lines.extend(f'- `{fix}`: enabled' for fix in blocker_fixes)
    else:
        lines.extend(f'- `{fix}`: configured by launcher; run-header evidence unavailable' for fix in RUNTIME_FIXES)
    lines += ['', 'Enabled playcall flags from the run header:', '']
    if layers:
        lines.extend(f'- `{name}`: `{value}`' for name, value in sorted(layers.items()))
    else:
        lines.append('- No individual playcall flags were recorded.')
    optional_style = header.get('playcall_qb_run_role_style', profile.get('qb_run_role_style') if isinstance(profile, dict) else None)
    lines += ['', f'Optional QB run-role-style layer: `{optional_style if optional_style is not None else "not recorded"}`.',
              '', '## Provenance and interpretation', '',
              f'- Audit JSON SHA-256: `{_hash(audit_path)}`.',
              f'- Run-header JSON SHA-256: `{_hash(header_path)}`.',
              '- Statistical outliers are distribution warnings. They do not invalidate otherwise legal games.',
              '- The report preserves blocked/error seeds and does not change or clip any outcome.', '']
    return '\n'.join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-json', required=True, type=Path)
    parser.add_argument('--run-header-json', required=True, type=Path)
    parser.add_argument('--benchmark-dir', required=True, type=Path)
    parser.add_argument('--bumper-config', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--source-repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--replace-existing', action='store_true',
                        help='replace report and comparison CSV previously rendered by this script')
    args = parser.parse_args(argv)

    audit = _read_json(args.audit_json)
    games = audit.get('matchups') or []
    if len(games) != 1:
        parser.error('audit JSON must contain exactly one matchup')
    game = games[0]
    header = _read_json(args.run_header_json)
    bumper = _read_json(args.bumper_config)
    comparisons = _comparisons(game, args.benchmark_dir)
    boxscore_metadata = _boxscore_metadata(args.output_dir)
    _write_csv(args.output_dir / 'player-workload-comparison.csv', comparisons,
               replace_existing=args.replace_existing)
    report = _render(game, header, bumper, comparisons, args.audit_json, args.run_header_json,
                     args.benchmark_dir, args.bumper_config, args.source_repo, boxscore_metadata)
    _write_once(args.output_dir / 'RESULTS.md', report, replace_existing=args.replace_existing)
    print(f'matchup={game.get("matchup")} audit_status={game.get("status")} '
          f'completed={game.get("valid_full_games", 0)} blocked={sum((game.get("blocker_counts") or {}).values())} '
          f'errors={game.get("simulation_or_validation_errors", 0)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
