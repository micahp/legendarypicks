"""Team win-loss streak splits for play calling: how each team's dropback rate changes with its current streak (SLC v1, research).

A team's streak state before a game is the run of wins or losses it carries into that game, counted within the season from its
prior results (a new season starts at NONE). The buckets are W3+, W1-2, NONE, L1-2 and L3+. For each team, the prior seasons give a
dropback rate in each bucket, shrunk toward the league's rate in the same bucket with the point splits' strength. The shift is the
log-odds of that bucket rate minus the log-odds of the team's own overall rate, so the team's general pass tendency (the fitted
team-by-down term) is not counted again. The shift is applied after the artifact's probability, the same way as the point splits.

Only games before the cutoff season enter the table, so a 2026 forecast uses 2016 to 2025 streak histories.
"""
import math
from collections import defaultdict

import playcall_model as pm

PRIOR_STRENGTH = 25.0
BUCKETS = ('W3+', 'W1-2', 'NONE', 'L1-2', 'L3+')


def bucket_of(state):
    """state: a signed streak, positive for wins and negative for losses; 0 is no streak."""
    if state >= 3:
        return 'W3+'
    if state > 0:
        return 'W1-2'
    if state == 0:
        return 'NONE'
    if state >= -2:
        return 'L1-2'
    return 'L3+'


def streak_states(results):
    """results: iterable of (season, week, game_id, team, won) with won in (True, False, None for a tie).

    Returns {game_id: {team: bucket}} with the state each team carried into that game."""
    by_team_season = defaultdict(list)
    for season, week, game_id, team, won in results:
        by_team_season[(team, season)].append((week, game_id, won))
    out = defaultdict(dict)
    for (team, _season), games in by_team_season.items():
        state = 0
        for week, game_id, won in sorted(games, key=lambda g: (g[0], g[1])):
            out[game_id][team] = bucket_of(state)
            if won is None:
                state = 0
            elif won:
                state = state + 1 if state > 0 else 1
            else:
                state = state - 1 if state < 0 else -1
    return out


def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def priors(frame, games, cutoff_season):
    """{'shift': {(team_index, bucket): log-odds shift}} from the frame's plays in seasons before the cutoff.

    games: {game_id: {team: bucket}} from streak_states (prior seasons are enough for the table)."""
    a = frame.a
    keep = a['season'] < int(cutoff_season)
    team_index = a['team'][keep]
    game_index = a['game'][keep]
    y = a['y'][keep].astype(float)
    game_ids = frame.games
    n_tb = defaultdict(float)
    y_tb = defaultdict(float)
    league_n = defaultdict(float)
    league_y = defaultdict(float)
    code_of = {index: code for code, index in frame.teams.items()}
    for t, g, yy in zip(team_index, game_index, y):
        code = code_of[int(t)]
        bucket = games.get(str(game_ids[int(g)]), {}).get(code)
        if bucket is None:
            continue
        n_tb[(int(t), bucket)] += 1
        y_tb[(int(t), bucket)] += yy
        league_n[bucket] += 1
        league_y[bucket] += yy
    league_all = sum(league_y.values()) / max(1.0, sum(league_n.values()))
    league_rate = {b: (league_y[b] + PRIOR_STRENGTH * league_all) / (league_n[b] + PRIOR_STRENGTH) for b in BUCKETS}
    teams = {t for t, _b in n_tb}
    shift = {}
    for t in teams:
        n_all = sum(n_tb[(t, b)] for b in BUCKETS)
        y_all = sum(y_tb[(t, b)] for b in BUCKETS)
        overall = (y_all + PRIOR_STRENGTH * league_all) / (n_all + PRIOR_STRENGTH)
        for b in BUCKETS:
            rate = (y_tb[(t, b)] + PRIOR_STRENGTH * league_rate[b]) / (n_tb[(t, b)] + PRIOR_STRENGTH)
            shift[(t, b)] = _logit(rate) - _logit(overall)
    return {'shift': shift, 'seasons': sorted({int(s) for s in a['season'][keep]})}


def shift_for(table, team_index, bucket):
    if team_index is None or bucket is None:
        return 0.0
    return table['shift'].get((int(team_index), bucket), 0.0)


def bucket_from_text(text):
    """A streak as written in the Week 8 records: 'W3', 'L1', or '' for none."""
    if not text:
        return 'NONE'
    count = int(text[1:])
    if text[0] == 'W':
        return bucket_of(count)
    return bucket_of(-count)


LEAGUE = -1  # the team index used for the league-wide table


def league_priors(frame, games, cutoff_season):
    """League-wide shifts of the dropback rate by streak bucket, from every play in the seasons before the cutoff.

    The shift in a bucket is its league dropback rate minus the league's overall rate, in log-odds, shrunk toward the overall rate.
    It carries no team information, so it is the league's own streak tendency."""
    a = frame.a
    keep = a['season'] < int(cutoff_season)
    team_index = a['team'][keep]
    game_index = a['game'][keep]
    y = a['y'][keep].astype(float)
    game_ids = frame.games
    code_of = {index: code for code, index in frame.teams.items()}
    n_b = defaultdict(float)
    y_b = defaultdict(float)
    for t, g, yy in zip(team_index, game_index, y):
        bucket = games.get(str(game_ids[int(g)]), {}).get(code_of[int(t)])
        if bucket is None:
            continue
        n_b[bucket] += 1
        y_b[bucket] += yy
    overall = sum(y_b.values()) / max(1.0, sum(n_b.values()))
    shift = {}
    for b in BUCKETS:
        rate = (y_b[b] + PRIOR_STRENGTH * overall) / (n_b[b] + PRIOR_STRENGTH)
        shift[(LEAGUE, b)] = _logit(rate) - _logit(overall)
    return {'shift': shift, 'seasons': sorted({int(s) for s in a['season'][keep]})}


def attach(rows, games):
    """Set row['streak'] to the offense's streak bucket going into the game (NONE when unknown) on each pool row."""
    for row in rows:
        row['streak'] = games.get(str(row['game_id']), {}).get(row.get('posteam'), 'NONE')
    return rows
