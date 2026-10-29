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
import rule_regimes as rr  # noqa: E402


PLAY_EXTRAS = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'play_extras_2022_2025.csv'
BLOCKED_KICKS = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'blocked_kick_outcomes_2022_2025.csv'
OVERTIME_DRIVES = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'overtime_drives_2022_2025.csv'
TRY_FALLBACK = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'try_fallback_2022_2025.csv'
CHOICE_MODEL = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'overtime_choice_model_2025.csv'
KICKOFF_SEASONS = (2022, 2023, 2024, 2025)  # every season whose kickoffs can be drawn; 2026 is the holdout and is never read
# Reference sources that are not cutoff-safe. Each holds 2022-2025 outcomes with no per-observation cutoff, or a fit on 2025
# alone. A historical cutoff refuses to load any of them until a cutoff-safe rebuild exists (docs/research/REFERENCE-COHORT-AUDIT).
# The default path (no cutoff, S0) keeps loading the pinned artifacts exactly as before.
COHORT_UNSAFE_SOURCES = {}  # every source now has a cutoff path (see docs/research/REFERENCE-COHORT-AUDIT); name one here to refuse
SAFETY_KICKS = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'safety_kick_outcomes_2022_2025.csv'
RECEIVER_POSITIONS = ('WR', 'TE', 'RB', 'FB')
RUNNER_POSITIONS = ('RB', 'FB', 'QB')


