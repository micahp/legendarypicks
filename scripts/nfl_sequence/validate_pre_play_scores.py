"""Validate pre-play score fields in the nflverse raw play-by-play, joined to nfl_pbp by (game_id, play_id).

Research infrastructure. It reads the raw files and the dev database read-only, for the seasons passed in. It never reads a
season outside them, and the 2026 holdout is refused before any file opens.

Checks, per season and regular-season week 1 to 18:
- join coverage between nfl_pbp and the raw file, in both directions;
- agreement of shared fields (team, quarter, down, distance, field, clock, play type) for matched plays;
- internal consistency: score_differential equals posteam_score minus defteam_score;
- continuity: a play's pre-play score equals the previous play's post-play score for the same team, and the team swaps when
  possession changes;
- pre-play totals never decrease within a game;
- final scores: the last play's post-play score matches nfl_schedule home_score and away_score.

Usage: python3 validate_pre_play_scores.py --seasons 2022 2023 2024 2025 [--raw DIR] [--out JSON]
"""
import argparse
import csv
import gzip
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import nfl_team_codes  # noqa: E402
import holdout  # noqa: E402

DEFAULT_RAW = '/root/gridiron-playbooks-research/data/raw'
DEFAULT_DB = '/root/legendarypicks/backend/data/picks.dev.db'
RAW_FIELDS = ('game_id', 'play_id', 'season', 'week', 'season_type', 'qtr', 'game_seconds_remaining', 'down', 'ydstogo',
              'yardline_100', 'play_type', 'posteam', 'defteam', 'home_team', 'away_team', 'posteam_score', 'defteam_score',
              'score_differential', 'total_home_score', 'total_away_score', 'posteam_score_post', 'defteam_score_post')
SHARED = ('posteam', 'qtr', 'down', 'ydstogo', 'yardline_100', 'game_seconds_remaining', 'play_type')
# nflverse spells two clubs LA and WAS; the play-by-play table spells them LAR and WSH. Both sides are normalised to the table.
TEAM_CODES = nfl_team_codes.PBP_TEAM_CODE_ALIASES


def norm(code):
    return nfl_team_codes.to_pbp_team_code(code) if code else code


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(text):
    if text in (None, ''):
        return None
    return float(text)


def raw_plays(path, season):
    rows = {}
    with gzip.open(path, 'rt', newline='') as f:
        for r in csv.DictReader(f):
            if r['season_type'] != 'REG' or not r['week'] or int(r['week']) > 18:
                continue
            if int(r['season']) != season:
                continue
            row = {k: r[k] for k in RAW_FIELDS}
            for field in ('posteam', 'defteam', 'home_team', 'away_team'):
                row[field] = norm(row[field])
            rows[(r['game_id'], int(float(r['play_id'])))] = row
    return rows


def db_plays(db, season):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    try:
        cur = con.execute("""SELECT game_id, play_id, posteam, qtr, down, ydstogo, yardline_100, game_seconds_remaining,
                                    play_type FROM nfl_pbp WHERE season=? AND week<=18""", (season,))
        return {(g, int(p)): dict(zip(('posteam', 'qtr', 'down', 'ydstogo', 'yardline_100', 'game_seconds_remaining',
                                       'play_type'), rest)) for g, p, *rest in cur}
    finally:
        con.close()


def schedule_finals(db, season):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    try:
        return {g: (h, a, norm(ht), norm(at)) for g, h, a, ht, at in con.execute(
            "SELECT game_id, home_score, away_score, home_team, away_team FROM nfl_schedule WHERE season=? "
            "AND game_type='REG' AND home_score IS NOT NULL AND away_score IS NOT NULL", (season,))}
    finally:
        con.close()


