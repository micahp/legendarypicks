"""Market comparison cohort for 2026 weeks 5 to 7 (research, not adopted).

A game is in the cohort when a live market capture (Bovada or The Odds API) has a captured_at before the game's kickoff. nflverse
rows carry ingest times, not quote times, so they are counted separately and do not define the cohort. For each game the script records the earliest
capture and whether an existing model's locked projection (nfl_projections_superseded, locked = 1) has an as_of before that
capture. No SLC forecast was locked before these games, so SLC has no eligible prediction in this cohort.

Usage: python3 market_cohort_2026.py --db DB --out JSON
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone

import pytz

LIVE_SOURCES = ('bovada', 'theoddsapi:draftkings')
ET = pytz.timezone('America/New_York')


def kickoff_utc(gameday, gametime):
    return ET.localize(datetime.strptime(f'{gameday} {gametime}', '%Y-%m-%d %H:%M')).astimezone(timezone.utc)


def parse(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    schedule = {r[0]: r for r in con.execute(
        "SELECT game_id, season, week, gameday, gametime, away_team, home_team FROM nfl_schedule "
        "WHERE season=2026 AND week BETWEEN 5 AND 7")}
    captures, nflverse_pre = {}, set()
    for source, game_id, captured in con.execute(
            "SELECT source, game_id, captured_at FROM nfl_line_snapshots WHERE substr(game_id, 1, 7) IN "
            "('2026_05', '2026_06', '2026_07')"):
        if source in LIVE_SOURCES:
            captures.setdefault(game_id, []).append((parse(captured), source))
        elif source == 'nflverse' and game_id in schedule and parse(captured) < kickoff_utc(schedule[game_id][3], schedule[game_id][4]):
            nflverse_pre.add(game_id)
    locked = {}
    for game_id, as_of, model in con.execute(
            "SELECT game_id, as_of, model_version FROM nfl_projections_superseded WHERE locked = 1"):
        locked.setdefault(game_id, []).append((parse(as_of), model))
    rows, cohort = [], 0
    for game_id, (gid, season, week, gameday, gametime, away, home) in sorted(schedule.items()):
        kick = kickoff_utc(gameday, gametime)
        live = sorted(c for c in captures.get(game_id, []) if c[0] < kick)
        if not live:
            continue
        cohort += 1
        first = live[0][0]
        before = sorted({model for as_of, model in locked.get(game_id, []) if as_of < first})
        rows.append({'game_id': game_id, 'week': week, 'kickoff_utc': kick.isoformat().replace('+00:00', 'Z'),
                     'first_pre_kickoff_capture_utc': first.isoformat().replace('+00:00', 'Z'),
                     'capture_sources': sorted({s for _t, s in live}),
                     'existing_locked_models_before_capture': before,
                     'slc_locked_before_capture': False})
    summary = {'games_in_schedule_weeks_5_7': len(schedule), 'cohort_games': cohort,
               'with_existing_locked_model_before_capture': sum(1 for r in rows if r['existing_locked_models_before_capture']),
               'with_slc_locked_before_capture': 0,
               'nflverse_rows_before_kickoff_supporting_only': len(nflverse_pre),
               'note': 'the cohort uses live captures only (Bovada, The Odds API). nflverse rows carry ingest times, and the '
                       'values they hold may have changed after the pull, so they support but do not define the cohort'}
    with open(args.out, 'w') as handle:
        json.dump({'summary': summary, 'games': rows}, handle, indent=1, sort_keys=True)
        handle.write('\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
