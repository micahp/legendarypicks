"""Apply a frozen weekly availability snapshot to a pregame snapshot's full-depth rosters.

The availability snapshot (lp-nfl-weekly-availability-snapshot-1, avail-rules-v1) decides for each rostered player
whether they are in the game-day pool. This module applies that decision to a pregame snapshot whose rosters already
come from the pinned full depth chart:

  include = False   removed from the roster; recorded in the availability block with its decision
  include = True    kept; its flags (questionable, missing_report, unknown_status) are copied onto the player
  removed starter   the best available non-starter at the same group and position takes the starting role

It refuses rather than guesses. A hash that does not verify, a season or week mismatch, a snapshot frozen after the
pregame cutoff, a depth-chart player with no row in the snapshot, or a starting role with no available backup each
raise ValueError before the snapshot is changed.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nfl_team_codes  # noqa: E402
import pregame_snapshot

SCHEMA = 'lp-nfl-weekly-availability-snapshot-1'
RULE_VERSION = 'avail-rules-v1'
STARTER_ROLES = 28
# Kept as an import-compatible alias; the directional mapping is defined centrally.
DB_TO_NFLVERSE = nfl_team_codes.NFLVERSE_TEAM_CODE_ALIASES


def _canonical_sha(body: dict) -> str:
    text = json.dumps(body, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def load(path: str) -> tuple[dict, str]:
    """Return (snapshot, content_sha256) after verifying the content hash and schema."""
    snapshot = json.loads(Path(path).read_text())
    if snapshot.get('schema') != SCHEMA:
        raise ValueError(f'{path}: not a {SCHEMA} availability snapshot')
    if snapshot.get('rule_version') != RULE_VERSION:
        raise ValueError(f'{path}: unsupported availability rule version {snapshot.get("rule_version")!r}')
    body = {key: value for key, value in snapshot.items() if key not in ('snapshot_id', 'content_sha256')}
    digest = _canonical_sha(body)
    if snapshot.get('content_sha256') != digest:
        raise ValueError(f'{path}: availability snapshot content does not match its hash')
    if not str(snapshot.get('snapshot_id', '')).endswith(digest[:10]):
        raise ValueError(f'{path}: snapshot id does not carry the content hash')
    return snapshot, digest


def select(store_dir: str, season: int, week: int, as_of: str) -> str:
    """Path of the newest availability snapshot for season and week frozen at or before the cutoff."""
    index = Path(store_dir) / 'index.jsonl'
    if not index.exists():
        raise ValueError(f'no availability index at {index}')
    cutoff = pregame_snapshot.parse_as_of(as_of)
    prefix = f'nfl-{season}-w{week:02d}-'
    candidates = []
    for line in index.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if not str(entry.get('snapshot_id', '')).startswith(prefix):
            continue
        frozen = pregame_snapshot.parse_as_of(entry['freeze_time_utc'])
        if frozen <= cutoff:
            candidates.append((frozen, entry['path']))
    if not candidates:
        raise ValueError(f'no availability snapshot for {season} week {week} frozen by {as_of}')
    return max(candidates)[1]


def _role(player: dict) -> dict:
    return {'group': player.get('group'), 'pos_abb': player.get('pos_abb'), 'pos_rank': player.get('pos_rank')}


def apply(snapshot: dict, availability_path: str) -> dict:
    """Apply the availability decisions to snapshot in place, reseal it, and return the availability block."""
    if 'roster_snapshot_source' not in snapshot:
        raise ValueError('availability needs the pinned full-depth roster: pass --roster-snapshot and --roster-provenance')
    avail, digest = load(availability_path)
    schedule = snapshot['schedule']
    if (avail['season'], avail['week']) != (schedule['season'], schedule['week']):
        raise ValueError('availability snapshot season or week does not match the frozen game')
    cutoff = pregame_snapshot.parse_as_of(snapshot['as_of'])
    frozen_at = pregame_snapshot.parse_as_of(avail['freeze_time_utc'])
    if frozen_at > cutoff:
        raise ValueError('availability snapshot was frozen after the pregame cutoff')

    rows = {(player['team'], player['gsis_id']): player for player in avail['players']}
    unmatched = []
    for side in ('home', 'away'):
        team = snapshot['rosters'][side]['team']
        avail_team = nfl_team_codes.to_nflverse_team_code(team)
        for player in snapshot['rosters'][side]['players']:
            if (avail_team, player['gsis_id']) not in rows:
                unmatched.append(f"{team} {player.get('player_name')} ({player['gsis_id']})")
    if unmatched:
        raise ValueError(f'{len(unmatched)} depth-chart players have no row in the availability snapshot: '
                         f'{unmatched[:5]}')

    removed, promoted, team_counts = [], [], {}
    flag_counts = Counter()
    designations_seen = False
    for side in ('home', 'away'):
        roster = snapshot['rosters'][side]
        team = roster['team']
        avail_team = nfl_team_codes.to_nflverse_team_code(team)
        kept = []
        for player in roster['players']:
            row = rows[(avail_team, player['gsis_id'])]
            if row.get('designation') is not None:
                designations_seen = True
            if not row['include']:
                removed.append({'team': team, 'gsis_id': player['gsis_id'], 'player_name': player.get('player_name'),
                                'decision': row['decision'], 'reason': row['reason'],
                                'starter_roles': [_role(player)] if player.get('starter') else []})
                continue
            player['availability'] = {'decision': row['decision'], 'designation': row['designation'],
                                      'flags': list(row['flags'])}
            flag_counts.update(row['flags'])
            kept.append(player)

        team_promotions = 0
        for gone in [r for r in removed if r['team'] == team and r['starter_roles']]:
            for role in gone['starter_roles']:
                backups = sorted(
                    (p for p in kept if not p.get('starter') and p.get('group') == role['group']
                     and p.get('pos_abb') == role['pos_abb']),
                    key=lambda p: p['pos_rank'])
                if not backups:
                    raise ValueError(f"{team} has no available backup for {role['pos_abb']} {role['pos_rank']} "
                                     f"after {gone['player_name']} was removed")
                chosen = backups[0]
                chosen['starter'] = True
                # The simulator identifies the starting passer, and other starters, by pos_rank == 1 or by role rank.
                # A promoted backup takes the removed starter's rank so that its role is found where the simulator looks.
                chosen['rank_before_promotion'] = chosen['pos_rank']
                chosen['pos_rank'] = role['pos_rank']
                chosen['promoted_for'] = {'gsis_id': gone['gsis_id'], 'player_name': gone['player_name'],
                                          'decision': gone['decision'], 'role': role}
                promoted.append({'team': team, 'gsis_id': chosen['gsis_id'], 'player_name': chosen.get('player_name'),
                                 'pos_abb': role['pos_abb'], 'pos_rank': chosen['pos_rank'],
                                 'rank_before_promotion': chosen['rank_before_promotion'],
                                 'replaces': gone['gsis_id']})
                team_promotions += 1
        roster['players'] = kept
        starters = sum(1 for p in kept if p.get('starter'))
        if starters != STARTER_ROLES:
            raise ValueError(f'{team} has {starters} starting roles after availability; expected {STARTER_ROLES}')
        team_counts[team] = {'removed_players': len({r['gsis_id'] for r in removed if r['team'] == team}),
                             'promoted_roles': team_promotions, 'kept_role_rows': len(kept),
                             'starter_roles': starters}

    block = {
        'snapshot_id': avail['snapshot_id'], 'content_sha256': digest, 'path': str(Path(availability_path)),
        'rule_version': RULE_VERSION, 'season': avail['season'], 'week': avail['week'],
        'freeze_time_utc': avail['freeze_time_utc'],
        'applied_to_roster_snapshot_id': snapshot.get('roster_snapshot_id'),
        'classification': 'timestamp-proxy' if designations_seen else 'unverifiable',
        'classification_note': ('an injury designation exists for at least one rostered player; capture time is an '
                                'observation time, not a publication time' if designations_seen else
                                'no injury designation exists for these teams in the availability snapshot; '
                                'missing-report flags are the only injury evidence'),
        'counts': {'removed_role_rows': len(removed),
                   'removed_players': len({r['gsis_id'] for r in removed}),
                   'promoted_starter_roles': len(promoted), 'flags': dict(flag_counts)},
        'teams': team_counts, 'removed': removed, 'promoted': promoted,
    }
    snapshot['availability'] = block
    pregame_snapshot.reseal(snapshot)
    return block
