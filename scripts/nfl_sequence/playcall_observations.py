"""Historical play-call observations from nfl_pbp, with exact pre-snap fields, pre-play scores and cutoff-safe selection.

Model layer: situational play-calling. The play facts come from nfl_pbp, which holds the regular-season history from 2010 to
2025. The pre-play scores come from the nflverse raw play-by-play for the same seasons, joined on (game_id, play_id). Each raw
file is checked against a pinned SHA-256 before it is read, and a season with no verified raw file fails closed.

It does not read FTN charting, participation or NGS. Those layers can join on top of these rows where they exist, and their
absence never removes a play.

Score status:
- pre_play_nflverse_raw: the joined pre-play scores are present; score_differential is posteam minus defteam before the play.
- excluded_no_play_row: a no-play row (penalty or timeout). Its score fields are not pre-play state, so they are dropped.
- raw_score_missing: the play joined, but a score field is empty in the raw file.
- unmatched_in_raw: the play has no row in the raw file.
"""
import csv
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import holdout

FIRST_SEASON = 2010
LAST_SEASON = 2025  # 2026 is the sealed holdout; nothing in this module reads it
MODEL_LAYER = 'situational_play_calling'
SOURCE = 'nfl_pbp'
RAW_2022_2025 = Path('/root/gridiron-playbooks-research/data/raw')
PINS_2022_2025 = Path('/root/gridiron-playbooks-research/data/playbooks/research-2026-10-27/build_manifest.json')
RAW_2010_2021 = Path('/root/lp-snapshots/nfl-pbp-2010-2021')
COLUMNS = ('game_id', 'play_id', 'season', 'week', 'posteam', 'defteam', 'home_team', 'away_team', 'qtr', 'down',
           'ydstogo', 'yardline_100', 'game_seconds_remaining', 'play_type', 'yards_gained', 'pass_attempt', 'rush_attempt',
           'qb_dropback', 'sack', 'qb_scramble', 'two_point_attempt', 'shotgun', 'no_huddle', 'touchdown', 'interception',
           'fumble_lost', 'complete_pass')
SPECIAL_TEAMS = {'punt': 'punt', 'field_goal': 'field_goal', 'extra_point': 'extra_point', 'kickoff': 'kickoff'}
FLAGS_PATH = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'score-exceptions' / 'score_continuity_exceptions_2010_2025.csv'


def load_score_flags(path=FLAGS_PATH):
    """Plays whose pre-play score disagrees with the previous play's post-play score (the 2010 to 2025 trace). A flagged play
    keeps its score and is labelled, so a query can exclude it. Nothing is corrected."""
    import csv
    flags = {}
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            flags[(r['game_id'], int(float(r['play_id'])))] = r['label']
    return flags


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def score_source(season):
    """(path, pinned sha256) for the raw play-by-play that carries the pre-play scores for a season."""
    if 2022 <= season <= 2025:
        pinned = json.loads(PINS_2022_2025.read_text())['source_hashes'][str(season)]['pbp']['sha256']
        return RAW_2022_2025 / f'pbp_{season}.csv.gz', pinned
    if 2010 <= season <= 2021:
        pinned = json.loads((RAW_2010_2021 / 'MANIFEST.json').read_text())['files'][str(season)]['sha256']
        return RAW_2010_2021 / f'pbp_{season}.csv.gz', pinned
    raise ValueError(f'no raw pre-play score source for season {season}')


def _int_or_none(text):
    return None if text in (None, '') else int(float(text))


def load_pre_play_scores(path, expected_sha256):
    """Pre-play scores from one raw file, keyed by (game_id, play_id). Refuses a file whose checksum is not the pinned one."""
    actual = sha256(path)
    if actual != expected_sha256:
        raise ValueError(f'pre-play score source checksum mismatch: {path} has {actual}, pinned {expected_sha256}')
    scores = {}
    with gzip.open(path, 'rt', newline='') as f:
        for r in csv.DictReader(f):
            if r['season_type'] != 'REG' or not r['week'] or int(r['week']) > 18:
                continue
            scores[(r['game_id'], int(float(r['play_id'])))] = {
                'posteam_score': _int_or_none(r['posteam_score']),
                'defteam_score': _int_or_none(r['defteam_score']),
                'score_differential': _int_or_none(r['score_differential']),
                'goal_to_go': _int_or_none(r['goal_to_go']),
            }
    return scores


def scores_for_season(season):
    """Pre-play scores for one season. Read per call and not cached: observations() visits each season once, so holding
    every season in memory would cost space without saving any time."""
    path, pinned = score_source(season)
    return load_pre_play_scores(path, pinned)


def classify(row):
    """Return (intent, fourth_down_decision). Intent is the called action where the record supports one.

    A dropback that ends as a sack or a recorded scramble stays a dropback; the outcome is kept in its own flags.
    Missing play types stay 'unknown'. Nothing is guessed from yardage or the result.
    """
    play_type = row['play_type']
    if row['two_point_attempt'] == 1:
        return 'two_point', None
    if play_type == 'qb_kneel':
        return 'kneel', None
    if play_type == 'qb_spike':
        return 'spike', None
    if play_type in SPECIAL_TEAMS:
        decision = SPECIAL_TEAMS[play_type] if row['down'] == 4 else None
        return 'special_teams', decision
    if play_type == 'no_play':
        return 'no_play', None
    if play_type is None:
        return 'unknown', None
    if play_type == 'pass' or row['sack'] == 1 or row['qb_scramble'] == 1:
        decision = 'go_for_it' if row['down'] == 4 else None
        return 'dropback', decision
    if play_type == 'run':
        decision = 'go_for_it' if row['down'] == 4 else None
        return 'run', decision
    return 'unknown', None


