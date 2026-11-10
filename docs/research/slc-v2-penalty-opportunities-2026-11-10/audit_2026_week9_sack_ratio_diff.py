"""Compare BUF-MIN Week 9 team sack multipliers with and without the 2026 penalty overlay."""
import collections
import hashlib
import json
import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_2026_penalty_overlay as audit

OUT = '/tmp/slc-2026-week9-sack-ratio-diff.json'
TARGET = '2026_09_BUF_MIN'
EXPECTED_DB_SHA256 = '1a775208bc6e38763ef59c38a6cc79bda3636007feb8c6dc44f085f668341daa'
EXPECTED_OVERLAY_SHA256 = '0af09583a74a8dd1578b2d6cebb1d259a989a41a85352cda94c1e2dacab4b7de'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    db_sha = sha256(audit.DB)
    overlay_sha = sha256(audit.PENALTY_OVERLAY)
    if db_sha != EXPECTED_DB_SHA256:
        raise ValueError(f'database SHA mismatch: {db_sha}')
    if overlay_sha != EXPECTED_OVERLAY_SHA256:
        raise ValueError(f'overlay SHA mismatch: {overlay_sha}')
    _history_rows, _pool, history, _excluded, _raw, _yard = audit.freeze_base(2026)
    con = sqlite3.connect(f'file:{audit.DB}?mode=ro', uri=True, timeout=30)
    schedule = [dict(zip(('game_id', 'season', 'week', 'gameday', 'gametime'), row))
                for row in con.execute(
                    "SELECT game_id,season,week,gameday,gametime FROM nfl_schedule "
                    "WHERE season=2026 AND game_type='REG'")]
    details = {row[0]: (row[1], row[2]) for row in con.execute(
        "SELECT game_id,home_team,away_team FROM nfl_schedule WHERE season=2026 AND game_type='REG'")}
    rows = [dict(zip(audit.e1.COLUMNS, row)) for row in con.execute(
        f"SELECT {', '.join(audit.e1.COLUMNS)} FROM nfl_pbp WHERE season=2026 ORDER BY game_id,play_id")]
    con.close()

    target_schedule = {row['game_id']: row for row in schedule}[TARGET]
    kickoff = audit.tsa.kickoff_utc(target_schedule['gameday'], target_schedule['gametime'])
    cutoff = audit.tsa.cutoff_utc(kickoff)
    available_ids, undated = audit.tsa.available_games(schedule, 2026, cutoff, TARGET)
    if undated:
        raise ValueError(f'cutoff has undated games: {undated}')
    available = set(available_ids)
    current = [row for row in rows if row['game_id'] in available]
    status_counts = audit.patch_2026_penalty_status(current)
    corrected_inputs = [row for row in current if row.get('_penalty_status_known') is not False]
    legacy_inputs = [dict(row, penalty=None) for row in current]
    team_games = collections.Counter()
    for game_id in available_ids:
        home, away = details[game_id]
        team_games[home] += 1
        team_games[away] += 1

    corrected, _ = audit.tsa.adapt(history, corrected_inputs, n0=4.0, team_games=dict(team_games))
    legacy, _ = audit.tsa.adapt(history, legacy_inputs, n0=4.0, team_games=dict(team_games))
    corrected_pool, corrected_excluded = audit.e1.build_pool(corrected_inputs)
    legacy_pool, legacy_excluded = audit.e1.build_pool(legacy_inputs)
    penalty_prefiltered = sum(
        row.get('penalty') == 1
        and (row.get('play_type') not in audit.e1.PLAY_TYPES
             or row.get('down') is None
             or not 1 <= row.get('down') <= 4)
        for row in corrected_inputs
    )
    teams = (('offense', 'MIN'), ('defense', 'MIN'), ('offense', 'BUF'), ('defense', 'BUF'))
    cell_rows = []
    for side, team in teams:
        team_field = 'posteam' if side == 'offense' else 'defteam'
        candidate_cells = set(corrected_pool) | set(legacy_pool)
        for cell in sorted(candidate_cells):
            corrected_support = sum(1 for event, row, _runoff, _spot in corrected_pool.get(cell, ())
                                    if event == 'sack' and row[team_field] == team)
            legacy_support = sum(1 for event, row, _runoff, _spot in legacy_pool.get(cell, ())
                                 if event == 'sack' and row[team_field] == team)
            if not corrected_support and not legacy_support:
                continue
            cell_name = audit.tt.cell_name(cell)
            corrected_ratio = corrected.ratios[side].get(team, {}).get(cell_name, {}).get('sack', 1.0)
            legacy_ratio = legacy.ratios[side].get(team, {}).get(cell_name, {}).get('sack', 1.0)
            cell_rows.append({
                'side': side, 'team': team, 'cell': list(cell),
                'corrected_ratio': corrected_ratio, 'legacy_null_ratio': legacy_ratio,
                'ratio_delta': corrected_ratio - legacy_ratio,
                'corrected_sack_support': corrected_support, 'legacy_sack_support': legacy_support,
            })
    cell_rows.sort(key=lambda row: abs(row['ratio_delta']), reverse=True)
    result = {
        'target_game_id': TARGET,
        'kickoff_utc': kickoff.isoformat(), 'pregame_cutoff_utc': cutoff.isoformat(),
        'source_database_sha256': db_sha, 'penalty_overlay_sha256': overlay_sha,
        'history_table_sha256': history.manifest['sha256'],
        'current_season': {
            'available_games': len(available_ids), 'available_database_rows': len(current),
            'source_penalty_status': dict(sorted(status_counts.items())),
            'corrected_adapter_input_rows': len(corrected_inputs),
            'corrected_adapter_excluded_unknown_rows': sum(row.get('_penalty_status_known') is False for row in current),
            'confirmed_penalty_rows_explicitly_rejected_by_e1_classifier': corrected_excluded.get(
                'penalty (not modelled)', 0),
            'confirmed_penalty_rows_prefiltered_before_e1_classifier': penalty_prefiltered,
            'legacy_adapter_input_rows': len(legacy_inputs),
            'legacy_pool_exclusions': dict(sorted(legacy_excluded.items())),
            'team_games': dict(sorted(team_games.items())),
        },
        'sack_event_team_ratio_cells': cell_rows,
        'largest_absolute_ratio_delta': max((abs(row['ratio_delta']) for row in cell_rows), default=0.0),
        'interpretation': 'Ratios are multiplicative team event weights within a selected dropback and situation cell. They are not final game sack probabilities. Current-season penalty correction is compared with the old all-null database behavior using the same cutoff and games.',
    }
    Path(OUT).write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('target_game_id', 'kickoff_utc', 'pregame_cutoff_utc',
                                              'current_season', 'largest_absolute_ratio_delta')},
                     sort_keys=True))


if __name__ == '__main__':
    main()