def validate(season, raw_dir, db):
    holdout.refuse_if_holdout(season, 'pre-play score validation')
    path = Path(raw_dir) / f'pbp_{season}.csv.gz'
    raw = raw_plays(path, season)
    db_rows = db_plays(db, season)
    result = {'season': season, 'raw_file': path.name, 'raw_file_sha256': sha256(path),
              'raw_regular_season_plays': len(raw), 'db_regular_season_plays': len(db_rows)}
    result['raw_matched_to_db'] = sum(1 for key in raw if key in db_rows)
    result['db_unmatched_in_raw'] = sum(1 for key in db_rows if key not in raw)
    result['raw_unmatched_in_db'] = sum(1 for key in raw if key not in db_rows)

    mismatches = Counter()
    for key, db_row in db_rows.items():
        r = raw.get(key)
        if r is None:
            continue
        for field in SHARED:
            if field == 'posteam':
                same = (db_row['posteam'] or '') == (r['posteam'] or '')
            elif field in ('ydstogo', 'yardline_100', 'game_seconds_remaining', 'down', 'qtr'):
                a, b = db_row[field], number(r[field])
                same = (a is None and b is None) or (a is not None and b is not None and abs(float(a) - b) < 1e-9)
            else:
                same = (db_row[field] or '') == (r[field] or '')
            if not same:
                mismatches[field] += 1
    result['shared_field_mismatches'] = dict(mismatches)

    inconsistent = 0
    scored = 0
    by_game = defaultdict(list)
    for key, r in raw.items():
        ps, ds, sd = number(r['posteam_score']), number(r['defteam_score']), number(r['score_differential'])
        if ps is not None and ds is not None and sd is not None:
            scored += 1
            if abs((ps - ds) - sd) > 1e-9:
                inconsistent += 1
        by_game[key[0]].append((key[1], r))
    result['score_differential_checked'] = scored
    result['score_differential_inconsistent'] = inconsistent

    decreases = 0
    decrease_types = Counter()
    continuity_checked = continuity_bad = 0
    for game, plays in by_game.items():
        plays.sort(key=lambda item: item[0])
        last_home = last_away = None
        for index, (_, r) in enumerate(plays):
            home, away = number(r['total_home_score']), number(r['total_away_score'])
            if home is not None and last_home is not None and home < last_home:
                decreases += 1
                decrease_types[r['play_type'] or 'null'] += 1
            if away is not None and last_away is not None and away < last_away:
                decreases += 1
                decrease_types[r['play_type'] or 'null'] += 1
            last_home = home if home is not None else last_home
            last_away = away if away is not None else last_away
            if index + 1 < len(plays):
                nxt = plays[index + 1][1]
                if r['posteam_score_post'] and nxt['posteam_score'] and r['posteam'] and nxt['posteam']:
                    continuity_checked += 1
                    if nxt['posteam'] == r['posteam']:
                        expected = (number(r['posteam_score_post']), number(r['defteam_score_post']))
                        actual = (number(nxt['posteam_score']), number(nxt['defteam_score']))
                    else:
                        expected = (number(r['defteam_score_post']), number(r['posteam_score_post']))
                        actual = (number(nxt['posteam_score']), number(nxt['defteam_score']))
                    if expected != actual:
                        continuity_bad += 1
    result['pre_play_totals_decreases'] = decreases
    result['pre_play_totals_decreases_by_play_type'] = dict(decrease_types)
    result['continuity_checked'] = continuity_checked
    result['continuity_mismatches'] = continuity_bad

    finals = schedule_finals(db, season)
    final_checked = final_ok = 0
    for game, plays in by_game.items():
        if game not in finals or not plays:
            continue
        last = plays[-1][1]
        home_score, away_score, home_team, away_team = finals[game]
        post_team, post_opp = number(last['posteam_score_post']), number(last['defteam_score_post'])
        if post_team is None or post_opp is None or not last['posteam']:
            continue
        home_post, away_post = (post_team, post_opp) if last['posteam'] == home_team else (post_opp, post_team)
        final_checked += 1
        if home_post == home_score and away_post == away_score:
            final_ok += 1
    result['final_scores_checked'] = final_checked
    result['final_scores_matching_schedule'] = final_ok
    result['games_with_raw_plays'] = len(by_game)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', type=int, nargs='+', required=True)
    ap.add_argument('--raw', default=DEFAULT_RAW)
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    report = [validate(season, args.raw, args.db) for season in args.seasons]
    text = json.dumps(report, indent=1, sort_keys=True)
    if args.out:
        args.out.write_text(text + '\n')
    print(text)


if __name__ == '__main__':
    main()
