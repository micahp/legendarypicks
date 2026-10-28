"""Historical play-call observations from nfl_pbp, with exact pre-snap fields and cutoff-safe selection.

Model layer: situational play-calling. Reads only nfl_pbp, which holds the regular-season history from 2010 to 2025. It does
not read FTN charting, participation or NGS. Those layers can join on top of these rows where they exist, and their absence
never removes a play.

Score differential is not stored in nfl_pbp (there are no score or kick-result columns), so it is returned as None with
score_status='unavailable_in_pbp'. It is not reconstructed or estimated here.
"""
import sqlite3

import holdout

FIRST_SEASON = 2010
LAST_SEASON = 2025  # 2026 is the sealed holdout; nothing in this module reads it
MODEL_LAYER = 'situational_play_calling'
SOURCE = 'nfl_pbp'
COLUMNS = ('game_id', 'play_id', 'season', 'week', 'posteam', 'defteam', 'home_team', 'away_team', 'qtr', 'down',
           'ydstogo', 'yardline_100', 'game_seconds_remaining', 'play_type', 'yards_gained', 'pass_attempt', 'rush_attempt',
           'qb_dropback', 'sack', 'qb_scramble', 'two_point_attempt', 'shotgun', 'no_huddle', 'touchdown', 'interception',
           'fumble_lost', 'complete_pass')
SPECIAL_TEAMS = {'punt': 'punt', 'field_goal': 'field_goal', 'extra_point': 'extra_point', 'kickoff': 'kickoff'}


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


def observation(row):
    qtr = row['qtr']
    clock = row['game_seconds_remaining']
    regulation = qtr is not None and 1 <= int(qtr) <= 4 and clock is not None
    seconds_in_quarter = int(clock) - 900 * (4 - int(qtr)) if regulation else None
    intent, decision = classify(row)
    yardline = row['yardline_100']
    return {
        'game_id': row['game_id'], 'play_id': row['play_id'], 'season': row['season'], 'week': row['week'],
        'qtr': qtr, 'overtime': qtr is not None and int(qtr) >= 5,
        'down': row['down'], 'ydstogo': row['ydstogo'], 'yardline_100': yardline,
        'game_seconds_remaining': clock, 'seconds_in_quarter': seconds_in_quarter,
        'two_minute_window': bool(regulation and int(qtr) in (2, 4) and seconds_in_quarter <= 120),
        'goal_to_go_derived': None if yardline is None else yardline <= 10,
        'posteam': row['posteam'], 'defteam': row['defteam'], 'home_team': row['home_team'], 'away_team': row['away_team'],
        'shotgun': row['shotgun'], 'no_huddle': row['no_huddle'],
        'intent': intent, 'fourth_down_decision': decision,
        'sack': row['sack'], 'scramble': row['qb_scramble'], 'touchdown': row['touchdown'],
        'interception': row['interception'], 'fumble_lost': row['fumble_lost'], 'yards_gained': row['yards_gained'],
        'score_differential': None, 'score_status': 'unavailable_in_pbp',
        'provenance': {'source': SOURCE, 'season': row['season'], 'model_layer': MODEL_LAYER},
    }


def observations(db, first_season=FIRST_SEASON, last_season=LAST_SEASON, cutoff=None):
    """Yield play-call observations for regular-season plays in [first_season, last_season].

    `cutoff` is (season, week). When given, only games in weeks strictly before it are yielded, so a later game cannot
    reach an earlier prediction. The holdout season is refused before any query, and the range is capped at LAST_SEASON.
    """
    holdout.refuse_if_holdout(last_season, 'play-call observations')
    if first_season < FIRST_SEASON or last_season > LAST_SEASON or first_season > last_season:
        raise ValueError(f'play-call window must sit inside {FIRST_SEASON}-{LAST_SEASON}')
    clauses = ['season BETWEEN ? AND ?', 'week <= 18']
    params = [first_season, last_season]
    if cutoff is not None:
        cutoff_season, cutoff_week = int(cutoff[0]), int(cutoff[1])
        if cutoff_season > LAST_SEASON + 1:
            raise ValueError('cutoff is outside the allowed history')
        clauses.append('(season < ? OR (season = ? AND week < ?))')
        params += [cutoff_season, cutoff_season, cutoff_week]
    sql = (f"SELECT {', '.join(COLUMNS)} FROM nfl_pbp WHERE {' AND '.join(clauses)} "
           "ORDER BY season, game_id, play_id")
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        for row in con.execute(sql, params):
            yield observation(dict(row))
    finally:
        con.close()
