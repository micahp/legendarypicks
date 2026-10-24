#!/usr/bin/env python3
"""Join the 2022 Big Data Bowl tracking plays (weeks 1-9) to LP nfl_pbp, and audit which join fields actually match.

Read-only on both sides: the dev database is opened with mode=ro, and the BDB files are read, never written.

BDB source: /root/nfl-tracking-data/bdb2025/code-data (games.csv, plays.csv; the 2022 season, see PROVENANCE.json).
LP source:  nfl_pbp in the dev database, season 2022, weeks 1-9.

Join fields, all taken from both sides:
- game:      LP game_id, from season, week, away and home team (BDB uses LA and WAS; LP uses LAR and WSH)
- quarter:   BDB quarter == LP qtr (overtime, quarter 5, is reported separately: its clock convention is not checked here)
- clock:     BDB gameClock (mm:ss left in the quarter) == LP game_seconds_remaining minus the seconds of later quarters
- down:      BDB down == LP down
- distance:  BDB yardsToGo == LP ydstogo
- team:      BDB possessionTeam == LP posteam
- spot:      BDB yardline (side and number) converted to offense-relative yardline_100 == LP yardline_100

Usage: python3 bdb2022_join.py [--out-dir DIR]
"""
import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

BDB = Path('/root/nfl-tracking-data/bdb2025/code-data')
DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
TEAM = {'LA': 'LAR', 'WAS': 'WSH'}
QUARTER_SECONDS = 900
FIELDS = ('game', 'quarter', 'clock', 'down', 'distance', 'team', 'spot')


def lp_team(abbr):
    return TEAM.get(abbr, abbr) if abbr else None


def bdb_clock(mmss):
    m, s = mmss.split(':')
    return int(m) * 60 + int(s)


def bdb_spot(possession, side, number):
    """Offense-relative yardline_100 from BDB's side-of-field and number. None when the side is not a team."""
    if side in (None, '', 'NA'):
        return None
    side = lp_team(side)  # the side field uses BDB abbreviations too (WAS, LA), so it is mapped like the possession team
    number = int(number)
    if side == possession:
        return 100 - number
    return number


def lp_quarter_clock(qtr, gsr):
    return gsr - (4 - qtr) * QUARTER_SECONDS


def load_bdb():
    games = {}
    for g in csv.DictReader(open(BDB / 'games.csv')):
        games[g['gameId']] = {'season': int(g['season']), 'week': int(g['week']),
                              'away': lp_team(g['visitorTeamAbbr']), 'home': lp_team(g['homeTeamAbbr'])}
    plays = list(csv.DictReader(open(BDB / 'plays.csv')))
    return games, plays


def load_lp(season_weeks=(1, 9)):
    con = sqlite3.connect(DB, uri=True)
    try:
        rows = con.execute(
            "SELECT game_id, play_id, season, week, away_team, home_team, qtr, down, ydstogo, posteam, defteam, "
            "yardline_100, game_seconds_remaining, play_type FROM nfl_pbp WHERE season = 2022 AND week BETWEEN ? AND ?",
            season_weeks).fetchall()
    finally:
        con.close()
    keys = ('game_id', 'play_id', 'season', 'week', 'away_team', 'home_team', 'qtr', 'down', 'ydstogo', 'posteam',
            'defteam', 'yardline_100', 'game_seconds_remaining', 'play_type')
    return [dict(zip(keys, r)) for r in rows]


def lp_game_key(game):
    return (game['season'], game['week'], game['away'], game['home'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=str(Path(__file__).resolve().parents[2] / 'docs' / 'research'))
    args = ap.parse_args()
    games, bdb_plays = load_bdb()
    lp_rows = load_lp()
    lp_games = {}
    lp_index = {}
    for r in lp_rows:
        lp_games.setdefault(r['game_id'], []).append(r)
        lp_index[(r['season'], r['week'], r['away_team'], r['home_team'])] = r['game_id']
    game_map, unmatched_games = {}, []
    for bdb_id, g in games.items():
        key = (g['season'], g['week'], g['away'], g['home'])
        if key in lp_index:
            game_map[bdb_id] = lp_index[key]
        else:
            unmatched_games.append(bdb_id)
    report = {'bdb_games': len(games), 'games_matched': len(game_map), 'games_unmatched': unmatched_games,
              'bdb_plays': len(bdb_plays)}
    steps = ('game', 'quarter', 'clock', 'down', 'distance', 'team', 'spot')
    funnel_alive = Counter()    # plays whose candidate set is still non-empty after each step
    funnel_killed = Counter()   # the step at which the candidate set became empty
    candidate_counts = Counter()
    outcome = Counter()
    matched_pairs = {}
    spot_unknown = 0
    ot = 0
    for p in bdb_plays:
        bdb_id = p['gameId']
        if bdb_id not in game_map:
            outcome['game not matched'] += 1
            continue
        qtr = int(p['quarter'])
        if qtr > 4:
            ot += 1
            continue
        clock = bdb_clock(p['gameClock'])
        down = int(p['down']) if p['down'] else None
        distance = int(p['yardsToGo']) if p['yardsToGo'] else None
        team = lp_team(p['possessionTeam'])
        spot = bdb_spot(team, p['yardlineSide'], p['yardlineNumber'])
        if spot is None:
            spot_unknown += 1
        cands = [r for r in lp_games[game_map[bdb_id]] if r['season'] == 2022]
        tests = [
            ('quarter', lambda r: r['qtr'] == qtr),
            ('clock', lambda r: r['game_seconds_remaining'] is not None
                                and lp_quarter_clock(r['qtr'], r['game_seconds_remaining']) == clock),
            ('down', lambda r: r['down'] == down),
            ('distance', lambda r: r['ydstogo'] == distance),
            ('team', lambda r: r['posteam'] == team),
            ('spot', lambda r: spot is not None and r['yardline_100'] == spot),
        ]
        funnel_alive['game'] += 1
        for name, test in tests:
            cands = [r for r in cands if test(r)]
            if cands:
                funnel_alive[name] += 1
            else:
                funnel_killed[name] += 1
                break
        else:
            pass
        candidate_counts[len(cands)] += 1
        if len(cands) == 1:
            matched_pairs[(bdb_id, p['playId'])] = (cands[0]['game_id'], cands[0]['play_id'])
    report.update({'overtime_plays_not_checked': ot, 'spot_unknown_plays': spot_unknown,
                   'funnel_plays_still_matching_after_step': dict(funnel_alive),
                   'funnel_step_that_eliminated_all_candidates': dict(funnel_killed),
                   'final_candidate_count_distribution': dict(candidate_counts),
                   'unique_matches': len(matched_pairs), 'outcomes': dict(outcome)})
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'bdb2022-join-counts-2026-10-24.json').write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
    with open(out / 'bdb2022-join-pairs-2026-10-24.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['bdb_gameId', 'bdb_playId', 'lp_game_id', 'lp_play_id'])
        for (g_id, p_id), (lg, lp_pid) in sorted(matched_pairs.items()):
            w.writerow([g_id, p_id, lg, lp_pid])
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
