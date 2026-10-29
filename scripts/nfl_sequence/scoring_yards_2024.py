"""Yards per run and pass play by field zone, replay against 2024 (research, exploratory).

The replay is the default SLC path (the same snapshots, cutoff and artifact as scoring_calibration_2024.py). For each simulated run or
pass play, the yards gained are the state's yard line before minus the yard line after, when the play stays on the field; a touchdown gains the yard line before (it
has no spot after). Sacks, interceptions and lost fumbles are excluded on both sides, so the two sides count the same plays. The
actual yards come from the play-by-play column yards_gained. Zones are the yard line before the play: 1-19, 20-49, 50-99. Output: mean yards,
the share of plays that gain a first down (sim: the next play is first down for the same offense; actual: the first-down flag),
and counts, per play type and zone.

Usage: python3 scoring_yards_2024.py --seeds N --out JSON
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


def zone(yl):
    if yl is None:
        return None
    return '1-19' if yl <= 19 else '20-49' if yl <= 49 else '50-99'


def simulated(seeds):
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    games = con.execute("SELECT game_id, gameday FROM nfl_schedule WHERE season=2024 AND game_type='REG' AND week >= 2 "
                        "ORDER BY week, gameday, game_id").fetchall()
    ref, _ = er.load(DB, eligible_before=(2024, 1), playcall_artifact=ARTIFACT, playcall_teams={'A': 'X', 'B': 'Y'})
    acc = collections.defaultdict(lambda: [0, 0.0, 0, 0])  # (type, zone) -> plays, yards, first downs, with a next play
    for game_id, gameday in games:
        as_of = (date.fromisoformat(gameday) - timedelta(days=1)).isoformat() + 'T12:00:00Z'
        try:
            snapshot = ps.build(DB, game_id, as_of, allow_unverified_current_schedule_exploratory=True,
                                evaluation='exploratory_replay')
        except ValueError:
            continue
        ref.contextual_sampler.side_teams = se.side_teams(snapshot)
        snapshot['model_reference']['observed_reference'] = ref.model_inputs
        for seed in range(1, seeds + 1):
            try:
                record, _d = se.play(seed, ref, snapshot)
            except Exception:
                continue
            for drive in record['drives']:
                plays = drive.get('plays', [])
                for i, play in enumerate(plays):
                    kind = {'run': 'run', 'pass_complete': 'pass', 'pass_incomplete': 'pass'}.get(play['event_type'])
                    before = play['state_before']['yardline_100']
                    after = play['state_after'].get('yardline_100')
                    if kind is None or before is None:
                        continue
                    if play['outcome']['touchdown']:  # a touchdown has no spot after it: the gain is the distance to the goal
                        gain = before
                    elif after is None or play['state_after'].get('down') is None:
                        continue
                    else:
                        gain = before - after
                    z = zone(before)
                    if z is None:
                        continue
                    row = acc[(kind, z)]
                    row[0] += 1
                    row[1] += gain
                    nxt = plays[i + 1] if i + 1 < len(plays) else None
                    if nxt is not None:
                        row[3] += 1
                        if nxt['state_before']['down'] == 1:
                            row[2] += 1
    return acc


def actual():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    acc = collections.defaultdict(lambda: [0, 0.0, 0, 0])
    rows = con.execute("SELECT game_id, drive, posteam, play_id, down, play_type, yardline_100, yards_gained, sack, interception, "
                       "fumble_lost FROM nfl_pbp WHERE season=2024 AND week BETWEEN 2 AND 18 AND posteam IS NOT NULL "
                       "AND drive IS NOT NULL ORDER BY game_id, drive, posteam, play_id").fetchall()
    drives = collections.defaultdict(list)
    for row in rows:
        drives[(row[0], row[1], row[2])].append(row)
    for plays in drives.values():
        for i, play in enumerate(plays):
            _g, _d, _t, _p, down, play_type, yl, gained, sack, interception, fumble_lost = play
            if play_type not in ('run', 'pass') or yl is None or gained is None:
                continue
            if sack == 1 or interception == 1 or fumble_lost == 1:  # the same exclusions as the replay
                continue
            z = zone(int(yl))
            row = acc[(play_type, z)]
            row[0] += 1
            row[1] += float(gained)
            nxt = plays[i + 1] if i + 1 < len(plays) else None
            if nxt is not None:
                row[3] += 1
                if nxt[4] == 1:
                    row[2] += 1
    return acc


def table(acc):
    out = {}
    for (kind, z), (n, yards, firsts, with_next) in sorted(acc.items()):
        out[f'{kind}_{z}'] = {'plays': n, 'mean_yards': round(yards / n, 3) if n else None,
                              'first_down_share': round(firsts / with_next, 4) if with_next else None}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    result = {'replay': table(simulated(args.seeds)), 'actual_2024': table(actual()),
              'definitions': ('run or pass plays with a known yard line; sacks, interceptions and lost fumbles excluded on both '
                              'sides; touchdowns included on both sides (replay gain = yard line before the play); zone by yard '
                              'line before the play')}
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True)[:600])


if __name__ == '__main__':
    main()