def load_position_usage(db=e1.DEFAULT_DB, eligible_before=None):
    """Measure ball-carrier and target position shares on the E1 historical window.

    Position is joined by GSIS ID to the canonical NFL player table. Unmatched
    or unusual positions remain counted as unclassified rather than guessed.
    With `eligible_before`, only plays before the cutoff are counted.
    """
    cut_sql, cut_args = _cutoff_sql(eligible_before, alias='n.')
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
                  AND n.{player_column} IS NOT NULL{cut_sql}
                GROUP BY COALESCE(p.position, 'UNMAPPED')""", (play_type, *cut_args)).fetchall()
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
    if getattr(reference, 'overtime_try_p_two', None) is not None:
        for bucket in sorted(reference.overtime_try_p_two):
            add(['overtime-try-fallback', bucket, reference.overtime_try_p_two[bucket]])
        add(['overtime-try-fallback-sha256', reference.overtime_try_sha256])
    if getattr(reference, 'overtime_p_kick', None) is not None:
        add(['overtime-choice-p-kick', reference.overtime_p_kick])
        add(['overtime-choice-sha256', reference.overtime_choice_sha256])
    if getattr(reference, 'overtime_choice', None) is not None:
        add(['overtime-choice-forced', reference.overtime_choice])
    if getattr(reference, 'overtime_toss', None) is not None:
        add(['overtime-toss-override', reference.overtime_toss])
    extras_hash = hashlib.sha256(PLAY_EXTRAS.read_bytes()).hexdigest()
    add(['play-extras-file-sha256', extras_hash])
    if getattr(reference, 'contextual_sampler', None) is not None:
        add(['contextual-sampler', reference.contextual_sampler.describe()])
        add(['contextual-pool-manifest', reference.contextual_pool_manifest])
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


_before_cutoff = mk.before_cutoff  # one definition, shared with the kick-results loaders


def _cutoff_sql(eligible_before, alias=''):
    """SQL clause and arguments for the same cutoff, for tables that carry season and week. `alias` qualifies the columns."""
    if eligible_before is None:
        return '', ()
    cutoff_season, cutoff_week = int(eligible_before[0]), int(eligible_before[1])
    return (f' AND ({alias}season < ? OR ({alias}season = ? AND {alias}week < ?))',
            (cutoff_season, cutoff_season, cutoff_week))


def load_blocked_kicks(path=BLOCKED_KICKS, eligible_before=None):
    """Load every observed blocked kick, retaining unresolved rows so a sampled unknown outcome can fail closed.

    With `eligible_before`, only records before the cutoff are kept and `rates` is None. The pinned rates cover the whole
    window, so they must be recomputed from the kept records before any use. The full file is still checked first."""
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
        if _before_cutoff(row['season'], row['week'], eligible_before):
            pools[row['kick_type']].append(row)
    return {'records': pools, 'rates': None if eligible_before is not None else manifest['observed_rates'],
            'sha256': source_hash,
            'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'source_hashes': manifest['sources'], 'source': manifest['source_dataset'], 'window': manifest['window']}


# The play extras file spells two clubs as nflverse does (LA, WAS); the play-by-play table spells them LAR and WSH. A timeout
# caller must match the play's own team codes, so the extras are mapped to the table's codes.
EXTRAS_TEAM_CODES = {'LA': 'LAR', 'WAS': 'WSH'}


def extras_team(code):
    return EXTRAS_TEAM_CODES.get(code, code)


def load_participants(db=e1.DEFAULT_DB, extras=PLAY_EXTRAS, eligible_before=None):
    """Observed play facts keyed by (game_id, play_id), for the window.

    From the dev table: passer, rusher and receiver ids, the posting team, air yards, and receiving yards. Yards after
    catch are derived as receiving yards minus air yards (labelled `derived` in the record; the curated table has no
    yards_after_catch). From the rebuilt play_extras CSV: timeout called (and by which team) and out_of_bounds. A play
    with no entry in the CSV has timeout 0 and out_of_bounds 0.
    """
    import csv
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        cut_sql, cut_args = _cutoff_sql(eligible_before)
        rows = con.execute(f"""SELECT game_id, play_id, passer_player_id, rusher_player_id, receiver_player_id,
        posteam, defteam, air_yards, receiving_yards, play_type FROM nfl_pbp WHERE {mk.WINDOW}{cut_sql}""",
                           cut_args).fetchall()
    finally:
        con.close()
    flags = {}
    with open(extras, newline='') as f:
        for r in csv.DictReader(f):
            if not _before_cutoff(r['season'], r['week'], eligible_before):
                continue
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


def load_overtime_choice_model(path=CHOICE_MODEL, eligible_before=None):
    """The observed kick rate for the winning coach's overtime decision (2025 regular season). Checked against its manifest.

    With `eligible_before`, the fitted row is not used. Its games are all 2025, and the toss winner's choice is not recorded in
    the play-by-play. The only table that records it (the coin-toss fixture) also holds 2026 rows, which are not read here. Before
    the cutoff the rate is therefore the Beta(1, 1) prior with no observed games: (kicks + 1) / (games + 2) = 0.5."""
    if eligible_before is not None:
        meta = {'basis': 'beta_1_1_prior_no_observed_games', 'eligible_before': list(eligible_before), 'games': 0, 'kicks': 0}
        return (0 + 1) / (0 + 2), hashlib.sha256(json.dumps(meta, sort_keys=True).encode()).hexdigest()
    import csv
    manifest = json.loads(path.with_suffix(path.suffix + '.manifest.json').read_text())
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest['output']['sha256'] != source_hash:
        raise ValueError(f'overtime choice model checksum mismatch: {path}')
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1:
        raise ValueError('the overtime choice model has one fitted row')
    p = float(rows[0]['p_kick'])
    if not 0.0 <= p <= 1.0:
        raise ValueError('overtime p_kick outside [0, 1]')
    return p, source_hash


def wilson_95(successes, total):
    """Wilson score interval, rounded as the pinned blocked-kick manifest rounds it."""
    import math
    if total == 0:
        return [0.0, 1.0]
    z = 1.959963984540054
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [round(max(0.0, centre - half), 5), round(min(1.0, centre + half), 5)]


def cutoff_blocked_rates(db, blocked, eligible_before=None):
    """Blocked-kick rates with the pinned manifest's definitions, from the cutoff's kick results and kept records.

    A field-goal attempt is a made, missed or blocked kick in its yardline bucket (the same counts the kick table holds, cut the
    same way). A punt attempt is any punt play in the window, cut by (season, week). The blocked counts come from the kept
    records, so the rates and the records always describe the same plays."""
    kicks = mk.load_kick_table(db, eligible_before=eligible_before)
    fg = {}
    for bucket, (made, missed, blocked_fg) in kicks['field_goal_outcomes'].items():
        attempts = made + missed + blocked_fg
        fg[bucket] = {'attempts': attempts, 'blocked': blocked_fg,
                      'rate': blocked_fg / attempts if attempts else 0.0,
                      'wilson_95': wilson_95(blocked_fg, attempts)}
    cut_sql, cut_args = _cutoff_sql(eligible_before)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        punt_attempts = con.execute(
            f"SELECT COUNT(*) FROM nfl_pbp WHERE play_type='punt' AND {mk.WINDOW}{cut_sql}", cut_args).fetchone()[0]
    finally:
        con.close()
    punt_blocked = len(blocked['records']['punt'])
    punt = {'attempts': punt_attempts, 'blocked': punt_blocked,
            'rate': punt_blocked / punt_attempts if punt_attempts else 0.0,
            'wilson_95': wilson_95(punt_blocked, punt_attempts)}
    return {'field_goal_blocked_by_snap_bucket': fg, 'punt_blocked': punt}


def load_overtime_try_fallback(path=TRY_FALLBACK, eligible_before=None):
    """The conditional overtime try table: the two-point probability for each margin bucket (overtime cells of the fitted
    table). The file is checked against its manifest before any row is read.

    With `eligible_before`, the cells are refitted from tries before the cutoff only (build_try_fallback.cutoff_table). The
    committed file is not used, because it was fitted on 2022 to 2025 and its overtime cells come from 2025 alone."""
    if eligible_before is not None:
        import build_try_fallback as btf
        cells, meta = btf.cutoff_table(btf.SOURCE, eligible_before)
        table = {bucket: cells[('ot', bucket)][3] for bucket in [b[2] for b in btf.MARGIN_BUCKETS]}
        meta_sha = hashlib.sha256(json.dumps(meta, sort_keys=True).encode()).hexdigest()
        return table, meta_sha
    import csv
    manifest = json.loads(path.with_suffix(path.suffix + '.manifest.json').read_text())
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest['output']['sha256'] != source_hash:
        raise ValueError(f'try fallback checksum mismatch: {path}')
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    table = {r['margin_bucket']: float(r['p_two']) for r in rows if r['group'] == 'ot'}
    if len(table) != len([b for b in rows if b['group'] == 'ot']):
        raise ValueError('duplicate overtime margin bucket in the try fallback')
    if not all(0.0 <= p <= 1.0 for p in table.values()):
        raise ValueError('try fallback probability outside [0, 1]')
    return table, source_hash


def load_overtime_drive_pool(path=OVERTIME_DRIVES, eligible_before=None):
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
        if not _before_cutoff(row['season'], row['week'], eligible_before):
            continue
        pool.append({'outcome': row['outcome'], 'duration': int(row['duration_seconds']),
                     'points_offense': int(row['points_offense']), 'points_defense': int(row['points_defense']),
                     'next_offense': row['next_offense'] or None,
                     'next_yardline': int(row['next_start_yardline_100']) if row['next_start_yardline_100'] else None,
                     'try_kind': row['try_kind'] or None,
                     'try_made': None if row['try_made'] == '' else bool(int(row['try_made'])),
                     'turnover_kind': row['turnover_kind'],
                     'game_id': row['game_id'], 'drive': int(float(row['drive']))})
    if eligible_before is None and len(pool) != manifest['usable_count']:
        raise ValueError('overtime usable rows disagree with the manifest')
    return pool, source_hash


def load_safety_kick_pool(path=SAFETY_KICKS, eligible_before=None):
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
        if not _before_cutoff(row['season'], row['week'], eligible_before):
            continue
        spot, runoff = int(row['receiving_snap_yardline_100']), int(row['clock_runoff_seconds'])
        if not 1 <= spot <= 99 or runoff < 0:
            raise ValueError(f"safety-kick row {row['safety_play_id']} has an impossible spot or runoff")
        pool.append({'spot': spot, 'runoff': runoff, 'game_id': row['game_id'], 'game_date': row['game_date'],
                     'play_id': int(float(row['receiving_snap_play_id'])),
                     'safety_play_id': int(float(row['safety_play_id'])), 'kick_play_id': int(float(row['kick_play_id'])),
                     'kick_type': row['kick_type'], 'season': int(row['season'])})
    if eligible_before is None and len(pool) != manifest['usable_count']:
        raise ValueError('safety-kick usable rows disagree with the manifest')
    return pool, source_hash


def load_missed_field_goal_pool(db=e1.DEFAULT_DB, eligible_before=None):
    """Historical defense start spots immediately following a missed kick, by E1 field-position bucket.

    With `eligible_before`, only misses before the cutoff are used. The following snap is in the same game and drive, so it
    shares the miss's week and cannot be later than the cutoff when the miss is not."""
    cut_sql, cut_args = _cutoff_sql(eligible_before, alias='fg.')
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(f"""SELECT fg.game_id, fg.play_id, fg.yardline_100, fg.qtr, fg.drive,
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
                 AND fg.yardline_100 IS NOT NULL AND fg.drive IS NOT NULL{cut_sql}
               ORDER BY fg.game_id, fg.play_id""", cut_args).fetchall()
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


