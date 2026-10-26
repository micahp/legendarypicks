"""Build a reproducible, read-only NFL matchup and depth-chart snapshot.

The schedule is the version in force at the requested cutoff, the newest one observed on or
before it, and player rows are selected from each team's latest depth-chart artifact at or
before that cutoff. The raw scheduled date/time strings are preserved because
the source does not declare a timezone for ``gametime``.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path


SCHEMA = 'lp-nfl-pregame-snapshot-1'


def parse_as_of(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError) as exc:
        raise ValueError('--as-of must be an ISO-8601 timestamp with a timezone') from exc
    if parsed.tzinfo is None:
        raise ValueError('--as-of must include a timezone, for example 2026-10-25T12:00:00Z')
    return parsed.astimezone(timezone.utc)


def _utc(value: str | None, label: str) -> datetime:
    if not value:
        raise ValueError(f'{label} is missing')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def schedule_at(con: sqlite3.Connection, game_id: str, cutoff: datetime) -> dict | None:
    """The schedule row in force at ``cutoff``: the newest version observed on or before it.

    None when no version was observed by then. The caller must refuse. A later refresh
    must not be used instead, because it was not visible at the cutoff.
    """
    cur = con.execute(
        """SELECT game_id, season, game_type, week, gameday, gametime, away_team, home_team,
                  location, source, observed_at AS ingested_at
             FROM nfl_schedule_versions WHERE game_id=? AND observed_at<=?
            ORDER BY observed_at DESC LIMIT 1""",
        (game_id, cutoff.strftime('%Y-%m-%d %H:%M:%S')))
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([d[0] for d in cur.description], row))


def _canonical_hash(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def reseal(snapshot: dict) -> dict:
    """Recompute the content hash after adding a measured model input fingerprint."""
    snapshot.pop('snapshot_sha256', None)
    snapshot['snapshot_sha256'] = _canonical_hash(snapshot)
    return snapshot


def load_frozen_snapshot(path: str) -> dict:
    """Load a hash-verified snapshot file or game payload containing one."""
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'cannot read frozen snapshot JSON: {exc}') from exc
    snapshot = payload.get('pregame_snapshot', payload) if isinstance(payload, dict) else None
    if not isinstance(snapshot, dict) or snapshot.get('schema') != SCHEMA:
        raise ValueError('frozen input must contain a supported pregame snapshot')
    expected = snapshot.get('snapshot_sha256')
    body = {key: value for key, value in snapshot.items() if key != 'snapshot_sha256'}
    if not isinstance(expected, str) or expected != _canonical_hash(body):
        raise ValueError('frozen pregame snapshot hash does not match its content')
    schedule = snapshot.get('schedule')
    required = ('game_id', 'season', 'week', 'game_type', 'home_team', 'away_team', 'scheduled_kickoff_utc')
    if not isinstance(schedule, dict) or any(schedule.get(key) is None for key in required):
        raise ValueError('frozen pregame snapshot has incomplete game identity')
    if not isinstance(snapshot.get('model_reference'), dict):
        raise ValueError('frozen pregame snapshot has no model reference block')
    rosters = snapshot.get('rosters')
    if not isinstance(rosters, dict):
        raise ValueError('frozen pregame snapshot has no roster block')
    for side in ('home', 'away'):
        roster = rosters.get(side)
        if (not isinstance(roster, dict) or roster.get('team') != schedule[f'{side}_team']
                or not isinstance(roster.get('players'), list)):
            raise ValueError(f'frozen pregame snapshot has an invalid {side} roster')
    cutoff = parse_as_of(snapshot.get('as_of'))
    kickoff = schedule.get('scheduled_kickoff_utc')
    if kickoff and cutoff >= parse_as_of(kickoff):
        raise ValueError('frozen pregame snapshot cutoff is not before scheduled kickoff')
    return snapshot


def apply_full_depth_roster_snapshot(snapshot: dict, roster_path: str, provenance_path: str) -> dict:
    """Replace partial rosters with the hash-pinned full depth chart, including backups and starter flags."""
    raw = Path(roster_path).read_bytes()
    roster_sha = hashlib.sha256(raw).hexdigest()
    full_depth = json.loads(raw)
    provenance = json.loads(Path(provenance_path).read_text())
    output = provenance.get('output', {})
    if output.get('file') != Path(roster_path).name or output.get('sha256') != roster_sha:
        raise ValueError('full depth roster file does not match its provenance pin')
    if full_depth.get('schema') != 'lp-nfl-full-depth-roster-snapshot-1':
        raise ValueError('unsupported full depth roster schema')
    if provenance.get('schema') != 'lp-nfl-full-depth-roster-provenance-1':
        raise ValueError('unsupported full depth roster provenance schema')
    starter_builder = provenance.get('starter_builder', {})
    if (starter_builder.get('repository') != 'micahp/legendarypicks'
            or starter_builder.get('branch') != 'feat/nfl-roster-full-depth-2026-10-26'
            or starter_builder.get('commit') != '4ee931a4379567978d87491b3c0e4ae55055b8b9'
            or starter_builder.get('file') != 'backend/build_nfl_starters_snapshot.py'
            or starter_builder.get('file_sha256') != '7fe1923608c5bd72396fe3dff52020a9df9697d97935959a8f32cd727060738e'):
        raise ValueError('full depth roster does not retain the pinned starter-builder provenance')
    full_builder = provenance.get('full_depth_builder', {})
    builder_file = Path(__file__).resolve().parents[2] / 'scripts/nfl_sequence/build_full_depth_roster_snapshot.py'
    if (full_builder.get('repository') != 'micahp/legendarypicks'
            or full_builder.get('file') != 'scripts/nfl_sequence/build_full_depth_roster_snapshot.py'
            or full_builder.get('file_sha256') != hashlib.sha256(builder_file.read_bytes()).hexdigest()
            or full_builder.get('worktree_dirty') is not False):
        raise ValueError('full depth roster builder code does not match its clean provenance pin')
    if full_depth.get('starter_snapshot_sha256') != provenance.get('starter_snapshot', {}).get('sha256'):
        raise ValueError('full depth roster was built from a different pinned starter snapshot')

    cutoff = _utc(snapshot['as_of'], 'snapshot as_of')
    source_artifacts = provenance.get('source_artifacts', [])
    if len(source_artifacts) != 2:
        raise ValueError('full depth provenance must pin both nflverse input artifacts')
    for artifact in source_artifacts:
        if not artifact.get('sha256') or len(artifact['sha256']) != 64:
            raise ValueError('nflverse source artifact is missing a SHA-256 pin')
        if _utc(artifact.get('last_modified_utc'), 'source last_modified_utc') > cutoff:
            raise ValueError('nflverse source artifact was published after the frozen pregame cutoff')

    sides = {'away': snapshot['schedule']['away_team'], 'home': snapshot['schedule']['home_team']}
    min_rows = {'away': 22, 'home': 21}
    frozen_rosters = {}
    for side, team in sides.items():
        entry = full_depth.get('rosters', {}).get(side)
        if not entry or entry.get('team') != team:
            raise ValueError(f'{side} full depth roster team does not match the frozen schedule')
        depth_date = entry.get('depth_chart_dt')
        if _utc(depth_date, f'{team} depth_chart_dt') > cutoff:
            raise ValueError(f'{team} depth chart was published after the frozen pregame cutoff')
        if entry.get('jersey_week') != snapshot['schedule']['week']:
            raise ValueError(f'{team} jersey numbers are not pinned to the frozen game week')
        if entry.get('missing'):
            raise ValueError(f'{team} full depth roster contains unfilled data')
        players = entry.get('players', [])
        if len(players) < max(min_rows[side], 29):
            raise ValueError(f'{team} full depth roster dropped backups or depth-chart rows')
        if output.get('role_row_counts', {}).get(team) != len(players):
            raise ValueError(f'{team} role-row count differs from the pinned full depth manifest')
        if output.get('unique_player_counts', {}).get(team) != len({p.get('gsis_id') for p in players}):
            raise ValueError(f'{team} unique-player count differs from the pinned full depth manifest')
        if output.get('starter_role_counts', {}).get(team) != 28:
            raise ValueError(f'{team} manifest must pin 28 starting roles')
        role_keys = set()
        player_identity = {}
        starter_count = 0
        for player in players:
            gsis_id = player.get('gsis_id')
            role_key = (player.get('group'), player.get('pos_abb'), player.get('pos_rank'))
            if not gsis_id:
                raise ValueError(f'{team} full depth roster has a missing GSIS id')
            if player.get('player_id') is None:
                raise ValueError(f'{team} full depth roster has a missing LP player id')
            if player.get('jersey_number') is None:
                raise ValueError(f'{team} full depth roster has a missing jersey number')
            if not player.get('group') or not player.get('pos_abb') or not isinstance(player.get('pos_rank'), int) or player['pos_rank'] < 1:
                raise ValueError(f'{team} full depth roster has an incomplete position/rank')
            if not isinstance(player.get('starter'), bool):
                raise ValueError(f'{team} full depth roster must flag every starter role and backup')
            if role_key in role_keys:
                raise ValueError(f'{team} full depth roster has a duplicate position/rank role')
            identity = (player['player_id'], player.get('player_name'), player['jersey_number'])
            if gsis_id in player_identity and player_identity[gsis_id] != identity:
                raise ValueError(f'{team} full depth roster has conflicting rows for one GSIS id')
            role_keys.add(role_key)
            player_identity[gsis_id] = identity
            starter_count += int(player['starter'])
        if starter_count != 28:
            raise ValueError(f'{team} full depth roster must mark exactly 28 starter roles')
        frozen_rosters[side] = {
            'team': team, 'snapshot_at': depth_date, 'source': full_depth['source'],
            'depth_chart_dt': depth_date, 'defense_group': entry['defense_group'],
            'jersey_week': entry['jersey_week'], 'missing': [], 'players': players,
        }

    snapshot['rosters'] = frozen_rosters
    snapshot['roster_snapshot_id'] = f"nflverse-full-depth:{_canonical_hash(frozen_rosters)}"
    snapshot['roster_snapshot_source'] = {
        'provenance': provenance, 'full_depth_roster_sha256': roster_sha,
    }
    return reseal(snapshot)


def build(db: str, game_id: str, as_of: str, kickoff_utc: str | None = None,
          kickoff_source_url: str | None = None) -> dict:
    cutoff = parse_as_of(as_of)
    scheduled_start = parse_as_of(kickoff_utc) if kickoff_utc else None
    if bool(scheduled_start) != bool(kickoff_source_url):
        raise ValueError('--kickoff-utc and --kickoff-source-url must be supplied together')
    if scheduled_start and cutoff >= scheduled_start:
        raise ValueError('--as-of must precede the verified scheduled kickoff')
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        game = schedule_at(con, game_id, cutoff)
        if game is None:
            raise ValueError(f'{game_id}: no schedule version was observed on or before --as-of')
        if game['game_type'] not in ('REG', 'POST'):
            raise ValueError(f'{game_id}: unsupported game type {game["game_type"]!r}')
        if not game['gameday'] or not game['gametime']:
            raise ValueError(f'{game_id}: scheduled date and time are required')
        if scheduled_start is None and date.fromisoformat(game['gameday']) <= cutoff.date():
            raise ValueError(f'{game_id}: as-of date must precede scheduled game day')
        teams ={'away': game['away_team'], 'home': game['home_team']}
        if not all(teams.values()) or teams['away'] == teams['home']:
            raise ValueError(f'{game_id}: schedule must contain two distinct team abbreviations')
        rosters = {}
        for side, team in teams.items():
            rows = con.execute(
                """SELECT player_id, gsis_id, player_name, team, pos_abb, pos_rank,
                          snapshot_at, source
                     FROM nfl_depth_chart
                    WHERE season=? AND team=? AND player_id IS NOT NULL
                      AND gsis_id IS NOT NULL AND pos_rank > 0
                      AND snapshot_at IS NOT NULL
                    ORDER BY snapshot_at DESC, pos_abb, pos_rank, gsis_id""",
                (game['season'], team),
            ).fetchall()
            eligible = [row for row in rows if _utc(row['snapshot_at'], f'{team} snapshot_at') <= cutoff]
            if not eligible:
                raise ValueError(f'{game_id}: no pregame depth-chart rows for {team} by {cutoff.isoformat()}')
            latest_time = max(_utc(row['snapshot_at'], f'{team} snapshot_at') for row in eligible)
            latest = next(row['snapshot_at'] for row in eligible
                          if _utc(row['snapshot_at'], f'{team} snapshot_at') == latest_time)
            selected = [dict(row) for row in eligible
                        if _utc(row['snapshot_at'], f'{team} snapshot_at') == latest_time]
            positions = {row['pos_abb'] for row in selected}
            qb1 = [row for row in selected if row['pos_abb'] == 'QB' and row['pos_rank'] == 1]
            if len(qb1) != 1:
                raise ValueError(f'{game_id}: {team} snapshot {latest} must have exactly one QB1')
            rb1 = [row for row in selected if row['pos_abb'] == 'RB' and row['pos_rank'] == 1]
            if len(rb1) != 1:
                raise ValueError(f'{game_id}: {team} snapshot {latest} must have exactly one RB1')
            if not positions.intersection({'WR', 'TE', 'RB', 'FB'}):
                raise ValueError(f'{game_id}: {team} snapshot {latest} has no receiving options')
            rosters[side] = {
                'team': team,
                'snapshot_at': latest,
                'source': selected[0]['source'],
                'players': selected,
            }
    finally:
        con.close()

    snapshot = {
        'schema': SCHEMA,
        'as_of': cutoff.isoformat().replace('+00:00', 'Z'),
        'roster_snapshot_id': f"nfl-depth-chart:{_canonical_hash(rosters)}",
        'schedule': {
            'game_id': game['game_id'], 'season': game['season'], 'game_type': game['game_type'],
            'week': game['week'], 'gameday': game['gameday'], 'gametime': game['gametime'],
            'gametime_timezone': None, 'away_team': game['away_team'], 'home_team': game['home_team'],
            'source': game['source'], 'ingested_at': game['ingested_at'],
            'scheduled_kickoff_utc': scheduled_start.isoformat().replace('+00:00', 'Z') if scheduled_start else None,
            'kickoff_source_url': kickoff_source_url,
        },
        'rosters': rosters,
        'model_reference': {
            'play_pool': 'nfl_pbp seasons 2022-2025, weeks 1-18; empirical E1 cell sampler',
            'rule_version': 'NFL-2026-GAME-STATE-RULES.md / E2 successor rules matrix',
            'participant_assignment_version': 'pregame-role-usage-v1',
        },
    }
    return reseal(snapshot)
