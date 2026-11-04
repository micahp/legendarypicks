"""Validation for explicitly retrospective, archive-backed pregame snapshots.

This path is separate from pregame_capture. It proves that exact archived bytes were published before a recorded cutoff;
it does not claim that Legendary Picks captured those bytes at the time.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = 'lp-nfl-historical-archive-reconstruction-1'
MODE = 'retrospective_archive_reconstruction'
SECONDARY_CLASSES = ('exploratory reconstruction', 'refused')
ASSETS = {
    'schedule': ('s', 'games.rds', 'schedule_sha256', 'schedule_observed_utc'),
    'depth': ('d', 'depth_charts_2026.rds', 'depth_sha256', 'depth_published_utc'),
    'roster': ('r', 'roster_weekly_2026.rds', 'roster_sha256', 'roster_published_utc'),
    'injury': ('i', 'injuries_2026.rds', 'injury_sha256', 'injury_published_utc'),
}


def _utc(value, label):
    if not value:
        raise ValueError(f'{label} is missing')
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'{label} is not an ISO-8601 timestamp') from exc
    if parsed.tzinfo is None:
        raise ValueError(f'{label} must include a timezone')
    return parsed.astimezone(timezone.utc)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def readiness_row(path, game_id, tier='primary'):
    """The game's readiness row, checked for its tier.

    primary: the 28 cutoff-valid Week 5-7 games with a recorded LP lock (the only tier for the primary comparison).
    secondary: the exploratory and refused Week 1-7 games, built and scored separately and always labelled as such."""
    with Path(path).open(newline='') as handle:
        rows = [row for row in csv.DictReader(handle) if row.get('game_id') == game_id]
    if len(rows) != 1:
        raise ValueError(f'{game_id}: readiness matrix must contain exactly one row (found {len(rows)})')
    row = rows[0]
    if tier == 'secondary':
        if row.get('readiness_class') not in SECONDARY_CLASSES:
            raise ValueError(f'{game_id}: the secondary tier holds only exploratory and refused readiness rows')
        if row.get('week') not in ('1', '2', '3', '4', '5', '6', '7'):
            raise ValueError(f'{game_id}: archive reconstruction is restricted to Weeks 1-7')
        return row
    if tier != 'primary':
        raise ValueError(f'{game_id}: unknown archive reconstruction tier {tier!r}')
    if row.get('readiness_class') != 'cutoff-valid':
        raise ValueError(f'{game_id}: only cutoff-valid readiness rows may enter the primary comparison')
    if row.get('cutoff_basis') != 'recorded LP lock':
        raise ValueError(f'{game_id}: archive reconstruction requires a recorded LP lock cutoff')
    if row.get('week') not in ('5', '6', '7'):
        raise ValueError(f'{game_id}: primary archive reconstruction is restricted to Weeks 5-7')
    if row.get('simulation_ready_with_committed_loader') == 'True':
        raise ValueError(f'{game_id}: readiness row unexpectedly describes the prospective loader')
    return row


def row_cutoff(row):
    """The cutoff text of a readiness row: the recorded LP lock, or kickoff minus one second where none was recorded."""
    if row.get('cutoff_basis') == 'recorded LP lock':
        return row['cutoff_utc']
    if not row.get('audit_boundary_utc'):
        raise ValueError(f"{row.get('game_id')}: readiness row has neither a recorded lock nor an audit boundary")
    return row['audit_boundary_utc']


def _asset_path(root, archive_tag, filename, expected_sha):
    archive_date = archive_tag[len('archive-'):] if archive_tag.startswith('archive-') else archive_tag
    candidates = [Path(root) / archive_tag / filename, Path(root) / filename]
    matches = []
    for path in candidates:
        if path.is_file() and _sha256(path) == expected_sha:
            matches.append(path)
    if not matches:
        raise ValueError(f'{archive_tag}/{filename}: no local file matches the pinned SHA-256 {expected_sha}')
    return matches[0], archive_date


def validate_snapshot(snapshot, *, readiness_matrix, archive_manifest, archive_root,
                      streak_file=None, expected_game_id=None):
    """Verify exact archive versions, bytes, cutoff, readiness row, and retrospective labels."""
    block = snapshot.get('archive_reconstruction')
    if not isinstance(block, dict) or block.get('schema') != SCHEMA or block.get('mode') != MODE:
        raise ValueError('snapshot is not an explicitly labelled historical archive reconstruction')
    if block.get('prospective_eligible') is not False:
        raise ValueError('archive reconstruction cannot be marked eligible for prospective forecasts')
    schedule = snapshot.get('schedule') or {}
    game_id = schedule.get('game_id')
    if not game_id or (expected_game_id and game_id != expected_game_id):
        raise ValueError('archive reconstruction game identity does not match the requested game')
    if snapshot.get('evaluation', {}).get('class') != MODE:
        raise ValueError('archive reconstruction must be labelled retrospective in evaluation metadata')
    if schedule.get('availability_classification') != MODE:
        raise ValueError('archive reconstruction schedule must retain its retrospective classification')

    tier = block.get('tier', 'primary')
    row = readiness_row(readiness_matrix, game_id, tier)
    matrix_sha = _sha256(readiness_matrix)
    if block.get('readiness_matrix_sha256') != matrix_sha:
        raise ValueError(f'{game_id}: readiness matrix does not match the snapshot pin')
    cutoff = _utc(snapshot.get('as_of'), 'snapshot cutoff')
    kickoff = _utc(schedule.get('scheduled_kickoff_utc'), 'scheduled kickoff')
    if cutoff >= kickoff:
        raise ValueError(f'{game_id}: archive cutoff is not before kickoff')
    if cutoff != _utc(row_cutoff(row), 'readiness cutoff'):
        raise ValueError(f'{game_id}: snapshot cutoff differs from the readiness cutoff')
    if kickoff != _utc(row.get('kickoff_utc'), 'readiness kickoff'):
        raise ValueError(f'{game_id}: snapshot kickoff differs from the readiness matrix')
    if (str(schedule.get('season')) != '2026' or str(schedule.get('week')) != row.get('week')
            or str(schedule.get('game_type')) != 'REG'):
        raise ValueError(f'{game_id}: snapshot season/week/type differs from its readiness row')
    parts = game_id.split('_')
    if len(parts) < 4 or (schedule.get('away_team'), schedule.get('home_team')) != (parts[-2], parts[-1]):
        raise ValueError(f'{game_id}: snapshot teams differ from the published game id')

    manifest_path = Path(archive_manifest)
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha != block.get('archive_manifest_sha256'):
        raise ValueError(f'{game_id}: archive manifest does not match the snapshot pin')

    builder_path = Path(__file__).with_name('build_historical_archive_snapshots.py')
    builder_sha = _sha256(builder_path)
    if block.get('builder_sha256') != builder_sha:
        raise ValueError(f'{game_id}: archive snapshot was produced by a different reconstruction builder')
    manifest = json.loads(manifest_bytes)
    archive_tag = row.get('archive_tag')
    archive_date = archive_tag[len('archive-'):] if archive_tag.startswith('archive-') else archive_tag
    release = manifest.get('archives', {}).get(archive_date)
    if not isinstance(release, dict):
        raise ValueError(f'{game_id}: archive tag {archive_tag!r} is missing from the pinned archive manifest')

    pinned = block.get('source_assets')
    if not isinstance(pinned, dict) or set(pinned) != set(ASSETS):
        raise ValueError(f'{game_id}: archive provenance must pin schedule, depth, roster, and injury assets')
    resolved = {}
    for name, (code, filename, matrix_hash_field, matrix_time_field) in ASSETS.items():
        source = pinned[name]
        if source is None and name == 'injury' and tier == 'secondary' and release.get(code) is None:
            resolved[name] = None  # this archive release published no injury file; the supplements below must cover it
            continue
        release_entry = release.get(code)
        if not isinstance(release_entry, list) or len(release_entry) != 2:
            raise ValueError(f'{game_id}: archive manifest has no {name} release entry')
        published_at, release_sha = release_entry
        expected_sha = row.get(matrix_hash_field)
        expected_published = row.get(matrix_time_field)
        if (source.get('file_name') != filename or source.get('archive_tag') != archive_tag
                or source.get('sha256') != expected_sha or source.get('sha256') != release_sha
                or source.get('published_at_utc') != published_at or published_at != expected_published):
            raise ValueError(f'{game_id}: {name} provenance does not match readiness and release manifests')
        if _utc(published_at, f'{name} archive publication') > cutoff:
            raise ValueError(f'{game_id}: {name} archive version was published after the game cutoff')
        path, _ = _asset_path(archive_root, archive_tag, filename, expected_sha)
        resolved[name] = {'path': f'{archive_tag}/{filename}', 'sha256': expected_sha,
                          'published_at_utc': published_at}

    supplements = block.get('injury_supplements') or {}
    if supplements and tier != 'secondary':
        raise ValueError(f'{game_id}: only the secondary tier may take an injury report from another archive release')
    if resolved['injury'] is None and set(supplements) != {'away', 'home'}:
        raise ValueError(f'{game_id}: the pinned release has no injury file and the supplements do not cover both teams')
    for side, supplement in supplements.items():
        if side not in ('away', 'home') or not isinstance(supplement, dict):
            raise ValueError(f'{game_id}: malformed injury supplement {side!r}')
        published = _utc(supplement.get('published_at_utc'), f'{side} injury supplement publication')
        if supplement.get('published_after_cutoff') is not (published > cutoff):
            raise ValueError(f'{game_id}: {side} injury supplement mislabels its publication relative to the cutoff')
        _asset_path(archive_root, supplement.get('archive_tag', ''), supplement.get('file_name', ''),
                              supplement.get('sha256'))
        if not supplement.get('rows'):
            raise ValueError(f'{game_id}: {side} injury supplement carries no rows')

    streak = block.get('streak_context')
    if not isinstance(streak, dict) or streak.get('game_id') != game_id:
        raise ValueError(f'{game_id}: missing frozen pregame streak provenance')
    if _utc(streak.get('cutoff_utc'), 'streak cutoff') != cutoff:
        raise ValueError(f'{game_id}: streak context cutoff differs from the recorded LP lock')
    if streak_file is None:
        raise ValueError(f'{game_id}: pass the pinned pregame streak file')
    streak_path = Path(streak_file)
    actual_streak_sha = _sha256(streak_path)
    if actual_streak_sha != streak.get('file_sha256'):
        raise ValueError(f'{game_id}: streak context does not match the snapshot pin')
    streak_payload = json.loads(streak_path.read_text())
    if (streak_payload.get('game_id') != game_id or streak_payload.get('cutoff_utc') != row_cutoff(row)
            or streak_payload.get('teams') != streak.get('teams')):
        raise ValueError(f'{game_id}: streak file identity/content differs from its snapshot provenance')
    return {
        'classification': MODE,
        'prospective': False,
        'tier': tier,
        'readiness_class': row['readiness_class'],
        'recorded_cutoff_utc': row_cutoff(row),
        'cutoff_basis': row.get('cutoff_basis'),
        'injury_supplements': {side: {k: v for k, v in sup.items() if k != 'rows'} for side, sup in supplements.items()},
        'kickoff_utc': row['kickoff_utc'],
        'archive_tag': archive_tag,
        'archive_manifest_sha256': manifest_sha,
        'readiness_matrix_sha256': matrix_sha,
        'builder_sha256': builder_sha,
        'source_assets': resolved,
        'streak_file_sha256': actual_streak_sha,
        'local_capture_observed_utc': None,
        'note': 'Retrospective archive reconstruction; official publication precedes cutoff, historical local capture is unverified.',
    }