def regime_kickoffs(kpool, target_season, kickoff_before):
    """Research variant (opt-in): kickoffs only from the seasons whose registered kickoff rules match the target season.

    Seasons are not pooled across a registered kickoff change, because their spot distributions differ (KS tests in the
    evidence note). Kickoffs on or after `kickoff_before` are dropped, so the validity game is not its own sample.
    """
    if kickoff_before is None:
        raise ValueError('a regime kickoff pool needs kickoff_before')
    kpool = [k for k in kpool if k['game_date'] < kickoff_before]
    registry, registry_sha = rr.load_registry()
    rules = rr.active_rules(registry, target_season, 'REG', 'kickoff')
    pool_seasons = sorted({k['season'] for k in kpool})
    seasons = rr.seasons_with_same_rules(registry, target_season, pool_seasons, 'REG', 'kickoff')
    if not seasons:
        raise SystemExit(f'no kickoff season in the pool has the {target_season} kickoff rules {rules}')
    record = {'target_season': target_season, 'rule_ids': rules, 'seasons': seasons, 'kickoff_before': kickoff_before,
              'samples': sum(1 for k in kpool if k['season'] in seasons),
              'samples_by_season': {s: sum(1 for k in kpool if k['season'] == s) for s in pool_seasons},
              'registry_sha256': registry_sha}
    return [k for k in kpool if k['season'] in seasons], record