def score_fields(intent, raw_scores):
    """The pre-play score fields and their status for one play, from the raw record (or None when unmatched)."""
    if raw_scores is None:
        return {'posteam_score_pre': None, 'defteam_score_pre': None, 'score_differential': None,
                'score_status': 'unmatched_in_raw'}
    if intent == 'no_play':
        return {'posteam_score_pre': None, 'defteam_score_pre': None, 'score_differential': None,
                'score_status': 'excluded_no_play_row'}
    posteam, defteam = raw_scores['posteam_score'], raw_scores['defteam_score']
    if posteam is None or defteam is None:
        return {'posteam_score_pre': None, 'defteam_score_pre': None, 'score_differential': None,
                'score_status': 'raw_score_missing'}
    return {'posteam_score_pre': posteam, 'defteam_score_pre': defteam, 'score_differential': posteam - defteam,
            'score_status': 'pre_play_nflverse_raw'}


def goal_to_go_flag(raw_scores):
    """The verified goal-to-go indicator from the raw file, or None. Distance to goal is not used: a second-and-2 at the
    opponent's 8 is not goal-to-go, and only the publisher's flag says whether it was."""
    if raw_scores is None or raw_scores.get('goal_to_go') is None:
        return None
    return bool(raw_scores['goal_to_go'])


def observation(row, raw_scores=None, score_flag=None):
    qtr = row['qtr']
    clock = row['game_seconds_remaining']
    regulation = qtr is not None and 1 <= int(qtr) <= 4 and clock is not None
    seconds_in_quarter = int(clock) - 900 * (4 - int(qtr)) if regulation else None
    intent, decision = classify(row)
    yardline = row['yardline_100']
    scores = score_fields(intent, raw_scores)
    if score_flag is not None and scores['score_status'] == 'pre_play_nflverse_raw':
        scores = {**scores, 'score_status': 'flagged_continuity_exception'}
    return {
        'game_id': row['game_id'], 'play_id': row['play_id'], 'season': row['season'], 'week': row['week'],
        'qtr': qtr, 'overtime': qtr is not None and int(qtr) >= 5,
        'down': row['down'], 'ydstogo': row['ydstogo'], 'yardline_100': yardline,
        'game_seconds_remaining': clock, 'seconds_in_quarter': seconds_in_quarter,
        'two_minute_window': bool(regulation and int(qtr) in (2, 4) and seconds_in_quarter <= 120),
        'red_zone': None if yardline is None else yardline <= 20,
        'goal_to_go': goal_to_go_flag(raw_scores),
        'goal_to_go_status': 'verified_nflverse_raw' if raw_scores is not None and raw_scores.get('goal_to_go') is not None
        else 'unavailable',
        'posteam': row['posteam'], 'defteam': row['defteam'], 'home_team': row['home_team'], 'away_team': row['away_team'],
        'shotgun': row['shotgun'], 'no_huddle': row['no_huddle'],
        'intent': intent, 'fourth_down_decision': decision,
        'sack': row['sack'], 'scramble': row['qb_scramble'], 'touchdown': row['touchdown'],
        'interception': row['interception'], 'fumble_lost': row['fumble_lost'], 'yards_gained': row['yards_gained'],
        **scores,
        'score_flag': score_flag,
        'provenance': {'source': SOURCE, 'season': row['season'], 'model_layer': MODEL_LAYER,
                       'score_source': 'nflverse raw play-by-play, pinned' if raw_scores is not None else None},
    }


def observations(db, first_season=FIRST_SEASON, last_season=LAST_SEASON, cutoff=None, scores=scores_for_season,
                 flags=None):
    """Yield play-call observations for regular-season plays in [first_season, last_season].

    `cutoff` is (season, week). When given, only games in weeks strictly before it are yielded, so a later game cannot
    reach an earlier prediction. The holdout season is refused before any query, and the range is capped at LAST_SEASON.
    `scores(season)` returns the pre-play scores for a season; the default reads the pinned raw files.
    """
    holdout.refuse_if_holdout(last_season, 'play-call observations')
    if first_season < FIRST_SEASON or last_season > LAST_SEASON or first_season > last_season:
        raise ValueError(f'play-call window must sit inside {FIRST_SEASON}-{LAST_SEASON}')
    season_flags = load_score_flags() if flags is None else flags
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        for season in range(first_season, last_season + 1):
            clauses = ['season = ?', 'week <= 18']
            params = [season]
            if cutoff is not None:
                cutoff_season, cutoff_week = int(cutoff[0]), int(cutoff[1])
                if cutoff_season > LAST_SEASON + 1:
                    raise ValueError('cutoff is outside the allowed history')
                clauses.append('(season < ? OR (season = ? AND week < ?))')
                params += [cutoff_season, cutoff_season, cutoff_week]
            sql = (f"SELECT {', '.join(COLUMNS)} FROM nfl_pbp WHERE {' AND '.join(clauses)} "
                   "ORDER BY season, game_id, play_id")
            season_scores = scores(season)
            for row in con.execute(sql, params):
                key = (row['game_id'], int(row['play_id']))
                yield observation(dict(row), season_scores.get(key), season_flags.get(key))
    finally:
        con.close()
