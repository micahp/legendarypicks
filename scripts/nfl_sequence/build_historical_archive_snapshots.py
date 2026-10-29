#!/usr/bin/env python3
"""Build retrospectively downloaded, source-time-verified Week 5-7 snapshots from nflverse RDS archives.

The builder uses one archive release at a time, writes each game atomically, and can resume after interruption. It does not
alter or relax pregame_capture's prospective acquisition-time checks.
"""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 backend environment
    import pytz

    ZoneInfo = pytz.timezone

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import historical_archive as archive  # noqa: E402
import pregame_snapshot as ps  # noqa: E402


RDS_FILES = {
    'games': ('s', 'games.rds'),
    'depth': ('d', 'depth_charts_2026.rds'),
    'roster': ('r', 'roster_weekly_2026.rds'),
    'injury': ('i', 'injuries_2026.rds'),
}
DB_TO_ARCHIVE_TEAM = {'LAR': 'LA', 'WSH': 'WAS'}
EASTERN = ZoneInfo('America/New_York')
STARTER_ROLES = {
    '3WR 1TE': {
        ('QB', 1), ('RB', 1), ('TE', 1), ('WR', 1), ('WR', 2), ('WR', 3),
        ('LT', 1), ('LG', 1), ('C', 1), ('RG', 1), ('RT', 1),
    },
    'Base 4-3 D': {
        ('LDE', 1), ('LDT', 1), ('RDT', 1), ('RDE', 1), ('MLB', 1), ('WLB', 1),
        ('SLB', 1), ('LCB', 1), ('RCB', 1), ('FS', 1), ('SS', 1),
    },
    'Base 3-4 D': {
        ('LDE', 1), ('NT', 1), ('RDE', 1), ('LILB', 1), ('RILB', 1), ('SLB', 1),
        ('WLB', 1), ('LCB', 1), ('RCB', 1), ('FS', 1), ('SS', 1),
    },
    'Special Teams': {('PK', 1), ('P', 1), ('LS', 1), ('H', 1), ('KR', 1), ('PR', 1)},
}
EXPECTED_STARTERS = 28
# NFL's official 2022 Rams and 2025 Packers media guides use both "Matthew Orzech" and
# "Matt Orzech" for this player. Keep the exception keyed by GSIS and exact normalized
# names; never use it to join identities. Sources:
# https://static.www.nfl.com/image/upload/league/apps/league-site/media-guides/2022/LAR.pdf
# https://static.www.nfl.com/image/upload/league/apps/league-site/media-guides/2025/GB.pdf
VERIFIED_NAME_VARIANTS = {
    '00-0035118': frozenset({('matt orzech', 'matthew orzech')}),
    # Bengals materials identify Daxton Hill as Dax Hill and report that he prefers Dax.
    # https://www.bengals.com/news/daxton-hill-press-conference-transcripts
    '00-0037743': frozenset({('dax hill', 'daxton hill')}),
    # Packers materials confirm T.J. is Tedarrell Slaton's nickname.
    # https://www.packers.com/news/inbox-it-serves-a-playmaking-purpose
    '00-0036642': frozenset({('tj slaton', 'tedarrell slaton')}),
}


def _sha(path):
    return archive._sha256(path)


def _missing(value):
    if value is None:
        return True
    try:
        return bool(math.isnan(value))
    except (TypeError, ValueError):
        return False


def _text(value):
    return None if _missing(value) else str(value)


def _int(value, label):
    if _missing(value):
        raise ValueError(f'{label} is missing')
    return int(value)


def _name_key(value):
    # Sources vary on periods in initialisms ("DJ" vs "D.J."). Remove periods
    # after letters before tokenizing; stable GSIS IDs remain the join key.
    value = re.sub(r'(?<=[a-z])\.(?=[a-z\s]|$)', '', str(value).lower())
    key = re.sub(r'[^a-z0-9]+', ' ', value).strip()
    return re.sub(r'\s+(jr|sr|ii|iii|iv)$', '', key)


