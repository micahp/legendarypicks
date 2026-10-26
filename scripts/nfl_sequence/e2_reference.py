"""Observed reference data for E2 games, loaded once from the dev nfl_pbp table. Read-only.

The window is E1's: 2022-2025, weeks 1-18. The pool, the kickoff pool, the kick table and the participant lookup all
come from that window, so every draw in a game is from the same observed seasons.
"""
import sqlite3
import sys
import hashlib
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
import game_state as gs  # noqa: E402
import measure_kick_outcomes as mk  # noqa: E402


PLAY_EXTRAS = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'play_extras_2022_2025.csv'
BLOCKED_KICKS = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'blocked_kick_outcomes_2022_2025.csv'
OVERTIME_DRIVES = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'overtime_drives_2022_2025.csv'
SAFETY_KICKS = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'safety_kick_outcomes_2022_2025.csv'
RECEIVER_POSITIONS = ('WR', 'TE', 'RB', 'FB')
RUNNER_POSITIONS = ('RB', 'FB', 'QB')


def load_position_usage(db=e1.DEFAULT_DB):
    """Measure ball-carrier and target position shares on the E1 historical window.

    Position is joined by GSIS ID to the canonical NFL player table. Unmatched
    or unusual positions remain counted as unclassified rather than guessed.
    """
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        result = {}
        for label, player_column, allowed, play_type in (
                ('receiver', 'receiver_player_id', RECEIVER_POSITIONS, 'pass'),
                ('runner', 'rusher_player_id', RUNNER_POSITIONS, 'run')):
            rows = con.execute(f"""SELECT COALESCE(p.position, 'UNMAPPED'), COUNT(*)
                FROM nfl_pbp n
                LEFT JOIN players p ON p.nfl_gsis_id=n.{player_column} AND lower(p.league)='nfl'
                WHERE n.season BETWEEN 2022 AND 2025 AND n.week <= 18
                  AND n.play_type=?
                  AND n.{player_column} IS NOT NULL
                GROUP BY COALESCE(p.position, 'UNMAPPED')""", (play_type,)).fetchall()
            counts = {position: int(count) for position, count in rows}
            eligible = {position: counts.get(position, 0) for position in allowed if counts.get(position, 0)}
            denominator = sum(eligible.values())
            if denominator == 0:
                raise ValueError(f'no historically joined {label} positions in the E1 window')
            result[f'{label}_position_usage'] = {
                'source': 'nfl_pbp player GSIS ID joined to players.nfl_gsis_id; position groups from canonical NFL identity',
                'counts_by_position': dict(sorted(counts.items())),
                'classified_rows': denominator,
                'noneligible_position_rows': sum(counts.values()) - denominator,
                'shares': {position: count / denominator for position, count in sorted(eligible.items())},
            }
    finally:
        con.close()
    return result


def _reference_fingerprint(reference):
    digest = hashlib.sha256()

    def add(value):
        digest.update(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())
        digest.update(b'\n')

    for key in sorted(reference.pool):
        add(['play-cell', key])
        for event, row, runoff, spot in reference.pool[key]:
            add([event, row, runoff, spot])
    for kickoff in reference.kickoff_pool:
        add(['kickoff', kickoff])
    add(['kick-table', reference.kicks])
    for key in sorted(reference.participants):
        add(['participants', key, reference.participants[key]])
    add(['position-usage', reference.position_usage])
    for bucket in sorted(reference.missed_field_goal_pool):
        add(['missed-field-goal-return-bucket', bucket])
        for sample in reference.missed_field_goal_pool[bucket]:
            add(['missed-field-goal-return', bucket, sample])
    for kick_type in sorted(reference.blocked_kicks.get('records', {})):
        add(['blocked-kick-type', kick_type])
        for sample in reference.blocked_kicks['records'][kick_type]:
            add(['blocked-kick-outcome', kick_type, sample])
    add(['blocked-kick-rates', reference.blocked_kicks.get('rates')])
    add(['blocked-kick-source-sha256', reference.blocked_kicks.get('sha256')])
    add(['blocked-kick-manifest-sha256', reference.blocked_kicks.get('manifest_sha256')])
    add(['blocked-kick-input-source-sha256', reference.blocked_kicks.get('source_hashes')])
    if reference.safety_kick_pool is not None:
        # Absent table: the fingerprint, and so every seed's draws, stay as they were before the table existed.
        for sample in reference.safety_kick_pool:
            add(['safety-kick-sample', sample])
        add(['safety-kick-source-sha256', reference.safety_kick_sha256])
    if reference.overtime_pool is not None:
        # Absent table: the fingerprint and every seed's draws stay as they were before the overtime table existed.
        for drive in reference.overtime_pool:
            add(['overtime-drive', drive])
        add(['overtime-source-sha256', reference.overtime_sha256])
    extras_hash = hashlib.sha256(PLAY_EXTRAS.read_bytes()).hexdigest()
    add(['play-extras-file-sha256', extras_hash])
    summary = {
        'schema': 'lp-e2-observed-reference-3',
        'sha256': digest.hexdigest(),
        **reference.position_usage,
        'play_cells': len(reference.pool),
        'play_samples': sum(len(cell) for cell in reference.pool.values()),
        'kickoff_samples': len(reference.kickoff_pool),
        'participant_rows': len(reference.participants),
        'missed_field_goal_return_samples': sum(len(rows) for rows in reference.missed_field_goal_pool.values()),
        'missed_field_goal_return_buckets': {bucket: len(rows)
                                             for bucket, rows in sorted(reference.missed_field_goal_pool.items())},
        'blocked_kick_outcome_samples': {
            kick_type: len(rows) for kick_type, rows in sorted(reference.blocked_kicks.get('records', {}).items())},
        'blocked_kick_rates': reference.blocked_kicks.get('rates'),
        'blocked_kick_source_sha256': reference.blocked_kicks.get('sha256'),
        'blocked_kick_manifest_sha256': reference.blocked_kicks.get('manifest_sha256'),
        'blocked_kick_input_source_sha256': reference.blocked_kicks.get('source_hashes'),
        'play_extras_sha256': extras_hash,
    }
    if reference.safety_kick_pool is not None:
        # Added only with the table: the summary is resealed into every snapshot, so an absent table must leave it unchanged.
        summary['safety_kick_samples'] = len(reference.safety_kick_pool)
        summary['safety_kick_source_sha256'] = reference.safety_kick_sha256
    if reference.overtime_pool is not None:
        summary['overtime_drive_samples'] = len(reference.overtime_pool)
        summary['overtime_source_sha256'] = reference.overtime_sha256
    return summary


