"""Which layer makes the touchdown deficit: red-zone outcomes and fourth-down decisions, replay against 2024 (research, exploratory).

The replay is the one in scoring_calibration_2024.py (same snapshots, cutoff and artifact). For each simulated play it reads the
decision type (run, dropback, punt, field goal) and the state, and for each drive whether it started inside the 20. The actual 2024
rates come from the play-by-play with the same definitions:
- a fourth-down try is a run or pass play on down 4; it converts when the next play in the drive is first down (the play-by-play has
  no conversion column, so this is the definition used on both sides);
- a red-zone trip is a drive that reaches 20 yards or closer to the goal line at any scrimmage play; its outcome is the drive's
  terminal (touchdown, field-goal attempt, turnover, and so on). Drives that start there are rare and are not the measure.

Usage: python3 scoring_redzone_2024.py --seeds N --out JSON
"""
import argparse
import collections
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


def simulated(args):
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    games = con.execute("SELECT game_id, gameday FROM nfl_schedule WHERE season=2024 AND game_type='REG' AND week >= 2 "
                        "ORDER BY week, gameday, game_id").fetchall()
    ref, _ = er.load(DB, eligible_before=(2024, 1), playcall_artifact=ARTIFACT, playcall_teams={'A': 'X', 'B': 'Y'})
    fourth = collections.Counter()
    redzone = collections.Counter()
    for game_id, gameday in games:
        as_of = (date.fromisoformat(gameday) - timedelta(days=1)).isoformat() + 'T12:00:00Z'
        try:
            snapshot = ps.build(DB, game_id, as_of, allow_unverified_current_schedule_exploratory=True,
                                evaluation='exploratory_replay')
        except ValueError:
            continue
        ref.contextual_sampler.side_teams = se.side_teams(snapshot)
        snapshot['model_reference']['observed_reference'] = ref.model_inputs
        for seed in range(1, args.seeds + 1):
            try:
                record, _decisions = se.play(seed, ref, snapshot)
            except Exception:
                fourth['errors'] += 1
                continue
            for drive in record['drives']:
                plays = drive.get('plays', [])
                if any(p['state_before']['yardline_100'] <= 20 for p in plays):  # a red-zone trip: reached the 20 at any point
                    redzone['drives'] += 1
                    redzone[f"outcome_{drive.get('terminal')}"] += 1
                for i, play in enumerate(plays):
                    state = play['state_before']
                    if state['down'] != 4:
                        continue
                    kind = play['decision']['type']
                    fourth['tries'] += 1
                    fourth[f'decision_{kind}'] += 1
                    if kind in ('run', 'dropback'):
                        fourth['go'] += 1
                        nxt = plays[i + 1] if i + 1 < len(plays) else None
                        if nxt is not None and nxt['state_before']['down'] == 1:
                            fourth['converted'] += 1
    return fourth, redzone


def actual(con):
    rows = con.execute("SELECT game_id, drive, posteam, play_id, down, play_type, yardline_100, series_result FROM nfl_pbp "
                       "WHERE season=2024 AND week BETWEEN 2 AND 18 AND posteam IS NOT NULL AND drive IS NOT NULL "
                       "ORDER BY game_id, drive, play_id").fetchall()
    drives = collections.defaultdict(list)
    for row in rows:
        drives[(row[0], row[1], row[2])].append(row)
    fourth = collections.Counter()
    redzone = collections.Counter()
    for plays in drives.values():
        if any(p[6] is not None and p[6] <= 20 for p in plays):  # a red-zone trip: reached the 20 at any scrimmage play
            redzone['drives'] += 1
            text = (plays[-1][7] or '').lower()
            if 'touchdown' in text:
                redzone['outcome_touchdown'] += 1
            elif 'field goal' in text:
                redzone['outcome_field_goal'] += 1
            else:
                redzone['outcome_other'] += 1
        for i, play in enumerate(plays):
            if play[4] != 4:
                continue
            fourth['tries'] += 1
            if play[5] in ('run', 'pass'):
                fourth['go'] += 1
                nxt = plays[i + 1] if i + 1 < len(plays) else None
                if nxt is not None and nxt[4] == 1:
                    fourth['converted'] += 1
            else:
                fourth[f'decision_{play[5]}'] += 1
    return fourth, redzone


def rates(counter):
    out = {k: v for k, v in counter.items()}
    if counter.get('tries'):
        out['go_rate'] = round(counter.get('go', 0) / counter['tries'], 4)
    if counter.get('go'):
        out['conversion_rate'] = round(counter.get('converted', 0) / counter['go'], 4)
    if counter.get('drives'):
        out['touchdown_per_redzone_drive'] = round(counter.get('outcome_touchdown', 0) / counter['drives'], 4)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    sim_fourth, sim_red = simulated(args)
    act_fourth, act_red = actual(sqlite3.connect(f'file:{DB}?mode=ro', uri=True))
    result = {
        'replay': {'fourth_down': rates(sim_fourth), 'redzone': rates(sim_red)},
        'actual_2024': {'fourth_down': rates(act_fourth), 'redzone': rates(act_red)},
        'definitions': 'fourth down: run or pass on down 4; converted: the next play in the drive is first down; red zone: '
                       'the drive reaches 20 or closer at any scrimmage play. Replay weeks 2-18, 2 seeds per game, exploratory.',
    }
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