def refuse_unsafe_cutoff(eligible_before):
    """Refuse a historical cutoff while any reference source is still listed in COHORT_UNSAFE_SOURCES. Empty means none."""
    if eligible_before is not None and COHORT_UNSAFE_SOURCES:
        raise ValueError('historical cutoff refused: reference sources are not cutoff-safe yet: '
                         + ', '.join(sorted(COHORT_UNSAFE_SOURCES)))


def load(db=e1.DEFAULT_DB, regulation_only=True, try_policy=None, safety_kick_table=True, overtime_table=True,
         overtime_toss=None, overtime_choice=None, kickoff_regime_season=None, kickoff_before=None,
         eligible_before=None, contextual_context=None, contextual_mode=None, contextual_bandwidth=1.0,
         contextual_min_effective_games=10.0, team_tendency=False, team_tendency_teams=None,
         playcall_artifact=None, playcall_teams=None, playcall_team_outcomes=False, playcall_formation=False,
         playcall_player_shares=False, playcall_exact_yardline=False, playcall_coverage=False,
         playcall_point_splits=False, playcall_streak=False, playcall_streak_league=False):
    """Returns (Reference, excluded_kickoffs). Refuses a kick table whose buckets do not match the engine's.

    `regulation_only` (the successor default): the E1 pool and the kickoff pool draw from quarters 1-4 only. The 1,214 overtime
    rows of 2022-2025 are excluded and counted on the reference as `pool_scope`. False reproduces the accepted E2 artifacts,
    which sampled overtime rows. The published kick table is not filtered (its rates include the overtime kicks), and this is
    disclosed on the reference too.

    `try_policy` (opt-in, None by default): a try_policy.TryPolicy that replaces the published two-point share after each
    touchdown. None keeps the unconditional policy and every existing record unchanged.

    `safety_kick_table` (True by default): sample safety free kicks from the observed 2022-2025 table. False keeps the
    block, the control arm for the safety correction.

    `kickoff_regime_season` (opt-in, None by default): draw kickoffs only from the seasons whose registered kickoff rules match
    that season, before `kickoff_before` (required then). None keeps the 2022-2025 kickoff pool that every earlier run used.

    `eligible_before` (opt-in): rebuild the E1 scrimmage and kickoff pool from 2022 through the weeks before the target.
    Kick-result, blocked-kick, missed-field-goal-return, participant-position, and timeout-extras inputs remain their
    separately pinned 2022-2025 artifacts and are identified as such in `pool_scope`.

    `contextual_mode` (opt-in): `offense`, `defense`, or `both`. Requires a target context and eligible-before cutoff.

    `team_tendency` (opt-in, research): the drive policy becomes the team-tendency sampler, built from the plays of seasons
    before the cutoff season (team_tendency.py). It needs an eligible-before cutoff and cannot be combined with contextual_mode,
    because both fill the same drive-policy slot. False keeps every existing reference unchanged.
    """
    refuse_unsafe_cutoff(eligible_before)
    if team_tendency and contextual_mode is not None:
        raise ValueError('team tendencies and contextual sampling are alternative drive policies; choose one')
    if team_tendency and eligible_before is None:
        raise ValueError('team tendencies require an eligible-before cutoff')
    if team_tendency and not team_tendency_teams:
        raise ValueError('team tendencies need the side map {"A": home, "B": away} from the frozen schedule')
    rows = e1.load(db, eligible_before=eligible_before)
    pool, pool_excluded = e1.build_pool(rows, regulation_only=regulation_only)
    contextual_sampler = None
    contextual_pool_manifest = {}
    if contextual_mode is not None:
        if contextual_mode not in ('offense', 'defense', 'both'):
            raise ValueError(f'unknown contextual mode {contextual_mode!r}')
        if eligible_before is None or contextual_context is None:
            raise ValueError('contextual sampling requires both target context and eligible_before cutoff')
        import contextual_pool as cp
        pool_rows = [row for cell in pool.values() for _event, row, _runoff, _spot in cell]
        contextual_sampler, contextual_pool_manifest = cp.build(
            db, pool_rows, contextual_context, mode=contextual_mode, bandwidth=contextual_bandwidth,
            min_effective_games=contextual_min_effective_games)
    if team_tendency:
        import team_tendency as tt
        cutoff_season = int(eligible_before[0])
        prior_rows = [row for row in rows if int(row['season']) < cutoff_season]
        tendencies = tt.build_from_rows(prior_rows, cutoff_season)
        contextual_sampler = tt.TendencySampler(tendencies, side_teams=team_tendency_teams)  # the drive-policy slot
        contextual_pool_manifest = tendencies.manifest
    if playcall_artifact is not None:
        if team_tendency or contextual_mode is not None:
            raise ValueError('the play-call layer cannot be combined with team tendency or contextual sampling')
        import slc_playcall as slc
        contextual_sampler = slc.PlayCallSampler(slc.PlayCallLayer.load(playcall_artifact), side_teams=playcall_teams)
        if playcall_team_outcomes:  # team event splits from the prior seasons only, the same cutoff as the pool
            if eligible_before is None:
                raise ValueError('team outcome splits need an eligible-before cutoff')
            import team_tendency as tt
            cutoff_season = int(eligible_before[0])
            prior_rows = [row for row in rows if int(row['season']) < cutoff_season]
            contextual_sampler.team_outcomes = tt.build_from_rows(prior_rows, cutoff_season, cutoff=(cutoff_season, 1))
        if playcall_formation:  # pre-event formation and personnel from the seasons before the cutoff; outcomes conditioned on it
            if eligible_before is None:
                raise ValueError('formation priors need an eligible-before cutoff')
            import formation_layer as fl
            seasons = sorted({int(row['season']) for row in rows})
            participation = fl.load_participation(db, seasons)
            fl.attach([row for cell in pool.values() for _event, row, _runoff, _spot in cell], participation)
            contextual_sampler.formation_priors = fl.priors(db, int(eligible_before[0]))
            contextual_sampler.formation_outcomes = True
        contextual_sampler.exact_yardline = bool(playcall_exact_yardline)
        if playcall_point_splits:  # team score-state shifts of the dropback rate, from the seasons before the cutoff only
            if eligible_before is None:
                raise ValueError('point splits need an eligible-before cutoff')
            import playcall_model as pm2
            import point_splits as sp
            seasons = range(2010, int(eligible_before[0]))
            if isinstance(playcall_point_splits, str):  # a frame cache whose fingerprint matches the same seasons
                frame = pm2.load_frame_cached(Path(playcall_point_splits), seasons, db=db)
            else:
                frame = pm2.load_frame(seasons, db=db)
            contextual_sampler.point_shifts = sp.priors(frame, int(eligible_before[0]))
        if playcall_streak:  # win-loss streak splits from the prior seasons' streak histories
            if eligible_before is None:
                raise ValueError('streak splits need an eligible-before cutoff')
            import playcall_model as pm3
            import streak_splits as ss
            cutoff = int(eligible_before[0])
            seasons = range(2010, cutoff)
            frame = pm3.load_frame_cached(Path(playcall_streak), seasons, db=db) if isinstance(playcall_streak, str) \
                else pm3.load_frame(seasons, db=db)
            con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
            try:
                schedule_rows = con.execute("SELECT season, week, game_id, home_team, away_team, home_score, away_score FROM nfl_schedule "
                                            "WHERE game_type='REG' AND season < ? AND home_score IS NOT NULL", (cutoff,)).fetchall()
            finally:
                con.close()
            results = []
            for season, week, game_id, home, away, hs, aw in schedule_rows:
                outcome = None if hs == aw else hs > aw
                results.append((season, week, game_id, home, outcome))
                results.append((season, week, game_id, away, None if outcome is None else not outcome))
            states = ss.streak_states(results)
            contextual_sampler.streak_shifts = ss.priors(frame, states, cutoff)
        if playcall_streak_league:  # league-wide streak splits: a league dropback shift and outcome lifts, prior seasons only
            if eligible_before is None:
                raise ValueError('league streak splits need an eligible-before cutoff')
            import playcall_model as pm4
            import streak_splits as ss2
            cutoff = int(eligible_before[0])
            seasons = range(2010, cutoff)
            frame = pm4.load_frame_cached(Path(playcall_streak_league), seasons, db=db) if isinstance(playcall_streak_league, str) \
                else pm4.load_frame(seasons, db=db)
            con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
            try:
                rows_s = con.execute("SELECT season, week, game_id, home_team, away_team, home_score, away_score FROM nfl_schedule "
                                     "WHERE game_type='REG' AND season < ? AND home_score IS NOT NULL", (cutoff,)).fetchall()
            finally:
                con.close()
            res = []
            for season, week, game_id, home, away, hs, aw in rows_s:
                outcome = None if hs == aw else hs > aw
                res.append((season, week, game_id, home, outcome))
                res.append((season, week, game_id, away, None if outcome is None else not outcome))
            states_l = ss2.streak_states(res)
            ss2.attach([row for cell in pool.values() for _event, row, _runoff, _spot in cell], states_l)
            contextual_sampler.streak_league = ss2.league_priors(frame, states_l, cutoff)
            contextual_sampler.streak_outcomes = True
        if playcall_coverage:  # defensive coverage on dropbacks: the defense's prior shares; outcomes conditioned on it
            if eligible_before is None:
                raise ValueError('coverage priors need an eligible-before cutoff')
            import defense_layer as dl
            seasons = sorted({int(row['season']) for row in rows})
            dl.attach([row for cell in pool.values() for _event, row, _runoff, _spot in cell], dl.load_coverage(db, seasons))
            contextual_sampler.defense_priors = dl.priors(db, int(eligible_before[0]))
            contextual_sampler.coverage_outcomes = True
        if playcall_player_shares:  # prior-season player target and carry shares for the pre-event adapter
            if eligible_before is None:
                raise ValueError('player shares need an eligible-before cutoff')
            import player_shares as ps
            contextual_sampler.player_shares = ps.load(db, int(eligible_before[0]))
        contextual_pool_manifest = contextual_sampler.describe()
    kick_source = rows if kickoff_regime_season is None else e1.load_seasons(db, KICKOFF_SEASONS)
    kick_rows = [r for r in kick_source if not regulation_only or (r['qtr'] is not None and int(r['qtr']) <= 4)]
    kpool, kex = gs.build_kickoff_pool(kick_rows, include_season=kickoff_regime_season is not None)
    kickoff_regime = None
    if kickoff_regime_season is not None:
        kpool, kickoff_regime = regime_kickoffs(kpool, kickoff_regime_season, kickoff_before)
    kicks = mk.load_kick_table(db, eligible_before=eligible_before)
    # Under a cutoff a bucket can have no observed attempts yet (for example 50+ before 2025). It is left out rather than
    # filled, and the engine then records `field_goal_outcomes_missing:<bucket>` as a blocker if a kick reaches it.
    fg_missing = sorted(set(gs.FG_BUCKETS) - set(kicks['field_goal']))
    if eligible_before is None and fg_missing:
        raise SystemExit(f"kick table buckets {sorted(kicks['field_goal'])} do not match {list(gs.FG_BUCKETS)}")
    if not set(kicks['field_goal']) <= set(gs.FG_BUCKETS):
        raise SystemExit(f"kick table has unknown buckets {sorted(kicks['field_goal'])}")
    blocked = load_blocked_kicks(eligible_before=eligible_before)
    if eligible_before is not None:
        blocked['rates'] = cutoff_blocked_rates(db, blocked, eligible_before)
    for bucket, expected in blocked['rates']['field_goal_blocked_by_snap_bucket'].items():
        counts = kicks['field_goal_outcomes'].get(bucket)
        if counts is None or sum(counts) != expected['attempts'] or counts[2] != expected['blocked']:
            raise ValueError(f'blocked field-goal rate and publisher kick table disagree in bucket {bucket}')
    punt_rate = blocked['rates']['punt_blocked']
    if (len(blocked['records']['punt']) != punt_rate['blocked']
            or len(blocked['records']['field_goal']) != sum(x['blocked'] for x in
                                                             blocked['rates']['field_goal_blocked_by_snap_bucket'].values())):
        raise ValueError('blocked-kick transition counts disagree with the observed-rate manifest')
    safety_pool, safety_sha = (load_safety_kick_pool(eligible_before=eligible_before)
                               if safety_kick_table else (None, None))
    overtime_pool, overtime_sha = (load_overtime_drive_pool(eligible_before=eligible_before)
                                   if overtime_table else (None, None))
    try_fallback, try_fallback_sha = (load_overtime_try_fallback(eligible_before=eligible_before)
                                      if overtime_table else (None, None))
    choice_p, choice_sha = (load_overtime_choice_model(eligible_before=eligible_before)
                            if overtime_table else (None, None))
    reference = gs.Reference(pool, kpool, kicks, load_participants(db, eligible_before=eligible_before),
                             load_missed_field_goal_pool(db, eligible_before=eligible_before), blocked,
                             try_policy=try_policy,
                             safety_kick_pool=safety_pool, overtime_pool=overtime_pool, overtime_toss=overtime_toss,
                             overtime_try_p_two=try_fallback, overtime_p_kick=choice_p, overtime_choice=overtime_choice,
                             contextual_sampler=contextual_sampler)
    reference.overtime_try_sha256 = try_fallback_sha
    reference.kickoff_regime = kickoff_regime
    reference.overtime_choice_sha256 = choice_sha
    reference.safety_kick_sha256 = safety_sha
    reference.overtime_sha256 = overtime_sha
    reference.position_usage = load_position_usage(db, eligible_before=eligible_before)
    reference.pool_scope = {'regulation_only': regulation_only,
                            'overtime_rows_excluded_from_pool': pool_excluded.get('overtime rows (regulation-only pool)', 0),
                            'overtime_rows_removed_before_kickoff_pool': len(rows) - len(kick_rows),
                            'kick_table': 'not filtered: the published kick rates include overtime kicks',
                            'eligible_before': list(eligible_before) if eligible_before is not None else None,
                            'eligible_play_seasons': sorted({int(row['season']) for row in rows}),
                            'special_teams_artifact_window': '2022-2025',
                            'safety_kick_table': 'observed 2022-2025 regular-season safety free kicks, usable rows only'}
    if contextual_sampler is not None:
        reference.contextual_pool_manifest = contextual_pool_manifest
    reference.model_inputs = _reference_fingerprint(reference)
    return reference, kex