def _identity_name_matches(gsis_id, source_name, canonical_name):
    source_key, canonical_key = _name_key(source_name), _name_key(canonical_name)
    if source_key == canonical_key:
        return True
    pair = (source_key, canonical_key)
    reverse = (canonical_key, source_key)
    return pair in VERIFIED_NAME_VARIANTS.get(str(gsis_id), ()) or reverse in VERIFIED_NAME_VARIANTS.get(
        str(gsis_id), ())


def _iso_utc(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError(f'timestamp lacks a timezone: {value}')
    return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _schedule_row(games, row):
    match = games[games['game_id'].astype(str) == row['game_id']]
    if len(match) != 1:
        raise ValueError(f"{row['game_id']}: archived schedule must contain exactly one row")
    game = match.iloc[0].to_dict()
    kickoff_local = datetime.strptime(f"{game['gameday']} {game['gametime']}", '%Y-%m-%d %H:%M')
    kickoff = (EASTERN.localize(kickoff_local) if hasattr(EASTERN, 'localize')
               else kickoff_local.replace(tzinfo=EASTERN))
    kickoff = kickoff.astimezone(timezone.utc)
    expected_kickoff = archive._utc(row['kickoff_utc'], 'readiness kickoff')
    if kickoff != expected_kickoff:
        raise ValueError(f"{row['game_id']}: archived schedule kickoff {kickoff.isoformat()} differs from readiness")
    if not _missing(game.get('home_score')) or not _missing(game.get('away_score')):
        raise ValueError(f"{row['game_id']}: target game outcome is present in the pre-cutoff source version")
    if str(game['game_type']) != 'REG' or int(game['week']) != int(row['week']):
        raise ValueError(f"{row['game_id']}: archived schedule type/week differs from readiness")
    if (str(game['away_team']), str(game['home_team'])) != tuple(row['game_id'].split('_')[-2:]):
        raise ValueError(f"{row['game_id']}: archived teams differ from the published game id")
    return game, kickoff


def _source_pins(row, manifest):
    archive_tag = row['archive_tag']
    date = archive_tag[len('archive-'):] if archive_tag.startswith('archive-') else archive_tag
    release = manifest.get('archives', {}).get(date)
    if not release:
        raise ValueError(f'{archive_tag}: no archive-release record')
    pins = {}
    for key, (code, filename) in RDS_FILES.items():
        entry = release.get(code)
        if not isinstance(entry, list) or len(entry) != 2 or not entry[1]:
            raise ValueError(f'{archive_tag}: missing {key} publication/hash pin')
        row_hash = row.get({'games': 'schedule_sha256', 'depth': 'depth_sha256',
                            'roster': 'roster_sha256', 'injury': 'injury_sha256'}[key])
        if entry[1] != row_hash:
            raise ValueError(f'{archive_tag}: {key} archive hash differs from the readiness matrix')
        published_field = {'games': 'schedule_observed_utc', 'depth': 'depth_published_utc',
                           'roster': 'roster_published_utc', 'injury': 'injury_published_utc'}[key]
        if entry[0] != row.get(published_field):
            raise ValueError(f'{archive_tag}: {key} publication timestamp differs from the readiness matrix')
        pins[key] = {'archive_tag': archive_tag, 'file_name': filename,
                     'published_at_utc': entry[0], 'sha256': entry[1]}
    return pins


def _load_archive(pyreadr, root, pins):
    tables, paths = {}, {}
    for key, pin in pins.items():
        tag, filename = pin['archive_tag'], pin['file_name']
        path, _ = archive._asset_path(root, tag, filename, pin['sha256'])
        print(f'archive {tag}: reading {key} from {path}', file=sys.stderr, flush=True)
        tables[key] = next(iter(pyreadr.read_r(str(path)).values()))
        paths[key] = path
    return tables, paths


def _database_players(db_path, gsis_ids):
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        found = {}
        for gsis_id in sorted(gsis_ids):
            rows = con.execute(
                "SELECT id, name, nfl_gsis_id FROM players WHERE lower(league)='nfl' AND nfl_gsis_id=?",
                (gsis_id,),
            ).fetchall()
            if len(rows) != 1:
                raise ValueError(f'{gsis_id}: expected one canonical NFL player identity, found {len(rows)}')
            found[gsis_id] = {'player_id': int(rows[0]['id']), 'canonical_name': rows[0]['name']}
        return found
    finally:
        con.close()


def _current_streaks(games, game, cutoff, game_id):
    target_week = int(game['week'])
    completed = games[(games['season'] == int(game['season'])) & (games['game_type'] == 'REG')
                      & (games['week'] < target_week)]
    source_games = []
    for record in completed.to_dict('records'):
        home_score, away_score = record.get('home_score'), record.get('away_score')
        if _missing(home_score) or _missing(away_score):
            if record.get('home_team') in (game['home_team'], game['away_team']) or record.get('away_team') in (
                    game['home_team'], game['away_team']):
                raise ValueError(f"{game_id}: earlier scheduled team game {record['game_id']} has no published result")
            continue
        # The season archive itself was published before this cutoff; only earlier weeks are eligible here.
        source_games.append(record)

    streaks = {}
    for team in (str(game['home_team']), str(game['away_team'])):
        results = []
        for record in source_games:
            if record['home_team'] == team:
                won = int(record['home_score']) > int(record['away_score'])
                tied = int(record['home_score']) == int(record['away_score'])
            elif record['away_team'] == team:
                won = int(record['away_score']) > int(record['home_score'])
                tied = int(record['home_score']) == int(record['away_score'])
            else:
                continue
            results.append((int(record['week']), str(record['game_id']), won, tied))
        results.sort()
        state = 0
        for _week, _gid, won, tied in results:
            if tied:
                state = 0
            elif won:
                state = state + 1 if state > 0 else 1
            else:
                state = state - 1 if state < 0 else -1
        streaks[team] = {'streak': f'W{state}' if state > 0 else f'L{-state}' if state < 0 else '',
                         'prior_games': [gid for _week, gid, _won, _tied in results]}
    return streaks, source_games


def _team_roster(*, side, team, week, cutoff, depth, roster, injuries, identity, roster_summary, game_id):
    source_team = DB_TO_ARCHIVE_TEAM.get(team, team)
    depth_rows = depth[(depth['team'].astype(str) == source_team)]
    depth_rows = depth_rows[depth_rows['dt'].map(lambda x: archive._utc(x, f'{team} depth timestamp') <= cutoff)]
    if depth_rows.empty:
        raise ValueError(f'{game_id}: no archived depth rows by cutoff for {team}')
    latest = max(depth_rows['dt'].map(lambda x: archive._utc(x, f'{team} depth timestamp')))
    depth_date = latest.isoformat().replace('+00:00', 'Z')
    depth_rows = depth_rows[depth_rows['dt'].map(lambda x: archive._utc(x, f'{team} depth timestamp') == latest)]

    roster_rows = roster[(roster['season'] == 2026) & (roster['week'] == week)
                         & (roster['game_type'] == 'REG') & (roster['team'].astype(str) == source_team)]
    by_gsis = {}
    for record in roster_rows.to_dict('records'):
        gsis_id = _text(record.get('gsis_id'))
        if not gsis_id:
            continue
        old = by_gsis.get(gsis_id)
        value = {'status': _text(record.get('status')), 'jersey_number': None if _missing(record.get('jersey_number'))
                 else int(record['jersey_number']), 'full_name': _text(record.get('full_name'))}
        if old is not None and old != value:
            raise ValueError(f'{game_id}: conflicting weekly roster records for {team} {gsis_id}')
        by_gsis[gsis_id] = value
    if not by_gsis:
        raise ValueError(f'{game_id}: no archived Week {week} roster rows for {team}')

    injuries_team = injuries[(injuries['season'] == 2026) & (injuries['week'] == week)
                             & (injuries['game_type'] == 'REG') & (injuries['team'].astype(str) == source_team)]
    injury_by_gsis = {}
    injury_rows = []
    for record in injuries_team.to_dict('records'):
        gsis_id = _text(record.get('gsis_id'))
        if not gsis_id:
            raise ValueError(f'{game_id}: {team} injury report row has no GSIS identity')
        status = _text(record.get('report_status'))
        practice = _text(record.get('practice_status'))
        injury_rows.append({'gsis_id': gsis_id, 'report_status': status, 'practice_status': practice})
        injury_by_gsis[gsis_id] = status

    defense_group = roster_summary.get('defense_group')
    if defense_group not in ('Base 3-4 D', 'Base 4-3 D'):
        raise ValueError(f'{game_id}: unsupported defense group for {team}: {defense_group!r}')
    expected_roles = {(group, position, rank) for group, roles in STARTER_ROLES.items()
                      if group in ('3WR 1TE', 'Special Teams', defense_group)
                      for position, rank in roles}
    retained = []
    source_role_keys = set()
    missing_ids = set()
    name_mismatches = []
    for record in depth_rows.to_dict('records'):
        gsis_id = _text(record.get('gsis_id'))
        group, pos = _text(record.get('pos_grp')), _text(record.get('pos_abb'))
        rank = _int(record.get('pos_rank'), f'{team} {pos} depth rank')
        if group not in ('3WR 1TE', 'Special Teams', defense_group) or not gsis_id:
            continue
        rank = _int(record.get('pos_rank'), f'{team} {pos} depth rank')
        roster_entry = by_gsis.get(gsis_id)
        if roster_entry is None:
            continue
        if roster_entry['status'] not in ('ACT', 'Active', None):
            continue
        player_identity = identity.get(gsis_id)
        if not player_identity:
            missing_ids.add(gsis_id)
            continue
        source_name = _text(record.get('player_name')) or roster_entry.get('full_name')
        canonical_name = player_identity['canonical_name']
        if not source_name or not canonical_name or not _identity_name_matches(gsis_id, source_name, canonical_name):
            name_mismatches.append({'gsis_id': gsis_id, 'archive_name': source_name,
                                    'canonical_name': canonical_name})
            continue
        role_key = (group, pos, rank)
        if role_key in source_role_keys:
            raise ValueError(f'{game_id}: duplicate archived depth role for {team} {role_key}')
        source_role_keys.add(role_key)
        report_status = injury_by_gsis.get(gsis_id)
        excluded = report_status in ('Out', 'Doubtful')
        retained.append({
            'gsis_id': gsis_id,
            'player_id': player_identity['player_id'],
            'player_name': source_name,
            'team': team,
            'pos_abb': pos,
            'pos_rank': rank,
            'group': group,
            'unit': 'offense' if group == '3WR 1TE' else 'special_teams' if group == 'Special Teams' else 'defense',
            'starter': False,
            'roster_eligible': not excluded,
            'availability': {'decision': 'exclude_report_status' if excluded else
                             'include_questionable' if report_status == 'Questionable' else
                             'include_missing_report' if report_status is None else 'include_report_status',
                             'designation': report_status,
                             'flags': ['questionable'] if report_status == 'Questionable' else
                             ['missing_report'] if report_status is None else []},
            'jersey_number': roster_entry['jersey_number'],
            'snapshot_at': depth_date,
            'source': 'nflverse_depth_charts_archived',
        })
    if name_mismatches:
        raise ValueError(f'{game_id}: unresolved archived/canonical name mismatches for {team}: {name_mismatches}')
    if missing_ids:
        raise ValueError(f'{game_id}: {team} depth players have no unique canonical ID: {sorted(missing_ids)[:5]}')

    # If the listed starter is not on the archived game-week roster, promote the best rostered player for that role.
    promotions = []
    for group, pos, rank in sorted(expected_roles):
        same_position = sorted((p for p in retained if p['roster_eligible']
                                and p['group'] == group and p['pos_abb'] == pos),
                               key=lambda p: (p['pos_rank'], p['gsis_id']))
        exact = next((p for p in same_position if p['pos_rank'] == rank), None)
        chosen = exact or next((p for p in same_position if not p['starter']), None)
        if chosen is None:
            raise ValueError(f'{game_id}: {team} has no available depth player for starter role {group}/{pos}/{rank}')
        chosen['starter'] = True
        if chosen['pos_rank'] != rank:
            promotions.append({'group': group, 'pos_abb': pos, 'starter_rank': rank,
                               'promoted_gsis_id': chosen['gsis_id'], 'promoted_depth_rank': chosen['pos_rank']})
    if sum(bool(player['starter']) for player in retained) != EXPECTED_STARTERS:
        raise ValueError(f'{game_id}: {team} archive roster does not resolve to exactly {EXPECTED_STARTERS} starter roles')
    if not any(p['pos_abb'] == 'QB' and p['pos_rank'] == 1 and p['roster_eligible'] for p in retained):
        if not any(p['pos_abb'] == 'QB' and p['roster_eligible'] for p in retained):
            raise ValueError(f'{game_id}: {team} has no pregame-eligible quarterback after roster/injury checks')

    roster = {
        'team': team,
        'snapshot_at': depth_date,
        'source': 'nflverse_depth_charts_archived',
        'depth_chart_dt': depth_date,
        'defense_group': defense_group,
        'jersey_week': week,
        'missing': [],
        'players': sorted(retained, key=lambda p: (p['group'], p['pos_abb'], p['pos_rank'], p['gsis_id'])),
        'promotions': promotions,
        'injury_report': {'rows': len(injury_rows), 'available': bool(injury_rows), 'players': injury_rows},
        'source_row_counts': {'depth_rows': len(depth_rows), 'week_roster_rows': len(roster_rows),
                              'matched_players': len(retained)},
    }
    return roster


def _build_one(*, row, tables, paths, db_path, archive_manifest, archive_manifest_sha,
               readiness_matrix, out_dir):
    game, kickoff = _schedule_row(tables['games'], row)
    cutoff = archive._utc(row['cutoff_utc'], 'readiness cutoff')
    if cutoff >= kickoff:
        raise ValueError(f"{row['game_id']}: readiness cutoff is not before kickoff")
    pins = _source_pins(row, archive_manifest)
    all_depth_ids = set()
    teams = {'away': str(game['away_team']), 'home': str(game['home_team'])}
    depth = tables['depth']
    for side, team in teams.items():
        roster_summary = json.loads(row[f'{side}_full_roster'])
        source_team = DB_TO_ARCHIVE_TEAM.get(team, team)
        team_depth = depth[(depth['team'].astype(str) == source_team)
                           & depth['dt'].map(lambda x: archive._utc(x, 'depth source timestamp') <= cutoff)]
        if team_depth.empty:
            raise ValueError(f"{row['game_id']}: no archived depth rows by cutoff for {team}")
        latest = max(team_depth['dt'].map(lambda x: archive._utc(x, 'depth source timestamp')))
        team_depth = team_depth[team_depth['dt'].map(lambda x: archive._utc(x, 'depth source timestamp') == latest)]
        weekly = tables['roster'][(tables['roster']['season'] == 2026)
                                  & (tables['roster']['week'] == int(game['week']))
                                  & (tables['roster']['game_type'] == 'REG')
                                  & (tables['roster']['team'].astype(str) == source_team)]
        roster_ids = {str(r['gsis_id']) for r in weekly.to_dict('records')
                      if not _missing(r.get('gsis_id')) and _text(r.get('status')) == 'ACT'}
        groups = {'3WR 1TE', 'Special Teams', roster_summary.get('defense_group')}
        for record in team_depth.to_dict('records'):
            gsis_id = _text(record.get('gsis_id'))
            if gsis_id and gsis_id in roster_ids and record.get('pos_grp') in groups:
                all_depth_ids.add(gsis_id)
    identity = _database_players(db_path, all_depth_ids)
    # Rebuild with the pinned identity map, asserting that GSIS is the only join key.
    rosters = {}
    for side, team in teams.items():
        roster_summary = json.loads(row[f'{side}_full_roster'])
        rosters[side] = _team_roster(
            side=side, team=team, week=int(game['week']), cutoff=cutoff,
            depth=depth, roster=tables['roster'], injuries=tables['injury'], identity=identity,
            roster_summary=roster_summary, game_id=row['game_id'])

    streak_teams, source_games = _current_streaks(tables['games'], game, cutoff, row['game_id'])
    streak_payload = {
        'schema': 'lp-nfl-pregame-streak-1', 'game_id': row['game_id'],
        'cutoff_utc': row['cutoff_utc'], 'teams': {team: {'streak': entry['streak']}
                                                    for team, entry in streak_teams.items()},
        'source_archive_tag': row['archive_tag'],
        'source_archive_sha256': pins['games']['sha256'],
        'source_games': [str(g['game_id']) for g in source_games],
    }
    output_dir = Path(out_dir)
    streak_path = output_dir / 'streaks' / f"{row['game_id']}.json"
    streak_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(streak_path, streak_payload)
    streak_sha = _sha(streak_path)

    source_assets = {}
    for key, pin in pins.items():
        code, filename = RDS_FILES[key]
        source_assets[{'games': 'schedule', 'depth': 'depth', 'roster': 'roster', 'injury': 'injury'}[key]] = {
            **pin, 'source': 'official_nflverse_dated_archive',
            'path': f"{pin['archive_tag']}/{pin['file_name']}", 'sha256': pin['sha256'],
        }
    full_identity = {
        'join_key': 'players.league=nfl AND players.nfl_gsis_id=archived.gsis_id',
        'resolved_unique_gsis_ids': len(identity),
        'source_name_checks': 'stable GSIS identity joined; both archive and canonical names retained for review',
    }
    snapshot = {
        'schema': ps.SCHEMA,
        'as_of': row['cutoff_utc'].replace('+00:00', 'Z'),
        'evaluation': {'class': archive.MODE, 'verified': False,
                       'source_availability_verified': True,
                       'unverified_inputs': ['retrospective local acquisition time is unknown; this is not prospective']},
        'roster_snapshot_id': 'archive:' + ps._canonical_hash(rosters),
        'schedule': {
            'game_id': row['game_id'], 'season': int(game['season']), 'game_type': str(game['game_type']),
            'week': int(game['week']), 'gameday': str(game['gameday']), 'gametime': str(game['gametime']),
            'gametime_timezone': 'America/New_York', 'away_team': teams['away'], 'home_team': teams['home'],
            'source': 'official_nflverse_archived_games', 'ingested_at': None,
            'availability_classification': archive.MODE,
            'scheduled_kickoff_utc': kickoff.isoformat().replace('+00:00', 'Z'),
            'kickoff_source_url': 'https://github.com/nflverse/nflverse-data-archives/releases',
        },
        'rosters': rosters,
        'model_reference': {
            'play_pool': 'nfl_pbp seasons before 2026 only; target-season outcomes excluded',
            'rule_version': 'NFL-2026-GAME-STATE-RULES.md / E2 successor rules matrix',
            'participant_assignment_version': 'pregame-role-usage-v1',
        },
        'archive_reconstruction': {
            'schema': archive.SCHEMA, 'mode': archive.MODE, 'prospective_eligible': False,
            'source_availability_verified': True,
            'local_capture_observed_utc': None,
            'archive_tag': row['archive_tag'], 'archive_manifest_sha256': archive_manifest_sha,
            'readiness_matrix_sha256': _sha(readiness_matrix),
            'builder_sha256': _sha(Path(__file__).resolve()),
            'source_assets': source_assets,
            'identity_resolution': full_identity,
            'streak_context': {'game_id': row['game_id'], 'cutoff_utc': row['cutoff_utc'],
                               'teams': streak_payload['teams'], 'source_games': streak_payload['source_games'],
                               'source_archive_sha256': pins['games']['sha256'], 'file_sha256': streak_sha,
                               'file': os.path.relpath(streak_path, start=output_dir / 'snapshots')},
            'note': ('Retrospective archive reconstruction. Exact official asset hashes and publication times are pinned; '
                     'local acquisition before the historical cutoff is not established.'),
        },
    }
    snapshot = ps.reseal(snapshot)
    return snapshot, streak_path


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)


