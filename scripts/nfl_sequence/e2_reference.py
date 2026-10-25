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
    extras_hash = hashlib.sha256(PLAY_EXTRAS.read_bytes()).hexdigest()
    add(['play-extras-file-sha256', extras_hash])
    return {
        'schema': 'lp-e2-observed-reference-1',
        'sha256': digest.hexdigest(),
        **reference.position_usage,
        'play_cells': len(reference.pool),
        'play_samples': sum(len(cell) for cell in reference.pool.values()),
        'kickoff_samples': len(reference.kickoff_pool),
        'participant_rows': len(reference.participants),
        'play_extras_sha256': extras_hash,
    }


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
posteam, air_yards, receiving_yards, play_type FROM nfl_pbp WHERE {mk.WINDOW}""").fetchall()
    finally:
        con.close()
    flags = {}
    with open(extras, newline='') as f:
        for r in csv.DictReader(f):
            flags[(r['game_id'], int(float(r['play_id'])))] = (int(r['timeout']), r['timeout_team'],
                                                                int(r['out_of_bounds']))
    out = {}
    for g, p, pa, ru, re_, posteam, air, rec_yds, play_type in rows:
        t, t_team, oob = flags.get((g, int(p)), (0, '', 0))
        yac = (rec_yds - air) if (rec_yds is not None and air is not None and re_) else None
        out[(g, int(p))] = {'passer_id': pa, 'rusher_id': ru, 'receiver_id': re_, 'posteam': posteam,
                            'air_yards': air, 'yards_after_catch': yac, 'play_type': play_type,
                            'timeout': t, 'timeout_team': t_team,
                            'out_of_bounds': oob}
    return out


def load(db=e1.DEFAULT_DB, regulation_only=True):
    """Returns (Reference, excluded_kickoffs). Refuses a kick table whose buckets do not match the engine's.

    `regulation_only` (the successor default): the E1 pool and the kickoff pool draw from quarters 1-4 only. The 1,214 overtime
    rows of 2022-2025 are excluded and counted on the reference as `pool_scope`. False reproduces the accepted E2 artifacts,
    which sampled overtime rows. The published kick table is not filtered (its rates include the overtime kicks), and this is
    disclosed on the reference too.
    """
    rows = e1.load(db)
    pool, pool_excluded = e1.build_pool(rows, regulation_only=regulation_only)
    kick_rows = [r for r in rows if not regulation_only or (r['qtr'] is not None and int(r['qtr']) <= 4)]
    kpool, kex = gs.build_kickoff_pool(kick_rows)
    kicks = mk.load_kick_table(db)
    if set(kicks['field_goal']) != set(gs.FG_BUCKETS):
        raise SystemExit(f"kick table buckets {sorted(kicks['field_goal'])} do not match {list(gs.FG_BUCKETS)}")
    reference = gs.Reference(pool, kpool, kicks, load_participants(db))
    reference.position_usage = load_position_usage(db)
    reference.pool_scope = {'regulation_only': regulation_only,
                            'overtime_rows_excluded_from_pool': pool_excluded.get('overtime rows (regulation-only pool)', 0),
                            'overtime_rows_removed_before_kickoff_pool': len(rows) - len(kick_rows),
                            'kick_table': 'not filtered: the published kick rates include overtime kicks'}
    reference.model_inputs = _reference_fingerprint(reference)
    return reference, kex