def load_blocked_kicks(path=BLOCKED_KICKS):
    """Load every observed blocked kick, retaining unresolved rows so a sampled unknown outcome can fail closed."""
    import csv
    manifest_path = path.with_suffix(path.suffix + '.manifest.json')
    manifest = json.loads(manifest_path.read_text())
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest['output']['sha256'] != source_hash:
        raise ValueError(f'blocked-kick fixture checksum mismatch: {path}')
    pools = {'field_goal': [], 'punt': []}
    integer_fields = ('play_id', 'season', 'week', 'down', 'ydstogo', 'yardline_100', 'quarter',
                      'clock_seconds_remaining', 'clock_runoff_seconds', 'crossed_line',
                      'recovery_spot_yardline_100', 'return_endpoint_yardline_100', 'return_yards',
                      'recovery_yards_from_los', 'return_endpoint_yards_from_los', 'dead_ball_yards_from_los',
                      'next_snap_yardline_100', 'next_snap_down', 'next_snap_ydstogo', 'touchdown', 'safety',
                      'return_yards_field', 'return_touchdown_field', 'receiving_team_touched_beyond_line')
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != manifest['record_count']:
        raise ValueError(f'blocked-kick fixture row count mismatch: {path}')
    seen = set()
    for row in rows:
        for field in integer_fields:
            value = row[field]
            row[field] = int(float(value)) if value not in ('', None) else None
        row['blocked'] = row['blocked'] == '1'
        key = (row['game_id'], row['play_id'])
        if key in seen:
            raise ValueError(f'duplicate blocked-kick source row: {key}')
        seen.add(key)
        if row['kick_type'] not in pools:
            raise ValueError(f'unknown blocked-kick type: {row["kick_type"]!r}')
        if manifest['sources'].get(row['source_file']) != row['source_sha256']:
            raise ValueError(f'blocked-kick source provenance mismatch: {key}')
        if row['blocked'] is not True:
            raise ValueError(f'non-blocked source event in blocked-kick fixture: {key}')
        pools[row['kick_type']].append(row)
    return {'records': pools, 'rates': manifest['observed_rates'], 'sha256': source_hash,
            'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'source_hashes': manifest['sources'], 'source': manifest['source_dataset'], 'window': manifest['window']}


# The play extras file spells two clubs as nflverse does (LA, WAS); the play-by-play table spells them LAR and WSH. A timeout
# caller must match the play's own team codes, so the extras are mapped to the table's codes.
EXTRAS_TEAM_CODES = {'LA': 'LAR', 'WAS': 'WSH'}


def extras_team(code):
    return EXTRAS_TEAM_CODES.get(code, code)


def load_participants(db=e1.DEFAULT_DB, extras=PLAY_EXTRAS):
    """Observed play facts keyed by (game_id, play_id), for the window.

    From the dev table: passer, rusher and receiver ids, the posting team, air yards, and receiving yards. Yards after
    catch are derived as receiving yards minus air yards (labelled `derived` in the record; the curated table has no
    yards_after_catch). From the rebuilt play_extras CSV: timeout called (and by which team) and out_of_bounds. A play
    with no entry in the CSV has timeout 0 and out_of_bounds 0.
    """
    import csv
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(f"""SELECT game_id, play_id, passer_player_id, rusher_player_id, receiver_player_id,
        posteam, defteam, air_yards, receiving_yards, play_type FROM nfl_pbp WHERE {mk.WINDOW}""").fetchall()
    finally:
        con.close()
    flags = {}
    with open(extras, newline='') as f:
        for r in csv.DictReader(f):
            flags[(r['game_id'], int(float(r['play_id'])))] = (int(r['timeout']), extras_team(r['timeout_team']),
                                                                int(r['out_of_bounds']))
    out = {}
    for g, p, pa, ru, re_, posteam, defteam, air, rec_yds, play_type in rows:
        t, t_team, oob = flags.get((g, int(p)), (0, '', 0))
        yac = (rec_yds - air) if (rec_yds is not None and air is not None and re_) else None
        out[(g, int(p))] = {'passer_id': pa, 'rusher_id': ru, 'receiver_id': re_, 'posteam': posteam,
                            'defteam': defteam,
                            'air_yards': air, 'yards_after_catch': yac, 'play_type': play_type,
                            'timeout': t, 'timeout_team': t_team,
                            'out_of_bounds': oob}
    return out


def load_overtime_drive_pool(path=OVERTIME_DRIVES):
    """Usable observed regular-season overtime drives (Rule 16): how each ended, the points each side scored on it, the clock
    it used, and the other team's next start. Returns (pool, file sha256). The fixture is checked against its manifest before
    any row is read; refused rows stay in the file for audit and are never drawn."""
    import csv
    manifest = json.loads(path.with_suffix(path.suffix + '.manifest.json').read_text())
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest['output']['sha256'] != source_hash:
        raise ValueError(f'overtime fixture checksum mismatch: {path}')
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != manifest['drive_count']:
        raise ValueError(f'overtime fixture row count mismatch: {path}')
    pool = []
    for row in rows:
        if row['status'] != 'usable':
            continue
        pool.append({'outcome': row['outcome'], 'duration': int(row['duration_seconds']),
                     'points_offense': int(row['points_offense']), 'points_defense': int(row['points_defense']),
                     'next_offense': row['next_offense'] or None,
                     'next_yardline': int(row['next_start_yardline_100']) if row['next_start_yardline_100'] else None,
                     'game_id': row['game_id'], 'drive': int(float(row['drive']))})
    if len(pool) != manifest['usable_count']:
        raise ValueError('overtime usable rows disagree with the manifest')
    return pool, source_hash


def load_safety_kick_pool(path=SAFETY_KICKS):
    """Usable observed safety free kicks: the receiving team's first snap and the clock it took. Returns (pool, file sha256).

    The fixture is checked against its manifest's checksum and row count before any row is read. Refused rows stay in the
    file for audit and are never drawn.
    """
    import csv
    manifest = json.loads(path.with_suffix(path.suffix + '.manifest.json').read_text())
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest['output']['sha256'] != source_hash:
        raise ValueError(f'safety-kick fixture checksum mismatch: {path}')
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != manifest['record_count']:
        raise ValueError(f'safety-kick fixture row count mismatch: {path}')
    pool = []
    for row in rows:
        if row['status'] != 'usable':
            continue
        spot, runoff = int(row['receiving_snap_yardline_100']), int(row['clock_runoff_seconds'])
        if not 1 <= spot <= 99 or runoff < 0:
            raise ValueError(f"safety-kick row {row['safety_play_id']} has an impossible spot or runoff")
        pool.append({'spot': spot, 'runoff': runoff, 'game_id': row['game_id'], 'game_date': row['game_date'],
                     'play_id': int(float(row['receiving_snap_play_id'])),
                     'safety_play_id': int(float(row['safety_play_id'])), 'kick_play_id': int(float(row['kick_play_id'])),
                     'kick_type': row['kick_type'], 'season': int(row['season'])})
    if len(pool) != manifest['usable_count']:
        raise ValueError('safety-kick usable rows disagree with the manifest')
    return pool, source_hash


def load_missed_field_goal_pool(db=e1.DEFAULT_DB):
    """Historical defense start spots immediately following a missed kick, by E1 field-position bucket."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute("""SELECT fg.game_id, fg.play_id, fg.yardline_100, fg.qtr, fg.drive,
                    next.play_id, next.yardline_100
                FROM nfl_pbp fg
                JOIN nfl_pbp next
                  ON next.game_id=fg.game_id AND next.qtr=fg.qtr AND next.drive=fg.drive+1
                 AND next.posteam=fg.defteam AND next.play_type IN ('run','pass')
                 AND next.play_id=(
                    SELECT MIN(n.play_id) FROM nfl_pbp n
                     WHERE n.game_id=fg.game_id AND n.qtr=fg.qtr AND n.drive=fg.drive+1
                       AND n.posteam=fg.defteam AND n.play_type IN ('run','pass'))
               WHERE fg.season BETWEEN 2022 AND 2025 AND fg.week <= 18
                 AND fg.play_type='field_goal' AND fg.series_result='Missed field goal'
                 AND fg.yardline_100 IS NOT NULL AND fg.drive IS NOT NULL
               ORDER BY fg.game_id, fg.play_id""").fetchall()
    finally:
        con.close()
    pools = {bucket: [] for bucket in gs.FG_BUCKETS}
    for game_id, play_id, snap_yardline, quarter, drive, next_play_id, next_yardline in rows:
        snap = int(round(snap_yardline))
        actual_spot = int(round(next_yardline))
        if not 1 <= actual_spot <= 99:
            continue
        baseline = gs.missed_field_goal_spot(gs.kick_spot_yardline_100(snap))
        pools[gs.fg_bucket(snap)].append({
            'spot_adjustment_yards': actual_spot - baseline,
            'source': {'game_id': game_id, 'play_id': int(play_id),
                       'next_drive_index': int(drive) + 1, 'next_play_id': int(next_play_id)},
        })
    return pools


def load(db=e1.DEFAULT_DB, regulation_only=True, try_policy=None, safety_kick_table=True, overtime_table=True):
    """Returns (Reference, excluded_kickoffs). Refuses a kick table whose buckets do not match the engine's.

    `regulation_only` (the successor default): the E1 pool and the kickoff pool draw from quarters 1-4 only. The 1,214 overtime
    rows of 2022-2025 are excluded and counted on the reference as `pool_scope`. False reproduces the accepted E2 artifacts,
    which sampled overtime rows. The published kick table is not filtered (its rates include the overtime kicks), and this is
    disclosed on the reference too.

    `try_policy` (opt-in, None by default): a try_policy.TryPolicy that replaces the published two-point share after each
    touchdown. None keeps the unconditional policy and every existing record unchanged.

    `safety_kick_table` (True by default): sample safety free kicks from the observed 2022-2025 table. False keeps the
    block, the control arm for the safety correction.
    """
    rows = e1.load(db)
    pool, pool_excluded = e1.build_pool(rows, regulation_only=regulation_only)
    kick_rows = [r for r in rows if not regulation_only or (r['qtr'] is not None and int(r['qtr']) <= 4)]
    kpool, kex = gs.build_kickoff_pool(kick_rows)
    kicks = mk.load_kick_table(db)
    if set(kicks['field_goal']) != set(gs.FG_BUCKETS):
        raise SystemExit(f"kick table buckets {sorted(kicks['field_goal'])} do not match {list(gs.FG_BUCKETS)}")
    blocked = load_blocked_kicks()
    for bucket, expected in blocked['rates']['field_goal_blocked_by_snap_bucket'].items():
        counts = kicks['field_goal_outcomes'].get(bucket)
        if counts is None or sum(counts) != expected['attempts'] or counts[2] != expected['blocked']:
            raise ValueError(f'blocked field-goal rate and publisher kick table disagree in bucket {bucket}')
    punt_rate = blocked['rates']['punt_blocked']
    if (len(blocked['records']['punt']) != punt_rate['blocked']
            or len(blocked['records']['field_goal']) != sum(x['blocked'] for x in
                                                             blocked['rates']['field_goal_blocked_by_snap_bucket'].values())):
        raise ValueError('blocked-kick transition counts disagree with the observed-rate manifest')
    safety_pool, safety_sha = load_safety_kick_pool() if safety_kick_table else (None, None)
    overtime_pool, overtime_sha = load_overtime_drive_pool() if overtime_table else (None, None)
    reference = gs.Reference(pool, kpool, kicks, load_participants(db),
                             load_missed_field_goal_pool(db), blocked, try_policy=try_policy,
                             safety_kick_pool=safety_pool, overtime_pool=overtime_pool)
    reference.safety_kick_sha256 = safety_sha
    reference.overtime_sha256 = overtime_sha
    reference.position_usage = load_position_usage(db)
    reference.pool_scope = {'regulation_only': regulation_only,
                            'overtime_rows_excluded_from_pool': pool_excluded.get('overtime rows (regulation-only pool)', 0),
                            'overtime_rows_removed_before_kickoff_pool': len(rows) - len(kick_rows),
                            'kick_table': 'not filtered: the published kick rates include overtime kicks',
                            'safety_kick_table': 'observed 2022-2025 regular-season safety free kicks, usable rows only'}
    reference.model_inputs = _reference_fingerprint(reference)
    return reference, kex
