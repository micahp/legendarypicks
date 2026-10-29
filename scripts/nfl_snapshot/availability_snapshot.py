#!/usr/bin/env python3
"""Immutable NFL availability snapshot for projections and simulations.

One snapshot per (season, week, freeze time). It records the games, the roster basis, the injury designations
observed before the freeze time, the availability decision for every rostered player, and the source provenance.
Snapshots are written once to a store directory outside the repository and never rewritten. A new freeze time gives a
new snapshot ID; the earlier snapshot stays as it was.

Rules (avail-rules-v1), applied per player on the exact (team, GSIS) key:
  Out                          exclude
  Doubtful                     exclude
  Questionable                 include, flag questionable (normal conditional projection, no probability discount)
  Note (no game status)        include
  no injury row                include, flag missing_report
  present row, null status     include, flag unknown_status (missing data is not treated as an injury)
  roster status not ACT/INA   exclude (IR, suspended, cut, practice squad, exempt, retired and similar)
  roster status INA            used only as roster membership; never as evidence of game-day availability
  official inactive list       not used here: no official list exists before it is published. The snapshot
                               records official_inactive as 'not_yet_published'.

Source freshness: injury observations are taken only if observed at or before the freeze time. The snapshot records the
age of the newest injury observation and states whether a capture ran within MAX_GAP_HOURS of the freeze time.

Usage:
  python3 availability_snapshot.py --season 2026 --week 8 --roster-file ROSTER.parquet \
      --injury-store /path/injury_snapshots.sqlite --db /root/legendarypicks/backend/data/picks.db \
      [--freeze-time 2026-10-27T18:00:00+00:00] [--store-dir /root/lp-snapshots/nfl]
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

import pandas as pd

RULE_VERSION = 'avail-rules-v1'
SCHEMA = 'lp-nfl-weekly-availability-snapshot-1'
MAX_GAP_HOURS = 6
DEFAULT_STORE = '/root/lp-snapshots/nfl'
ELIGIBLE_ROSTER_STATUS = ('ACT', 'INA')
DB_TO_NFLVERSE = {'LAR': 'LA', 'WSH': 'WAS'}


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str)


def sha256_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def decide(designation, roster_status, has_row):
    """Return (include: bool, decision: str, flags: list, reason: str)."""
    if roster_status not in ELIGIBLE_ROSTER_STATUS:
        return False, 'exclude_roster_status', [], f'roster status {roster_status} is not an active-roster status'
    if not has_row:
        return True, 'include_missing_report', ['missing_report'], 'no injury report line on the exact key'
    if designation is None:
        return True, 'include_unknown_status', ['unknown_status'], 'injury row present with null status'
    if designation == 'Out':
        return False, 'exclude_out', [], 'Out'
    if designation == 'Doubtful':
        return False, 'exclude_doubtful', [], 'Doubtful'
    if designation == 'Questionable':
        return True, 'include_questionable', ['questionable'], 'Questionable: normal conditional projection'
    return True, 'include', [], f'designation {designation}'


def kickoff_utc(gameday, gametime):
    local = pd.Timestamp(f'{gameday} {gametime or "13:00"}').tz_localize('America/New_York')
    return local.tz_convert('UTC').isoformat()


def build(args):
    freeze = args.freeze_time or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    freeze_ts = pd.Timestamp(freeze)
    if freeze_ts.tzinfo is None:
        raise SystemExit('freeze time must be timezone-qualified')
    freeze_utc = freeze_ts.tz_convert('UTC').isoformat()

    # schedule: published game rows for the target week, from the database (read-only)
    db = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    games = pd.read_sql("select game_id, season, game_type, week, gameday, gametime, home_team, away_team, "
                        "ingested_at from nfl_schedule where season=? and week=?", db, params=(args.season, args.week))
    if games.empty:
        raise SystemExit(f'no scheduled games for {args.season} week {args.week}')
    schedule_ingested = games.ingested_at.max()

    # roster basis: the file's rows for the target week; fall back to the newest published week, and say so
    roster = pd.read_parquet(args.roster_file, columns=['season', 'game_type', 'week', 'team', 'gsis_id', 'full_name',
                                                        'position', 'status'])
    roster = roster[(roster.season == args.season) & (roster.game_type == 'REG') & roster.gsis_id.notna()].copy()
    published = sorted(int(w) for w in roster.week.unique())
    roster_week = args.week if args.week in published else max(published)
    roster = roster[roster.week == roster_week].drop_duplicates(['team', 'gsis_id'])
    roster['team'] = roster.team.replace(DB_TO_NFLVERSE)

    # injuries: newest observation per exact key at or before the freeze time, from the append-only capture store
    store = sqlite3.connect(f'file:{args.injury_store}?mode=ro', uri=True)
    last_run = store.execute("select max(observed_at_utc) from snapshot_runs "
                             "where status='ok' and season=? and observed_at_utc <= ?",
                             (args.season, freeze_utc)).fetchone()[0]
    inj = pd.read_sql("select r.team, r.gsis_id, r.report_status, r.observed_at_utc, r.date_modified_as_published "
                      "from injury_snapshot_rows r where r.season=? and r.week=? and r.observed_at_utc <= ? "
                      "and r.row_id = (select max(x.row_id) from injury_snapshot_rows x where x.season=r.season "
                      "and x.game_type=r.game_type and x.week=r.week and x.team=r.team and x.gsis_id=r.gsis_id "
                      "and x.observed_at_utc <= ?)",
                      store, params=(args.season, args.week, freeze_utc, freeze_utc))
    inj['team'] = inj.team.replace(DB_TO_NFLVERSE)
    inj = inj.drop_duplicates(['team', 'gsis_id'], keep='last')
    keyed = {(r.team, r.gsis_id): r for r in inj.itertuples(index=False)}

    # depth roles: newest depth observation per GSIS at or before the freeze time, from the database
    depth = pd.read_sql("select team, gsis_id, pos_abb, pos_rank, snapshot_at from nfl_depth_chart "
                        "where season=? and snapshot_at <= ?", db, params=(args.season, freeze_utc))
    depth = depth.sort_values('snapshot_at').drop_duplicates(['team', 'gsis_id'], keep='last')
    depth_by = {(r.team, r.gsis_id): r for r in depth.itertuples(index=False)}

    players = []
    for r in roster.itertuples(index=False):
        inj_row = keyed.get((r.team, r.gsis_id))
        designation = None
        observed = None
        if inj_row is not None:
            designation = inj_row.report_status if isinstance(inj_row.report_status, str) else None
            observed = inj_row.observed_at_utc
        include, decision, flags, reason = decide(designation, r.status, inj_row is not None)
        d = depth_by.get((r.team, r.gsis_id))
        players.append({
            'team': r.team, 'gsis_id': r.gsis_id, 'name': r.full_name, 'position': r.position,
            'roster_status': r.status, 'roster_basis_week': roster_week,
            'designation': designation if designation is not None else ('NULL' if inj_row is not None else None),
            'designation_observed_at_utc': observed,
            'official_inactive': 'not_yet_published',
            'depth_pos': None if d is None else d.pos_abb, 'depth_rank': None if d is None else int(d.pos_rank),
            'depth_snapshot_at': None if d is None else d.snapshot_at,
            'include': include, 'decision': decision, 'flags': flags, 'reason': reason,
        })

    newest_injury = inj.observed_at_utc.max() if len(inj) else None
    gap_ok = bool(last_run) and (freeze_ts - pd.Timestamp(last_run)) <= pd.Timedelta(hours=MAX_GAP_HOURS)
    body = {
        'schema': SCHEMA, 'rule_version': RULE_VERSION, 'season': args.season, 'week': args.week,
        'freeze_time_utc': freeze_utc,
        'games': [{'game_id': g.game_id, 'game_type': g.game_type, 'home_team': g.home_team,
                   'away_team': g.away_team, 'kickoff_utc': kickoff_utc(g.gameday, g.gametime)}
                  for g in games.itertuples(index=False)],
        'players': players,
        'provenance': {
            'roster_file': os.path.basename(args.roster_file), 'roster_file_sha256': sha256_file(args.roster_file),
            'roster_basis_week': roster_week, 'roster_published_weeks': published,
            'roster_target_week_published': args.week in published,
            'injury_store': os.path.basename(args.injury_store), 'injury_store_last_run_utc': last_run,
            'injury_newest_observation_utc': newest_injury,
            'injury_capture_within_gap': gap_ok, 'max_gap_hours': MAX_GAP_HOURS,
            'database': os.path.basename(args.db), 'schedule_ingested_at': schedule_ingested,
            'depth_chart_rows_used': int(len(depth)),
            'official_inactives': 'not_yet_published',
        },
        'counts': {
            'players': len(players),
            'included': sum(1 for p in players if p['include']),
            'excluded': sum(1 for p in players if not p['include']),
            'questionable_included': sum(1 for p in players if 'questionable' in p['flags']),
            'missing_report_included': sum(1 for p in players if 'missing_report' in p['flags']),
            'unknown_status_included': sum(1 for p in players if 'unknown_status' in p['flags']),
        },
    }
    content_hash = sha256_text(canonical(body))
    snapshot_id = f"nfl-{args.season}-w{args.week:02d}-{freeze_ts.strftime('%Y%m%dT%H%M%SZ')}-{content_hash[:10]}"
    body['snapshot_id'] = snapshot_id
    body['content_sha256'] = content_hash
    os.makedirs(args.store_dir, exist_ok=True)
    path = os.path.join(args.store_dir, snapshot_id + '.json')
    if os.path.exists(path):
        raise SystemExit(f'snapshot exists and is never rewritten: {path}')
    with open(path, 'w') as handle:
        handle.write(json.dumps(body, indent=1, sort_keys=True) + '\n')
    os.chmod(path, 0o444)
    with open(os.path.join(args.store_dir, 'index.jsonl'), 'a') as handle:
        handle.write(json.dumps({'snapshot_id': snapshot_id, 'path': path, 'content_sha256': content_hash,
                                 'freeze_time_utc': body['freeze_time_utc'], 'counts': body['counts']},
                                sort_keys=True) + '\n')
    return body, path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--week', type=int, required=True)
    ap.add_argument('--roster-file', required=True)
    ap.add_argument('--injury-store', required=True)
    ap.add_argument('--db', required=True)
    ap.add_argument('--freeze-time', default=None)
    ap.add_argument('--store-dir', default=DEFAULT_STORE)
    args = ap.parse_args()
    body, path = build(args)
    print(json.dumps({'snapshot_id': body['snapshot_id'], 'path': path, 'content_sha256': body['content_sha256'],
                      'counts': body['counts'], 'roster_basis_week': body['provenance']['roster_basis_week'],
                      'injury_capture_within_gap': body['provenance']['injury_capture_within_gap'],
                      'injury_store_last_run_utc': body['provenance']['injury_store_last_run_utc']}, indent=1))


if __name__ == '__main__':
    main()
