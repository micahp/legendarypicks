"""Replay 2024 regular-season games through the SLC path and record each simulated drive (research, exploratory, not adopted).

Every game is built from an exploratory snapshot (no schedule version or depth publication time is verified for 2024), and the
reference is cut to the weeks before the season (2024, week 1): only 2022 and 2023 outcomes enter the pool. The play-call artifact
is fitted through 2023. Outputs are one line per simulated game: points, and for each drive its terminal, points, plays and clock.
This is a calibration of the engine against the 2024 season, not a predictive test.

Usage: python3 scoring_calibration_2024.py --seeds N --out JSONL
"""
import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402
import pregame_snapshot as ps  # noqa: E402
import slc_engine as se  # noqa: E402

DB = '/root/legendarypicks/backend/data/picks.dev.db'
ARTIFACT = 'docs/research/SLC-PLAYCALL-ARTIFACT-FIT-2010-2023-v1.json'


def drive_rows(record):
    rows = []
    for drive in record['drives']:
        plays = drive.get('plays', [])
        rows.append({'offense': drive['offense_team'], 'terminal': drive.get('terminal'),
                     'points': (drive.get('points_scored_on_drive') or {}).get('points', 0),
                     'plays': len(plays), 'events': [play['event_type'] for play in plays],
                     'quarter_start': drive.get('quarter_start'), 'end_quarter': drive.get('end_quarter'),
                     'clock_start': drive.get('clock_start'), 'end_clock': drive.get('end_clock')})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seeds', type=int, default=5)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--formation', action='store_true', help='pre-event formation and personnel, outcomes conditioned on formation')
    args = ap.parse_args()
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    games = con.execute("SELECT game_id, week, gameday FROM nfl_schedule WHERE season=2024 AND game_type='REG' "
                        "ORDER BY week, gameday, game_id").fetchall()
    ref, _ = er.load(DB, eligible_before=(2024, 1), playcall_artifact=ARTIFACT, playcall_teams={'A': 'X', 'B': 'Y'},
                     playcall_formation=args.formation)
    with args.out.open('w') as out:
        for game_id, week, gameday in games:
            as_of = (date.fromisoformat(gameday) - timedelta(days=1)).isoformat() + 'T12:00:00Z'
            try:
                snapshot = ps.build(DB, game_id, as_of, allow_unverified_current_schedule_exploratory=True,
                                    evaluation='exploratory_replay')
            except ValueError as exc:
                out.write(json.dumps({'game_id': game_id, 'skipped': str(exc)[:160]}) + '\n')
                continue
            ref.contextual_sampler.side_teams = se.side_teams(snapshot)
            ref.contextual_sampler.participant_chooser = None  # set per game by slc_engine.play
            snapshot['model_reference']['observed_reference'] = ref.model_inputs
            for seed in range(1, args.seeds + 1):
                try:
                    record, _decisions = se.play(seed, ref, snapshot)
                except Exception as exc:  # every attempted game is recorded, including engine errors
                    out.write(json.dumps({'game_id': game_id, 'seed': seed, 'error': f'{type(exc).__name__}: {exc}'[:200]}) + '\n')
                    continue
                out.write(json.dumps({'game_id': game_id, 'seed': seed, 'week': week, 'status': record.get('status'),
                                      'points': record.get('points'), 'teams': {'A': snapshot['schedule']['home_team'],
                                                                                'B': snapshot['schedule']['away_team']},
                                      'drives': drive_rows(record)}) + '\n')
            out.flush()


if __name__ == '__main__':
    main()
