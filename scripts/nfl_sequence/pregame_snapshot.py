"""Build a reproducible, read-only NFL matchup and depth-chart snapshot.

The schedule is accepted only when it was ingested before the requested cutoff,
and player rows are selected from each team's latest depth-chart artifact at or
before that cutoff. The raw scheduled date/time strings are preserved because
the source does not declare a timezone for ``gametime``.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone


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


def _canonical_hash(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def reseal(snapshot: dict) -> dict:
    """Recompute the content hash after adding a measured model input fingerprint."""
    snapshot.pop('snapshot_sha256', None)
    snapshot['snapshot_sha256'] = _canonical_hash(snapshot)
    return snapshot


def build(db: str, game_id: str, as_of: str) -> dict:
    cutoff = parse_as_of(as_of)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        game = con.execute(
            """SELECT game_id, season, game_type, week, gameday, gametime, away_team,
                      home_team, source, ingested_at
                 FROM nfl_schedule WHERE game_id=?""", (game_id,)
        ).fetchone()
        if game is None:
            raise ValueError(f'schedule has no game_id {game_id!r}')
        if game['game_type'] not in ('REG', 'POST'):
            raise ValueError(f'{game_id}: unsupported game type {game["game_type"]!r}')
        if not game['gameday'] or not game['gametime']:
            raise ValueError(f'{game_id}: scheduled date and time are required')
        if date.fromisoformat(game['gameday']) <= cutoff.date():
            raise ValueError(f'{game_id}: as-of date must precede scheduled game day')
        schedule_ingested = _utc(game['ingested_at'], 'schedule ingested_at')
        if schedule_ingested > cutoff:
            raise ValueError(f'{game_id}: schedule row was ingested after --as-of')

        teams = {'away': game['away_team'], 'home': game['home_team']}
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
            if not any(row['pos_abb'] == 'QB' and row['pos_rank'] == 1 for row in selected):
                raise ValueError(f'{game_id}: {team} snapshot {latest} has no QB1')
            if not any(row['pos_abb'] == 'RB' and row['pos_rank'] == 1 for row in selected):
                raise ValueError(f'{game_id}: {team} snapshot {latest} has no RB1')
            if not positions.intersection({'WR', 'TE', 'FB'}):
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
        'schedule': {
            'game_id': game['game_id'], 'season': game['season'], 'game_type': game['game_type'],
            'week': game['week'], 'gameday': game['gameday'], 'gametime': game['gametime'],
            'gametime_timezone': None, 'away_team': game['away_team'], 'home_team': game['home_team'],
            'source': game['source'], 'ingested_at': game['ingested_at'],
        },
        'rosters': rosters,
        'model_reference': {
            'play_pool': 'nfl_pbp seasons 2022-2025, weeks 1-18; empirical E1 cell sampler',
            'rule_version': 'NFL-2026-GAME-STATE-RULES.md / E2 successor rules matrix',
        },
    }
    return reseal(snapshot)