def main(argv=None):
    global args
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--readiness-matrix', required=True)
    parser.add_argument('--archive-manifest', required=True)
    parser.add_argument('--archive-root', required=True)
    parser.add_argument('--db', required=True, help='canonical identity SQLite DB, opened read-only')
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--resume', action='store_true', help='validate and keep complete existing snapshots; refuse mismatches')
    args = parser.parse_args(argv)

    try:
        import pyreadr
    except ImportError as exc:
        raise SystemExit('pyreadr is required only by this archive builder; use the prepared archive-reader Python environment') from exc

    readiness_path, manifest_path = Path(args.readiness_matrix), Path(args.archive_manifest)
    matrix_rows = []
    with readiness_path.open(newline='') as handle:
        matrix_rows = list(csv.DictReader(handle))
    classes = {}
    for row in matrix_rows:
        classes[row['readiness_class']] = classes.get(row['readiness_class'], 0) + 1
    if (len(matrix_rows) != 107 or classes != {'cutoff-valid': 28, 'exploratory reconstruction': 51, 'refused': 28}):
        raise ValueError(f'readiness matrix population changed; expected 28 cutoff-valid, 51 exploratory, 28 refused: {classes}')
    rows = []
    for row in matrix_rows:
        if row.get('week') in ('5', '6', '7') and row.get('readiness_class') == 'cutoff-valid':
            archive.readiness_row(readiness_path, row['game_id'])
            rows.append(row)
    if len(rows) != 28:
        raise ValueError(f'expected 28 source-valid locked Week 5-7 games; readiness matrix has {len(rows)}')
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = json.loads(manifest_bytes)

    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    by_archive = {}
    for row in rows:
        by_archive.setdefault(row['archive_tag'], []).append(row)
    completed = 0
    for archive_tag, archive_rows in sorted(by_archive.items()):
        print(f'loading {archive_tag}: {len(archive_rows)} eligible games', file=sys.stderr, flush=True)
        pins = _source_pins(archive_rows[0], manifest)
        tables, paths = _load_archive(pyreadr, args.archive_root, pins)
        for row in archive_rows:
            snapshot_path = output_dir / 'snapshots' / f"{row['game_id']}.json"
            if snapshot_path.exists():
                if not args.resume:
                    raise FileExistsError(f'{snapshot_path} exists; pass --resume to validate and skip it')
                existing = ps.load_frozen_snapshot(str(snapshot_path))
                relative_streak = existing['archive_reconstruction']['streak_context']['file']
                existing_streak = (snapshot_path.parent / relative_streak).resolve()
                archive.validate_snapshot(existing, readiness_matrix=readiness_path, archive_manifest=manifest_path,
                                          archive_root=args.archive_root,
                                          streak_file=existing_streak,
                                          expected_game_id=row['game_id'])
                completed += 1
                print(f'progress {completed}/{len(rows)} reused {row["game_id"]}', file=sys.stderr, flush=True)
                continue
            snapshot, streak_path = _build_one(row=row, tables=tables, paths=paths, db_path=args.db,
                                               archive_manifest=manifest, archive_manifest_sha=manifest_sha,
                                               readiness_matrix=readiness_path, out_dir=output_dir)
            archive.validate_snapshot(snapshot, readiness_matrix=readiness_path, archive_manifest=manifest_path,
                                      archive_root=args.archive_root, streak_file=streak_path,
                                      expected_game_id=row['game_id'])
            _atomic_json(snapshot_path, snapshot)
            completed += 1
            print(f'progress {completed}/{len(rows)} wrote {row["game_id"]} snapshot={snapshot_path} '
                  f'streak_sha256={_sha(streak_path)}', file=sys.stderr, flush=True)
        del tables
        gc.collect()
    print(f'complete {completed}/{len(rows)} retrospective snapshots in {output_dir}', file=sys.stderr, flush=True)


if __name__ == '__main__':
    main()
